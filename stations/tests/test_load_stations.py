"""
Tests for the load_stations management command.

Uses pytest-django's @pytest.mark.django_db and a temp fixture file so the
real fixture on disk is never touched during the test run.
"""

import csv
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from stations.models import FuelStation


def _fixture_entry(
    pk: int, name: str, city: str = "Gila Bend", state: str = "AZ"
) -> dict:
    return {
        "model": "stations.fuelstation",
        "pk": pk,
        "fields": {
            "opis_id": pk,
            "name": name,
            "address": "I-8, EXIT 119",
            "city": city,
            "state": state,
            "rack_id": 930,
            "price": "3.8990",
            "latitude": 32.94,
            "longitude": -112.71,
            "geohash": "9qkgz",
            "geocode_source": "precise",
        },
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    headers = [
        "OPIS Truckstop ID",
        "Truckstop Name",
        "Address",
        "City",
        "State",
        "Rack ID",
        "Retail Price",
    ]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _csv_row(name: str, city: str, state: str, price: str) -> dict:
    return {
        "OPIS Truckstop ID": 1,
        "Truckstop Name": name,
        "Address": "I-8",
        "City": city,
        "State": state,
        "Rack ID": 930,
        "Retail Price": price,
    }


@pytest.mark.django_db
class TestLoadStationsCommand:
    """
    - load_stations must be idempotent: a second run replaces rather than appends.
    - Missing fixture must raise CommandError so entrypoint.sh fails loudly.
    - Price is taken from the minimum across all CSV rows for that station.
    - All fixture fields must be persisted correctly.
    """

    def test_loads_stations_from_fixture(self, tmp_path):
        fixture_path = tmp_path / "stations_geocoded.json"
        fixture_path.write_text(json.dumps([_fixture_entry(1, "PILOT #1")]))
        csv_path = tmp_path / "prices.csv"
        _write_csv(csv_path, [_csv_row("PILOT #1", "Gila Bend", "AZ", "3.8990")])

        with (
            patch(
                "stations.management.commands.load_stations.FIXTURE_PATH", fixture_path
            ),
            patch("stations.management.commands.load_stations.CSV_PATH", csv_path),
        ):
            call_command("load_stations")

        assert FuelStation.objects.count() == 1
        station = FuelStation.objects.get()
        assert station.name == "PILOT #1"
        assert station.geohash == "9qkgz"

    def test_is_idempotent(self, tmp_path):
        fixture_path = tmp_path / "stations_geocoded.json"
        fixture_path.write_text(json.dumps([_fixture_entry(1, "PILOT #1")]))
        csv_path = tmp_path / "prices.csv"
        _write_csv(csv_path, [_csv_row("PILOT #1", "Gila Bend", "AZ", "3.8990")])

        with (
            patch(
                "stations.management.commands.load_stations.FIXTURE_PATH", fixture_path
            ),
            patch("stations.management.commands.load_stations.CSV_PATH", csv_path),
        ):
            call_command("load_stations")
            call_command("load_stations")

        assert FuelStation.objects.count() == 1

    def test_raises_on_missing_fixture(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        with patch("stations.management.commands.load_stations.FIXTURE_PATH", missing):
            with pytest.raises(CommandError, match="Fixture not found"):
                call_command("load_stations")

    def test_loads_multiple_stations(self, tmp_path):
        entries = [_fixture_entry(i, f"Station {i}") for i in range(1, 6)]
        fixture_path = tmp_path / "stations_geocoded.json"
        fixture_path.write_text(json.dumps(entries))
        csv_path = tmp_path / "prices.csv"
        _write_csv(
            csv_path,
            [_csv_row(f"Station {i}", "Gila Bend", "AZ", "3.899") for i in range(1, 6)],
        )

        with (
            patch(
                "stations.management.commands.load_stations.FIXTURE_PATH", fixture_path
            ),
            patch("stations.management.commands.load_stations.CSV_PATH", csv_path),
        ):
            call_command("load_stations")

        assert FuelStation.objects.count() == 5

    def test_uses_min_price_from_csv(self, tmp_path):
        """Price in DB must be the minimum across all CSV rows, not the fixture value."""
        fixture_path = tmp_path / "stations_geocoded.json"
        fixture_path.write_text(json.dumps([_fixture_entry(1, "PILOT #1")]))
        csv_path = tmp_path / "prices.csv"
        _write_csv(
            csv_path,
            [
                _csv_row("PILOT #1", "Gila Bend", "AZ", "3.999"),
                _csv_row("PILOT #1", "Gila Bend", "AZ", "3.499"),  # cheapest
                _csv_row("PILOT #1", "Gila Bend", "AZ", "3.799"),
            ],
        )

        with (
            patch(
                "stations.management.commands.load_stations.FIXTURE_PATH", fixture_path
            ),
            patch("stations.management.commands.load_stations.CSV_PATH", csv_path),
        ):
            call_command("load_stations")

        assert FuelStation.objects.get().price == Decimal("3.499")

    def test_falls_back_to_fixture_price_when_station_not_in_csv(self, tmp_path):
        """If the CSV has no row for a station, the fixture price is used unchanged."""
        fixture_path = tmp_path / "stations_geocoded.json"
        fixture_path.write_text(json.dumps([_fixture_entry(1, "PILOT #1")]))
        csv_path = tmp_path / "prices.csv"
        _write_csv(csv_path, [_csv_row("DIFFERENT STOP", "Other City", "TX", "2.999")])

        with (
            patch(
                "stations.management.commands.load_stations.FIXTURE_PATH", fixture_path
            ),
            patch("stations.management.commands.load_stations.CSV_PATH", csv_path),
        ):
            call_command("load_stations")

        assert FuelStation.objects.get().price == Decimal("3.8990")

    def test_price_stored_as_decimal(self, tmp_path):
        fixture_path = tmp_path / "stations_geocoded.json"
        fixture_path.write_text(json.dumps([_fixture_entry(1, "PILOT #1")]))
        csv_path = tmp_path / "prices.csv"
        _write_csv(csv_path, [_csv_row("PILOT #1", "Gila Bend", "AZ", "3.8990")])

        with (
            patch(
                "stations.management.commands.load_stations.FIXTURE_PATH", fixture_path
            ),
            patch("stations.management.commands.load_stations.CSV_PATH", csv_path),
        ):
            call_command("load_stations")

        assert FuelStation.objects.get().price == Decimal("3.8990")
