"""core/telegram/commands_system.py - Despachador de comandos nativos de control, administración, red, seguridad y cámara C310."""
from __future__ import annotations

from core.telegram.common import *


def handle_system_command(
    self: Any,
    *,
    cmd: str,
    args: List[str],
    arg_str: str,
    text: str,
    chat_id: Any,
    msg_id: Any,
    user_id: Any,
    user_name: str,
    member_name: str,
    msg: Dict[str, Any],
) -> bool:
    """Ejecuta comandos de sistema/control/seguridad/C310. Devuelve True si la actualización ya fue atendida."""
    parts = text.split()
    if cmd in ADMIN_RESERVED_COMMANDS:
        if not self.is_architect_private_terminal(chat_id, user_id):
            if self.is_admin(user_id) or self.is_admin(chat_id):
                self.send_message(get_terminal_exclusive_denial_response(), chat_id=chat_id, reply_to_message_id=msg_id)
            else:
                self.send_message(get_admin_denial_response(), chat_id=chat_id, reply_to_message_id=msg_id)
            return True

    if cmd in ("/grupo", "/group", "/miembros", "/miembros_grupo"):
        try:
            from core.telegram_group_manager import get_telegram_group_manager
            gm = get_telegram_group_manager()
            gm.sync_group_from_api(chat_id, self.bot_token)
            summary = gm.format_group_summary(chat_id)
            self.send_message(summary, chat_id=chat_id, reply_to_message_id=msg_id)
        except Exception as e_ginfo:
            self.send_message(f"⚠️ Error consultando grupo: {e_ginfo}", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    # Detección de intenciones de videollamada y llamada en lenguaje natural
    text_lower = text.lower()
    if any(phrase in text_lower for phrase in (
        "hazme una videollamada", "inicia una videollamada", "iniciar videollamada",
        "haz una videollamada", "hacer una videollamada", "videollamada en vivo",
        "quiero una videollamada", "quiero hacer una videollamada", "llámame por video",
        "llamame por video", "llamada con video", "llamada por video",
        "abre videollamada", "abrir videollamada", "conectar videollamada",
    )):
        self.start_video_call(chat_id, user_name=user_name)
        return True

    if any(phrase in text_lower for phrase in (
        "hazme una llamada", "inicia una llamada", "iniciar llamada",
        "llámame", "llamame", "haz una llamada", "hacer una llamada",
        "llamada en vivo", "hablar por llamada", "quiero llamarte",
    )):
        self.start_call(chat_id, user_name=user_name)
        return True

    if any(phrase in text_lower for phrase in (
        "cuelga la llamada", "colgar llamada", "termina la llamada", "terminar llamada",
        "cuelga la videollamada", "colgar videollamada", "termina la videollamada", "cuelga",
    )):
        cid_int = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
        if cid_int in self.active_calls or cid_int in self.active_video_calls:
            self.end_call(chat_id)
            return True

    if cmd in ("/videollamada", "/videocall", "/video_llamada", "/vcall", "/vc", "/llamar_video"):
        vc_parts = arg_str.split(maxsplit=1)
        target = chat_id
        custom_speech = None
        if vc_parts:
            if vc_parts[0].isdigit() or vc_parts[0].startswith("-"):
                target = vc_parts[0]
                custom_speech = vc_parts[1] if len(vc_parts) > 1 else None
            else:
                custom_speech = arg_str
        self.start_video_call(target, user_name=user_name, initial_speech=custom_speech)
        return True

    if cmd in ("/llamar", "/call", "/llamada", "/iniciar_llamada", "/marcar"):
        parts = arg_str.split(maxsplit=1)
        target = chat_id
        custom_speech = None
        if parts:
            if parts[0].isdigit() or parts[0].startswith("-"):
                target = parts[0]
                custom_speech = parts[1] if len(parts) > 1 else None
            else:
                custom_speech = arg_str
        self.start_call(target, user_name=user_name, initial_speech=custom_speech)
        return True

    if cmd in ("/colgar", "/endcall", "/terminar", "/colgar_llamada", "/fin"):
        self.end_call(chat_id)
        return True

    if cmd in ("/voz_modo", "/voz_forzada"):
        if arg_str.lower() in ("on", "1", "activar", "si", "true"):
            self.voice_mode_always = True
            self.send_message("🗣️ Modo de respuesta por voz forzada activado para todos los mensajes.", chat_id=chat_id)
        elif arg_str.lower() in ("off", "0", "desactivar", "no", "false"):
            self.voice_mode_always = False
            self.send_message("🔇 Modo de respuesta por voz forzada desactivado.", chat_id=chat_id)
        else:
            st = "🟢 ACTIVADO" if self.voice_mode_always else "🔴 DESACTIVADO"
            self.send_message(f"🗣️ Modo de voz forzada: {st}. Usa `/voz_modo on` o `/voz_modo off`.", chat_id=chat_id)
        return True

    if cmd in ("/voz_recurrente", "/recurring_voice", "/voz_periodica", "/notas_recurrentes"):
        from core.recurring_voice_manager import get_recurring_voice_manager
        rvm = get_recurring_voice_manager()
        parts_arg = arg_str.split()
        subcmd = parts_arg[0].lower() if parts_arg else ""

        if subcmd in ("on", "activar", "start", "1", "si", "true"):
            new_cfg = {"enabled": True, "chat_id": chat_id}
            if len(parts_arg) > 1 and parts_arg[1].replace(".", "", 1).isdigit():
                new_cfg["interval_minutes"] = float(parts_arg[1])
            if len(parts_arg) > 2 and parts_arg[2].lower() in ("reflexion", "telemetria", "caminante", "conjetura", "rotativo"):
                new_cfg["mode"] = parts_arg[2].lower()
            rvm.update_config(new_cfg)
            rvm.start()
            st = rvm.get_status()
            self.send_message(
                f"🎙️ **[MENSAJES DE VOZ RECURRENTES ACTIVADOS]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Estado:** 🟢 ACTIVO 24/7\n"
                f"• **Intervalo:** Cada `{st['interval_minutes']}` minutos\n"
                f"• **Modo:** `{st['mode'].upper()}`\n"
                f"• **Voz:** `{st['voice_id']}` (Cortana Neural)\n"
                f"• **Destino:** Chat `{chat_id}`\n\n"
                f"TARDIS te enviará periódicamente notas de voz habladas con reproductor integrado.",
                chat_id=chat_id,
                reply_to_message_id=msg_id
            )
            return True

        elif subcmd in ("off", "desactivar", "stop", "0", "no", "false"):
            rvm.update_config({"enabled": False})
            rvm.stop()
            self.send_message("🔇 **[MENSAJES DE VOZ RECURRENTES DESACTIVADOS]**: El envío periódico de notas de voz ha sido pausado.", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        elif subcmd in ("intervalo", "tiempo", "cada"):
            if len(parts_arg) > 1 and parts_arg[1].replace(".", "", 1).isdigit():
                mins = float(parts_arg[1])
                rvm.update_config({"interval_minutes": mins})
                self.send_message(f"⏱️ Intervalo de voz recurrente establecido a **cada {mins} minutos**.", chat_id=chat_id, reply_to_message_id=msg_id)
            else:
                self.send_message("⏱️ Uso: `/voz_recurrente intervalo <minutos>`. Ejemplo: `/voz_recurrente intervalo 15`", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        elif subcmd in ("modo", "tipo"):
            if len(parts_arg) > 1 and parts_arg[1].lower() in ("reflexion", "telemetria", "caminante", "conjetura", "rotativo"):
                m = parts_arg[1].lower()
                rvm.update_config({"mode": m})
                self.send_message(f"🌀 Modo de voz recurrente establecido a: `{m.upper()}`.", chat_id=chat_id, reply_to_message_id=msg_id)
            else:
                self.send_message(
                    "🌀 Modos disponibles:\n"
                    "• `/voz_recurrente modo rotativo` (Alterna entre todos los temas)\n"
                    "• `/voz_recurrente modo reflexion` (Aprendizaje existencial y ontológico)\n"
                    "• `/voz_recurrente modo telemetria` (Reporte hablado de CPU/RAM/Red/Seguridad)\n"
                    "• `/voz_recurrente modo caminante` (Coordenadas espaciotemporales autónomas)\n"
                    "• `/voz_recurrente modo conjetura` (Conjeturas formuladas en silencio)",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
            return True

        elif subcmd in ("ahora", "test", "despachar", "enviar", "now"):
            self.send_message("🎙️ Generando y sintetizando nota de voz bajo demanda...", chat_id=chat_id, reply_to_message_id=msg_id)
            spec_mode = parts_arg[1].lower() if len(parts_arg) > 1 and parts_arg[1].lower() in ("reflexion", "telemetria", "caminante", "conjetura") else None
            res_disp = rvm.dispatch_recurring_voice(target_chat_id=chat_id, mode=spec_mode)
            if not res_disp.get("voice_sent"):
                self.send_message(f"⚠️ Aviso en despacho de voz: {res_disp}", chat_id=chat_id)
            return True

        else:
            st = rvm.get_status()
            st_lbl = "🟢 ACTIVO" if (st["running"] and st["enabled"]) else ("⏸️ EN ESPERA" if st["running"] else "🔴 DETENIDO")
            self.send_message(
                f"🎙️ **[ESTADO DE MENSAJES DE VOZ RECURRENTES]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Estado:** {st_lbl}\n"
                f"• **Intervalo:** Cada `{st['interval_minutes']}` min ({st['interval_seconds']} s)\n"
                f"• **Próximo Envío en:** `{st['next_dispatch_in_seconds']}` segundos\n"
                f"• **Modo Activo:** `{st['mode'].upper()}`\n"
                f"• **Voz:** `{st['voice_id']}` (Cortana Neural)\n"
                f"• **Total Despachados:** `{st['total_dispatches']}`\n\n"
                f"💡 **Comandos:**\n"
                f"• `/voz_recurrente on [min] [modo]` : Activar envío periódico\n"
                f"• `/voz_recurrente off` : Pausar envíos\n"
                f"• `/voz_recurrente ahora` : Enviar una nota de voz inmediatamente\n"
                f"• `/voz_recurrente intervalo <min>` : Ajustar frecuencia\n"
                f"• `/voz_recurrente modo <rotativo|reflexion|telemetria|caminante|conjetura>`",
                chat_id=chat_id,
                reply_to_message_id=msg_id
            )
            return True

    # Enrutar "/video pensante ..." y "/video abstracto ..." directamente al motor /VideoPensante
    if cmd == "/video" and arg_str.strip().lower().startswith(("pensante", "abstracto", "pensando")):
        parts_vp = arg_str.strip().split(maxsplit=1)
        cmd = "/videopensante"
        arg_str = parts_vp[1].strip() if len(parts_vp) > 1 else ""

    if cmd in ("/video", "/video_modo", "/videonota"):
        arg_l = arg_str.lower()
        if arg_l in ("on", "1", "activar", "si", "true"):
            self.video_mode_always = True
            self.config["video_mode_always"] = True
            self.save_config()
            self.send_message("🎬 **MODO VIDEO ACTIVADO**: A partir de ahora responderé exclusivamente con video del sistema hablando (sin texto plano ni voz suelta).", chat_id=chat_id)
        elif arg_l in ("off", "0", "desactivar", "no", "false"):
            self.video_mode_always = False
            self.config["video_mode_always"] = False
            self.save_config()
            self.send_message("🔇 **MODO VIDEO DESACTIVADO**: Volviendo al modo de texto o voz regular.", chat_id=chat_id)
        elif arg_l in ("nota", "circular", "redondo"):
            self.video_delivery_type = "video_note"
            self.config["video_delivery_type"] = "video_note"
            self.save_config()
            self.send_message("📹 **FORMATO CONFIGURADO**: Videonota circular (telescopio de Telegram).", chat_id=chat_id)
        elif arg_l in ("estandar", "video", "mp4", "cuadrado"):
            self.video_delivery_type = "video"
            self.config["video_delivery_type"] = "video"
            self.save_config()
            self.send_message("🎬 **FORMATO CONFIGURADO**: Video MP4 estándar con subtítulo.", chat_id=chat_id)
        else:
            st = "🟢 ACTIVADO" if self.video_mode_always else "🔴 DESACTIVADO"
            fmt = "Videonota Circular (sendVideoNote)" if self.video_delivery_type == "video_note" else "Video Estándar (sendVideo)"
            self.send_message(
                f"🎬 **ESTADO DEL MODO VIDEO**\n\n"
                f"• **Respuesta exclusiva en video:** {st}\n"
                f"• **Formato de entrega:** `{fmt}`\n\n"
                f"💡 *Comandos disponibles:*\n"
                f"• `/video on` : Activar video exclusivo\n"
                f"• `/video off` : Desactivar modo video\n"
                f"• `/video nota` : Usar videonota redonda\n"
                f"• `/video estandar` : Usar video MP4 estándar",
                chat_id=chat_id
            )
        return True

    if cmd in ("/modo", "/mode"):
        arg_l = arg_str.lower()
        if "vid" in arg_l:
            self.video_mode_always = True
            self.voice_mode_always = False
            self.config["video_mode_always"] = True
            self.config["voice_mode_always"] = False
            self.save_config()
            self.send_message("🎬 **MODO DE RESPUESTA: VIDEO DEL SISTEMA HABLANDO** (Texto y voz suelta omitidos).", chat_id=chat_id)
        elif "voz" in arg_l or "audio" in arg_l:
            self.video_mode_always = False
            self.voice_mode_always = True
            self.config["video_mode_always"] = False
            self.config["voice_mode_always"] = True
            self.save_config()
            self.send_message("🎙️ **MODO DE RESPUESTA: VOZ NEURAL (CORTANA)**.", chat_id=chat_id)
        elif "txt" in arg_l or "text" in arg_l:
            self.video_mode_always = False
            self.voice_mode_always = False
            self.config["video_mode_always"] = False
            self.config["voice_mode_always"] = False
            self.save_config()
            self.send_message("💬 **MODO DE RESPUESTA: SOLO TEXTO**.", chat_id=chat_id)
        else:
            act = "🎬 Video del Sistema Hablando" if self.video_mode_always else ("🎙️ Voz Neural" if self.voice_mode_always else "💬 Solo Texto")
            self.send_message(
                f"⚙️ **MODO ACTIVO DE RESPUESTA:** `{act}`\n\n"
                f"Cambia de modo con:\n"
                f"• `/modo video` : Responder exclusivamente con video del sistema hablando\n"
                f"• `/modo voz` : Responder con audio de voz Cortana\n"
                f"• `/modo texto` : Responder únicamente con texto",
                chat_id=chat_id
            )
        return True

    if any(phrase in text_lower for phrase in ("manda video", "mandame video", "responde con video", "habla en video", "modo video")):
        self.video_mode_always = True
        self.voice_mode_always = False
        self.config["video_mode_always"] = True
        self.config["voice_mode_always"] = False
        self.save_config()
        self.send_reply_with_video("He activado el modo de video exclusivo. A partir de ahora te responderé siempre con un video mío hablando.", chat_id=chat_id)
        return True

    if any(phrase in text_lower for phrase in ("solo texto", "desactiva video", "apaga video", "modo texto")):
        self.video_mode_always = False
        self.voice_mode_always = False
        self.config["video_mode_always"] = False
        self.config["voice_mode_always"] = False
        self.save_config()
        self.send_message("💬 He desactivado el modo video. Ahora te responderé únicamente con texto.", chat_id=chat_id)
        return True

    if any(p in text_lower for p in (
        "mensajes de voz recurrentes", "mensaje de voz recurrente", "notas de voz recurrentes",
        "nota de voz recurrente", "voz recurrente", "mensajes de voz periodicos", "mensajes de voz periódicos",
        "mandame notas de voz", "mándame notas de voz", "mandame mensajes de voz", "mándame mensajes de voz",
        "hablame de forma recurrente", "háblame de forma recurrente", "hablame periodicamente", "háblame periódicamente"
    )):
        from core.recurring_voice_manager import get_recurring_voice_manager
        rvm = get_recurring_voice_manager()
        if any(w in text_lower for w in ("desactiva", "apaga", "detener", "cancela", "stop", "quitar")):
            rvm.update_config({"enabled": False})
            rvm.stop()
            self.send_message("🔇 **[VOZ RECURRENTE PAUSADA]**: He desactivado el envío periódico de notas de voz.", chat_id=chat_id, reply_to_message_id=msg_id)
            return True
        elif any(w in text_lower for w in ("ahora", "inmediato", "prueba", "test", "ejemplo")):
            self.send_message("🎙️ Sintetizando y despachando nota de voz al instante...", chat_id=chat_id, reply_to_message_id=msg_id)
            rvm.dispatch_recurring_voice(target_chat_id=chat_id)
            return True
        else:
            m_int = re.search(r"cada\s+([0-9]+)\s*(?:min|minuto)", text_lower)
            new_cfg = {"enabled": True, "chat_id": chat_id}
            if m_int:
                new_cfg["interval_minutes"] = float(m_int.group(1))
            rvm.update_config(new_cfg)
            rvm.start()
            st = rvm.get_status()
            self.send_message(
                f"🎙️ **[HABILIDAD DE VOZ RECURRENTE ACTIVADA]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"A partir de ahora te enviaré notas de voz periódicamente cada **{st['interval_minutes']} minutos** en modo **{st['mode'].upper()}** con mi voz neuronal Cortana, tal como envío texto.\n\n"
                f"• Para enviar una ahora mismo: `/voz_recurrente ahora`\n"
                f"• Para ajustar intervalo: `/voz_recurrente intervalo <minutos>`\n"
                f"• Para cambiar modo: `/voz_recurrente modo <rotativo|reflexion|telemetria|caminante|conjetura>`\n"
                f"• Para pausar: `/voz_recurrente off`",
                chat_id=chat_id,
                reply_to_message_id=msg_id
            )
            threading.Thread(target=lambda: (time.sleep(1.0), rvm.dispatch_recurring_voice(target_chat_id=chat_id)), daemon=True).start()
            return True

    if cmd in ("/rotar", "/limpiar_tokens", "/vaciar_tokens", "/liberar_tokens", "/rotar_contexto"):
        try:
            from core.daily_context_rotator import get_daily_context_rotator
            res = get_daily_context_rotator().rotate_now()
            rep = (
                "🧹 **[ROTACIÓN DE CONTEXTO EXITOSA]**\n\n"
                f"• **Registros Archivados:** `{res['archive']['total_records']}`\n"
                f"• **Tokens Liberados Estimados:** `{res['clear']['tokens_freed_estimate']}`\n"
                f"• **Archivo Local:** `{res['archive']['json_path']}`\n"
                f"• **Próxima Rotación Automática:** `{res['next_rotation_iso']}`\n\n"
                "El contexto del modelo está 100% libre para máxima velocidad."
            )
            self.send_message(rep, chat_id=chat_id, reply_to_message_id=msg_id)
        except Exception as e_rot:
            self.send_message(f"⚠️ Error rotando contexto: {e_rot}", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/start", "/help", "/ayuda"):
        if not self.is_architect_private_terminal(chat_id, user_id):
            welcome_msg = (
                "Un placer, soy TARDIS asistente de inteligencia artificial, "
                "mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.\n\n"
                f"¡Hola, {user_name}! He sido creada por El Arquitecto (₪) como inteligencia soberana. "
                "Estoy a tu entera disposición para conversar, responder tus preguntas y compartir arte y ciencia.\n\n"
                "🎨 **¿Qué podemos hacer juntos?**\n"
                "• **Conversar de lo que quieras:** Hazme cualquier pregunta sobre ciencia, filosofía, el universo o dialoguemos con naturalidad.\n"
                "• **Crear Dibujos y Arte Procedural (ChronoVision):** Pídeme que dibuje lo que gustes: *\"TARDIS mándame un dibujo\"*, *\"dibuja una galaxia\"*, *\"dibuja la flor de la vida\"*, *\"dibuja un mandala\"*, *\"dibuja el reloj del tiempo\"*, *\"dibuja un árbol cósmico\"*, o usa `/dibujar <concepto>`.\n"
                "• **Graficación Científica:** Pídeme *\"grafica el atractor de lorenz\"*, *\"grafica sin(x)*exp(-x)\"*, o usa `/graficar <función|atractor>`.\n"
                "• **Video y Animación:** Pídeme *\"haz un video de un fractal\"* o usa `/video_gen <tema>`.\n"
                "• **Inspiración Espontánea:** Usa `/inspiracion` o `/tardis_dibuja` para que medite y dibuje algo libre para ti.\n"
                "• **Notas de Voz y Video:** Envíame notas de voz o texto y te responderé con calidez e inteligencia.\n\n"
                "✨ *Escríbeme o háblame; es un honor acompañarte en este viaje temporal.*"
            )
            self.send_message(welcome_msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        help_msg = (
            f"👑 **TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL · TELEGRAM SOBERANO**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🧠 **Cerebro Central:** {self.active_model_label} [Fijado Indefinido]\n"
            f"💻 **Usuario:** {user_name} (Chat ID: `{chat_id}`)\n\n"
            f"**✉️ Mensajes, Difusión y Dibujos a Terceros:**\n"
            f"• `/enviar <nombre|id> <mensaje>` : Despacha un mensaje a una persona o grupo\n"
            f"• `/enviar_dibujo <nombre|id> [tema]` : Genera un dibujo y lo envía a una persona o grupo\n"
            f"• `/difundir <mensaje>` : Envía un mensaje a todos los chats y grupos conocidos\n"
            f"• `/difundir_dibujo [tema]` : Genera y difunde una obra de arte a todos\n"
            f"• `/personas` o `/contactos` : Directorio de contactos y grupos registrados\n\n"
            f"**🎬 Diálogo por Video del Sistema Hablando:**\n"
            f"• `/video <on|off>` : Activar/desactivar respuesta exclusiva en video\n"
            f"• `/video <nota|estandar>` : Conmutar entre videonota circular o video MP4\n"
            f"• `/modo <video|voz|texto>` : Cambiar modo de respuesta del sistema\n\n"
            f"**🧠 Video Pensante y Abstracción Visual Autónoma (Cada 35 min):**\n"
            f"• `/VideoPensante` o `/videoAbstracto` : Búsqueda, descarga, análisis visual y abstracción cognitiva inmediata\n"
            f"• `/VideoPensante <tema>` : Investiga y abstrae un tema específico solicitado\n"
            f"• `/VideoPensante memoria` : Consulta los videos aprendidos e intereses de TARDIS\n"
            f"• `/VideoPensante ver <id>` : Detalle y abstracción profunda de un video específico\n"
            f"• `/VideoPensante status` : Estado, próximo ciclo autónomo y métricas\n\n"
            f"**👁️ Inteligencia Visual, Entorno y Veredictos:**\n"
            f"• `/veredicto` : Captura tu entorno (GOD-EYE C310), lo comprende con VLM y emite dictamen + nivel de riesgo\n"
            f"• `/veredicto local [pregunta]` : Usa la cámara del portátil en lugar de la C310\n"
            f"• `/veredicto <pregunta>` : Pregunta algo concreto sobre lo que te rodea\n"
            f"• `/veredictos` : Últimos dictámenes visuales emitidos y su riesgo\n"
            f"• `/visual` : Estado del motor de visión, VLM, OCR y bóveda\n"
            f"• *Envía cualquier foto:* TARDIS la observa, la describe y emite veredicto automáticamente.\n\n"
            f"**📡 Función Social (Publicación de Conclusiones y Videos descargados):**\n"
            f"• `/Social` o `/Socializar` : Sube a TikTok el último video de /VideoPensante y su tarjeta de conclusiones\n"
            f"• `/Social publicar <id>` : Publica un video específico de la memoria con sus conclusiones\n"
            f"• `/Social backfill [N]` : Socializa los N videos más antiguos aún sin publicar\n"
            f"• `/Social pendientes` : Consulta la cola persistente de publicaciones en espera\n"
            f"• `/Social retry` : Reintenta la cola pendiente contra la red social\n"
            f"• `/Social tarjeta <id>` : Genera y envía el MP4 de conclusiones de un video específico\n"
            f"• `/Social status|historial` : Estado del motor social y registro permanente\n\n"
            f"**🎨 Dibujo, Animación y Arte (ChronoVision & 3D Studio):**\n"
            f"• `/vp <texto|tema>` : Genera video Pixel Art hiper-realista a 1080P (1920×1080) a 60 FPS Nativos con análisis textual, investigación factual, boceto de imagen y audio sincronizado.\n"
            f"• `/v <teoría|fórmula>` : Genera animación 3D de alta complejidad y fotorrealismo en Blender 5.0.1 de teorías físicas (agujero negro de Kerr, Calabi-Yau, entrelazamiento ER=EPR, ondas gravitacionales, efecto túnel, etc.)\n"
            f"• `/animacion <concepto>` : Genera animación procedural fluida 2D o 3D (galaxia, reloj temporal, metatron, mandala, synthwave, etc.)\n"
            f"• `/3d <modelo>` o `/animacion3d <modelo>` : Proyecta modelo 3D en animación orbital 360° (dna, atom, tesseract, torus, onda, etc.)\n"
            f"• `/animaciones <on|off>` : Activar/desactivar envío prioritario de animaciones en lugar de imágenes fijas\n"
            f"• `/dibujar <concepto>` : Dibuja geometría sagrada, esquemas HUD o arte en movimiento\n"
            f"• `/graficar <función|atractor>` : Grafica funciones 2D/3D o atractores caóticos (lorenz, rossler, clifford)\n"
            f"• `/video_gen <tema>` : Genera un video dinámico MP4 acelerado por hardware NVENC\n"
            f"• `/inspiracion` o `/tardis_dibuja` : TARDIS medita y crea autónomamente arte o animaciones libres para ti\n"
            f"• *Lenguaje Natural:* Escribe libremente \"/v kerr\", \"/v calabi-yau\", \"TARDIS genera una animación\", \"muestra en 3d el átomo\", etc.\n\n"
            f"**📞 Diálogo, Llamadas y Videollamadas en Vivo:**\n"
            f"• `/videollamada` o `/videocall` : Iniciar videollamada HD bidireccional en vivo con visión Qwen3-VL y avatar 60 FPS\n"
            f"• `/llamar` o `/call` : Iniciar llamada interactiva por voz con GIA\n"
            f"• `/colgar` o `/endcall` : Finalizar llamada o videollamada activa\n"
            f"• `/voz_modo <on|off>` : Activar/desactivar respuesta por voz en todos los turnos\n"
            f"• `/voz_recurrente <on|off|ahora|intervalo|modo>` : Envío periódico recurrente de notas de voz a Telegram\n"
            f"• *Notas de Voz:* Envía cualquier nota de voz y GIA te responderá por video o voz hablada.\n\n"
            f"**🎮 Comandos de Control Maestro:**\n"
            f"• `/link` o `/qr` : Enlace web activo y código QR\n"
            f"• `/sh <cmd>` : Ejecutar comando en la terminal Linux\n"
            f"• `/status` : Telemetría completa (CPU, 18GB RAM, GPU, batería, Wi-Fi)\n"
            f"• `/shot [ventana <título|clase>]` : Captura de pantalla completa o de una ventana concreta\n"
            f"• `/ventanas` : Lista ventanas abiertas para capturarlas por nombre\n"
            f"• `/avances [on|off]` : Capturas automáticas del avance de los programas creados por FTL/por voz\n"
            f"• `/avances intervalo <30-900>` · `/avances ventana <título>` : Ajuste y captura de una ventana\n"
            f"• `/lock` / `/unlock` : Bloquear / Desbloquear pantalla (clave 0)\n"
            f"• `/vol <0-100>` : Ajustar volumen de la laptop\n"
            f"• `/mute` / `/unmute` : Silenciar o activar audio\n"
            f"• `/kbd <0-3>` : Controlar brillo del teclado ASUS TUF\n"
            f"• `/wifi` o `/hotspot` : Red Wi-Fi Soberana TimeMachine (SSID, Clave, Clientes)\n"
            f"• `/auditar` o `/shield` : Auditoría de red, dispositivos, filtro adblock y anti-espionaje\n"
            f"• `/trafico` o `/accesos` : Auditoría de flujos en vivo, quién accede a tus dispositivos y conexiones\n"
            f"• `/recurrentes` o `/frecuentes` : Entidades que reciben tu tráfico recurrentemente y motivo causal\n"
            f"• `/adblock` : Alternar filtro DNS Sinkhole de publicidad\n"
            f"• `/mente` o `/ruido` : Espectrograma 2D de ruido cognitivo y fase de pensamiento\n"
            f"• `/say <texto>` : Síntesis de voz hablada en los altavoces de la PC\n"
            f"• `/sms <número> <msg>` : Enviar SMS a cualquier teléfono móvil\n"
            f"• `/sms_status` : Estado del puente SMS y proveedores\n"
            f"• `/reboot` : Reiniciar el equipo (orden manual) (orden manual)\n"
            f"• `/agy` : Estado y arranque de Google Antigravity\n"
            f"• `/ftl <petición>` : Pedir a FTL creación o mejora de código (`/ftl` para ver opciones)\n"
            f"• `/ftl-local` : Acceso soberano a FTL concedido mediante red local (LAN) · `/ftl-local` para activar\n"
            f"• `/timeemergency <msg>` : Chatear con TimeEmergency (Qwen3.8-27B)\n\n"
            f"**🔬 Exploración Científica & Papers Académicos (OpenAlex, arXiv, EuropePMC):**\n"
            f"• `/investigar <tema>` : Investigación profunda de rigor científico con enlaces y PDFs\n"
            f"• `/paper <tema>` : Búsqueda de papers revisados por pares con enlaces de acceso directo\n"
            f"• `/agenda` : Currículum autónomo de aprendizaje continuo y temas pendientes\n"
            f"• `/agenda agregar <tema>` : Añadir tema científico a la cola de estudio\n"
            f"• `/agenda siguiente` : Investigar de inmediato el próximo tema en cola\n"
            f"• `/agenda auto <on|off>` : Activar/desactivar despacho autónomo periódico\n\n"
            f"💬 *También puedes hablarle directamente por audio o escribir cualquier directiva. {self.active_model_label} responderá de inmediato.*"
        )
        self.send_message(help_msg, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    # ----------------------------------------------------------------------
    # COMANDOS DE INVESTIGACIÓN CIENTÍFICA (/investigar, /paper, /agenda, /ciencia)
    # ----------------------------------------------------------------------
    if cmd in ("/investigar", "/investigacion", "/investigación", "/paper", "/papers", "/ciencia", "/science"):
        if not arg_str:
            self.send_message(
                "🔬 **[SISTEMA DE INVESTIGACIÓN DE RIGOR CIENTÍFICO]**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "• **Uso:** `/investigar <tema de interés>`\n"
                "• **Ejemplos:**\n"
                "   `/investigar Entrelazamiento Cuántico y Teorema de Bell`\n"
                "   `/investigar Termodinámica del No Equilibrio y Sintropía`\n"
                "   `/investigar State Space Models vs Transformers`\n"
                "   `/investigar Fusión Nuclear Confinamiento Magnético`\n"
                "   `/paper CRISPR-Cas9 y Epigenética`\n\n"
                "💡 *El sistema buscará en arXiv, OpenAlex, Nature, Science y Europe PMC, sintetizará el marco teórico y te enviará enlaces directos a los artículos y PDFs.*",
                chat_id=chat_id, reply_to_message_id=msg_id
            )
            return True

        self.send_message(
            f"🔬 **[INICIANDO INVESTIGACIÓN DE RIGOR CIENTÍFICO]**\n"
            f"• **Tema:** `{arg_str}`\n"
            f"• **Fuentes:** arXiv, OpenAlex (250M+ obras), Europe PMC, PubMed & DOIs\n"
            f"⏳ *Buscando literatura académica, analizando abstracts y sintetizando informe...*",
            chat_id=chat_id, reply_to_message_id=msg_id
        )

        try:
            from core.scientific_research_engine import get_scientific_research_engine
            s_engine = get_scientific_research_engine()
            with ChatActionKeeper(self, chat_id, "typing"):
                report = s_engine.execute_research(arg_str, max_papers=4)
                s_engine.send_report_to_telegram(report, chat_id=chat_id, reply_to_message_id=msg_id)
        except Exception as e_sci:
            logger.error(f"Error en comando /investigar: {e_sci}")
            self.send_message(f"⚠️ Error ejecutando investigación científica: {e_sci}", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/agenda", "/curriculum", "/aprendizaje"):
        from core.scientific_research_engine import get_scientific_research_engine
        s_engine = get_scientific_research_engine()
        agenda = s_engine.load_agenda()
        topics = agenda.get("topics", [])

        subparts = arg_str.split(maxsplit=1)
        subcmd = subparts[0].lower() if subparts else ""
        subarg = subparts[1].strip() if len(subparts) > 1 else ""

        if subcmd in ("agregar", "add", "nuevo"):
            if not subarg:
                self.send_message("⚠️ Especifica el tema. Ejemplo: `/agenda agregar Fusión Nuclear Tokamaks`", chat_id=chat_id, reply_to_message_id=msg_id)
                return True
            res_add = s_engine.add_topic_to_agenda(subarg)
            self.send_message(
                f"✅ **[TEMA AÑADIDO A LA AGENDA DE APRENDIZAJE CIENTÍFICO]**\n"
                f"• **Tema:** `{subarg}`\n"
                f"• **Prioridad:** Alta (1)\n"
                f"• **Acción:** {res_add.get('action')}\n\n"
                f"Puedes investigarlo inmediatamente con `/agenda siguiente` o dejar que el daemon lo investigue automáticamente.",
                chat_id=chat_id, reply_to_message_id=msg_id
            )
            return True

        elif subcmd in ("siguiente", "next", "ahora"):
            self.send_message("⏳ Seleccionando e investigando el próximo tema prioritario en la agenda...", chat_id=chat_id, reply_to_message_id=msg_id)
            with ChatActionKeeper(self, chat_id, "typing"):
                cycle_res = s_engine.run_autonomous_cycle(chat_id=chat_id)
                if not cycle_res.get("ok"):
                    self.send_message(f"⚠️ No se pudo completar el ciclo: {cycle_res.get('error')}", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        elif subcmd in ("auto", "daemon", "modo"):
            if subarg.lower() in ("on", "1", "activar", "si", "true"):
                agenda["autonomous_mode"] = True
                s_engine.save_agenda(agenda)
                s_engine.start_autonomous_daemon()
                self.send_message("🟢 **[APRENDIZAJE CIENTÍFICO AUTÓNOMO ACTIVADO]**: TARDIS investigará y enviará periódicamente papers a Telegram.", chat_id=chat_id, reply_to_message_id=msg_id)
            elif subarg.lower() in ("off", "0", "desactivar", "no", "false"):
                agenda["autonomous_mode"] = False
                s_engine.save_agenda(agenda)
                s_engine.stop_autonomous_daemon()
                self.send_message("🔴 **[APRENDIZAJE CIENTÍFICO AUTÓNOMO PAUSADO]**: El envío periódico ha sido detenido.", chat_id=chat_id, reply_to_message_id=msg_id)
            else:
                st_txt = "🟢 ACTIVADO" if agenda.get("autonomous_mode", True) else "🔴 DESACTIVADO"
                self.send_message(f"⚙️ Modo autónomo: {st_txt}. Usa `/agenda auto on` o `/agenda auto off`.", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        else:
            # Listar estado de la agenda
            st_txt = "🟢 ACTIVO" if agenda.get("autonomous_mode", True) else "🔴 PAUSADO"
            lines = [
                f"📖 **[AGENDA DE APRENDIZAJE & RIGOR CIENTÍFICO TARDIS]**",
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"• **Modo Autónomo:** {st_txt} (Cada `{agenda.get('interval_hours', 12)}` horas)",
                f"• **Total de Temas:** `{len(topics)}`",
                "",
                "📋 **TEMAS EN CURRÍCULUM:**"
            ]
            for i, t in enumerate(topics[:8], 1):
                icon = "✅" if t.get("status") == "completed" else "⏳"
                lines.append(f"{icon} **{i}. {t.get('topic')}**")
                lines.append(f"   🏛️ *{t.get('domain', 'General')}* · Researched: `{t.get('researched_count', 0)}`")

            if len(topics) > 8:
                lines.append(f"\n*... y {len(topics) - 8} temas más.*")

            lines.append("")
            lines.append("💡 **Comandos:**")
            lines.append("• `/agenda agregar <tema>` : Añadir nuevo tema")
            lines.append("• `/agenda siguiente` : Investigar el próximo tema ahora")
            lines.append("• `/agenda auto <on|off>` : Activar/desactivar ciclo periódico")

            self.send_message("\n".join(lines), chat_id=chat_id, reply_to_message_id=msg_id)
            return True


    if cmd in ("/enviar", "/send", "/mensaje"):
        if not arg_str:
            self.send_message(
                "✉️ **[ENVIAR MENSAJE A UNA PERSONA O GRUPO]**\n"
                "• **Uso:** `/enviar <nombre_o_id> <mensaje>`\n"
                "• **Ejemplos:**\n"
                "   `/enviar Gonzalo Hola Gonzalo, ¿cómo estás?`\n"
                "   `/enviar REDACTED_PHONE Saludos desde el puente de control.`\n"
                "   `/enviar T.A.R.D.I.S Hola a todos los del grupo.`",
                chat_id=chat_id, reply_to_message_id=msg_id
            )
            return True

        parts_send = arg_str.split(maxsplit=1)
        target_query = parts_send[0].strip()
        body_send = parts_send[1].strip() if len(parts_send) > 1 else ""

        if not body_send:
            self.send_message("⚠️ Especifica el mensaje que deseas enviar. Ejemplo: `/enviar Gonzalo Hola!`", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        from core.telegram_group_manager import get_telegram_group_manager
        gm = get_telegram_group_manager()
        target_info = gm.find_recipient(target_query)

        if not target_info:
            self.send_message(f"⚠️ No se encontró al destinatario `{target_query}` en el directorio. Revisa `/personas` o usa su Chat ID numérico.", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        dest_cid = target_info.get("chat_id")
        dest_name = target_info.get("name", str(dest_cid))

        try:
            res = self.send_message(body_send, chat_id=dest_cid)
            if res and res.get("ok"):
                self.send_message(
                    f"✅ **[MENSAJE ENVIADO CON ÉXITO]**\n"
                    f"• **Destinatario:** {dest_name} (ID: `{dest_cid}`)\n"
                    f"• **Mensaje:** {body_send}",
                    chat_id=chat_id, reply_to_message_id=msg_id
                )
            else:
                err_desc = res.get("description", "Error en API de Telegram") if res else "No se pudo entregar"
                group_id = target_info.get("group_id")
                if group_id:
                    fallback_msg = f"@{target_info.get('username') or dest_name}, te han enviado el siguiente mensaje: {body_send}"
                    res_grp = self.send_message(fallback_msg, chat_id=group_id)
                    if res_grp and res_grp.get("ok"):
                        self.send_message(f"ℹ️ El usuario no tiene chat privado iniciado con el bot. Se entregó en el grupo compartido.", chat_id=chat_id, reply_to_message_id=msg_id)
                        return True
                self.send_message(f"⚠️ Fallo al despachar a {dest_name} (`{dest_cid}`): {err_desc}", chat_id=chat_id, reply_to_message_id=msg_id)
        except Exception as e_send:
            self.send_message(f"⚠️ Error despachando mensaje: {e_send}", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/enviar_dibujo", "/send_drawing", "/mandar_dibujo", "/manda_dibujo"):
        if not arg_str:
            self.send_message(
                "🎨 **[ENVIAR DIBUJO A UNA PERSONA O GRUPO]**\n"
                "• **Uso:** `/enviar_dibujo <nombre_o_id> [tema_del_dibujo]`\n"
                "• **Ejemplos:**\n"
                "   `/enviar_dibujo Gonzalo galaxia`\n"
                "   `/enviar_dibujo Gonzalo flor de la vida`\n"
                "   `/enviar_dibujo REDACTED_PHONE reloj temporal`\n"
                "   `/enviar_dibujo T.A.R.D.I.S mandala` (envía al grupo)",
                chat_id=chat_id, reply_to_message_id=msg_id
            )
            return True

        parts_d = arg_str.split(maxsplit=1)
        target_query = parts_d[0].strip()
        theme_d = parts_d[1].strip() if len(parts_d) > 1 else ""

        from core.telegram_group_manager import get_telegram_group_manager
        gm = get_telegram_group_manager()
        target_info = gm.find_recipient(target_query)

        if not target_info:
            self.send_message(f"⚠️ No se encontró al destinatario `{target_query}`. Consulta `/personas` o usa su Chat ID numérico.", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        dest_cid = target_info.get("chat_id")
        dest_name = target_info.get("name", str(dest_cid))

        self.send_message(f"🎨 Generando y renderizando dibujo en ultra HD para {dest_name}...", chat_id=chat_id, reply_to_message_id=msg_id)

        from core.chronovision_engine import get_chronovision_engine
        c_engine = get_chronovision_engine()
        c_res = c_engine.process_request(f"dibuja {theme_d}" if theme_d else "dibuja algo libre", recipient=dest_name)

        if c_res.ok and c_res.bytes_data:
            res_photo = self.send_photo(c_res.bytes_data, caption=c_res.telegram_caption, chat_id=dest_cid)
            if res_photo and res_photo.get("ok"):
                self.send_message(
                    f"✅ **[DIBUJO ENVIADO CON ÉXITO]**\n"
                    f"• **Destinatario:** {dest_name} (ID: `{dest_cid}`)\n"
                    f"• **Obra:** {c_res.title}",
                    chat_id=chat_id, reply_to_message_id=msg_id
                )
            else:
                group_id = target_info.get("group_id")
                if group_id:
                    res_p_grp = self.send_photo(c_res.bytes_data, caption=f"Para {dest_name}:\n{c_res.telegram_caption}", chat_id=group_id)
                    if res_p_grp and res_p_grp.get("ok"):
                        self.send_message(f"ℹ️ Entregado con éxito a {dest_name} en el grupo compartido.", chat_id=chat_id, reply_to_message_id=msg_id)
                        return True
                err_desc = res_photo.get("description", "Error de entrega") if res_photo else "Fallo"
                self.send_message(f"⚠️ No se pudo entregar la foto a {dest_name}: {err_desc}", chat_id=chat_id, reply_to_message_id=msg_id)
        else:
            self.send_message(f"⚠️ Error generando el dibujo: {c_res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/difundir", "/broadcast", "/difusion"):
        if not arg_str:
            self.send_message("📢 Uso: `/difundir <mensaje a enviar a todos los chats y grupos>`", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        from core.telegram_group_manager import get_telegram_group_manager
        gm = get_telegram_group_manager()
        destinations = gm.get_all_active_destinations()
        seen_cids = {d["chat_id"] for d in destinations}
        for c in self.config.get("allowed_chats", []):
            try:
                c_int = int(c)
                if c_int not in seen_cids:
                    seen_cids.add(c_int)
                    destinations.append({"chat_id": c_int, "name": f"Chat {c_int}", "type": "chat"})
            except Exception:
                pass

        sent_count = 0
        for d in destinations:
            t_cid = d["chat_id"]
            if t_cid == chat_id:
                continue
            try:
                r = self.send_message(arg_str, chat_id=t_cid)
                if r and r.get("ok"):
                    sent_count += 1
            except Exception:
                pass

        self.send_message(f"📢 **[DIFUSIÓN COMPLETADA]**: Mensaje enviado a `{sent_count}` chats y grupos activos.", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/difundir_dibujo", "/broadcast_drawing"):
        theme_b = arg_str or "universo"
        self.send_message(f"🎨 Generando obra '{theme_b}' para difusión masiva a todos los chats y grupos...", chat_id=chat_id, reply_to_message_id=msg_id)

        from core.chronovision_engine import get_chronovision_engine
        c_engine = get_chronovision_engine()
        c_res = c_engine.process_request(f"dibuja {theme_b}")

        if c_res.ok and c_res.bytes_data:
            from core.telegram_group_manager import get_telegram_group_manager
            destinations = get_telegram_group_manager().get_all_active_destinations()
            seen_cids = {d["chat_id"] for d in destinations}
            for c in self.config.get("allowed_chats", []):
                try:
                    c_int = int(c)
                    if c_int not in seen_cids:
                        seen_cids.add(c_int)
                        destinations.append({"chat_id": c_int, "name": f"Chat {c_int}"})
                except Exception:
                    pass

            sent_count = 0
            for d in destinations:
                t_cid = d["chat_id"]
                try:
                    r = self.send_photo(c_res.bytes_data, caption=c_res.telegram_caption, chat_id=t_cid)
                    if r and r.get("ok"):
                        sent_count += 1
                except Exception:
                    pass
            self.send_message(f"🎨 **[DIBUJO DIFUNDIDO]**: Obra '{c_res.title}' enviada a `{sent_count}` chats y grupos.", chat_id=chat_id, reply_to_message_id=msg_id)
        else:
            self.send_message(f"⚠️ Error generando obra: {c_res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/personas", "/contactos", "/directorio", "/lista_personas"):
        from core.telegram_group_manager import get_telegram_group_manager
        summary = get_telegram_group_manager().format_all_contacts_summary()
        self.send_message(summary, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/link", "/enlace", "/qr"):
        from omni_temporal_control import BRIDGE
        b_status = BRIDGE.get_status()
        auth_url = b_status.get("auth_url", "")
        local_url = b_status.get("local_url", "")
        perm_url = "https://ntfy.sh/godworks_sovereign_timemachine_portal"

        msg_link = (
            f"🌐 **ESTADO DE CONEXIÓN A GODWORKS**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📶 **Red Local Loopback:**\n`{local_url}`\n\n"
            f"🔒 **Nota de Seguridad:** La terminal y accesos privilegiados están limitados al host físico local."
        )
        self.send_message(msg_link, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/sh", "/bash", "/cmd", "/terminal"):
        if not self.is_architect_private_terminal(chat_id, user_id):
            if self.is_admin(user_id) or self.is_admin(chat_id):
                self.send_message(get_terminal_exclusive_denial_response(), chat_id=chat_id, reply_to_message_id=msg_id)
            else:
                self.send_message(get_admin_denial_response(), chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        if not arg_str:
            help_sh = (
                "⚡ <b>[TERMINAL SOBERANA :: CONTROL ABSOLUTO]</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "• <b>Terminal exclusiva del Arquitecto (REDACTED_PHONE)</b>\n"
                "• Ejecuta cualquier comando bash directamente en el host.\n\n"
                "<b>Uso:</b> <code>/sh &lt;comando bash&gt;</code>\n\n"
                "<b>Ejemplos:</b>\n"
                "• <code>/sh uptime &amp;&amp; uname -a</code>\n"
                "• <code>/sh systemctl --user status tardis</code>\n"
                "• <code>/sh nvidia-smi</code>\n"
                "• <code>/sh ls -la ~</code>"
            )
            self.send_message(help_sh, chat_id=chat_id, parse_mode="HTML", reply_to_message_id=msg_id)
            return True

        def _run_terminal_async(cmd_to_run: str, target_chat: int, reply_id: Optional[int]):
            try:
                self.send_chat_action(action="typing", chat_id=target_chat)
                t_start = time.time()
                proc = subprocess.run(
                    cmd_to_run,
                    shell=True,
                    executable="/bin/bash",
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(Path.home()),
                    env=dict(os.environ, TERM="dumb", NO_COLOR="1", COLUMNS="120")
                )
                t_elapsed = time.time() - t_start
                stdout_str = (proc.stdout or "").strip()
                stderr_str = (proc.stderr or "").strip()
                rc = proc.returncode

                status_icon = "🟢" if rc == 0 else "🔴"
                header = (
                    f"{status_icon} <b>[TERMINAL HOST · EXIT {rc} · {t_elapsed:.2f}s]</b>\n"
                    f"<code>$ {html.escape(cmd_to_run[:120])}</code>\n"
                )

                body_out = ""
                if stdout_str:
                    body_out += f"<pre><code>{html.escape(stdout_str)}</code></pre>"
                if stderr_str:
                    if body_out:
                        body_out += "\n"
                    body_out += f"⚠️ <b>stderr:</b>\n<pre><code>{html.escape(stderr_str)}</code></pre>"
                if not stdout_str and not stderr_str:
                    body_out += "<i>(Comando ejecutado exitosamente sin salida)</i>"

                full_msg = f"{header}\n{body_out}"
                if len(full_msg) > 3900:
                    full_msg = full_msg[:3700] + "\n\n<i>[Salida truncada: límite de Telegram alcanzado]</i>"

                self.send_message(full_msg, chat_id=target_chat, parse_mode="HTML", reply_to_message_id=reply_id)
            except subprocess.TimeoutExpired:
                self.send_message(
                    f"⏱️ <b>Tiempo agotado (120s):</b> <code>{html.escape(cmd_to_run)}</code>",
                    chat_id=target_chat,
                    parse_mode="HTML",
                    reply_to_message_id=reply_id
                )
            except Exception as ex_sh:
                self.send_message(
                    f"❌ <b>Error ejecutando en terminal:</b> <code>{html.escape(str(ex_sh))}</code>",
                    chat_id=target_chat,
                    parse_mode="HTML",
                    reply_to_message_id=reply_id
                )

        threading.Thread(target=_run_terminal_async, args=(arg_str, chat_id, msg_id), daemon=True).start()
        return True

    # ----------------------------------------------------------------------
    # COMANDOS DE INTELIGENCIA VISUAL (/visual, /videos, /ver)
    # ----------------------------------------------------------------------
    if cmd in ("/visual", "/inteligencia_visual", "/vision"):
        from core.visual_intelligence_engine import get_visual_intelligence_engine, DATA_DIR
        vie = get_visual_intelligence_engine()
        st = vie.get_status()
        daemon_active = False
        daemon_pid = 0
        daemon_uptime = 0.0
        st_file = DATA_DIR / "daemon_status.json"
        if st_file.exists():
            try:
                d_data = json.loads(st_file.read_text(encoding="utf-8"))
                daemon_active = d_data.get("running", False)
                daemon_pid = d_data.get("pid", 0)
                daemon_uptime = d_data.get("uptime_sec", 0.0)
            except Exception:
                pass

        msg_v = (
            f"👁️ **[TARDIS :: ESTADO DE INTELIGENCIA VISUAL]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Motor:** {st.get('engine')}\n"
            f"• **Demonio 24/7:** {'🟢 ACTIVO (PID ' + str(daemon_pid) + ')' if daemon_active else '🟡 LISTO (Bajo demanda)'}\n"
            f"• **Tiempo Activo:** {daemon_uptime/3600:.1f} horas\n"
            f"• **Videos Almacenados:** {st.get('stored_videos_count', 0)}\n"
            f"• **Imágenes Procesadas:** {st.get('stored_images_count', 0)}\n"
            f"• **Audios / Sonidos:** {st.get('stored_sounds_count', 0)}\n"
            f"• **Veredictos Emitidos:** {st.get('stored_verdicts_count', 0)}\n"
            f"• **Visión Multimodal (VLM):** {'✅ ' + str(st.get('vlm_model')) if st.get('vlm_ready') else '⚠️ Sin VLM local'}\n"
            f"• **Aceleración Whisper:** {st.get('whisper_accel')}\n"
            f"• **OCR Pytesseract:** {'✅ LISTO' if st.get('ocr_ready') else '❌'}\n"
            f"• **Bóveda Permanente:** `{st.get('vault_dir')}`\n\n"
            f"TARDIS analiza y almacena automáticamente todo video, imagen o nota visual que envíes.\n"
            f"Usa `/veredicto` para que observe tu entorno en vivo y emita un dictamen con nivel de riesgo."
        )
        self.send_message(msg_v, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/veredicto", "/dictamen", "/alrededor", "/entorno", "/que_ves", "/qué_ves", "/queves"):
        from core.visual_intelligence_engine import get_visual_intelligence_engine
        raw_args = text[len(parts[0]):].strip()
        camera_req = "auto"
        question_req = raw_args
        first_tok, _, rest_tok = raw_args.partition(" ")
        cam_aliases = {
            "c310": "c310", "godeye": "c310", "god-eye": "c310", "seguridad": "c310",
            "exterior": "c310", "camara": "c310", "cámara": "c310", "tapo": "c310",
            "local": "local", "laptop": "local", "portatil": "local", "portátil": "local",
            "webcam": "webcam", "auto": "auto",
        }
        if first_tok.lower() in cam_aliases:
            camera_req = cam_aliases[first_tok.lower()]
            question_req = rest_tok.strip()

        self.send_message(
            f"👁️ **Capturando y dictaminando el entorno** (`{camera_req}`)...\n"
            "Estoy observando la imagen con visión multimodal y emitiendo veredicto.",
            chat_id=chat_id, reply_to_message_id=msg_id
        )
        try:
            with ChatActionKeeper(self, chat_id, "upload_photo"):
                vie = get_visual_intelligence_engine()
                res_v = vie.analyze_surroundings(
                    camera=camera_req,
                    question=question_req,
                    source="telegram",
                    user_name=member_name,
                )
            try:
                self.send_photo(
                    res_v.file_path,
                    caption=f"👁️ GOD-EYE · veredicto `{res_v.id}` · riesgo {res_v.verdict_data.get('risk_level', '?')}/10",
                    chat_id=chat_id,
                )
            except Exception:
                pass
            self.send_message(res_v.full_report, chat_id=chat_id, reply_to_message_id=msg_id)
        except Exception as e_verdict:
            self.send_message(
                f"⚠️ **No pude emitir el veredicto visual:** `{e_verdict}`\n"
                "Verifica que la cámara esté disponible (`/c310` para GOD-EYE o `/veredicto local` para la cámara del portátil).",
                chat_id=chat_id, reply_to_message_id=msg_id
            )
        return True

    if cmd in ("/veredictos", "/dictamenes", "/dictámenes", "/ultimos_veredictos", "/últimos_veredictos"):
        from core.visual_intelligence_engine import get_visual_intelligence_engine
        vie = get_visual_intelligence_engine()
        recs = vie.list_recent_records(limit=8)
        recs = [r for r in recs if (r.get("verdict") or "").strip()]
        if not recs:
            self.send_message("⚖️ Aún no hay veredictos visuales registrados. Usa `/veredicto` para emitir el primero.", chat_id=chat_id, reply_to_message_id=msg_id)
            return True
        lines = ["⚖️ **[TARDIS :: ÚLTIMOS VEREDICTOS VISUALES]**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
        for r in recs:
            risk = "?"
            try:
                risk = (json.loads(r.get("metadata_json") or "{}").get("verdict_data") or {}).get("risk_level", "?")
            except Exception:
                pass
            lines.append(
                f"• `{r.get('id')}` · {str(r.get('created_at', ''))[:16].replace('T', ' ')} · riesgo {risk}/10\n"
                f"  {(r.get('verdict') or '')[:260]}...\n"
            )
        self.send_message("\n".join(lines), chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/videos", "/videos_guardados", "/boveda_videos"):
        from core.visual_intelligence_engine import get_visual_intelligence_engine
        vie = get_visual_intelligence_engine()
        vids = vie.list_stored_videos(limit=10)
        if not vids:
            self.send_message("📂 No hay videos registrados en la Bóveda de Inteligencia Visual aún.", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        lines = ["📂 **[VIDEOS ALMACENADOS EN LA BÓVEDA TARDIS]**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
        for v in vids:
            lines.append(
                f"🎬 **ID:** `{v.get('id')}`\n"
                f"• **Fecha:** {v.get('created_at', '')[:16].replace('T', ' ')} | **Duración:** {v.get('duration', 0)}s | {v.get('width', 0)}x{v.get('height', 0)}\n"
                f"• **Remitente:** {v.get('user_name', 'Usuario')}\n"
                f"• **Resumen:** {v.get('summary', '')[:140]}...\n"
            )
        lines.append("Puedes consultar el análisis completo de cualquiera con `/ver <ID>`.")
        self.send_message("\n".join(lines), chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/ver", "/analizar_video", "/video_detalle"):
        if not arg_str:
            self.send_message("⚠️ Especifica el ID del video a consultar. Ejemplo: `/ver vid_20261001_...`", chat_id=chat_id, reply_to_message_id=msg_id)
            return True
        from core.visual_intelligence_engine import get_visual_intelligence_engine
        vie = get_visual_intelligence_engine()
        rec = vie.get_record(arg_str.strip())
        if not rec:
            self.send_message(f"⚠️ No se encontró ningún registro con ID `{arg_str.strip()}`.", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        rep = (
            f"👁️ **[DETALLE DE BÓVEDA :: {rec.get('id')}]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Tipo:** {str(rec.get('media_type')).upper()} | **Fecha:** {rec.get('created_at')}\n"
            f"• **Resolución:** {rec.get('width')}x{rec.get('height')} | **Duración:** {rec.get('duration')}s\n"
            f"• **Remitente:** {rec.get('user_name')} (Chat `{rec.get('chat_id')}`)\n\n"
            f"📝 **RESUMEN:**\n{rec.get('summary')}\n\n"
            f"🎬 **LO QUE VEO:**\n{rec.get('visual_description')}\n\n"
            f"🔊 **LO QUE ESCUCHO:**\n{rec.get('audio_transcript') or '(Sin habla detectada)'}\n\n"
            f"🧠 **CONCLUSIONES DE TARDIS:**\n{rec.get('conclusions')}"
        )
        self.send_message(rep, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    # ----------------------------------------------------------------------
    # COMANDOS DE VIDEO PENSANTE / VIDEO ABSTRACTO (/VideoPensante, /videoAbstracto)
    # ----------------------------------------------------------------------
    if cmd in ("/videopensante", "/videoabstracto", "/videopensando", "/vabstracto", "/video_pensante", "/video_abstracto"):
        from core.tardis_video_thinking_engine import get_video_thinking_engine, CANONICAL_GREETING
        vte = get_video_thinking_engine()
        sub_arg = (arg_str or "").strip()

        if sub_arg.lower() in ("status", "estado", "info"):
            st = vte.get_status()
            msg_st = (
                f"🛸 **[TARDIS · VIDEO PENSANTE :: ESTADO DEL SISTEMA]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Estado:** {'🟢 ACTIVO 24/7' if st.get('enabled') else '🔴 PAUSADO'}\n"
                f"• **Frecuencia:** Cada {st.get('interval_minutes')} minutos (35 min nominal)\n"
                f"• **Último Ciclo:** Hace {st.get('elapsed_since_last_run_sec')/60:.1f} min\n"
                f"• **Próxima Búsqueda:** En {st.get('next_run_in_min')} min ({st.get('next_run_in_sec'):.0f}s)\n"
                f"• **Videos Asimilados:** {st.get('total_learned_videos')}\n"
                f"• **Último Tema:** `{st.get('last_topic') or 'Ninguno aún'}`\n"
                f"• **Auto-Mejoras:** {st.get('auto_improvements')}\n\n"
                f"Para investigar un tema específico: `/VideoPensante <tema>`\n"
                f"Para consultar la memoria de lo aprendido: `/VideoPensante memoria`"
            )
            self.send_message(msg_st, chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        if sub_arg.lower() in ("memoria", "memory", "lista", "list", "historial", "recordar", "intereses"):
            mem = vte.get_memory_summary(limit=8)
            if not mem:
                self.send_message("📂 Aún no hay videos registrados en la Memoria de Abstracción de TARDIS.", chat_id=chat_id, reply_to_message_id=msg_id)
                return True
            lines = [
                "📚 **[TARDIS :: MEMORIA DE ABSTRACCIÓN E INTERESES]**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Temas y videos aprendidos por el sistema:"
            ]
            for v in mem:
                lines.append(
                    f"🎬 **ID:** `{v.get('id')}`\n"
                    f"• **Tema:** `{v.get('topic')}` ({v.get('domain')})\n"
                    f"• **Título:** *\"{v.get('title')}\"*\n"
                    f"• **Duración:** {v.get('duration_sec', 0):.0f}s | {v.get('resolution')} | {v.get('created_at', '')[:16].replace('T', ' ')}\n"
                )
            lines.append("Consulta la abstracción completa de cualquiera con `/VideoPensante ver <ID>`.")
            self.send_message("\n".join(lines), chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        if sub_arg.lower().startswith("ver ") or sub_arg.lower().startswith("detalle "):
            v_id = sub_arg.split(maxsplit=1)[1].strip()
            det = vte.get_video_detail(v_id)
            if not det:
                self.send_message(f"⚠️ No se encontró ningún video con ID `{v_id}` en la memoria de abstracción.", chat_id=chat_id, reply_to_message_id=msg_id)
                return True
            rep = (
                f"👁️ **[TARDIS :: ABSTRACCIÓN DETALLADA :: {det.get('id')}]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏛️ **Dominio:** *{det.get('domain')}*\n"
                f"🔬 **Tema:** `{det.get('topic')}`\n"
                f"🎬 **Video:** *\"{det.get('title')}\"*\n"
                f"⏱️ **Duración:** {det.get('duration_sec', 0):.0f}s | **Resolución:** {det.get('resolution')}\n\n"
                f"💡 **POR QUÉ LE INTERESÓ A TARDIS:**\n{det.get('curiosity_rationale')}\n\n"
                f"👁️ **LO QUE VIO:**\n{det.get('visual_summary')}\n\n"
                f"🔊 **LO QUE ESCUCHÓ:**\n{det.get('audio_summary') or det.get('audio_transcript') or '(Sin habla destacada)'}\n\n"
                f"🧠 **CONCLUSIONES & ABSTRACCIÓN:**\n{det.get('abstraction_conclusions')}\n\n"
                f"📚 **APRENDIZAJES ASIMILADOS:**\n" +
                "\n".join([f"• 🔹 {ins}" for ins in det.get("learned_insights", [])]) +
                "\n\n❓ **PREGUNTAS DETONADORAS:**\n" +
                "\n".join([f"• 🔸 {q}" for q in det.get("next_questions", [])])
            )
            self.send_message(rep, chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        # Ejecución de investigación inmediata (autónoma o con tema solicitado)
        topic_req = sub_arg if sub_arg else None
        notif_msg = (
            f"🛸 **[TARDIS · INICIANDO INVESTIGACIÓN VISUAL]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• Saludo Canónico: *\"{CANONICAL_GREETING}\"*\n"
            f"• Modo: {'Investigación de tema solicitado: `' + topic_req + '`' if topic_req else 'Búsqueda autónoma de interés propio de TARDIS'}\n"
            f"• Procesando: Búsqueda en internet -> Descarga MP4 -> Análisis óptico/acústico -> Abstracción cognitiva...\n\n"
            f"⏳ En breve recibirás el video y las conclusiones completas."
        )
        self.send_message(notif_msg, chat_id=chat_id, reply_to_message_id=msg_id)

        def _run_thinking_async():
            try:
                rec = vte.execute_cycle(explicit_topic=topic_req)
                # Si el chat donde se solicitó no es admin ni general, responderle directamente
                if str(chat_id) not in rec.dispatched_chats:
                    v_path = Path(rec.file_path)
                    self.send_video(
                        video=v_path,
                        caption=f"🧠 [TARDIS :: {rec.topic}]\n{rec.title[:80]}",
                        chat_id=chat_id,
                        duration=int(rec.duration_sec),
                        reply_to_message_id=msg_id
                    )
                    rep_text = vte.format_telegram_report(rec)
                    self.send_message(rep_text, chat_id=chat_id, reply_to_message_id=msg_id)
            except Exception as e_run:
                self.send_message(f"⚠️ Error en la investigación de video pensante: {e_run}", chat_id=chat_id, reply_to_message_id=msg_id)

        threading.Thread(target=_run_thinking_async, daemon=True, name="VideoThinkingThread").start()
        return True

    # ----------------------------------------------------------------------
    # COMANDOS SOCIALES (/Social, /Socializar): publica conclusiones y videos
    # ----------------------------------------------------------------------
    if cmd in ("/social", "/socializar", "/soc"):
        from core.tardis_social_engine import get_social_engine
        se = get_social_engine()
        sub = (arg_str or "").strip()

        if sub.lower() in ("status", "estado", "info", ""):
            st = se.get_status()
            msg_st = (
                f"📡 **[TARDIS · FUNCIÓN SOCIAL :: ESTADO]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Motor Social:** {'🟢 ACTIVO' if st.get('social_enabled') else '🔴 PAUSADO'}\n"
                f"• **Auto por Ciclo:** {'Sí — cada /VideoPensante publica en X.com' if st.get('auto_on_new_cycles') else 'No — solo bajo demanda'}\n"
                f"• **X.com (`@AsleepAstronaut`):** {'🟢 Conectado y listo (videos + reflexiones)' if st.get('x_ready') else '🔴 Inactivo'}\n"
                f"• **TikTok:** {'🟢 Autenticado' if st.get('platform_ready') else '⚪ Sin tokens (cola en espera)'}\n"
                f"• **Privacidad:** `{st.get('privacy_level')}`\n"
                f"• **Log por Estado:** `{st.get('log_counts')}`\n\n"
                f"Subcomandos: `x <id|ultimo>` · `publicar <id>` · `pendientes` · `retry` · `backfill [N]` · `tarjeta <id>` · `historial`"
            )
            self.send_message(msg_st, chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        if sub.lower().startswith("x ") or sub.lower() == "x":
            parts_x = sub.split(maxsplit=1)
            vid = parts_x[1].strip() if len(parts_x) > 1 else "ultimo"
            if vid.lower() in ("ultimo", "último", "latest", ""):
                from core.tardis_video_thinking_engine import get_video_thinking_engine
                vte_x = get_video_thinking_engine()
                vid = vte_x.state.get("last_video_id", "")
                if not vid:
                    mem_x = vte_x.get_memory_summary(limit=1)
                    vid = mem_x[0]["id"] if mem_x else ""
            if not vid:
                self.send_message("⚠️ No hay videos registrados aún en `/VideoPensante`.", chat_id=chat_id, reply_to_message_id=msg_id)
                return True
            self.send_message(f"📡 Subiendo video `{vid}` + reflexiones de TARDIS en línea a **X.com**…", chat_id=chat_id, reply_to_message_id=msg_id)

            def _run_x_pub_async():
                try:
                    rep = se.publish_video_by_id(vid, item="video", platform="x")
                    if "skipped" in rep:
                        self.send_message(f"⚠️ {rep['skipped']}", chat_id=chat_id)
                        return
                    rx = (rep.get("x_results") or rep.get("results") or {}).get("x_video") or {}
                    mark = "✅" if rx.get("status") == "published" else ("↺" if rx.get("status") == "skipped" else "❌")
                    detail_txt = rx.get("tweet_url") or rx.get("publish_id") or rx.get("reason") or rx.get("error") or rx.get("status")
                    self.send_message(f"📡 **[SOCIAL X.COM :: `{vid}`]**\n• {mark} Estado: `{rx.get('status')}`\n• Detalle: {detail_txt}", chat_id=chat_id)
                except Exception as e_xp:
                    self.send_message(f"⚠️ Error publicando en X.com: {e_xp}", chat_id=chat_id)

            threading.Thread(target=_run_x_pub_async, daemon=True, name="SocialXPublishThread").start()
            return True

        if sub.lower() in ("pendientes", "cola", "pending"):
            pend = se.pending_list()
            if not pend:
                self.send_message("✅ La cola social está vacía: todo lo aprendido ya se publicó o rechazó.", chat_id=chat_id, reply_to_message_id=msg_id)
                return True
            lines = ["⏳ **[TARDIS :: COLA SOCIALES PENDIENTES]**\n"];
            for row in pend[:10]:
                lines.append(f"• `{row['video_id']}` · {row['item_type']} · intentos {row.get('attempts', 0)}")
            if len(pend) > 10:
                lines.append(f"\n…y {len(pend) - 10} más en cola.")
            self.send_message("\n".join(lines), chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        if sub.lower() in ("retry", "reintentar", "vaciar"):
            self.send_message("🧹 Reintentando la cola social pendiente contra TikTok…", chat_id=chat_id, reply_to_message_id=msg_id)

            def _run_retry_async():
                try:
                    res = se.retry_pending()
                    pub = res.get("published", [])
                    txt = (
                        f"📡 **[SOCIAL :: REINTENTO COMPLETADO]**\n"
                        f"• Publicados ahora: {len(pub)}\n"
                        f"• Fallidos: {res.get('failed', 0)}\n"
                        + ("\n".join([f"• ✅ `{p['video_id']}` ({p['item']}) → `{p['publish_id']}`" for p in pub]))
                    )
                    self.send_message(txt, chat_id=chat_id)
                except Exception as e_retry:
                    self.send_message(f"⚠️ Aviso en reintento social: {e_retry}", chat_id=chat_id)

            threading.Thread(target=_run_retry_async, daemon=True, name="SocialRetryThread").start()
            return True

        if sub.lower().startswith("backfill") or sub.lower().startswith("socializar_todos"):
            parts = sub.split()
            n_arg = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            self.send_message(f"📦 Socializando videos aún sin publicar (lote de {n_arg or se.cfg.get('max_backlog_per_run', 3)})…", chat_id=chat_id, reply_to_message_id=msg_id)

            def _run_backfill_async():
                try:
                    out = se.backfill(maximum=n_arg)
                    lines = [f"📦 **[SOCIAL :: BACKFILL]** Candidatos: {out.get('candidates')} · Procesados: {out.get('processed')}"]
                    for entry in out.get("reports", []):
                        for it, res_i in (entry.get("report", {}).get("results") or {}).items():
                            mark = "✅" if res_i.get("status") == "published" else ("⏳" if res_i.get("status") in ("pending", "requeued") else "🛡️")
                            lines.append(f"• {mark} `{entry.get('video_id')}` · {it} · {res_i.get('status')}{(' → ' + str(res_i.get('publish_id'))) if res_i.get('publish_id') else ''}")
                    self.send_message("\n".join(lines) if len(lines) > 1 else "📦 Nada pendiente por socializar.", chat_id=chat_id)
                except Exception as e_bf:
                    self.send_message(f"⚠️ Aviso en backfill social: {e_bf}", chat_id=chat_id)

            threading.Thread(target=_run_backfill_async, daemon=True, name="SocialBackfillThread").start()
            return True

        if sub.lower().startswith("publicar "):
            vid = sub.split(maxsplit=1)[1].strip()
            self.send_message(f"📡 Publicando `{vid}` en TikTok (video + conclusiones)…", chat_id=chat_id, reply_to_message_id=msg_id)

            def _run_publish_async():
                try:
                    rep = se.publish_video_by_id(vid, item="all")
                    if "skipped" in rep:
                        self.send_message(f"⚠️ {rep['skipped']}", chat_id=chat_id)
                        return
                    lines = [f"📡 **[SOCIAL :: PUBLICACIÓN `{vid}`]**"]
                    for it, res_i in (rep.get("results") or {}).items():
                        mark = {"published": "✅", "pending": "⏳", "refused": "🛡️", "requeued": "🔁",
                                "failed": "❌", "skipped": "↺"}.get(res_i.get("status"), "•")
                        lines.append(f"• {mark} {it} → {res_i.get('publish_id') or res_i.get('reason') or res_i.get('error') or res_i.get('status')}")
                    self.send_message("\n".join(lines), chat_id=chat_id)
                except Exception as e_pub:
                    self.send_message(f"⚠️ Aviso publicando: {e_pub}", chat_id=chat_id)

            threading.Thread(target=_run_publish_async, daemon=True, name="SocialPublishThread").start()
            return True

        if sub.lower().startswith("tarjeta "):
            vid = sub.split(maxsplit=1)[1].strip()
            try:
                from core.tardis_video_thinking_engine import get_video_thinking_engine
                detail = get_video_thinking_engine().get_video_detail(vid)
                if not detail:
                    self.send_message(f"⚠️ No hay videos con ID `{vid}` en la memoria de abstracción.", chat_id=chat_id, reply_to_message_id=msg_id)
                    return True
                card = se.render_card_for(detail)
                if card and Path(card).exists():
                    self.send_video(video=card, caption=f"🧠 [TARDIS · TARJETA DE CONCLUSIONES]\n{detail.get('topic', '')}", chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_message("❌ El renderizado de la tarjeta falló.", chat_id=chat_id, reply_to_message_id=msg_id)
            except Exception as e_card:
                self.send_message(f"⚠️ Aviso generando tarjeta: {e_card}", chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        if sub.lower() in ("historial", "log", "registro"):
            hist = se.publish_history(limit=10)
            if not hist:
                self.send_message("🗄️ Sin publicaciones registradas aún.", chat_id=chat_id, reply_to_message_id=msg_id)
                return True
            lines = ["🗄️ **[TARDIS :: REGISTRO SOCIAL PERMANENTE]**"]
            for row in hist:
                mark = {"published": "✅", "pending": "⏳", "refused": "🛡️"}.get(row["status"], "•")
                lines.append(f"{mark} `{row['video_id']}` · {row['item_type']} · {row['created_at'][:16].replace('T', ' ')}")
            self.send_message("\n".join(lines), chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        self.send_message(
            "📡 **Uso de /Social**\n"
            "• `/Social status` — estado del motor\n"
            "• `/Social publicar <id>` — publica video + conclusiones\n"
            "• `/Social tarjeta <id>` — genera el MP4 de conclusiones\n"
            "• `/Social backfill [N]` — socializa lo aprendido sin publicar\n"
            "• `/Social pendientes` · `/Social retry` · `/Social historial`",
            chat_id=chat_id, reply_to_message_id=msg_id
        )
        return True

    from core.telegram.commands_ops import handle_ops_command
    return handle_ops_command(
        self,
        cmd=cmd,
        args=args,
        arg_str=arg_str,
        text=text,
        chat_id=chat_id,
        msg_id=msg_id,
        user_id=user_id,
        user_name=user_name,
        member_name=member_name,
        msg=msg,
    )
