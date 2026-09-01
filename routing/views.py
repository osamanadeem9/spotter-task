import json

from django.http import HttpRequest, HttpResponse


def health(request: HttpRequest) -> HttpResponse:
    """
    - Readiness probe: confirms the app process is alive and responding.
    - Returns 200 so load balancers and Docker health checks pass immediately.
    """
    return HttpResponse(json.dumps({"status": "ok"}), content_type="application/json")
