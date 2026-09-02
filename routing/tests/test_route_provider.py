"""
Unit tests for routing.services.route_provider.

- All HTTP calls are intercepted by the `responses` library — no real network.
- Tests cover: happy path, location-not-found, route-not-found.
"""

import pytest
import responses as resp_mock
from django.conf import settings

from routing.services.route_provider import (
    LocationNotFoundError,
    ORSRouteProvider,
    RouteNotFoundError,
    RouteResult,
)

_GEOCODE_URL = settings.ORS_GEOCODE_URL
_DIRECTIONS_URL = settings.ORS_DIRECTIONS_URL

_GEOCODE_SF = {"features": [{"geometry": {"coordinates": [-122.4194, 37.7749]}}]}
_GEOCODE_NY = {"features": [{"geometry": {"coordinates": [-74.0060, 40.7128]}}]}

_DIRECTIONS_OK = {
    "features": [
        {
            "properties": {"summary": {"distance": 4489408}},  # ~2790 miles in metres
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [-122.4194, 37.7749],
                    [-74.0060, 40.7128],
                ],
            },
        }
    ]
}


@pytest.fixture
def provider():
    return ORSRouteProvider(api_key="test-key")


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------


class TestGeocoding:
    @resp_mock.activate
    def test_latlong_string_bypasses_geocode_call(self, provider):
        """'lat,lng' input must not trigger a geocode HTTP call."""
        resp_mock.add(resp_mock.POST, _DIRECTIONS_URL, json=_DIRECTIONS_OK)

        provider.get_route("37.7749,-122.4194", "40.7128,-74.0060")

        assert len(resp_mock.calls) == 1
        assert _DIRECTIONS_URL in resp_mock.calls[0].request.url

    @resp_mock.activate
    def test_place_name_triggers_geocode_call(self, provider):
        resp_mock.add(resp_mock.GET, _GEOCODE_URL, json=_GEOCODE_SF)
        resp_mock.add(resp_mock.GET, _GEOCODE_URL, json=_GEOCODE_NY)
        resp_mock.add(resp_mock.POST, _DIRECTIONS_URL, json=_DIRECTIONS_OK)

        provider.get_route("San Francisco, CA", "New York, NY")

        assert len(resp_mock.calls) == 3

    @resp_mock.activate
    def test_location_not_found_raises(self, provider):
        resp_mock.add(resp_mock.GET, _GEOCODE_URL, json={"features": []})

        with pytest.raises(LocationNotFoundError, match="Location not found"):
            provider.get_route("Nowhere, ZZ", "New York, NY")


# ---------------------------------------------------------------------------
# Route result
# ---------------------------------------------------------------------------


class TestGetRoute:
    @resp_mock.activate
    def test_returns_route_result(self, provider):
        resp_mock.add(resp_mock.POST, _DIRECTIONS_URL, json=_DIRECTIONS_OK)

        result = provider.get_route("37.7749,-122.4194", "40.7128,-74.0060")

        assert isinstance(result, RouteResult)

    @resp_mock.activate
    def test_distance_converted_to_miles(self, provider):
        """4,489,408 metres ≈ 2789.4 miles (within 1 mile tolerance)."""
        resp_mock.add(resp_mock.POST, _DIRECTIONS_URL, json=_DIRECTIONS_OK)

        result = provider.get_route("37.7749,-122.4194", "40.7128,-74.0060")

        assert abs(result.total_distance_miles - 2789.4) < 1.0

    @resp_mock.activate
    def test_coordinates_swapped_to_lat_lng(self, provider):
        """ORS returns [lng, lat]; result must be (lat, lng) tuples."""
        resp_mock.add(resp_mock.POST, _DIRECTIONS_URL, json=_DIRECTIONS_OK)

        result = provider.get_route("37.7749,-122.4194", "40.7128,-74.0060")

        first = result.polyline_points[0]
        assert first == (37.7749, -122.4194)

    @resp_mock.activate
    def test_route_not_found_404_raises(self, provider):
        resp_mock.add(resp_mock.POST, _DIRECTIONS_URL, status=404, json={})

        with pytest.raises(RouteNotFoundError):
            provider.get_route("37.7749,-122.4194", "40.7128,-74.0060")

    @resp_mock.activate
    def test_route_not_found_empty_routes_raises(self, provider):
        resp_mock.add(resp_mock.POST, _DIRECTIONS_URL, json={"features": []})

        with pytest.raises(RouteNotFoundError):
            provider.get_route("37.7749,-122.4194", "40.7128,-74.0060")

    @resp_mock.activate
    def test_polyline_preserves_all_points(self, provider):
        directions = {
            "features": [
                {
                    "properties": {"summary": {"distance": 1000}},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [-122.4194, 37.7749],
                            [-100.0, 39.0],
                            [-74.0060, 40.7128],
                        ],
                    },
                }
            ]
        }
        resp_mock.add(resp_mock.POST, _DIRECTIONS_URL, json=directions)

        result = provider.get_route("37.7749,-122.4194", "40.7128,-74.0060")

        assert len(result.polyline_points) == 3
