"""
REA Bridge for Xcode on Linux
Integrates Reverse-Engineer-Anything (REA) with the Linux Xcode environment.
Provides automated IPA decompilation, entitlement extraction, and binary diagnostics.
"""

import os
import sys
import zipfile
import plistlib
import subprocess
from macho_engine import parse_macho, print_macho_summary

def inspect_ipa_with_rea(ipa_path):
    """Deep inspection of an iOS/iPadOS IPA package."""
    if not os.path.isfile(ipa_path):
        return {"error": f"IPA file not found: {ipa_path}"}

    results = {
        "ipa": ipa_path,
        "size": os.path.getsize(ipa_path),
        "app_name": None,
        "bundle_id": None,
        "version": None,
        "min_ios": None,
        "executable": None,
        "macho_info": None,
        "entitlements": None,
        "embedded_frameworks": [],
        "has_mobileprovision": False,
        "files_count": 0,
    }

    try:
        with zipfile.ZipFile(ipa_path, "r") as z:
            results["files_count"] = len(z.infolist())
            
            # Find Info.plist
            info_plists = [n for n in z.namelist() if n.endswith(".app/Info.plist")]
            if info_plists:
                plist_data = z.read(info_plists[0])
                pl = plistlib.loads(plist_data)
                results["bundle_id"] = pl.get("CFBundleIdentifier")
                results["app_name"] = pl.get("CFBundleDisplayName") or pl.get("CFBundleName")
                results["version"] = pl.get("CFBundleShortVersionString") or pl.get("CFBundleVersion")
                results["min_ios"] = pl.get("MinimumOSVersion")
                exec_name = pl.get("CFBundleExecutable")
                app_dir = os.path.dirname(info_plists[0])
                if exec_name:
                    results["executable"] = f"{app_dir}/{exec_name}"

            # Check embedded mobileprovision
            provs = [n for n in z.namelist() if n.endswith("embedded.mobileprovision")]
            if provs:
                results["has_mobileprovision"] = True

            # Frameworks
            frameworks = set()
            for n in z.namelist():
                if ".framework/" in n:
                    parts = n.split(".framework/")[0] + ".framework"
                    frameworks.add(os.path.basename(parts))
            results["embedded_frameworks"] = sorted(list(frameworks))

            # Extract main binary to inspect Mach-O structure if available
            if results["executable"] and results["executable"] in z.namelist():
                import tempfile
                with tempfile.NamedTemporaryFile(suffix="_macho") as tmp:
                    tmp.write(z.read(results["executable"]))
                    tmp.flush()
                    results["macho_info"] = parse_macho(tmp.name)
                    results["macho_info"]["file"] = results["executable"]

    except Exception as e:
        results["error"] = str(e)

    return results

def print_ipa_report(res):
    """Prints a structured REA report for an iOS app."""
    if "error" in res:
        print(f"[!] Error inspecting IPA: {res['error']}")
        return
    print("==========================================================")
    print("          REA SOBERANO: REPORTE DE IPA / XCODE            ")
    print("==========================================================")
    print(f"Paquete IPA:       {os.path.basename(res['ipa'])}")
    print(f"Tamaño:            {res['size']/1024/1024:.2f} MB ({res['files_count']} archivos empaquetados)")
    print(f"Nombre de la App:  {res['app_name'] or 'N/A'}")
    print(f"Bundle Identifier: {res['bundle_id'] or 'N/A'}")
    print(f"Versión:           {res['version'] or 'N/A'}")
    print(f"Versión Mínima iOS:{res['min_ios'] or 'N/A'}")
    print(f"Ejecutable Mach-O: {res['executable'] or 'N/A'}")
    print(f"Mobileprovision:   {'Presente (Firmado previo)' if res['has_mobileprovision'] else 'Ausente (Requiere firma/sideloading)'}")
    print(f"Frameworks:        {len(res['embedded_frameworks'])} embebidos")
    for fw in res['embedded_frameworks'][:6]:
        print(f"  * {fw}")
    if len(res['embedded_frameworks']) > 6:
        print(f"  ... y {len(res['embedded_frameworks']) - 6} frameworks adicionales.")

    if res.get("macho_info"):
        print("\n--- Telemetría del Binario Mach-O ---")
        archs = ", ".join(s["arch"] for s in res["macho_info"]["slices"])
        print(f"Arquitecturas:     {archs}")
        print(f"Firma Criptográfica:{'Sí' if res['macho_info']['has_codesig'] else 'No'}")
        print(f"Cifrado DRM FairPlay:{'Sí (Protegido)' if res['macho_info']['is_encrypted'] else 'No (Limpio/Desencriptado)'}")
        print(f"Librerías Dinámicas: {len(res['macho_info']['dylibs'])} enlazadas")
    print("==========================================================")
