from django.urls import path

from routing.views import health

urlpatterns = [
    path("health/", health, name="api-health"),
]
