#!/usr/bin/env python3
"""
projects/linpad_m2.py — Script de Diagnóstico y Control de LinPad 1.6.0-TARDIS-M2
=================================================================================
Ejecutable directamente desde el IDE Soberano en el iPad Pro M2.
"""
import json
import sys

sys.path.insert(0, "/home/timemachine")
from modulos_ftl.ftl_linpad import FtlLinpad


def main() -> None:
    ctl = FtlLinpad()
    status = ctl.get_status()
    print("=== LINPAD 1.6.0-TARDIS-M2 :: DIAGNÓSTICO DESDE IPAD PRO M2 ===")
    print(status["fastfetch_output"])
    print()
    print(status["tardis_bridge_output"])
    print()
    bench = ctl.run_benchmark()
    print(bench["output"])


if __name__ == "__main__":
    main()
