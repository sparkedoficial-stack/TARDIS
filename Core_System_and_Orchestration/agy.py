#!/usr/bin/env python3
"""
bin/agy.py - Módulo Python Soberano de Antigravity (AGY) para iPad Pro M2 & TARDIS
=============================================================================
Permite importar y ejecutar AGY en scripts de Python o directamente desde CLI.
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional

class AntigravityClient:
    def __init__(self, model: str = "claude-opus-5-5-high", effort: str = "high"):
        self.model = model
        self.effort = effort
        self.agy_bin = Path("/home/timemachine/.local/bin/agy")
        if not self.agy_bin.exists():
            self.agy_bin = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM/bin/agy")

    def run_prompt(self, prompt: str, timeout: int = 180) -> Dict[str, Any]:
        """Ejecuta un prompt no interactivo en AGY Ultra Mode."""
        env = os.environ.copy()
        env["AGY_MODE"] = "ultra"
        env["AGY_MODEL"] = self.model
        env["AGY_VERBOSITY"] = "high"
        env["AGY_KERNEL_LEVEL"] = "1"
        env["KERNEL_OPERATIONS"] = "1"
        env["FTL_AUTONOMOUS"] = "1"

        cmd = [
            str(self.agy_bin),
            "--mode", "auto",
            "--effort", self.effort,
            "--dangerously-skip-permissions",
            "-p", prompt
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd="/home/timemachine/Escritorio/GODWORKS SYSTEM"
            )
            return {
                "ok": res.returncode == 0,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.returncode
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"AGY excedió el timeout de {timeout}s"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def models(self) -> str:
        cmd = [str(self.agy_bin), "models"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.stdout or res.stderr

    def agents(self) -> str:
        cmd = [str(self.agy_bin), "agents"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.stdout or res.stderr

if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        client = AntigravityClient()
        if query == "models":
            print(client.models())
        elif query in ("agent", "agents"):
            print(client.agents())
        else:
            result = client.run_prompt(query)
            if result.get("ok"):
                print(result["stdout"])
            else:
                print(f"[AGY ERROR] {result.get('error') or result.get('stderr')}", file=sys.stderr)
    else:
        print("Uso: python3 agy.py <prompt | models | agents>")
