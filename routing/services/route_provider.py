"""
ORS route provider: geocoding and driving-route retrieval.

- ORSRouteProvider makes exactly ONE HTTP call per request: the /directions endpoint
  returns the polyline and total distance together.
- _geocode() short-circuits for "lat,lng" inputs, skipping the geocode API call.
- Raises LocationNotFoundError / RouteNotFoundError for the view layer to convert
  into 4xx responses.
"""

import logging
import os
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class RouteNotFoundError(Exception):
    """Raised when the routing API cannot find a route between the two locations."""


class LocationNotFoundError(Exception):
    """Raised when a start or finish location cannot be geocoded."""


@dataclass(frozen=True)
class RouteResult:
    """
    - polyline_points: ordered list of (lat, lng) tuples covering the full route.
    - total_distance_miles: route length in miles, as reported by the routing API.
    """

    polyline_points: list[tuple[float, float]]
    total_distance_miles: float


class ORSRouteProvider:
    """
    - Uses the OpenRouteService Directions API (driving-car profile).
    - Geocodes start/finish via ORS /geocode/search before routing so we can
      validate that both points exist and surface a clear error if not.
    - The directions call returns a GeoJSON LineString; we extract the coordinate
      list and convert distance from metres to miles.
    - Raises LocationNotFoundError if ORS cannot resolve either endpoint.
    - Raises RouteNotFoundError if ORS returns no routes.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ORS_API_KEY", "")

    def _geocode(self, location: str) -> tuple[float, float]:
        """
        - Resolves a place-name or "lat,lng" string to (longitude, latitude).
        - ORS geocode returns coordinates as [lng, lat]; we return them in that order
          for direct use in the ORS directions payload which also expects [lng, lat].
        - "lat,lng" shorthand bypasses the geocode call entirely.
        """
        parts = location.split(",")
        if len(parts) == 2:
            try:
                lat, lng = float(parts[0].strip()), float(parts[1].strip())
                return lng, lat
            except ValueError:
                pass

        resp = requests.get(
            settings.ORS_GEOCODE_URL,
            params={"api_key": self._api_key, "text": location, "size": 1},
            timeout=settings.ORS_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if not features:
            raise LocationNotFoundError(f"Location not found: {location!r}")
        coords = features[0]["geometry"]["coordinates"]
        return coords[0], coords[1]  # (lng, lat)

    def get_route(self, start: str, finish: str) -> RouteResult:
        """
        - Geocodes both endpoints, then calls ORS /directions.
        - Converts GeoJSON [lng, lat] coordinates to (lat, lng) tuples.
        - Converts distance from metres to miles.
        """
        start_lng, start_lat = self._geocode(start)
        finish_lng, finish_lat = self._geocode(finish)

        payload = {
            "coordinates": [[start_lng, start_lat], [finish_lng, finish_lat]],
        }
        headers = {
            "Authorization": self._api_key,
            "Content-Type": "application/json",
        }
        resp = requests.post(
            settings.ORS_DIRECTIONS_URL,
            json=payload,
            headers=headers,
            timeout=settings.ORS_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            raise RouteNotFoundError(f"No route found between {start!r} and {finish!r}")
        resp.raise_for_status()

        data = resp.json()
        features = data.get("features", [])
        if not features:
            raise RouteNotFoundError(f"No route found between {start!r} and {finish!r}")

        feature = features[0]
        distance_metres = feature["properties"]["summary"]["distance"]
        total_distance_miles = distance_metres / 1609.344

        # GeoJSON coordinates are [lng, lat]; convert to (lat, lng) tuples
        geometry_coords = feature["geometry"]["coordinates"]
        polyline_points = [(lat, lng) for lng, lat in geometry_coords]

        logger.debug(
            "ORS route: %.1f miles, %d polyline points",
            total_distance_miles,
            len(polyline_points),
        )
        return RouteResult(
            polyline_points=polyline_points,
            total_distance_miles=total_distance_miles,
        )
