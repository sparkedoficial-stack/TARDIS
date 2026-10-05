#!/usr/bin/env python3
"""
TARDIS Sovereign CLI · Consola de Terminal Universal
Permite consultar telemetría, chatear con el núcleo soberano (Dolphin 3.0 / Ollama), reactivar botones
y controlar el sistema operativo directamente desde cualquier shell.
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error
import shutil
import subprocess

PORT = 8757
TOKEN = "REDACTED"
API_BASE = f"http://REDACTED_IP:{PORT}"

C_RESET = "\033[0m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_GOLD = "\033[38;5;220m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"

def api_request(endpoint: str, method: str = "GET", payload: dict = None, timeout: int = 15):
    url = f"{API_BASE}{endpoint}"
    if "?" in endpoint:
        url += f"&key={TOKEN}"
    else:
        url += f"?key={TOKEN}"

    data = json.dumps(payload).encode("utf-8") if payload else None
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"No se pudo conectar con TARDIS en {API_BASE}: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def print_banner():
    print(f"{C_CYAN}{C_BOLD}")
    print("      ▲")
    print("    ▲ ▲ ▲   T A R D I S   C L I   v 2 6 . 4")
    print("   ▲ ▲ ▲ ▲  Consola Soberana de Sistema")
    print(f"{C_RESET}")

def cmd_status():
    print(f"{C_BOLD}--- TELEMETRÍA Y ESTADO DE TARDIS ---{C_RESET}")
    res = api_request("/api/health")
    if res.get("status") == "ok" or res.get("ok"):
        print(f"  {C_GREEN}● Servidor Central:{C_RESET} ACTIVO ({API_BASE})")
        print(f"  {C_CYAN}  Modelo Activo:{C_RESET}    {res.get('active_model', res.get('model', 'TARDIS-NEURAL-SPACE-KAIJU'))}")
        print(f"  {C_CYAN}  Versión API:{C_RESET}      {res.get('version', '26.4')}")
        print(f"  {C_CYAN}  Nodos Activos:{C_RESET}    {res.get('nodes_online', 1)}")
    else:
        print(f"  {C_RED}○ Servidor Central:{C_RESET} INACTIVO ({res.get('error')})")

    # Ollama check
    try:
        with urllib.request.urlopen("http://REDACTED_IP:11434/api/tags", timeout=2) as r:
            tags = json.loads(r.read().decode("utf-8"))
            models = [m.get("name") for m in tags.get("models", [])]
            print(f"  {C_GREEN}● Motor Ollama:{C_RESET}    ACTIVO (Modelos: {', '.join(models[:3])})")
    except Exception:
        print(f"  {C_YELLOW}○ Motor Ollama:{C_RESET}    INACTIVO o no accesible en 11434")

    # Companion check
    res_comp = subprocess.run(["pgrep", "-f", "tardis_desktop_companion.py"], stdout=subprocess.PIPE)
    if res_comp.returncode == 0:
        print(f"  {C_GREEN}● Asistente Flotante:{C_RESET} ACTIVO sobre el Escritorio OS")
    else:
        print(f"  {C_DIM}○ Asistente Flotante: Inactivo (ejecuta 'tardis companion'){C_RESET}")

def cmd_chat(message: str):
    active_m = os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")
    m_label = active_m
    print(f"{C_DIM}Consultando a {m_label} en TARDIS...{C_RESET}")
    res = api_request("/api/chat", method="POST", payload={
        "message": message,
        "stream": False,
        "num_predict": 400
    }, timeout=45)

    if "reply" in res:
        print(f"\n{C_GOLD}{C_BOLD}▲ TARDIS ({m_label}):{C_RESET}\n{res['reply']}\n")
    else:
        print(f"{C_RED}Error:{C_RESET} {res.get('error', 'Sin respuesta')}")

def cmd_reactivate():
    print(f"{C_CYAN}⚡ Reactivando todos los botones y subsistemas de hardware y software...{C_RESET}")
    res = api_request("/api/system/buttons/auto_activate_all", method="POST")
    if res.get("ok"):
        count = res.get("activated_count", 63)
        print(f"{C_GREEN}✓ Éxito: {count} subsistemas y botones activados.{C_RESET}")
    else:
        print(f"{C_YELLOW}Respuesta:{C_RESET} {res}")

def cmd_explain_screen():
    print(f"{C_CYAN}📸 Capturando pantalla de escritorio y analizando con IA...{C_RESET}")
    res = api_request("/api/system/companion/explain_os_screen", method="POST", payload={}, timeout=35)
    if "explanation" in res:
        print(f"\n{C_GREEN}{C_BOLD}▲ Análisis de Pantalla OS:{C_RESET}\n{res['explanation']}\n")
    else:
        print(f"{C_RED}Error analizando pantalla:{C_RESET} {res.get('error', 'Sin datos')}")

def interactive_repl():
    print_banner()
    print(f"{C_DIM}Escribe tu consulta para chatear con el núcleo soberano, o comandos especiales:")
    print("  /status      - Ver salud de servidores")
    print("  /reactivate  - Reactivar todos los botones y módulos")
    print("  /screen      - Explicar lo que hay en tu pantalla")
    print("  /companion   - Abrir el asistente flotante en tu escritorio")
    print(f"  /exit        - Salir de la consola{C_RESET}\n")

    while True:
        try:
            line = input(f"{C_CYAN}{C_BOLD}TARDIS > {C_RESET}").strip()
            if not line:
                continue
            if line in ("/exit", "exit", "quit", ":q"):
                print(f"{C_GREEN}Hasta luego.{C_RESET}")
                break
            elif line in ("/status", "status"):
                cmd_status()
            elif line in ("/reactivate", "reactivate"):
                cmd_reactivate()
            elif line in ("/screen", "screen"):
                cmd_explain_screen()
            elif line in ("/companion", "companion"):
                subprocess.Popen(["/home/timemachine/Escritorio/GODWORKS SYSTEM/launch_tardis_companion.sh"])
                print(f"{C_GREEN}✓ Asistente flotante lanzado.{C_RESET}")
            else:
                cmd_chat(line)
        except (KeyboardInterrupt, EOFError):
            print(f"\n{C_GREEN}Sesión finalizada.{C_RESET}")
            break

def main():
    parser = argparse.ArgumentParser(description="TARDIS Sovereign CLI Interface", add_help=True)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Muestra el estado del sistema y servicios")
    subparsers.add_parser("reactivate", help="Reactiva los 63 botones y subsistemas")
    subparsers.add_parser("explain-screen", help="Captura y explica la pantalla del SO")
    subparsers.add_parser("companion", help="Lanza el asistente flotante de escritorio")

    chat_p = subparsers.add_parser("chat", help="Preguntar al núcleo soberano")
    chat_p.add_argument("message", nargs="+", help="Mensaje para el modelo")

    args = parser.parse_args()

    if not args.command:
        interactive_repl()
    elif args.command == "status":
        cmd_status()
    elif args.command == "reactivate":
        cmd_reactivate()
    elif args.command == "explain-screen":
        cmd_explain_screen()
    elif args.command == "companion":
        subprocess.Popen(["/home/timemachine/Escritorio/GODWORKS SYSTEM/launch_tardis_companion.sh"])
        print(f"{C_GREEN}✓ Asistente flotante lanzado.{C_RESET}")
    elif args.command == "chat":
        cmd_chat(" ".join(args.message))

if __name__ == "__main__":
    main()
