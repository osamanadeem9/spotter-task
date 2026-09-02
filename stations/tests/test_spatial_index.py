"""
Unit tests for stations.services.spatial_index.

- All tests use a small hand-crafted station set; no DB is needed except where
  explicitly testing build_index() (marked django_db).
- Coordinates chosen so their precision-5 geohashes are predictable and stable.
"""

import pygeohash
import pytest

from stations.services.spatial_index import (
    _INDEX_PRECISION,
    StationPoint,
    _expand,
    build_index,
    geohashes_for_route,
    get_candidate_stations,
)


def _make_station(pk: int, lat: float, lng: float, price: float = 3.0) -> StationPoint:
    """Build a StationPoint at the given coordinates for test use."""
    return StationPoint(
        pk=pk,
        name=f"Station {pk}",
        address="123 Test Rd",
        city="Testville",
        state="TX",
        price=price,
        latitude=lat,
        longitude=lng,
        geocode_source="precise",
    )


def _small_index(*stations: StationPoint) -> dict[str, list[StationPoint]]:
    """Build a minimal index dict from an explicit list of StationPoints."""
    index: dict[str, list[StationPoint]] = {}
    for s in stations:
        cell = pygeohash.encode(s.latitude, s.longitude, precision=_INDEX_PRECISION)
        index.setdefault(cell, []).append(s)
    return index


# ---------------------------------------------------------------------------
# geohashes_for_route
# ---------------------------------------------------------------------------


class TestGeohashesForRoute:
    def test_empty_route_returns_empty(self):
        assert geohashes_for_route([]) == []

    def test_single_point_returns_one_cell(self):
        cells = geohashes_for_route([(36.566, -95.221)])
        assert len(cells) == 1
        assert len(cells[0]) == _INDEX_PRECISION

    def test_duplicate_points_deduplicated(self):
        """Two points in the same precision-5 cell produce one cell entry."""
        # Points very close together — guaranteed same precision-5 cell.
        cells = geohashes_for_route([(36.566, -95.221), (36.567, -95.222)])
        assert len(cells) == 1

    def test_distant_points_produce_distinct_cells(self):
        """Points across the USA must produce distinct cells."""
        cells = geohashes_for_route([(37.7749, -122.4194), (40.7128, -74.0060)])
        assert len(cells) == 2
        assert cells[0] != cells[1]

    def test_output_length_matches_unique_cells(self):
        points = [
            (36.566, -95.221),
            (36.567, -95.222),  # same cell as above
            (40.712, -74.006),  # different cell
        ]
        cells = geohashes_for_route(points)
        assert len(cells) == 2


# ---------------------------------------------------------------------------
# get_candidate_stations
# ---------------------------------------------------------------------------


class TestGetCandidateStations:
    def test_no_route_points_returns_empty(self):
        index = _small_index(_make_station(1, 36.566, -95.221))
        assert get_candidate_stations([], index) == []

    def test_station_in_exact_cell_is_returned(self):
        station = _make_station(1, 36.566, -95.221)
        index = _small_index(station)
        cell = pygeohash.encode(36.566, -95.221, precision=_INDEX_PRECISION)
        candidates = get_candidate_stations([cell], index)
        assert station in candidates

    def test_station_in_neighbor_cell_is_returned(self):
        """
        A station just across a cell boundary must still be found via the 8-neighbor
        expansion — this is the core correctness guarantee of the design.
        """
        # Place the station in one cell and query from an adjacent cell.
        station = _make_station(1, 36.566, -95.221)
        station_cell = pygeohash.encode(36.566, -95.221, precision=_INDEX_PRECISION)
        index = _small_index(station)

        # Pick a neighbor of the station's cell to query from.
        neighbors = _expand(station_cell)
        query_cell = next(c for c in neighbors if c != station_cell)

        candidates = get_candidate_stations([query_cell], index)
        assert station in candidates

    def test_station_far_from_route_not_returned(self):
        """Station 1000+ km away from the queried cell must not appear."""
        station = _make_station(1, 36.566, -95.221)  # Oklahoma
        index = _small_index(station)
        # Query a cell in San Francisco — not a neighbor of the Oklahoma cell.
        sf_cell = pygeohash.encode(37.7749, -122.4194, precision=_INDEX_PRECISION)
        candidates = get_candidate_stations([sf_cell], index)
        assert station not in candidates

    def test_duplicate_stations_deduplicated(self):
        """
        When two consecutive route cells share a neighbor, the same station must
        appear only once in the candidate list.
        """
        station = _make_station(1, 36.566, -95.221)
        index = _small_index(station)
        cell = pygeohash.encode(36.566, -95.221, precision=_INDEX_PRECISION)
        # Pass the same cell twice — station should appear exactly once.
        candidates = get_candidate_stations([cell, cell], index)
        pks = [s.pk for s in candidates]
        assert pks.count(1) == 1

    def test_multiple_stations_all_returned(self):
        s1 = _make_station(1, 36.566, -95.221)
        s2 = _make_station(2, 36.570, -95.225)  # close, likely same cell
        index = _small_index(s1, s2)
        cell = pygeohash.encode(36.566, -95.221, precision=_INDEX_PRECISION)
        candidates = get_candidate_stations([cell], index)
        pks = {s.pk for s in candidates}
        assert {1, 2} <= pks

    def test_empty_index_returns_empty(self):
        cell = pygeohash.encode(36.566, -95.221, precision=_INDEX_PRECISION)
        assert get_candidate_stations([cell], {}) == []


# ---------------------------------------------------------------------------
# build_index (requires DB)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBuildIndex:
    def test_empty_db_returns_empty_index(self):
        index = build_index()
        assert index == {}

    def test_station_appears_in_its_cell(self, fuel_station_factory):
        """A loaded station must appear in the index under its precision-5 cell."""
        station = fuel_station_factory(latitude=36.566, longitude=-95.221)
        index = build_index()
        cell = pygeohash.encode(36.566, -95.221, precision=_INDEX_PRECISION)
        assert cell in index
        pks = [s.pk for s in index[cell]]
        assert station.pk in pks

    def test_two_stations_same_cell(self, fuel_station_factory):
        """Two stations at similar coordinates land in the same cell."""
        s1 = fuel_station_factory(
            latitude=36.566, longitude=-95.221, name="A", city="CityA"
        )
        s2 = fuel_station_factory(
            latitude=36.567, longitude=-95.222, name="B", city="CityB"
        )
        index = build_index()
        cell = pygeohash.encode(36.566, -95.221, precision=_INDEX_PRECISION)
        pks = {s.pk for s in index.get(cell, [])}
        assert {s1.pk, s2.pk} <= pks
