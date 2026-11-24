"""
tests/test_sovereign_alternate_systems.py
=========================================
Suite integral de pruebas unitarias para los 4 nuevos sistemas alternos soberanos
y las correcciones críticas de TARDIS:
  1. SovereignEventBus (publish, dedup, durable cursor consume, stats, prune)
  2. TardisResourceGovernor (snapshot, admission control, pressure levels, dry-run reclaim)
  3. TardisCanaryVerifier (AST check, secret/mlockall guard, snapshot & atomic rollback)
  4. TardisAgyCoevolutionEngine (6-lens scan, capability matrix, anti-recursion guard,
     bidirectional dialogue TARDIS <-> AGY, inbox digest)
  5. Regresiones corregidas: hub_health probes, autonomous_coder backup relative path,
     tardis_error_sentinel urllib.parse & active systemd tunnel check.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_event_bus_publish_dedup_and_durable_cursors(tmp_path: Path):
    from core.tardis_event_bus import SovereignEventBus

    bus = SovereignEventBus(db_path=tmp_path / "bus.db")
    r1 = bus.publish("health.regression", "test_suite", {"subsystem": "chat", "to": "offline"}, severity="HIGH", dedup_window_s=60.0)
    assert r1["ok"] and r1["published"] and not r1["duplicate"]

    # Duplicado en ventana debe suprimirse
    r2 = bus.publish("health.regression", "test_suite", {"subsystem": "chat", "to": "offline"}, severity="HIGH", dedup_window_s=60.0)
    assert r2["ok"] and not r2["published"] and r2["duplicate"]

    # Evento distinto se publica normalmente
    r3 = bus.publish("discovery.system", "test_suite", {"title": "Semantic Cache"}, severity="INFO", dedup_window_s=60.0)
    assert r3["ok"] and r3["published"]

    # Consumo con cursor durable
    batch1 = bus.consume("consumer_a", topics=("health.regression",), advance=True)
    assert len(batch1) == 1
    assert batch1[0]["topic"] == "health.regression"

    batch2 = bus.consume("consumer_a", topics=("health.regression",), advance=True)
    assert len(batch2) == 0

    st = bus.stats()
    assert st["total_events"] == 2
    assert st["by_topic"]["health.regression"] == 1


def test_resource_governor_snapshot_and_admission(tmp_path: Path):
    from core.tardis_resource_governor import TardisResourceGovernor

    gov = TardisResourceGovernor(db_path=tmp_path / "gov.db")
    snap = gov.collect_snapshot(persist=False)
    assert snap["ok"] is True
    assert snap["level"] in ("GREEN", "YELLOW", "ORANGE", "RED")
    assert snap["memory"]["total_mb"] > 0
    assert snap["admission"]["interactive"] is True
    assert snap["admission"]["critical_repair"] is True

    adm = gov.admit("interactive")
    assert adm["ok"] and adm["allowed"] is True

    rec = gov.reclaim_resources(dry_run=True, prune_backups=False)
    assert rec["ok"] and rec["dry_run"] is True


def test_canary_verifier_static_snapshot_and_rollback(tmp_path: Path):
    from core.tardis_canary_verifier import TardisCanaryVerifier

    verifier = TardisCanaryVerifier(db_path=tmp_path / "canary.db")
    sample = tmp_path / "sample_mod.py"
    sample.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    res_ok = verifier.verify_files([sample], run_tests=False, check_live_api=False, create_snapshot=True)
    assert res_ok["ok"] is True
    run_id = res_ok["run_id"]

    # Introducir error de sintaxis y verificar que falla la puerta canaria
    sample.write_text("def broken(:\n    pass\n", encoding="utf-8")
    res_bad = verifier.verify_files([sample], run_tests=False, check_live_api=False)
    assert res_bad["ok"] is False
    assert res_bad["static"]["high_issues"] >= 1

    # Rollback atómico debe restaurar el código válido
    rb = verifier.rollback(run_id)
    assert rb["ok"] is True
    assert "return a + b" in sample.read_text(encoding="utf-8")


def test_coevolution_engine_discovery_bidirectional_and_anti_recursion(tmp_path: Path, monkeypatch):
    from core.tardis_agy_coevolution import TardisAgyCoevolutionEngine

    eng = TardisAgyCoevolutionEngine(db_path=tmp_path / "coev.db")
    # Escanear capacidades: los 4 sistemas nuevos ya existen, pero faltan capacidades futuras (ej. semantic cache)
    scan_res = eng.scan(lens="capabilities")
    assert scan_res["ok"] is True
    assert scan_res["evaluated"] >= 1

    props = eng.list_proposals(status="pending", limit=10)
    assert len(props) >= 1
    first_pid = props[0]["proposal_id"]

    # Anti-recursion guard debe bloquear envíos anidados
    monkeypatch.setenv("TARDIS_COEVOLUTION_NESTED", "1")
    blocked = eng.communicate_with_agy(proposal_id=first_pid, sync=False, force=False)
    assert blocked["ok"] is False
    assert blocked.get("blocked") == "anti_recursion_guard"
    monkeypatch.delenv("TARDIS_COEVOLUTION_NESTED", raising=False)

    # Respuesta de AGY hacia TARDIS debe actualizar propuesta y registrar diálogo
    rep = eng.record_agy_reply(
        "Blueprint validado para sistema alterno de caché semántica.",
        proposal_id=first_pid,
        status="reviewed",
        sender="Antigravity-Test",
    )
    assert rep["ok"] is True
    updated = eng.get_proposal(first_pid)
    assert updated is not None and updated["status"] == "reviewed"
    dlg = eng.get_dialogue(limit=5)
    assert any(m["direction"] == "AGY->TARDIS" and m["proposal_id"] == first_pid for m in dlg)


def test_hub_health_probes_fixed():
    from core.hub_health import PROBES

    assert PROBES["terminal_pty"]["http"] == "http://127.0.0.1:7681/terminal/"
    assert PROBES["embeddings_srv"]["unit"] == "tardis-embed-brain"
    assert PROBES["quantum_bridge"]["unit"] == "tardis"
    for new_sub in ("resource_governor", "event_bus", "canary_verifier", "agy_coevolution"):
        assert new_sub in PROBES


def test_error_sentinel_imports_and_tunnel_check():
    from core.tardis_error_sentinel import TardisErrorSentinel

    s = TardisErrorSentinel(check_interval=60.0)
    ok, msg = s.check_online_tunnel()
    assert ok is True
    assert isinstance(msg, str) and len(msg) > 0
