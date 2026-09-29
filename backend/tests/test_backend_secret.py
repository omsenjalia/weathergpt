"""Clients connect only when they send the BACKEND_SECRET the server has (X-Backend-Secret)."""

from __future__ import annotations

import pytest

from weathergpt.config import reset_settings


@pytest.fixture
def secret(monkeypatch) -> str:
    monkeypatch.setenv("BACKEND_SECRET", "shared-s3cret")
    reset_settings()
    return "shared-s3cret"


def test_without_a_server_secret_everything_stays_open(client):
    assert client.get("/v2/weather/catalog").status_code == 200


def test_wrong_or_missing_secret_is_refused(client, secret):
    for headers in ({}, {"X-Backend-Secret": "nope"}, {"X-Backend-Secret": ""}):
        r = client.get("/v2/weather/catalog", headers=headers)
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "backend_secret_mismatch"
        assert r.headers["access-control-allow-origin"] == "*"  # the app can read the reason
    r = client.post("/chat", json={"message": "hi"}, headers={"X-Backend-Secret": "shared-s3cret-extra"})
    assert r.status_code == 401


def test_matching_secret_connects(client, secret):
    r = client.get("/v2/weather/catalog", headers={"X-Backend-Secret": secret})
    assert r.status_code == 200 and r.json()["providers"]


def test_health_root_and_cors_preflight_stay_open(client, secret):
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    r = client.options("/chat", headers={"Origin": "https://example.org", "Access-Control-Request-Method": "POST",
                                        "Access-Control-Request-Headers": "x-backend-secret,content-type"})
    assert r.status_code == 200 and "x-backend-secret" in r.headers["access-control-allow-headers"].lower()


def test_admin_routes_need_both_secrets(client, secret, admin):
    assert client.get("/dev/imd/probe", headers=admin).status_code == 401
    r = client.get("/dev/imd/probe", headers={**admin, "X-Backend-Secret": secret})
    assert r.status_code == 200
