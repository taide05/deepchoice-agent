"""Tests for optional API-key auth + in-memory rate limiting."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deepchoice.server.security import ApiSecurityMiddleware


def _client(**middleware_kwargs) -> TestClient:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/research/x/status")
    def status():
        return {"status": "running"}

    @app.post("/research")
    def research():
        return {"status": "started"}

    app.add_middleware(ApiSecurityMiddleware, **middleware_kwargs)
    return TestClient(app)


def test_auth_and_rate_limit_are_disabled_by_default():
    client = _client(api_key="", rate_limit_per_minute=0)
    assert client.post("/research").status_code == 200
    assert client.get("/research/x/status").status_code == 200


def test_health_stays_public_when_auth_enabled():
    client = _client(api_key="secret")
    assert client.get("/health").status_code == 200


def test_api_key_is_required_when_configured():
    client = _client(api_key="secret")
    assert client.post("/research").status_code == 401
    assert client.post("/research", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/research", headers={"X-API-Key": "secret"}).status_code == 200
    # reads are protected too (task id in the path is not a secret)
    assert client.get("/research/x/status").status_code == 401
    assert client.get("/research/x/status", headers={"X-API-Key": "secret"}).status_code == 200


def test_rate_limit_only_affects_mutating_requests():
    client = _client(api_key="", rate_limit_per_minute=2)
    assert client.post("/research", headers={"X-API-Key": "k"}).status_code == 200
    assert client.post("/research", headers={"X-API-Key": "k"}).status_code == 200
    assert client.post("/research", headers={"X-API-Key": "k"}).status_code == 429
    # reads are not rate limited
    assert client.get("/research/x/status").status_code == 200


def test_rate_limit_buckets_are_per_api_key():
    client = _client(api_key="", rate_limit_per_minute=1)
    assert client.post("/research", headers={"X-API-Key": "one"}).status_code == 200
    assert client.post("/research", headers={"X-API-Key": "one"}).status_code == 429
    assert client.post("/research", headers={"X-API-Key": "two"}).status_code == 200


def test_invalid_rate_limit_value_falls_back_to_disabled():
    client = _client(api_key="", rate_limit_per_minute=-5)
    assert client.post("/research").status_code == 200
    assert client.post("/research").status_code == 200
