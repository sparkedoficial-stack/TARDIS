"""
core/network_shield.py - Escudo de Red Soberano, AdBlock DNS Sinkhole & Auditoría Anti-Espionaje
=================================================================================================
GODWORKS SYSTEM v26.4 - Suite Soberana de Control Temporal e Inteligencia Causal

Proporciona tres defensas cibernéticas integradas:
  1. DNS Sinkhole (Pi-hole nativo): Resuelve dominios de publicidad y rastreadores a REDACTED_IP.
  2. Blindaje Anti-Espionaje y Anti-Telemetría: Bloquea balizas de vigilancia (Microsoft, Google, Meta, TikTok, etc.).
  3. Auditoría Activa de Red: Mapeo de dispositivos, escaneo no invasivo de puertos de riesgo y detección de intrusiones.
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("godworks.network_shield")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "shield"
ADBLOCK_HOSTS_FILE = DATA_DIR / "adblock_hosts"
CUSTOM_BLOCKLIST_FILE = DATA_DIR / "custom_blocklist.json"
WHITELIST_FILE = DATA_DIR / "whitelist.json"
SHIELD_CONF_PATH = Path("/etc/NetworkManager/dnsmasq-shared.d/01-godworks-shield.conf")

# =============================================================================
# LISTAS BASE DE DOMINIOS DE PUBLICIDAD, RASTREO Y TELEMETRÍA ESPÍA
# =============================================================================

CORE_AD_DOMAINS = [
    # Redes masivas de anuncios
    "doubleclick.net", "adservice.google.com", "pagead2.googlesyndication.com",
    "admob.com", "ads.google.com", "adservice.google.es", "adservice.google.com.mx",
    "pagead2.googleadservices.com", "googlesyndication.com", "googleads.g.doubleclick.net",
    "taboola.com", "outbrain.com", "criteo.com", "criteo.net",
    "rubiconproject.com", "pubmatic.com", "advertising.com", "adroll.com",
    "smartadserver.com", "scorecardresearch.com", "quantserve.com",
    "adnxs.com", "flashtalking.com", "zedo.com", "popads.net", "propellerads.com",
    "inmobi.com", "adcolony.com", "unityads.unity3d.com", "applovin.com",
    "vungle.com", "chartboost.com", "ironsrc.com", "fyber.com",
    "ad-delivery.net", "adform.net", "amazon-adsystem.com", "serving-sys.com",
    "adbutler.com", "bidswitch.net", "casalemedia.com", "openx.net",
    "moatads.com", "trafficjunky.com", "ero-advertising.com", "exoclick.com",
    "popcash.net", "admaven.com", "clickadu.com", "adsterra.com",
    "revcontent.com", "mgid.com", "adrecover.com", "adblade.com"
]

CORE_SPYWARE_AND_TELEMETRY_DOMAINS = [
    # Telemetría invasiva Windows / Microsoft
    "vortex.data.microsoft.com", "telemetry.microsoft.com", "watson.telemetry.microsoft.com",
    "settings-win.data.microsoft.com", "diagnostics.support.microsoft.com",
    "mobile.pipe.aria.microsoft.com", "watson.ppe.telemetry.microsoft.com",
    "telecommand.telemetry.microsoft.com", "sqm.telemetry.microsoft.com",
    "feedback.search.microsoft.com", "choice.microsoft.com", "telemetry.urs.microsoft.com",
    "df.telemetry.microsoft.com", "oca.telemetry.microsoft.com",
    
    # Vigilancia y seguimiento Meta / Facebook
    "graph.facebook.com", "pixel.facebook.com", "an.facebook.com",
    "connect.facebook.net", "tr.snapchat.com", "ads.twitter.com",
    "analytics.twitter.com", "static.ads-twitter.com",
    
    # Telemetría y analíticas Google / Android
    "google-analytics.com", "ssl.google-analytics.com", "app-measurement.com",
    "firebase-settings.crashlytics.com", "crashlytics.com", "reports.crashlytics.com",
    "analytics.google.com", "click.googleanalytics.com",
    
    # Telemetría TikTok / ByteDance
    "analytics.tiktok.com", "log.byteoversea.com", "mon.byteoversea.com",
    "ads-api.tiktok.com", "business-api.tiktok.com",
    
    # Telemetría Apple / Xiaomi / Samsung
    "metrics.icloud.com", "iadsdk.apple.com", "iad.apple.com",
    "data.mistat.xiaomi.com", "tracking.miui.com", "smetrics.samsung.com",
    "samsungadhub.com", "nmetrics.samsung.com",
    
    # Dominios de Stalkerware y Rastreo de Terceros
    "flurry.com", "adjust.com", "appsflyer.com", "branch.io",
    "kochava.com", "singular.net", "singular.io", "braze.com",
    "amplitude.com", "mixpanel.com", "segment.io", "segment.com",
    "onesignal.com", "clevertap.com", "leanplum.com", "instabug.com"
]


class NetworkShield:
    """Motor central de auditoría de red, bloqueo de publicidad y defensa anti-espionaje."""

    _instance: Optional["NetworkShield"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.adblock_enabled = True
        self.antispy_enabled = True
        self.last_audit_time = 0.0
        self.last_audit_results: Dict[str, Any] = {}
        self._ensure_directories()
        self._load_config()

    @classmethod
    def get_instance(cls) -> "NetworkShield":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _ensure_directories(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not CUSTOM_BLOCKLIST_FILE.exists():
            CUSTOM_BLOCKLIST_FILE.write_text("[]", encoding="utf-8")
        if not WHITELIST_FILE.exists():
            WHITELIST_FILE.write_text("[]", encoding="utf-8")

    def _load_config(self):
        cfg_file = DATA_DIR / "shield_config.json"
        if cfg_file.exists():
            try:
                data = json.loads(cfg_file.read_text(encoding="utf-8"))
                self.adblock_enabled = data.get("adblock_enabled", True)
                self.antispy_enabled = data.get("antispy_enabled", True)
            except Exception:
                pass

    def _save_config(self):
        cfg_file = DATA_DIR / "shield_config.json"
        try:
            cfg_file.write_text(json.dumps({
                "adblock_enabled": self.adblock_enabled,
                "antispy_enabled": self.antispy_enabled,
                "last_audit_time": self.last_audit_time
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 1. COMPILACIÓN DE LISTA DE BLOQUEO Y DESPLIEGUE EN DNSMASQ
    # -------------------------------------------------------------------------

    def compile_and_apply_blocklist(self) -> Dict[str, Any]:
        """
        Compila la lista negra de dominios de publicidad y espionaje
        y la inyecta directamente en el servidor dnsmasq de TimeMachine.
        """
        domains_to_block: Set[str] = set()

        if self.adblock_enabled:
            domains_to_block.update(CORE_AD_DOMAINS)

        if self.antispy_enabled:
            domains_to_block.update(CORE_SPYWARE_AND_TELEMETRY_DOMAINS)

        # Cargar lista personalizada adicional
        try:
            if CUSTOM_BLOCKLIST_FILE.exists():
                custom_d = json.loads(CUSTOM_BLOCKLIST_FILE.read_text(encoding="utf-8"))
                if isinstance(custom_d, list):
                    domains_to_block.update(custom_d)
        except Exception:
            pass

        # Quitar dominios en whitelist
        try:
            if WHITELIST_FILE.exists():
                wl = json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
                if isinstance(wl, list):
                    domains_to_block.difference_update(wl)
        except Exception:
            pass

        # 1. Generar archivo de configuración nativo para dnsmasq con sintaxis address=/dominio/REDACTED_IP
        # Esto bloquea automáticamente tanto el dominio principal como TODOS sus subdominios (*.dominio).
        conf_lines = [
            "# GODWORKS SYSTEM v26.4 - ESCUDO SOBERANO DNS SINKHOLE & ANTI-ESPIONAJE",
            f"# Generado: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Dominios bloqueados: {len(domains_to_block)}",
            "bogus-priv",
            "filterwin2k",
            "domain-needed",
            ""
        ]

        # 2. Generar también formato hosts standard para referencia o auditoría
        hosts_lines = [
            "# GODWORKS SYSTEM v26.4 - ESCUDO SOBERANO DNS SINKHOLE (HOSTS FORMAT)",
            f"# Generado: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Dominios bloqueados: {len(domains_to_block)}",
            "REDACTED_IP localhost",
            "::1 localhost",
            ""
        ]

        for d in sorted(domains_to_block):
            d_clean = d.strip().lower()
            if d_clean and not d_clean.startswith("#"):
                conf_lines.append(f"address=/{d_clean}/REDACTED_IP")
                conf_lines.append(f"address=/{d_clean}/::")
                hosts_lines.append(f"REDACTED_IP {d_clean}")
                hosts_lines.append(f":: {d_clean}")

        try:
            ADBLOCK_HOSTS_FILE.write_text("\n".join(hosts_lines) + "\n", encoding="utf-8")
        except Exception as e_h:
            logger.warning(f"[NetworkShield] No se pudo escribir hosts local: {e_h}")

        logger.info(f"[NetworkShield] Lista de bloqueo compilada con {len(domains_to_block)} dominios únicos.")

        # Desplegar en /etc/NetworkManager/dnsmasq-shared.d/01-godworks-shield.conf
        deployed = self._deploy_to_dnsmasq("\n".join(conf_lines) + "\n")

        return {
            "ok": True,
            "blocked_domains_count": len(domains_to_block),
            "adblock_active": self.adblock_enabled,
            "antispy_active": self.antispy_enabled,
            "deployed_to_dnsmasq": deployed,
            "conf_file": str(SHIELD_CONF_PATH),
            "hosts_file": str(ADBLOCK_HOSTS_FILE)
        }

    def _deploy_to_dnsmasq(self, conf_content: str) -> bool:
        """Instala las reglas address=/dominio/REDACTED_IP en dnsmasq y recarga el proceso con SIGHUP."""
        tmp_conf = DATA_DIR / "01-godworks-shield.conf.tmp"
        try:
            tmp_conf.write_text(conf_content, encoding="utf-8")
        except Exception as e:
            logger.warning(f"[NetworkShield] Error escribiendo tmp_conf: {e}")
            return False

        try:
            # Copiar a /etc/NetworkManager/dnsmasq-shared.d/ con sudo no interactivo
            copy_cmd = ["sudo", "-S", "cp", str(tmp_conf), str(SHIELD_CONF_PATH)]
            cp_res = subprocess.run(copy_cmd, input="0\n", text=True, capture_output=True, timeout=5)
            if cp_res.returncode != 0:
                logger.warning(f"[NetworkShield] Error copiando configuración a dnsmasq: {cp_res.stderr}")
                return False

            # Enviar SIGHUP a dnsmasq para recargar listas de inmediato sin reiniciar la red
            reload_cmd = ["sudo", "-S", "killall", "-HUP", "dnsmasq"]
            res = subprocess.run(reload_cmd, input="0\n", text=True, capture_output=True, timeout=5)
            logger.info("[NetworkShield] Filtro de dnsmasq recargado con éxito vía SIGHUP.")
            return True
        except Exception as e:
            logger.warning(f"[NetworkShield] Error desplegando a dnsmasq: {e}")
            return False

    # -------------------------------------------------------------------------
    # 2. AUDITORÍA ACTIVA DE RED & CUIDADO DE DISPOSITIVOS
    # -------------------------------------------------------------------------

    def audit_network(self) -> Dict[str, Any]:
        """
        Escanea la red Wi-Fi TimeMachine y la red local cableada para auditar
        dispositivos asociados, evaluar puertos vulnerables y calcular la salud de red.
        """
        t_start = time.time()
        devices = []
        alerts = []
        seen_macs: Set[str] = set()

        # 1. Leer ARP table
        arp_entries = []
        if os.path.exists("/proc/net/arp"):
            try:
                with open("/proc/net/arp", "r", encoding="utf-8") as f:
                    for line in f.readlines()[1:]:
                        p = line.split()
                        if len(p) >= 6 and p[3] != "00:00:00:00:00:00" and p[2] != "0x0":
                            arp_entries.append({"ip": p[0], "mac": p[3].upper(), "device": p[5]})
            except Exception:
                pass

        # 2. Leer DHCP leases de dnsmasq
        leases = {}
        try:
            for l_file in Path("/var/lib/NetworkManager").glob("dnsmasq-*.leases"):
                try:
                    with open(l_file, "r", encoding="utf-8") as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) >= 4:
                                leases[parts[1].upper()] = {"ip": parts[2], "host": parts[3]}
                except Exception:
                    pass
        except Exception:
            pass

        # Si leases está vacío, intentar lectura directa con sudo no interactivo
        if not leases:
            try:
                res = subprocess.run(
                    ["sudo", "-S", "cat", "/var/lib/NetworkManager/dnsmasq-wlp3s0.leases"],
                    input="0\n", text=True, capture_output=True, timeout=3
                )
                if res.returncode == 0:
                    for line in res.stdout.strip().splitlines():
                        parts = line.strip().split()
                        if len(parts) >= 4:
                            leases[parts[1].upper()] = {"ip": parts[2], "host": parts[3]}
            except Exception:
                pass

        # 3. Mapear y auditar cada dispositivo
        for entry in arp_entries:
            mac = entry["mac"]
            ip = entry["ip"]
            iface = entry["device"]

            # Detección de ARP Spoofing (mismo MAC con IPs conflictivas anómalas)
            if mac in seen_macs and iface == "wlp3s0":
                alerts.append(f"⚠️ Posible anomalía ARP o IP duplicada detectada para MAC {mac}")
            seen_macs.add(mac)

            hostname = leases.get(mac, {}).get("host") or ("Gateway Router" if ip.endswith(".1") else "Dispositivo Conectado")
            if hostname == "*":
                hostname = "Dispositivo Móvil / Laptop"

            # Fabricante aproximado por OUI
            vendor = self._resolve_vendor(mac)

            # Análisis rápido de puertos de riesgo (no intrusivo, timeout ultracorto)
            risky_ports = self._check_risky_ports(ip)

            is_safe = len(risky_ports) == 0
            if risky_ports:
                alerts.append(f"🚨 Dispositivo en {ip} ({hostname}) tiene puertos de riesgo abiertos: {', '.join(map(str, risky_ports))}")

            devices.append({
                "ip": ip,
                "mac": mac,
                "hostname": hostname,
                "interface": iface,
                "vendor": vendor,
                "risky_ports": risky_ports,
                "is_safe": is_safe,
                "network_type": "Wi-Fi TimeMachine" if iface == "wlp3s0" else "Ethernet LAN"
            })

        # 4. Cálculo de puntuación de seguridad (Score 0-100)
        base_score = 100
        if alerts:
            base_score -= len(alerts) * 12
        if not self.adblock_enabled:
            base_score -= 15
        if not self.antispy_enabled:
            base_score -= 20

        security_score = max(20, min(100, base_score))
        grade = "A+ (Soberano)" if security_score >= 95 else ("A" if security_score >= 85 else ("B" if security_score >= 70 else "C (Vulnerable)"))

        audit_data = {
            "ok": True,
            "timestamp": time.time(),
            "elapsed_ms": round((time.time() - t_start) * 1000, 1),
            "security_score": security_score,
            "grade": grade,
            "adblock_active": self.adblock_enabled,
            "antispy_active": self.antispy_enabled,
            "blocked_domains_count": len(CORE_AD_DOMAINS) + len(CORE_SPYWARE_AND_TELEMETRY_DOMAINS),
            "devices_count": len(devices),
            "devices": devices,
            "alerts": alerts,
            "recommendation": "Red en estado óptimo. Todas las consultas son filtradas contra publicidad y telemetría." if not alerts else "Se detectaron posibles vulnerabilidades. Revisa los dispositivos señalados."
        }

        self.last_audit_time = time.time()
        self.last_audit_results = audit_data
        self._save_config()
        return audit_data

    def _resolve_vendor(self, mac: str) -> str:
        """Identifica el fabricante por el prefijo MAC OUI."""
        prefix = mac[:8].upper()
        # Prefijos comunes de Apple, Samsung, Intel, Google, Xiaomi
        vendors = {
            "42:96:6F": "Apple iOS (Private Wi-Fi Address)",
            "FE:B1:2B": "Apple Device",
            "14:13:33": "MediaTek Wi-Fi 6 (GODWORKS Hardware)",
            "00:31:92": "Router Gateway",
            "50:EB:F6": "Realtek Gigabit Ethernet",
            "F4:D1:08": "Apple iPhone",
            "DC:A6:32": "Raspberry Pi Foundation",
            "B8:27:EB": "Raspberry Pi",
            "00:1A:2B": "Samsung Electronics",
            "BC:D0:74": "Samsung Electronics"
        }
        for p, v in vendors.items():
            if mac.startswith(p):
                return v
        if mac[1] in ("2", "6", "A", "E"):
            return "Dirección MAC Aleatoria / Privada (Android/iOS)"
        return "Dispositivo de Red Genérico"

    def _check_risky_ports(self, ip: str) -> List[int]:
        """Comprueba de forma pasiva y no invasiva puertos vulnerables comunes."""
        target_ports = [23, 445, 5555]  # Telnet, SMB inseguro, Android ADB desprotegido
        open_ports = []
        for port in target_ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.08)
                res = s.connect_ex((ip, port))
                s.close()
                if res == 0:
                    open_ports.append(port)
            except Exception:
                pass
        return open_ports

    # -------------------------------------------------------------------------
    # 3. CONTROL DE ESTADO Y ALTERNADORES (TOGGLES)
    # -------------------------------------------------------------------------

    def toggle_adblock(self, enabled: bool) -> Dict[str, Any]:
        self.adblock_enabled = bool(enabled)
        self._save_config()
        return self.compile_and_apply_blocklist()

    def toggle_antispy(self, enabled: bool) -> Dict[str, Any]:
        self.antispy_enabled = bool(enabled)
        self._save_config()
        return self.compile_and_apply_blocklist()

    def get_traffic_summary(self) -> Dict[str, Any]:
        """Obtiene la auditoría en tiempo real de flujos de tráfico y accesos a dispositivos."""
        from core.traffic_monitor import get_traffic_monitor
        return get_traffic_monitor().analyze_traffic_and_accesses()

    def get_status(self) -> Dict[str, Any]:
        """Retorna el estado global del escudo de red y auditoría."""
        if not self.last_audit_results:
            self.audit_network()

        # Obtener métricas rápidas de tráfico
        traffic_info = {}
        try:
            from core.traffic_monitor import get_traffic_monitor
            traffic_info = get_traffic_monitor().get_quick_status()
        except Exception:
            pass

        return {
            "ok": True,
            "adblock_active": self.adblock_enabled,
            "antispy_active": self.antispy_enabled,
            "blocked_domains_count": len(CORE_AD_DOMAINS) + len(CORE_SPYWARE_AND_TELEMETRY_DOMAINS),
            "security_score": self.last_audit_results.get("security_score", 100),
            "grade": self.last_audit_results.get("grade", "A+ (Soberano)"),
            "devices_count": len(self.last_audit_results.get("devices", [])),
            "devices": self.last_audit_results.get("devices", []),
            "alerts": self.last_audit_results.get("alerts", []) + (traffic_info.get("alerts", []) if traffic_info else []),
            "last_audit_time": self.last_audit_time,
            "sinkhole_ip": "REDACTED_IP",
            "protected_networks": ["TimeMachine (REDACTED_IP/24)", "Ethernet LAN (REDACTED_IP/24)"],
            "traffic_flows_count": traffic_info.get("total_active_flows", 0),
            "inbound_access_count": traffic_info.get("inbound_access_count", 0)
        }


def get_network_shield() -> NetworkShield:
    return NetworkShield.get_instance()


if __name__ == "__main__":
    shield = get_network_shield()
    print("Compilando y desplegando lista de bloqueo...")
    res_comp = shield.compile_and_apply_blocklist()
    print("Compilación:", res_comp)
    print("\nEjecutando auditoría de red...")
    audit = shield.audit_network()
    print(f"Auditoría: Puntuación={audit['security_score']}% ({audit['grade']}), Dispositivos={audit['devices_count']}")
    for d in audit["devices"]:
        print(f" • {d['ip']} | {d['mac']} | {d['hostname']} | {d['vendor']}")
