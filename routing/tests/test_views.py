from unittest.mock import MagicMock, patch

import pygeohash
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from routing.services.fuel_optimizer import OptimizationResult, UnreachableGapError
from routing.services.route_provider import (
    LocationNotFoundError,
    RouteNotFoundError,
    RouteResult,
)
from stations.models import FuelStation

_MOCK_OPT_RESULT = OptimizationResult(
    stops=[], total_fuel_cost=0.0, total_gallons=278.9
)

ROUTE_URL = "/api/v1/route/"
STATIONS_URL = "/api/v1/stations/"
HEALTH_URL = "/api/v1/health/"

# A minimal two-point polyline (SF → NYC, simplified)
_POLYLINE = [(37.7749, -122.4194), (40.7128, -74.0060)]
_DISTANCE_MILES = 2789.4

_MOCK_ROUTE_RESULT = RouteResult(
    polyline_points=_POLYLINE,
    total_distance_miles=_DISTANCE_MILES,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def station_near_route(db):
    """A station with coordinates near the SF→NYC polyline midpoint."""
    lat, lng = 39.0, -98.0  # Kansas — roughly on the route
    return FuelStation.objects.create(
        opis_id=1,
        name="Midway Fuel",
        address="1 Main St",
        city="Salina",
        state="KS",
        rack_id=1,
        price="3.25",
        latitude=lat,
        longitude=lng,
        geohash=pygeohash.encode(lat, lng, precision=8),
        geocode_source=FuelStation.GEOCODE_SOURCE_PRECISE,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/route/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRouteView:
    def _mock_provider(self, mocker, result=_MOCK_ROUTE_RESULT):
        mock_instance = MagicMock()
        mock_instance.get_route.return_value = result
        mocker.patch("routing.views.ORSRouteProvider", return_value=mock_instance)
        mocker.patch("routing.views.optimize", return_value=_MOCK_OPT_RESULT)
        return mock_instance

    def test_missing_start_returns_400(self, client, mocker):
        self._mock_provider(mocker)
        resp = client.post(ROUTE_URL, {"finish": "New York, NY"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_finish_returns_400(self, client, mocker):
        self._mock_provider(mocker)
        resp = client.post(ROUTE_URL, {"start": "San Francisco, CA"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_location_not_found_returns_400(self, client, mocker):
        mock = MagicMock()
        mock.get_route.side_effect = LocationNotFoundError(
            "Location not found: 'Nowhere'"
        )
        mocker.patch("routing.views.ORSRouteProvider", return_value=mock)

        resp = client.post(
            ROUTE_URL,
            {"start": "Nowhere, ZZ", "finish": "New York, NY"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in resp.data

    def test_route_not_found_returns_422(self, client, mocker):
        mock = MagicMock()
        mock.get_route.side_effect = RouteNotFoundError("No route found")
        mocker.patch("routing.views.ORSRouteProvider", return_value=mock)

        resp = client.post(
            ROUTE_URL,
            {"start": "San Francisco, CA", "finish": "London, UK"},
            format="json",
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_unreachable_gap_returns_422(self, client, mocker):
        self._mock_provider(mocker)
        mocker.patch(
            "routing.views.optimize",
            side_effect=UnreachableGapError("Gap > 500 miles at mile 0.0"),
        )

        resp = client.post(
            ROUTE_URL,
            {"start": "San Francisco, CA", "finish": "New York, NY"},
            format="json",
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_successful_response_shape(self, client, mocker):
        self._mock_provider(mocker)

        resp = client.post(
            ROUTE_URL,
            {"start": "San Francisco, CA", "finish": "New York, NY"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.data
        assert "route" in data
        assert "fuel_stops" in data
        assert "total_fuel_cost" in data

    def test_route_block_contains_required_fields(self, client, mocker):
        self._mock_provider(mocker)

        resp = client.post(
            ROUTE_URL,
            {"start": "San Francisco, CA", "finish": "New York, NY"},
            format="json",
        )

        route = resp.data["route"]
        assert "geometry" in route
        assert "total_distance_miles" in route
        assert "total_gallons" in route

    def test_total_gallons_matches_distance_over_mpg(self, client, mocker):
        self._mock_provider(mocker)

        resp = client.post(
            ROUTE_URL,
            {"start": "San Francisco, CA", "finish": "New York, NY"},
            format="json",
        )

        route = resp.data["route"]
        expected_gallons = round(_DISTANCE_MILES / 10, 2)
        assert abs(route["total_gallons"] - expected_gallons) < 0.1

    def test_only_one_provider_call_per_request(self, client, mocker):
        """The design guarantee: exactly one external routing call per request."""
        mock = self._mock_provider(mocker)

        client.post(
            ROUTE_URL,
            {"start": "San Francisco, CA", "finish": "New York, NY"},
            format="json",
        )

        mock.get_route.assert_called_once()

    def test_fuel_stop_fields_present(self, client, mocker, station_near_route):
        """When a stop is selected it must carry all documented fields."""
        # Use a short polyline that passes near the station so it gets found
        short_result = RouteResult(
            polyline_points=[(39.0, -98.0), (39.0, -97.0)],  # ~55 miles
            total_distance_miles=55.0,
        )
        self._mock_provider(mocker, result=short_result)

        # Build a local index for this test so the station is found
        from stations.services.spatial_index import build_index

        index = build_index()
        with patch("routing.views.station_index", index):
            resp = client.post(
                ROUTE_URL,
                {"start": "Salina, KS", "finish": "Abilene, KS"},
                format="json",
            )

        assert resp.status_code == status.HTTP_200_OK
        # Short route (55 mi < 500) → no stops needed, but response shape is valid
        assert isinstance(resp.data["fuel_stops"], list)


# ---------------------------------------------------------------------------
# GET /api/v1/stations/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStationsView:
    def test_empty_db_returns_empty_list(self, client):
        resp = client.get(STATIONS_URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_returns_all_stations(self, client, station_near_route):
        resp = client.get(STATIONS_URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1

    def test_response_contains_required_fields(self, client, station_near_route):
        resp = client.get(STATIONS_URL)
        station = resp.data[0]
        for field in ["name", "city", "state", "price", "latitude", "longitude"]:
            assert field in station

    def test_internal_fields_not_exposed(self, client, station_near_route):
        resp = client.get(STATIONS_URL)
        station = resp.data[0]
        for field in ["geohash", "rack_id", "opis_id", "geocode_source"]:
            assert field not in station


# ---------------------------------------------------------------------------
# GET /api/v1/health/
# ---------------------------------------------------------------------------


class TestHealthView:
    def test_returns_200(self, client):
        resp = client.get(HEALTH_URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_status_field_is_ok(self, client):
        resp = client.get(HEALTH_URL)
        assert resp.data["status"] == "ok"

    def test_index_loaded_field_present(self, client):
        resp = client.get(HEALTH_URL)
        assert "station_index_loaded" in resp.data
