"""
Loads the pre-geocoded station fixture into the database.

This is the command called by entrypoint.sh on every container start.
It is idempotent: it clears the table first and reloads, so re-running
is safe and always leaves the DB in sync with the fixture on disk.
"""

import csv
import json
import logging
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stations.models import FuelStation

CSV_PATH = settings.CSV_PATH
FIXTURE_PATH = settings.LOAD_FIXTURE_PATH

logger = logging.getLogger(__name__)


def _build_min_price_index() -> dict[tuple, Decimal]:
    """
    - Reads the source CSV and builds a dict mapping (name, city, state) to the
      minimum retail price across all rows for that station.
    - The fixture holds one row per station (deduped on name/city/state), but the
      CSV may have the same station listed multiple times at different prices. We
      always want the cheapest price in the DB so the optimizer picks the best stop.
    """
    min_prices: dict[tuple, Decimal] = {}

    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row["Truckstop Name"], row["City"], row["State"])
            price = Decimal(row["Retail Price"])
            if key not in min_prices or price < min_prices[key]:
                min_prices[key] = price

    return min_prices


class Command(BaseCommand):
    """
    - Truncates the FuelStation table and reloads from the geocoded fixture.
    - Overrides price from the fixture with the minimum price found in the source
      CSV for each station, so the optimizer always sees the cheapest available price.
    - Idempotent: safe to call on every deploy / container start.
    - Uses bulk_create for a single DB round-trip instead of one INSERT per row.
    - Raises CommandError (non-zero exit) if the fixture is missing so
      entrypoint.sh fails loudly rather than silently serving a stationless API.
    """

    help = "Load pre-geocoded stations fixture into the database."

    def handle(self, *args, **options):
        if not FIXTURE_PATH.exists():
            raise CommandError(
                f"Fixture not found at {FIXTURE_PATH}. "
                "Run `python manage.py geocode_stations` first."
            )

        with FIXTURE_PATH.open() as fh:
            entries = json.load(fh)

        min_prices = _build_min_price_index()

        logger.info("Clearing FuelStation table before reload.")
        FuelStation.objects.all().delete()

        stations = []
        for e in entries:
            f = e["fields"]
            key = (f["name"], f["city"], f["state"])
            price = min_prices.get(key, Decimal(str(f["price"])))
            stations.append(
                FuelStation(
                    opis_id=f["opis_id"],
                    name=f["name"],
                    address=f["address"],
                    city=f["city"],
                    state=f["state"],
                    rack_id=f["rack_id"],
                    price=price,
                    latitude=f["latitude"],
                    longitude=f["longitude"],
                    geohash=f["geohash"],
                    geocode_source=f["geocode_source"],
                )
            )

        FuelStation.objects.bulk_create(stations)
        logger.info("Loaded %d fuel stations from fixture.", len(stations))
