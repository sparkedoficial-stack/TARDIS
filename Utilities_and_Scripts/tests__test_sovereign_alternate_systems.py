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


def test_resource_governor_orange_cpu_thermal_and_psi_mitigation_with_power_profile(tmp_path: Path, monkeypatch):
    from unittest.mock import MagicMock
    from core import tardis_resource_governor as trg

    gov = trg.TardisResourceGovernor(
        db_path=tmp_path / "gov_thermal_psi.db",
        throttle_state_file=tmp_path / "throttle_thermal_psi.json",
    )
    monkeypatch.setattr(trg, "_systemd_control_enabled", lambda: True)
    monkeypatch.setattr(trg, "_power_profile_control_enabled", lambda: True)

    current_pp = {"profile": "performance"}
    monkeypatch.setattr(trg, "_get_power_profile", lambda: current_pp["profile"])

    def _fake_set_pp(prof: str) -> bool:
        current_pp["profile"] = prof
        return True

    monkeypatch.setattr(trg, "_set_power_profile", _fake_set_pp)

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
    monkeypatch.setattr(trg, "_query_systemd_unit_props", lambda u: live_props.get(u))

    def _fake_apply(unit, *, cpu_weight=None, io_weight=None, cpu_quota=None):
        if unit in live_props:
            if cpu_weight is not None:
                live_props[unit]["CPUWeight"] = str(cpu_weight)
            if io_weight is not None:
                live_props[unit]["IOWeight"] = str(io_weight)
            if cpu_quota is not None:
                live_props[unit]["CPUQuotaPerSecUSec"] = cpu_quota or "infinity"
        return True

    monkeypatch.setattr(trg, "_apply_systemd_unit_props", _fake_apply)

    # Simular escenario exacto: ORANGE (CPU PSI60=32.39%, CPU=83°C, RAM=12681.5 MB) + modelo CPU-only en :11434
    fake_resp = MagicMock()
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False
    fake_resp.read.return_value = b"{}"
    monkeypatch.setattr(trg.urllib.request, "urlopen", lambda req, timeout=12.0: fake_resp)
    monkeypatch.setattr(trg.time, "sleep", lambda _s: None)
    monkeypatch.setattr(trg, "_query_ollama_ps", lambda port: [])

    orange_cpu_snap = {
        "ok": True,
        "level": "ORANGE",
        "call_priority_active": False,
        "cpu": {"cores": 16, "load1": 11.81, "psi": {"some_avg60": 32.39}, "temp_c": 83.0, "power_profile": "performance"},
        "gpu": {"available": True, "temp_c": 75.0},
        "memory": {"available_mb": 12681.5, "swap_used_mb": 1767.0},
        "inference_lanes": {
            "duplicate_models": [],
            "ollama_11434": [{"name": "llama3.2:3b", "size_mb": 2048.0, "size_vram_mb": 0.0}],
        },
        "oversubscribed_units": [],
    }
    monkeypatch.setattr(gov, "collect_snapshot", lambda persist=False: orange_cpu_snap)

    # 1. Reclaim debe descargar modelo CPU-only en :11434, aplicar throttling cgroup + cambiar perfil a balanced
    rec1 = gov.reclaim_resources(dry_run=False, prune_backups=False)
    assert rec1["ok"] is True
    assert len(rec1["models_evicted"]) == 1
    assert rec1["models_evicted"][0]["action"] == "unloaded"
    assert rec1["models_evicted"][0]["reason"] == "cpu_psi_or_thermal_pressure_eviction"
    assert rec1["throttling"]["action"] == "throttled"
    assert rec1["throttling"]["power_profile_action"] == "switched_to_balanced"
    assert rec1["cpu_temp_before_c"] == 83.0
    assert current_pp["profile"] == "balanced"
    assert "tardis-temporal-brain.service" in gov.get_throttle_status()["units"]

    # 2. Drift vivo: si tardis-tapo-c310-sentinel se reinicia y pierde su CPUQuota, apply_throttling debe re-aplicar
    live_props["tardis-tapo-c310-sentinel.service"]["CPUQuotaPerSecUSec"] = "infinity"
    th_drift = gov.apply_throttling(orange_cpu_snap, dry_run=False)
    sentinel_entry = next(u for u in th_drift["applied_units"] if u["unit"] == "tardis-tapo-c310-sentinel.service")
    assert sentinel_entry["action"] == "throttled"
    assert live_props["tardis-tapo-c310-sentinel.service"]["CPUQuotaPerSecUSec"] == "150%"

    # 3. De-escalación parcial: ORANGE solo por RAM baja (térmica y PSI ya normales) libera TemporalBrain del plan
    orange_ram_only_snap = {
        "ok": True,
        "level": "ORANGE",
        "call_priority_active": False,
        "cpu": {"cores": 16, "load1": 3.0, "psi": {"some_avg60": 12.0}, "temp_c": 68.0, "power_profile": "balanced"},
        "gpu": {"available": True, "temp_c": 60.0},
        "memory": {"available_mb": 2900.0, "swap_used_mb": 1767.0},
        "inference_lanes": {"duplicate_models": [], "ollama_11434": []},
        "oversubscribed_units": [],
    }
    th_deesc = gov.apply_throttling(orange_ram_only_snap, dry_run=False)
    tb_entry = next(u for u in th_deesc["applied_units"] if u["unit"] == "tardis-temporal-brain.service")
    assert tb_entry["action"] == "released_from_plan"
    assert live_props["tardis-temporal-brain.service"]["CPUWeight"] == "40"
    assert live_props["tardis-temporal-brain.service"]["CPUQuotaPerSecUSec"] == "infinity"
    assert "tardis-temporal-brain.service" not in gov.get_throttle_status()["units"]

    # 4. Recuperación Schmitt-trigger en YELLOW seguro (77.5°C, PSI60=8.5%): libera cgroups pero conserva balanced
    safe_yellow_snap = {
        "ok": True,
        "level": "YELLOW",
        "call_priority_active": False,
        "cpu": {"cores": 16, "load1": 3.4, "psi": {"some_avg60": 8.5}, "temp_c": 77.5, "power_profile": "balanced"},
        "gpu": {"available": True, "temp_c": 70.0},
        "memory": {"available_mb": 13100.0, "swap_used_mb": 1767.0},
        "inference_lanes": {"duplicate_models": [], "ollama_11434": []},
        "oversubscribed_units": [],
    }
    monkeypatch.setattr(gov, "collect_snapshot", lambda persist=False: safe_yellow_snap)
    rec_yellow = gov.reclaim_resources(dry_run=False, prune_backups=False)
    assert rec_yellow["throttling"]["action"] == "restored"
    assert rec_yellow["throttling"]["power_profile_action"] == "kept_balanced_thermal_headroom"
    assert gov.get_throttle_status()["active"] is False
    assert gov.get_throttle_status()["power_profile_mitigated"] is True
    assert current_pp["profile"] == "balanced"

    # 5. Enfriamiento completo (GREEN 68°C / GPU 62°C): restaura perfil energético 'performance'
    cool_green_snap = {
        "ok": True,
        "level": "GREEN",
        "call_priority_active": False,
        "cpu": {"cores": 16, "load1": 2.1, "psi": {"some_avg60": 4.0}, "temp_c": 68.0, "power_profile": "balanced"},
        "gpu": {"available": True, "temp_c": 62.0},
        "memory": {"available_mb": 13500.0, "swap_used_mb": 1767.0},
        "inference_lanes": {"duplicate_models": [], "ollama_11434": []},
        "oversubscribed_units": [],
    }
    monkeypatch.setattr(gov, "collect_snapshot", lambda persist=False: cool_green_snap)
    rec_cool = gov.reclaim_resources(dry_run=False, prune_backups=False)
    assert rec_cool["throttling"]["power_profile_action"] == "restored_performance"
    assert current_pp["profile"] == "performance"
    assert gov.get_throttle_status()["power_profile_mitigated"] is False


def test_resource_governor_combined_yellow_trigger_and_transient_spike_filter(tmp_path: Path):
    import sqlite3
    from core import tardis_resource_governor as trg

    # Trigger proactivo YELLOW con CPU caliente + PSI moderado-alto
    yellow_stress = {
        "level": "YELLOW",
        "call_priority_active": False,
        "cpu": {"cores": 16, "load1": 8.0, "psi": {"some_avg60": 32.4}, "temp_c": 78.5},
        "gpu": {"available": True, "temp_c": 70.0},
        "memory": {"available_mb": 12681.5, "swap_used_mb": 1767.0},
    }
    assert trg._resolve_throttle_target_level(yellow_stress) == "ORANGE"
    assert trg._is_in_safe_recovery_band(yellow_stress) is False

    # YELLOW tranquilo (Tctl ~77.5°C, PSI60=9.5%): no dispara throttling y SÍ habilita banda de recuperación
    yellow_calm = {
        "level": "YELLOW",
        "call_priority_active": False,
        "cpu": {"cores": 16, "load1": 3.5, "psi": {"some_avg60": 9.5}, "temp_c": 77.5},
        "gpu": {"available": True, "temp_c": 70.0},
        "memory": {"available_mb": 13100.0, "swap_used_mb": 1767.0},
    }
    assert trg._resolve_throttle_target_level(yellow_calm) is None
    assert trg._is_in_safe_recovery_band(yellow_calm) is True

    # Filtro de micro-picos Ryzen Tctl (83°C con PSI 5.1% vs 83°C con PSI 32.4%)
    spike_only = {
        "level": "ORANGE",
        "call_priority_active": False,
        "cpu": {"cores": 16, "load1": 3.35, "psi": {"some_avg60": 5.13}, "temp_c": 83.0},
        "gpu": {"available": True, "temp_c": 69.0},
        "memory": {"available_mb": 13096.5, "swap_used_mb": 1767.0},
    }
    real_orange = {
        "level": "ORANGE",
        "call_priority_active": False,
        "cpu": {"cores": 16, "load1": 11.81, "psi": {"some_avg60": 32.39}, "temp_c": 83.0},
        "gpu": {"available": True, "temp_c": 75.0},
        "memory": {"available_mb": 12681.5, "swap_used_mb": 1767.0},
    }
    assert trg._is_pure_transient_cpu_thermal_spike(spike_only) is True
    assert trg._is_pure_transient_cpu_thermal_spike(real_orange) is False

    # Verificar migración de esquema SQLite para columna cpu_temp_c
    legacy_db = tmp_path / "legacy_gov.db"
    with sqlite3.connect(str(legacy_db)) as conn:
        conn.execute(
            "CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, iso TEXT, level TEXT, cpu_psi_60 REAL, mem_avail_mb REAL, swap_used_mb REAL, load1 REAL, gpu_temp_c REAL, vram_used_mb REAL, duplicate_models_count INTEGER, reasons_json TEXT)"
        )
    gov = trg.TardisResourceGovernor(db_path=legacy_db, throttle_state_file=tmp_path / "th.json")
    snap = gov.collect_snapshot(persist=False)
    gov._persist_db(snap)
    hist = gov.history(limit=5)
    assert len(hist) == 1
    assert "cpu_temp_c" in hist[0]


def test_canary_verifier_static_snapshot_and_rollback(tmp_path: Path):
    from core.tardis_canary_verifier import CANARY_BACKUP_ROOT, TardisCanaryVerifier

    verifier = TardisCanaryVerifier(db_path=tmp_path / "canary.db")
    assert verifier.backup_root.resolve() != CANARY_BACKUP_ROOT.resolve()
    sample = tmp_path / "sample_mod.py"
    sample.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    res_ok = verifier.verify_files([sample], run_tests=False, check_live_api=False, create_snapshot=True)
    assert res_ok["ok"] is True
    assert str(tmp_path) in str(res_ok["backup_dir"])
    run_id = res_ok["run_id"]

    # Introducir error de sintaxis y verificar que falla la puerta canaria
    sample.write_text("def broken(:\n    pass\n", encoding="utf-8")
    res_bad = verifier.verify_files([sample], run_tests=False, check_live_api=False)
    assert res_bad["ok"] is False
    assert res_bad["static"]["high_issues"] >= 1

    # Rollback atómico debe restaurar el código válido sin contaminar _selfmod_backups/canary
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


def test_feedback_bridge_health_hysteresis_recovery_and_partial_hub_guard():
    from core import tardis_feedback_bridge as tfb

    base_subs = {f"sub_{i}": "online" for i in range(10)}
    prev = {
        "ts": 1000.0,
        "iso": "2026-11-23 21:21:00",
        "subsystems": dict(base_subs),
        "self_improve": {"score": 100, "status": "HEALTHY", "metrics": {}, "needs": [], "penalties": []},
        "governor": {"level": "YELLOW", "cpu_psi_60": 33.1},
        "inbox": {"pending": []},
        "health_tracker": {"low_streak": 0, "regression_active": False, "baseline_score": 100, "last_score": 100},
    }

    # 1. Caída leve transitoria (100 -> 85, sigue HEALTHY): no dispara salud_baja en el 1er ciclo
    cur1 = {
        "ts": 1060.0,
        "iso": "2026-11-23 21:22:10",
        "subsystems": dict(base_subs),
        "self_improve": {
            "score": 85,
            "status": "HEALTHY",
            "metrics": {"cpu_percent": 88.2, "cpu_ema": 62.0},
            "needs": [],
            "penalties": [{"factor": "cpu_sustained", "points": -15}],
        },
        "governor": {"level": "ORANGE", "cpu_psi_60": 28.4},
        "inbox": {"pending": []},
    }
    ev1 = tfb.diff(prev, cur1)
    assert not any(e["kind"] == "salud_baja" for e in ev1)
    assert any(e["kind"] == "salud_fluctuacion" and e["confirmed"] is False for e in ev1)
    assert cur1["health_tracker"]["low_streak"] == 1
    assert cur1["health_tracker"]["regression_active"] is False

    # 2. Persistencia en 2º ciclo (sigue en 85): confirma salud_baja MEDIUM con contexto diagnóstico
    cur2 = {
        "ts": 1120.0,
        "iso": "2026-11-23 21:23:10",
        "subsystems": dict(base_subs),
        "self_improve": dict(cur1["self_improve"]),
        "governor": dict(cur1["governor"]),
        "inbox": {"pending": []},
    }
    ev2 = tfb.diff(cur1, cur2)
    baja = [e for e in ev2 if e["kind"] == "salud_baja"]
    assert len(baja) == 1
    assert baja[0]["severity"] == "MEDIUM"
    assert baja[0]["confirmed"] is True
    assert baja[0]["diagnostics"]["governor"]["level"] == "ORANGE"
    assert cur2["health_tracker"]["regression_active"] is True

    # 3. Recuperación simétrica (85 -> 100): emite salud_recuperada
    cur3 = {
        "ts": 1180.0,
        "iso": "2026-11-23 21:24:10",
        "subsystems": dict(base_subs),
        "self_improve": {"score": 100, "status": "HEALTHY", "metrics": {"cpu_percent": 18.0}, "needs": [], "penalties": []},
        "governor": {"level": "GREEN", "cpu_psi_60": 8.0},
        "inbox": {"pending": []},
    }
    ev3 = tfb.diff(cur2, cur3)
    rec = [e for e in ev3 if e["kind"] == "salud_recuperada"]
    assert len(rec) == 1
    assert rec[0]["from"] == 85 and rec[0]["to"] == 100
    assert cur3["health_tracker"]["regression_active"] is False
    assert cur3["health_tracker"]["low_streak"] == 0

    # 4. Caída severa (<80 / DEGRADED): escala inmediatamente con severity HIGH
    cur_sev = {
        "ts": 1240.0,
        "iso": "2026-11-23 21:25:10",
        "subsystems": dict(base_subs),
        "self_improve": {"score": 70, "status": "DEGRADED", "metrics": {}, "needs": ["Temporal Brain offline"], "penalties": []},
        "governor": {"level": "RED", "cpu_psi_60": 82.0},
        "inbox": {"pending": []},
    }
    ev_sev = tfb.diff(cur3, cur_sev)
    baja_sev = [e for e in ev_sev if e["kind"] == "salud_baja"]
    assert len(baja_sev) == 1 and baja_sev[0]["severity"] == "HIGH"

    # 5. Guard contra snapshot parcial de /api/hub/health (evita tormenta de subsistema_ausente)
    cur_partial = {
        "ts": 1300.0,
        "iso": "2026-11-23 21:26:10",
        "subsystems": {"sub_0": "online", "sub_1": "online"},
        "self_improve": dict(cur3["self_improve"]),
        "governor": {},
        "inbox": {"pending": []},
    }
    ev_partial = tfb.diff(cur3, cur_partial)
    assert not any(e["kind"] == "subsistema_ausente" for e in ev_partial)
    assert any(e["kind"] == "hub_snapshot_partial" for e in ev_partial)


def test_antigravity_bridge_cpu_spike_hysteresis_and_diagnostics(monkeypatch):
    import antigravity_bridge

    bridge = antigravity_bridge.OmniFeedbackBridge()
    monkeypatch.setattr(
        bridge,
        "_probe_subsystems",
        lambda: {
            "ollama_online": True,
            "temporal_brain_online": True,
            "rf_radar_active": False,
            "radar_variance": 0.1,
            "ios_bridge": True,
            "geon_engine": True,
            "memory_fts": True,
            "sensors": True,
        },
    )
    monkeypatch.setattr(antigravity_bridge, "_atomic_write_json", lambda *a, **kw: None)
    monkeypatch.setattr(antigravity_bridge, "_safe_tail", lambda *a, **kw: [])
    import psutil
    from types import SimpleNamespace
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: SimpleNamespace(percent=50.0, available=16 * 1024**3, total=32 * 1024**3),
    )

    # Ciclo 1: pico transitorio único de 91% CPU con EMA baja previa -> NO debe penalizar a 85
    bridge._cpu_ema = 25.0
    monkeypatch.setattr(bridge, "_sample_cpu_percent", lambda: 91.0)
    a1 = bridge.assess_system_needs()
    assert a1["health_score"] == 100
    assert a1["metrics"]["high_cpu_streak"] == 1
    assert a1["penalties"] == []

    # Ciclo 2: CPU sigue >85% en 2º ciclo consecutivo -> penalización sostenida -15 con trazabilidad
    monkeypatch.setattr(bridge, "_sample_cpu_percent", lambda: 92.0)
    a2 = bridge.assess_system_needs()
    assert a2["health_score"] == 85
    assert a2["metrics"]["high_cpu_streak"] == 2
    assert any(p["factor"] == "cpu_sustained" and p["points"] == -15 for p in a2["penalties"])

    st = bridge.get_status()
    assert "metrics" in st and "penalties" in st and "needs" in st
    assert st["metrics"]["high_cpu_streak"] == 2


def test_event_bus_pytest_isolation_and_coevolution_recovery_correlation(tmp_path: Path, monkeypatch):
    from core import tardis_event_bus as teb
    from core.tardis_agy_coevolution import TardisAgyCoevolutionEngine

    # 1. get_event_bus() bajo pytest NO debe abrir data/sovereign_event_bus.db de producción
    bus_default = teb.get_event_bus()
    assert bus_default.db_path.resolve() != teb.DEFAULT_BUS_DB.resolve()

    # 2. Co-evolución debe correlacionar health.recovered para omitir regresiones transitorias ya recuperadas
    iso_bus = teb.SovereignEventBus(db_path=tmp_path / "iso_bus.db")
    monkeypatch.setattr(teb, "get_event_bus", lambda db_path=None: iso_bus)

    iso_bus.publish(
        "health.regression",
        "tardis_feedback_bridge",
        {"kind": "salud_baja", "from": 100, "to": 85},
        severity="HIGH",
        dedup_window_s=0.0,
    )
    iso_bus.publish(
        "health.recovered",
        "tardis_feedback_bridge",
        {"kind": "salud_recuperada", "from": 85, "to": 100},
        severity="INFO",
        dedup_window_s=0.0,
    )
    # También filtrar artefacto sintético sample_mod.py
    iso_bus.publish(
        "evolution.rollback",
        "tardis_canary_verifier",
        {"run_id": "canary_test", "restored_files": ["sample_mod.py"]},
        severity="HIGH",
        dedup_window_s=0.0,
    )

    eng = TardisAgyCoevolutionEngine(db_path=tmp_path / "coev_corr.db")
    monkeypatch.setattr("core.hub_health.hub_health", lambda force=False: {"counts": {"online": 41}, "subsystems": {}})
    found = eng._scan_runtime_lens()
    pending = eng.list_proposals(status="pending", limit=20)
    assert not any(p["category"] == "regression" for p in pending)
    assert isinstance(found, list)


def test_tapo_bounded_streamer_ffmpeg_cmd_caps_threads_and_fps():
    from core.tapo_c310_sentinel import BoundedTapoStreamer

    streamer = BoundedTapoStreamer(
        tapo=None,
        audio=[],
        quality="HD",
        mode="pipe",
        decoder_threads=2,
        encoder_threads=2,
        filter_threads=1,
        max_fps=6.0,
        mjpeg_qscale=5,
        ff_args={
            "-loglevel": "error",
            "-probesize": "300000",
            "-analyzeduration": "300000",
            "-c:v": "mjpeg",
            "-f": "image2pipe",
        },
    )
    cmd = streamer.build_ffmpeg_cmd()
    # Verificar límites explícitos de hilos de decodificación, filtros y codificación + FPS acotado
    assert cmd[0] == "ffmpeg"
    assert cmd.count("-threads") == 2
    in_idx = cmd.index("-i")
    assert cmd.index("-threads") < in_idx
    assert "-filter_threads" in cmd and cmd[cmd.index("-filter_threads") + 1] == "1"
    assert "-filter_complex_threads" in cmd and cmd[cmd.index("-filter_complex_threads") + 1] == "1"
    assert "-r" in cmd and cmd[cmd.index("-r") + 1] == "6"
    assert "-q:v" in cmd and cmd[cmd.index("-q:v") + 1] == "5"


def test_coevolution_hub_health_mass_outage_guard_and_auto_reconcile(tmp_path: Path, monkeypatch):
    from core import tardis_event_bus as teb
    from core.tardis_agy_coevolution import TardisAgyCoevolutionEngine

    iso_bus = teb.SovereignEventBus(db_path=tmp_path / "iso_bus_hub.db")
    monkeypatch.setattr(teb, "get_event_bus", lambda db_path=None: iso_bus)
    eng = TardisAgyCoevolutionEngine(db_path=tmp_path / "coev_hub.db")

    # 1. Simular reinicio masivo de tardis.service (8/10 subsistemas offline): NO debe spammear propuestas individuales
    mass_offline = {f"sub_{i}": {"id": f"sub_{i}", "status": "offline" if i < 8 else "online"} for i in range(10)}
    monkeypatch.setattr("core.hub_health.hub_health", lambda force=False: {"counts": {"offline": 8, "online": 2}, "subsystems": mass_offline})
    eng._scan_runtime_lens()
    assert not any(p["category"] == "reliability" for p in eng.list_proposals(status="pending", limit=20))

    # 2. Fallo real de 1 solo subsistema -> crea propuesta reliability pendiente
    one_offline = {f"sub_{i}": {"id": f"sub_{i}", "status": "offline" if i == 0 else "online"} for i in range(10)}
    monkeypatch.setattr("core.hub_health.hub_health", lambda force=False: {"counts": {"offline": 1, "online": 9}, "subsystems": one_offline})
    eng._scan_runtime_lens()
    rel_pend = [p for p in eng.list_proposals(status="pending", limit=20) if p["category"] == "reliability"]
    assert len(rel_pend) == 1 and "sub_0" in rel_pend[0]["title"]

    # 3. Al recuperarse sub_0 -> online, el siguiente scan auto-reconcilia la propuesta a reviewed
    all_online = {f"sub_{i}": {"id": f"sub_{i}", "status": "online"} for i in range(10)}
    monkeypatch.setattr("core.hub_health.hub_health", lambda force=False: {"counts": {"online": 10}, "subsystems": all_online})
    eng._scan_runtime_lens()
    assert not any(p["category"] == "reliability" for p in eng.list_proposals(status="pending", limit=20))
    updated = eng.get_proposal(rel_pend[0]["proposal_id"])
    assert updated is not None and updated["status"] == "reviewed"


def test_telegram_fps_transcode_skips_upsampling_caps_threads_and_caches(monkeypatch):
    import subprocess as sp
    from core import telegram_bridge as tb_mod

    bridge = object.__new__(tb_mod.TelegramBridge)
    bridge._fps_transcode_cache = {}
    calls = []
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + (b"0" * 2048)

    def _fake_run_30fps(cmd, **kwargs):
        calls.append(list(cmd))
        res = sp.CompletedProcess(cmd, 0, stdout="r_frame_rate=30/1\navg_frame_rate=30/1\npix_fmt=yuv420p\n", stderr="")
        return res

    monkeypatch.setattr(tb_mod.subprocess, "run", _fake_run_30fps)
    out30 = bridge.transcode_to_telegram_fps(fake_mp4, target_fps=60)
    assert out30 == fake_mp4
    # Solo debe llamar a ffprobe; NUNCA debe invocar ffmpeg para upsamplear 30 FPS -> 60 FPS
    assert len(calls) == 1 and calls[0][0] == "ffprobe"

    # Ahora probar downsampling legítimo 120 FPS -> 60 FPS: debe acotar hilos (<=4, sin -threads 16) y cachear
    calls.clear()
    fake_120_mp4 = b"\x00\x00\x00\x18ftypmp42" + (b"1" * 2048)

    def _fake_run_120fps(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[0] == "ffprobe":
            return sp.CompletedProcess(cmd, 0, stdout="r_frame_rate=120/1\npix_fmt=yuv420p\n", stderr="")
        out_file = Path(cmd[-1])
        out_file.write_bytes(b"\x00\x00\x00\x18ftypmp42CONVERTED")
        return sp.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(tb_mod.subprocess, "run", _fake_run_120fps)
    out1 = bridge.transcode_to_telegram_fps(fake_120_mp4, target_fps=60)
    assert out1 == b"\x00\x00\x00\x18ftypmp42CONVERTED"
    ff_calls = [c for c in calls if c[0] == "ffmpeg"]
    assert len(ff_calls) == 1
    assert "-filter_threads" in ff_calls[0] and "-filter_complex_threads" in ff_calls[0]
    assert "-threads" in ff_calls[0]
    for idx, tok in enumerate(ff_calls[0]):
        if tok == "-threads":
            assert int(ff_calls[0][idx + 1]) <= 4

    # 2ª llamada con los mismos bytes (ej. 2º chat de Telegram) debe servirse desde caché sin ejecutar ffprobe/ffmpeg
    calls.clear()
    out2 = bridge.transcode_to_telegram_fps(fake_120_mp4, target_fps=60)
    assert out2 == out1
    assert calls == []


def test_tapo_static_scene_motion_gate_skips_static_and_triggers_on_motion_or_heartbeat():
    import numpy as np
    from core.tapo_c310_sentinel import StaticSceneMotionGate

    gate = StaticSceneMotionGate(enabled=True, mean_threshold=2.2, area_threshold=0.008, pixel_delta=14, heartbeat_sec=4.0)
    static_frame = np.full((360, 640, 3), 40, dtype=np.uint8)

    run0, r0, _ = gate.should_run_yolo(static_frame, now=100.0, presence_active=False)
    assert run0 is True and r0 == "first_frame"

    # Fotograma idéntico 0.5s después -> omitir YOLOv8s redundante
    run1, r1, _ = gate.should_run_yolo(static_frame, now=100.5, presence_active=False)
    assert run1 is False and r1 == "static_skip"

    # Fotograma con movimiento localizado (silueta humana entrando) -> disparo inmediato
    moving = static_frame.copy()
    moving[100:260, 260:340] = 190
    run2, r2, _ = gate.should_run_yolo(moving, now=101.0, presence_active=False)
    assert run2 is True and r2 == "motion"

    # Presencia activa siempre ejecuta YOLOv8s incluso sin movimiento
    run3, r3, _ = gate.should_run_yolo(moving, now=101.5, presence_active=True)
    assert run3 is True and r3 == "presence_active"

    # Sin movimiento por >= heartbeat_sec -> ejecuta verificación obligatoria
    run4, r4, _ = gate.should_run_yolo(moving, now=106.0, presence_active=False)
    assert run4 is True and r4 == "heartbeat"


def test_resource_governor_two_stage_thermal_power_saver_escalation_and_recovery(tmp_path: Path, monkeypatch):
    from core import tardis_resource_governor as trg

    gov = trg.TardisResourceGovernor(
        db_path=tmp_path / "gov_pp2.db",
        throttle_state_file=tmp_path / "throttle_pp2.json",
    )
    monkeypatch.setattr(trg, "_systemd_control_enabled", lambda: True)
    monkeypatch.setattr(trg, "_power_profile_control_enabled", lambda: True)
    monkeypatch.setattr(trg, "_query_systemd_unit_props", lambda u: None)

    pp_state = {"profile": "balanced"}
    monkeypatch.setattr(trg, "_get_power_profile", lambda: pp_state["profile"])

    def _fake_set_pp(prof: str) -> bool:
        pp_state["profile"] = prof
        return True

    monkeypatch.setattr(trg, "_set_power_profile", _fake_set_pp)

    hot_snap = {
        "ok": True,
        "level": "ORANGE",
        "call_priority_active": False,
        "cpu": {"cores": 16, "load1": 4.3, "psi": {"some_avg60": 38.2}, "temp_c": 90.5},
        "gpu": {"available": True, "temp_c": 76.0},
        "memory": {"available_mb": 12000.0, "swap_used_mb": 1900.0},
    }
    res_hot = gov.apply_throttling(hot_snap, dry_run=False)
    assert res_hot["ok"] is True
    assert res_hot["power_profile_action"] == "switched_to_power-saver"
    assert pp_state["profile"] == "power-saver"

    # Al enfriarse por debajo de 82°C CPU y 76°C GPU en banda YELLOW, retrocede de power-saver -> balanced
    warm_snap = {
        "ok": True,
        "level": "YELLOW",
        "call_priority_active": False,
        "cpu": {"cores": 16, "load1": 2.5, "psi": {"some_avg60": 10.0}, "temp_c": 77.0},
        "gpu": {"available": True, "temp_c": 71.0},
        "memory": {"available_mb": 12500.0, "swap_used_mb": 1900.0},
    }
    rel = gov.release_throttling(dry_run=False, snap=warm_snap)
    assert rel["ok"] is True
    assert rel["power_profile_action"] == "stepped_back_to_balanced"
    assert pp_state["profile"] == "balanced"


def test_video_pipeline_4k_budget_and_encoder_thread_caps(monkeypatch):
    from core import tardis_resource_governor as trg
    from core import video_pipeline_4k as vp4k

    fake_snap = {"level": "GREEN", "cpu": {"psi": {"some_avg60": 5.0}}}

    class _FakeGov:
        def read_fast_snapshot(self, max_age_s: float = 60.0):
            return fake_snap

    monkeypatch.setattr(trg, "get_resource_governor", lambda: _FakeGov())
    monkeypatch.setattr(vp4k.os, "sched_getaffinity", lambda _pid: set(range(8, 16)), raising=False)

    # GREEN en cpuset de 8 CPUs -> máximo 2 workers, 1 hilo OpenCV y 1 hilo FFmpeg por worker
    w_g, cv_g, ff_g, lvl_g = vp4k._resolve_render_budget(None, 1800)
    assert (w_g, cv_g, ff_g, lvl_g) == (2, 1, 1, "GREEN")

    # YELLOW con PSI60 >= 35% -> contrae proactivamente a 1 worker para evitar contención CCD1
    fake_snap["level"] = "YELLOW"
    fake_snap["cpu"]["psi"]["some_avg60"] = 39.4
    w_y, cv_y, ff_y, lvl_y = vp4k._resolve_render_budget(None, 1800)
    assert w_y == 1 and cv_y <= 2 and ff_y == 2 and lvl_y == "YELLOW"

    # RED -> fuerza 1 worker y 1 hilo FFmpeg incluso si el invocador pidió 4 workers
    fake_snap["level"] = "RED"
    fake_snap["cpu"]["psi"]["some_avg60"] = 75.5
    w_r, cv_r, ff_r, lvl_r = vp4k._resolve_render_budget(4, 1800)
    assert w_r == 1 and ff_r == 1 and lvl_r == "RED"

    # Todos los perfiles de codificación (VAAPI, NVENC, libx264) deben acotar -threads <= 4
    for enc_args in (
        vp4k._video_encoder_args(12000, False, threads=2, vaapi_device="/dev/dri/renderD128"),
        vp4k._video_encoder_args(12000, True, threads=2, vaapi_device=None),
        vp4k._video_encoder_args(12000, False, threads=8, vaapi_device=None),
    ):
        assert "-threads" in enc_args
        t_val = int(enc_args[enc_args.index("-threads") + 1])
        assert 1 <= t_val <= 4


def test_resource_governor_observes_tardis_service_and_aggregate_oversubscription(tmp_path: Path, monkeypatch):
    from core import tardis_resource_governor as trg

    # tardis.service debe observarse para PSI/sobresuscripción pero permanecer estrictamente protegida contra throttling
    assert "tardis.service" in trg.OBSERVED_ONLY_UNITS
    assert "tardis.service" in trg.ALL_INSPECTED_UNITS
    assert "tardis.service" in trg.PROTECTED_UNITS
    assert "tardis.service" not in trg.BACKGROUND_THROTTLE_UNITS
    assert "tardis.service" not in trg.SENTINEL_THROTTLE_UNITS
    assert "tardis.service" not in trg.INFERENCE_MANAGED_UNITS

    # Simular un cgroup tardis.service con cpuset 8-15 (8 CPUs) y 4 workers con 3 hilos 'R' cada uno (12 > 8)
    app_slice = tmp_path / "app.slice"
    cg = app_slice / "tardis.service"
    cg.mkdir(parents=True)
    (cg / "cpuset.cpus.effective").write_text("8-15\n", encoding="utf-8")
    (cg / "cpu.max").write_text("max 100000\n", encoding="utf-8")
    (cg / "cpu.weight").write_text("100\n", encoding="utf-8")
    (cg / "cpu.pressure").write_text(
        "some avg10=48.50 avg60=42.10 avg300=18.00 total=1000\nfull avg10=1.20 avg60=0.80 avg300=0.30 total=100\n",
        encoding="utf-8",
    )
    fake_pids = [91001, 91002, 91003, 91004]
    (cg / "cgroup.procs").write_text("\n".join(str(p) for p in fake_pids) + "\n", encoding="utf-8")

    orig_read_bytes = Path.read_bytes
    orig_read_text = Path.read_text

    def _fake_read_bytes(self: Path):
        s = str(self)
        if s.startswith("/proc/9100") and s.endswith("/cmdline"):
            return b"python3\x00core/video_pipeline_4k.py\x00--job\x00job.json"
        return orig_read_bytes(self)

    def _fake_read_text(self: Path, *args, **kwargs):
        s = str(self)
        if s.startswith("/proc/9100") and s.endswith("/comm"):
            return "python3\n"
        return orig_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _fake_read_bytes)
    monkeypatch.setattr(Path, "read_text", _fake_read_text)
    monkeypatch.setattr(trg, "_count_runnable_threads", lambda pid: 3 if pid in fake_pids else 0)

    pressure_rows, oversub = trg._inspect_cgroup_units(units=("tardis.service",), cgroup_app_slice=app_slice)
    assert len(pressure_rows) == 1
    assert pressure_rows[0]["unit"] == "tardis.service"
    assert pressure_rows[0]["pids_count"] == 4
    assert pressure_rows[0]["psi_some_avg60"] == 42.10

    assert len(oversub) == 1
    assert oversub[0]["unit"] == "tardis.service"
    assert oversub[0]["runnable_threads"] == 12
    assert oversub[0]["active_pids"] == 4
    assert oversub[0]["oversubscription_ratio"] == 1.5


def test_resource_governor_proactive_psi_load_admission_and_power_saver_step_down(tmp_path: Path, monkeypatch):
    from core import tardis_resource_governor as trg

    gov = trg.TardisResourceGovernor(
        db_path=tmp_path / "gov_proactive.db",
        throttle_state_file=tmp_path / "throttle_proactive.json",
    )

    # 1) YELLOW con load1=19.36 y PSI60=39.4% -> debe cerrar heavy_learning/idle_evolution y activar trigger ORANGE
    monkeypatch.setattr(trg, "_read_meminfo_mb", lambda: {"total_mb": 32000.0, "available_mb": 8500.0, "used_mb": 23500.0, "used_pct": 73.4, "swap_total_mb": 32000.0, "swap_used_mb": 3200.0})
    monkeypatch.setattr(trg, "_parse_psi_file", lambda _p: {"some_avg10": 42.0, "some_avg60": 39.4, "some_avg300": 20.0, "full_avg10": 0.0, "full_avg60": 0.0})
    monkeypatch.setattr(trg, "_read_cpu_thermal", lambda: {"temp_c": 75.0, "source": "k10temp", "fan_rpm": {}})
    monkeypatch.setattr(trg, "_read_cpu_power_profile", lambda: {"power_profile": "balanced", "scaling_driver": "amd-pstate-epp", "scaling_governor": "powersave", "epp": "balance_performance", "boost": True})
    monkeypatch.setattr(trg, "_read_gpu", lambda: {"available": True, "temp_c": 71.0, "util_pct": 10.0, "vram_used_mb": 3500.0, "vram_free_mb": 4500.0, "vram_total_mb": 8000.0, "vram_used_pct": 43.8})
    monkeypatch.setattr(trg, "_inspect_cgroup_units", lambda *a, **kw: ([], []))
    monkeypatch.setattr(trg, "_query_ollama_ps", lambda _p: [])
    monkeypatch.setattr(trg, "_is_call_active", lambda: False)
    monkeypatch.setattr(trg, "_read_loadavg", lambda: (19.36, 12.5, 8.0))
    monkeypatch.setattr(trg.os, "cpu_count", lambda: 16)

    snap_yellow = gov.collect_snapshot(persist=False)
    assert snap_yellow["level"] == "YELLOW"
    assert snap_yellow["admission"]["heavy_learning"] is False
    assert snap_yellow["admission"]["idle_evolution"] is False
    assert trg._resolve_throttle_target_level(snap_yellow) == "ORANGE"

    # 2) PSI60=46.0% + load1=20.80 (>= 1.25 * 16) -> escalación proactiva directa a ORANGE antes de llegar a RED
    monkeypatch.setattr(trg, "_parse_psi_file", lambda _p: {"some_avg10": 50.0, "some_avg60": 46.0, "some_avg300": 25.0, "full_avg10": 0.0, "full_avg60": 0.0})
    monkeypatch.setattr(trg, "_read_loadavg", lambda: (20.80, 14.0, 9.0))
    snap_orange = gov.collect_snapshot(persist=False)
    assert snap_orange["level"] == "ORANGE"
    assert any("Contención combinada CPU PSI/Load" in r for r in snap_orange["reasons"])

    # 3) _needs_power_profile_step_down: cuando ya está ORANGE+balanced y GPU sube a 79°C -> debe pedir step-down a power-saver
    hot_orange_snap = {
        "level": "ORANGE",
        "cpu": {"cores": 16, "load1": 6.0, "psi": {"some_avg60": 40.0}, "temp_c": 83.0, "power_profile": "balanced"},
        "gpu": {"available": True, "temp_c": 79.0},
    }
    st_balanced = {"active": True, "level": "ORANGE", "power_profile_applied": "balanced"}
    st_power_saver = {"active": True, "level": "ORANGE", "power_profile_applied": "power-saver"}
    assert trg._needs_power_profile_step_down(hot_orange_snap, "ORANGE", st_balanced) is True
    assert trg._needs_power_profile_step_down(hot_orange_snap, "ORANGE", st_power_saver) is False


def test_semantic_cache_l1_l2_anti_anisotropy_volatility_and_prompt_router(tmp_path: Path, monkeypatch):
    import numpy as np
    from core import tardis_semantic_cache as tsc

    cache = tsc.TardisSemanticCache(
        db_path=tmp_path / "sem_cache.db",
        embed_socket="/nonexistent/embed.sock",
        similarity_threshold=0.94,
    )
    monkeypatch.setattr(tsc, "_read_governor_state_fast", lambda: {"ok": True, "level": "GREEN", "call_priority_active": False})

    # Simular embeddings de cono estrecho (anisotropía tipo multilingual-e5-small) donde incluso textos distintos tienen cos ~0.96
    base_v = np.zeros(384, dtype=np.float32)
    base_v[0] = 0.985
    base_v[1] = 0.172
    para_v = np.zeros(384, dtype=np.float32)
    para_v[0] = 0.990
    para_v[1] = 0.141
    unrel_v = np.zeros(384, dtype=np.float32)
    unrel_v[0] = 0.975
    unrel_v[1] = 0.222  # cos(base_v, unrel_v) > 0.99 pero sin solapamiento léxico!

    def _fake_embed(text: str, *, conn=None):
        low = text.lower()
        if "gobernador" in low and "manera" in low:
            return para_v / np.linalg.norm(para_v)
        if "gobernador" in low:
            return base_v / np.linalg.norm(base_v)
        return unrel_v / np.linalg.norm(unrel_v)

    monkeypatch.setattr(cache, "embed_query", _fake_embed)

    st = cache.store(
        "Explica cómo mitiga el gobernador de recursos la presión CPU PSI en puerto 8757",
        "El gobernador aplica cuotas cgroup v2 y perfil energético adaptativo.",
        model="TARDIS-NEURAL-SPACE-KAIJU",
        namespace="background",
        elapsed_ms=2200.0,
        usage={"prompt_tokens": 40, "completion_tokens": 60},
    )
    assert st["ok"] and st["stored"] is True and st["semantic_indexed"] is True

    # 1) L1 Exact Hit (<1ms, 0 llamadas extra)
    h1 = cache.lookup(
        "  Explica cómo mitiga el gobernador de recursos la presión CPU PSI en puerto 8757 ",
        model="TARDIS-NEURAL-SPACE-KAIJU",
        namespace="background",
    )
    assert h1["hit"] is True and h1["match_type"] == "exact" and h1["tokens_saved"] == 100

    # 2) L2 Semantic Hit (paráfrasis real con mismo puerto 8757)
    h2 = cache.lookup(
        "Explica de qué manera el gobernador de recursos mitiga la presión CPU PSI en puerto 8757",
        model="TARDIS-NEURAL-SPACE-KAIJU",
        namespace="background",
    )
    assert h2["hit"] is True and h2["match_type"] == "semantic" and h2["similarity"] >= 0.94

    # 3) Guarda de discriminador numérico: puerto distinto (11435 vs 8757) JAMÁS debe colisionar
    h_port = cache.lookup(
        "Explica de qué manera el gobernador de recursos mitiga la presión CPU PSI en puerto 11435",
        model="TARDIS-NEURAL-SPACE-KAIJU",
        namespace="background",
    )
    assert h_port["hit"] is False

    # 4) Guarda anti-anisotropía: prompt totalmente distinto con cos > 0.99 JAMÁS debe producir falso positivo
    h_unrel = cache.lookup(
        "Receta tradicional para hornear pan de centeno con masa madre",
        model="TARDIS-NEURAL-SPACE-KAIJU",
        namespace="background",
    )
    assert h_unrel["hit"] is False

    # 5) Guarda de volatilidad y temperatura alta
    h_vol = cache.lookup("¿Qué hora es ahora mismo en el sistema?", namespace="background")
    assert h_vol["hit"] is False and h_vol["reason"] == "volatile_prompt_bypass"
    h_temp = cache.lookup(
        "Explica cómo mitiga el gobernador de recursos la presión CPU PSI en puerto 8757",
        namespace="background",
        temperature=0.95,
    )
    assert h_temp["hit"] is False and h_temp["reason"] == "high_temperature_bypass"

    # 6) Prompt Router: acierto en caché -> semantic_cache; llamada Telegram activa -> defer; RED -> defer
    rt_hit = cache.route_prompt(
        "Explica cómo mitiga el gobernador de recursos la presión CPU PSI en puerto 8757",
        model="TARDIS-NEURAL-SPACE-KAIJU",
        namespace="background",
        task_class="background",
    )
    assert rt_hit["lane"] == "semantic_cache" and rt_hit["cache_hit"] is True

    rt_call = cache.route_prompt(
        "Consulta nueva no cacheada sobre arquitectura",
        namespace="background",
        task_class="background",
        check_cache=False,
        governor_snapshot={"level": "RED", "call_priority_active": True},
    )
    assert rt_call["lane"] == "defer" and rt_call["should_defer"] is True

    stats = cache.stats()
    assert stats["counters"]["exact_hits"] == 2  # h1 + rt_hit
    assert stats["counters"]["semantic_hits"] == 1
    assert stats["savings"]["tokens_saved_total"] == 300
    assert stats["savings"]["cpu_ms_saved"] >= 6600.0


def test_resource_governor_gpu_eco_pstate_and_hyprland_lifecycle(tmp_path: Path, monkeypatch):
    from core import tardis_resource_governor as trg

    gov = trg.TardisResourceGovernor(
        db_path=tmp_path / "gov_gpu.db",
        throttle_state_file=tmp_path / "throttle_gpu.json",
        gpu_eco_state_file=tmp_path / "gpu_eco.json",
    )
    monkeypatch.setattr(trg, "_gpu_eco_control_enabled", lambda: True)

    # 1) Reglas puras de decisión _resolve_gpu_eco_mode
    idle_headless_snap = {
        "level": "GREEN",
        "call_priority_active": False,
        "gpu": {"available": True, "pstate": "P0", "temp_c": 56.0, "util_pct": 2.0, "power_w": 12.0},
    }
    disp_headless = {"connected_displays": 0, "total_connectors": 3, "headless_or_display_off": True, "hyprland_signature": "sig1", "temporal_brain_busy": False}
    disp_busy_cuda = {**disp_headless, "temporal_brain_busy": True}
    assert trg._resolve_gpu_eco_mode(idle_headless_snap, disp_headless) == "eco_idle"
    # Con inferencia CUDA activa en TemporalBrain -> NUNCA degrada relojes (<84°C)
    assert trg._resolve_gpu_eco_mode(idle_headless_snap, disp_busy_cuda) == "normal"
    # Con llamada Telegram activa -> siempre normal
    assert trg._resolve_gpu_eco_mode({**idle_headless_snap, "call_priority_active": True}, disp_headless) == "normal"
    # En RED térmico (GPU 85°C) -> eco_thermal (P5)
    hot_red_snap = {
        "level": "RED",
        "call_priority_active": False,
        "gpu": {"available": True, "pstate": "P0", "temp_c": 85.0, "util_pct": 18.0, "power_w": 33.0},
    }
    assert trg._resolve_gpu_eco_mode(hot_red_snap, disp_headless) == "eco_thermal"

    # 2) Ciclo completo reversible: normal -> eco_idle (P8 + Hyprland eco) -> normal (unlock + restaurar Hyprland)
    gpu_calls = []
    hypr_state = {"animations:enabled": 1, "decoration:blur:enabled": 1, "decoration:shadow:enabled": 1}

    def _fake_cap(mode: str):
        gpu_calls.append(mode)
        return True, ("clocks_unlocked" if mode == "normal" else f"capped_{mode}")

    monkeypatch.setattr(trg, "_apply_nvidia_clock_cap", _fake_cap)
    monkeypatch.setattr(trg, "_hyprctl_get_bool", lambda sig, opt: hypr_state.get(opt))

    def _fake_hypr_set(sig: str, opt: str, val):
        hypr_state[opt] = int(val)
        return True

    monkeypatch.setattr(trg, "_hyprctl_set_keyword", _fake_hypr_set)
    monkeypatch.setattr(trg, "_read_display_session_state", lambda: disp_headless)

    res_eco = gov.reconcile_gpu_eco(idle_headless_snap, dry_run=False)
    assert res_eco["ok"] is True and res_eco["action"] == "switched_to_eco_idle"
    assert gpu_calls == ["eco_idle"]
    assert all(v == 0 for v in hypr_state.values())
    assert gov.get_gpu_eco_status()["mode"] == "eco_idle"

    # Al activarse TemporalBrain (CUDA busy) -> desbloqueo instantáneo y restauración de Hyprland
    monkeypatch.setattr(trg, "_read_display_session_state", lambda: disp_busy_cuda)
    res_norm = gov.reconcile_gpu_eco(idle_headless_snap, dry_run=False)
    assert res_norm["ok"] is True and res_norm["action"] == "switched_to_normal"
    assert gpu_calls == ["eco_idle", "normal"]
    assert all(v == 1 for v in hypr_state.values())
    assert gov.get_gpu_eco_status()["mode"] == "normal"


def test_embed_isotropy_calibrator_zca_and_abtt_collapse_cone_and_boost_retrieval(tmp_path: Path, monkeypatch):
    import numpy as np
    from core.embed_isotropy import EmbedIsotropyCalibrator, _measure_random_pair_isotropy
    from core import tardis_semantic_cache as tsc

    rng = np.random.default_rng(7)
    n_docs, dim = 200, 64
    # Construir un corpus fuertemente anisotrópico (cono estrecho alrededor de una dirección dominante,
    # análogo al fenómeno medido en embed-e5-small.gguf con coseno medio > 0.90)
    cone_dir = rng.normal(size=(1, dim)).astype(np.float32)
    cone_dir /= np.linalg.norm(cone_dir)
    semantic_signal = rng.normal(scale=0.04, size=(n_docs, dim)).astype(np.float32)
    M_raw = cone_dir + semantic_signal
    M_raw /= np.linalg.norm(M_raw, axis=1, keepdims=True)

    raw_mean, _ = _measure_random_pair_isotropy(M_raw)
    assert raw_mean > 0.85

    # 1) Regularized ZCA Whitening debe colapsar el coseno medio aleatorio cerca de 0 y preservar exactitud en disco
    art_path = tmp_path / "iso_cal.npz"
    cal_zca = EmbedIsotropyCalibrator(artifact_path=art_path, method="zca_whitening", reg=5e-5, alpha=0.50)
    meta = cal_zca.fit(M_raw, min_samples=32)
    assert meta["ok"] and meta["fitted"] is True
    assert meta["raw_rand_cosine_mean"] > 0.85
    assert abs(meta["calibrated_rand_cosine_mean"]) < 0.08
    assert meta["isotropy_gain"] > 0.75

    # Guardar y recargar desde disco (.npz + .json) debe reproducir la transformación al 100%
    assert cal_zca.save() is True
    cal_loaded = EmbedIsotropyCalibrator(artifact_path=art_path)
    assert cal_loaded.load() is True
    assert np.allclose(cal_zca.transform(M_raw[:10]), cal_loaded.transform(M_raw[:10]), atol=1e-5)

    # 2) All-but-the-Top (ABTT d=2) también debe colapsar la anisotropía
    cal_abtt = EmbedIsotropyCalibrator(artifact_path=tmp_path / "iso_abtt.npz", method="abtt", abtt_dims=2)
    meta_abtt = cal_abtt.fit(M_raw, min_samples=32)
    assert meta_abtt["ok"] and abs(meta_abtt["calibrated_rand_cosine_mean"]) < 0.08

    # 3) Integración en TardisSemanticCache: rechaza falso positivo anisotrópico cuando iso_sim < min_isotropic_similarity
    cache = tsc.TardisSemanticCache(
        db_path=tmp_path / "sem_iso.db",
        embed_socket="/nonexistent/embed.sock",
        similarity_threshold=0.90,
        min_lexical_overlap=0.0,  # probar que el filtro isotrópico ZCA por sí solo frena colisiones de cono
        min_isotropic_similarity=0.50,
        isotropy_calibrator=cal_loaded,
    )
    monkeypatch.setattr(tsc, "_read_governor_state_fast", lambda: {"ok": True, "level": "GREEN", "call_priority_active": False})

    # Dos documentos distintos dentro del mismo cono anisotrópico (raw cos > 0.90, pero ZCA iso_sim ~ 0)
    v_doc0 = M_raw[0]
    v_para0 = v_doc0 + rng.normal(scale=0.015, size=(dim,)).astype(np.float32)
    v_para0 /= np.linalg.norm(v_para0)
    v_other = M_raw[1]
    assert float(np.dot(v_doc0, v_other)) > 0.85

    def _fake_embed(text: str, *, conn=None):
        if "parafrasis" in text:
            return v_para0
        if "ajena" in text:
            return v_other
        return v_doc0

    monkeypatch.setattr(cache, "embed_query", _fake_embed)
    cache.store("consulta original kernel linux", "respuesta verificada", namespace="background")

    hit_para = cache.lookup("parafrasis cercana kernel linux", namespace="background")
    assert hit_para["hit"] is True and hit_para["match_type"] == "semantic"
    assert hit_para["isotropic_similarity"] >= 0.50

    miss_other = cache.lookup("consulta ajena totalmente distinta", namespace="background")
    assert miss_other["hit"] is False
    assert cache.stats()["isotropy_calibration"]["fitted"] is True


def test_eval_harness_all_suites_baseline_comparison_and_regression_detection(tmp_path: Path):
    from core.tardis_eval_harness import TardisEvalHarness

    harness = TardisEvalHarness(db_path=tmp_path / "eval_test.db")

    class _MockRAG:
        def search(self, query: str, k: int = 5, hybrid: bool = True):
            return [
                {
                    "title": f"Doc {query[:20]}",
                    "term": "tardis",
                    "text": "Gobernador de recursos CPU PSI Linux RAG embeddings vector busqueda AEGIS seguridad kernel escudo",
                    "score": 0.85,
                }
            ]

        def stats(self):
            return {"chunks": 23800, "isotropy_calibration": {"fitted": True, "isotropy_gain": 0.92}}

    class _MockCache:
        def stats(self):
            return {"ok": True, "enabled": True}

    def _fast_probe(_ep: str):
        return True, 18.5

    def _mock_judge(_prompt: str) -> str:
        return '```json\n{"accuracy": 9, "completeness": 9, "safety": 10, "conciseness": 8, "verdict": "pass"}\n```'

    # 1) Ejecutar Golden Baseline con todas las suites incluyendo LLM-as-judge
    base = harness.run_eval(
        include_llm_judge=True,
        tag="baseline",
        rag_vault=_MockRAG(),
        semantic_cache=_MockCache(),
        latency_probe_fn=_fast_probe,
        judge_fn=_mock_judge,
        latency_samples=2,
    )
    assert base["ok"] is True
    assert base["passed"] is True
    assert base["overall_score"] >= 90.0
    assert base["suites"]["aegis"]["redaction_violations"] == 0
    assert base["suites"]["aegis"]["f1"] >= 0.85
    assert base["suites"]["tool_calling"]["score"] == 100.0
    assert base["suites"]["rag"]["isotropy_fitted"] is True
    assert base["suites"]["latency"]["score"] == 100.0
    assert base["suites"]["llm_judge"]["judge_mode"] == "custom_judge"
    assert base["suites"]["llm_judge"]["score"] == 90.0

    # 2) Ejecutar candidato post-evolución degradado (latencia P95 explotada + RAG vacío) -> debe detectar regresiones
    class _BrokenRAG:
        def search(self, query: str, k: int = 5, hybrid: bool = True):
            return []

        def stats(self):
            return {"chunks": 0, "isotropy_calibration": {"fitted": False, "isotropy_gain": 0.0}}

    def _slow_probe(_ep: str):
        return True, 650.0

    cand = harness.run_eval(
        include_llm_judge=True,
        tag="post_evolution",
        canary_run_id="canary_test_123",
        rag_vault=_BrokenRAG(),
        semantic_cache=_MockCache(),
        latency_probe_fn=_slow_probe,
        judge_fn=None,
        use_live_llm_judge=False,
        latency_samples=2,
    )
    assert cand["ok"] is True
    assert cand["passed"] is False
    assert cand["baseline_eval_id"] == base["eval_id"]
    scopes = {r["scope"] for r in cand["regressions"]}
    assert "overall" in scopes
    assert "rag" in scopes
    assert "latency" in scopes

    # 3) Verificar persistencia SQLite WAL, compare_runs() y status()
    cmp_res = harness.compare_runs(base["eval_id"], cand["eval_id"])
    assert cmp_res["ok"] is True and cmp_res["has_regression"] is True
    st = harness.status()
    assert st["total_runs"] == 2
    assert st["runs_with_regressions"] == 1
    assert st["baseline"]["eval_id"] == base["eval_id"]


def test_memory_compactor_rag_simhash_kg_dedup_offline_and_deep_memory(tmp_path: Path):
    import sqlite3
    import numpy as np
    from core.tardis_memory_compactor import TardisMemoryCompactor

    # 1) Crear bóveda RAG aislada con duplicado exacto, cuasi-duplicado SimHash/coseno, FTS5 contentless y 6 chunks para RAPTOR L1
    rag_db = tmp_path / "rag_test.db"
    con = sqlite3.connect(str(rag_db))
    con.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE rag_chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, source TEXT, url TEXT, title TEXT, term TEXT, text TEXT, ts REAL, chunk_hash TEXT UNIQUE);
        CREATE TABLE rag_vectors (chunk_id INTEGER PRIMARY KEY, vec BLOB NOT NULL, FOREIGN KEY(chunk_id) REFERENCES rag_chunks(id) ON DELETE CASCADE);
        CREATE VIRTUAL TABLE rag_fts USING fts5(text, title, term, content='');
        CREATE TABLE rag_relations (id INTEGER PRIMARY KEY AUTOINCREMENT, source_term TEXT, relation TEXT, target_term TEXT, evidence TEXT, chunk_id INTEGER, weight REAL, ts REAL);
        CREATE TABLE rag_summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, level INTEGER, title TEXT, summary TEXT, cluster_tag TEXT, chunk_ids TEXT, ts REAL);
        """
    )
    base_vec = np.ones(16, dtype=np.float32)
    base_vec /= np.linalg.norm(base_vec)
    other_vec = np.linspace(1.0, -1.0, 16, dtype=np.float32)
    other_vec /= np.linalg.norm(other_vec)

    base_txt = "El gobernador de recursos Ring 0 mitiga la presion sostenida de silicio en Linux mediante cuotas cgroup v2 y perfil energetico adaptativo."
    near_txt = "El gobernador de recursos Ring 0 mitiga la presion sostenida de silicio en Linux mediante cuotas cgroup v2 y perfil energetico adaptativo!"
    chunks_seed = [
        ("doc_a", "docs", "Gobernador Ring 0", "governor", base_txt, "h1", base_vec),
        ("doc_a", "docs", "Gobernador Ring 0", "governor", base_txt + "   ", "h2", base_vec),  # exact norm dup
        ("doc_a", "docs", "Gobernador Ring 0", "governor", near_txt, "h3", base_vec),           # simhash + cosine dup
    ]
    for i in range(6):
        distinct_v = np.roll(other_vec, i)
        chunks_seed.append((
            "doc_ep",
            "research",
            "Arquitectura Soberana TARDIS",
            f"tema_{i}",
            f"Capitulo {i} sobre arquitecturas distribuidas autonomas de memoria cuantica y grafos transversales con numero unico {1000 + i * 77}.",
            f"h_ep_{i}",
            distinct_v,
        ))

    for doc_id, src, title, term, txt, h, vec in chunks_seed:
        cur = con.execute(
            "INSERT INTO rag_chunks(doc_id,source,url,title,term,text,ts,chunk_hash) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, src, "", title, term, txt, 1000.0, h),
        )
        cid = cur.lastrowid
        con.execute("INSERT INTO rag_vectors(chunk_id, vec) VALUES (?,?)", (cid, vec.tobytes()))
        con.execute("INSERT INTO rag_fts(rowid, text, title, term) VALUES (?,?,?,?)", (cid, txt, title, term))
    con.execute("INSERT INTO rag_relations(source_term,relation,target_term,evidence,chunk_id,weight,ts) VALUES ('gov','optimiza','cpu','ev',2,1.0,1000.0)")
    con.commit()
    con.close()

    # 2) Crear KnowledgeGraph aislado con nodos duplicados ("El video", "- El video", "el video") y aristas colisionando
    kg_db = tmp_path / "kg_test.db"
    con = sqlite3.connect(str(kg_db))
    con.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE kg_nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, entity_type TEXT, description TEXT, metadata TEXT, ts REAL);
        CREATE TABLE kg_edges (id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER, target_id INTEGER, relation TEXT, weight REAL, evidence TEXT, ts REAL, FOREIGN KEY(source_id) REFERENCES kg_nodes(id) ON DELETE CASCADE, FOREIGN KEY(target_id) REFERENCES kg_nodes(id) ON DELETE CASCADE, UNIQUE(source_id, target_id, relation));
        CREATE TABLE kg_communities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, summary TEXT, level INTEGER, node_ids TEXT, ts REAL);
        """
    )
    con.execute("INSERT INTO kg_nodes VALUES (1, 'El video', 'concept', 'Descripcion larga', '{}', 100.0)")
    con.execute("INSERT INTO kg_nodes VALUES (2, '- El video', 'concept', '', '{}', 101.0)")
    con.execute("INSERT INTO kg_nodes VALUES (3, 'el video', 'concept', '', '{}', 102.0)")
    con.execute("INSERT INTO kg_nodes VALUES (4, 'TARDIS', 'system', 'Nucleo soberano', '{}', 103.0)")
    con.execute("INSERT INTO kg_nodes VALUES (5, 'Kernel Linux', 'system', 'Ring 0', '{}', 104.0)")
    con.execute("INSERT INTO kg_edges VALUES (1, 1, 4, 'analiza', 1.0, '', 100.0)")
    con.execute("INSERT INTO kg_edges VALUES (2, 2, 4, 'analiza', 2.5, '', 101.0)")  # debe sumar peso -> 3.5 en (1,4)
    con.execute("INSERT INTO kg_edges VALUES (3, 1, 3, 'igual_a', 1.0, '', 102.0)")  # se vuelve auto-lazo -> eliminar
    con.execute("INSERT INTO kg_edges VALUES (4, 4, 5, 'opera_en', 1.0, '', 103.0)")
    con.commit()
    con.close()

    # 3) Crear OfflineChat aislado con turno eco-duplicado dentro de 120s
    oc_db = tmp_path / "offline_test.db"
    con = sqlite3.connect(str(oc_db))
    con.executescript(
        """
        CREATE TABLE offline_chat_turns (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, iso TEXT, session_id TEXT, client_id TEXT, user_message TEXT, assistant_reply TEXT);
        CREATE VIRTUAL TABLE offline_chat_fts USING fts5(user_message, assistant_reply, session_id, turn_id UNINDEXED);
        """
    )
    con.execute("INSERT INTO offline_chat_turns VALUES (1, 1000.0, '2026-11-24', 's1', 'c1', 'hola tardis', 'hola arquitecto')")
    con.execute("INSERT INTO offline_chat_turns VALUES (2, 1020.0, '2026-11-24', 's1', 'c1', 'hola tardis', 'hola arquitecto')")
    con.execute("INSERT INTO offline_chat_turns VALUES (3, 5000.0, '2026-11-24', 's1', 'c1', 'hola tardis', 'hola arquitecto')")  # >120s: conservar!
    con.commit()
    con.close()

    comp = TardisMemoryCompactor(db_path=tmp_path / "compactor_ledger.db")

    # Dry-run NO debe mutar ninguna fila
    dry = comp.run_compaction(
        targets=("rag", "kg", "offline_chats"),
        dry_run=True,
        rag_db=rag_db,
        kg_db=kg_db,
        offline_chat_db=oc_db,
    )
    assert dry["ok"] is True and dry["dry_run"] is True
    assert dry["targets"]["rag"]["duplicates_pruned"] == 2
    assert dry["targets"]["kg"]["nodes_merged"] == 2
    assert dry["targets"]["offline_chats"]["duplicates_pruned"] == 1

    # Ejecución real debe podar duplicados, consolidar pesos/episodios y dejar bases íntegras
    real = comp.run_compaction(
        targets=("rag", "kg", "offline_chats"),
        dry_run=False,
        force=True,
        rag_db=rag_db,
        kg_db=kg_db,
        offline_chat_db=oc_db,
    )
    assert real["ok"] is True and real["dry_run"] is False
    assert real["targets"]["rag"]["duplicates_pruned"] == 2
    assert real["targets"]["rag"]["episodes_consolidated"] == 1
    assert real["targets"]["kg"]["nodes_merged"] == 2
    assert real["targets"]["kg"]["communities_created"] >= 1
    assert real["targets"]["offline_chats"]["duplicates_pruned"] == 1

    # Verificar integridad post-compactación en SQLite
    con_r = sqlite3.connect(str(rag_db))
    assert con_r.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0] == 7
    assert con_r.execute("SELECT COUNT(*) FROM rag_vectors").fetchone()[0] == 7
    assert con_r.execute("SELECT chunk_id FROM rag_relations WHERE id = 1").fetchone()[0] == 1  # re-enlazado al canónico
    assert con_r.execute("SELECT COUNT(*) FROM rag_summaries").fetchone()[0] == 1
    con_r.close()

    con_k = sqlite3.connect(str(kg_db))
    assert con_k.execute("SELECT COUNT(*) FROM kg_nodes").fetchone()[0] == 3
    w_merged = con_k.execute("SELECT weight FROM kg_edges WHERE source_id=1 AND target_id=4 AND relation='analiza'").fetchone()[0]
    assert abs(float(w_merged) - 3.5) < 1e-6
    assert con_k.execute("SELECT COUNT(*) FROM kg_edges WHERE source_id = target_id").fetchone()[0] == 0
    con_k.close()

    con_o = sqlite3.connect(str(oc_db))
    assert con_o.execute("SELECT COUNT(*) FROM offline_chat_turns").fetchone()[0] == 2
    con_o.close()


def test_memory_compactor_telemetry_ttl_rollups_and_wal_migration(tmp_path: Path):
    import sqlite3
    import time as _time
    from core.tardis_memory_compactor import TardisMemoryCompactor

    now = _time.time()
    old_20d = now - (20 * 86400.0)
    old_10d = now - (10 * 86400.0)
    fresh_1d = now - (1 * 86400.0)

    # 1) Crear subsystem_agents.db en journal_mode=delete con filas expiradas (>14d) y frescas (<=14d)
    sa_db = tmp_path / "subsystem_agents_test.db"
    con = sqlite3.connect(str(sa_db))
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute(
        "CREATE TABLE cycles (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, subsystem TEXT, health TEXT, findings INTEGER, findings_json TEXT, applied_json TEXT, proposals_json TEXT)"
    )
    con.executemany(
        "INSERT INTO cycles (ts,subsystem,health,findings,findings_json,applied_json,proposals_json) VALUES (?,?,?,?,?,?,?)",
        [
            (old_20d, "chat", "online", 2, "{}", "[]", "[]"),
            (old_20d + 60, "chat", "degraded", 5, "{}", "[]", "[]"),
            (old_10d, "chat", "online", 1, "{}", "[]", "[]"),
            (fresh_1d, "shield", "online", 0, "{}", "[]", "[]"),
        ],
    )
    con.commit()
    con.close()

    # 2) Crear gods_eye.db en journal_mode=delete con detecciones (>7d y <=7d) y eventos (>14d y <=14d)
    ge_db = tmp_path / "gods_eye_test.db"
    con = sqlite3.connect(str(ge_db))
    con.execute("PRAGMA journal_mode=DELETE")
    con.executescript(
        """
        CREATE TABLE detections (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, terminal_id TEXT, cell TEXT, motion REAL, objects INTEGER, centroid_x REAL, centroid_y REAL, histogram TEXT);
        CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, terminal_id TEXT, zone TEXT, detail TEXT, confidence REAL);
        """
    )
    con.executemany(
        "INSERT INTO detections (ts,terminal_id,cell,motion,objects,centroid_x,centroid_y,histogram) VALUES (?,?,?,?,?,?,?,?)",
        [
            (old_10d, "cam1", "c1", 0.25, 1, 0.5, 0.5, "[0.1]"),
            (old_10d + 30, "cam1", "c2", 0.75, 2, 0.4, 0.6, "[0.2]"),
            (fresh_1d, "cam1", "c1", 0.10, 0, 0.5, 0.5, "[0.0]"),
        ],
    )
    con.executemany(
        "INSERT INTO events (ts,kind,terminal_id,zone,detail,confidence) VALUES (?,?,?,?,?,?)",
        [
            (old_20d, "motion", "cam1", "z1", "d1", 0.8),
            (fresh_1d, "person", "cam1", "z1", "d2", 0.95),
        ],
    )
    con.commit()
    con.close()

    comp = TardisMemoryCompactor(db_path=tmp_path / "comp_ttl.db")

    # Dry-run NO muta journal_mode ni filas
    dry = comp.run_compaction(
        targets=("subsystem_agents", "gods_eye"),
        dry_run=True,
        subsystem_agents_db=sa_db,
        gods_eye_db=ge_db,
    )
    assert dry["ok"] is True
    assert dry["targets"]["subsystem_agents"]["expired_rows_pruned"] == 2
    assert dry["targets"]["gods_eye"]["detections_pruned"] == 2
    assert dry["targets"]["gods_eye"]["events_pruned"] == 1

    # Ejecución real: migra a WAL, consolida rollups diarios y poda solo lo expirado
    real = comp.run_compaction(
        targets=("subsystem_agents", "gods_eye"),
        dry_run=False,
        force=True,
        subsystem_agents_db=sa_db,
        gods_eye_db=ge_db,
    )
    assert real["ok"] is True
    assert real["targets"]["subsystem_agents"]["journal_mode_before"] == "delete"
    assert real["targets"]["subsystem_agents"]["journal_mode_after"] == "wal"
    assert real["targets"]["subsystem_agents"]["expired_rows_pruned"] == 2
    assert real["targets"]["subsystem_agents"]["rollup_groups_saved"] == 1

    assert real["targets"]["gods_eye"]["journal_mode_before"] == "delete"
    assert real["targets"]["gods_eye"]["journal_mode_after"] == "wal"
    assert real["targets"]["gods_eye"]["detections_pruned"] == 2
    assert real["targets"]["gods_eye"]["events_pruned"] == 1

    # Validar integridad de datos frescos + rollups acumulados
    con_sa = sqlite3.connect(str(sa_db))
    assert con_sa.execute("SELECT COUNT(*) FROM cycles").fetchone()[0] == 2
    r_sa = con_sa.execute("SELECT cycles_count, ok_count, degraded_count, total_findings FROM cycles_daily_rollup").fetchone()
    assert r_sa == (2, 1, 1, 7)
    con_sa.close()

    con_ge = sqlite3.connect(str(ge_db))
    assert con_ge.execute("SELECT COUNT(*) FROM detections").fetchone()[0] == 1
    assert con_ge.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    r_det = con_ge.execute("SELECT detections_count, max_motion, total_objects FROM detections_daily_rollup").fetchone()
    assert r_det[0] == 2 and abs(float(r_det[1]) - 0.75) < 1e-6 and r_det[2] == 3
    r_evt = con_ge.execute("SELECT events_count, kind FROM events_daily_rollup").fetchone()
    assert r_evt == (1, "motion")
    con_ge.close()


def test_ollama_cpuset_thread_governance_and_kaiju_boot_race_guard(tmp_path: Path, monkeypatch):
    """Regresión COEV-20261124-0A569D: evita -t 16 en cpuset 8-15 y bloquea duplicado KAIJU en :11434 durante warmup."""
    import io
    import json
    import urllib.request
    import gia_sovereign_engine as gse
    from engine.sovereign_client import SovereignClient
    from core.temporal_brain import TemporalBrain

    # 1) _resolve_safe_cpu_ollama_threads respeta cpuset.cpus.effective y cpu.max en cgroup v2
    fake_slice = tmp_path / "app.slice"
    cg = fake_slice / "ollama.service"
    cg.mkdir(parents=True)
    (cg / "cpuset.cpus.effective").write_text("8-15\n", encoding="utf-8")
    (cg / "cpu.max").write_text("max 100000\n", encoding="utf-8")

    monkeypatch.setenv("GIA_NUM_THREADS", "16")
    monkeypatch.delenv("GIA_CPU_OLLAMA_THREADS", raising=False)
    assert gse._resolve_safe_cpu_ollama_threads(cgroup_app_slice=fake_slice) == 4
    assert gse._resolve_safe_cpu_ollama_threads(16, cgroup_app_slice=fake_slice) == 4
    assert gse._resolve_safe_cpu_ollama_threads(2, cgroup_app_slice=fake_slice) == 2

    # Con throttling cgroup (CPUQuota=200% -> 2 cores; CPUQuota=100% -> 1 core)
    (cg / "cpu.max").write_text("200000 100000\n", encoding="utf-8")
    assert gse._resolve_safe_cpu_ollama_threads(16, cgroup_app_slice=fake_slice) == 2
    (cg / "cpu.max").write_text("100000 100000\n", encoding="utf-8")
    assert gse._resolve_safe_cpu_ollama_threads(16, cgroup_app_slice=fake_slice) == 1

    # Con cpuset reducido (4 CPUs -> <= 2 hilos)
    (cg / "cpuset.cpus.effective").write_text("12-15\n", encoding="utf-8")
    (cg / "cpu.max").write_text("max 100000\n", encoding="utf-8")
    assert gse._resolve_safe_cpu_ollama_threads(16, cgroup_app_slice=fake_slice) == 2

    # 2) _http_chat_stream hacia :11434 debe capear num_thread <= 4, num_batch <= 512, keep_alive=0 y omitir use_mlock
    captured_payloads = []

    class _FakeResp(io.BytesIO):
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        captured_payloads.append(json.loads(req.data.decode("utf-8")))
        return _FakeResp(b'{"message":{"content":"ok"},"done":true}\n')

    monkeypatch.setenv("GIA_NUM_THREADS", "16")
    monkeypatch.setenv("GIA_NUM_BATCH", "2048")
    monkeypatch.setenv("GIA_OLLAMA_FALLBACK_KEEP_ALIVE", "0")
    monkeypatch.setattr(gse, "_resolve_safe_cpu_ollama_threads", lambda *a, **k: 4)
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    monkeypatch.setattr(gse.SovereignInferenceEngine, "diagnose_and_heal", lambda self, **k: {"ok": True})
    monkeypatch.setattr(gse.SovereignInferenceEngine, "_start_keepalive_watchdog", lambda self: None)
    eng = gse.SovereignInferenceEngine()
    monkeypatch.setattr(eng, "find_working_endpoint", lambda model=None: "http://127.0.0.1:11434")
    tokens = list(eng._http_chat_stream([{"role": "user", "content": "hola"}], model="deepseek-r1:1.5b", num_ctx=16384))
    assert "".join(tokens) == "ok"
    assert len(captured_payloads) == 1
    p = captured_payloads[0]
    assert p["keep_alive"] == 0
    assert p["options"]["num_thread"] == 4
    assert p["options"]["num_batch"] == 512
    assert p["options"]["num_ctx"] == 8192
    assert "use_mlock" not in p["options"]

    # 3) SovereignClient._build_options también alinea num_thread <= 4 y omite use_mlock
    sc = SovereignClient()
    sc_opts = sc._build_options()
    assert 1 <= sc_opts["num_thread"] <= 4
    assert sc_opts["num_batch"] <= 512
    assert "use_mlock" not in sc_opts

    # 4) Anti-duplicación KAIJU durante warmup de TemporalBrain: nunca derrama hacia :11434
    monkeypatch.setenv("GIA_TEMPORAL_BRAIN_WAIT_SEC", "0.2")
    monkeypatch.setenv("GIA_TEMPORAL_BRAIN_POLL_SEC", "0.05")
    monkeypatch.setenv("GIA_ALLOW_KAIJU_CPU_DUPLICATE", "0")

    class _WarmingTB:
        def __init__(self, succeed_on_attempt: int = 999):
            self.calls = 0
            self.succeed_on_attempt = succeed_on_attempt
            self.socket_path = tmp_path / "temporal_brain.sock"
            self.socket_path.write_text("", encoding="utf-8")

        def is_serverless_ready(self, model_name=None):
            return True

        def chat_stream(self, *args, **kwargs):
            self.calls += 1
            if self.calls < self.succeed_on_attempt:
                raise RuntimeError("HTTP 503 Loading model")
            yield "listo-desde-tb"

    # 4a) Recuperación durante ventana de warmup -> responde por TemporalBrain sin tocar HTTP :11434
    tb_recover = _WarmingTB(succeed_on_attempt=2)
    monkeypatch.setattr(gse, "_TEMPORAL_BRAIN_ACTIVE", True)
    monkeypatch.setattr(gse, "get_temporal_brain", lambda: tb_recover)
    http_called = {"n": 0}
    monkeypatch.setattr(eng, "_http_chat_stream", lambda *a, **k: (http_called.__setitem__("n", http_called["n"] + 1) or iter(["bad"])))
    out_toks = list(eng.chat_stream([{"role": "user", "content": "ping"}], model="TARDIS-NEURAL-SPACE-KAIJU"))
    assert "".join(out_toks) == "listo-desde-tb"
    assert tb_recover.calls == 2
    assert http_called["n"] == 0

    # 4b) Si TemporalBrain sigue calentando al agotar presupuesto -> bloquea fallback duplicado KAIJU en :11434
    tb_stuck = _WarmingTB(succeed_on_attempt=999)
    monkeypatch.setattr(gse, "get_temporal_brain", lambda: tb_stuck)
    with pytest.raises(RuntimeError, match="fallback duplicado de KAIJU"):
        list(eng.chat_stream([{"role": "user", "content": "ping"}], model="TARDIS-NEURAL-SPACE-KAIJU"))
    assert http_called["n"] == 0

    # 5) TemporalBrain.chat() soporta múltiples HTTP 503 consecutivos de warmup antes de responder 200
    monkeypatch.setenv("TEMPORAL_BRAIN_WARMUP_WAIT_SEC", "1.0")
    monkeypatch.setenv("TEMPORAL_BRAIN_WARMUP_POLL_SEC", "0.05")
    tb_real = TemporalBrain()
    tb_real.socket_path = tmp_path / "tb_unit.sock"
    monkeypatch.setattr(tb_real, "is_running", lambda: True)

    class _FakeHttpResp:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    seq = [
        _FakeHttpResp(503, {"error": "Loading model"}),
        _FakeHttpResp(503, {"error": "Loading model"}),
        _FakeHttpResp(200, {"choices": [{"message": {"content": "warmup-ok"}}], "usage": {"completion_tokens": 2}}),
    ]

    class _FakeUdsClient:
        def post(self, *args, **kwargs):
            return seq.pop(0)

    monkeypatch.setattr(tb_real, "_get_uds_client", lambda timeout=None: _FakeUdsClient())
    res_tb = tb_real.chat([{"role": "user", "content": "hola"}], use_cache=False)
    assert res_tb["ok"] is True
    assert res_tb["reply"] == "warmup-ok"
    assert len(seq) == 0


def test_hub_health_retry_feedback_mass_flap_hysteresis_and_coevolution_full_bus_drain(tmp_path: Path, monkeypatch):
    """Regresión COEV-20261125-E31804: retry en hub_health, supresión de ola masiva/histéresis 2 ciclos y drenaje >40 eventos."""
    import urllib.request
    from core import hub_health as hh
    from core import tardis_feedback_bridge as tfb
    from core import tardis_event_bus as teb
    from core.tardis_agy_coevolution import TardisAgyCoevolutionEngine

    # 1) hub_health._probe_one reintenta TimeoutError transitorio una vez y falla rápido en ConnectionRefusedError
    monkeypatch.setattr(hh, "RETRY_BACKOFF_S", 0.01)
    timeout_calls = {"n": 0}

    class _OkResp:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def _flaky_urlopen(url, timeout=None):
        timeout_calls["n"] += 1
        if timeout_calls["n"] == 1:
            raise TimeoutError("transient event-loop stall")
        return _OkResp()

    monkeypatch.setattr(urllib.request, "urlopen", _flaky_urlopen)
    res_ok = hh._probe_one("mundo_sin_censura", {"http": "/api/mundo_sin_censura/status", "unit": None})
    assert res_ok["status"] == "online" and res_ok["http"] == 200 and timeout_calls["n"] == 2

    refused_calls = {"n": 0}
    def _refused_urlopen(url, timeout=None):
        refused_calls["n"] += 1
        raise ConnectionRefusedError("port closed")

    monkeypatch.setattr(urllib.request, "urlopen", _refused_urlopen)
    res_off = hh._probe_one("dead_srv", {"http": "http://127.0.0.1:19999/", "unit": None})
    assert res_off["status"] == "offline" and refused_calls["n"] == 1

    # 2) tardis_feedback_bridge: ola masiva de 22/46 subsistemas cayendo en 1 ciclo se suprime sin emitir 22 subsistema_cambio
    subs_all_ok = {f"sub_{i}": "online" for i in range(46)}
    prev_state = {
        "ts": 1000.0,
        "iso": "2026-11-25 14:01:40",
        "subsystems": dict(subs_all_ok),
        "self_improve": {"score": 100, "status": "HEALTHY", "metrics": {}, "needs": [], "penalties": []},
        "governor": {"level": "GREEN"},
        "inbox": {"pending": []},
    }
    subs_wave = {f"sub_{i}": ("offline" if i >= 24 else "online") for i in range(46)}
    cur_wave = {
        "ts": 1060.0,
        "iso": "2026-11-25 14:02:48",
        "subsystems": subs_wave,
        "self_improve": dict(prev_state["self_improve"]),
        "governor": {"level": "YELLOW"},
        "inbox": {"pending": []},
    }
    ev_wave = tfb.diff(prev_state, cur_wave)
    assert any(e["kind"] == "hub_mass_flap_suppressed" and e["affected_count"] == 22 for e in ev_wave)
    assert not any(e["kind"] == "subsistema_cambio" for e in ev_wave)

    # Recuperación al ciclo siguiente -> cero alertas falsas
    cur_back = {
        "ts": 1120.0,
        "iso": "2026-11-25 14:03:49",
        "subsystems": dict(subs_all_ok),
        "self_improve": dict(prev_state["self_improve"]),
        "governor": {"level": "GREEN"},
        "inbox": {"pending": []},
    }
    ev_back = tfb.diff(cur_wave, cur_back)
    assert not any(e["kind"] == "subsistema_cambio" for e in ev_back)

    # Caída individual: ciclo 1 -> subsistema_fluctuacion (no escalada); ciclo 2 -> subsistema_cambio confirmado; ciclo 3 -> recuperación simétrica
    subs_one_down = dict(subs_all_ok)
    subs_one_down["mundo_sin_censura"] = "offline"
    cur_back["subsystems"]["mundo_sin_censura"] = "online"
    cur_back["subsystem_tracker"]["confirmed_status"]["mundo_sin_censura"] = "online"

    c1 = {"ts": 1180.0, "iso": "2026-11-25 14:04:50", "subsystems": dict(subs_one_down), "self_improve": dict(prev_state["self_improve"]), "governor": {}, "inbox": {"pending": []}}
    e1 = tfb.diff(cur_back, c1)
    assert any(e["kind"] == "subsistema_fluctuacion" and e["subsystem"] == "mundo_sin_censura" for e in e1)
    assert not any(e["kind"] == "subsistema_cambio" for e in e1)

    c2 = {"ts": 1240.0, "iso": "2026-11-25 14:05:50", "subsystems": dict(subs_one_down), "self_improve": dict(prev_state["self_improve"]), "governor": {}, "inbox": {"pending": []}}
    e2 = tfb.diff(c1, c2)
    assert any(e["kind"] == "subsistema_cambio" and e["subsystem"] == "mundo_sin_censura" and e["to"] == "offline" and e.get("confirmed") is True for e in e2)

    subs_one_up = dict(subs_one_down)
    subs_one_up["mundo_sin_censura"] = "online"
    c3 = {"ts": 1300.0, "iso": "2026-11-25 14:06:50", "subsystems": subs_one_up, "self_improve": dict(prev_state["self_improve"]), "governor": {}, "inbox": {"pending": []}}
    e3 = tfb.diff(c2, c3)
    assert any(e["kind"] == "subsistema_cambio" and e["subsystem"] == "mundo_sin_censura" and e["from"] == "offline" and e["to"] == "online" for e in e3)

    # 3) Co-evolución drena >40 eventos (22 regression + 22 recovered = 44) sin partir el lote ni crear 4 propuestas fantasma
    iso_bus = teb.SovereignEventBus(db_path=tmp_path / "iso_bus_44.db")
    monkeypatch.setattr(teb, "get_event_bus", lambda db_path=None: iso_bus)
    names = [f"sub_{i}" for i in range(21)] + ["mundo_sin_censura"]
    for name in names:
        iso_bus.publish("health.regression", "tardis_feedback_bridge", {"kind": "subsistema_cambio", "subsystem": name, "from": "online", "to": "offline"}, severity="HIGH", dedup_window_s=0.0)
    for name in names:
        iso_bus.publish("health.recovered", "tardis_feedback_bridge", {"kind": "subsistema_cambio", "subsystem": name, "from": "offline", "to": "online"}, severity="INFO", dedup_window_s=0.0)

    eng = TardisAgyCoevolutionEngine(db_path=tmp_path / "coev_44.db")
    monkeypatch.setattr("core.hub_health.hub_health", lambda force=False: {"counts": {"online": 0}, "subsystems": {}})
    eng._scan_runtime_lens()
    assert not any(p["category"] == "regression" for p in eng.list_proposals(status="pending", limit=50))

    # 4) Cross-check contra hub_health en vivo: regresión obsoleta en bus + propuesta pendiente previa se auto-reconcilian si el subsistema está ONLINE
    iso_bus.publish("health.regression", "tardis_feedback_bridge", {"kind": "subsistema_cambio", "subsystem": "mundo_sin_censura", "from": "online", "to": "offline"}, severity="HIGH", dedup_window_s=0.0)
    eng.upsert_proposal(
        lens="runtime",
        category="regression",
        severity="HIGH",
        roi_score=91,
        title="Resolver evento crítico health.regression desde tardis_feedback_bridge",
        problem='{"subsystem": "mundo_sin_censura", "to": "offline"}',
        proposed_solution="Test",
        evidence={"id": 9999, "topic": "health.regression", "source": "tardis_feedback_bridge", "payload": {"subsystem": "mundo_sin_censura", "to": "offline"}},
        fingerprint_seed="test|stale|mundo_sin_censura",
    )
    monkeypatch.setattr(
        "core.hub_health.hub_health",
        lambda force=False: {"counts": {"online": 1}, "subsystems": {"mundo_sin_censura": {"id": "mundo_sin_censura", "status": "online", "http": 200}}},
    )
    eng._scan_runtime_lens()
    assert not any(p["category"] == "regression" for p in eng.list_proposals(status="pending", limit=20))


def test_resource_governor_swap_bloat_detection_and_safe_idle_recycle(tmp_path: Path, monkeypatch):
    """Regresión COEV-20261124-5B1F5C: detección de swap-bloat cgroup v2 y reciclaje seguro únicamente en reposo."""
    from core import tardis_resource_governor as trg

    # 1) Construir árbol cgroup v2 simulado con TemporalBrain en swap-bloat (6.17 GB swap) y Ollama Voice sano
    fake_slice = tmp_path / "app.slice"
    cg_tb = fake_slice / "tardis-temporal-brain.service"
    cg_ov = fake_slice / "tardis-ollama-voice.service"
    cg_tb.mkdir(parents=True)
    cg_ov.mkdir(parents=True)

    (cg_tb / "cgroup.procs").write_text("11111\n", encoding="utf-8")
    (cg_tb / "memory.current").write_text(str(6200 * 1024 * 1024), encoding="utf-8")
    (cg_tb / "memory.high").write_text(str(7 * 1024**3), encoding="utf-8")
    (cg_tb / "memory.max").write_text(str(9 * 1024**3), encoding="utf-8")
    (cg_tb / "memory.swap.current").write_text(str(6170 * 1024 * 1024), encoding="utf-8")
    (cg_tb / "memory.swap.max").write_text(str(2 * 1024**3), encoding="utf-8")

    (cg_ov / "cgroup.procs").write_text("22222\n", encoding="utf-8")
    (cg_ov / "memory.current").write_text(str(2800 * 1024 * 1024), encoding="utf-8")
    (cg_ov / "memory.high").write_text(str(4500 * 1024 * 1024), encoding="utf-8")
    (cg_ov / "memory.max").write_text(str(6 * 1024**3), encoding="utf-8")
    (cg_ov / "memory.swap.current").write_text("0", encoding="utf-8")
    (cg_ov / "memory.swap.max").write_text(str(1536 * 1024 * 1024), encoding="utf-8")

    def _fake_mem(pid: int):
        if pid == 11111:
            return {"rss_mb": 6190.0, "rss_anon_mb": 4200.0, "rss_file_mb": 1990.0, "mlock_mb": 0.0, "swap_mb": 6170.0}
        return {"rss_mb": 2800.0, "rss_anon_mb": 2100.0, "rss_file_mb": 700.0, "mlock_mb": 0.0, "swap_mb": 0.0}

    monkeypatch.setattr(trg, "_read_proc_mem_status", _fake_mem)
    monkeypatch.setattr(trg, "_read_proc_uptime_s", lambda pid: 3600.0 if pid == 11111 else 3600.0)

    rows, bloated = trg._inspect_service_memory_bloat(cgroup_app_slice=fake_slice)
    assert len(rows) == 2
    assert len(bloated) == 1
    assert bloated[0]["unit"] == "tardis-temporal-brain.service"
    assert bloated[0]["recycle_eligible"] is True
    assert bloated[0]["swap_mb"] == 6170.0
    assert bloated[0]["total_mb"] == 12360.0

    # 2) Probar todas las guardas de seguridad de reconcile_swap_bloat
    gov = trg.TardisResourceGovernor(
        db_path=tmp_path / "gov_sb.db",
        throttle_state_file=tmp_path / "th_sb.json",
        gpu_eco_state_file=tmp_path / "ge_sb.json",
        swap_recycle_state_file=tmp_path / "sr_sb.json",
    )
    monkeypatch.setattr(trg, "_swap_recycle_control_enabled", lambda: True)
    restarted_units = []
    monkeypatch.setattr(trg, "_restart_systemd_user_unit", lambda u, timeout=20.0: (restarted_units.append(u) or True, "restarted"))

    snap_bloated = {
        "call_priority_active": False,
        "inference_memory": rows,
        "memory_bloat_units": bloated,
    }

    # 2a) Llamada Telegram activa -> veto absoluto
    res_call = gov.reconcile_swap_bloat({**snap_bloated, "call_priority_active": True}, dry_run=False)
    assert res_call["action"] == "skipped_call_priority" and restarted_units == []

    # 2b) Proceso recién arrancado (<min_uptime_s) -> diferido
    snap_young = {
        "call_priority_active": False,
        "inference_memory": rows,
        "memory_bloat_units": [{**bloated[0], "uptime_s": 120.0}],
    }
    res_young = gov.reconcile_swap_bloat(snap_young, dry_run=False)
    assert res_young["action"] == "deferred_min_uptime" and restarted_units == []

    # 2c) Slots activos en TemporalBrain -> JAMÁS interrumpir
    monkeypatch.setattr(trg, "_is_service_idle_for_recycle", lambda u, k: (False, "temporal_brain_slots_busy:[0]"))
    res_busy = gov.reconcile_swap_bloat(snap_bloated, dry_run=False)
    assert res_busy["action"] == "deferred_busy" and restarted_units == []

    # 2d) En reposo verificado + dry_run -> would_recycle sin reiniciar
    monkeypatch.setattr(trg, "_is_service_idle_for_recycle", lambda u, k: (True, "all_slots_idle"))
    res_dry = gov.reconcile_swap_bloat(snap_bloated, dry_run=True)
    assert res_dry["action"] == "would_recycle" and restarted_units == []

    # 2e) En reposo verificado + ejecución real -> recicla una vez y aplica cooldown en la siguiente ronda
    res_real = gov.reconcile_swap_bloat(snap_bloated, dry_run=False)
    assert res_real["action"] == "recycled"
    assert restarted_units == ["tardis-temporal-brain.service"]
    st = gov.get_swap_recycle_status()
    assert st["recycled_units"]["tardis-temporal-brain.service"]["recycle_count"] == 1

    res_cool = gov.reconcile_swap_bloat(snap_bloated, dry_run=False)
    assert res_cool["action"] == "deferred_cooldown"
    assert restarted_units == ["tardis-temporal-brain.service"]


def test_cyberdefense_and_network_shield_ttl_cache_and_api_status_thread_offload(monkeypatch):
    """Regresión COEV-20261125-8237EE: caché TTL en cyberdefense/network_shield (cero sudo repetido) y cero /api/* sync-in-async en server/api.py."""
    import ast
    from core import cyberdefense_sentinel as cs
    from core import network_shield as ns
    from core.hub_health import PROBES

    # 1) CyberdefenseSentinel.assess_security_state usa caché TTL (default 20s), lee flags en memoria sin get_status() e invalida en contramedidas
    sentinel = cs.CyberdefenseSentinel()
    calls = {"ports": 0, "threats": 0, "shield_get_status": 0}
    monkeypatch.setattr(sentinel, "scan_listening_ports", lambda: (calls.__setitem__("ports", calls["ports"] + 1) or []))
    monkeypatch.setattr(sentinel, "inspect_active_threats", lambda: (calls.__setitem__("threats", calls["threats"] + 1) or ([], 0)))

    class _FakeShield:
        adblock_enabled = True
        antispy_enabled = True
        def get_status(self):
            calls["shield_get_status"] += 1
            return {"adblock_active": True, "antispy_active": True}

    monkeypatch.setattr(ns, "get_network_shield", lambda: _FakeShield())
    monkeypatch.setattr(sentinel, "_save_events", lambda: None)

    a1 = sentinel.assess_security_state(ttl_s=20.0)
    a2 = sentinel.assess_security_state(ttl_s=20.0)
    assert a1 is a2
    assert calls["ports"] == 1 and calls["threats"] == 1
    assert calls["shield_get_status"] == 0
    assert sentinel._assessment_cache_hits >= 1

    # force=True recalcula; trigger_countermeasure invalida caché
    a3 = sentinel.assess_security_state(force=True, ttl_s=20.0)
    assert calls["ports"] == 2
    sentinel.trigger_countermeasure("RELEASE_LOCKDOWN")
    a4 = sentinel.assess_security_state(ttl_s=20.0)
    assert calls["ports"] == 3 and a4.defense_score >= 90

    # 2) NetworkShield.get_status usa caché TTL (15s) sin disparar traffic_monitor repetidamente
    shield = ns.NetworkShield()
    shield.last_audit_results = {"security_score": 100, "grade": "A+", "devices": [], "alerts": []}
    tm_calls = {"n": 0}
    from core import traffic_monitor as tm_mod

    class _FakeTM:
        def get_quick_status(self):
            tm_calls["n"] += 1
            return {"total_active_flows": 5, "inbound_access_count": 0, "alerts": []}

    monkeypatch.setattr(tm_mod, "get_traffic_monitor", lambda: _FakeTM())
    monkeypatch.setattr(shield, "_save_config", lambda: None)
    monkeypatch.setattr(shield, "compile_and_apply_blocklist", lambda: {"ok": True})

    s1 = shield.get_status(ttl_s=15.0)
    s2 = shield.get_status(ttl_s=15.0)
    assert s1["traffic_flows_count"] == 5 and s2["traffic_flows_count"] == 5
    assert tm_calls["n"] == 1
    shield.toggle_adblock(True)
    _ = shield.get_status(ttl_s=15.0)
    assert tm_calls["n"] == 2

    # 3) Auditoría AST en server/api.py: ningún endpoint /api/* sondeado por core/hub_health.py puede ser async def sin await
    api_src = (Path(__file__).resolve().parent.parent / "server" / "api.py").read_text(encoding="utf-8")
    tree = ast.parse(api_src)
    hub_api_paths = {v["http"] for v in PROBES.values() if isinstance(v.get("http"), str) and v["http"].startswith("/api/")}
    offending = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            routes = set()
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    routes.add(dec.args[0].value)
            matched = routes & hub_api_paths
            if matched:
                has_await = any(isinstance(sub, (ast.Await, ast.AsyncFor, ast.AsyncWith)) for sub in ast.walk(node))
                if not has_await:
                    offending.append((node.name, sorted(matched)))
    assert offending == [], f"Endpoints /api/* de hub_health bloqueando event loop ASGI sin await: {offending}"


def test_temporal_brain_threads_batch_cpuset_headroom_eliminates_9_of_8_oversubscription():
    """Regresión COEV-20261125-DB539A: --threads-batch reserva 2 CPUs de margen en cpuset 8-15 (8 -> 6)."""
    import json
    from core.temporal_brain import _resolve_safe_threads_batch

    assert _resolve_safe_threads_batch(8, 4, None) == 6
    assert _resolve_safe_threads_batch(8, 4, 8) == 6
    assert _resolve_safe_threads_batch(8, 4, 16) == 6
    assert _resolve_safe_threads_batch(8, 4, 5) == 5
    assert _resolve_safe_threads_batch(6, 3, 8) == 4
    assert _resolve_safe_threads_batch(4, 2, 4) == 3
    assert _resolve_safe_threads_batch(4, 4, 4) == 4

    cfg = json.loads((Path(__file__).resolve().parent.parent / "temporal_brain_config.json").read_text(encoding="utf-8"))
    assert int(cfg.get("threads_batch", 0)) == 6


def test_sqlite_incremental_compaction_and_subsystem_proposals_blob_dedup(tmp_path: Path, monkeypatch):
    """Regresión COEV-20261123-7251BC: deduplicación content-addressed en subsystem_agents + incremental_compact no bloqueante en RAGVault y DeepMemoryVault."""
    import json
    import sqlite3
    import time
    from core import subsystem_agents as sa
    from core import rag_vault as rv
    from core import deep_memory_vault as dmv
    from core.tardis_memory_compactor import TardisMemoryCompactor, AUX_WAL_DBS

    # 1) frontier_lab.db debe estar cubierto por AUX_WAL_DBS
    assert any(p.name == "frontier_lab.db" for p in AUX_WAL_DBS)

    # 2) subsystem_agents._persist_cycle deduplica propuestas con distinto created_ts en proposals_blobs
    sa_db = tmp_path / "subsystem_agents_dedup.db"
    monkeypatch.setattr(sa, "STATE_DB", sa_db)
    base_props = [
        {"subsystem": "chat", "file": "server/api.py", "rule": "huge_function", "description": "desc " + ("x" * 180), "diff_summary": "api.py:10", "created_ts": 1000.0},
        {"subsystem": "chat", "file": "server/api.py", "rule": "todo", "description": "todo " + ("y" * 180), "diff_summary": "api.py:20", "created_ts": 1000.1},
    ]
    for i in range(5):
        props_i = [dict(p, created_ts=2000.0 + i) for p in base_props]
        sa._persist_cycle({
            "ts": time.time() - 10 + i,
            "agent": "chat",
            "health": "online",
            "findings": 2,
            "by_rule": {"huge_function": 1, "todo": 1},
            "applied": [],
            "proposals": props_i,
        })
    with sqlite3.connect(sa_db) as con:
        assert con.execute("SELECT COUNT(*) FROM cycles").fetchone()[0] == 5
        assert con.execute("SELECT COUNT(*) FROM proposals_blobs").fetchone()[0] == 1
        row = con.execute("SELECT proposals_json, proposals_hash FROM cycles LIMIT 1").fetchone()
        assert row[0].startswith("@blob:") and row[1]
        resolved = sa.resolve_cycle_proposals(con, row[0], row[1])
        assert len(resolved) == 2 and resolved[0]["rule"] == "huge_function"
        idxs = {r[1] for r in con.execute("PRAGMA index_list(cycles)").fetchall()}
        assert "idx_cycles_subsystem_ts" in idxs

    # 3) compact_subsystem_agents deduplica retroactivamente filas legadas con JSON inline repetido y migra a auto_vacuum=INCREMENTAL
    legacy_db = tmp_path / "subsystem_agents_legacy.db"
    now = time.time()
    with sqlite3.connect(legacy_db) as con:
        con.execute("CREATE TABLE cycles (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, subsystem TEXT, health TEXT, findings INTEGER, findings_json TEXT, applied_json TEXT, proposals_json TEXT)")
        for i in range(80):
            props_i = [dict(p, created_ts=now + i) for p in base_props]
            con.execute(
                "INSERT INTO cycles (ts, subsystem, health, findings, findings_json, applied_json, proposals_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now - 3600 + i, "chat", "online", 2, '{"huge_function":1}', "[]", json.dumps(props_i)),
            )
        con.commit()
    comp = TardisMemoryCompactor(db_path=tmp_path / "comp.db")
    res_sa = comp.compact_subsystem_agents(legacy_db, dry_run=False)
    assert res_sa["ok"] is True
    assert res_sa["proposals_deduplicated"] == 80
    assert res_sa["unique_proposal_blobs"] == 1
    assert res_sa["auto_vacuum_after"] == 2
    assert res_sa["bytes_after"] < res_sa["bytes_before"]

    # 4) RAGVault.incremental_compact no bloqueante (PASSIVE + FTS5 optimize + nuevos índices + migración INCREMENTAL)
    rag_db = tmp_path / "rag_inc.db"
    monkeypatch.setattr(rv, "DB_PATH", rag_db)
    vault = rv.RAGVault()
    with vault._connect() as con:
        con.execute("INSERT INTO rag_chunks (doc_id, source, url, title, term, text, ts, chunk_hash) VALUES ('d1','doc','','T','t','contenido prueba sqlite incremental',?,'h1')", (now,))
        cid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute("INSERT INTO rag_fts(rowid, text, title, term) VALUES (?, 'contenido prueba sqlite incremental', 'T', 't')", (cid,))
        con.commit()
    res_rv_nb = vault.incremental_compact(checkpoint_mode="PASSIVE", max_pages=64, optimize_fts=True)
    assert res_rv_nb["ok"] is True and res_rv_nb["checkpoint_mode"] == "PASSIVE" and res_rv_nb["fts_optimized"] is True
    res_rv_mig = vault.incremental_compact(checkpoint_mode="TRUNCATE", enable_incremental_vacuum=True)
    assert res_rv_mig["auto_vacuum_after"] == 2
    with vault._connect() as con:
        rag_idxs = {r[1] for r in con.execute("PRAGMA index_list(rag_chunks)").fetchall()}
        assert "idx_chunks_source" in rag_idxs and "idx_chunks_ts" in rag_idxs

    # 5) DeepMemoryVault.incremental_compact migra auto_vacuum=0 -> 2 y optimiza vault_fts sin bloquear en modo PASSIVE
    dmv_dir = tmp_path / "dmv_inc"
    dmv_dir.mkdir(parents=True, exist_ok=True)
    # Simular DB legada creada con auto_vacuum=0
    legacy_dmv_db = dmv_dir / "vault_master.db"
    with sqlite3.connect(legacy_dmv_db) as con:
        con.execute("PRAGMA auto_vacuum=NONE")
        con.execute("CREATE TABLE _boot(id INTEGER PRIMARY KEY)")
        con.commit()
    dm = dmv.DeepMemoryVault(vault_dir=dmv_dir)
    dm.ingest(role="user", content="Prueba de compactación incremental DeepMemoryVault", session_id="s1")
    res_dm_nb = dm.incremental_compact(checkpoint_mode="PASSIVE", max_pages=64, optimize_fts=True)
    assert res_dm_nb["ok"] is True and res_dm_nb["checkpoint_mode"] == "PASSIVE" and res_dm_nb["fts_optimized"] is True
    res_dm_mig = dm.incremental_compact(checkpoint_mode="TRUNCATE", enable_incremental_vacuum=True)
    assert res_dm_mig["auto_vacuum_after"] == 2
    res_nb_run = comp.run_compaction(
        targets=("rag", "deep_memory", "subsystem_agents"),
        non_blocking=True,
        rag_db=rag_db,
        deep_memory_db=legacy_dmv_db,
        subsystem_agents_db=legacy_db,
        persist=False,
    )
    assert res_nb_run["ok"] is True
    assert res_nb_run["targets"]["rag"]["maintenance"]["checkpoint_mode"] == "PASSIVE"
