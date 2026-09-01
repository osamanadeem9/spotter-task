from django.db import models


class FuelStation(models.Model):
    """
    - Represents a single fuel station loaded from the source CSV.
    - opis_id is not used as unique/PK because it repeats in the source data —
      same physical location listed under two brand names and pricing.
    - Geohash stores the values at a precision level of GEOHASH_PRECISION. The
      spatial index uses this column for O(1) corridor lookups at request time.
    - geocode_source distinguishes precise geocodes from city-centroid fallbacks,
      useful when debugging stations that appear far off-route.
    - We use a combination of "name", "city" and "state" to determine unique fuel stations.
    """

    GEOCODE_SOURCE_PRECISE = "precise"
    GEOCODE_SOURCE_CITY_CENTROID = "city_centroid"
    GEOCODE_SOURCE_CHOICES = [
        (GEOCODE_SOURCE_PRECISE, "Precise"),
        (GEOCODE_SOURCE_CITY_CENTROID, "City centroid"),
    ]

    opis_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.IntegerField()
    price = models.DecimalField(max_digits=6, decimal_places=4)
    latitude = models.FloatField()
    longitude = models.FloatField()
    geohash = models.CharField(max_length=12, db_index=True)
    geocode_source = models.CharField(
        max_length=20,
        choices=GEOCODE_SOURCE_CHOICES,
        default=GEOCODE_SOURCE_PRECISE,
    )

    class Meta:
        verbose_name = "Fuel Station"
        verbose_name_plural = "Fuel Stations"
        unique_together = [("name", "city", "state")]

    def __str__(self) -> str:
        return f"{self.name} - {self.city}, {self.state}"
