"""core/telegram/calls.py - Gestión de llamadas/videollamadas Telegram, prioridad Ring 0 y notificación de arranque."""
from __future__ import annotations

from core.telegram.common import *


class TelegramCallMixin:
    """Métodos de prioridad de llamadas Telegram y despacho de sesiones de voz/video para TelegramBridge."""

    def prioritize_system(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        """Prioriza el sistema y sus funciones cuando llega una llamada por Telegram."""
        return self.prioritize_system_for_telegram_call(chat_id)

    def prioritize_system_for_telegram_call(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        """Activa el modo prioritario soberano al recibir una llamada por Telegram.

        Delega en el gestor central (compartido con el servidor de llamadas en vivo)
        para que el refuerzo de prioridad aplique tanto al bot como a la Mini App,
        con abortado automático por TTL si un proceso muere sin liberar.
        """
        self.system_priority = True
        self.system_priority_active = True
        self.priority_mode = "telegram_call"
        self.call_priority = True
        result: Dict[str, Any] = {"ok": True, "system_priority": True, "chat_id": chat_id}
        try:
            from core.telegram_call_priority import activate_call_priority

            source = f"bridge:{chat_id}" if chat_id is not None else "bridge"
            state = activate_call_priority(source, chat_id=chat_id)
            result.update({
                "manager_active": state.get("active", False),
                "holder_count": state.get("holder_count", 0),
                "priority_mode": state.get("priority_mode", "telegram_call"),
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso activando gestor de prioridad de llamada: {exc}")
        # La actividad del usuario posterga de inmediato cualquier ciclo de fondo.
        try:
            from core.idle_evolution_daemon import get_idle_evolution_daemon

            get_idle_evolution_daemon().record_user_activity()
        except Exception:
            pass
        return result

    def prioritize_system_and_functions(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        return self.prioritize_system_for_telegram_call(chat_id)

    def boost_system_priority(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        return self.prioritize_system_for_telegram_call(chat_id)

    def boost_priority_for_call(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        return self.prioritize_system_for_telegram_call(chat_id)

    def enable_system_priority(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        return self.prioritize_system_for_telegram_call(chat_id)

    def set_system_priority(self, value: bool = True, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        if value:
            return self.prioritize_system_for_telegram_call(chat_id)
        self.system_priority = False
        self.system_priority_active = False
        self.priority_mode = "normal"
        self.call_priority = False
        result: Dict[str, Any] = {"ok": True, "system_priority": False, "chat_id": chat_id}
        try:
            from core.telegram_call_priority import release_call_priority

            source = f"bridge:{chat_id}" if chat_id is not None else "bridge"
            state = release_call_priority(source)
            result.update({
                "manager_active": state.get("active", False),
                "holder_count": state.get("holder_count", 0),
                "priority_mode": state.get("priority_mode", "normal"),
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso liberando gestor de prioridad de llamada: {exc}")
        return result

    def on_telegram_call(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        return self.prioritize_system_for_telegram_call(chat_id)

    def on_telegram_call_received(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        return self.prioritize_system_for_telegram_call(chat_id)

    def handle_telegram_call_priority(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        return self.prioritize_system_for_telegram_call(chat_id)

    def restore_system_priority(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        return self.set_system_priority(False, chat_id)

    def restore_normal_priority(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        return self.set_system_priority(False, chat_id)

    def start_call(self, chat_id: int | str, user_name: str = "Usuario", initial_speech: Optional[str] = None) -> Dict[str, Any]:
        """Inicia una llamada interactiva en vivo (Mini App Full-Duplex + modo voz en chat) con el usuario de Telegram."""
        cid = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
        self.active_calls.add(cid)
        # Prioridad soberana del sistema y sus funciones al recibir llamada por Telegram
        try:
            self.prioritize_system_for_telegram_call(chat_id)
        except Exception:
            pass
        is_private_chat = not str(chat_id).startswith("-")

        # Si el usuario es el administrador conocido
        if user_name in ("Usuario", None, ""):
            if str(cid) == str(self.config.get("admin_chat_id")) or str(cid) == "REDACTED_PHONE":
                user_name = "Arquitecto"

        live_call_url = ""
        live_videocall_url = ""
        try:
            from core.telegram_live_call_server import build_live_call_url, build_live_videocall_url
            live_call_url = build_live_call_url(chat_id=chat_id, user_name=user_name)
            live_videocall_url = build_live_videocall_url(chat_id=chat_id, user_name=user_name)
        except Exception as e_url:
            logger.warning(f"Aviso generando URL de llamada en vivo: {e_url}")

        greeting_text = initial_speech or (
            f"Hola {user_name}, he abierto la línea de llamada contigo en Telegram. "
            "Toca el botón Abrir Llamada en Vivo para hablar manos libres en tiempo real, "
            "o envíame notas de voz aquí mismo y te contestaré hablándote en cada turno."
        )

        call_banner = (
            "📞 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 **[LLAMADA ENTRANTE DE GIA · TARDIS EN LÍNEA]**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Interlocutor:** {user_name} (ID: `{chat_id}`)\n"
            "🎙️ **Modalidad 1 (Manos Libres en Vivo):** Pulsa **«📞 Abrir Llamada en Vivo»** abajo para conversar en tiempo real sin presionar botones.\n"
            "📹 **Modalidad Video HD:** Pulsa **«📹 Abrir Videollamada en Vivo»** para activar cámara bidireccional y visión Qwen3-VL.\n"
            "🗣️ **Modalidad 2 (Notas de Voz):** Envía notas de voz en este chat y TARDIS te responderá con voz en cada turno.\n"
            f"⚡ **Voz Neural:** `{self.config.get('cortana_voice', 'es-MX-DaliaNeural')}` · **Motor:** `{self.active_model_label}`"
        )

        inline_buttons = []
        if live_call_url:
            if is_private_chat:
                inline_buttons.append([{"text": "📞 Abrir Llamada en Vivo (Manos Libres)", "web_app": {"url": live_call_url}}])
            else:
                inline_buttons.append([{"text": "📞 Unirse a Llamada en Vivo (Manos Libres)", "url": live_call_url}])
        if live_videocall_url:
            if is_private_chat:
                inline_buttons.append([{"text": "📹 Abrir Videollamada en Vivo (HD)", "web_app": {"url": live_videocall_url}}])
            else:
                inline_buttons.append([{"text": "📹 Unirse a Videollamada en Vivo (HD)", "url": live_videocall_url}])
        inline_buttons.append([{"text": "🔴 Colgar Llamada", "callback_data": "end_call"}])
        call_markup = {"inline_keyboard": inline_buttons}

        self.send_message(call_banner, chat_id=chat_id, reply_markup=call_markup)

        # Enviar saludo hablado inmediato como nota de voz Opus nativa
        with ChatActionKeeper(self, chat_id, "record_voice"):
            ogg = self.synthesize_speech(greeting_text)
            if ogg:
                self.send_voice(ogg, caption=f"🎙️ {greeting_text}", chat_id=chat_id)
            else:
                self.send_message(f"🗣️ {greeting_text}", chat_id=chat_id)

        return {
            "ok": True,
            "call_active": True,
            "chat_id": chat_id,
            "user_name": user_name,
            "live_call_url": live_call_url,
            "live_videocall_url": live_videocall_url,
            "speech": greeting_text,
        }

    def start_video_call(
        self,
        chat_id: int | str,
        user_name: str = "Usuario",
        initial_speech: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Inicia una videollamada bidireccional en vivo (cámara + visión VLM + avatar 60 FPS + voz full-duplex)."""
        cid = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
        self.active_calls.add(cid)
        self.active_video_calls.add(cid)
        try:
            self.prioritize_system_for_telegram_call(chat_id)
        except Exception:
            pass
        is_private_chat = not str(chat_id).startswith("-")

        if user_name in ("Usuario", None, ""):
            if str(cid) == str(self.config.get("admin_chat_id")) or str(cid) == "REDACTED_PHONE":
                user_name = "Arquitecto"

        live_videocall_url = ""
        live_call_url = ""
        try:
            from core.telegram_live_call_server import build_live_call_url, build_live_videocall_url
            live_videocall_url = build_live_videocall_url(chat_id=chat_id, user_name=user_name)
            live_call_url = build_live_call_url(chat_id=chat_id, user_name=user_name)
        except Exception as e_url:
            logger.warning(f"Aviso generando URL de videollamada en vivo: {e_url}")

        greeting_text = initial_speech or (
            f"Un placer, {user_name}. He abierto una videollamada en vivo contigo. "
            "Toca Abrir Videollamada en Vivo para encender tu cámara y conversar cara a cara en tiempo real."
        )

        video_banner = (
            "📹 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 **[VIDEOLLAMADA ENTRANTE DE TARDIS · CANAL HD EN VIVO]**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Interlocutor:** {user_name} (ID: `{chat_id}`)\n"
            "👁️ **Visión Bidireccional:** Cámara frontal/trasera y compartir pantalla con análisis en vivo `Qwen3-VL`.\n"
            "🌌 **Presencia TARDIS:** Avatar holográfico reactivo a 60 FPS + cambio a GOD-EYE C310 o Pantalla Host.\n"
            "🎙️ **Audio Full-Duplex:** Manos libres (Auto VAD) + interrupción instantánea (Barge-In) + Prioridad Soberana.\n"
            f"⚡ **Voz Neural:** `{self.config.get('cortana_voice', 'es-MX-DaliaNeural')}` · **Motor:** `{self.active_model_label}`"
        )

        inline_buttons = []
        if live_videocall_url:
            if is_private_chat:
                inline_buttons.append([{"text": "📹 Abrir Videollamada en Vivo (HD)", "web_app": {"url": live_videocall_url}}])
            else:
                inline_buttons.append([{"text": "📹 Unirse a Videollamada en Vivo (HD)", "url": live_videocall_url}])
        if live_call_url:
            if is_private_chat:
                inline_buttons.append([{"text": "📞 Abrir Solo Voz (Manos Libres)", "web_app": {"url": live_call_url}}])
            else:
                inline_buttons.append([{"text": "📞 Unirse Solo Voz", "url": live_call_url}])
        inline_buttons.append([{"text": "🔴 Colgar Videollamada", "callback_data": "end_call"}])
        call_markup = {"inline_keyboard": inline_buttons}

        self.send_message(video_banner, chat_id=chat_id, reply_markup=call_markup)

        with ChatActionKeeper(self, chat_id, "record_voice"):
            ogg = self.synthesize_speech(greeting_text)
            if ogg:
                self.send_voice(ogg, caption=f"📹 {greeting_text}", chat_id=chat_id)
            else:
                self.send_message(f"📹 {greeting_text}", chat_id=chat_id)

        return {
            "ok": True,
            "call_active": True,
            "video_call_active": True,
            "mode": "video",
            "chat_id": chat_id,
            "user_name": user_name,
            "live_videocall_url": live_videocall_url,
            "live_call_url": live_call_url,
            "speech": greeting_text,
        }

    def make_video_call(
        self,
        chat_id: Optional[int | str] = None,
        initial_speech: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Realiza una videollamada proactiva hacia el usuario autorizado."""
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No hay chat_id destino disponible"}
        u_name = (
            "Arquitecto"
            if str(target_chat) in (str(self.config.get("admin_chat_id")), "REDACTED_PHONE")
            else "Usuario"
        )
        return self.start_video_call(target_chat, user_name=u_name, initial_speech=initial_speech)

    def end_call(self, chat_id: int | str) -> Dict[str, Any]:
        """Finaliza la llamada o videollamada activa en Telegram."""
        cid = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
        was_video = cid in self.active_video_calls
        if cid in self.active_calls:
            self.active_calls.discard(cid)
        if cid in self.active_video_calls:
            self.active_video_calls.discard(cid)
        # Restaurar prioridad normal si ya no hay llamadas activas
        if not self.active_calls and not self.active_video_calls and not self.voice_mode_always:
            try:
                self.set_system_priority(False, chat_id)
            except Exception:
                pass

        farewell = (
            "Videollamada finalizada. El canal de video y voz se cierra. Puedes reactivarla cuando gustes con /videollamada."
            if was_video
            else "Llamada finalizada. El canal de voz se cierra. Puedes seguir comunicándote por texto o reactivar la llamada con /llamar."
        )
        self.send_message(
            "📵 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔴 **[LLAMADA FINALIZADA · CANAL CERRADO]**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Sesión de {'videollamada' if was_video else 'diálogo por voz'} concluida.\n"
            "💬 Para volver a conectar, envía `/videollamada` o `/llamar`.",
            chat_id=chat_id
        )
        ogg = self.synthesize_speech(farewell)
        if ogg:
            self.send_voice(ogg, caption=f"🎙️ {farewell}", chat_id=chat_id)
        return {"ok": True, "call_active": False, "video_call_active": False, "chat_id": chat_id}

    def make_call(self, chat_id: Optional[int | str] = None, initial_speech: Optional[str] = None) -> Dict[str, Any]:
        """Realiza una llamada proactiva hacia el usuario autorizado."""
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No hay chat_id destino disponible"}
        u_name = "Arquitecto (X)" if str(target_chat) in (str(self.config.get("admin_chat_id")), "REDACTED_PHONE") else "Usuario"
        return self.start_call(target_chat, user_name=u_name, initial_speech=initial_speech)

    def notify_system_boot(self, auth_url: str, local_url: str):
        """Notifica proactivamente a todos los chats autorizados que el sistema inició con éxito."""
        if not self.config.get("notify_on_boot"):
            return

        # Si ya se inició una conversación por Telegram, suprimir notificaciones del sistema activo
        if self.has_active_conversation():
            logger.info("Omitiendo notificación de arranque: conversación activa ya iniciada en Telegram.")
            return

        chats = self.config.get("allowed_chats", [])
        if not chats and self.config.get("admin_chat_id"):
            chats = [self.config.get("admin_chat_id")]

        if not chats:
            return

        msg = (
            "🚀 **TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL EN LÍNEA**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🖥️ **Estado:** Sistema encendido y auto-desbloqueado (clave: `0`).\n"
            f"🧠 **Cerebro Central:** {self.active_model_label} · 100% Soberano.\n"
            "⚡ **Enlace Web Activo:**\n"
            f"{auth_url}\n\n"
            f"📶 **Red Local Wi-Fi:** `{local_url}`\n"
            "📱 *Puedes hablarme directamente aquí o enviar /sh para controlar la terminal.*"
        )

        for cid in chats:
            if self.has_active_conversation(cid):
                continue
            try:
                self.send_message(msg, chat_id=cid, parse_mode="Markdown")
            except Exception:
                pass
