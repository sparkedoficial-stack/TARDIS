"""
tardis_ipad_sync_daemon.py - Demonio de Sincronización Bidireccional Soberana
=============================================================================
GODWORKS SYSTEM v26.4 · TARDIS Pro M2 · FTL KERNEL BRIDGE
Sincronización en Tiempo Real entre iPad Pro M2 (AFC Storage), Host y GitHub.

Directiva Soberana:
"El sistema puede pesar localmente 100gb así que puedes reconstruir todo el software
incluyendo flt en el para poder programar directamente en el sistema todo cambio
debe ser reflejado en el sistema principal así como en el nodo ipad."
"""

import os
import sys
import time
import json
import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

# Añadir modulos_ftl y core al path
sys.path.insert(0, "/home/timemachine")
sys.path.insert(0, "/home/timemachine/Escritorio/GODWORKS SYSTEM")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [TARDIS-IPAD-SYNC] %(message)s"
)
logger = logging.getLogger("TARDIS.IpadSync")

LOCAL_WORKSPACE = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
FTL_WORKSPACE = Path("/home/timemachine/modulos_ftl")
IPAD_AFC_ROOT = "/TARDIS_WORKSPACE"

SYNC_STATE_FILE = Path("/home/timemachine/.tardis_ipad_sync_state.json")

def calculate_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""

class TardisIpadSyncDaemon:
    def __init__(self):
        self.state: Dict[str, str] = self._load_state()
        self.lock = asyncio.Lock()

    def _load_state(self) -> Dict[str, str]:
        if SYNC_STATE_FILE.exists():
            try:
                return json.loads(SYNC_STATE_FILE.read_text())
            except Exception:
                pass
        return {}

    def _save_state(self):
        try:
            SYNC_STATE_FILE.write_text(json.dumps(self.state, indent=2))
        except Exception as e:
            logger.warning(f"Error guardando estado de sync: {e}")

    async def get_afc_client(self):
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService
        ld = await create_using_usbmux()
        return AfcService(ld)

    async def push_file_to_ipad(self, local_path: Path, remote_rel_path: str) -> bool:
        """Sube un archivo local al almacenamiento interno del iPad."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.afc import AfcService
            
            ld = await create_using_usbmux()
            async with AfcService(ld) as afc:
                remote_full_path = f"{IPAD_AFC_ROOT}/{remote_rel_path.lstrip('/')}"
                parent_dir = str(Path(remote_full_path).parent)
                
                # Crear directorios si no existen
                parts = parent_dir.strip("/").split("/")
                curr = ""
                for p in parts:
                    curr += f"/{p}"
                    try:
                        await afc.makedirs(curr)
                    except Exception:
                        pass

                data = local_path.read_bytes()
                await afc.set_file_contents(remote_full_path, data)
                self.state[remote_rel_path] = calculate_sha256(local_path)
                self._save_state()
                logger.info(f"Sincronizado Host -> iPad: {remote_rel_path} ({len(data)} bytes)")
                return True
        except Exception as e:
            logger.error(f"Fallo enviando {remote_rel_path} a iPad: {e}")
            return False

    async def pull_file_from_ipad(self, remote_rel_path: str, local_path: Path) -> bool:
        """Descarga un archivo desde el iPad hacia el Host."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.afc import AfcService
            
            ld = await create_using_usbmux()
            async with AfcService(ld) as afc:
                remote_full_path = f"{IPAD_AFC_ROOT}/{remote_rel_path.lstrip('/')}"
                data = await afc.get_file_contents(remote_full_path)
                
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(data)
                self.state[remote_rel_path] = calculate_sha256(local_path)
                self._save_state()
                logger.info(f"Sincronizado iPad -> Host: {remote_rel_path} ({len(data)} bytes)")
                return True
        except Exception as e:
            logger.error(f"Fallo descargando {remote_rel_path} desde iPad: {e}")
            return False

    async def sync_all_ftl_to_ipad(self) -> int:
        """Sincroniza todos los módulos de modulos_ftl hacia el iPad."""
        count = 0
        if not FTL_WORKSPACE.exists():
            return 0

        for f in FTL_WORKSPACE.glob("*.py"):
            rel = f"modulos_ftl/{f.name}"
            chash = calculate_sha256(f)
            if self.state.get(rel) != chash:
                if await self.push_file_to_ipad(f, rel):
                    count += 1
        return count

    async def trigger_github_sync(self, commit_msg: str) -> Dict[str, Any]:
        """Ejecuta FTL Git Sync para reflejar cambios en GitHub."""
        try:
            from modulos_ftl.ftl_git_sync import FtlGitSync
            syncer = FtlGitSync()
            res = syncer.run("sync", message=commit_msg)
            logger.info(f"GitHub Sync completado: {res.get('ok')}")
            return res
        except Exception as e:
            logger.warning(f"Error en Git Sync: {e}")
            return {"ok": False, "error": str(e)}

    async def daemon_loop(self):
        """Ciclo continuo de supervisión y sincronización."""
        logger.info("Iniciando bucle de sincronización bidireccional continua...")
        while True:
            try:
                # Sincronizar modulos FTL pendientes
                await self.sync_all_ftl_to_ipad()
            except Exception as e:
                logger.debug(f"Pausa en ciclo de sync: {e}")
            await asyncio.sleep(15)

if __name__ == "__main__":
    daemon = TardisIpadSyncDaemon()
    try:
        asyncio.run(daemon.daemon_loop())
    except KeyboardInterrupt:
        logger.info("Demonio de sincronización detenido.")
