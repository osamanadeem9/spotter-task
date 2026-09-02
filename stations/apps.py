import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)

# Module-level singleton so any app can import and use it without re-querying the DB.
station_index: dict = {}


class StationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stations"

    def ready(self) -> None:
        """
        - Builds the geohash spatial index once when Django starts.
        - Guarded by a try/except so a missing DB (first migrate run, CI) doesn't
          crash the process — the index stays empty and the health endpoint reports it
          as unloaded.
        """
        global station_index
        try:
            from stations.services.spatial_index import build_index

            station_index = build_index()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not build station index at startup: %s", exc)
