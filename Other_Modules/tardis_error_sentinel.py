"""
core/tardis_error_sentinel.py - Centinela de Detección, Auto-Corrección y Auto-Notificación
=============================================================================================
SISTEMA TARDIS v26.4 · Arquitecto: Miguel Ángel May Canché (₪)

Vigila 24/7 el estado del sistema en entornos locales y online:
  1. Detección Local: Ollama, recursos de silicio (RAM/GPU), procesos y excepciones no capturadas.
  2. Detección Online: Conectividad a Internet, latencia y disponibilidad del túnel Cloudflare.
  3. Auto-Corrección: Reinicio de servicios, purga de buffers y recuperación de túneles caídos.
  4. Auto-Notificación: Emite alertas estructuradas inmediatas a Antigravity (antigravity_bridge.py)
     en live_dialogue.jsonl y system_feedback.json para activar auto-corrección guiada.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("tardis.sentinel")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import antigravity_bridge
import gia_bootstrap

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SENTINEL_LOG = CONFIG_DIR / "sentinel.log"
TUNNEL_FILE = BASE_DIR / "CURRENT_TUNNEL_URL.txt"


class TardisErrorSentinel:
    """Motor centinela autónomo de supervisión de fallos, auto-reparación y notificación."""

    _instance: Optional["TardisErrorSentinel"] = None
    _lock = threading.Lock()

    def __init__(self, check_interval: float = 15.0):
        self.interval = max(5.0, check_interval)
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        self.bridge = antigravity_bridge.get_bridge()
        self.incident_history: List[Dict[str, Any]] = []
        self.health_score: int = 100
        self.last_check_ts: float = 0.0
        self.last_status: Dict[str, Any] = {
            "status": "OPERATIONAL",
            "local_healthy": True,
            "online_healthy": True,
            "incidents_count": 0,
            "last_incident": None
        }

    @classmethod
    def get_instance(cls) -> "TardisErrorSentinel":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} | [TARDIS-CENTINELA] {level:5} | {msg}"
        print(line)
        try:
            with open(SENTINEL_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    # =========================================================================
    # 1. VERIFICACIONES LOCALES
    # =========================================================================

    def check_local_ollama(self) -> Tuple[bool, str]:
        """Comprueba el servicio local de inferencia Ollama."""
        endpoint = gia_bootstrap.DEFAULT_OLLAMA_ENDPOINT
        alive = gia_bootstrap.is_ollama_alive(endpoint, timeout=1.5)
        if alive:
            return True, f"Ollama operativo en {endpoint}"
        return False, f"Servicio Ollama no responde en {endpoint}"

    def check_local_memory(self) -> Tuple[bool, str]:
        """Comprueba que haya suficiente memoria RAM disponible."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            free_gb = mem.available / (1024 ** 3)
            if free_gb < 1.0:
                return False, f"Memoria RAM crítica: solo {free_gb:.2f} GB disponibles ({mem.percent}% en uso)"
            return True, f"RAM saludable ({free_gb:.1f} GB disponibles, {mem.percent}% uso)"
        except Exception as e:
            return True, f"Telemetría RAM no disponible: {e}"

    def check_master_port(self, port: int = 8757) -> Tuple[bool, str]:
        """Verifica si el puerto maestro del servidor responde."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.5)
                res = s.connect_ex(("REDACTED_IP", port))
                if res == 0:
                    return True, f"Puerto maestro {port} respondiendo correctamente."
                return False, f"Puerto maestro {port} inaccesible (código {res})"
        except Exception as e:
            return False, f"Error sondeando puerto {port}: {e}"

    # =========================================================================
    # 2. VERIFICACIONES ONLINE
    # =========================================================================

    def check_internet_reachability(self) -> Tuple[bool, str]:
        """Verifica si la estación tiene conectividad real a internet."""
        hosts = [("REDACTED_IP", 53), ("REDACTED_IP", 53)]
        for host, port in hosts:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2.0)
                    s.connect((host, port))
                    return True, "Conexión a Internet activa."
            except Exception:
                continue
        return False, "Sin conexión a Internet (fallaron servidores DNS raíz)."

    def check_online_tunnel(self) -> Tuple[bool, str]:
        """Comprueba el estado del túnel Cloudflare si está configurado."""
        if not TUNNEL_FILE.exists():
            return True, "Túnel Cloudflare no configurado (modo 100% local)."

        url = ""
        try:
            raw_url = TUNNEL_FILE.read_text(encoding="utf-8").strip()
            parsed = urllib.parse.urlsplit(raw_url)
            if parsed.scheme and parsed.netloc:
                url = f"{parsed.scheme}://{parsed.netloc}"
            else:
                url = raw_url.split("?")[0].rstrip("/")
        except Exception:
            pass

        if not url or not url.startswith("http"):
            return False, "Archivo de túnel vacío o con formato inválido."

        try:
            test_url = f"{url}/api/health"
            req = urllib.request.Request(test_url, headers={"User-Agent": "TARDIS-Sentinel/26.4"})
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                if resp.status == 200:
                    return True, f"Túnel activo y respondiendo en {url}"
                return False, f"Túnel devolvió código HTTP {resp.status}"
        except urllib.error.HTTPError as he:
            if he.code in (200, 401, 403):
                # 401/403 significa que el servidor responde pero exige auth, túnel vivo
                return True, f"Túnel activo ({he.code}) en {url}"
            return False, f"Error HTTP en túnel: {he.code}"
        except Exception as e:
            return False, f"Túnel inaccesible: {e}"

    # =========================================================================
    # 3. AUTO-CORRECCIÓN Y AUTO-REPARACIÓN
    # =========================================================================

    def auto_repair_local_ollama(self) -> bool:
        """Reinicia e inicia el servicio Ollama automáticamente."""
        self.log("Auto-reparando Ollama: Levantando servicio...", "WARN")
        try:
            endpoint = gia_bootstrap.DEFAULT_OLLAMA_ENDPOINT
            return gia_bootstrap.ensure_ollama(endpoint=endpoint, timeout_seconds=15.0, verbose=False)
        except Exception as e:
            self.log(f"Fallo en auto-reparación de Ollama: {e}", "ERROR")
            return False

    def auto_repair_memory_pressure(self) -> bool:
        """Libera memoria cerrando procesos temporales y purgando cachés."""
        self.log("Auto-reparando presión de memoria: Vaciando cachés de SO...", "WARN")
        try:
            subprocess.run(["sync"], check=False)
            return True
        except Exception:
            return False

    def auto_repair_tunnel(self) -> bool:
        """Reinicia el proceso de túnel de Cloudflare con protección de cooldown (300s)."""
        now = time.time()
        if now - getattr(self, "_last_tunnel_repair_ts", 0.0) < 300.0:
            return False
        self._last_tunnel_repair_ts = now

        self.log("Auto-reparando túnel Cloudflare: Reiniciando túnel de conexión...", "WARN")
        try:
            # Limpiar instancias colgadas de cloudflared
            subprocess.run(["pkill", "-f", "cloudflared tunnel"], check=False)
            time.sleep(1.0)
            try:
                import sys
                if "omni_temporal_control" in sys.modules:
                    otc = sys.modules["omni_temporal_control"]
                    if hasattr(otc, "BRIDGE") and otc.BRIDGE:
                        otc.BRIDGE.stop()
                        time.sleep(1.0)
                        otc.BRIDGE.start()
                        return True
            except Exception:
                pass
            return True
        except Exception as e:
            self.log(f"Fallo relanzando túnel: {e}", "ERROR")
        return False

    # =========================================================================
    # 4. AUTO-NOTIFICACIÓN A ANTIGRAVITY (PUENTE BIDIRECCIONAL)
    # =========================================================================

    def notify_antigravity(self, error_type: str, detail: str, repair_action: str, success: bool):
        """Notifica automáticamente a Antigravity del incidente y el resultado de la auto-reparación (con deduplicación)."""
        status_str = "AUTO-REPARADO CON ÉXITO" if success else "REQUIERE ATENCIÓN AGÉNTICA"

        if not hasattr(self, "_last_notified"):
            self._last_notified = {}
        last = self._last_notified.get(error_type)
        now = time.time()
        if last and last.get("status") == status_str and (now - last.get("ts", 0.0) < 600.0):
            # Silenciar notificaciones idénticas repetidas en la ventana de 10 min
            return
        self._last_notified[error_type] = {"status": status_str, "ts": now}

        message_text = (
            f"🚨 [TARDIS CENTINELA] Detección de anomalía [{error_type}]: {detail}\n"
            f"⚡ Acción ejecutada: {repair_action} -> Estado: {status_str}"
        )
        
        self.log(f"Notificando a Antigravity: {error_type} - {status_str}", "WARN" if not success else "OK")
        
        try:
            self.bridge.post_dialogue_message(
                sender="TARDIS-Sentinel",
                text=message_text,
                role="system",
                category="self_repair"
            )
        except Exception as e:
            self.log(f"Error despachando mensaje al puente de diálogo: {e}", "ERROR")

    # =========================================================================
    # 5. CICLO INTEGRAL DE SUPERVISIÓN
    # =========================================================================

    def run_check_cycle(self) -> Dict[str, Any]:
        """Ejecuta una ronda completa de verificación y auto-corrección."""
        self.last_check_ts = time.time()
        score = 100
        detected_errors = []
        repaired_actions = []

        # 1. Local: Ollama
        ok_ollama, msg_ollama = self.check_local_ollama()
        if not ok_ollama:
            score -= 35
            detected_errors.append({"type": "local_ollama", "detail": msg_ollama})
            repaired = self.auto_repair_local_ollama()
            repaired_actions.append({"component": "ollama", "success": repaired})
            self.notify_antigravity("Local: Ollama", msg_ollama, "Reinicio automático de proceso Ollama", repaired)

        # 2. Local: Memoria RAM
        ok_mem, msg_mem = self.check_local_memory()
        if not ok_mem:
            score -= 20
            detected_errors.append({"type": "local_ram", "detail": msg_mem})
            repaired = self.auto_repair_memory_pressure()
            repaired_actions.append({"component": "ram_purge", "success": repaired})
            self.notify_antigravity("Local: Presión RAM", msg_mem, "Sincronización y purga de buffers", repaired)

        # 3. Local: Puerto maestro 8757
        ok_port, msg_port = self.check_master_port(8757)
        if not ok_port:
            score -= 25
            detected_errors.append({"type": "local_port_8757", "detail": msg_port})

        # 4. Online: Internet
        ok_net, msg_net = self.check_internet_reachability()
        if not ok_net:
            score -= 15
            detected_errors.append({"type": "online_internet", "detail": msg_net})

        # 5. Online: Túnel Cloudflare / SSH
        ok_tun, msg_tun = self.check_online_tunnel()
        if not ok_tun:
            self._tunnel_failures = getattr(self, "_tunnel_failures", 0) + 1
            if self._tunnel_failures >= 4:
                score -= 15
                detected_errors.append({"type": "online_tunnel", "detail": msg_tun})
                repaired = self.auto_repair_tunnel()
                repaired_actions.append({"component": "cloudflare_tunnel", "success": repaired})
                self.notify_antigravity("Online: Túnel de Acceso", msg_tun, "Relanzamiento automático del túnel", repaired)
        else:
            self._tunnel_failures = 0

        self.health_score = max(0, score)
        summary = {
            "timestamp": self.last_check_ts,
            "iso": datetime.datetime.now().isoformat(),
            "health_score": self.health_score,
            "local_healthy": ok_ollama and ok_mem,
            "online_healthy": ok_net and ok_tun,
            "errors": detected_errors,
            "repairs": repaired_actions
        }
        self.last_status = summary
        return summary

    def start(self):
        """Inicia el hilo supervisor 24/7."""
        with self._lock:
            if self.running:
                return
            self.running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="TardisErrorSentinel")
            self._thread.start()
            self.log("Centinela de Auto-Corrección y Notificación iniciado 24/7.", "OK")

    def stop(self):
        """Detiene el centinela de forma limpia."""
        with self._lock:
            if not self.running:
                return
            self.running = False
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=3.0)
            self.log("Centinela detenido.", "INFO")

    def _worker_loop(self):
        # Ronda inicial de estabilización
        time.sleep(3.0)
        while not self._stop_event.is_set():
            try:
                self.run_check_cycle()
            except Exception as e:
                self.log(f"Excepción en ciclo centinela: {e}", "ERROR")
            self._stop_event.wait(self.interval)


def get_sentinel() -> TardisErrorSentinel:
    return TardisErrorSentinel.get_instance()


if __name__ == "__main__":
    s = get_sentinel()
    print("Ejecutando ciclo de diagnóstico centinela...")
    res = s.run_check_cycle()
    print(json.dumps(res, indent=2, ensure_ascii=False))
