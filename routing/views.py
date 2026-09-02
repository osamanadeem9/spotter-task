"""
API views for the routing app.

- RouteView orchestrates the full pipeline: validate → route → spatial filter
  → tag mile-markers → optimize → serialize response. One ORS call per request.
- StationsView is just a read-only list of all geocoded stations
- HealthView is a health check probe.
"""

import logging

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.serializers import RouteRequestSerializer, StationListSerializer
from routing.services.fuel_optimizer import UnreachableGapError, optimize
from routing.services.route_geometry import (
    cumulative_distances,
    station_mile_marker,
)
from routing.services.route_provider import (
    LocationNotFoundError,
    ORSRouteProvider,
    RouteNotFoundError,
)
from stations.apps import station_index
from stations.models import FuelStation
from stations.services.spatial_index import (
    StationPoint,
    geohashes_for_route,
    get_candidate_stations,
)

logger = logging.getLogger(__name__)


class RouteView(APIView):
    """
    POST /api/v1/route/

    - Makes exactly one external routing call (ORS).
    - Spatial filtering and optimization are in-memory. No DB hit after startup.
    - Explicit error cases return 4xx with a clear message. Unexpected errors -> 500.
    """

    def post(self, request: Request) -> Response:
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        start = serializer.validated_data["start"]
        finish = serializer.validated_data["finish"]

        provider = ORSRouteProvider()
        try:
            route_result = provider.get_route(start, finish)
        except LocationNotFoundError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RouteNotFoundError as exc:
            return Response(
                {"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        polyline = route_result.polyline_points
        total_miles = route_result.total_distance_miles

        # Spatial filter: geohash route -> look up nearby stations in the index
        route_cells = geohashes_for_route(polyline)
        candidates = get_candidate_stations(route_cells, station_index)

        # Tag each candidate with its mile-marker along the route
        cum_dist = cumulative_distances(polyline)
        tagged: list[StationPoint] = []
        for station in candidates:
            marker = station_mile_marker(
                station.latitude, station.longitude, polyline, cum_dist
            )
            # Attach mile_marker as a dynamic attribute (optimizer reads via getattr)
            tagged_station = _TaggedStation(station, marker)
            tagged.append(tagged_station)

        # logger.debug(
        #     "Tagged %d candidate stations: %s",
        #     len(tagged),
        #     [(s.name, s.city, round(s.mile_marker, 1)) for s in tagged],
        # )
        try:
            opt_result = optimize(tagged, total_miles)
        except UnreachableGapError as exc:
            return Response(
                {"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        # Shape the response
        geometry_coords = [[lat, lng] for lat, lng in polyline]
        response_data = {
            "route": {
                "geometry": geometry_coords,
                "total_distance_miles": round(total_miles, 2),
                "total_gallons": opt_result.total_gallons,
            },
            "fuel_stops": [
                {
                    "name": s.name,
                    "city": s.city,
                    "state": s.state,
                    "price_per_gallon": s.price_per_gallon,
                    "distance_from_start_miles": s.distance_from_start_miles,
                    "gallons_purchased": s.gallons_purchased,
                    "leg_cost": s.leg_cost,
                    "latitude": s.latitude,
                    "longitude": s.longitude,
                }
                for s in opt_result.stops
            ],
            "total_fuel_cost": opt_result.total_fuel_cost,
        }
        return Response(response_data, status=status.HTTP_200_OK)


class _TaggedStation:
    """
    Thin wrapper that attaches a mile_marker to a StationPoint without mutating it.
    The optimizer reads all fields via attribute access, so we proxy them here.
    """

    def __init__(self, station: StationPoint, mile_marker: float) -> None:
        self._station = station
        self.mile_marker = mile_marker
        for field in station._fields:
            setattr(self, field, getattr(station, field))


class StationsView(APIView):
    """
    GET /api/v1/stations/

    - Returns all geocoded stations as a lean JSON list for the map layer.
    - Will cache later. Data changes only when the fixture is reloaded.
    """

    def get(self, request: Request) -> Response:
        stations = FuelStation.objects.all()
        serializer = StationListSerializer(stations, many=True)
        return Response(serializer.data)


class HealthView(APIView):
    """
    GET /api/v1/health/

    - Health check probe.
    """

    def get(self, request: Request) -> Response:
        return Response(
            {
                "status": "ok",
                "station_index_loaded": bool(station_index),
            }
        )
