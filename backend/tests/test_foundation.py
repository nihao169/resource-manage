from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.core.config import Settings
from app.core.resources import make_resources
from app.integrations.minio_client import MinioAdapter
from app.main import create_app

def fake_resources():
    engine, storage = MagicMock(), MagicMock()
    resources = SimpleNamespace(engine=engine, storage=storage)
    resources.close = lambda: (storage.close(), engine.dispose())
    return resources

def test_live_and_request_identifier(monkeypatch):
    resources = fake_resources()
    app = create_app(Settings(app_env="test"), lambda _: resources)
    with TestClient(app) as client:
        response = client.get("/api/health/live", headers={"X-Request-ID": "not-trusted"})
        assert response.status_code == 200
        UUID(response.json()["request_id"])
        assert response.headers["X-Request-ID"] == response.json()["request_id"]
        assert response.json()["data"] == {"status": "live"}
        resources.engine.connect.assert_not_called()
    resources.storage.close.assert_called_once()
    resources.engine.dispose.assert_called_once()

def test_business_routes_are_protected_and_production_docs_are_hidden():
    resources = fake_resources()
    with TestClient(create_app(Settings(app_env="production"), lambda _: resources)) as client:
        result = client.get("/api/files")
        assert result.status_code == 401
        assert result.json()["error"]["code"] == "UNAUTHENTICATED"
        result = client.get("/api/auth/login")
        assert result.status_code == 405
        for route in ("/api/docs", "/api/openapi.json"):
            result = client.get(route)
            assert result.status_code == 404
            assert result.json()["error"]["code"] == "NOT_FOUND"

@pytest.mark.parametrize("failure", ["database", "storage", None])
def test_readiness(monkeypatch, failure):
    resources = fake_resources()
    def check(_):
        if failure == "database":
            raise RuntimeError("password=must-not-leak")
    monkeypatch.setattr("app.services.health_service.check_database", check)
    if failure == "storage":
        resources.storage.check_buckets.side_effect = RuntimeError("secret=must-not-leak")
    with TestClient(create_app(Settings(app_env="test"), lambda _: resources)) as client:
        response = client.get("/api/health/ready")
        assert response.status_code == (200 if failure is None else 503)
        assert "must-not-leak" not in response.text
        if failure:
            expected = "DATABASE_UNAVAILABLE" if failure == "database" else "STORAGE_UNAVAILABLE"
            assert response.json()["error"]["code"] == expected

def test_configuration_and_secret(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("test-value\n", encoding="utf-8")
    assert Settings.read_secret(secret) == "test-value"
    assert "test-value" not in repr(Settings(database_password_file=secret))
    with pytest.raises(ValidationError):
        Settings(database_port=0)

def test_stream_released_on_failure():
    adapter = object.__new__(MinioAdapter)
    adapter.client = MagicMock()
    response = adapter.client.get_object.return_value
    with pytest.raises(RuntimeError):
        with adapter.open_stream("contents", "validated-key"):
            raise RuntimeError("client disconnected")
    response.close.assert_called_once()
    response.release_conn.assert_called_once()

def test_stream_released_when_close_fails():
    adapter = object.__new__(MinioAdapter)
    adapter.client = MagicMock()
    response = adapter.client.get_object.return_value
    response.close.side_effect = RuntimeError("close failed")
    with pytest.raises(RuntimeError):
        with adapter.open_stream("contents", "validated-key"):
            pass
    response.release_conn.assert_called_once()

def test_storage_constructor_failure_clears_pool(monkeypatch):
    pool = MagicMock()
    monkeypatch.setattr("app.integrations.minio_client.PoolManager", lambda **_: pool)
    monkeypatch.setattr(Settings, "read_secret", staticmethod(lambda _: (_ for _ in ()).throw(ValueError())))
    with pytest.raises(ValueError):
        MinioAdapter(Settings())
    pool.clear.assert_called_once()

def test_partial_resource_initialization_releases_engine(monkeypatch):
    engine = MagicMock()
    monkeypatch.setattr("app.core.resources.create_database_engine", lambda _: engine)
    def broken(_):
        raise RuntimeError("storage config failure")
    monkeypatch.setattr("app.core.resources.MinioAdapter", broken)
    with pytest.raises(RuntimeError):
        make_resources(Settings())
    engine.dispose.assert_called_once()
