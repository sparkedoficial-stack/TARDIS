"""
modulos_ftl/ftl_linpad.py - Controlador Soberano de LinPad 1.6.0-TARDIS-M2
==========================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU · FTL AUTOMATION SUITE
Arquitecto: El Arquitecto (₪)

Módulo de control, compilación, telemetría y sincronización bidireccional
para LinPad 1.6.0-TARDIS-M2 (Linux Desktop Environment para Apple iPad Pro M2
y motor nativo iSH + Wayland Compositor Bridge ishwl en Linux).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class FtlLinpad:
    """
    Controlador soberano de LinPad 1.6.0-TARDIS-M2 para FTL, TARDIS y AGY.
    """

    def __init__(self) -> None:
        self.name = "linpad"
        self.version = "1.6.0-TARDIS-M2"
        self.repo_dir = Path("/home/timemachine/LinPad")
        self.build_dir = self.repo_dir / "build-linux"
        self.wl_bridge_dir = self.repo_dir / "wl-bridge"
        self.ipa_path = self.repo_dir / "build" / "LinPad-1.6.0-TARDIS-M2.ipa"
        self.catalog_path = self.repo_dir / "release" / "guest" / "linpad" / "catalog.json"
        self.themes_path = (
            self.repo_dir
            / "desktop"
            / "DesktopKit"
            / "Sources"
            / "DesktopKit"
            / "Resources"
            / "ColorThemes"
            / "themes.json"
        )
        self.repair_kit_json = (
            self.repo_dir / "build" / "unpacked" / "Payload" / "iSH ARM64.app" / "repair-kit.json"
        )

    def _run_cmd(self, cmd: List[str], timeout: int = 30) -> Dict[str, Any]:
        env = os.environ.copy()
        env["PATH"] = f"/usr/local/bin:/home/timemachine/.local/bin:{env.get('PATH', '')}"
        start_t = time.time()
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.repo_dir),
                env=env,
            )
            return {
                "ok": res.returncode == 0,
                "rc": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "elapsed_s": round(time.time() - start_t, 3),
            }
        except Exception as e:
            return {"ok": False, "rc": -1, "error": str(e)}

    def get_status(self) -> Dict[str, Any]:
        """Obtiene el estado integral de LinPad 1.6.0-TARDIS-M2."""
        dev_info = {}
        for field in (
            "app",
            "host",
            "chip",
            "cpu",
            "jit",
            "gpu",
            "style",
            "theme",
            "ftl",
        ):
            r = self._run_cmd(["/usr/local/bin/ish-device-info", field], timeout=5)
            dev_info[field] = r.get("stdout", "")

        fetch_res = self._run_cmd(["/usr/local/bin/linpad-fetch", "--pipe"], timeout=8)
        tardis_res = self._run_cmd(["/usr/local/bin/linpad-tardis", "status"], timeout=8)

        repair_meta = {}
        if self.repair_kit_json.exists():
            try:
                rk = json.loads(self.repair_kit_json.read_text(encoding="utf-8"))
                repair_meta = {
                    "version": rk.get("version"),
                    "built": rk.get("built"),
                    "entries_count": len(rk.get("entries", [])),
                }
            except Exception:
                pass

        return {
            "status": "ok",
            "version": self.version,
            "device_info": dev_info,
            "fastfetch_output": fetch_res.get("stdout", ""),
            "tardis_bridge_output": tardis_res.get("stdout", ""),
            "native_binaries": {
                "ish": {
                    "path": str(self.build_dir / "ish"),
                    "exists": (self.build_dir / "ish").exists(),
                    "size_bytes": (self.build_dir / "ish").stat().st_size
                    if (self.build_dir / "ish").exists()
                    else 0,
                },
                "ishwl": {
                    "path": str(self.wl_bridge_dir / "ishwl"),
                    "exists": (self.wl_bridge_dir / "ishwl").exists(),
                    "size_bytes": (self.wl_bridge_dir / "ishwl").stat().st_size
                    if (self.wl_bridge_dir / "ishwl").exists()
                    else 0,
                },
                "fakefsify": {
                    "path": str(self.build_dir / "tools" / "fakefsify"),
                    "exists": (self.build_dir / "tools" / "fakefsify").exists(),
                },
            },
            "ipa_package": {
                "path": str(self.ipa_path),
                "exists": self.ipa_path.exists(),
                "size_mb": round(self.ipa_path.stat().st_size / (1024 * 1024), 2)
                if self.ipa_path.exists()
                else 0,
                "ipad_afc_path": "/Downloads/LinPad-1.6.0-TARDIS-M2.ipa",
            },
            "repair_kit": repair_meta,
        }

    def get_catalog(self) -> Dict[str, Any]:
        """Devuelve el catálogo de aplicaciones de LinPad (catalog.json)."""
        if not self.catalog_path.exists():
            return {"status": "error", "error": "catalog.json no encontrado"}
        try:
            data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            return {
                "status": "ok",
                "version": data.get("version"),
                "categories": data.get("categories", []),
                "packs": data.get("packs", []),
                "total_packs": len(data.get("packs", [])),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_themes(self) -> Dict[str, Any]:
        """Devuelve el catálogo de esquemas de color Omarchy (themes.json)."""
        if not self.themes_path.exists():
            return {"status": "error", "error": "themes.json no encontrado"}
        try:
            themes = json.loads(self.themes_path.read_text(encoding="utf-8"))
            return {
                "status": "ok",
                "total_themes": len(themes),
                "themes": themes,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def run_benchmark(self) -> Dict[str, Any]:
        """Ejecuta el benchmark de subsistema LinPad TARDIS M2."""
        res = self._run_cmd(["/usr/local/bin/linpad-tardis", "benchmark"], timeout=25)
        return {
            "status": "ok" if res.get("ok") else "error",
            "output": res.get("stdout", ""),
            "elapsed_s": res.get("elapsed_s", 0),
        }

    def run(self, action: str = "status", **kwargs: Any) -> Dict[str, Any]:
        """
        Punto de entrada universal para FTL Omni-Registry y TARDIS Bridge.
        Acciones soportadas:
          - 'status': Estado integral de LinPad M2, binarios nativos e IPA.
          - 'fetch': Salida de linpad-fetch + ish-device-info.
          - 'catalog' / 'apps': Lista los paquetes de aplicaciones de LinPad.
          - 'themes': Lista los temas visuales Omarchy (incluyendo tardis-m2).
          - 'benchmark': Ejecuta linpad-tardis benchmark.
          - 'tests': Ejecuta la suite de pruebas CTest (fifo_test, float80_test).
        """
        act = action.lower().strip()
        if act in ("status", "info"):
            return self.get_status()
        elif act == "fetch":
            r = self._run_cmd(["/usr/local/bin/linpad-fetch", "--pipe"], timeout=8)
            return {"status": "ok" if r.get("ok") else "error", "output": r.get("stdout", "")}
        elif act in ("catalog", "apps"):
            return self.get_catalog()
        elif act == "themes":
            return self.get_themes()
        elif act == "benchmark":
            return self.run_benchmark()
        elif act == "tests":
            r = self._run_cmd(["ctest", "--test-dir", str(self.build_dir), "--output-on-failure"], timeout=30)
            return {"status": "ok" if r.get("ok") else "error", "output": r.get("stdout", "")}
        else:
            return {
                "status": "error",
                "error": f"Acción '{action}' no reconocida en FtlLinpad.",
                "supported_actions": ["status", "fetch", "catalog", "themes", "benchmark", "tests"],
            }

    execute = run


if __name__ == "__main__":
    import sys

    ctl = FtlLinpad()
    act = sys.argv[1] if len(sys.argv) > 1 else "status"
    print(json.dumps(ctl.run(act), indent=2, ensure_ascii=False))
