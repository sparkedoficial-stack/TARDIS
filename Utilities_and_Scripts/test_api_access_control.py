"""
Regresion: control de acceso del servidor FastAPI.

- Las APIs sensibles (admin de usuarios, sandbox, camaras, sensores) eran publicas:
  un equipo de la red local podia darse de alta como autorizado.
- Una peticion reenviada por un tunel llega desde REDACTED_IP y se trataba como local.
"""
import pytest
from fastapi.testclient import TestClient

from server.api import app

SENSITIVE = [
    "/api/admin/users",
    "/api/admin/users/devices",
    "/api/sandbox/status",
    "/api/terminal_cameras/list",
    "/api/sensors/individuals",
    "/api/chinese_api/status",
    "/api/pocket/status",
    "/openapi.json",
    "/offline_chat_vault.html",
]


@pytest.fixture
def remote():
    return TestClient(app, client=("REDACTED_IP", 50000))


@pytest.fixture
def local():
    return TestClient(app, client=("REDACTED_IP", 50000))


@pytest.mark.parametrize("path", SENSITIVE)
def test_remote_without_token_denied(remote, path):
    assert remote.get(path).status_code == 401


@pytest.mark.parametrize("path", ["/api/pocket/ota/deploy", "/api/admin/users"])
def test_remote_post_without_token_denied(remote, path):
    assert remote.post(path, json={}).status_code == 401


@pytest.mark.parametrize("hdr", ["cf-connecting-ip", "x-forwarded-for", "x-real-ip"])
def test_proxied_loopback_is_not_local(local, hdr):
    r = local.get("/api/admin/users", headers={hdr: "REDACTED_IP"})
    assert r.status_code == 401


def test_health_and_ui_shell_remain_public(remote):
    assert remote.get("/health").status_code == 200
    assert remote.get("/").status_code == 200


def test_true_loopback_still_allowed(local):
    assert local.get("/api/pocket/status").status_code != 401
