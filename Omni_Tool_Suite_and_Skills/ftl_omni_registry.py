"""
modulos_ftl/ftl_omni_registry.py - Registro Soberano y Centro de Control de Herramientas Omni-Sistema
====================================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU · FTL AUTOMATION SUITE
Arquitecto: El Arquitecto (₪)

Directiva Soberana:
"Todas las herramientas con las que tiene acceso agy, tardis, asi como ftl deben tener
control y saber de su conocimiento para poder emplearlas en sus sistemas de forma individual.
Hablo del phone harness, xcode-for linux, rea, asi como todo lo que esta en el chat y repositorios agy locales."

Este módulo centraliza el conocimiento exhaustivo, estado operativo y despacho ejecutable individual
de todas las herramientas soberanas:
1. Phone Harness (Control móvil de Android ADB, Apple iOS Mirroring y Cloud Phones)
2. Xcode para Linux (Toolchain iOS, Mach-O, zsign, pymobiledevice3, AFC, CoreDevice)
3. REA - Reverse Engineer Anything (Descompilación nativa, APK, IPA, JS, firmware)
4. Kernel Bridge (Ring 0, sysctl, dmesg, PSI, /dev/uinput, /dev/uhid)
5. Git Sync Soberano (Compilación de portafolio, sanitización y push a GitHub)
6. Easy Touch Engine (Auto-cicatrización preventiva y vigilancia en segundo plano)
7. Ecosistema de Skills y MCP de AGY (Antigravity CLI / Gemini)
"""

from __future__ import annotations

import os
import sys
import json
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FTL.OmniRegistry")


class FtlOmniRegistry:
    """
    Directorio universal de conocimiento, control individual e interoperabilidad
    entre AGY, TARDIS y FTL.
    """

    def __init__(self):
        self.name = "omni_registry"
        self.version = "26.4.0"
        self.catalog = self._build_tools_catalog()

    def _build_tools_catalog(self) -> Dict[str, Dict[str, Any]]:
        """Construye el inventario exhaustivo de herramientas con su conocimiento y rutas operativas."""
        return {
            "phone_harness": {
                "name": "Phone Harness",
                "binary": "/home/timemachine/.local/bin/phone-harness",
                "module": "modulos_ftl.ftl_phone_harness",
                "skill_path": "/home/timemachine/.agents/skills/phone-harness/SKILL.md",
                "category": "Mobile Automation & Hardware Perception",
                "description": "Control bidireccional de teléfonos: Android vía ADB, personal iPhone vía Mirroring/USB, y Cloud Phones. Lectura por OCR/Accessibility tree, pulsaciones, gestos, swipes y tecleo.",
                "capabilities": ["ensure_device", "screen", "screenshot", "tap", "tap_text", "type_text", "open_app", "swipe", "scroll", "home", "back", "doctor"],
                "active": shutil.which("phone-harness") is not None or os.path.exists("/home/timemachine/.local/bin/phone-harness")
            },
            "xcode_linux": {
                "name": "Xcode for Linux",
                "binary": "/usr/local/bin/xcode-linux",
                "module": "modulos_ftl.ftl_xcode_linux",
                "skill_path": "/home/timemachine/.agents/skills/xcode-for-linux/SKILL.md",
                "toolchain_root": "/opt/xcode-linux",
                "category": "Apple iOS Development & Deployment",
                "description": "Toolchain completo para iOS/iPadOS en Linux: compilador Clang arm64, LLD, inspección Mach-O, firmado zsign, puente REA, transferencia AFC y despliegue por usbmuxd.",
                "capabilities": ["info", "devices", "apps", "inspect", "install", "push", "console", "build"],
                "active": shutil.which("xcode-linux") is not None or os.path.exists("/usr/local/bin/xcode-linux")
            },
            "rea": {
                "name": "Reverse Engineer Anything (REA)",
                "binary": "/usr/local/bin/rea",
                "module": "modulos_ftl.ftl_rea",
                "skill_path": "/home/timemachine/.agents/skills/rea/SKILL.md",
                "category": "Binary Analysis & Decompilation",
                "description": "Suite de ingeniería inversa para binarios nativos (Mach-O, ELF, PE), aplicaciones móviles (APK, IPA), arquitecturas JavaScript/Electron y firmwares embebidos.",
                "capabilities": ["providers", "inspect_apk", "inspect_ipa", "inspect_js", "decompile", "disassemble", "search", "inventory"],
                "active": shutil.which("rea") is not None or os.path.exists("/usr/local/bin/rea")
            },
            "kernel_bridge": {
                "name": "FTL Kernel Bridge (Ring 0)",
                "module": "modulos_ftl.ftl_kernel_bridge",
                "sysctl_conf": "/etc/sysctl.d/99-tardis-kernel.conf",
                "udev_rules": "/etc/udev/rules.d/99-tardis-kernel-access.rules",
                "category": "Kernel Ring 0 & Low-Level Hardware",
                "description": "Control soberano del núcleo del sistema: observabilidad PSI (/proc/pressure), lectura de dmesg sin restricciones, sintonización de sysctl en caliente, purga de memoria RAM y acceso 0666 a /dev/uinput y /dev/uhid.",
                "capabilities": ["status", "psi", "dmesg", "sysctl_get", "sysctl_set", "tune_all", "drop_caches", "modules", "uinput_status", "root_exec"],
                "active": True
            },
            "git_sync": {
                "name": "FTL Git Sync",
                "module": "modulos_ftl.ftl_git_sync",
                "portfolio_dir": "/home/timemachine/TARDIS_Portfolio",
                "category": "Continuous Integration & Deployment",
                "description": "Compilador del portafolio soberano TARDIS, sanitizador de secretos y llaves de API, generador de commits estructurados y sincronización con GitHub (sparkedoficial-stack/TARDIS.git).",
                "capabilities": ["sync", "push", "status", "log", "build_only"],
                "active": True
            },
            "easy_touch": {
                "name": "Easy Touch Engine",
                "engine_path": "/home/timemachine/Escritorio/GODWORKS SYSTEM/core/easy_touch_engine.py",
                "ledger": "/home/timemachine/vw-control/easy_touch_ledger.jsonl",
                "category": "Autonomous Self-Healing & Preventive Maintenance",
                "description": "Motor de auto-reparación preventiva en segundo plano. Intercepta excepciones, sanea dependencias pip, permisos de archivo, bloqueos git, conflictos de puertos y auto-cicatrización de hardware uinput.",
                "capabilities": ["intercept_chat", "intercept_execution", "auto_heal_memory", "auto_heal_kernel_hardware", "auto_install_package", "auto_fix_permissions"],
                "active": True
            },
            "tardis_hybrid_synergy": {
                "name": "TARDIS Hybrid Synergy Matrix",
                "path": "/home/timemachine/Escritorio/GODWORKS SYSTEM/core/tardis_hybrid_synergy.py",
                "category": "Cognitive Multi-Model & Paradigm Orchestration",
                "description": "Matriz unificada que evalúa la combinación óptima de modelos de lenguaje (KAIJU, Gemini, Claude, DeepSeek, Qwen) y capas de ingeniería (ECCA, SSM, FTS5, Radar, ChronoVision).",
                "capabilities": ["evaluate", "matrix", "get_models", "get_layers"],
                "active": True
            },
            "tardis4ever": {
                "name": "Tardis4Ever Sovereign Agent",
                "binary": "/usr/local/bin/tardis4ever",
                "module": "modulos_ftl.ftl_tardis4ever",
                "service": "tardis4ever.service",
                "skill_path": "/home/timemachine/.agents/skills/tardis4ever/SKILL.md",
                "category": "Continuous Integration, Milestone Watcher & Automated Publication",
                "description": "Agente soberano de sincronización continua: rutina de 24h automática y publicación inmediata en GitHub ante hitos importantes o llamativos con blindaje total de privacidad.",
                "capabilities": ["status", "check", "sync", "daemon", "daemon_status"],
                "active": True
            },
            "linpad": {
                "name": "LinPad 1.6.0-TARDIS-M2 (Linux Desktop on iPad Pro M2)",
                "binary": "/home/timemachine/.local/bin/linpad-ctl",
                "module": "modulos_ftl.ftl_linpad",
                "repo_path": "/home/timemachine/LinPad",
                "ipa_path": "/home/timemachine/LinPad/build/LinPad-1.6.0-TARDIS-M2.ipa",
                "category": "Apple iPadOS Linux Desktop & Wayland Compositor Bridge",
                "description": "Entorno de escritorio Linux completo para iPad Pro M2 (Sway + Waybar + Wofi + Foot + Chromium + LibreOffice + GIMP + TARDIS/FTL/AGY Bridge) sobre motor nativo iSH ARM64 + Wayland Bridge ishwl y aceleración Metal/Venus.",
                "capabilities": ["status", "fetch", "catalog", "themes", "benchmark", "tests"],
                "active": True
            }
        }

    def run(self, action: str = "list", **kwargs) -> Dict[str, Any]:
        """
        Punto de entrada compatible con Master Hub FTL.
        Acciones soportadas:
          - 'list' / 'catalog': Retorna el inventario completo de herramientas con su estado.
          - 'health_check': Realiza un diagnóstico exhaustivo de disponibilidad de todas las herramientas.
          - 'info': Obtiene la ficha técnica y documentación de una herramienta específica ('tool').
          - 'exec': Ejecuta una acción sobre una herramienta específica de forma individual ('tool', 'cmd_action', **kwargs).
        """
        action = action.lower().strip()
        try:
            if action in ("list", "catalog"):
                return {"status": "ok", "total_tools": len(self.catalog), "tools": self.catalog}
            elif action == "health_check":
                return self.run_health_check()
            elif action == "info":
                t_name = kwargs.get("tool") or kwargs.get("name")
                if not t_name:
                    return {"status": "error", "error": "Parámetro 'tool' requerido."}
                return self.get_tool_info(t_name)
            elif action == "exec":
                t_name = kwargs.get("tool") or kwargs.get("name")
                cmd_act = kwargs.get("cmd_action") or kwargs.get("action_name") or "status"
                if not t_name:
                    return {"status": "error", "error": "Parámetro 'tool' requerido."}
                return self.execute_tool(t_name, cmd_act, **kwargs)
            else:
                return {
                    "status": "error",
                    "error": f"Acción '{action}' no reconocida.",
                    "available_actions": ["list", "health_check", "info", "exec"]
                }
        except Exception as e:
            logger.error(f"[OMNI-REGISTRY] Error en acción '{action}': {e}")
            return {"status": "error", "error": str(e)}

    # Alias para compatibilidad con Master Hub
    execute = run

    def run_health_check(self) -> Dict[str, Any]:
        """Ejecuta una auditoría de salud técnica sobre todas las herramientas."""
        results = {}
        for key, tool in self.catalog.items():
            check = {"name": tool["name"], "category": tool["category"], "available": False}
            if "binary" in tool:
                p = tool["binary"]
                check["binary_exists"] = os.path.exists(p)
                check["available"] = os.path.exists(p) and os.access(p, os.X_OK)
            elif "module" in tool:
                try:
                    mod_name = tool["module"].split(".")[-1]
                    fpath = Path("/home/timemachine/modulos_ftl") / f"{mod_name}.py"
                    check["module_exists"] = fpath.exists()
                    check["available"] = fpath.exists()
                except Exception:
                    check["available"] = False
            else:
                check["available"] = True
            results[key] = check

        all_ok = all(r.get("available", False) for r in results.values())
        return {
            "status": "ok" if all_ok else "warning",
            "all_healthy": all_ok,
            "audit": results
        }

    def get_tool_info(self, tool_name: str) -> Dict[str, Any]:
        """Devuelve el conocimiento y documentación completa de una herramienta."""
        key = tool_name.lower().replace("-", "_")
        tool = self.catalog.get(key)
        if not tool:
            return {"status": "error", "error": f"Herramienta '{tool_name}' no encontrada en el catálogo."}

        # Leer SKILL.md si existe
        skill_doc = ""
        if "skill_path" in tool and os.path.exists(tool["skill_path"]):
            try:
                skill_doc = Path(tool["skill_path"]).read_text(encoding="utf-8")[:1500] + "\n... [Documentación truncada]"
            except Exception:
                pass

        return {
            "status": "ok",
            "tool": tool,
            "skill_preview": skill_doc or "Documentación nativa del sistema TARDIS / FTL"
        }

    def execute_tool(self, tool_name: str, action: str = "status", **kwargs) -> Dict[str, Any]:
        """Ejecuta una herramienta individual de forma aislada."""
        key = tool_name.lower().replace("-", "_")
        tool = self.catalog.get(key)
        if not tool:
            return {"status": "error", "error": f"Herramienta '{tool_name}' no encontrada."}

        # Intentar despacho por módulo FTL
        if "module" in tool:
            try:
                mod_name = tool["module"].split(".")[-1]
                sys_path = "/home/timemachine"
                if sys_path not in sys.path:
                    sys.path.insert(0, sys_path)
                import importlib
                mod = importlib.import_module(f"modulos_ftl.{mod_name}")
                # Buscar clase o punto de entrada
                for attr_name in dir(mod):
                    cls = getattr(mod, attr_name)
                    if isinstance(cls, type) and hasattr(cls, "run") and attr_name.lower().startswith("ftl"):
                        inst = cls()
                        return inst.run(action=action, **kwargs)
            except Exception as e:
                logger.warning(f"[OMNI-REGISTRY] Despacho por módulo falló ({e}), intentando CLI...")

        # Despacho por binario CLI
        if "binary" in tool:
            try:
                cmd = [tool["binary"], action]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
                return {
                    "status": "ok" if res.returncode == 0 else "error",
                    "rc": res.returncode,
                    "stdout": res.stdout.strip(),
                    "stderr": res.stderr.strip()
                }
            except Exception as e:
                return {"status": "error", "error": str(e)}

        return {"status": "error", "error": f"No se pudo resolver el método de ejecución para '{tool_name}'."}


# Instancia singleton
_omni_instance: Optional[FtlOmniRegistry] = None

def get_omni_registry() -> FtlOmniRegistry:
    global _omni_instance
    if _omni_instance is None:
        _omni_instance = FtlOmniRegistry()
    return _omni_instance


if __name__ == "__main__":
    registry = FtlOmniRegistry()
    print("=== FTL OMNI-TOOL REGISTRY :: AUDITORÍA GLOBAL ===")
    health = registry.run_health_check()
    print(json.dumps(health, indent=2))
