from django.contrib import admin

from stations.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "price", "geocode_source")
    list_filter = ("state", "geocode_source")
    search_fields = ("name", "city", "state")
    ordering = ("state", "city", "name")
