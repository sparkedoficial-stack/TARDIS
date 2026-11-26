"""core/telegram/transport.py - Capa de transporte Telegram Bot API (texto, fotos, audio, voz, video, C310 live y FFmpeg)."""
from __future__ import annotations

from core.telegram.common import *
from core.telegram.common import _get_aegis_context_line, _boost_inference_process_for_call


class TelegramTransportMixin:
    """Métodos de envío/descarga multimedia, transcodificación FFmpeg y streaming C310 para TelegramBridge."""

    # --------------------------------------------------------------------------
    # VISUALIZACIÓN EN TERMINAL LOCAL & COMUNICACIÓN DE SALIDA (SEND API)
    # --------------------------------------------------------------------------

    def _print_incoming_request(self, user_name: str, chat_id: Any, req_type: str, content: str, username: str = ""):
        """Imprime un banner ANSI de alta visibilidad en la terminal local ante cada petición recibida por Telegram."""
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            user_label = f"{user_name} (@{username})" if username else str(user_name)
            clean_lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
            preview = clean_lines[0] if clean_lines else "(vacío)"
            if len(preview) > 60:
                preview = preview[:57] + "..."
            if len(clean_lines) > 1:
                preview += f" [+{len(clean_lines)-1} líneas]"

            banner = (
                f"\n\033[1;36m╔══════════════════════════════════════════════════════════════════════════════╗\033[0m\n"
                f"\033[1;36m║\033[1;97;44m 📱 [TELEGRAM -> TERMINAL LOCAL] PETICIÓN ENTRANTE                             \033[0m\033[1;36m║\033[0m\n"
                f"\033[1;36m╠══════════════════════════════════════════════════════════════════════════════╣\033[0m\n"
                f"\033[1;36m║\033[0m \033[1;33m• Remitente:\033[0m \033[1;97m{user_label:<63}\033[0m\033[1;36m║\033[0m\n"
                f"\033[1;36m║\033[0m \033[1;33m• Chat ID  :\033[0m \033[1;97m{str(chat_id):<63}\033[0m\033[1;36m║\033[0m\n"
                f"\033[1;36m║\033[0m \033[1;33m• Tipo     :\033[0m \033[1;92m{req_type:<63}\033[0m\033[1;36m║\033[0m\n"
                f"\033[1;36m║\033[0m \033[1;33m• Petición :\033[0m \033[1;93m\"{preview}\"\033[0m\n"
                f"\033[1;36m║\033[0m \033[1;33m• Timestamp:\033[0m \033[0;37m{now_str:<63}\033[0m\033[1;36m║\033[0m\n"
                f"\033[1;36m╚══════════════════════════════════════════════════════════════════════════════╝\033[0m\n"
            )
            sys.stdout.write(banner)
            sys.stdout.flush()
        except Exception as e:
            logger.debug(f"Error imprimiendo banner telegram entrante: {e}")

    def _print_outgoing_response(self, target_chat: Any, res_type: str, content: str):
        """Imprime un banner ANSI de alta visibilidad en la terminal local ante cada respuesta despachada hacia Telegram."""
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            clean_lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
            preview = clean_lines[0] if clean_lines else "(vacío)"
            if len(preview) > 60:
                preview = preview[:57] + "..."
            if len(clean_lines) > 1:
                preview += f" [+{len(clean_lines)-1} líneas]"

            banner = (
                f"\n\033[1;32m╔══════════════════════════════════════════════════════════════════════════════╗\033[0m\n"
                f"\033[1;32m║\033[1;97;42m 🤖 [TARDIS -> TELEGRAM] RESPUESTA DESPACHADA                                  \033[0m\033[1;32m║\033[0m\n"
                f"\033[1;32m╠══════════════════════════════════════════════════════════════════════════════╣\033[0m\n"
                f"\033[1;32m║\033[0m \033[1;33m• Destino  :\033[0m \033[1;97mChat ID {str(target_chat):<55}\033[0m\033[1;32m║\033[0m\n"
                f"\033[1;32m║\033[0m \033[1;33m• Tipo     :\033[0m \033[1;96m{res_type:<63}\033[0m\033[1;32m║\033[0m\n"
                f"\033[1;32m║\033[0m \033[1;33m• Respuesta:\033[0m \033[1;92m\"{preview}\"\033[0m\n"
                f"\033[1;32m║\033[0m \033[1;33m• Timestamp:\033[0m \033[0;37m{now_str:<63}\033[0m\033[1;32m║\033[0m\n"
                f"\033[1;32m╚══════════════════════════════════════════════════════════════════════════════╝\033[0m\n"
            )
            sys.stdout.write(banner)
            sys.stdout.flush()
        except Exception as e:
            logger.debug(f"Error imprimiendo banner telegram saliente: {e}")

    def send_message(
        self,
        text: str,
        chat_id: Optional[int | str] = None,
        parse_mode: str = "Markdown",
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        message_thread_id: Optional[int] = None
    ) -> Dict[str, Any]:
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token configured"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]

        if not target_chat:
            return {"ok": False, "error": "No target chat_id available"}

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if message_thread_id:
            payload["message_thread_id"] = message_thread_id

        # Visualizar respuesta en la terminal local
        self._print_outgoing_response(target_chat, "💬 TEXTO MARKDOWN", text)

        try:
            resp = requests.post(url, json=payload, timeout=12.0)
            data = resp.json()
            if not data.get("ok"):
                # Fallback sin parse_mode si falla por markdown
                payload.pop("parse_mode", None)
                resp_fb = requests.post(url, json=payload, timeout=12.0)
                data = resp_fb.json()
            return data
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_photo(
        self,
        photo: bytes | io.BytesIO | str | Path,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]

        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        # Visualizar despacho de imagen en la terminal local
        self._print_outgoing_response(target_chat, "📸 IMAGEN / CAPTURA", caption or "Imagen enviada")

        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        data: Dict[str, Any] = {"chat_id": target_chat}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "Markdown"
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

        try:
            files = {}
            if isinstance(photo, (str, Path)):
                p = Path(photo)
                if p.is_file():
                    files["photo"] = open(p, "rb")
                else:
                    return {"ok": False, "error": f"Archivo no encontrado: {photo}"}
            elif isinstance(photo, bytes):
                is_jpg = photo[:2] == b"\xff\xd8"
                files["photo"] = (
                    "snapshot.jpg" if is_jpg else "screenshot.png",
                    photo,
                    "image/jpeg" if is_jpg else "image/png",
                )
            elif isinstance(photo, io.BytesIO):
                raw_val = photo.getvalue()
                is_jpg = raw_val[:2] == b"\xff\xd8"
                files["photo"] = (
                    "image.jpg" if is_jpg else "image.png",
                    raw_val,
                    "image/jpeg" if is_jpg else "image/png",
                )

            resp = requests.post(url, data=data, files=files, timeout=20.0)
            res_json = resp.json()
            if not res_json.get("ok") and caption and "parse_mode" in data:
                data.pop("parse_mode", None)
                if isinstance(photo, (str, Path)):
                    files["photo"] = open(Path(photo), "rb")
                resp_fb = requests.post(url, data=data, files=files, timeout=20.0)
                res_json = resp_fb.json()
            return res_json
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def edit_message_media_photo(
        self,
        chat_id: int | str,
        message_id: int,
        photo_bytes: bytes,
        caption: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Actualiza en tiempo real un mensaje existente en Telegram con un nuevo fotograma (monitor en vivo en chat)."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}
        url = f"https://api.telegram.org/bot{token}/editMessageMedia"
        media_obj: Dict[str, Any] = {
            "type": "photo",
            "media": "attach://photo",
        }
        if caption:
            media_obj["caption"] = caption[:1020]
            media_obj["parse_mode"] = "Markdown"
        data: Dict[str, Any] = {
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "media": json.dumps(media_obj, ensure_ascii=False),
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup
        files = {"photo": (f"live_{int(time.time()*1000)}.jpg", photo_bytes, "image/jpeg")}
        try:
            resp = requests.post(url, data=data, files=files, timeout=12.0)
            return resp.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _build_c310_live_reply_markup(
        self,
        chat_id: int | str,
        live_feed_active: bool = False,
    ) -> Dict[str, Any]:
        """Construye la botonera táctica para controlar la cámara Tapo C310 en vivo desde Telegram."""
        is_private_chat = not str(chat_id).startswith("-")
        live_cam_url = ""
        try:
            from core.telegram_live_call_server import build_live_camera_url
            live_cam_url = build_live_camera_url(chat_id=chat_id, user_name="Arquitecto")
        except Exception:
            live_cam_url = ""

        rows: List[List[Dict[str, Any]]] = []
        if live_cam_url:
            if is_private_chat:
                rows.append(
                    [
                        {
                            "text": "📡 Abrir Monitor en Vivo (Tiempo Real)",
                            "web_app": {"url": live_cam_url},
                        }
                    ]
                )
            else:
                rows.append(
                    [
                        {
                            "text": "📡 Abrir Monitor en Vivo (Tiempo Real)",
                            "url": live_cam_url,
                        }
                    ]
                )

        rows.append(
            [
                {"text": "🎬 Clip en Vivo (6s)", "callback_data": "c310_live_clip"},
                {"text": "🎬 Clip en Vivo (12s)", "callback_data": "c310_live_clip_12"},
            ]
        )
        if live_feed_active:
            rows.append(
                [
                    {
                        "text": "⏹️ Detener Monitor en Chat",
                        "callback_data": "c310_chat_live_stop",
                    }
                ]
            )
        else:
            rows.append(
                [
                    {
                        "text": "🔴 Monitor Continuo en Chat (60s)",
                        "callback_data": "c310_chat_live_start",
                    }
                ]
            )
        rows.append(
            [
                {"text": "📸 Captura 2K QHD", "callback_data": "c310_snapshot"},
                {"text": "🔊 Alerta por Bocina", "callback_data": "c310_speak_alert"},
            ]
        )
        return {"inline_keyboard": rows}

    def send_c310_live_video(
        self,
        chat_id: Optional[int | str] = None,
        duration_sec: float = 6.0,
        reply_to_message_id: Optional[int] = None,
        start_chat_monitor: bool = False,
    ) -> Dict[str, Any]:
        """
        Captura y transmite en tiempo real un flujo de video MP4 H.264 con HUD táctico TARDIS
        y telemetría YOLOv8s directamente desde la cámara de seguridad TP-Link Tapo C310 (REDACTED_IP)
        hacia la terminal de Telegram, junto con controles interactivos y acceso a la Mini App en vivo.
        """
        target_chat = chat_id or self.config.get("admin_chat_id") or REDACTED_PHONE
        duration_sec = max(3.0, min(20.0, float(duration_sec)))

        from core.tapo_c310_sentinel import (
            get_c310_live_hud_jpeg_sync,
            record_c310_live_clip_sync,
        )

        markup = self._build_c310_live_reply_markup(target_chat, live_feed_active=start_chat_monitor)

        with ChatActionKeeper(self, target_chat, "upload_video"):
            clip_res = record_c310_live_clip_sync(
                duration_sec=duration_sec,
                fps=12,
                width=1280,
                hud=True,
            )

            if clip_res.get("ok") and clip_res.get("path"):
                mp4_path = Path(clip_res["path"])
                if mp4_path.is_file():
                    ts_now = time.strftime("%Y-%m-%d %H:%M:%S")
                    caption = (
                        f"🔴 **[TRANSMISIÓN DE VIDEO EN VIVO · GOD-EYE C310]**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"• **Cámara:** `GOD-EYE (TP-Link Tapo C310 @ REDACTED_IP)`\n"
                        f"• **Flujo Nativo:** `2304×1296 (2K QHD)` → Stream `{clip_res.get('width', 1280)}×{clip_res.get('height', 720)}` @ `{clip_res.get('fps', 12)} FPS`\n"
                        f"• **Duración / Cuadros:** `{clip_res.get('duration_sec', duration_sec)}s` (`{clip_res.get('frames', 0)} fotogramas en vivo`)\n"
                        f"• **Individuos en escena (YOLOv8s):** `{clip_res.get('persons_detected', 0)}`\n"
                        f"• **Hora local:** `{ts_now}`\n\n"
                        f"💡 *Pulsa* **«📡 Abrir Monitor en Vivo»** *para ver el stream continuo en tiempo real y hablar por la bocina, o* **«🔴 Monitor Continuo en Chat»** *para actualizar el visor aquí mismo.*"
                    )
                    res_vid = self.send_video(
                        mp4_path,
                        caption=caption,
                        chat_id=target_chat,
                        reply_to_message_id=reply_to_message_id,
                        duration=int(round(float(clip_res.get("duration_sec", duration_sec)))),
                        width=int(clip_res.get("width", 1280)),
                        height=int(clip_res.get("height", 720)),
                        supports_streaming=True,
                        reply_markup=markup,
                    )
                    if start_chat_monitor:
                        self.start_c310_chat_live_feed(chat_id=target_chat, duration_sec=60.0)
                    return {
                        "ok": bool(res_vid.get("ok")),
                        "mode": "live_video_mp4",
                        "clip": clip_res,
                        "telegram": res_vid,
                    }

            # Fallback inmediato con fotograma en vivo + monitor en chat si el clip falló
            jpg_bytes, meta = get_c310_live_hud_jpeg_sync(width=1280, hud=True)
            if jpg_bytes:
                metrics = meta.get("metrics", {})
                caption_fb = (
                    f"🔴 **[SEÑAL EN VIVO · GOD-EYE C310 (`REDACTED_IP`)]**\n"
                    f"• **Individuos en escena:** `{metrics.get('current_persons', 0)}`\n"
                    f"• **Estado:** `ACTIVO 24/7`"
                )
                res_ph = self.send_photo(
                    jpg_bytes,
                    caption=caption_fb,
                    chat_id=target_chat,
                    reply_to_message_id=reply_to_message_id,
                    reply_markup=markup,
                )
                return {"ok": bool(res_ph.get("ok")), "mode": "live_snapshot_fallback", "telegram": res_ph}

            return {"ok": False, "error": clip_res.get("error", "No se pudo transmitir video en vivo de C310")}

    def stop_c310_chat_live_feed(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        target_chat = chat_id or self.config.get("admin_chat_id") or REDACTED_PHONE
        key = str(target_chat)
        ev = self.active_c310_live_feeds.pop(key, None)
        if ev is not None:
            ev.set()
            return {"ok": True, "stopped": True, "chat_id": target_chat}
        return {"ok": True, "stopped": False, "chat_id": target_chat}

    def start_c310_chat_live_feed(
        self,
        chat_id: Optional[int | str] = None,
        duration_sec: float = 60.0,
        interval_sec: float = 1.8,
    ) -> Dict[str, Any]:
        """
        Inicia un monitor en vivo dentro del propio chat de Telegram que actualiza el fotograma
        de la cámara Tapo C310 cada ~1.8s in-place (`editMessageMedia`) durante `duration_sec`.
        """
        target_chat = chat_id or self.config.get("admin_chat_id") or REDACTED_PHONE
        key = str(target_chat)

        # Detener cualquier bucle previo en este chat
        prev_ev = self.active_c310_live_feeds.pop(key, None)
        if prev_ev is not None:
            prev_ev.set()

        stop_ev = threading.Event()
        self.active_c310_live_feeds[key] = stop_ev

        from core.tapo_c310_sentinel import get_c310_live_hud_jpeg_sync

        jpg0, meta0 = get_c310_live_hud_jpeg_sync(width=1280, hud=True)
        if not jpg0:
            self.active_c310_live_feeds.pop(key, None)
            return {"ok": False, "error": "No hay fotograma en vivo disponible en C310"}

        metrics0 = meta0.get("metrics", {})
        ts0 = time.strftime("%Y-%m-%d %H:%M:%S")
        init_caption = (
            f"🔴 **[MONITOR EN VIVO EN CHAT · GOD-EYE C310]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Estado:** `TRANSMITIENDO EN TIEMPO REAL` (Restan `{int(duration_sec)}s`)\n"
            f"• **Cámara:** `TP-Link Tapo C310 @ REDACTED_IP`\n"
            f"• **Individuos en escena (YOLOv8s):** `{metrics0.get('current_persons', 0)}`\n"
            f"• **Hora del fotograma:** `{ts0}`"
        )
        active_markup = self._build_c310_live_reply_markup(target_chat, live_feed_active=True)
        init_res = self.send_photo(
            jpg0,
            caption=init_caption,
            chat_id=target_chat,
            reply_markup=active_markup,
        )
        msg_obj = (init_res or {}).get("result") or {}
        message_id = msg_obj.get("message_id")
        if not message_id:
            self.active_c310_live_feeds.pop(key, None)
            return {"ok": False, "error": f"No se pudo crear mensaje de monitor: {init_res}"}

        def _live_updater_loop() -> None:
            t_start = time.time()
            frame_idx = 1
            try:
                while not stop_ev.is_set():
                    elapsed = time.time() - t_start
                    rem = duration_sec - elapsed
                    if rem <= 0:
                        break
                    stop_ev.wait(timeout=max(1.2, float(interval_sec)))
                    if stop_ev.is_set():
                        break
                    jpg_n, meta_n = get_c310_live_hud_jpeg_sync(width=1280, hud=True)
                    if not jpg_n:
                        continue
                    frame_idx += 1
                    metrics_n = meta_n.get("metrics", {})
                    ts_n = time.strftime("%Y-%m-%d %H:%M:%S")
                    cap_n = (
                        f"🔴 **[MONITOR EN VIVO EN CHAT · CUADRO #{frame_idx}]**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"• **Estado:** `EN VIVO` (Restan `{max(0, int(duration_sec - (time.time() - t_start)))}s`)\n"
                        f"• **Cámara:** `GOD-EYE · Tapo C310 @ REDACTED_IP`\n"
                        f"• **Individuos en escena (YOLOv8s):** `{metrics_n.get('current_persons', 0)}`\n"
                        f"• **Inferencia IA:** `{metrics_n.get('last_inference_ms', 0)} ms`\n"
                        f"• **Hora del fotograma:** `{ts_n}`"
                    )
                    self.edit_message_media_photo(
                        chat_id=target_chat,
                        message_id=message_id,
                        photo_bytes=jpg_n,
                        caption=cap_n,
                        reply_markup=active_markup,
                    )
            finally:
                if self.active_c310_live_feeds.get(key) is stop_ev:
                    self.active_c310_live_feeds.pop(key, None)
                jpg_end, meta_end = get_c310_live_hud_jpeg_sync(width=1280, hud=True)
                if jpg_end:
                    metrics_end = meta_end.get("metrics", {})
                    ts_end = time.strftime("%Y-%m-%d %H:%M:%S")
                    cap_end = (
                        f"📹 **[MONITOR EN CHAT FINALIZADO · {frame_idx} CUADROS SERVIDOS]**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"• **Cámara:** `GOD-EYE · Tapo C310 @ REDACTED_IP`\n"
                        f"• **Individuos en escena:** `{metrics_end.get('current_persons', 0)}`\n"
                        f"• **Última actualización:** `{ts_end}`\n"
                        f"💡 *Pulsa* **«🔴 Monitor Continuo en Chat»** *o* **«📡 Abrir Monitor en Vivo»** *para continuar.*"
                    )
                    self.edit_message_media_photo(
                        chat_id=target_chat,
                        message_id=message_id,
                        photo_bytes=jpg_end,
                        caption=cap_end,
                        reply_markup=self._build_c310_live_reply_markup(target_chat, live_feed_active=False),
                    )

        threading.Thread(
            target=_live_updater_loop,
            daemon=True,
            name=f"C310LiveChatMonitor-{target_chat}",
        ).start()
        return {"ok": True, "chat_id": target_chat, "message_id": message_id, "duration_sec": duration_sec}

    def send_document(
        self,
        document: bytes | io.BytesIO | str | Path,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Envía un documento (ej: PDF, reporte de investigación) a Telegram."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]

        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        self._print_outgoing_response(target_chat, "📄 DOCUMENTO PDF", caption or (filename or "Documento enviado"))

        url = f"https://api.telegram.org/bot{token}/sendDocument"
        data: Dict[str, Any] = {"chat_id": target_chat}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "Markdown"
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if message_thread_id:
            data["message_thread_id"] = message_thread_id

        fp_to_close = None
        try:
            files = {}
            if isinstance(document, (str, Path)):
                p = Path(document)
                if p.is_file():
                    fname = filename or p.name
                    mime = "application/pdf" if fname.lower().endswith(".pdf") else "application/octet-stream"
                    fp_to_close = open(p, "rb")
                    files["document"] = (fname, fp_to_close, mime)
                else:
                    return {"ok": False, "error": f"Archivo no encontrado: {document}"}
            elif isinstance(document, bytes):
                fname = filename or "documento.pdf"
                mime = "application/pdf" if fname.lower().endswith(".pdf") else "application/octet-stream"
                files["document"] = (fname, document, mime)
            elif isinstance(document, io.BytesIO):
                fname = filename or "documento.pdf"
                mime = "application/pdf" if fname.lower().endswith(".pdf") else "application/octet-stream"
                files["document"] = (fname, document.getvalue(), mime)

            try:
                resp = requests.post(url, data=data, files=files, timeout=45.0)
                res_json = resp.json()
                if not res_json.get("ok") and "caption" in data and "parse_mode" in data:
                    data.pop("parse_mode", None)
                    if fp_to_close:
                        fp_to_close.seek(0)
                        files["document"] = (fname, fp_to_close, mime)
                    resp = requests.post(url, data=data, files=files, timeout=45.0)
                    res_json = resp.json()
                return res_json
            finally:
                if fp_to_close:
                    try:
                        fp_to_close.close()
                    except Exception:
                        pass
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def transcode_to_telegram_fps(self, video_bytes: bytes, target_fps: int = 60) -> bytes:
        """
        Adapta la animación/video para entrega óptima en Telegram a target_fps (60 FPS por defecto).
        Toma el master renderizado a alta fidelidad (120 FPS) y lo transcodifica/remuestrea a 60 FPS
        con aceleración NVENC (respaldo CPU libx264) y +faststart para compatibilidad total con Telegram.
        """
        if not video_bytes or len(video_bytes) < 1024:
            return video_bytes

        # Verificar cabecera básica MP4 (ftyp / atom)
        if not (b"ftyp" in video_bytes[:64] or video_bytes.startswith(b"\x00\x00\x00")):
            return video_bytes

        # Caché LRU acotada por (sha256, target_fps) para no re-codificar el mismo video al enviarlo a múltiples chats
        import hashlib
        cache_key = (hashlib.sha256(video_bytes).hexdigest(), int(target_fps))
        fps_cache = getattr(self, "_fps_transcode_cache", None)
        if isinstance(fps_cache, dict) and cache_key in fps_cache:
            return fps_cache[cache_key]

        # Calcular hilos seguros según cpuset efectivo y presión del ResourceGovernor (evita -threads 16 en cgroups acotados)
        try:
            allowed_cpus = max(1, len(os.sched_getaffinity(0)))
        except Exception:
            allowed_cpus = max(1, os.cpu_count() or 4)
        ff_threads = max(1, min(4, allowed_cpus // 2 or 1))
        try:
            from core.tardis_resource_governor import get_pressure_sleep_multiplier
            gov_lvl, _ = get_pressure_sleep_multiplier(max_age_s=60.0)
            if gov_lvl in ("ORANGE", "RED"):
                ff_threads = min(ff_threads, 2)
        except Exception:
            pass
        ff_threads_s = str(ff_threads)

        in_path = None
        out_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as in_f:
                in_path = Path(in_f.name)
                in_f.write(video_bytes)

            # Solo remuestrear a la baja cuando el master supera target_fps (ej. 120/240 FPS -> 60 FPS).
            # Nunca hacer upsampling de videos 24/25/30/50/60 FPS: Telegram los reproduce nativamente y
            # duplicar cuadros quema minutos de NVENC/CPU y provoca timeouts bajo CPUQuota.
            is_hdr = False
            in_fps = 0.0
            try:
                probe = subprocess.run([
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=r_frame_rate,avg_frame_rate,pix_fmt,color_space",
                    "-of", "default=noprint_wrappers=1", str(in_path)
                ], capture_output=True, text=True, timeout=5.0)
                out_txt = probe.stdout.lower()
                if "p010" in out_txt or "10le" in out_txt or "bt2020" in out_txt:
                    is_hdr = True
                for line in out_txt.splitlines():
                    if "frame_rate" in line and "=" in line:
                        _, rate_str = line.split("=", 1)
                        if "/" in rate_str:
                            num, den = rate_str.split("/", 1)
                            if den and float(den) > 0:
                                in_fps = float(num) / float(den)
                                break
                if in_fps > 0 and in_fps <= (target_fps + 0.5):
                    return video_bytes
            except Exception:
                pass

            out_path = in_path.with_name(f"{in_path.stem}_tg{target_fps}.mp4")

            # Mezcla temporal de 4 fotogramas para renderizados a 240 FPS portados a 60 FPS
            if in_fps >= 230.0 and target_fps == 60:
                filter_v = f"tmix=frames=4:weights='1 1 1 1',fps={target_fps}"
            else:
                filter_v = f"fps=fps={target_fps}"

            common_in = [
                "ffmpeg", "-y",
                "-threads", ff_threads_s,
                "-filter_threads", "1",
                "-filter_complex_threads", "1",
                "-i", str(in_path),
                "-filter:v", filter_v,
            ]
            if is_hdr:
                cmd_nvenc = common_in + [
                    "-threads", ff_threads_s,
                    "-c:v", "hevc_nvenc",
                    "-preset", "p4",
                    "-cq", "22",
                    "-b:v", "25M",
                    "-maxrate", "38M",
                    "-bufsize", "50M",
                    "-pix_fmt", "p010le",
                    "-color_primaries", "bt2020",
                    "-color_trc", "arib-std-b67",
                    "-colorspace", "bt2020nc",
                    "-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=18:matrix_coefficients=9",
                    "-tag:v", "hvc1",
                    "-movflags", "+faststart",
                    str(out_path)
                ]
                cmd_cpu = common_in + [
                    "-c:v", "libx265",
                    "-preset", "ultrafast",
                    "-crf", "20",
                    "-pix_fmt", "yuv420p10le",
                    "-color_primaries", "bt2020",
                    "-color_trc", "arib-std-b67",
                    "-colorspace", "bt2020nc",
                    "-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=18:matrix_coefficients=9",
                    "-tag:v", "hvc1",
                    "-threads", ff_threads_s,
                    "-movflags", "+faststart",
                    str(out_path)
                ]
            else:
                cmd_nvenc = common_in + [
                    "-threads", ff_threads_s,
                    "-c:v", "h264_nvenc",
                    "-preset", "p4",
                    "-cq", "22",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    str(out_path)
                ]
                cmd_cpu = common_in + [
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "21",
                    "-pix_fmt", "yuv420p",
                    "-threads", ff_threads_s,
                    "-movflags", "+faststart",
                    str(out_path)
                ]

            proc = None
            try:
                proc = subprocess.run(cmd_nvenc, capture_output=True, timeout=60.0)
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ [TELEGRAM_FPS_CONVERTER] Timeout en NVENC (60s); usando fallback CPU...")
                proc = None
            if proc is None or proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
                if out_path.exists():
                    out_path.unlink(missing_ok=True)
                proc = subprocess.run(cmd_cpu, capture_output=True, timeout=90.0)

            if out_path.exists() and out_path.stat().st_size > 0:
                converted_bytes = out_path.read_bytes()
                if not isinstance(fps_cache, dict):
                    fps_cache = {}
                    self._fps_transcode_cache = fps_cache
                if len(fps_cache) >= 4:
                    fps_cache.pop(next(iter(fps_cache)), None)
                fps_cache[cache_key] = converted_bytes
                logger.info(f"🎞️ [TELEGRAM_FPS_CONVERTER] Video/Animación adaptada exitosamente a {target_fps} FPS para Telegram ({len(video_bytes)} -> {len(converted_bytes)} bytes, HDR={is_hdr}, threads={ff_threads_s}).")
                return converted_bytes
            return video_bytes
        except Exception as e:
            logger.warning(f"⚠️ [TELEGRAM_FPS_CONVERTER] Excepción transcodificando video para Telegram: {e}")
            return video_bytes
        finally:
            try:
                if in_path and in_path.exists(): in_path.unlink()
                if out_path and out_path.exists(): out_path.unlink()
            except Exception:
                pass

    def send_animation(
        self,
        animation: bytes | io.BytesIO | str | Path,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        duration: Optional[int] = None,
        width: int = 720,
        height: int = 720,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Envía una animación en bucle continuo (sendAnimation MP4/GIF) a Telegram con fallback a sendVideo."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        # MANDATO SOBERANO: Si la entrega está configurada como video o para reproducir audio,
        # despachar vía sendVideo para que Telegram active el reproductor con sonido.
        if self.config.get("animation_delivery_type") == "video":
            return self.send_video(
                video=animation,
                caption=caption,
                chat_id=target_chat,
                reply_to_message_id=reply_to_message_id,
                duration=duration,
                width=width,
                height=height,
                reply_markup=reply_markup
            )

        anim_bytes = None
        if isinstance(animation, (str, Path)):
            p = Path(animation)
            if p.is_file():
                anim_bytes = p.read_bytes()
            else:
                return {"ok": False, "error": f"Archivo no encontrado: {animation}"}
        elif isinstance(animation, io.BytesIO):
            anim_bytes = animation.getvalue()
        elif isinstance(animation, bytes):
            anim_bytes = animation

        if not anim_bytes:
            return {"ok": False, "error": "Animación vacía"}

        # Remuestrear video a 60 FPS para despacho soberano en Telegram
        anim_bytes = self.transcode_to_telegram_fps(anim_bytes, target_fps=self.animation_telegram_fps)

        url = f"https://api.telegram.org/bot{token}/sendAnimation"
        data: Dict[str, Any] = {
            "chat_id": target_chat,
            "width": int(width),
            "height": int(height),
        }
        if caption:
            caption_trunc = caption[:1015] + "..." if len(caption) > 1020 else caption
            data["caption"] = caption_trunc
            data["parse_mode"] = "Markdown"
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if duration:
            data["duration"] = int(duration)
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

        files = {"animation": ("animation.mp4", anim_bytes, "video/mp4")}

        self._print_outgoing_response(target_chat, "🌀 ANIMACIÓN DINÁMICA (LOOP MP4)", caption or "Animación enviada")

        try:
            resp = requests.post(url, data=data, files=files, timeout=45.0)
            res_data = resp.json()
            if not res_data.get("ok"):
                if caption and "parse_mode" in data:
                    data.pop("parse_mode", None)
                    files = {"animation": ("animation.mp4", anim_bytes, "video/mp4")}
                    res_data = requests.post(url, data=data, files=files, timeout=45.0).json()
                if not res_data.get("ok"):
                    logger.warning(f"sendAnimation falló ({res_data.get('description')}), probando fallback a sendVideo...")
                    return self.send_video(
                        video=anim_bytes,
                        caption=caption,
                        chat_id=target_chat,
                        reply_to_message_id=reply_to_message_id,
                        duration=duration,
                        width=width,
                        height=height,
                        reply_markup=reply_markup
                    )
            return res_data
        except Exception as e:
            logger.error(f"Excepción en send_animation: {e}, aplicando fallback a send_video...")
            return self.send_video(
                video=anim_bytes,
                caption=caption,
                chat_id=target_chat,
                reply_to_message_id=reply_to_message_id,
                duration=duration,
                width=width,
                height=height,
                reply_markup=reply_markup
            )

    def send_3d_model_hd_to_architect(
        self,
        mesh: Any,
        style: str = "hologram",
        pitch_deg: float = 24.0,
        yaw_deg: float = 42.0,
        roll_deg: float = 0.0,
        width: int = 1920,
        height: int = 1440,
        source: str = "Motor de Renderizado 3D HoloDeck",
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        as_animation: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Renderiza y despacha automáticamente un modelo 3D como animación orbital 360°
        o en Alta Definición estática (1920x1440 HD) al Telegram del Arquitecto (REDACTED_PHONE).
        """
        try:
            from core.render_3d_engine import get_render_3d_engine
            engine = get_render_3d_engine()

            target_chat = chat_id or self.config.get("admin_chat_id") or REDACTED_PHONE

            # Determinar si se envía como animación 3D u objeto fijo
            should_animate = as_animation is True

            if should_animate:
                anim_w = self.animation_width
                anim_h = self.animation_height
                anim_bytes = engine.render_mesh_animation(
                    mesh,
                    frames=240,
                    fps=self.animation_render_fps,
                    ported_fps=self.animation_telegram_fps,
                    width=anim_w,
                    height=anim_h,
                    hdr=self.animation_hdr_enabled,
                    style=style,
                    pitch_deg=pitch_deg,
                    show_hud=True
                )
                if anim_bytes:
                    caption = (
                        f"🌀 **[MODELO 3D EN ANIMACIÓN ORBITAL 360° · DESPACHO SOBERANO]**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"• **Modelo:** {mesh.title}\n"
                        f"• **Categoría:** {mesh.category}\n"
                        f"• **Dinámica:** Órbita Continua 360° & Fases Cuánticas\n"
                        f"• **Resolución:** 4K UHD ({anim_w} × {anim_h}) HDR · {self.animation_render_fps} FPS Render (Porteado a {self.animation_telegram_fps} FPS por Telegram)\n"
                        f"• **Origen:** {source}\n"
                        f"• **Topología:** `{len(mesh.vertices)}` vértices | `{len(mesh.faces)}` caras\n"
                        f"• **Ecuación / Ley:** `{mesh.formula}`\n"
                        f"• **Explicación Científica:** {mesh.description}\n"
                        f"💡 *Dato Curioso:* {mesh.fun_fact}"
                    )
                    res = self.send_animation(
                        anim_bytes,
                        caption=caption,
                        chat_id=target_chat,
                        reply_to_message_id=reply_to_message_id,
                        duration=3,
                        width=anim_w,
                        height=anim_h
                    )
                    logger.info(f"🚀 [3D_ANIM_DISPATCH] Animación 3D {mesh.title} ({anim_w}x{anim_h}) despachada al Telegram del Arquitecto ({target_chat}).")
                    return res

            png_bytes = engine.render_to_png_bytes(
                mesh,
                width=width,
                height=height,
                pitch_deg=pitch_deg,
                yaw_deg=yaw_deg,
                style=style,
                show_hud=True,
                rot_z=roll_deg
            )

            caption = (
                f"🎨 **[MODELO 3D EN ALTA DEFINICIÓN (HD) · DESPACHO SOBERANO]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Modelo:** {mesh.title}\n"
                f"• **Categoría:** {mesh.category}\n"
                f"• **Resolución:** `{width} × {height}` HD (Hi-Res Super-Sampling)\n"
                f"• **Origen:** {source}\n"
                f"• **Topología:** `{len(mesh.vertices)}` vértices | `{len(mesh.faces)}` caras | `{len(mesh.edges)}` aristas\n"
                f"• **Ecuación / Ley:** `{mesh.formula}`\n"
                f"• **Explicación Científica:** {mesh.description}\n"
                f"💡 *Dato Curioso:* {mesh.fun_fact}"
            )

            res = self.send_photo(png_bytes, caption=caption, chat_id=target_chat, reply_to_message_id=reply_to_message_id)
            logger.info(f"🚀 [3D_HD_DISPATCH] Modelo {mesh.title} ({width}x{height} HD) despachado al Telegram del Arquitecto ({target_chat}).")
            return res
        except Exception as e:
            logger.error(f"❌ [3D_HD_DISPATCH_ERROR] Error al despachar modelo 3D HD a Telegram: {e}")
            return {"ok": False, "error": str(e)}

    def send_tardis_autonomous_creation(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        """
        Ejecuta un ciclo de inspiración espontánea de TARDIS, genera la obra
        (geometría sagrada, atractor caótico, fractal, simulación física, animación o video)
        y la despacha proactivamente a Telegram con la reflexión ontológica de TARDIS.
        """
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat"}

        try:
            from core.chronovision_engine import get_chronovision_engine
            engine = get_chronovision_engine()
            item, res = engine.genesis.get_spontaneous_inspiration(prefer_animation=self.prefer_animations_over_still_images)
            if res.ok and res.bytes_data:
                if res.media_type in ("video", "animation"):
                    send_res = self.send_animation(
                        res.bytes_data,
                        caption=res.telegram_caption,
                        chat_id=target_chat,
                        duration=int(res.duration or 4),
                        width=res.width,
                        height=res.height
                    )
                else:
                    send_res = self.send_photo(
                        res.bytes_data,
                        caption=res.telegram_caption,
                        chat_id=target_chat
                    )
                return {"ok": True, "title": item["title"], "send_result": send_res}
            return {"ok": False, "error": res.error or "Error generando obra"}
        except Exception as e:
            logger.error(f"Error en send_tardis_autonomous_creation: {e}")
            return {"ok": False, "error": str(e)}

    def send_chat_action(self, action: str = "record_voice", chat_id: Optional[int | str] = None) -> bool:
        """Envía indicador de acción a Telegram (record_voice, typing, upload_voice)."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return False

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return False

        url = f"https://api.telegram.org/bot{token}/sendChatAction"
        try:
            resp = requests.post(url, json={"chat_id": target_chat, "action": action}, timeout=8.0)
            return bool(resp.json().get("ok"))
        except Exception:
            return False

    def convert_to_wav(self, audio_bytes: bytes) -> Optional[bytes]:
        """Convierte cualquier formato de audio recibido (OGG, MP3, etc.) a WAV 16kHz mono para STT."""
        try:
            cmd = ["ffmpeg", "-y", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            wav_out, _ = proc.communicate(input=audio_bytes, timeout=15.0)
            if proc.returncode == 0 and wav_out:
                return wav_out
        except Exception as e:
            logger.error(f"Error convirtiendo audio a WAV con ffmpeg: {e}")
        return None

    def convert_to_ogg(self, audio_bytes: bytes) -> Optional[bytes]:
        """Convierte audio (MP3 o WAV) a OGG Opus nativo para Telegram Voice Notes."""
        try:
            cmd = ["ffmpeg", "-y", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "32k", "-vbr", "on", "-f", "ogg", "pipe:1"]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            ogg_out, _ = proc.communicate(input=audio_bytes, timeout=15.0)
            if proc.returncode == 0 and ogg_out:
                return ogg_out
        except Exception as e:
            logger.error(f"Error convirtiendo audio a OGG Opus con ffmpeg: {e}")
        return None

    def download_telegram_file(self, file_id: str) -> Optional[bytes]:
        """Descarga un archivo (nota de voz/audio) directamente desde los servidores de Telegram."""
        token = self.config.get("bot_token", "").strip()
        if not token or not file_id:
            return None
        try:
            gf_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
            res = requests.get(gf_url, timeout=15.0).json()
            if not res.get("ok"):
                return None
            file_path = res.get("result", {}).get("file_path")
            if not file_path:
                return None
            dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            resp = requests.get(dl_url, timeout=30.0)
            if resp.status_code == 200:
                return resp.content
        except Exception as e:
            logger.error(f"Error descargando archivo {file_id} de Telegram: {e}")
        return None

    def download_telegram_file_to_disk(self, file_id: str, dest_path: Path | str, timeout: float = 120.0) -> bool:
        """Descarga un archivo grande (ej: video de hasta 20 MB) de Telegram directamente a disco por streaming."""
        token = self.config.get("bot_token", "").strip()
        if not token or not file_id:
            return False
        try:
            gf_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
            res = requests.get(gf_url, timeout=20.0).json()
            if not res.get("ok"):
                logger.error(f"Telegram getFile falló para {file_id}: {res.get('description')}")
                return False
            file_path = res.get("result", {}).get("file_path")
            if not file_path:
                return False
            dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            dest = Path(dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(dl_url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
            return dest.exists() and dest.stat().st_size > 0
        except Exception as e:
            logger.error(f"Error descargando archivo de Telegram a disco {file_id}: {e}")
            return False

    def transcribe_audio(self, audio_bytes: bytes, lang: str = "es-MX") -> Optional[str]:
        """Transcribe bytes de voz a texto priorizando faster-whisper local con respaldo Google STT."""
        if not audio_bytes:
            return None

        # 1. Motor primario soberano: faster-whisper local (baja latencia, sin dependencia externa)
        try:
            if not hasattr(self, "_local_stt") or self._local_stt is None:
                from core.tardis_voice_local import LocalSpeechToText
                self._local_stt = LocalSpeechToText(model_size="base", cpu_threads=6)
            short_lang = (lang.split("-")[0] if lang else "es").lower()
            txt_local, _ = self._local_stt.transcribe_bytes(audio_bytes, suffix=".ogg", language=short_lang)
            if txt_local and txt_local.strip():
                return txt_local.strip()
        except Exception as e_lw:
            logger.warning(f"Respaldo desde faster-whisper local en transcribe_audio: {e_lw}")

        # 2. Respaldo secundario: SpeechRecognition (Google STT)
        wav_bytes = self.convert_to_wav(audio_bytes)
        if not wav_bytes:
            return None

        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                audio_data = recognizer.record(source)

            try:
                text = recognizer.recognize_google(audio_data, language=lang)
                if text and text.strip():
                    return text.strip()
            except sr.UnknownValueError:
                pass
            except sr.RequestError as re_err:
                logger.warning(f"Google STT request error ({lang}): {re_err}")

            try:
                text = recognizer.recognize_google(audio_data, language="es-ES")
                if text and text.strip():
                    return text.strip()
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Error procesando transcripción STT: {e}")

        return None

    def clean_text_for_speech(self, text: str) -> str:
        """Limpia markdown y caracteres de interfaz para una lectura natural y fluida con Cortana."""
        if not text:
            return ""
        t = text
        # Simplificar bloques de código multilínea para que Cortana los mencione de manera natural
        t = re.sub(r"```[a-zA-Z0-9_-]*\n([\s\S]*?)```", r" Código en pantalla: \1 ", t)
        t = re.sub(r"```", " ", t)
        t = re.sub(r"`([^`]+)`", r"\1", t)
        # Convertir enlaces markdown [Texto](URL) a solo Texto
        t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", t)
        # Quitar formato de negrita y cursiva
        t = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", t)
        t = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", t)
        # Quitar numerales de encabezados
        t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
        # Quitar separadores gráficos repetidos
        t = re.sub(r"[━─=_\-]{3,}", " ", t)
        # Normalizar espacios
        t = re.sub(r"[ \t]+", " ", t)
        return t.strip()

    def synthesize_speech(self, text: str, voice_id: Optional[str] = None) -> Optional[bytes]:
        """Sintetiza texto completo a voz usando voice.py (Cortana Neural / Edge-TTS) y genera OGG Opus."""
        text_clean = self.clean_text_for_speech(text)
        if not text_clean:
            return None
        target_voice = voice_id or self.config.get("cortana_voice", "es-MX-DaliaNeural")
        try:
            import voice as _v
            # Asegurar locución con la voz de Cortana Neural
            mp3_bytes = _v.synthesize_to_bytes(text_clean, voice=target_voice)
            if mp3_bytes:
                ogg_bytes = self.convert_to_ogg(mp3_bytes)
                return ogg_bytes or mp3_bytes
        except Exception as e:
            logger.error(f"Error sintetizando voz de Cortana para Telegram: {e}")
        return None

    def send_reply_with_voice(
        self,
        text: str,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        caption_voice: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Envía la respuesta de texto a Telegram y simultáneamente sintetiza un audio
        leyendo todo el texto con la voz de Cortana, enviándolo a la vez que el texto.
        """
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]

        # 1. Enviar el mensaje de texto de inmediato
        res_msg = self.send_message(text, chat_id=target_chat, reply_to_message_id=reply_to_message_id)

        # 2. Sintetizar la lectura completa con Cortana y enviarla a la vez si está activado
        res_voice = None
        cid_int = int(target_chat) if str(target_chat).lstrip("-").isdigit() else target_chat
        should_voice = self.voice_mode_always or (cid_int in self.active_calls)

        if should_voice:
            with ChatActionKeeper(self, target_chat, "record_voice"):
                ogg_audio = self.synthesize_speech(text)
                if ogg_audio:
                    voice_caption = caption_voice or f"🎙️ {text}"
                    res_voice = self.send_voice(
                        ogg_audio,
                        caption=voice_caption,
                        chat_id=target_chat,
                        reply_to_message_id=reply_to_message_id
                    )

        return {"ok": True, "message_result": res_msg, "voice_result": res_voice}

    def send_voice_from_text(
        self,
        text: str,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        voice_id: Optional[str] = None,
        also_send_text: bool = False
    ) -> Dict[str, Any]:
        """
        Sintetiza texto directamente a nota de voz Opus OGG y la despacha por sendVoice.
        Opcionalmente envía también el texto completo por send_message si se solicita.
        """
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]

        clean_text = self.clean_text_for_speech(text)
        if not clean_text:
            return {"ok": False, "error": "Texto vacío para síntesis de voz"}

        with ChatActionKeeper(self, target_chat, "record_voice"):
            ogg_audio = self.synthesize_speech(clean_text, voice_id=voice_id)
            if not ogg_audio:
                res_msg = self.send_message(text, chat_id=target_chat, reply_to_message_id=reply_to_message_id)
                return {"ok": False, "error": "Fallo en síntesis TTS", "fallback_message": res_msg}

            cap = caption or (f"🎙️ {clean_text[:900]}..." if len(clean_text) > 900 else f"🎙️ {clean_text}")
            res_voice = self.send_voice(
                ogg_audio,
                caption=cap,
                chat_id=target_chat,
                reply_to_message_id=reply_to_message_id
            )

            res_text = None
            if also_send_text:
                res_text = self.send_message(text, chat_id=target_chat, reply_to_message_id=reply_to_message_id)

            return {
                "ok": res_voice.get("ok", False),
                "voice_result": res_voice,
                "text_result": res_text
            }

    def send_voice(
        self,
        voice: bytes | io.BytesIO | str | Path,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        duration: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Envía una nota de voz nativa (sendVoice) a Telegram con reproductor de audio integrado."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        voice_bytes = None
        if isinstance(voice, (str, Path)):
            p = Path(voice)
            if p.is_file():
                voice_bytes = p.read_bytes()
            else:
                return {"ok": False, "error": f"Archivo no encontrado: {voice}"}
        elif isinstance(voice, io.BytesIO):
            voice_bytes = voice.getvalue()
        elif isinstance(voice, bytes):
            voice_bytes = voice

        if not voice_bytes:
            return {"ok": False, "error": "Audio vacío"}

        # Convertir a OGG si no tiene cabecera OggS
        if not voice_bytes.startswith(b"OggS"):
            ogg_conv = self.convert_to_ogg(voice_bytes)
            if ogg_conv:
                voice_bytes = ogg_conv

        url = f"https://api.telegram.org/bot{token}/sendVoice"
        data: Dict[str, Any] = {"chat_id": target_chat}
        if caption:
            caption_trunc = caption[:1015] + "..." if len(caption) > 1020 else caption
            data["caption"] = caption_trunc
            data["parse_mode"] = "Markdown"
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if duration:
            data["duration"] = int(duration)
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

        files = {"voice": ("voice.ogg", voice_bytes, "audio/ogg")}

        # Visualizar despacho de nota de voz en la terminal local
        self._print_outgoing_response(target_chat, "🎙️ NOTA DE VOZ (OPUS OGG)", caption or "Nota de voz enviada")

        try:
            resp = requests.post(url, data=data, files=files, timeout=30.0)
            res_data = resp.json()
            if not res_data.get("ok") and caption and "parse_mode" in data:
                data.pop("parse_mode", None)
                files = {"voice": ("voice.ogg", voice_bytes, "audio/ogg")}
                res_data = requests.post(url, data=data, files=files, timeout=30.0).json()
            return res_data
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_video(
        self,
        video: bytes | io.BytesIO | str | Path,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        duration: Optional[int] = None,
        width: int = 480,
        height: int = 480,
        supports_streaming: bool = True,
        reply_markup: Optional[Dict[str, Any]] = None,
        message_thread_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Envía un video estándar (sendVideo) a Telegram con reproductor de video integrado y subtítulo."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        video_bytes = None
        if isinstance(video, (str, Path)):
            p = Path(video)
            if p.is_file():
                # MANDATO SOBERANO: Garantizar que todo video contenga audio/frecuencia/sonido
                try:
                    from core.tardis_audio_synthesizer import ensure_video_has_audio
                    ensure_video_has_audio(p, title=caption or p.stem)
                except Exception as _e_aud:
                    logger.warning(f"Error asegurando audio en video: {_e_aud}")
                video_bytes = p.read_bytes()
            else:
                return {"ok": False, "error": f"Archivo no encontrado: {video}"}
        elif isinstance(video, io.BytesIO):
            video_bytes = video.getvalue()
        elif isinstance(video, bytes):
            video_bytes = video

        if not video_bytes:
            return {"ok": False, "error": "Video vacío"}

        # Remuestrear video a 60 FPS si viene a mayor framerate (ej. 120 FPS)
        video_bytes = self.transcode_to_telegram_fps(video_bytes, target_fps=self.animation_telegram_fps)

        url = f"https://api.telegram.org/bot{token}/sendVideo"
        data: Dict[str, Any] = {
            "chat_id": target_chat,
            "width": int(width),
            "height": int(height),
            "supports_streaming": bool(supports_streaming)
        }
        if caption:
            caption_trunc = caption[:1015] + "..." if len(caption) > 1020 else caption
            data["caption"] = caption_trunc
            data["parse_mode"] = "Markdown"
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if duration:
            data["duration"] = int(duration)
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup
        if message_thread_id:
            data["message_thread_id"] = int(message_thread_id)

        files = {"video": ("speaking_system.mp4", video_bytes, "video/mp4")}

        self._print_outgoing_response(target_chat, "🎬 VIDEO DEL SISTEMA HABLANDO", caption or "Video de locución enviado")

        try:
            resp = requests.post(url, data=data, files=files, timeout=45.0)
            res_data = resp.json()
            if not res_data.get("ok") and caption and "parse_mode" in data:
                data.pop("parse_mode", None)
                files = {"video": ("speaking_system.mp4", video_bytes, "video/mp4")}
                res_data = requests.post(url, data=data, files=files, timeout=45.0).json()
            return res_data
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_video_note(
        self,
        video_note: bytes | io.BytesIO | str | Path,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        duration: Optional[int] = None,
        length: int = 480,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Envía un videomensaje circular nativo (sendVideoNote / telescopio) de Telegram."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        vn_bytes = None
        if isinstance(video_note, (str, Path)):
            p = Path(video_note)
            if p.is_file():
                # MANDATO SOBERANO: Garantizar que todo video contenga audio/frecuencia/sonido
                try:
                    from core.tardis_audio_synthesizer import ensure_video_has_audio
                    ensure_video_has_audio(p, title="Videonota TARDIS")
                except Exception as _e_aud:
                    logger.warning(f"Error asegurando audio en videonota: {_e_aud}")
                vn_bytes = p.read_bytes()
            else:
                return {"ok": False, "error": f"Archivo no encontrado: {video_note}"}
        elif isinstance(video_note, io.BytesIO):
            vn_bytes = video_note.getvalue()
        elif isinstance(video_note, bytes):
            vn_bytes = video_note

        if not vn_bytes:
            return {"ok": False, "error": "Videonota vacía"}

        url = f"https://api.telegram.org/bot{token}/sendVideoNote"
        data: Dict[str, Any] = {
            "chat_id": target_chat,
            "length": int(length)
        }
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if duration:
            data["duration"] = int(duration)
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

        files = {"video_note": ("video_note.mp4", vn_bytes, "video/mp4")}

        self._print_outgoing_response(target_chat, "📹 VIDEONOTA CIRCULAR (SISTEMA HABLANDO)", "Videonota redonda enviada")

        try:
            resp = requests.post(url, data=data, files=files, timeout=45.0)
            return resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_reply_with_video(
        self,
        text: str,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sintetiza la respuesta y renderiza un video dinámico del sistema hablando.
        Despacha exclusivamente el video a Telegram (sustituyendo texto plano y notas de voz).
        """
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat"}

        use_note = (self.video_delivery_type == "video_note")
        action = "record_video_note" if use_note else "upload_video"

        with ChatActionKeeper(self, target_chat, action):
            try:
                from core.speaking_video_generator import get_speaking_video_generator
                gen = get_speaking_video_generator()
                # Las videonotas se recortan en circulo y la API las limita a ~640 px:
                # solo el video estandar puede transportar el render en 4K.
                v_res = gen.generate_speaking_video(
                    text,
                    voice_id=self.config.get("cortana_voice"),
                    mode="note" if use_note else "uhd",
                )

                if v_res and v_res.get("ok") and v_res.get("video_bytes"):
                    dur = int(v_res.get("duration", 4))
                    # Si es videonota y dura <= 60s (límite API Telegram para video notes)
                    if use_note and dur <= 60:
                        res_send = self.send_video_note(
                            v_res["video_bytes"],
                            chat_id=target_chat,
                            reply_to_message_id=reply_to_message_id,
                            duration=dur
                        )
                        if res_send and res_send.get("ok"):
                            return {"ok": True, "type": "video_note", "result": res_send}
                        logger.warning(f"sendVideoNote falló ({res_send}), reintentando como sendVideo...")

                    # Enviar como video regular MP4 con subtítulo y telemetría viva de TARDIS
                    v_w = int(v_res.get("width") or 3840)
                    v_h = int(v_res.get("height") or 2160)
                    v_fps = int(v_res.get("fps") or 60)
                    res_txt = f"{v_w}x{v_h} · {v_fps} FPS"
                    telem_tag = ""
                    try:
                        from core.tardis_telemetry_snapshot import format_caption_telemetry
                        telem_tag = format_caption_telemetry(v_res.get("telemetry_summary"))
                    except Exception:
                        telem_tag = ""
                    header_meta = f"{res_txt} · {telem_tag}" if telem_tag else res_txt
                    vid_cap = caption or f"🎬 **TARDIS** · {header_meta}\n\n{text}"
                    res_send = self.send_video(
                        v_res["video_bytes"],
                        caption=vid_cap,
                        chat_id=target_chat,
                        reply_to_message_id=reply_to_message_id,
                        duration=dur,
                        width=v_w,
                        height=v_h,
                        supports_streaming=True,
                    )
                    return {"ok": True, "type": "video", "result": res_send}

                else:
                    logger.warning(f"Error generando video hablando: {v_res.get('error')}. Fallback a voz...")
            except Exception as e:
                logger.error(f"Excepción en send_reply_with_video: {e}. Fallback a voz...")

        # Fallback de seguridad en caso de falla crítica
        return self.send_reply_with_voice(text, chat_id=target_chat, reply_to_message_id=reply_to_message_id)
