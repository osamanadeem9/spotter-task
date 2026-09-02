"""
Route geometry helpers: cumulative distance and station mile-marker projection.

- haversine() gives great-circle distance between two lat/lng points in miles.
- cumulative_distances() converts the ORS polyline into a running mile-marker array
  so each polyline vertex has an exact distance from the route start.
- station_mile_marker() projects a station onto the polyline by finding the nearest
  vertex. Nearest-vertex is sufficient: optimizer window is 500 miles and stations
  are within ~5 km of the road, so error is negligible.
"""

import math
from typing import Sequence

_EARTH_RADIUS_MILES = 3958.8


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    - Great-circle distance in miles between two (lat, lng) points.
    - Uses the haversine formula; accurate to <0.5% for distances under 5,000 miles.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def cumulative_distances(
    polyline: Sequence[tuple[float, float]],
) -> list[float]:
    """
    - Returns a list of the same length as polyline where element i is the total
      miles from polyline[0] to polyline[i].
    - Element 0 is always 0.0.
    - Used to convert a vertex index into a route mile-marker.
    """
    if not polyline:
        return []
    distances = [0.0]
    for i in range(1, len(polyline)):
        prev_lat, prev_lng = polyline[i - 1]
        curr_lat, curr_lng = polyline[i]
        distances.append(
            distances[-1] + haversine(prev_lat, prev_lng, curr_lat, curr_lng)
        )
    return distances


def station_mile_marker(
    station_lat: float,
    station_lng: float,
    polyline: Sequence[tuple[float, float]],
    cum_distances: Sequence[float],
) -> float:
    """
    - Projects a station onto the polyline by finding the nearest polyline vertex.
    - Returns the cumulative mile-marker of that vertex as the station's position.
    - Nearest-vertex (rather than nearest-point-on-segment) is sufficient: the
      optimizer window is 500 miles and stations within a ~5 km geohash cell
      introduce at most ~3 miles of error — negligible cost impact.
    - Requires cum_distances pre-computed by cumulative_distances() so this
      function is pure arithmetic with no repeated distance calculations.
    """
    min_dist = math.inf
    best_idx = 0
    for i, (lat, lng) in enumerate(polyline):
        d = haversine(station_lat, station_lng, lat, lng)
        if d < min_dist:
            min_dist = d
            best_idx = i
    return cum_distances[best_idx]
