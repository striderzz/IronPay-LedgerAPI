import pytest

pytestmark = pytest.mark.integration


def test_health_reports_postgres_and_redis(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"postgres": "ok", "redis": "ok"}}


def test_metrics_endpoint_exposes_prometheus_text(client):
    client.get("/health")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "http_requests_total" in r.text
