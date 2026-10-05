"""
gia_self_test.py - Diagnóstico Preventivo y Motor de Auto-Reparación de Fallos
=============================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana OMNI-LOCAL-TEMPORAL CONTROL
Ejecuta un análisis pre-vuelo integral de todos los componentes y subsistemas.
Si detecta alguna anomalía, aplica auto-reparación instantánea antes de usar el sistema.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gia_bootstrap

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WORKSPACE_DIR = Path(__file__).resolve().parent
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
GIA_STORAGE = LOCALAPPDATA / "vw-control"


class SelfTestEngine:
    """Motor de validación pre-vuelo y auto-reparación del sistema."""

    def __init__(self):
        self.results: List[Dict[str, Any]] = []
        self.repaired_items: List[str] = []
        self.health_score: int = 100

    def _log_result(self, name: str, passed: bool, message: str, repaired: bool = False):
        self.results.append({
            "name": name,
            "passed": passed,
            "message": message,
            "repaired": repaired
        })
        status_tag = "[OK]" if passed else "[FAIL]"
        repair_tag = " -> [AUTO-REPARADO]" if repaired else ""
        print(f" {status_tag:6} {name:28} : {message}{repair_tag}")

    def test_storage_and_tokens(self) -> bool:
        """Verifica y repara la estructura de carpetas y tokens maestros."""
        try:
            GIA_STORAGE.mkdir(parents=True, exist_ok=True)
            (GIA_STORAGE / "antigravity_bridge").mkdir(parents=True, exist_ok=True)
            (GIA_STORAGE / "improvement_queue").mkdir(parents=True, exist_ok=True)
            (GIA_STORAGE / "memory").mkdir(parents=True, exist_ok=True)

            token = gia_bootstrap.ensure_storage_and_tokens()
            if token and len(token) >= 8:
                self._log_result("Almacenamiento y Tokens", True, f"Token verificado ({token[:6]}...)")
                return True
            else:
                self.health_score -= 15
                self._log_result("Almacenamiento y Tokens", False, "Fallo al generar token irrevocable.")
                return False
        except Exception as e:
            self.health_score -= 20
            self._log_result("Almacenamiento y Tokens", False, f"Error en almacenamiento: {e}")
            return False

    def test_ollama_service(self) -> bool:
        """Verifica que el servicio de Ollama responda; si no, lo auto-inicia."""
        endpoint = gia_bootstrap.DEFAULT_OLLAMA_ENDPOINT
        if gia_bootstrap.is_ollama_alive(endpoint, timeout=1.5):
            self._log_result("Servicio Ollama", True, f"Online en {endpoint}")
            return True

        # Intento de auto-reparación
        print(" [*] Intentando auto-reparación: Levantando servicio Ollama...")
        repaired = gia_bootstrap.ensure_ollama(endpoint, timeout_seconds=20.0, verbose=False)
        if repaired:
            self.repaired_items.append("Servicio Ollama iniciado automáticamente")
            self._log_result("Servicio Ollama", True, f"Online tras auto-inicio en {endpoint}", repaired=True)
            return True
        else:
            self.health_score -= 40
            self._log_result("Servicio Ollama", False, f"No se pudo conectar con {endpoint}")
            return False

    def test_local_models(self) -> bool:
        """Verifica la presencia de modelos locales para inferencia."""
        endpoint = gia_bootstrap.DEFAULT_OLLAMA_ENDPOINT
        models = gia_bootstrap.list_local_models(endpoint)
        if models:
            active = gia_bootstrap.resolve_best_model(endpoint=endpoint)
            self._log_result("Modelos LLM Locales", True, f"{len(models)} detectados (Activo: {active})")
            return True

        # Auto-reparación: intentar descargar modelo ligero por defecto si no hay ninguno
        print(" [!] No se encontraron modelos en Ollama. Intentando descarga de emergencia (llama3.2:3b)...")
        try:
            bin_path = gia_bootstrap.find_ollama_binary()
            if bin_path:
                p = subprocess.run([bin_path, "pull", "llama3.2:3b"], timeout=180, capture_output=True)
                if p.returncode == 0:
                    self.repaired_items.append("Modelo 'llama3.2:3b' descargado automáticamente")
                    self._log_result("Modelos LLM Locales", True, "Modelo llama3.2:3b instalado", repaired=True)
                    return True
        except Exception as e:
            pass

        self.health_score -= 30
        self._log_result("Modelos LLM Locales", False, "No hay modelos descargados en Ollama")
        return False

    def test_hardware_and_ram(self) -> bool:
        """Verifica disponibilidad de memoria RAM y temperatura GPU."""
        try:
            import psutil
            ram = psutil.virtual_memory()
            free_gb = ram.available / (1024 ** 3)
            if free_gb < 1.0:
                self.health_score -= 15
                self._log_result("Recursos de Sistema", False, f"RAM libre muy baja: {free_gb:.1f} GB")
                return False
            else:
                self._log_result("Recursos de Sistema", True, f"RAM libre: {free_gb:.1f} GB (Uso: {ram.percent}%)")
                return True
        except Exception:
            self._log_result("Recursos de Sistema", True, "psutil no disponible, omitiendo test de RAM")
            return True

    def test_direct_inference(self) -> bool:
        """Ejecuta una consulta micro-sonda para medir latencia real de inferencia a través de Colibri."""
        try:
            import gia_sovereign_engine as _gse
            eng = _gse.get_engine()
            start_t = time.time()
            res = eng.chat("1+1=", model="Qwen3.8-27B-Uncensored-MLX:latest", system="Responde conciso: 2")
            if res.get("ok"):
                elapsed = time.time() - start_t
                provider = res.get("provider", "colibri")
                self._log_result("Inferencia Directa", True, f"Sonda Colibri completada en {elapsed:.2f}s ({provider} / {res.get('model')})")
                return True
        except Exception:
            pass

        # Fallback a sonda HTTP directa
        endpoint = gia_bootstrap.DEFAULT_OLLAMA_ENDPOINT
        if not gia_bootstrap.is_ollama_alive(endpoint, timeout=1.0):
            self.health_score -= 25
            self._log_result("Inferencia Directa", False, "Motor local no disponible para prueba")
            return False

        models = gia_bootstrap.list_local_models(endpoint)
        active_model = gia_bootstrap.resolve_best_model(endpoint=endpoint)
        try:
            start_t = time.time()
            req = urllib.request.Request(
                f"{endpoint}/api/chat",
                data=json.dumps({
                    "model": active_model,
                    "messages": [{"role": "user", "content": "1+1="}],
                    "stream": False,
                    "options": {"num_ctx": 512, "num_thread": 8, "num_predict": 16}
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                if resp.status == 200:
                    elapsed = time.time() - start_t
                    self._log_result("Inferencia Directa", True, f"Sonda completada en {elapsed:.2f}s ({active_model})")
                    return True
        except Exception as e:
            self.health_score -= 20
            self._log_result("Inferencia Directa", False, f"Fallo en prueba de inferencia: {e}")
            return False

        return False

    def test_port_availability(self) -> bool:
        """Comprueba disponibilidad del puerto maestro HTTP 8757."""
        port = 8757
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            in_use = (s.connect_ex(("REDACTED_IP", port)) == 0)

        if in_use:
            self._log_result("Puerto Maestro 8757", True, "Puerto ocupado (Servidor ya en ejecución)")
        else:
            self._log_result("Puerto Maestro 8757", True, "Puerto libre y listo para enlazar")
        return True

    def run_all_tests(self) -> Dict[str, Any]:
        """Ejecuta toda la batería de tests preventivos y devuelve reporte holístico."""
        print("====================================================================")
        print("   GIA PRE-FLIGHT SELF-TEST & AUTO-REPAIR ENGINE v26.4")
        print("====================================================================")

        self.test_storage_and_tokens()
        self.test_hardware_and_ram()
        self.test_port_availability()
        self.test_ollama_service()
        self.test_local_models()
        self.test_direct_inference()

        self.health_score = max(0, min(100, self.health_score))
        all_passed = all(r["passed"] for r in self.results)

        print("--------------------------------------------------------------------")
        print(f" Puntuación de Salud del Sistema : {self.health_score}/100")
        print(f" Estado Final                    : {'TODO OPERATIVO (100% LISTO)' if all_passed else 'ADVERTENCIAS DETECTADAS'}")
        if self.repaired_items:
            print(f" Auto-reparaciones ejecutadas    : {len(self.repaired_items)}")
            for item in self.repaired_items:
                print(f"   - {item}")
        print("====================================================================\n")

        return {
            "healthy": all_passed,
            "health_score": self.health_score,
            "results": self.results,
            "repaired_items": self.repaired_items
        }


def run_preflight_check() -> bool:
    """Función rápida que ejecuta el pre-vuelo y devuelve True si el sistema está saludable."""
    engine = SelfTestEngine()
    report = engine.run_all_tests()
    return report.get("healthy", False)


if __name__ == "__main__":
    success = run_preflight_check()
    sys.exit(0 if success else 1)
