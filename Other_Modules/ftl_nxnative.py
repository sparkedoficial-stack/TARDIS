"""
modulos_ftl/ftl_nxnative.py - Controlador Soberano de nxnative · Mario Kart 8 Deluxe (0100152000022000 v4.0.1)
==============================================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU · FTL AUTOMATION SUITE
Arquitecto: El Arquitecto (₪)

Módulo soberano de control, compilación, inspección de los 29,785 shaders NVN -> Metal 4
(12,579 vertex, 17,177 pixel, 28 compute, 1 geometry; 19,012 variation pairs; 23 librerías _b.metallib
en msl/b-8e52e2292032), reescritura de binarios AArch64 NSO (main, subsdk0, sdk) y despliegue de
nxnative (Mario Kart 8 Deluxe 0100152000022000 v4.0.1 / v1507328) para Apple iPad Pro M2 (iPad14,6).
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
    Controlador soberano de nxnative + Mario Kart 8 Deluxe (0100152000022000 v4.0.1) para iPad Pro M2.
    """

    def __init__(self) -> None:
        self.name = "nxnative"
        self.version = "4.0.1-v1507328"
        self.game_id = "0100152000022000"
        self.game_name = "Mario Kart 8 Deluxe"
        self.bundle_id = f"org.nxnative.{self.game_id}"
        self.msl_chain = "8e52e2292032"
        self.chain_inputs = "beadcc8fc60e"
        self.repo_dir = Path("/home/timemachine/nxnative")
        self.game_dir = self.repo_dir / "dm" / "games" / self.game_id
        self.build_dir = self.repo_dir / "build"
        self.ipa_path = self.build_dir / "MarioKart8Deluxe.ipa"
        self.app_dir = self.build_dir / "DmIOS.app"
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
        """Obtiene las métricas exactas de dm/games/0100152000022000/README.md#files-and-shaders."""
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
            "version": "4.0.1",
            "package": "v1507328",
            "bundle_id": self.bundle_id,
            "engine": "Nintendo sead / agl / gsys + NintendoWare (G3d, Ui2d, Vfx, Atk) + Pia on SDK 4.4.0 NVN -> Metal 4",
            "builds_tested": [
                {
                    "version": "v1441792",
                    "display": "4.0.0",
                    "main": "2c336a9bcf79c3040ce506cdd391b578",
                    "subsdk0": "d9de423efc1512328c3c05378c7cb031",
                    "sdk": "ba520906609c503227871a314a94fb5f",
                },
                {
                    "version": "v1507328",
                    "display": "4.0.1",
                    "main": "158c0c7399aabd7bf83795c2ef3484c7",
                    "subsdk0": "d9de423efc1512328c3c05378c7cb031",
                    "sdk": "ba520906609c503227871a314a94fb5f",
                },
            ],
            "memory_layout": {
                "mem_reserve": "0x100000000 (4.0 GB)",
                "mem_alias": "0x10000000 (256 MB)",
                "mem_stack": "0x10000000 (256 MB)",
                "app_pool": "0xCD500000 (3,285 MB / 3.03 GB heap)",
                "sys_resource": "0x0 (IsVirtualAddressMemoryEnabled = false)",
            },
            "files_and_shaders": {
                "total_shaders": 29785,
                "vertex_shaders": 12579,
                "pixel_shaders": 17177,
                "compute_shaders": 28,
                "geometry_shaders": 1,
                "variation_pairs": 19012,
                "pso_manifest_entries": 1516,
                "pso_pairs_entries": 2665,
                "msl_chain": f"b-{self.msl_chain}",
                "chain_inputs": self.chain_inputs,
                "metallib_packages": 23,
                "romfs_marker": "UI/cmn/movie/StaffCredits.mp4",
                "aoc_title_id": "0100152000023001 (contents.dat + version.txt)",
                "mii_standin": "0100000000000802 (MiiResource: 6 default Miis + empty head mesh)",
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
        """Devuelve el estado integral de nxnative + Mario Kart 8 Deluxe v4.0.1 en el host e iPad Pro M2."""
        bin_path = self.app_dir / "DmIOS"
        font_path = self.app_dir / "dm" / "font" / "nintendo_ext.ttf"
        msl_dir = self.build_dir / "msl_ios" / f"b-{self.msl_chain}"
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
                "entries": 96,
                "bundle_id": self.bundle_id,
                "ipad_afc_paths": [
                    "/Downloads/MarioKart8Deluxe.ipa",
                    "/TARDIS_WORKSPACE/nxnative/MarioKart8Deluxe.ipa",
                ],
                "edge_download_url": "/download/MarioKart8Deluxe.ipa",
                "webclip_url": "/mk8d.mobileconfig",
            },
            "artifacts": {
                "dmios_macho": {
                    "path": str(bin_path),
                    "exists": bin_path.exists(),
                    "size_bytes": bin_path.stat().st_size if bin_path.exists() else 0,
                },
                "msl_libraries": {
                    "path": str(msl_dir),
                    "exists": msl_dir.exists(),
                    "metallib_count": len(list(msl_dir.glob("*_b.metallib"))) if msl_dir.exists() else 0,
                },
                "nintendo_ext_font": {
                    "path": str(font_path),
                    "exists": font_path.exists(),
                    "size_bytes": font_path.stat().st_size if font_path.exists() else 0,
                },
            },
        }

    def rebuild_ipa(self) -> Dict[str, Any]:
        """Recompila y empaqueta MarioKart8Deluxe.ipa v4.0.1 con pack_ipa.py."""
        return self._run_cmd(
            ["python3", str(self.repo_dir / "scripts" / "build_mk8d_linux_ipa.py")],
            timeout=60,
        )

    def run(self, action: str = "status", **kwargs: Any) -> Dict[str, Any]:
        act = action.lower().strip()
        if act in ("status", "info"):
            return self.get_status()
        elif act in ("profile", "mk8d", "shaders"):
            return self.get_mk8d_profile()
        elif act in ("catalog", "games", "list"):
            return self.get_games_catalog()
        elif act in ("build", "rebuild"):
            return self.rebuild_ipa()
        return {"status": "error", "error": f"Acción no reconocida: {action}"}
