"""
Unit tests for routing.services.route_geometry.

- All tests use hand-crafted coordinate data so results are deterministic.
- Haversine distances are verified against known values (San Francisco → Los Angeles
  is ~347 miles great-circle; SF → NYC is ~2,570 miles).
"""

import pytest

from routing.services.route_geometry import (
    cumulative_distances,
    haversine,
    station_mile_marker,
)

# Known coordinates
_SF = (37.7749, -122.4194)
_LA = (34.0522, -118.2437)
_NYC = (40.7128, -74.0060)
_CHICAGO = (41.8781, -87.6298)


class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine(*_SF, *_SF) == 0.0

    def test_sf_to_la_approx(self):
        """Great-circle SF→LA is ~347 miles; accept ±5 miles."""
        d = haversine(*_SF, *_LA)
        assert 342 < d < 352

    def test_sf_to_nyc_approx(self):
        """Great-circle SF→NYC is ~2,570 miles; accept ±20 miles."""
        d = haversine(*_SF, *_NYC)
        assert 2550 < d < 2590

    def test_symmetry(self):
        """Distance A→B must equal B→A."""
        assert haversine(*_SF, *_NYC) == pytest.approx(haversine(*_NYC, *_SF))

    def test_returns_miles_not_km(self):
        """Result must be in miles (SF→LA ~347), not km (~559)."""
        d = haversine(*_SF, *_LA)
        assert d < 500  # would be ~559 if returned in km


class TestCumulativeDistances:
    def test_empty_polyline_returns_empty(self):
        assert cumulative_distances([]) == []

    def test_single_point_returns_zero(self):
        assert cumulative_distances([_SF]) == [0.0]

    def test_two_points_first_is_zero(self):
        result = cumulative_distances([_SF, _LA])
        assert result[0] == 0.0

    def test_two_points_second_is_sf_la_distance(self):
        result = cumulative_distances([_SF, _LA])
        assert 342 < result[1] < 352

    def test_monotonically_increasing(self):
        polyline = [_SF, _LA, _NYC]
        result = cumulative_distances(polyline)
        for i in range(1, len(result)):
            assert result[i] > result[i - 1]

    def test_three_points_last_equals_sum_of_legs(self):
        polyline = [_SF, _LA, _NYC]
        result = cumulative_distances(polyline)
        leg1 = haversine(*_SF, *_LA)
        leg2 = haversine(*_LA, *_NYC)
        assert result[2] == pytest.approx(leg1 + leg2, rel=1e-6)

    def test_length_matches_polyline(self):
        polyline = [_SF, _LA, _CHICAGO, _NYC]
        result = cumulative_distances(polyline)
        assert len(result) == 4


class TestStationMileMarker:
    def test_station_at_start_returns_zero(self):
        polyline = [_SF, _LA, _NYC]
        cum = cumulative_distances(polyline)
        # Station exactly at start vertex
        marker = station_mile_marker(_SF[0], _SF[1], polyline, cum)
        assert marker == pytest.approx(0.0)

    def test_station_at_end_returns_total_distance(self):
        polyline = [_SF, _LA, _NYC]
        cum = cumulative_distances(polyline)
        marker = station_mile_marker(_NYC[0], _NYC[1], polyline, cum)
        assert marker == pytest.approx(cum[-1])

    def test_station_near_midpoint_returns_midpoint_marker(self):
        """A station very close to LA (the middle vertex) should snap to that marker."""
        polyline = [_SF, _LA, _NYC]
        cum = cumulative_distances(polyline)
        # Slightly offset from LA
        marker = station_mile_marker(34.06, -118.25, polyline, cum)
        assert marker == pytest.approx(cum[1], rel=0.01)

    def test_closer_vertex_wins(self):
        """Station closer to SF vertex must get SF marker (0.0), not LA or NYC."""
        polyline = [_SF, _LA, _NYC]
        cum = cumulative_distances(polyline)
        # Very close to SF
        marker = station_mile_marker(37.78, -122.42, polyline, cum)
        assert marker == pytest.approx(0.0)

    @pytest.mark.parametrize(
        "lat,lng,expected_idx",
        [
            (37.7749, -122.4194, 0),  # exactly SF
            (34.0522, -118.2437, 1),  # exactly LA
            (40.7128, -74.0060, 2),  # exactly NYC
        ],
    )
    def test_exact_vertex_returns_its_marker(self, lat, lng, expected_idx):
        polyline = [_SF, _LA, _NYC]
        cum = cumulative_distances(polyline)
        marker = station_mile_marker(lat, lng, polyline, cum)
        assert marker == pytest.approx(cum[expected_idx])
