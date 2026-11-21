"""Pruebas del capturador soberano Wayland/X11."""
from __future__ import annotations

import io
import json
import socket
from pathlib import Path

import pytest
from PIL import Image

from core import screen_capture as sc


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 24), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_geometry_for_window():
    window = {"at": [100, 200], "size": [800, 600]}
    assert sc._geometry_for(window) == "100,200 800x600"


def test_find_window_scores_title_and_class(monkeypatch):
    windows = [
        {"address": "0x1", "title": "Terminal", "class": "foot", "initial_class": "foot"},
        {"address": "0x2", "title": "Telegram Desktop", "class": "telegram", "initial_class": "telegram"},
    ]
    monkeypatch.setattr(sc, "list_windows", lambda: windows)
    assert sc.find_window("telegram")["address"] == "0x2"
    assert sc.find_window("TERM")["address"] == "0x1"
    assert sc.find_window("no-existe") is None


def test_session_env_detects_wayland_socket(tmp_path, monkeypatch):
    runtime = tmp_path / "run"
    runtime.mkdir()
    sock_path = runtime / "wayland-7"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(sock_path))
    try:
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
        env = sc.session_env()
        assert env["WAYLAND_DISPLAY"] == "wayland-7"
        assert env["XDG_RUNTIME_DIR"] == str(runtime)
    finally:
        sock.close()


def test_capture_uses_grim_and_converts_to_jpeg(monkeypatch):
    monkeypatch.setattr(sc, "is_locked", lambda: False)
    monkeypatch.setattr(sc, "_grim_available", lambda: True)
    monkeypatch.setattr(
        sc,
        "_capture_png",
        lambda region=None, window=None: (_png_bytes(), "grim"),
    )
    raw, meta = sc.capture(fmt="jpeg", max_width=20, quality=70)
    assert raw[:2] == b"\xff\xd8"
    assert meta["method"] == "grim"
    assert meta["format"] == "jpeg"
    assert meta["width"] == 20


def test_capture_refuses_locked_screen(monkeypatch):
    monkeypatch.setattr(sc, "is_locked", lambda: True)
    with pytest.raises(RuntimeError, match="bloqueada"):
        sc.capture()


def test_list_windows_parses_hyprctl(monkeypatch):
    payload = [
        {
            "address": "0xabc",
            "mapped": True,
            "hidden": False,
            "at": [10, 20],
            "size": [640, 480],
            "class": "foot",
            "title": "shell",
            "initialClass": "foot",
            "workspace": {"name": "1"},
        },
        {
            "address": "0xdef",
            "mapped": False,
            "hidden": False,
            "at": [0, 0],
            "size": [10, 10],
            "class": "ghost",
            "title": "oculta",
        },
    ]
    monkeypatch.setattr(sc, "_hypr_json", lambda args: payload)
    windows = sc.list_windows()
    assert len(windows) == 1
    assert windows[0]["title"] == "shell"
    assert windows[0]["size"] == [640, 480]
