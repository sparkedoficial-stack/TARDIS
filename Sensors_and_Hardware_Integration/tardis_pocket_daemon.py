#!/usr/bin/env python3
"""
mobile_terminal/tardis_pocket_daemon.py
========================================================================================
DEMONIO SOBERANO LOCAL AUTÓNOMO 24/7 PARA TARDIS-POCKET (MOTOROLA MOTO X PLAY)
========================================================================================
Convierte a TARDIS-POCKET en un nodo autónomo independiente que opera continuamente sin
necesidad de abrir navegadores ni escribir URLs externas:
  1. Servidor HTTP local embebido en REDACTED_IP:8080 para la cabina soberana offline.
  2. Bucle centinela de telemetría física (Batería, GPS, Red) en segundo plano.
  3. Enrutador Omni-Ruta dinámico:
       - Prioridad 1: Hotspot Soberano Directo (http://REDACTED_IP:8757)
       - Prioridad 2: LAN Local (http://REDACTED_IP:8757)
       - Prioridad 3: Túnel Dinámico Auto-Descubierto
       - Prioridad 4: Motor de Inferencia Autónomo Local Offline
  4. Escucha y ejecución proactiva de comandos remotos (Voz TTS, Vibración, Shell).
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# Configuración Base
SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "tardis_pocket_daemon.log"
CONFIG_FILE = SCRIPT_DIR / "tardis_terminal_config.json"
CACHE_DIR = SCRIPT_DIR / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
ROUTES_CACHE = CACHE_DIR / "active_routes.json"

LOCAL_PORT = 8080
AUTHORIZED_SERIAL = "ZY222ZXWPP"
SOVEREIGN_KEY = "DiosDelTiempo01"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [TardisPocketDaemon] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)
logger = logging.getLogger("TardisPocketDaemon")

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from tardis_kaiju_pocket_engine import get_tardis_kaiju_pocket_engine, TardisKaijuPocketEngine
except ImportError:
    from mobile_terminal.tardis_kaiju_pocket_engine import get_tardis_kaiju_pocket_engine, TardisKaijuPocketEngine



class SystemHardwareProber:
    """Sonda nativa de hardware para Android y Termux (Batería, GPS, Red)."""

    @staticmethod
    def get_battery_info() -> Dict[str, Any]:
        """Obtiene el estado de la batería mediante termux-battery-status o sysfs."""
        # 1. Probar termux-battery-status
        if shutil.which("termux-battery-status"):
            try:
                res = subprocess.run(
                    ["termux-battery-status"], capture_output=True, text=True, timeout=3
                )
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    return {
                        "level": data.get("percentage", 100),
                        "charging": data.get("status", "") == "CHARGING" or data.get("plugged", "") != "UNPLUGGED",
                        "temp": round(data.get("temperature", 25.0), 1),
                        "health": data.get("health", "GOOD"),
                        "source": "termux-api"
                    }
            except Exception:
                pass

        # 2. Fallback directo a /sys/class/power_supply/battery
        sys_bat = Path("/sys/class/power_supply/battery")
        if sys_bat.exists():
            try:
                cap_file = sys_bat / "capacity"
                stat_file = sys_bat / "status"
                temp_file = sys_bat / "temp"

                level = int(cap_file.read_text().strip()) if cap_file.exists() else 100
                status = stat_file.read_text().strip() if stat_file.exists() else "Unknown"
                raw_temp = int(temp_file.read_text().strip()) if temp_file.exists() else 250
                temp = raw_temp / 10.0 if raw_temp > 100 else float(raw_temp)

                return {
                    "level": level,
                    "charging": status.lower() in ("charging", "full"),
                    "temp": round(temp, 1),
                    "health": "GOOD",
                    "source": "sysfs"
                }
            except Exception:
                pass

        return {"level": 100, "charging": False, "temp": 25.0, "source": "simulated"}

    @staticmethod
    def get_gps_info() -> Dict[str, Any]:
        """Obtiene la geolocalización actual mediante termux-location o caché previa."""
        if shutil.which("termux-location"):
            try:
                res = subprocess.run(
                    ["termux-location", "-p", "network", "-r", "last"],
                    capture_output=True, text=True, timeout=4
                )
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    return {
                        "lat": round(data.get("latitude", 0.0), 4),
                        "lon": round(data.get("longitude", 0.0), 4),
                        "alt": round(data.get("altitude", 0.0), 1),
                        "accuracy": round(data.get("accuracy", 0.0), 1),
                        "source": "termux-api"
                    }
            except Exception:
                pass

        # Ubicación ancla por defecto (Playa del Carmen / Q. Roo / Matriz Central)
        return {"lat": 20.6274, "lon": -87.0799, "alt": 10.0, "accuracy": 15.0, "source": "anchor"}

    @staticmethod
    def get_network_info() -> Dict[str, Any]:
        """Obtiene la interfaz y estado de red actual."""
        net = {"ssid": "Unknown", "ip": "REDACTED_IP", "interface": "unknown"}
        if shutil.which("termux-wifi-connectioninfo"):
            try:
                res = subprocess.run(
                    ["termux-wifi-connectioninfo"], capture_output=True, text=True, timeout=3
                )
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    net["ssid"] = data.get("ssid", "").replace('"', '')
                    net["ip"] = data.get("ip", "REDACTED_IP")
            except Exception:
                pass
        return net


class OmniRouteResolver:
    """Enrutador de conexión inteligente con cascada de prioridades."""

    def __init__(self):
        self.cached_tunnel = ""
        self.active_route_name = "AUTONOMOUS_FALLBACK"
        self.active_base_url = ""
        self.was_connected = False
        self._load_cached_routes()

    def _load_cached_routes(self):
        if ROUTES_CACHE.exists():
            try:
                data = json.loads(ROUTES_CACHE.read_text(encoding="utf-8"))
                self.cached_tunnel = data.get("tunnel_url", "")
            except Exception:
                pass

    def _save_cached_tunnel(self, url: str):
        if url and url != self.cached_tunnel:
            self.cached_tunnel = url
            try:
                ROUTES_CACHE.write_text(json.dumps({"tunnel_url": url, "updated_at": int(time.time())}), encoding="utf-8")
            except Exception:
                pass

    def test_url(self, base_url: str, timeout: float = 1.5) -> bool:
        """Comprueba si un endpoint de TARDIS responde correctamente."""
        if not base_url:
            return False
        try:
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/health",
                headers={"User-Agent": "TardisPocketDaemon/2.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _trigger_background_sync(self, base_url: str):
        try:
            engine = get_tardis_kaiju_pocket_engine()
            res = engine.sync_offline_vault(base_url)
            if res.get("synced", 0) > 0:
                logger.info(f"✓ Sincronización automática completada: {res['synced']} turnos subidos a la central.")
        except Exception as e:
            logger.debug(f"Aviso en auto-sincronización: {e}")

    def resolve_active_route(self) -> tuple[str, str]:
        """Evalúa las rutas en orden estricto de soberanía y velocidad."""
        prev_connected = self.was_connected
        chosen_route = "AUTONOMOUS_FALLBACK"
        chosen_base = ""

        # 0. Enlace Directo USB / ADB Loopback Central (http://REDACTED_IP:8757)
        if self.test_url("http://REDACTED_IP:8757", timeout=0.8):
            chosen_route = "DIRECT_USB_TETHER"
            chosen_base = "http://REDACTED_IP:8757"

        # 1. Hotspot Soberano Directo TimeMachine (REDACTED_IP:8757)
        elif self.test_url("http://REDACTED_IP:8757", timeout=1.2):
            chosen_route = "DIRECT_HOTSPOT"
            chosen_base = "http://REDACTED_IP:8757"

        # 2. LAN Local Central (REDACTED_IP:8757)
        elif self.test_url("http://REDACTED_IP:8757", timeout=1.2):
            chosen_route = "LOCAL_LAN"
            chosen_base = "http://REDACTED_IP:8757"

        # 3. Túnel Dinámico Cloudflare (si está en caché o configurado)
        elif self.cached_tunnel and self.test_url(self.cached_tunnel, timeout=2.5):
            chosen_route = "GLOBAL_TUNNEL"
            chosen_base = self.cached_tunnel

        self.active_route_name = chosen_route
        self.active_base_url = chosen_base

        if chosen_base:
            self.was_connected = True
            if not prev_connected:
                logger.info(f"🛰️ CONEXIÓN A ESTACIÓN CENTRAL DETECTADA ({chosen_route}: {chosen_base}). Despachando sincronización offline...")
                threading.Thread(target=self._trigger_background_sync, args=(chosen_base,), daemon=True).start()
        else:
            self.was_connected = False

        return self.active_route_name, self.active_base_url


    def update_dynamic_endpoints(self, base_url: str):
        """Descarga del nodo central la lista de rutas dinámicas actualizadas."""
        if not base_url:
            return
        try:
            req = urllib.request.Request(f"{base_url.rstrip('/')}/api/pocket/endpoints")
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                routes = data.get("routes", {})
                tunnel = routes.get("priority_3_tunnel", "")
                if tunnel:
                    self._save_cached_tunnel(tunnel)
        except Exception:
            pass


def run_telephony_cli(cli_args: List[str]) -> Dict[str, Any]:
    """Ejecuta el subsistema nativo de telefonía Java/Android en TARDIS POCKET."""
    jar = "/data/local/tmp/tardis_telephony.jar"
    if not os.path.exists(jar):
        jar = str(SCRIPT_DIR / "tardis_telephony.jar")
    cmd = ["app_process", "/", "com.tardis.telephony.TardisTelephonyCLI"] + cli_args
    env = os.environ.copy()
    env["CLASSPATH"] = jar
    try:
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=12)
        out = res.stdout.strip()
        for line in out.splitlines():
            line_str = line.strip()
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    return json.loads(line_str)
                except Exception:
                    pass
        return {"ok": res.returncode == 0, "output": out, "stderr": res.stderr.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class CommandExecutor:
    """Ejecutor local de comandos físicos en TARDIS-POCKET."""

    @staticmethod
    def execute(cmd: Dict[str, Any]):
        action = cmd.get("action", "").lower()
        params = cmd.get("params", {})
        logger.info(f"⚡ Ejecutando comando local en dispositivo: {action} con params: {params}")

        if action == "tts" or action == "speak":
            text = params.get("text", "Mensaje recibido del nodo central TARDIS.")
            if shutil.which("termux-tts-speak"):
                subprocess.Popen(["termux-tts-speak", text])
            logger.info(f"🔊 Síntesis de voz reproducida: '{text}'")

        elif action == "vibrate":
            duration = str(params.get("duration", 350))
            if shutil.which("termux-vibrate"):
                subprocess.Popen(["termux-vibrate", "-d", duration])
            logger.info(f"📳 Pulso háptico activado ({duration}ms)")

        elif action == "notify":
            title = params.get("title", "TARDIS SOBERANO")
            content = params.get("content", "Notificación del sistema central.")
            if shutil.which("termux-notification"):
                subprocess.Popen(["termux-notification", "--title", title, "--content", content])

        elif action == "open_ui":
            url = f"http://REDACTED_IP:{LOCAL_PORT}"
            logger.info(f"🖥️ Levantando interfaz local nativa en pantalla: {url}")
            subprocess.Popen([
                "am", "start", "-a", "android.intent.action.VIEW", "-d", url
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        elif action in ("sms", "send_sms"):
            dest = params.get("to") or params.get("number") or params.get("dest")
            msg = params.get("message") or params.get("text") or ""
            if dest and msg:
                res = run_telephony_cli(["send_sms", dest, msg])
                logger.info(f"📱 SMS despachado: {res}")
                return res

        elif action in ("call", "make_call", "dial"):
            dest = params.get("number") or params.get("to")
            if dest:
                res = run_telephony_cli(["make_call", dest])
                logger.info(f"📞 Llamada iniciada a {dest}: {res}")
                return res

        elif action in ("hangup", "end_call", "colgar"):
            res = run_telephony_cli(["hangup"])
            logger.info(f"📴 Llamada finalizada: {res}")
            return res

        elif action in ("answer", "contestar"):
            res = run_telephony_cli(["answer"])
            logger.info(f"📲 Llamada contestada: {res}")
            return res

        elif action in ("mobile_data", "data"):
            enable_val = params.get("enabled", True)
            mode = "enable" if enable_val else "disable"
            res = run_telephony_cli(["mobile_data", mode])
            logger.info(f"📶 Datos móviles actualizados: {res}")
            return res

        elif action in ("usb_tether", "tether"):
            enable_val = params.get("enabled", True)
            mode = "enable" if enable_val else "disable"
            res = run_telephony_cli(["usb_tether", mode])
            logger.info(f"🔄 USB Tethering actualizado: {res}")
            return res

        elif action == "exec" or action == "shell":
            command_str = params.get("command", "")
            if command_str:
                try:
                    res = subprocess.run(
                        command_str, shell=True, capture_output=True, text=True, timeout=15
                    )
                    logger.info(f"Shell exec output: {res.stdout.strip()}")
                except Exception as e:
                    logger.error(f"Error en comando shell: {e}")


class TardisPocketHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Manejador HTTP que sirve la interfaz offline y atiende endpoints locales."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SCRIPT_DIR), **kwargs)

    def do_GET(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

        if path in ("/", "/index.html", "/pocket", "/tardis_pocket"):
            self.path = "/tardis_pocket.html"
            return super().do_GET()

        if path == "/api/local/status":
            self._handle_local_status()
            return

        if path == "/api/local/telemetry":
            self._handle_local_telemetry()
            return

        if path == "/api/local/history":
            self._handle_local_history()
            return

        if path == "/api/local/sync":
            self._handle_local_sync()
            return

        if path in ("/api/local/telephony/status", "/api/local/telephony", "/api/local/sim"):
            self._handle_telephony_status()
            return

        return super().do_GET()

    def do_POST(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

        if path == "/api/local/chat":
            self._handle_local_chat()
            return

        if path == "/api/local/command":
            self._handle_local_command()
            return

        if path == "/api/local/sync":
            self._handle_local_sync()
            return

        if path in ("/api/local/sms/send", "/api/local/sms"):
            self._handle_sms_send()
            return

        if path in ("/api/local/calls/dial", "/api/local/calls/make", "/api/local/call"):
            self._handle_call_dial()
            return

        if path in ("/api/local/calls/hangup", "/api/local/hangup"):
            self._handle_call_hangup()
            return

        if path in ("/api/local/calls/answer", "/api/local/answer"):
            self._handle_call_answer()
            return

        if path in ("/api/local/mobile/data", "/api/local/data"):
            self._handle_mobile_data()
            return

        if path in ("/api/local/mobile/tether", "/api/local/tether"):
            self._handle_usb_tether()
            return

        self.send_response(404)
        self.end_headers()

    def _handle_telephony_status(self):
        res = run_telephony_cli(["status"])
        self._send_json(res)

    def _handle_sms_send(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}
        dest = req_data.get("to") or req_data.get("number") or req_data.get("phone", "")
        message = req_data.get("message") or req_data.get("text", "")
        if not dest or not message:
            self._send_json({"ok": False, "error": "Campos 'to' y 'message' son obligatorios."}, status=400)
            return
        res = run_telephony_cli(["send_sms", dest, message])
        self._send_json(res)

    def _handle_call_dial(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}
        dest = req_data.get("number") or req_data.get("to") or req_data.get("phone", "")
        if not dest:
            self._send_json({"ok": False, "error": "Campo 'number' es obligatorio."}, status=400)
            return
        res = run_telephony_cli(["make_call", dest])
        self._send_json(res)

    def _handle_call_hangup(self):
        res = run_telephony_cli(["hangup"])
        self._send_json(res)

    def _handle_call_answer(self):
        res = run_telephony_cli(["answer"])
        self._send_json(res)

    def _handle_mobile_data(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}
        enable_val = req_data.get("enable", req_data.get("enabled", True))
        mode = "enable" if enable_val else "disable"
        res = run_telephony_cli(["mobile_data", mode])
        self._send_json(res)

    def _handle_usb_tether(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}
        enable_val = req_data.get("enable", req_data.get("enabled", True))
        mode = "enable" if enable_val else "disable"
        res = run_telephony_cli(["usb_tether", mode])
        self._send_json(res)

    def _handle_local_status(self):
        daemon = TardisPocketDaemon.get_instance()
        engine = get_tardis_kaiju_pocket_engine()
        unsynced_turns = len(engine.vault.get_unsynced_turns())
        total_turns = len(engine.vault.turns)

        data = {
            "device": "TARDIS_POCKET",
            "serial": AUTHORIZED_SERIAL,
            "daemon": "ONLINE",
            "active_route": daemon.resolver.active_route_name,
            "active_base_url": daemon.resolver.active_base_url,
            "kaiju_nano_status": "READY",
            "offline_vault_turns": total_turns,
            "unsynced_offline_turns": unsynced_turns,
            "battery": daemon.last_battery,
            "gps": daemon.last_gps,
            "network": daemon.last_network,
            "cached_tunnel": daemon.resolver.cached_tunnel,
            "timestamp": int(time.time())
        }
        self._send_json(data)

    def _handle_local_telemetry(self):
        daemon = TardisPocketDaemon.get_instance()
        self._send_json({
            "battery": daemon.last_battery,
            "gps": daemon.last_gps,
            "network": daemon.last_network,
            "route_mode": daemon.resolver.active_route_name
        })

    def _handle_local_history(self):
        engine = get_tardis_kaiju_pocket_engine()
        history = engine.vault.get_recent_history(50)
        self._send_json({"ok": True, "turns": history, "total": len(engine.vault.turns)})

    def _handle_local_sync(self):
        daemon = TardisPocketDaemon.get_instance()
        engine = get_tardis_kaiju_pocket_engine()
        route_name, base_url = daemon.resolver.resolve_active_route()
        if base_url:
            res = engine.sync_offline_vault(base_url)
            self._send_json({"ok": True, "route": route_name, "base_url": base_url, "sync": res})
        else:
            self._send_json({
                "ok": False,
                "status": "offline_no_central_route",
                "unsynced": len(engine.vault.get_unsynced_turns())
            })

    def _handle_local_chat(self):
        daemon = TardisPocketDaemon.get_instance()
        engine = get_tardis_kaiju_pocket_engine()

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        message = req_data.get("message", "")
        route_name, base_url = daemon.resolver.resolve_active_route()

        # 1. Si tenemos enlace central activo (Hotspot, LAN o Túnel), despachar a la Central TARDIS
        if base_url:
            try:
                payload = json.dumps({
                    "message": message,
                    "key": SOVEREIGN_KEY,
                    "device": "TARDIS_POCKET",
                    "serial": AUTHORIZED_SERIAL,
                    "model": "TARDIS-NEURAL-SPACE-KAIJU"
                }).encode("utf-8")

                req = urllib.request.Request(
                    f"{base_url.rstrip('/')}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    central_text = resp_data.get("response") or resp_data.get("text") or "Sin respuesta del núcleo central."
                    self._send_json({
                        "response": central_text,
                        "mode": route_name,
                        "source": "CENTRAL_STATION"
                    })
                    # Sincronizar en segundo plano posibles turnos offline anteriores
                    threading.Thread(target=engine.sync_offline_vault, args=(base_url,), daemon=True).start()
                    return
            except Exception as e:
                logger.warning(f"Aviso: Fallo conectando a estación central ({base_url}): {e}. Conmutando de inmediato a KAIJU-NANO local...")

        # 2. Inferencia Cognitiva Soberana Local (TARDIS-NEURAL-SPACE-KAIJU-NANO)
        telemetry = {
            "battery": daemon.last_battery,
            "gps": daemon.last_gps,
            "network": daemon.last_network
        }
        kaiju_res = engine.chat(message, telemetry=telemetry)
        self._send_json({
            "response": kaiju_res["response"],
            "mode": "OFFLINE_SOVEREIGN",
            "source": "KAIJU_NANO_LOCAL",
            "intent": kaiju_res.get("intent"),
            "turn_id": kaiju_res.get("turn_id"),
            "timestamp": kaiju_res.get("timestamp")
        })

    def _handle_local_command(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            cmd = json.loads(body)
            CommandExecutor.execute(cmd)
            self._send_json({"ok": True, "executed": cmd.get("action")})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, status=500)

    def _send_json(self, data: Any, status: int = 200):
        out = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()


class TardisPocketDaemon:
    """Demonio principal de TARDIS-POCKET con bucle centinela y servidor local."""

    _instance: Optional[TardisPocketDaemon] = None

    @classmethod
    def get_instance(cls) -> TardisPocketDaemon:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.running = False
        self.resolver = OmniRouteResolver()
        self.last_battery = {"level": 100, "charging": False, "temp": 25.0}
        self.last_gps = {"lat": 20.6274, "lon": -87.0799, "alt": 10.0}
        self.last_network = {"ssid": "Unknown", "ip": "REDACTED_IP"}
        self.server: Optional[socketserver.TCPServer] = None

    def start_local_server(self):
        """Inicia el servidor web local en REDACTED_IP:8080."""
        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        try:
            self.server = ReusableTCPServer(("REDACTED_IP", LOCAL_PORT), TardisPocketHTTPRequestHandler)
            logger.info(f"🚀 Servidor Web Soberano local escuchando en http://REDACTED_IP:{LOCAL_PORT}")
            self.server.serve_forever()
        except Exception as e:
            logger.error(f"Error iniciando servidor web local: {e}")

    def run_telemetry_loop(self):
        """Bucle centinela que reporta telemetría y ejecuta comandos en segundo plano."""
        logger.info("📡 Iniciando bucle centinela de telemetría y comandos en segundo plano...")
        consecutive_sync_failures = 0

        while self.running:
            try:
                # 1. Sondear hardware físico
                self.last_battery = SystemHardwareProber.get_battery_info()
                self.last_gps = SystemHardwareProber.get_gps_info()
                self.last_network = SystemHardwareProber.get_network_info()

                engine = get_tardis_kaiju_pocket_engine()
                engine.update_hardware_telemetry({
                    "battery": self.last_battery,
                    "gps": self.last_gps,
                    "network": self.last_network
                })

                # 2. Resolver mejor ruta
                route_name, base_url = self.resolver.resolve_active_route()

                if base_url:
                    # 3. Sincronizar turnos offline acumulados si existen
                    try:
                        if engine.vault.get_unsynced_turns():
                            engine.sync_offline_vault(base_url, timeout=3.5)
                    except Exception as e_sync:
                        logger.debug(f"Aviso en sincronización periódica: {e_sync}")

                    # 4. Transmitir telemetría al nodo central
                    telemetry_payload = json.dumps({
                        "device": "TARDIS_POCKET",
                        "serial": AUTHORIZED_SERIAL,
                        "battery": self.last_battery,
                        "gps": self.last_gps,
                        "network": self.last_network.get("ssid", "Wi-Fi"),
                        "client_ip": self.last_network.get("ip", ""),
                        "route_mode": route_name,
                        "daemon_version": "2.0-SOVEREIGN"
                    }).encode("utf-8")

                    post_url = f"{base_url.rstrip('/')}/api/pocket/telemetry?key={SOVEREIGN_KEY}"
                    req = urllib.request.Request(
                        post_url,
                        data=telemetry_payload,
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        if resp.status == 200:
                            consecutive_sync_failures = 0

                    # 5. Actualizar rutas dinámicas
                    self.resolver.update_dynamic_endpoints(base_url)

                    # 6. Extraer y ejecutar comandos pendientes del nodo central
                    poll_url = f"{base_url.rstrip('/')}/api/pocket/commands/poll?serial={AUTHORIZED_SERIAL}&key={SOVEREIGN_KEY}"
                    poll_req = urllib.request.Request(poll_url)
                    with urllib.request.urlopen(poll_req, timeout=3.0) as resp:
                        poll_data = json.loads(resp.read().decode("utf-8"))
                        commands = poll_data.get("commands", [])
                        for cmd in commands:
                            CommandExecutor.execute(cmd)

                else:
                    consecutive_sync_failures += 1
                    if consecutive_sync_failures % 6 == 1:
                        logger.info("Modo Autónomo Local Activo (Estación central no alcanzable en este momento · KAIJU-NANO en guardia).")


            except Exception as e:
                logger.debug(f"Ciclo de sincronización: {e}")

            time.sleep(20)

    def run(self):
        """Inicia el demonio completo."""
        self.running = True
        logger.info("===============================================================")
        logger.info(" TARDIS POCKET SOBERANO DAEMON v2.0 - ARRANQUE AUTÓNOMO")
        logger.info(" Dispositivo : Motorola Moto X Play (lux)")
        logger.info(f" Serial      : {AUTHORIZED_SERIAL}")
        logger.info(" Modo        : 100% AUTÓNOMO (CERO DEPENDENCIAS DE URLS)")
        logger.info("===============================================================")

        # Lanzar servidor web local en hilo secundario
        t_server = threading.Thread(target=self.start_local_server, daemon=True)
        t_server.start()

        # Bucle centinela en hilo principal
        self.run_telemetry_loop()


def main():
    daemon = TardisPocketDaemon.get_instance()
    try:
        daemon.run()
    except KeyboardInterrupt:
        logger.info("Deteniendo demonio por señal de usuario...")
        daemon.running = False


if __name__ == "__main__":
    main()
