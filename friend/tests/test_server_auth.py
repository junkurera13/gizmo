from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from gizmo_friend.server import app_factory


def test_cloud_requires_device_token(tmp_path, monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "test")
    with pytest.raises(RuntimeError, match="GIZMO_DEVICE_TOKEN"):
        app_factory(tmp_path)


def test_cloud_rejects_unauthenticated_clients(tmp_path, monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "test")
    monkeypatch.setenv("GIZMO_DEVICE_TOKEN", "test-device-token")
    with TestClient(app_factory(tmp_path)) as client:
        assert client.get("/health").status_code == 200
        assert "name" not in client.get("/health").json()
        assert client.get("/api/pages").status_code == 401
        assert client.get("/").status_code == 401
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass
        headers = {"Authorization": "Bearer test-device-token"}
        assert client.get("/api/pages", headers=headers).status_code == 200
        with client.websocket_connect("/ws", headers=headers) as socket:
            assert socket.receive_json()["type"] == "hello"


def test_local_without_token_still_works(tmp_path):
    with TestClient(app_factory(tmp_path)) as client:
        with client.websocket_connect("/ws") as socket:
            assert socket.receive_json()["type"] == "hello"
