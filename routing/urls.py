from django.urls import path

from routing.views import HealthView, RouteView, StationsView

urlpatterns = [
    path("health/", HealthView.as_view(), name="api-health"),
    path("route/", RouteView.as_view(), name="api-route"),
    path("stations/", StationsView.as_view(), name="api-stations"),
]
