"""
Unit tests for routing.services.fuel_optimizer.

- Tests use small hand-crafted station sets with pre-set mile_marker attributes.
- Covers: single stop (short route), multi-stop, cheapest-in-window selection,
  and the unreachable-gap failure mode.
"""

import pytest
from django.conf import settings

from routing.services.fuel_optimizer import (
    OptimizationResult,
    UnreachableGapError,
    optimize,
)
from stations.services.spatial_index import StationPoint


def _station(
    pk: int,
    mile_marker: float,
    price: float,
    name: str = "",
) -> StationPoint:
    """Create a StationPoint with a .mile_marker attribute attached."""
    s = StationPoint(
        pk=pk,
        name=name or f"Station {pk}",
        address="123 Rd",
        city="City",
        state="TX",
        price=price,
        latitude=30.0 + pk * 0.1,
        longitude=-90.0,
        geocode_source="precise",
    )
    # Attach mile_marker dynamically (optimizer reads it via getattr)
    object.__setattr__(
        s, "mile_marker", mile_marker
    )  # NamedTuple is immutable; use a wrapper
    return s


class _Tagged:
    """Thin wrapper so we can attach mile_marker to a StationPoint for tests."""

    def __init__(self, sp: StationPoint, mile_marker: float) -> None:
        self._sp = sp
        self.mile_marker = mile_marker
        # Expose all StationPoint fields transparently
        for field in sp._fields:
            setattr(self, field, getattr(sp, field))


def _tag(pk: int, mile_marker: float, price: float, name: str = "") -> _Tagged:
    sp = StationPoint(
        pk=pk,
        name=name or f"Station {pk}",
        address="123 Rd",
        city="City",
        state="TX",
        price=price,
        latitude=30.0 + pk * 0.1,
        longitude=-90.0,
        geocode_source="precise",
    )
    return _Tagged(sp, mile_marker)


class TestOptimizeNoStop:
    def test_short_route_under_tank_range_needs_no_stop(self):
        """Route of 300 miles fits in a single tank (≤500) → zero stops needed."""
        stations = [_tag(1, 200.0, 3.50)]
        result = optimize(stations, total_distance_miles=300.0)
        assert len(result.stops) == 0

    def test_total_gallons_is_distance_over_mpg_even_with_no_stops(self):
        """300 miles / 10 mpg = 30 gallons regardless of stop count."""
        result = optimize([], total_distance_miles=300.0)
        assert result.total_gallons == pytest.approx(30.0)

    def test_total_cost_is_zero_when_no_stops(self):
        result = optimize([], total_distance_miles=300.0)
        assert result.total_fuel_cost == 0


class TestOptimizeSingleStop:
    def test_route_just_over_tank_range_needs_one_stop(self):
        """Route of 600 miles (> 500) with station at 400 → exactly one stop."""
        stations = [_tag(1, 400.0, 3.50)]
        result = optimize(stations, total_distance_miles=600.0)
        assert len(result.stops) == 1

    def test_stop_fields_correct(self):
        stations = [_tag(1, 400.0, 3.50, name="Quick Stop")]
        result = optimize(stations, total_distance_miles=600.0)
        stop = result.stops[0]
        assert stop.name == "Quick Stop"
        assert stop.price_per_gallon == 3.50
        assert stop.distance_from_start_miles == 400.0

    def test_gallons_is_leg_miles_over_mpg(self):
        """Leg is 400 miles from start; 400/10 = 40 gallons."""
        stations = [_tag(1, 400.0, 3.50)]
        result = optimize(stations, total_distance_miles=600.0)
        assert result.stops[0].gallons_purchased == pytest.approx(40.0)

    def test_leg_cost_is_gallons_times_price(self):
        """40 gallons × $3.50 = $140.00."""
        stations = [_tag(1, 400.0, 3.50)]
        result = optimize(stations, total_distance_miles=600.0)
        assert result.stops[0].leg_cost == pytest.approx(140.0)

    def test_total_gallons_is_distance_over_mpg(self):
        """600 miles / 10 mpg = 60 gallons."""
        stations = [_tag(1, 400.0, 3.50)]
        result = optimize(stations, total_distance_miles=600.0)
        assert result.total_gallons == pytest.approx(60.0)


class TestOptimizeMultiStop:
    def test_long_route_produces_multiple_stops(self):
        """2,800-mile route needs at least 5 stops at 500-mile range."""
        stations = [
            _tag(1, 450.0, 3.20),
            _tag(2, 900.0, 3.10),
            _tag(3, 1350.0, 3.30),
            _tag(4, 1800.0, 3.00),
            _tag(5, 2250.0, 3.15),
            _tag(6, 2700.0, 3.25),
        ]
        result = optimize(stations, total_distance_miles=2800.0)
        assert len(result.stops) >= 5

    def test_stops_are_ordered_by_mile_marker(self):
        stations = [
            _tag(1, 450.0, 3.20),
            _tag(2, 900.0, 3.10),
            _tag(3, 1350.0, 3.30),
        ]
        result = optimize(stations, total_distance_miles=1500.0)
        markers = [s.distance_from_start_miles for s in result.stops]
        assert markers == sorted(markers)

    def test_total_cost_equals_sum_of_leg_costs(self):
        stations = [
            _tag(1, 450.0, 3.20),
            _tag(2, 900.0, 3.10),
        ]
        result = optimize(stations, total_distance_miles=1000.0)
        assert result.total_fuel_cost == pytest.approx(
            sum(s.leg_cost for s in result.stops), rel=1e-4
        )

    def test_returns_optimization_result_type(self):
        stations = [_tag(1, 300.0, 3.0)]
        result = optimize(stations, total_distance_miles=400.0)
        assert isinstance(result, OptimizationResult)


class TestCheapestInWindow:
    def test_cheapest_station_in_window_chosen(self):
        """Two stations in range — the cheaper one must be selected."""
        stations = [
            _tag(1, 200.0, 3.80, name="Expensive"),
            _tag(2, 300.0, 2.90, name="Cheap"),
        ]
        # Route is 700 miles (> 500) so at least one stop is required
        result = optimize(stations, total_distance_miles=700.0)
        assert result.stops[0].name == "Cheap"

    def test_station_beyond_range_not_chosen(self):
        """A station at mile 600 is out of range from position 0; only in-range selected."""
        stations = [
            _tag(1, 400.0, 3.00, name="In range"),
            _tag(2, 600.0, 1.00, name="Too far"),  # beyond 500 miles
        ]
        result = optimize(stations, total_distance_miles=650.0)
        # First stop must be "In range", not "Too far"
        assert result.stops[0].name == "In range"

    def test_station_at_exact_range_boundary_is_reachable(self):
        """A station at exactly settings.TANK_RANGE_MILES from position is reachable (≤, not <)."""
        stations = [_tag(1, settings.TANK_RANGE_MILES, 3.00)]
        result = optimize(stations, total_distance_miles=settings.TANK_RANGE_MILES + 1)
        assert len(result.stops) >= 1
        assert result.stops[0].distance_from_start_miles == settings.TANK_RANGE_MILES

    def test_station_at_zero_not_chosen(self):
        """Station at mile_marker 0 is at or before current position — must be skipped."""
        stations = [
            _tag(1, 0.0, 1.00, name="At start"),
            _tag(2, 300.0, 3.50, name="Valid"),
        ]
        result = optimize(stations, total_distance_miles=400.0)
        assert all(s.name != "At start" for s in result.stops)


class TestUnreachableGap:
    def test_no_stations_raises(self):
        with pytest.raises(UnreachableGapError):
            optimize([], total_distance_miles=600.0)

    def test_gap_beyond_range_raises(self):
        """Station at mile 600 is out of first-tank range — gap error."""
        stations = [_tag(1, 600.0, 3.00)]
        with pytest.raises(UnreachableGapError):
            optimize(stations, total_distance_miles=700.0)

    def test_error_message_contains_position(self):
        with pytest.raises(UnreachableGapError, match=r"mile 0\.0"):
            optimize([], total_distance_miles=600.0)
