"""
tests/test_tapo_c310_interactive_conversation.py
================================================
Suite integral de pruebas para el motor de conversación interactiva, enseñanza,
visión por cámara, investigación documental/web y aprendizaje continuo de TARDIS
conectada a la Tapo C310 (GOD-EYE · REDACTED_IP).
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tardis_c310_conversation import (
    CameraVisionInvestigator,
    CapsuleLibrary,
    ConversationDirector,
    ConversationMemory,
    EnergyVad,
    InteractiveResearchEngine,
    InteractiveWakeMatcher,
    ResearchFinding,
    VisionObservation,
    VoiceBrain,
    clean_spoken_spanish,
    compute_pcm_rms,
    extract_visitor_name,
)
from core.tardis_teaching import (
    detect_pedagogical_adjustment,
    extract_research_query,
    is_curiosity_intent,
    is_research_intent,
    is_vision_intent,
)


# ---------------------------------------------------------------------------
# 1. Sanitización hablada (incluyendo eliminación de caracteres CJK/markdown)
# ---------------------------------------------------------------------------


def test_clean_spoken_spanish_removes_think_markdown_and_cjk():
    raw = (
        "<think>razonamiento interno</think>"
        "**¡Claro!** La fotosíntesis usa plantas,藻, y luz solar. "
        "Ver [Wikipedia](https://es.wikipedia.org/wiki/Fotosintesis) para detalles. "
        "```python\nprint('x')\n```"
    )
    cleaned = clean_spoken_spanish(raw, max_sentences=3, max_chars=400)
    assert "<think>" not in cleaned
    assert "razonamiento interno" not in cleaned
    assert "藻" not in cleaned
    assert "https://" not in cleaned
    assert "**" not in cleaned
    assert "fotosíntesis" in cleaned.lower()
    assert cleaned.endswith((".", "!", "?"))


# ---------------------------------------------------------------------------
# 2. Wake interactivo para visitantes + cero falsos positivos
# ---------------------------------------------------------------------------


class TestInteractiveWakeMatcher:
    @pytest.mark.parametrize(
        "phrase,expected_kind",
        [
            ("Hola TARDIS", "greeting"),
            ("Oye TARDIS, enséñame sobre los agujeros negros", "greeting"),
            ("Hey TARDIS, ¿qué ves en la cámara?", "greeting"),
            ("TARDIS enséñame sobre los cenotes", "interactive_command"),
            ("TARDIS investiga sobre la fusión nuclear", "interactive_command"),
            ("TARDIS mira esto que tengo en la mano", "interactive_command"),
            ("TARDIS cuéntame algo interesante", "interactive_command"),
            ("TARDIS qué es la entropía", "interactive_command"),
        ],
    )
    def test_accepts_natural_visitor_wakes(self, phrase, expected_kind):
        matcher = InteractiveWakeMatcher()
        res = matcher.find(phrase)
        assert res is not None and res.matched is True
        assert res.kind == expected_kind

    @pytest.mark.parametrize(
        "phrase",
        [
            "Buenas tardes, ¿cómo está?",
            "En la tarde pasamos por aquí",
            "Más tarde te llamo",
            "TARDIS está en línea funcionando",
            "Hola, buenos días a todos",
            "",
        ],
    )
    def test_rejects_false_positives(self, phrase):
        matcher = InteractiveWakeMatcher()
        assert matcher.find(phrase) is None


# ---------------------------------------------------------------------------
# 3. Intenciones de investigación, visión, curiosidad y ajuste pedagógico
# ---------------------------------------------------------------------------


def test_extended_intents_and_query_extraction():
    assert is_research_intent("Investiga sobre la fusión nuclear") is True
    assert is_research_intent("¿Cómo funciona un agujero negro?") is True
    assert is_research_intent("¿Qué dice la ciencia sobre el sueño?") is True
    assert is_research_intent("Hola, buenas noches") is False

    assert is_vision_intent("TARDIS, ¿qué ves en la cámara?") is True
    assert is_vision_intent("Mira esto que tengo en la mano") is True
    assert is_vision_intent("Analiza esto que te muestro") is True
    assert is_vision_intent("¿Qué hora es?") is False

    assert is_curiosity_intent("Quiero aprender algo interesante") is True
    assert is_curiosity_intent("Sorpréndeme con un dato curioso") is True

    assert detect_pedagogical_adjustment("Explícamelo más fácil, no entendí") == "simpler"
    assert detect_pedagogical_adjustment("Profundiza más a nivel avanzado") == "deeper"
    assert detect_pedagogical_adjustment("Dame un ejemplo cotidiano") == "example"
    assert detect_pedagogical_adjustment("Hazme una pregunta para evaluarme") == "quiz"

    assert extract_research_query("Oye TARDIS, investiga sobre los cenotes de Yucatán") == "cenotes de yucatan"
    assert extract_visitor_name("Hola, me llamo Valeria") == "Valeria"
    assert extract_visitor_name("Soy Carlos") == "Carlos"
    assert extract_visitor_name("Soy un visitante curioso") == ""


# ---------------------------------------------------------------------------
# 4. EnergyVad adaptativo (inicio de voz + silencio -> utterance completa)
# ---------------------------------------------------------------------------


def test_energy_vad_segments_speech_and_silence():
    vad = EnergyVad(min_rms=100.0, start_ms=60, end_ms=100, pre_roll_ms=40)
    quiet = np.zeros(320, dtype=np.int16).tobytes()
    # Tono sinusoidal de amplitud 2000 (RMS ~ 1414)
    t = np.arange(320, dtype=np.float32) / 16000.0
    loud = (np.sin(2 * np.pi * 440.0 * t) * 2000.0).astype(np.int16).tobytes()
    assert compute_pcm_rms(loud) > 1000.0

    for _ in range(5):
        assert vad.push(quiet) is None
    for _ in range(10):
        assert vad.push(loud) is None
    assert vad.is_speaking is True

    utterance = None
    for _ in range(10):
        out = vad.push(quiet)
        if out is not None:
            utterance = out
            break
    assert utterance is not None
    assert len(utterance) >= 10 * len(loud)
    assert vad.is_speaking is False


# ---------------------------------------------------------------------------
# 5. Biblioteca de cápsulas, memoria persistente y cola autónoma de aprendizaje
# ---------------------------------------------------------------------------


def test_capsule_library_and_multilevel_rendering(tmp_path):
    lib = CapsuleLibrary(path=tmp_path / "capsules.json")
    assert len(lib.capsules) >= 20
    cap = lib.find_best("cenotes de quintana roo")
    assert cap is not None
    assert cap["id"] == "regional-cenotes"

    basic = lib.render_spoken(cap, level="principiante")
    adv = lib.render_spoken(cap, level="avanzado")
    assert basic != adv
    assert "caliza" in basic.lower()
    assert "chicxulub" in adv.lower() or "pleistoceno" in adv.lower()

    nxt = lib.pick_next(seen_ids=[cap["id"]])
    assert nxt["id"] != cap["id"]


def test_conversation_memory_profiles_facts_and_learning_queue(tmp_path):
    mem = ConversationMemory(data_dir=tmp_path)
    p1, ret1 = mem.get_or_create_visitor("Valeria", reason="Aprender ciencia")
    assert ret1 is False
    assert p1["visit_count"] == 1

    mem.update_visitor("Valeria", topic="Agujeros negros", level="avanzado", capsule_id="fisica-agujeros-negros")
    p2, ret2 = mem.get_or_create_visitor("valeria")
    assert ret2 is True
    assert p2["visit_count"] == 2
    assert p2["pedagogical_level"] == "avanzado"
    assert "Agujeros negros" in p2["topics_studied"]

    mem.remember_fact("Valeria estudia física.", category="visitor", visitor="Valeria")
    assert mem.total_learned_facts == 1

    mem.queue_question("¿Qué es la materia oscura?", visitor="Valeria")
    assert len(mem.learning_queue) == 1
    mem.mark_queue_item_done(0, "La materia oscura compone ~27% del universo.")
    assert mem.learning_queue[0]["status"] == "researched"


# ---------------------------------------------------------------------------
# 6. Director conversacional multi-turno: enseñanza + pedagogía + visión + web
# ---------------------------------------------------------------------------


class _FakeVoiceBrain:
    def __init__(self, reply: str = "Explicación interactiva clara de TARDIS. ¿Quieres profundizar?") -> None:
        self.reply = reply
        self.calls: List[Dict[str, Any]] = []
        self.fast_ollama_url = "http://127.0.0.1:11435"
        self.fast_model = "qwen3-vl:2b-instruct"

    async def chat(self, messages, **kwargs) -> Tuple[str, float, str]:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return self.reply, 0.42, "voice_gpu:qwen3-vl:2b-instruct"

    async def close(self) -> None:
        pass


class _FakeVision:
    vlm_model = "qwen3-vl:2b-instruct"

    def __init__(self, description: str = "Veo una planta suculenta verde sobre una maceta de barro.") -> None:
        self.description = description
        self.calls: List[str] = []

    async def inspect(self, question: str = "", frame_jpeg: Optional[bytes] = None) -> VisionObservation:
        self.calls.append(question)
        return VisionObservation(
            ok=True,
            description=self.description,
            latency_ms=850.0,
            model=self.vlm_model,
            backend="http://127.0.0.1:11435",
            frame_size=(448, 252),
        )


class _FakeResearch:
    def __init__(self) -> None:
        self.queries: List[str] = []

    async def research(self, raw_query: str, visitor_name: str = "", visual_context: str = "", persist: bool = True) -> ResearchFinding:
        self.queries.append(raw_query)
        return ResearchFinding(
            ok=True,
            query=raw_query,
            summary="Las plantas suculentas almacenan agua en sus hojas gruesas y realizan fotosíntesis CAM para resistir climas secos.",
            sources=[{"title": "Suculenta (Wikipedia ES)", "url": "https://es.wikipedia.org/wiki/Planta_suculenta", "engine": "wikipedia_es"}],
            elapsed_ms=210.0,
        )


def test_director_full_interactive_teaching_vision_and_research_flow(tmp_path):
    mem = ConversationMemory(data_dir=tmp_path)
    caps = CapsuleLibrary(path=tmp_path / "capsules.json")
    brain = _FakeVoiceBrain()
    vision = _FakeVision()
    research = _FakeResearch()

    director = ConversationDirector(
        brain=brain,
        vision=vision,
        research=research,
        memory=mem,
        capsules=caps,
    )

    prefaces: List[str] = []

    async def _on_preface(text: str) -> None:
        prefaces.append(text)

    async def _scenario():
        # 1. Inicio con handoff tras entrevista
        greet = director.start_session(trigger="interview_handoff", visitor_name="Valeria", reason="Curiosidad científica")
        assert "Valeria" in greet
        assert director.active is True

        # 2. Enseñanza por cápsula
        t1 = await director.handle_turn("Enséñame sobre los cenotes", speak_preface_cb=_on_preface)
        assert t1.intent == "teach_capsule"
        assert "cenote" in t1.reply.lower() or "caliza" in t1.reply.lower() or "karst" in t1.reply.lower()

        # 3. Ajuste pedagógico a nivel más sencillo
        t2 = await director.handle_turn("Explícamelo más fácil, no entendí")
        assert t2.intent == "pedagogical_simpler"
        assert director.pedagogical_level == "basico"

        # 4. Quiz socrático + evaluación de respuesta
        t3 = await director.handle_turn("Hazme una pregunta para evaluarme")
        assert t3.intent == "pedagogical_quiz"
        assert director.quiz_pending is True
        t4 = await director.handle_turn("Porque el agua de lluvia disuelve la roca caliza")
        assert t4.intent == "quiz_answer"
        assert director.quiz_pending is False

        # 5. Investigación combinada: Cámara Tapo C310 + Investigación Web
        t5 = await director.handle_turn(
            "Mira esto que tengo en la mano e investiga cómo funciona",
            speak_preface_cb=_on_preface,
        )
        assert t5.used_vision is True
        assert t5.used_research is True
        assert t5.intent == "vision_and_research"
        assert vision.calls
        assert research.queries
        assert any("cámara" in p.lower() for p in prefaces)

        # 6. Investigación documental pura
        t6 = await director.handle_turn("Investiga sobre la energía de fusión", speak_preface_cb=_on_preface)
        assert t6.used_research is True
        assert t6.intent == "research"
        assert len(t6.sources) >= 1

        # 7. Despedida y persistencia de sesión
        t7 = await director.handle_turn("Muchas gracias, hasta luego")
        assert t7.end_session is True
        assert director.active is False
        assert mem.total_sessions == 1
        assert "Valeria" in t7.reply

        # 8. Procesamiento de cola autónoma de aprendizaje
        mem.queue_question("¿Qué es un púlsar?", visitor="Valeria")
        learned_n = await director.process_learning_queue(max_items=2)
        assert learned_n == 1

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# 7. Integración TapoC310VoiceChannel: entrevista -> handoff interactivo y wake
# ---------------------------------------------------------------------------


def test_voice_channel_interview_handoff_opens_conversation(tmp_path, monkeypatch):
    from core.tapo_c310_voice_channel import TapoC310VoiceChannel

    cfg_path = tmp_path / "tapo_c310_config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "host": "REDACTED_IP",
                "conversation_enabled": True,
                "conversation_handoff_after_interview": True,
                "conversation_idle_exit_sec": 45,
                "visitor_interview_enabled": True,
                "visitor_interview_settle_sec": 0.0,
                "visitor_interview_retries": 0,
            }
        ),
        encoding="utf-8",
    )
    ch = TapoC310VoiceChannel(config_path=cfg_path)
    ch.conv_memory = ConversationMemory(data_dir=tmp_path / "conv")
    ch.director.memory = ch.conv_memory
    ch.director.brain = _FakeVoiceBrain("La gravedad curva el espacio-tiempo. ¿Quieres un ejemplo?")
    ch.director.vision = _FakeVision()
    ch.director.research = _FakeResearch()

    spoken: List[str] = []

    async def _fake_speak(text: str):
        spoken.append(text)
        return {"ok": True, "audio_duration_sec": 1.0}

    ch._speak = _fake_speak
    ch._write_state = lambda force=False: None
    ch._write_session_flag = lambda active_until: None
    ch._write_visitor_interview_record = lambda rec: None

    answers_iter = iter([("Sofía", "whisper"), ("Quiero aprender sobre astronomía", "whisper")])

    async def _fake_listen(field: str):
        return next(answers_iter, ("", ""))

    ch._listen_visitor_answer = _fake_listen

    async def _run():
        await ch._run_visitor_interview({"request_id": "vi_test_1", "track_ids": [7]})
        # Tras registrar a Sofía pidiendo aprender astronomía, TARDIS debe haber
        # respondido ya su solicitud y mantenido el canal en estado "conversation"!
        assert ch.state == "conversation"
        assert ch.director.active is True
        assert ch.director.visitor_name == "Sofía"
        assert ch.teaching_mode is True
        assert any("Sofía" in s or "luz" in s.lower() or "astronom" in s.lower() or "estrellas" in s.lower() for s in spoken)

        payload = ch._state_payload()
        assert payload["conversation"]["active"] is True
        assert payload["conversation"]["visitor_name"] == "Sofía"

        await ch._end_interactive_conversation("test_done")
        assert ch.state == "wake"
        await ch.brain.close()
        await ch.conv_brain.close()

    asyncio.run(_run())


def test_temporal_brain_client_never_sends_image_url_to_text_unix_server(tmp_path):
    from core.tapo_c310_voice_channel import TemporalBrainClient

    client = TemporalBrainClient(
        socket_path=tmp_path / "nonexistent.sock",
        fast_ollama_url="http://127.0.0.1:19999",
        fast_model="qwen3-vl:2b-instruct",
    )
    unix_called = False

    class _DummyUnix:
        async def post(self, *a, **k):
            nonlocal unix_called
            unix_called = True
            raise AssertionError("No debe enviarse image_url al servidor UNIX sin mmproj")

        async def aclose(self):
            pass

    class _DummyResp:
        status_code = 200

        def json(self):
            return {"message": {"content": "Veo un libro abierto sobre física."}}

    captured_payloads: List[Dict[str, Any]] = []

    class _DummyHttp:
        async def post(self, url, json=None, timeout=None):
            captured_payloads.append({"url": url, "json": json})
            return _DummyResp()

        async def aclose(self):
            pass

    client._unix_client = _DummyUnix()
    client._http_client = _DummyHttp()

    async def _run():
        text, _sec, backend = await client.chat(
            [{"role": "user", "content": "¿Qué ves?"}],
            images=[b"\xff\xd8\xff\xe0fakejpeg"],
        )
        assert unix_called is False
        assert "libro" in text.lower()
        assert backend == "voice_gpu:qwen3-vl:2b-instruct"
        assert captured_payloads[0]["url"].endswith("/api/chat")
        assert "images" in captured_payloads[0]["json"]["messages"][-1]

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 8. Regresión de fuga de tareas asyncio en TapoC310Sentinel._analysis_worker
# ---------------------------------------------------------------------------


def test_sentinel_analysis_worker_does_not_leak_stop_event_waiters(monkeypatch, tmp_path):
    from core import tapo_c310_sentinel as sentinel_mod
    from core.tapo_c310_sentinel import TapoC310Sentinel

    monkeypatch.setattr(
        sentinel_mod,
        "YoloV8PersonDetector",
        lambda **kwargs: SimpleNamespace(detect=lambda img: ([], 1.0)),
    )
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        json.dumps(
            {
                "host": "REDACTED_IP",
                "sample_interval_sec": 0.01,
                "cctv_hub_feed_enabled": False,
                "telegram_notify_enabled": False,
                "desktop_notify_enabled": False,
                "face_intel_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    sentinel = TapoC310Sentinel(config_path=cfg)
    monkeypatch.setattr(sentinel, "_update_state_file", lambda *a, **k: None)

    frame = np.full((32, 32, 3), 20, dtype=np.uint8)
    ok, enc = cv2.imencode(".jpg", frame)
    assert ok
    jpg = enc.tobytes()

    async def _run():
        worker = asyncio.create_task(sentinel._analysis_worker(client=None))
        for seq in range(1, 7):
            sentinel._latest_jpeg = jpg
            sentinel._latest_frame_ts = time.time()
            sentinel._frame_seq = seq
            sentinel._new_frame_event.set()
            await asyncio.sleep(0.03)
        # No deben acumularse waiters huérfanos en _stop_event._waiters
        waiters = getattr(sentinel._stop_event, "_waiters", [])
        assert len(waiters) <= 1, f"Se fugaron waiters en _stop_event: {len(waiters)}"
        sentinel._stop_event.set()
        await asyncio.wait_for(worker, timeout=3.0)

    asyncio.run(_run())
