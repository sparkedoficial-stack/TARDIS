"""
modulos_ftl/ftl_git_sync.py - Módulo FTL de Sincronización Soberana con GitHub
=============================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU · FTL AUTOMATION SUITE
Arquitecto: El Arquitecto (₪)

Directiva Soberana:
"y utilizando ftl sube mis avances de software a github"

Este módulo integra en el Master Hub FTL la capacidad de:
1. Ejecutar el constructor y sanitizador de portafolio TARDIS (build_portfolio.py).
2. Capturar y organizar todos los avances de software (GODWORKS SYSTEM, FTL, Easy Touch, Kernel Bridge).
3. Sanitizar credenciales, llaves de API y tokens de forma estricta.
4. Generar commits soberanos con telemetría de versión y fecha.
5. Realizar push seguro al repositorio remoto en GitHub (sparkedoficial-stack/TARDIS.git).
"""

from __future__ import annotations

import os
import sys
import json
import logging
import subprocess
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FTL.GitSync")

PORTFOLIO_DIR = Path("/home/timemachine/TARDIS_Portfolio")
BUILD_SCRIPT = Path("/home/timemachine/build_portfolio.py")


class FtlGitSync:
    """
    Módulo oficial FTL para sincronización continua y push de avances a GitHub.
    Integrado en el Master Hub FTL y utilizable por TARDIS, Easy Touch y CLI.
    """

    def __init__(self):
        self.name = "git_sync"
        self.version = "26.4.0"
        self.repo_dir = PORTFOLIO_DIR
        self.build_script = BUILD_SCRIPT

    def run(self, action: str = "sync", **kwargs) -> Dict[str, Any]:
        """
        Punto de entrada principal para Master Hub FTL.
        Acciones soportadas:
          - 'sync' o 'push': Construye el portafolio, sanitiza y hace push a GitHub.
          - 'status': Verifica el estado de trabajo de git en el portafolio.
          - 'log': Muestra los últimos commits en el repositorio remoto/local.
          - 'build_only': Ejecuta únicamente la sanitización y copia sin hacer commit/push.
        """
        action = action.lower().strip()
        try:
            if action in ("sync", "push"):
                commit_msg = kwargs.get("message")
                return self.sync_and_push(custom_message=commit_msg)
            elif action == "status":
                return self.get_repo_status()
            elif action == "log":
                n = int(kwargs.get("n", 5))
                return self.get_recent_commits(n=n)
            elif action == "build_only":
                return self.run_portfolio_builder()
            else:
                return {
                    "status": "error",
                    "error": f"Acción '{action}' no reconocida.",
                    "available_actions": ["sync", "push", "status", "log", "build_only"]
                }
        except Exception as e:
            logger.error(f"[GIT-SYNC] Error ejecutando acción '{action}': {e}")
            return {"status": "error", "error": str(e)}

    # Alias para compatibilidad con Master Hub
    execute = run

    def run_portfolio_builder(self) -> Dict[str, Any]:
        """Ejecuta el script build_portfolio.py para sanitizar y catalogar avances."""
        if not self.build_script.exists():
            return {"status": "error", "error": f"No se encontró {self.build_script}"}

        logger.info("[GIT-SYNC] Ejecutando constructor y sanitizador de portafolio TARDIS...")
        cmd = [sys.executable, str(self.build_script)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)

        if res.returncode == 0:
            logger.info("[GIT-SYNC] Portafolio construido y sanitizado exitosamente.")
            return {"status": "ok", "output": res.stdout.strip()}
        else:
            logger.error(f"[GIT-SYNC] Fallo al construir portafolio: {res.stderr}")
            return {"status": "error", "rc": res.returncode, "error": res.stderr.strip()}

    def get_repo_status(self) -> Dict[str, Any]:
        """Retorna el estado de git en TARDIS_Portfolio."""
        if not self.repo_dir.exists():
            return {"status": "error", "error": f"Directorio {self.repo_dir} no existe."}

        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(self.repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15
        )
        changes = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        return {
            "status": "ok",
            "clean": len(changes) == 0,
            "pending_changes_count": len(changes),
            "changes": changes[:25]
        }

    def get_recent_commits(self, n: int = 5) -> Dict[str, Any]:
        """Obtiene el historial reciente de commits."""
        res = subprocess.run(
            ["git", "log", f"-n{n}", "--pretty=format:%h|%s|%cd", "--date=iso"],
            cwd=str(self.repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15
        )
        commits = []
        for line in res.stdout.splitlines():
            if "|" in line:
                chash, subj, dt = line.split("|", 2)
                commits.append({"hash": chash, "subject": subj, "date": dt})
        return {"status": "ok", "commits": commits}

    def sync_and_push(self, custom_message: Optional[str] = None) -> Dict[str, Any]:
        """
        Orquesta el ciclo completo de sincronización:
        1. Compilación y sanitización de código
        2. Staging de git (git add -A)
        3. Detección de cambios
        4. Commit soberano con timestamp
        5. Push a GitHub origin main
        """
        # 1. Construir portafolio
        build_res = self.run_portfolio_builder()
        if build_res.get("status") != "ok":
            return build_res

        # 2. Agregar todos los cambios
        subprocess.run(["git", "add", "-A"], cwd=str(self.repo_dir), check=True, timeout=30)

        # 3. Comprobar si hay cambios
        check = subprocess.run(
            ["git", "diff-index", "--quiet", "HEAD", "--"],
            cwd=str(self.repo_dir)
        )

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if check.returncode != 0:
            # Hay cambios pendientes para confirmar
            if not custom_message:
                custom_message = (
                    f"Sovereign FTL Sync :: TARDIS & Easy Touch Kernel Integration ({now_str})\n\n"
                    f"- Acceso universal de herramientas a nivel Kernel (Ring 0 / Root Scope)\n"
                    f"- Integración de FTL Kernel Bridge (/proc, /sys, PSI, dmesg, uinput, uhid)\n"
                    f"- Módulo FTL Git Sync para publicación soberana continua\n"
                    f"- Actualización de subsistemas Easy Touch con auto-cicatrización de hardware"
                )

            logger.info("[GIT-SYNC] Creando commit soberano...")
            commit_res = subprocess.run(
                ["git", "commit", "-m", custom_message],
                cwd=str(self.repo_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            if commit_res.returncode != 0:
                logger.error(f"[GIT-SYNC] Error en git commit: {commit_res.stderr}")
                return {"status": "error", "error": commit_res.stderr.strip()}

            # Obtener hash del commit
            rev_res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(self.repo_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            commit_hash = rev_res.stdout.strip()

            # 4. Push a origin main
            logger.info("[GIT-SYNC] Subiendo avances a GitHub (git push origin main)...")
            push_res = subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=str(self.repo_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120
            )
            if push_res.returncode == 0:
                logger.info(f"[GIT-SYNC] Push completado exitosamente. Commit: {commit_hash}")
                return {
                    "status": "ok",
                    "action": "pushed",
                    "commit_hash": commit_hash,
                    "timestamp": now_str,
                    "push_output": push_res.stdout.strip() or push_res.stderr.strip(),
                    "message": "Avances de software subidos a GitHub exitosamente a través de FTL."
                }
            else:
                logger.error(f"[GIT-SYNC] Fallo al hacer push a GitHub: {push_res.stderr}")
                return {
                    "status": "error",
                    "error": push_res.stderr.strip(),
                    "commit_hash": commit_hash
                }
        else:
            logger.info("[GIT-SYNC] Árbol de trabajo limpio. Todos los avances ya están sincronizados.")
            rev_res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(self.repo_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            return {
                "status": "ok",
                "action": "clean",
                "commit_hash": rev_res.stdout.strip(),
                "timestamp": now_str,
                "message": "No se detectaron cambios sin confirmar. El portafolio está al día en GitHub."
            }


# Instancia singleton
_sync_instance: Optional[FtlGitSync] = None

def get_git_sync() -> FtlGitSync:
    global _sync_instance
    if _sync_instance is None:
        _sync_instance = FtlGitSync()
    return _sync_instance


if __name__ == "__main__":
    sync = FtlGitSync()
    print("=== FTL GIT SYNC :: ESTADO DEL REPOSITORIO ===")
    st = sync.get_repo_status()
    print(json.dumps(st, indent=2))
