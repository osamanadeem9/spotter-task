"""
App-level constants for the stations app.

All path, URL, and tuning constants are centralised here so management
commands and tests import from one place rather than redefining them.
"""

from pathlib import Path

from django.conf import settings

# Source data
CSV_PATH = Path(settings.BASE_DIR) / "data" / "fuel-prices-for-be-assessment.csv"

# Geocoded fixture produced by geocode_stations (Nominatim)
NOMINATIM_FIXTURE_PATH = (
    Path(settings.BASE_DIR) / "stations" / "fixtures" / "stations_geocoded.json"
)

# Geocoded fixture produced by geocode_stations_mapquest (DEFAULT)
MAPQUEST_FIXTURE_PATH = (
    Path(settings.BASE_DIR)
    / "stations"
    / "fixtures"
    / "stations_geocoded_mapquest.json"
)

# The fixture consumed by load_stations (defaults to MapQuest output)
LOAD_FIXTURE_PATH = MAPQUEST_FIXTURE_PATH

# Geohash precision used when encoding coordinates
GEOHASH_PRECISION = 8

# Nominatim
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "spotter-task, itsosamanadeem@gmail.com"
# 1.1 s keeps us safely under Nominatim's 1 req/sec rate limit
NOMINATIM_REQUEST_DELAY = 1.1

# MapQuest
MAPQUEST_BATCH_URL = "https://www.mapquestapi.com/geocoding/v1/batch"
MAPQUEST_BATCH_SIZE = 100
