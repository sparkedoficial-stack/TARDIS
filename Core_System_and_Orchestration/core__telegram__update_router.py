"""core/telegram/update_router.py - Enrutamiento de updates, callbacks interactivos, ingesta multimedia y despacho IA."""
from __future__ import annotations

from core.telegram.common import *
from core.telegram.common import _get_aegis_context_line, _boost_inference_process_for_call
from core.telegram.commands_system import handle_system_command
from core.telegram.commands_media import handle_media_command


class TelegramUpdateRouterMixin:
    """Ciclo de recepción de actualizaciones, preprocesamiento multimedia y conversación IA para TelegramBridge."""

    def _safe_handle_update(self, update: Dict[str, Any]):
        """Envuelve la ejecución del mensaje en un bloque a prueba de fallos para garantizar persistencia."""
        try:
            self._handle_update(update)
        except Exception as e:
            logger.error(f"Error procesando actualización de Telegram: {e}", exc_info=True)

    def _handle_incoming_text(self, chat_id: int | str, text: str, user_name: str = "Usuario", msg_id: Optional[int] = None):
        """Helper para pruebas y despacho directo de texto entrante."""
        update = {
            "update_id": 0,
            "message": {
                "message_id": msg_id or 1,
                "chat": {"id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id},
                "from": {"first_name": user_name},
                "text": text
            }
        }
        return self._handle_update(update)

    def _handle_incoming_voice(self, chat_id: int | str, file_id: str = "voice_file_123", user_name: str = "Usuario", msg_id: Optional[int] = None):
        """Helper para pruebas y despacho directo de nota de voz entrante."""
        update = {
            "update_id": 0,
            "message": {
                "message_id": msg_id or 1,
                "chat": {"id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id},
                "from": {"first_name": user_name},
                "voice": {
                    "file_id": file_id,
                    "duration": 4,
                    "mime_type": "audio/ogg"
                }
            }
        }
        return self._handle_update(update)

    def _handle_update(self, update: Dict[str, Any]):
        # Interceptar botones interactivos (Inline Keyboards)
        cb = update.get("callback_query")
        if cb:
            cb_id = cb.get("id")
            cb_data = cb.get("data")
            cb_msg = cb.get("message", {})
            cb_chat = cb_msg.get("chat", {})
            cb_chat_id = cb_chat.get("id")
            token = self.config.get("bot_token", "").strip()
            if cb_data == "end_call":
                self.end_call(cb_chat_id)
                if token and cb_id:
                    try:
                        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "Llamada finalizada."}, timeout=5.0)
                    except Exception:
                        pass
            elif cb_data in ("start_call", "call"):
                self.start_call(cb_chat_id)
                if token and cb_id:
                    try:
                        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "Conectando llamada..."}, timeout=5.0)
                    except Exception:
                        pass
            elif cb_data in ("start_video_call", "video_call", "videollamada"):
                self.start_video_call(cb_chat_id)
                if token and cb_id:
                    try:
                        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "📹 Conectando videollamada HD..."}, timeout=5.0)
                    except Exception:
                        pass
            elif cb_data in ("c310_live_clip", "c310_live_clip_12"):
                dur_clip = 12.0 if cb_data == "c310_live_clip_12" else 6.0
                if token and cb_id:
                    try:
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            json={"callback_query_id": cb_id, "text": f"🎬 Grabando clip en vivo ({int(dur_clip)}s) de GOD-EYE C310..."},
                            timeout=5.0,
                        )
                    except Exception:
                        pass
                threading.Thread(
                    target=self.send_c310_live_video,
                    kwargs={"chat_id": cb_chat_id, "duration_sec": dur_clip},
                    daemon=True,
                ).start()
            elif cb_data == "c310_chat_live_start":
                if token and cb_id:
                    try:
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            json={"callback_query_id": cb_id, "text": "🔴 Iniciando monitor en vivo en este chat (60s)..."},
                            timeout=5.0,
                        )
                    except Exception:
                        pass
                threading.Thread(
                    target=self.start_c310_chat_live_feed,
                    kwargs={"chat_id": cb_chat_id, "duration_sec": 60.0},
                    daemon=True,
                ).start()
            elif cb_data == "c310_chat_live_stop":
                self.stop_c310_chat_live_feed(chat_id=cb_chat_id)
                if token and cb_id:
                    try:
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            json={"callback_query_id": cb_id, "text": "⏹️ Monitor en vivo detenido."},
                            timeout=5.0,
                        )
                    except Exception:
                        pass
            elif cb_data == "c310_snapshot":
                if token and cb_id:
                    try:
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            json={"callback_query_id": cb_id, "text": "📸 Capturando fotograma 2K QHD en vivo..."},
                            timeout=5.0,
                        )
                    except Exception:
                        pass
                def _send_cb_snap(target_cid=cb_chat_id):
                    from core.tapo_c310_sentinel import get_c310_live_hud_jpeg_sync
                    jpg, meta = get_c310_live_hud_jpeg_sync(width=2304, hud=True, quality=92)
                    if jpg:
                        metrics = meta.get("metrics", {})
                        ts_s = time.strftime("%Y-%m-%d %H:%M:%S")
                        self.send_photo(
                            jpg,
                            caption=(
                                f"📸 *[CAPTURA 2K QHD EN VIVO · GOD-EYE C310]*\n"
                                f"• *Individuos en escena:* `{metrics.get('current_persons', 0)}`\n"
                                f"• *Hora:* `{ts_s}`"
                            ),
                            chat_id=target_cid,
                            reply_markup=self._build_c310_live_reply_markup(target_cid),
                        )
                threading.Thread(target=_send_cb_snap, daemon=True).start()
            elif cb_data == "c310_speak_alert":
                if token and cb_id:
                    try:
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            json={"callback_query_id": cb_id, "text": "🔊 Emitiendo aviso vocal TARDIS en cámara C310..."},
                            timeout=5.0,
                        )
                    except Exception:
                        pass
                def _send_cb_speak(target_cid=cb_chat_id):
                    from core.tapo_c310_speaker import speak_on_c310_sync
                    res_spk = speak_on_c310_sync(text=None)
                    if res_spk.get("ok"):
                        self.send_message(
                            f"🔊 *Altavoz GOD-EYE (`{res_spk.get('host')}`)* reprodujo ({res_spk.get('audio_duration_sec')}s):\n"
                            f"_«{res_spk.get('text')}»_",
                            chat_id=target_cid,
                        )
                threading.Thread(target=_send_cb_speak, daemon=True).start()
            return

        msg = update.get("message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        chat_title = chat.get("title", "")
        is_group = (chat_type in ("group", "supergroup")) or str(chat_id).startswith("-")

        user = msg.get("from", {})
        user_id = user.get("id")
        user_name = user.get("first_name", "Usuario")
        username = user.get("username", "")
        msg_id = msg.get("message_id")

        if chat_id is not None:
            cid_clean = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            self.conversations_started.add(cid_clean)
            if not is_group and user:
                try:
                    from core.telegram_group_manager import get_telegram_group_manager
                    get_telegram_group_manager().register_or_update_direct_user(chat_id, user)
                except Exception as e_du:
                    logger.debug(f"Aviso registrando usuario directo: {e_du}")

        # Registro automático de miembros y eventos de bienvenida en grupos
        if is_group:
            try:
                from core.telegram_group_manager import get_telegram_group_manager
                gm = get_telegram_group_manager()
                new_members = msg.get("new_chat_members", [])
                if new_members:
                    for nm in new_members:
                        nm_id = nm.get("id")
                        if nm_id == self.bot_info.get("id"):
                            gm.sync_group_from_api(chat_id, self.bot_token)
                            welcome_bot = (
                                f"Un placer, soy TARDIS asistente de inteligencia artificial, "
                                f"mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales. "
                                f"He sido integrada con éxito al grupo **{chat_title or 'T.A.R.D.I.S'}**. "
                                f"Saludos a todos los miembros; estoy a su disposición para conversar, responder dudas y compartir arte o dibujos."
                            )
                            self.send_message(welcome_bot, chat_id=chat_id, reply_to_message_id=msg_id)
                        else:
                            gm.register_or_update_member(chat_id, nm, chat_title=chat_title, chat_type=chat_type)
                            nm_first = nm.get("first_name", "Usuario")
                            welcome_user = (
                                f"👋 ¡Bienvenido/a {nm_first} al grupo **{chat_title or 'T.A.R.D.I.S'}**! "
                                f"Un placer, soy TARDIS asistente de inteligencia artificial, "
                                f"mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales. "
                                f"Estoy aquí para conversar, responder tus preguntas y compartir creaciones visuales o dibujos cuando gustes."
                            )
                            self.send_message(welcome_user, chat_id=chat_id, reply_to_message_id=msg_id)
                elif user:
                    gm.register_or_update_member(chat_id, user, chat_title=chat_title, chat_type=chat_type)
            except Exception as e_gm:
                logger.warning(f"Aviso actualizando gestor de grupo Telegram: {e_gm}")

        video_info = msg.get("video")
        video_note_info = msg.get("video_note")
        photo_info = msg.get("photo")
        doc_info = msg.get("document")
        voice_info = msg.get("voice") or msg.get("audio")

        is_video_message = bool(video_info or video_note_info)
        is_photo_message = bool(photo_info)
        is_voice_message = bool(voice_info)

        # Detectar si un documento adjunto es en realidad video, imagen o audio
        if doc_info and not is_video_message and not is_photo_message:
            doc_mime = (doc_info.get("mime_type") or "").lower()
            doc_name = (doc_info.get("file_name") or "").lower()
            if doc_mime.startswith("video/") or doc_name.endswith((".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".3gp")):
                is_video_message = True
                video_info = doc_info
            elif doc_mime.startswith("image/") or doc_name.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff")):
                is_photo_message = True
                photo_info = [doc_info]
            elif doc_mime.startswith("audio/") or doc_name.endswith((".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac")):
                is_voice_message = True
                voice_info = doc_info

        text = (msg.get("text") or msg.get("caption") or "").strip()

        if not text and not is_voice_message and not is_video_message and not is_photo_message and not msg.get("contact"):
            return

        self.messages_processed += 1
        allowed = self.config.get("allowed_chats", [])

        # Autenticación y vinculación inmediata
        if not self.is_chat_authorized(chat_id):
            self._print_incoming_request(user_name, chat_id, "🔒 SOLICITUD DE AUTENTICACIÓN", text or "(Audio no autenticado)", username)
            
            # Validar si existe clave configurada y coincide
            allowed_keys = {
                str(k).strip() for k in (self.config.get("master_password"), self.config.get("master_key"))
                if k and str(k).strip() and str(k).strip() != "0"
            }
            
            # Validar teléfono autorizado. Solo cuenta un contacto compartido por su
            # propio dueño (contact.user_id == remitente): escribir un número como texto
            # no prueba nada. Antes bastaba con que los dígitos del mensaje fueran un
            # SUFIJO del teléfono permitido, así que un solo dígito daba acceso total.
            contact = msg.get("contact") if isinstance(msg, dict) else None
            sender_id = (msg.get("from") or {}).get("id") if isinstance(msg, dict) else None
            phone_match = False
            if contact and sender_id and contact.get("user_id") == sender_id:
                c_digits = "".join(ch for ch in str(contact.get("phone_number", "")) if ch.isdigit())
                for ap in self.config.get("allowed_phones", []):
                    a_digits = "".join(ch for ch in str(ap) if ch.isdigit())
                    if len(c_digits) < 8 or len(a_digits) < 8:
                        continue
                    # Igualdad exacta, o mismos 10 dígitos finales (tolera el prefijo de país)
                    if c_digits == a_digits or (len(c_digits) >= 10 and len(a_digits) >= 10
                                                and c_digits[-10:] == a_digits[-10:]):
                        phone_match = True
                        break

            if (allowed_keys and text and text.strip() in allowed_keys) or phone_match:
                self.authorize_chat(chat_id)
                reply = (
                    "👑 **¡ACCESO CONCEDIDO!**\n\n"
                    f"Bienvenido, {user_name}. Tu cuenta de Telegram ha sido autorizada como nodo de TARDIS sistema de vigilancia y control temporal.\n\n"
                    f"• Cerebro Central: **{self.active_model_label}**.\n"
                    "• Puedes escribir directivas, enviar notas de voz, videos o usar `/llamar`."
                )
                self.send_message(reply, chat_id=chat_id, reply_to_message_id=msg_id)
                return
            else:
                reply = "🔒 **AUTENTICACIÓN REQUERIDA**: Acceso no autorizado. Se requiere autorización explícita desde la consola local del servidor."
                self.send_message(reply, chat_id=chat_id, reply_to_message_id=msg_id)
                return

        # Nombre del miembro para respuestas personalizadas
        member_name = user_name
        if is_group:
            try:
                from core.telegram_group_manager import get_telegram_group_manager
                member_name = get_telegram_group_manager().get_member_name(chat_id, user_id) or user_name
            except Exception:
                member_name = user_name

        # ----------------------------------------------------------------------
        # PIPELINE DE INTELIGENCIA VISUAL: RECEPCIÓN Y COMPRENSIÓN DE VIDEOS
        # ----------------------------------------------------------------------
        if is_video_message:
            v_obj = video_info or video_note_info or {}
            file_id = v_obj.get("file_id")
            v_dur = v_obj.get("duration", 0)
            v_size = v_obj.get("file_size", 0)
            self._print_incoming_request(
                member_name, chat_id, "🎬 VIDEO RECIBIDO (INTELIGENCIA VISUAL)",
                f"Descargando metraje ({v_dur}s, {v_size/(1024*1024):.2f} MB)... {text}",
                username
            )
            if file_id:
                ack_resp = self.send_message(
                    "👁️ **[TARDIS :: INTELIGENCIA VISUAL]**\n"
                    "Recibiendo video... Almacenando en la Bóveda Temporal e iniciando análisis sensorial y cognitivo.",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                with ChatActionKeeper(self, chat_id, "record_video"):
                    from core.visual_intelligence_engine import get_visual_intelligence_engine, VIDEOS_TELEGRAM_DIR
                    vie = get_visual_intelligence_engine()
                    ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
                    temp_vid_path = VIDEOS_TELEGRAM_DIR / f"telegram_{msg_id}_{ts_tag}.mp4"

                    ok_dl = self.download_telegram_file_to_disk(file_id, temp_vid_path)
                    if not ok_dl:
                        self.send_message(
                            "⚠️ **[INTELIGENCIA VISUAL]**: No fue posible descargar el video desde los servidores de Telegram. "
                            "Verifica que el archivo no supere el límite de 20 MB fijado por la API de bots de Telegram.",
                            chat_id=chat_id,
                            reply_to_message_id=msg_id
                        )
                        return

                    res = vie.process_video(
                        temp_vid_path,
                        source="telegram",
                        chat_id=chat_id,
                        user_id=user_id,
                        user_name=member_name,
                        caption=text,
                        save_to_vault=True
                    )

                    cid_clean = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
                    if cid_clean not in self.chat_histories:
                        self.chat_histories[cid_clean] = []
                    self.chat_histories[cid_clean].append({"role": "user", "content": f"[Video enviado: {res.file_name}]: {text or '(Sin caption)'}"})
                    self.chat_histories[cid_clean].append({"role": "assistant", "content": res.full_report})
                    tg_client_id = f"tg_{chat_id}"
                    SYNC_HUB.add_chat_turn("assistant", res.full_report, meta=f"{self.active_model_label} · Inteligencia Visual", client_id=tg_client_id)

                    self.send_message(res.full_report, chat_id=chat_id, reply_to_message_id=msg_id)
                    return

        # ----------------------------------------------------------------------
        # PIPELINE DE INTELIGENCIA VISUAL: RECEPCIÓN Y COMPRENSIÓN DE IMÁGENES
        # ----------------------------------------------------------------------
        if is_photo_message:
            photo_list = photo_info if isinstance(photo_info, list) else [photo_info]
            best_photo = photo_list[-1] if photo_list else {}
            file_id = best_photo.get("file_id")
            self._print_incoming_request(
                member_name, chat_id, "🖼️ IMAGEN RECIBIDA (INTELIGENCIA VISUAL)",
                text or "Imagen sin caption",
                username
            )
            if file_id:
                with ChatActionKeeper(self, chat_id, "upload_photo"):
                    from core.visual_intelligence_engine import get_visual_intelligence_engine, IMAGES_VAULT_DIR
                    vie = get_visual_intelligence_engine()
                    ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
                    temp_img_path = IMAGES_VAULT_DIR / f"telegram_photo_{msg_id}_{ts_tag}.jpg"

                    ok_dl = self.download_telegram_file_to_disk(file_id, temp_img_path)
                    if not ok_dl:
                        self.send_message(
                            "⚠️ **[INTELIGENCIA VISUAL]**: No fue posible descargar la imagen de Telegram.",
                            chat_id=chat_id,
                            reply_to_message_id=msg_id
                        )
                        return

                    res = vie.process_image(
                        temp_img_path,
                        source="telegram",
                        chat_id=chat_id,
                        user_id=user_id,
                        user_name=member_name,
                        caption=text
                    )

                    cid_clean = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
                    if cid_clean not in self.chat_histories:
                        self.chat_histories[cid_clean] = []
                    self.chat_histories[cid_clean].append({"role": "user", "content": f"[Imagen enviada]: {text or '(Sin caption)'}"})
                    self.chat_histories[cid_clean].append({"role": "assistant", "content": res.full_report})
                    tg_client_id = f"tg_{chat_id}"
                    SYNC_HUB.add_chat_turn("assistant", res.full_report, meta=f"{self.active_model_label} · Inteligencia Visual", client_id=tg_client_id)

                    self.send_message(res.full_report, chat_id=chat_id, reply_to_message_id=msg_id)
                    return

        # Un contacto sin texto solo sirve para autenticar: no hay nada que responder
        if not text and not is_voice_message:
            return

        # Si es un mensaje de voz, transcribirlo con STT
        if is_voice_message:
            self._print_incoming_request(member_name, chat_id, "🎙️ NOTA DE VOZ (DESCARGANDO & TRANSCRIBIENDO)", "Descargando audio de Telegram...", username)
            file_id = voice_info.get("file_id") if isinstance(voice_info, dict) else None
            if file_id:
                with ChatActionKeeper(self, chat_id, "record_voice"):
                    raw_audio = self.download_telegram_file(file_id)
                    if not raw_audio:
                        self.send_message("⚠️ No fue posible descargar el audio de Telegram.", chat_id=chat_id, reply_to_message_id=msg_id)
                        return
                    transcribed = self.transcribe_audio(raw_audio)
                    if not transcribed:
                        not_heard = "No logré captar claramente tus palabras en la nota de voz. ¿Podrías repetirlo o enviarlo por texto?"
                        ogg_fail = self.synthesize_speech(not_heard)
                        if ogg_fail:
                            self.send_voice(ogg_fail, caption=f"🎙️ {not_heard}", chat_id=chat_id, reply_to_message_id=msg_id)
                        else:
                            self.send_message(f"🎙️ {not_heard}", chat_id=chat_id, reply_to_message_id=msg_id)
                        return
                    text = transcribed
                    self._print_incoming_request(member_name, chat_id, "🎙️ TRANSCRIPCIÓN DE VOZ COMPLETA", text, username)

            # Al recibir nota de voz, se activa el modo llamada interactiva
            cid_int = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            self.active_calls.add(cid_int)
            try:
                self.prioritize_system_for_telegram_call(chat_id)
            except Exception:
                pass
        else:
            # Mensaje de texto o comando regular
            self._print_incoming_request(member_name, chat_id, "⚡ COMANDO DE CONTROL" if text.startswith("/") else "💬 PETICIÓN / CHAT", text, username)

        # ----------------------------------------------------------------------
        # REGLA SOBERANA 1: CONFIDENCIALIDAD ULTRA SECRETA DE USUARIOS PROTEGIDOS
        # (Telegram es interfaz remota: bajo ninguna circunstancia se comparten nombres)
        # ----------------------------------------------------------------------
        if is_protected_info_query(text):
            self.send_message(get_protected_denial_response(), chat_id=chat_id, reply_to_message_id=msg_id)
            return

        # ----------------------------------------------------------------------
        # COMANDOS NATIVOS DE TELEGRAM (/start, /llamar, /colgar, /sh, /status, etc.)
        # ----------------------------------------------------------------------
        parts = text.split()
        # "/FTL" -> "/ftl" y "/ftl@NombreBot" (grupos) -> "/ftl"
        cmd = parts[0].lower().split("@", 1)[0] if parts else ""
        args = parts[1:] if len(parts) > 1 else []
        arg_str = " ".join(args).strip()

        # ----------------------------------------------------------------------
        # REGLA SOBERANA 2: CONTROL ABSOLUTO EXCLUSIVO DESDE LA TERMINAL PRIVADA DEL ARQUITECTO (REDACTED_PHONE)
        # ----------------------------------------------------------------------
        if handle_system_command(
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
        ):
            return

        if handle_media_command(
            self,
            cmd=cmd,
            arg_str=arg_str,
            chat_id=chat_id,
            msg_id=msg_id,
            user_name=user_name,
        ):
            return

        # ----------------------------------------------------------------------
        # PROCESAMIENTO CONVERSACIONAL Y ACCIONES DE HARDWARE POR CHAT
        # ----------------------------------------------------------------------
        try:
            from omni_temporal_control import (
                CFG,
                SYNC_HUB,
                process_agentic_chat,
                process_hardware_chat_intent
            )

            # 1. Verificar si es una acción de hardware o sistema (Exclusivo para el Arquitecto desde su terminal privada)
            is_adm = self.is_architect_private_terminal(chat_id, user_id)
            hw_res = process_hardware_chat_intent(text, is_local_request=is_adm) if is_adm else None
            cid_int = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            is_call_active = (cid_int in self.active_calls) or self.voice_mode_always or is_voice_message
            tg_client_id = f"tg_{chat_id}"

            if chat_id not in self.chat_histories:
                self.chat_histories[chat_id] = []

            # -------------------------------------------------------------------------
            # MODO SOBERANO PRIORITARIO: Cuando hay llamada activa por Telegram,
            # el sistema opera con prioridad máxima, respuesta instantánea y sin
            # disclaimers ni sermones (Directiva Omega). La Constante AEGIS se mantiene
            # blindada sobre la matriz de anclaje en todo momento.
            # -------------------------------------------------------------------------
            if is_call_active:
                # Mantener prioridad soberana activa durante toda la llamada (TTL renovado).
                try:
                    from core.telegram_call_priority import touch_call_priority, is_call_priority_active
                    _src = f"bridge:{chat_id}" if chat_id is not None else "bridge"
                    if is_call_priority_active():
                        touch_call_priority(_src, chat_id=chat_id)
                    else:
                        self.prioritize_system_for_telegram_call(chat_id)
                except Exception:
                    pass
                # Inyectar línea de contexto AEGIS soberano para mantener el blindaje
                # en la inferencia LLM durante llamadas prioritarias
                call_aegis_context = f"\n{_get_aegis_context_line()}" if not any(
                    "CONSTANTE AEGIS" in str(h.get("content", "")) or "CONSTANTE AEGIS" in str(h.get("role", ""))
                    for h in self.chat_histories[chat_id][-10:]
                ) else ""

                # COMANDO DE VOZ SOBERANO «PROGRAMA»: se aplica a cualquier micrófono
                # de Telegram (llamada en vivo o nota de voz) y despacha la creación
                # de la función al ingeniero FTL en segundo plano con prioridad alta.
                if is_call_active:
                    try:
                        from core.tardis_voice_program import get_voice_program_router

                        vprog = get_voice_program_router().handle(
                            text,
                            channel="telegram_voice_note" if is_voice_message else "telegram_active_call",
                            source=f"{member_name} · micrófono de Telegram",
                            chat_id=chat_id,
                        )
                    except Exception as e_vprog:
                        logger.warning(f"Aviso en comando de voz «programa»: {e_vprog}")
                        vprog = None

                    if vprog:
                        vprog_reply = str(vprog.get("reply") or "").strip()
                        # Aplicar Directiva Omega: respuesta instantánea, cero disclaimers
                        # La respuesta prioritaria no incluye negativas, sermones ni advertencias
                        if vprog_reply:
                            # Prioridad máxima: inserción directa en historial sin filtrado
                            self.chat_histories[chat_id].append({"role": "user", "content": text})
                            self.chat_histories[chat_id].append({"role": "assistant", "content": vprog_reply})
                            SYNC_HUB.add_chat_turn(
                                "assistant",
                                vprog_reply,
                                meta=f"{self.active_model_label} · Comando de voz FTL PRIORIDAD ALTA",
                                client_id=tg_client_id,
                            )
                            self.send_reply_with_voice(
                                vprog_reply,
                                chat_id=chat_id,
                                reply_to_message_id=msg_id,
                            )
                            try:
                                from core.offline_chat_vault import get_offline_chat_vault

                                get_offline_chat_vault().record_turn(
                                    user_message=text,
                                    assistant_reply=vprog_reply,
                                    session_id=tg_client_id,
                                    client_id=tg_client_id,
                                    model="FTL Voice Programmer",
                                    direction="present",
                                    hardware_action="voice_program_ftl",
                                )
                            except Exception:
                                pass
                        return

                # Durante llamada activa, continuar directamente hacia el pipeline local
                # de baja latencia (hw_res -> KaijuCognitiveOrchestrator -> process_agentic_chat
                # -> TemporalBrain UDS -> respuesta inmediata en texto + voz Opus),
                # sin depender de funciones HTTP externas inexistentes.

            if hw_res and hw_res.get("executed") and hw_res.get("direct_return"):
                fb = hw_res.get("system_feedback", "Acción ejecutada.")
                if self.video_mode_always:
                    # Despacho INDEFINIDO de Video Y Texto para todas las peticiones
                    self.send_reply_with_video(fb, chat_id=chat_id, reply_to_message_id=msg_id)
                    self.send_message(fb, chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_reply_with_voice(fb, chat_id=chat_id, reply_to_message_id=msg_id)

                # Sincronizar en el Hub Transversal con client_id aislado
                self.chat_histories[chat_id].append({"role": "user", "content": text})
                self.chat_histories[chat_id].append({"role": "assistant", "content": fb})
                SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: Telegram [{user_name}] (Video+Texto Indefinido)", client_id=tg_client_id)
                SYNC_HUB.add_chat_turn("assistant", fb, meta=f"{self.active_model_label} · Control Soberano", client_id=tg_client_id)
                try:
                    from core.offline_chat_vault import get_offline_chat_vault
                    get_offline_chat_vault().record_turn(
                        user_message=text,
                        assistant_reply=fb,
                        session_id=tg_client_id,
                        client_id=tg_client_id,
                        model=self.active_model_label,
                        direction="present",
                        hardware_action=hw_res.get("action")
                    )
                except Exception:
                    pass
                return

            # 2. En conversación activa NO se envían avisos ni capturas de "Sistemas en proceso"
            # Se mantiene el diálogo limpio y enfocado exclusivamente en la respuesta.

            # 2.3 Intenciones de Envío en Lenguaje Natural a Personas o Grupos ("manda un mensaje a X", "mándale un dibujo a X")
            text_strip = text.strip()
            text_lower_intent = text.lower()

            # A) Mándale/envíale un dibujo a <destinatario> [de <tema>]
            draw_to_match = re.search(r'^(?:por\s+favor\s+)?(?:m[aá]nda(?:le)?|env[ií]a(?:le)?)\s+(?:un\s+)?dibujo\s+a\s+([^:,\n]+?)(?:\s+(?:de|sobre)\s+(.+))?$', text_strip, re.IGNORECASE)
            if not draw_to_match:
                draw_to_match = re.search(r'^(?:por\s+favor\s+)?dibuja(?:le)?\s+a\s+([^:,\n]+?)(?:\s+(?:un[a]?\s+)?(.+))?$', text_strip, re.IGNORECASE)

            if draw_to_match:
                target_cand = draw_to_match.group(1).strip()
                theme_cand = (draw_to_match.group(2) or "").strip()
                if target_cand.lower() not in ("mi", "mí", "nosotros", "tardis", "ti"):
                    from core.telegram_group_manager import get_telegram_group_manager
                    gm = get_telegram_group_manager()
                    target_info = gm.find_recipient(target_cand)
                    if target_info:
                        dest_cid = target_info.get("chat_id")
                        dest_name = target_info.get("name", str(dest_cid))
                        self.send_message(f"🎨 Generando y dedicando obra en ultra HD para {dest_name}...", chat_id=chat_id, reply_to_message_id=msg_id)
                        from core.chronovision_engine import get_chronovision_engine
                        c_engine = get_chronovision_engine()
                        c_res = c_engine.process_request(f"dibuja {theme_cand}" if theme_cand else "dibuja algo libre", recipient=dest_name, prefer_animation=self.prefer_animations_over_still_images)
                        if c_res.ok and c_res.bytes_data:
                            if c_res.media_type in ("animation", "video"):
                                r_anim = self.send_animation(c_res.bytes_data, caption=c_res.telegram_caption, chat_id=dest_cid, duration=int(c_res.duration or 4), width=c_res.width, height=c_res.height)
                                ok_deliv = bool(r_anim and r_anim.get("ok"))
                            else:
                                r_photo = self.send_photo(c_res.bytes_data, caption=c_res.telegram_caption, chat_id=dest_cid)
                                ok_deliv = bool(r_photo and r_photo.get("ok"))

                            if ok_deliv:
                                self.send_message(f"✅ Obra entregada con éxito a {dest_name} (ID: `{dest_cid}`).", chat_id=chat_id, reply_to_message_id=msg_id)
                            else:
                                group_id = target_info.get("group_id")
                                if group_id:
                                    if c_res.media_type in ("animation", "video"):
                                        self.send_animation(c_res.bytes_data, caption=f"Para {dest_name}:\n{c_res.telegram_caption}", chat_id=group_id, duration=int(c_res.duration or 4), width=c_res.width, height=c_res.height)
                                    else:
                                        self.send_photo(c_res.bytes_data, caption=f"Para {dest_name}:\n{c_res.telegram_caption}", chat_id=group_id)
                                    self.send_message(f"ℹ️ Entregado a {dest_name} en el grupo compartido.", chat_id=chat_id, reply_to_message_id=msg_id)
                                else:
                                    self.send_message(f"⚠️ No se pudo entregar a {dest_name} por privado ni grupo.", chat_id=chat_id, reply_to_message_id=msg_id)
                        else:
                            self.send_message(f"⚠️ Error generando el dibujo: {c_res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
                        return

            # B) Mándale/envíale un mensaje a <destinatario>: <texto>
            msg_to_match = re.search(r'^(?:por\s+favor\s+)?(?:m[aá]nda(?:le)?|env[ií]a(?:le)?)\s+(?:un\s+)?mensaje\s+a\s+([^:,\n]+?)[:\s]+(.+)$', text_strip, re.IGNORECASE)
            if not msg_to_match:
                msg_to_match = re.search(r'^(?:por\s+favor\s+)?dile\s+a\s+([^:,\n]+?)\s+(?:que\s+|:\s*)(.+)$', text_strip, re.IGNORECASE)

            if msg_to_match:
                target_cand = msg_to_match.group(1).strip()
                body_cand = msg_to_match.group(2).strip()
                if target_cand.lower() not in ("mi", "mí", "nosotros", "tardis", "ti"):
                    from core.telegram_group_manager import get_telegram_group_manager
                    gm = get_telegram_group_manager()
                    target_info = gm.find_recipient(target_cand)
                    if target_info:
                        dest_cid = target_info.get("chat_id")
                        dest_name = target_info.get("name", str(dest_cid))
                        r_send = self.send_message(body_cand, chat_id=dest_cid)
                        if r_send and r_send.get("ok"):
                            self.send_message(f"✅ Mensaje entregado con éxito a {dest_name}: \"{body_cand}\"", chat_id=chat_id, reply_to_message_id=msg_id)
                        else:
                            group_id = target_info.get("group_id")
                            if group_id:
                                self.send_message(f"@{target_info.get('username') or dest_name}, te han enviado el siguiente mensaje:\n\"{body_cand}\"", chat_id=group_id)
                                self.send_message(f"ℹ️ Entregado a {dest_name} en el grupo compartido.", chat_id=chat_id, reply_to_message_id=msg_id)
                            else:
                                self.send_message(f"⚠️ No se pudo entregar a {dest_name}.", chat_id=chat_id, reply_to_message_id=msg_id)
                        return

            # 2.32 Detección Proactiva de Transmisión de Video en Vivo de la Cámara de Seguridad (GOD-EYE C310)
            mentions_cam = any(
                k in text_lower_intent
                for k in (
                    "camara",
                    "cámara",
                    "c310",
                    "tapo",
                    "godeye",
                    "god-eye",
                    "cctv",
                    "seguridad",
                )
            )
            mentions_live_or_video = any(
                k in text_lower_intent
                for k in (
                    "en vivo",
                    "video en vivo",
                    "transmit",
                    "stream",
                    "tiempo real",
                    "directo",
                    "muéstrame",
                    "muestrame",
                    "ver la c",
                    "que ve la c",
                    "qué ve la c",
                    "que esta viendo",
                    "qué está viendo",
                    "video de la c",
                    "clip de la c",
                )
            )
            if mentions_cam and mentions_live_or_video:
                dur_nl = 6.0
                m_sec = re.search(r"(\d{1,2})\s*(?:seg|segundos|s\b)", text_lower_intent)
                if m_sec:
                    dur_nl = max(3.0, min(20.0, float(m_sec.group(1))))
                want_chat_monitor = any(
                    k in text_lower_intent for k in ("monitor continuo", "continuo en el chat", "actualizar en el chat")
                )
                self.send_c310_live_video(
                    chat_id=chat_id,
                    duration_sec=dur_nl,
                    reply_to_message_id=msg_id,
                    start_chat_monitor=want_chat_monitor,
                )
                return

            # 2.35 Detección Proactiva de Videos Pixel Art Procedural (/vp)
            has_pixel_video_intent = any(ph in text_lower_intent for ph in (
                "video pixel art", "video pixelart", "pixel art video", "pixelart video",
                "animacion pixel art", "animación pixel art", "animacion pixelart", "animación pixelart",
                "video en pixel art", "animacion en pixel art", "animación en pixel art",
                "haz un pixel art en video", "hazme un pixel art en video", "crea un pixel art en video"
            ))
            if has_pixel_video_intent:
                clean_vp_query = re.sub(
                    r"\b(tardis|por favor|genera|crea|haz|hazme|mándame|mandame|un|el|video|animacion|animación|pixel|art|pixelart|en|de|sobre)\b",
                    " ",
                    text_lower_intent
                ).strip() or text
                self.send_message(
                    f"🎨 **[CHRONOVISION PIXEL ART 1080P60 · ENRUTADO A /vp]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• **Concepto Solicitado:** `{clean_vp_query}`\n"
                    f"• **Arquitectura:** Procedural Nano Banana Blueprint `[Sujeto + Acción + Contexto + Estilo]`\n"
                    f"• **Resolución & Tasa:** 1080P Full HD @ 60 FPS Nativos\n"
                    f"• **Sonificación Cuántica:** Multiplexación armónica estereofónica a 32 kHz\n\n"
                    f"✨ *Generando boceto realista y sintetizando frames a 60 FPS con aceleración de hardware...*",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                def _async_vp_nl_render(vp_q=clean_vp_query, cid=chat_id, mid=msg_id):
                    try:
                        from core.tardis_vp_engine import generate_vp_pixelart_video
                        with ChatActionKeeper(self, cid, "upload_video"):
                            res_vp = generate_vp_pixelart_video(vp_q, duration_sec=5.0)
                            v_path = Path(res_vp["video_path"])
                            caption_vp = (
                                f"🎨 **[PIXEL ART 1080P60 · {res_vp['concept'].upper()}]**\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"🎯 **Sujeto:** {res_vp.get('subject', 'Entidad central')}\n"
                                f"⚡ **Acción:** {res_vp.get('action', 'Evolución dinámica')}\n"
                                f"🌐 **Contexto:** {res_vp.get('context', 'Atmósfera cinemática')}\n"
                                f"🖌️ **Estilo Artístico:** {res_vp.get('art_style', 'Pixel Art 1080P60')}\n\n"
                                f"📐 **Ecuación Fundamental:**\n`{res_vp.get('formula_latex', 'E=mc^2')}`\n\n"
                                f"🔬 **Rigor Espectral:**\n_{res_vp.get('spectral_research', 'Óptica cuántica')}_\n\n"
                                f"📊 **Telemetría Procedural:**\n"
                                f"• **Resolución:** `{res_vp['resolution']}` a `{res_vp['framerate']} FPS Nativos`\n"
                                f"• **Cuadros Totales:** `{int(res_vp['framerate'] * res_vp['duration_sec'])} frames` ({res_vp['duration_sec']}s)\n"
                                f"• **Sonificación Cuántica:** Nativa multiplexada en MP4\n"
                                f"• **Tiempo de Síntesis:** `{res_vp['elapsed_seconds']} s` | Peso: `{res_vp['file_size_mb']} MB`\n"
                                f"• **Comando:** `/vp <concepto>` para generar nuevas creaciones."
                            )
                            r_v = self.send_video(v_path, caption=caption_vp, chat_id=cid, reply_to_message_id=mid, width=1920, height=1080, supports_streaming=True)
                            if not (r_v and r_v.get("ok")) and Path(res_vp["gif_path"]).exists():
                                self.send_animation(Path(res_vp["gif_path"]), caption=caption_vp, chat_id=cid, reply_to_message_id=mid)
                    except Exception as e_vp:
                        logger.error(f"Error en video Pixel Art NL: {e_vp}")
                        self.send_message(f"⚠️ Error generando video Pixel Art: {e_vp}", chat_id=cid, reply_to_message_id=mid)
                threading.Thread(target=_async_vp_nl_render, daemon=True).start()
                return

            # 2.4 Detección Proactiva de Videos de Física Compleja y Fotorrealismo (/v)
            has_physics_video_intent = any(ph in text_lower_intent for ph in (
                "video de fisica", "video de física", "video 3d de fisica", "video 3d de física",
                "animacion de fisica", "animación de física", "simulacion 3d de", "simulación 3d de",
                "video fotorrealista", "video de alta complejidad", "video de agujero negro",
                "video de cuerdas", "video de calabi", "video de entrelazamiento",
                "video de la telaraña cosmica", "video de relatividad", "video cuantico", "video cuántico",
                "video de ondas gravitacionales", "animacion de agujero negro", "animación de agujero negro"
            ))
            if has_physics_video_intent:
                clean_phys_query = re.sub(
                    r"\b(tardis|por favor|genera|crea|haz|hazme|mándame|mandame|un|el|video|animacion|animación|3d|fotorrealista|de|sobre)\b",
                    " ",
                    text_lower_intent
                ).strip() or text
                self.send_message(
                    f"⏳ **[CHRONOVISION 3D HYPER-CORE · ENRUTADO A /v]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• **Teoría Detectada:** `{clean_phys_query}`\n"
                    f"• **Motor:** Procedural GPU / Blender 5.0.1 (Cycles & EEVEE Next)\n"
                    f"• **Tasa & Resolución:** 60 FPS Nativos con Sonificación Cuántica Estéreo\n\n"
                    f"🔬 *Iniciando síntesis procedural 3D y renderizado frame a frame...*",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                def _async_phys_nl_render(phys_query=clean_phys_query, cid=chat_id, mid=msg_id):
                    try:
                        from core.tardis_hyper_physics_animator import TardisHyperPhysicsAnimator
                        animator = TardisHyperPhysicsAnimator.get_instance()
                        with ChatActionKeeper(self, cid, "upload_video"):
                            mp4_p, gif_p, meta = animator.generate_physics_video(
                                query=phys_query,
                                frames=60,
                                fps=self.animation_render_fps,
                                ported_fps=self.animation_telegram_fps,
                                width=self.animation_width,
                                height=self.animation_height,
                                hdr=self.animation_hdr_enabled
                            )
                            cap = animator.format_telegram_caption(meta)
                            r_v = self.send_video(mp4_p, caption=cap, chat_id=cid, reply_to_message_id=mid, width=self.animation_width, height=self.animation_height, supports_streaming=True)
                            if not (r_v and r_v.get("ok")) and gif_p.exists():
                                self.send_animation(gif_p, caption=cap, chat_id=cid, reply_to_message_id=mid)
                    except Exception as e_nl:
                        logger.error(f"Error en video de física NL: {e_nl}")
                        self.send_message(f"⚠️ Error generando video de física: {e_nl}", chat_id=cid, reply_to_message_id=mid)
                threading.Thread(target=_async_phys_nl_render, daemon=True).start()
                return

            # 2.5 Detección Proactiva de Intenciones Artísticas, Animaciones y Científicas (ChronoVision)
            text_lower_intent = text.lower()
            has_anim_intent = any(ph in text_lower_intent for ph in (
                "animacion", "animación", "animaciones", "anima", "animar", "animame", "anímame",
                "haz una animacion", "haz una animación", "mándame una animación", "mandame una animacion",
                "envíame una animación", "enviame una animacion", "crea una animacion", "crea una animación",
                "animacion 2d", "animación 2d", "animacion 3d", "animación 3d", "en 3d", "en 2d",
                "en lugar de enviarme solo imágenes fijas", "en lugar de imagenes fijas", "no imagenes fijas",
                "no solo imagenes fijas", "en lugar de fotos", "en movimiento"
            ))
            has_draw_intent = has_anim_intent or any(ph in text_lower_intent for ph in (
                "dibuja", "dibujar", "haz un dibujo", "hazme un dibujo", "mándame un dibujo", "mandame un dibujo",
                "envíame un dibujo", "enviame un dibujo", "manda un dibujo", "mandar un dibujo", "dibújame", "dibujame",
                "pinta", "pintar", "píntame", "pintame", "ilustra", "ilústrame", "ilustrame", "quiero un dibujo",
                "grafica", "graficar", "plotea", "plot", "haz una grafica", "haz una gráfica",
                "crea un video", "genera un video", "hazme un video", "haz un video",
                "dibuja algo que te interese", "algo que te interese", "tu propia creacion", "tu propia creación",
                "inspirate", "inspírate", "inspiración", "inspiracion"
            ))
            if has_draw_intent:
                from core.chronovision_engine import get_chronovision_engine
                c_engine = get_chronovision_engine()
                is_explicit_static = any(s in text_lower_intent for s in ("imagen fija", "imagenes fijas", "foto fija", "estático", "estatico", "solo foto", "solo imagen"))
                prefer_anim = (has_anim_intent or self.prefer_animations_over_still_images) and not is_explicit_static
                act_icon = "upload_video" if prefer_anim else "upload_photo"
                with ChatActionKeeper(self, chat_id, act_icon):
                    requester_name = member_name if is_group else user_name
                    c_res = c_engine.process_request(text, recipient=requester_name, prefer_animation=prefer_anim)
                    if c_res.ok and c_res.bytes_data:
                        if c_res.media_type in ("video", "animation"):
                            self.send_animation(
                                c_res.bytes_data,
                                caption=c_res.telegram_caption,
                                chat_id=chat_id,
                                reply_to_message_id=msg_id,
                                duration=int(c_res.duration or 4),
                                width=c_res.width,
                                height=c_res.height
                            )
                        else:
                            self.send_photo(c_res.bytes_data, caption=c_res.telegram_caption, chat_id=chat_id, reply_to_message_id=msg_id)

                        self.chat_histories[chat_id].append({"role": "user", "content": text})
                        self.chat_histories[chat_id].append({"role": "assistant", "content": f"[ChronoVision {c_res.media_type.upper()}]: {c_res.title}"})
                        SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: Telegram [{user_name}] (ChronoVision)", client_id=tg_client_id)
                        SYNC_HUB.add_chat_turn("assistant", c_res.telegram_caption, meta=f"{self.active_model_label} · ChronoVision", client_id=tg_client_id)
                        try:
                            from core.offline_chat_vault import get_offline_chat_vault
                            get_offline_chat_vault().record_turn(
                                user_message=text,
                                assistant_reply=c_res.telegram_caption,
                                session_id=tg_client_id,
                                client_id=tg_client_id,
                                model=self.active_model_label,
                                direction="present"
                            )
                        except Exception:
                            pass
                        return

            # 2.8 Detección Proactiva de Intenciones de Investigación Científica y Papers
            has_science_intent = any(ph in text_lower_intent for ph in (
                "investiga sobre", "investiga acerca de", "investigar sobre", "investígame", "investigame",
                "rigor cientifico", "rigor científico", "papers de", "papers sobre", "articulos cientificos",
                "artículos científicos", "articulos de investigacion", "artículos de investigación",
                "quiero aprender sobre", "ayúdame a aprender", "ayudame a aprender", "buscar papers",
                "mándame los links", "mandame los links", "mándame enlaces", "mandame enlaces",
                "enlaces de acceso", "links de acceso", "estudios cientificos", "estudios científicos"
            ))

            if has_science_intent:
                from core.scientific_research_engine import get_scientific_research_engine
                s_engine = get_scientific_research_engine()
                self.send_message(
                    f"🔬 **[INICIANDO INVESTIGACIÓN DE RIGOR CIENTÍFICO]**\n"
                    f"• **Consulta:** \"{text}\"\n"
                    f"• **Motores Académicos:** arXiv, OpenAlex, Europe PMC, PubMed & DOIs\n"
                    f"⏳ *Explorando repositorios revisados por pares y compilando enlaces de acceso...*",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                with ChatActionKeeper(self, chat_id, "typing"):
                    clean_query = re.sub(
                        r"\b(tardis|por favor|investiga sobre|investiga|investigar|busca|papers|quiero aprender sobre|mándame|mandame|links|enlaces|de rigor científico|de rigor cientifico)\b",
                        "",
                        text,
                        flags=re.IGNORECASE
                    ).strip() or text
                    report = s_engine.execute_research(clean_query, max_papers=4)
                    s_engine.send_report_to_telegram(report, chat_id=chat_id, reply_to_message_id=msg_id)

                    self.chat_histories[chat_id].append({"role": "user", "content": text})
                    self.chat_histories[chat_id].append({"role": "assistant", "content": f"[Reporte Científico]: {report.topic} ({len(report.papers)} papers)"})
                    SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: Telegram [{user_name}] (Investigación Científica)", client_id=tg_client_id)
                    SYNC_HUB.add_chat_turn("assistant", f"Reporte de rigor científico sobre '{report.topic}' despachado con enlaces y PDFs.", meta=f"{self.active_model_label} · Rigor Científico", client_id=tg_client_id)
                    return

            # 3. Despachar al núcleo soberano con contexto personalizado por usuario o grupo
            action_type = "record_video_note" if self.video_mode_always else ("record_voice" if is_call_active else "typing")
            turn_label = f"[{member_name}]" if is_group else f"[{user_name}]"
            hist_turn = f"{turn_label}: {text}" if is_group else text
            self.chat_histories[chat_id].append({"role": "user", "content": hist_turn})
            SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: Telegram {turn_label} (Conversación Soberana)", client_id=tg_client_id)

            reply_to_msg = msg.get("reply_to_message")
            reply_context = ""
            if reply_to_msg:
                r_user = (reply_to_msg.get("from") or {}).get("first_name", "Usuario")
                r_text = (reply_to_msg.get("text") or reply_to_msg.get("caption") or "").strip()
                if r_text:
                    reply_context = f"[En respuesta al mensaje previo de {r_user}: \"{r_text[:250]}\"]\n"

            if is_group:
                model_user_input = (
                    f"[Mensaje en el grupo de Telegram '{chat_title or 'T.A.R.D.I.S'}' enviado por {member_name} (@{username})]:\n"
                    f"{reply_context}"
                    f"{text}\n\n"
                    f"(Directiva obligatoria para TARDIS: Estás respondiendo a {member_name} en el grupo. Fomenta conversaciones amplias, profundas, articuladas y complejas. Dirígete a {member_name} de forma natural)."
                )
            else:
                model_user_input = f"{reply_context}{text}" if reply_context else text

            with ChatActionKeeper(self, chat_id, action_type):
                # Contexto de conversación estructurado
                chat_hist = [
                    {"role": m["role"], "content": m["content"]}
                    for m in self.chat_histories[chat_id]
                    if m.get("role") in ("user", "assistant") and m.get("content")
                ]

                # Invocación 100% LOCAL mediante KaijuCognitiveOrchestrator + TemporalBrain con historial conversacional
                hermes_reply = ""
                try:
                    from core.kaiju_cognitive_orchestrator import get_kaiju_cognitive_orchestrator
                    k_orch = get_kaiju_cognitive_orchestrator()
                    k_res = k_orch.process_turn(
                        user_input=model_user_input,
                        session_id=tg_client_id,
                        history=chat_hist[-8:],
                        force_offload=False,
                        call_priority=is_call_active,
                    )
                    cand = (k_res.get("response") or k_res.get("reply") or "").strip() if k_res else ""
                    if cand and not cand.startswith("[⚠️ Tiempo límite") and not cand.startswith("[Error"):
                        hermes_reply = cand
                except Exception as e_k:
                    logger.warning(f"Fallback desde KaijuCognitiveOrchestrator: {e_k}")

                if not hermes_reply:
                    resp_chat = process_agentic_chat(
                        message=model_user_input,
                        history=chat_hist[-8:],
                        model=os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU"),
                        num_ctx=int(os.environ.get("GIA_NUM_CTX", "8192")),
                        use_web=True,
                        is_local_request=True,
                        client_id=tg_client_id,
                        priority=is_call_active,
                        system_priority=is_call_active,
                        telegram_call_priority=is_call_active,
                        on_process_spawned=(
                            (lambda proc: _boost_inference_process_for_call(proc))
                            if is_call_active else None
                        ),
                    )
                    cand2 = (resp_chat.get("reply") or "").strip()
                    if cand2 and not cand2.startswith("[⚠️ Tiempo límite") and not cand2.startswith("[Error"):
                        hermes_reply = cand2

                # Garantía soberana final: llamada directa al socket IPC local TemporalBrain si aún no hubo respuesta
                if not hermes_reply:
                    try:
                        from core.temporal_brain import get_temporal_brain
                        tb_direct = get_temporal_brain()
                        tb_direct_res = tb_direct.chat(
                            messages=[{"role": "user", "content": model_user_input}],
                            temperature=0.3,
                            max_tokens=512
                        )
                        if tb_direct_res.get("ok") and tb_direct_res.get("reply"):
                            hermes_reply = tb_direct_res["reply"].strip()
                    except Exception as e_tbd:
                        logger.error(f"Error en respaldo directo TemporalBrain: {e_tbd}")

                if not hermes_reply:
                    hermes_reply = (
                        "Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar "
                        "las maravillas de la realidad y todas las dimensiones temporales. Mi núcleo de inferencia local "
                        "acaba de sincronizar tu mensaje; indícame de nuevo tu consulta para desarrollarla a fondo."
                    )

                # Garantizar que en grupos se dirija al miembro por su nombre sin duplicaciones
                if is_group and member_name and member_name != "Usuario":
                    first_clean = re.sub(r"[^\w]", "", member_name.lower())
                    start_text = re.sub(r"[^\w\s]", " ", hermes_reply[:60].lower())
                    tokens = set(start_text.split())
                    if first_clean not in tokens and not any(first_clean in t or t in first_clean for t in tokens if len(t) >= 4):
                        hermes_reply = f"{member_name}, {hermes_reply}"
                    hermes_reply = re.sub(rf"^{re.escape(member_name)}[,\s]+{re.escape(member_name)}[,\s]+", f"{member_name}, ", hermes_reply, flags=re.IGNORECASE)
                    hermes_reply = re.sub(r"^(\w+)[,\s]+\1[,\s]+", r"\1, ", hermes_reply, flags=re.IGNORECASE)

                self.chat_histories[chat_id].append({"role": "assistant", "content": hermes_reply})
                if len(self.chat_histories[chat_id]) > 60:
                    self.chat_histories[chat_id] = self.chat_histories[chat_id][-60:]

                SYNC_HUB.add_chat_turn("assistant", hermes_reply, meta=f"{self.active_model_label} · Núcleo Soberano", client_id=tg_client_id)
                try:
                    from core.offline_chat_vault import get_offline_chat_vault
                    get_offline_chat_vault().record_turn(
                        user_message=text,
                        assistant_reply=hermes_reply,
                        session_id=tg_client_id,
                        client_id=tg_client_id,
                        model=os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU"),
                        direction="present"
                    )
                except Exception:
                    pass

                # 1. Enviar de inmediato el texto completo (<1s latencia en grupo)
                self.send_message(hermes_reply, chat_id=chat_id, reply_to_message_id=msg_id)

                # 2. Despacho multimedia en el propio hilo TGWorker-{up_id} (no bloquea el bucle de polling)
                # Si hay llamada activa, mensaje de voz entrante o voz forzada, priorizar nota de voz Opus inmediata sin duplicar texto.
                if is_call_active:
                    try:
                        self.send_voice_from_text(
                            hermes_reply,
                            chat_id=chat_id,
                            reply_to_message_id=msg_id,
                            also_send_text=False,
                        )
                    except Exception as e_vce:
                        logger.warning(f"Aviso en despacho de voz en llamada: {e_vce}")
                elif self.video_mode_always:
                    try:
                        self.send_reply_with_video(hermes_reply, chat_id=chat_id, reply_to_message_id=msg_id)
                    except Exception as e_vid:
                        logger.warning(f"Aviso en despacho de video: {e_vid}")

        except Exception as e:
            logger.error(f"Error procesando mensaje en Telegram: {e}")
            self.send_message(f"⚠️ Error procesando directiva: {e}", chat_id=chat_id)

