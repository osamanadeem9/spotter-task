import pygeohash
import pytest

from stations.models import FuelStation

_GEOHASH_PRECISION = 8


@pytest.fixture
def fuel_station_factory(db):
    """
    - Returns a callable that creates and returns a persisted FuelStation.
    - Caller may override any field; geohash is auto-computed from lat/lng.
    - Each call increments opis_id by default to avoid accidental uniqueness
      collisions across tests that create multiple stations.
    """
    counter = {"n": 0}

    def factory(
        name: str = "Test Station",
        address: str = "123 Test Rd",
        city: str = "Testville",
        state: str = "TX",
        price: float = 3.0,
        latitude: float = 36.566,
        longitude: float = -95.221,
        geocode_source: str = FuelStation.GEOCODE_SOURCE_PRECISE,
        **kwargs,
    ) -> FuelStation:
        counter["n"] += 1
        geohash = pygeohash.encode(latitude, longitude, precision=_GEOHASH_PRECISION)
        return FuelStation.objects.create(
            opis_id=kwargs.pop("opis_id", counter["n"]),
            name=name,
            address=address,
            city=city,
            state=state,
            rack_id=kwargs.pop("rack_id", 1),
            price=price,
            latitude=latitude,
            longitude=longitude,
            geohash=geohash,
            geocode_source=geocode_source,
            **kwargs,
        )

    return factory
