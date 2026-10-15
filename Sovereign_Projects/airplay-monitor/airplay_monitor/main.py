#!/usr/bin/env python3
"""
AirPlay Monitor Soberano - Punto de Entrada Principal
"""
import sys
from pathlib import Path

# Agregar directorio raíz al PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from airplay_monitor.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
