"""
Geohash-based spatial index for fast corridor lookups at request time.

- Builds a dict[geohash_prefix -> list[FuelStation]] once at startup from the DB.
- Precision-5 cells (~5×5 km) are coarse enough to be a broad corridor but tight
  enough to exclude irrelevant stations far from the route.
- 8-neighbor inclusion is mandatory: a station sitting at a cell boundary would be
  missed by an exact-cell lookup. _expand() returns the cell + all 8 neighbors.
- Request-time work is just dict lookups — no DB hit, no external API calls.
"""

import logging
from typing import NamedTuple

import pygeohash
from pygeohash import get_adjacent

from stations.models import FuelStation

logger = logging.getLogger(__name__)

# Stored geohash is precision-8; spatial filtering uses the first 5 chars (~5 km cells).
_INDEX_PRECISION = 5


def _expand(cell: str) -> list[str]:
    """
    - Returns the cell itself plus its 8 cardinal/diagonal neighbors (9 total).
    - pygeohash has no built-in expand(); we derive it from get_adjacent().
    - Diagonal neighbors are computed as the lateral neighbor of a vertical neighbor,
      which is the standard approach for geohash neighbor grids.
    """
    top = get_adjacent(cell, "top")
    bottom = get_adjacent(cell, "bottom")
    right = get_adjacent(cell, "right")
    left = get_adjacent(cell, "left")
    return [
        cell,
        top,
        bottom,
        right,
        left,
        get_adjacent(top, "right"),
        get_adjacent(top, "left"),
        get_adjacent(bottom, "right"),
        get_adjacent(bottom, "left"),
    ]


class StationPoint(NamedTuple):
    """Lightweight station representation stored in the index."""

    pk: int
    name: str
    address: str
    city: str
    state: str
    price: float
    latitude: float
    longitude: float
    geocode_source: str


def _to_point(station: FuelStation) -> StationPoint:
    return StationPoint(
        pk=station.pk,
        name=station.name,
        address=station.address,
        city=station.city,
        state=station.state,
        price=float(station.price),
        latitude=station.latitude,
        longitude=station.longitude,
        geocode_source=station.geocode_source,
    )


def build_index() -> dict[str, list[StationPoint]]:
    """
    - Queries all FuelStation rows once and bins them by their precision-5 geohash prefix.
    - Called once at app startup (from AppConfig.ready); subsequent lookups are O(1).
    - Precision-5 from the stored precision-8 string is a simple slice — no re-encode.
    """
    index: dict[str, list[StationPoint]] = {}
    count = 0
    for station in FuelStation.objects.all().iterator():
        cell = station.geohash[:_INDEX_PRECISION]
        index.setdefault(cell, []).append(_to_point(station))
        count += 1
    logger.info("Spatial index built: %d stations across %d cells", count, len(index))
    return index


def get_candidate_stations(
    route_geohashes: list[str],
    index: dict[str, list[StationPoint]],
) -> list[StationPoint]:
    """
    - Expands each route-point geohash (precision-5) to its 8 neighbors, then
      collects all stations from those cells.
    - Deduplication by station pk prevents the same station appearing twice when
      consecutive route points share neighboring cells.
    - Returns a flat list; the optimizer sorts by mile-marker, not by cell.

    Args:
        route_geohashes: precision-5 geohashes derived from route polyline points.
        index: the dict built by build_index().
    """
    seen_pks: set[int] = set()
    candidates: list[StationPoint] = []

    for cell in route_geohashes:
        for neighbor in _expand(cell):
            for station in index.get(neighbor, []):
                if station.pk not in seen_pks:
                    seen_pks.add(station.pk)
                    candidates.append(station)

    return candidates


def geohashes_for_route(route_points: list[tuple[float, float]]) -> list[str]:
    """
    - Encodes each (lat, lng) route point to a precision-5 geohash and deduplicates.
    - Deduplication keeps the cell set small: consecutive route points that fall in the
      same cell produce only one lookup, not N identical lookups.

    Args:
        route_points: list of (latitude, longitude) tuples from the route polyline.
    """
    seen: set[str] = set()
    cells: list[str] = []
    for lat, lng in route_points:
        cell = pygeohash.encode(lat, lng, precision=_INDEX_PRECISION)
        if cell not in seen:
            seen.add(cell)
            cells.append(cell)
    return cells
