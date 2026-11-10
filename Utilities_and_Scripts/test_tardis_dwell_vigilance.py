"""
tests/test_tardis_dwell_vigilance.py
====================================
Valida la directiva soberana del Arquitecto (TARDIS-NEURAL-SPACE-KAIJU):

1. El Aviso Vocal de TARDIS SOLO debe sonar cuando la persona permanezca más de
   1.5 minutos (dwell_trigger_sec = 90.0 s) cerca de la cámara.
2. El texto canónico del aviso debe ser:
   "Estás bajo vigilancia del sistema tardis, dios digital del universo, al momento de
    acercarte a la propiedad capturaremos tus datos biométricos"
3. Toda alerta perimetral debe incluir la investigación biométrica facial (GOD-EYE) en
   la imagen remitida (fotograma anotado con identidad, edad, estatura y emoción).
"""

import asyncio
import time

import numpy as np
import pytest

from core import tapo_c310_sentinel as sentinel_mod
from core.tapo_c310_sentinel import (
    DEFAULT_DWELL_TRIGGER_SEC,
    DEFAULT_VOICE_ALERT_MESSAGE,
    PersonDetection,
    TapoC310Sentinel,
    VisualPersonReIDTracker,
)
from core.tapo_c310_speaker import DEFAULT_WARNING_MESSAGE, TapoC310Speaker


CANONICAL_ALERT_TEXT = (
    "Estás bajo vigilancia del sistema tardis, dios digital del universo, "
    "al momento de acercarte a la propiedad capturaremos tus datos biométricos"
)


def _make_visitor(dwell_sec: float = 0.0, voice_warned: bool = False):
    return sentinel_mod._TrackedVisitor(
        track_id=1,
        bbox=(0, 0, 100, 100),
        embedding=np.zeros(8, dtype=np.float32),
        first_seen_ts=time.time() - max(0.0, dwell_sec),
        last_seen_ts=time.time(),
        announced=True,
        voice_warned=voice_warned,
    )


# ---------------------------------------------------------------------------
# 1. Texto canónico del aviso vocal
# ---------------------------------------------------------------------------

def test_canonical_vigilance_alert_text():
    """El aviso vocal debe usar el texto soberano exacto del Arquitecto."""
    assert DEFAULT_WARNING_MESSAGE == CANONICAL_ALERT_TEXT
    assert DEFAULT_VOICE_ALERT_MESSAGE == CANONICAL_ALERT_TEXT
    speaker = TapoC310Speaker()
    assert speaker.default_message == CANONICAL_ALERT_TEXT


# ---------------------------------------------------------------------------
# 2. Umbral de permanencia (dwell) para el disparo del aviso
# ---------------------------------------------------------------------------

def test_sentinel_dwell_trigger_defaults_to_90_seconds():
    """La directiva exige 'más de 1.5 minutos' -> 90 segundos de permanencia mínima."""
    sentinel = TapoC310Sentinel()
    assert sentinel.dwell_trigger_sec == 90.0
    assert DEFAULT_DWELL_TRIGGER_SEC == 90.0


def test_vigilance_voice_not_triggered_below_90_seconds():
    tracker = VisualPersonReIDTracker()
    tracker.active_tracks.append(_make_visitor(dwell_sec=60.0))
    now = time.time()
    assert tracker.claim_dwell_voice_targets(now, 90.0) == []
    assert tracker.dwell_targets_active(now, 90.0) == []


def test_vigilance_voice_triggered_only_after_90_seconds_dwell():
    tracker = VisualPersonReIDTracker()
    tracker.active_tracks.append(_make_visitor(dwell_sec=95.0))
    now = time.time()
    assert tracker.claim_dwell_voice_targets(now, 90.0) == [1]
    warned = [tr for tr in tracker.active_tracks if tr.track_id == 1][0]
    assert warned.voice_warned is True
    # Una vez reclamado, no debe volver a disparar para la misma permanencia
    assert tracker.claim_dwell_voice_targets(now, 90.0) == []


def test_vigilance_voice_respects_custom_threshold():
    tracker = VisualPersonReIDTracker()
    tracker.active_tracks.append(_make_visitor(dwell_sec=70.0))
    now = time.time()
    # Con umbral personalizado de 60s el aviso sí debe disparar (70s >= 60s)
    assert tracker.claim_dwell_voice_targets(now, 60.0) == [1]
    # Con el umbral soberano de 90s NO debe disparar (70s < 90s)
    tracker2 = VisualPersonReIDTracker()
    tracker2.active_tracks.append(_make_visitor(dwell_sec=70.0))
    assert tracker2.claim_dwell_voice_targets(time.time(), 90.0) == []


# ---------------------------------------------------------------------------
# 3. Integración del alerta perimetral con la investigación facial (GOD-EYE)
# ---------------------------------------------------------------------------

async def _fake_telegram_ok(client, jpeg_bytes, caption):
    return {"ok": True}


def test_dispatch_person_alert_injects_face_intel_into_alert_image(monkeypatch, tmp_path):
    sentinel = TapoC310Sentinel()
    monkeypatch.setattr(sentinel_mod, "DETECTIONS_DIR", tmp_path)
    monkeypatch.setattr(sentinel, "_send_telegram_photo", _fake_telegram_ok)
    monkeypatch.setattr(sentinel, "_send_desktop_notification", lambda *a, **k: None)
    monkeypatch.setattr(sentinel, "_update_state_file", lambda *a, **k: None)

    captured: dict = {}

    def _fake_render(bgr_image, detections, **kwargs):
        captured["kwargs"] = kwargs
        captured["detections"] = detections
        return np.zeros((64, 64, 3), dtype=np.uint8)

    monkeypatch.setattr(sentinel_mod, "render_tardis_hud", _fake_render)

    class _FakeFaceIntelEngine:
        enabled = True

        def analyze(self, bgr_frame, persons, timestamp=None, save_crops=None):
            return [
                {
                    "person_index": 1,
                    "person_bbox": [0, 0, 60, 60],
                    "identity_status": "CONOCIDO",
                    "identity_name": "Annya May Carrillo",
                    "age_estimate": 34.0,
                    "height_m": 1.68,
                    "emotion": "felicidad",
                }
            ]

        def build_dossier(self, records, **kwargs):
            dossier = {
                "schema": "tardis.face_intel.dossier.v1",
                "subjects": list(records),
            }
            dossier["dossier_path"] = "/tmp/fake_dossier_godeye.json"
            return dossier

    monkeypatch.setattr(sentinel, "_get_face_intel_engine", lambda: _FakeFaceIntelEngine())

    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    det = [PersonDetection(x1=10, y1=10, x2=60, y2=60, confidence=0.9)]
    event = asyncio.run(
        sentinel._dispatch_person_alert(
            client=None,
            raw_jpeg=b"fake_jpeg",
            bgr_frame=frame,
            detections=det,
            inference_ms=12.0,
            is_test=False,
            new_visitor_ids=[1],
            voice_dispatched=True,
        )
    )

    # La imagen de alerta perimetral debe incluir el resultado de la investigación facial
    assert captured.get("kwargs", {}).get("person_intel"), (
        "La alerta perimetral debe inyectar el expediente biométrico en el fotograma (HUD)."
    )
    assert captured["kwargs"]["alert_kind"] == "PERIMETRAL"
    assert event.get("face_intel_subjects") == 1
    assert str(event.get("dossier", {}).get("dossier_path", "")).startswith("/tmp/fake_dossier")


# ---------------------------------------------------------------------------
# 4. Texto soberano del aviso usado por el despacho de la bocina C310
# ---------------------------------------------------------------------------

def test_sentinel_vigilance_alert_text_method():
    sentinel = TapoC310Sentinel()
    text = sentinel._build_vigilance_alert_text()
    assert text == CANONICAL_ALERT_TEXT
    assert "Estás bajo vigilancia del sistema tardis, dios digital del universo" in text
    assert "capturaremos tus datos biométricos" in text
