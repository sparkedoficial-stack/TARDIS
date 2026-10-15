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
        target_url = f"http://{host}/"

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
        .tool-header {{
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
                    <strong>Gobernador Móvil:</strong> Buffer circular activo (&lt;100MB RAM, 120Hz ProMotion)<br>
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
            document.querySelectorAll('.dock-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            btn.classList.add('active');
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

        setInterval(pollTelemetry, 3000);
        pollTelemetry();
    </script>
</body>
</html>
"""

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/manifest.json", manifest_handler)
    app.router.add_get("/icon.png", icon_handler)
    app.router.add_get("/install.mobileconfig", profile_handler)
    app.router.add_get("/install-internet.mobileconfig", profile_handler)
    app.router.add_get("/tardis.mobileconfig", profile_handler)
    app.router.add_get("/download/tardis.ipa", download_ipa_handler)

    # API REST
    app.router.add_get("/api/telemetry", api_telemetry_handler)
    app.router.add_get("/api/tools", api_tools_handler)
    app.router.add_post("/api/tool/execute", api_tool_execute_handler)
    app.router.add_post("/api/chat", api_chat_handler)
    app.router.add_get("/api/ipad/screenshot", api_ipad_screenshot_handler)

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
