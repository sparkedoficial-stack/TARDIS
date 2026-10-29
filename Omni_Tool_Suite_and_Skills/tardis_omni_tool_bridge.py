"""
core/tardis_omni_tool_bridge.py - Puente Soberano de Control y Conocimiento Omni-Herramientas
=============================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Directiva Soberana:
"Todas las herramientas con las que tiene acceso agy, tardis, asi como ftl deben tener
control y saber de su conocimiento para poder emplearlas en sus sistemas de forma individual.
Hablo del phone harness, xcode-for linux, rea, asi como todo lo que esta en el chat y repositorios agy locales."

Este puente unifica el control individual, la documentación y el despacho de ejecución
para que TARDIS (GIA, KAIJU, Supervisor, Easy Touch) y FTL puedan activar cualquier
herramienta del ecosistema bajo demanda:
  - Phone Harness (Control móvil de Android ADB, Apple iOS Mirroring y Cloud Phones)
  - Xcode para Linux (Toolchain iOS, Mach-O, zsign, pymobiledevice3, AFC, CoreDevice)
  - REA - Reverse Engineer Anything (Descompilación nativa, APK, IPA, JS, firmware)
  - Kernel Bridge (Ring 0, sysctl, dmesg, PSI, /dev/uinput, /dev/uhid)
  - FTL Git Sync (Compilación, sanitización y push continuo a GitHub)
"""

from __future__ import annotations

import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("TARDIS.OmniToolBridge")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOME_DIR = Path.home()


class TardisOmniToolBridge:
    """
    Puente de interoperabilidad omni-herramientas para TARDIS.
    Permite consultar documentación, verificar estado y ejecutar individualmente
    Phone Harness, Xcode Linux, REA, Kernel Bridge y Git Sync.
    """

    _instance: Optional["TardisOmniToolBridge"] = None

    def __init__(self):
        self._ensure_paths()
        self.tools = {
            "phone_harness": {
                "name": "Phone Harness",
                "binary": str(HOME_DIR / ".local" / "bin" / "phone-harness"),
                "module": "modulos_ftl.ftl_phone_harness",
                "domain": "mobile_control",
                "description": "Control integral de teléfonos: Android vía ADB, iPhone vía Mirroring y Cloud Phones. Lectura OCR/Accessibility tree, pulsaciones, gestos y tecleo.",
                "actions": ["ensure_device", "screen", "screenshot", "tap", "tap_text", "type_text", "open_app", "swipe", "scroll", "home", "back", "doctor"]
            },
            "xcode_linux": {
                "name": "Xcode para Linux",
                "binary": "/usr/local/bin/xcode-linux",
                "module": "modulos_ftl.ftl_xcode_linux",
                "domain": "ios_toolchain",
                "description": "Toolchain completo para iOS/iPadOS en Linux: compilador Clang arm64, LLD, inspección Mach-O, firmado zsign, puente REA, transferencia AFC y despliegue por usbmuxd.",
                "actions": ["info", "devices", "apps", "inspect", "install", "push", "console", "build"]
            },
            "rea": {
                "name": "REA (Reverse Engineer Anything)",
                "binary": "/usr/local/bin/rea",
                "module": "modulos_ftl.ftl_rea",
                "domain": "reverse_engineering",
                "description": "Ingeniería inversa profunda de binarios nativos (Mach-O, ELF, PE), paquetes APK/IPA, aplicaciones JavaScript/Electron y firmwares.",
                "actions": ["providers", "inspect_apk", "inspect_ipa", "inspect_js", "decompile", "disassemble", "search"]
            },
            "kernel_bridge": {
                "name": "FTL Kernel Bridge (Ring 0)",
                "module": "modulos_ftl.ftl_kernel_bridge",
                "domain": "kernel_ring0",
                "description": "Acceso irrestricto al núcleo de Linux: observabilidad PSI, dmesg libre, sintonización sysctl, purga de memoria en caliente y control /dev/uinput.",
                "actions": ["status", "psi", "dmesg", "sysctl_get", "sysctl_set", "tune_all", "drop_caches", "modules", "uinput_status", "root_exec"]
            },
            "git_sync": {
                "name": "FTL Git Sync",
                "module": "modulos_ftl.ftl_git_sync",
                "domain": "git_automation",
                "description": "Compilación del portafolio soberano TARDIS, sanitización de secretos y sincronización con GitHub (sparkedoficial-stack/TARDIS.git).",
                "actions": ["sync", "push", "status", "log", "build_only"]
            },
            "tardis4ever": {
                "name": "Tardis4Ever Sovereign Agent",
                "binary": "/usr/local/bin/tardis4ever",
                "module": "modulos_ftl.ftl_tardis4ever",
                "domain": "ci_cd_publication",
                "description": "Agente soberano de sincronización continua: rutina de 24h automática y publicación inmediata en GitHub ante hitos importantes o llamativos con blindaje total de privacidad.",
                "actions": ["status", "check", "sync", "daemon", "daemon_status"]
            },
            "tardis_navigator": {
                "name": "TARDIS Quantum Navigator & Automation Studio",
                "binary": str(HOME_DIR / ".local" / "bin" / "tardis-browser"),
                "module": "core.tardis_navigator_engine",
                "domain": "browser_ai_automation",
                "description": "Navegador gráfico multi-pestaña (GTK3+WebKit2) con TARDIS como asistente de búsqueda IA multi-motor, inspector DOM en vivo, grabadora de macros y estudio de automatización de procesos.",
                "actions": ["gui", "search", "analyze_dom", "run_workflow", "generate_workflow", "record_macro", "schedule"]
            },
            "nxnative": {
                "name": "nxnative · Mario Kart 8 Deluxe (0100152000022000)",
                "module": "modulos_ftl.ftl_nxnative",
                "domain": "switch_native_ios",
                "description": "Motor nativo nxnative para Apple iPad Pro M2 con perfil completo de Mario Kart 8 Deluxe (0100152000022000, 29,650 shaders NVN->Metal 4, DmGamepad y Launcher.swift).",
                "actions": ["status", "profile", "catalog", "build"]
            }
        }
        self._register_in_dynamic_registry()

    @classmethod
    def get_instance(cls) -> "TardisOmniToolBridge":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_paths(self):
        ftl_path = "/home/timemachine"
        if ftl_path not in sys.path:
            sys.path.insert(0, ftl_path)

    def _register_in_dynamic_registry(self):
        """Registra el puente en data/dynamic_tools_registry.json de TARDIS."""
        try:
            reg_path = PROJECT_ROOT / "data" / "dynamic_tools_registry.json"
            registry = {}
            if reg_path.exists():
                try:
                    registry = json.loads(reg_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            for t_id, t_info in self.tools.items():
                registry[f"omni_tool_{t_id}"] = {
                    "name": f"omni_tool_{t_id}",
                    "tool_id": t_id,
                    "title": t_info["name"],
                    "domain": t_info["domain"],
                    "description": t_info["description"],
                    "actions": t_info["actions"],
                    "status": "ACTIVE_SOVEREIGN"
                }

            reg_path.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("[OMNI-BRIDGE] Herramientas registradas en dynamic_tools_registry.json de TARDIS.")
        except Exception as e:
            logger.debug(f"[OMNI-BRIDGE] Nota de registro dinámico: {e}")

    def list_tools(self) -> Dict[str, Any]:
        """Retorna el catálogo completo con el estado de cada herramienta."""
        status_report = {}
        for k, info in self.tools.items():
            bin_path = info.get("binary")
            available = False
            if bin_path and os.path.exists(bin_path) and os.access(bin_path, os.X_OK):
                available = True
            elif "module" in info:
                mod_file = Path("/home/timemachine") / f"{info['module'].replace('.', '/')}.py"
                available = mod_file.exists()

            status_report[k] = {
                "name": info["name"],
                "domain": info["domain"],
                "description": info["description"],
                "available": available,
                "supported_actions": info["actions"]
            }
        return {"status": "ok", "total": len(status_report), "tools": status_report}

    def execute_tool(self, tool_id: str, action: str = "status", **kwargs) -> Dict[str, Any]:
        """Ejecuta una herramienta individual por su ID."""
        tool_id = tool_id.lower().replace("-", "_")
        if tool_id not in self.tools:
            return {"status": "error", "error": f"Herramienta '{tool_id}' no reconocida. Disponibles: {list(self.tools.keys())}"}

        tool = self.tools[tool_id]

        # 1. Intentar despacho mediante módulo FTL
        if "module" in tool:
            try:
                import importlib
                mod = importlib.import_module(tool["module"])
                for attr in dir(mod):
                    cls_obj = getattr(mod, attr)
                    if isinstance(cls_obj, type) and hasattr(cls_obj, "run") and attr.lower().startswith("ftl"):
                        inst = cls_obj()
                        return inst.run(action=action, **kwargs)
            except Exception as e:
                logger.warning(f"[OMNI-BRIDGE] Fallo en despacho por módulo ({e}), intentando binario directo...")

        # 2. Despacho directo por CLI
        if "binary" in tool and os.path.exists(tool["binary"]):
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

        return {"status": "error", "error": f"No se pudo ejecutar la herramienta '{tool_id}'."}


# Instancia singleton accesible
get_omni_bridge = TardisOmniToolBridge.get_instance


if __name__ == "__main__":
    bridge = TardisOmniToolBridge.get_instance()
    print("=== TARDIS OMNI-TOOL BRIDGE :: ESTADO GENERAL ===")
    print(json.dumps(bridge.list_tools(), indent=2, ensure_ascii=False))
