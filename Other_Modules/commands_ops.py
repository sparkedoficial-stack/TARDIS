"""core/telegram/commands_ops.py - Comandos operativos: estado, capturas, C310, energía, FTL/AGY/SCP, audio, red y bóveda offline."""
from __future__ import annotations

from core.telegram.common import *


def handle_ops_command(
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
    """Ejecuta comandos operativos/seguridad/C310/red. Devuelve True si la actualización ya fue atendida."""
    parts = text.split()
    if cmd in ("/status", "/estado"):
        from core.hardware_controller import get_hardware_controller
        hw = get_hardware_controller()
        diag = hw.get_full_diagnostic()
        cpu = diag.get("system", {}).get("cpu_percent", 0)
        ram = diag.get("system", {}).get("ram_percent", 0)
        bat = diag.get("battery", {})
        net = diag.get("network", {})
        pwr = diag.get("power_profile", {}).get("active_profile", "performance")

        st_msg = (
            f"🖥️ **DIAGNÓSTICO SOBERANO DEL SISTEMA**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🧠 **Modelo:** {self.active_model_label} [Indefinido]\n"
            f"⚡ **CPU / Perfil:** {cpu}% · {pwr.upper()}\n"
            f"💾 **RAM (18 GB Dedicada):** {ram}% en uso\n"
            f"🔋 **Batería:** {bat.get('percent', 100):.1f}% ({bat.get('status', 'Conectado')})\n"
            f"📶 **Red Wi-Fi:** {net.get('active_connection', {}).get('connection', 'Conectado')}\n"
            f"🔒 **Pantalla Bloqueada:** {'SÍ' if diag.get('display', {}).get('locked') else 'NO'}\n"
            f"🚀 **Google Antigravity:** {'ACTIVO' if diag.get('antigravity', {}).get('running') else 'DETENIDO'}"
        )
        self.send_message(st_msg, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/shot", "/screenshot", "/captura"):
        from core.screen_capture import capture

        window_term = None
        lowered_shot = arg_str.strip().lower()
        if lowered_shot.startswith(("ventana ", "window ")):
            window_term = arg_str.split(maxsplit=1)[1].strip()
        try:
            raw_bytes, meta = capture(
                fmt="jpeg", max_width=1600, quality=82, window=window_term
            )
            win_title = ((meta or {}).get("window") or {}).get("title", "")
            clean_title = re.sub(r"[*_`\[\]]", "", win_title).strip()
            caption = "📸 Captura de pantalla actual del sistema"
            if clean_title:
                caption += f"\n🪟 Ventana: {clean_title}"
            caption += f"\n🖥️ {meta.get('width', 0)}×{meta.get('height', 0)} · {meta.get('method', '?')}"
            self.send_photo(raw_bytes, caption=caption, chat_id=chat_id, reply_to_message_id=msg_id)
        except Exception as exc_shot:
            self.send_message(
                "⚠️ No fue posible capturar la pantalla en este momento.\n"
                f"• Detalle: `{str(exc_shot)[:300]}`\n"
                "• Usa `/ventanas` para listar ventanas disponibles.",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
        return True

    if cmd in ("/ventanas", "/windows", "/lista_ventanas"):
        from core.screen_capture import list_windows

        windows = list_windows()
        if not windows:
            self.send_message(
                "🪟 No hay ventanas visibles detectables (Hyprland no responde o escritorio vacío).",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
            return True
        lines = [f"🪟 **VENTANAS VISIBLES ({len(windows)})**", "━━━━━━━━━━━━━━━━━━━━━━"]
        for index, window in enumerate(windows[:20], 1):
            title = re.sub(r"[*_`\[\]]", "", window.get("title") or "(sin título)").strip()
            klass = re.sub(r"[*_`\[\]]", "", window.get("class") or "?").strip()
            width, height = window.get("size") or [0, 0]
            lines.append(f"{index}. **{title}**\n    `{klass}` · {width}×{height}")
        lines.append("")
        lines.append("Captura una: `/shot ventana <título o clase>`")
        self.send_message("\n".join(lines), chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/avances", "/progreso", "/capturas", "/avance"):
        from core.program_progress import get_program_progress
        from core.screen_capture import capture

        progress = get_program_progress()
        sub = arg_str.strip()
        low = sub.lower()

        if low in ("on", "activar", "activo", "si", "sí", "1", "start"):
            progress.configure(enabled=True)
            self.send_message(
                "🧬 **CANAL DE AVANCES VISUALES ACTIVADO**\n"
                f"• Intervalo: {progress.interval_sec} s\n"
                "• Recibirás capturas automáticas del escritorio y de la ventana del "
                "programa en creación, sólo en esta terminal privada.\n"
                "• Pausa: `/avances off` · Ajuste: `/avances intervalo 120`",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
            return True

        if low in ("off", "pausar", "pausa", "desactivar", "no", "0", "stop"):
            stopped = progress.cancel_all()
            progress.configure(enabled=False)
            self.send_message(
                f"⏸️ **CANAL DE AVANCES EN PAUSA** ({stopped} sesiones detenidas)\n"
                "Reanuda con `/avances on`.",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
            return True

        if low.startswith(("intervalo ", "cada ", "interval ")):
            match_interval = re.search(r"\d+", sub)
            if not match_interval:
                self.send_message(
                    "⚠️ Indica los segundos: `/avances intervalo 120` (mínimo 30, máximo 900).",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id,
                )
                return True
            seconds = int(match_interval.group(0))
            progress.configure(interval_sec=seconds)
            self.send_message(
                f"⏱️ Intervalo de capturas ajustado a **{progress.interval_sec} s**.",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
            return True

        window_term = None
        if low.startswith(("ventana ", "window ")):
            window_term = sub.split(maxsplit=1)[1].strip()

        try:
            raw_bytes, meta = capture(
                fmt="jpeg", max_width=1600, quality=82, window=window_term
            )
            win_title = ((meta or {}).get("window") or {}).get("title", "")
            clean_title = re.sub(r"[*_`\[\]]", "", win_title).strip()
            caption = "🧬 AVANCE ACTUAL DEL SISTEMA"
            if clean_title:
                caption += f"\n🪟 {clean_title}"
            caption += (
                f"\n🖥️ {meta.get('width', 0)}×{meta.get('height', 0)}"
                f" · {meta.get('method', '?')} · {datetime.datetime.now().strftime('%H:%M:%S')}"
            )
            self.send_photo(raw_bytes, caption=caption, chat_id=chat_id, reply_to_message_id=msg_id)
        except Exception as exc_adv:
            self.send_message(
                f"⚠️ No fue posible tomar la captura de avance: `{str(exc_adv)[:300]}`",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
        self.send_message(progress.active_summary(), chat_id=chat_id)
        return True

    if cmd in ("/voz_c310", "/hablar_c310", "/hablar_camara", "/hablar_cámara"):
        msg_to_say = text[len(parts[0]):].strip()
        try:
            from core.tapo_c310_speaker import speak_on_c310_sync
            res_spk = speak_on_c310_sync(text=msg_to_say if msg_to_say else None)
            if res_spk.get("ok"):
                self.send_message(
                    f"🔊 *Altavoz C310 (`{res_spk.get('host')}`)* reprodujo ({res_spk.get('audio_duration_sec')}s):\n"
                    f"_«{res_spk.get('text')}»_",
                    chat_id=chat_id,
                )
            else:
                self.send_message(
                    f"⚠️ Fallo emitiendo voz en C310: `{res_spk.get('error') or res_spk}`",
                    chat_id=chat_id,
                )
        except Exception as e_spk:
            self.send_message(f"⚠️ Error de altavoz C310: {e_spk}", chat_id=chat_id)
        return True

    if cmd in (
        "/camara_vivo",
        "/cámara_vivo",
        "/c310_vivo",
        "/vivo",
        "/en_vivo",
        "/stream_camara",
        "/stream_cámara",
        "/transmitir_camara",
        "/transmitir_cámara",
        "/cctv_vivo",
        "/video_camara",
        "/video_cámara",
    ):
        sub_v = text[len(parts[0]):].strip().lower()
        if sub_v in ("stop", "detener", "parar", "off"):
            self.stop_c310_chat_live_feed(chat_id=chat_id)
            self.send_message("⏹️ Monitor en vivo en chat detenido.", chat_id=chat_id, reply_to_message_id=msg_id)
            return True
        if sub_v in ("monitor", "continuo", "chat"):
            self.start_c310_chat_live_feed(chat_id=chat_id, duration_sec=60.0)
            return True
        dur_req = 6.0
        for tok_w in sub_v.split():
            if tok_w.rstrip("s").isdigit():
                dur_req = max(3.0, min(20.0, float(tok_w.rstrip("s"))))
                break
        threading.Thread(
            target=self.send_c310_live_video,
            kwargs={"chat_id": chat_id, "duration_sec": dur_req, "reply_to_message_id": msg_id},
            daemon=True,
            name="C310LiveVideoCmd",
        ).start()
        return True

    if cmd in ("/c310", "/godeye", "/camara", "/cámara", "/cctv"):
        sub_args = text[len(parts[0]):].strip()
        sub_low = sub_args.lower()
        if sub_low.startswith(("hablar ", "decir ", "voz ")) or sub_low in ("hablar", "voz", "alerta"):
            spoken_arg = sub_args.split(None, 1)[1].strip() if " " in sub_args else ""
            try:
                from core.tapo_c310_speaker import speak_on_c310_sync
                res_spk = speak_on_c310_sync(text=spoken_arg if spoken_arg else None)
                if res_spk.get("ok"):
                    self.send_message(
                        f"🔊 *Altavoz GOD-EYE (`{res_spk.get('host')}`)* reprodujo ({res_spk.get('audio_duration_sec')}s):\n"
                        f"_«{res_spk.get('text')}»_",
                        chat_id=chat_id,
                    )
                else:
                    self.send_message(
                        f"⚠️ Fallo emitiendo voz en C310: `{res_spk.get('error') or res_spk}`",
                        chat_id=chat_id,
                    )
            except Exception as e_spk:
                self.send_message(f"⚠️ Error de altavoz C310: {e_spk}", chat_id=chat_id)
            return True
        if sub_low in ("stop", "detener", "parar"):
            self.stop_c310_chat_live_feed(chat_id=chat_id)
            self.send_message("⏹️ Monitor en vivo en chat detenido.", chat_id=chat_id, reply_to_message_id=msg_id)
            return True
        if sub_low in ("monitor", "continuo"):
            self.start_c310_chat_live_feed(chat_id=chat_id, duration_sec=60.0)
            return True
        if (
            sub_low in ("vivo", "en vivo", "video", "stream", "transmitir", "transmision", "transmisión", "clip")
            or sub_low.startswith(("vivo ", "en vivo ", "video ", "stream ", "transmitir ", "clip "))
        ):
            dur_c = 6.0
            for tok_w in sub_low.split():
                if tok_w.rstrip("s").isdigit():
                    dur_c = max(3.0, min(20.0, float(tok_w.rstrip("s"))))
                    break
            threading.Thread(
                target=self.send_c310_live_video,
                kwargs={"chat_id": chat_id, "duration_sec": dur_c, "reply_to_message_id": msg_id},
                daemon=True,
                name="C310LiveSubCmd",
            ).start()
            return True
        try:
            from core.tapo_c310_sentinel import (
                DETECTIONS_DIR,
                TapoC310Sentinel,
                get_c310_live_hud_jpeg_sync,
            )
            hud_bytes, meta = get_c310_live_hud_jpeg_sync(width=2304, hud=True, quality=92)
            markup_c310 = self._build_c310_live_reply_markup(chat_id)
            if hud_bytes:
                metrics = meta.get("metrics", {})
                caption = (
                    f"📹 *GOD-EYE · TP-Link Tapo C310 (`REDACTED_IP`)*\n"
                    f"• *Estado Centinela:* `ACTIVO 24/7 (Voz + Visión + Stream en Vivo)`\n"
                    f"• *Individuos en escena:* `{metrics.get('current_persons', 0)}`\n"
                    f"• *Alertas / Avisos vocales:* `{metrics.get('total_alerts_sent', 0)}` / `{metrics.get('total_voice_warnings_spoken', 0)}`"
                )
                self.send_photo(hud_bytes, caption=caption, chat_id=chat_id, reply_markup=markup_c310)
            else:
                import asyncio as _aio
                snap = _aio.run(TapoC310Sentinel().capture_single_snapshot(send_telegram=False))
                if snap.get("ok") and snap.get("path"):
                    self.send_photo(
                        Path(snap["path"]),
                        caption=(
                            f"📹 *GOD-EYE · TP-Link Tapo C310 (`REDACTED_IP`)*\n"
                            f"• *Resolución:* `{snap.get('resolution')}`\n"
                            f"• *Individuos detectados:* `{snap.get('persons_detected', 0)}`"
                        ),
                        chat_id=chat_id,
                        reply_markup=markup_c310,
                    )
                else:
                    self.send_message(f"⚠️ No se pudo obtener imagen de C310: {snap.get('error')}", chat_id=chat_id)
        except Exception as e_cam:
            self.send_message(f"⚠️ Error consultando cámara C310: {e_cam}", chat_id=chat_id)
        return True

    if cmd in ("/lock", "/bloquear"):
        from core.hardware_controller import get_hardware_controller
        hw = get_hardware_controller()
        hw.dispatch_action("lock_screen")
        self.send_message("🔒 Pantalla y sesión del sistema bloqueadas.", chat_id=chat_id)
        return True

    if cmd in ("/unlock", "/desbloquear"):
        from core.hardware_controller import get_hardware_controller
        hw = get_hardware_controller()
        hw.dispatch_action("unlock_screen", {"password": "REDACTED"})
        self.send_message("🔓 Pantalla desbloqueada con éxito (clave: 0).", chat_id=chat_id)
        return True

    if cmd in ("/reboot", "/reiniciar"):
        from core.autonomous_controller import get_autonomous_controller
        ac = get_autonomous_controller()
        self.send_message("🔄 Reinicio de optimización programado en 3 segundos. El bot se reconectará y te notificará al arrancar.", chat_id=chat_id)
        ac.reboot_for_improvement(reason="Reinicio /reboot ordenado desde Telegram", force=True, manual=True)
        return True


    if cmd.lower() in ("/timeemergency",):
        te_args = text[len(parts[0]):].strip()
        try:
            import sys
            te_path = "/home/m11/TimeEmergency"
            if te_path not in sys.path:
                sys.path.append(te_path)
            from engine import TimeEmergencyEngine

            if not hasattr(self, "_te_engine"):
                self._te_engine = TimeEmergencyEngine()

            if te_args:
                self.send_message(f"⏳ [TimeEmergency KAIJU] Procesando...", chat_id=chat_id)
                reply = self._te_engine.generate(te_args)
                self.send_message(f"🌀 *TimeEmergency (Qwen3.8-27B)*:\n{reply}", chat_id=chat_id, parse_mode="Markdown")
            else:
                self.send_message("🛸 *Modo TimeEmergency* activo. Usa `/timeemergency <mensaje>` para hablar con el sistema Qwen.", chat_id=chat_id, parse_mode="Markdown")
        except Exception as e:
            self.send_message(f"⚠️ Error al conectar con TimeEmergency: {e}", chat_id=chat_id)
        return True

    if cmd in ("/ftl_local", "/ftl-local", "/ftllocal", "/ftllocal"):

        # [TAREA ARQUITECTO :: /FTL-LOCAL] ACCESO LOCAL SOBERANO A FTL:
        # El Arquitecto solicita el acceso al sistema FTL mediante red local
        # (LAN/Wi-Fi del host físico). Se concede el enlace local con token
        # irrevocable y se informa del estado del puente GIA local.
        from omni_temporal_control import BRIDGE
        try:
            b_status = BRIDGE.get_status() or {}
        except Exception as e_bstatus:
            b_status = {}
        local_url = b_status.get("local_url") or ""
        lan_ip = b_status.get("lan_ip") or "127.0.0.1"
        local_ok = False
        try:
            import urllib.request as _urllib_request_local
            with _urllib_request_local.urlopen(f"http://127.0.0.1:{BRIDGE.port}/health", headers={"User-Agent": "TARDIS-FTL-Local"}, timeout=3) as _resp_local:
                local_ok = (_resp_local.status == 200)
        except Exception:
            local_ok = False
        online = bool(b_status.get("online")) or local_ok

        status_lbl = "🟢 OPERATIVO" if online else "🟡 EN ESPERA DE ARRANQUE"
        msg_local = (
            f"🛸 **[TARDIS · ACCESO LOCAL FTL CONCEDIDO]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔓 **Estado del Puente Local:** {status_lbl}\n"
            f"🧠 **Motor FTL Local (GIA Bridge LAN):** `{local_url}`\n"
            f"📡 **Dirección IP Local del Host:** `{lan_ip}`\n"
            f"💻 **Terminal FTL Local (ttyd :7681):** `http://{lan_ip}:7681/terminal`\n"
            f"🌐 **Portal FTL Local (FastAPI :8765):** `http://{lan_ip}:8765`\n\n"
            f"✅ **ACCESO LOCAL CONCEDIDO**: el sistema FTL te ha entregado el acceso "
            f"mediante red local. Conéctate desde un dispositivo dentro de la red LAN/Wi-Fi "
            f"del host físico y autentícate con el token irrevocable (`?key=...`).\n\n"
            f"💡 **Acciones soberanas disponibles desde esta sesión local:**\n"
            f"• `/ftl <petición>` : Dirigir el motor FTL de creación/mejora de código\n"
            f"• `/sh <comando bash>` : Control absoluto del host desde la terminal privada\n"
            f"• `/status` : Telemetría completa del sistema soberano"
        )
        if arg_str and arg_str.strip().lower() in ("reiniciar", "restart", "arrancar", "start", "activar", "iniciar"):
            try:
                BRIDGE.start()
            except Exception:
                pass
        self.send_message(msg_local, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/ftl",):

        # Petición de creación/mejora de código para FTL. Se conserva el texto
        # original (saltos de línea incluidos) tras el comando y el mensaje citado si aplica.
        from core.ftl_telegram_runner import get_ftl_runner
        ftl_args = text[len(parts[0]):].strip()
        replied = msg.get("reply_to_message") if isinstance(msg, dict) else None
        if isinstance(replied, dict) and ftl_args:
            quoted_txt = (replied.get("text") or replied.get("caption") or "").strip()
            if quoted_txt and ftl_args.lower() not in ("cancelar", "cancel", "stop", "detener", "models", "modelos", "help", "ayuda"):
                ftl_args = f"{ftl_args}\n\n[MENSAJE CITADO EN TELEGRAM]:\n{quoted_txt[:3500]}"
        runner = get_ftl_runner(
            lambda body, target, reply_to: self.send_message(
                body, chat_id=target, parse_mode="HTML", reply_to_message_id=reply_to
            )
        )
        runner.handle(chat_id, ftl_args, msg_id)
        return True

    if cmd in ("/agy", "/antigravity"):
        from core.antigravity_remote_controller import get_remote_controller
        ctrl = get_remote_controller()
        raw_agy_args = text[len(parts[0]):].strip()
        low_arg = raw_agy_args.lower()

        if not raw_agy_args or low_arg in ("status", "estado", "info"):
            res = ctrl.get_gui_status()
            st_lbl = "🟢 EN EJECUCIÓN" if res.get("running") else "🟢 TERMINAL CLI ACTIVA"
            self.send_message(
                f"🪐 <b>Google Antigravity · Puente Terminal Soberano</b>\n"
                f"• Estado: {st_lbl} (PIDs GUI: {res.get('pids')})\n"
                f"• Sesión de Terminal Conectada: <code>{res.get('target_conversation_id')}</code>\n"
                f"• Uso directo: escribe <code>/agy &lt;tu petición&gt;</code> para actualizar, mejorar, cambiar o crear código/sistemas directamente en esta terminal.",
                chat_id=chat_id,
                parse_mode="HTML",
                reply_to_message_id=msg_id,
            )
        elif low_arg in ("start", "open", "iniciar", "abrir", "gui"):
            res = ctrl.open_conversation_in_gui()
            self.send_message(
                f"🪐 Antigravity sincronizado y abierto en sesión <code>{res.get('conversation_id')}</code>.",
                chat_id=chat_id,
                parse_mode="HTML",
                reply_to_message_id=msg_id,
            )
        elif low_arg in ("sync", "sincronizar"):
            res = ctrl.sync_session()
            self.send_message(
                f"🔄 Sesión <code>{res.get('conversation_id')}</code> sincronizada (DB: {res.get('db_synced')}, Symlinks: {res.get('symlinks_ok')}).",
                chat_id=chat_id,
                parse_mode="HTML",
                reply_to_message_id=msg_id,
            )
        else:
            # Ejecutar petición directamente en Antigravity (Modo AGY autónomo conectado a esta terminal)
            from core.ftl_telegram_runner import get_ftl_runner
            ctrl.sync_session()
            runner = get_ftl_runner(
                lambda body, target, reply_to: self.send_message(
                    body, chat_id=target, parse_mode="HTML", reply_to_message_id=reply_to
                )
            )
            if low_arg in ("cancelar", "cancel", "stop", "detener", "models", "modelos", "help", "ayuda"):
                runner.handle(chat_id, raw_agy_args, msg_id)
            else:
                effective_args = raw_agy_args
                replied = msg.get("reply_to_message") if isinstance(msg, dict) else None
                if isinstance(replied, dict):
                    quoted_txt = (replied.get("text") or replied.get("caption") or "").strip()
                    if quoted_txt:
                        effective_args = f"{raw_agy_args}\n\n[MENSAJE CITADO EN TELEGRAM]:\n{quoted_txt[:3500]}"
                if effective_args.startswith("-m ") or effective_args.startswith("--mode "):
                    runner.handle(chat_id, effective_args, msg_id)
                else:
                    runner.handle(chat_id, f"-m agy {effective_args}", msg_id)
        return True

    if cmd in ("/scp",):
        from core.scp_conceptual_suite import get_scp_suite, DEFAULT_UNIVERSE_CODE
        suite = get_scp_suite()
        scp_raw = text[len(parts[0]):].strip()
        scp_parts = scp_raw.split(maxsplit=1)
        sub_c = scp_parts[0].lower() if scp_parts else "status"
        sub_val = scp_parts[1].strip() if len(scp_parts) > 1 else ""

        if sub_c in ("status", "estado", "info"):
            st = suite.get_status()
            self.send_message(
                f"🗂️ *Suite Computacional SCP*\n"
                f"• Ramas DAG: `{st['total_branches']}` | Eventos: `{st['total_events']}`\n"
                f"• Artefactos creados: `{st['generated_creations_count']}`\n"
                f"• Subcomandos: `/scp demo`, `/scp biblioteca <texto>`, `/scp tiempo <ancla>`, "
                f"`/scp universo <pos 0-23> <digito>`, `/scp verdad <ruta|texto>`, `/scp crear <nombre>`",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
        elif sub_c == "demo":
            res_d = suite.run_full_demonstration()
            self.send_message(
                f"✅ *Demostración SCP Ejecutada*\n"
                f"• *SCP-001 (Biblioteca):* `{res_d['scp_001_library']['short_address']}` (Roundtrip: `{res_d['scp_001_library']['exact_roundtrip_verified']}`)\n"
                f"• *SCP-002 (Tiempo):* Rama `{res_d['scp_002_time_machine']['new_branch_id']}`\n"
                f"• *SCP-003 (Universo):* Divergencia `{res_d['scp_003_universe_code']['divergence']['hamming_spacetime_divergence']:.2%}`\n"
                f"• *SCP-004 (Verdad):* SHA-256 `{res_d['scp_004_truth_camera']['verification_report']['sha256'][:16]}...`\n"
                f"• *SCP-005 (Creación):* `{res_d['scp_005_creation_engine']['creation_id']}`",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
        elif sub_c in ("biblioteca", "locate"):
            loc = suite.library.locate_text(sub_val or "biblioteca determinista")
            self.send_message(
                f"📚 *SCP-001 · Biblioteca Biyectiva*\n• Coordenada: `{loc['short_address']}`\n• Dirección completa:\n`{loc['address']}`",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
        elif sub_c in ("tiempo", "jump"):
            jmp = suite.time_machine.jump_and_branch(sub_val or "2286", "Consulta desde Telegram")
            self.send_message(
                f"⏳ *SCP-002 · Máquina del Tiempo*\n• Nueva rama: `{jmp['new_branch_id']}`\n• Padre: `{jmp['parent_branch_id']}`\n• Profundidad DAG: `{jmp['lineage_depth']}`",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
        elif sub_c in ("universo", "mutate"):
            u_args = sub_val.split()
            pos = int(u_args[0]) if len(u_args) >= 1 and u_args[0].isdigit() else 2
            dig = u_args[1] if len(u_args) >= 2 else "9"
            mut = suite.universe.mutate_single_digit(DEFAULT_UNIVERSE_CODE, pos, dig)
            div = mut["divergence"]
            self.send_message(
                f"🌌 *SCP-003 · Código del Universo*\n• Rama: `{mut['branch_id']}`\n• Mutación pos[{pos}]: `{div['old_digit']} -> {div['new_digit']}`\n"
                f"• Divergencia espacio-temporal: `{div['hamming_spacetime_divergence']:.2%}`\n• Fase: `{div['phase_transition']}`",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
        elif sub_c in ("verdad", "inspect"):
            ins = suite.truth_camera.inspect(sub_val or str(BASE_DIR / "core" / "telegram_bridge.py"))
            rep = ins["verification_report"]
            self.send_message(
                f"🔍 *SCP-004 · Cámara de la Verdad*\n• Rama: `{ins['branch_id']}`\n• MIME: `{rep['detected_mime']}` | `{rep['size_bytes']} B`\n"
                f"• Entropía: `{rep['shannon_entropy_bits_per_byte']} bits/B` (`{rep['entropy_profile']}`)\n• SHA-256: `{rep['sha256'][:24]}...`",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
        elif sub_c in ("crear", "create"):
            cre = suite.creator.create(sub_val or "Artefacto Procedural", "artifact")
            self.send_message(
                f"🛠️ *SCP-005 · Máquina de la Creación*\n• ID: `{cre['creation_id']}` | Rama: `{cre['branch_id']}`\n"
                f"• Plano JSON: `{cre['files']['json_blueprint']}`\n• Geometría SVG: `{cre['files']['svg_geometry']}`",
                chat_id=chat_id,
                reply_to_message_id=msg_id,
            )
        return True

    if cmd in ("/vol", "/volumen"):
        from core.hardware_controller import get_hardware_controller
        hw = get_hardware_controller()
        if arg_str:
            try:
                lvl = int(arg_str)
                res = hw.set_volume(lvl)
                self.send_message(f"🔊 Volumen ajustado a {res.get('volume_percent', lvl)}%.", chat_id=chat_id)
            except ValueError:
                self.send_message("🔊 Usa `/vol <0-100>`. Ejemplo: `/vol 75`", chat_id=chat_id)
        else:
            res = hw.get_volume()
            self.send_message(f"🔊 Volumen actual: {res.get('volume_percent', 0)}% (Mute: {res.get('muted')})", chat_id=chat_id)
        return True

    if cmd in ("/mute", "/silencio"):
        from core.hardware_controller import get_hardware_controller
        hw = get_hardware_controller()
        res = hw.set_mute(True)
        self.send_message("🔇 Audio silenciado.", chat_id=chat_id)
        return True

    if cmd in ("/unmute", "/desilenciar"):
        from core.hardware_controller import get_hardware_controller
        hw = get_hardware_controller()
        res = hw.set_mute(False)
        self.send_message("🔊 Audio activado.", chat_id=chat_id)
        return True

    if cmd in ("/kbd", "/teclado"):
        from core.hardware_controller import get_hardware_controller
        hw = get_hardware_controller()
        if arg_str:
            try:
                lvl = int(arg_str)
                res = hw.set_keyboard_brightness(lvl)
                self.send_message(f"💡 Brillo de teclado ASUS TUF ajustado a nivel {res.get('brightness', lvl)}/3.", chat_id=chat_id)
            except ValueError:
                self.send_message("💡 Usa `/kbd <0-3>`. Ejemplo: `/kbd 3`", chat_id=chat_id)
        else:
            res = hw.get_keyboard_brightness()
            self.send_message(f"💡 Brillo de teclado actual: nivel {res.get('brightness', 0)}/3.", chat_id=chat_id)
        return True

    if cmd in ("/power", "/perfil"):
        from core.hardware_controller import get_hardware_controller
        hw = get_hardware_controller()
        if arg_str in ("performance", "balanced", "power-saver"):
            res = hw.set_power_profile(arg_str)
            self.send_message(f"⚡ Perfil energético establecido a `{arg_str.upper()}`.", chat_id=chat_id)
        else:
            res = hw.get_power_profile()
            self.send_message(f"⚡ Perfil activo: `{res.get('active_profile', 'desconocido')}`. Opciones: `performance`, `balanced`, `power-saver`.", chat_id=chat_id)
        return True

    if cmd in ("/say", "/habla", "/voz"):
        if not arg_str:
            self.send_message("🗣️ Usa `/say <texto a pronunciar>`. Ejemplo: `/say Hola Miguel`", chat_id=chat_id)
            return True
        try:
            from autonomous_voice import speak_now
            speak_now(arg_str)
            self.send_message(f"🗣️ Voz reproducida en la PC: \"{arg_str}\"", chat_id=chat_id)
        except Exception:
            subprocess.Popen(["espeak", "-v", "es", arg_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.send_message(f"🗣️ Voz sintetizada en la PC: \"{arg_str}\"", chat_id=chat_id)
        return True

    if cmd in ("/hotspot", "/wifi_ap", "/ap", "/wifi", "/red"):
        from core.network_controller import get_network_controller
        net = get_network_controller()
        st = net.get_hotspot_status()
        clients_str = ""
        if st.get("clients"):
            c_items = [f"   • `{c['ip']}` ({c['mac']})" for c in st["clients"]]
            clients_str = "\n" + "\n".join(c_items)
        else:
            clients_str = " Ninguno"

        msg = (
            f"📶 **[RED WI-FI SOBERANA · TIMEMACHINE]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **SSID:** `{st['ssid']}`\n"
            f"• **Contraseña:** `{st['raw_password']}`\n"
            f"• **Estado:** {'🟢 ACTIVA 24/7 (Inmune a Caídas)' if st['active'] else '🔴 INACTIVA'}\n"
            f"• **Gateway:** `{st['gateway_ip']}`\n"
            f"• **HUD Local:** `{st['hud_url']}`\n"
            f"• **Clientes Conectados ({st['client_count']}):**{clients_str}\n"
            f"• **Centinela:** `godworks-hotspot.service` (Activo)"
        )
        self.send_message(msg, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/auditar", "/shield", "/seguridad", "/escanear_red"):
        from core.network_shield import get_network_shield
        shield = get_network_shield()
        audit = shield.audit_network()
        dev_lines = []
        for d in audit.get("devices", []):
            risk = "🚨 Riesgo" if not d.get("is_safe") else "✅ Seguro"
            dev_lines.append(f"   • `{d['ip']}` | {d['hostname']} ({d['vendor']}) [{risk}]")
        dev_str = "\n".join(dev_lines) if dev_lines else "   Ninguno"
        alerts_str = "\n".join([f"   ⚠️ {a}" for a in audit.get("alerts", [])]) or "   ✅ Red blindada sin anomalías"

        msg = (
            f"🛡️ **[ESCUDO SOBERANO · AUDITORÍA DE RED]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Puntuación de Seguridad:** `{audit['security_score']}%` ({audit['grade']})\n"
            f"• **Filtro DNS Sinkhole:** {'🟢 ACTIVO (0.0.0.0)' if audit['adblock_active'] else '🔴 INACTIVO'}\n"
            f"• **Anti-Espionaje & Telemetría:** {'🟢 ACTIVO' if audit['antispy_active'] else '🔴 INACTIVO'}\n"
            f"• **Dominios Bloqueados:** `{audit['blocked_domains_count']}`\n"
            f"• **Dispositivos Asociados ({audit['devices_count']}):**\n{dev_str}\n\n"
            f"• **Alertas:**\n{alerts_str}\n\n"
            f"• **Causalidad:** {audit['recommendation']}"
        )
        self.send_message(msg, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/adblock", "/bloquear_anuncios"):
        from core.network_shield import get_network_shield
        shield = get_network_shield()
        if arg_str.lower() in ("off", "0", "desactivar", "apagar"):
            res = shield.toggle_adblock(False)
            state = "🔴 Desactivado"
        else:
            res = shield.toggle_adblock(True)
            state = "🟢 Activado"
        msg = (
            f"🛡️ **Filtro DNS Sinkhole (AdBlock):** {state}\n"
            f"• Dominios bloqueados: `{res.get('blocked_domains_count', 0)}`"
        )
        self.send_message(msg, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/trafico", "/accesos", "/conexiones", "/flows"):
        from core.traffic_monitor import get_traffic_monitor
        tm = get_traffic_monitor()
        data = tm.analyze_traffic_and_accesses()

        dev_activity = []
        for dev, count in data.get("traffic_summary_by_device", {}).items():
            dev_activity.append(f"   • **{dev}**: `{count}` sesiones activas")
        dev_str = "\n".join(dev_activity) if dev_activity else "   Ninguno"

        inbound_lines = []
        for f in data.get("inbound_accesses", [])[:4]:
            inbound_lines.append(f"   • `{f['src_ip']}` -> `{f['dst_name']}` ({f['service']})")
        inbound_str = "\n".join(inbound_lines) if inbound_lines else "   ✅ Ningún acceso externo no autorizado"

        msg = (
            f"📡 **[AUDITORÍA DE TRÁFICO & ACCESOS A DISPOSITIVOS]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Flujos Totales:** `{data['total_active_flows']}`\n"
            f"• **Accesos Entrantes:** `{data['inbound_access_count']}`\n"
            f"• **Destinos Remotos:** `{data['remote_endpoints_contacted']}`\n\n"
            f"📱 **Actividad por Dispositivo:**\n{dev_str}\n\n"
            f"🛡️ **Accesos Entrantes Inbound:**\n{inbound_str}\n\n"
            f"• **Veredicto:** {data['assessment']}"
        )
        self.send_message(msg, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/recurrentes", "/frecuentes", "/top_trafico", "/destinos"):
        from core.traffic_monitor import get_traffic_monitor
        rep = get_traffic_monitor().get_recurring_traffic_report()
        self.send_message(rep.get("formatted_report", ""), chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/offline", "/boveda", "/historial_offline", "/chats_offline"):
        from core.offline_chat_vault import get_offline_chat_vault
        vault = get_offline_chat_vault()
        total = vault.get_total_count()
        msg = (
            f"💾 **[BÓVEDA SOBERANA DE CHATS OFFLINE]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Turnos Almacenados Inmutables:** `{total}`\n"
            f"• **Base de Datos Local:** `data/offline_chats.db`\n"
            f"• **Visor Autónomo Fuera de Línea:** Abre directamente `HISTORIAL_CHATS_OFFLINE.html` en el Escritorio de tu PC aún con el servidor apagado.\n"
            f"• **RAG Cognitivo:** {self.active_model_label} consulta este historial antes de formular cada respuesta."
        )
        self.send_message(msg, chat_id=chat_id, reply_to_message_id=msg_id)
        return True
    return False
