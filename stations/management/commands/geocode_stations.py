"""
Offline, resumable geocoding command: CSV -> coordinates -> fixture.

Run once before shipping. Takes ~2.5 hours for 8,151 stations at Nominatim's
1 req/sec rate limit. Safe to kill and restart — already-geocoded entries are
read from the partial fixture and skipped.
"""

import csv
import json
import logging
import time

import pygeohash
import requests
from django.core.management.base import BaseCommand

from stations.app_settings import (
    CSV_PATH,
    GEOHASH_PRECISION,
)
from stations.app_settings import NOMINATIM_FIXTURE_PATH as FIXTURE_PATH
from stations.app_settings import NOMINATIM_REQUEST_DELAY as REQUEST_DELAY
from stations.app_settings import (
    NOMINATIM_URL,
    NOMINATIM_USER_AGENT,
)

logger = logging.getLogger(__name__)


def _geocode_address(
    name: str, address: str, city: str, state: str
) -> tuple[float, float, str] | None:
    """
    - Two-step fallback: try full address first, then city+state centroid.
    - Returns (lat, lng, source) where source is 'precise' or 'city_centroid'.
    - Returns None if both attempts fail (logged as WARNING, station is skipped).
    - Uses structured Nominatim params to improve hit rate on highway descriptors.
    """
    params_precise = {
        "q": f"{name}, {address.split(',')[0]}, {city}, {state}, USA",
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    params_fallback = {
        "q": f"{city}, {state}, USA",
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    headers = {"User-Agent": NOMINATIM_USER_AGENT}

    for params, source in [
        (params_precise, "precise"),
        (params_fallback, "city_centroid"),
    ]:
        try:
            resp = requests.get(
                NOMINATIM_URL, params=params, headers=headers, timeout=10
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                lat = float(results[0]["lat"])
                lng = float(results[0]["lon"])
                return lat, lng, source
        except requests.RequestException as exc:
            logger.warning("Nominatim request failed for %r: %s", params.get("q"), exc)

    return None


def _load_existing_fixture(fixture_path: str) -> dict[str, dict]:
    """
    - Reads the partial fixture (if it exists) and returns a dict keyed by
      a dedup key so already-geocoded stations are skipped on resume.
    - Keyed on (name, city, state) to match the dedup strategy used during write.
    """
    if not fixture_path.exists():
        return {}

    with fixture_path.open() as fh:
        data = json.load(fh)

    existing = {}
    for entry in data:
        fields = entry["fields"]
        key = (fields["name"], fields["city"], fields["state"])
        existing[key] = entry
    return existing


def _read_csv_stations() -> list[dict]:
    """
    - Reads the source CSV and deduplicates on (name, city, state), keeping the
      row with the lowest retail price when duplicates exist.
    - The CSV has rows with the same station appearing multiple times — either
      identical duplicates or the same location at different price points. Keeping
      the cheapest is the most useful choice for the optimizer downstream.
    """
    best: dict[tuple, dict] = {}

    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = (row["Truckstop Name"], row["City"], row["State"])
            if key not in best or float(row["Retail Price"]) < float(
                best[key]["Retail Price"]
            ):
                best[key] = row

    return list(best.values())


class Command(BaseCommand):
    """
    - Geocodes all stations from the source CSV using Nominatim (OpenStreetMap).
    - Writes results incrementally to stations/fixtures/stations_geocoded.json
      so the process is resumable after any interruption.
    - Skips rows already present in the partial fixture (keyed on name+city+state).
    - Respects Nominatim's 1 req/sec policy via a 1.1s sleep between requests.
    """

    help = "Geocode fuel stations from CSV and write to fixture (resumable)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Process only the first 5 stations (for smoke-testing).",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]

        stations = _read_csv_stations()
        existing = _load_existing_fixture(FIXTURE_PATH)

        logger.info(
            "CSV rows (deduped): %d | already geocoded: %d",
            len(stations),
            len(existing),
        )

        if dry_run:
            stations = stations[:20]
            logger.info("Dry-run mode: processing first 5 stations only.")

        results = list(existing.values())
        pk_counter = len(results) + 1
        geocoded = 0
        skipped = 0
        failed = 0

        for station in stations:
            name = station["Truckstop Name"]
            city = station["City"]
            state = station["State"]
            key = (name, city, state)

            if key in existing:
                skipped += 1
                continue

            coords = _geocode_address(name, station["Address"], city, state)
            if coords is None:
                logger.warning(
                    "Could not geocode: %s, %s, %s — skipping.", name, city, state
                )
                failed += 1
                time.sleep(REQUEST_DELAY)
                continue

            lat, lng, source = coords
            gh = pygeohash.encode(lat, lng, precision=GEOHASH_PRECISION)

            entry = {
                "model": "stations.fuelstation",
                "pk": pk_counter,
                "fields": {
                    "opis_id": int(station["OPIS Truckstop ID"]),
                    "name": name,
                    "address": station["Address"],
                    "city": city,
                    "state": state,
                    "rack_id": int(station["Rack ID"]),
                    "price": station["Retail Price"],
                    "latitude": lat,
                    "longitude": lng,
                    "geohash": gh,
                    "geocode_source": source,
                },
            }
            results.append(entry)
            existing[key] = entry
            pk_counter += 1
            geocoded += 1

            # Write after every station so a crash loses at most one entry.
            FIXTURE_PATH.write_text(json.dumps(results, indent=2))

            logger.debug(
                "Geocoded [%d/%d] %s -> (%.5f, %.5f) [%s]",
                pk_counter - 1,
                len(stations),
                name,
                lat,
                lng,
                source,
            )
            time.sleep(REQUEST_DELAY)

        logger.info(
            "Done. geocoded=%d skipped=%d failed=%d fixture=%s",
            geocoded,
            skipped,
            failed,
            FIXTURE_PATH,
        )
