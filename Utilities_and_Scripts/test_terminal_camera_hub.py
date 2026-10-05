"""
tests/test_terminal_camera_hub.py - Pruebas Unitarias del Hub de Cámaras de Terminales y Streaming MJPEG
Verifica:
1. Registro de frames (Base64 JPEG) provenientes de terminales cliente (navegadores, móviles, laptops).
2. Cálculo de FPS, resolución, User-Agent, IP del cliente y telemetría biométrica.
3. Cámara local del host TARDIS y generación de frames sintéticos/reales.
4. Generador continuo multipart/x-mixed-replace (MJPEG) para streaming sin WebRTC/STUN.
5. Endpoints REST (/api/terminal_cameras/feed, /list, /snapshot/{id}, /stream/{id}).
"""

import base64
import time
import pytest
from starlette.testclient import TestClient

from core.terminal_camera_hub import TerminalCameraHub, get_terminal_camera_hub, classify_network_origin
from server.api import app

client = TestClient(app)

# Frame JPEG mínimo sintético de 1x1 píxel
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////"
    "////////////////////////////////////////////////////wgALCAABAAEBAREA"
    "/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
)


def test_hub_frame_registration():
    hub = TerminalCameraHub()
    terminal_id = "test_terminal_phone_01"
    terminal_name = "iPhone 15 Pro - Alpha"

    success = hub.register_frame(
        terminal_id=terminal_id,
        terminal_name=terminal_name,
        device_type="mobile_safari",
        image_data=f"data:image/jpeg;base64,{TINY_JPEG_B64}",
        client_ip="REDACTED_IP",
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        resolution="640x480",
        biometrics={"emotion": "neutral", "attention": 0.88}
    )

    assert success["ok"] is True

    terminals = hub.get_terminals_list()
    found = [t for t in terminals if t["terminal_id"] == terminal_id]
    assert len(found) == 1
    t_info = found[0]
    assert t_info["terminal_name"] == terminal_name
    assert t_info["is_online"] is True
    assert t_info["resolution"] == "640x480"
    assert t_info["biometrics"]["emotion"] == "neutral"

    # Verificar snapshot
    snapshot = hub.get_latest_snapshot(terminal_id)
    assert snapshot is not None
    assert len(snapshot) > 10
    assert snapshot.startswith(b"\xff\xd8")  # Encabezado JPEG


def test_hub_mjpeg_stream_generator():
    hub = TerminalCameraHub()
    terminal_id = "test_terminal_laptop_02"
    hub.register_frame(
        terminal_id=terminal_id,
        terminal_name="MacBook M3 - Beta",
        device_type="desktop_chrome",
        image_data=TINY_JPEG_B64,
        client_ip="REDACTED_IP",
        resolution="1280x720"
    )

    gen = hub.mjpeg_generator(terminal_id, fps=10)
    # Extraer el primer frame del generador
    first_chunk = next(gen)
    assert b"--frame\r\n" in first_chunk
    assert b"Content-Type: image/jpeg\r\n" in first_chunk
    assert b"\xff\xd8" in first_chunk


def test_api_terminal_cameras_endpoints():
    test_id = "api_client_terminal_03"
    payload = {
        "terminal_id": test_id,
        "terminal_name": "Terminal Web Móvil",
        "device_type": "android_chrome",
        "image_base64": TINY_JPEG_B64,
        "resolution": "480x360",
        "biometrics": {"emotion": "focused", "confidence": 0.94},
        "client_ip": "REDACTED_IP",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8)"
    }

    # 1. POST feed
    resp_feed = client.post("/api/terminal_cameras/feed", json=payload)
    assert resp_feed.status_code == 200
    feed_data = resp_feed.json()
    assert feed_data["ok"] is True
    assert feed_data["terminal_id"] == test_id

    # 2. GET list
    resp_list = client.get("/api/terminal_cameras/list")
    assert resp_list.status_code == 200
    list_data = resp_list.json()
    assert list_data["ok"] is True
    assert list_data["count"] >= 1
    ids = [t["terminal_id"] for t in list_data["terminals"]]
    assert test_id in ids

    # 3. GET snapshot
    resp_snap = client.get(f"/api/terminal_cameras/snapshot/{test_id}")
    assert resp_snap.status_code == 200
    assert resp_snap.headers["content-type"] == "image/jpeg"
    assert resp_snap.content.startswith(b"\xff\xd8")

    # 4. GET non-existent snapshot
    resp_404 = client.get("/api/terminal_cameras/snapshot/terminal_inexistente_999999")
    assert resp_404.status_code == 404

    # 5. GET stream (verificar cabeceras iniciales y chunks)
    with client.stream("GET", f"/api/terminal_cameras/stream/{test_id}?duration=0.05") as stream_resp:
        assert stream_resp.status_code == 200
        assert "multipart/x-mixed-replace" in stream_resp.headers["content-type"]
        for chunk in stream_resp.iter_raw():
            assert b"--frame" in chunk or len(chunk) > 0
            break


def test_classify_network_origin():
    # Host loopback
    assert classify_network_origin("REDACTED_IP") == "HOST"
    assert classify_network_origin("localhost") == "HOST"
    assert classify_network_origin("::1") == "HOST"
    assert classify_network_origin("") == "HOST"

    # Red Local (LAN)
    assert classify_network_origin("REDACTED_IP") == "LAN"
    assert classify_network_origin("REDACTED_IP") == "LAN"
    assert classify_network_origin("REDACTED_IP") == "LAN"
    assert classify_network_origin("REDACTED_IP") == "LAN"

    # Internet / Túnel público
    assert classify_network_origin("REDACTED_IP") == "INTERNET"
    assert classify_network_origin("REDACTED_IP") == "INTERNET"
    assert classify_network_origin("REDACTED_IP") == "INTERNET"
    assert classify_network_origin("invalid_address") == "INTERNET"


def test_hub_720p_and_bitrate_tracking():
    hub = TerminalCameraHub()
    terminal_id = "test_hd_terminal_720p"

    # Registrar frame con resolución 720p y bitrate 1000 kbps
    res = hub.register_frame(
        terminal_id=terminal_id,
        terminal_name="Galaxy Ultra - 720p Stream",
        device_type="mobile_android",
        image_data=TINY_JPEG_B64,
        client_ip="REDACTED_IP",
        resolution="1280x720",
        country="MX",
        bitrate_kbps=985.4
    )
    assert res["ok"] is True
    assert res["resolution"] == "1280x720"

    terminals = hub.get_terminals_list()
    entry = next((t for t in terminals if t["terminal_id"] == terminal_id), None)
    assert entry is not None
    assert entry["resolution"] == "1280x720"
    assert entry["origin"] == "INTERNET"
    assert entry["country"] == "MX"
    assert entry["target_bitrate_kbps"] == 1000
    assert entry["quality_profile"] == "720p HD @ 1000 kbps"
    assert entry["bitrate_kbps"] >= 0


def test_camera_capabilities_and_endpoint():
    hub = TerminalCameraHub.get_instance()
    caps = hub.get_camera_capabilities()
    assert caps["ok"] is True
    assert "1280x720" in caps["target_resolution"]
    assert caps["target_bitrate_kbps"] == 1000
    assert caps["primary_cognitive_motor"] == "huihui_ai/llama3.1-8b-instruct-abliterated"
    assert len(caps["capabilities"]) >= 6

    # Test REST endpoint
    resp = client.get("/api/terminal_cameras/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["target_bitrate_kbps"] == 1000
    assert any("720p" in c["name"] for c in data["capabilities"])
    assert any("Alertas" in c["name"] for c in data["capabilities"])


def test_api_cloudflare_internet_headers():
    test_id = "test_cf_tunnel_camera"
    payload = {
        "terminal_id": test_id,
        "terminal_name": "iPhone Remoto Internet",
        "device_type": "mobile_safari",
        "image_base64": TINY_JPEG_B64,
        "resolution": "1280x720",
        "bitrate_kbps": 1024.0
    }
    headers = {
        "cf-connecting-ip": "REDACTED_IP",
        "cf-ipcountry": "ES"
    }

    resp = client.post("/api/terminal_cameras/feed", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    # Verificar que /api/terminal_cameras/list detecta el cliente como INTERNET y país ES
    resp_list = client.get("/api/terminal_cameras/list")
    assert resp_list.status_code == 200
    terminals = resp_list.json()["terminals"]
    cf_t = next((t for t in terminals if t["terminal_id"] == test_id), None)
    assert cf_t is not None
    assert cf_t["origin"] == "INTERNET"
    assert cf_t["client_ip"] == "REDACTED_IP"
    assert cf_t["country"] == "ES"
    assert cf_t["resolution"] == "1280x720"


def test_hub_save_connected_snapshot():
    hub = TerminalCameraHub.get_instance()
    import base64
    raw_frame = base64.b64decode(TINY_JPEG_B64)
    term_id = "test_user_capture_terminal_99"

    res = hub.save_connected_snapshot(
        terminal_id=term_id,
        frame_bytes=raw_frame,
        terminal_name="iPhone 16 Pro Max",
        origin="INTERNET",
        client_ip="REDACTED_IP",
        country="MX",
        resolution="1280x720",
        biometrics={"primary": "focused"}
    )
    assert res["ok"] is True
    assert "filename" in res
    assert res["record"]["terminal_id"] == term_id

    # Comprobar que aparece en get_connected_snapshots()
    captures = hub.get_connected_snapshots(limit=10)
    assert len(captures) >= 1
    found = next((c for c in captures if c["terminal_id"] == term_id), None)
    assert found is not None
    assert found["origin"] == "INTERNET"
    assert found["country"] == "MX"


def test_api_capture_connected_endpoints():
    term_id = "api_client_auto_snap_01"
    payload = {
        "terminal_id": term_id,
        "terminal_name": "Terminal Web Laptop",
        "image_base64": TINY_JPEG_B64,
        "resolution": "1280x720",
        "biometrics": {"faces_count": 1, "primary": "happy"}
    }
    headers = {
        "cf-connecting-ip": "REDACTED_IP",
        "cf-ipcountry": "MX"
    }

    # 1. POST capture_connected
    resp_post = client.post("/api/terminal_cameras/capture_connected", json=payload, headers=headers)
    assert resp_post.status_code == 200
    data = resp_post.json()
    assert data["ok"] is True
    filename = data["filename"]

    # 2. GET captures list
    resp_list = client.get("/api/terminal_cameras/captures")
    assert resp_list.status_code == 200
    c_data = resp_list.json()
    assert c_data["ok"] is True
    assert c_data["count"] >= 1
    found = next((c for c in c_data["captures"] if c["terminal_id"] == term_id), None)
    assert found is not None
    assert found["filename"] == filename

    # 3. GET capture file
    resp_file = client.get(f"/api/terminal_cameras/captures/{filename}")
    assert resp_file.status_code == 200
    assert resp_file.headers["content-type"] == "image/jpeg"
    assert len(resp_file.content) > 0


