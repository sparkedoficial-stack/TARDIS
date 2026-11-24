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
