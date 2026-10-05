"""
core/package_manager.py - Gestor Autónomo de Paqueterías y Sistemas Soberanos
GODWORKS SYSTEM v26.4

Permite al sistema, al modelo de IA local y al Arquitecto instalar, actualizar
y auditar librerías de Python en el entorno virtual activo (.venv-linux),
descargar modelos de Ollama y desplegar utilidades del sistema en ~/.local/bin.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import BASE_DIR, get_settings

logger = logging.getLogger("GODWORKS.PackageManager")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# Mapeo de módulos estándar de importación hacia el paquete PyPI correspondiente
MODULE_TO_PYPI = {
    "PIL": "Pillow",
    "cv2": "opencv-python-headless",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "serial": "pyserial",
    "magic": "python-magic",
    "jwt": "PyJWT",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "fitz": "PyMuPDF",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "openpyxl": "openpyxl",
    "xlsxwriter": "XlsxWriter",
    "psutil": "psutil",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "websockets": "websockets",
    "requests": "requests",
    "httpx": "httpx",
    "numpy": "numpy",
    "scipy": "scipy",
    "pandas": "pandas",
    "torch": "torch",
    "edge_tts": "edge-tts",
    "mss": "mss",
    "pyautogui": "pyautogui",
}


class PackageManager:
    """
    Gestor Soberano de Paqueterías y Entornos.
    Garantiza que el sistema pueda auto-reparar dependencias faltantes y expandir
    sus capacidades algorítmicas de forma completamente autónoma.
    """

    _instance: Optional["PackageManager"] = None

    def __init__(self):
        self.settings = get_settings()
        self.base_dir: Path = BASE_DIR
        self.venv_dir: Path = self.base_dir / ".venv-linux"
        self.pip_path: Path = self.venv_dir / "bin" / "pip"
        self.python_path: Path = self.venv_dir / "bin" / "python3"
        self.user_bin_dir: Path = Path(os.path.expanduser("~/.local/bin"))
        self.user_bin_dir.mkdir(parents=True, exist_ok=True)

        # Fallback si no está el venv directo
        if not self.pip_path.exists():
            system_pip = shutil.which("pip3") or shutil.which("pip")
            if system_pip:
                self.pip_path = Path(system_pip)

        self.history_file: Path = self.settings.telemetry_dir / "package_manager_history.json"
        self._ensure_history_file()

    @classmethod
    def get_instance(cls) -> "PackageManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_history_file(self):
        if not self.history_file.exists():
            try:
                self.history_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.history_file, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2)
            except Exception as e:
                logger.warning(f"No se pudo inicializar historial de paquetes: {e}")

    def _record_history(self, entry: Dict[str, Any]):
        try:
            entries = []
            if self.history_file.exists():
                with open(self.history_file, "r", encoding="utf-8") as f:
                    entries = json.load(f)
            entries.append(entry)
            # Mantener los últimos 200 registros
            if len(entries) > 200:
                entries = entries[-200:]
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
        except Exception as e:
            logger.warning(f"Error registrando historial: {e}")

    def get_environment_info(self) -> Dict[str, Any]:
        """Devuelve información detallada del entorno de ejecución y rutas."""
        return {
            "python_executable": str(self.python_path if self.python_path.exists() else sys.executable),
            "pip_executable": str(self.pip_path if self.pip_path.exists() else "not_found"),
            "venv_dir": str(self.venv_dir),
            "venv_active": self.venv_dir.exists(),
            "user_bin_dir": str(self.user_bin_dir),
            "ram_budget_gb": getattr(self.settings, "ram_budget_gb", 18.0),
            "ollama_host": getattr(self.settings, "ollama_url", "http://REDACTED_IP:11434"),
        }

    def list_installed_packages(self, filter_term: str = "") -> List[Dict[str, str]]:
        """
        Lista todas las librerías instaladas en el entorno virtual de Python.
        """
        if not self.pip_path.exists():
            return []

        try:
            cmd = [str(self.pip_path), "list", "--format=json"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                pkgs = json.loads(res.stdout)
                if filter_term:
                    f_term = filter_term.lower().strip()
                    pkgs = [p for p in pkgs if f_term in p.get("name", "").lower()]
                return pkgs
            else:
                logger.error(f"Error listando paquetes pip: {res.stderr}")
                return []
        except Exception as e:
            logger.error(f"Excepción en list_installed_packages: {e}")
            return []

    def install_python_package(
        self, package_name: str, upgrade: bool = False, extra_args: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Instala de forma segura un paquete de Python en .venv-linux.
        Soporta especificación de versiones (ej: `numpy>=1.24.0`, `scipy`).
        """
        t0 = time.time()
        pkg_clean = package_name.strip()
        if not pkg_clean:
            return {"ok": False, "error": "Nombre de paquete vacío."}

        # Validación básica de seguridad para evitar comandos maliciosos
        if not re.match(r"^[a-zA-Z0-9_\-\.\[\],=<>~!@/]+$", pkg_clean):
            return {"ok": False, "error": f"Nombre de paquete inválido o con caracteres no permitidos: {pkg_clean}"}

        if not self.pip_path.exists():
            return {"ok": False, "error": f"Binario pip no encontrado en {self.pip_path}"}

        cmd = [str(self.pip_path), "install"]
        if upgrade:
            cmd.append("--upgrade")
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(pkg_clean)

        logger.info(f"Instalando paquete Python: {' '.join(cmd)}")
        try:
            env = os.environ.copy()
            env["PATH"] = f"{self.venv_dir / 'bin'}:{env.get('PATH', '')}"
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
            duration = round(time.time() - t0, 2)
            success = (res.returncode == 0)

            history_entry = {
                "type": "python_package",
                "package": pkg_clean,
                "command": " ".join(cmd),
                "success": success,
                "returncode": res.returncode,
                "duration_seconds": duration,
                "timestamp": time.time(),
                "time_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._record_history(history_entry)

            if success:
                logger.info(f"Paquete {pkg_clean} instalado con éxito ({duration}s).")
                return {
                    "ok": True,
                    "package": pkg_clean,
                    "duration_seconds": duration,
                    "stdout": res.stdout.strip(),
                    "message": f"Paquete '{pkg_clean}' instalado exitosamente.",
                }
            else:
                logger.warning(f"Fallo al instalar {pkg_clean}: {res.stderr}")
                return {
                    "ok": False,
                    "package": pkg_clean,
                    "duration_seconds": duration,
                    "error": res.stderr.strip() or res.stdout.strip(),
                    "message": f"Error instalando '{pkg_clean}'.",
                }
        except subprocess.TimeoutExpired:
            return {"ok": False, "package": pkg_clean, "error": "Tiempo de espera agotado (timeout 300s)."}
        except Exception as e:
            return {"ok": False, "package": pkg_clean, "error": str(e)}

    def uninstall_python_package(self, package_name: str) -> Dict[str, Any]:
        """Desinstala un paquete de Python de forma no interactiva."""
        pkg_clean = package_name.strip()
        if not pkg_clean:
            return {"ok": False, "error": "Nombre de paquete vacío."}

        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", pkg_clean):
            return {"ok": False, "error": f"Nombre de paquete inválido: {pkg_clean}"}

        cmd = [str(self.pip_path), "uninstall", "-y", pkg_clean]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return {
                "ok": res.returncode == 0,
                "package": pkg_clean,
                "stdout": res.stdout.strip(),
                "error": res.stderr.strip() if res.returncode != 0 else None,
            }
        except Exception as e:
            return {"ok": False, "package": pkg_clean, "error": str(e)}

    def auto_install_missing_module(self, module_name: str) -> Dict[str, Any]:
        """
        Auto-recuperación ante `ModuleNotFoundError`.
        Traduce el nombre del módulo importado al paquete PyPI adecuado y lo instala.
        """
        mod = module_name.strip()
        # Verificar mapeo
        target_pkg = MODULE_TO_PYPI.get(mod, mod)
        logger.info(f"Auto-resolviendo módulo faltante: {mod} -> PyPI: {target_pkg}")
        return self.install_python_package(target_pkg)

    def pull_ollama_model(self, model_name: str) -> Dict[str, Any]:
        """
        Descarga de forma asíncrona o directa un modelo de IA en el servidor Ollama local.
        """
        m_clean = model_name.strip()
        if not m_clean:
            return {"ok": False, "error": "Nombre de modelo vacío."}

        if not re.match(r"^[a-zA-Z0-9_\-\.:/]+$", m_clean):
            return {"ok": False, "error": f"Nombre de modelo no válido: {m_clean}"}

        ollama_bin = shutil.which("ollama") or "/usr/local/bin/ollama" or "/usr/bin/ollama"
        t0 = time.time()

        if shutil.which("ollama"):
            try:
                cmd = ["ollama", "pull", m_clean]
                logger.info(f"Iniciando descarga de modelo Ollama: {' '.join(cmd)}")
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                duration = round(time.time() - t0, 2)
                success = (res.returncode == 0)

                self._record_history({
                    "type": "ollama_model",
                    "model": m_clean,
                    "success": success,
                    "duration_seconds": duration,
                    "timestamp": time.time(),
                    "time_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                })

                if success:
                    return {
                        "ok": True,
                        "model": m_clean,
                        "duration_seconds": duration,
                        "message": f"Modelo Ollama '{m_clean}' descargado e integrado con éxito.",
                        "stdout": res.stdout.strip(),
                    }
                else:
                    return {
                        "ok": False,
                        "model": m_clean,
                        "error": res.stderr.strip() or res.stdout.strip(),
                    }
            except subprocess.TimeoutExpired:
                return {"ok": False, "model": m_clean, "error": "Tiempo de descarga agotado (timeout 600s)."}
            except Exception as e:
                return {"ok": False, "model": m_clean, "error": str(e)}

        # Fallback a petición HTTP directa a la API de Ollama
        try:
            import urllib.request
            url = f"{getattr(self.settings, 'ollama_url', 'http://REDACTED_IP:11434')}/api/pull"
            req = urllib.request.Request(
                url,
                data=json.dumps({"name": m_clean, "stream": False}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=300) as response:
                body = response.read().decode("utf-8")
                return {"ok": True, "model": m_clean, "response": json.loads(body)}
        except Exception as e:
            return {"ok": False, "model": m_clean, "error": f"Fallo al contactar API de Ollama: {e}"}

    def install_system_package(self, package_name: str) -> Dict[str, Any]:
        """
        Instala herramientas de sistema o paquetes binarios en ~/.local/bin o apt si hay privilegios.
        """
        pkg_clean = package_name.strip()
        if not pkg_clean or not re.match(r"^[a-zA-Z0-9_\-\.]+$", pkg_clean):
            return {"ok": False, "error": f"Nombre de paquete de sistema inválido: {pkg_clean}"}

        # 1. Verificar si ya existe en el PATH o en ~/.local/bin
        bin_path = shutil.which(pkg_clean)
        if bin_path:
            return {"ok": True, "package": pkg_clean, "already_installed": True, "path": bin_path}

        # 2. Intentar apt-get con sudo no interactivo (-n)
        try:
            cmd = ["sudo", "-n", "apt-get", "install", "-y", pkg_clean]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode == 0:
                return {
                    "ok": True,
                    "package": pkg_clean,
                    "method": "apt-get",
                    "stdout": res.stdout.strip()
                }
        except Exception:
            pass

        # 3. Intentar snap si existe
        if shutil.which("snap"):
            try:
                cmd = ["sudo", "-n", "snap", "install", pkg_clean]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if res.returncode == 0:
                    return {"ok": True, "package": pkg_clean, "method": "snap", "stdout": res.stdout.strip()}
            except Exception:
                pass

        return {
            "ok": False,
            "package": pkg_clean,
            "error": "No se pudo instalar con apt/snap sin intervención de contraseña de superusuario. "
                     "Para binarios standalone o librerías de Python, use install_python_package."
        }

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Devuelve el historial de instalaciones recientes."""
        try:
            if self.history_file.exists():
                with open(self.history_file, "r", encoding="utf-8") as f:
                    entries = json.load(f)
                    return entries[-limit:]
            return []
        except Exception:
            return []


def get_package_manager() -> PackageManager:
    return PackageManager.get_instance()
