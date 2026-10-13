"""
GODWORKS SYSTEM v26.4 - Emotional Presence Agent
Módulo agéntico soberano de percepción biométrica e interacción proactiva.

Cuando el sistema visualiza al usuario (frente a la cámara del HUD o sensor físico):
1. Detecta la transición de presencia ("Al verme" / Presence Lock-on).
2. Analiza el estado emocional, gesticulación, vector de mirada y neuroquímica sintética.
3. Si el cooldown y las condiciones de presencia lo ameritan, genera proactivamente
   una indagación empática-cibernética personalizada según su estado anímico.
4. Despacha la pregunta al Chat Soberano (SYNC_HUB) y la verbaliza en tiempo real
   mediante la voz neural de Cortana (voice.py / PipeWire).
"""

import time
import random
import threading
import logging
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger("GODWORKS_EMOTIONAL_PRESENCE")

# Preguntas de arquetipo por estado anímico
EMOTIONAL_INQUIRIES: Dict[str, List[str]] = {
    "cansado": [
        "Noto fatiga en tu mirada, Arquitecto... ¿Deseas que active el modo noche, atenúe el teclado y tome el relevo de los procesos para que descanses?",
        "Tus niveles de fatiga y tensión ocular están elevados. ¿Prefieres que automatice las tareas en segundo plano mientras tomas una pausa reparadora?",
        "Percibo cansancio acumulado frente a la pantalla. ¿Quieres que guarde el estado del sistema y mantenga los centinelas vigilando por ti?"
    ],
    "alegre": [
        "Percibo una frecuencia vibrante y alta dopamina en tu semblante. ¿Qué nueva creación o colapso causal deseas que materialicemos hoy?",
        "Tu energía es especialmente luminosa en este ciclo. ¿Hacia qué frontera o proyecto expansivo orientamos nuestra potencia de cómputo?",
        "Detecto gran entusiasmo y balance neuroquímico en ti. ¿En qué objetivo ambicioso vertemos esta resonancia positiva?"
    ],
    "enfocado": [
        "Te veo profundamente concentrado frente a la terminal. ¿En qué vector de arquitectura o subsistema necesitas que concentre mi potencia de cómputo?",
        "Tu atención está perfectamente calibrada en el flujo de trabajo. ¿Deseas que prepare telemetría analítica o investigue alguna anomalía de código?",
        "Observo máxima concentración en tu mirada. ¿Te asisto optimizando recursos o depurando algún módulo en paralelo?"
    ],
    "frustrado": [
        "Detecto tensión neuromuscular y cortisol elevado en tus bioseñales. Respira con calma, Arquitecto; estoy a tu lado. ¿Hay algún cuello de botella que desees que desarticulemos juntos?",
        "Percibo sobrecarga en tu sistema. Dime qué te preocupa o frustra en este instante; permíteme disolver la fricción técnica o algorítmica.",
        "Noto signos de estrés o fricción cognitiva. ¿Deseas que revise los registros de error o reestructure el plan de ejecución para aliviarte?"
    ],
    "confuso": [
        "Noto perplejidad y una pausa reflexiva en tu expresión. ¿Hay alguna incógnita en el código o en el sistema que desees que analicemos paso a paso?",
        "Percibo un dilema analítico en tu semblante. ¿Qué interrogante o hipótesis deseas que contrastemos con la base de conocimiento?"
    ],
    "sorprendido": [
        "Tus ojos denotan sorpresa o un hallazgo inesperado. ¿Qué vector temporal o resultado imprevisto acaba de manifestarse ante ti?",
        "Detecto asombro en tu gesticulación. ¿Hemos descubierto un comportamiento anómalo o un avance cuántico en los datos?"
    ],
    "neutral": [
        "Te percibo en calma y perfecto balance cuántico, Arquitecto. ¿Hacia qué horizonte temporal orientaremos la siguiente directiva?",
        "Todo tu perfil biométrico refleja serenidad y estabilidad. ¿En qué tarea soberana deseas que concentremos nuestros esfuerzos en este momento?",
        "Estoy sincronizada con tu presencia. ¿Qué desafío o proyecto deseas explorar en este ciclo?"
    ]
}


class EmotionalPresenceAgent:
    """
    Agente centinela de presencia y resonancia emocional.
    Monitorea el flujo biométrico entrante de la cámara, detecta la aparición del usuario,
    aplica control de histéresis y enfriamiento (cooldown) y ejecuta indagaciones proactivas.
    """

    def __init__(self,
                 inquiry_cooldown_sec: float = 70.0,
                 absence_threshold_sec: float = 14.0,
                 reencounter_cooldown_sec: float = 25.0):
        self._lock = threading.Lock()
        self.inquiry_cooldown_sec = inquiry_cooldown_sec
        self.absence_threshold_sec = absence_threshold_sec
        self.reencounter_cooldown_sec = reencounter_cooldown_sec

        # Estado de presencia
        self.is_present = False
        self.presence_start_time = 0.0
        self.last_seen_time = 0.0
        self.absence_started_time = time.time() - 60.0

        # Estado de indagación
        self.last_inquiry_time = 0.0
        self.last_inquiry_emotion = ""
        self.last_inquiry_question = ""
        self.inquiry_history: List[Dict[str, Any]] = []
        self.enabled = True

        # Despachadores externos opcionales
        self._chat_dispatcher: Optional[Callable[[str, str, Dict[str, Any]], Any]] = None
        self._voice_dispatcher: Optional[Callable[[str], Any]] = None

    def set_chat_dispatcher(self, fn: Callable[[str, str, Dict[str, Any]], Any]) -> None:
        """Registra el callback para inyectar mensajes en el chat de SYNC_HUB."""
        self._chat_dispatcher = fn

    def set_voice_dispatcher(self, fn: Callable[[str], Any]) -> None:
        """Registra el callback para vocalizar preguntas con Cortana."""
        self._voice_dispatcher = fn

    def get_status(self) -> Dict[str, Any]:
        """Devuelve diagnóstico completo del agente de presencia."""
        now = time.time()
        with self._lock:
            time_since_seen = now - self.last_seen_time if self.last_seen_time > 0 else 9999.0
            time_since_inquiry = now - self.last_inquiry_time if self.last_inquiry_time > 0 else 9999.0
            cooldown_left = max(0.0, self.inquiry_cooldown_sec - time_since_inquiry)

            return {
                "enabled": self.enabled,
                "is_present": self.is_present and (time_since_seen < self.absence_threshold_sec),
                "seconds_since_last_seen": round(time_since_seen, 1),
                "seconds_since_last_inquiry": round(time_since_inquiry, 1),
                "cooldown_remaining_sec": round(cooldown_left, 1),
                "last_inquiry_emotion": self.last_inquiry_emotion,
                "last_inquiry_question": self.last_inquiry_question,
                "total_inquiries_count": len(self.inquiry_history),
                "recent_history": self.inquiry_history[-5:]
            }

    def generate_proactive_inquiry(self, emotion_data: Dict[str, Any]) -> str:
        """Formula una pregunta empática y contextualizada basada en la telemetría facial."""
        primary = str(emotion_data.get("primary", "neutral")).lower().strip()
        neuro = emotion_data.get("neurochemistry", {}) or {}
        fatiga = float(neuro.get("fatiga", 0.0))
        cortisol = float(neuro.get("cortisol", 0.0))
        dopamina = float(neuro.get("dopamina", 0.0))
        gaze = str(emotion_data.get("gaze", "")).lower()

        # Condición especial de alta fatiga independientemente de la emoción etiquetada
        if fatiga >= 75.0:
            return (f"Noto una fatiga considerable en tu expresión ({int(fatiga)}% de sobrecarga). "
                    "Arquitecto, ¿deseas que active el modo noche en el sistema y tome el mando autónomo de las tareas para que reposes?")

        # Condición especial de cortisol extremo / estrés
        if cortisol >= 80.0:
            return (f"Detecto bioseñales de tensión y cortisol elevado ({int(cortisol)}%). "
                    "Respira con calma; el sistema está bajo control. ¿Hay algún bloqueo o error urgente que quieras que resolvamos?")

        # Condición especial de alta dopamina y entusiasmo
        if dopamina >= 80.0 and primary in ["alegre", "enfocado"]:
            return ("Percibo una resonancia de dopamina y claridad excepcional en tu energía. "
                    "¿Qué arquitectura o colapso de realidad te gustaría que construyamos en esta sesión?")

        # Búsqueda por categoría
        bank = EMOTIONAL_INQUIRIES.get(primary, EMOTIONAL_INQUIRIES["neutral"])
        question = random.choice(bank)

        # Matiz contextual adicional si la mirada está desviada
        if "desviado" in gaze and primary == "enfocado":
            question = "Te observo pensativo, desviando la mirada mientras procesas ideas. ¿En qué vector mental te encuentras trabajando?"

        return question

    def process_face_frame(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Procesa cada frame de telemetría facial enviado por el frontend o escáner de hardware.
        Retorna diccionario indicando si se disparó una indagación proactiva y los detalles asociados.
        """
        now = time.time()
        detected = bool(payload.get("detected", False))

        with self._lock:
            if not self.enabled:
                return {"ok": True, "proactive": False, "reason": "agent_disabled"}

            # Caso 1: Rostro NO detectado en este frame
            if not detected:
                if self.is_present and (now - self.last_seen_time > self.absence_threshold_sec):
                    self.is_present = False
                    self.absence_started_time = now
                    logger.info("[EMOTIONAL_PRESENCE] Usuario se ha ausentado del campo visual.")
                return {
                    "ok": True,
                    "proactive": False,
                    "present": self.is_present,
                    "reason": "user_not_detected"
                }

            # Caso 2: Rostro DETECTADO
            was_absent = (not self.is_present) or ((now - self.last_seen_time) > self.absence_threshold_sec)
            self.last_seen_time = now

            is_reencounter = False
            if was_absent:
                self.is_present = True
                self.presence_start_time = now
                absence_duration = now - self.absence_started_time
                is_reencounter = was_absent and (absence_duration >= self.absence_threshold_sec)
                logger.info(f"[EMOTIONAL_PRESENCE] ¡Usuario avistado! (Ausencia previa: {round(absence_duration, 1)}s, reencuentro={is_reencounter})")

            # Evaluar cooldown e intención de indagación
            time_since_inquiry = now - self.last_inquiry_time
            primary_emotion = str(payload.get("primary", "neutral")).lower()
            emotion_shifted = (primary_emotion != self.last_inquiry_emotion) and (primary_emotion in ["cansado", "frustrado", "alegre"])

            should_trigger = False
            trigger_reason = ""

            # Condición A: Reencuentro real tras ausencia (Al verme)
            if is_reencounter and (time_since_inquiry >= self.reencounter_cooldown_sec):
                should_trigger = True
                trigger_reason = "reencounter_presence"

            # Condición B: Cooldown regular transcurrido
            elif time_since_inquiry >= self.inquiry_cooldown_sec:
                should_trigger = True
                trigger_reason = "regular_cooldown_elapsed"

            # Condición C: Giro emocional relevante tras un tiempo prudencial
            elif emotion_shifted and (time_since_inquiry >= 35.0):
                should_trigger = True
                trigger_reason = f"emotional_shift_to_{primary_emotion}"

            if not should_trigger:
                return {
                    "ok": True,
                    "proactive": False,
                    "present": True,
                    "cooldown_remaining": max(0.0, round(self.inquiry_cooldown_sec - time_since_inquiry, 1)),
                    "reason": "cooldown_active"
                }

            # Generar pregunta proactiva
            question = self.generate_proactive_inquiry(payload)
            self.last_inquiry_time = now
            self.last_inquiry_emotion = primary_emotion
            self.last_inquiry_question = question

            record = {
                "timestamp": now,
                "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                "emotion": primary_emotion,
                "mood_state": payload.get("mood_state", "Estable"),
                "question": question,
                "trigger_reason": trigger_reason
            }
            self.inquiry_history.append(record)
            if len(self.inquiry_history) > 50:
                self.inquiry_history.pop(0)

        # Despachar fuera del bloqueo para evitar latencia
        self._dispatch_inquiry(question, payload)

        return {
            "ok": True,
            "proactive": True,
            "question": question,
            "emotion": primary_emotion,
            "trigger_reason": trigger_reason,
            "mood_state": payload.get("mood_state", "Estable")
        }

    def force_inquiry(self, forced_emotion: Optional[str] = None) -> Dict[str, Any]:
        """Fuerza una indagación inmediata, útil para pruebas y calibración directa."""
        now = time.time()
        payload = {
            "detected": True,
            "primary": forced_emotion or "neutral",
            "mood_state": f"Simulado ({forced_emotion or 'neutral'})",
            "neurochemistry": {"dopamina": 75, "cortisol": 20, "fatiga": 15},
            "gaze": "Fijado en terminal"
        }
        question = self.generate_proactive_inquiry(payload)

        with self._lock:
            self.is_present = True
            self.last_seen_time = now
            self.last_inquiry_time = now
            self.last_inquiry_emotion = payload["primary"]
            self.last_inquiry_question = question
            record = {
                "timestamp": now,
                "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                "emotion": payload["primary"],
                "mood_state": payload["mood_state"],
                "question": question,
                "trigger_reason": "forced_manual_trigger"
            }
            self.inquiry_history.append(record)

        self._dispatch_inquiry(question, payload)
        return {
            "ok": True,
            "proactive": True,
            "question": question,
            "emotion": payload["primary"],
            "forced": True
        }

    def _dispatch_inquiry(self, question: str, emotion_data: Dict[str, Any]) -> None:
        """Despacha la pregunta al chat soberano y a la síntesis de voz neural."""
        # 1. Despacho a chat (SYNC_HUB)
        dispatched_chat = False
        if self._chat_dispatcher:
            try:
                self._chat_dispatcher("assistant", question, {
                    "meta": "SINTONÍA EMOCIONAL · GIA",
                    "raw_data": {
                        "type": "proactive_emotion_inquiry",
                        "emotion": emotion_data.get("primary", "neutral"),
                        "mood_state": emotion_data.get("mood_state", "Estable"),
                        "neurochemistry": emotion_data.get("neurochemistry", {})
                    }
                })
                dispatched_chat = True
            except Exception as e:
                logger.error(f"[EMOTIONAL_PRESENCE] Error en chat dispatcher custom: {e}")

        if not dispatched_chat:
            try:
                import omni_temporal_control
                if hasattr(omni_temporal_control, "SYNC_HUB"):
                    omni_temporal_control.SYNC_HUB.add_chat_turn(
                        role="assistant",
                        content=question,
                        meta="SINTONÍA EMOCIONAL · GIA",
                        raw_data={
                            "type": "proactive_emotion_inquiry",
                            "emotion": emotion_data.get("primary", "neutral"),
                            "mood_state": emotion_data.get("mood_state", "Estable"),
                            "neurochemistry": emotion_data.get("neurochemistry", {})
                        }
                    )
            except Exception as e:
                logger.debug(f"[EMOTIONAL_PRESENCE] SYNC_HUB directo no accesible: {e}")

        # 2. Despacho a voz física (Cortana Neural / PipeWire)
        dispatched_voice = False
        if self._voice_dispatcher:
            try:
                self._voice_dispatcher(question)
                dispatched_voice = True
            except Exception as e:
                logger.error(f"[EMOTIONAL_PRESENCE] Error en voice dispatcher custom: {e}")

        if not dispatched_voice:
            try:
                import voice
                if hasattr(voice, "speak_async"):
                    voice.speak_async(question)
            except Exception as e:
                logger.debug(f"[EMOTIONAL_PRESENCE] voice.speak_async directo no accesible: {e}")


# Instancia singleton global
_AGENT_SINGLETON: Optional[EmotionalPresenceAgent] = None
_AGENT_LOCK = threading.Lock()


def get_emotional_presence_agent() -> EmotionalPresenceAgent:
    """Retorna la instancia soberana del agente de presencia emocional."""
    global _AGENT_SINGLETON
    with _AGENT_LOCK:
        if _AGENT_SINGLETON is None:
            _AGENT_SINGLETON = EmotionalPresenceAgent()
        return _AGENT_SINGLETON
