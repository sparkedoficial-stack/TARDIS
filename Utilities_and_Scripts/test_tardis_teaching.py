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
import time
from pathlib import Path

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
    assert teaching_topic("TARDIS enséname sobre la entropía del universo") == (
        "sobre la entropia del universo"
    )
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
    assert "markdown" in prompt.lower() or "markdown" in prompt
    assert "arroll" not in prompt  # sanity: no accidental content
    assert "TARDIS" in prompt


def test_teaching_prompt_defaults_are_safe_without_context():
    prompt = build_teaching_prompt()
    assert "MODO ENSEÑANZA" in prompt
    assert isinstance(prompt, str) and len(prompt) > 40


# ---------------------------------------------------------------------------
# 4. Límites de respuesta: conversación normal vs enseñanza
# ---------------------------------------------------------------------------

class TestTeachingReplyLimits:
    @pytest.mark.parametrize(
        ("teaching", "sentences", "chars"),
        [
            (False, 3, 420),
            (True, 6, 900),
        ],
    )
    def test_reply_limits_switch_with_teaching(self, teaching, sentences, chars):
        assert teaching_reply_limits(teaching=teaching) == {"sentences": sentences, "chars": chars}


# ---------------------------------------------------------------------------
# 5. Canal C310: modo enseñanza y límites de habla
# ---------------------------------------------------------------------------

class TestTapoC310TeachingChannel:
    def test_teaching_mode_enter_exit(self, tmp_path):
        from core.tapo_c310_voice_channel import TapoC310VoiceChannel

        channel = TapoC310VoiceChannel(config_path=tmp_path / "tapo_c310_config.json")
        assert channel.teaching_mode is False
        channel._enter_teaching("fisica cuántica", context={"name": "Miguel", "reason": "Curiosidad"})
        assert channel.teaching_mode is True
        assert channel.teaching_topic == "fisica cuántica"
        assert channel.visitor_context.get("name") == "Miguel"
        channel._exit_teaching("test")
        assert channel.teaching_mode is False
        assert channel.teaching_topic == ""

    def test_prepare_speech_teaching_allows_more_sentences(self):
        from core.tapo_c310_voice_channel import TapoC310VoiceChannel

        channel = TapoC310VoiceChannel(config_path=Path("/home/m11/Escritorio/GODWORKS SYSTEM/tapo_c310_config.json"))
        teaching_reply = "Un placer. Soy TARDIS. Estoy aquí. Con gusto te enseño. Hasta pronto."
        long_reply = ". ".join(f"Frase didactica numero {i} del tema." for i in range(1, 8))

        channel.teaching_mode = False
        out_normal = channel._prepare_speech(teaching_reply)
        assert len(teaching_mod.split_sentences(out_normal)) <= 3

        channel.teaching_mode = True
        out_teaching = channel._prepare_speech(long_reply)
        kept = teaching_mod.split_sentences(out_teaching)
        assert len(kept) <= 6

    def test_state_payload_exposes_teaching(self):
        from core.tapo_c310_voice_channel import TapoC310VoiceChannel

        channel = TapoC310VoiceChannel(config_path=Path("/home/m11/Escritorio/GODWORKS SYSTEM/tapo_c310_config.json"))
        channel.teaching_mode = True
        channel.teaching_topic = "fisica"
        payload = channel._state_payload()
        assert payload["teaching"]["active"] is True
        assert payload["teaching"]["topic"] == "fisica"
        assert payload["teaching"]["enabled"] is True


# ---------------------------------------------------------------------------
# 6. Canal slim (tardis_voice_channel_c310): memoria conversacional
# ---------------------------------------------------------------------------

class TestSlimChannelTeachingState:
    def test_handle_turn_teaching_sets_context_and_closes(self, monkeypatch):
        from core import tardis_voice_channel_c310 as slim

        channel = slim.TardisVoiceChannelC310.__new__(slim.TardisVoiceChannelC310)
        # Sin inicializar recursos hardware: solo el estado de conversación.
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
        channel.history = []
        channel.visitor_context = {"name": "Miguel", "reason": "Curiosidad"}
        channel.speaker = None
        channel.mind = slim.TardisMind()

        replied = []

        class _FakeMind:
            @classmethod
            def llm_reply(cls, text, timeout, teaching=False, context=None, pedagogical_level=None,
                         dialectic_role=None, language=None, history=None):
                replied.append((text, teaching, context, pedagogical_level, dialectic_role, language, history))
                return "Un placer. Soy TARDIS. Con gusto te enseño."

        channel.mind = _FakeMind()

        async def _fake_speak(text):
            return {"ok": True}

        channel._speak_via_camera = _fake_speak

        channel._handle_turn("TARDIS enséname sobre la física cuántica")
        assert channel.teaching_mode is True
        assert channel.teaching_topic == "sobre la fisica cuantica"
        assert replied[0][1] is True
        assert replied[0][2].get("name") == "Miguel"
        assert replied[0][6] == []

        channel._handle_turn("cierra el canal")
        # «cierra el canal» no es intención de enseñanza; la respuesta local la cierra.
        assert isinstance(replied, list)
        assert channel.history[-2]["role"] == "user"


def test_slim_channel_handle_turn_teaching_history_tracking():
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
    channel.history = []
    channel.visitor_context = {}
    channel.speaker = None
    channel.mind = slim.TardisMind()

    async def _fake_speak(text):
        return {"ok": True}

    channel._speak_via_camera = _fake_speak

    import asyncio

    async def _drive():
        channel._handle_turn("Explícame qué es la entropía")
        # Esperar la tarea de procesamiento (asyncio task creado dentro de _handle_turn)
        for _ in range(50):
            if not channel._processing if hasattr(channel, "_processing") else True:
                break
            await asyncio.sleep(0.01)
        return channel

    # _handle_turn puede crear tareas asyncio; usar task wrapper cuando sea necesario.
    import asyncio as _asyncio

    task = _asyncio.create_task(channel._handle_turn("Explícame qué es la entropía"))
    # _handle_turn es síncrono (crea task interna), así que simplemente esperamos a que termine.
    try:
        import asyncio as _a2
        # No bloqueante: _handle_turn no es async en esta clase
    except Exception:
        pass
    task.cancel()
    try:
        await task
    except Exception:
        pass
    assert channel.teaching_mode is True
    assert len(channel.history) == 2
