"""
- MapView renders the Leaflet map page. All data fetching is done client-side
  via the API endpoints. This view only serves the template.
"""

from django.shortcuts import render
from django.views import View


class MapView(View):
    """
    - Serves the Leaflet map page at GET /.
    - The template itself calls POST /api/v1/route/ and GET /api/v1/stations/
      via JavaScript; no server-side data fetching is needed here.
    """

    def get(self, request):
        return render(request, "frontend/map.html")
