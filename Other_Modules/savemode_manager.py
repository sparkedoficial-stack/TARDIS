#!/usr/bin/env python3
"""
SAVEMODE MANAGER · TARDIS REMOTE EDGE DELEGATION
=================================================
Implementa el perfil SaveMode solicitado por el Arquitecto:

  * Estado de ejecución: ACTIVE / SAVE_MODE / DEEP_SAVE_MODE / REMOTE_EDGE_DELEGATION.
  * Telemetría completa del nodo (OS, CPU, RAM, GPU, disco, red, procesos).
  * Comandos remotos autorizados con allowlist estricta y auditoría JSONL.
  * API local en 127.0.0.1:8796 para TARDIS, FTL y el portal público.
  * Estado persistente en ~/.config/tardis/savemode.json.

Uso:
  python3 ~/.ftl/savemode_manager.py --daemon
  python3 ~/.ftl/savemode_manager.py --status
  python3 ~/.ftl/savemode_manager.py --telemetry
  python3 ~/.ftl/savemode_manager.py --command check_logs
  python3 ~/.ftl/savemode_manager.py --mode SAVE_MODE
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from aiohttp import web

HOME = Path.home()
CONFIG_DIR = HOME / ".config" / "tardis"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = CONFIG_DIR / "savemode.json"
AUDIT_PATH = CONFIG_DIR / "savemode_audit.jsonl"
STATE_PATH = CONFIG_DIR / "savemode_state.json"

VALID_MODES = {"ACTIVE", "SAVE_MODE", "DEEP_SAVE_MODE", "REMOTE_EDGE_DELEGATION"}

DEFAULT_CONFIG: Dict[str, Any] = {
    "profile_name": "SaveMode",
    "schema_version": "1.0.0",
    "execution_mode": "REMOTE_EDGE_DELEGATION",
    "host_id": "linux-core-workstation",
    "status": "ACTIVE_STANDBY",
    "control_port": 8796,
    "authorized_remote_commands": {
        "wake_heavy_models": "systemctl --user start ollama; docker unpause vision-engine",
        "enter_deep_savemode": "systemctl --user stop ollama; docker pause $(docker ps -q --filter 'label=tier=heavy')",
        "restart_gateway": "systemctl --user restart ftl-public-gateway.service ftl-web-portal.service ftl-web-terminal.service",
        "clean_memory_cache": "sync; echo 3 > /proc/sys/vm/drop_caches",
        "check_logs": "journalctl -p 3 -xb -n 20 --no-pager",
    },
    "created_at": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _atomic_write(path: Path, data: Dict[str, Any], mode: int = 0o600) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    if not cfg.get("created_at"):
        cfg["created_at"] = _now_iso()
        _atomic_write(CONFIG_PATH, cfg)
    return cfg


def load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "mode": "REMOTE_EDGE_DELEGATION",
        "status": "ACTIVE_STANDBY",
        "last_command": None,
        "last_command_at": None,
        "last_result": None,
        "commands_executed": 0,
        "updated_at": None,
    }


# ---------------------------------------------------------------------------
# Telemetría
# ---------------------------------------------------------------------------


def _read_os_release() -> Dict[str, str]:
    data: Dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k] = v.strip().strip('"')
    except Exception:
        pass
    return data


def _cpu_temp() -> Optional[float]:
    try:
        temps = psutil.sensors_temperatures()
        for key in ("coretemp", "k10temp", "acpitz", "zenpower"):
            if key in temps and temps[key]:
                return round(float(temps[key][0].current), 1)
        for entries in temps.values():
            if entries:
                return round(float(entries[0].current), 1)
    except Exception:
        pass
    return None


def _gpu_info() -> Dict[str, Any]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,temperature.gpu,utilization.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).decode().strip()
        if out:
            parts = [p.strip() for p in out.split(",")]
            if len(parts) >= 6:
                return {
                    "available": True,
                    "name": parts[0],
                    "vram_total_mb": _to_int(parts[1]),
                    "vram_used_mb": _to_int(parts[2]),
                    "temp_c": _to_int(parts[3]),
                    "utilization_percent": _to_int(parts[4]),
                    "power_draw_watts": _to_float(parts[5]),
                }
    except Exception:
        pass
    return {"available": False}


def _to_int(value: str) -> Optional[int]:
    try:
        return int(float(value))
    except Exception:
        return None


def _to_float(value: str) -> Optional[float]:
    try:
        return round(float(value), 1)
    except Exception:
        return None


def _network_info() -> Dict[str, Any]:
    interfaces: List[Dict[str, Any]] = []
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, entries in addrs.items():
            ipv4 = [e.address for e in entries if e.family == socket.AF_INET]
            if not ipv4:
                continue
            interfaces.append(
                {
                    "name": name,
                    "ipv4": ipv4,
                    "up": bool(stats.get(name).isup) if name in stats else None,
                    "speed_mbps": stats.get(name).speed if name in stats else None,
                }
            )
    except Exception:
        pass
    return {"interfaces": interfaces}


def _top_processes(limit: int = 5) -> List[Dict[str, Any]]:
    procs: List[Dict[str, Any]] = []
    try:
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                procs.append(
                    {
                        "pid": info.get("pid"),
                        "name": info.get("name"),
                        "cpu_percent": round(float(info.get("cpu_percent") or 0.0), 1),
                        "memory_percent": round(float(info.get("memory_percent") or 0.0), 2),
                    }
                )
            except Exception:
                continue
    except Exception:
        pass
    procs.sort(key=lambda p: (p["cpu_percent"], p["memory_percent"]), reverse=True)
    return procs[:limit]


def collect_telemetry() -> Dict[str, Any]:
    now = time.time()
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    boot = psutil.boot_time()
    osr = _read_os_release()
    return {
        "timestamp": now,
        "iso": _now_iso(),
        "os": {
            "distro": osr.get("PRETTY_NAME", platform.platform()),
            "id": osr.get("ID", ""),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "uptime_seconds": int(now - boot),
            "load_average": [round(x, 2) for x in load],
        },
        "resources": {
            "cpu_usage_percent": round(psutil.cpu_percent(interval=0.2), 1),
            "cpu_temp_celsius": _cpu_temp(),
            "cpu_count": psutil.cpu_count(logical=True),
            "memory": {
                "total_mb": round(mem.total / (1024 * 1024)),
                "used_mb": round(mem.used / (1024 * 1024)),
                "available_mb": round(mem.available / (1024 * 1024)),
                "percent": round(mem.percent, 1),
                "swap_used_mb": round(swap.used / (1024 * 1024)),
            },
            "gpu": _gpu_info(),
            "storage_root": {
                "mount": "/",
                "used_percent": round(disk.percent, 1),
                "free_gb": round(disk.free / (1024**3), 1),
                "total_gb": round(disk.total / (1024**3), 1),
            },
        },
        "network": _network_info(),
        "processes_top": _top_processes(),
        "hostname": socket.gethostname(),
    }


# ---------------------------------------------------------------------------
# Comandos autorizados
# ---------------------------------------------------------------------------


class CommandError(Exception):
    pass


def _run(cmd: List[str], timeout: float = 30.0, input_text: Optional[str] = None) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        res = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": res.returncode == 0,
            "rc": res.returncode,
            "stdout": (res.stdout or "")[-4000:],
            "stderr": (res.stderr or "")[-2000:],
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "cmd": " ".join(cmd),
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "rc": 127,
            "stdout": "",
            "stderr": f"Binario no encontrado: {cmd[0]}",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "cmd": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "rc": 124,
            "stdout": "",
            "stderr": f"Timeout tras {timeout}s",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "cmd": " ".join(cmd),
        }
    except Exception as exc:
        return {
            "ok": False,
            "rc": 1,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "cmd": " ".join(cmd),
        }


def _audit(entry: Dict[str, Any]) -> None:
    entry.setdefault("ts", _now_iso())
    with AUDIT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    try:
        os.chmod(AUDIT_PATH, 0o600)
    except Exception:
        pass


def execute_command(name: str) -> Dict[str, Any]:
    cfg = load_config()
    state = load_state()
    allowed = cfg.get("authorized_remote_commands", {})
    if name not in allowed:
        raise CommandError(f"Comando no autorizado: {name}. Permitidos: {sorted(allowed)}")

    if name == "wake_heavy_models":
        results = [
            _run(["systemctl", "--user", "start", "ollama"], timeout=45),
            _run(["docker", "unpause", "vision-engine"], timeout=20),
        ]
        result = {"ok": any(r["ok"] for r in results), "steps": results}
        state["mode"] = "ACTIVE"
        state["status"] = "ACTIVE_RUNNING"
    elif name == "enter_deep_savemode":
        results = [
            _run(["systemctl", "--user", "stop", "ollama"], timeout=30),
        ]
        # Pausar contenedores pesados si Docker está disponible.
        ps = _run(["docker", "ps", "-q", "--filter", "label=tier=heavy"], timeout=10)
        ids = [x for x in (ps.get("stdout") or "").splitlines() if x.strip()]
        if ids:
            results.append(_run(["docker", "pause", *ids], timeout=30))
        result = {"ok": all(r["ok"] for r in results), "steps": results}
        state["mode"] = "DEEP_SAVE_MODE"
        state["status"] = "SUSPENDED_SAVE_MODE"
    elif name == "restart_gateway":
        result = _run(
            [
                "systemctl",
                "--user",
                "restart",
                "ftl-public-gateway.service",
                "ftl-web-portal.service",
                "ftl-web-terminal.service",
            ],
            timeout=45,
        )
    elif name == "clean_memory_cache":
        # Requiere sudo sin contraseña o root. Se intenta de forma no interactiva.
        result = _run(["sudo", "-n", "sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches"], timeout=30)
        if not result["ok"] and "password" in (result.get("stderr") or "").lower():
            result["hint"] = "sudo requiere autenticación interactiva en esta estación."
    elif name == "check_logs":
        result = _run(["journalctl", "-p", "3", "-xb", "-n", "20", "--no-pager"], timeout=20)
    elif name == "status":
        result = {"ok": True, "telemetry": collect_telemetry(), "state": state, "config": cfg}
    else:
        raise CommandError(f"Comando sin implementación: {name}")

    state["last_command"] = name
    state["last_command_at"] = _now_iso()
    state["last_result"] = {
        "ok": result.get("ok", False),
        "summary": _summarize(result),
    }
    state["commands_executed"] = int(state.get("commands_executed", 0)) + 1
    state["updated_at"] = _now_iso()
    _atomic_write(STATE_PATH, state)
    _audit({"command": name, "result": result, "state": state})
    return {"ok": bool(result.get("ok")), "command": name, "result": result, "state": state}


def _summarize(result: Dict[str, Any]) -> str:
    if "steps" in result:
        return "; ".join(
            f"{s.get('cmd', '?')}: rc={s.get('rc')}" for s in result.get("steps", [])
        )[:500]
    if result.get("cmd"):
        return f"{result['cmd']}: rc={result.get('rc')} {str(result.get('stderr') or '')[:200]}"
    return "ok" if result.get("ok") else "fallo"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class SaveModeServer:
    def __init__(self) -> None:
        self.config = load_config()
        self.state = load_state()

    async def status(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "profile": self.config.get("profile_name", "SaveMode"),
                "schema_version": self.config.get("schema_version", "1.0.0"),
                "execution_mode": self.config.get("execution_mode", "REMOTE_EDGE_DELEGATION"),
                "host_id": self.config.get("host_id"),
                "status": self.state.get("status", "ACTIVE_STANDBY"),
                "mode": self.state.get("mode", "REMOTE_EDGE_DELEGATION"),
                "state": self.state,
                "authorized_commands": sorted(self.config.get("authorized_remote_commands", {}).keys()),
                "updated_at": _now_iso(),
            }
        )

    async def telemetry(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "telemetry": collect_telemetry(), "state": self.state})

    async def command(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "JSON inválido"}, status=400)
        name = str(body.get("command", "")).strip()
        if not name:
            return web.json_response({"ok": False, "error": "Falta 'command'"}, status=400)
        try:
            result = execute_command(name)
            self.state = load_state()
            return web.json_response(result)
        except CommandError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def set_mode(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "JSON inválido"}, status=400)
        mode = str(body.get("mode", "")).upper().strip()
        if mode not in VALID_MODES:
            return web.json_response(
                {"ok": False, "error": f"Modo inválido. Válidos: {sorted(VALID_MODES)}"}, status=400
            )
        self.state["mode"] = mode
        self.state["status"] = "ACTIVE_STANDBY" if mode == "ACTIVE" else mode
        self.state["updated_at"] = _now_iso()
        _atomic_write(STATE_PATH, self.state)
        _audit({"event": "set_mode", "mode": mode})
        return web.json_response({"ok": True, "mode": mode, "state": self.state})

    async def audit(self, request: web.Request) -> web.Response:
        limit = min(500, max(1, int(request.query.get("limit", 50))))
        entries: List[Dict[str, Any]] = []
        if AUDIT_PATH.exists():
            lines = AUDIT_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-limit:]:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
        return web.json_response({"ok": True, "count": len(entries), "entries": entries})

    async def run(self) -> None:
        app = web.Application()
        app.router.add_get("/status", self.status)
        app.router.add_get("/telemetry", self.telemetry)
        app.router.add_post("/command", self.command)
        app.router.add_post("/mode", self.set_mode)
        app.router.add_get("/audit", self.audit)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", int(self.config.get("control_port", 8796)))
        await site.start()
        print(f"[SAVEMODE] API en http://127.0.0.1:{self.config.get('control_port', 8796)}", flush=True)
        while True:
            await asyncio.sleep(3600)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="SaveMode Manager · TARDIS Remote Edge Delegation")
    parser.add_argument("--daemon", action="store_true", help="Ejecutar API de control continua")
    parser.add_argument("--status", action="store_true", help="Mostrar estado del perfil")
    parser.add_argument("--telemetry", action="store_true", help="Emitir telemetría completa")
    parser.add_argument("--command", metavar="NAME", help="Ejecutar un comando autorizado")
    parser.add_argument("--mode", metavar="MODE", help="Cambiar modo de ejecución")
    args = parser.parse_args()

    if args.status:
        cfg = load_config()
        state = load_state()
        print(json.dumps({"config": cfg, "state": state}, indent=2, ensure_ascii=False))
        return
    if args.telemetry:
        print(json.dumps(collect_telemetry(), indent=2, ensure_ascii=False))
        return
    if args.command:
        try:
            print(json.dumps(execute_command(args.command), indent=2, ensure_ascii=False))
        except CommandError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, ensure_ascii=False))
            sys.exit(2)
        return
    if args.mode:
        mode = args.mode.upper().strip()
        if mode not in VALID_MODES:
            print(f"Modo inválido. Válidos: {sorted(VALID_MODES)}")
            sys.exit(2)
        state = load_state()
        state["mode"] = mode
        state["status"] = "ACTIVE_STANDBY" if mode == "ACTIVE" else mode
        state["updated_at"] = _now_iso()
        _atomic_write(STATE_PATH, state)
        _audit({"event": "set_mode", "mode": mode, "source": "cli"})
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return
    if args.daemon:
        import asyncio

        asyncio.run(SaveModeServer().run())
        return
    parser.print_help()


if __name__ == "__main__":
    main()
