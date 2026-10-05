"""
share_client_link.py - Servicio Autónomo y Enlace Continuo para Clientes (24/7)
================================================================================
Gestiona y mantiene activo de forma ininterrumpida el túnel público Cloudflare
hacia el servicio de clientes en el puerto 8757, con reconexión automática ante
caídas de red, monitoreo de salud constante y sincronización de enlaces.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LINK_FILE = DATA_DIR / "client_chat_link.txt"
JSON_FILE = DATA_DIR / "client_chat_link.json"
BRIDGE_STATUS_FILE = DATA_DIR / "bridge_status.json"
DESKTOP_FILE = Path.home() / "Escritorio" / "URL_CLIENTES_CHAT.txt"
LOG_FILE = DATA_DIR / "tunnel_client.log"

PORT = 8757
_SHUTDOWN = False


def sig_handler(signum, frame):
    global _SHUTDOWN
    _SHUTDOWN = True
    print(f"\n[CLIENT-SERVICE] Señal recibida ({signum}). Deteniendo servicio de forma segura...")


signal.signal(signal.SIGTERM, sig_handler)
signal.signal(signal.SIGINT, sig_handler)


def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("REDACTED_IP", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "REDACTED_IP"


def is_local_server_up(port: int = PORT, timeout: float = 1.5) -> bool:
    try:
        req = urllib.request.Request(
            f"http://REDACTED_IP:{port}/client",
            headers={"User-Agent": "ClientServiceMonitor/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 302, 307)
    except Exception:
        return False


def get_bridge_public_url() -> str | None:
    if not BRIDGE_STATUS_FILE.exists():
        return None
    try:
        data = json.loads(BRIDGE_STATUS_FILE.read_text(encoding="utf-8", errors="ignore"))
        if data.get("online") and data.get("public_url"):
            return data["public_url"].strip()
    except Exception:
        pass
    return None


def load_tunnel_config() -> dict:
    cfg_file = PROJECT_ROOT / "tunnel_config.json"
    defaults = {
        "client_permanent_portal_url": "https://ntfy.sh/godworks_sovereign_client_chat",
        "cloudflare_tunnel_token": "",
        "custom_permanent_url": "",
        "token": os.environ.get("GIA_AUTH_TOKEN", "").strip() or os.environ.get("GIA_TOKEN", "").strip(),
    }
    if cfg_file.exists():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            defaults.update(data)
        except Exception:
            pass
    return defaults


def sync_client_permanent_portal(client_url: str):
    cfg = load_tunnel_config()
    portal_url = cfg.get("client_permanent_portal_url") or "https://ntfy.sh/godworks_sovereign_client_chat"
    try:
        req = urllib.request.Request(
            portal_url,
            data=f"TARDIS CHAT CLIENTE ACTIVO\nEnlace: {client_url}".encode("utf-8"),
            headers={
                "Title": "TARDIS - Asistente de IA para Clientes",
                "Click": client_url,
                "Actions": f"view, Abrir Chat TARDIS, {client_url}",
                "Tags": "robot,speech_balloon"
            }
        )
        with urllib.request.urlopen(req, timeout=5.0):
            pass
    except Exception:
        pass


def generate_sovereign_portal_html(active_url: str):
    cfg = load_tunnel_config()
    portal_topic_url = cfg.get("client_permanent_portal_url") or "https://ntfy.sh/godworks_sovereign_client_chat"
    poll_api_url = f"{portal_topic_url}/json?poll=1"

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Portal Soberano TARDIS - Acceso Permanente para Clientes</title>
  <style>
    :root {{
      --bg: #070a12;
      --card: rgba(13, 18, 30, 0.85);
      --cyan: #00f2ff;
      --purple: #7928ca;
      --text: #e2e8f0;
      --muted: #94a3b8;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }}
    body {{
      background: radial-gradient(circle at 50% 30%, #111827 0%, var(--bg) 100%);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 20px;
      overflow-x: hidden;
    }}
    .stars {{
      position: fixed; top: 0; left: 0; width: 100%; height: 100%;
      background-image: radial-gradient(#00f2ff 1px, transparent 1px), radial-gradient(#7928ca 1px, transparent 1px);
      background-size: 50px 50px;
      background-position: 0 0, 25px 25px;
      opacity: 0.15;
      z-index: 0;
      pointer-events: none;
    }}
    .card {{
      position: relative;
      z-index: 1;
      background: var(--card);
      border: 1px solid rgba(0, 242, 255, 0.2);
      border-radius: 24px;
      padding: 40px 32px;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6), 0 0 30px rgba(0, 242, 255, 0.1);
      backdrop-filter: blur(12px);
    }}
    .avatar-wrapper {{
      position: relative;
      width: 110px;
      height: 110px;
      margin: 0 auto 24px;
    }}
    .rings {{
      position: absolute;
      top: -10px; left: -10px; right: -10px; bottom: -10px;
      border: 2px dashed rgba(0, 242, 255, 0.4);
      border-radius: 50%;
      animation: spin 16s linear infinite;
    }}
    @keyframes spin {{ 100% {{ transform: rotate(360deg); }} }}
    .avatar {{
      width: 100%; height: 100%;
      background: linear-gradient(135deg, #091326 0%, #1e1035 100%);
      border: 2px solid var(--cyan);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 42px;
      box-shadow: 0 0 25px rgba(0, 242, 255, 0.3);
    }}
    h1 {{
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 1px;
      background: linear-gradient(135deg, #ffffff 0%, var(--cyan) 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 8px;
    }}
    .subtitle {{
      font-size: 14px;
      color: var(--muted);
      margin-bottom: 24px;
      line-height: 1.5;
    }}
    .status-badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(0, 242, 255, 0.1);
      border: 1px solid rgba(0, 242, 255, 0.3);
      color: var(--cyan);
      padding: 6px 16px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 28px;
    }}
    .dot {{
      width: 8px; height: 8px;
      background: var(--cyan);
      border-radius: 50%;
      box-shadow: 0 0 10px var(--cyan);
      animation: pulse 1.5s infinite;
    }}
    @keyframes pulse {{ 0%, 100% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.4; transform: scale(0.85); }} }}
    .btn {{
      display: block;
      width: 100%;
      background: linear-gradient(135deg, var(--cyan) 0%, var(--purple) 100%);
      color: #050b14;
      font-weight: 700;
      font-size: 15px;
      padding: 14px 24px;
      border-radius: 14px;
      text-decoration: none;
      transition: all 0.25s ease;
      box-shadow: 0 4px 20px rgba(0, 242, 255, 0.3);
      border: none;
      cursor: pointer;
    }}
    .btn:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 25px rgba(0, 242, 255, 0.45);
      color: #ffffff;
    }}
    .info {{
      margin-top: 24px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.6;
    }}
  </style>
</head>
<body>
  <div class="stars"></div>
  <div class="card">
    <div class="avatar-wrapper">
      <div class="rings"></div>
      <div class="avatar">⏳</div>
    </div>
    <h1>TARDIS SOBERANO</h1>
    <p class="subtitle">Portal Permanente de Acceso para Clientes · Disponible 24/7 de forma indefinida</p>
    <div class="status-badge">
      <span class="dot"></span>
      <span id="status-text">Sincronizando con Núcleo Activo...</span>
    </div>
    <a id="connect-btn" class="btn" href="{active_url}">Entrar al Chat de TARDIS</a>
    <p class="info">
      Este portal soberano es permanente e invariable. Resuelve y conecta automáticamente con la instancia viva de TARDIS sin importar reinicios ni cambios de red.
    </p>
  </div>

  <script>
    const fallbackUrl = "{active_url}";
    const pollApi = "{poll_api_url}";

    async function resolveActiveLink() {{
      const btn = document.getElementById('connect-btn');
      const statusText = document.getElementById('status-text');

      try {{
        const resp = await fetch(pollApi, {{ cache: 'no-store' }});
        if (resp.ok) {{
          const text = await resp.text();
          const lines = text.trim().split('\\n');
          for (let i = lines.length - 1; i >= 0; i--) {{
            if (!lines[i]) continue;
            try {{
              const ev = JSON.parse(lines[i]);
              if (ev.click && ev.click.startsWith('http')) {{
                btn.href = ev.click;
                statusText.innerText = 'Núcleo En Línea · Redirigiendo...';
                setTimeout(() => {{ window.location.replace(ev.click); }}, 700);
                return;
              }}
            }} catch (e) {{}}
          }}
        }}
      }} catch (err) {{
        console.warn('Fallback al enlace preconfigurado:', err);
      }}

      if (fallbackUrl && fallbackUrl.startsWith('http')) {{
        btn.href = fallbackUrl;
        statusText.innerText = 'En Línea';
        setTimeout(() => {{ window.location.replace(fallbackUrl); }}, 1200);
      }} else {{
        statusText.innerText = 'Esperando conexión del servidor...';
      }}
    }}

    resolveActiveLink();
  </script>
</body>
</html>
"""
    try:
        portal_desktop = Path.home() / "Escritorio" / "ENLACE_SOBERANO_CLIENTES.html"
        portal_desktop.write_text(html_content, encoding="utf-8")
        portal_web = PROJECT_ROOT / "web" / "sovereign_portal.html"
        portal_web.parent.mkdir(parents=True, exist_ok=True)
        portal_web.write_text(html_content, encoding="utf-8")
    except Exception as e:
        print(f"[CLIENT-SERVICE] Error creando archivo portal: {e}")


def save_client_links(public_url: str | None, port: int = PORT) -> str:
    cfg = load_tunnel_config()
    lan_ip = get_lan_ip()
    client_pub = f"{public_url}/client" if public_url else "Conectando túnel público..."
    lan_link = f"http://{lan_ip}:{port}/client"
    local_link = f"http://localhost:{port}/client"

    sovereign_link = cfg.get("custom_permanent_url") or cfg.get("client_permanent_portal_url") or "https://ntfy.sh/godworks_sovereign_client_chat"

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_text = (
        "=================================================================\n"
        "   ENLACE SOBERANO DE CHAT PARA CLIENTES (DISPONIBLE 24/7)\n"
        "=================================================================\n"
        f"Actualizado: {ts}\n"
        f"👑 Enlace Soberano Invariable : {sovereign_link}\n"
        f"🌐 Enlace Directo Internet    : {client_pub}\n"
        f"📱 Enlace Red Local (Wi-Fi)   : {lan_link}\n"
        f"💻 Enlace Local (PC)          : {local_link}\n"
        "=================================================================\n"
        "El Enlace Soberano Invariable nunca cambia y está disponible de\n"
        "forma indefinida para todos los clientes en cualquier momento.\n"
        "Modo seguro: Clientes solo pueden conversar sin acceso a herramientas.\n"
    )

    try:
        LINK_FILE.write_text(output_text, encoding="utf-8")
        json_data = {
            "online": bool(public_url),
            "sovereign_permanent_url": sovereign_link,
            "client_public_url": client_pub if public_url else "",
            "client_lan_url": lan_link,
            "client_local_url": local_link,
            "port": port,
            "lan_ip": lan_ip,
            "timestamp": time.time(),
            "updated_at": datetime.datetime.now().isoformat()
        }
        JSON_FILE.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
        DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        DESKTOP_FILE.write_text(output_text, encoding="utf-8")
        if public_url:
            sync_client_permanent_portal(client_pub)
            generate_sovereign_portal_html(client_pub)
    except Exception as e:
        print(f"[CLIENT-SERVICE] Error guardando registro de enlaces: {e}")

    return output_text


def find_cloudflared_bin() -> str | None:
    paths = [
        "/home/timemachine/.local/bin/cloudflared",
        "/usr/local/bin/cloudflared",
        "/usr/bin/cloudflared"
    ]
    for p in paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    import shutil
    return shutil.which("cloudflared")


def run_daemon():
    global _SHUTDOWN
    print("[CLIENT-SERVICE] 🚀 Iniciando Servicio Autónomo de Clientes TARDIS 24/7...")
    cf_bin = find_cloudflared_bin()
    if not cf_bin:
        print("[CLIENT-SERVICE] ❌ ERROR: Binario cloudflared no disponible.")
        sys.exit(1)

    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    consecutive_errors = 0

    while not _SHUTDOWN:
        # 1. Esperar a que el servidor maestro responda en el puerto 8757
        if not is_local_server_up(PORT):
            print(f"[CLIENT-SERVICE] Esperando disponibilidad del servidor maestro en puerto {PORT}...")
            for _ in range(10):
                if _SHUTDOWN or is_local_server_up(PORT):
                    break
                time.sleep(1)
            if _SHUTDOWN:
                break
            if not is_local_server_up(PORT):
                time.sleep(2)
                continue

        # 2. Verificar si el puente BRIDGE ya tiene un túnel activo
        bridge_url = get_bridge_public_url()
        if bridge_url:
            save_client_links(bridge_url, PORT)
            print(f"[CLIENT-SERVICE] ✅ Túnel detectado desde BRIDGE: {bridge_url}/client")
            # Monitorear salud continuamente
            while not _SHUTDOWN:
                time.sleep(15)
                if not is_local_server_up(PORT):
                    print("[CLIENT-SERVICE] ⚠️ Servidor local no responde. Reiniciando ciclo de verificación...")
                    break
                current_bridge = get_bridge_public_url()
                if not current_bridge:
                    print("[CLIENT-SERVICE] ⚠️ Túnel BRIDGE desconectado. Iniciando failover autónomo...")
                    break
                # Actualizar timestamp periódicamente
                save_client_links(current_bridge, PORT)
            if _SHUTDOWN:
                break

        # 3. Failover / Túnel Autónomo Dedicado si BRIDGE no está activo
        cfg = load_tunnel_config()
        cf_token = cfg.get("cloudflare_tunnel_token", "").strip()
        custom_perm = cfg.get("custom_permanent_url", "").strip()

        if cf_token:
            print(f"[CLIENT-SERVICE] 👑 Arrancando Túnel Soberano Cloudflare Named con token persistente...")
            cf_args = [cf_bin, "tunnel", "run", "--token", cf_token]
        else:
            print(f"[CLIENT-SERVICE] 🌐 Estableciendo túnel Cloudflare seguro hacia http://localhost:{PORT}...")
            cf_args = [cf_bin, "tunnel", "--url", f"http://localhost:{PORT}"]

        proc = None
        public_url = custom_perm if (cf_token and custom_perm) else None
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as lf:
                lf.write(f"\n--- INICIO TÚNEL CLIENTES: {datetime.datetime.now().isoformat()} ---\n")
                proc = subprocess.Popen(
                    cf_args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )

            # Si ya tenemos public_url por custom_permanent_url con named tunnel
            if public_url:
                summary = save_client_links(public_url, PORT)
                print(summary)

            # Leer la salida en tiempo real buscando la URL asignada si es quick tunnel
            start_wait = time.time()
            for line in proc.stdout:
                if _SHUTDOWN:
                    break
                with open(LOG_FILE, "a", encoding="utf-8") as lf:
                    lf.write(line)
                if not public_url:
                    m = url_pattern.search(line)
                    if m:
                        public_url = m.group(0)
                        summary = save_client_links(public_url, PORT)
                        print(summary)
                        consecutive_errors = 0
                        break
                if time.time() - start_wait > 30.0:
                    if not public_url:
                        print("[CLIENT-SERVICE] ⚠️ Tiempo de espera agotado negociando URL de Cloudflare.")
                    break

            if public_url and proc and proc.poll() is None:
                # Bucle de mantenimiento mientras el proceso del túnel continúe vivo
                while not _SHUTDOWN and proc.poll() is None:
                    time.sleep(15)
                    save_client_links(public_url, PORT)

            if proc and proc.poll() is not None:
                print(f"[CLIENT-SERVICE] ⚠️ El proceso de túnel terminó (código {proc.returncode}). Reconectando...")

        except Exception as e:
            consecutive_errors += 1
            print(f"[CLIENT-SERVICE] Error en túnel: {e}. Reintentando en breve...")
            time.sleep(min(2 * consecutive_errors, 10))

        finally:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        if not _SHUTDOWN:
            time.sleep(2)

    print("[CLIENT-SERVICE] Servicio de clientes finalizado ordenadamente.")


def main():
    parser = argparse.ArgumentParser(description="Servicio Autónomo de Enlace de Clientes TARDIS")
    parser.add_argument("--daemon", action="store_true", help="Ejecutar en modo servicio 24/7 sin cortes")
    parser.add_argument("--status", action="store_true", help="Mostrar estado y enlace actual sin bloquear")
    args = parser.parse_args()

    if args.status:
        if LINK_FILE.exists():
            print(LINK_FILE.read_text(encoding="utf-8"))
        else:
            print("No hay enlace de clientes generado aún.")
        return

    # Si se invoca con --daemon o directamente, ejecutar el daemon autónomo
    if args.daemon:
        run_daemon()
    else:
        # Modo interactivo: Si ya existe un enlace activo reciente (<20s), mostrarlo y continuar en daemon
        if LINK_FILE.exists():
            content = LINK_FILE.read_text(encoding="utf-8")
            print(content)
        run_daemon()


if __name__ == "__main__":
    main()
