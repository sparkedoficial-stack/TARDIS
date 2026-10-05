"""
core/whatsapp_bridge.py - Puente Soberano de WhatsApp para GODWORKS SYSTEM v26.4
================================================================================
Permite la interacción total y bidireccional con el sistema a través de WhatsApp:
  1. Integración oficial con Meta WhatsApp Business Cloud API (v21.0).
  2. Webhook compatible con túnel Cloudflare o URL pública fija.
  3. Verificación criptográfica HMAC-SHA256 (X-Hub-Signature-256).
  4. Conversación autónoma con el modelo central Hermes 3 (8B) vía process_agentic_chat.
  5. Sincronización transversal de contexto en SYNC_HUB con la PC y terminales.
  6. Comandos de control de hardware y terminal Linux (/sh, /status, /shot, /lock, /link).
  7. Auto-vinculación segura mediante clave maestra ("0" o "DiosDelTiempo01").
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import io
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

CONFIG_FILE = BASE_DIR / "whatsapp_config.json"
logger = logging.getLogger("WhatsAppBridge")

GRAPH_BASE = "https://graph.facebook.com"
DEFAULT_GRAPH_VERSION = "v21.0"

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "provider": "meta",
    "bot_name": "GIA",
    "phone_number_id": "",
    "access_token": "",
    "verify_token": "DiosDelTiempo01",
    "app_secret": "",
    "allowed_numbers": [],
    "admin_number": "",
    "master_password": "0",
    "master_key": "DiosDelTiempo01",
    "notify_on_boot": True,
    "graph_version": DEFAULT_GRAPH_VERSION,
}


def _digits(s: str) -> str:
    """Extrae únicamente los dígitos de una cadena telefónica."""
    return re.sub(r"\D", "", s or "")


class WhatsAppBridge:
    """Gestor soberano de integración y supervisión de WhatsApp Cloud API."""

    _instance: Optional[WhatsAppBridge] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, config_path: Optional[Path | str] = None) -> WhatsAppBridge:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config_path=config_path)
            return cls._instance

    def __init__(self, config_path: Optional[Path | str] = None):
        self.config_path = Path(config_path) if config_path else CONFIG_FILE
        self.config = self._load_config()
        self.pairing_passwords = ["0", "DiosDelTiempo01"]
        self.messages_processed = 0
        self.last_error: Optional[str] = None
        self._executor_lock = threading.Lock()

    @property
    def active_model_label(self) -> str:
        act = os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated")
        if "dolphin" in act.lower():
            return "Dolphin 3.0 (8B)"
        return act

    # --------------------------------------------------------------------------
    # CONFIGURACIÓN Y PERSISTENCIA
    # --------------------------------------------------------------------------

    def _load_config(self) -> Dict[str, Any]:
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        # Variables de entorno prioritarias
        env_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
        if env_token:
            cfg["access_token"] = env_token
        env_pnid = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        if env_pnid:
            cfg["phone_number_id"] = env_pnid
        env_verify = os.environ.get("WHATSAPP_VERIFY_TOKEN", "").strip()
        if env_verify:
            cfg["verify_token"] = env_verify

        if getattr(self, "config_path", None) and self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                cfg.update(data)
            except Exception as e:
                logger.error(f"Error cargando {self.config_path}: {e}")

        # Normalizar allowed_numbers a lista de strings sólo con dígitos
        norm_allowed = []
        for n in cfg.get("allowed_numbers", []):
            d = _digits(str(n))
            if d and d not in norm_allowed:
                norm_allowed.append(d)
        cfg["allowed_numbers"] = norm_allowed
        return cfg

    def save_config(self) -> bool:
        try:
            target = getattr(self, "config_path", None) or CONFIG_FILE
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(self.config, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except Exception as e:
            self.last_error = f"Error guardando configuración: {e}"
            return False

    def update_config(self, new_cfg: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            # Procesar allowed_numbers si viene como string o lista
            if "allowed_numbers" in new_cfg:
                val = new_cfg["allowed_numbers"]
                if isinstance(val, str):
                    numbers = [_digits(n) for n in re.split(r"[,\n;]+", val) if _digits(n)]
                elif isinstance(val, list):
                    numbers = [_digits(str(n)) for n in val if _digits(str(n))]
                else:
                    numbers = []
                new_cfg["allowed_numbers"] = list(dict.fromkeys(numbers))

            self.config.update(new_cfg)
            self.save_config()
            return self.get_status()

    # --------------------------------------------------------------------------
    # AUTORIZACIÓN Y VINCULACIÓN
    # --------------------------------------------------------------------------

    @property
    def authorized_numbers(self) -> set:
        class _NumberSet(set):
            def __init__(outer_self, bridge):
                super().__init__(bridge.config.get("allowed_numbers", []))
                outer_self._bridge = bridge

            def add(outer_self, item):
                super().add(_digits(str(item)))
                outer_self._bridge.authorize_number(item)

            def remove(outer_self, item):
                d = _digits(str(item))
                super().discard(d)
                allowed = outer_self._bridge.config.setdefault("allowed_numbers", [])
                if d in allowed:
                    allowed.remove(d)
                outer_self._bridge.save_config()

        return _NumberSet(self)

    def authorize_number(self, phone_number: str | int):
        num_clean = _digits(str(phone_number))
        if not num_clean:
            return
        allowed = self.config.setdefault("allowed_numbers", [])
        if num_clean not in allowed:
            allowed.append(num_clean)
        self.config["admin_number"] = num_clean
        self.save_config()

    def is_number_authorized(self, phone_number: str | int) -> bool:
        num_clean = _digits(str(phone_number))
        if not num_clean:
            return False
        allowed = self.config.get("allowed_numbers", [])
        if not allowed:
            return False
        return num_clean in allowed

    # --------------------------------------------------------------------------
    # VERIFICACIÓN DE WEBHOOK & SEGURIDAD (META CLOUD API)
    # --------------------------------------------------------------------------

    def verify_challenge(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Handshake de suscripción del webhook GET. Devuelve challenge si OK."""
        expected_token = self.config.get("verify_token", "DiosDelTiempo01")
        if mode == "subscribe" and token and token == expected_token:
            return challenge
        return None

    def verify_webhook_token(self, token: str) -> bool:
        """Helper compatible con comprobaciones booleanas simples."""
        expected = self.config.get("verify_token", "DiosDelTiempo01")
        return bool(token and token == expected)

    def verify_signature(self, raw_body: bytes, header: Optional[str]) -> bool:
        """Verifica la cabecera X-Hub-Signature-256 (HMAC-SHA256 con app_secret)."""
        secret = self.config.get("app_secret", "").strip()
        if not secret:
            # Si no se configuró app_secret, se acepta la solicitud
            return True
        if not header or not header.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        received = header.split("=", 1)[1]
        return hmac.compare_digest(expected, received)

    # --------------------------------------------------------------------------
    # ENVÍO DE MENSAJES (GRAPH API)
    # --------------------------------------------------------------------------

    def send_message(self, to: str, text: str) -> Dict[str, Any]:
        """Envía un mensaje de texto por WhatsApp a través de Meta Cloud API."""
        token = self.config.get("access_token", "").strip()
        pnid = self.config.get("phone_number_id", "").strip()
        target = _digits(to)

        if not (token and pnid):
            return {"ok": False, "error": "WhatsApp no configurado (falta access_token o phone_number_id)"}
        if not target:
            return {"ok": False, "error": "Número de destinatario no válido"}

        version = self.config.get("graph_version", DEFAULT_GRAPH_VERSION)
        url = f"{GRAPH_BASE}/{version}/{pnid}/messages"

        # WhatsApp limita el texto a ~4096 caracteres
        payload = {
            "messaging_product": "whatsapp",
            "to": target,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": (text or "")[:4000] or "(sin texto)"
            }
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=15.0
            )
            ok = resp.status_code in (200, 201)
            resp_data = resp.json() if resp.content else {}
            if not ok:
                self.last_error = f"HTTP {resp.status_code}: {resp_data.get('error', {}).get('message', 'Error Graph API')}"
            return {"ok": ok, "status": resp.status_code, "resp": resp_data}
        except Exception as e:
            self.last_error = f"Error de conexión Graph API: {e}"
            return {"ok": False, "error": str(e)}

    # --------------------------------------------------------------------------
    # RECEPCIÓN Y DESPACHO DE MENSAJES ENTRANTES
    # --------------------------------------------------------------------------

    def handle_incoming_webhook(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Alias para el procesador de webhooks entrantes."""
        return self.handle_incoming(payload)

    def handle_incoming(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Procesa el payload estándar de Meta WhatsApp Webhook."""
        results = []
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    # Extraer metadatos de contactos si vienen
                    contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "Usuario") for c in value.get("contacts", [])}

                    for msg in value.get("messages", []):
                        sender = _digits(msg.get("from", ""))
                        sender_name = contacts.get(sender, "Usuario")
                        msg_type = msg.get("type", "")

                        if msg_type == "text":
                            text = (msg.get("text", {}) or {}).get("body", "").strip()
                            res = self._handle_incoming_text(sender, text, sender_name)
                            results.append(res)
                        else:
                            # Notificar tipo de contenido no soportado amablemente
                            self.send_message(
                                sender,
                                f"📎 Recibí un elemento de tipo '{msg_type}'. Por el momento interactúo mediante directivas de texto y comandos."
                            )
                            results.append({"sender": sender, "type": msg_type, "handled": False})
        except Exception as e:
            logger.error(f"Error procesando webhook de WhatsApp: {e}")
            results.append({"error": str(e)})
        return results

    def _handle_incoming_text(self, sender: str, text: str, sender_name: str = "Usuario") -> Dict[str, Any]:
        """Procesa texto entrante, ejecuta autenticación, comandos o inferencia con Hermes 3."""
        if not text or not sender:
            return {"ok": False, "error": "Texto o remitente vacío"}

        self.messages_processed += 1
        allowed = self.config.get("allowed_numbers", [])

        # Autenticación y vinculación por clave maestra
        if not self.is_number_authorized(sender):
            if text in (self.config.get("master_password"), self.config.get("master_key"), "0", "DiosDelTiempo01"):
                self.authorize_number(sender)
                reply = (
                    "👑 *¡ACCESO SOBERANO CONCEDIDO POR WHATSAPP!*\n\n"
                    f"Bienvenido, {sender_name}. Tu número (+{sender}) ha sido vinculado como nodo soberano de *GODWORKS SYSTEM v26.4*.\n\n"
                    "• Control de hardware y terminal habilitado.\n"
                    f"• Cerebro Central: *{self.active_model_label}*.\n"
                    "• Escribe `/start` para consultar los comandos o háblame directamente."
                )
                self.send_message(sender, reply)
                return {"ok": True, "authorized": True, "sender": sender}
            elif not allowed:
                # Si no hay ningún número registrado aún en el sistema
                reply = (
                    "🔒 *AUTENTICACIÓN REQUERIDA · GODWORKS SYSTEM*\n\n"
                    f"Hola {sender_name}. Para vincular tu número de WhatsApp con el nodo central, ingresa la clave maestra del sistema (clave: `0` o `DiosDelTiempo01`)."
                )
                self.send_message(sender, reply)
                return {"ok": False, "authorized": False, "reason": "unauthenticated"}
            else:
                reply = "🔒 *ACCESO NO AUTORIZADO*: Introduce la clave maestra del sistema (clave: `0`) para vincular este número."
                self.send_message(sender, reply)
                return {"ok": False, "authorized": False, "reason": "unauthorized"}

        # ----------------------------------------------------------------------
        # COMANDOS SOBERANOS DE WHATSAPP (/start, /sh, /status, /shot, etc.)
        # ----------------------------------------------------------------------
        parts = text.split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        arg_str = " ".join(args).strip()

        if cmd in ("/start", "/help", "/ayuda"):
            help_msg = (
                f"👑 *GODWORKS SYSTEM v26.4 · WHATSAPP SOBERANO*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧠 *Cerebro Central:* {self.active_model_label} [Fijado Indefinido]\n"
                f"📱 *Usuario:* {sender_name} (+{sender})\n\n"
                f"*🎮 Comandos de Control Maestro:*\n"
                f"• `/link` o `/qr` : Enlace web activo y portal permanente\n"
                f"• `/sh <cmd>` : Ejecutar comando en terminal Linux\n"
                f"• `/status` : Telemetría completa (CPU, 18GB RAM, batería, Wi-Fi)\n"
                f"• `/shot` : Tomar captura de pantalla de la PC\n"
                f"• `/lock` / `/unlock` : Bloquear / Desbloquear pantalla (clave 0)\n"
                f"• `/vol <0-100>` : Ajustar volumen de la laptop\n"
                f"• `/mute` / `/unmute` : Silenciar o activar audio\n"
                f"• `/say <texto>` : Síntesis de voz hablada en los altavoces\n"
                f"• `/reboot` : Reiniciar el equipo para auto-mejora\n\n"
                f"💬 *También puedes escribir cualquier directiva o pregunta libremente. {self.active_model_label} responderá con memoria compartida con tu PC.*"
            )
            self.send_message(sender, help_msg)
            return {"ok": True, "command": cmd, "sender": sender}

        if cmd in ("/link", "/enlace", "/qr", "/portal"):
            try:
                from omni_temporal_control import BRIDGE
                b_status = BRIDGE.get_status()
                auth_url = b_status.get("auth_url", "")
                local_url = b_status.get("local_url", "")
            except Exception:
                auth_url = "https://harper-skins-donation-frost.trycloudflare.com/?key=DiosDelTiempo01"
                local_url = "http://REDACTED_IP:8757"

            perm_url = "https://ntfy.sh/godworks_sovereign_timemachine_portal"
            msg_link = (
                f"🌐 *ENLACE Y ACCESO PERMANENTE A GODWORKS*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔗 *Enlace Remoto Mundial:*\n{auth_url}\n\n"
                f"🏛️ *Portal Invariable Permanente:*\n{perm_url}\n\n"
                f"📶 *Red Local Wi-Fi:*\n`{local_url}`\n\n"
                f"🔑 *Clave Maestra:* `DiosDelTiempo01`"
            )
            self.send_message(sender, msg_link)
            return {"ok": True, "command": cmd, "sender": sender}

        if cmd in ("/sh", "/bash", "/cmd", "/terminal"):
            if not arg_str:
                self.send_message(sender, "💻 Especifica el comando a ejecutar. Ejemplo: `/sh uname -a` o `/sh free -h`")
                return {"ok": False, "error": "missing_arg"}

            try:
                from core.os_controller import get_os_controller
                os_c = get_os_controller()
                res = os_c.execute_terminal_command(arg_str, timeout=35.0)
                out = res.get("stdout", "").strip()
                err = res.get("stderr", "").strip()
                rc = res.get("returncode", 0)
                elapsed = res.get("elapsed_s", 0.0)

                body_out = []
                if out:
                    body_out.append(out)
                if err:
                    body_out.append(f"[stderr]\n{err}")
                res_str = "\n".join(body_out) if body_out else "(Sin salida estándar)"
                if len(res_str) > 3500:
                    res_str = res_str[:3500] + "\n... [Salida truncada]"

                reply = (
                    f"💻 *Terminal Linux (`{arg_str}`)*\n"
                    f"• Código: `{rc}` | Tiempo: `{elapsed}s`\n"
                    f"```\n{res_str}\n```"
                )
            except Exception as e:
                reply = f"⚠️ Error ejecutando comando en terminal: {e}"

            self.send_message(sender, reply)
            return {"ok": True, "command": cmd, "sender": sender}

        if cmd in ("/status", "/estado"):
            try:
                from core.hardware_controller import get_hardware_controller
                hw = get_hardware_controller()
                diag = hw.get_full_diagnostic()
                cpu = diag.get("system", {}).get("cpu_percent", 0)
                ram = diag.get("system", {}).get("ram_percent", 0)
                bat = diag.get("battery", {})
                net = diag.get("network", {})
                pwr = diag.get("power_profile", {}).get("active_profile", "performance")

                st_msg = (
                    f"🖥️ *DIAGNÓSTICO SOBERANO DEL SISTEMA*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🧠 *Modelo:* {self.active_model_label} [Indefinido]\n"
                    f"⚡ *CPU / Perfil:* {cpu}% · {pwr.upper()}\n"
                    f"💾 *RAM (18 GB Dedicada):* {ram}% en uso\n"
                    f"🔋 *Batería:* {bat.get('percent', 100):.1f}% ({bat.get('status', 'Conectado')})\n"
                    f"📶 *Red Wi-Fi:* {net.get('active_connection', {}).get('connection', 'Conectado')}\n"
                    f"🔒 *Pantalla Bloqueada:* {'SÍ' if diag.get('display', {}).get('locked') else 'NO'}"
                )
            except Exception as e:
                st_msg = f"⚠️ Diagnóstico de hardware no disponible: {e}"

            self.send_message(sender, st_msg)
            return {"ok": True, "command": cmd, "sender": sender}

        if cmd in ("/lock", "/bloquear"):
            try:
                from core.hardware_controller import get_hardware_controller
                get_hardware_controller().dispatch_action("lock_screen")
                self.send_message(sender, "🔒 Pantalla y sesión del sistema bloqueadas.")
            except Exception as e:
                self.send_message(sender, f"⚠️ Error bloqueando pantalla: {e}")
            return {"ok": True, "command": cmd, "sender": sender}

        if cmd in ("/unlock", "/desbloquear"):
            try:
                from core.hardware_controller import get_hardware_controller
                get_hardware_controller().dispatch_action("unlock_screen", {"password": "0"})
                self.send_message(sender, "🔓 Pantalla desbloqueada con clave soberana.")
            except Exception as e:
                self.send_message(sender, f"⚠️ Error desbloqueando pantalla: {e}")
            return {"ok": True, "command": cmd, "sender": sender}

        if cmd in ("/say", "/habla", "/voz"):
            if not arg_str:
                self.send_message(sender, "🗣️ Usa `/say <texto>`. Ejemplo: `/say Hola Miguel`")
                return {"ok": False, "error": "missing_text"}
            try:
                from autonomous_voice import speak_now
                speak_now(arg_str)
                self.send_message(sender, f"🗣️ Voz reproducida en la PC: \"{arg_str}\"")
            except Exception:
                import subprocess
                subprocess.Popen(["espeak", "-v", "es", arg_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.send_message(sender, f"🗣️ Voz sintetizada en la PC: \"{arg_str}\"")
            return {"ok": True, "command": cmd, "sender": sender}

        # ----------------------------------------------------------------------
        # ENRUTADO A HERMES 3 (8B) CON SINCRONIZACIÓN TRANSVERSAL
        # ----------------------------------------------------------------------
        try:
            from omni_temporal_control import SYNC_HUB, process_agentic_chat

            SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: WhatsApp [+{sender}]")

            with SYNC_HUB._lock:
                chat_hist = [
                    {"role": m["role"], "content": m["content"]}
                    for m in SYNC_HUB.history
                    if m.get("role") in ("user", "assistant") and m.get("content")
                ]

            resp_chat = process_agentic_chat(
                message=text,
                history=chat_hist[-12:],
                model=os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated"),
                num_ctx=4096,
                use_web=True
            )

            hermes_reply = resp_chat.get("reply", "Directiva procesada.").strip()
            SYNC_HUB.add_chat_turn("assistant", hermes_reply, meta=f"{self.active_model_label} · WhatsApp")
            self.send_message(sender, hermes_reply)
            return {"ok": True, "reply": hermes_reply, "sender": sender}

        except Exception as e:
            logger.error(f"Error procesando mensaje en WhatsApp con Hermes 3: {e}")
            fallback_reply = f"No pude completar la inferencia con el modelo soberano: {e}"
            self.send_message(sender, fallback_reply)
            return {"ok": False, "error": str(e), "sender": sender}

    # --------------------------------------------------------------------------
    # ESTADO Y DIAGNÓSTICO
    # --------------------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.config.get("access_token") and self.config.get("phone_number_id"))

    def get_status(self) -> Dict[str, Any]:
        configured = self.is_configured()
        token = self.config.get("access_token", "")
        hint_token = (token[:6] + "..." + token[-4:]) if len(token) > 10 else ("configurado" if token else "")
        allowed = self.config.get("allowed_numbers", [])

        # URL pública estimada del webhook
        pub = ""
        try:
            from omni_temporal_control import BRIDGE
            if getattr(BRIDGE, "public_url", None):
                pub = BRIDGE.public_url.rstrip("/")
        except Exception:
            pass

        if not pub:
            url_file = BASE_DIR / "CURRENT_TUNNEL_URL.txt"
            if url_file.exists():
                try:
                    raw_url = url_file.read_text(encoding="utf-8").strip()
                    if raw_url:
                        # Limpiar parámetros como ?key=...
                        pub = raw_url.split("?")[0].rstrip("/")
                except Exception:
                    pass

        webhook_url = f"{pub}/whatsapp/webhook" if pub else "/whatsapp/webhook"

        return {
            "ok": True,
            "enabled": bool(self.config.get("enabled", True)),
            "configured": configured,
            "provider": self.config.get("provider", "meta"),
            "phone_number_id": self.config.get("phone_number_id", ""),
            "access_token": hint_token,
            "verify_token": self.config.get("verify_token", "DiosDelTiempo01"),
            "app_secret_set": bool(self.config.get("app_secret")),
            "allowed_numbers": allowed,
            "authorized_numbers_count": len(allowed),
            "admin_number": self.config.get("admin_number", ""),
            "messages_processed": self.messages_processed,
            "webhook_url": webhook_url,
            "last_error": self.last_error,
        }


def get_whatsapp_bridge() -> WhatsAppBridge:
    return WhatsAppBridge.get_instance()
