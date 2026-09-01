import pytest

from stations.models import FuelStation


@pytest.mark.django_db
class TestFuelStationModel:
    """
    - Confirms the model persists and retrieves all fields correctly.
    - Verifies __str__ output and geocode_source default.
    """

    def _make_station(self, **overrides) -> FuelStation:
        defaults = dict(
            opis_id=7,
            name="WOODSHED OF BIG CABIN",
            address="I-44, EXIT 283 & US-69",
            city="Big Cabin",
            state="OK",
            rack_id=307,
            price="3.0073",
            latitude=36.5381,
            longitude=-95.2201,
            geohash="9yvf4",
        )
        defaults.update(overrides)
        return FuelStation.objects.create(**defaults)

    def test_create_and_retrieve(self):
        station = self._make_station()
        fetched = FuelStation.objects.get(pk=station.pk)
        assert fetched.name == "WOODSHED OF BIG CABIN"
        assert fetched.state == "OK"
        assert abs(fetched.latitude - 36.5381) < 1e-4

    def test_str_representation(self):
        station = self._make_station()
        assert str(station) == "WOODSHED OF BIG CABIN - Big Cabin, OK"

    def test_geocode_source_defaults_to_precise(self):
        station = self._make_station()
        assert station.geocode_source == FuelStation.GEOCODE_SOURCE_PRECISE

    def test_geocode_source_city_centroid(self):
        station = self._make_station(
            geocode_source=FuelStation.GEOCODE_SOURCE_CITY_CENTROID
        )
        assert station.geocode_source == "city_centroid"

    @pytest.mark.parametrize(
        "opis_id, name",
        [
            (20, "PILOT TRAVEL CENTER #1243"),
            (20, "PILOT #1243"),
        ],
    )
    def test_duplicate_opis_id_allowed(self, opis_id, name):
        """opis_id repeats in the source CSV; both rows must be storable."""
        self._make_station(opis_id=opis_id, name=name)

    def test_both_duplicate_opis_id_rows_persist(self):
        self._make_station(opis_id=20, name="PILOT TRAVEL CENTER #1243")
        self._make_station(opis_id=20, name="PILOT #1243")
        assert FuelStation.objects.filter(opis_id=20).count() == 2
