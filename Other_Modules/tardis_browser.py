#!/usr/bin/env python3
"""
tardis_browser.py - Punto de Entrada Soberano de Navegación Cuántica TARDIS
============================================================================
Acceso directo desde /home/timemachine para control 100% autónomo.
"""

import sys
from pathlib import Path

# Inyectar Escritorio/GODWORKS SYSTEM al path
CORE_DIR = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from core.tardis_browser import (
    TardisBrowser,
    TardisTurboEngine,
    TardisCDPEngine,
    TardisCognitiveLearner,
    TardisAutonomousLearningLoop,
    get_tardis_browser,
    main,
)

if __name__ == "__main__":
    main()
