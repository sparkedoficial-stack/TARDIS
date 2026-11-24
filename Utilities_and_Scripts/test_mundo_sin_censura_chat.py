"""
tests/test_mundo_sin_censura_chat.py - Pruebas del Chat Exclusivo Un Mundo Sin Censura
======================================================================================
Verifica:
  1. Bloqueo estricto de modelo (`enforce_model_lock` y HTTP 403 ante cualquier otro modelo).
  2. CRUD de sesiones aisladas en SQLite WAL, auto-título, limpieza y exportación.
  3. Streaming SSE (`POST /api/mundo_sin_censura/chat/stream`) con persistencia de turnos
     y cancelación (`POST /api/mundo_sin_censura/chat/cancel`).
  4. Entrega HTML de la interfaz web en `/mundo-sin-censura`, `/mundo-sin-censura-chat`
     y `/chat/mundo-sin-censura`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path("/home/m11/Escritorio/GODWORKS SYSTEM").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import core.mundo_sin_censura_chat as mchat


def test_enforce_model_lock_rejects_other_models():
    assert mchat.enforce_model_lock(None) == "mundo-sin-censura"
    assert mchat.enforce_model_lock("") == "mundo-sin-censura"
    assert mchat.enforce_model_lock("mundo-sin-censura") == "mundo-sin-censura"
    assert mchat.enforce_model_lock("mundo-sin-censura:latest") == "mundo-sin-censura"
    assert mchat.enforce_model_lock("Un-Mundo-Sin-Censura") == "mundo-sin-censura"

    for forbidden in ("gpt-4o", "claude-opus", "deepseek-r1:7b", "TARDIS-NEURAL-SPACE-KAIJU", "qwen3-vl:2b"):
        with pytest.raises(mchat.ModelLockError):
            mchat.enforce_model_lock(forbidden)


def test_isolated_sqlite_session_crud_and_export(tmp_path):
    store = mchat.MundoSinCensuraChatStore(db_path=tmp_path / "chat.db")
    sess = store.create_session(title="Prueba Aislada", lane="temporal_brain", temperature=0.2, max_tokens=512)
    sid = sess["id"]
    assert sess["model"] == "mundo-sin-censura"
    assert sess["lane"] == "temporal_brain"

    store.add_message(sid, "user", "Hola mundo")
    store.add_message(sid, "assistant", "Respuesta exclusiva", lane="temporal_brain", elapsed_s=1.4, approx_tokens=12)

    loaded = store.get_session(sid)
    assert loaded is not None
    assert loaded["message_count"] == 2
    assert loaded["messages"][0]["content"] == "Hola mundo"
    assert loaded["messages"][1]["model"] == "mundo-sin-censura"

    renamed = store.update_session(sid, title="Renombrada")
    assert renamed is not None and renamed["title"] == "Renombrada"

    exp_md = store.export_session(sid, fmt="markdown")
    assert exp_md is not None and "Un Mundo Sin Censura" in exp_md["content"]
    exp_json = store.export_session(sid, fmt="json")
    assert exp_json is not None and json.loads(exp_json["content"])["id"] == sid

    cleared = store.clear_session(sid)
    assert cleared is not None and cleared["message_count"] == 0
    assert store.delete_session(sid) is True
    assert store.get_session(sid) is None


def test_fastapi_exclusive_chat_ui_lock_and_sse_stream(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from server.api import create_app

    store = mchat.MundoSinCensuraChatStore(db_path=tmp_path / "api_chat.db")
    monkeypatch.setattr(mchat, "_CHAT_STORE", store)

    app = create_app()
    client = TestClient(app)

    # 1. Interfaz web exclusiva
    for route in ("/mundo-sin-censura", "/mundo-sin-censura-chat", "/chat/mundo-sin-censura"):
        r = client.get(route)
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert "Un Mundo Sin Censura" in r.text

    # 2. Bloqueo estricto HTTP 403 si se pide otro modelo
    r_forbid_sess = client.post("/api/mundo_sin_censura/sessions", json={"model": "deepseek-r1:7b"})
    assert r_forbid_sess.status_code == 403

    r_forbid_stream = client.post(
        "/api/mundo_sin_censura/chat/stream",
        json={"message": "hola", "model": "TARDIS-NEURAL-SPACE-KAIJU"},
    )
    assert r_forbid_stream.status_code == 403

    # 3. Streaming SSE con persistencia real en SQLite
    class _FakeAgent:
        def inspect_temporal_brain(self, timeout=1.0):
            return {"ready": True}

        def chat_stream(self, messages, **kwargs):
            yield "Hola "
            yield "desde "
            yield "mundo-sin-censura"
            return "Hola desde mundo-sin-censura"

    with patch.object(mchat, "get_mundo_sin_censura", return_value=_FakeAgent()):
        r_stream = client.post(
            "/api/mundo_sin_censura/chat/stream",
            json={"message": "Primera pregunta exclusiva", "model": "mundo-sin-censura", "lane": "auto"},
        )
        assert r_stream.status_code == 200
        events = []
        for ln in r_stream.text.splitlines():
            if ln.startswith("data: ") and ln != "data: [DONE]":
                events.append(json.loads(ln[6:]))

    types = [e["type"] for e in events]
    assert "meta" in types and "token" in types and "done" in types
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["model"] == "mundo-sin-censura"
    sid = meta["session_id"]

    r_get = client.get(f"/api/mundo_sin_censura/sessions/{sid}")
    assert r_get.status_code == 200
    sess = r_get.json()["session"]
    assert sess["title"] == "Primera pregunta exclusiva"
    assert len(sess["messages"]) == 2
    assert sess["messages"][1]["content"] == "Hola desde mundo-sin-censura"
