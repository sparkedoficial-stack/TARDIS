"""
cleanup_models.py - Limpieza profunda de modelos obsoletos y residuos en el sistema.
Mantiene única y exclusivamente TARDIS-NEURAL-SPACE-KAIJU en Ollama y libera espacio en disco.
"""
import json
import os
import subprocess
import sys
import time

import gia_sovereign_engine as gse

print("=== INICIANDO LIMPIEZA TOTAL DE MODELOS OBSOLETOS ===")
eng = gse.get_engine()
diag = eng.diagnose_and_heal(auto_start=True, wait_seconds=15)
print("Estado del motor:", diag.get("mode"), "| Endpoint:", diag.get("endpoint"))

# 1. Obtener modelos actuales
models = eng.get_available_models(refresh=True)
print(f"Modelos detectados ({len(models)}):", models)

preserve_keywords = ["tardis-neural-space-kaiju"]

binary = gse.find_ollama_binary()
for m in models:
    name = m.strip()
    is_target = any(k in name.lower() for k in preserve_keywords)
    if not is_target:
        print(f"[*] Eliminando modelo obsoleto: '{name}'...")
        if binary:
            try:
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                res = subprocess.run([binary, "rm", name], capture_output=True, text=True, creationflags=flags)
                print(f"    [OK] Eliminado via CLI: {res.stdout.strip() or res.stderr.strip() or 'OK'}")
            except Exception as ex:
                print(f"    [ERROR] Falló CLI rm: {ex}")

# 2. Eliminar instaladores y cachés temporales en %TEMP%
temp_dir = os.environ.get("TEMP", "")
if temp_dir and os.path.exists(temp_dir):
    for f in ["OllamaSetup.exe", "OllamaSetup(1).exe"]:
        fp = os.path.join(temp_dir, f)
        if os.path.exists(fp):
            try:
                os.remove(fp)
                print(f"[OK] Eliminado residuo temporal: {fp}")
            except Exception:
                pass

# 3. Modelos resultantes
remaining = eng.get_available_models(refresh=True)
print("\n=== MODELOS ACTIVOS EXCLUSIVOS ===")
for r in remaining:
    print(f" ✔ {r}")

print("\n[CLEANUP] Limpieza completada con éxito.")
