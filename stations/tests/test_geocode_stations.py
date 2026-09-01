"""
Tests for the geocode_stations management command helpers.

All Nominatim HTTP calls are mocked via the `responses` library — no real
network traffic is made during the test suite.
"""

import json
from pathlib import Path
from unittest.mock import patch

import responses as rsps_lib

from stations.management.commands.geocode_stations import (
    _geocode_address,
    _load_existing_fixture,
    _read_csv_stations,
)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class TestGeocodeAddress:
    """
    - Verifies the two-step fallback: precise → city_centroid.
    - Verifies None is returned when both attempts fail.
    """

    @rsps_lib.activate
    def test_returns_precise_on_first_hit(self):
        rsps_lib.add(
            rsps_lib.GET,
            NOMINATIM_URL,
            json=[{"lat": "36.538", "lon": "-95.220"}],
            status=200,
        )
        result = _geocode_address(
            "WOODSHED OF BIG CABIN", "I-44, EXIT 283 & US-69", "Big Cabin", "OK"
        )
        assert result == (36.538, -95.220, "precise")

    @rsps_lib.activate
    def test_falls_back_to_city_centroid(self):
        # First call (precise) returns empty; second (city centroid) returns a hit.
        rsps_lib.add(rsps_lib.GET, NOMINATIM_URL, json=[], status=200)
        rsps_lib.add(
            rsps_lib.GET,
            NOMINATIM_URL,
            json=[{"lat": "36.538", "lon": "-95.220"}],
            status=200,
        )
        result = _geocode_address(
            "WOODSHED OF BIG CABIN", "I-44, EXIT 283 & US-69", "Big Cabin", "OK"
        )
        assert result == (36.538, -95.220, "city_centroid")

    @rsps_lib.activate
    def test_returns_none_when_both_fail(self):
        rsps_lib.add(rsps_lib.GET, NOMINATIM_URL, json=[], status=200)
        rsps_lib.add(rsps_lib.GET, NOMINATIM_URL, json=[], status=200)
        result = _geocode_address("UNKNOWN STOP", "Unknown Road", "Nowhere", "XX")
        assert result is None

    @rsps_lib.activate
    def test_returns_none_on_network_error(self):
        import requests as req_lib

        rsps_lib.add(
            rsps_lib.GET,
            NOMINATIM_URL,
            body=req_lib.exceptions.ConnectionError("timeout"),
        )
        rsps_lib.add(
            rsps_lib.GET,
            NOMINATIM_URL,
            body=req_lib.exceptions.ConnectionError("timeout"),
        )
        result = _geocode_address("STOP NAME", "Any Rd", "City", "ST")
        assert result is None


class TestLoadExistingFixture:
    """
    - Verifies resume behaviour: existing entries are keyed on (name, city, state).
    - Returns empty dict when fixture is absent.
    """

    def test_returns_empty_when_no_fixture(self, tmp_path):
        result = _load_existing_fixture(tmp_path / "nonexistent.json")
        assert result == {}

    def test_loads_existing_entries(self, tmp_path):
        fixture = [
            {
                "model": "stations.fuelstation",
                "pk": 1,
                "fields": {
                    "name": "PILOT #1",
                    "city": "Gila Bend",
                    "state": "AZ",
                    "opis_id": 20,
                    "address": "I-8, EXIT 119",
                    "rack_id": 930,
                    "price": "3.899",
                    "latitude": 32.94,
                    "longitude": -112.71,
                    "geohash": "9qkgz",
                    "geocode_source": "precise",
                },
            }
        ]
        fixture_path = tmp_path / "stations_geocoded.json"
        fixture_path.write_text(json.dumps(fixture))

        result = _load_existing_fixture(fixture_path)

        assert ("PILOT #1", "Gila Bend", "AZ") in result


class TestReadCsvStations:
    """
    - Verifies deduplication: rows with the same (name, city, state) are collapsed.
    - Verifies cheapest price is kept when duplicates have different prices.
    - Verifies all non-duplicate rows are returned.
    """

    def _write_csv(self, tmp_path: Path, rows: list[dict]) -> Path:
        csv_path = tmp_path / "test.csv"
        headers = [
            "OPIS Truckstop ID",
            "Truckstop Name",
            "Address",
            "City",
            "State",
            "Rack ID",
            "Retail Price",
        ]
        lines = [",".join(headers)]
        for r in rows:
            lines.append(",".join(str(r[h]) for h in headers))
        csv_path.write_text("\n".join(lines))
        return csv_path

    def test_deduplicates_same_name_city_state(self, tmp_path):
        rows = [
            {
                "OPIS Truckstop ID": 20,
                "Truckstop Name": "PILOT #1",
                "Address": "I-8",
                "City": "Gila Bend",
                "State": "AZ",
                "Rack ID": 930,
                "Retail Price": "3.899",
            },
            {
                "OPIS Truckstop ID": 20,
                "Truckstop Name": "PILOT #1",
                "Address": "I-8",
                "City": "Gila Bend",
                "State": "AZ",
                "Rack ID": 930,
                "Retail Price": "3.899",
            },
        ]
        csv_path = self._write_csv(tmp_path, rows)
        with patch("stations.management.commands.geocode_stations.CSV_PATH", csv_path):
            result = _read_csv_stations()
        assert len(result) == 1

    def test_keeps_cheapest_price_among_duplicates(self, tmp_path):
        rows = [
            {
                "OPIS Truckstop ID": 20,
                "Truckstop Name": "PILOT #1",
                "Address": "I-8",
                "City": "Gila Bend",
                "State": "AZ",
                "Rack ID": 930,
                "Retail Price": "3.999",
            },
            {
                "OPIS Truckstop ID": 20,
                "Truckstop Name": "PILOT #1",
                "Address": "I-8",
                "City": "Gila Bend",
                "State": "AZ",
                "Rack ID": 930,
                "Retail Price": "3.499",
            },
            {
                "OPIS Truckstop ID": 20,
                "Truckstop Name": "PILOT #1",
                "Address": "I-8",
                "City": "Gila Bend",
                "State": "AZ",
                "Rack ID": 930,
                "Retail Price": "3.799",
            },
        ]
        csv_path = self._write_csv(tmp_path, rows)
        with patch("stations.management.commands.geocode_stations.CSV_PATH", csv_path):
            result = _read_csv_stations()
        assert len(result) == 1
        assert float(result[0]["Retail Price"]) == 3.499

    def test_keeps_distinct_rows(self, tmp_path):
        rows = [
            {
                "OPIS Truckstop ID": 7,
                "Truckstop Name": "WOODSHED",
                "Address": "I-44",
                "City": "Big Cabin",
                "State": "OK",
                "Rack ID": 307,
                "Retail Price": "3.007",
            },
            {
                "OPIS Truckstop ID": 9,
                "Truckstop Name": "KWIK TRIP",
                "Address": "I-94",
                "City": "Tomah",
                "State": "WI",
                "Rack ID": 420,
                "Retail Price": "3.287",
            },
        ]
        csv_path = self._write_csv(tmp_path, rows)
        with patch("stations.management.commands.geocode_stations.CSV_PATH", csv_path):
            result = _read_csv_stations()
        assert len(result) == 2
