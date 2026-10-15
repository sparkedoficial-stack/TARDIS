"""
config.py - Configuración Central del Sistema Cognitivo Soberano
==============================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any

# Rutas Fundamentales
SYSTEM_ROOT = Path("/home/timemachine/cognitivo_sistema").resolve()
PROJECT_DIR = SYSTEM_ROOT / "proyectos_paralelos"
SOFTWARE_DIR = SYSTEM_ROOT / "software_generado"
SIMULATION_DIR = SYSTEM_ROOT / "simulaciones"
KNOWLEDGE_DIR = SYSTEM_ROOT / "conocimiento"
LOGS_DIR = SYSTEM_ROOT / "logs"

# Integración con el Sistema TARDIS y FTL
TARDIS_ROOT = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM").resolve()
MODULOS_FTL = Path("/home/timemachine/modulos_ftl").resolve()

for directory in (PROJECT_DIR, SOFTWARE_DIR, SIMULATION_DIR, KNOWLEDGE_DIR, LOGS_DIR, MODULOS_FTL):
    directory.mkdir(parents=True, exist_ok=True)

# Parámetros del Núcleo de Inferencia y Servidor GIA Local
GIA_HOST = os.environ.get("GIA_HOST", "127.0.0.1")
GIA_PORT = int(os.environ.get("GIA_PORT", "8757"))
GIA_TOKEN = os.environ.get("GIA_TOKEN", "GIA-Nt2HE-cn4mFV2bR-XqI6UUqSV9CAQZEgK6-BgBEtofM")
GIA_URL = f"http://{GIA_HOST}:{GIA_PORT}"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# Configuración de Hardware y Telemetría Kernel
CPU_TOTAL_THREADS = 16  # AMD Ryzen 7 4800H
RAM_TOTAL_GB = 32.0
GPU_TARGET = "NVIDIA GeForce RTX 3050 Laptop GPU"
MAX_SIMULATION_RUNTIME_SEC = 120
AUTOPROGRAM_TIMEOUT_SEC = 45
MAX_REPAIR_ATTEMPTS = 3

# Intervalos de Auto-Entrenamiento y Curiosidad (en segundos)
DEFAULT_LEARNING_INTERVAL = 3600  # 1 hora por ciclo autónomo
CURIOSITY_DRIFT_FACTOR = 0.15

# Archivo de Estado y Bitácora Cognitiva
DIARIO_COGNITIVO_PATH = SYSTEM_ROOT / "diario_cognitivo.json"
ESTADO_SISTEMA_PATH = SYSTEM_ROOT / "estado_cognitivo.json"
