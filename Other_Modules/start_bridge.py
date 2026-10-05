"""
start_bridge.py - Puente de Internet Resiliente y Supervisor de Acceso Remoto
=============================================================================
GODWORKS SYSTEM / GIA Ecosystem

Proporciona un enlace seguro, cifrado (HTTPS / WSS) y de alta estabilidad
para conectar tu celular (iPhone / Android), laptop o navegador desde
cualquier parte del mundo a tu servidor local de GIA.

Características:
  1. Detección automática de cloudflared (túnel Edge Anycast de Cloudflare).
  2. Levantamiento y supervisión de gia_web_server.py en el puerto local.
  3. Token de autenticación persistente (no cambia en cada reinicio).
  4. Generación de código QR en terminal y archivo HTML para escaneo directo con cámara móvil.
  5. Watchdog de auto-reconexión ante caídas de red o cambio de Wi-Fi.
  6. Exportación de estado a bridge_status.json y CURRENT_TUNNEL_URL.txt.
  7. Compatible con túneles efímeros rápidos y túneles permanentes (Named Tunnels).

Uso:
    python start_bridge.py
    python start_bridge.py --port 8757 --model llama3.1:8b
    python start_bridge.py --tunnel-token <CLOUDFLARE_NAMED_TUNNEL_TOKEN>
    python start_bridge.py --no-auth
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen, Request

BASE_DIR = Path(__file__).resolve().parent
TOKEN_FILE = BASE_DIR / "gia_bridge_token.txt"
STATUS_FILE = BASE_DIR / "bridge_status.json"
URL_FILE = BASE_DIR / "CURRENT_TUNNEL_URL.txt"
DASHBOARD_FILE = BASE_DIR / "bridge_dashboard.html"

# Colores ANSI para terminal
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_DIM = "\033[90m"
C_RED = "\033[91m"
C_MAGENTA = "\033[95m"
C_BOLD = "\033[1m"
C_RESET = "\033[0m"

os.system("")  # Habilitar ANSI en Windows Console


def find_python() -> str:
    """Encuentra el intérprete de Python preferido (.venv o actual)."""
    candidates = [
        BASE_DIR / ".venv-linux" / "bin" / "python3",
        BASE_DIR / ".venv" / "bin" / "python3",
        BASE_DIR / ".venv-build-v60" / "Scripts" / "python.exe",
        BASE_DIR / ".venv-build-v51" / "Scripts" / "python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "vw-control" / ".venv" / "Scripts" / "python.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return sys.executable


def find_cloudflared() -> str | None:
    """Busca el ejecutable de cloudflared en rutas del sistema."""
    exe = shutil.which("cloudflared")
    if exe:
        return exe

    candidates = [
        Path("/usr/local/bin/cloudflared"),
        Path("/usr/bin/cloudflared"),
        Path("/opt/cloudflared/cloudflared"),
        Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"),
        Path(r"C:\Program Files\cloudflared\cloudflared.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe",
    ]
    pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if pkgs.is_dir():
        for p in pkgs.glob("Cloudflare.cloudflared*/**/cloudflared.exe"):
            candidates.append(p)

    for c in candidates:
        if c and c.is_file():
            return str(c)
    return None


def get_lan_ip() -> str:
    """Obtiene la dirección IP en la red local."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("REDACTED_IP", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "REDACTED_IP"


def is_port_open(port: int, host: str = "REDACTED_IP") -> bool:
    """Comprueba si el puerto local está respondiendo."""
    try:
        with socket.create_connection((host, port), timeout=1.2):
            return True
    except Exception:
        return False


def check_health(port: int) -> bool:
    """Verifica si el servidor GIA responde al endpoint de salud."""
    try:
        req = Request(f"http://REDACTED_IP:{port}/health", headers={"User-Agent": "GIA-Bridge-Watchdog/1.0"})
        with urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return is_port_open(port)


def get_or_create_token(custom_token: str | None = None) -> str:
    """Obtiene o genera un token seguro y persistente."""
    if custom_token:
        TOKEN_FILE.write_text(custom_token.strip(), encoding="utf-8")
        return custom_token.strip()

    env_tok = os.environ.get("GIA_AUTH_TOKEN", "").strip()
    if env_tok:
        return env_tok

    if TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(tok) >= 8:
            return tok

    new_tok = secrets.token_urlsafe(16)
    TOKEN_FILE.write_text(new_tok, encoding="utf-8")
    return new_tok


def print_ascii_qr(data: str):
    """Renderiza un código QR en la consola con caracteres ANSI/Unicode."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        matrix = qr.get_matrix()

        print(f"\n{C_BOLD}  ESCANEA CON LA CÁMARA DE TU CELULAR (IPHONE / ANDROID):{C_RESET}")
        for r in range(0, len(matrix), 2):
            line = "    "
            for c in range(len(matrix[0])):
                top = matrix[r][c]
                bottom = matrix[r + 1][c] if r + 1 < len(matrix) else False
                if top and bottom:
                    line += " "
                elif top and not bottom:
                    line += "▄"
                elif not top and bottom:
                    line += "▀"
                else:
                    line += "█"
            print(line)
        print()
    except Exception:
        pass


def generate_dashboard_html(public_url: str, auth_url: str, local_url: str, token: str, model: str):
    """Genera un panel HTML interactivo con diseño cibernético y QR SVG en vivo."""
    encoded_url = auth_url.replace("&", "&amp;")
    qr_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=260x260&amp;data={auth_url}"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GIA · Puente de Enlace Cuántico &amp; Remoto</title>
    <style>
        :root {{
            --bg: #06090e;
            --panel: #0b111a;
            --panel-border: #1a2736;
            --teal: #00d4c8;
            --gold: #e8b64a;
            --text: #e2e8f0;
            --text-dim: #7e8c9f;
            --purple: #b39ddb;
            --glow: rgba(0, 212, 200, 0.25);
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            background-image: 
                radial-gradient(ellipse at 50% 0%, rgba(0,212,200,0.12) 0%, transparent 60%),
                radial-gradient(circle at 85% 80%, rgba(232,182,74,0.06) 0%, transparent 50%);
        }}
        .container {{
            max-width: 780px;
            width: 100%;
            background: var(--panel);
            border: 1px solid var(--panel-border);
            border-radius: 16px;
            padding: 30px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6), 0 0 30px var(--glow);
            position: relative;
            overflow: hidden;
        }}
        .container::before {{
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 3px;
            background: linear-gradient(90deg, var(--teal), var(--gold), var(--purple));
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 25px;
            border-bottom: 1px solid var(--panel-border);
            padding-bottom: 16px;
        }}
        .title {{
            font-size: 20px;
            font-weight: 700;
            letter-spacing: 1px;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .title span {{
            color: var(--teal);
            font-family: monospace;
            font-size: 14px;
            padding: 2px 8px;
            background: rgba(0,212,200,0.12);
            border: 1px solid var(--teal);
            border-radius: 4px;
        }}
        .status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 6px 14px;
            border-radius: 20px;
            background: rgba(0, 212, 200, 0.15);
            border: 1px solid var(--teal);
            color: var(--teal);
            font-size: 13px;
            font-weight: 600;
        }}
        .status-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--teal);
            box-shadow: 0 0 8px var(--teal);
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.4; transform: scale(0.85); }}
        }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr 240px;
            gap: 25px;
            margin-bottom: 25px;
        }}
        @media (max-width: 650px) {{
            .grid {{ grid-template-columns: 1fr; }}
        }}
        .card {{
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--panel-border);
            border-radius: 12px;
            padding: 18px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .field-label {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-dim);
            font-weight: 600;
        }}
        .field-value {{
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid #1e2c3d;
            border-radius: 8px;
            padding: 10px 14px;
            font-family: monospace;
            font-size: 13px;
            word-break: break-all;
        }}
        .field-value a {{
            color: var(--teal);
            text-decoration: none;
            flex: 1;
        }}
        .field-value a:hover {{ text-decoration: underline; }}
        .btn-copy {{
            background: rgba(0, 212, 200, 0.12);
            border: 1px solid var(--teal);
            color: var(--teal);
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.2s;
            white-space: nowrap;
        }}
        .btn-copy:hover {{
            background: var(--teal);
            color: #000;
        }}
        .qr-box {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: #ffffff;
            border-radius: 12px;
            padding: 12px;
            box-shadow: 0 8px 25px rgba(0,0,0,0.5);
        }}
        .qr-box img {{
            width: 100%;
            height: auto;
            border-radius: 6px;
        }}
        .qr-caption {{
            color: #111;
            font-size: 11px;
            font-weight: 700;
            margin-top: 8px;
            text-align: center;
            letter-spacing: 0.5px;
        }}
        .instructions {{
            background: rgba(232, 182, 74, 0.04);
            border: 1px solid rgba(232, 182, 74, 0.2);
            border-radius: 12px;
            padding: 18px;
            font-size: 13px;
            line-height: 1.6;
        }}
        .instructions h4 {{
            color: var(--gold);
            margin-bottom: 8px;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .instructions ol {{
            padding-left: 20px;
            color: var(--text);
        }}
        .instructions li {{ margin-bottom: 6px; }}
        .footer {{
            margin-top: 20px;
            text-align: center;
            font-size: 11px;
            color: var(--text-dim);
            font-family: monospace;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">
                🌐 GIA PUENTE DE INTERNET <span>ACTIVO</span>
            </div>
            <div class="status-badge">
                <div class="status-dot"></div>
                ENLACE SEGURO GLOBAL
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <div>
                    <div class="field-label">Enlace Remoto Mundial (Con Token de Seguridad):</div>
                    <div class="field-value">
                        <a href="{auth_url}" target="_blank" id="authLink">{auth_url}</a>
                        <button class="btn-copy" onclick="navigator.clipboard.writeText('{auth_url}'); this.innerText='¡Copiado!'; setTimeout(()=>this.innerText='Copiar', 2000)">Copiar</button>
                    </div>
                </div>

                <div>
                    <div class="field-label">URL Base del Servidor (Para App iOS / API):</div>
                    <div class="field-value">
                        <span style="color:#fff; flex:1;">{public_url}</span>
                        <button class="btn-copy" onclick="navigator.clipboard.writeText('{public_url}'); this.innerText='¡Copiado!'; setTimeout(()=>this.innerText='Copiar', 2000)">Copiar</button>
                    </div>
                </div>

                <div>
                    <div class="field-label">Token Secreto de Acceso:</div>
                    <div class="field-value">
                        <span style="color:var(--gold); font-weight:700; flex:1;">{token}</span>
                        <button class="btn-copy" onclick="navigator.clipboard.writeText('{token}'); this.innerText='¡Copiado!'; setTimeout(()=>this.innerText='Copiar', 2000)">Copiar</button>
                    </div>
                </div>

                <div>
                    <div class="field-label">Enlace Local / Red Misma Wi-Fi:</div>
                    <div class="field-value">
                        <a href="{local_url}" target="_blank">{local_url}</a>
                    </div>
                </div>
            </div>

            <div class="qr-box">
                <img src="{qr_api_url}" alt="Código QR de Acceso">
                <div class="qr-caption">📱 ESCANEA CON TU CELULAR</div>
            </div>
        </div>

        <div class="instructions">
            <h4>📱 Cómo Conectar tu iPhone / iPad / Android desde Cualquier Lugar:</h4>
            <ol>
                <li><strong>Desde el Navegador (Safari / Chrome):</strong> Escanea el código QR de arriba o abre el <em>Enlace Remoto Mundial</em> en tu teléfono. Podrás chatear, ver sensores y usar la interfaz OMNI en cualquier red móvil.</li>
                <li><strong>Desde la App Nativa iOS de GIA:</strong> En los Ajustes de la App, coloca en <em>URL del Servidor</em>: <code style="color:var(--teal)">{public_url}</code> y en <em>Token</em>: <code style="color:var(--gold)">{token}</code>.</li>
                <li><strong>Instalar como App (PWA):</strong> En Safari en tu iPhone, pulsa el botón Compartir (el ícono de flecha hacia arriba) y selecciona <em>"Agregar a pantalla de inicio"</em>.</li>
            </ol>
        </div>

        <div class="footer">
            SISTEMA GODWORKS · GIA V26 ARCHITECT · MODELO: {model} · ACTUALIZADO: {now_str}
        </div>
    </div>
</body>
</html>"""
    DASHBOARD_FILE.write_text(html, encoding="utf-8")


def write_status(public_url: str | None, auth_url: str | None, local_url: str, token: str, is_online: bool, model: str):
    """Guarda el estado actual del túnel en archivos JSON y TXT."""
    data = {
        "online": is_online,
        "public_url": public_url or "",
        "auth_url": auth_url or "",
        "local_url": local_url,
        "token": token,
        "model": model,
        "timestamp": time.time(),
        "updated_at": datetime.datetime.now().isoformat(),
        "watchdog": True
    }
    STATUS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if public_url:
        URL_FILE.write_text(auth_url or public_url, encoding="utf-8")


def ensure_backend_running(python_bin: str, port: int, model: str, token: str, no_auth: bool) -> subprocess.Popen | None:
    """Verifica si el servidor web de GIA está activo; si no, lo inicia."""
    if check_health(port):
        print(f"{C_GREEN}[✓] Servidor local ya está respondiendo en http://REDACTED_IP:{port}{C_RESET}")
        return None

    print(f"{C_YELLOW}[*] Levantando servidor web GIA en el puerto {port}...{C_RESET}")
    cmd = [python_bin, str(BASE_DIR / "gia_web_server.py"), "--lan", "--port", str(port), "--model", model]
    if no_auth:
        cmd.append("--no-auth")
    else:
        cmd.extend(["--token", token])

    proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0)

    # Esperar hasta 20 segundos a que responda
    for _ in range(20):
        time.sleep(1)
        if check_health(port):
            print(f"{C_GREEN}[✓] Servidor GIA iniciado con éxito en http://REDACTED_IP:{port}{C_RESET}")
            return proc

    print(f"{C_YELLOW}[!] Advertencia: El servidor aún no responde /health; el túnel continuará esperando.{C_RESET}")
    return proc


def run_bridge_watchdog(port: int, model: str, token: str, no_auth: bool, tunnel_token: str | None = None):
    """Bucle supervisor de alta disponibilidad y auto-reconexión del túnel."""
    cf_bin = find_cloudflared()
    if not cf_bin:
        print(f"\n{C_RED}[ERROR] cloudflared no está instalado en este equipo.{C_RESET}")
        print(f"{C_YELLOW}Instálalo fácilmente ejecutando en PowerShell:{C_RESET}")
        print(f"  {C_CYAN}winget install Cloudflare.cloudflared{C_RESET}\n")
        return 1

    py_bin = find_python()
    lan_ip = get_lan_ip()
    local_url = f"http://{lan_ip}:{port}" + ("" if no_auth else f"/?key={token}")

    print(f"\n{C_CYAN}===================================================================={C_RESET}")
    print(f"{C_BOLD}{C_CYAN}         GODWORKS SYSTEM · PUENTE DE INTERNET RESILIENTE{C_RESET}")
    print(f"{C_CYAN}===================================================================={C_RESET}")
    print(f"{C_DIM}Python    : {py_bin}{C_RESET}")
    print(f"{C_DIM}Cloudflare: {cf_bin}{C_RESET}")
    print(f"{C_DIM}Puerto    : {port} (LAN: http://{lan_ip}:{port}){C_RESET}")
    if not no_auth:
        print(f"{C_DIM}Token     : {token}{C_RESET}")
    print(f"{C_CYAN}--------------------------------------------------------------------{C_RESET}\n")

    # 1. Asegurar Backend
    backend_proc = ensure_backend_running(py_bin, port, model, token, no_auth)

    url_regex = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
    retry_count = 0

    while True:
        try:
            print(f"{C_YELLOW}[*] Conectando túnel cifrado a la red global de Cloudflare...{C_RESET}")
            if tunnel_token:
                cf_args = [cf_bin, "tunnel", "run", "--token", tunnel_token]
            else:
                cf_args = [cf_bin, "tunnel", "--url", f"http://REDACTED_IP:{port}"]

            proc = subprocess.Popen(
                cf_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="ignore"
            )

            public_url = None
            auth_url = None

            for line in proc.stdout:
                m = url_regex.search(line)
                if m and not public_url:
                    public_url = m.group(0)
                    auth_url = public_url + ("" if no_auth else f"/?key={token}")
                    retry_count = 0

                    write_status(public_url, auth_url, local_url, token, True, model)
                    generate_dashboard_html(public_url, auth_url, local_url, token, model)

                    print(f"\n{C_GREEN}===================================================================={C_RESET}")
                    print(f"{C_BOLD}{C_GREEN}  🚀 ¡PUENTE GLOBAL ESTABLECIDO CON ÉXITO!{C_RESET}")
                    print(f"{C_GREEN}===================================================================={C_RESET}")
                    print(f"  {C_BOLD}URL Pública Remota :{C_RESET} {C_CYAN}{public_url}{C_RESET}")
                    print(f"  {C_BOLD}Enlace con Acceso  :{C_RESET} {C_GREEN}{auth_url}{C_RESET}")
                    print(f"  {C_BOLD}Enlace LAN Local   :{C_RESET} {C_DIM}{local_url}{C_RESET}")
                    if not no_auth:
                        print(f"  {C_BOLD}Token de Seguridad :{C_RESET} {C_YELLOW}{token}{C_RESET}")
                    print(f"{C_GREEN}--------------------------------------------------------------------{C_RESET}")

                    print_ascii_qr(auth_url)

                    print(f"  {C_BOLD}Dashboard Local    :{C_RESET} {DASHBOARD_FILE}")
                    print(f"  {C_DIM}Presiona Ctrl+C para detener el puente.{C_RESET}\n")

                elif not public_url and ("ERR" in line or "error" in line.lower()):
                    print(f"{C_DIM}  cf-log| {line.strip()[:100]}{C_RESET}")

            proc.wait()
            write_status(None, None, local_url, token, False, model)
            print(f"\n{C_YELLOW}[!] El túnel de Cloudflare se cerró o se reinició la conexión.{C_RESET}")

        except KeyboardInterrupt:
            print(f"\n{C_YELLOW}[*] Cerrando puente y limpiando procesos...{C_RESET}")
            try:
                proc.terminate()
            except Exception:
                pass
            write_status(None, None, local_url, token, False, model)
            break
        except Exception as e:
            print(f"{C_RED}[!] Error en el supervisor: {e}{C_RESET}")

        retry_count += 1
        wait_s = min(2 * (2 ** min(retry_count, 4)), 30)
        print(f"{C_YELLOW}[*] Reconectando túnel automáticamente en {wait_s}s (Intento #{retry_count})...{C_RESET}")
        time.sleep(wait_s)

    return 0


def main() -> int:
    try:
        import gia_sovereign_engine as _gse
        _def_model = _gse.get_engine().resolve_model()
    except Exception:
        _def_model = os.environ.get("GIA_MODEL", "Qwen3.8-27B-Uncensored-MLX:latest")
    ap = argparse.ArgumentParser(description="Supervisor de Puente de Internet para GIA / GODWORKS")
    ap.add_argument("--port", type=int, default=8757, help="Puerto local del servidor GIA (default: 8757)")
    ap.add_argument("--model", default=_def_model, help="Modelo de lenguaje a utilizar")
    ap.add_argument("--token", default=None, help="Token de autenticación fijo para el enlace")
    ap.add_argument("--tunnel-token", default=os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", None), help="Token de Named Tunnel permanente de Cloudflare")
    ap.add_argument("--no-auth", action="store_true", help="Desactivar verificación de token")
    args = ap.parse_args()

    token = "" if args.no_auth else get_or_create_token(args.token)
    return run_bridge_watchdog(
        port=args.port,
        model=args.model,
        token=token,
        no_auth=args.no_auth,
        tunnel_token=args.tunnel_token
    )


if __name__ == "__main__":
    raise SystemExit(main())
