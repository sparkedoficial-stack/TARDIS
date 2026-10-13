"""
core/config.py - Gestor Centralizado de Configuración para GODWORKS SYSTEM v26.4
Carga valores desde .env, variables de entorno del sistema y parámetros por defecto.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(dotenv_path=None, override=False):
        if dotenv_path and Path(dotenv_path).exists():
            try:
                for line in Path(dotenv_path).read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if override or k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass

BASE_DIR = Path(__file__).resolve().parent.parent

# Cargar .env si existe en la raíz sin sobreescribir variables ya exportadas por el sistema/demonio
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)


class Settings:
    def __init__(self):
        # Directorios
        self.base_dir: Path = BASE_DIR
        self.appdata_dir: Path = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
        self.captures_dir: Path = self.appdata_dir / "captures"
        self.telemetry_dir: Path = self.appdata_dir / "telemetry"

        # Red y Servidor HTTP - Restringido a loopback local por diseño de seguridad
        self.host: str = os.getenv("GIA_HOST", "127.0.0.1")
        self.port: int = int(os.getenv("GIA_PORT", "8757"))
        self.token: str = os.getenv("GIA_TOKEN", "")

        # Detección dinámica de hardware (Sintonización para 32 GB RAM / Ryzen 16 hilos)
        total_ram_gb = 32.0
        try:
            import psutil
            total_ram_gb = psutil.virtual_memory().total / (1024**3)
        except Exception:
            pass

        default_ctx = 32768 if total_ram_gb >= 30.0 else (8192 if total_ram_gb >= 22.0 else 2048)
        default_batch = 2048 if total_ram_gb >= 30.0 else (1024 if total_ram_gb >= 22.0 else 512)
        default_budget = 28.0 if total_ram_gb >= 30.0 else (18.0 if total_ram_gb >= 22.0 else round(total_ram_gb * 0.75, 1))

        # Modelo e Inferencia Soberana
        self.model: str = os.getenv("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")
        self.num_ctx: int = int(os.getenv("GIA_NUM_CTX", str(default_ctx)))
        self.num_predict: int = int(os.getenv("GIA_NUM_PREDICT", "512"))
        self.temperature: float = float(os.getenv("GIA_TEMPERATURE", "0.3"))
        self.ollama_url: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        self.ollama_keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
        self.ollama_flash_attention: bool = os.getenv("OLLAMA_FLASH_ATTENTION", "1").lower() in ("1", "true", "yes")
        self.ollama_num_parallel: int = int(os.getenv("OLLAMA_NUM_PARALLEL", "1"))
        self.ram_budget_gb: float = float(os.getenv("GIA_RAM_BUDGET_GB", str(default_budget)))
        self.num_threads: int = int(os.getenv("GIA_NUM_THREADS", "16"))
        self.num_batch: int = int(os.getenv("GIA_NUM_BATCH", str(default_batch)))
        self.use_mlock: bool = os.getenv("GIA_USE_MLOCK", "1").lower() in ("1", "true", "yes")

        # Hardware & Sensores
        self.camera_index: int = int(os.getenv("GIA_CAMERA_INDEX", "0"))
        self.camera_fps: int = int(os.getenv("GIA_CAMERA_FPS", "5"))
        self.camera_idle_timeout: int = int(os.getenv("GIA_CAMERA_IDLE_TIMEOUT", "30"))
        self.enable_face_scanner: bool = os.getenv("GIA_ENABLE_FACE_SCANNER", "1").lower() in ("1", "true", "yes")
        self.enable_rf_radar: bool = os.getenv("GIA_ENABLE_RF_RADAR", "1").lower() in ("1", "true", "yes")

        # Asegurar directorios de trabajo
        for d in (self.captures_dir, self.telemetry_dir):
            d.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "model": self.model,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "temperature": self.temperature,
            "ollama_keep_alive": self.ollama_keep_alive,
            "ollama_flash_attention": self.ollama_flash_attention,
            "camera_index": self.camera_index,
            "camera_fps": self.camera_fps,
            "camera_idle_timeout": self.camera_idle_timeout,
            "enable_face_scanner": self.enable_face_scanner,
            "enable_rf_radar": self.enable_rf_radar
        }


_SETTINGS: Optional[Settings] = None

def get_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings()
    return _SETTINGS
