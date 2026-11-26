"""Pruebas unitarias aisladas para core/tapo_c310_voice_channel.py (COEV-20261123-ADB934)."""
from __future__ import annotations

import struct

from core import tapo_c310_voice_channel as tvc


def test_text_normalization_edit_distance_and_pcm_rms():
    assert tvc.normalize_text("  ¡Hola, TÁRDIS! ¿Cómo estás? ") == "hola tardis como estas"
    assert tvc._edit_distance("tardis", "tardis") == 0
    assert tvc._edit_distance("tardis", "tardiz") == 1
    assert tvc._edit_distance("tardis", "abcdef", max_dist=2) > 2

    silence = b"\x00\x00" * 160
    assert tvc.pcm_rms(silence) == 0.0
    loud = struct.pack("<160h", *([4000] * 160))
    assert tvc.pcm_rms(loud) > 3000.0


def test_wake_phrase_matcher_pcm_ring_and_brain_client_helpers():
    matcher = tvc.WakePhraseMatcher()
    m = matcher.find("oye tardis estas ahi enciende la luz del laboratorio")
    assert m is not None
    rem = matcher.strip("oye tardis estas ahi enciende la luz del laboratorio", m)
    assert "enciende" in rem.lower()
    assert matcher.find("buenas tardes como estas hoy") is None
    assert matcher.find("clima soleado en la playa") is None

    ring = tvc.PcmRing(max_seconds=1.0, rate=16000)
    chunk = b"\x01\x00" * 4000
    off0 = ring.start_offset()
    ring.append(chunk)
    sliced = ring.slice_from(off0)
    assert len(sliced) == len(chunk)
    ring.clear()
    assert ring.slice_from(ring.start_offset()) == b""

    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "hola"}, {"type": "image_url", "image_url": {"url": "data:..."}}]}
    ]
    plain = tvc.TemporalBrainClient._text_only_messages(msgs)
    assert plain[0]["content"] == "hola"
    parsed = tvc.TemporalBrainClient._parse_response({"choices": [{"message": {"content": "  Listo  "}}]})
    assert parsed == "Listo"
