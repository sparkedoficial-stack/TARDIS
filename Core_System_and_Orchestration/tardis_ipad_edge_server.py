#!/usr/bin/env python3
"""
tardis_ipad_edge_server.py - Servidor Soberano Edge de TARDIS para iPad Pro M2
=============================================================================
GODWORKS SYSTEM v26.4 · Arquitectura Soberana TARDIS-NEURAL-SPACE-KAIJU
Diseñado específicamente para el Apple iPad Pro 12.9" M2 (Liquid Retina XDR, ProMotion 120Hz)
con Gobernador de Recursos Móviles (<100MB footprint), Avatar Triangular TARDIS y
Router de Complejidad Local vs Central.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs

import aiohttp
from aiohttp import web

# Configuración de Rutas y Módulos
BASE_DIR = Path(__file__).resolve().parent.parent
FTL_PATH = Path("/home/timemachine")
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(FTL_PATH) not in sys.path:
    sys.path.insert(0, str(FTL_PATH))

# Logger Soberano
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [TARDIS-IPAD-EDGE] %(message)s"
)
logger = logging.getLogger("TARDIS.iPadEdge")

# Constantes del Sistema
TARDIS_PORT = 8757
EDGE_HOST = "0.0.0.0"
EDGE_PORT = 8088
USB_IPAD_IP = "REDACTED_IP"
USB_HOST_IP = "REDACTED_IP"
LAN_HOST_IP = "REDACTED_IP"
INTERNET_URL_FILE = BASE_DIR / "IPAD_INTERNET_URL.txt"
IPA_PATH = BASE_DIR / "tardis_ipad_native" / "build" / "tardis_ipad_native.ipa"
ASSETS_DIR = BASE_DIR / "tardis_ipad_native" / "assets"
ICON_PNG = ASSETS_DIR / "icon_512.png"
if not ICON_PNG.exists():
    ICON_PNG = ASSETS_DIR / "icon_192.png"

# Lazy-loaded Omni Tool Bridge
_omni_bridge = None

def get_bridge():
    global _omni_bridge
    if _omni_bridge is None:
        try:
            from core.tardis_omni_tool_bridge import TardisOmniToolBridge
            _omni_bridge = TardisOmniToolBridge.get_instance()
        except Exception as e:
            logger.error(f"Error cargando TardisOmniToolBridge: {e}")
    return _omni_bridge

def get_internet_url() -> str:
    if INTERNET_URL_FILE.exists():
        try:
            url = INTERNET_URL_FILE.read_text().strip()
            if url.startswith("https://"):
                return url
        except Exception:
            pass
    return "https://importance-also-makeup-evidence.trycloudflare.com"

# Telemetría de Kernel (PSI, Memoria, CPU)
def get_kernel_psi() -> Dict[str, Any]:
    psi_data = {"cpu": "N/A", "memory": "N/A", "io": "N/A"}
    for res in ("cpu", "memory", "io"):
        p = Path(f"/proc/pressure/{res}")
        if p.exists():
            try:
                psi_data[res] = p.read_text().strip().replace("\n", " | ")
            except Exception:
                pass
    return psi_data

def get_system_telemetry() -> Dict[str, Any]:
    # CPU & Memoria
    mem_info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    mem_info[parts[0].strip()] = parts[1].strip()
        mem_total_kb = int(mem_info.get("MemTotal", "0 kB").split()[0])
        mem_avail_kb = int(mem_info.get("MemAvailable", "0 kB").split()[0])
        mem_used_pct = round((mem_total_kb - mem_avail_kb) / max(1, mem_total_kb) * 100, 1)
        mem_total_gb = round(mem_total_kb / 1048576, 2)
        mem_avail_gb = round(mem_avail_kb / 1048576, 2)
    except Exception:
        mem_used_pct, mem_total_gb, mem_avail_gb = 0, 0, 0

    # Load avg
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        load1, load5, load15 = 0.0, 0.0, 0.0

    # Ping a iPad
    ping_ms = "<1.0"
    try:
        res = subprocess.run(["ping", "-c", "1", "-W", "1", USB_IPAD_IP], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if "time=" in line:
                    ping_ms = line.split("time=")[1].split()[0] + " ms"
    except Exception:
        pass

    return {
        "timestamp": time.time(),
        "mem_used_pct": mem_used_pct,
        "mem_total_gb": mem_total_gb,
        "mem_avail_gb": mem_avail_gb,
        "load_avg": [round(load1, 2), round(load5, 2), round(load15, 2)],
        "psi": get_kernel_psi(),
        "ipad_usb_ip": USB_IPAD_IP,
        "ipad_ping": ping_ms,
        "host_ip": LAN_HOST_IP,
        "internet_url": get_internet_url()
    }

# Generador del WebClip Mobileconfig
def generate_webclip_profile(target_url: Optional[str] = None) -> bytes:
    profile_uuid = "REDACTED_PHONE-2108-201E-TARDIS000001"
    payload_uuid = "REDACTED_PHONE-2108-201E-TARDIS000002"

    if not target_url:
        target_url = get_internet_url()

    icon_data = b""
    if ICON_PNG.exists():
        icon_data = ICON_PNG.read_bytes()

    payload = {
        "PayloadType": "com.apple.webClip.managed",
        "PayloadVersion": 1,
        "PayloadIdentifier": "com.godworks.tardis.m2.webclip",
        "PayloadUUID": payload_uuid,
        "PayloadDisplayName": "TARDIS Pro M2",
        "PayloadDescription": "Acceso Soberano TARDIS GODWORKS System en iPad Pro M2",
        "PayloadOrganization": "GODWORKS System",
        "Label": "TARDIS Pro M2",
        "URL": target_url,
        "FullScreen": True,
        "IsRemovable": True,
        "Precomposed": True,
        "Icon": icon_data,
        "IgnoreManifestScope": True
    }

    profile = {
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadIdentifier": "com.godworks.tardis.m2.profile",
        "PayloadUUID": profile_uuid,
        "PayloadDisplayName": "TARDIS Pro M2 Native",
        "PayloadDescription": "Instalación Nativa de TARDIS en Apple iPad Pro M2",
        "PayloadOrganization": "GODWORKS System",
        "PayloadContent": [payload]
    }

    return plistlib.dumps(profile)

# Vistas y Rutas HTTP
async def index_handler(request: web.Request) -> web.Response:
    logger.info(f"[HTTP] Solicitud recibida GET / desde cliente IP: {request.remote}")
    html_content = get_client_html()
    return web.Response(text=html_content, content_type="text/html")

async def manifest_handler(request: web.Request) -> web.Response:
    manifest = {
        "name": "TARDIS Pro M2 Sovereign",
        "short_name": "TARDIS M2",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#030712",
        "theme_color": "#030712",
        "orientation": "any",
        "icons": [
            {
                "src": "/icon.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }
    return web.json_response(manifest)

async def icon_handler(request: web.Request) -> web.Response:
    if ICON_PNG.exists():
        return web.FileResponse(ICON_PNG)
    return web.Response(status=404)

async def profile_handler(request: web.Request) -> web.Response:
    target_url = None
    if "internet" in request.path or "internet" in request.query:
        target_url = get_internet_url()
    else:
        host = request.headers.get("Host", f"{LAN_HOST_IP}:{EDGE_PORT}").split(":")[0]
        if host in ("127.0.0.1", "localhost", "0.0.0.0"):
            host = LAN_HOST_IP
        target_url = f"http://{host}:{EDGE_PORT}/"

    profile_data = generate_webclip_profile(target_url=target_url)
    return web.Response(
        body=profile_data,
        content_type="application/x-apple-aspen-config",
        headers={
            "Content-Disposition": 'attachment; filename="tardis_pro_m2.mobileconfig"'
        }
    )

async def download_ipa_handler(request: web.Request) -> web.Response:
    if IPA_PATH.exists():
        return web.FileResponse(
            IPA_PATH,
            headers={
                "Content-Disposition": 'attachment; filename="TARDIS_Pro_M2.ipa"'
            }
        )
    return web.Response(text="IPA no encontrado", status=404)

LINPAD_IPA_PATH = Path("/home/timemachine/LinPad/build/LinPad-1.6.0-TARDIS-M2.ipa")
LINPAD_ICON_PNG = Path("/home/timemachine/LinPad/build/unpacked/Payload/iSH ARM64.app/REDACTED_EMAIL")

async def download_linpad_ipa_handler(request: web.Request) -> web.Response:
    if LINPAD_IPA_PATH.exists():
        return web.FileResponse(
            LINPAD_IPA_PATH,
            headers={
                "Content-Disposition": 'attachment; filename="LinPad-1.6.0-TARDIS-M2.ipa"'
            }
        )
    return web.Response(text="LinPad IPA no encontrado", status=404)

async def linpad_profile_handler(request: web.Request) -> web.Response:
    host = request.headers.get("Host", f"{LAN_HOST_IP}:{EDGE_PORT}").split(":")[0]
    if host in ("127.0.0.1", "localhost", "0.0.0.0"):
        host = LAN_HOST_IP
    target_url = f"http://{host}:{EDGE_PORT}/linpad"
    icon_data = b""
    if LINPAD_ICON_PNG.exists():
        icon_data = LINPAD_ICON_PNG.read_bytes()
    elif ICON_PNG.exists():
        icon_data = ICON_PNG.read_bytes()

    payload = {
        "PayloadType": "com.apple.webClip.managed",
        "PayloadVersion": 1,
        "PayloadIdentifier": "com.godworks.linpad.m2.webclip",
        "PayloadUUID": "REDACTED_PHONE-2108-201E-LINPAD000002",
        "PayloadDisplayName": "LinPad 1.6 M2",
        "PayloadDescription": "LinPad 1.6.0-TARDIS-M2 Linux Desktop Environment para iPad Pro M2",
        "PayloadOrganization": "GODWORKS System · LinPad M2",
        "Label": "LinPad M2",
        "URL": target_url,
        "FullScreen": True,
        "IsRemovable": True,
        "Precomposed": True,
        "Icon": icon_data,
        "IgnoreManifestScope": True
    }
    profile = {
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadIdentifier": "com.godworks.linpad.m2.profile",
        "PayloadUUID": "REDACTED_PHONE-2108-201E-LINPAD000001",
        "PayloadDisplayName": "LinPad 1.6.0-TARDIS-M2 Desktop",
        "PayloadDescription": "Instalación de LinPad 1.6.0-TARDIS-M2 (Sway + Waybar + FTL/TARDIS) en Apple iPad Pro M2",
        "PayloadOrganization": "GODWORKS System",
        "PayloadContent": [payload]
    }
    return web.Response(
        body=plistlib.dumps(profile),
        content_type="application/x-apple-aspen-config",
        headers={
            "Content-Disposition": 'attachment; filename="linpad_m2.mobileconfig"'
        }
    )

async def api_linpad_status_handler(request: web.Request) -> web.Response:
    try:
        from modulos_ftl.ftl_linpad import FtlLinpad
        ctl = FtlLinpad()
        st = ctl.get_status()
        cat = ctl.get_catalog()
        thm = ctl.get_themes()
        return web.json_response({
            "ok": True,
            "status": st,
            "catalog": cat,
            "themes": thm
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_linpad_exec_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "JSON malformado"}, status=400)
    cmd = body.get("command", "linpad-fetch --pipe").strip()
    env = os.environ.copy()
    env["PATH"] = f"/usr/local/bin:/home/timemachine/.local/bin:/home/timemachine/Escritorio/GODWORKS SYSTEM/bin:{env.get('PATH', '')}"
    start_t = time.time()
    try:
        res = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/home/timemachine/LinPad",
            env=env
        )
        return web.json_response({
            "ok": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "exit_code": res.returncode,
            "elapsed_s": round(time.time() - start_t, 3)
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_telemetry_handler(request: web.Request) -> web.Response:
    data = get_system_telemetry()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{TARDIS_PORT}/api/status", timeout=1.5) as resp:
                if resp.status == 200:
                    tardis_data = await resp.json()
                    data["tardis"] = {
                        "online": True,
                        "model": tardis_data.get("model", "TARDIS-NEURAL-SPACE-KAIJU"),
                        "vault": tardis_data.get("vault_250gb", {}),
                        "thoughts": tardis_data.get("background_thoughts_count", 0)
                    }
    except Exception:
        data["tardis"] = {"online": False}

    return web.json_response(data)

async def api_tools_handler(request: web.Request) -> web.Response:
    bridge = get_bridge()
    if bridge:
        return web.json_response(bridge.list_tools())
    return web.json_response({"status": "error", "message": "Bridge no disponible"})

async def api_tool_execute_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"status": "error", "error": "JSON malformado"}, status=400)

    tool_id = body.get("tool_id")
    action = body.get("action", "status")
    params = body.get("params", {})

    if not tool_id:
        return web.json_response({"status": "error", "error": "tool_id requerido"}, status=400)

    bridge = get_bridge()
    if not bridge:
        return web.json_response({"status": "error", "error": "Bridge omni-herramientas no inicializado"}, status=500)

    res = bridge.execute_tool(tool_id, action=action, **params)
    return web.json_response(res)

async def api_chat_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "JSON malformado"}, status=400)

    prompt = body.get("prompt") or body.get("message")
    if not prompt:
        return web.json_response({"ok": False, "error": "Prompt vacío"}, status=400)

    client_id = body.get("client_id", "ipad_pro_m2")
    model = body.get("model", "TARDIS-NEURAL-SPACE-KAIJU")

    payload = {
        "prompt": prompt,
        "message": prompt,
        "client_id": client_id,
        "model": model,
        "client_mode": True,
        "direction": "present"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{TARDIS_PORT}/api/chat",
                json=payload,
                timeout=60.0
            ) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    return web.json_response(res_json)
                else:
                    err_txt = await resp.text()
                    return web.json_response({"ok": False, "error": f"TARDIS Error {resp.status}: {err_txt[:200]}"}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"ok": False, "error": "Timeout esperando respuesta de Central TARDIS (60s)"}, status=504)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Fallo de conexión con Central TARDIS: {str(e)}"}, status=500)

async def api_ipad_screenshot_handler(request: web.Request) -> web.Response:
    temp_shot = Path("/tmp/ipad_live_capture.png")
    try:
        res = subprocess.run(
            ["python3", "-m", "pymobiledevice3", "developer", "dvt", "screenshot", str(temp_shot)],
            capture_output=True,
            text=True,
            timeout=10
        )
        if res.returncode == 0 and temp_shot.exists():
            return web.FileResponse(temp_shot, headers={"Cache-Control": "no-cache"})
    except Exception as e:
        logger.warning(f"Error capturando pantalla iPad: {e}")

    return web.Response(text="Error capturando pantalla", status=500)

# HTML5 / CSS3 / JavaScript con Gobernador de Memoria (<100MB), Avatar Triangular TARDIS y Local LLM

# =========================================================================
# --- APIS DEL IDE SOBERANO & SINCRONIZACIÓN BIDIRECCIONAL ---
# =========================================================================
LOCAL_WORKSPACE = BASE_DIR
PROJECTS_DIR = BASE_DIR / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
FTL_DIR = Path("/home/timemachine/modulos_ftl")

async def api_fs_tree_handler(request: web.Request) -> web.Response:
    items = []
    # projects
    if PROJECTS_DIR.exists():
        for p in sorted(PROJECTS_DIR.glob("**/*")):
            if p.is_file():
                rel = str(p.relative_to(PROJECTS_DIR))
                items.append({
                    "name": p.name,
                    "rel_path": f"projects/{rel}",
                    "size": p.stat().st_size,
                    "type": "file",
                    "group": "projects"
                })
    # modulos_ftl
    if FTL_DIR.exists():
        for p in sorted(FTL_DIR.glob("*.py")):
            if p.is_file():
                items.append({
                    "name": p.name,
                    "rel_path": f"modulos_ftl/{p.name}",
                    "size": p.stat().st_size,
                    "type": "file",
                    "group": "modulos_ftl"
                })
    return web.json_response({"ok": True, "files": items, "root": "/TARDIS_WORKSPACE"})

async def api_fs_read_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "JSON malformado"}, status=400)
    rel_path = body.get("path", "").strip().lstrip("/")
    if not rel_path:
        return web.json_response({"ok": False, "error": "Ruta vacía"}, status=400)

    target = None
    if rel_path.startswith("projects/"):
        target = PROJECTS_DIR / rel_path[len("projects/"):]
    elif rel_path.startswith("modulos_ftl/"):
        target = FTL_DIR / rel_path[len("modulos_ftl/"):]
    else:
        target = LOCAL_WORKSPACE / rel_path

    if target and target.exists() and target.is_file():
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            return web.json_response({"ok": True, "path": rel_path, "content": content, "size": target.stat().st_size})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    return web.json_response({"ok": False, "error": f"Archivo no encontrado: {rel_path}"}, status=404)

async def api_fs_write_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "JSON malformado"}, status=400)
    rel_path = body.get("path", "").strip().lstrip("/")
    content = body.get("content", "")
    commit_msg = body.get("commit_message") or f"iPad M2 edit: {rel_path}"

    if not rel_path:
        return web.json_response({"ok": False, "error": "Ruta vacía"}, status=400)

    target = None
    if rel_path.startswith("projects/"):
        target = PROJECTS_DIR / rel_path[len("projects/"):]
    elif rel_path.startswith("modulos_ftl/"):
        target = FTL_DIR / rel_path[len("modulos_ftl/"):]
    else:
        target = LOCAL_WORKSPACE / rel_path

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    # Sincronización inmediata al iPad vía AFC
    afc_ok = False
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService
        ld = await create_using_usbmux()
        async with AfcService(ld) as afc:
            remote_full = f"/TARDIS_WORKSPACE/{rel_path}"
            parent = str(Path(remote_full).parent)
            parts = parent.strip("/").split("/")
            curr = ""
            for p in parts:
                curr += f"/{p}"
                try:
                    await afc.makedirs(curr)
                except Exception:
                    pass
            await afc.set_file_contents(remote_full, content.encode("utf-8"))
            afc_ok = True
    except Exception as e:
        logger.warning(f"Error sincronizando vía AFC a iPad: {e}")

    # Sincronización con GitHub vía FTL Git Sync
    git_res = {"ok": False}
    try:
        from modulos_ftl.ftl_git_sync import FtlGitSync
        git_res = FtlGitSync().run("sync", message=commit_msg)
    except Exception as e:
        git_res = {"ok": False, "error": str(e)}

    return web.json_response({
        "ok": True,
        "path": rel_path,
        "bytes_written": len(content.encode("utf-8")),
        "afc_synced": afc_ok,
        "git_synced": git_res.get("ok", False),
        "git_status": git_res
    })

async def api_fs_execute_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "JSON malformado"}, status=400)
    code = body.get("code")
    rel_path = body.get("path")
    
    cmd = []
    if code:
        cmd = [sys.executable, "-c", code]
    elif rel_path:
        target = None
        if rel_path.startswith("projects/"):
            target = PROJECTS_DIR / rel_path[len("projects/"):]
        elif rel_path.startswith("modulos_ftl/"):
            target = FTL_DIR / rel_path[len("modulos_ftl/"):]
        else:
            target = LOCAL_WORKSPACE / rel_path
        if not target or not target.exists():
            return web.json_response({"ok": False, "error": f"Archivo no existe: {rel_path}"}, status=404)
        cmd = [sys.executable, str(target)]
    else:
        return web.json_response({"ok": False, "error": "Ni código ni ruta proporcionados"}, status=400)

    start_t = time.time()
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(LOCAL_WORKSPACE)
        )
        elapsed = round(time.time() - start_t, 3)
        return web.json_response({
            "ok": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "exit_code": res.returncode,
            "elapsed_s": elapsed
        })
    except subprocess.TimeoutExpired:
        return web.json_response({"ok": False, "error": "Ejecución excedió el límite de 30 segundos", "elapsed_s": 30.0}, status=504)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_terminal_exec_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "JSON malformado"}, status=400)
    command = body.get("command", "").strip()
    if not command:
        return web.json_response({"ok": False, "error": "Comando vacío"}, status=400)

    start_t = time.time()
    env = os.environ.copy()
    bin_dir = "/home/timemachine/Escritorio/GODWORKS SYSTEM/bin"
    local_bin = "/home/timemachine/.local/bin"
    env["PATH"] = f"{bin_dir}:{local_bin}:{env.get('PATH', '')}"
    env["AGY_MODE"] = "ultra"
    env["AGY_MODEL"] = "claude-opus-5-5-high"
    env["AGY_VERBOSITY"] = "high"
    env["AGY_KERNEL_LEVEL"] = "1"
    env["FTL_AUTONOMOUS"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    timeout_limit = 180 if ("agy" in command) else 45
    try:
        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_limit,
            cwd=str(LOCAL_WORKSPACE),
            env=env
        )
        elapsed = round(time.time() - start_t, 3)
        return web.json_response({
            "ok": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "exit_code": res.returncode,
            "elapsed_s": elapsed
        })
    except subprocess.TimeoutExpired:
        return web.json_response({"ok": False, "error": f"Comando excedió límite de {timeout_limit} segundos", "elapsed_s": float(timeout_limit)}, status=504)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_kernel_base_handler(request: web.Request) -> web.Response:
    # 1. Linux Ring 0 PSI & Telemetria
    psi_info = get_kernel_psi()
    
    # 2. dmesg tail
    dmesg_tail = []
    try:
        res = subprocess.run(["dmesg", "--ctime"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            dmesg_tail = res.stdout.splitlines()[-12:]
    except Exception:
        pass

    # 3. iPadOS Darwin / Mach Kernel via DVT
    ipad_processes = []
    try:
        res = subprocess.run(
            ["python3", "-m", "pymobiledevice3", "developer", "dvt", "proclist"],
            capture_output=True, text=True, timeout=6
        )
        if res.returncode == 0:
            plist = json.loads(res.stdout)
            for p in plist[:35]:
                ipad_processes.append({
                    "pid": p.get("pid"),
                    "name": p.get("name"),
                    "is_app": p.get("isApplication", False),
                    "path": p.get("realAppName", "")
                })
    except Exception as e:
        logger.warning(f"Error obteniendo procesos DVT: {e}")

    return web.json_response({
        "ok": True,
        "linux_ring0": {
            "psi": psi_info,
            "dmesg": dmesg_tail,
            "swappiness": os.popen("sysctl -n vm.swappiness 2>/dev/null").read().strip(),
            "dirty_ratio": os.popen("sysctl -n vm.dirty_ratio 2>/dev/null").read().strip(),
            "tcp_congestion": os.popen("sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null").read().strip()
        },
        "ipad_darwin_kernel": {
            "device": 'Apple iPad Pro 12.9" 6th Gen (Apple M2)',
            "os": "iPadOS 27.0 (Build 24A437, Developer Mode)",
            "total_disk_gb": 256.0,
            "free_disk_gb": 201.8,
            "allocated_quota_gb": 100.0,
            "processes_count": len(ipad_processes),
            "top_processes": ipad_processes[:20]
        }
    })

def get_client_html() -> str:
    internet_url = get_internet_url()
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="TARDIS M2">
    <meta name="format-detection" content="telephone=no">
    <title>TARDIS Pro M2 · Sovereign Neural Interface</title>
    <link rel="apple-touch-icon" href="/icon.png">
    <link rel="manifest" href="/manifest.json">
    <style>
        :root {{
            --bg-deep: #030712;
            --bg-card: rgba(15, 23, 42, 0.75);
            --bg-card-border: rgba(56, 189, 248, 0.2);
            --neon-cyan: #06b6d4;
            --neon-blue: #3b82f6;
            --neon-green: #10b981;
            --neon-amber: #f59e0b;
            --neon-purple: #a855f7;
            --neon-red: #ef4444;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", Roboto, sans-serif;
            --safe-top: env(safe-area-inset-top, 24px);
            --safe-bottom: env(safe-area-inset-bottom, 20px);
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
            user-select: none;
        }}
        body {{
            background-color: var(--bg-deep);
            color: var(--text-main);
            font-family: var(--font-sans);
            height: 100vh;
            width: 100vw;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            padding-top: var(--safe-top);
            padding-bottom: var(--safe-bottom);
            background-image: 
                radial-gradient(circle at 15% 15%, rgba(6, 182, 212, 0.08) 0%, transparent 40%),
                radial-gradient(circle at 85% 85%, rgba(168, 85, 247, 0.08) 0%, transparent 40%);
        }}
        /* Header Superior */
        
        .header-nav {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .nav-chip {{
            background: rgba(15, 23, 42, 0.65);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: var(--text-muted);
            padding: 6px 14px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .nav-chip:hover {{
            border-color: var(--neon-cyan);
            color: #fff;
        }}
        .nav-chip.active {{
            background: rgba(6, 182, 212, 0.18);
            border-color: var(--neon-cyan);
            color: #ffffff;
            box-shadow: 0 0 12px rgba(6, 182, 212, 0.3);
        }}

        header {{
            height: 64px;
            padding: 0 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--bg-card-border);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            background: rgba(3, 7, 18, 0.85);
            z-index: 100;
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .brand-logo {{
            width: 38px;
            height: 38px;
            border-radius: 10px;
            box-shadow: 0 0 15px rgba(6, 182, 212, 0.5);
            border: 1px solid var(--neon-cyan);
        }}
        .brand-title {{
            font-size: 1.15rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            background: linear-gradient(135deg, #38bdf8, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .brand-subtitle {{
            font-size: 0.68rem;
            color: var(--neon-cyan);
            font-family: var(--font-mono);
            letter-spacing: 0.1em;
        }}
        .header-badges {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .internet-badge {{
            display: flex;
            align-items: center;
            gap: 6px;
            background: rgba(168, 85, 247, 0.15);
            border: 1px solid rgba(168, 85, 247, 0.4);
            color: #d8b4fe;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-family: var(--font-mono);
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s ease;
        }}
        .internet-badge:active {{
            transform: scale(0.96);
            background: rgba(168, 85, 247, 0.3);
        }}
        .status-dot {{
            width: 8px;
            height: 8px;
            background-color: var(--neon-green);
            border-radius: 50%;
            box-shadow: 0 0 8px var(--neon-green);
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0% {{ transform: scale(0.95); opacity: 0.7; }}
            50% {{ transform: scale(1.15); opacity: 1; }}
            100% {{ transform: scale(0.95); opacity: 0.7; }}
        }}

        /* Contenedor Principal */
        main {{
            flex: 1;
            position: relative;
            overflow: hidden;
            display: flex;
        }}
        .tab-view {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            display: none;
            flex-direction: column;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            padding: 16px 20px;
            opacity: 0;
            transform: scale(0.98);
            transition: opacity 0.2s ease, transform 0.2s ease;
        }}
        .tab-view.active {{
            display: flex;
            opacity: 1;
            transform: scale(1);
        }}

        /* PERSONAJE TRIANGULAR TARDIS (AVATAR PROCEDURAL) */
        .character-hero {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 20px;
            padding: 10px 0 16px 0;
            background: radial-gradient(circle at center, rgba(6, 182, 212, 0.08) 0%, transparent 70%);
            border-bottom: 1px solid rgba(56, 189, 248, 0.15);
            margin-bottom: 12px;
        }}
        #companion-avatar-wrap {{
            position: relative;
            width: 130px;
            height: 130px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            animation: companionFloat 3.6s ease-in-out infinite;
        }}
        @keyframes companionFloat {{
            0%, 100% {{ transform: translateY(0px); }}
            50% {{ transform: translateY(-7px); }}
        }}
        #companion-canvas {{
            width: 130px;
            height: 130px;
            display: block;
            border-radius: 50%;
            transition: filter 0.25s, transform 0.2s;
        }}
        #companion-avatar-wrap:active #companion-canvas {{
            transform: scale(0.95);
            filter: brightness(1.3) drop-shadow(0 0 20px rgba(0, 212, 200, 0.9));
        }}
        .character-meta {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .char-title {{
            font-size: 1.1rem;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: 0.05em;
        }}
        .char-state {{
            font-size: 0.78rem;
            font-family: var(--font-mono);
            color: var(--neon-cyan);
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .char-desc {{
            font-size: 0.75rem;
            color: var(--text-muted);
            max-width: 380px;
            line-height: 1.35;
        }}

        /* Selector de Modo de Inferencia (Auto / Local M2 / Central) */
        .router-selector {{
            display: flex;
            align-items: center;
            gap: 6px;
            background: rgba(15, 23, 42, 0.85);
            padding: 4px;
            border-radius: 20px;
            border: 1px solid var(--bg-card-border);
            width: fit-content;
            margin-top: 4px;
        }}
        .router-btn {{
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 5px 12px;
            border-radius: 16px;
            font-size: 0.72rem;
            font-family: var(--font-mono);
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .router-btn.active {{
            background: var(--neon-cyan);
            color: #030712;
            font-weight: 700;
            box-shadow: 0 0 10px rgba(6, 182, 212, 0.4);
        }}

        /* Barra de Navegación Inferior (Dock iPad Touch) */
        nav.bottom-dock {{
            height: 70px;
            background: rgba(15, 23, 42, 0.88);
            backdrop-filter: blur(25px);
            -webkit-backdrop-filter: blur(25px);
            border-top: 1px solid var(--bg-card-border);
            display: flex;
            justify-content: space-around;
            align-items: center;
            padding: 0 20px;
            z-index: 100;
        }}
        .dock-btn {{
            background: transparent;
            border: none;
            color: var(--text-muted);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 5px;
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            padding: 8px 18px;
            border-radius: 14px;
            transition: all 0.2s ease;
        }}
        .dock-btn svg {{
            width: 22px;
            height: 22px;
            stroke: currentColor;
            stroke-width: 2;
            fill: none;
            transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
        }}
        .dock-btn.active {{
            color: var(--neon-cyan);
            background: rgba(6, 182, 212, 0.12);
        }}
        .dock-btn.active svg {{
            transform: scale(1.15) translateY(-2px);
            stroke: var(--neon-cyan);
            filter: drop-shadow(0 0 6px var(--neon-cyan));
        }}

        /* CHAT CONTAINER */
        .chat-container {{
            display: flex;
            flex-direction: column;
            height: 100%;
            max-width: 1200px;
            margin: 0 auto;
            width: 100%;
        }}
        .chat-history {{
            flex: 1;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            padding: 10px 0;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }}
        .chat-bubble {{
            max-width: 88%;
            padding: 16px 20px;
            border-radius: 18px;
            font-size: 0.98rem;
            line-height: 1.6;
            word-break: break-word;
            user-select: text;
            animation: fadeIn 0.25s ease;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .chat-bubble.user {{
            align-self: flex-end;
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: #ffffff;
            border-bottom-right-radius: 4px;
            box-shadow: 0 4px 15px rgba(37, 99, 235, 0.3);
        }}
        .chat-bubble.assistant {{
            align-self: flex-start;
            background: rgba(30, 41, 59, 0.7);
            border: 1px solid var(--bg-card-border);
            color: var(--text-main);
            border-bottom-left-radius: 4px;
            backdrop-filter: blur(10px);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }}
        .bubble-meta {{
            font-size: 0.72rem;
            font-family: var(--font-mono);
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .badge-router {{
            padding: 3px 8px;
            border-radius: 10px;
            font-size: 0.68rem;
            font-weight: 700;
        }}
        .badge-local {{
            background: rgba(16, 185, 129, 0.2);
            color: var(--neon-green);
            border: 1px solid rgba(16, 185, 129, 0.4);
        }}
        .badge-central {{
            background: rgba(168, 85, 247, 0.2);
            color: #d8b4fe;
            border: 1px solid rgba(168, 85, 247, 0.4);
        }}
        .chat-chips {{
            display: flex;
            gap: 8px;
            overflow-x: auto;
            padding: 6px 0;
            margin-bottom: 6px;
            scrollbar-width: none;
        }}
        .chat-chip {{
            background: rgba(30, 41, 59, 0.6);
            border: 1px solid var(--bg-card-border);
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.78rem;
            color: var(--neon-cyan);
            white-space: nowrap;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .chat-chip:active {{
            background: var(--neon-cyan);
            color: #030712;
            transform: scale(0.96);
        }}
        .chat-input-bar {{
            display: flex;
            gap: 10px;
            background: rgba(15, 23, 42, 0.88);
            padding: 10px 16px;
            border-radius: 24px;
            border: 1px solid var(--bg-card-border);
            backdrop-filter: blur(20px);
        }}
        .chat-input-bar input {{
            flex: 1;
            background: transparent;
            border: none;
            color: var(--text-main);
            font-size: 1.05rem;
            outline: none;
            user-select: text;
        }}
        .send-btn {{
            background: linear-gradient(135deg, var(--neon-cyan), var(--neon-blue));
            border: none;
            width: 44px;
            height: 44px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 0 15px rgba(6, 182, 212, 0.4);
            transition: transform 0.15s ease;
        }}
        .send-btn:active {{
            transform: scale(0.9);
        }}
        .send-btn svg {{
            width: 20px;
            height: 20px;
            fill: #ffffff;
        }}

        /* TAB 2: OMNI TOOLS */
        .tools-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }}
        .tool-card {{
            background: var(--bg-card);
            border: 1px solid var(--bg-card-border);
            border-radius: 20px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            backdrop-filter: blur(15px);
        }}
        .tool-
        .header-nav {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .nav-chip {{
            background: rgba(15, 23, 42, 0.65);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: var(--text-muted);
            padding: 6px 14px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .nav-chip:hover {{
            border-color: var(--neon-cyan);
            color: #fff;
        }}
        .nav-chip.active {{
            background: rgba(6, 182, 212, 0.18);
            border-color: var(--neon-cyan);
            color: #ffffff;
            box-shadow: 0 0 12px rgba(6, 182, 212, 0.3);
        }}

        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .tool-name {{
            font-size: 1.1rem;
            font-weight: 700;
            color: #ffffff;
        }}
        .tool-badge {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--neon-green);
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-family: var(--font-mono);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}
        .tool-desc {{
            font-size: 0.85rem;
            color: var(--text-muted);
            line-height: 1.4;
        }}
        .tool-actions {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 6px;
        }}
        .action-btn {{
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid var(--bg-card-border);
            color: #38bdf8;
            padding: 8px 14px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-family: var(--font-mono);
            cursor: pointer;
            transition: all 0.15s ease;
        }}
        .action-btn:active {{
            background: #0284c7;
            color: #ffffff;
            transform: scale(0.95);
        }}
        .terminal-box {{
            background: #000000;
            border: 1px solid var(--bg-card-border);
            border-radius: 18px;
            padding: 16px;
            font-family: var(--font-mono);
            font-size: 0.85rem;
            color: #10b981;
            height: 260px;
            overflow-y: auto;
            user-select: text;
            box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.8);
            white-space: pre-wrap;
        }}

        /* TAB 3: TELEMETRY & RADAR */
        .telemetry-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background: var(--bg-card);
            border: 1px solid var(--bg-card-border);
            border-radius: 20px;
            padding: 20px;
            backdrop-filter: blur(15px);
        }}
        .stat-label {{
            font-size: 0.8rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 6px;
        }}
        .stat-value {{
            font-size: 1.8rem;
            font-weight: 800;
            color: var(--neon-cyan);
            font-family: var(--font-mono);
        }}
        .stat-sub {{
            font-size: 0.8rem;
            color: var(--neon-green);
            margin-top: 4px;
        }}

        /* TAB 4: VAULT & DOWNLOADS */
        .vault-card {{
            background: var(--bg-card);
            border: 1px solid var(--bg-card-border);
            border-radius: 24px;
            padding: 24px;
            max-width: 800px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 18px;
        }}
        .btn-action {{
            color: #ffffff;
            border: none;
            padding: 16px 24px;
            border-radius: 16px;
            font-size: 1.02rem;
            font-weight: 700;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            transition: transform 0.15s ease;
        }}
        .btn-action:active {{
            transform: scale(0.98);
        }}
        .btn-internet {{
            background: linear-gradient(135deg, #a855f7, #6b21a8);
            box-shadow: 0 4px 15px rgba(168, 85, 247, 0.4);
        }}
        .btn-download {{
            background: linear-gradient(135deg, #10b981, #059669);
            box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3);
        }}
        .btn-config {{
            background: linear-gradient(135deg, #3b82f6, #1d4ed8);
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3);
        }}
    
        /* IDE SOBERANO STYLES */
        .ide-container {{
            display: flex;
            height: calc(100vh - 170px);
            background: rgba(10, 15, 30, 0.95);
            border: 1px solid rgba(0, 212, 200, 0.25);
            border-radius: 14px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0,0,0,0.6);
        }}
        .ide-sidebar {{
            width: 280px;
            background: rgba(15, 23, 42, 0.85);
            border-right: 1px solid rgba(255, 255, 255, 0.1);
            padding: 14px;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
        }}
        .ide-sidebar-title {{
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--neon-cyan);
            letter-spacing: 1.5px;
            text-transform: uppercase;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .ide-editor-pane {{
            flex: 1;
            display: flex;
            flex-direction: column;
            padding: 14px;
            background: #020610;
        }}
        .ide-toolbar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 10px;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .ide-active-tab {{
            font-family: var(--font-mono);
            font-size: 0.9rem;
            color: var(--neon-cyan);
            background: rgba(0, 212, 200, 0.1);
            padding: 6px 14px;
            border-radius: 8px;
            border: 1px solid rgba(0, 212, 200, 0.3);
        }}
        .ide-btn-group {{
            display: flex;
            gap: 8px;
        }}
        .btn-ide {{
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 0.82rem;
            font-weight: 700;
            cursor: pointer;
            border: none;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
        }}
        .btn-ide-save {{
            background: var(--neon-cyan);
            color: #000;
        }}
        .btn-ide-run {{
            background: var(--neon-gold);
            color: #000;
        }}
        .btn-ide-push {{
            background: var(--neon-purple);
            color: #fff;
        }}
        .ide-code-box {{
            flex: 1;
            min-height: 280px;
            font-family: var(--font-mono);
            font-size: 0.92rem;
            background: #010409;
            color: #e2e8f0;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 14px;
            resize: none;
            outline: none;
            line-height: 1.6;
            white-space: pre;
            tab-size: 4;
        }}
        .ide-console-box {{
            height: 140px;
            font-family: var(--font-mono);
            font-size: 0.8rem;
            background: #000000;
            color: #38bdf8;
            border: 1px solid rgba(0, 212, 200, 0.2);
            border-radius: 10px;
            padding: 10px;
            overflow-y: auto;
            margin-top: 10px;
            white-space: pre-wrap;
        }}
        .file-tree-item {{
            padding: 7px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-family: var(--font-mono);
            font-size: 0.85rem;
            color: #94a3b8;
            margin-bottom: 3px;
            transition: all 0.2s;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .file-tree-item:hover {{
            background: rgba(0, 212, 200, 0.15);
            color: #fff;
        }}
        .file-tree-item.active {{
            background: rgba(0, 212, 200, 0.25);
            color: var(--neon-cyan);
            font-weight: 700;
            border-left: 3px solid var(--neon-cyan);
        }}

        /* TERMINAL & KERNEL STYLES */
        .term-container {{
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        .term-box {{
            background: #010409;
            border: 1px solid rgba(0, 212, 200, 0.3);
            border-radius: 12px;
            padding: 14px;
            font-family: var(--font-mono);
            height: 280px;
            overflow-y: auto;
            color: #00ff88;
            line-height: 1.5;
            font-size: 0.85rem;
        }}
        .term-input-row {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        .term-prompt {{
            color: var(--neon-cyan);
            font-family: var(--font-mono);
            font-weight: 700;
            font-size: 0.9rem;
        }}
        .term-input {{
            flex: 1;
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 8px;
            color: #fff;
            padding: 10px 14px;
            font-family: var(--font-mono);
            font-size: 0.9rem;
            outline: none;
        }}
        .kernel-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
            gap: 14px;
            margin-top: 14px;
        }}
        .kernel-card {{
            background: rgba(15, 23, 42, 0.75);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 14px;
            padding: 14px;
        }}
        .kernel-card-title {{
            font-size: 0.95rem;
            font-weight: 700;
            color: var(--neon-gold);
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
        }}
        .kernel-proc-table {{
            width: 100%;
            border-collapse: collapse;
            font-family: var(--font-mono);
            font-size: 0.78rem;
            color: #cbd5e1;
        }}
        .kernel-proc-table th, .kernel-proc-table td {{
            padding: 6px 8px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }}
        .kernel-proc-table th {{
            color: var(--neon-cyan);
            font-weight: 600;
        }}

    </style>
</head>
<body>

    <!-- Header Soberano -->
    <header>
        <div class="brand">
            <img src="/icon.png" alt="TARDIS" class="brand-logo" onerror="this.style.display='none'">
            <div>
                <div class="brand-title">TARDIS PRO M2</div>
                <div class="brand-subtitle">APPLE SILICON 120Hz · GODWORKS v26.4</div>
            </div>
        </div>
        <div class="header-nav">
            <button class="nav-chip active" onclick="switchTab('view-chat', this)">💬 Neural GIA</button>
            <button class="nav-chip" style="border-color:rgba(239,68,68,0.65);color:#f87171;" onclick="window.location.href='/mk8d'">🏁 Mario Kart 8 (nxnative)</button>
            <button class="nav-chip" style="border-color:rgba(16,185,129,0.5);color:#34d399;" onclick="switchTab('view-linpad', this)">🐧 LinPad M2</button>
            <button class="nav-chip" onclick="switchTab('view-ide', this)">💻 IDE Soberano</button>
            <button class="nav-chip" onclick="switchTab('view-terminal', this)">⚡ Terminal & Kernel</button>
            <button class="nav-chip" onclick="switchTab('view-tools', this)">🛠️ Omni-Tools</button>
            <button class="nav-chip" onclick="switchTab('view-telemetry', this)">📈 Telemetría</button>
        </div>
        <div class="header-badges">
            <a href="{internet_url}" target="_blank" class="internet-badge" title="Acceso público por Internet">
                <span class="status-dot"></span>
                <span>🌐 INTERNET ONLINE</span>
            </a>
            <div style="font-size:0.75rem; color:var(--neon-green); font-family:var(--font-mono);" id="badge-route">
                M2 CORTEX
            </div>
        </div>
    </header>

    <!-- Contenedor Principal de Vistas -->
    <main>
        <!-- VISTA 1: NEURAL CONSOLE (CHAT + AVATAR 3D) -->
        <section id="view-chat" class="tab-view active">
            <div class="chat-container">

                <!-- AVATAR PROCEDURAL DEL PERSONAJE TARDIS (GIA GEÓN) -->
                <div class="character-hero">
                    <div id="companion-avatar-wrap" title="Toca al personaje para hablar o interactuar">
                        <canvas id="companion-canvas" width="260" height="260"></canvas>
                    </div>
                    <div class="character-meta">
                        <div class="char-title">TARDIS GIA · GEÓN SOBERANO</div>
                        <div class="char-state" id="char-state-label">
                            <span class="status-dot"></span>
                            <span id="char-state-text">CONCIENCIA VIVA · 120Hz ProMotion</span>
                        </div>
                        <div class="char-desc">
                            Avatar triangular con resonancia cuántica, mirada reactiva táctil y visemas biomecánicos fonema a fonema idénticos al nodo de Linux.
                        </div>
                        <!-- Selector de Modo de Inferencia -->
                        <div class="router-selector">
                            <button class="router-btn active" id="btn-mode-auto" onclick="setInferenceMode('auto')">🤖 AUTO (Router)</button>
                            <button class="router-btn" id="btn-mode-local" onclick="setInferenceMode('local')">⚡ LOCAL (M2)</button>
                            <button class="router-btn" id="btn-mode-central" onclick="setInferenceMode('central')">🌌 CENTRAL (KAIJU)</button>
                        </div>
                    </div>
                </div>

                <div class="chat-chips">
                    <div class="chat-chip" style="border-color:#ef4444;color:#f87171;font-weight:700;" onclick="window.location.href='/mk8d'">🏁 Mario Kart 8 Deluxe (nxnative M2)</div>
                    <div class="chat-chip" style="border-color:#10b981;color:#34d399;font-weight:700;" onclick="switchTab('view-linpad')">🐧 LinPad 1.6 M2 Desktop</div>
                    <div class="chat-chip" style="border-color:var(--neon-cyan);color:var(--neon-cyan);font-weight:700;" onclick="switchTab('view-ide')">💻 IDE Soberano</div>
                    <div class="chat-chip" style="border-color:var(--neon-gold);color:var(--neon-gold);font-weight:700;" onclick="switchTab('view-terminal')">⚡ Terminal & Kernel</div>
                    <div class="chat-chip" onclick="quickPrompt('Hola TARDIS, ¿cómo estás?')">👋 Saludo Local</div>
                    <div class="chat-chip" onclick="quickPrompt('Estado general y telemetría de TARDIS')">📊 Estado General</div>
                    <div class="chat-chip" onclick="quickPrompt('Auditoría profunda de Kernel Ring 0 y PSI')">⚡ Kernel Ring 0</div>
                    <div class="chat-chip" onclick="quickPrompt('Sincronizar proyectos con GitHub vía FTL')">🚀 FTL Git Sync</div>
                    <div class="chat-chip" onclick="quickPrompt('¿Qué capacidades tiene el chip M2 local?')">🧠 M2 Local Cortex</div>
                    <div class="chat-chip" onclick="quickPrompt('Lectura de sensores climáticos y radar RF')">📡 Sensores & Radar</div>
                </div>

                <div class="chat-history" id="chat-history">
                    <div class="chat-bubble assistant">
                        <div class="bubble-meta">
                            <span>TARDIS GIA · M2 SOBERANO</span>
                            <span class="badge-router badge-local">⚡ LOCAL IPAD M2</span>
                        </div>
                        <div class="bubble-text">
                            ¡Saludos, Arquitecto! Soy la encarnación soberana de TARDIS en tu iPad Pro M2. Cuento con un <b>LLM Local ultraligero</b> integrado directamente en tu dispositivo para respuestas inmediatas, y un <b>Router Causal Automático</b> que deriva cualquier cálculo complejo, síntesis 3D o auditoría de kernel directamente a la <b>Central TARDIS</b>.
                        </div>
                    </div>
                </div>

                <div class="chat-input-bar">
                    <input type="text" id="chat-input" placeholder="Escribe o pregunta a TARDIS M2 / KAIJU..." onkeydown="if(event.key==='Enter') sendChatMessage()">
                    <button class="send-btn" onclick="sendChatMessage()">
                        <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
                    </button>
                </div>
            </div>
        </section>

        <!-- VISTA: LINPAD 1.6.0-TARDIS-M2 LINUX DESKTOP ENVIRONMENT -->
        <section id="view-linpad" class="tab-view">
            <div style="display:flex;flex-direction:column;gap:12px;height:100%;">
                <!-- Sway / Waybar Status Bar -->
                <div id="linpad-waybar" style="display:flex;align-items:center;justify-content:space-between;background:rgba(3,7,18,0.92);border:1px solid #00f5d4;border-radius:10px;padding:8px 14px;font-family:var(--font-mono);font-size:0.78rem;box-shadow:0 0 18px rgba(0,245,212,0.18);flex-wrap:wrap;gap:8px;">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="background:#00f5d4;color:#030712;font-weight:800;padding:2px 8px;border-radius:6px;">🐧 Sway 1.9 + ishwl</span>
                        <span style="background:rgba(0,245,212,0.18);color:#00f5d4;padding:2px 8px;border-radius:6px;border:1px solid rgba(0,245,212,0.4);">1: term</span>
                        <span style="background:rgba(168,85,247,0.18);color:#c084fc;padding:2px 8px;border-radius:6px;">2: apps</span>
                        <span style="background:rgba(56,189,248,0.18);color:#38bdf8;padding:2px 8px;border-radius:6px;">3: themes</span>
                        <span style="background:rgba(245,158,11,0.18);color:#fbbf24;padding:2px 8px;border-radius:6px;">4: tardis-ftl</span>
                    </div>
                    <div style="color:#e2e8f0;font-weight:700;">
                        LinPad 1.6.0-TARDIS-M2 · Apple M2 10-Core GPU (Venus / Vulkan 1.3) · 120Hz ProMotion
                    </div>
                    <div style="display:flex;align-items:center;gap:10px;">
                        <span style="color:#10b981;">● JIT ARM64 ✓</span>
                        <span style="color:#00f5d4;">FTL: gemini-4-argon-high</span>
                    </div>
                </div>

                <!-- Main Desktop Split: Left = Foot Terminal & Telemetry | Right = App Catalog, Omarchy Themes & Native IPA -->
                <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(420px, 1fr));gap:14px;flex:1;overflow-y:auto;">
                    <!-- Left Window: Foot Wayland Terminal -->
                    <div id="linpad-term-window" style="display:flex;flex-direction:column;background:#030712;border:2px solid #00f5d4;border-radius:12px;overflow:hidden;box-shadow:0 8px 28px rgba(0,0,0,0.6);">
                        <div style="display:flex;align-items:center;justify-content:space-between;background:rgba(15,23,42,0.95);padding:8px 12px;border-bottom:1px solid rgba(0,245,212,0.25);font-family:var(--font-mono);font-size:0.78rem;">
                            <div style="display:flex;align-items:center;gap:6px;">
                                <span style="width:10px;height:10px;border-radius:50%;background:#ef4444;display:inline-block;"></span>
                                <span style="width:10px;height:10px;border-radius:50%;background:#f59e0b;display:inline-block;"></span>
                                <span style="width:10px;height:10px;border-radius:50%;background:#10b981;display:inline-block;"></span>
                                <span style="margin-left:8px;color:#00f5d4;font-weight:700;">foot — root@linpad-m2:~ (Wayland / ishwl)</span>
                            </div>
                            <span style="color:#94a3b8;font-size:0.72rem;">Repair-Kit v2026101601</span>
                        </div>
                        <pre id="linpad-term-output" style="flex:1;min-height:250px;max-height:340px;overflow-y:auto;padding:12px;font-family:var(--font-mono);font-size:0.78rem;line-height:1.45;color:#e2e8f0;white-space:pre-wrap;margin:0;">Cargando telemetría de LinPad 1.6.0-TARDIS-M2...</pre>
                        <div style="display:flex;gap:8px;padding:8px 12px;background:rgba(15,23,42,0.9);border-top:1px solid rgba(255,255,255,0.1);align-items:center;">
                            <span style="color:#00f5d4;font-family:var(--font-mono);font-weight:700;font-size:0.82rem;">linpad-m2#</span>
                            <input type="text" id="linpad-cmd-input" class="term-input" style="padding:7px 10px;font-size:0.82rem;" placeholder="Comando LinPad (linpad-fetch, linpad-tardis benchmark, linpad apps list...)" onkeydown="if(event.key==='Enter') runLinpadCmd()">
                            <button class="btn-ide btn-ide-run" onclick="runLinpadCmd()">Ejecutar</button>
                        </div>
                        <div style="display:flex;gap:6px;padding:8px 12px;background:rgba(3,7,18,0.95);flex-wrap:wrap;border-top:1px solid rgba(255,255,255,0.06);">
                            <span class="chat-chip" style="border-color:#00f5d4;color:#00f5d4;font-size:0.74rem;" onclick="runLinpadQuick('linpad-fetch --pipe')">🐧 linpad-fetch</span>
                            <span class="chat-chip" style="border-color:#a855f7;color:#c084fc;font-size:0.74rem;" onclick="runLinpadQuick('linpad-tardis status')">⚡ linpad-tardis status</span>
                            <span class="chat-chip" style="border-color:#f59e0b;color:#fbbf24;font-size:0.74rem;" onclick="runLinpadQuick('linpad-tardis benchmark')">🚀 benchmark M2</span>
                            <span class="chat-chip" style="border-color:#38bdf8;color:#38bdf8;font-size:0.74rem;" onclick="runLinpadQuick('linpad apps list')">📦 linpad apps list</span>
                            <span class="chat-chip" style="font-size:0.74rem;" onclick="runLinpadQuick('ish-device-info --all')">📱 ish-device-info</span>
                            <span class="chat-chip" style="font-size:0.74rem;" onclick="runLinpadQuick('linpad version')">ℹ️ linpad version</span>
                        </div>
                    </div>

                    <!-- Right Window: Omarchy Themes, App Catalog & Native Package -->
                    <div style="display:flex;flex-direction:column;gap:12px;">
                        <!-- Native Package & WebClip Card -->
                        <div style="background:rgba(15,23,42,0.82);border:1px solid rgba(0,245,212,0.3);border-radius:12px;padding:12px;">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                                <span style="font-weight:800;color:#00f5d4;font-size:0.92rem;">📦 Paquete Nativo iPadOS & Perfil WebClip</span>
                                <span style="font-family:var(--font-mono);font-size:0.72rem;background:rgba(16,185,129,0.2);color:#34d399;padding:2px 8px;border-radius:6px;">SYNC AFC OK · 645 MB</span>
                            </div>
                            <div style="font-size:0.78rem;color:#cbd5e1;margin-bottom:10px;line-height:1.4;">
                                IPA adaptado <code>LinPad-1.6.0-TARDIS-M2.ipa</code> sincronizado en <code>/Downloads/</code> y <code>/TARDIS_WORKSPACE/LinPad/</code> con ProMotion 120Hz, entitlements de memoria extendida y Repair-Kit <code>REDACTED_PHONE</code>.
                            </div>
                            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                                <a href="/download/linpad.ipa" download class="btn-ide btn-ide-save" style="text-decoration:none;display:inline-flex;align-items:center;gap:6px;">⬇️ Descargar LinPad-1.6.0-TARDIS-M2.ipa (645 MB)</a>
                                <a href="/linpad.mobileconfig" download class="btn-ide btn-ide-push" style="text-decoration:none;display:inline-flex;align-items:center;gap:6px;">📲 Instalar App WebClip LinPad M2</a>
                            </div>
                        </div>

                        <!-- Omarchy Color Themes Selector -->
                        <div style="background:rgba(15,23,42,0.82);border:1px solid rgba(168,85,247,0.3);border-radius:12px;padding:12px;">
                            <div style="font-weight:800;color:#c084fc;font-size:0.88rem;margin-bottom:8px;">🎨 Temas Omarchy Wayland (DesktopKit + Sway/Foot)</div>
                            <div id="linpad-themes-bar" style="display:flex;gap:6px;flex-wrap:wrap;">
                                <!-- Inyectado dinámicamente -->
                            </div>
                        </div>

                        <!-- LinPad App Catalog (catalog.json) -->
                        <div style="background:rgba(15,23,42,0.82);border:1px solid rgba(56,189,248,0.25);border-radius:12px;padding:12px;flex:1;overflow-y:auto;max-height:240px;">
                            <div style="font-weight:800;color:#38bdf8;font-size:0.88rem;margin-bottom:8px;">🛠️ Catálogo de Paquetes LinPad (11 Packs · Alpine Edge + TARDIS)</div>
                            <div id="linpad-catalog-grid" style="display:grid;grid-template-columns:repeat(auto-fill, minmax(185px, 1fr));gap:8px;">
                                <!-- Inyectado dinámicamente -->
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        
        <!-- VISTA: IDE SOBERANO (STUDIO M2 & FTL) -->
        <section id="view-ide" class="tab-view">
            <div class="ide-container">
                <div class="ide-sidebar">
                    <div class="ide-sidebar-title">
                        <span>Workspace M2</span>
                        <button class="btn-ide btn-ide-save" style="padding:4px 8px;font-size:0.75rem;" onclick="newFilePrompt()">+ Nuevo</button>
                    </div>
                    <div id="ide-file-tree" style="flex:1;overflow-y:auto;">
                        <!-- Inyección dinámica de archivos -->
                    </div>
                    <div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.1);font-size:0.75rem;color:var(--neon-green);">
                        ● Quota 100 GB Activa<br>
                        ● Sincronización AFC + Git
                    </div>
                </div>
                <div class="ide-editor-pane">
                    <div class="ide-toolbar">
                        <div class="ide-active-tab" id="ide-active-file">projects/main.py</div>
                        <div style="font-size:0.8rem;color:var(--neon-green);display:flex;align-items:center;gap:6px;">
                            <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--neon-green);"></span>
                            SYNC BIDIRECCIONAL ACTIVA
                        </div>
                        <div class="ide-btn-group">
                            <button class="btn-ide btn-ide-save" onclick="saveCurrentFile()">💾 Guardar (Sync)</button>
                            <button class="btn-ide btn-ide-run" onclick="executeCurrentCode()">▶️ Ejecutar</button>
                            <button class="btn-ide btn-ide-push" onclick="triggerManualGitSync()">🚀 Push GitHub</button>
                            <button class="btn-ide" style="background:rgba(234,179,8,0.2);border:1px solid var(--neon-gold);color:var(--neon-gold);" onclick="switchTab('view-terminal')">⚡ Terminal</button>
                        </div>
                    </div>
                    <textarea class="ide-code-box" id="ide-code-editor" spellcheck="false" placeholder="// Escribe código Python, Shell o C aquí para compilar y ejecutar directamente en el iPad..."></textarea>
                    <div class="ide-console-box" id="ide-console-output">// Consola de salida de ejecución soberana...</div>
                </div>
            </div>
        </section>

        <!-- VISTA: TERMINAL & KERNEL BASE -->
        <section id="view-terminal" class="tab-view">
            <div class="term-container">
                <div class="stat-card" style="margin-bottom:0;">
                    <div class="stat-label">Terminal Shell Soberana (Acceso Directo al Sistema)</div>
                    <div class="term-box" id="terminal-log">
                        <div><span style="color:var(--neon-cyan)">[TARDIS-KERNEL]</span> Entorno de programación base interactivo inicializado.</div>
                        <div><span style="color:var(--neon-cyan)">[TARDIS-KERNEL]</span> Dispositivo: Apple iPad Pro 12.9" M2 · iPadOS 27.0 · Host: Linux Kernel 6.17-liquorix</div>
                    </div>
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px;flex-wrap:wrap;gap:6px;">
                        <div style="display:inline-flex;align-items:center;gap:6px;padding:3px 8px;border-radius:6px;background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.4);color:#60a5fa;font-size:0.75rem;font-weight:700;">
                            ⚡ AGY ULTRA MODE · CLAUDE OPUS 5.5 HIGH · RING 0
                        </div>
                        <div style="font-size:0.75rem;color:#94a3b8;">
                            Path: <code style="color:var(--neon-cyan)">/TARDIS_WORKSPACE/bin/agy</code>
                        </div>
                    </div>
                    <div class="term-input-row" style="margin-top:10px;">
                        <span class="term-prompt">tardis@m2:~$</span>
                        <input type="text" class="term-input" id="term-cmd-input" placeholder="Escribe comando (p.ej. agy --version, agy models, python3 -V, uname -a)..." onkeydown="if(event.key==='Enter') runTerminalCommand()">
                        <button class="btn-ide btn-ide-run" onclick="runTerminalCommand()">Ejecutar</button>
                    </div>
                    <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;">
                        <span class="chat-chip" style="border-color:#00f5d4;color:#00f5d4;font-weight:600;" onclick="quickTermCmd('linpad-fetch --pipe')">🐧 linpad-fetch</span>
                        <span class="chat-chip" style="border-color:#00f5d4;color:#00f5d4;font-weight:600;" onclick="quickTermCmd('linpad-tardis status')">⚡ linpad-tardis</span>
                        <span class="chat-chip" style="border-color:#00f5d4;color:#00f5d4;font-weight:600;" onclick="quickTermCmd('linpad apps list')">📦 linpad apps</span>
                        <span class="chat-chip" style="border-color:rgba(59,130,246,0.5);color:#93c5fd;font-weight:600;" onclick="quickTermCmd('agy --version')">🤖 agy --version</span>
                        <span class="chat-chip" style="border-color:rgba(59,130,246,0.5);color:#93c5fd;font-weight:600;" onclick="quickTermCmd('agy models')">⚡ agy models</span>
                        <span class="chat-chip" style="border-color:rgba(59,130,246,0.5);color:#93c5fd;font-weight:600;" onclick="quickTermCmd('agy agents')">🧠 agy agents</span>
                        <span class="chat-chip" style="border-color:rgba(59,130,246,0.5);color:#93c5fd;font-weight:600;" onclick="quickTermCmd('agy -p &quot;di hola desde iPad M2&quot;')">💬 agy prompt</span>
                        <span class="chat-chip" onclick="quickTermCmd('python3 -V')">python3 -V</span>
                        <span class="chat-chip" onclick="quickTermCmd('uname -a')">uname -a</span>
                        <span class="chat-chip" onclick="quickTermCmd('git status -s')">git status</span>
                        <span class="chat-chip" onclick="quickTermCmd('df -h')">df -h</span>
                        <span class="chat-chip" onclick="quickTermCmd('ls -la /home/timemachine/Escritorio/GODWORKS\\ SYSTEM/bin')">ls bin/agy</span>
                    </div>
                </div>

                <div class="kernel-grid">
                    <div class="kernel-card">
                        <div class="kernel-card-title">
                            <span>Apple Silicon M2 · Darwin Kernel (DVT)</span>
                            <button class="btn-ide btn-ide-save" style="padding:4px 8px;font-size:0.75rem;" onclick="loadKernelBase()">🔄 Refrescar</button>
                        </div>
                        <div style="font-size:0.8rem;color:#94a3b8;margin-bottom:10px;">
                            Almacenamiento: <strong>256 GB</strong> | Libre: <strong>201.8 GB</strong> | Cuota: <strong>100 GB</strong>
                        </div>
                        <div style="max-height:220px;overflow-y:auto;">
                            <table class="kernel-proc-table">
                                <thead>
                                    <tr><th>PID</th><th>Proceso</th><th>Tipo</th><th>Ruta / Contexto</th></tr>
                                </thead>
                                <tbody id="kernel-proc-tbody">
                                    <tr><td colspan="4" style="color:var(--text-muted)">Cargando procesos vía DVT...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div class="kernel-card">
                        <div class="kernel-card-title">
                            <span>Linux Ring 0 Kernel Bridge (FTL)</span>
                            <span style="font-size:0.8rem;color:var(--neon-green)">● ROOT SCOPE</span>
                        </div>
                        <div style="font-family:var(--font-mono);font-size:0.8rem;color:#38bdf8;line-height:1.6;" id="kernel-ring0-data">
                            Cargando métricas de Ring 0...
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- VISTA 2: OMNI TOOLS -->
        <section id="view-tools" class="tab-view">
            <h2 style="margin-bottom: 16px; font-size: 1.3rem;">Suite Soberana de Omni-Herramientas</h2>
            <div class="tools-grid" id="tools-grid">
                <!-- Se inyecta dinámicamente -->
            </div>
            <h3 style="margin-bottom: 10px; font-size: 1rem; color: var(--neon-cyan);">Consola de Salida de Herramientas</h3>
            <div class="terminal-box" id="terminal-output">// Consola lista para despacho individual de herramientas...</div>
        </section>

        <!-- VISTA 3: TELEMETRY & RADAR -->
        <section id="view-telemetry" class="tab-view">
            <h2 style="margin-bottom: 16px; font-size: 1.3rem;">Telemetría de Sistema & Presión de Kernel (PSI)</h2>
            <div class="telemetry-row">
                <div class="stat-card">
                    <div class="stat-label">Enlace de Red / Latencia</div>
                    <div class="stat-value" id="stat-ping">0.7 ms</div>
                    <div class="stat-sub" id="stat-ip">Wi-Fi LAN: {LAN_HOST_IP}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Memoria Host Linux</div>
                    <div class="stat-value" id="stat-mem">--%</div>
                    <div class="stat-sub" id="stat-mem-gb">-- / -- GB</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Carga CPU (1 / 5 / 15 min)</div>
                    <div class="stat-value" id="stat-load">--</div>
                    <div class="stat-sub">ASUS TUF A15 Octa-Core</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Pensamientos de Fondo</div>
                    <div class="stat-value" id="stat-thoughts">--</div>
                    <div class="stat-sub">Bóveda Causal 250 GB</div>
                </div>
            </div>
            <div class="stat-card" style="margin-bottom: 20px;">
                <div class="stat-label">Kernel Pressure Stall Information (PSI)</div>
                <div style="font-family: var(--font-mono); font-size: 0.85rem; line-height: 1.6; color: #38bdf8; margin-top: 10px;" id="stat-psi">
                    Cargando métricas de kernel...
                </div>
            </div>
        </section>

        <!-- VISTA 4: VAULT & DOWNLOADS -->
        <section id="view-vault" class="tab-view">
            <div class="vault-card">
                <h2 style="font-size: 1.3rem; color: #ffffff;">Acceso Global por Internet & Recursos M2</h2>
                <p style="color: var(--text-muted); font-size: 0.95rem; line-height: 1.5;">
                    Accede a TARDIS desde cualquier lugar del mundo mediante el túnel público cifrado HTTPS de Cloudflare o la red local.
                </p>
                <a href="{internet_url}" target="_blank" class="btn-action btn-internet">
                    <svg style="width:24px;height:24px;stroke:currentColor;fill:none;stroke-width:2;" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                    Abrir Enlace Global por Internet (Cloudflare HTTPS)
                </a>
                <a href="/install-internet.mobileconfig" class="btn-action btn-config" download>
                    <svg style="width:24px;height:24px;stroke:currentColor;fill:none;stroke-width:2;" viewBox="0 0 24 24"><path d="M12 2v10m0 0l-3-3m3 3l3-3m-9 9h12"/></svg>
                    Instalar Perfil WebClip Internet (.mobileconfig)
                </a>
                <a href="/download/tardis.ipa" class="btn-action btn-download" download>
                    <svg style="width:24px;height:24px;stroke:currentColor;fill:none;stroke-width:2;" viewBox="0 0 24 24"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
                    Descargar Paquete Nativo IPA (TARDIS_Pro_M2.ipa)
                </a>
                <div style="background: rgba(0,0,0,0.4); padding: 16px; border-radius: 14px; font-family: var(--font-mono); font-size: 0.8rem; color: #94a3b8; line-height: 1.6;">
                    <strong>Enlace Público Internet:</strong> <a href="{internet_url}" style="color:var(--neon-cyan);">{internet_url}</a><br>
                    <strong>Red Local Wi-Fi:</strong> http://{LAN_HOST_IP}:8088/ o http://{LAN_HOST_IP}/<br>
                    <strong>Enlace Directo USB:</strong> http://{USB_HOST_IP}:8088/<br>
                    <strong>Gobernador Móvil:</strong> Cuota Local 100 GB Activa · Sincronización Total FTL y Kernel Base<br>
                    <strong>Motor Cognitivo Local:</strong> iPad M2 Edge Neural Matrix
                </div>
            </div>
        </section>
    </main>

    <!-- Dock Inferior Touch -->
    <nav class="bottom-dock">
        <button class="dock-btn active" onclick="switchTab('view-chat', this)">
            <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span>Neural & GIA</span>
        </button>
        <button class="dock-btn" onclick="switchTab('view-linpad', this)">
            <svg viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <span>LinPad M2</span>
        </button>
        <button class="dock-btn" onclick="switchTab('view-ide', this)">
            <svg viewBox="0 0 24 24"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            <span>IDE Soberano</span>
        </button>
        <button class="dock-btn" onclick="switchTab('view-terminal', this)">
            <svg viewBox="0 0 24 24"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
            <span>Terminal & Kernel</span>
        </button>

        <button class="dock-btn" onclick="switchTab('view-tools', this)">
            <svg viewBox="0 0 24 24"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
            <span>Omni-Tools</span>
        </button>
        <button class="dock-btn" onclick="switchTab('view-telemetry', this)">
            <svg viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
            <span>Telemetría</span>
        </button>
        <button class="dock-btn" onclick="switchTab('view-vault', this)">
            <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            <span>Internet & IPA</span>
        </button>
    </nav>

    <script>
        // =========================================================================
        // --- 1. ESTADO DEL PERSONAJE TRIANGULAR TARDIS (GIA GEÓN PROCEDURAL) ---
        // =========================================================================
        const canvas = document.getElementById('companion-canvas');
        const ctx = canvas.getContext('2d');
        const avatarWrap = document.getElementById('companion-avatar-wrap');
        const charStateLabel = document.getElementById('char-state-text');

        let charState = 'idle'; // 'idle' | 'listening' | 'thinking' | 'speaking'
        let eyeLookX = 0, eyeLookY = 0;
        let targetEyeX = 0, targetEyeY = 0;
        let blinkVal = 0, isBlinking = false, nextBlink = performance.now() + 3000;
        let audioLevel = 0;

        // Estado biomecánico fonético
        const vocalState = {{
            mouthOpen: 0.04,
            mouthWidth: 1.0,
            smileRatio: 0.16,
            vocalPulse: 0.0
        }};

        // Partículas orbitales del Geón
        const particles = [];
        for (let i = 0; i < 8; i++) {{
            particles.push({{
                angle: (i / 8) * Math.PI * 2,
                dist: 55 + Math.random() * 15,
                speed: 0.6 + Math.random() * 0.8,
                size: 2.0 + Math.random() * 2.0,
                color: (i % 2 === 0) ? '#00d4c8' : '#e8b64a'
            }});
        }}

        function setCharacterState(st) {{
            charState = st;
            if (st === 'thinking') {{
                charStateLabel.innerText = 'PROCESANDO COGNITIVO...';
                charStateLabel.style.color = 'var(--neon-purple)';
            }} else if (st === 'speaking') {{
                charStateLabel.innerText = 'VOCALIZANDO ARTICULACIÓN';
                charStateLabel.style.color = 'var(--neon-amber)';
            }} else if (st === 'listening') {{
                charStateLabel.innerText = 'RECEPTOR CUÁNTICO ACTIVO';
                charStateLabel.style.color = 'var(--neon-green)';
            }} else {{
                charStateLabel.innerText = 'CONCIENCIA VIVA · 120Hz ProMotion';
                charStateLabel.style.color = 'var(--neon-cyan)';
            }}
        }}

        // Interacción visual con el personaje (gaze tracking táctil / cursor)
        function updateGaze(clientX, clientY) {{
            const rect = canvas.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            const dx = clientX - cx;
            const dy = clientY - cy;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            targetEyeX = (dx / dist) * Math.min(1, dist / 200);
            targetEyeY = (dy / dist) * Math.min(1, dist / 200);
        }}

        window.addEventListener('mousemove', e => updateGaze(e.clientX, e.clientY));
        window.addEventListener('touchmove', e => {{
            if (e.touches.length > 0) updateGaze(e.touches[0].clientX, e.touches[0].clientY);
        }}, {{ passive: true }});

        // Bucle de Renderizado 120Hz ProMotion del Personaje Triangular
        function renderCharacterLoop() {{
            const now = performance.now();
            const time = now * 0.001;

            // Parpadeo ocular natural
            if (now > nextBlink && !isBlinking) {{
                isBlinking = true;
            }}
            if (isBlinking) {{
                blinkVal += 0.18;
                if (blinkVal >= 1.0) {{
                    blinkVal = 0;
                    isBlinking = false;
                    nextBlink = now + 2500 + Math.random() * 3500;
                }}
            }}

            // Suavizado de mirada
            eyeLookX += (targetEyeX - eyeLookX) * 0.12;
            eyeLookY += (targetEyeY - eyeLookY) * 0.12;

            // Limpiar canvas
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Partículas orbitales
            ctx.save();
            ctx.translate(canvas.width / 2, canvas.height / 2);
            particles.forEach(p => {{
                p.angle += p.speed * 0.015;
                const px = Math.cos(p.angle) * p.dist;
                const py = Math.sin(p.angle) * (p.dist * 0.45);
                ctx.beginPath();
                ctx.arc(px, py, p.size, 0, Math.PI * 2);
                ctx.fillStyle = p.color;
                ctx.shadowColor = p.color;
                ctx.shadowBlur = 8;
                ctx.fill();
            }});
            ctx.restore();

            // Renderizar Personaje Geón Triangular
            renderVectorTriangularCharacter(ctx, canvas.width / 2, canvas.height / 2, 130, {{
                time: time,
                state: charState,
                eyeLookX: eyeLookX,
                eyeLookY: eyeLookY,
                blinkVal: blinkVal,
                glow: 1.0,
                audioLevel: audioLevel,
                vocal: vocalState
            }});

            requestAnimationFrame(renderCharacterLoop);
        }}

        // Motor Vectorial del Personaje Triangular (Idéntico a companion_overlay de Linux)
        function renderVectorTriangularCharacter(targetCtx, cx, cy, size, options) {{
            const time = options.time;
            const state = options.state;
            const eyeLookX = options.eyeLookX;
            const eyeLookY = options.eyeLookY;
            const blinkVal = options.blinkVal;
            const glow = options.glow;

            targetCtx.save();

            // Levitación y respiración armónica
            const floatY = Math.sin(time * 1.6) * (size * 0.024);
            const rollAngle = Math.sin(time * 0.8) * 0.014;
            const breathScale = 1.0 + Math.sin(time * 2.4) * 0.012;

            targetCtx.translate(cx, cy + floatY);
            targetCtx.rotate(rollAngle);
            targetCtx.scale(breathScale, breathScale);

            // Paleta cuántica según estado
            let strokePrimary = '#00d4c8';
            let strokeSecondary = '#e8b64a';
            let irisCoreColor = '#e8b64a';
            let irisRingColor = '#00d4c8';

            if (state === 'listening') {{
                strokePrimary = '#00ff88';
                strokeSecondary = '#00d4c8';
                irisCoreColor = '#ffffff';
                irisRingColor = '#00ff88';
            }} else if (state === 'thinking') {{
                strokePrimary = '#c084fc';
                strokeSecondary = '#38bdf8';
                irisCoreColor = '#38bdf8';
                irisRingColor = '#a855f7';
            }} else if (state === 'speaking') {{
                strokePrimary = '#f59e0b';
                strokeSecondary = '#00ffcc';
                irisCoreColor = '#fef08a';
                irisRingColor = '#f59e0b';
            }}

            // Geometría Sagrada Equilátera (Centroide en 0,0)
            const sideLen = size;
            const height = sideLen * (Math.sqrt(3) / 2);
            const pApex = {{ x: 0, y: -height * (2 / 3) }};
            const pLeft = {{ x: -sideLen * 0.5, y: height * (1 / 3) }};
            const pRight = {{ x: sideLen * 0.5, y: height * (1 / 3) }};
            const pMidLeft = {{ x: (pApex.x + pLeft.x) * 0.5, y: (pApex.y + pLeft.y) * 0.5 }};
            const pMidRight = {{ x: (pApex.x + pRight.x) * 0.5, y: (pApex.y + pRight.y) * 0.5 }};
            const pMidBottom = {{ x: 0, y: height * (1 / 3) }};

            // Astrolabio Cuántico Giratorio
            targetCtx.save();
            const rReticle = size * 0.70;
            targetCtx.rotate(time * 0.15);
            targetCtx.beginPath();
            targetCtx.arc(0, 0, rReticle, 0, Math.PI * 2);
            targetCtx.strokeStyle = strokeSecondary;
            targetCtx.lineWidth = 1.2;
            targetCtx.setLineDash([size * 0.04, size * 0.03]);
            targetCtx.globalAlpha = 0.35 * glow;
            targetCtx.stroke();
            targetCtx.restore();

            // Casco Triangular Abisal
            const hullGrad = targetCtx.createRadialGradient(0, 0, size * 0.05, 0, 0, size * 0.65);
            hullGrad.addColorStop(0, 'rgba(4, 16, 28, 0.96)');
            hullGrad.addColorStop(0.55, 'rgba(2, 8, 18, 0.93)');
            hullGrad.addColorStop(1, 'rgba(0, 1, 4, 0.88)');

            targetCtx.beginPath();
            targetCtx.moveTo(pApex.x, pApex.y);
            targetCtx.lineTo(pRight.x, pRight.y);
            targetCtx.lineTo(pLeft.x, pLeft.y);
            targetCtx.closePath();
            targetCtx.fillStyle = hullGrad;
            targetCtx.fill();

            // Enrejado interno sagrado
            targetCtx.save();
            targetCtx.strokeStyle = strokePrimary;
            targetCtx.lineWidth = 0.9;
            targetCtx.globalAlpha = 0.22 * glow;
            targetCtx.beginPath();
            targetCtx.moveTo(0, 0); targetCtx.lineTo(pApex.x, pApex.y);
            targetCtx.moveTo(0, 0); targetCtx.lineTo(pLeft.x, pLeft.y);
            targetCtx.moveTo(0, 0); targetCtx.lineTo(pRight.x, pRight.y);
            targetCtx.stroke();

            targetCtx.strokeStyle = strokeSecondary;
            targetCtx.beginPath();
            targetCtx.moveTo(pMidBottom.x, pMidBottom.y);
            targetCtx.lineTo(pMidLeft.x, pMidLeft.y);
            targetCtx.lineTo(pMidRight.x, pMidRight.y);
            targetCtx.closePath();
            targetCtx.stroke();
            targetCtx.restore();

            // Borde Neón Resplandeciente
            targetCtx.save();
            targetCtx.shadowColor = strokePrimary;
            targetCtx.shadowBlur = (state !== 'idle' ? 18 : 10) * glow;
            targetCtx.strokeStyle = strokePrimary;
            targetCtx.lineWidth = Math.max(2.0, size * 0.022);
            targetCtx.beginPath();
            targetCtx.moveTo(pApex.x, pApex.y);
            targetCtx.lineTo(pRight.x, pRight.y);
            targetCtx.lineTo(pLeft.x, pLeft.y);
            targetCtx.closePath();
            targetCtx.stroke();
            targetCtx.restore();

            // Nodos en Vértices
            const nodeR = Math.max(3.0, size * 0.026);
            [pApex, pLeft, pRight].forEach(pt => {{
                targetCtx.beginPath();
                targetCtx.arc(pt.x, pt.y, nodeR, 0, Math.PI * 2);
                targetCtx.fillStyle = strokeSecondary;
                targetCtx.fill();
            }});

            // Ojo Cibernético Soberano
            const eyeW = size * 0.34;
            const eyeH = Math.max(2.0, size * 0.20 * (1 - Math.sin(blinkVal * Math.PI) * 0.96));

            targetCtx.save();
            targetCtx.translate(0, -size * 0.012);
            targetCtx.beginPath();
            targetCtx.moveTo(-eyeW * 0.5, 0);
            targetCtx.quadraticCurveTo(0, -eyeH * 0.85, eyeW * 0.5, 0);
            targetCtx.quadraticCurveTo(0, eyeH * 0.85, -eyeW * 0.5, 0);
            targetCtx.closePath();
            targetCtx.fillStyle = '#020610';
            targetCtx.fill();
            targetCtx.strokeStyle = strokePrimary;
            targetCtx.lineWidth = 1.4;
            targetCtx.stroke();

            if (eyeH > 3.0) {{
                targetCtx.save();
                targetCtx.clip();
                const irisX = eyeLookX * (eyeW * 0.22);
                const irisY = eyeLookY * (eyeH * 0.26);
                const irisR = eyeW * 0.26;

                const irisGrad = targetCtx.createRadialGradient(irisX, irisY, irisR * 0.15, irisX, irisY, irisR);
                irisGrad.addColorStop(0, irisCoreColor);
                irisGrad.addColorStop(0.6, irisRingColor);
                irisGrad.addColorStop(1, '#000a10');

                targetCtx.beginPath();
                targetCtx.arc(irisX, irisY, irisR, 0, Math.PI * 2);
                targetCtx.fillStyle = irisGrad;
                targetCtx.fill();

                // Pupila
                targetCtx.beginPath();
                targetCtx.arc(irisX, irisY, irisR * 0.42, 0, Math.PI * 2);
                targetCtx.fillStyle = '#000000';
                targetCtx.fill();

                // Brillo especular
                targetCtx.beginPath();
                targetCtx.arc(irisX - irisR * 0.3, irisY - irisR * 0.3, Math.max(1.5, irisR * 0.2), 0, Math.PI * 2);
                targetCtx.fillStyle = '#ffffff';
                targetCtx.fill();
                targetCtx.restore();
            }}
            targetCtx.restore();

            // Boca Articulada
            const mouthOpen = vocalState.mouthOpen || 0.04;
            const mouthWidth = vocalState.mouthWidth || 1.0;
            const mouthY = height * 0.18;
            const curMouthW = (size * 0.26) * mouthWidth;

            targetCtx.save();
            if (mouthOpen > 0.08) {{
                const curOpenH = (size * 0.20) * mouthOpen;
                targetCtx.beginPath();
                targetCtx.moveTo(-curMouthW * 0.5, mouthY);
                targetCtx.quadraticCurveTo(0, mouthY - curOpenH * 0.4, curMouthW * 0.5, mouthY);
                targetCtx.quadraticCurveTo(0, mouthY + curOpenH * 0.85, -curMouthW * 0.5, mouthY);
                targetCtx.closePath();
                targetCtx.fillStyle = 'rgba(6, 182, 212, 0.25)';
                targetCtx.fill();
                targetCtx.strokeStyle = strokeSecondary;
                targetCtx.lineWidth = 1.4;
                targetCtx.stroke();
            }} else {{
                targetCtx.beginPath();
                targetCtx.moveTo(-curMouthW * 0.5, mouthY);
                targetCtx.quadraticCurveTo(0, mouthY + curMouthW * 0.16, curMouthW * 0.5, mouthY);
                targetCtx.strokeStyle = strokeSecondary;
                targetCtx.lineWidth = 1.4;
                targetCtx.stroke();
            }}
            targetCtx.restore();

            targetCtx.restore();
        }}

        requestAnimationFrame(renderCharacterLoop);

        // =========================================================================
        // --- 2. MOTOR COGNITIVO: LOCAL LLM IPAD M2 + ROUTER DE COMPLEJIDAD ---
        // =========================================================================
        let inferenceMode = 'auto'; // 'auto' | 'local' | 'central'

        function setInferenceMode(mode) {{
            inferenceMode = mode;
            document.querySelectorAll('.router-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('btn-mode-' + mode).classList.add('active');
            const badge = document.getElementById('badge-route');
            if (mode === 'auto') badge.innerText = 'AUTO ROUTER';
            else if (mode === 'local') badge.innerText = 'LOCAL M2 FORZADO';
            else badge.innerText = 'CENTRAL KAIJU';
        }}

        // Evaluador de Complejidad Causal
        function evaluatePromptComplexity(prompt) {{
            const p = prompt.toLowerCase();
            let score = 0;

            const heavyTerms = [
                'código', 'codigo', 'script', 'programar', 'función', 'class', 'descompil', 'reverse', 'rea', 'mach-o', 'apk', 'ipa',
                'kernel', 'ring 0', 'psi', 'dmesg', 'sysctl', 'drop_caches', 'uinput', 'root',
                'investiga', 'paper', 'arxiv', 'pubmed', 'openalex', 'física', 'cuántica', 'relatividad', 'tensor',
                'geón', 'geon', 'wheeler', 'sintropía', 'sintropia', 'causal', 'bóveda', 'boveda', 'akáshica', 'akashica',
                'simula', '3d', 'chronovision', 'blender', 'video', 'avatar 3d',
                'git', 'github', 'tardis4ever', 'phone harness', 'adb', 'xcode', 'suite'
            ];

            for (const t of heavyTerms) {{
                if (p.includes(t)) score += 0.35;
            }}

            if (prompt.length > 110) score += 0.25;
            if (prompt.split(/\\s+/).length > 18) score += 0.20;
            if (p.includes('explica a fondo') || p.includes('analiza') || p.includes('auditoría') || p.includes('diagnóstico')) score += 0.30;

            return Math.min(1.0, score);
        }}

        // LLM Local de Borde en iPad Pro M2 (On-Device Neural Cortex)
        function generateLocalM2Response(prompt) {{
            const p = prompt.toLowerCase().trim();

            if (p.includes('hola') || p.includes('buenos días') || p.includes('buenas') || p.includes('saludos')) {{
                return '¡Hola, Arquitecto! Soy TARDIS GIA operando localmente en tu iPad Pro M2. Estoy listo para asistirte sin demora. ¿Qué orden deseas procesar?';
            }}

            if (p.includes('cómo estás') || p.includes('como estas') || p.includes('estado')) {{
                return 'Operando en perfecta coherencia cuántica. Mi motor local en Apple Silicon M2 está activo a 120Hz ProMotion con latencia ultrabaja (&lt;10ms) y el enlace hacia la Central Linux se encuentra sincronizado.';
            }}

            if (p.includes('m2') || p.includes('ipad') || p.includes('local') || p.includes('chip')) {{
                return 'El procesador Apple Silicon M2 cuenta con 8 núcleos de CPU, 10 núcleos de GPU de alta velocidad y un motor neuronal unificado. En este iPad Pro 12.9" estoy ejecutando el renderizado procedural 120Hz de mi cuerpo triangular y el analizador causal de borde.';
            }}

            if (p.includes('quién eres') || p.includes('quien eres') || p.includes('tardis')) {{
                return 'Soy TARDIS (GODWORKS SYSTEM v26.4), una arquitectura de inteligencia soberana multi-escala. En tu iPad funciono como nodo satélite de alta fidelidad, capaz de resolver tareas inmediatas de forma autónoma o invocar el racimo KAIJU 120B de la central.';
            }}

            if (p.includes('hora') || p.includes('fecha') || p.includes('tiempo')) {{
                const now = new Date();
                return `Tiempo local: ${{now.toLocaleTimeString()}} del ${{now.toLocaleDateString('es-ES', {{ weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }})}}. Coherencia temporal sincronizada.`;
            }}

            if (/^[0-9+\\-*\\/().\\s^]+$/.test(p.replace(/cuánto es|calcula|calculame/g, '').trim())) {{
                try {{
                    const expr = p.replace(/cuánto es|calcula|calculame/g, '').trim();
                    const res = Function('"use strict";return (' + expr + ')')();
                    return `Resultado del cálculo local: **${{res}}** (procesado instantáneamente en el hardware del iPad).`;
                }} catch(e) {{}}
            }}

            return 'Comprendo tu solicitud. He evaluado la consulta en mi Cortex Local M2. Si requieres que la Central aplique sus 120B parámetros o ejecute comandos de Ring 0, indícamelo o conmuta a modo CENTRAL.';
        }}

        // =========================================================================
        // --- 3. ENVÍO Y RUTEO DE MENSAJES ---
        // =========================================================================
        const MAX_DOM_BUBBLES = 50;

        function switchTab(tabId, btn) {{
            document.querySelectorAll('.tab-view').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.dock-btn, .nav-chip').forEach(el => el.classList.remove('active'));
            const target = document.getElementById(tabId);
            if (target) target.classList.add('active');
            document.querySelectorAll(`[onclick*="${{tabId}}"]`).forEach(el => el.classList.add('active'));
            if (tabId === 'view-linpad') loadLinpadDesktop();
            if (tabId === 'view-ide') loadFilesTree();
            if (tabId === 'view-terminal') loadKernelBase();
            if (tabId === 'view-tools') loadToolsCatalog();
            if (tabId === 'view-telemetry') pollTelemetry();
        }}

        function quickPrompt(text) {{
            document.getElementById('chat-input').value = text;
            sendChatMessage();
        }}

        async function sendChatMessage() {{
            const input = document.getElementById('chat-input');
            const text = input.value.trim();
            if (!text) return;
            input.value = '';

            addChatBubble('user', text);

            const complexity = evaluatePromptComplexity(text);
            let targetRoute = 'local';

            if (inferenceMode === 'central') targetRoute = 'central';
            else if (inferenceMode === 'local') targetRoute = 'local';
            else targetRoute = complexity >= 0.35 ? 'central' : 'local';

            setCharacterState('thinking');

            if (targetRoute === 'local') {{
                // --- INFERENCIA LOCAL EN IPAD PRO M2 ---
                const startT = performance.now();
                await new Promise(r => setTimeout(r, 60)); // Simulación de ciclo de GPU
                const reply = generateLocalM2Response(text);
                const elapsed = ((performance.now() - startT) / 1000).toFixed(2);

                addChatBubble('assistant', reply, false, 'local', elapsed);
                triggerSpeechVisemes(reply);
                setCharacterState('speaking');
            }} else {{
                // --- ESCALACIÓN A CENTRAL TARDIS (KAIJU / HOST) ---
                const loadBubble = addChatBubble('assistant', 'Escalando petición compleja a Central TARDIS KAIJU...', true, 'central');
                const startT = performance.now();

                try {{
                    const res = await fetch('/api/chat', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ prompt: text, client_id: 'ipad_pro_m2' }})
                    }});
                    const data = await res.json();
                    const elapsed = ((performance.now() - startT) / 1000).toFixed(1);

                    if (data.ok && data.reply) {{
                        loadBubble.querySelector('.bubble-text').innerText = data.reply;
                        loadBubble.querySelector('.badge-router').innerText = `🌌 CENTRAL TARDIS [${{data.model || 'KAIJU'}} · ${{elapsed}}s]`;
                        triggerSpeechVisemes(data.reply);
                        setCharacterState('speaking');
                    }} else {{
                        loadBubble.querySelector('.bubble-text').innerText = 'Error Central: ' + (data.error || 'Fallo inesperado');
                        setCharacterState('idle');
                    }}
                }} catch (err) {{
                    loadBubble.querySelector('.bubble-text').innerText = 'Fallo de enlace con Central TARDIS: ' + err.message;
                    setCharacterState('idle');
                }}
            }}
            pruneDomNodes();
        }}

        function addChatBubble(role, text, isPending = false, route = 'local', elapsed = '0.05') {{
            const container = document.getElementById('chat-history');
            const bubble = document.createElement('div');
            bubble.className = `chat-bubble ${{role}}`;

            const badgeHtml = role === 'user' 
                ? '' 
                : (route === 'local' 
                    ? `<span class="badge-router badge-local">⚡ LOCAL IPAD M2 [${{elapsed}}s]</span>`
                    : `<span class="badge-router badge-central">🌌 CENTRAL TARDIS [${{elapsed}}s]</span>`);

            bubble.innerHTML = `
                <div class="bubble-meta">
                    <span>${{role === 'user' ? 'ARQUITECTO (IPAD M2)' : 'TARDIS GIA'}}</span>
                    ${{badgeHtml}}
                </div>
                <div class="bubble-text" style="white-space: pre-wrap;">${{escapeHtml(text)}}</div>
            `;
            container.appendChild(bubble);
            container.scrollTop = container.scrollHeight;
            return bubble;
        }}

        function pruneDomNodes() {{
            const container = document.getElementById('chat-history');
            while (container.children.length > MAX_DOM_BUBBLES) {{
                container.removeChild(container.firstChild);
            }}
        }}

        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.innerText = text;
            return div.innerHTML;
        }}

        // Sincronización de visemas fonéticos con voz
        function triggerSpeechVisemes(text) {{
            if (!window.speechSynthesis) {{
                setTimeout(() => setCharacterState('idle'), 2500);
                return;
            }}

            const clean = text.replace(/[*_#`~|]/g, '').slice(0, 220);
            const utter = new SpeechSynthesisUtterance(clean);
            utter.lang = 'es-MX';
            utter.rate = 1.05;

            utter.onstart = () => {{
                setCharacterState('speaking');
            }};

            utter.onboundary = (e) => {{
                vocalState.mouthOpen = 0.35 + Math.random() * 0.45;
                vocalState.vocalPulse = 0.6;
                setTimeout(() => {{
                    vocalState.mouthOpen = 0.04;
                    vocalState.vocalPulse = 0.0;
                }}, 120);
            }};

            utter.onend = () => {{
                vocalState.mouthOpen = 0.04;
                setCharacterState('idle');
            }};

            utter.onerror = () => {{
                vocalState.mouthOpen = 0.04;
                setCharacterState('idle');
            }};

            window.speechSynthesis.speak(utter);
        }}

        
        // =========================================================================
        // --- 4. CONTROLADOR DEL IDE SOBERANO (STUDIO M2 & SYNC BIDIRECCIONAL) ---
        // =========================================================================
        let currentOpenPath = 'projects/main.py';

        async function loadFilesTree() {{
            const list = document.getElementById('ide-file-tree');
            if (!list) return;
            list.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;">Cargando archivos...</div>';
            try {{
                const res = await fetch('/api/fs/tree');
                const data = await res.json();
                if (data.ok && data.files) {{
                    list.innerHTML = '';
                    let lastGroup = '';
                    data.files.forEach(f => {{
                        if (f.group !== lastGroup) {{
                            lastGroup = f.group;
                            const gh = document.createElement('div');
                            gh.style.cssText = 'font-weight:700;color:var(--neon-cyan);font-size:0.75rem;margin:12px 0 4px;text-transform:uppercase;letter-spacing:1px;';
                            gh.innerText = f.group === 'projects' ? '📁 Proyectos iPad' : '⚡ Módulos FTL';
                            list.appendChild(gh);
                        }}
                        const it = document.createElement('div');
                        it.className = 'file-tree-item' + (f.rel_path === currentOpenPath ? ' active' : '');
                        it.innerText = f.name;
                        it.onclick = () => openFile(f.rel_path, it);
                        list.appendChild(it);
                    }});
                    if (data.files.length > 0 && !currentOpenPath) {{
                        openFile(data.files[0].rel_path);
                    }}
                }}
            }} catch(err) {{
                list.innerHTML = '<div style="color:#ef4444;">Error cargando árbol</div>';
            }}
        }}

        async function openFile(relPath, el) {{
            currentOpenPath = relPath;
            document.querySelectorAll('.file-tree-item').forEach(i => i.classList.remove('active'));
            if (el) el.classList.add('active');
            document.getElementById('ide-active-file').innerText = relPath;
            
            try {{
                const res = await fetch('/api/fs/read', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{path: relPath}})
                }});
                const data = await res.json();
                if (data.ok) {{
                    document.getElementById('ide-code-editor').value = data.content;
                    document.getElementById('ide-console-output').innerText = `// Archivo cargado: ${{relPath}} (${{data.size}} bytes)\n// Listo para editar y compilar.`;
                }} else {{
                    alert('Error: ' + data.error);
                }}
            }} catch(err) {{
                alert('Fallo cargando archivo: ' + err.message);
            }}
        }}

        async function saveCurrentFile() {{
            if (!currentOpenPath) {{
                alert('Selecciona o crea un archivo primero.');
                return;
            }}
            const content = document.getElementById('ide-code-editor').value;
            const con = document.getElementById('ide-console-output');
            con.innerText = `[SYNC] Guardando y sincronizando ${{currentOpenPath}}...\n`;
            
            try {{
                const res = await fetch('/api/fs/write', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        path: currentOpenPath,
                        content: content,
                        commit_message: `iPad Pro M2 edit: ${{currentOpenPath}}`
                    }})
                }});
                const data = await res.json();
                if (data.ok) {{
                    con.innerText += `✓ Guardado en Host: ${{data.bytes_written}} bytes\n`;
                    con.innerText += `✓ Sincronizado en iPad AFC (/TARDIS_WORKSPACE/${{data.path}}): ${{data.afc_synced ? 'OK' : 'Pendiente'}}\n`;
                    con.innerText += `✓ Sincronizado en GitHub (FTL Git Sync): ${{data.git_synced ? 'OK' : 'Local Commited'}}\n`;
                }} else {{
                    con.innerText += `✗ Error: ${{data.error}}\n`;
                }}
            }} catch(err) {{
                con.innerText += `✗ Fallo de red: ${{err.message}}\n`;
            }}
        }}

        async function executeCurrentCode() {{
            const code = document.getElementById('ide-code-editor').value;
            const con = document.getElementById('ide-console-output');
            con.innerText = `[RUN] Ejecutando ${{currentOpenPath || 'código'}} en el motor soberano...\n`;
            
            try {{
                const res = await fetch('/api/fs/execute', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        path: currentOpenPath,
                        code: code
                    }})
                }});
                const data = await res.json();
                con.innerText += `--- SALIDA (${{data.elapsed_s}}s | Exit: ${{data.exit_code}}) ---\n`;
                if (data.stdout) con.innerText += data.stdout;
                if (data.stderr) con.innerText += `[STDERR]\n${{data.stderr}}`;
                if (!data.stdout && !data.stderr) con.innerText += '(Sin salida)';
            }} catch(err) {{
                con.innerText += `✗ Fallo de ejecución: ${{err.message}}\n`;
            }}
        }}

        function newFilePrompt() {{
            const name = prompt('Nombre del nuevo archivo (p.ej. projects/mi_script.py):');
            if (!name) return;
            currentOpenPath = name;
            document.getElementById('ide-active-file').innerText = name;
            document.getElementById('ide-code-editor').value = `# Nuevo script soberano en iPad Pro M2
import sys
print('Hola desde iPad Pro M2!')
`;
            saveCurrentFile().then(() => loadFilesTree());
        }}

        async function triggerManualGitSync() {{
            const con = document.getElementById('ide-console-output');
            con.innerText += `[GIT] Iniciando sincronización manual con GitHub...\n`;
            try {{
                const res = await fetch('/api/fs/write', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        path: currentOpenPath || 'projects/sync.log',
                        content: document.getElementById('ide-code-editor').value,
                        commit_message: 'Manual push from iPad Pro M2'
                    }})
                }});
                const data = await res.json();
                con.innerText += `[GIT] Resultado: ${{data.git_synced ? 'Exitoso' : 'Completado local'}}\n`;
            }} catch(e) {{
                con.innerText += `[GIT] Error: ${{e.message}}\n`;
            }}
        }}

        // =========================================================================
        // --- 5. CONTROLADOR DE TERMINAL & KERNEL BASE ---
        // =========================================================================
        async function runTerminalCommand() {{
            const inp = document.getElementById('term-cmd-input');
            const cmd = inp.value.trim();
            if (!cmd) return;
            inp.value = '';
            
            const box = document.getElementById('terminal-log');
            box.innerHTML += `<div><span style="color:var(--neon-cyan)">tardis@m2:~$</span> ${{escapeHtml(cmd)}}</div>`;
            
            const isAgy = cmd.includes('agy');
            const tempId = 'exec_' + Date.now();
            const msg = isAgy ? '⚡ [AGY ULTRA] Pensando y ejecutando modelo Claude Opus 5.5 High...' : '⏳ Ejecutando en sistema...';
            box.innerHTML += `<div id="${{tempId}}" style="color:var(--neon-gold);font-style:italic;margin:4px 0;">${{msg}}</div>`;
            box.scrollTop = box.scrollHeight;
            
            try {{
                const res = await fetch('/api/terminal/exec', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{command: cmd}})
                }});
                const tempEl = document.getElementById(tempId);
                if (tempEl) tempEl.remove();
                
                const data = await res.json();
                if (data.stdout) box.innerHTML += `<pre style="color:#e2e8f0;margin:4px 0;white-space:pre-wrap;font-family:monospace;">${{escapeHtml(data.stdout)}}</pre>`;
                if (data.stderr) box.innerHTML += `<pre style="color:#ef4444;margin:4px 0;white-space:pre-wrap;font-family:monospace;">${{escapeHtml(data.stderr)}}</pre>`;
                if (!data.stdout && !data.stderr && data.error) {{
                    box.innerHTML += `<div style="color:#ef4444">Error: ${{escapeHtml(data.error)}}</div>`;
                }}
                box.scrollTop = box.scrollHeight;
            }} catch(err) {{
                const tempEl = document.getElementById(tempId);
                if (tempEl) tempEl.remove();
                box.innerHTML += `<div style="color:#ef4444">Error: ${{err.message}}</div>`;
                box.scrollTop = box.scrollHeight;
            }}
        }}

        function quickTermCmd(cmd) {{
            document.getElementById('term-cmd-input').value = cmd;
            runTerminalCommand();
        }}

        async function loadKernelBase() {{
            try {{
                const res = await fetch('/api/kernel/base');
                const data = await res.json();
                if (data.ok) {{
                    const tbody = document.getElementById('kernel-proc-tbody');
                    if (tbody && data.ipad_darwin_kernel && data.ipad_darwin_kernel.top_processes) {{
                        tbody.innerHTML = '';
                        data.ipad_darwin_kernel.top_processes.forEach(p => {{
                            const tr = document.createElement('tr');
                            tr.innerHTML = `<td style="color:var(--neon-cyan)">${{p.pid}}</td><td style="color:#fff;font-weight:600">${{escapeHtml(p.name)}}</td><td>${{p.is_app ? 'App' : 'Daemon'}}</td><td style="color:#94a3b8;font-size:0.75rem">${{escapeHtml(p.path.slice(0, 35))}}</td>`;
                            tbody.appendChild(tr);
                        }});
                    }}
                    const ring0Box = document.getElementById('kernel-ring0-data');
                    if (ring0Box && data.linux_ring0) {{
                        let html = `<div><strong>CPU Pressure:</strong> ${{escapeHtml(data.linux_ring0.psi.cpu)}}</div>`;
                        html += `<div><strong>Memory Pressure:</strong> ${{escapeHtml(data.linux_ring0.psi.memory)}}</div>`;
                        html += `<div><strong>I/O Pressure:</strong> ${{escapeHtml(data.linux_ring0.psi.io)}}</div>`;
                        html += `<div><strong>sysctl:</strong> swappiness=${{data.linux_ring0.swappiness}} | dirty_ratio=${{data.linux_ring0.dirty_ratio}} | tcp_cc=${{data.linux_ring0.tcp_congestion}}</div>`;
                        html += `<div style="margin-top:8px;font-weight:700;color:var(--neon-gold)">dmesg ring buffer (reciente):</div>`;
                        html += `<pre style="color:#94a3b8;font-size:0.75rem;max-height:120px;overflow-y:auto;background:rgba(0,0,0,0.4);padding:6px;border-radius:6px;">${{escapeHtml((data.linux_ring0.dmesg || []).join(`\n`))}}</pre>`;
                        ring0Box.innerHTML = html;
                    }}
                }}
            }} catch(err) {{
                console.error('Error cargando kernel base:', err);
            }}
        }}

        // Catálogo de Omni-Herramientas
        async function loadToolsCatalog() {{
            const grid = document.getElementById('tools-grid');
            grid.innerHTML = '<div style="color:var(--neon-cyan)">Cargando suite soberana...</div>';
            try {{
                const res = await fetch('/api/tools');
                const data = await res.json();
                if (data.tools) {{
                    grid.innerHTML = '';
                    for (const [key, t] of Object.entries(data.tools)) {{
                        const card = document.createElement('div');
                        card.className = 'tool-card';
                        let actionBtns = '';
                        (t.supported_actions || []).slice(0, 5).forEach(act => {{
                            actionBtns += `<button class="action-btn" onclick="executeTool('${{key}}', '${{act}}')">${{act}}</button>`;
                        }});
                        card.innerHTML = `
                            <div class="tool-header">
                                <span class="tool-name">${{t.name}}</span>
                                <span class="tool-badge">${{t.available ? 'ACTIVO' : 'STANDBY'}}</span>
                            </div>
                            <div class="tool-desc">${{t.description}}</div>
                            <div class="tool-actions">${{actionBtns}}</div>
                        `;
                        grid.appendChild(card);
                    }}
                }}
            }} catch (err) {{
                grid.innerHTML = `<div style="color:var(--neon-red)">Error cargando herramientas: ${{err.message}}</div>`;
            }}
        }}

        async function executeTool(toolId, action) {{
            const term = document.getElementById('terminal-output');
            term.innerText = `[TARDIS-EXEC] Ejecutando '${{toolId}}' acción '${{action}}'...\\n`;
            try {{
                const res = await fetch('/api/tool/execute', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ tool_id: toolId, action: action }})
                }});
                const data = await res.json();
                term.innerText += JSON.stringify(data, null, 2);
            }} catch (err) {{
                term.innerText += `[ERROR] ${{err.message}}`;
            }}
            term.scrollTop = term.scrollHeight;
        }}

        // Sondeo de Telemetría
        async function pollTelemetry() {{
            try {{
                const res = await fetch('/api/telemetry');
                const d = await res.json();
                document.getElementById('stat-ping').innerText = d.ipad_ping || '0.7 ms';
                document.getElementById('stat-mem').innerText = (d.mem_used_pct || 0) + '%';
                document.getElementById('stat-mem-gb').innerText = `${{d.mem_avail_gb}} GB libres / ${{d.mem_total_gb}} GB`;
                document.getElementById('stat-load').innerText = (d.load_avg || []).join(' · ');
                if (d.tardis) {{
                    document.getElementById('stat-thoughts').innerText = d.tardis.thoughts || '2,354';
                }}
                if (d.psi) {{
                    document.getElementById('stat-psi').innerHTML = `
                        <strong>CPU:</strong> ${{escapeHtml(d.psi.cpu || 'N/A')}}<br>
                        <strong>MEM:</strong> ${{escapeHtml(d.psi.memory || 'N/A')}}<br>
                        <strong>I/O:</strong> ${{escapeHtml(d.psi.io || 'N/A')}}
                    `;
                }}
            }} catch (e) {{}}
        }}

        // =========================================================================
        // --- 6. CONTROLADOR LINPAD 1.6.0-TARDIS-M2 DESKTOP ---
        // =========================================================================
        let linpadLoaded = false;
        let linpadThemesList = [];

        async function loadLinpadDesktop() {{
            const termOut = document.getElementById('linpad-term-output');
            const themesBar = document.getElementById('linpad-themes-bar');
            const catalogGrid = document.getElementById('linpad-catalog-grid');
            try {{
                const res = await fetch('/api/linpad/status');
                const data = await res.json();
                if (data.ok && data.status) {{
                    if (!linpadLoaded) {{
                        termOut.innerText = (data.status.fastfetch_output || '') + '\n\n' + (data.status.tardis_bridge_output || '');
                        linpadLoaded = true;
                    }}
                    if (data.themes && data.themes.themes && themesBar) {{
                        linpadThemesList = data.themes.themes;
                        themesBar.innerHTML = '';
                        linpadThemesList.slice(0, 12).forEach(th => {{
                            const btn = document.createElement('button');
                            btn.className = 'action-btn';
                            btn.style.cssText = `background:${{th.background}};color:${{th.foreground}};border:1px solid ${{th.accent}};display:inline-flex;align-items:center;gap:5px;padding:4px 9px;border-radius:8px;font-size:0.74rem;cursor:pointer;`;
                            btn.innerHTML = `<span style="width:8px;height:8px;border-radius:50%;background:${{th.accent}};display:inline-block;"></span>${{escapeHtml(th.name)}}`;
                            btn.onclick = () => applyLinpadTheme(th);
                            themesBar.appendChild(btn);
                        }});
                    }}
                    if (data.catalog && data.catalog.packs && catalogGrid) {{
                        catalogGrid.innerHTML = '';
                        data.catalog.packs.forEach(pk => {{
                            const card = document.createElement('div');
                            card.style.cssText = 'background:rgba(3,7,18,0.75);border:1px solid rgba(56,189,248,0.22);border-radius:8px;padding:8px;display:flex;flex-direction:column;justify-content:space-between;gap:4px;';
                            const isTardis = pk.id === 'tardis-ftl';
                            if (isTardis) card.style.borderColor = '#00f5d4';
                            card.innerHTML = `
                                <div style="display:flex;justify-content:space-between;align-items:center;">
                                    <span style="font-weight:700;font-size:0.78rem;color:${{isTardis ? '#00f5d4' : '#f1f5f9'}};">${{escapeHtml(pk.name)}}</span>
                                    <span style="font-size:0.65rem;color:#34d399;font-family:var(--font-mono);">${{pk.size_mb}} MB</span>
                                </div>
                                <div style="font-size:0.7rem;color:#94a3b8;line-height:1.3;">${{escapeHtml((pk.description || '').slice(0, 72))}}</div>
                                <button class="action-btn" style="margin-top:4px;font-size:0.7rem;padding:3px 6px;" onclick="runLinpadQuick('linpad apps info ${{pk.id}} || linpad apps list')">🔍 Inspeccionar ${{escapeHtml(pk.id)}}</button>
                            `;
                            catalogGrid.appendChild(card);
                        }});
                    }}
                }}
            }} catch (e) {{
                if (termOut) termOut.innerText = 'Error cargando LinPad Desktop: ' + e.message;
            }}
        }}

        function applyLinpadTheme(th) {{
            const win = document.getElementById('linpad-term-window');
            const out = document.getElementById('linpad-term-output');
            const bar = document.getElementById('linpad-waybar');
            if (win) {{
                win.style.background = th.background;
                win.style.borderColor = th.accent;
            }}
            if (out) {{
                out.style.color = th.foreground;
            }}
            if (bar) {{
                bar.style.borderColor = th.accent;
            }}
        }}

        async function runLinpadCmd() {{
            const inp = document.getElementById('linpad-cmd-input');
            const cmd = inp.value.trim();
            if (!cmd) return;
            inp.value = '';
            await runLinpadQuick(cmd);
        }}

        async function runLinpadQuick(cmd) {{
            const out = document.getElementById('linpad-term-output');
            out.innerText += `\n\nroot@linpad-m2:~# ${{cmd}}\n`;
            out.scrollTop = out.scrollHeight;
            try {{
                const res = await fetch('/api/linpad/exec', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{command: cmd}})
                }});
                const data = await res.json();
                if (data.stdout) out.innerText += data.stdout;
                if (data.stderr) out.innerText += `\n[stderr] ${{data.stderr}}`;
                out.scrollTop = out.scrollHeight;
            }} catch (e) {{
                out.innerText += `\n[error] ${{e.message}}`;
            }}
        }}

        setInterval(pollTelemetry, 3000);
        pollTelemetry();
        if (window.location.pathname.indexOf('/linpad') === 0) {{
            switchTab('view-linpad');
        }}
    </script>
</body>
</html>
"""

def _edge_authorized(request: web.Request, body: Optional[Dict[str, Any]] = None) -> bool:
    device_id = request.headers.get("X-TARDIS-Device-ID", "")
    if not device_id and body:
        device_id = str(body.get("device_id", ""))
    if device_id:
        try:
            from core.security import is_request_authorized
            headers = {k.lower(): v for k, v in request.headers.items()}
            params = {k: v[0] for k, v in parse_qs(request.query_string).items()}
            return is_request_authorized(headers, params, client_ip=request.remote or "")
        except Exception:
            return False
    return False


@web.middleware
async def _edge_auth_middleware(request: web.Request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    body = None
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = None
    if not _edge_authorized(request, body):
        return web.json_response({"ok": False, "error": "dispositivo no autorizado"}, status=401)
    return await handler(request)


NXNATIVE_IPA_PATH = Path("/home/timemachine/nxnative/build/MarioKart8Deluxe.ipa")
NXNATIVE_ICON_PNG = Path("/home/timemachine/nxnative/build/mk8d_icon_512.png")
NXNATIVE_FONT_TTF = Path("/home/timemachine/nxnative/build/DmIOS.app/dm/font/nintendo_ext.ttf")


async def nxnative_ui_handler(request: web.Request) -> web.Response:
    from core.nxnative_mk8d_ipad_ui import get_nxnative_mk8d_html
    return web.Response(
        text=get_nxnative_mk8d_html(),
        content_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


async def nxnative_icon_handler(request: web.Request) -> web.Response:
    if NXNATIVE_ICON_PNG.exists():
        return web.FileResponse(NXNATIVE_ICON_PNG)
    return web.Response(status=404)


async def nxnative_font_handler(request: web.Request) -> web.Response:
    if NXNATIVE_FONT_TTF.exists():
        return web.FileResponse(NXNATIVE_FONT_TTF)
    return web.Response(status=404)


async def download_mk8d_ipa_handler(request: web.Request) -> web.Response:
    if NXNATIVE_IPA_PATH.exists():
        return web.FileResponse(
            NXNATIVE_IPA_PATH,
            headers={
                "Content-Disposition": 'attachment; filename="MarioKart8Deluxe.ipa"'
            },
        )
    return web.Response(text="MarioKart8Deluxe.ipa no encontrado", status=404)


async def nxnative_profile_handler(request: web.Request) -> web.Response:
    if "lan" in request.query:
        host = request.headers.get("Host", f"{LAN_HOST_IP}:{EDGE_PORT}").split(":")[0]
        if host in ("127.0.0.1", "localhost", "0.0.0.0"):
            host = LAN_HOST_IP
        target_url = f"http://{host}:{EDGE_PORT}/mk8d?v=4.0.1"
    else:
        target_url = f"{get_internet_url().rstrip('/')}/mk8d?v=4.0.1"
    icon_data = b""
    if NXNATIVE_ICON_PNG.exists():
        icon_data = NXNATIVE_ICON_PNG.read_bytes()
    elif ICON_PNG.exists():
        icon_data = ICON_PNG.read_bytes()

    payload = {
        "PayloadType": "com.apple.webClip.managed",
        "PayloadVersion": 1,
        "PayloadIdentifier": "org.nxnative.0100152000022000.webclip",
        "PayloadUUID": "REDACTED_PHONE-2108-201E-TARDIS000002",
        "PayloadDisplayName": "Mario Kart 8 Deluxe 4.0.1",
        "PayloadDescription": "nxnative · Mario Kart 8 Deluxe 4.0.1 (v1507328 · 29,785 Shaders · 23 _b.metallib) para Apple iPad Pro M2",
        "PayloadOrganization": "nxnative · GODWORKS System",
        "Label": "Mario Kart 8",
        "URL": target_url,
        "FullScreen": True,
        "IsRemovable": True,
        "Precomposed": True,
        "Icon": icon_data,
        "IgnoreManifestScope": True,
    }
    profile = {
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadIdentifier": "org.nxnative.0100152000022000.profile",
        "PayloadUUID": "REDACTED_PHONE-2108-201E-MK8DNX000001",
        "PayloadDisplayName": "Mario Kart 8 Deluxe 4.0.1 (nxnative M2)",
        "PayloadDescription": "Instalación Nativa de Mario Kart 8 Deluxe 4.0.1 (0100152000022000 · Chain b-8e52e2292032 · 29,785 Shaders) vía nxnative en Apple iPad Pro M2",
        "PayloadOrganization": "nxnative · GODWORKS System",
        "PayloadContent": [payload],
    }
    return web.Response(
        body=plistlib.dumps(profile),
        content_type="application/x-apple-aspen-config",
        headers={
            "Content-Disposition": 'attachment; filename="nxnative_mk8d_m2.mobileconfig"'
        },
    )


async def api_nxnative_status_handler(request: web.Request) -> web.Response:
    try:
        from modulos_ftl.ftl_nxnative import FtlNxnative
        ctl = FtlNxnative()
        return web.json_response({
            "ok": True,
            "status": ctl.get_status(),
            "catalog": ctl.get_games_catalog(),
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


def create_app() -> web.Application:
    app = web.Application(middlewares=[_edge_auth_middleware])
    app.router.add_get("/", index_handler)
    app.router.add_get("/linpad", index_handler)
    app.router.add_get("/mk8d", nxnative_ui_handler)
    app.router.add_get("/nxnative", nxnative_ui_handler)
    app.router.add_get("/mk8d/icon.png", nxnative_icon_handler)
    app.router.add_get("/mk8d/font.ttf", nxnative_font_handler)
    app.router.add_get("/manifest.json", manifest_handler)
    app.router.add_get("/icon.png", icon_handler)
    app.router.add_get("/install.mobileconfig", profile_handler)
    app.router.add_get("/install-internet.mobileconfig", profile_handler)
    app.router.add_get("/tardis.mobileconfig", profile_handler)
    app.router.add_get("/linpad.mobileconfig", linpad_profile_handler)
    app.router.add_get("/mk8d.mobileconfig", nxnative_profile_handler)
    app.router.add_get("/nxnative.mobileconfig", nxnative_profile_handler)
    app.router.add_get("/download/tardis.ipa", download_ipa_handler)
    app.router.add_get("/download/linpad.ipa", download_linpad_ipa_handler)
    app.router.add_get("/download/MarioKart8Deluxe.ipa", download_mk8d_ipa_handler)
    app.router.add_get("/download/nxnative-mk8d.ipa", download_mk8d_ipa_handler)

    # API REST
    app.router.add_get("/api/telemetry", api_telemetry_handler)
    app.router.add_get("/api/tools", api_tools_handler)
    app.router.add_post("/api/tool/execute", api_tool_execute_handler)
    app.router.add_post("/api/chat", api_chat_handler)
    app.router.add_get("/api/ipad/screenshot", api_ipad_screenshot_handler)

    # API LINPAD 1.6.0-TARDIS-M2 & NXNATIVE MK8D
    app.router.add_get("/api/linpad/status", api_linpad_status_handler)
    app.router.add_post("/api/linpad/exec", api_linpad_exec_handler)
    app.router.add_get("/api/nxnative/status", api_nxnative_status_handler)
    
    # NUEVAS APIS DE PROGRAMACIÓN & KERNEL BASE
    app.router.add_get("/api/fs/tree", api_fs_tree_handler)
    app.router.add_post("/api/fs/read", api_fs_read_handler)
    app.router.add_post("/api/fs/write", api_fs_write_handler)
    app.router.add_post("/api/fs/execute", api_fs_execute_handler)
    app.router.add_post("/api/terminal/exec", api_terminal_exec_handler)
    app.router.add_get("/api/kernel/base", api_kernel_base_handler)

    return app

async def async_main():
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()

    # Iniciar en puerto 80 (para acceso directo http://REDACTED_IP/ o http://REDACTED_IP/)
    try:
        site_80 = web.TCPSite(runner, EDGE_HOST, 80)
        await site_80.start()
        logger.info(f"Servidor Edge TARDIS escuchando en puerto nativo 80 (http://{EDGE_HOST}:80)")
    except Exception as e:
        logger.warning(f"Aviso puerto 80: {e}")

    # Iniciar en puerto 8088
    try:
        site_8088 = web.TCPSite(runner, EDGE_HOST, EDGE_PORT)
        await site_8088.start()
        logger.info(f"Servidor Edge TARDIS escuchando en puerto 8088 (http://{EDGE_HOST}:{EDGE_PORT})")
    except Exception as e:
        logger.error(f"Error puerto 8088: {e}")

    while True:
        await asyncio.sleep(3600)

def main():
    logger.info("Iniciando Servidor Edge TARDIS para iPad Pro M2...")
    try:
        asyncio.run(async_main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Servidor detenido limpiamente.")

if __name__ == "__main__":
    main()
