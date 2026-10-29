"""
modulos_ftl/ftl_nxnative.py - Controlador Soberano de nxnative · Mario Kart 8 Deluxe (0100152000022000)
========================================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU · FTL AUTOMATION SUITE
Arquitecto: El Arquitecto (₪)

Módulo soberano de control, compilación, inspección de shaders NVN -> Metal 4,
reescritura de binarios AArch64 NSO y despliegue de nxnative (Mario Kart 8 Deluxe
0100152000022000) para Apple iPad Pro M2 (iPad14,6).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List


class FtlNxnative:
    """
    Controlador soberano de nxnative + Mario Kart 8 Deluxe (0100152000022000) para iPad Pro M2.
    """

    def __init__(self) -> None:
        self.name = "nxnative"
        self.version = "3.0.3-TARDIS-M2"
        self.game_id = "0100152000022000"
        self.game_name = "Mario Kart 8 Deluxe"
        self.bundle_id = f"org.nxnative.{self.game_id}"
        self.repo_dir = Path("/home/timemachine/nxnative")
        self.game_dir = self.repo_dir / "dm" / "games" / self.game_id
        self.build_dir = self.repo_dir / "build"
        self.ipa_path = self.build_dir / "MarioKart8Deluxe.ipa"
        self.app_dir = self.build_dir / "Payload" / "DmRunner.app"
        self.launcher_json = self.app_dir / "dm" / "launcher.json"

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

    def get_mk8d_profile(self) -> Dict[str, Any]:
        """Obtiene las métricas del perfil de Mario Kart 8 Deluxe (0100152000022000)."""
        shader_map = self.game_dir / "shader_map.tsv"
        shader_pairs = self.game_dir / "shader_pairs.tsv"
        pso_manifest = self.game_dir / "pso_manifest.tsv"
        pso_pairs = self.game_dir / "pso_pairs.tsv"
        shader_facts = self.game_dir / "shader_facts.tsv"

        def _count_lines(p: Path) -> int:
            if not p.exists():
                return 0
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return sum(1 for line in f if line.strip() and not line.startswith("#"))

        launcher_settings = []
        if self.launcher_json.exists():
            try:
                data = json.loads(self.launcher_json.read_text(encoding="utf-8"))
                launcher_settings = data.get("settings", [])
            except Exception:
                pass

        return {
            "game_id": self.game_id,
            "name": self.game_name,
            "bundle_id": self.bundle_id,
            "engine": "Nintendo LunchPack + NVN -> Apple Metal 4",
            "builds_tested": [
                {"version": "v1441792", "display": "3.0.3 / 4.0.0", "main": "2c336a9bcf79c3040ce506cdd391b578"},
                {"version": "v1507328", "display": "4.0.1", "main": "158c0c7399aabd7bf83795c2ef3484c7"},
            ],
            "memory_layout": {
                "mem_reserve": "0x100000000 (4.0 GB)",
                "mem_alias": "0x10000000 (256 MB)",
                "mem_stack": "0x10000000 (256 MB)",
                "app_pool": "0xcd500000 (3,285 MB)",
                "mem_used": "0x4000000 (64 MB)",
            },
            "shaders": {
                "shader_map_entries": _count_lines(shader_map),
                "shader_pairs_entries": _count_lines(shader_pairs),
                "pso_manifest_entries": _count_lines(pso_manifest),
                "pso_pairs_entries": _count_lines(pso_pairs),
                "shader_facts_entries": _count_lines(shader_facts),
            },
            "launcher_settings": launcher_settings,
        }

    def get_games_catalog(self) -> Dict[str, Any]:
        """Lista todos los perfiles de juegos soportados por nxnative."""
        games_root = self.repo_dir / "dm" / "games"
        profiles = []
        if games_root.exists():
            for d in sorted(games_root.iterdir()):
                tsv = d / "game.tsv"
                if d.is_dir() and tsv.exists():
                    name = d.name
                    opmode = "1"
                    for line in tsv.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.startswith("name\t"):
                            name = line.split("\t", 1)[1].strip()
                        elif line.startswith("opmode\t"):
                            opmode = line.split("\t", 1)[1].strip()
                    profiles.append({
                        "id": d.name,
                        "name": name,
                        "opmode": "Docked" if opmode == "1" else "Handheld",
                        "is_mk8d": d.name == self.game_id,
                    })
        return {
            "status": "ok",
            "total_profiles": len(profiles),
            "featured": self.game_id,
            "profiles": profiles,
        }

    def get_status(self) -> Dict[str, Any]:
        """Devuelve el estado integral de nxnative + Mario Kart 8 Deluxe en el host e iPad Pro M2."""
        bin_path = self.app_dir / "DmRunner"
        font_path = self.app_dir / "dm" / "nintendo_ext.ttf"
        return {
            "status": "ok",
            "name": self.name,
            "version": self.version,
            "featured_game": self.get_mk8d_profile(),
            "ipa_package": {
                "path": str(self.ipa_path),
                "exists": self.ipa_path.exists(),
                "size_mb": round(self.ipa_path.stat().st_size / (1024 * 1024), 2)
                if self.ipa_path.exists()
                else 0,
                "bundle_id": self.bundle_id,
                "ipad_afc_paths": [
                    "/Downloads/MarioKart8Deluxe.ipa",
                    "/TARDIS_WORKSPACE/nxnative/MarioKart8Deluxe.ipa",
                ],
                "edge_download_url": "/download/MarioKart8Deluxe.ipa",
                "webclip_url": "/mk8d.mobileconfig",
            },
            "artifacts": {
                "dmrunner_macho": {
                    "path": str(bin_path),
                    "exists": bin_path.exists(),
                    "size_bytes": bin_path.stat().st_size if bin_path.exists() else 0,
                },
                "nintendo_ext_font": {
                    "path": str(font_path),
                    "exists": font_path.exists(),
                    "size_bytes": font_path.stat().st_size if font_path.exists() else 0,
                },
                "launcher_json": {
                    "path": str(self.launcher_json),
                    "exists": self.launcher_json.exists(),
                },
            },
        }

    def rebuild_ipa(self) -> Dict[str, Any]:
        """Recompila y empaqueta MarioKart8Deluxe.ipa."""
        return self._run_cmd(
            ["python3", str(self.repo_dir / "scripts" / "build_mk8d_linux_ipa.py")],
            timeout=60,
        )

    def run(self, action: str = "status", **kwargs: Any) -> Dict[str, Any]:
        """Punto de entrada universal para FTL Omni-Registry y TARDIS Bridge."""
        act = action.lower().strip()
        if act in ("status", "info"):
            return self.get_status()
        elif act in ("profile", "mk8d"):
            return self.get_mk8d_profile()
        elif act in ("catalog", "games", "list"):
            return self.get_games_catalog()
        elif act in ("build", "rebuild"):
            return self.rebuild_ipa()
        return {"status": "error", "error": f"Acción no reconocida: {action}"}
