"""
Project-wide app constants, imported into base.py so they are accessible
anywhere via django.conf.settings.

BASE_DIR is re-derived here to avoid a circular import with the settings module.
"""

from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent.parent

###########################
# --- Stations ---
###########################

CSV_PATH = _BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"

NOMINATIM_FIXTURE_PATH = _BASE_DIR / "stations" / "fixtures" / "stations_geocoded.json"

MAPQUEST_FIXTURE_PATH = (
    _BASE_DIR / "stations" / "fixtures" / "stations_geocoded_mapquest.json"
)

LOAD_FIXTURE_PATH = MAPQUEST_FIXTURE_PATH

GEOHASH_PRECISION = 8

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "spotter-task, itsosamanadeem@gmail.com"
NOMINATIM_REQUEST_DELAY = 1.1

MAPQUEST_BATCH_URL = "https://www.mapquestapi.com/geocoding/v1/batch"
MAPQUEST_BATCH_SIZE = 100

###########################
# --- ORS ---
###########################

ORS_DIRECTIONS_URL = (
    "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
)
ORS_GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
ORS_REQUEST_TIMEOUT = 30

###########################
# --- Fuel Optimizer ---
###########################

TANK_RANGE_MILES = 500.0
MPG = 10.0
