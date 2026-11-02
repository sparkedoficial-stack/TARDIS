#!/usr/bin/env python3
"""
Pruebas de la Bóveda de Peticiones Soberanas y del Historial Unificado.
Ejecutar:  python3 -m pytest -q .ftl/test_chat_sovereign.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

FTL_DIR = Path(__file__).resolve().parent
if str(FTL_DIR) not in sys.path:
    sys.path.insert(0, str(FTL_DIR))

import chat_history as history  # noqa: E402
import chat_vault as vault  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    base = tmp_path / "composer"
    monkeypatch.setattr(vault, "CHAT_DIR", tmp_path)
    monkeypatch.setattr(vault, "VAULT_DIR", base)
    monkeypatch.setattr(vault, "LOCKS_DIR", base / "locks")
    monkeypatch.setattr(vault, "ARCHIVE_DIR", base / "archive")
    monkeypatch.setattr(vault, "JOURNAL_FILE", base / "journal.jsonl")
    monkeypatch.setattr(vault, "GATE_FILE", base / "gate.json")
    monkeypatch.setattr(vault, "MUTEX_FILE", base / ".mutex")
    yield


# ---------------------------------------------------------------------------
# Bóveda: exclusividad y ciclo de vida
# ---------------------------------------------------------------------------
def test_open_heartbeat_release():
    draft = vault.acquire("ftlchat_test", client_id="web", text="hola")
    assert draft["text"] == "hola"
    assert draft["token"]
    assert vault.should_defer_updates() is True

    hb = vault.heartbeat(draft["draft_id"], draft["token"], text="hola mundo", revision=0)
    assert hb["text"] == "hola mundo"
    assert hb["revision"] == 1
    assert hb["checksum"] == vault.checksum("hola mundo")

    closed = vault.release(draft["draft_id"], draft["token"])
    assert closed["state"] == "released"
    assert vault.should_defer_updates() is False


def test_second_client_is_locked_out():
    first = vault.acquire("ftlchat_test", client_id="tab-1", text="secreto")
    with pytest.raises(vault.VaultLocked) as exc:
        vault.acquire("ftlchat_test", client_id="tab-2", text="intruso")
    assert exc.value.status == 423
    assert exc.value.extra["active"]["draft_id"] == first["draft_id"]


def test_takeover_supersedes_previous_vault():
    first = vault.acquire("ftlchat_test", client_id="tab-1", text="viejo")
    second = vault.acquire("ftlchat_test", client_id="tab-2", text="nuevo", takeover=True)
    assert second["draft_id"] != first["draft_id"]
    archived = json.loads((vault.ARCHIVE_DIR / f"{first['draft_id']}.json").read_text())
    assert archived["state"] == "superseded"


def test_wrong_token_cannot_touch_vault():
    draft = vault.acquire("ftlchat_test", text="intacto")
    with pytest.raises(vault.VaultForbidden):
        vault.heartbeat(draft["draft_id"], "token-falso", text="secuestrado")
    stored = json.loads((vault.LOCKS_DIR / f"{draft['draft_id']}.json").read_text())
    assert stored["text"] == "intacto"


def test_revision_conflict_blocks_external_edit():
    draft = vault.acquire("ftlchat_test", text="original")
    vault.heartbeat(draft["draft_id"], draft["token"], text="original v2", revision=0)
    with pytest.raises(vault.VaultConflict) as exc:
        vault.heartbeat(draft["draft_id"], draft["token"], text="alterado", revision=0)
    assert exc.value.extra["authoritative"]["text"] == "original v2"
    stored = json.loads((vault.LOCKS_DIR / f"{draft['draft_id']}.json").read_text())
    assert stored["text"] == "original v2"


def test_send_requires_matching_text_and_revision():
    draft = vault.acquire("ftlchat_test", text="petición legítima")
    with pytest.raises(vault.VaultConflict):
        vault.claim_for_send(draft["draft_id"], draft["token"], revision=0, text="petición inyectada")
    sealed = vault.claim_for_send(draft["draft_id"], draft["token"], revision=0, text="petición legítima")
    assert sealed["state"] == "sending"
    vault.attach_run(draft["draft_id"], "run_test")
    sent = vault.consume(draft["draft_id"], run_id="run_test")
    assert sent["state"] == "sent"
    assert not (vault.LOCKS_DIR / f"{draft['draft_id']}.json").exists()


def test_expired_vault_is_archived_and_recoverable():
    draft = vault.acquire("ftlchat_test", text="borrador huérfano", ttl=0.01)
    time.sleep(0.05)
    assert vault.should_defer_updates() is False
    recovered = vault.recover("ftlchat_test")
    assert any(d["text"] == "borrador huérfano" for d in recovered)


def test_gate_file_is_written_for_updaters():
    draft = vault.acquire("ftlchat_test", text="no me interrumpas")
    gate = json.loads(vault.GATE_FILE.read_text())
    assert gate["defer_updates"] is True
    assert gate["active"] == 1
    vault.consume(draft["draft_id"], run_id="run_x")
    gate = json.loads(vault.GATE_FILE.read_text())
    assert gate["defer_updates"] is False


# ---------------------------------------------------------------------------
# Historial unificado
# ---------------------------------------------------------------------------
def test_prompt_history_parser(tmp_path):
    path = tmp_path / "history"
    path.write_text(
        "# 2026-10-01 10:00:00.000000\n+primera petición\n"
        "# 2026-10-02 11:30:00.000000\n+segunda petición\ncon continuación\n",
        encoding="utf-8",
    )
    rows = history._parse_prompt_history(path, "consola")
    assert len(rows) == 2
    assert rows[0]["text"] == "primera petición"
    assert "con continuación" in rows[1]["text"]
    assert rows[1]["source"] == "terminal"


def test_unified_merges_all_sources(monkeypatch):
    fixed = [
        history._entry(id_="chat:1", ts=100.0, source="chat", channel="chat", role="user",
                       text="hola desde el chat", session_id="ftlchat_x"),
        history._entry(id_="terminal:1", ts=200.0, source="terminal", channel="consola",
                       role="user", text="hola desde la terminal"),
        history._entry(id_="vault:1", ts=300.0, source="vault", channel="bóveda",
                       role="user", text="petición blindada"),
    ]
    monkeypatch.setattr(history, "_chat_entries", lambda q: [fixed[0]])
    monkeypatch.setattr(history, "_parse_prompt_history", lambda p, c: [fixed[1]] if c == "consola" else [])
    monkeypatch.setattr(history, "_tardis_entries", lambda: [])
    monkeypatch.setattr(history, "_vault_entries", lambda: [fixed[2]])

    data = history.unified(limit=10)
    assert data["total"] == 3
    assert [r["source"] for r in data["entries"]] == ["vault", "terminal", "chat"]
    assert data["counts"] == {"chat": 1, "terminal": 1, "vault": 1}

    filtered = history.unified("terminal", limit=10)
    assert filtered["total"] == 1
    assert filtered["entries"][0]["source"] == "terminal"


def test_history_export_markdown(tmp_path, monkeypatch):
    entry = history._entry(id_="chat:1", ts=100.0, source="chat", channel="chat",
                           role="user", text="exporta esto")
    monkeypatch.setattr(history, "_chat_entries", lambda q: [entry])
    monkeypatch.setattr(history, "_parse_prompt_history", lambda p, c: [])
    monkeypatch.setattr(history, "_tardis_entries", lambda: [])
    monkeypatch.setattr(history, "_vault_entries", lambda: [])
    path = history.export_markdown(tmp_path / "hist.md")
    text = path.read_text(encoding="utf-8")
    assert "exporta esto" in text
    assert "Historial Unificado" in text


# ---------------------------------------------------------------------------
# Compuerta de actualizaciones
# ---------------------------------------------------------------------------
def test_update_guard_defers_while_vault_open():
    import ftl_update_guard as guard

    snap = guard.snapshot()
    assert snap["busy"] is False
    draft = vault.acquire("ftlchat_test", text="actualización en pausa")
    snap = guard.snapshot()
    assert snap["busy"] is True
    assert snap["vault"]["active"] == 1
    vault.consume(draft["draft_id"], run_id="run_y")
    assert guard.snapshot()["busy"] is False


def test_update_guard_wait_respects_timeout():
    import ftl_update_guard as guard

    draft = vault.acquire("ftlchat_test", text="bloqueo breve")
    snap = guard.wait_until_clear(0.2, quiet=True)
    assert snap["busy"] is True
    assert snap["timed_out"] is True
    vault.release(draft["draft_id"], draft["token"], keep=False)
