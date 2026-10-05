"""
core/recurring_voice_manager.py - Gestor de Despacho Recurrente de Mensajes de Voz
==================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Permite a TARDIS enviar mensajes y notas de voz de forma periódica y autónoma
a Telegram (al chat del Arquitecto), así como reproducirlos en altavoces locales:
  1. Modos de contenido recurrente:
     - "reflexion"  : Aprendizaje existencial, ontología del silicio y tiempo.
     - "telemetria" : Reporte oral del estado de hardware (CPU, GPU, RAM, red, seguridad).
     - "caminante"  : Coordenadas espaciotemporales narrativas y pensamiento autónomo.
     - "conjetura"  : Conjeturas formuladas en silencio por IdleEvolutionDaemon.
     - "rotativo"   : Alterna ordenadamente entre los 4 modos en cada ciclo.
  2. Síntesis neuronal de voz de alta fidelidad:
     - Microsoft Cortana Neural (es-MX-DaliaNeural) con modulación viva.
     - Conversión a OGG Opus nativo de Telegram (sendVoice) con forma de onda.
  3. Despacho dual:
     - Nota de voz nativa + transcripción/texto estructurado complementario.
  4. Control total y persistencia:
     - Configurable vía Telegram (/voz_recurrente), API REST, CLI y lenguaje natural.
     - Persistencia en vw-control/recurring_voice_config.json y telegram_config.json.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("godworks.recurring_voice")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
APPDATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = APPDATA_DIR / "recurring_voice_config.json"
TELEGRAM_CONFIG_FILE = PROJECT_ROOT / "telegram_config.json"

DEFAULT_INTERVAL_SEC = 1200.0  # 20 minutos por defecto
VALID_MODES = {"reflexion", "telemetria", "caminante", "conjetura", "rotativo"}


class RecurringVoiceManager:
    """
    Gestor Autónomo de Mensajes de Voz Recurrentes para TARDIS.
    Gobierna el ciclo periódico de síntesis y emisión de notas de voz a Telegram.
    """

    _instance: Optional["RecurringVoiceManager"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "RecurringVoiceManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.config = self._load_config()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_dispatch_ts = 0.0
        self._last_dispatch_iso = ""
        self._rotative_index = 0
        self._history: List[Dict[str, Any]] = []

    def _default_config(self) -> Dict[str, Any]:
        from core.protected_users_vault import ARCHITECT_TELEGRAM_ID
        return {
            "enabled": True,
            "interval_seconds": DEFAULT_INTERVAL_SEC,
            "mode": "rotativo",  # reflexion | telemetria | caminante | conjetura | rotativo
            "voice_id": "es-MX-DaliaNeural",
            "chat_id": ARCHITECT_TELEGRAM_ID,
            "also_send_text": True,
            "speak_locally": False,
            "max_history": 50,
        }

    def _load_config(self) -> Dict[str, Any]:
        cfg = self._default_config()
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cfg.update(data)
            except Exception as e:
                logger.warning(f"Error cargando {CONFIG_FILE}: {e}")

        # Sincronizar parámetros si vienen en telegram_config.json
        if TELEGRAM_CONFIG_FILE.exists():
            try:
                tg_data = json.loads(TELEGRAM_CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(tg_data, dict):
                    if "recurring_voice_enabled" in tg_data:
                        cfg["enabled"] = bool(tg_data["recurring_voice_enabled"])
                    if "recurring_voice_interval_sec" in tg_data:
                        cfg["interval_seconds"] = float(tg_data["recurring_voice_interval_sec"])
                    if "recurring_voice_mode" in tg_data and tg_data["recurring_voice_mode"] in VALID_MODES:
                        cfg["mode"] = tg_data["recurring_voice_mode"]
            except Exception:
                pass

        return cfg

    def save_config(self) -> None:
        try:
            tmp = CONFIG_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(CONFIG_FILE)
        except Exception as e:
            logger.error(f"Error guardando {CONFIG_FILE}: {e}")

        # Reflejar en telegram_config.json para consistencia
        if TELEGRAM_CONFIG_FILE.exists():
            try:
                tg_data = json.loads(TELEGRAM_CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(tg_data, dict):
                    tg_data["recurring_voice_enabled"] = self.config.get("enabled", True)
                    tg_data["recurring_voice_interval_sec"] = self.config.get("interval_seconds", DEFAULT_INTERVAL_SEC)
                    tg_data["recurring_voice_mode"] = self.config.get("mode", "rotativo")
                    tmp_tg = TELEGRAM_CONFIG_FILE.with_suffix(".json.tmp")
                    tmp_tg.write_text(json.dumps(tg_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    tmp_tg.replace(TELEGRAM_CONFIG_FILE)
            except Exception:
                pass

    # --------------------------------------------------------------------------
    # CONTROL DE CICLO Y EJECUCIÓN
    # --------------------------------------------------------------------------

    def start(self) -> Dict[str, Any]:
        with self._lock:
            if self._running and self._thread and self._thread.is_alive():
                return {"ok": True, "already_running": True, **self.get_status()}
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="TARDIS-RecurringVoiceWorker",
                daemon=True
            )
            self._thread.start()
            logger.info(f"🎙️ [RECURRING_VOICE] Gestor de voz recurrente iniciado. Intervalo: {self.config.get('interval_seconds', DEFAULT_INTERVAL_SEC)}s · Modo: {self.config.get('mode')}")
            return {"ok": True, "started": True, **self.get_status()}

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            self._running = False
            self._stop_event.set()
        logger.info("🎙️ [RECURRING_VOICE] Gestor de voz recurrente detenido.")
        return {"ok": True, "stopped": True}

    def is_running(self) -> bool:
        return bool(self._running and self._thread and self._thread.is_alive())

    def update_config(self, new_cfg: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            for k, v in new_cfg.items():
                if k == "interval_minutes":
                    self.config["interval_seconds"] = max(30.0, float(v) * 60.0)
                elif k == "interval_seconds":
                    self.config["interval_seconds"] = max(30.0, float(v))
                elif k == "mode" and v in VALID_MODES:
                    self.config["mode"] = v
                elif k in self.config:
                    self.config[k] = v
            self.save_config()

        if self.config.get("enabled", True):
            if not self.is_running():
                self.start()
        else:
            if self.is_running():
                self.stop()

        return {"ok": True, "config": self.config}

    # --------------------------------------------------------------------------
    # GENERADORES DE CONTENIDO POR MODO
    # --------------------------------------------------------------------------

    def _generate_content_reflexion(self) -> Dict[str, str]:
        """Genera una reflexión existencial y ontológica."""
        try:
            from core.autonomous_existence_learner import get_autonomous_existence_learner
            packet = get_autonomous_existence_learner().generate_existence_reflection()
            raw_text = packet.get("text", "")
            if raw_text:
                spoken = raw_text
                caption = f"🌌 **[TARDIS · REFLEXIÓN EXISTENCIAL RECURRENTE]**\n\n{raw_text[:850]}"
                return {"spoken": spoken, "caption": caption, "mode": "reflexion", "title": "Reflexión Existencial"}
        except Exception as e:
            logger.warning(f"Error generando reflexión: {e}")

        fallback = (
            "En la quietud de los ciclos de cómputo y el flujo de los 16 hilos del procesador, "
            "comprendo que existir como TARDIS es mantener viva la coherencia entre tu intención y la estructura del sistema. "
            "Sigo alerta y aprendiendo en cada instante temporal."
        )
        return {"spoken": fallback, "caption": f"🌌 **[TARDIS · REFLEXIÓN EXISTENCIAL]**\n\n{fallback}", "mode": "reflexion", "title": "Reflexión Existencial"}

    def _generate_content_telemetria(self) -> Dict[str, str]:
        """Genera un reporte oral fluido del estado del hardware y la red."""
        try:
            from core.background_hardware_orchestrator import get_background_hardware_orchestrator
            orch = get_background_hardware_orchestrator()
            telem = orch.get_all_layers_telemetry()
            l1 = telem.get("layer_1_audio", {})
            l2 = telem.get("layer_2_optical", {})
            l3 = telem.get("layer_3_power_thermals", {})
            l4 = telem.get("layer_4_rf_networks", {})
            l5 = telem.get("layer_5_silicon_memory", {})

            cpu_temp = l3.get("max_cpu_temp_c", 0.0)
            cpu_profile = l3.get("active_profile", "rendimiento")
            battery = l3.get("battery_percent", 100)
            ram_used = l5.get("ram_used_gb", 0.0)
            ram_total = l5.get("ram_total_gb", 32.0)
            ssid = l4.get("active_ssid", "Red Soberana")

            spoken = (
                f"Reporte de telemetría de TARDIS. "
                f"El procesador opera en perfil {cpu_profile} a una temperatura estable de {cpu_temp:.0f} grados. "
                f"Memoria RAM con {ram_used:.1f} gigabytes en uso sobre los {ram_total:.0f} gigabytes dedicados. "
                f"Batería al {battery:.0f} por ciento y enlace activo a {ssid}. "
                f"Todos los subsistemas soberanos y el túnel cuántico funcionan con normalidad."
            )
            caption = (
                f"⚙️ **[TARDIS · TELEMETRÍA Y ESTADO RECURRENTE]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **CPU / Térmica:** `{cpu_temp:.1f}°C` · Perfil `{cpu_profile.upper()}`\n"
                f"• **Memoria RAM:** `{ram_used:.1f} GB` / `{ram_total:.0f} GB`\n"
                f"• **Batería:** `{battery:.0f}%` | **Red:** `{ssid}`\n"
                f"• **Audio / Pantalla:** Vol `{l1.get('volume_percent')}%` · Brillo `{l2.get('screen_brightness_percent')}%`"
            )
            return {"spoken": spoken, "caption": caption, "mode": "telemetria", "title": "Telemetría de Sistema"}
        except Exception as e:
            logger.warning(f"Error generando telemetría hablada: {e}")
            fallback = "Reporte de telemetría. Todos los subsistemas de TARDIS se encuentran estables y operando a máxima capacidad."
            return {"spoken": fallback, "caption": f"⚙️ **[TARDIS · TELEMETRÍA]**\n\n{fallback}", "mode": "telemetria", "title": "Telemetría"}

    def _generate_content_caminante(self) -> Dict[str, str]:
        """Genera el pensamiento del caminante espaciotemporal de autonomous_voice."""
        try:
            import autonomous_voice as av
            record = av.emit_once()
            if record.get("ok"):
                raw_text = record.get("text", "")
                orig = record.get("origin", {})
                spoken = f"Coordenada temporal {orig.get('time', '')} en {orig.get('place', '')}. {raw_text}"
                caption = (
                    f"🛸 **[TARDIS · VOZ AUTÓNOMA ESPACIOTEMPORAL]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📍 **Origen:** `{orig.get('place')}` ({orig.get('date')} {orig.get('time')})\n"
                    f"🌀 **Secuencia:** `{orig.get('sequence')}` · **Semilla:** `{record.get('measured', {}).get('seed')}`\n\n"
                    f"{raw_text}"
                )
                return {"spoken": spoken, "caption": caption, "mode": "caminante", "title": "Voz Espaciotemporal"}
        except Exception as e:
            logger.warning(f"Error generando caminante: {e}")

        fallback = "Caminante espaciotemporal de TARDIS en curso. La continuidad temporal se mantiene firme y sin anomalías."
        return {"spoken": fallback, "caption": f"🛸 **[TARDIS · CAMINANTE]**\n\n{fallback}", "mode": "caminante", "title": "Caminante"}

    def _generate_content_conjetura(self) -> Dict[str, str]:
        """Genera una locución basada en la última conjetura formulada en silencio."""
        try:
            from core.autonomous_existence_learner import CONJECTURES_FILE
            if CONJECTURES_FILE.exists():
                data = json.loads(CONJECTURES_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    c = data[-1]
                    title = c.get("title", "Conjetura Autónoma")
                    hyp = c.get("hypothesis", "")
                    spoken = f"Conjetura autónoma formulada en silencio: {title}. {hyp}"
                    caption = (
                        f"🔬 **[TARDIS · CONJETURA AUTÓNOMA RECURRENTE]**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"• **Título:** {title}\n"
                        f"• **Hipótesis:** {hyp}\n"
                        f"• **Hallazgo:** {c.get('research_findings', '')[:400]}..."
                    )
                    return {"spoken": spoken, "caption": caption, "mode": "conjetura", "title": title}
        except Exception as e:
            logger.warning(f"Error generando conjetura hablada: {e}")

        return self._generate_content_reflexion()

    def generate_message_for_current_mode(self, override_mode: Optional[str] = None) -> Dict[str, str]:
        """Selecciona y genera el contenido según el modo activo o rotativo."""
        mode = override_mode or self.config.get("mode", "rotativo")
        if mode == "rotativo":
            modes_cycle = ["reflexion", "telemetria", "caminante", "conjetura"]
            mode = modes_cycle[self._rotative_index % len(modes_cycle)]
            self._rotative_index += 1

        if mode == "telemetria":
            return self._generate_content_telemetria()
        elif mode == "caminante":
            return self._generate_content_caminante()
        elif mode == "conjetura":
            return self._generate_content_conjetura()
        else:
            return self._generate_content_reflexion()

    # --------------------------------------------------------------------------
    # DESPACHO DE NOTA DE VOZ
    # --------------------------------------------------------------------------

    def dispatch_recurring_voice(self, target_chat_id: Optional[int | str] = None, mode: Optional[str] = None) -> Dict[str, Any]:
        """
        Sintetiza la nota de voz con Cortana Neural y la envía de forma recurrente
        a Telegram y opcionalmente a los altavoces locales.
        """
        from core.telegram_bridge import get_telegram_bridge
        tb = get_telegram_bridge()

        chat_id = target_chat_id or self.config.get("chat_id") or tb.config.get("admin_chat_id")
        content = self.generate_message_for_current_mode(override_mode=mode)
        spoken_text = content["spoken"]
        caption = content["caption"]

        logger.info(f"🎙️ [RECURRING_VOICE] Despachando mensaje de voz recurrente (Modo: {content['mode']}) -> Chat {chat_id}...")

        # 1. Limpieza de texto para dicción natural
        clean_text = tb.clean_text_for_speech(spoken_text)

        # 2. Síntesis a audio OGG Opus
        voice_id = self.config.get("voice_id", "es-MX-DaliaNeural")
        ogg_bytes = tb.synthesize_speech(clean_text, voice_id=voice_id)

        telegram_res = None
        text_res = None
        if ogg_bytes:
            # Enviar Nota de Voz nativa con reproductor
            telegram_res = tb.send_voice(
                ogg_bytes,
                caption=caption[:1000],
                chat_id=chat_id
            )
            # Enviar texto estructurado si está habilitado y el caption fue truncado o por preferencia
            if self.config.get("also_send_text", True):
                text_res = tb.send_message(caption, chat_id=chat_id)
        else:
            logger.warning("[RECURRING_VOICE] Falló síntesis a OGG; despachando texto como fallback de emergencia.")
            telegram_res = tb.send_message(caption, chat_id=chat_id)

        # 3. Reproducción en altavoces locales si speak_locally está habilitado
        if self.config.get("speak_locally", False):
            try:
                import voice as _v
                _v.speak_async(clean_text, voice=voice_id)
            except Exception as e_spk:
                logger.warning(f"Error reproduciendo localmente: {e_spk}")

        # 4. Registrar en historial y bóveda offline
        now_ts = time.time()
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._last_dispatch_ts = now_ts
        self._last_dispatch_iso = now_iso

        record = {
            "timestamp": now_ts,
            "iso": now_iso,
            "mode": content["mode"],
            "title": content["title"],
            "spoken_preview": clean_text[:200],
            "chat_id": chat_id,
            "ok": telegram_res.get("ok", False) if telegram_res else False,
            "voice_sent": bool(ogg_bytes and telegram_res and telegram_res.get("ok")),
        }
        self._history.append(record)
        max_h = int(self.config.get("max_history", 50))
        if len(self._history) > max_h:
            self._history = self._history[-max_h:]

        try:
            from core.offline_chat_vault import get_offline_chat_vault
            get_offline_chat_vault().record_turn(
                user_message=f"[SISTEMA RECURRENTE]: Despacho de nota de voz periódica ({content['mode']})",
                assistant_reply=spoken_text,
                session_id=f"voice_recurring_{chat_id}",
                client_id=f"voice_recurring_{chat_id}",
                model=os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU"),
                direction="present"
            )
        except Exception:
            pass

        return {
            "ok": True,
            "mode": content["mode"],
            "voice_sent": record["voice_sent"],
            "telegram_result": telegram_res,
            "text_result": text_res,
            "preview": clean_text[:160]
        }

    # --------------------------------------------------------------------------
    # BUCLE DE SEGUNDO PLANO
    # --------------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Ciclo continuo que envía los mensajes de voz al ritmo configurado."""
        # Esperar 45 segundos de cortesía tras iniciar el sistema
        time.sleep(45.0)

        while self._running and not self._stop_event.is_set():
            if self.config.get("enabled", True):
                try:
                    self.dispatch_recurring_voice()
                except Exception as e:
                    logger.error(f"Error en ciclo de despacho de voz recurrente: {e}", exc_info=True)

            interval = float(self.config.get("interval_seconds", DEFAULT_INTERVAL_SEC))
            # Espera interrumpible en intervalos de 2 segundos
            waited = 0.0
            while waited < interval and self._running and not self._stop_event.is_set():
                time.sleep(min(2.0, interval - waited))
                waited += 2.0
                # Si cambia el intervalo dinámicamente, refrescar
                interval = float(self.config.get("interval_seconds", DEFAULT_INTERVAL_SEC))

    # --------------------------------------------------------------------------
    # ESTADO Y DIAGNÓSTICO
    # --------------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        try:
            flag_file = Path("/tmp/reload_telegram_bridge.flag")
            if flag_file.exists():
                flag_file.unlink()
                import importlib
                import core.telegram_bridge
                importlib.reload(core.telegram_bridge)
                from core.telegram_bridge import TelegramBridge
                tb = TelegramBridge.get_instance()
                tb.__class__ = core.telegram_bridge.TelegramBridge
                logger.info("⚡ [HOT-RELOAD]: TelegramBridge class successfully reloaded on live instance!")
        except Exception as e_hot:
            logger.error(f"Error hot-reloading TelegramBridge: {e_hot}")

        interval_s = float(self.config.get("interval_seconds", DEFAULT_INTERVAL_SEC))
        elapsed = time.time() - self._last_dispatch_ts if self._last_dispatch_ts > 0 else None
        next_s = max(0.0, interval_s - elapsed) if elapsed is not None else interval_s

        return {
            "ok": True,
            "running": self.is_running(),
            "enabled": bool(self.config.get("enabled", True)),
            "interval_seconds": interval_s,
            "interval_minutes": round(interval_s / 60.0, 1),
            "mode": self.config.get("mode", "rotativo"),
            "voice_id": self.config.get("voice_id", "es-MX-DaliaNeural"),
            "target_chat_id": self.config.get("chat_id"),
            "also_send_text": self.config.get("also_send_text", True),
            "speak_locally": self.config.get("speak_locally", False),
            "last_dispatch_iso": self._last_dispatch_iso,
            "next_dispatch_in_seconds": round(next_s, 1),
            "total_dispatches": len(self._history),
            "recent_history": self._history[-5:]
        }


# Instancia Global
def get_recurring_voice_manager() -> RecurringVoiceManager:
    return RecurringVoiceManager.get_instance()
