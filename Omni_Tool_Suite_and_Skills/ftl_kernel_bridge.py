"""
modulos_ftl/ftl_kernel_bridge.py - Puente Soberano de Control de Kernel (Ring 0 / Root Scope)
=============================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU · FTL AUTOMATION SUITE
Arquitecto: El Arquitecto (₪)

Directiva Soberana:
"Permite que todas mis herramientas tengan acceso a todos mis sistemas desde ftl, tardis
hasta easytouch a nivel kernel"

Este módulo otorga soberanía operativa y capacidades de control de Kernel a:
1. FTL Master Hub y CLI (ftl_cli.py)
2. TARDIS Core y TARDIS Singularity Engine
3. Easy Touch Engine (Auto-Corrección Preventiva en Segundo Plano)
4. Agentes Autónomos y Subagentes KAIJU
"""

from __future__ import annotations

import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FTL.KernelBridge")


class FtlKernelBridge:
    """
    Puente de enlace e integración de Kernel (Ring 0 / Root Scope) para FTL, TARDIS y Easy Touch.
    Permite acceso total y telemetría profunda a interfaces /proc, /sys, sysctl, dmesg,
    Pressure Stall Information (PSI), módulos de kernel y dispositivos uinput/uhid/hidraw.
    """

    def __init__(self):
        self.name = "kernel_bridge"
        self.version = "26.4.0"
        self.sysctl_conf_path = Path("/etc/sysctl.d/99-tardis-kernel.conf")
        self.udev_rules_path = Path("/etc/udev/rules.d/99-tardis-kernel-access.rules")

    def run(self, action: str = "status", **kwargs) -> Dict[str, Any]:
        """
        Punto de entrada oficial para el Master Hub FTL.
        Acciones soportadas:
          - 'status': Diagnóstico global del kernel (PSI, sysctl, nodos de hardware, RAM).
          - 'psi': Lectura detallada de Pressure Stall Information (CPU, Memoria, I/O).
          - 'dmesg': Volcado filtrado del ringbuffer del kernel sin requerir root interactivo.
          - 'sysctl_get': Consulta parámetros específicos de sysctl.
          - 'sysctl_set': Modifica en caliente parámetros de sysctl.
          - 'tune_all': Verifica y reaplica la configuración soberana de kernel.
          - 'drop_caches': Sincroniza y purga de forma segura cachés de kernel y páginas inactivas.
          - 'modules': Lista módulos cargados o ejecuta modprobe.
          - 'uinput_status': Verifica el estado y permisos de /dev/uinput y /dev/uhid.
          - 'root_exec': Ejecuta comandos de sistema con privilegios root sin solicitar contraseña.
        """
        action = action.lower().strip()
        try:
            if action in ("status", "telemetry"):
                return self.get_kernel_status()
            elif action == "psi":
                return {"status": "ok", "psi": self.get_psi_telemetry()}
            elif action == "dmesg":
                lines = int(kwargs.get("lines", 50))
                filter_term = kwargs.get("filter")
                return {"status": "ok", "dmesg": self.read_dmesg(lines=lines, filter_term=filter_term)}
            elif action == "sysctl_get":
                param = kwargs.get("param") or kwargs.get("key")
                if not param:
                    return {"status": "error", "error": "Parámetro 'param' requerido."}
                return {"status": "ok", "param": param, "value": self.get_sysctl(param)}
            elif action == "sysctl_set":
                param = kwargs.get("param") or kwargs.get("key")
                val = kwargs.get("value") or kwargs.get("val")
                if not param or val is None:
                    return {"status": "error", "error": "Se requieren 'param' y 'value'."}
                return self.set_sysctl(param, str(val))
            elif action == "tune_all":
                return self.apply_sovereign_kernel_tuning()
            elif action == "drop_caches":
                return self.drop_kernel_caches()
            elif action == "modules":
                subcmd = kwargs.get("subcmd", "list")
                mod_name = kwargs.get("name")
                return self.manage_kernel_modules(subcmd=subcmd, mod_name=mod_name)
            elif action == "uinput_status":
                return {"status": "ok", "nodes": self.check_hardware_nodes()}
            elif action == "root_exec":
                cmd = kwargs.get("cmd") or kwargs.get("command")
                if not cmd:
                    return {"status": "error", "error": "Parámetro 'cmd' requerido."}
                rc, out, err = self.exec_root(cmd)
                return {"status": "ok" if rc == 0 else "error", "rc": rc, "stdout": out, "stderr": err}
            else:
                return {
                    "status": "error",
                    "error": f"Acción '{action}' no reconocida.",
                    "available_actions": [
                        "status", "psi", "dmesg", "sysctl_get", "sysctl_set",
                        "tune_all", "drop_caches", "modules", "uinput_status", "root_exec"
                    ]
                }
        except Exception as e:
            logger.error(f"[KERNEL-BRIDGE] Error ejecutando acción '{action}': {e}")
            return {"status": "error", "error": str(e)}

    # Alias para compatibilidad con ejecutores FTL
    execute = run

    # -------------------------------------------------------------------------
    # Métodos Nucleares de Acceso y Control
    # -------------------------------------------------------------------------

    def exec_root(self, cmd: str | List[str], timeout: float = 30.0) -> Tuple[int, str, str]:
        """Ejecuta un comando con privilegios root (sudo non-interactivo) de forma segura."""
        if isinstance(cmd, str):
            full_cmd = ["sudo", "-n", "bash", "-c", cmd]
        else:
            full_cmd = ["sudo", "-n"] + list(cmd)

        try:
            res = subprocess.run(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return 124, "", f"Timeout ({timeout}s) ejecutando comando root."
        except Exception as e:
            return 1, "", str(e)

    def get_psi_telemetry(self) -> Dict[str, Dict[str, Any]]:
        """Lee y estructura Pressure Stall Information (PSI) desde el Kernel (/proc/pressure)."""
        psi_data = {}
        for metric in ("cpu", "memory", "io"):
            p = Path(f"/proc/pressure/{metric}")
            if p.exists():
                try:
                    lines = p.read_text(encoding="utf-8").strip().splitlines()
                    metric_dict = {}
                    for line in lines:
                        parts = line.split()
                        scope = parts[0]
                        vals = {}
                        for kv in parts[1:]:
                            if "=" in kv:
                                k, v = kv.split("=", 1)
                                vals[k] = float(v)
                        metric_dict[scope] = vals
                    psi_data[metric] = metric_dict
                except Exception as e:
                    psi_data[metric] = {"error": str(e)}
            else:
                psi_data[metric] = {"status": "unsupported"}
        return psi_data

    def read_dmesg(self, lines: int = 50, filter_term: Optional[str] = None) -> List[str]:
        """Lee el ringbuffer de dmesg directamente."""
        try:
            cmd = ["dmesg", "--color=never", "-T"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            if res.returncode == 0:
                out_lines = res.stdout.splitlines()
                if filter_term:
                    f_low = filter_term.lower()
                    out_lines = [l for l in out_lines if f_low in l.lower()]
                return out_lines[-lines:]
        except Exception:
            pass
        return []

    def get_sysctl(self, param: str) -> str:
        """Obtiene el valor de un parámetro sysctl."""
        try:
            res = subprocess.run(["sysctl", "-n", param], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return "N/A"

    def set_sysctl(self, param: str, value: str) -> Dict[str, Any]:
        """Modifica un parámetro sysctl en caliente con privilegios soberanos."""
        rc, out, err = self.exec_root(["sysctl", "-w", f"{param}={value}"])
        if rc == 0:
            return {"status": "ok", "param": param, "value": value, "output": out}
        return {"status": "error", "rc": rc, "error": err}

    def drop_kernel_caches(self) -> Dict[str, Any]:
        """Purga cachés de memoria (pagecache, dentries, inodes) de manera limpia y segura."""
        rc, out, err = self.exec_root("sync && echo 3 > /proc/sys/vm/drop_caches")
        if rc == 0:
            return {"status": "ok", "message": "Cachés de kernel purgadas con éxito (sync && drop_caches=3)."}
        return {"status": "error", "rc": rc, "error": err}

    def check_hardware_nodes(self) -> Dict[str, Dict[str, Any]]:
        """Verifica la existencia y permisos de nodos de control clave."""
        nodes = [
            "/dev/uinput",
            "/dev/uhid",
            "/dev/fuse",
            "/dev/net/tun",
            "/dev/rtc0",
            "/dev/hidraw0"
        ]
        status = {}
        for n in nodes:
            p = Path(n)
            if p.exists():
                try:
                    st = p.stat()
                    mode_octal = oct(st.st_mode)[-4:]
                    status[n] = {
                        "exists": True,
                        "mode": mode_octal,
                        "uid": st.st_uid,
                        "gid": st.st_gid,
                        "readable": os.access(str(p), os.R_OK),
                        "writable": os.access(str(p), os.W_OK)
                    }
                except Exception as e:
                    status[n] = {"exists": True, "error": str(e)}
            else:
                status[n] = {"exists": False}
        return status

    def manage_kernel_modules(self, subcmd: str = "list", mod_name: Optional[str] = None) -> Dict[str, Any]:
        """Gestiona la carga e inspección de módulos de kernel."""
        if subcmd == "list":
            try:
                res = subprocess.run(["lsmod"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
                lines = res.stdout.strip().splitlines()
                modules = [l.split()[0] for l in lines[1:] if l.strip()]
                return {"status": "ok", "count": len(modules), "modules": modules[:30]}
            except Exception as e:
                return {"status": "error", "error": str(e)}
        elif subcmd == "load":
            if not mod_name:
                return {"status": "error", "error": "Parámetro 'mod_name' requerido."}
            rc, out, err = self.exec_root(["modprobe", mod_name])
            return {"status": "ok" if rc == 0 else "error", "rc": rc, "output": out or err}
        return {"status": "error", "error": f"Subcomando '{subcmd}' inválido."}

    def apply_sovereign_kernel_tuning(self) -> Dict[str, Any]:
        """Aplica la sintonización completa de kernel TARDIS."""
        rc, out, err = self.exec_root(["sysctl", "--system"])
        return {
            "status": "ok" if rc == 0 else "error",
            "rc": rc,
            "stdout": out,
            "stderr": err
        }

    def get_kernel_status(self) -> Dict[str, Any]:
        """Retorna telemetría exhaustiva a nivel de Kernel."""
        # Sysctl relevantes
        params = {
            "dmesg_restrict": self.get_sysctl("kernel.dmesg_restrict"),
            "ptrace_scope": self.get_sysctl("kernel.yama.ptrace_scope"),
            "perf_event_paranoid": self.get_sysctl("kernel.perf_event_paranoid"),
            "kptr_restrict": self.get_sysctl("kernel.kptr_restrict"),
            "unprivileged_bpf_disabled": self.get_sysctl("kernel.unprivileged_bpf_disabled"),
            "file_max": self.get_sysctl("fs.file-max"),
            "max_user_watches": self.get_sysctl("fs.inotify.max_user_watches"),
            "max_map_count": self.get_sysctl("vm.max_map_count"),
            "swappiness": self.get_sysctl("vm.swappiness"),
            "vfs_cache_pressure": self.get_sysctl("vm.vfs_cache_pressure")
        }

        # Nodos
        nodes = self.check_hardware_nodes()

        # PSI
        psi = self.get_psi_telemetry()

        # Memoria básica de SO
        mem_info = {}
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if any(k in line for k in ("MemTotal:", "MemFree:", "MemAvailable:", "Buffers:", "Cached:")):
                        k, v = line.split(":", 1)
                        mem_info[k.strip()] = v.strip()
        except Exception:
            pass

        return {
            "status": "ok",
            "kernel_release": os.uname().release,
            "sysctl": params,
            "hardware_nodes": nodes,
            "psi": psi,
            "mem_info": mem_info,
            "sovereign_mode": "RING_0_ROOT_SCOPE_ENABLED"
        }


# Instancia singleton para importación directa
_bridge_instance: Optional[FtlKernelBridge] = None

def get_kernel_bridge() -> FtlKernelBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = FtlKernelBridge()
    return _bridge_instance


if __name__ == "__main__":
    bridge = FtlKernelBridge()
    print("=== FTL KERNEL BRIDGE :: ESTADO DE KERNEL ===")
    status = bridge.get_kernel_status()
    print(json.dumps(status, indent=2))
