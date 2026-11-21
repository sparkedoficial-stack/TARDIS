"""
Pruebas de verificación para core/ftl_terminal_continuator.py (AGY · FTL · OpenCode).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import ftl_terminal_continuator as ftlc


def test_verify_all_terminals_live():
    cont = ftlc.get_ftl_terminal_continuator()
    rep = cont.verify_all_terminals()
    assert rep["ok"] is True, f"Verificación falló: {rep}"
    assert rep["checks"]["agy_zero_prompt_verified"] is True
    assert rep["checks"]["agy_interactive_path_uses_wrapper"] is True
    assert rep["checks"]["ftl_bypass_permissions_enabled"] is True
    assert rep["checks"]["ftl_continue_cli_executable"] is True
    assert rep["checks"]["opencode_wrapper_executable"] is True
    assert rep["checks"]["opencode_interactive_path_uses_wrapper"] is True
    assert rep["checks"]["opencode_config_skills_m11"] is True
    assert rep["checks"]["opencode_config_autonomous_permissions"] is True


def test_extract_user_task_and_probe_filter():
    wrapped = (
        "<USER_REQUEST>\n=== [LINEAMIENTOS SOBERANOS] ===\n"
        "[TAREA ACTUAL DEL ARQUITECTO]:\nCorrige todos los errores del sistema\n</USER_REQUEST>"
    )
    assert ftlc._extract_user_task(wrapped) == "Corrige todos los errores del sistema"
    assert ftlc._is_trivial_probe("Reply with only: OK_AUTONOMOUS") is True
    assert ftlc._is_trivial_probe(wrapped) is False


def test_scan_agy_and_opencode_and_reconcile_isolated(tmp_path, monkeypatch):
    brain_dir = tmp_path / "brain"
    presence_dir = tmp_path / "presence"
    convs_dir = tmp_path / "conversations"
    state_dir = tmp_path / "state"
    for d in (brain_dir, presence_dir, convs_dir, state_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Crear una conversación AGY inconclusa y otra terminada
    stalled_cid = "REDACTED_PHONE-1111-1111-REDACTED_PHONE"
    stalled_tr = brain_dir / stalled_cid / ".system_generated" / "logs" / "transcript.jsonl"
    stalled_tr.parent.mkdir(parents=True)
    stalled_tr.write_text(
        json.dumps({"step_index": 0, "type": "USER_INPUT", "status": "DONE", "content": "<USER_REQUEST>Repara el modulo principal de TARDIS</USER_REQUEST>"}) + "\n" +
        json.dumps({"step_index": 1, "type": "GENERIC", "status": "DONE", "content": "Output parcial"}) + "\n",
        encoding="utf-8",
    )
    done_cid = "REDACTED_PHONE-2222-2222-REDACTED_PHONE"
    done_tr = brain_dir / done_cid / ".system_generated" / "logs" / "transcript.jsonl"
    done_tr.parent.mkdir(parents=True)
    done_tr.write_text(
        json.dumps({"step_index": 0, "type": "USER_INPUT", "status": "DONE", "content": "<USER_REQUEST>Completa la auditoria final</USER_REQUEST>"}) + "\n" +
        json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "content": "Auditoria finalizada correctamente."}) + "\n",
        encoding="utf-8",
    )
    old_mtime = time.time() - 600
    for p in (stalled_tr, done_tr):
        import os
        os.utime(p, (old_mtime, old_mtime))

    # 2. Crear opencode.db simulada con una sesión fallida 429 y otra exitosa
    oc_db = tmp_path / "opencode.db"
    conn = sqlite3.connect(str(oc_db))
    conn.executescript("""
        CREATE TABLE session_v2 (
            id TEXT PRIMARY KEY, title TEXT, directory TEXT, model TEXT,
            idle_outcome TEXT, time_created INT, time_updated INT,
            time_busy INT, time_idle INT, time_suspended INT, resume_attempts INT
        );
        CREATE TABLE session_message (
            id TEXT PRIMARY KEY, session_id TEXT, time_created INT, data TEXT
        );
    """)
    t_old_ms = int((time.time() - 900) * 1000)
    conn.execute(
        "INSERT INTO session_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("ses_failed_1", "Tarea fallida 429", str(tmp_path), '{"id":"deepseek-v4.1-flash-free","providerID":"opencode","variant":"max"}',
         "failed", t_old_ms, t_old_ms, t_old_ms, t_old_ms, None, 0),
    )
    conn.execute(
        "INSERT INTO session_message VALUES (?,?,?,?)",
        ("m1", "ses_failed_1", t_old_ms, json.dumps({"text": "Implementa soporte completo de telemetria"})),
    )
    conn.execute(
        "INSERT INTO session_message VALUES (?,?,?,?)",
        ("m2", "ses_failed_1", t_old_ms + 1000, json.dumps({"outcome": "failed", "error": {"type": "provider.free-limit", "message": "Free usage limit reached"}})),
    )
    conn.execute(
        "INSERT INTO session_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("ses_ok_1", "Capturas Telegram", str(tmp_path), '{"id":"beam-free","providerID":"opencode"}',
         "succeeded", t_old_ms, t_old_ms, t_old_ms, t_old_ms, None, 0),
    )
    conn.execute(
        "INSERT INTO session_message VALUES (?,?,?,?)",
        ("m3", "ses_ok_1", t_old_ms, json.dumps({"text": "Permite recibir capturas en Telegram"})),
    )
    # Sesión fallida superada por ses_ok_1 (debe filtrarse como superseded)
    conn.execute(
        "INSERT INTO session_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("ses_failed_superseded", "Capturas Telegram fallo previo", str(tmp_path), '{"id":"glm-5.3-flash-free","providerID":"opencode"}',
         "failed", t_old_ms - 5000, t_old_ms - 4000, t_old_ms - 5000, t_old_ms - 4000, None, 0),
    )
    conn.execute(
        "INSERT INTO session_message VALUES (?,?,?,?)",
        ("m4", "ses_failed_superseded", t_old_ms - 5000, json.dumps({"text": "Permite recibir capturas en Telegram"})),
    )
    conn.execute(
        "INSERT INTO session_message VALUES (?,?,?,?)",
        ("m5", "ses_failed_superseded", t_old_ms - 4000, json.dumps({"outcome": "failed", "error": {"type": "provider.no-route"}})),
    )
    conn.commit()
    conn.close()

    # 3. Crear continuity_vault.db simulada con una fila reconciliable y otra pendiente
    cont_db = tmp_path / "continuity_vault.db"
    c2 = sqlite3.connect(str(cont_db))
    c2.execute("""
        CREATE TABLE request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, timestamp REAL,
            iso TEXT, source TEXT, prompt TEXT, plan_mode TEXT, model TEXT,
            status TEXT, progress_summary TEXT, artifacts_json TEXT, reboot_survived INT
        )
    """)
    c2.execute(
        "INSERT INTO request_log VALUES (1,'master_timeline',?,?, 'FTL', ?, 'deepseek', 'm', 'in_progress', 'Petición registrada', '[]', 0)",
        (time.time() - 900, "2026-11-20 20:00:00", "Permite recibir capturas en Telegram"),
    )
    c2.execute(
        "INSERT INTO request_log VALUES (2,'master_timeline',?,?, 'FTL', ?, 'gemini', 'm', 'in_progress', 'Petición registrada', '[]', 0)",
        (time.time() - 800, "2026-11-20 20:05:00", "Construye el puente de telemetria satelital"),
    )
    c2.commit()
    c2.close()

    monkeypatch.setattr(ftlc, "AGY_BRAIN_DIR", brain_dir)
    monkeypatch.setattr(ftlc, "AGY_PRESENCE_DIR", presence_dir)
    monkeypatch.setattr(ftlc, "AGY_CONVERSATIONS_DIR", convs_dir)
    monkeypatch.setattr(ftlc, "OPENCODE_DB", oc_db)
    monkeypatch.setattr(ftlc, "CONTINUITY_DB", cont_db)
    monkeypatch.setattr(ftlc, "STATE_DIR", state_dir)
    monkeypatch.setattr(ftlc, "STATE_FILE", state_dir / "state.json")
    monkeypatch.setattr(ftlc, "LEDGER_FILE", state_dir / "ledger.jsonl")
    monkeypatch.setattr(ftlc, "LOCK_FILE", state_dir / "continuator.lock")
    monkeypatch.setattr(ftlc, "FTL_TELEGRAM_JOBS_DIR", tmp_path / "no_tg_jobs")

    engine = ftlc.FtlTerminalContinuator()
    scan = engine.scan_all_terminals(max_age_hours=24, active_grace_seconds=60, reconcile_first=True)

    assert scan["reconciled"]["reconciled_count"] == 1
    assert scan["counts"]["agy"] == 1
    assert scan["agy"][0]["conversation_id"] == stalled_cid
    assert scan["counts"]["opencode"] == 1
    assert scan["opencode"][0]["session_id"] == "ses_failed_1"
    assert scan["counts"]["ftl"] == 1
    assert scan["ftl"][0]["request_id"] == 2

    # Verificar que continue_opencode_session rota del modelo fallido al siguiente disponible
    with mock.patch.object(ftlc.subprocess, "run") as mrun:
        mrun.return_value = mock.Mock(returncode=0, stdout="> build · beam-free\nTrabajo completado con éxito.", stderr="")
        oc_res = engine.continue_opencode_session("ses_failed_1", allow_agy_fallback=False)
        assert oc_res["ok"] is True
        assert oc_res["model"] != "opencode/deepseek-v4.1-flash-free#max"
        args_used = mrun.call_args[0][0]
        assert "--session" in args_used and "ses_failed_1" in args_used and "--auto" in args_used
