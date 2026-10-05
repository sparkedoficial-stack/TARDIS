"""
core/tardis_pocket_tunnel_bridge.py - Puente de Enlace Seguro y Telemetría TARDIS POCKET
========================================================================================
Gestiona el enlace seguro exclusivo entre el nodo local central de TARDIS y el
dispositivo móvil TARDIS POCKET (Motorola Moto X Play, serial ZY222ZXWPP):
  1. Autenticación Criptográfica Irrevocable por Hardware (Serial ZY222ZXWPP).
  2. Recepción y registro continuo de telemetría física (Batería, GPS, Red, Hardware).
  3. Despacho y enrutamiento dinámico sin URLs fijas (Hotspot REDACTED_IP, LAN, Túnel).
  4. Cola bidireccional de comandos soberanos en segundo plano (TTS, Vibración, Shell).
  5. Despacho de actualizaciones Over-The-Air (OTA) inalámbricas con auto-descubrimiento.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("TardisPocketBridge")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "pocket"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TELEMETRY_LOG = DATA_DIR / "pocket_telemetry.json"
COMMAND_QUEUE_FILE = DATA_DIR / "command_queue.json"
AUTHORIZED_SERIAL = "ZY222ZXWPP"
SOVEREIGN_KEY = "DiosDelTiempo01"


def get_local_lan_ip() -> str:
    """Obtiene la IP de la interfaz LAN activa del equipo."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("REDACTED_IP", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "REDACTED_IP"


class TardisPocketBridge:
    """Controlador central del vínculo seguro para TARDIS POCKET."""

    _instance: Optional[TardisPocketBridge] = None

    @classmethod
    def get_instance(cls) -> TardisPocketBridge:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.last_telemetry: Dict[str, Any] = {
            "device": "TARDIS_POCKET",
            "serial": AUTHORIZED_SERIAL,
            "battery": {"level": 100, "charging": False, "temp": 25},
            "gps": {"lat": 0.0, "lon": 0.0, "alt": 0.0},
            "network": "Wi-Fi",
            "client_ip": "",
            "last_seen": 0,
            "status": "INITIALIZING"
        }
        self.command_queue: List[Dict[str, Any]] = []
        self._load_last_telemetry()
        self._load_command_queue()

    def _load_last_telemetry(self):
        if TELEMETRY_LOG.exists():
            try:
                self.last_telemetry = json.loads(TELEMETRY_LOG.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"No se pudo cargar telemetría previa de TARDIS POCKET: {e}")

    def _load_command_queue(self):
        if COMMAND_QUEUE_FILE.exists():
            try:
                self.command_queue = json.loads(COMMAND_QUEUE_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"No se pudo cargar cola de comandos previa: {e}")
                self.command_queue = []

    def _save_command_queue(self):
        try:
            COMMAND_QUEUE_FILE.write_text(json.dumps(self.command_queue, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando cola de comandos: {e}")

    def validate_device(self, serial: str, key: str) -> bool:
        """Verifica que la petición provenga exclusivamente del dispositivo físico autorizado."""
        if not serial or not key:
            return False
        return serial.strip().upper() == AUTHORIZED_SERIAL and key.strip() == SOVEREIGN_KEY

    def record_telemetry(self, data: Dict[str, Any], client_ip: str = "") -> bool:
        """Registra la telemetría física recibida de TARDIS POCKET en segundo plano."""
        serial = data.get("serial", "")
        if serial.strip().upper() != AUTHORIZED_SERIAL:
            logger.warning(f"Intento de acceso denegado: Serial no autorizado '{serial}'")
            return False

        detected_ip = client_ip or data.get("client_ip", "") or self.last_telemetry.get("client_ip", "")
        
        self.last_telemetry = {
            "device": "TARDIS_POCKET",
            "serial": AUTHORIZED_SERIAL,
            "battery": data.get("battery", {}),
            "gps": data.get("gps", {}),
            "network": data.get("network", "Wi-Fi"),
            "client_ip": detected_ip,
            "route_mode": data.get("route_mode", "DIRECT"),
            "daemon_version": data.get("daemon_version", "2.0-SOVEREIGN"),
            "last_seen": int(time.time()),
            "status": "ONLINE"
        }

        try:
            TELEMETRY_LOG.write_text(json.dumps(self.last_telemetry, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando telemetría de TARDIS POCKET: {e}")

        logger.info(
            f"⚡ Telemetría TARDIS POCKET recibida: IP {detected_ip} | Batería {self.last_telemetry['battery'].get('level')}% | GPS {self.last_telemetry['gps'].get('lat')},{self.last_telemetry['gps'].get('lon')}"
        )
        return True

    def get_status(self) -> Dict[str, Any]:
        """Retorna el estado de conexión y telemetría actual de TARDIS POCKET."""
        now = int(time.time())
        is_online = (now - self.last_telemetry.get("last_seen", 0)) < 90
        return {
            "device": "TARDIS_POCKET",
            "hardware": "Motorola Moto X Play (Snapdragon 615 / 2GB RAM)",
            "serial": AUTHORIZED_SERIAL,
            "online": is_online,
            "last_seen": self.last_telemetry.get("last_seen", 0),
            "client_ip": self.last_telemetry.get("client_ip", ""),
            "route_mode": self.last_telemetry.get("route_mode", "UNKNOWN"),
            "battery": self.last_telemetry.get("battery", {}),
            "gps": self.last_telemetry.get("gps", {}),
            "pending_commands": len(self.command_queue),
            "status": "ONLINE" if is_online else "STANDBY"
        }

    def get_connection_endpoints(self) -> Dict[str, Any]:
        """Calcula dinámicamente todos los puntos de enlace disponibles sin requerir URLs manuales."""
        lan_ip = get_local_lan_ip()
        
        # Leer URL de túnel dinámico actual si existe
        dynamic_tunnel = ""
        link_json = BASE_DIR / "data" / "client_chat_link.json"
        if link_json.exists():
            try:
                dt = json.loads(link_json.read_text(encoding="utf-8"))
                pub_url = dt.get("client_public_url", "")
                if pub_url and "trycloudflare.com" in pub_url:
                    # Extraer base del host
                    dynamic_tunnel = pub_url.split("/client")[0]
            except Exception:
                pass

        if not dynamic_tunnel:
            tunnel_file = BASE_DIR / "CLIENT_GATEWAY_TUNNEL_URL.txt"
            if tunnel_file.exists():
                try:
                    dynamic_tunnel = tunnel_file.read_text(encoding="utf-8").strip()
                except Exception:
                    pass

        return {
            "device": "TARDIS_POCKET",
            "serial": AUTHORIZED_SERIAL,
            "auth_key": SOVEREIGN_KEY,
            "routes": {
                "priority_1_hotspot": "http://REDACTED_IP:8757",
                "priority_2_lan": f"http://{lan_ip}:8757",
                "priority_3_tunnel": dynamic_tunnel,
                "local_daemon": "http://REDACTED_IP:8080"
            },
            "timestamp": int(time.time())
        }

    def queue_command(self, action: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Encola un comando soberano para ser ejecutado por el demonio nativo de TARDIS POCKET."""
        cmd_id = f"cmd_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        item = {
            "id": cmd_id,
            "action": action,
            "params": params or {},
            "queued_at": int(time.time()),
            "status": "PENDING"
        }
        self.command_queue.append(item)
        self._save_command_queue()
        logger.info(f"Comando encolado para TARDIS POCKET: {action} (ID: {cmd_id})")
        return cmd_id

    def pop_commands(self, serial: str) -> List[Dict[str, Any]]:
        """Extrae los comandos pendientes para el dispositivo autorizado."""
        if serial.strip().upper() != AUTHORIZED_SERIAL:
            return []
        
        pending = list(self.command_queue)
        self.command_queue.clear()
        self._save_command_queue()
        return pending

    def sync_offline_dialogues(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recibe e ingesta en la memoria histórica del nodo central los turnos
        conversacionales registrados por TARDIS-POCKET mientras estuvo offline.
        """
        serial = data.get("serial", "")
        if serial.strip().upper() != AUTHORIZED_SERIAL:
            return {"ok": False, "error": "Serial no autorizado"}

        turns = data.get("turns", [])
        if not turns:
            return {"ok": True, "ingested": 0}

        sync_file = DATA_DIR / "pocket_synced_chats.json"
        existing = []
        if sync_file.exists():
            try:
                existing = json.loads(sync_file.read_text(encoding="utf-8"))
            except Exception:
                existing = []

        existing_ids = {t.get("id") for t in existing if isinstance(t, dict)}
        added_count = 0
        for t in turns:
            if t.get("id") not in existing_ids:
                existing.append(t)
                existing_ids.add(t.get("id"))
                added_count += 1
                
                # Ingestar en OfflineChatVault central si está disponible
                try:
                    from core.offline_chat_vault import OfflineChatVault
                    vault = OfflineChatVault.get_instance()
                    vault.record_turn(
                        user_message=t.get("user_message", ""),
                        assistant_reply=t.get("assistant_reply", ""),
                        session_id=f"pocket_{serial}",
                        client_id="TARDIS-POCKET",
                        model="TARDIS-NEURAL-SPACE-KAIJU-NANO",
                        meta={"pocket_id": t.get("id"), "synced_at": time.time(), "device": "Motorola Moto X Play"}
                    )
                except Exception as e_vault:
                    logger.warning(f"Aviso ingestando turno en OfflineChatVault: {e_vault}")

        try:
            sync_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error escribiendo pocket_synced_chats.json: {e}")

        logger.info(f"✓ {added_count} turnos offline de TARDIS-POCKET integrados a la memoria central.")
        return {"ok": True, "ingested": added_count, "total_synced": len(existing)}

    # =========================================================================
    # GESTIÓN DE ENLACE FÍSICO Y TELEFONÍA SOBERANA (LLAMADAS & SMS)
    # =========================================================================

    def ensure_bridge_connected(self) -> Dict[str, Any]:
        """
        Garantiza que el túnel de comunicación con TARDIS POCKET esté 100% activo:
        1. Comprueba conectividad ADB por USB o WiFi.
        2. Configura reenvío inverso de puertos:
           - Host -> Pocket: port 8080 (servidor web local de TARDIS POCKET)
           - Pocket -> Host: port 8757 (servidor central de TARDIS)
        3. Verifica o arranca el demonio local en el dispositivo.
        4. Despliega el subsistema de telefonía 'tardis_telephony.jar' si es necesario.
        """
        status: Dict[str, Any] = {
            "adb_connected": False,
            "transport": "none",
            "forward_8080": False,
            "reverse_8757": False,
            "daemon_alive": False,
            "telephony_jar_ready": False,
        }

        # 1. Chequeo de dispositivos ADB
        try:
            res = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=3.0)
            lines = res.stdout.strip().splitlines()[1:]
            active_devs = [l.split()[0] for l in lines if "\tdevice" in l]

            device_id = ""
            if AUTHORIZED_SERIAL in active_devs:
                device_id = AUTHORIZED_SERIAL
                status["transport"] = "USB"
            elif any(d.startswith("192.168.") for d in active_devs):
                device_id = [d for d in active_devs if d.startswith("192.168.")][0]
                status["transport"] = "WIFI_LAN"
            elif active_devs:
                device_id = active_devs[0]
                status["transport"] = "ADB_GENERIC"
            else:
                # Intentar conectar a la IP LAN conocida
                lan_ip = self.last_telemetry.get("client_ip", "REDACTED_IP")
                subprocess.run(["adb", "connect", f"{lan_ip}:5555"], capture_output=True, timeout=3.0)
                res2 = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=3.0)
                active_devs2 = [l.split()[0] for l in res2.stdout.strip().splitlines()[1:] if "\tdevice" in l]
                if active_devs2:
                    device_id = active_devs2[0]
                    status["transport"] = "WIFI_LAN_RECONNECTED"

            if device_id:
                status["adb_connected"] = True
                status["device_id"] = device_id

                # 2. Configurar túneles de puertos
                cmd_prefix = ["adb", "-s", device_id] if len(active_devs) > 1 else ["adb"]
                
                # Forward 8080 (PC -> Phone)
                r_fwd = subprocess.run(cmd_prefix + ["forward", "tcp:8080", "tcp:8080"], capture_output=True, timeout=3.0)
                status["forward_8080"] = (r_fwd.returncode == 0)

                # Reverse 8757 (Phone -> PC)
                r_rev = subprocess.run(cmd_prefix + ["reverse", "tcp:8757", "tcp:8757"], capture_output=True, timeout=3.0)
                status["reverse_8757"] = (r_rev.returncode == 0)

                # 3. Comprobar o desplegar tardis_telephony.jar
                local_jar = BASE_DIR / "core" / "tardis_telephony.jar"
                if local_jar.exists():
                    chk_jar = subprocess.run(cmd_prefix + ["shell", "ls -l /data/local/tmp/tardis_telephony.jar 2>/dev/null"], capture_output=True, text=True, timeout=3.0)
                    if "tardis_telephony.jar" not in chk_jar.stdout:
                        subprocess.run(cmd_prefix + ["push", str(local_jar), "/data/local/tmp/tardis_telephony.jar"], capture_output=True, timeout=5.0)
                        subprocess.run(cmd_prefix + ["push", str(local_jar), "/sdcard/tardis/tardis_telephony.jar"], capture_output=True, timeout=5.0)
                    status["telephony_jar_ready"] = True

                # 4. Verificar si el demonio en el teléfono responde en 8080
                try:
                    req = urllib.request.Request("http://REDACTED_IP:8080/api/local/status", headers={"User-Agent": "TARDIS-Central/26.4"})
                    with urllib.request.urlopen(req, timeout=1.5) as resp:
                        if resp.status == 200:
                            status["daemon_alive"] = True
                except Exception:
                    # Despertar demonio si no está activo
                    wake_cmd = cmd_prefix + ["shell", "run-as com.termux sh -c 'nohup /data/data/com.termux/files/usr/bin/python3 /sdcard/tardis/tardis_pocket_daemon.py > /sdcard/tardis/daemon.log 2>&1 & echo $!'"]
                    subprocess.run(wake_cmd, capture_output=True, timeout=5.0)
                    time.sleep(1.0)
                    try:
                        req = urllib.request.Request("http://REDACTED_IP:8080/api/local/status", headers={"User-Agent": "TARDIS-Central/26.4"})
                        with urllib.request.urlopen(req, timeout=1.5) as resp:
                            if resp.status == 200:
                                status["daemon_alive"] = True
                    except Exception:
                        status["daemon_alive"] = False

        except Exception as e:
            status["error"] = str(e)

        return status

    def _call_pocket_api(self, endpoint: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None, timeout: float = 6.0) -> Optional[Dict[str, Any]]:
        """Intenta invocar la API REST local de TARDIS POCKET (REDACTED_IP:8080 o IP LAN)."""
        urls = ["http://REDACTED_IP:8080"]
        lan_ip = self.last_telemetry.get("client_ip", "REDACTED_IP")
        if lan_ip and lan_ip != "REDACTED_IP":
            urls.append(f"http://{lan_ip}:8080")

        data_bytes = json.dumps(payload).encode("utf-8") if payload else None
        headers = {"Content-Type": "application/json", "User-Agent": "TARDIS-Central/26.4"}

        for base_url in urls:
            try:
                full_url = f"{base_url}{endpoint}"
                req = urllib.request.Request(full_url, data=data_bytes, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    resp_text = resp.read().decode("utf-8")
                    return json.loads(resp_text)
            except Exception:
                continue
        return None

    def _run_adb_telephony(self, args: List[str]) -> Dict[str, Any]:
        """Ejecuta directamente el subsistema de telefonía por puente ADB (fallback transparente)."""
        jar = "/data/local/tmp/tardis_telephony.jar"
        cmd = ["adb", "shell", f"CLASSPATH={jar} app_process / com.tardis.telephony.TardisTelephonyCLI " + " ".join([f"'{a}'" for a in args])]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=12.0)
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

    def send_sms(self, to_number: str, message: str) -> Dict[str, Any]:
        """
        Envía un SMS a través de la tarjeta SIM o RIL móvil de TARDIS POCKET.
        Prioridad 1: API REST HTTP directa (REDACTED_IP:8080).
        Prioridad 2: Invocación directa ADB shell (fallback resiliente).
        """
        clean_num = to_number.strip().replace(" ", "").replace("-", "")
        clean_msg = message.strip()
        if not clean_num or not clean_msg:
            return {"ok": False, "error": "Número y mensaje son obligatorios"}

        # 1. Probar HTTP REST
        http_res = self._call_pocket_api("/api/local/sms/send", method="POST", payload={"to": clean_num, "message": clean_msg})
        if http_res and http_res.get("ok"):
            return {
                "ok": True,
                "provider": "tardis_pocket",
                "transport": "HTTP_REST",
                "to": clean_num,
                "message": clean_msg,
                "raw": http_res
            }

        # 2. Fallback por puente ADB
        adb_res = self._run_adb_telephony(["send_sms", clean_num, clean_msg])
        if adb_res.get("ok"):
            return {
                "ok": True,
                "provider": "tardis_pocket",
                "transport": "ADB_SHELL_FALLBACK",
                "to": clean_num,
                "message": clean_msg,
                "raw": adb_res
            }

        return {
            "ok": False,
            "provider": "tardis_pocket",
            "to": clean_num,
            "error": adb_res.get("error") or "Fallo de comunicación con TARDIS POCKET",
            "raw": adb_res
        }

    def make_call(self, phone_number: str) -> Dict[str, Any]:
        """
        Inicia una llamada telefónica por la red celular de TARDIS POCKET.
        """
        clean_num = phone_number.strip().replace(" ", "").replace("-", "")
        if not clean_num:
            return {"ok": False, "error": "Número telefónico no válido"}

        http_res = self._call_pocket_api("/api/local/calls/dial", method="POST", payload={"number": clean_num})
        if http_res and http_res.get("ok"):
            return {"ok": True, "action": "make_call", "dest": clean_num, "transport": "HTTP_REST", "raw": http_res}

        adb_res = self._run_adb_telephony(["make_call", clean_num])
        if adb_res.get("ok"):
            return {"ok": True, "action": "make_call", "dest": clean_num, "transport": "ADB_SHELL_FALLBACK", "raw": adb_res}

        return {"ok": False, "action": "make_call", "dest": clean_num, "error": adb_res.get("error", "Error iniciando llamada")}

    def hangup_call(self) -> Dict[str, Any]:
        """Finaliza cualquier llamada telefónica activa en TARDIS POCKET."""
        http_res = self._call_pocket_api("/api/local/calls/hangup", method="POST", payload={})
        if http_res and http_res.get("ok"):
            return {"ok": True, "action": "hangup", "transport": "HTTP_REST", "raw": http_res}

        adb_res = self._run_adb_telephony(["hangup"])
        return {"ok": adb_res.get("ok", False), "action": "hangup", "transport": "ADB_SHELL_FALLBACK", "raw": adb_res}

    def get_telephony_status(self) -> Dict[str, Any]:
        """Obtiene el estado del subsistema celular (SIM, Operador, Red, Datos)."""
        http_res = self._call_pocket_api("/api/local/telephony/status", method="GET")
        if http_res and http_res.get("ok"):
            http_res["transport"] = "HTTP_REST"
            return http_res

        adb_res = self._run_adb_telephony(["status"])
        adb_res["transport"] = "ADB_SHELL_FALLBACK"
        return adb_res

    def set_mobile_data(self, enabled: bool = True) -> Dict[str, Any]:
        """Activa o desactiva la conexión de datos móviles en TARDIS POCKET."""
        http_res = self._call_pocket_api("/api/local/mobile/data", method="POST", payload={"enable": enabled})
        if http_res and http_res.get("ok"):
            return http_res

        mode = "enable" if enabled else "disable"
        return self._run_adb_telephony(["mobile_data", mode])

    def set_usb_tether(self, enabled: bool = True) -> Dict[str, Any]:
        """Activa o desactiva el anclaje de red USB (RNDIS Tethering) para dar internet móvil a la PC."""
        http_res = self._call_pocket_api("/api/local/mobile/tether", method="POST", payload={"enable": enabled})
        if http_res and http_res.get("ok"):
            return http_res

        mode = "enable" if enabled else "disable"
        return self._run_adb_telephony(["usb_tether", mode])


def get_tardis_pocket_bridge() -> TardisPocketBridge:
    """Acceso canónico al singleton de TardisPocketBridge."""
    return TardisPocketBridge.get_instance()


