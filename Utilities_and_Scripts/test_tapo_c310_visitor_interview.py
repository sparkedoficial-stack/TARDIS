"""
tests/test_tapo_c310_visitor_interview.py
=========================================
Regresiones de la directiva 2026-11-17 para la Tapo C310 (REDACTED_IP):

  1. Al detectar un humano NUEVO se despacha de inmediato el alerta perimetral
     (notificación + foto). El centinela lo perdía porque `new_visitor_ids_now`
     nunca se incorporaba a `pending_new_ids`.
  2. Quince segundos después se emite la entrevista (nombre + motivo de visita).
     La ventana de presencia debe ser >= retardo: con 6 s la entrevista se omitía
     siempre que el visitante hubiera sido visto sólo en el instante de detección.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from core import tapo_c310_sentinel as sentinel_mod
from core.tapo_c310_sentinel import PersonDetection, TapoC310Sentinel


def _write_config(tmp_path, **overrides):
    cfg = {
        "host": "REDACTED_IP",
        "device_model": "C310",
        "device_alias": "GOD-EYE",
        "yolo_model_path": "models/yolov8s.onnx",
        "sample_interval_sec": 0.05,
        "confirm_frames": 1,
        "best_shot_extra_frames": 0,
        "alert_cooldown_sec": 30.0,
        "clear_reset_sec": 8.0,
        "cctv_hub_feed_enabled": False,
        "telegram_notify_enabled": False,
        "desktop_notify_enabled": False,
        "face_intel_enabled": False,
        "speaker_enabled": True,
        "visitor_interview_enabled": True,
        "visitor_interview_delay_sec": 15.0,
        "visitor_interview_presence_window_sec": 25.0,
        "visitor_interview_require_presence": True,
        "visitor_interview_cooldown_sec": 30.0,
        "visitor_interview_speaker_fallback": True,
    }
    cfg.update(overrides)
    path = tmp_path / "tapo_config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def _make_sentinel(monkeypatch, tmp_path, **overrides) -> TapoC310Sentinel:
    # Evita cargar el modelo ONNX real: estas pruebas son de orquestación, no de inferencia.
    monkeypatch.setattr(
        sentinel_mod,
        "YoloV8PersonDetector",
        lambda **kwargs: SimpleNamespace(detect=lambda img: ([], 0.0)),
    )
    return TapoC310Sentinel(config_path=_write_config(tmp_path, **overrides))


# ---------------------------------------------------------------------------
# 1. Aviso inmediato al detectar humanos (foto + notificación)
# ---------------------------------------------------------------------------

def test_new_visitor_dispatches_immediate_perimeter_alert(monkeypatch, tmp_path):
    """Un individuo nuevo debe generar el alerta en el mismo ciclo de confirmación."""
    sentinel = _make_sentinel(monkeypatch, tmp_path)
    monkeypatch.setattr(sentinel, "_update_state_file", lambda *a, **k: None)
    monkeypatch.setattr(sentinel, "_schedule_visitor_interview", lambda ids: None)

    dispatched = []

    async def _fake_dispatch(client, raw_jpeg, bgr_frame, detections, inference_ms, **kwargs):
        dispatched.append({"ids": kwargs.get("new_visitor_ids"), "persons": len(detections)})
        return {}

    sentinel._dispatch_person_alert = _fake_dispatch

    frame = np.full((64, 64, 3), 32, dtype=np.uint8)
    ok, enc = cv2.imencode(".jpg", frame)
    assert ok
    detection = PersonDetection(x1=4, y1=4, x2=60, y2=60, confidence=0.93)
    monkeypatch.setattr(sentinel.detector, "detect", lambda img: ([detection], 7.5))

    sentinel._latest_jpeg = enc.tobytes()
    sentinel._latest_frame_ts = time.time()
    sentinel._frame_seq = 1
    sentinel._new_frame_event.set()

    async def _stop_after_one_cycle():
        await asyncio.sleep(0.15)
        sentinel._stop_event.set()

    async def _run():
        asyncio.create_task(_stop_after_one_cycle())
        await asyncio.wait_for(sentinel._analysis_worker(client=None), timeout=3.0)

    asyncio.run(_run())

    assert dispatched, "El visitante nuevo debe despachar el alerta perimetral de inmediato."
    assert dispatched[0]["ids"] == [1]
    assert dispatched[0]["persons"] == 1


# ---------------------------------------------------------------------------
# 2. Entrevista a los 15 s (nombre + motivo), aunque la persona se haya ido de cuadro
# ---------------------------------------------------------------------------

def test_interview_still_fires_15s_after_detection(monkeypatch, tmp_path):
    """Tras el retardo debe preguntar aunque la detección ocurriera hace 15 s."""
    sentinel = _make_sentinel(monkeypatch, tmp_path)
    assert sentinel.visitor_interview_presence_window_sec >= sentinel.visitor_interview_delay_sec

    # Persona vista hace 15 s (justo en la detección) y sin detecciones posteriores.
    sentinel.last_person_seen_ts = time.time() - 15.0
    sentinel.last_alert_ts = time.time() - 15.0
    monkeypatch.setattr(sentinel, "_voice_channel_alive", lambda: False)

    delays = []

    async def _instant_sleep(seconds):
        delays.append(seconds)
        return None

    monkeypatch.setattr(sentinel_mod.asyncio, "sleep", _instant_sleep)

    spoken = []

    async def _fake_warn(ids, custom_text=None):
        spoken.append({"ids": list(ids), "text": custom_text or ""})
        return {"ok": True}

    sentinel._announce_new_person_voice = _fake_warn

    asyncio.run(sentinel._run_visitor_interview_request([1]))

    assert delays and delays[0] == 15.0, "La entrevista debe agendarse exactamente 15 s después."
    assert len(spoken) == 1, "La entrevista no debe omitirse por la ventana de presencia."
    assert spoken[0]["ids"] == [1]
    assert "¿Cuál es su nombre?" in spoken[0]["text"]
    assert "motivo de su visita" in spoken[0]["text"]
    assert sentinel.total_visitor_interviews_requested == 1


def test_interview_is_skipped_when_person_gone_beyond_window(monkeypatch, tmp_path):
    """Con una ausencia muy prolongada sí se conserva la omitición (sentido común)."""
    sentinel = _make_sentinel(
        monkeypatch, tmp_path, visitor_interview_presence_window_sec=25.0
    )
    sentinel.last_person_seen_ts = time.time() - 120.0
    sentinel.last_alert_ts = time.time() - 120.0
    monkeypatch.setattr(sentinel, "_voice_channel_alive", lambda: False)

    async def _instant_sleep(seconds):
        return None

    monkeypatch.setattr(sentinel_mod.asyncio, "sleep", _instant_sleep)

    spoken = []

    async def _fake_warn(ids, custom_text=None):
        spoken.append(ids)
        return {"ok": True}

    sentinel._announce_new_person_voice = _fake_warn

    asyncio.run(sentinel._run_visitor_interview_request([1]))

    assert spoken == []
    assert sentinel.total_visitor_interviews_requested == 0
