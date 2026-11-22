"""
tests/test_tardis_teaching.py - Conversación interactiva de enseñanza TARDIS (C310)
=====================================================================================
Regresiones de la tarea soberana del Arquitecto (₪) para la Tapo C310 (GOD-EYE @ REDACTED_IP):

  1. Detección de intenciones de enseñanza («enséname», «explícame», «instruyeme»...).
  2. Extracción del tema de enseñanza desde la frase del interlocutor.
  3. Construcción del prompt docente con contexto de visitante y pedagogía.
  4. Modo enseñanza en el canal de voz: límites de respuesta y contexto.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import tardis_teaching as teaching_mod
from core.tardis_teaching import (
    build_teaching_prompt,
    is_teaching_intent,
    teaching_reply_limits,
    teaching_topic,
)
from core.tardis_voice_local import split_sentences


# ---------------------------------------------------------------------------
# 1. Detección de intenciones de enseñanza
# ---------------------------------------------------------------------------

class TestTeachingIntent:
    @pytest.mark.parametrize(
        "phrase",
        [
            "TARDIS enséname sobre la entropía del universo",
            "Enséname a mí, por favor",
            "Explícame cómo funciona la gravedad",
            "Instruyeme en esto que quiero aprender",
            "Doctrina sobre la historia de México",
            "Oye TARDIS, enséname sobre la fotosíntesis",
        ],
    )
    def test_teach_intent_detected(self, phrase):
        assert is_teaching_intent(phrase) is True

    @pytest.mark.parametrize(
        "phrase",
        [
            "¿Qué hora es?",
            "¿Estás ahí?",
            "Hola TARDIS, ¿qué tal todo?",
            "Necesito que me ayudes a programar una función",
            "¿Qué es la entropía?",
            "",
        ],
    )
    def test_non_teach_intent_ignored(self, phrase):
        assert is_teaching_intent(phrase) is False


# ---------------------------------------------------------------------------
# 2. Tema de enseñanza
# ---------------------------------------------------------------------------

def test_teaching_topic_strips_trigger_and_filler():
    assert teaching_topic("TARDIS enséname sobre la entropía del universo") == "sobre la entropia del universo"
    assert teaching_topic("Explícame cómo funciona la gravedad") == "como funciona la gravedad"


# ---------------------------------------------------------------------------
# 3. Prompt docente
# ---------------------------------------------------------------------------

def test_teaching_prompt_contains_persona_context_and_pedagogy():
    prompt = build_teaching_prompt(
        interlocutor_name="Miguel",
        context={"reason": "Interesado en física cuántica", "topic": "Superposición cuántica"},
        pedagogical_level="avanzado",
        dialectic_role="teacher",
        language="es",
    )
    assert "MODO ENSEÑANZA" in prompt
    assert "Miguel" in prompt
    assert "Superposición cuántica" in prompt
    assert "avanzado" in prompt
    lowered = prompt.lower()
    assert "markdown" in lowered
    assert "limitaciones" in lowered


def test_teaching_prompt_defaults_are_safe_without_context():
    prompt = build_teaching_prompt()
    assert "MODO ENSEÑANZA" in prompt
    assert isinstance(prompt, str) and len(prompt) > 40


# ---------------------------------------------------------------------------
# 4. Límites de respuesta: conversación normal vs enseñanza
# ---------------------------------------------------------------------------

def test_reply_limits_switch_with_teaching():
    assert teaching_reply_limits(teaching=False) == {"sentences": 3, "chars": 420}
    assert teaching_reply_limits(teaching=True) == {"sentences": 6, "chars": 900}


# ---------------------------------------------------------------------------
# 5. Canal C310 (core/tapo_c310_voice_channel.py): modo enseñanza
# ---------------------------------------------------------------------------

def _make_channel(tmp_path: Path):
    from core.tapo_c310_voice_channel import TapoC310VoiceChannel

    return TapoC310VoiceChannel(config_path=tmp_path / "tapo_c310_config.json")


def test_teaching_mode_enter_exit(tmp_path):
    channel = _make_channel(tmp_path)
    assert channel.teaching_mode is False
    channel._enter_teaching("fisica cuántica", context={"name": "Miguel", "reason": "Curiosidad"})
    assert channel.teaching_mode is True
    assert channel.teaching_topic == "fisica cuántica"
    assert channel.visitor_context.get("name") == "Miguel"
    channel._exit_teaching("test")
    assert channel.teaching_mode is False
    assert channel.teaching_topic == ""


def test_prepare_speech_teaching_allows_more_sentences(tmp_path):
    channel = _make_channel(tmp_path)
    channel.teaching_enabled = True
    channel.max_reply_sentences = 3
    channel.max_reply_chars = 420
    channel.teaching_max_reply_sentences = 6
    channel.teaching_max_reply_chars = 900

    long_reply = ". ".join(f"Frase didactica numero {i} del tema." for i in range(1, 8))

    channel.teaching_mode = False
    out_normal = channel._prepare_speech(long_reply)
    assert len(split_sentences(out_normal)) <= 3

    channel.teaching_mode = True
    out_teaching = channel._prepare_speech(long_reply)
    assert len(split_sentences(out_teaching)) <= 6


def test_state_payload_exposes_teaching(tmp_path):
    channel = _make_channel(tmp_path)
    channel.teaching_mode = True
    channel.teaching_topic = "fisica"
    payload = channel._state_payload()
    assert payload["teaching"]["active"] is True
    assert payload["teaching"]["topic"] == "fisica"
    assert payload["teaching"]["enabled"] is True


# ---------------------------------------------------------------------------
# 6. Canal slim (core/tardis_voice_channel_c310.py): memoria e intención
# ---------------------------------------------------------------------------

def _make_slim_channel() -> Any:
    from core import tardis_voice_channel_c310 as slim

    channel = slim.TardisVoiceChannelC310.__new__(slim.TardisVoiceChannelC310)
    channel.cfg = {
        "max_reply_chars": 420,
        "max_reply_sentences": 3,
        "pedagogical_level": "intermedio",
        "dialectic_role": "teacher",
        "language": "es",
    }
    channel.llm_timeout = 25.0
    channel.followup_sec = 20.0
    channel.teaching_enabled = True
    channel.teaching_mode = False
    channel.teaching_topic = ""
    channel.teaching_max_reply_chars = 900
    channel.teaching_max_reply_sentences = 6
    channel.history: List[Dict[str, str]] = []
    channel.visitor_context: Dict[str, Any] = {"name": "Miguel", "reason": "Curiosidad"}
    channel.speaker = None

    class _FakeMind:
        def __init__(self) -> None:
            self.last_call = None

        def llm_reply(self, text, timeout, teaching=False, context=None, pedagogical_level=None,
                     dialectic_role=None, language=None, history=None):
            self.last_call = {
                "text": text,
                "teaching": teaching,
                "context": context,
                "pedagogical_level": pedagogical_level,
                "dialectic_role": dialectic_role,
                "language": language,
                "history": history,
            }
            return "Un placer. Soy TARDIS. Con gusto te enseño."

    fake_mind = _FakeMind()
    channel.mind = fake_mind
    channel._speak_via_camera = lambda text: {"ok": True}
    channel._reset_recognizer = lambda: None
    return channel, fake_mind


def test_slim_channel_handle_turn_teaching_uses_context_and_memory():
    channel, fake_mind = _make_slim_channel()

    channel._handle_turn("TARDIS enséname sobre la física cuántica")
    assert channel.teaching_mode is True
    assert channel.teaching_topic == "sobre la fisica cuantica"

    last_call = fake_mind.last_call
    assert last_call is not None
    assert last_call["teaching"] is True
    assert last_call["context"].get("name") == "Miguel"
    assert len(last_call["history"]) == 2  # memoria conversacional del canal (turno actual)

    assert len(channel.history) == 2
    assert channel.history[0]["role"] == "user"
    assert channel.history[1]["role"] == "assistant"


def test_slim_channel_handle_turn_non_teaching_keeps_history_clean():
    channel, fake_mind = _make_slim_channel()

    channel._handle_turn("¿Qué hora es?")
    assert channel.teaching_mode is False
    last_call = fake_mind.last_call
    assert last_call["teaching"] is False
    assert len(channel.history) == 2


def test_slim_channel_close_clears_teaching():
    channel, _fake_mind = _make_slim_channel()
    channel.teaching_mode = True
    channel.teaching_topic = "fisica"
    channel._close_channel()
    assert channel.teaching_mode is False
    assert channel.teaching_topic == ""
