"""
core/network_controller.py - Controlador Maestro de Redes y Autonomía de Conectividad
=====================================================================================
GODWORKS SYSTEM v26.4 - Suite Soberana de Control Temporal e Inteligencia Causal

Proporciona capacidades integrales para:
  1. Escaneo y análisis del espectro Wi-Fi circundante (SSID, señal, cifrado, canales).
  2. Conexión manual y programática a redes Wi-Fi mediante NetworkManager (`nmcli`).
  3. Diagnóstico de conectividad e internet global en tiempo real (DNS, sockets, ping).
  4. Demonio Centinela de Conectividad (WiFiKeepAliveDaemon):
     - Supervisa la salida a internet cada N segundos.
     - Ante caída de enlace o corte de red, analiza las redes disponibles.
     - Realiza failover automático reconectando a perfiles guardados o redes abiertas.
     - Reanima y notifica al supervisor del túnel Cloudflare para garantizar acceso 24/7.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("godworks.network")


class NetworkController:
    """Controlador unificado de interfaces de red, escaneo Wi-Fi y persistencia de enlace."""

    _instance: Optional["NetworkController"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._nmcli_path = shutil.which("nmcli")
        self._last_scan_time = 0.0
        self._cached_networks: List[Dict[str, Any]] = []
        self._failover_history: List[Dict[str, Any]] = []

    @classmethod
    def get_instance(cls) -> "NetworkController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # -------------------------------------------------------------------------
    # 1. VERIFICACIÓN DE INTERNET GLOBAL
    # -------------------------------------------------------------------------

    def check_internet_access(self, targets: Optional[List[Tuple[str, int]]] = None, timeout: float = 2.0) -> Dict[str, Any]:
        """
        Verifica si el equipo tiene salida real a internet global mediante
        conexiones socket directas a DNS públicos ultrarrápidos (REDACTED_IP, REDACTED_IP, REDACTED_IP).
        """
        if targets is None:
            targets = [("REDACTED_IP", 53), ("REDACTED_IP", 53), ("REDACTED_IP", 53)]

        t0 = time.time()
        for host, port in targets:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(timeout)
                s.connect((host, port))
                s.close()
                latency_ms = round((time.time() - t0) * 1000, 1)
                return {
                    "online": True,
                    "target": host,
                    "latency_ms": latency_ms,
                    "timestamp": time.time()
                }
            except Exception:
                continue

        # Si fallaron los sockets TCP a puerto 53, intentar resolución UDP rápida
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("REDACTED_IP", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return {
                "online": True,
                "target": "REDACTED_IP:80",
                "local_ip": local_ip,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "timestamp": time.time()
            }
        except Exception:
            pass

        return {
            "online": False,
            "target": None,
            "latency_ms": None,
            "timestamp": time.time()
        }

    # -------------------------------------------------------------------------
    # 2. ESCANEO Y ANÁLISIS DE REDES WI-FI CIRCUNDANTES
    # -------------------------------------------------------------------------

    def scan_networks(self, rescan: bool = True, max_age_seconds: float = 10.0) -> Dict[str, Any]:
        """
        Escanea y analiza el espectro Wi-Fi circundante.
        Retorna lista de redes ordenadas por potencia de señal, indicando si son abiertas o cifradas.
        """
        now = time.time()
        if not rescan and self._cached_networks and (now - self._last_scan_time < max_age_seconds):
            return {
                "ok": True,
                "networks": self._cached_networks,
                "count": len(self._cached_networks),
                "cached": True,
                "scan_time": self._last_scan_time
            }

        if not self._nmcli_path:
            return {"ok": False, "error": "nmcli no está instalado en el sistema", "networks": []}

        try:
            # 1. Forzar rescan si se requiere
            if rescan:
                try:
                    subprocess.run(
                        [self._nmcli_path, "dev", "wifi", "rescan"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=4.0
                    )
                except Exception:
                    pass

            # 2. Obtener lista detallada con formato parseable
            # Campos: IN-USE, BSSID, SSID, MODE, CHAN, RATE, SIGNAL, BARS, SECURITY
            cmd = [
                self._nmcli_path, "-t", "-f",
                "IN-USE,BSSID,SSID,MODE,CHAN,RATE,SIGNAL,BARS,SECURITY",
                "dev", "wifi", "list"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=8.0)
            if res.returncode != 0 and not res.stdout:
                return {"ok": False, "error": f"Error ejecutando nmcli: {res.stderr}", "networks": []}

            networks: List[Dict[str, Any]] = []

            for line in res.stdout.strip().split("\n"):
                if not line or not line.strip():
                    continue

                clean_parts = re.split(r"(?<!\\):", line)
                clean_parts = [p.replace(r"\:", ":").strip() for p in clean_parts]

                if len(clean_parts) < 9:
                    continue

                in_use = clean_parts[0] == "*"
                bssid = clean_parts[1]
                ssid = clean_parts[2]
                mode = clean_parts[3]
                chan = clean_parts[4]
                rate = clean_parts[5]
                try:
                    signal = int(clean_parts[6])
                except Exception:
                    signal = 0
                bars = clean_parts[7]
                security = clean_parts[8] if len(clean_parts) > 8 else "--"

                if not ssid:
                    ssid = "[Oculta / BSSID: " + bssid[-8:] + "]"

                is_open = (security in ("--", "", "none", "NONE"))
                net_info = {
                    "ssid": ssid,
                    "bssid": bssid,
                    "in_use": in_use,
                    "signal": signal,
                    "bars": bars,
                    "security": security if security not in ("--", "") else "Abierta (Sin clave)",
                    "is_open": is_open,
                    "channel": chan,
                    "rate": rate,
                    "mode": mode
                }

                networks.append(net_info)

            # Ordenar por potencia de señal descendente
            networks.sort(key=lambda x: (x["in_use"], x["signal"]), reverse=True)
            self._cached_networks = networks
            self._last_scan_time = now

            return {
                "ok": True,
                "networks": networks,
                "count": len(networks),
                "open_networks": [n for n in networks if n["is_open"] and not n["in_use"]],
                "scan_time": now
            }

        except Exception as e:
            return {"ok": False, "error": f"Fallo al escanear redes Wi-Fi: {e}", "networks": []}

    # -------------------------------------------------------------------------
    # 3. ESTADO GENERAL DE CONEXIONES Y PERFILES GUARDADOS
    # -------------------------------------------------------------------------

    def get_saved_connections(self) -> List[Dict[str, Any]]:
        """Devuelve la lista de conexiones y redes guardadas en NetworkManager."""
        if not self._nmcli_path:
            return []
        try:
            cmd = [self._nmcli_path, "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0)
            if res.returncode != 0:
                return []
            conns = []
            for line in res.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(":")
                if len(parts) >= 4:
                    conns.append({
                        "name": parts[0],
                        "uuid": parts[1],
                        "type": parts[2],
                        "device": parts[3] if parts[3] != "--" else None
                    })
            return conns
        except Exception:
            return []

    def get_status(self) -> Dict[str, Any]:
        """Obtiene el diagnóstico completo del estado de redes, IP y salida a internet."""
        inet = self.check_internet_access()
        saved = self.get_saved_connections()
        
        active_conn = None
        wifi_device = None
        devices = []
        if self._nmcli_path:
            try:
                res = subprocess.run(
                    [self._nmcli_path, "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"],
                    capture_output=True, text=True, timeout=3.0
                )
                if res.returncode == 0:
                    for line in res.stdout.strip().split("\n"):
                        p = line.split(":")
                        if len(p) >= 4:
                            dev_info = {"device": p[0], "type": p[1], "state": p[2], "connection": p[3]}
                            devices.append(dev_info)
                            if p[2] == "connected" or p[2] == "conectado":
                                if not active_conn or p[1] == "ethernet":
                                    active_conn = dev_info
                            if p[1] == "wifi":
                                wifi_device = p[0]
            except Exception:
                pass

        lan_ip = "REDACTED_IP"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("REDACTED_IP", 80))
            lan_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass

        return {
            "ok": True,
            "internet_online": inet["online"],
            "internet_latency_ms": inet.get("latency_ms"),
            "lan_ip": lan_ip,
            "active_connection": active_conn,
            "wifi_device": wifi_device,
            "devices": devices,
            "saved_profiles_count": len(saved),
            "timestamp": time.time()
        }

    # -------------------------------------------------------------------------
    # 4. CONEXIÓN DIRECTA A UNA RED WI-FI
    # -------------------------------------------------------------------------

    def connect(self, ssid: str, password: Optional[str] = None, timeout: float = 15.0) -> Dict[str, Any]:
        """
        Conecta el dispositivo a una red Wi-Fi específica usando `nmcli`.
        Si la red ya estaba guardada, `password` puede omitirse.
        """
        if not self._nmcli_path:
            return {"ok": False, "error": "nmcli no disponible"}

        ssid = ssid.strip()
        if not ssid:
            return {"ok": False, "error": "SSID no especificado"}

        cmd = [self._nmcli_path, "dev", "wifi", "connect", ssid]
        if password and password.strip():
            cmd.extend(["password", password.strip()])

        t0 = time.time()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            elapsed = round(time.time() - t0, 2)
            if res.returncode == 0:
                time.sleep(1.5)
                inet = self.check_internet_access(timeout=3.0)
                return {
                    "ok": True,
                    "ssid": ssid,
                    "message": f"Conexión exitosa a '{ssid}' en {elapsed}s",
                    "stdout": res.stdout.strip(),
                    "internet_verified": inet["online"],
                    "latency_ms": inet.get("latency_ms")
                }
            else:
                return {
                    "ok": False,
                    "ssid": ssid,
                    "error": f"Fallo al conectar a '{ssid}': {res.stderr or res.stdout}",
                    "elapsed_s": elapsed
                }
        except subprocess.TimeoutExpired:
            return {"ok": False, "ssid": ssid, "error": f"Tiempo de espera agotado ({timeout}s) conectando a '{ssid}'"}
        except Exception as e:
            return {"ok": False, "ssid": ssid, "error": f"Excepción conectando a '{ssid}': {e}"}

    # -------------------------------------------------------------------------
    # 5. RECONEXIÓN Y FAILOVER AUTÓNOMO DE EMERGENCIA
    # -------------------------------------------------------------------------

    def auto_recover_internet(self, allow_open_networks: bool = True) -> Dict[str, Any]:
        """
        Algoritmo soberano de autorrecuperación de internet:
          1. Verifica si realmente no hay internet.
          2. Escanea el espectro de redes a su alrededor.
          3. Cruza las redes visibles con los perfiles guardados y conocidos.
          4. Intenta conectarse a las redes conocidas por potencia.
          5. Si fallan y se autorizan redes abiertas, intenta enlace a una red abierta.
          6. Verifica restablecimiento de internet global.
        """
        init_check = self.check_internet_access(timeout=1.5)
        if init_check["online"]:
            return {
                "ok": True,
                "recovered": False,
                "reason": "La conexión a internet ya está activa y saludable.",
                "latency_ms": init_check.get("latency_ms")
            }

        incident_record = {
            "timestamp": time.time(),
            "trigger": "Internet caído detectado",
            "actions_taken": [],
            "success": False
        }

        logger.warning("[NETWORK FAILOVER] ⚠️ Internet caído detectado. Iniciando protocolo de recuperación autónoma...")

        scan_res = self.scan_networks(rescan=True)
        networks = scan_res.get("networks", [])
        if not networks:
            incident_record["actions_taken"].append("Escaneo Wi-Fi no encontró redes visibles.")
            self._failover_history.append(incident_record)
            return {"ok": False, "error": "No se detectaron redes Wi-Fi circundantes disponibles."}

        saved = self.get_saved_connections()
        saved_names = {s["name"].lower(): s["name"] for s in saved if s.get("name")}

        known_in_range = []
        open_in_range = []
        for n in networks:
            ssid = n.get("ssid", "")
            if not ssid or ssid.startswith("[Oculta"):
                continue
            if ssid.lower() in saved_names:
                known_in_range.append(n)
            elif n.get("is_open"):
                open_in_range.append(n)

        # 4. Intentar reconectar a redes guardadas
        for net in known_in_range:
            target_ssid = net["ssid"]
            incident_record["actions_taken"].append(f"Intentando reconexión a red conocida '{target_ssid}' (Señal: {net['signal']}%)")
            logger.info(f"[NETWORK FAILOVER] Intentando conectar a red conocida: {target_ssid} (Señal: {net['signal']}%)")
            
            c_res = self.connect(target_ssid, timeout=12.0)
            if c_res.get("ok") and c_res.get("internet_verified"):
                incident_record["success"] = True
                incident_record["recovered_with"] = target_ssid
                self._failover_history.append(incident_record)
                logger.info(f"[NETWORK FAILOVER] ✅ Internet restablecido con éxito a través de '{target_ssid}'!")
                return {
                    "ok": True,
                    "recovered": True,
                    "connected_to": target_ssid,
                    "type": "known_profile",
                    "latency_ms": c_res.get("latency_ms"),
                    "details": incident_record
                }

        # 5. Si no hubo éxito con conocidas y se autorizan redes abiertas
        if allow_open_networks and open_in_range:
            for net in open_in_range:
                target_ssid = net["ssid"]
                incident_record["actions_taken"].append(f"Intentando enlace de emergencia a red abierta '{target_ssid}' (Señal: {net['signal']}%)")
                logger.info(f"[NETWORK FAILOVER] Intentando enlace a red abierta de auxilio: {target_ssid}")
                
                c_res = self.connect(target_ssid, timeout=12.0)
                if c_res.get("ok") and c_res.get("internet_verified"):
                    incident_record["success"] = True
                    incident_record["recovered_with"] = target_ssid
                    self._failover_history.append(incident_record)
                    logger.info(f"[NETWORK FAILOVER] ✅ Internet restablecido con red de auxilio abierta: '{target_ssid}'!")
                    return {
                        "ok": True,
                        "recovered": True,
                        "connected_to": target_ssid,
                        "type": "open_network",
                        "latency_ms": c_res.get("latency_ms"),
                        "details": incident_record
                    }

        incident_record["success"] = False
        incident_record["actions_taken"].append("Todos los intentos de conexión fallaron o no brindaron acceso a internet.")
        self._failover_history.append(incident_record)
        return {
            "ok": False,
            "recovered": False,
            "error": "No fue posible restablecer internet con las redes visibles disponibles.",
            "details": incident_record
        }

    def get_failover_history(self) -> List[Dict[str, Any]]:
        """Devuelve el historial de incidentes de recuperación de red."""
        return self._failover_history[-20:]

    # -------------------------------------------------------------------------
    # 6. HOTSPOT SOBERANO Y PUNTO DE ACCESO ININTERRUMPIDO
    # -------------------------------------------------------------------------

    def ensure_hotspot_active(
        self,
        ssid: str = "TimeMachine",
        password: str = "987654321",
        ifname: str = "wlp3s0",
        band: str = "bg"
    ) -> Dict[str, Any]:
        """
        Asegura que el punto de acceso inalámbrico 'TimeMachine' esté creado,
        configurado para auto-arranque continuo y activo en la interfaz inalámbrica.
        """
        if not self._nmcli_path:
            return {"ok": False, "error": "nmcli no está disponible en este sistema"}

        con_name = f"{ssid}-Hotspot"

        # 1. Verificar si la radio Wi-Fi está encendida
        try:
            r_out = subprocess.run([self._nmcli_path, "radio", "wifi"], capture_output=True, text=True, timeout=5)
            if "desactivado" in r_out.stdout.lower() or "disabled" in r_out.stdout.lower():
                subprocess.run([self._nmcli_path, "radio", "wifi", "on"], capture_output=True, text=True, timeout=5)
        except Exception as e:
            logger.warning(f"Error verificando radio wifi: {e}")

        # 2. Verificar si el perfil de conexión ya existe
        try:
            chk = subprocess.run(
                [self._nmcli_path, "-t", "-f", "NAME,UUID", "connection", "show"],
                capture_output=True,
                text=True,
                timeout=5
            )
            exists = any(line.split(":")[0] == con_name for line in chk.stdout.splitlines() if line)
        except Exception:
            exists = False

        if not exists:
            logger.info(f"[Hotspot] Creando nuevo perfil de punto de acceso: {con_name} (SSID: {ssid})")
            add_cmd = [
                self._nmcli_path, "connection", "add",
                "type", "wifi",
                "ifname", ifname,
                "con-name", con_name,
                "autoconnect", "yes",
                "ssid", ssid,
                "mode", "ap"
            ]
            res = subprocess.run(add_cmd, capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                logger.error(f"[Hotspot] Error creando conexión: {res.stderr}")
                return {"ok": False, "error": res.stderr.strip()}

        # 3. Aplicar configuración de persistencia total, seguridad y DHCP/NAT
        mod_cmd = [
            self._nmcli_path, "connection", "modify", con_name,
            "802-11-wireless.band", band,
            "802-11-wireless-security.key-mgmt", "wpa-psk",
            "802-11-wireless-security.psk", password,
            "802-11-wireless-security.proto", "rsn",
            "802-11-wireless-security.pairwise", "ccmp",
            "802-11-wireless-security.group", "ccmp",
            "ipv4.method", "shared",
            "ipv6.method", "ignore",
            "connection.autoconnect", "yes",
            "connection.autoconnect-priority", "100",
            "connection.autoconnect-retries", "0"
        ]
        subprocess.run(mod_cmd, capture_output=True, text=True, timeout=10)

        # 4. Verificar si está actualmente conectada
        st = self.get_hotspot_status(con_name=con_name, ifname=ifname)
        if not st.get("active"):
            logger.info(f"[Hotspot] Levantando punto de acceso {con_name}...")
            up_res = subprocess.run([self._nmcli_path, "connection", "up", con_name], capture_output=True, text=True, timeout=15)
            if up_res.returncode != 0:
                logger.warning(f"[Hotspot] Advertencia al levantar: {up_res.stderr}")
            st = self.get_hotspot_status(con_name=con_name, ifname=ifname)

        return {"ok": True, "status": st}

    def get_hotspot_status(self, con_name: str = "TimeMachine-Hotspot", ifname: str = "wlp3s0") -> Dict[str, Any]:
        """
        Retorna el estado en tiempo real del punto de acceso Wi-Fi Soberano.
        """
        active = False
        ip_addr = "REDACTED_IP"
        ssid = "TimeMachine"

        if self._nmcli_path:
            try:
                res = subprocess.run(
                    [self._nmcli_path, "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in res.stdout.splitlines():
                    parts = line.split(":")
                    if len(parts) >= 4:
                        dev, dev_type, state, conn = parts[0], parts[1], parts[2], parts[3]
                        if dev == ifname and state.lower() in ("conectado", "connected") and conn == con_name:
                            active = True
                            break
            except Exception as e:
                logger.warning(f"Error consultando estado de hotspot: {e}")

        # Obtener IP de la interfaz
        try:
            ip_res = subprocess.run(["ip", "-4", "addr", "show", ifname], capture_output=True, text=True, timeout=5)
            match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", ip_res.stdout)
            if match:
                ip_addr = match.group(1)
        except Exception:
            pass

        clients = self.get_connected_hotspot_clients(ifname=ifname)

        return {
            "ok": True,
            "active": active,
            "ssid": ssid,
            "password": "•••••••••",
            "raw_password": "987654321",
            "ifname": ifname,
            "connection_name": con_name,
            "gateway_ip": ip_addr,
            "hud_url": f"http://{ip_addr}:8757",
            "client_count": len(clients),
            "clients": clients,
            "timestamp": time.time()
        }

    def get_connected_hotspot_clients(self, ifname: str = "wlp3s0") -> List[Dict[str, Any]]:
        """
        Obtiene los dispositivos clientes conectados al punto de acceso
        inspeccionando la tabla ARP del kernel y las concesiones DHCP de dnsmasq.
        """
        clients = []
        # 1. Leer /proc/net/arp
        try:
            if os.path.exists("/proc/net/arp"):
                with open("/proc/net/arp", "r", encoding="utf-8") as f:
                    lines = f.readlines()[1:]
                    for line in lines:
                        parts = line.split()
                        if len(parts) >= 6:
                            ip, hw_type, flags, mac, mask, dev = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
                            if dev == ifname and mac != "00:00:00:00:00:00" and flags != "0x0":
                                clients.append({
                                    "ip": ip,
                                    "mac": mac.upper(),
                                    "device": dev,
                                    "hostname": "Dispositivo Wi-Fi"
                                })
        except Exception as e:
            logger.warning(f"Error leyendo /proc/net/arp: {e}")

        # 2. Enriquecer con leases de dnsmasq si existe
        lease_path = f"/var/lib/NetworkManager/dnsmasq-{ifname}.leases"
        if os.path.exists(lease_path):
            try:
                with open(lease_path, "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 4:
                            ts, mac, ip, host = parts[0], parts[1].upper(), parts[2], parts[3]
                            found = False
                            for c in clients:
                                if c["mac"] == mac or c["ip"] == ip:
                                    c["hostname"] = host if host != "*" else "Cliente TimeMachine"
                                    found = True
                                    break
                            if not found:
                                clients.append({
                                    "ip": ip,
                                    "mac": mac,
                                    "device": ifname,
                                    "hostname": host if host != "*" else "Cliente TimeMachine"
                                })
            except Exception:
                pass

        return clients

    def stop_hotspot(self, con_name: str = "TimeMachine-Hotspot") -> Dict[str, Any]:
        """Detiene temporalmente el punto de acceso inalámbrico."""
        if not self._nmcli_path:
            return {"ok": False, "error": "nmcli no disponible"}
        res = subprocess.run([self._nmcli_path, "connection", "down", con_name], capture_output=True, text=True, timeout=10)
        return {"ok": res.returncode == 0, "output": res.stdout.strip() or res.stderr.strip()}

    get_connected_clients = get_connected_hotspot_clients


# =============================================================================
# DEMONIO CENTINELA DE RED: WiFiKeepAliveDaemon
# =============================================================================

class WiFiKeepAliveDaemon:
    """
    Hilo centinela en segundo plano que supervisa continuamente el enlace a internet
    y dispara el failover autónomo si detecta un corte en la conexión.
    """

    def __init__(self, check_interval_seconds: float = 25.0, on_recovered_callback=None):
        self.interval = check_interval_seconds
        self.on_recovered_callback = on_recovered_callback
        self.running = False
        self.enabled = True
        self.thread: Optional[threading.Thread] = None
        self.consecutive_failures = 0
        self.last_check_status: Dict[str, Any] = {"online": True}
        self.controller = NetworkController.get_instance()

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True, name="WiFiKeepAliveDaemon")
        self.thread.start()
        logger.info("[WiFiKeepAliveDaemon] Centinela de conectividad 24/7 iniciado.")

    def stop(self):
        self.running = False

    def set_enabled(self, enabled: bool):
        self.enabled = enabled

    def _loop(self):
        time.sleep(5)
        while self.running:
            try:
                if self.enabled:
                    chk = self.controller.check_internet_access(timeout=2.0)
                    self.last_check_status = chk
                    if chk["online"]:
                        self.consecutive_failures = 0
                    else:
                        self.consecutive_failures += 1
                        logger.warning(f"[WiFiKeepAliveDaemon] Fallo de conectividad #{self.consecutive_failures}")

                        if self.consecutive_failures >= 2:
                            logger.error("[WiFiKeepAliveDaemon] 🚨 Pérdida sostenida de internet. Activando protocolo de failover...")
                            recover_res = self.controller.auto_recover_internet()
                            if recover_res.get("recovered"):
                                self.consecutive_failures = 0
                                if self.on_recovered_callback:
                                    try:
                                        self.on_recovered_callback(recover_res)
                                    except Exception:
                                        pass

            except Exception as e:
                logger.error(f"[WiFiKeepAliveDaemon] Error en ciclo de supervisión: {e}")

            time.sleep(self.interval)

    def get_status(self) -> Dict[str, Any]:
        return {
            "daemon_running": self.running,
            "enabled": self.enabled,
            "interval_seconds": self.interval,
            "consecutive_failures": self.consecutive_failures,
            "last_check": self.last_check_status,
            "incidents_logged": len(self.controller.get_failover_history())
        }


# Instancia Global
def get_network_controller() -> NetworkController:
    return NetworkController.get_instance()
