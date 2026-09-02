"""
Greedy fuel-stop optimizer.

- Greedy "cheapest reachable within range" is the standard approach and produces cost-effective
results without DP complexity. Tradeoff documented in README.
- TANK_RANGE_MILES and MPG are read from django.conf.settings (500 mi, 10 mpg).
"""

import logging
from dataclasses import dataclass

from django.conf import settings

from stations.services.spatial_index import StationPoint

logger = logging.getLogger(__name__)


class UnreachableGapError(Exception):
    """
    Raised when no station exists within TANK_RANGE_MILES of the current position.
    This is rare in the contiguous US but can happen on very long stretches of
    desert or mountain highway with no truck stops.
    """


@dataclass(frozen=True)
class FuelStop:
    """Represents one chosen fuel stop and the cost of the leg ending there."""

    name: str
    address: str
    city: str
    state: str
    price_per_gallon: float
    latitude: float
    longitude: float
    distance_from_start_miles: float
    gallons_purchased: float
    leg_cost: float


@dataclass(frozen=True)
class OptimizationResult:
    """Full output of the optimizer: ordered stops and summed cost."""

    stops: list[FuelStop]
    total_fuel_cost: float
    total_gallons: float


def optimize(
    stations: list[StationPoint],
    total_distance_miles: float,
) -> OptimizationResult:
    """
    - Uses StationPoint list which has mile_markers attached to it via a parallel dict.
    - Returns OptimizationResult with ordered stops and totals.

    Args:
        stations: candidate stations already filtered to the route corridor,
            each carrying a 'mile_marker' attribute.
        total_distance_miles: full route length, used to determine when we've arrived.
    """
    tank_range = settings.TANK_RANGE_MILES
    mpg = settings.MPG

    # Build (mile_marker, station) pairs from the attribute set by the caller
    tagged: list[tuple[float, StationPoint]] = [
        (getattr(s, "mile_marker"), s) for s in stations
    ]
    tagged.sort(key=lambda x: x[0])

    position = 0.0
    stops: list[FuelStop] = []
    prev_position = 0.0

    while position + tank_range < total_distance_miles:
        window_end = position + tank_range
        reachable = [
            (marker, s) for marker, s in tagged if position < marker <= window_end
        ]
        if not reachable:
            raise UnreachableGapError(
                f"No fuel station reachable within {tank_range} miles "
                f"of mile {position:.1f}. Route may cross an area with no stations."
            )

        # Pick the cheapest station in the reachable window
        marker, chosen = min(reachable, key=lambda x: x[1].price)

        leg_miles = marker - prev_position
        gallons = leg_miles / mpg
        leg_cost = round(gallons * chosen.price, 2)

        stops.append(
            FuelStop(
                name=chosen.name,
                address=chosen.address,
                city=chosen.city,
                state=chosen.state,
                price_per_gallon=chosen.price,
                latitude=chosen.latitude,
                longitude=chosen.longitude,
                distance_from_start_miles=round(marker, 2),
                gallons_purchased=round(gallons, 2),
                leg_cost=leg_cost,
            )
        )
        logger.debug(
            "Stop: %s @ mile %.1f — $%.4f/gal, leg %.1f mi, cost $%.2f",
            chosen.name,
            marker,
            chosen.price,
            leg_miles,
            leg_cost,
        )

        prev_position = marker
        position = marker

    total_gallons = round(total_distance_miles / mpg, 2)
    total_cost = round(sum(s.leg_cost for s in stops), 2)
    return OptimizationResult(
        stops=stops,
        total_fuel_cost=total_cost,
        total_gallons=total_gallons,
    )
