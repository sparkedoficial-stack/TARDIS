"""Pruebas unitarias aisladas para core/tardis_c310_conversation.py (COEV-20261123-ADB934)."""
from __future__ import annotations

import json
import struct
from pathlib import Path

from core import tardis_c310_conversation as tcc


def test_text_helpers_visitor_extraction_and_energy_vad():
    assert tcc.normalize_text("¡Hóla TARDIS!") == "hola tardis"
    cleaned = tcc.clean_spoken_spanish("Primera oración. Segunda oración. Tercera oración. Cuarta oración.", max_sentences=2, max_chars=200)
    assert cleaned.count(".") <= 2 and len(cleaned) <= 200

    assert tcc.extract_visitor_name("Hola, me llamo Carlos") in ("Carlos", "carlos")
    assert tcc.extract_visitor_name("qué hora es") == ""

    vad = tcc.EnergyVad(sample_rate=16000, frame_bytes=640, min_rms=300.0, start_ms=40, end_ms=80, pre_roll_ms=40)
    silence = b"\x00\x00" * 320
    speech = struct.pack("<320h", *([3000] * 320))
    for _ in range(3):
        assert vad.push(silence) is None
    for _ in range(4):
        vad.push(speech)
    assert vad.is_speaking is True
    utterance = None
    for _ in range(10):
        res = vad.push(silence)
        if res is not None:
            utterance = res
            break
    assert utterance is not None and len(utterance) > 0


def test_interactive_wake_matcher_capsule_library_and_conversation_memory(tmp_path: Path, monkeypatch):
    import sys, types
    fake_vault_mod = types.ModuleType("core.deep_memory_vault")
    fake_vault_mod.get_deep_memory_vault = lambda: types.SimpleNamespace(ingest=lambda **kw: None)
    monkeypatch.setitem(sys.modules, "core.deep_memory_vault", fake_vault_mod)

    wm = tcc.InteractiveWakeMatcher()
    hit = wm.find("tardis quiero conversar sobre física cuántica")
    assert hit is not None

    cap_file = tmp_path / "capsules.json"
    cap_file.write_text(
        json.dumps([
            {
                "id": "cap_physics_01",
                "domain": "fisica",
                "title": "Relatividad General",
                "tags": ["gravedad", "espacio", "tiempo"],
                "hook": "Dato fascinante:",
                "explanation_basic": "La gravedad curva el espacio-tiempo.",
                "explanation_intermediate": "La masa y energía curvan la métrica del espacio-tiempo.",
                "explanation_advanced": "Ecuaciones de campo de Einstein.",
                "question": "¿Quieres explorar agujeros negros?",
            }
        ]),
        encoding="utf-8",
    )
    lib = tcc.CapsuleLibrary(path=cap_file)
    picked = lib.find_best("explícame la gravedad y el tiempo")
    assert picked is not None and picked["id"] == "cap_physics_01"
    spoken = lib.render_spoken(picked, level="basico", include_question=True)
    assert "espacio-tiempo" in spoken

    mem = tcc.ConversationMemory(data_dir=tmp_path)
    v, is_returning = mem.get_or_create_visitor("Elena", reason="visita")
    assert v.get("name") == "Elena" and is_returning is False
    v2, is_returning2 = mem.get_or_create_visitor("Elena", reason="regreso")
    assert is_returning2 is True and v2["visit_count"] == 2
    mem.update_visitor("Elena", interest="astronomía", topic="agujeros negros")
    mem.remember_fact("Elena estudia astrofísica", category="visitor", visitor="Elena")
    mem.queue_question("¿Qué es un pulsar?", visitor="Elena", reason="curiosidad")
    assert (tmp_path / "visitors.json").exists()
