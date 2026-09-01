"""
Tests for the geocode_stations_mapquest management command helpers.

All MapQuest HTTP calls are mocked via the `responses` library.
"""

import json
from unittest.mock import patch

import pytest
import responses as rsps_lib
from django.core.management import call_command
from django.core.management.base import CommandError

from stations.management.commands.geocode_stations_mapquest import (
    MAPQUEST_BATCH_URL,
    _batch_geocode,
    _build_location_string,
    _geocode_batch_with_fallback,
    _location_matches,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mapquest_response(
    lat: float,
    lng: float,
    quality: str = "A1AAAa",
    city: str = "Gila Bend",
    state: str = "Arizona",
) -> dict:
    """Minimal MapQuest batch response shape for a single successful location."""
    return {
        "results": [
            {
                "locations": [
                    {
                        "latLng": {"lat": lat, "lng": lng},
                        "geocodeQualityCode": quality,
                        "adminArea5": city,
                        "adminArea3": state,
                    }
                ]
            }
        ]
    }


def _mapquest_empty_response() -> dict:
    return {"results": [{"locations": []}]}


# ---------------------------------------------------------------------------
# _location_matches
# ---------------------------------------------------------------------------


class TestLocationMatches:
    """Covers exact city+state matching, case-insensitivity, and empty-value edge cases."""

    @pytest.mark.parametrize(
        "r_city, r_state, e_city, e_state, expected",
        [
            ("Big Cabin", "OK", "Big Cabin", "OK", True),
            ("BIG CABIN", "ok", "Big Cabin", "OK", True),  # case-insensitive
            ("Big Cabin", "OK", "big cabin", "ok", True),
            ("Gila Bend", "AZ", "Big Cabin", "OK", False),  # wrong city and state
            ("Big Cabin", "TX", "Big Cabin", "OK", False),  # right city, wrong state
            ("Tomah", "OK", "Big Cabin", "OK", False),  # wrong city, right state
            ("", "OK", "Big Cabin", "OK", False),  # empty returned city
            ("Big Cabin", "", "Big Cabin", "OK", False),  # empty returned state
            (
                "Big Cabin Township",
                "OK",
                "Big Cabin",
                "OK",
                False,
            ),  # substring not accepted
        ],
    )
    def test_location_matching(self, r_city, r_state, e_city, e_state, expected):
        assert _location_matches(r_city, r_state, e_city, e_state) == expected


# ---------------------------------------------------------------------------
# _build_location_string
# ---------------------------------------------------------------------------


class TestBuildLocationString:
    """Verifies the address string includes name, strips junction noise before the first comma."""

    @pytest.mark.parametrize(
        "name, address, city, state, expected",
        [
            (
                "WOODSHED OF BIG CABIN",
                "I-44, EXIT 283 & US-69",
                "Big Cabin",
                "OK",
                "WOODSHED OF BIG CABIN, I-44, Big Cabin, OK, USA",
            ),
            (
                "KWIK TRIP #796",
                "123 Main St, Suite 5",
                "Tomah",
                "WI",
                "KWIK TRIP #796, 123 Main St, Tomah, WI, USA",
            ),
            (
                "PILOT #1243",
                "Simple Road",
                "Gila Bend",
                "AZ",
                "PILOT #1243, Simple Road, Gila Bend, AZ, USA",
            ),
        ],
    )
    def test_formats_correctly(self, name, address, city, state, expected):
        assert _build_location_string(name, address, city, state) == expected


# ---------------------------------------------------------------------------
# _batch_geocode
# ---------------------------------------------------------------------------


class TestBatchGeocode:
    """Verifies the MapQuest batch POST parsing and error handling."""

    @rsps_lib.activate
    def test_returns_coordinates_on_success(self):
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json=_mapquest_response(36.538, -95.220),
            status=200,
        )
        results = _batch_geocode(["I-44, Big Cabin, OK, USA"], api_key="test-key")
        assert len(results) == 1
        assert results[0]["lat"] == 36.538
        assert results[0]["lng"] == -95.220

    @rsps_lib.activate
    def test_returns_none_for_empty_location(self):
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json=_mapquest_empty_response(),
            status=200,
        )
        results = _batch_geocode(["Unknown Road, Nowhere, XX, USA"], api_key="test-key")
        assert results == [None]

    @rsps_lib.activate
    def test_returns_all_none_on_network_error(self):
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            body=requests_connection_error(),
        )
        results = _batch_geocode(["Loc A", "Loc B"], api_key="test-key")
        assert results == [None, None]

    @rsps_lib.activate
    def test_preserves_order_for_multiple_locations(self):
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json={
                "results": [
                    {
                        "locations": [
                            {
                                "latLng": {"lat": 36.5, "lng": -95.2},
                                "geocodeQualityCode": "A1AAAa",
                            }
                        ]
                    },
                    {
                        "locations": [
                            {
                                "latLng": {"lat": 32.9, "lng": -112.7},
                                "geocodeQualityCode": "A1AAAa",
                            }
                        ]
                    },
                ]
            },
            status=200,
        )
        results = _batch_geocode(["Loc A", "Loc B"], api_key="test-key")
        assert results[0]["lat"] == 36.5
        assert results[1]["lat"] == 32.9


def requests_connection_error():
    import requests as req_lib

    return req_lib.exceptions.ConnectionError("timeout")


# ---------------------------------------------------------------------------
# _geocode_batch_with_fallback
# ---------------------------------------------------------------------------


class TestGeocodeWithFallback:
    """Verifies the two-pass precise → city_centroid fallback logic."""

    def _station(
        self, name="PILOT", address="I-8, EXIT 119", city="Gila Bend", state="AZ"
    ) -> dict:
        return {
            "Truckstop Name": name,
            "Address": address,
            "City": city,
            "State": state,
        }

    @rsps_lib.activate
    def test_precise_match_returns_precise_source(self):
        # P1CAA is the quality code MapQuest returns for a point-level match.
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json=_mapquest_response(
                32.94, -112.71, quality="P1CAA", city="Gila Bend", state="AZ"
            ),
        )
        results = _geocode_batch_with_fallback([self._station()], api_key="test-key")
        assert results[0] == (32.94, -112.71, "precise")

    @rsps_lib.activate
    def test_coarse_quality_marked_as_city_centroid(self):
        # Z1XAA = zip-level quality — coarse result even though location matches.
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json=_mapquest_response(
                32.94, -112.71, quality="Z1XAA", city="Gila Bend", state="AZ"
            ),
        )
        results = _geocode_batch_with_fallback([self._station()], api_key="test-key")
        assert results[0] == (32.94, -112.71, "city_centroid")

    @rsps_lib.activate
    def test_location_mismatch_triggers_fallback(self):
        """MapQuest returned a result in the wrong city+state — must be discarded and retried."""
        # First POST: point-level result but wrong location entirely.
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json=_mapquest_response(
                34.05, -118.24, quality="P1CAA", city="Los Angeles", state="CA"
            ),
        )
        # Second POST (centroid fallback): correct location.
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json=_mapquest_response(
                32.94, -112.71, quality="Z1XAA", city="Gila Bend", state="AZ"
            ),
        )
        results = _geocode_batch_with_fallback([self._station()], api_key="test-key")
        lat, lng, source = results[0]
        assert source == "city_centroid"
        assert abs(lat - 32.94) < 0.01

    @rsps_lib.activate
    def test_wrong_state_only_triggers_fallback(self):
        """Right city, wrong state — still must fall back."""
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json=_mapquest_response(
                32.94, -112.71, quality="P1CAA", city="Gila Bend", state="CA"
            ),
        )
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json=_mapquest_response(
                32.94, -112.71, quality="Z1XAA", city="Gila Bend", state="AZ"
            ),
        )
        results = _geocode_batch_with_fallback([self._station()], api_key="test-key")
        assert results[0][2] == "city_centroid"

    @rsps_lib.activate
    def test_fallback_triggered_when_precise_fails(self):
        # First POST (precise) → empty; second POST (fallback) → hit with coarse quality.
        rsps_lib.add(rsps_lib.POST, MAPQUEST_BATCH_URL, json=_mapquest_empty_response())
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json=_mapquest_response(
                32.94, -112.71, quality="Z1XAA", city="Gila Bend", state="AZ"
            ),
        )
        results = _geocode_batch_with_fallback([self._station()], api_key="test-key")
        assert results[0] == (32.94, -112.71, "city_centroid")

    @rsps_lib.activate
    def test_returns_none_when_both_passes_fail(self):
        rsps_lib.add(rsps_lib.POST, MAPQUEST_BATCH_URL, json=_mapquest_empty_response())
        rsps_lib.add(rsps_lib.POST, MAPQUEST_BATCH_URL, json=_mapquest_empty_response())
        results = _geocode_batch_with_fallback([self._station()], api_key="test-key")
        assert results[0] is None


# ---------------------------------------------------------------------------
# Command integration
# ---------------------------------------------------------------------------


class TestGeocodeMqCommand:
    """Verifies the management command raises on missing key and writes the fixture."""

    def test_raises_without_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(CommandError, match="MAPQUEST_API_KEY"):
                call_command("geocode_stations_mapquest")

    @rsps_lib.activate
    @pytest.mark.django_db
    def test_writes_fixture_on_dry_run(self, tmp_path):
        # Dry-run processes 1 batch (BATCH_SIZE stations) from the real CSV.
        # Mock returns one result per station in the batch.
        from stations.management.commands.geocode_stations_mapquest import BATCH_SIZE

        single_result = {
            "locations": [
                {
                    "latLng": {"lat": 36.538, "lng": -95.220},
                    "geocodeQualityCode": "P1CAA",
                    "adminArea5": "Big Cabin",
                    "adminArea3": "OK",
                }
            ]
        }
        # Allow multiple POST calls (precise pass + possible fallback pass per batch).
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json={"results": [single_result] * BATCH_SIZE},
            status=200,
        )
        rsps_lib.add(
            rsps_lib.POST,
            MAPQUEST_BATCH_URL,
            json={"results": [single_result] * BATCH_SIZE},
            status=200,
        )
        fixture_path = tmp_path / "stations_geocoded_mapquest.json"

        with (
            patch.dict("os.environ", {"MAPQUEST_API_KEY": "test-key"}),
            patch(
                "stations.management.commands.geocode_stations_mapquest.FIXTURE_PATH",
                fixture_path,
            ),
            patch(
                "stations.management.commands.geocode_stations_mapquest._load_existing_fixture",
                return_value={},
            ),
        ):
            call_command("geocode_stations_mapquest", dry_run=True)

        assert fixture_path.exists()
        data = json.loads(fixture_path.read_text())
        assert len(data) > 0
        assert data[0]["model"] == "stations.fuelstation"
