from rest_framework import serializers

from stations.models import FuelStation


class RouteRequestSerializer(serializers.Serializer):
    """Serializes/Validates route endpoint request body."""

    start = serializers.CharField(max_length=255)
    finish = serializers.CharField(max_length=255)


class FuelStopSerializer(serializers.Serializer):
    """Read-only response shape for a single chosen fuel stop."""

    name = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    price_per_gallon = serializers.FloatField()
    distance_from_start_miles = serializers.FloatField()
    gallons_purchased = serializers.FloatField()
    leg_cost = serializers.FloatField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class RouteSerializer(serializers.Serializer):
    """Route metadata nested inside the response envelope."""

    geometry = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField())
    )
    total_distance_miles = serializers.FloatField()
    total_gallons = serializers.FloatField()


class RouteResponseSerializer(serializers.Serializer):
    """Top-level POST /api/v1/route/ response envelope."""

    route = RouteSerializer()
    fuel_stops = FuelStopSerializer(many=True)
    total_fuel_cost = serializers.FloatField()


class StationListSerializer(serializers.ModelSerializer):
    """
    - Lean projection of FuelStation for the GET /api/v1/stations/ list endpoint.
    - Only exposes fields the map markers and popups need; omits internal fields
      like geohash, rack_id, opis_id that have no front-end use.
    """

    class Meta:
        model = FuelStation
        fields = ["name", "city", "state", "price", "latitude", "longitude"]
