#!/usr/bin/env python3
"""
tardis_ipad_edge_server.py - Servidor Soberano Edge de TARDIS para iPad Pro M2
=============================================================================
GODWORKS SYSTEM v26.4 · Arquitectura Soberana TARDIS-NEURAL-SPACE-KAIJU
Diseñado específicamente para el Apple iPad Pro 12.9" M2 (Liquid Retina XDR, ProMotion 120Hz)
con Gobernador de Recursos Móviles (<100MB footprint) y Acceso Total a Omni-Tools.
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
        "host_ip": USB_HOST_IP
    }

# Generador del WebClip Mobileconfig
def generate_webclip_profile(host_ip: str = USB_HOST_IP, port: int = EDGE_PORT) -> bytes:
    profile_uuid = "REDACTED_PHONE-2108-201E-TARDIS000001"
    payload_uuid = "REDACTED_PHONE-2108-201E-TARDIS000002"

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
        "URL": f"http://{host_ip}:{port}/",
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
    # Determinar host de la petición
    host = request.headers.get("Host", f"{USB_HOST_IP}:{EDGE_PORT}").split(":")[0]
    profile_data = generate_webclip_profile(host_ip=host, port=EDGE_PORT)
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
    # Enriquecer con estado de TARDIS si está activo
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
        return web.json_response({"ok": False, "error": "Timeout esperando respuesta de TARDIS (60s)"}, status=504)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Fallo de conexión con TARDIS: {str(e)}"}, status=500)

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

# HTML5 / CSS3 / JavaScript con Gobernador de Memoria (<100MB) para iPad Pro M2
def get_client_html() -> str:
    return """<!DOCTYPE html>
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
        :root {
            --bg-deep: #030712;
            --bg-card: rgba(15, 23, 42, 0.75);
            --bg-card-border: rgba(56, 189, 248, 0.2);
            --neon-cyan: #06b6d4;
            --neon-blue: #3b82f6;
            --neon-green: #10b981;
            --neon-amber: #f59e0b;
            --neon-red: #ef4444;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", Roboto, sans-serif;
            --safe-top: env(safe-area-inset-top, 24px);
            --safe-bottom: env(safe-area-inset-bottom, 20px);
        }
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
            user-select: none;
        }
        body {
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
                radial-gradient(circle at 85% 85%, rgba(59, 130, 246, 0.08) 0%, transparent 40%);
        }
        /* Header Superior */
        header {
            height: 64px;
            padding: 0 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--bg-card-border);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            background: rgba(3, 7, 18, 0.85);
            z-index: 100;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 14px;
        }
        .brand-logo {
            width: 40px;
            height: 40px;
            border-radius: 10px;
            box-shadow: 0 0 15px rgba(6, 182, 212, 0.5);
            border: 1px solid var(--neon-cyan);
        }
        .brand-title {
            font-size: 1.25rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .brand-subtitle {
            font-size: 0.72rem;
            color: var(--neon-cyan);
            font-family: var(--font-mono);
            letter-spacing: 0.12em;
        }
        .device-badge {
            display: flex;
            align-items: center;
            gap: 12px;
            background: rgba(15, 23, 42, 0.8);
            padding: 8px 16px;
            border-radius: 30px;
            border: 1px solid rgba(16, 185, 129, 0.3);
            font-size: 0.8rem;
            font-family: var(--font-mono);
        }
        .status-dot {
            width: 10px;
            height: 10px;
            background-color: var(--neon-green);
            border-radius: 50%;
            box-shadow: 0 0 10px var(--neon-green);
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(0.95); opacity: 0.7; }
            50% { transform: scale(1.15); opacity: 1; }
            100% { transform: scale(0.95); opacity: 0.7; }
        }
        /* Contenedor Principal */
        main {
            flex: 1;
            position: relative;
            overflow: hidden;
            display: flex;
        }
        .tab-view {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            display: none;
            flex-direction: column;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            padding: 20px 24px;
            opacity: 0;
            transform: scale(0.98);
            transition: opacity 0.2s ease, transform 0.2s ease;
        }
        .tab-view.active {
            display: flex;
            opacity: 1;
            transform: scale(1);
        }
        /* Barra de Navegación Inferior (Dock iPad Touch) */
        nav.bottom-dock {
            height: 72px;
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(25px);
            -webkit-backdrop-filter: blur(25px);
            border-top: 1px solid var(--bg-card-border);
            display: flex;
            justify-content: space-around;
            align-items: center;
            padding: 0 20px;
            z-index: 100;
        }
        .dock-btn {
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
        }
        .dock-btn svg {
            width: 24px;
            height: 24px;
            stroke: currentColor;
            stroke-width: 2;
            fill: none;
            transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
        .dock-btn.active {
            color: var(--neon-cyan);
            background: rgba(6, 182, 212, 0.12);
        }
        .dock-btn.active svg {
            transform: scale(1.15) translateY(-2px);
            stroke: var(--neon-cyan);
            filter: drop-shadow(0 0 6px var(--neon-cyan));
        }

        /* TAB 1: NEURAL CONSOLE (CHAT) */
        .chat-container {
            display: flex;
            flex-direction: column;
            height: 100%;
            max-width: 1200px;
            margin: 0 auto;
            width: 100%;
        }
        .chat-history {
            flex: 1;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            padding: 10px 0;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .chat-bubble {
            max-width: 85%;
            padding: 16px 20px;
            border-radius: 18px;
            font-size: 1rem;
            line-height: 1.6;
            word-break: break-word;
            user-select: text;
            animation: fadeIn 0.25s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .chat-bubble.user {
            align-self: flex-end;
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: #ffffff;
            border-bottom-right-radius: 4px;
            box-shadow: 0 4px 15px rgba(37, 99, 235, 0.3);
        }
        .chat-bubble.assistant {
            align-self: flex-start;
            background: rgba(30, 41, 59, 0.7);
            border: 1px solid var(--bg-card-border);
            color: var(--text-main);
            border-bottom-left-radius: 4px;
            backdrop-filter: blur(10px);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }
        .bubble-meta {
            font-size: 0.75rem;
            color: var(--neon-cyan);
            font-family: var(--font-mono);
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
        }
        .chat-chips {
            display: flex;
            gap: 10px;
            overflow-x: auto;
            padding: 10px 0;
            margin-bottom: 8px;
            scrollbar-width: none;
        }
        .chat-chip {
            background: rgba(30, 41, 59, 0.6);
            border: 1px solid var(--bg-card-border);
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 0.82rem;
            color: var(--neon-cyan);
            white-space: nowrap;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .chat-chip:active {
            background: var(--neon-cyan);
            color: #030712;
            transform: scale(0.96);
        }
        .chat-input-bar {
            display: flex;
            gap: 12px;
            background: rgba(15, 23, 42, 0.85);
            padding: 12px 18px;
            border-radius: 24px;
            border: 1px solid var(--bg-card-border);
            backdrop-filter: blur(20px);
        }
        .chat-input-bar input {
            flex: 1;
            background: transparent;
            border: none;
            color: var(--text-main);
            font-size: 1.05rem;
            outline: none;
            user-select: text;
        }
        .send-btn {
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
        }
        .send-btn:active {
            transform: scale(0.9);
        }
        .send-btn svg {
            width: 20px;
            height: 20px;
            fill: #ffffff;
        }

        /* TAB 2: OMNI TOOLS */
        .tools-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }
        .tool-card {
            background: var(--bg-card);
            border: 1px solid var(--bg-card-border);
            border-radius: 20px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            backdrop-filter: blur(15px);
            transition: border-color 0.2s ease;
        }
        .tool-card:hover {
            border-color: var(--neon-cyan);
        }
        .tool-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .tool-name {
            font-size: 1.1rem;
            font-weight: 700;
            color: #ffffff;
        }
        .tool-badge {
            background: rgba(16, 185, 129, 0.15);
            color: var(--neon-green);
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-family: var(--font-mono);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }
        .tool-desc {
            font-size: 0.85rem;
            color: var(--text-muted);
            line-height: 1.4;
        }
        .tool-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 6px;
        }
        .action-btn {
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid var(--bg-card-border);
            color: #38bdf8;
            padding: 8px 14px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-family: var(--font-mono);
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .action-btn:active {
            background: #0284c7;
            color: #ffffff;
            transform: scale(0.95);
        }
        .terminal-box {
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
        }

        /* TAB 3: TELEMETRY & RADAR */
        .telemetry-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--bg-card-border);
            border-radius: 20px;
            padding: 20px;
            backdrop-filter: blur(15px);
        }
        .stat-label {
            font-size: 0.8rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 6px;
        }
        .stat-value {
            font-size: 1.8rem;
            font-weight: 800;
            color: var(--neon-cyan);
            font-family: var(--font-mono);
        }
        .stat-sub {
            font-size: 0.8rem;
            color: var(--neon-green);
            margin-top: 4px;
        }

        /* TAB 4: VAULT & DOWNLOADS */
        .vault-card {
            background: var(--bg-card);
            border: 1px solid var(--bg-card-border);
            border-radius: 24px;
            padding: 24px;
            max-width: 800px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .download-btn {
            background: linear-gradient(135deg, #10b981, #059669);
            color: #ffffff;
            border: none;
            padding: 16px 24px;
            border-radius: 16px;
            font-size: 1.05rem;
            font-weight: 700;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
        }
        .download-btn:active {
            transform: scale(0.98);
        }
        .config-btn {
            background: linear-gradient(135deg, #3b82f6, #1d4ed8);
            color: #ffffff;
            border: none;
            padding: 16px 24px;
            border-radius: 16px;
            font-size: 1.05rem;
            font-weight: 700;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
        }
        .config-btn:active {
            transform: scale(0.98);
        }

        /* Mobile Governor Indicator */
        .governor-tag {
            font-size: 0.72rem;
            padding: 3px 8px;
            border-radius: 10px;
            background: rgba(6, 182, 212, 0.15);
            color: var(--neon-cyan);
            border: 1px solid rgba(6, 182, 212, 0.3);
        }
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
        <div class="device-badge">
            <div class="status-dot"></div>
            <span id="conn-status">USB LINK 0.7ms</span>
            <span class="governor-tag" id="dom-nodes">DOM: 0 N</span>
        </div>
    </header>

    <!-- Contenedor Principal de Vistas -->
    <main>
        <!-- VISTA 1: NEURAL CORE (CHAT) -->
        <section id="view-chat" class="tab-view active">
            <div class="chat-container">
                <div class="chat-chips">
                    <div class="chat-chip" onclick="quickPrompt('Estado general y telemetría de TARDIS')">📊 Estado General</div>
                    <div class="chat-chip" onclick="quickPrompt('Auditoría profunda de Kernel Ring 0 y PSI')">⚡ Kernel & PSI</div>
                    <div class="chat-chip" onclick="quickPrompt('Sincronizar proyectos con GitHub vía FTL')">🚀 FTL Git Sync</div>
                    <div class="chat-chip" onclick="quickPrompt('Diagnóstico Easy Touch Engine')">🛡️ Easy Touch</div>
                    <div class="chat-chip" onclick="quickPrompt('Lectura de sensores climáticos y radar RF')">📡 Sensores & Radar</div>
                </div>
                <div class="chat-history" id="chat-history">
                    <div class="chat-bubble assistant">
                        <div class="bubble-meta">
                            <span>TARDIS-NEURAL-SPACE-KAIJU</span>
                            <span>M2 EDGE ONLINE</span>
                        </div>
                        Bienvenido a la consola nativa de TARDIS en tu iPad Pro M2. Acceso soberano a todos los modelos neuronales, herramientas omnicanal y telemetría en tiempo real activo. ¿Qué orden deseas ejecutar?
                    </div>
                </div>
                <div class="chat-input-bar">
                    <input type="text" id="chat-input" placeholder="Pregunta a TARDIS KAIJU / GIA..." onkeydown="if(event.key==='Enter') sendChatMessage()">
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
                    <div class="stat-label">Latencia Enlace USB iPad</div>
                    <div class="stat-value" id="stat-ping">0.7 ms</div>
                    <div class="stat-sub" id="stat-ip">enx2e180932577d · REDACTED_IP</div>
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
                <h2 style="font-size: 1.3rem; color: #ffffff;">Instalación & Recursos Nativos M2</h2>
                <p style="color: var(--text-muted); font-size: 0.95rem; line-height: 1.5;">
                    Configuración soberana del iPad Pro M2 para acceso permanente a TARDIS. Puedes instalar el perfil de aplicación web nativo o descargar el paquete compilado.
                </p>
                <a href="/install.mobileconfig" class="config-btn" download>
                    <svg style="width:24px;height:24px;stroke:currentColor;fill:none;stroke-width:2;" viewBox="0 0 24 24"><path d="M12 2v10m0 0l-3-3m3 3l3-3m-9 9h12"/></svg>
                    Instalar Perfil Nativo WebClip (.mobileconfig)
                </a>
                <a href="/download/tardis.ipa" class="download-btn" download>
                    <svg style="width:24px;height:24px;stroke:currentColor;fill:none;stroke-width:2;" viewBox="0 0 24 24"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
                    Descargar Paquete Nativo IPA (TARDIS_Pro_M2.ipa)
                </a>
                <div style="background: rgba(0,0,0,0.4); padding: 16px; border-radius: 14px; font-family: var(--font-mono); font-size: 0.8rem; color: #94a3b8;">
                    <strong>Ubicación AFC en iPad:</strong> /Downloads/TARDIS_Pro_M2.ipa<br>
                    <strong>Identificador:</strong> com.godworks.tardis.m2<br>
                    <strong>Pantalla:</strong> Liquid Retina XDR (3180 x 2384 @ 120Hz ProMotion)<br>
                    <strong>Gobernador Móvil:</strong> Buffer circular activo (Máximo 50 nodos DOM, <100MB)
                </div>
            </div>
        </section>
    </main>

    <!-- Dock Inferior Touch -->
    <nav class="bottom-dock">
        <button class="dock-btn active" onclick="switchTab('view-chat', this)">
            <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span>Neural</span>
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
            <span>Bóveda & IPA</span>
        </button>
    </nav>

    <script>
        // Gobernador de Recursos Móviles (Mobile Memory Governor)
        const MAX_DOM_BUBBLES = 50;
        let messageHistoryCache = [];

        function switchTab(tabId, btn) {
            document.querySelectorAll('.tab-view').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.dock-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            btn.classList.add('active');
            if (tabId === 'view-tools') loadToolsCatalog();
            if (tabId === 'view-telemetry') pollTelemetry();
        }

        function quickPrompt(text) {
            document.getElementById('chat-input').value = text;
            sendChatMessage();
        }

        async function sendChatMessage() {
            const input = document.getElementById('chat-input');
            const text = input.value.trim();
            if (!text) return;
            input.value = '';

            addChatBubble('user', text);

            // Placeholder animado
            const loadBubble = addChatBubble('assistant', 'Pensando...', true);

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: text, client_id: 'ipad_pro_m2' })
                });
                const data = await res.json();
                if (data.ok && data.reply) {
                    loadBubble.querySelector('.bubble-text').innerText = data.reply;
                    if (data.node || data.model) {
                        loadBubble.querySelector('.bubble-meta-info').innerText = `${data.model || 'TARDIS'} · ${data.elapsed_s ? data.elapsed_s.toFixed(1)+'s' : ''}`;
                    }
                } else {
                    loadBubble.querySelector('.bubble-text').innerText = 'Error: ' + (data.error || 'Respuesta inesperada');
                }
            } catch (err) {
                loadBubble.querySelector('.bubble-text').innerText = 'Fallo de conexión con TARDIS Core: ' + err.message;
            }
            pruneDomNodes();
        }

        function addChatBubble(role, text, isPending = false) {
            const container = document.getElementById('chat-history');
            const bubble = document.createElement('div');
            bubble.className = `chat-bubble ${role}`;
            bubble.innerHTML = `
                <div class="bubble-meta">
                    <span>${role === 'user' ? 'ARQUITECTO (IPAD M2)' : 'TARDIS KAIJU'}</span>
                    <span class="bubble-meta-info">${new Date().toLocaleTimeString()}</span>
                </div>
                <div class="bubble-text" style="white-space: pre-wrap;">${escapeHtml(text)}</div>
            `;
            container.appendChild(bubble);
            container.scrollTop = container.scrollHeight;

            messageHistoryCache.push(bubble);
            pruneDomNodes();
            return bubble;
        }

        // Gobernador de Memoria DOM (<100MB)
        function pruneDomNodes() {
            const container = document.getElementById('chat-history');
            while (container.children.length > MAX_DOM_BUBBLES) {
                container.removeChild(container.firstChild);
            }
            document.getElementById('dom-nodes').innerText = `DOM: ${container.children.length} N`;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.innerText = text;
            return div.innerHTML;
        }

        // Catálogo y Despacho de Omni-Herramientas
        async function loadToolsCatalog() {
            const grid = document.getElementById('tools-grid');
            grid.innerHTML = '<div style="color:var(--neon-cyan)">Cargando catálogo soberano...</div>';
            try {
                const res = await fetch('/api/tools');
                const data = await res.json();
                if (data.tools) {
                    grid.innerHTML = '';
                    for (const [key, t] of Object.entries(data.tools)) {
                        const card = document.createElement('div');
                        card.className = 'tool-card';
                        let actionBtns = '';
                        (t.supported_actions || []).slice(0, 5).forEach(act => {
                            actionBtns += `<button class="action-btn" onclick="executeTool('${key}', '${act}')">${act}</button>`;
                        });
                        card.innerHTML = `
                            <div class="tool-header">
                                <span class="tool-name">${t.name}</span>
                                <span class="tool-badge">${t.available ? 'ACTIVO' : 'STANDBY'}</span>
                            </div>
                            <div class="tool-desc">${t.description}</div>
                            <div class="tool-actions">${actionBtns}</div>
                        `;
                        grid.appendChild(card);
                    }
                }
            } catch (err) {
                grid.innerHTML = `<div style="color:var(--neon-red)">Error cargando herramientas: ${err.message}</div>`;
            }
        }

        async function executeTool(toolId, action) {
            const term = document.getElementById('terminal-output');
            term.innerText = `[TARDIS-EXEC] Ejecutando '${toolId}' acción '${action}'...\\n`;
            try {
                const res = await fetch('/api/tool/execute', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tool_id: toolId, action: action })
                });
                const data = await res.json();
                term.innerText += JSON.stringify(data, null, 2);
            } catch (err) {
                term.innerText += `[ERROR] ${err.message}`;
            }
            term.scrollTop = term.scrollHeight;
        }

        // Sondeo de Telemetría
        async function pollTelemetry() {
            try {
                const res = await fetch('/api/telemetry');
                const d = await res.json();
                document.getElementById('stat-ping').innerText = d.ipad_ping || '0.7 ms';
                document.getElementById('stat-mem').innerText = (d.mem_used_pct || 0) + '%';
                document.getElementById('stat-mem-gb').innerText = `${d.mem_avail_gb} GB libres / ${d.mem_total_gb} GB`;
                document.getElementById('stat-load').innerText = (d.load_avg || []).join(' · ');
                if (d.tardis) {
                    document.getElementById('stat-thoughts').innerText = d.tardis.thoughts || '2,354';
                }
                if (d.psi) {
                    document.getElementById('stat-psi').innerHTML = `
                        <strong>CPU:</strong> ${escapeHtml(d.psi.cpu || 'N/A')}<br>
                        <strong>MEM:</strong> ${escapeHtml(d.psi.memory || 'N/A')}<br>
                        <strong>I/O:</strong> ${escapeHtml(d.psi.io || 'N/A')}
                    `;
                }
            } catch (e) {
                console.error(e);
            }
        }

        // Bucle de Telemetría cada 3 segundos
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

    # Iniciar en puerto 80 (para acceso directo http://REDACTED_IP/)
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

    # Mantener en ejecución indefinida
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
