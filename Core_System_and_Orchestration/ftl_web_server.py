"""
FTL Sovereign Web Portal & Telemetry Hub
Faster-Than-Light: Unified Anthropic Claude Code & Google AGY/Gemini Engine
Serves the responsive Web Terminal Dashboard on port 8765.
"""

import os
import sys
import json
import time
import socket
import base64
import io
import subprocess
from pathlib import Path
from typing import Dict, Any, List

import psutil
import qrcode
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# Include ~/.ftl in Python path
FTL_DIR = Path(__file__).parent
sys.path.insert(0, str(FTL_DIR))

try:
    from config import load_config
    from models import registry
except Exception:
    pass

app = FastAPI(title="FTL Sovereign Web Terminal", version="1.0.0")

def get_network_ips() -> List[Dict[str, str]]:
    """Discovers all non-loopback IPv4 addresses."""
    ips = []
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    ips.append({"interface": iface, "ip": addr.address})
    except Exception as e:
        ips.append({"interface": "unknown", "ip": "127.0.0.1"})
    return ips

def get_primary_lan_ip() -> str:
    """Returns the most likely LAN IP."""
    ips = get_network_ips()
    for item in ips:
        if item["ip"].startswith("192.168."):
            return item["ip"]
    for item in ips:
        if not item["ip"].startswith("127."):
            return item["ip"]
    return "127.0.0.1"

def get_gpu_info() -> Dict[str, Any]:
    """Queries NVIDIA GPU metrics via nvidia-smi if available."""
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,temperature.gpu",
            "--format=csv,noheader,nounits"
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=2).decode().strip()
        if out:
            parts = [p.strip() for p in out.split(",")]
            if len(parts) >= 4:
                return {
                    "available": True,
                    "name": parts[0],
                    "total_mb": int(parts[1]),
                    "used_mb": int(parts[2]),
                    "temp_c": int(parts[3])
                }
    except Exception:
        pass
    return {"available": False, "name": "N/A", "total_mb": 0, "used_mb": 0, "temp_c": 0}

def get_tardis_status() -> Dict[str, Any]:
    """Checks TARDIS Daemon status."""
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8757/health", headers={"User-Agent": "FTL-Web"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                return {"online": True, "details": data}
    except Exception:
        pass
    return {"online": False, "details": {"mode": "standby"}}

def get_imac_cluster_status() -> Dict[str, Any]:
    """Queries iMac 14,1 Ollama & cluster node status."""
    try:
        import urllib.request
        req = urllib.request.Request("http://REDACTED_IP:11434/api/tags", headers={"User-Agent": "FTL-Web"})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            if resp.status == 200:
                tags = json.loads(resp.read().decode())
                models = [m.get("name") for m in tags.get("models", [])]
                return {"online": True, "ip": "REDACTED_IP", "models": models}
    except Exception:
        pass
    return {"online": False, "ip": "REDACTED_IP", "models": []}

def get_ftl_stats() -> Dict[str, Any]:
    """Loads FTL stats ledger."""
    stats_file = Path.home() / ".config" / "ftl" / "stats.json"
    if stats_file.exists():
        try:
            return json.loads(stats_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "total_queries": 0,
        "estimated_tokens_saved": 0,
        "estimated_usd_saved": 0.0,
        "failovers_recovered": 0
    }

def generate_qr_base64(url: str) -> str:
    """Generates a base64 encoded PNG for a given URL."""
    qr = qrcode.QRCode(box_size=5, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#00ffcc", back_color="#0a0e17")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()



@app.post("/api/voice_command")
async def api_voice_command(request: Request):
    try:
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return JSONResponse({"status": "error", "error": "No text provided"})
        
        text_lower = text.lower()
        import subprocess
        output = ""
        
        # Lógica de tardis_voice_terminal
        if "lista los archivos" in text_lower or "listar archivos" in text_lower:
            res = subprocess.run("ls -la", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "qué hora es" in text_lower or "que hora es" in text_lower:
            res = subprocess.run("date", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "estado del sistema" in text_lower or "memoria" in text_lower:
            res = subprocess.run("free -h && df -h", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "limpiar" in text_lower or "borrar pantalla" in text_lower:
            res = subprocess.run("clear", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "quién soy" in text_lower or "quien soy" in text_lower:
            res = subprocess.run("whoami", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "procesos" in text_lower:
            res = subprocess.run("top -b -n 1 | head -n 15", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "crea un archivo" in text_lower or "crear un archivo" in text_lower:
            parts = text_lower.split("llamado")
            if len(parts) > 1:
                filename = parts[1].strip().replace(" ", "_") + ".txt"
                subprocess.run(f"touch {filename}", shell=True)
                output = f"Archivo {filename} creado."
        else:
            # Enviar a FTL HUB
            try:
                import requests
                FTL_HUB_API = "http://127.0.0.1:8757/api/chat?key=%s" % os.environ.get("GIA_AUTH_TOKEN", "") + ""
                payload = {"message": f"Desde terminal de voz FTL Web: {text}", "source": "voice"}
                response = requests.post(FTL_HUB_API, json=payload, timeout=5)
                if response.status_code == 200:
                    output = "TARDIS HUB: " + str(response.json().get('response', 'OK'))
            except Exception as e:
                output = "Comando recibido pero FTL HUB no está disponible: " + text

        return JSONResponse({"status": "ok", "text": text, "output": output})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

@app.get("/api/status")
async def api_status():
    """Returns real-time telemetry of system and FTL."""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    gpu = get_gpu_info()
    tardis = get_tardis_status()
    imac = get_imac_cluster_status()
    ftl = get_ftl_stats()
    ips = get_network_ips()

    return JSONResponse({
        "timestamp": time.time(),
        "hostname": socket.gethostname(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram": {
            "total_gb": round(mem.total / (1024**3), 1),
            "used_gb": round(mem.used / (1024**3), 1),
            "percent": mem.percent
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 1),
            "used_gb": round(disk.used / (1024**3), 1),
            "percent": disk.percent
        },
        "gpu": gpu,
        "tardis": tardis,
        "imac_cluster": imac,
        "ftl": ftl,
        "ips": ips,
        "primary_ip": get_primary_lan_ip()
    })


@app.get("/api/qr")
async def api_qr(url: str = None):
    """Returns QR code base64 for a specific URL."""
    target_url = url or f"http://{get_primary_lan_ip()}:8765"
    b64 = generate_qr_base64(target_url)
    return JSONResponse({"url": target_url, "qr": b64})


@app.get("/api/brightness")
async def api_get_brightness():
    """Returns real-time dual-node brightness telemetry."""
    try:
        res = subprocess.run(["/usr/local/bin/tardis-brightness", "--json"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3.0)
        if res.returncode == 0 and res.stdout.strip():
            return JSONResponse(json.loads(res.stdout.strip()))
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)
    return JSONResponse({"status": "error", "error": "command failed"}, status_code=500)


@app.post("/api/brightness")
async def api_set_brightness(request: Request):
    """Sets brightness for iMac, TUF, or all."""
    try:
        body = await request.json()
        val = str(body.get("value", 80))
        target = str(body.get("target", "all"))
        res = subprocess.run(["/usr/local/bin/tardis-brightness", val, target],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=6.0)
        return JSONResponse({"status": "ok", "target": target, "value": val, "output": res.stdout.strip()})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def portal_index(request: Request):
    """Serves the Sovereign FTL Web Dashboard with embedded terminal."""
    client_host = request.client.host if request.client else "localhost"
    primary_ip = get_primary_lan_ip()
    ips = get_network_ips()
    qr_portal = generate_qr_base64(f"http://{primary_ip}:8765")
    qr_term = generate_qr_base64(f"http://{primary_ip}:7681")

    # Generate IP list HTML
    ip_list_html = ""
    for item in ips:
        ip_list_html += f"""
        <div class="ip-chip" onclick="copyText('http://{item['ip']}:8765')">
            <span class="iface">{item['interface']}</span>
            <span class="addr">http://{item['ip']}:8765</span>
            <span class="copy-hint">📋</span>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover, interactive-widget=resizes-content">
    <title>FTL Sovereign Web Terminal :: Mascota TON 618</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌌</text></svg>">
    <style>
        :root {{
            --bg-base: #07090e;
            --bg-card: rgba(14, 20, 32, 0.75);
            --bg-card-hover: rgba(22, 32, 50, 0.85);
            --border-glow: rgba(0, 255, 204, 0.25);
            --border-glow-gold: rgba(255, 184, 108, 0.3);
            --neon-cyan: #00ffcc;
            --neon-gold: #ffb86c;
            --neon-green: #50fa7b;
            --neon-magenta: #bd93f9;
            --neon-red: #ff5555;
            --text-primary: #e2e8f0;
            --text-muted: #94a3b8;
            --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        html, body {{
            height: 100%;
            height: 100dvh;
            min-height: 100%;
            min-height: 100dvh;
            background: var(--bg-base);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            -webkit-text-size-adjust: 100%;
        }}

        /* Header Cyberpunk */
        header {{
            background: linear-gradient(180deg, rgba(16, 24, 39, 0.95) 0%, rgba(7, 9, 14, 0.85) 100%);
            border-bottom: 1px solid var(--border-glow);
            padding: 10px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 10px;
            backdrop-filter: blur(12px);
            z-index: 50;
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}

        .brand-icon {{
            font-size: 26px;
            animation: pulse-glow 2s infinite alternate;
        }}

        @keyframes pulse-glow {{
            0% {{ filter: drop-shadow(0 0 4px var(--neon-cyan)); transform: scale(1); }}
            100% {{ filter: drop-shadow(0 0 12px var(--neon-cyan)); transform: scale(1.05); }}
        }}

        .brand-title h1 {{
            font-family: var(--font-mono);
            font-size: 1.15rem;
            font-weight: 800;
            letter-spacing: 0.5px;
            background: linear-gradient(90deg, var(--neon-cyan), #38bdf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .brand-title .badge {{
            font-size: 0.72rem;
            padding: 2px 6px;
            border-radius: 4px;
            background: rgba(0, 255, 204, 0.12);
            color: var(--neon-cyan);
            border: 1px solid rgba(0, 255, 204, 0.3);
            font-family: var(--font-mono);
        }}

        /* Telemetry Badges in Header */
        .telemetry-row {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }}

        .badge-pill {{
            background: var(--bg-card);
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 4px 10px;
            border-radius: 6px;
            font-family: var(--font-mono);
            font-size: 0.75rem;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .badge-pill.status-online {{
            border-color: var(--neon-green);
            color: var(--neon-green);
        }}

        .dot-green {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--neon-green);
            box-shadow: 0 0 8px var(--neon-green);
            animation: blink 1.5s infinite;
        }}

        @keyframes blink {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.4; }}
        }}

        /* Action Buttons */
        .header-actions {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .btn {{
            background: var(--bg-card);
            color: var(--text-primary);
            border: 1px solid var(--border-glow);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.8rem;
            font-family: var(--font-mono);
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
            text-decoration: none;
        }}

        .btn:hover {{
            background: var(--bg-card-hover);
            border-color: var(--neon-cyan);
            box-shadow: 0 0 10px rgba(0, 255, 204, 0.2);
            color: var(--neon-cyan);
        }}

        .btn-gold {{
            border-color: var(--border-glow-gold);
            color: var(--neon-gold);
        }}
        .btn-gold:hover {{
            border-color: var(--neon-gold);
            box-shadow: 0 0 10px rgba(255, 184, 108, 0.25);
            color: #fff;
        }}

        /* Command Quick Bar */
        .quickbar {{
            background: #090d14;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding: 6px 14px;
            display: flex;
            align-items: center;
            gap: 6px;
            overflow-x: auto;
            white-space: nowrap;
        }}

        .quickbar::-webkit-scrollbar {{
            height: 4px;
        }}
        .quickbar::-webkit-scrollbar-thumb {{
            background: var(--border-glow);
            border-radius: 2px;
        }}

        .quickbar-label {{
            font-family: var(--font-mono);
            font-size: 0.72rem;
            color: var(--text-muted);
            text-transform: uppercase;
            margin-right: 4px;
        }}

        .cmd-chip {{
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #cbd5e1;
            padding: 3px 8px;
            border-radius: 4px;
            font-family: var(--font-mono);
            font-size: 0.75rem;
            cursor: pointer;
            transition: all 0.15s ease;
        }}

        .cmd-chip:hover {{
            background: rgba(0, 255, 204, 0.15);
            border-color: var(--neon-cyan);
            color: var(--neon-cyan);
            transform: translateY(-1px);
        }}

        /* Main Container with Iframe Terminal - WebKit / iPadOS Optimized */
        main {{
            flex: 1 1 auto;
            min-height: 0;
            min-width: 0;
            display: flex;
            flex-direction: column;
            position: relative;
            background: #0a0e17;
            overflow: hidden;
        }}

        .terminal-frame-container {{
            flex: 1 1 auto;
            min-height: 0;
            min-width: 0;
            width: 100%;
            height: 100%;
            position: relative;
            overflow: hidden;
            -webkit-overflow-scrolling: touch;
        }}

        iframe#terminal-frame {{
            width: 100%;
            height: 100%;
            min-height: 100%;
            border: none;
            display: block;
            background: #0a0e17;
        }}

        /* Fullscreen Viewport Mode */
        .fullscreen-active header,
        .fullscreen-active .quickbar,
        .fullscreen-active .drawer-bar,
        .compact-active header,
        .compact-active .quickbar,
        .compact-active .drawer-bar {{
            display: none !important;
        }}
        .fullscreen-active .terminal-frame-container,
        .compact-active .terminal-frame-container {{
            height: 100% !important;
            height: 100dvh !important;
        }}

        /* Floating Controls in Terminal */
        .terminal-overlay-controls {{
            position: absolute;
            top: 10px;
            right: 18px;
            display: flex;
            gap: 6px;
            z-index: 10;
            opacity: 0.4;
            transition: opacity 0.2s ease;
        }}
        .terminal-overlay-controls:hover {{
            opacity: 1;
        }}

        .btn-overlay {{
            background: rgba(10, 14, 23, 0.85);
            border: 1px solid var(--border-glow);
            color: var(--neon-cyan);
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-family: var(--font-mono);
            cursor: pointer;
            backdrop-filter: blur(6px);
        }}

        /* Drawer / Details Panel */
        .drawer-bar {{
            background: rgba(10, 14, 23, 0.95);
            border-top: 1px solid var(--border-glow);
            padding: 8px 16px;
            font-size: 0.8rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }}

        .ip-chips {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}

        .ip-chip {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 4px;
            padding: 3px 8px;
            font-family: var(--font-mono);
            font-size: 0.75rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 5px;
            transition: all 0.2s ease;
        }}

        .ip-chip:hover {{
            border-color: var(--neon-cyan);
            background: rgba(0, 255, 204, 0.1);
        }}

        .ip-chip .iface {{
            color: var(--neon-gold);
            font-weight: bold;
        }}
        .ip-chip .addr {{
            color: #f1f5f9;
        }}

        /* Modal QR */
        .modal-backdrop {{
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(8px);
            z-index: 100;
            align-items: center;
            justify-content: center;
        }}

        .modal-box {{
            background: #0f172a;
            border: 1px solid var(--neon-cyan);
            box-shadow: 0 0 30px rgba(0, 255, 204, 0.3);
            border-radius: 12px;
            padding: 24px;
            max-width: 440px;
            width: 90%;
            text-align: center;
        }}

        .modal-box h3 {{
            font-family: var(--font-mono);
            color: var(--neon-cyan);
            margin-bottom: 12px;
        }}

        .qr-display {{
            display: flex;
            justify-content: center;
            gap: 20px;
            margin: 16px 0;
            flex-wrap: wrap;
        }}

        .qr-card {{
            background: #07090e;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}

        .qr-card img {{
            width: 140px;
            height: 140px;
            display: block;
            margin: 0 auto 8px auto;
            border-radius: 4px;
        }}

        .qr-card span {{
            font-family: var(--font-mono);
            font-size: 0.75rem;
            color: var(--text-muted);
        }}

        /* Toast notification */
        #toast {{
            visibility: hidden;
            min-width: 200px;
            background-color: var(--neon-cyan);
            color: #07090e;
            text-align: center;
            border-radius: 6px;
            padding: 8px 16px;
            position: fixed;
            z-index: 200;
            left: 50%;
            bottom: 30px;
            transform: translateX(-50%);
            font-family: var(--font-mono);
            font-weight: bold;
            font-size: 0.85rem;
            box-shadow: 0 0 15px rgba(0, 255, 204, 0.6);
        }}

        #toast.show {{
            visibility: visible;
            animation: fadein 0.3s, fadeout 0.3s 2s;
        }}

        @keyframes fadein {{
            from {{ bottom: 0; opacity: 0; }}
            to {{ bottom: 30px; opacity: 1; }}
        }}

        @keyframes fadeout {{
            from {{ bottom: 30px; opacity: 1; }}
            to {{ bottom: 0; opacity: 0; }}
        }}

        @media (max-width: 768px) {{
            header {{
                padding: 8px 12px;
            }}
            .telemetry-row {{
                display: none;
            }}
            .terminal-frame-container {{
                height: calc(100vh - 100px);
            }}
        }}
    </style>
</head>
<body>

    <!-- Header -->
    <header>
        <div class="brand">
            <span class="brand-icon" title="Mascota Oficial FTL: TON 618 (Singularidad Cuántica · 66B M☉)">🌌</span>
            <div class="brand-title">
                <h1>FTL SOVEREIGN WEB TERMINAL</h1>
                <div style="display: flex; gap: 6px; align-items: center; margin-top: 2px;">
                    <span class="badge">APEX ENGINE</span>
                    <span class="badge" style="color: var(--neon-cyan); border-color: var(--border-glow);">MASCOTA: TON 618</span>
                    <span class="badge" style="color: var(--neon-gold); border-color: var(--border-glow-gold);">TARDIS KAIJU</span>
                </div>
            </div>
        </div>

        <div class="telemetry-row">
            <div class="badge-pill status-online">
                <span class="dot-green"></span>
                <span>LAN ACTIVA</span>
            </div>
            <div class="badge-pill" id="cpu-pill">CPU: --%</div>
            <div class="badge-pill" id="ram-pill">RAM: -- GB</div>
            <div class="badge-pill" id="gpu-pill">GPU: --°C</div>
            <div class="badge-pill" id="tardis-pill" style="border-color: var(--neon-magenta); color: var(--neon-magenta);">TARDIS :8757</div>
            <div class="badge-pill" id="imac-pill" style="border-color: var(--neon-cyan); color: var(--neon-cyan);">iMac: PING...</div>
        </div>

        <div class="header-actions">
                        <button class="btn" onclick="openBrightnessModal()" style="border-color: var(--neon-cyan); color: var(--neon-cyan);" title="Control de Brillo Dual (iMac & TUF)">🔆 Brillo</button>
            <button class="btn" onclick="startVoiceRecognition()" style="border-color: var(--neon-magenta); color: var(--neon-magenta);" title="Control por Voz FTL">🎤 Hablar</button>
            <button class="btn btn-gold" onclick="openQrModal()">📱 Código QR</button>
            <button class="btn" onclick="toggleCompactMode()" title="Maximizar espacio de terminal en iPad y tablets">📱 Maximizar</button>
            <a href="#" onclick="window.open(termUrl, '_blank'); return false;" class="btn" title="Abrir terminal nativa en pestaña separada">↗ Nativo :7681</a>
            <button class="btn" onclick="toggleFullscreen()" title="Pantalla Completa">⛶ Pantalla</button>
        </div>
    </header>

    <!-- Quick Commands Bar -->
    <div class="quickbar">
        <span class="quickbar-label">⚡ Comandos:</span>
        <span class="cmd-chip" onclick="openBrightnessModal()" style="border-color: var(--neon-cyan); color: var(--neon-cyan);">🔆 Brillo Dual</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':help')">:help</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':stats')">:stats</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':history')">:history</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':context')">:context</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':synth')">:synth</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':audit')">:audit</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':infinite')">:infinite</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':kaiju')">:kaiju</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':rails')">:rails</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':models')">:models</span>
        <span class="cmd-chip" onclick="handleQuickCmd(':heal')">:heal</span>
        <span class="cmd-chip" onclick="handleQuickCmd('$ git status')">$ git status</span>
        <span class="cmd-chip" onclick="handleQuickCmd('$ htop')">$ htop</span>
        <span class="cmd-chip" onclick="handleQuickCmd('$ df -h')">$ df -h</span>
        <span class="cmd-chip" onclick="reloadTerminal()" style="border-color: var(--neon-gold); color: var(--neon-gold);">🔄 Reiniciar Terminal</span>
    </div>

    <!-- Terminal Container -->
    <main>
        <div class="terminal-overlay-controls">
            <button class="btn-overlay" onclick="toggleCompactMode()" title="Alternar interfaz / espacio completo iPad">📱 Interfaz</button>
            <button class="btn-overlay" onclick="reloadTerminal()">🔄 Recargar</button>
            <button class="btn-overlay" onclick="toggleFullscreen()">⛶ Fullscreen</button>
        </div>
        <div class="terminal-frame-container" id="frame-container">
            <iframe id="terminal-frame" src="" allow="fullscreen" allowfullscreen></iframe>
        </div>
    </main>

    <!-- Footer Drawer -->
    <div class="drawer-bar">
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-family: var(--font-mono); color: var(--text-muted); font-size: 0.75rem;">DIRECCIONES EN TU RED:</span>
            <div class="ip-chips">
                {ip_list_html}
            </div>
        </div>
        <div style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-muted);">
            Estación: <strong style="color: #fff;">ASUS TUF A15</strong> (Linux x86_64)
        </div>
    </div>

    <!-- Modal QR -->
    <div class="modal-backdrop" id="qr-modal" onclick="closeQrModal(event)">
        <div class="modal-box" onclick="event.stopPropagation()">
            <h3>📱 ESCANEAR DESDE TU TELÉFONO O TABLET</h3>
            <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 12px;">Conéctate a la misma red Wi-Fi y escanea para abrir la terminal web al instante:</p>
            <div class="qr-display">
                <div class="qr-card">
                    <img src="{qr_portal}" alt="QR Portal 8765">
                    <span>Portal Completo (:8765)</span>
                </div>
                <div class="qr-card">
                    <img src="{qr_term}" alt="QR Terminal 7681">
                    <span>Terminal Directa (:7681)</span>
                </div>
            </div>
            <button class="btn" style="margin: 0 auto;" onclick="closeQrModal()">Entendido / Cerrar</button>
        </div>
    </div>

    <!-- Modal Brillo Dual -->
    <div class="modal-backdrop" id="brightness-modal" style="display: none;" onclick="closeBrightnessModal(event)">
        <div class="modal-box" onclick="event.stopPropagation()" style="max-width: 480px;">
            <h3 style="color: var(--neon-cyan);">🔆 CONTROL DE BRILLO SOBERANO DUAL</h3>
            <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 16px;">Control en tiempo real de pantallas iMac y ASUS TUF desde cualquier nodo:</p>
            
            <!-- iMac Control -->
            <div style="background: rgba(0,0,0,0.4); border: 1px solid var(--border-glow); border-radius: 8px; padding: 12px; margin-bottom: 12px; text-align: left;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span style="font-weight: bold; color: var(--neon-cyan);">🖥️ iMac 21.5" (Panel Interno)</span>
                    <span id="imac-bright-val" style="font-family: var(--font-mono); color: var(--neon-cyan); font-weight: bold;">--%</span>
                </div>
                <input type="range" id="imac-slider" min="10" max="100" value="80" style="width: 100%; accent-color: var(--neon-cyan); cursor: pointer;" onchange="setBrightness('imac', this.value)" oninput="document.getElementById('imac-bright-val').innerText = this.value + '%'">
                <div style="display: flex; gap: 6px; margin-top: 8px;">
                    <button class="btn" style="flex: 1; padding: 4px;" onclick="setBrightness('imac', 30)">30%</button>
                    <button class="btn" style="flex: 1; padding: 4px;" onclick="setBrightness('imac', 50)">50%</button>
                    <button class="btn" style="flex: 1; padding: 4px;" onclick="setBrightness('imac', 80)">80%</button>
                    <button class="btn" style="flex: 1; padding: 4px;" onclick="setBrightness('imac', 100)">100%</button>
                </div>
            </div>

            <!-- TUF Control -->
            <div style="background: rgba(0,0,0,0.4); border: 1px solid var(--border-glow-gold); border-radius: 8px; padding: 12px; margin-bottom: 12px; text-align: left;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span style="font-weight: bold; color: var(--neon-gold);">💻 ASUS TUF A15 (Monitores Externos)</span>
                    <span id="tuf-bright-val" style="font-family: var(--font-mono); color: var(--neon-gold); font-weight: bold;">--%</span>
                </div>
                <input type="range" id="tuf-slider" min="10" max="100" value="80" style="width: 100%; accent-color: var(--neon-gold); cursor: pointer;" onchange="setBrightness('tuf', this.value)" oninput="document.getElementById('tuf-bright-val').innerText = this.value + '%'">
                <div style="display: flex; gap: 6px; margin-top: 8px;">
                    <button class="btn" style="flex: 1; padding: 4px;" onclick="setBrightness('tuf', 30)">30%</button>
                    <button class="btn" style="flex: 1; padding: 4px;" onclick="setBrightness('tuf', 50)">50%</button>
                    <button class="btn" style="flex: 1; padding: 4px;" onclick="setBrightness('tuf', 80)">80%</button>
                    <button class="btn" style="flex: 1; padding: 4px;" onclick="setBrightness('tuf', 100)">100%</button>
                </div>
            </div>

            <!-- Both / All Control -->
            <div style="display: flex; gap: 8px; margin-bottom: 16px;">
                <button class="btn btn-gold" style="flex: 1;" onclick="setBrightness('all', 50)">🌓 Ambos 50%</button>
                <button class="btn btn-gold" style="flex: 1;" onclick="setBrightness('all', 80)">🌕 Ambos 80%</button>
                <button class="btn btn-gold" style="flex: 1;" onclick="setBrightness('all', 100)">☀️ Ambos 100%</button>
            </div>

            <button class="btn" style="margin: 0 auto; display: block;" onclick="closeBrightnessModal()">Cerrar</button>
        </div>
    </div>

    <!-- Toast -->
    <div id="toast">Comando copiado al portapapeles</div>

    <script>
        // Set dynamic terminal iframe URL using the browser's current host
        const termPort = '7681';
        const termHost = window.location.hostname || '{primary_ip}';
        const termUrl = window.location.protocol + '//' + termHost + ':' + termPort;
        document.getElementById('terminal-frame').src = termUrl;
                function startVoiceRecognition() {{
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {{
                showToast("Tu navegador no soporta control por voz.");
                return;
            }}
            const recognition = new SpeechRecognition();
            recognition.lang = 'es-ES';
            recognition.interimResults = false;
            recognition.maxAlternatives = 1;
            
            showToast("🎤 Escuchando... Di un comando.");
            
            recognition.onresult = async function(event) {{
                const transcript = event.results[0][0].transcript;
                showToast("Procesando: " + transcript);
                
                // Opción 1: Enviar al backend para que lo ejecute el sistema
                try {{
                    const res = await fetch('/api/voice_command', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{text: transcript}})
                    }});
                    if (res.ok) {{
                        const data = await res.json();
                        if (data.output) {{
                            showToast("Salida: " + data.output.substring(0, 100) + "...");
                        }} else {{
                            showToast("✅ Comando ejecutado: " + transcript);
                        }}
                    }}
                }} catch(e) {{
                    // Fallback
                    showToast("Error enviando comando");
                }}
                
                // Opción 2: También copiar al portapapeles por si quiere pegarlo en ttyd
                navigator.clipboard.writeText(transcript).catch(e=>console.log(e));
            }};
            
            recognition.onerror = function(event) {{
                showToast("Error de voz: " + event.error);
            }};
            
            recognition.start();
        }}

        function showToast(msg) {{
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.className = 'show';
            setTimeout(() => {{ t.className = t.className.replace('show', ''); }}, 2200);
        }}

        function copyText(txt) {{
            navigator.clipboard.writeText(txt).then(() => {{
                showToast('Copiado: ' + txt);
            }}).catch(() => {{
                showToast('URL: ' + txt);
            }});
        }}

        function handleQuickCmd(cmd) {{
            navigator.clipboard.writeText(cmd).then(() => {{
                showToast('Copiado: ' + cmd + ' (Pega en la terminal)');
            }});
        }}

        function reloadTerminal() {{
            const frame = document.getElementById('terminal-frame');
            frame.src = frame.src;
            showToast('Recargando terminal web...');
        }}

        function toggleFullscreen() {{
            const elem = document.documentElement;
            if (!document.fullscreenElement) {{
                if (elem.requestFullscreen) {{
                    elem.requestFullscreen();
                }} else if (elem.webkitRequestFullscreen) {{
                    elem.webkitRequestFullscreen();
                }}
                document.body.classList.add('fullscreen-active');
            }} else {{
                if (document.exitFullscreen) {{
                    document.exitFullscreen();
                }}
                document.body.classList.remove('fullscreen-active');
            }}
        }}

        function toggleCompactMode() {{
            document.body.classList.toggle('compact-active');
            const isCompact = document.body.classList.contains('compact-active');
            showToast(isCompact ? 'Terminal maximizada (Espacio completo)' : 'Interfaz FTL restaurada');
            const frame = document.getElementById('terminal-frame');
            if (frame) {{
                frame.style.height = '100%';
            }}
        }}

        // iPad / Mobile Viewport Adapter
        if (window.visualViewport) {{
            window.visualViewport.addEventListener('resize', () => {{
                const h = window.visualViewport.height;
                if (h < 520 && !document.body.classList.contains('compact-active') && !document.body.classList.contains('fullscreen-active')) {{
                    document.body.classList.add('compact-active');
                    showToast('Teclado detectado: Modo compacto activo para iPad');
                }}
            }});
        }}

        document.addEventListener('fullscreenchange', () => {{
            if (!document.fullscreenElement) {{
                document.body.classList.remove('fullscreen-active');
            }}
        }});

        function openQrModal() {{
            document.getElementById('qr-modal').style.display = 'flex';
        }}

        function closeQrModal() {{
            document.getElementById('qr-modal').style.display = 'none';
        }}

        async function openBrightnessModal() {{
            document.getElementById('brightness-modal').style.display = 'flex';
            try {{
                const res = await fetch('/api/brightness');
                if (res.ok) {{
                    const d = await res.json();
                    const nodes = d.nodes || {{}};
                    if (nodes.imac && nodes.imac.brightness) {{
                        document.getElementById('imac-slider').value = nodes.imac.brightness;
                        document.getElementById('imac-bright-val').innerText = nodes.imac.brightness + '%';
                    }}
                    if (nodes.tuf && nodes.tuf.brightness) {{
                        document.getElementById('tuf-slider').value = nodes.tuf.brightness;
                        document.getElementById('tuf-bright-val').innerText = nodes.tuf.brightness + '%';
                    }}
                }}
            }} catch(e) {{}}
        }}

        function closeBrightnessModal(e) {{
            if (!e || e.target.id === 'brightness-modal' || !e.target) {{
                document.getElementById('brightness-modal').style.display = 'none';
            }}
        }}

        async function setBrightness(target, val) {{
            showToast('Ajustando brillo ' + target.toUpperCase() + ': ' + val + '%...');
            try {{
                if (target === 'imac' || target === 'all') {{
                    document.getElementById('imac-slider').value = val;
                    document.getElementById('imac-bright-val').innerText = val + '%';
                }}
                if (target === 'tuf' || target === 'all') {{
                    document.getElementById('tuf-slider').value = val;
                    document.getElementById('tuf-bright-val').innerText = val + '%';
                }}
                const res = await fetch('/api/brightness', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{target: target, value: parseInt(val)}})
                }});
                if (res.ok) {{
                    showToast('✅ Brillo ' + target.toUpperCase() + ' fijado en ' + val + '%');
                }} else {{
                    showToast('⚠️ Error ajustando brillo');
                }}
            }} catch(e) {{
                showToast('Error de conexión');
            }}
        }}

        // Telemetry Polling
        async function updateTelemetry() {{
            try {{
                const res = await fetch('/api/status');
                if (!res.ok) return;
                const d = await res.json();

                document.getElementById('cpu-pill').innerText = 'CPU: ' + d.cpu_percent + '%';
                document.getElementById('ram-pill').innerText = 'RAM: ' + d.ram.used_gb + '/' + d.ram.total_gb + ' GB';

                if (d.gpu && d.gpu.available) {{
                    document.getElementById('gpu-pill').innerText = 'GPU: ' + d.gpu.temp_c + '°C';
                }} else {{
                    document.getElementById('gpu-pill').innerText = 'GPU: STANDBY';
                }}

                if (d.tardis && d.tardis.online) {{
                    document.getElementById('tardis-pill').innerText = 'TARDIS: ONLINE';
                    document.getElementById('tardis-pill').style.borderColor = 'var(--neon-green)';
                    document.getElementById('tardis-pill').style.color = 'var(--neon-green)';
                }} else {{
                    document.getElementById('tardis-pill').innerText = 'TARDIS: STANDBY';
                    document.getElementById('tardis-pill').style.borderColor = 'var(--neon-gold)';
                    document.getElementById('tardis-pill').style.color = 'var(--neon-gold)';
                }}

                if (d.imac_cluster && d.imac_cluster.online) {{
                    const mCount = d.imac_cluster.models ? d.imac_cluster.models.length : 0;
                    document.getElementById('imac-pill').innerText = 'iMac 14,1: ' + mCount + 'm';
                    document.getElementById('imac-pill').style.borderColor = 'var(--neon-cyan)';
                    document.getElementById('imac-pill').style.color = 'var(--neon-cyan)';
                }} else {{
                    document.getElementById('imac-pill').innerText = 'iMac: STANDBY';
                    document.getElementById('imac-pill').style.borderColor = '#555';
                    document.getElementById('imac-pill').style.color = '#777';
                }}
            }} catch (e) {{}}
        }}

        setInterval(updateTelemetry, 4000);
        updateTelemetry();
    </script>
</body>
</html>
"""
    return html


def start_server(host: str = "0.0.0.0", port: int = 8765):
    """Starts the FastAPI Web Portal."""
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    start_server()
