#!/usr/bin/env bash
# GODWORKS SYSTEM & TARDIS Sovereign CLI Bridge for Orca & Terminal
set -euo pipefail

BASE="/home/timemachine/Escritorio/GODWORKS SYSTEM"
PYTHON="$BASE/.venv-linux/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="/usr/bin/python3"
fi

exec "$PYTHON" - "$@" << 'PYEOF'
import sys
import os
import json
import urllib.request
import urllib.parse
from pathlib import Path

API_URL = os.environ.get("GIA_API_URL", "http://REDACTED_IP:8757")
TOKEN = os.environ.get("GIA_TOKEN", "DiosDelTiempo01")

def request_api(endpoint, method="GET", data=None):
    url = f"{API_URL}{endpoint}"
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}key={TOKEN}"
    headers = {"X-GIA-Key": TOKEN, "Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def cmd_status():
    print("🛸 GODWORKS SYSTEM v26.4 / TARDIS Sovereign Status")
    print(f" • Local Node API : {API_URL}")
    print(f" • Sovereign Token: {TOKEN[:4]}***")
    
    # 1. API Status
    res = request_api("/api/antigravity/feedback")
    if res.get("ok"):
        print(f" • Estado del Servidor: ONLINE (Salud: {res.get('health_score', 100)}%)")
    else:
        print(f" • Estado del Servidor: OFFLINE / {res.get('error')}")

    # 2. Conjectures & Auto-Improvement
    conj = request_api("/api/conjectures/status")
    if conj.get("ok"):
        print(f" • Centinela Auto-Mejora: {'ACTIVO' if conj.get('running') else 'INACTIVO'} (Inactividad: {conj.get('idle_minutes', 0):.1f}m / Umbral: 30m)")
        print(f" • Conjeturas Formuladas: {conj.get('total_conjectures', 0)}")
        lat = conj.get("latest_conjecture") or {}
        if lat.get("title"):
            print(f" • Última Conjetura : \"{lat.get('title')}\"")
    
    # 3. Tunnel URL
    tunnel_file = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM/dist/CURRENT_TUNNEL_URL.txt")
    if tunnel_file.exists():
        url = tunnel_file.read_text().strip()
        print(f" • Túnel Público    : {url}")

def cmd_research(query):
    if not query:
        print("Uso: godworks research <tema o consulta>")
        return
    print(f"🌐 Investigando en la web sobre: '{query}'...")
    res = request_api("/api/research/explore", method="POST", data={"topic": query, "deep": True})
    if res.get("ok"):
        rep = res.get("report")
        if isinstance(rep, dict):
            print(f"\n📑 Síntesis ({rep.get('provider_used', 'sovereign')} en {rep.get('elapsed_seconds', 0):.2f}s):")
            print(rep.get("synthesis", ""))
            sources = rep.get("sources", [])
            if sources:
                print("\n🔗 Fuentes:")
                for s in sources[:5]:
                    if isinstance(s, dict):
                        print(f" • {s.get('title', 'Fuente')}: {s.get('url', '')}")
                    else:
                        print(f" • {s}")
        else:
            print("\n" + str(rep))
    else:
        print(f"❌ Error en investigación: {res.get('error')}")

def cmd_evolve(filepath, goal):
    if not filepath or not goal:
        print("Uso: godworks evolve <archivo> <meta u optimización>")
        return
    print(f"🧬 Solicitando auto-evolución para '{filepath}'...")
    res = request_api("/api/code/evolve", method="POST", data={"target_file": filepath, "goal": goal})
    if res.get("ok"):
        print(f"✅ Evolución {res.get('status')} en {res.get('elapsed_seconds', 0):.2f}s vía {res.get('model_used')}")
        if res.get("backup_path"):
            print(f" • Respaldo: {res.get('backup_path')}")
        if res.get("test_output"):
            print(f" • Tests:\n{res.get('test_output')[:500]}")
    else:
        print(f"❌ Fallo en evolución: {res.get('error')}")

def cmd_conjecture(subcmd=""):
    if subcmd == "trigger":
        print("🧠 Forzando formulación inmediata de conjetura...")
        res = request_api("/api/conjectures/trigger", method="POST")
        print(json.dumps(res, indent=2))
    else:
        res = request_api("/api/conjectures/status")
        print(json.dumps(res, indent=2))

def cmd_chat(prompt):
    if not prompt:
        print("Uso: godworks chat <mensaje>")
        return
    res = request_api("/api/chat", method="POST", data={"message": prompt})
    if res.get("ok"):
        print(f"🤖 GIA ({res.get('model', 'sovereign')}): {res.get('reply')}")
    else:
        print(f"❌ Error: {res.get('error')}")

def cmd_missions():
    res = request_api("/api/missions/status")
    if not res.get("ok"):
        print(f"❌ Error al consultar misiones: {res.get('error')}")
        return
    print("🎯 Bóveda de Misiones y Prospección Soberana:")
    print(f" • Misiones Activas  : {res.get('active_missions')}/{res.get('total_missions')}")
    print(f" • Prospectos Totales: {res.get('total_prospects')}")
    print(f" • Invitaciones Token: {res.get('total_invitations')}")
    print(f" • Sinergia Promedio : {int(res.get('avg_synergy', 0)*100)}%")
    stages = res.get("stages", {})
    print(f" • Estados: {stages.get('scouted', 0)} scouted | {stages.get('proposed', 0)} propuestos | {stages.get('contacted', 0)} contactados")

def cmd_outreach(target):
    if not target:
        print("Uso: godworks outreach <autor o tema de investigación>")
        return
    print(f"🔍 [ORCHESTRATOR / OSINT] Prospección autónoma para '{target}'...")
    res = request_api("/api/missions/scout", method="POST", data={"query": target, "max_results": 2})
    if not res.get("ok"):
        print(f"❌ Error buscando investigadores: {res.get('error')}")
        return
    disc = res.get("discovered", [])
    print(f"✅ Se descubrieron/indexaron {len(disc)} investigadores/fuentes.")
    for p in disc:
        pid = p.get("id")
        print(f"\n👤 {p.get('name', 'Investigador')} [ID: {pid}] ({int(p.get('synergy_score', 0)*100)}% sinergia)")
        print(f"   • Bio: {p.get('bio', '')[:100]}...")
        if p.get('emails'):
            print(f"   • Emails: {', '.join(p['emails'])}")
        # Enriquecer contactos
        request_api("/api/missions/enrich_contacts", method="POST", data={"prospect_id": pid})
        # Generar propuesta estructurada con modelo soberano
        print(f"   🤖 Generando propuesta técnica con modelo soberano...")
        prop = request_api("/api/missions/generate_proposal", method="POST", data={"prospect_id": pid})
        if prop.get("proposal_text"):
            print("   --- PROPUESTA REDACTADA (EXTRACTO) ---")
            for line in prop["proposal_text"].split("\n")[:8]:
                print(f"   | {line}")
            print("   --------------------------------------")

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print("GODWORKS SYSTEM CLI - Suite Soberana para Orca & Terminal")
        print("Comandos disponibles:")
        print("  godworks status               Muestra salud, telemetría y conjeturas")
        print("  godworks research <tema>      Investigación web profunda con fuentes")
        print("  godworks outreach <tema/autor>Descubre autor, extrae emails y redacta correo")
        print("  godworks missions             Muestra estado de misiones y colaboradores")
        print("  godworks evolve <file> <meta> Auto-programa y optimiza código con tests")
        print("  godworks conjecture [trigger] Consulta o fuerza conjetura autónoma")
        print("  godworks chat <mensaje>       Consulta al modelo soberano")
        print("  godworks ui                   Abre la cabina web en el navegador")
        return

    cmd = args[0]
    if cmd == "status":
        cmd_status()
    elif cmd in ("research", "investiga", "investigar"):
        cmd_research(" ".join(args[1:]))
    elif cmd in ("outreach", "contactar", "autor", "prospect"):
        cmd_outreach(" ".join(args[1:]))
    elif cmd in ("missions", "misiones"):
        cmd_missions()
    elif cmd in ("evolve", "evolucionar"):
        if len(args) < 3:
            print("Uso: godworks evolve <archivo> <meta>")
            return
        cmd_evolve(args[1], " ".join(args[2:]))
    elif cmd in ("conjecture", "conjetura"):
        sub = args[1] if len(args) > 1 else ""
        cmd_conjecture(sub)
    elif cmd in ("chat", "ask"):
        cmd_chat(" ".join(args[1:]))
    elif cmd in ("ui", "cockpit", "web"):
        import subprocess
        subprocess.Popen(["google-chrome", f"{API_URL}/?key={TOKEN}"])
        print(f"🛸 Abriendo cabina en {API_URL}/?key={TOKEN}")
    else:
        print(f"Comando desconocido: {cmd}. Ejecuta 'godworks help'")

if __name__ == "__main__":
    main()
PYEOF
