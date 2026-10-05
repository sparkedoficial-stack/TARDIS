"""
GODWORKS SYSTEM v26.4 - Unit Tests for Emotional Presence Agent
Verifica detección de presencia ("Al verme"), histeresis, enfriamiento (cooldown),
generación empática de preguntas por arquetipos emocionales y despacho multimodal.
"""

import time
import pytest
from core.emotional_presence_agent import EmotionalPresenceAgent, get_emotional_presence_agent


@pytest.fixture
def agent():
    """Instancia limpia de EmotionalPresenceAgent para cada test."""
    return EmotionalPresenceAgent(
        inquiry_cooldown_sec=5.0,
        absence_threshold_sec=1.0,
        reencounter_cooldown_sec=2.0
    )


def test_presence_initial_state(agent):
    status = agent.get_status()
    assert status["enabled"] is True
    assert status["is_present"] is False
    assert status["total_inquiries_count"] == 0
    assert status["last_inquiry_emotion"] == ""


def test_presence_acquired_on_first_detection(agent):
    chat_messages = []
    voice_utterances = []

    agent.set_chat_dispatcher(lambda r, c, m: chat_messages.append((r, c, m)))
    agent.set_voice_dispatcher(lambda text: voice_utterances.append(text))

    frame = {
        "detected": True,
        "primary": "cansado",
        "mood_state": "Fatigado frente a pantalla",
        "neurochemistry": {"fatiga": 70, "cortisol": 40},
        "gaze": "Fijado en terminal"
    }

    res = agent.process_face_frame(frame)
    assert res["ok"] is True
    assert res["proactive"] is True
    assert res["emotion"] == "cansado"
    assert "fatiga" in res["question"].lower() or "noche" in res["question"].lower() or "descans" in res["question"].lower() or "pantalla" in res["question"].lower()

    # Verificar despacho a chat y voz
    assert len(chat_messages) == 1
    assert chat_messages[0][0] == "assistant"
    assert chat_messages[0][1] == res["question"]
    assert len(voice_utterances) == 1
    assert voice_utterances[0] == res["question"]

    # Verificar estado interno
    assert agent.is_present is True
    assert agent.last_inquiry_emotion == "cansado"
    assert len(agent.inquiry_history) == 1


def test_cooldown_suppression(agent):
    frame = {
        "detected": True,
        "primary": "neutral",
        "mood_state": "Sereno",
        "neurochemistry": {}
    }

    # Primer frame dispara indagación
    res1 = agent.process_face_frame(frame)
    assert res1["proactive"] is True

    # Segundo frame inmediato es suprimido por cooldown
    res2 = agent.process_face_frame(frame)
    assert res2["ok"] is True
    assert res2["proactive"] is False
    assert res2["reason"] == "cooldown_active"
    assert res2["cooldown_remaining"] > 0


def test_reencounter_after_absence(agent):
    frame_present = {"detected": True, "primary": "alegre"}
    frame_absent = {"detected": False}

    # 1. Aparece por primera vez
    res1 = agent.process_face_frame(frame_present)
    assert res1["proactive"] is True

    # 2. El usuario se retira de la cámara
    time.sleep(1.1)  # supera absence_threshold_sec (1.0s)
    res_absent = agent.process_face_frame(frame_absent)
    assert res_absent["present"] is False

    # 3. Esperar a que pase el reencounter_cooldown (2.0s) y simular ausencia real
    time.sleep(2.1)

    # 4. El usuario regresa ("Al verme")
    res_return = agent.process_face_frame(frame_present)
    assert res_return["proactive"] is True
    assert res_return["emotion"] == "alegre"


def test_archetype_questions_generation(agent):
    # Cansado
    q_cansado = agent.generate_proactive_inquiry({"primary": "cansado"})
    assert any(w in q_cansado.lower() for w in ["fatiga", "noche", "pausa", "descans", "pantalla", "cansancio"])

    # Alegre
    q_alegre = agent.generate_proactive_inquiry({"primary": "alegre"})
    assert any(w in q_alegre.lower() for w in ["dopamina", "luminosa", "entusiasmo", "creación", "vibrante"])

    # Enfocado
    q_enfocado = agent.generate_proactive_inquiry({"primary": "enfocado"})
    assert any(w in q_enfocado.lower() for w in ["concentrado", "arquitectura", "cómputo", "atención", "recursos"])

    # Frustrado
    q_frustrado = agent.generate_proactive_inquiry({"primary": "frustrado"})
    assert any(w in q_frustrado.lower() for w in ["cortisol", "tensión", "bloqueo", "calma", "fricción", "estrés"])

    # Neutral
    q_neutral = agent.generate_proactive_inquiry({"primary": "neutral"})
    assert any(w in q_neutral.lower() for w in ["calma", "cuántico", "serenidad", "sincronizada", "horizonte"])


def test_extreme_neurochemistry_overrides(agent):
    # Alta fatiga (>=75%) anula emoción primaria y formula asistencia de descanso
    frame_fatiga = {
        "primary": "enfocado",
        "neurochemistry": {"fatiga": 88, "cortisol": 30}
    }
    q_fatiga = agent.generate_proactive_inquiry(frame_fatiga)
    assert "fatiga considerable" in q_fatiga.lower() or "modo noche" in q_fatiga.lower()

    # Alto cortisol (>=80%) activa auxilio por estrés
    frame_cortisol = {
        "primary": "neutral",
        "neurochemistry": {"cortisol": 85, "fatiga": 20}
    }
    q_cortisol = agent.generate_proactive_inquiry(frame_cortisol)
    assert "cortisol elevado" in q_cortisol.lower() or "respira con calma" in q_cortisol.lower()


def test_force_inquiry(agent):
    voice_called = []
    agent.set_voice_dispatcher(lambda t: voice_called.append(t))

    res = agent.force_inquiry("frustrado")
    assert res["ok"] is True
    assert res["proactive"] is True
    assert res["emotion"] == "frustrado"
    assert res["forced"] is True
    assert len(voice_called) == 1


def test_device_sensors_cache_hook():
    import device_sensors
    res = device_sensors.update_face_emotion_cache({
        "detected": True,
        "primary": "enfocado",
        "mood_state": "Concentrado en terminal",
        "neurochemistry": {"dopamina": 70, "fatiga": 10}
    })
    assert isinstance(res, dict)
    assert res.get("ok") is True
    latest = device_sensors.get_latest_face_emotion()
    assert latest.get("primary") == "enfocado"
