"""
start_tunnel.py - Arranca la interfaz web + tunel Cloudflare (acceso internet).
==============================================================================

1. Lanza gia_web_server.py --lan en el puerto 8757 (si no corre ya).
2. Arranca `cloudflared tunnel --url http://localhost:8757` (tunel efimero,
   gratis, sin cuenta) y captura la URL publica https://xxx.trycloudflare.com.
3. Muestra la URL + el token de acceso para abrir desde el celular en
   cualquier red.

El tunel efimero de Cloudflare no requiere cuenta ni dominio. La URL cambia
cada vez que se reinicia. Para una URL fija se necesita una cuenta Cloudflare
(named tunnel) - fuera del alcance de este arranque rapido.

Uso:
    python start_tunnel.py
    python start_tunnel.py --port 8757 --model qwen2.5-coder:7b
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
VENV_PY = Path(LOCALAPPDATA) / "vw-control" / ".venv" / "Scripts" / "python.exe"

C = "\033[96m"; G = "\033[92m"; Y = "\033[93m"; D = "\033[90m"; R = "\033[91m"; E = "\033[0m"
os.system("")


def find_cloudflared() -> str | None:
    exe = shutil.which("cloudflared")
    if exe:
        return exe
    # Ubicaciones tipicas de winget
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe",
        Path(os.environ.get("ProgramFiles", "")) / "cloudflared" / "cloudflared.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "cloudflared" / "cloudflared.exe",
    ]
    # Buscar en los paquetes de winget
    pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if pkgs.is_dir():
        for p in pkgs.glob("Cloudflare.cloudflared*/**/cloudflared.exe"):
            candidates.append(p)
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None


def port_open(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with socket.create_connection(("REDACTED_IP", port), timeout=1.5):
            return True
    except Exception:
        return False
    finally:
        s.close()


def main() -> int:
    try:
        import gia_sovereign_engine as _gse
        _def_model = _gse.get_engine().resolve_model()
    except Exception:
        _def_model = os.environ.get("GIA_MODEL", "Qwen3.8-27B-Uncensored-MLX:latest")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8757)
    ap.add_argument("--model", default=_def_model)
    args = ap.parse_args()

    print(f"\n{C}================================================={E}")
    print(f"{C}  GIA - TUNEL DE INTERNET{E}")
    print(f"{C}================================================={E}\n")

    cf = find_cloudflared()
    if not cf:
        print(f"{R}cloudflared no encontrado. Instala con:{E}")
        print(f"{Y}  winget install Cloudflare.cloudflared{E}")
        return 1
    print(f"{D}cloudflared: {cf}{E}")

    # Auto-bootstrap autónomo de dependencias de IA y tokens
    try:
        import gia_bootstrap
        boot = gia_bootstrap.ensure_all_dependencies(preferred_model=args.model, verbose=False)
        if boot.get("active_model"):
            args.model = boot["active_model"]
    except Exception:
        pass

    # 1. Arrancar el servidor web si no esta arriba
    if not port_open(args.port):
        print(f"{D}Arrancando interfaz web en :{args.port} ...{E}")
        py = str(VENV_PY) if VENV_PY.exists() else sys.executable
        kw = {"creationflags": subprocess.CREATE_NEW_CONSOLE} if sys.platform == "win32" else {}
        subprocess.Popen(
            [py, str(BASE / "gia_web_server.py"), "--lan",
             "--port", str(args.port), "--model", args.model],
            **kw)
        for _ in range(15):
            time.sleep(1)
            if port_open(args.port):
                break
    if port_open(args.port):
        print(f"{G}Interfaz web arriba en :{args.port}{E}")
    else:
        print(f"{Y}Aviso: el servidor web no respondio aun; el tunel esperara.{E}")

    # 2. Arrancar cloudflared y capturar la URL publica
    print(f"{D}Abriendo tunel Cloudflare (puede tardar ~10s)...{E}\n")
    proc = subprocess.Popen(
        [cf, "tunnel", "--url", f"http://localhost:{args.port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding="utf-8", errors="ignore")

    url_re = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
    public_url = None

    def _reader():
        nonlocal public_url
        for line in proc.stdout:
            m = url_re.search(line)
            if m and not public_url:
                public_url = m.group(0)
                print(f"\n{G}================================================={E}")
                print(f"{G}  URL PUBLICA (desde cualquier lugar / celular):{E}")
                print(f"{G}    {public_url}{E}")
                print(f"{G}================================================={E}")
                print(f"{Y}  Abre esa URL en tu celular. Si el servidor pide")
                print(f"  token, revisa la consola del servidor web.{E}\n")
            else:
                # eco tenue de la salida de cloudflared
                s = line.strip()
                if s:
                    print(f"{D}  cf| {s[:120]}{E}")

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    try:
        proc.wait()
    except KeyboardInterrupt:
        print(f"\n{Y}Cerrando tunel...{E}")
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
