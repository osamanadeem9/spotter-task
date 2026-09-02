"""
MapQuest batch geocoder — faster and more precise than the Nominatim alternative.

MapQuest's batch endpoint accepts 100 addresses per POST, reducing ~8,151
individual calls to ~82 batch calls with no rate limits.

Requires MAPQUEST_API_KEY in the environment.

The output fixture is kept identical in format to the Nominatim command so
either command can populate the fixture consumed by load_stations.
"""

import json
import logging
import os

import pygeohash
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stations.management.commands.geocode_stations import (
    _load_existing_fixture,
    _read_csv_stations,
)

BATCH_SIZE = settings.MAPQUEST_BATCH_SIZE
FIXTURE_PATH = settings.MAPQUEST_FIXTURE_PATH
GEOHASH_PRECISION = settings.GEOHASH_PRECISION
MAPQUEST_BATCH_URL = settings.MAPQUEST_BATCH_URL

logger = logging.getLogger(__name__)


def _build_location_string(name: str, address: str, city: str, state: str) -> str:
    """
    - MapQuest accepts a single free-form string per location.
    - Including the business name improves hit rate for named truck stops.
    - Only the first segment of the address is used (before the first comma) to
      avoid confusing the geocoder with highway junction notation like
      "I-44, EXIT 283 & US-69".
    """
    street = address.split(",")[0].strip()
    return f"{name}, {street}, {city}, {state}, USA"


def _batch_geocode(locations: list[str], api_key: str) -> list[dict | None]:
    """
    - Sends one POST to MapQuest's batch endpoint for up to 100 locations.
    - Returns a list of result dicts (one per input), or None for each that failed.
    - MapQuest returns results in the same order as the input locations.
    - A result is considered failed if statusCode != 0 or the location list is empty.
    """
    payload = {
        "locations": [{"street": loc} for loc in locations],
        "options": {"thumbMaps": False, "maxResults": 1},
    }
    try:
        resp = requests.post(
            MAPQUEST_BATCH_URL,
            params={"key": api_key},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("MapQuest batch request failed: %s", exc)
        return [None] * len(locations)

    # Guard: MapQuest must return one result per input location.
    # Clip to len(locations) in case the API ever returns extra rows.
    results = data.get("results", [])[: len(locations)]
    out: list[dict | None] = []
    for result in results:
        locs = result.get("locations", [])
        if not locs:
            out.append(None)
            continue
        loc = locs[0]
        # displayLatLng is the road-snapped coordinate — more precise than latLng
        # (the raw geocode centroid). Fall back to latLng if display is absent.
        display = loc.get("displayLatLng") or loc.get("latLng") or {}
        lat = display.get("lat")
        lng = display.get("lng")
        quality = loc.get("geocodeQualityCode", "")
        returned_city = loc.get("adminArea5", "")
        returned_state = loc.get("adminArea3", "")
        if lat is None or lng is None:
            out.append(None)
        else:
            out.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "quality": quality,
                    "city": returned_city,
                    "state": returned_state,
                }
            )
    return out


def _location_matches(
    returned_city: str, returned_state: str, expected_city: str, expected_state: str
) -> bool:
    """
    - Exact match on both city and state after stripping whitespace and uppercasing.
    - Both fields must be non-empty; an empty return means MapQuest gave no location info.
    - MapQuest returns the 2-letter state abbreviation in adminArea3, matching the CSV.
    """
    return (
        bool(returned_city and returned_state)
        and returned_city.strip().lower() == expected_city.strip().lower()
        and returned_state.strip().upper() == expected_state.strip().upper()
    )


# Quality codes that indicate a street/point-level result (not city/zip/state coarse).
# P = point match, L = interpolated address, I = intersection — all are address-quality.
_PRECISE_QUALITY_PREFIXES = ("P", "L", "I")


def _geocode_batch_with_fallback(
    stations: list[dict], api_key: str
) -> list[tuple[float, float, str] | None]:
    """
    - Fallback triggers when any of these are true for a result:
        1. No result from MapQuest.
        2. Returned city or state doesn't exactly match the expected values — MapQuest
           can geocode a highway descriptor to a different city/state, which would
           silently corrupt the spatial index.
    - Source is 'precise' only when the location matches AND quality is address-level.
      Otherwise 'city_centroid' — still a valid coordinate, just less accurate.
    - Batching is preserved across both passes to minimise API call count.
    """
    precise_locs = [
        _build_location_string(s["Truckstop Name"], s["Address"], s["City"], s["State"])
        for s in stations
    ]
    results = _batch_geocode(precise_locs, api_key)

    # Any result with a missing or mismatched city+state goes to the centroid fallback.
    fallback_indices = {
        i
        for i, r in enumerate(results)
        if r is None
        or not _location_matches(
            r.get("city", ""),
            r.get("state", ""),
            stations[i]["City"],
            stations[i]["State"],
        )
    }

    if fallback_indices:
        fallback_locs = [
            f"{stations[i]['City']}, {stations[i]['State']}, USA"
            for i in fallback_indices
        ]
        fallback_results = _batch_geocode(fallback_locs, api_key)
        for idx, fb in zip(fallback_indices, fallback_results):
            results[idx] = fb

    out: list[tuple[float, float, str] | None] = []
    for i, result in enumerate(results):
        if result is None:
            out.append(None)
            continue
        lat, lng = result["lat"], result["lng"]
        if i in fallback_indices:
            # Results from the centroid fallback are always city_centroid regardless
            # of the quality code MapQuest returns for the city+state query.
            out.append((lat, lng, "city_centroid"))
        else:
            quality = result.get("quality", "").upper()
            source = (
                "precise"
                if quality.startswith(_PRECISE_QUALITY_PREFIXES)
                else "city_centroid"
            )
            out.append((lat, lng, source))

    return out


class Command(BaseCommand):
    """
    - Batch-geocodes all stations using MapQuest's geocoding API (100 per request).
    - Resumes from an existing partial fixture — already-geocoded stations are skipped.
    - Writes the fixture in the same format as geocode_stations (Nominatim) so
      load_stations works regardless of which geocoder produced the fixture.
    - Requires MAPQUEST_API_KEY in the environment.
    """

    help = (
        "Geocode fuel stations via MapQuest batch API and write to fixture (resumable)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Process only the first batch of stations (for smoke-testing).",
        )

    def handle(self, *args, **options):
        api_key = os.environ.get("MAPQUEST_API_KEY", "")
        if not api_key:
            raise CommandError("MAPQUEST_API_KEY environment variable is not set.")

        dry_run: bool = options["dry_run"]

        all_stations = _read_csv_stations()
        existing = _load_existing_fixture(FIXTURE_PATH)

        logger.info(
            "CSV rows (deduped): %d | already geocoded: %d",
            len(all_stations),
            len(existing),
        )

        pending = [
            s
            for s in all_stations
            if (s["Truckstop Name"], s["City"], s["State"]) not in existing
        ]

        if dry_run:
            pending = pending[:BATCH_SIZE]
            logger.info(
                "Dry-run mode: processing first %d stations only.", len(pending)
            )

        results = list(existing.values())
        pk_counter = len(results) + 1
        geocoded = 0
        failed = 0

        for batch_start in range(0, len(pending), BATCH_SIZE):
            batch = pending[batch_start : batch_start + BATCH_SIZE]
            coords_list = _geocode_batch_with_fallback(batch, api_key)

            for station, coords in zip(batch, coords_list):
                name = station["Truckstop Name"]
                city = station["City"]
                state = station["State"]

                if coords is None:
                    logger.warning(
                        "Could not geocode: %s, %s, %s — skipping.", name, city, state
                    )
                    failed += 1
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
                existing[(name, city, state)] = entry
                pk_counter += 1
                geocoded += 1

            # Persist after each batch so a crash loses at most one batch.
            FIXTURE_PATH.write_text(json.dumps(results, indent=2))
            logger.debug(
                "Batch %d–%d done. Total geocoded so far: %d",
                batch_start + 1,
                batch_start + len(batch),
                geocoded,
            )

        logger.info(
            "Done. geocoded=%d failed=%d fixture=%s",
            geocoded,
            failed,
            FIXTURE_PATH,
        )
