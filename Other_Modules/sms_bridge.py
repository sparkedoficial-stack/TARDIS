"""
core/sms_bridge.py - Puente Soberano de Mensajería SMS para GODWORKS SYSTEM v26.4
==================================================================================
GODWORKS SYSTEM & TARDIS Ecosystem

Proporciona capacidades integrales para el envío de mensajes de texto SMS:
1. Multi-proveedor resiliente:
   - Twilio (API oficial global de alta entrega)
   - Gateway Android / Termux / Local Relay (para enviar SMS gratis desde la SIM del celular)
   - Textbelt (API HTTP con clave de desarrollador o prepago)
   - Custom Webhook (compatible con cualquier pasarela SMS empresarial o privada)
   - Modem GSM / LTE local (vía mmcli / ModemManager o puerto serial AT /dev/ttyUSB*)
   - Email-to-SMS Gateway (pasarelas carrier sin costo: Telcel, Movistar, AT&T, etc.)
2. Normalización de números telefónicos internacionales (autocorrección con prefijo +52).
3. Registro de auditoría forense local en 'data/sms_audit.log' e historial en 'data/sms_history.json'.
4. Detección y ejecución automática de intenciones SMS en lenguaje natural.
5. Integración con el bot de Telegram (/sms <número> <mensaje>) y API REST (/api/sms/send).
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import smtplib
import subprocess
import sys
import threading
import time
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger("godworks.sms_bridge")

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "sms_config.json"
DATA_DIR = BASE_DIR / "data"
AUDIT_LOG = DATA_DIR / "sms_audit.log"
HISTORY_FILE = DATA_DIR / "sms_history.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "default_provider": "auto",
    "default_country_prefix": "+52",
    "tardis_pocket": {
        "enabled": True,
        "priority": 1,
        "serial": "ZY222ZXWPP",
        "host": "REDACTED_IP",
        "port": 8080,
    },
    "twilio": {
        "account_sid": "",
        "auth_token": "",
        "from_number": "",
    },
    "textbelt": {
        "api_key": "textbelt",
    },
    "android_gateway": {
        "url": "",
        "token": "",
    },
    "custom_webhook": {
        "url": "",
        "auth_header": "",
        "auth_token": "",
        "payload_template": "json",
    },
    "email_gateway": {
        "enabled": False,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_pass": "",
        "carrier": "telcel",
    },
    "modem": {
        "enabled": True,
        "device": "",
        "mmcli_modem_index": 0,
    },
    "allowed_numbers": [],
    "rate_limit_per_hour": 30,
}

CARRIER_GATEWAYS: Dict[str, str] = {
    "telcel": "{number}@itelcel.com",
    "movistar": "{number}@movistar.com.mx",
    "att_mx": "{number}@sms.att.com.mx",
    "att_us": "{number}@txt.att.net",
    "verizon": "{number}@vtext.com",
    "tmobile": "{number}@tmomail.net",
    "claro": "{number}@clarotorpedo.com.br",
}


def normalize_phone_number(raw: str, default_prefix: str = "+52") -> str:
    """Limpia y estandariza un número telefónico en formato E.164 (+<código><número>)."""
    clean = re.sub(r"[^\d+]", "", raw.strip())
    if clean.startswith("+"):
        return clean
    digits = re.sub(r"\D", "", clean)
    prefix = default_prefix.lstrip("+")
    if len(digits) == 10:
        return f"+{prefix}{digits}"
    elif len(digits) == 12 and digits.startswith(prefix):
        return f"+{digits}"
    elif len(digits) == 13 and digits.startswith(prefix + "1"):  # Formato móvil México histórico +521
        return f"+{prefix}{digits[3:]}"
    return f"+{digits}" if digits else clean


class SMSBridge:
    """Puente Soberano de Mensajería SMS multi-canal."""

    _instance: Optional["SMSBridge"] = None
    _lock = threading.Lock()

    def __init__(self, config_path: Optional[Path | str] = None):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.config_path = Path(config_path) if config_path else CONFIG_FILE
        self.config = self._load_config()
        self.history: List[Dict[str, Any]] = self._load_history()
        self.last_sent_ts: float = 0.0

    @classmethod
    def get_instance(cls) -> "SMSBridge":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    normalize_phone_number = staticmethod(normalize_phone_number)

    def _load_config(self) -> Dict[str, Any]:
        cfg = dict(DEFAULT_CONFIG)
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                        cfg[k].update(v)
                    else:
                        cfg[k] = v
            except Exception as e:
                logger.warning(f"Error leyendo {self.config_path}: {e}")
        else:
            self._save_config(cfg)
        return cfg

    def _save_config(self, cfg: Optional[Dict[str, Any]] = None) -> bool:
        try:
            target = cfg or self.config
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(target, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Error guardando {self.config_path}: {e}")
            return False

    def _load_history(self) -> List[Dict[str, Any]]:
        if HISTORY_FILE.exists():
            try:
                return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save_history_entry(self, entry: Dict[str, Any]) -> None:
        try:
            self.history.append(entry)
            if len(self.history) > 200:
                self.history = self.history[-200:]
            HISTORY_FILE.write_text(json.dumps(self.history, indent=2, ensure_ascii=False), encoding="utf-8")

            # Bitácora forense de texto plano
            now_iso = entry.get("timestamp_iso", datetime.datetime.now().isoformat())
            st = "OK" if entry.get("success") else "FAIL"
            log_line = f"[{now_iso}] [{st}] [{entry.get('provider')}] To: {entry.get('to')} | Status: {entry.get('status_message')} | Msg: {entry.get('message_preview')}\n"
            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception as e:
            logger.error(f"Error registrando historial SMS: {e}")

    # =========================================================================
    # DISPATCHERS DE PROVEEDORES
    # =========================================================================

    def _send_via_twilio(self, to_number: str, message: str) -> Dict[str, Any]:
        """Envío a través de la API REST oficial de Twilio."""
        tw_cfg = self.config.get("twilio", {})
        sid = tw_cfg.get("account_sid", "").strip()
        tok = tw_cfg.get("auth_token", "").strip()
        from_num = tw_cfg.get("from_number", "").strip()

        if not sid or not tok or not from_num:
            return {"success": False, "provider": "twilio", "error": "Credenciales de Twilio incompletas (requiere account_sid, auth_token, from_number)."}

        import base64
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        data = urlencode({"To": to_number, "From": from_num, "Body": message}).encode("utf-8")
        auth_header = "Basic " + base64.b64encode(f"{sid}:{tok}".encode("utf-8")).decode("utf-8")

        req = Request(url, data=data, headers={"Authorization": auth_header, "User-Agent": "GODWORKS-SMS/26.4"})
        try:
            with urlopen(req, timeout=12.0) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                return {
                    "success": True,
                    "provider": "twilio",
                    "message_id": res_json.get("sid"),
                    "status": res_json.get("status"),
                    "raw": res_json,
                }
        except Exception as e:
            err_msg = str(e)
            if hasattr(e, "read"):
                try:
                    err_msg += f" - {e.read().decode('utf-8')}"
                except Exception:
                    pass
            return {"success": False, "provider": "twilio", "error": err_msg}

    def _send_via_android_gateway(self, to_number: str, message: str) -> Dict[str, Any]:
        """Envío a través de un gateway Android / Termux local en Wi-Fi o red LAN."""
        ag_cfg = self.config.get("android_gateway", {})
        url = ag_cfg.get("url", "").strip()
        token = ag_cfg.get("token", "").strip()

        if not url:
            return {"success": False, "provider": "android_gateway", "error": "No hay URL de Android Gateway configurada."}

        payload = json.dumps({"to": to_number, "phone": to_number, "message": message, "text": message}).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "GODWORKS-SMS/26.4"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req = Request(url, data=payload, headers=headers)
        try:
            with urlopen(req, timeout=10.0) as resp:
                res_data = resp.read().decode("utf-8")
                return {
                    "success": True,
                    "provider": "android_gateway",
                    "status": f"HTTP {resp.status}",
                    "response": res_data[:200],
                }
        except Exception as e:
            return {"success": False, "provider": "android_gateway", "error": str(e)}

    def _send_via_tardis_pocket(self, to_number: str, message: str) -> Dict[str, Any]:
        """Envío directo y soberano a través de TARDIS POCKET (Motorola Moto X Play, serial ZY222ZXWPP)."""
        try:
            from core.tardis_pocket_tunnel_bridge import get_tardis_pocket_bridge
            bridge = get_tardis_pocket_bridge()
            res = bridge.send_sms(to_number, message)
            if res.get("ok"):
                return {
                    "success": True,
                    "provider": "tardis_pocket",
                    "transport": res.get("transport", "HTTP_REST"),
                    "raw": res,
                }
            return {
                "success": False,
                "provider": "tardis_pocket",
                "error": res.get("error", "Fallo al despachar por TARDIS POCKET"),
                "raw": res,
            }
        except Exception as e:
            return {"success": False, "provider": "tardis_pocket", "error": str(e)}

    def _send_via_custom_webhook(self, to_number: str, message: str) -> Dict[str, Any]:
        """Envío a través de un webhook HTTP POST personalizado."""
        wh_cfg = self.config.get("custom_webhook", {})
        url = wh_cfg.get("url", "").strip()
        if not url:
            return {"success": False, "provider": "custom_webhook", "error": "No hay URL de custom_webhook configurada."}

        headers = {"Content-Type": "application/json", "User-Agent": "GODWORKS-SMS/26.4"}
        if wh_cfg.get("auth_header") and wh_cfg.get("auth_token"):
            headers[wh_cfg["auth_header"]] = wh_cfg["auth_token"]

        payload = json.dumps({"to": to_number, "message": message, "timestamp": time.time()}).encode("utf-8")
        req = Request(url, data=payload, headers=headers)
        try:
            with urlopen(req, timeout=10.0) as resp:
                return {
                    "success": True,
                    "provider": "custom_webhook",
                    "status": f"HTTP {resp.status}",
                    "response": resp.read().decode("utf-8")[:200],
                }
        except Exception as e:
            return {"success": False, "provider": "custom_webhook", "error": str(e)}

    def _send_via_textbelt(self, to_number: str, message: str) -> Dict[str, Any]:
        """Envío a través del servicio Textbelt."""
        tb_cfg = self.config.get("textbelt", {})
        api_key = tb_cfg.get("api_key", "textbelt").strip() or "textbelt"

        url = "https://textbelt.com/text"
        data = urlencode({"phone": to_number, "message": message, "key": api_key}).encode("utf-8")
        req = Request(url, data=data, headers={"User-Agent": "GODWORKS-SMS/26.4"})
        try:
            with urlopen(req, timeout=12.0) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                if res_json.get("success"):
                    return {
                        "success": True,
                        "provider": "textbelt",
                        "textId": res_json.get("textId"),
                        "quotaRemaining": res_json.get("quotaRemaining"),
                        "raw": res_json,
                    }
                else:
                    return {
                        "success": False,
                        "provider": "textbelt",
                        "error": res_json.get("error", "Fallo en Textbelt"),
                        "raw": res_json,
                    }
        except Exception as e:
            return {"success": False, "provider": "textbelt", "error": str(e)}

    def _send_via_modem(self, to_number: str, message: str) -> Dict[str, Any]:
        """Envío mediante módem local GSM / LTE (mmcli ModemManager)."""
        clean_num = to_number.strip()
        try:
            # Comprobar si mmcli existe y tiene módems
            chk = subprocess.run(["mmcli", "-L"], capture_output=True, text=True, timeout=5.0)
            if "No modems were found" in chk.stdout or chk.returncode != 0:
                return {"success": False, "provider": "modem", "error": "No se detectaron módems GSM/LTE locales activos (mmcli)."}

            # Obtener índice del módem
            modem_idx = self.config.get("modem", {}).get("mmcli_modem_index", 0)
            create_cmd = [
                "mmcli", "-m", str(modem_idx),
                f"--messaging-create-sms=number='{clean_num}',text='{message}'"
            ]
            c_res = subprocess.run(create_cmd, capture_output=True, text=True, timeout=10.0)
            if c_res.returncode != 0:
                return {"success": False, "provider": "modem", "error": f"Error creando SMS con mmcli: {c_res.stderr.strip()}"}

            sms_match = re.search(r"/SMS/(\d+)", c_res.stdout)
            if not sms_match:
                return {"success": False, "provider": "modem", "error": f"No se pudo obtener el ID del SMS creado: {c_res.stdout.strip()}"}

            sms_id = sms_match.group(1)
            send_cmd = ["mmcli", "-s", sms_id, "--send"]
            s_res = subprocess.run(send_cmd, capture_output=True, text=True, timeout=15.0)
            if s_res.returncode == 0:
                return {"success": True, "provider": "modem", "sms_id": sms_id, "output": s_res.stdout.strip()}
            return {"success": False, "provider": "modem", "error": f"Fallo al enviar SMS #{sms_id}: {s_res.stderr.strip()}"}
        except Exception as e:
            return {"success": False, "provider": "modem", "error": str(e)}

    def _send_via_email_gateway(self, to_number: str, message: str) -> Dict[str, Any]:
        """Envío a través de pasarelas Carrier Email-to-SMS."""
        eg_cfg = self.config.get("email_gateway", {})
        if not eg_cfg.get("enabled"):
            return {"success": False, "provider": "email_gateway", "error": "Email-to-SMS Gateway desactivado en la configuración."}

        host = eg_cfg.get("smtp_host")
        port = int(eg_cfg.get("smtp_port", 587))
        user = eg_cfg.get("smtp_user")
        pwd = eg_cfg.get("smtp_pass")
        carrier = eg_cfg.get("carrier", "telcel")

        if not host or not user or not pwd:
            return {"success": False, "provider": "email_gateway", "error": "Credenciales SMTP incompletas para pasarela Email-to-SMS."}

        digits = re.sub(r"\D", "", to_number)
        if len(digits) > 10 and digits.startswith("52"):
            digits = digits[2:]  # Formato 10 dígitos para operadoras mexicanas

        tpl = CARRIER_GATEWAYS.get(carrier.lower(), "{number}@itelcel.com")
        target_email = tpl.format(number=digits)

        try:
            msg = MIMEText(message, "plain", "utf-8")
            msg["Subject"] = ""
            msg["From"] = user
            msg["To"] = target_email

            server = smtplib.SMTP(host, port, timeout=15.0)
            server.starttls()
            server.login(user, pwd)
            server.sendmail(user, [target_email], msg.as_string())
            server.quit()
            return {
                "success": True,
                "provider": "email_gateway",
                "carrier": carrier,
                "target_email": target_email,
                "status": "Despachado a pasarela SMTP",
            }
        except Exception as e:
            return {"success": False, "provider": "email_gateway", "error": str(e)}

    # =========================================================================
    # MÉTODO MAESTRO DE ENVÍO
    # =========================================================================

    def send_sms(
        self,
        to_number: str,
        message: str,
        provider: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Envía un SMS estandarizado gestionando la normalización, selección de proveedor,
        failover automático e historial de auditoría.
        """
        if not self.config.get("enabled", True):
            return {"success": False, "error": "El puente de SMS está desactivado en la configuración."}

        clean_text = message.strip()
        if not clean_text:
            return {"success": False, "error": "El mensaje no puede estar vacío."}

        norm_to = normalize_phone_number(to_number, self.config.get("default_country_prefix", "+52"))
        prov = (provider or self.config.get("default_provider", "auto")).lower()

        logger.info(f"[SMSBridge] 📤 Despachando SMS a '{norm_to}' (Proveedor: {prov})...")

        res: Dict[str, Any] = {"success": False, "error": "Sin proveedor válido"}
        providers_tried: List[str] = []

        # Estrategia de envío
        if prov in ("tardis_pocket", "pocket", "celular", "mobile", "moto"):
            res = self._send_via_tardis_pocket(norm_to, clean_text)
            providers_tried.append("tardis_pocket")

        elif prov == "twilio":
            res = self._send_via_twilio(norm_to, clean_text)
            providers_tried.append("twilio")

        elif prov == "android" or prov == "android_gateway":
            res = self._send_via_android_gateway(norm_to, clean_text)
            providers_tried.append("android_gateway")

        elif prov == "webhook" or prov == "custom_webhook":
            res = self._send_via_custom_webhook(norm_to, clean_text)
            providers_tried.append("custom_webhook")

        elif prov == "textbelt":
            res = self._send_via_textbelt(norm_to, clean_text)
            providers_tried.append("textbelt")

        elif prov == "modem":
            res = self._send_via_modem(norm_to, clean_text)
            providers_tried.append("modem")

        elif prov == "email" or prov == "email_gateway":
            res = self._send_via_email_gateway(norm_to, clean_text)
            providers_tried.append("email_gateway")

        else:
            # Modo AUTO: Intenta secuencialmente los proveedores con prioridad soberana
            # 1. TARDIS POCKET Móvil Soberano (Motorola Moto X Play) si está habilitado
            if self.config.get("tardis_pocket", {}).get("enabled", True):
                pocket_res = self._send_via_tardis_pocket(norm_to, clean_text)
                providers_tried.append("tardis_pocket")
                if pocket_res.get("success"):
                    res = pocket_res

            # 2. Twilio si tiene credenciales
            if not res.get("success"):
                tw = self.config.get("twilio", {})
                if tw.get("account_sid") and tw.get("auth_token"):
                    res = self._send_via_twilio(norm_to, clean_text)
                    providers_tried.append("twilio")

            # 2. Android Gateway si está configurado
            if not res.get("success") and self.config.get("android_gateway", {}).get("url"):
                res = self._send_via_android_gateway(norm_to, clean_text)
                providers_tried.append("android_gateway")

            # 3. Custom Webhook si está configurado
            if not res.get("success") and self.config.get("custom_webhook", {}).get("url"):
                res = self._send_via_custom_webhook(norm_to, clean_text)
                providers_tried.append("custom_webhook")

            # 4. Textbelt
            if not res.get("success"):
                res = self._send_via_textbelt(norm_to, clean_text)
                providers_tried.append("textbelt")

            # 5. Módem local GSM si está habilitado
            if not res.get("success") and self.config.get("modem", {}).get("enabled", True):
                mod_res = self._send_via_modem(norm_to, clean_text)
                providers_tried.append("modem")
                if mod_res.get("success"):
                    res = mod_res

            # 6. Email-to-SMS si está configurado
            if not res.get("success") and self.config.get("email_gateway", {}).get("enabled"):
                em_res = self._send_via_email_gateway(norm_to, clean_text)
                providers_tried.append("email_gateway")
                if em_res.get("success"):
                    res = em_res

        # Registro de resultado
        now_ts = time.time()
        now_iso = datetime.datetime.now().isoformat()
        self.last_sent_ts = now_ts

        entry = {
            "timestamp": now_ts,
            "timestamp_iso": now_iso,
            "to": norm_to,
            "message_preview": (clean_text[:60] + "...") if len(clean_text) > 60 else clean_text,
            "characters": len(clean_text),
            "provider": res.get("provider", prov),
            "providers_tried": providers_tried,
            "success": res.get("success", False),
            "status_message": "Enviado con éxito" if res.get("success") else res.get("error", "Error desconocido"),
            "details": res,
        }
        self._save_history_entry(entry)

        if res.get("success"):
            logger.info(f"[SMSBridge] ✅ SMS entregado a '{norm_to}' mediante [{res.get('provider')}].")
        else:
            logger.warning(f"[SMSBridge] ❌ Error enviando SMS a '{norm_to}': {res.get('error')}")

        return {
            "ok": res.get("success", False),
            "to": norm_to,
            "provider_used": res.get("provider", prov),
            "providers_tried": providers_tried,
            "message": clean_text,
            "result": res,
            "timestamp": now_iso,
        }

    # =========================================================================
    # PARSEO DE INTENCIONES EN LENGUAJE NATURAL
    # =========================================================================

    def execute_sms_intent(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Detecta si el usuario desea enviar un SMS en lenguaje natural.
        Ejemplos:
          - 'Envía un SMS a 9842615588 que diga hola'
          - 'Manda un mensaje de texto al número +529842615588 con el reporte'
          - 'SMS al 9842615588: Tu orden está lista'
        """
        t_low = text.lower().strip()
        if not any(k in t_low for k in ("sms", "mensaje de texto", "manda un texto", "enviar texto", "mandar texto")):
            return None

        # Extraer teléfono (10 o más dígitos, posiblemente con +)
        phone_match = re.search(r"(\+?\d{10,15})", text)
        if not phone_match:
            return None

        phone = phone_match.group(1)

        # Extraer el contenido del mensaje
        # Patrones: 'que diga <msg>', 'diciendo <msg>', ': <msg>', 'con el mensaje <msg>'
        content = ""
        m_body = re.search(r"(?:que diga|diciendo|con el mensaje|con el texto|:\s*)(.+)$", text, flags=re.IGNORECASE)
        if m_body:
            content = m_body.group(1).strip()
        else:
            # Si no hay delimitador, quitar la parte del comando y el teléfono
            clean = re.sub(r"(?:envía|manda|enviar|mandar)?\s*(?:un\s*)?(?:sms|mensaje de texto)\s*(?:al?|para)?\s*" + re.escape(phone), "", text, flags=re.IGNORECASE).strip()
            content = clean.lstrip(":,- ").strip()

        if not content:
            content = "Mensaje prioritario desde GODWORKS SYSTEM v26.4"

        return self.send_sms(to_number=phone, message=content)

    def get_status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "enabled": self.config.get("enabled", True),
            "default_provider": self.config.get("default_provider", "auto"),
            "default_prefix": self.config.get("default_country_prefix", "+52"),
            "providers_configured": {
                "twilio": bool(self.config.get("twilio", {}).get("account_sid")),
                "android_gateway": bool(self.config.get("android_gateway", {}).get("url")),
                "custom_webhook": bool(self.config.get("custom_webhook", {}).get("url")),
                "textbelt": True,
                "modem": self.config.get("modem", {}).get("enabled", True),
                "email_gateway": bool(self.config.get("email_gateway", {}).get("enabled")),
            },
            "total_sent_in_history": len(self.history),
            "last_sent_iso": self.history[-1].get("timestamp_iso") if self.history else "Ninguno",
            "audit_log": str(AUDIT_LOG),
        }


def get_sms_bridge() -> SMSBridge:
    return SMSBridge.get_instance()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Puente Soberano de Mensajería SMS · GODWORKS SYSTEM v26.4")
    parser.add_argument("--to", help="Número telefónico destinatario (ej: 9842615588 o +529842615588)")
    parser.add_argument("--message", help="Cuerpo del mensaje de texto SMS a enviar")
    parser.add_argument("--provider", default="auto", help="Proveedor (auto, twilio, android, webhook, textbelt, modem, email)")
    parser.add_argument("--status", action="store_true", help="Mostrar estado de proveedores SMS y configuración")
    parser.add_argument("--history", action="store_true", help="Ver historial de últimos SMS enviados")
    args = parser.parse_args()

    bridge = get_sms_bridge()

    if args.status:
        print(json.dumps(bridge.get_status(), indent=2, ensure_ascii=False))
        return 0

    if args.history:
        print(json.dumps(bridge.history[-10:], indent=2, ensure_ascii=False))
        return 0

    if args.to and args.message:
        res = bridge.send_sms(to_number=args.to, message=args.message, provider=args.provider)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
