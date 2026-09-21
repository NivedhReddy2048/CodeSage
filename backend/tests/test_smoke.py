"""Phase 0 placeholder suite: proves the project boots and routes resolve.

Deliberately touches no database, so CI passes before Postgres is wired in.
"""

from django.test import Client
from django.urls import reverse


def test_health_endpoint_reports_ok():
    response = Client().get(reverse("health"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_schema_is_served():
    response = Client().get(reverse("schema"))

    assert response.status_code == 200
