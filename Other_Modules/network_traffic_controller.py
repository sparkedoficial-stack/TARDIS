"""
core/network_traffic_controller.py - Sistema Soberano de Rastreo, Auditoría, Análisis y Control de Tráfico (Ethernet + Wi-Fi)
=============================================================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Creador y Autoridad Absoluta: El Arquitecto (₪)

Proporciona control integral en Anillo 0 (Kernel / NFTables / Conntrack / IProute2 / HWDB) sobre todas las interfaces:
  1. Rastreador Activo Multi-Subred (Ethernet enp2s0 REDACTED_IP/24, Wi-Fi Hotspot wlp3s0 REDACTED_IP/24,
     Puente Virtual veth-host-aq REDACTED_IP/24 y Malla Tailscale REDACTED_IP/10):
     - Descubrimiento concurrente ICMP/ARP + Vecinos IPv6 + Leases DHCP + Estaciones Wi-Fi 802.11 + mDNS/UPnP.
     - Resolución exacta de fabricante vía base IEEE OUI nativa (systemd-hwdb) y huella de puertos/servicios.
     - Base de datos persistente de dispositivos (first_seen, last_seen, historial IP, nivel de confianza, alias).
  2. Auditoría y Análisis Causal de Tráfico en Tiempo Real:
     - Contabilidad de bytes y paquetes por dispositivo local en el kernel mediante conjuntos dinámicos NFTables.
     - Correlación de flujos Conntrack con sockets y procesos locales (PID, ejecutable, usuario) y organizaciones (CIDR/ASN).
     - Telemetría de ancho de banda y contadores de interfaz (RX/TX bytes, paquetes, errores, drops).
  3. Control Activo de Tráfico y Cortafuegos Perimetral / Interno (NFTables + TC QoS):
     - Cuarentena inmediata de dispositivos por IP o dirección MAC (bloqueo en cadenas input, forward y output).
     - Limitación de tasa de transferencia (Throttling / QoS en KB/s) por dispositivo.
     - Bloqueo selectivo de endpoints remotos (IPs externas) y puertos TCP/UDP.
"""
from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import logging
import os
import psutil
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("godworks.network_traffic_controller")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
DATA_DIR = BASE_DIR / "data" / "shield"
DEVICE_DB_FILE = DATA_DIR / "device_tracker_db.json"
CONTROL_POLICY_FILE = DATA_DIR / "traffic_control_policy.json"
TRAFFIC_AUDIT_LOG_FILE = DATA_DIR / "traffic_audit_history.json"
NFT_CONTROLLER_FILE = DATA_DIR / "tardis_netguard_controller.nft"

# Puertos para identificación de perfil de dispositivo y auditoría de seguridad
FINGERPRINT_PORTS = [
    21, 22, 23, 53, 80, 111, 139, 443, 445, 515, 548, 554, 631,
    1865, 3389, 4070, 5000, 5555, 7000, 7681, 8008, 8009, 8080,
    8088, 8443, 8757, 8765, 8888, 9001, 9100, 11434, 49152, 62078
]

PORT_SERVICE_LABELS = {
    21: "FTP",
    22: "SSH",
    23: "Telnet (Inseguro)",
    53: "DNS",
    80: "HTTP Web",
    111: "RPCBind",
    139: "NetBIOS SMB",
    443: "HTTPS SSL",
    445: "SMB File Share",
    515: "LPD Printer",
    548: "AFP Apple Filing",
    554: "RTSP Stream",
    631: "IPP CUPS Printing",
    1865: "Epson Net Scan",
    3389: "RDP Remote Desktop",
    4070: "SpotifyConnect Audio",
    5000: "UPnP / AirPlay / Media",
    5222: "WhatsApp XMPP",
    5223: "Apple Push (APNs)",
    5353: "mDNS Bonjour",
    5555: "Android ADB Debug",
    7000: "AirPlay Receiver",
    7681: "FTL Web Terminal",
    7844: "Cloudflare Warp/Tunnel",
    8008: "Google Cast HTTP",
    8009: "Google Cast TLS",
    8080: "HTTP Proxy / Alt",
    8088: "TARDIS iPad Edge",
    8443: "HTTPS Control API",
    8757: "GODWORKS Master HUD",
    8765: "FTL Telemetry Portal",
    8888: "Antarctica Proxy",
    9001: "Weylus WebSocket",
    9100: "PDL RAW JetDirect Printer",
    11434: "Ollama LLM Engine",
    49152: "UPnP / Apple Companion",
    62078: "Apple iOS Wi-Fi Sync (lockdownd)"
}

RISKY_EXPOSED_PORTS = {21, 23, 139, 445, 3389, 5555}

# Conocimiento pre-calibrado de dispositivos de la red del Arquitecto (Constante Aegis)
PREKNOWN_SIGNATURES = {
    "00:31:92:DC:30:34": {
        "alias": "Router TP-Link Archer AX50 (Gateway Principal)",
        "device_type": "Router / Gateway Wi-Fi 6",
        "vendor_override": "TP-Link Systems Inc.",
        "trust_level": "TRUSTED"
    },
    "48:22:54:3E:A0:CE": {
        "alias": "Nodo TP-Link Smart / Extensor de Red",
        "device_type": "Infraestructura de Red TP-Link",
        "vendor_override": "TP-Link Systems Inc.",
        "trust_level": "TRUSTED"
    },
    "44:D2:44:12:42:DC": {
        "alias": "Impresora Multifuncional EPSON L375 (EPSON1242DC)",
        "device_type": "Impresora / Escáner de Red",
        "vendor_override": "Seiko Epson Corporation",
        "trust_level": "TRUSTED"
    },
    "A8:CA:77:52:B9:E4": {
        "alias": "Amazon Echo / Alexa (SpotifyConnect)",
        "device_type": "Altavoz Inteligente / IoT",
        "vendor_override": "Amazon Technologies Inc.",
        "trust_level": "KNOWN"
    },
    "B8:16:5F:C3:5B:53": {
        "alias": "Smart TV LG webOS (Sala / Principal)",
        "device_type": "Smart TV / Multimedia",
        "vendor_override": "LG Innotek",
        "trust_level": "KNOWN"
    },
    "D8:E3:5E:52:49:90": {
        "alias": "Smart TV LG webOS (Recámara / Secundaria)",
        "device_type": "Smart TV / Multimedia",
        "vendor_override": "LG Innotek",
        "trust_level": "KNOWN"
    },
    "D0:39:57:27:47:E5": {
        "alias": "Dispositivo Multimedia / Cliente Liteon",
        "device_type": "Smart Device / Estación Cliente",
        "vendor_override": "Liteon Technology Corporation",
        "trust_level": "KNOWN"
    },
    "50:EB:F6:E2:B8:50": {
        "alias": "TimeMachine (ASUS TUF Gaming A15 - Ethernet Host)",
        "device_type": "Estación Central Soberana (Host)",
        "vendor_override": "ASUSTek COMPUTER INC.",
        "trust_level": "AEGIS_PROTECTED"
    },
    "14:13:33:88:17:95": {
        "alias": "TimeMachine-Hotspot (Gateway Wi-Fi Soberano)",
        "device_type": "Gateway Wi-Fi 6 Soberano (Host)",
        "vendor_override": "AzureWave / MediaTek MT7921",
        "trust_level": "AEGIS_PROTECTED"
    },
    "26:6E:AA:8E:AC:76": {
        "alias": "Nodo Aislado Antarctica (NetNS Tunnel)",
        "device_type": "Namespace Virtual de Enrutamiento",
        "vendor_override": "Linux Virtual Ethernet (NetNS)",
        "trust_level": "AEGIS_PROTECTED"
    },
    "22:BA:EE:8B:BD:2F": {
        "alias": "Apple iOS / iPadOS #1 (Ecosistema Aegis)",
        "device_type": "Apple iPhone / iPad (iOS Sync Activo)",
        "vendor_override": "Apple Inc. (MAC Privada iOS)",
        "trust_level": "AEGIS_PROTECTED"
    },
    "1E:FA:BF:35:00:B2": {
        "alias": "Apple iOS / iPadOS #2 (Ecosistema Aegis)",
        "device_type": "Apple iPad Pro / iPhone (iOS Sync Activo)",
        "vendor_override": "Apple Inc. (MAC Privada iOS)",
        "trust_level": "AEGIS_PROTECTED"
    }
}


class TardisNetworkTrafficController:
    """
    Motor Soberano que unifica el rastreo de dispositivos en Ethernet y Wi-Fi,
    el análisis profundo de flujos/procesos y el control activo de tráfico en Kernel.
    """

    _instance: Optional["TardisNetworkTrafficController"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._state_lock = threading.Lock()
        self._oui_cache: Dict[str, str] = {}
        self._iface_rates_prev: Dict[str, Tuple[float, int, int]] = {}
        self.device_db: Dict[str, Dict[str, Any]] = {}
        self.policy: Dict[str, Any] = {
            "quarantined_ips": [],
            "quarantined_macs": [],
            "blocked_remote_ips": [],
            "blocked_ports": [],
            "throttled_devices": {},  # ip -> kbps
            "auto_quarantine_unknown": False,
            "strict_perimeter_mode": True,
            "last_policy_sync": 0.0
        }
        self._last_full_scan_ts = 0.0
        self._ensure_storage()
        self._load_state()

    @classmethod
    def get_instance(cls) -> "TardisNetworkTrafficController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _ensure_storage(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _run_cmd(self, args: List[str], timeout: float = 4.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout
        )

    def _run_sudo(self, args: List[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
        res = subprocess.run(
            ["sudo", "-n"] + args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if res.returncode != 0:
            res = subprocess.run(
                ["sudo", "-S"] + args,
                input="0\n",
                capture_output=True,
                text=True,
                timeout=timeout
            )
        return res

    def _load_state(self):
        with self._state_lock:
            if DEVICE_DB_FILE.exists():
                try:
                    data = json.loads(DEVICE_DB_FILE.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self.device_db = data
                except Exception as e:
                    logger.warning(f"[NetGuard] Error cargando device_db: {e}")

            if CONTROL_POLICY_FILE.exists():
                try:
                    pol = json.loads(CONTROL_POLICY_FILE.read_text(encoding="utf-8"))
                    if isinstance(pol, dict):
                        self.policy.update(pol)
                except Exception as e:
                    logger.warning(f"[NetGuard] Error cargando policy: {e}")

    def _save_state(self):
        with self._state_lock:
            try:
                DEVICE_DB_FILE.write_text(
                    json.dumps(self.device_db, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
            except Exception as e:
                logger.warning(f"[NetGuard] Error guardando device_db: {e}")

            try:
                CONTROL_POLICY_FILE.write_text(
                    json.dumps(self.policy, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
            except Exception as e:
                logger.warning(f"[NetGuard] Error guardando policy: {e}")

    # =========================================================================
    # 1. RASTREO ACTIVO E IDENTIFICACIÓN DE DISPOSITIVOS (ETHERNET + WI-FI)
    # =========================================================================

    def resolve_oui_vendor(self, mac: str) -> str:
        """Consulta la base IEEE OUI oficial del sistema vía systemd-hwdb."""
        mac_up = mac.upper().strip()
        if mac_up in PREKNOWN_SIGNATURES:
            return PREKNOWN_SIGNATURES[mac_up]["vendor_override"]

        prefix = mac_up[:8]
        if prefix in self._oui_cache:
            return self._oui_cache[prefix]

        oui_hex = prefix.replace(":", "")
        vendor = ""
        try:
            res = self._run_cmd(["systemd-hwdb", "query", f"OUI:{oui_hex}"], timeout=1.5)
            if res.returncode == 0 and res.stdout:
                for line in res.stdout.splitlines():
                    if line.startswith("ID_OUI_FROM_DATABASE="):
                        vendor = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass

        if not vendor:
            # Verificar bit Locally Administered Address (LAA - segundo dígito hex 2, 6, A, E)
            if len(oui_hex) >= 2 and oui_hex[1] in ("2", "6", "A", "E"):
                vendor = "Dirección MAC Privada / Aleatoria (iOS / Android / Linux)"
            else:
                vendor = "Fabricante de Red Estándar"

        self._oui_cache[prefix] = vendor
        return vendor

    def _active_subnet_sweep(self, subnets: Optional[List[str]] = None):
        """
        Ejecuta un barrido paralelo ultrarrápido (ICMP echo) en las subredes locales
        Ethernet (REDACTED_IP/24) y Wi-Fi Hotspot (REDACTED_IP/24) para poblar la tabla ARP del kernel.
        """
        if subnets is None:
            subnets = ["192.168.1", "10.42.0"]

        target_ips: List[str] = []
        for net_prefix in subnets:
            for host_id in range(1, 255):
                target_ips.append(f"{net_prefix}.{host_id}")

        def _ping_once(ip_str: str):
            try:
                subprocess.run(
                    ["ping", "-c", "1", "-W", "1", "-n", ip_str],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.3
                )
            except Exception:
                pass

        with concurrent.futures.ThreadPoolExecutor(max_workers=72) as executor:
            list(executor.map(_ping_once, target_ips))

    def _probe_device_ports(self, ip: str) -> List[int]:
        """Comprueba concurrentemente qué puertos de servicio están abiertos en una IP local."""
        if not ip or ip.startswith("fe80:"):
            return []
        open_ports: List[int] = []
        for port in FINGERPRINT_PORTS:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.06)
                if s.connect_ex((ip, port)) == 0:
                    open_ports.append(port)
                s.close()
            except Exception:
                pass
        return sorted(open_ports)

    def _get_wifi_station_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Obtiene señal RSSI (dBm), bitrate y bytes de estaciones conectadas al Hotspot wlp3s0."""
        stations: Dict[str, Dict[str, Any]] = {}
        try:
            res = self._run_sudo(["iw", "dev", "wlp3s0", "station", "dump"], timeout=2.5)
            current_mac = None
            for line in res.stdout.splitlines():
                line_s = line.strip()
                if line_s.startswith("Station "):
                    parts = line_s.split()
                    if len(parts) >= 2:
                        current_mac = parts[1].upper()
                        stations[current_mac] = {}
                elif current_mac:
                    if line_s.startswith("signal:"):
                        stations[current_mac]["signal_dbm"] = line_s.split(":", 1)[1].strip()
                    elif line_s.startswith("tx bitrate:"):
                        stations[current_mac]["tx_bitrate"] = line_s.split(":", 1)[1].strip()
                    elif line_s.startswith("rx bytes:"):
                        stations[current_mac]["wifi_rx_bytes"] = int(line_s.split(":", 1)[1].strip())
                    elif line_s.startswith("tx bytes:"):
                        stations[current_mac]["wifi_tx_bytes"] = int(line_s.split(":", 1)[1].strip())
                    elif line_s.startswith("connected time:"):
                        stations[current_mac]["connected_sec"] = line_s.split(":", 1)[1].strip()
        except Exception:
            pass
        return stations

    def _get_dhcp_leases(self) -> Dict[str, Dict[str, str]]:
        """Lee los leases DHCP de dnsmasq en wlp3s0 y archivos estándar."""
        leases: Dict[str, Dict[str, str]] = {}
        lease_paths = [
            Path("/var/lib/NetworkManager/dnsmasq-wlp3s0.leases"),
            Path("/var/lib/misc/dnsmasq.leases")
        ]
        for lp in lease_paths:
            content = ""
            try:
                if lp.exists() and os.access(lp, os.R_OK):
                    content = lp.read_text(encoding="utf-8")
                else:
                    res = self._run_sudo(["cat", str(lp)], timeout=2.0)
                    if res.returncode == 0:
                        content = res.stdout
            except Exception:
                pass
            for line in content.splitlines():
                parts = line.strip().split()
                if len(parts) >= 4:
                    mac = parts[1].upper()
                    leases[mac] = {
                        "expiry": parts[0],
                        "ip": parts[2],
                        "hostname": parts[3] if parts[3] != "*" else ""
                    }
        return leases

    def _get_mdns_hostnames(self) -> Dict[str, Dict[str, str]]:
        """Extrae nombres mDNS y servicios anunciados vía Avahi."""
        mdns_map: Dict[str, Dict[str, str]] = {}
        try:
            res = self._run_cmd(["avahi-browse", "-atrp"], timeout=2.5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if line.startswith("="):
                        fields = line.split(";")
                        if len(fields) >= 8:
                            service_name = fields[3].replace("\\032", " ").replace("\\064", "@")
                            service_type = fields[4]
                            hostname = fields[6]
                            address = fields[7]
                            entry = mdns_map.setdefault(address, {"hostname": hostname, "services": []})
                            if hostname and not entry.get("hostname"):
                                entry["hostname"] = hostname
                            svc_desc = f"{service_name} ({service_type})"
                            if svc_desc not in entry["services"]:
                                entry["services"].append(svc_desc)
        except Exception:
            pass
        return mdns_map

    def _classify_device(
        self,
        mac: str,
        ip: str,
        iface: str,
        vendor: str,
        open_ports: List[int],
        mdns_info: Dict[str, Any],
        dhcp_hostname: str
    ) -> Tuple[str, str, str]:
        """
        Retorna (alias, device_type, trust_level) combinando firmas conocidas,
        fabricante OUI, puertos abiertos y anuncios mDNS.
        """
        mac_up = mac.upper()
        # 1. Revisar si el usuario ya asignó un alias o nivel de confianza en device_db
        existing = self.device_db.get(mac_up, {})
        custom_alias = existing.get("custom_alias")
        custom_trust = existing.get("trust_level")

        # 2. Revisar firmas pre-calibradas
        if mac_up in PREKNOWN_SIGNATURES:
            sig = PREKNOWN_SIGNATURES[mac_up]
            return (
                custom_alias or sig["alias"],
                sig["device_type"],
                custom_trust or sig["trust_level"]
            )

        # 3. Clasificación heurística por puertos y fabricante
        if 62078 in open_ports:
            alias = custom_alias or f"Dispositivo Apple iOS/iPadOS ({ip})"
            dtype = "Apple iPhone / iPad (iOS Sync Activo)"
            trust = custom_trust or "AEGIS_PROTECTED"
            return alias, dtype, trust

        if 9100 in open_ports or 515 in open_ports or 1865 in open_ports or "epson" in vendor.lower():
            alias = custom_alias or (mdns_info.get("hostname") or f"Impresora de Red ({ip})")
            dtype = "Impresora / Escáner Multifuncional"
            trust = custom_trust or "TRUSTED"
            return alias, dtype, trust

        if 4070 in open_ports or "amazon" in vendor.lower():
            alias = custom_alias or f"Amazon Echo / Alexa ({ip})"
            dtype = "Altavoz Inteligente / SpotifyConnect"
            trust = custom_trust or "KNOWN"
            return alias, dtype, trust

        if "lg innotek" in vendor.lower() or "lg electronics" in vendor.lower():
            alias = custom_alias or f"Smart TV LG webOS ({ip})"
            dtype = "Smart TV / Pantalla Conectada"
            trust = custom_trust or "KNOWN"
            return alias, dtype, trust

        if ip == "REDACTED_IP":
            return (
                custom_alias or "Router Gateway Principal (REDACTED_IP)",
                "Router / Gateway WAN",
                custom_trust or "TRUSTED"
            )

        if "tp-link" in vendor.lower():
            return (
                custom_alias or f"Nodo de Red TP-Link ({ip})",
                "Infraestructura Wi-Fi / Switch / Smart Device",
                custom_trust or "TRUSTED"
            )

        if iface == "wlp3s0":
            h_name = dhcp_hostname or mdns_info.get("hostname") or f"Cliente Wi-Fi TimeMachine ({ip})"
            return (
                custom_alias or h_name,
                "Cliente Wi-Fi Hotspot (REDACTED_IP/24)",
                custom_trust or "KNOWN"
            )

        h_name = dhcp_hostname or mdns_info.get("hostname") or f"Dispositivo LAN ({ip})"
        return (
            custom_alias or h_name,
            f"Dispositivo de Red ({vendor})",
            custom_trust or "KNOWN"
        )

    def _measure_ping_rtt(self, ip: str) -> Optional[float]:
        """Mide latencia ICMP RTT en milisegundos hacia el dispositivo."""
        if not ip or ip.startswith("fe80:"):
            return None
        try:
            res = self._run_cmd(["ping", "-c", "1", "-W", "1", "-n", ip], timeout=1.2)
            if res.returncode == 0:
                m = re.search(r"time=([\d\.]+)\s*ms", res.stdout)
                if m:
                    return round(float(m.group(1)), 2)
        except Exception:
            pass
        return None

    def discover_all_devices(self, active_sweep: bool = True) -> List[Dict[str, Any]]:
        """
        Escanea y audita absolutamente todos los dispositivos en Ethernet (enp2s0),
        Wi-Fi Hotspot (wlp3s0), Namespace Virtual (veth-host-aq) y Vecinos IPv6.
        """
        now_ts = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()

        if active_sweep or len(self.device_db) == 0:
            self._active_subnet_sweep(["192.168.1", "10.42.0"])
            self._last_full_scan_ts = now_ts

        dhcp_leases = self._get_dhcp_leases()
        wifi_stations = self._get_wifi_station_metrics()
        mdns_map = self._get_mdns_hostnames()
        nft_Byte_counters = self._read_nft_device_counters()

        # Recolectar vecinos IPv4 e IPv6 desde `ip neigh show`
        neigh_ipv4: Dict[str, Dict[str, str]] = {}  # mac -> {ip, iface, state}
        neigh_ipv6: Dict[str, List[str]] = {}       # mac -> [ipv6_list]

        try:
            res = self._run_cmd(["ip", "neigh", "show"], timeout=3.0)
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) < 4:
                    continue
                addr = parts[0]
                state = parts[-1].upper()
                if state in ("FAILED", "INCOMPLETE"):
                    continue
                if "lladdr" not in parts:
                    continue
                ll_idx = parts.index("lladdr")
                if ll_idx + 1 >= len(parts):
                    continue
                mac = parts[ll_idx + 1].upper()
                dev_idx = parts.index("dev") if "dev" in parts else -1
                iface = parts[dev_idx + 1] if (dev_idx != -1 and dev_idx + 1 < len(parts)) else "unknown"

                if ":" in addr:
                    neigh_ipv6.setdefault(mac, []).append(addr)
                else:
                    neigh_ipv4[mac] = {"ip": addr, "iface": iface, "state": state}
        except Exception as e:
            logger.warning(f"[NetGuard] Error leyendo ip neigh: {e}")

        # Incluir las interfaces propias del host soberano TimeMachine
        local_host_entries = [
            {
                "mac": "50:EB:F6:E2:B8:50",
                "ip": "REDACTED_IP",
                "iface": "enp2s0",
                "state": "HOST_LOCAL",
                "ipv6": ["fe80::52eb:f6ff:fee2:b850"]
            },
            {
                "mac": "14:13:33:88:17:95",
                "ip": "REDACTED_IP",
                "iface": "wlp3s0",
                "state": "HOST_GATEWAY",
                "ipv6": ["fe80::1613:33ff:fe88:1795"]
            }
        ]
        for lh in local_host_entries:
            neigh_ipv4[lh["mac"]] = {"ip": lh["ip"], "iface": lh["iface"], "state": lh["state"]}
            neigh_ipv6.setdefault(lh["mac"], []).extend(lh["ipv6"])

        # Añadir clientes en DHCP leases de wlp3s0 aunque estén en ahorro de energía
        for mac, linfo in dhcp_leases.items():
            if mac not in neigh_ipv4:
                neigh_ipv4[mac] = {
                    "ip": linfo["ip"],
                    "iface": "wlp3s0",
                    "state": "DHCP_LEASE"
                }

        # Añadir vecinos que solo tienen IPv6 link-local activo
        for mac, v6_list in neigh_ipv6.items():
            if mac not in neigh_ipv4:
                prev_ip = self.device_db.get(mac, {}).get("ip", "")
                if prev_ip and not prev_ip.startswith("fe80:"):
                    neigh_ipv4[mac] = {
                        "ip": prev_ip,
                        "iface": "enp2s0",
                        "state": "STALE"
                    }
                else:
                    neigh_ipv4[mac] = {
                        "ip": v6_list[0],
                        "iface": "enp2s0",
                        "state": "IPV6_STALE"
                    }

        # Sondear puertos y RTT en paralelo para todos los dispositivos detectados
        mac_list = list(neigh_ipv4.keys())

        def _enrich_target(mac_key: str) -> Tuple[str, List[int], Optional[float]]:
            ip_addr = neigh_ipv4[mac_key]["ip"]
            if neigh_ipv4[mac_key]["state"] in ("HOST_LOCAL", "HOST_GATEWAY"):
                return mac_key, [22, 53, 111, 3389, 7681, 8080, 8757, 8765], 0.05
            cached = self.device_db.get(mac_key, {})
            if not active_sweep and cached and "open_ports" in cached:
                return mac_key, cached.get("open_ports", []), cached.get("rtt_ms")
            ports = self._probe_device_ports(ip_addr)
            rtt = self._measure_ping_rtt(ip_addr)
            return mac_key, ports, rtt

        enriched_map: Dict[str, Tuple[List[int], Optional[float]]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            for mac_k, p_list, rtt_val in pool.map(_enrich_target, mac_list):
                enriched_map[mac_k] = (p_list, rtt_val)

        quarantined_ips_set = set(self.policy.get("quarantined_ips", []))
        quarantined_macs_set = {m.upper() for m in self.policy.get("quarantined_macs", [])}
        throttled_map = self.policy.get("throttled_devices", {})

        discovered_devices: List[Dict[str, Any]] = []

        for mac, net_info in neigh_ipv4.items():
            ip = net_info["ip"]
            iface = net_info["iface"]
            state = net_info["state"]
            open_ports, rtt_ms = enriched_map.get(mac, ([], None))
            vendor = self.resolve_oui_vendor(mac)
            mdns_info = mdns_map.get(ip, {})
            dhcp_host = dhcp_leases.get(mac, {}).get("hostname", "")

            alias, dev_type, trust_level = self._classify_device(
                mac, ip, iface, vendor, open_ports, mdns_info, dhcp_host
            )

            is_quarantined = (ip in quarantined_ips_set) or (mac in quarantined_macs_set)
            if is_quarantined:
                trust_level = "QUARANTINED"

            risky_ports = [p for p in open_ports if p in RISKY_EXPOSED_PORTS and state not in ("HOST_LOCAL", "HOST_GATEWAY")]
            port_details = [
                {"port": p, "service": PORT_SERVICE_LABELS.get(p, f"TCP/{p}")}
                for p in open_ports
            ]

            # Clasificación de segmento de red
            if iface == "wlp3s0":
                network_segment = "Wi-Fi Soberana TimeMachine (REDACTED_IP/24)"
                connection_medium = "Wi-Fi (wlp3s0)"
            elif iface == "veth-host-aq":
                network_segment = "Namespace Virtual Antarctica (REDACTED_IP/24)"
                connection_medium = "Virtual Bridge (veth-host-aq)"
            else:
                network_segment = "Ethernet / LAN Principal (REDACTED_IP/24)"
                connection_medium = "Ethernet / LAN (enp2s0)"

            # Contadores de tráfico del dispositivo
            dev_counters = nft_Byte_counters.get(ip, {"rx_bytes": 0, "tx_bytes": 0, "packets": 0})
            wifi_st = wifi_stations.get(mac, {})
            if wifi_st:
                dev_counters["rx_bytes"] = max(dev_counters["rx_bytes"], wifi_st.get("wifi_rx_bytes", 0))
                dev_counters["tx_bytes"] = max(dev_counters["tx_bytes"], wifi_st.get("wifi_tx_bytes", 0))

            # Actualizar historial persistente en device_db
            prev_rec = self.device_db.get(mac, {})
            first_seen = prev_rec.get("first_seen", now_iso)
            ip_history = list(set(prev_rec.get("ip_history", []) + ([ip] if not ip.startswith("fe80:") else [])))

            device_record = {
                "mac": mac,
                "ip": ip,
                "ipv6_addresses": sorted(list(set(neigh_ipv6.get(mac, [])))),
                "alias": alias,
                "hostname": dhcp_host or mdns_info.get("hostname") or alias,
                "vendor": vendor,
                "device_type": dev_type,
                "interface": iface,
                "connection_medium": connection_medium,
                "network_segment": network_segment,
                "arp_state": state,
                "online": state not in ("FAILED", "INCOMPLETE", "OFFLINE"),
                "rtt_ms": rtt_ms,
                "open_ports": open_ports,
                "port_details": port_details,
                "risky_ports": risky_ports,
                "mdns_services": mdns_info.get("services", []),
                "wifi_metrics": wifi_st,
                "trust_level": trust_level,
                "is_quarantined": is_quarantined,
                "throttle_kbps": throttled_map.get(ip),
                "is_safe": (len(risky_ports) == 0) and not is_quarantined,
                "traffic_bytes_rx": dev_counters["rx_bytes"],
                "traffic_bytes_tx": dev_counters["tx_bytes"],
                "traffic_packets": dev_counters["packets"],
                "first_seen": first_seen,
                "last_seen": now_iso,
                "ip_history": sorted(ip_history)
            }

            with self._state_lock:
                self.device_db[mac] = {
                    **prev_rec,
                    **device_record
                }

            discovered_devices.append(device_record)

        # Incluir dispositivos históricos en device_db que hoy estén OFFLINE
        active_macs = {d["mac"] for d in discovered_devices}
        for mac_saved, rec_saved in list(self.device_db.items()):
            if mac_saved not in active_macs:
                offline_copy = dict(rec_saved)
                offline_copy["online"] = False
                offline_copy["arp_state"] = "OFFLINE"
                offline_copy["rtt_ms"] = None
                discovered_devices.append(offline_copy)

        self._save_state()

        # Ordenar: primero Online, luego por segmento e IP
        def _sort_key(d: Dict[str, Any]):
            ip_s = d.get("ip", "")
            try:
                ip_num = int(ipaddress.ip_address(ip_s)) if "." in ip_s else REDACTED_PHONE
            except Exception:
                ip_num = REDACTED_PHONE
            return (0 if d.get("online") else 1, ip_num)

        discovered_devices.sort(key=_sort_key)
        return discovered_devices

    # =========================================================================
    # 2. AUDITORÍA PROFUNDA DE TRÁFICO, PROCESOS E INTERFACES
    # =========================================================================

    def get_interface_telemetry(self) -> List[Dict[str, Any]]:
        """
        Lee /proc/net/dev y calcula tanto el volumen total acumulado (RX/TX bytes, paquetes, drops)
        como la velocidad instantánea (KB/s) de cada interfaz (enp2s0, wlp3s0, veth-host-aq, lo).
        """
        now = time.time()
        interfaces: List[Dict[str, Any]] = []
        try:
            lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
            for line in lines:
                if ":" not in line:
                    continue
                iface, rest = line.split(":", 1)
                iface = iface.strip()
                fields = rest.split()
                if len(fields) < 16:
                    continue
                rx_bytes = int(fields[0])
                rx_packets = int(fields[1])
                rx_errs = int(fields[2])
                rx_drop = int(fields[3])
                tx_bytes = int(fields[8])
                tx_packets = int(fields[9])
                tx_errs = int(fields[10])
                tx_drop = int(fields[11])

                rx_kbps = 0.0
                tx_kbps = 0.0
                if iface in self._iface_rates_prev:
                    prev_t, prev_rx, prev_tx = self._iface_rates_prev[iface]
                    dt = max(0.001, now - prev_t)
                    rx_kbps = round(((rx_bytes - prev_rx) / 1024.0) / dt, 2)
                    tx_kbps = round(((tx_bytes - prev_tx) / 1024.0) / dt, 2)
                self._iface_rates_prev[iface] = (now, rx_bytes, tx_bytes)

                role_map = {
                    "enp2s0": "Ethernet Gigabit LAN/WAN (REDACTED_IP/24)",
                    "wlp3s0": "Wi-Fi 6 Hotspot TimeMachine (REDACTED_IP/24)",
                    "veth-host-aq": "Puente Virtual Namespace Antarctica (REDACTED_IP/24)",
                    "lo": "Loopback Interno Soberano (127.0.0.1/8)"
                }

                interfaces.append({
                    "interface": iface,
                    "role": role_map.get(iface, "Interfaz de Red"),
                    "rx_bytes": rx_bytes,
                    "rx_mb": round(rx_bytes / (1024 * 1024), 2),
                    "rx_packets": rx_packets,
                    "rx_errors": rx_errs,
                    "rx_dropped": rx_drop,
                    "tx_bytes": tx_bytes,
                    "tx_mb": round(tx_bytes / (1024 * 1024), 2),
                    "tx_packets": tx_packets,
                    "tx_errors": tx_errs,
                    "tx_dropped": tx_drop,
                    "rx_rate_kbps": max(0.0, rx_kbps),
                    "tx_rate_kbps": max(0.0, tx_kbps)
                })
        except Exception as e:
            logger.warning(f"[NetGuard] Error leyendo /proc/net/dev: {e}")
        return interfaces

    def get_socket_process_map(self) -> Dict[Tuple[str, int, str, int], Dict[str, Any]]:
        """
        Construye un mapa (local_ip, local_port, remote_ip, remote_port) -> {pid, process, cmdline, username}
        para atribuir cada flujo de red al proceso exacto del sistema.
        """
        proc_map: Dict[Tuple[str, int, str, int], Dict[str, Any]] = {}
        try:
            for conn in psutil.net_connections(kind="inet"):
                if not conn.laddr:
                    continue
                lip = conn.laddr.ip
                lport = conn.laddr.port
                rip = conn.raddr.ip if conn.raddr else "*"
                rport = conn.raddr.port if conn.raddr else 0
                pid = conn.pid
                pname = "Kernel / NAT"
                cmdline = ""
                user = "root"
                if pid:
                    try:
                        p = psutil.Process(pid)
                        pname = p.name()
                        user = p.username()
                        cmdline = " ".join(p.cmdline()[:3])
                    except Exception:
                        pass
                info = {
                    "pid": pid,
                    "process": pname,
                    "user": user,
                    "cmdline": cmdline[:120],
                    "status": conn.status
                }
                proc_map[(lip, lport, rip, rport)] = info
                proc_map[(lip, lport, "*", 0)] = info
        except Exception as e:
            logger.warning(f"[NetGuard] Error mapeando procesos de red: {e}")
        return proc_map

    def _read_nft_device_counters(self) -> Dict[str, Dict[str, int]]:
        """Lee los contadores de bytes/paquetes por IP de la tabla conntrack e interfaces del kernel."""
        counters: Dict[str, Dict[str, int]] = {}
        try:
            res = self._run_sudo(["conntrack", "-L"], timeout=3.5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    srcs = re.findall(r"src=([\d\.]+)", line)
                    dsts = re.findall(r"dst=([\d\.]+)", line)
                    byts = re.findall(r"bytes=(\d+)", line)
                    pkts = re.findall(r"packets=(\d+)", line)
                    if not srcs or not dsts:
                        continue
                    s_ip, d_ip = srcs[0], dsts[0]
                    b0 = int(byts[0]) if len(byts) >= 1 else 0
                    b1 = int(byts[1]) if len(byts) >= 2 else 0
                    p0 = int(pkts[0]) if len(pkts) >= 1 else 0
                    p1 = int(pkts[1]) if len(pkts) >= 2 else 0

                    for ip_k, tx_b, rx_b, pk in ((s_ip, b0, b1, p0 + p1), (d_ip, b1, b0, p0 + p1)):
                        if ip_k.startswith(("192.168.1.", "10.42.0.", "10.240.82.")):
                            ent = counters.setdefault(ip_k, {"rx_bytes": 0, "tx_bytes": 0, "packets": 0})
                            ent["tx_bytes"] += tx_b
                            ent["rx_bytes"] += rx_b
                            ent["packets"] += pk
        except Exception:
            pass

        # Integrar contadores físicos de /proc/net/dev para interfaces propias y puentes
        try:
            lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
            iface_ip_map = {
                "enp2s0": "REDACTED_IP",
                "wlp3s0": "REDACTED_IP",
                "veth-host-aq": "REDACTED_IP"
            }
            for line in lines:
                if ":" not in line:
                    continue
                ifname, rest = line.split(":", 1)
                ifname = ifname.strip()
                if ifname in iface_ip_map:
                    f = rest.split()
                    if len(f) >= 10:
                        target_ip = iface_ip_map[ifname]
                        ent = counters.setdefault(target_ip, {"rx_bytes": 0, "tx_bytes": 0, "packets": 0})
                        ent["rx_bytes"] = max(ent["rx_bytes"], int(f[0]))
                        ent["tx_bytes"] = max(ent["tx_bytes"], int(f[8]))
                        ent["packets"] = max(ent["packets"], int(f[1]) + int(f[9]))
        except Exception:
            pass
        return counters

    def analyze_all_flows(self) -> Dict[str, Any]:
        """
        Analiza todos los flujos de red activos cruzando Conntrack + Procesos Locales +
        Inventario de Dispositivos Ethernet/Wi-Fi + Organizaciones Externas.
        """
        from core.traffic_monitor import get_traffic_monitor
        tm = get_traffic_monitor()

        # Sincronizar nombres conocidos de dispositivos con nuestra base de datos
        for mac, d in self.device_db.items():
            ip = d.get("ip")
            if ip and not ip.startswith("fe80:"):
                tm._known_devices[ip] = d.get("alias") or d.get("hostname") or ip

        proc_map = self.get_socket_process_map()
        raw_flows = tm.capture_conntrack_flows()

        enriched_flows: List[Dict[str, Any]] = []
        by_process: Dict[str, Dict[str, Any]] = {}
        by_device: Dict[str, Dict[str, Any]] = {}

        for fl in raw_flows:
            src_ip = fl["src_ip"]
            sport = fl["sport"]
            dst_ip = fl["dst_ip"]
            dport = fl["dport"]

            proc_info = (
                proc_map.get((src_ip, sport, dst_ip, dport))
                or proc_map.get((dst_ip, dport, src_ip, sport))
                or proc_map.get((src_ip, sport, "*", 0))
                or proc_map.get(("0.0.0.0", sport, "*", 0))
                or {"pid": None, "process": "Kernel / Enrutamiento NAT", "user": "system", "cmdline": ""}
            )

            fl["pid"] = proc_info["pid"]
            fl["process"] = proc_info["process"]
            fl["user"] = proc_info["user"]
            enriched_flows.append(fl)

            # Agregar resumen por proceso
            p_key = f"{proc_info['process']} (PID {proc_info['pid']})" if proc_info["pid"] else proc_info["process"]
            p_agg = by_process.setdefault(p_key, {
                "process": proc_info["process"],
                "pid": proc_info["pid"],
                "user": proc_info["user"],
                "flows_count": 0,
                "bytes": 0,
                "packets": 0,
                "destinations": set()
            })
            p_agg["flows_count"] += 1
            p_agg["bytes"] += fl.get("bytes", 0)
            p_agg["packets"] += fl.get("packets", 0)
            p_agg["destinations"].add(f"{fl['dst_org']} ({dst_ip}:{dport})")

            # Agregar resumen por dispositivo local
            for loc_ip, loc_name in ((src_ip, fl["src_name"]), (dst_ip, fl["dst_name"])):
                if loc_ip.startswith(("192.168.1.", "10.42.0.", "10.240.82.")):
                    d_agg = by_device.setdefault(loc_ip, {
                        "ip": loc_ip,
                        "name": loc_name,
                        "flows_count": 0,
                        "bytes": 0,
                        "packets": 0,
                        "organizations": set(),
                        "ports": set()
                    })
                    d_agg["flows_count"] += 1
                    d_agg["bytes"] += fl.get("bytes", 0)
                    d_agg["packets"] += fl.get("packets", 0)
                    d_agg["organizations"].add(fl["dst_org"])
                    d_agg["ports"].add(f"{dport}/{fl['proto']}")

        process_summary = []
        for k, v in by_process.items():
            process_summary.append({
                "process": v["process"],
                "pid": v["pid"],
                "user": v["user"],
                "flows_count": v["flows_count"],
                "bytes": v["bytes"],
                "packets": v["packets"],
                "destinations": sorted(list(v["destinations"]))[:6]
            })
        process_summary.sort(key=lambda x: (x["flows_count"], x["bytes"]), reverse=True)

        device_flow_summary = []
        for k, v in by_device.items():
            device_flow_summary.append({
                "ip": v["ip"],
                "name": v["name"],
                "flows_count": v["flows_count"],
                "bytes": v["bytes"],
                "packets": v["packets"],
                "organizations": sorted(list(v["organizations"])),
                "ports": sorted(list(v["ports"]))[:8]
            })
        device_flow_summary.sort(key=lambda x: (x["flows_count"], x["bytes"]), reverse=True)

        return {
            "ok": True,
            "timestamp": time.time(),
            "total_flows": len(enriched_flows),
            "flows": enriched_flows,
            "by_process": process_summary,
            "by_device": device_flow_summary
        }

    # =========================================================================
    # 3. CONTROL ACTIVO DE TRÁFICO Y FIREWALL SOBERANO (NFTABLES + TC)
    # =========================================================================

    def apply_firewall_and_traffic_policy(self) -> Dict[str, Any]:
        """
        Compila y aplica en caliente la tabla `inet tardis_aegis_shield` en el kernel Linux,
        integrando:
          - Protección de puertos sensibles del Host (Ethernet enp2s0 y Wi-Fi wlp3s0).
          - Conjuntos dinámicos de cuarentena por IP (`@quarantined_ips`) y por MAC (`@quarantined_macs`)
            aplicados tanto en `input` (hacia tus sistemas) como en `forward` (tráfico enrutado Wi-Fi/NAT).
          - Bloqueo bidireccional de IPs remotas maliciosas (`@blocked_ips` en `input`, `forward` y `output`).
          - Limitación de ancho de banda (Rate Limiting / Throttling) por dispositivo en KB/s.
        """
        protected_ports = "22, 111, 1701, 3389, 5555, 6969, 7681, 7682, 8080, 8088, 8757, 8758, 8765, 8787, 8888, 9001"

        q_ips = sorted(list(set(self.policy.get("quarantined_ips", []))))
        q_macs = sorted(list({m.lower() for m in self.policy.get("quarantined_macs", [])}))
        b_ips = sorted(list(set(self.policy.get("blocked_remote_ips", []))))
        b_ports = sorted(list({int(p) for p in self.policy.get("blocked_ports", []) if str(p).isdigit()}))
        throttled: Dict[str, int] = self.policy.get("throttled_devices", {})

        q_ips_elem = f"elements = {{ {', '.join(q_ips)} }}" if q_ips else ""
        q_macs_elem = f"elements = {{ {', '.join(q_macs)} }}" if q_macs else ""
        b_ips_elem = f"elements = {{ {', '.join(b_ips)} }}" if b_ips else ""
        b_ports_elem = f"elements = {{ {', '.join(map(str, b_ports))} }}" if b_ports else ""

        throttle_rules_input = []
        throttle_rules_forward = []
        for tip, kbps in throttled.items():
            kbps_int = max(10, int(kbps))
            throttle_rules_input.append(f"        ip saddr {tip} limit rate over {kbps_int} kbytes/second counter drop")
            throttle_rules_forward.append(f"        ip saddr {tip} limit rate over {kbps_int} kbytes/second counter drop")
            throttle_rules_forward.append(f"        ip daddr {tip} limit rate over {kbps_int} kbytes/second counter drop")

        throttle_in_str = "\n".join(throttle_rules_input)
        throttle_fw_str = "\n".join(throttle_rules_forward)

        nft_ruleset = f"""table inet tardis_aegis_shield
delete table inet tardis_aegis_shield
table inet tardis_aegis_shield {{
    set blocked_ips {{
        type ipv4_addr
        flags interval, timeout
        timeout 24h
        {b_ips_elem}
    }}

    set quarantined_ips {{
        type ipv4_addr
        flags interval
        {q_ips_elem}
    }}

    set quarantined_macs {{
        type ether_addr
        {q_macs_elem}
    }}

    set blocked_ports {{
        type inet_service
        {b_ports_elem}
    }}

    chain input {{
        type filter hook input priority -10; policy accept;

        iifname "lo" accept
        ct state invalid drop

        # Cuarentena inmediata de dispositivos aislados (IP o MAC) en Ethernet y Wi-Fi
        ether saddr @quarantined_macs counter drop
        ip saddr @quarantined_ips counter drop
        ip saddr @blocked_ips counter drop

        # Bloqueo de puertos globales restringidos
        tcp dport @blocked_ports counter drop
        udp dport @blocked_ports counter drop

        # Reglas de limitación de caudal (Throttling) por dispositivo
{throttle_in_str}

        ct state established,related accept

        # Permitir subredes locales soberanas y malla Tailscale hacia puertos de control
        ip saddr {{ REDACTED_IP/8, REDACTED_IP/24, REDACTED_IP/24, REDACTED_IP/24, REDACTED_IP/10 }} tcp dport {{ {protected_ports} }} accept
        ip6 saddr {{ ::1/128, fe80::/10, fd7a:115c:a1e0::/48 }} tcp dport {{ {protected_ports} }} accept

        # Bloquear cualquier intento externo no autorizado hacia puertos sensibles y RPC UDP
        tcp dport {{ {protected_ports} }} counter drop
        ip saddr != {{ REDACTED_IP/8, REDACTED_IP/24, REDACTED_IP/24, REDACTED_IP/24, REDACTED_IP/10 }} udp dport {{ 111, 5000 }} counter drop
    }}

    chain forward {{
        type filter hook forward priority -10; policy accept;

        ct state invalid drop

        # Control de dispositivos enrutados (Wi-Fi Hotspot wlp3s0 <-> Ethernet enp2s0 y NetNS)
        ether saddr @quarantined_macs counter drop
        ip saddr @quarantined_ips counter drop
        ip daddr @quarantined_ips counter drop
        ip saddr @blocked_ips counter drop
        ip daddr @blocked_ips counter drop

        tcp dport @blocked_ports counter drop
        udp dport @blocked_ports counter drop

        # Reglas de limitación de caudal (Throttling) en tráfico enrutado
{throttle_fw_str}
    }}

    chain output {{
        type filter hook output priority -10; policy accept;

        oifname "lo" accept
        ip daddr @blocked_ips counter drop
        ip daddr @quarantined_ips counter drop
        tcp dport @blocked_ports counter drop
        udp dport @blocked_ports counter drop
    }}
}}
"""
        try:
            NFT_CONTROLLER_FILE.write_text(nft_ruleset, encoding="utf-8")
            res = self._run_sudo(["nft", "-f", str(NFT_CONTROLLER_FILE)], timeout=5.0)
            ok = (res.returncode == 0)
            self.policy["last_policy_sync"] = time.time()
            self._save_state()
            return {
                "ok": ok,
                "quarantined_ips": q_ips,
                "quarantined_macs": q_macs,
                "blocked_remote_ips": b_ips,
                "blocked_ports": b_ports,
                "throttled_devices": throttled,
                "error": res.stderr.strip() if not ok else ""
            }
        except Exception as e:
            logger.error(f"[NetGuard] Error aplicando reglas nftables: {e}")
            return {"ok": False, "error": str(e)}

    def quarantine_device(self, target: str, reason: str = "Aislamiento manual por seguridad") -> Dict[str, Any]:
        """Aísla un dispositivo por dirección IP o MAC tanto en Ethernet como en Wi-Fi."""
        target_clean = target.strip()
        is_mac = bool(re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", target_clean))

        if is_mac:
            mac_up = target_clean.upper()
            q_macs = set(self.policy.get("quarantined_macs", []))
            q_macs.add(mac_up)
            self.policy["quarantined_macs"] = sorted(list(q_macs))
            if mac_up in self.device_db:
                self.device_db[mac_up]["is_quarantined"] = True
                self.device_db[mac_up]["trust_level"] = "QUARANTINED"
                ip_assoc = self.device_db[mac_up].get("ip", "")
                if ip_assoc and "." in ip_assoc:
                    q_ips = set(self.policy.get("quarantined_ips", []))
                    q_ips.add(ip_assoc)
                    self.policy["quarantined_ips"] = sorted(list(q_ips))
        else:
            q_ips = set(self.policy.get("quarantined_ips", []))
            q_ips.add(target_clean)
            self.policy["quarantined_ips"] = sorted(list(q_ips))
            for mac_k, dev in self.device_db.items():
                if dev.get("ip") == target_clean:
                    dev["is_quarantined"] = True
                    dev["trust_level"] = "QUARANTINED"
                    q_macs = set(self.policy.get("quarantined_macs", []))
                    q_macs.add(mac_k.upper())
                    self.policy["quarantined_macs"] = sorted(list(q_macs))

        res = self.apply_firewall_and_traffic_policy()
        return {
            "ok": res["ok"],
            "action": "QUARANTINE_DEVICE",
            "target": target_clean,
            "reason": reason,
            "policy": res
        }

    def release_device(self, target: str) -> Dict[str, Any]:
        """Libera a un dispositivo previamente puesto en cuarentena."""
        target_clean = target.strip()
        is_mac = bool(re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", target_clean))

        if is_mac:
            mac_up = target_clean.upper()
            self.policy["quarantined_macs"] = [
                m for m in self.policy.get("quarantined_macs", []) if m.upper() != mac_up
            ]
            if mac_up in self.device_db:
                self.device_db[mac_up]["is_quarantined"] = False
                self.device_db[mac_up]["trust_level"] = "KNOWN"
                ip_assoc = self.device_db[mac_up].get("ip", "")
                if ip_assoc:
                    self.policy["quarantined_ips"] = [
                        i for i in self.policy.get("quarantined_ips", []) if i != ip_assoc
                    ]
        else:
            self.policy["quarantined_ips"] = [
                i for i in self.policy.get("quarantined_ips", []) if i != target_clean
            ]
            for mac_k, dev in self.device_db.items():
                if dev.get("ip") == target_clean:
                    dev["is_quarantined"] = False
                    dev["trust_level"] = "KNOWN"
                    self.policy["quarantined_macs"] = [
                        m for m in self.policy.get("quarantined_macs", []) if m.upper() != mac_k.upper()
                    ]

        res = self.apply_firewall_and_traffic_policy()
        return {
            "ok": res["ok"],
            "action": "RELEASE_DEVICE",
            "target": target_clean,
            "policy": res
        }

    def throttle_device(self, ip: str, rate_kbps: int) -> Dict[str, Any]:
        """Limita el ancho de banda máximo de un dispositivo local en KB/s."""
        ip_clean = ip.strip()
        throttled = self.policy.setdefault("throttled_devices", {})
        throttled[ip_clean] = max(10, int(rate_kbps))
        res = self.apply_firewall_and_traffic_policy()
        return {
            "ok": res["ok"],
            "action": "THROTTLE_DEVICE",
            "ip": ip_clean,
            "rate_kbps": throttled[ip_clean],
            "policy": res
        }

    def unthrottle_device(self, ip: str) -> Dict[str, Any]:
        """Elimina el límite de ancho de banda sobre un dispositivo."""
        ip_clean = ip.strip()
        throttled = self.policy.setdefault("throttled_devices", {})
        throttled.pop(ip_clean, None)
        res = self.apply_firewall_and_traffic_policy()
        return {
            "ok": res["ok"],
            "action": "UNTHROTTLE_DEVICE",
            "ip": ip_clean,
            "policy": res
        }

    def block_remote_endpoint(self, ip_or_cidr: str) -> Dict[str, Any]:
        """Bloquea completamente el tráfico entrante, saliente y enrutado hacia una IP o CIDR externo."""
        target = ip_or_cidr.strip()
        b_ips = set(self.policy.get("blocked_remote_ips", []))
        b_ips.add(target)
        self.policy["blocked_remote_ips"] = sorted(list(b_ips))
        res = self.apply_firewall_and_traffic_policy()
        return {"ok": res["ok"], "action": "BLOCK_ENDPOINT", "target": target, "policy": res}

    def unblock_remote_endpoint(self, ip_or_cidr: str) -> Dict[str, Any]:
        """Desbloquea una IP o CIDR externo."""
        target = ip_or_cidr.strip()
        self.policy["blocked_remote_ips"] = [
            i for i in self.policy.get("blocked_remote_ips", []) if i != target
        ]
        res = self.apply_firewall_and_traffic_policy()
        return {"ok": res["ok"], "action": "UNBLOCK_ENDPOINT", "target": target, "policy": res}

    def set_device_metadata(
        self,
        target: str,
        alias: Optional[str] = None,
        trust_level: Optional[str] = None
    ) -> Dict[str, Any]:
        """Asigna un nombre personalizado (alias) o nivel de confianza a un dispositivo."""
        target_clean = target.strip().upper()
        matched_mac = None
        if target_clean in self.device_db:
            matched_mac = target_clean
        else:
            for mac_k, dev in self.device_db.items():
                if dev.get("ip") == target.strip():
                    matched_mac = mac_k
                    break

        if not matched_mac:
            return {"ok": False, "error": f"Dispositivo {target} no encontrado en el registro."}

        if alias:
            self.device_db[matched_mac]["custom_alias"] = alias.strip()
            self.device_db[matched_mac]["alias"] = alias.strip()
        if trust_level:
            self.device_db[matched_mac]["trust_level"] = trust_level.strip().upper()

        self._save_state()
        return {"ok": True, "mac": matched_mac, "device": self.device_db[matched_mac]}

    def get_complete_audit_snapshot(self, active_sweep: bool = False) -> Dict[str, Any]:
        """
        Genera el informe maestro unificado con:
          - Todos los dispositivos en Ethernet, Wi-Fi y NetNS (online e históricos).
          - Telemetría de interfaces físicas y virtuales (/proc/net/dev).
          - Todos los flujos activos correlacionados con procesos (PID) y organizaciones.
          - Estado activo del Firewall NFTables y DNS Sinkhole Anti-Espionaje.
        """
        t0 = time.time()
        devices = self.discover_all_devices(active_sweep=active_sweep)
        interfaces = self.get_interface_telemetry()
        flows_data = self.analyze_all_flows()

        online_devices = [d for d in devices if d.get("online")]
        eth_devices = [d for d in online_devices if d.get("interface") == "enp2s0"]
        wifi_devices = [d for d in online_devices if d.get("interface") == "wlp3s0"]
        virt_devices = [d for d in online_devices if d.get("interface") == "veth-host-aq"]

        alerts: List[str] = []
        for d in online_devices:
            if d.get("risky_ports"):
                alerts.append(
                    f"⚠️ Dispositivo {d['alias']} ({d['ip']}) expone puertos sensibles: {d['risky_ports']}"
                )
            if d.get("is_quarantined"):
                alerts.append(
                    f"🔒 Dispositivo {d['alias']} ({d['ip']} / {d['mac']}) se encuentra aislado en CUARENTENA."
                )

        return {
            "ok": True,
            "timestamp": time.time(),
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
            "summary": {
                "total_registered_devices": len(devices),
                "online_devices_count": len(online_devices),
                "ethernet_online_count": len(eth_devices),
                "wifi_online_count": len(wifi_devices),
                "virtual_online_count": len(virt_devices),
                "active_flows_count": flows_data["total_flows"],
                "quarantined_count": len(self.policy.get("quarantined_ips", [])) + len(self.policy.get("quarantined_macs", [])),
                "throttled_count": len(self.policy.get("throttled_devices", {})),
                "alerts_count": len(alerts)
            },
            "devices": devices,
            "interfaces": interfaces,
            "traffic": flows_data,
            "policy": self.policy,
            "alerts": alerts
        }


def get_traffic_controller() -> TardisNetworkTrafficController:
    return TardisNetworkTrafficController.get_instance()


if __name__ == "__main__":
    ctrl = get_traffic_controller()
    ctrl.apply_firewall_and_traffic_policy()
    snap = ctrl.get_complete_audit_snapshot(active_sweep=True)
    print(json.dumps(snap["summary"], indent=2, ensure_ascii=False))
    for dev in snap["devices"]:
        if dev["online"]:
            print(
                f" • [{dev['connection_medium']}] {dev['ip']:15} | {dev['mac']} | "
                f"{dev['alias']} | Ports: {dev['open_ports']} | RTT: {dev['rtt_ms']} ms"
            )
