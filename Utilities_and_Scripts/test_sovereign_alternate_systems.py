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


def test_resource_governor_reclaim_detects_in_flight_duplicate(tmp_path: Path, monkeypatch):
    from unittest.mock import MagicMock
    from core import tardis_resource_governor as trg

    gov = trg.TardisResourceGovernor(db_path=tmp_path / "gov_inflight.db")
    dup_snap = {
        "ok": True,
        "level": "ORANGE",
        "memory": {"available_mb": 7000.0},
        "inference_lanes": {
            "duplicate_models": [
                {
                    "port": 11434,
                    "model": "qwen3-vl:2b-instruct",
                    "size_mb": 1925.5,
                    "reason": "duplicado_cpu_con_gpu_lane_11435",
                }
            ]
        },
    }

    fake_resp = MagicMock()
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False
    fake_resp.read.return_value = b"{}"

    monkeypatch.setattr(gov, "collect_snapshot", lambda persist=False: dup_snap)
    monkeypatch.setattr(trg.urllib.request, "urlopen", lambda req, timeout=12.0: fake_resp)
    monkeypatch.setattr(trg.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        trg,
        "_query_ollama_ps",
        lambda port: [{"name": "qwen3-vl:2b-instruct", "size_mb": 1925.5, "size_vram_mb": 0.0}],
    )
    monkeypatch.setattr(
        trg,
        "_find_ollama_port_clients",
        lambda port=11434: [{"pid": 1426, "comm": "python3", "unit": "tardis-video-pensante.service", "cmdline": "tardis_video_pensante.py"}],
    )

    res = gov.reclaim_resources(dry_run=False, prune_backups=False)
    assert res["ok"] is True
    assert len(res["models_evicted"]) == 1
    assert res["models_evicted"][0]["action"] == "unload_deferred_in_flight"
    assert res["models_evicted"][0]["active_clients"][0]["unit"] == "tardis-video-pensante.service"


def test_resource_governor_ring0_throttling_lifecycle(tmp_path: Path, monkeypatch):
    from core import tardis_resource_governor as trg

    gov = trg.TardisResourceGovernor(
        db_path=tmp_path / "gov_throttle.db",
        throttle_state_file=tmp_path / "throttle_state.json",
    )
    monkeypatch.setattr(trg, "_systemd_control_enabled", lambda: True)

    live_props = {
        "tardis-video-pensante.service": {
            "ActiveState": "active",
            "CPUWeight": "25",
            "IOWeight": "100",
            "CPUQuotaPerSecUSec": "infinity",
        },
        "tardis-tapo-c310-sentinel.service": {
            "ActiveState": "active",
            "CPUWeight": "25",
            "IOWeight": "100",
            "CPUQuotaPerSecUSec": "infinity",
        },
        "tardis-temporal-brain.service": {
            "ActiveState": "active",
            "CPUWeight": "40",
            "IOWeight": "100",
            "CPUQuotaPerSecUSec": "infinity",
        },
    }
    applied_calls = []

    monkeypatch.setattr(trg, "_query_systemd_unit_props", lambda u: live_props.get(u))

    def _fake_apply(unit, *, cpu_weight=None, io_weight=None, cpu_quota=None):
        applied_calls.append((unit, cpu_weight, io_weight, cpu_quota))
        if unit in live_props:
            if cpu_weight is not None:
                live_props[unit]["CPUWeight"] = str(cpu_weight)
            if io_weight is not None:
                live_props[unit]["IOWeight"] = str(io_weight)
            if cpu_quota is not None:
                live_props[unit]["CPUQuotaPerSecUSec"] = cpu_quota or "infinity"
        return True

    monkeypatch.setattr(trg, "_apply_systemd_unit_props", _fake_apply)

    orange_snap = {
        "ok": True,
        "level": "ORANGE",
        "call_priority_active": False,
        "cpu": {"psi": {"some_avg60": 62.8}, "temp_c": 75.0},
        "gpu": {"available": True, "temp_c": 72.0},
        "memory": {"available_mb": 9389.8},
        "inference_lanes": {"duplicate_models": [], "ollama_11434": []},
    }

    # 1. Aplicar throttling en ORANGE
    th_orange = gov.apply_throttling(orange_snap, dry_run=False)
    assert th_orange["ok"] is True
    assert th_orange["action"] == "throttled"
    assert th_orange["level"] == "ORANGE"
    throttled_names = {u["unit"] for u in th_orange["applied_units"]}
    assert "tardis-video-pensante.service" in throttled_names
    assert "tardis-tapo-c310-sentinel.service" in throttled_names
    assert "tardis-temporal-brain.service" in throttled_names
    assert gov.get_throttle_status()["active"] is True

    # 2. Escalar a RED debe conservar los baselines originales (CPUWeight=25/40, CPUQuota="")
    red_snap = dict(orange_snap, level="RED", cpu={"psi": {"some_avg60": 80.0}, "temp_c": 85.0})
    th_red = gov.apply_throttling(red_snap, dry_run=False)
    assert th_red["ok"] is True
    assert th_red["level"] == "RED"
    state_raw = json.loads((tmp_path / "throttle_state.json").read_text(encoding="utf-8"))
    assert state_raw["baselines"]["tardis-video-pensante.service"]["CPUWeight"] == "25"
    assert state_raw["baselines"]["tardis-temporal-brain.service"]["CPUWeight"] == "40"
    assert state_raw["baselines"]["tardis-video-pensante.service"]["CPUQuota"] == ""

    # 3. Liberar throttling debe restaurar exactamente baselines originales y CPUQuota="" (infinity)
    rel = gov.release_throttling(dry_run=False)
    assert rel["ok"] is True
    assert rel["action"] == "restored"
    assert gov.get_throttle_status()["active"] is False
    assert live_props["tardis-video-pensante.service"]["CPUWeight"] == "25"
    assert live_props["tardis-video-pensante.service"]["CPUQuotaPerSecUSec"] == "infinity"
    assert live_props["tardis-temporal-brain.service"]["CPUWeight"] == "40"


def test_resource_governor_throttling_skips_during_telegram_call(tmp_path: Path, monkeypatch):
    from core import tardis_resource_governor as trg

    gov = trg.TardisResourceGovernor(
        db_path=tmp_path / "gov_call.db",
        throttle_state_file=tmp_path / "throttle_call.json",
    )
    monkeypatch.setattr(trg, "_systemd_control_enabled", lambda: True)
    call_snap = {
        "ok": True,
        "level": "RED",
        "call_priority_active": True,
        "cpu": {"psi": {"some_avg60": 70.0}, "temp_c": 75.0},
        "gpu": {"available": True, "temp_c": 70.0},
    }
    res = gov.apply_throttling(call_snap, dry_run=False)
    assert res["ok"] is True
    assert res["action"] == "skipped"
    assert res["skipped_reason"] == "telegram_call_priority_active"


def test_resource_governor_reclaim_applies_and_releases_throttling(tmp_path: Path, monkeypatch):
    from core import tardis_resource_governor as trg

    gov = trg.TardisResourceGovernor(
        db_path=tmp_path / "gov_rec_th.db",
        throttle_state_file=tmp_path / "throttle_rec.json",
    )
    monkeypatch.setattr(trg, "_systemd_control_enabled", lambda: True)
    monkeypatch.setattr(
        trg,
        "_query_systemd_unit_props",
        lambda u: (
            {"ActiveState": "active", "CPUWeight": "25", "IOWeight": "100", "CPUQuotaPerSecUSec": "infinity"}
            if u == "tardis-tapo-c310-sentinel.service"
            else None
        ),
    )
    monkeypatch.setattr(trg, "_apply_systemd_unit_props", lambda *a, **kw: True)

    orange_snap = {
        "ok": True,
        "level": "ORANGE",
        "call_priority_active": False,
        "cpu": {"psi": {"some_avg60": 62.76}, "temp_c": 74.0},
        "gpu": {"available": True, "temp_c": 72.0},
        "memory": {"available_mb": 9389.8},
        "inference_lanes": {"duplicate_models": [], "ollama_11434": []},
        "oversubscribed_units": [],
    }
    monkeypatch.setattr(gov, "collect_snapshot", lambda persist=False: orange_snap)
    rec1 = gov.reclaim_resources(dry_run=False, prune_backups=False)
    assert rec1["ok"] is True
    assert rec1["throttling"]["action"] == "throttled"
    assert gov.get_throttle_status()["active"] is True

    green_snap = {
        "ok": True,
        "level": "GREEN",
        "call_priority_active": False,
        "cpu": {"psi": {"some_avg60": 4.2}, "temp_c": 60.0},
        "gpu": {"available": True, "temp_c": 55.0},
        "memory": {"available_mb": 12000.0},
        "inference_lanes": {"duplicate_models": [], "ollama_11434": []},
        "oversubscribed_units": [],
    }
    monkeypatch.setattr(gov, "collect_snapshot", lambda persist=False: green_snap)
    rec2 = gov.reclaim_resources(dry_run=False, prune_backups=False)
    assert rec2["ok"] is True
    assert rec2["throttling"]["action"] == "restored"
    assert gov.get_throttle_status()["active"] is False


def test_resource_governor_cpulist_and_quota_helpers():
    from core import tardis_resource_governor as trg

    assert trg._parse_cpulist_count("8-15") == 8
    assert trg._parse_cpulist_count("0-3,8-11") == 8
    assert trg._parse_cpulist_count("0") == 1
    assert trg._parse_cpulist_count("") == 0
    assert trg._systemd_quota_usec_to_pct("infinity") == ""
    assert trg._systemd_quota_usec_to_pct("1.5s") == "150%"
    assert trg._systemd_quota_usec_to_pct("500ms") == "50%"
    assert trg._extract_cli_int_flag("llama-server --threads 8 --threads-batch 16 --poll 0", ("--threads-batch", "-tb")) == 16
    assert trg._extract_cli_int_flag("llama-server -t 4 -tb=8", ("--threads", "-t")) == 4


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
