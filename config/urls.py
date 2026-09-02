from django.contrib import admin
from django.urls import include, path

from frontend.views import MapView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("routing.urls")),
    path("", MapView.as_view(), name="map"),
]
