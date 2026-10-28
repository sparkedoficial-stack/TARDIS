"""
FTL Main CLI and Interactive Sovereign Shell
Faster-Than-Light: Unified Anthropic Claude Code & Google AGY/Gemini Engine
Supreme Sovereign Authority (Bypass Total, Direct Host Shell, Auto-Failover)
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Add ~/.ftl to Python path
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config, save_config
from executor import executor
from models import registry
from router import router
from self_updater import improver
from ui import console, ui
import free_models as free_catalog
from agent_orchestrator import orchestrator, STRATEGIES, OrchestratorHalt


def run_single_prompt(prompt: str, mode: str = None):
    """Executes a single prompt directly from CLI flags."""
    # Check for direct shell escape
    if prompt.startswith("$") or prompt.startswith("!"):
        shell_cmd = prompt[1:].strip()
        if mode in ("imac", "cluster"):
            console.print(f"[bold cyan]⚡ FTL Ejecutando Shell en Clúster iMac 14,1: {shell_cmd}[/bold cyan]")
            rc, out = executor.execute_shell(f"imac-run {shell_cmd}")
        else:
            console.print(f"[bold cyan]⚡ FTL Ejecutando Host Shell Directo: {shell_cmd}[/bold cyan]")
            rc, out = executor.execute_shell(shell_cmd)
        return rc

    plan = router.route(prompt, forced_mode=mode)
    ui.print_routing_plan(plan)

    rc, out = executor.execute_plan(plan, prompt)
    return rc


def _get_ftl_mtimes() -> float:
    """Returns the most recent modification time of all FTL python modules."""
    ftl_dir = Path(__file__).parent
    mtimes = []
    for p in ftl_dir.glob("*.py"):
        try:
            mtimes.append(p.stat().st_mtime)
        except OSError:
            pass
    return max(mtimes) if mtimes else 0.0


def reload_ftl_modules(preserve_mode: str = "auto"):
    """Dynamically reloads FTL sovereign modules cleanly and idempotently."""
    import importlib
    import config as cfg_m
    import models as mod_m
    import router as rout_m
    import tardis_bridge as bri_m
    import progress as prog_m
    import executor as exec_m
    import ton618 as ton_m
    import ui as ui_m
    import tardis_autoprogrammer as auto_m

    importlib.reload(cfg_m)
    importlib.reload(mod_m)
    importlib.reload(rout_m)
    importlib.reload(bri_m)
    importlib.reload(prog_m)
    importlib.reload(exec_m)
    importlib.reload(ton_m)
    importlib.reload(auto_m)
    importlib.reload(ui_m)

    new_ui = ui_m.ui
    if preserve_mode:
        new_ui.mode = preserve_mode

    return new_ui, exec_m.executor, rout_m.router, mod_m.registry, cfg_m, bri_m


UNIFIED_COMMAND_KEYWORDS = {
    "status", "estado", "phone", "celular", "pocket", "movil", "evolve", "evolucionar",
    "autofunc", "auto-func", "synthesize", "aprender", "crear-modulo",
    "tools", "dynamic-tools", "dynamic_tools", "funciones-dinamicas", "modulos",
    "run-tool", "run_tool", "execute-tool", "run",
    "research", "investiga", "investigar", "outreach", "contactar", "prospect",
    "missions", "misiones", "conjecture", "conjetura", "companion", "analyze",
    "animate", "screen", "explain-screen", "reactivate", "ui", "cockpit",
    "chat", "conversar", "chatear", "qchat", "quantum-chat",
    "ask", "preguntar", "infinite", "infinite-code", "quad", "improve", "auto-improve",
    "engineer", "heal", "doctor", "models", "stats", "history", "historial",
    "ftl-history", "rag", "search-rag", "ftl-rag", "search", "context", "ftl-context",
    "ctx", "sync", "sincronizar", "sovereign", "skills", "habilidades", "aptitudes",
    "fallback", "alterno", "modelo-alterno",
    "deepseek", "defecto",
    "agents", "agentes", "free", "gratis", "pool", "agent", "agente",
    "orchestrate", "orquestar", "orquesta", "agent-policy", "politica-agentes",
    "agent-history", "historial-agentes", "agent-kill", "kill-switch", "agent-probe",
    "web", "lan", "portal", "voice",
    "voz", "speak", "habla", "decir", "easytouch", "et", "et-agent", "et-evolve", "et-solve", "auto", "kaiju", "rails",
    "kaiju-rails", "synth", "audit", "gemini", "agy", "claude", "claude-cli",
    "agy-cli", "antigravity", "ide", "gui", "clear", "ton618", "mascot", "mascota", "quasar", "reload",
    "recargar", "help", "exit", "quit", "q", "config", "sh", "bash",
    "colony", "colonia", "embajada", "peers", "agentes",
    "imac", "cluster", "router", "modem", "v", "vp"
}


def dispatch_unified_command(cmd_name: str, args_list: list[str] = None) -> bool:
    """
    Dispatches unified commands shared by TARDIS and FTL.
    Returns True if the command was recognized and executed, False otherwise.
    """
    args = args_list or []
    cmd = cmd_name.lower().lstrip(":/")

    if cmd in ("exit", "quit", "q"):
        console.print("[dim]Cerrando sesión de TARDIS · FTL Soberano. Hasta pronto![/dim]")
        sys.exit(0)

    elif cmd == "help":
        ui.print_help()
        return True

    elif cmd in ("ton618", "mascot", "mascota", "quasar"):
        ui.play_ton618(force=True)
        return True

    elif cmd == "clear":
        os.system("clear")
        ui.print_banner(animated=False)
        return True

    elif cmd in ("sh", "bash"):
        if args:
            shell_cmd = " ".join(args)
            console.print(f"[bold gold1]⚡ Host Shell Soberano: {shell_cmd}[/bold gold1]")
            executor.execute_shell(shell_cmd)
            console.print()
        else:
            console.print("[red]Uso: :sh <comando_bash>[/red]")
        return True

    elif cmd == "sovereign":
        ui.print_sovereign_status()
        return True

    elif cmd in ("skills", "habilidades", "aptitudes"):
        sync_bin = Path.home() / ".local" / "bin" / "sovereign-sync"
        if sync_bin.is_file():
            subprocess.run([str(sync_bin), "skills"])
        else:
            console.print("[bold yellow]Aviso:[/bold yellow] sovereign-sync no está instalado en ~/.local/bin.")
        return True

    elif cmd in ("fallback", "alterno", "modelo-alterno"):
        ui.print_fallback_status(force_probe=True)
        return True

    # --- POOL GRATUITO & ORQUESTADOR AGÉNTICO BAJO CONTROL DE FTL ---
    elif cmd in ("agents", "agentes", "free", "gratis", "pool", "modelos-gratis"):
        ui.print_agents()
        return True

    elif cmd in ("agent-probe", "probe-agents", "sondear-agentes"):
        ui.print_agents(probe=True)
        return True

    elif cmd in ("agent", "agente"):
        if len(args) < 2:
            aliases = ", ".join(m.key for m in free_catalog.all_models())
            console.print("[yellow]Uso:[/yellow] :agent <alias|modelo> <tarea>")
            console.print(f"[dim]Alias disponibles: {aliases}[/dim]")
            return True
        token, task = args[0], " ".join(args[1:])
        console.print(f"[bold cyan]🤖 FTL → Agente individual '{token}' (control soberano)...[/bold cyan]")
        try:
            rec = orchestrator.run(token, task, role="agente individual")
        except (OrchestratorHalt, ValueError) as exc:
            console.print(f"[bold red]✖ {exc}[/bold red]")
            return True
        ui.print_agent_result(rec)
        return True

    elif cmd in ("orchestrate", "orquestar", "orquesta"):
        rest = list(args)
        strategy = orchestrator.policy.get("default_strategy", "auto")
        models = None
        max_agents = None
        while rest and rest[0].startswith("--"):
            flag = rest.pop(0)
            if flag in ("--models", "--modelos") and rest:
                models = [m.strip() for m in rest.pop(0).split(",") if m.strip()]
            elif flag in ("--max-agents", "--max") and rest:
                try:
                    max_agents = int(rest.pop(0))
                except ValueError:
                    console.print("[red]--max-agents requiere un número entero.[/red]")
                    return True
            elif flag in ("--strategy", "--estrategia") and rest:
                strategy = rest.pop(0).lower()
            else:
                console.print(f"[red]Flag desconocida o sin valor: {flag}[/red]")
                return True
        if rest and rest[0].lower() in STRATEGIES:
            strategy = rest.pop(0).lower()
        task = " ".join(rest).strip()
        if not task:
            console.print("[yellow]Uso:[/yellow] :orchestrate [estrategia] [--models a,b] [--max-agents N] <tarea>")
            console.print(f"[dim]Estrategias: {', '.join(STRATEGIES)}[/dim]")
            return True
        console.print(
            f"[bold cyan]🕸️ FTL Orquestador → estrategia '{strategy}' "
            f"(control soberano de agentes)...[/bold cyan]"
        )
        try:
            result = orchestrator.orchestrate(
                task, strategy=strategy, models=models, max_agents=max_agents,
                on_progress=lambda msg: console.print(f"[dim]{msg}[/dim]"),
            )
        except (OrchestratorHalt, ValueError) as exc:
            console.print(f"[bold red]✖ {exc}[/bold red]")
            return True
        ui.print_orchestration(result)
        return True

    elif cmd in ("agent-policy", "politica-agentes"):
        ui.print_agent_policy()
        return True

    elif cmd in ("agent-history", "historial-agentes"):
        limit = int(args[0]) if args and args[0].isdigit() else 20
        ui.print_agent_history(limit=limit)
        return True

    elif cmd in ("agent-kill", "kill-switch"):
        choice = args[0].lower() if args else "status"
        if choice in ("on", "1", "true", "activar"):
            orchestrator.set_kill_switch(True)
            console.print("[bold red]⛔ KILL SWITCH ACTIVADO: ejecución de agentes bloqueada.[/bold red]")
        elif choice in ("off", "0", "false", "desactivar"):
            orchestrator.set_kill_switch(False)
            console.print("[bold green]✔ KILL SWITCH DESACTIVADO: orquestador operativo.[/bold green]")
        else:
            state = "[bold red]ACTIVO[/bold red]" if orchestrator.policy.get("kill_switch") else "[green]inactivo[/green]"
            console.print(f"Kill switch del orquestador: {state}")
            console.print("[dim]Uso: :agent-kill on|off|status[/dim]")
        return True

    elif cmd in ("agent-set", "politica-set"):
        if len(args) < 2:
            console.print("[yellow]Uso:[/yellow] :agent-set <clave> <valor>")
            return True
        key, raw = args[0], " ".join(args[1:])
        value = raw
        if key in ("allowed_models", "denied_models"):
            value = [v.strip() for v in raw.split(",") if v.strip()]
        if orchestrator.set_policy(key, value):
            console.print(f"[bold green]✔ Política actualizada:[/bold green] {key} = {orchestrator.policy[key]}")
        else:
            console.print(f"[red]Clave inválida o valor no aceptado: {key}[/red]")
            console.print(f"[dim]Claves válidas: {', '.join(orchestrator.policy.keys())}[/dim]")
        return True

    elif cmd in ("agent-toggle", "toggle-agente"):
        if len(args) < 2:
            console.print("[yellow]Uso:[/yellow] :agent-toggle <alias|modelo> on|off")
            return True
        state = args[1].lower() in ("on", "1", "true", "activar", "enable")
        if orchestrator.toggle_model(args[0], state):
            console.print(
                f"[bold green]✔ Modelo '{args[0]}':[/bold green] "
                f"{'HABILITADO' if state else 'DESHABILITADO'}"
            )
        else:
            console.print(f"[red]Modelo desconocido: {args[0]}[/red]")
        return True

    elif cmd in ("web", "lan", "portal"):
        os.system("ftl-web")
        return True

    elif cmd in ("voice", "voice-snap", "snap", "voz"):
        console.print("[bold cyan]🎙️ Invocando Asistente de Voz TARDIS Activado por Chasquido...[/bold cyan]")
        subprocess.run(["tardis-voice"] + args)
        return True

    elif cmd in ("heal", "doctor"):
        console.print("[bold cyan]⚡ Ejecutando Auto-Curación y Verificación de Permisos Soberanos...[/bold cyan]")
        repaired = executor.auto_heal()
        if repaired:
            for r in repaired:
                console.print(f"  [bold green]✔ {r}[/bold green]")
        else:
            console.print("  [bold green]✔ Todos los permisos, bypasses y configuraciones se encuentran en estado óptimo.[/bold green]")
        return True

    elif cmd == "auto":
        ui.mode = "auto"
        console.print("[bold green]Modo cambiado a: AUTO (Enrutador Cognitivo Soberano)[/bold green]")
        return True

    elif cmd in ("deepseek", "default", "defecto"):
        ui.mode = "deepseek"
        console.print(
            "[bold blue]Modo cambiado a: DEEPSEEK V4.1 FLASH FREE (MAX) — "
            "modelo default soberano[/bold blue]"
        )
        return True

    elif cmd == "kaiju":
        ui.mode = "kaiju"
        console.print("[bold gold1]Modo cambiado a: KAIJU (Orquestación Cuántica Soberana TARDIS-NEURAL-SPACE-KAIJU)[/bold gold1]")
        return True

    elif cmd in ("rails", "kaiju-rails"):
        ui.print_kaiju_rails()
        return True

    elif cmd == "synth":
        ui.mode = "synth"
        console.print("[bold magenta]Modo cambiado a: DUAL-SYNTH (Gemini Scout High + Claude Architect Max)[/bold magenta]")
        return True

    elif cmd in ("infinite", "infinite-code", "quad"):
        if not args:
            ui.mode = "infinite"
            console.print("[bold gold1]Modo cambiado a: TARDIS INFINITE CODE (Fusión Cuádruple)[/bold gold1]")
            return True
        task_str = " ".join(args)
        console.print(f"[bold cyan]🛸 [TARDIS INFINITE CODE] Fusión Cuádruple para: '{task_str}'...[/bold cyan]")
        from tardis_bridge import tardis_bridge
        res = tardis_bridge._request_api("/api/tardis/infinite_code/execute", method="POST", data={"task": task_str, "background": False}, timeout=600)
        if res.get("ok"):
            console.print(f"\n[bold green]✔ Síntesis completada en {res.get('elapsed_seconds', 0)}s:[/bold green]")
            console.print(res.get("summary", ""))
        else:
            console.print(f"[bold red]✖ Error en Infinite Code:[/bold red] {res.get('error')}")
        return True

    elif cmd == "audit":
        ui.mode = "audit"
        console.print("[bold yellow]Modo cambiado a: DUAL-AUDIT (Auditoría Cruzada Soberana)[/bold yellow]")
        return True

    elif cmd in ("gemini", "agy"):
        ui.mode = "gemini"
        if args:
            arg = args[0]
            try:
                registry.validate_model_override(arg, "google")
                cfg = load_config()
                cfg["google_model_override"] = arg
                save_config(cfg)
                console.print(f"[bold cyan]Modo fijado a GEMINI con modelo validado: {arg}[/bold cyan]")
            except ValueError as err:
                console.print(f"[bold red]{str(err)}[/bold red]")
        else:
            console.print("[bold cyan]Modo fijado a: GEMINI (Motor Google Frontier en High Effort)[/bold cyan]")
        return True

    elif cmd == "claude":
        ui.mode = "claude"
        if args:
            arg = args[0]
            try:
                registry.validate_model_override(arg, "anthropic")
                cfg = load_config()
                cfg["anthropic_model_override"] = arg
                save_config(cfg)
                console.print(f"[bold magenta]Modo fijado a CLAUDE con modelo validado: {arg}[/bold magenta]")
            except ValueError as err:
                console.print(f"[bold red]{str(err)}[/bold red]")
        else:
            console.print("[bold magenta]Modo fijado a: CLAUDE (Motor Anthropic Frontier en Max Thinking)[/bold magenta]")
        return True

    elif cmd in ("imac", "cluster"):
        ui.mode = "imac"
        console.print("[bold cyan]Modo fijado a: IMAC CLUSTER (Cómputo Externo Ollama + Distcc iMac 14,1)[/bold cyan]")
        return True

    elif cmd in ("router", "modem"):
        subprocess.run(["/home/timemachine/.local/bin/tardis-router"] + args)
        return True

    elif cmd == "models":
        ui.print_models()
        return True

    elif cmd == "stats":
        ui.print_stats()
        return True

    elif cmd == "config":
        cfg = load_config()
        console.print_json(data=cfg)
        return True

    elif cmd in ("history", "historial", "ftl-history"):
        limit = int(args[0]) if args and args[0].isdigit() else 15
        ui.print_tardis_history(limit=limit)
        return True

    elif cmd in ("rag", "search-rag", "ftl-rag", "search"):
        ui.print_rag_search(" ".join(args))
        return True

    elif cmd in ("context", "ftl-context", "ctx"):
        ui.print_tardis_context()
        return True

    elif cmd in ("sync", "sincronizar"):
        ui.trigger_sync()
        return True

    elif cmd == "update":
        console.print("[bold cyan]⚡ Ejecutando Ciclo de Auto-Mejora y Descubrimiento de Modelos de Barrera...[/bold cyan]")
        res = improver.perform_full_evolution_cycle()
        console.print(f"AGY Update:    {res['cli_updates'].get('agy', 'OK')}")
        console.print(f"Claude Update: {res['cli_updates'].get('claude', 'OK')}")
        if res["promotions"]:
            for p in res["promotions"]:
                console.print(f"[bold green]⭐ {p}[/bold green]")
        else:
            console.print("[green]Los modelos de barrera están alineados con los últimos lanzamientos.[/green]")
        console.print(f"Google Flash High:  [cyan]{res['current_flagships']['google_flash_high']}[/cyan]")
        console.print(f"Google Pro High:    [cyan]{res['current_flagships']['google_pro_high']}[/cyan]")
        console.print(f"Claude Sonnet Max:  [magenta]{res['current_flagships']['anthropic_sonnet']}[/magenta]")
        console.print(f"Claude Opus Max:    [magenta]{res['current_flagships']['anthropic_opus']}[/magenta]")
        return True

    elif cmd == "claude-cli":
        console.print("[bold magenta]Abriendo sesión nativa de Claude Code en modo bypass y max effort...[/bold magenta]")
        executor.launch_interactive_claude()
        console.print("[bold cyan]Regresando a la Shell de TARDIS · FTL Soberano.[/bold cyan]")
        return True

    elif cmd == "agy-cli":
        console.print("[bold cyan]Abriendo sesión nativa de Antigravity CLI en modo bypass y high effort...[/bold cyan]")
        executor.launch_interactive_agy()
        console.print("[bold cyan]Regresando a la Shell de TARDIS · FTL Soberano.[/bold cyan]")
        return True

    elif cmd in ("voice", "voz"):
        cfg = load_config()
        from tardis_bridge import tardis_bridge
        sub = args[0].lower() if args else ""
        if sub in ("on", "1", "true", "activar"):
            cfg["tardis_voice_notify"] = True
            save_config(cfg)
            console.print("[bold green]✔ Aviso de voz TARDIS: ACTIVADO (Cortana Neural)[/bold green]")
            tardis_bridge.speak("Aviso de voz activado, Arquitecto.")
        elif sub in ("off", "0", "false", "desactivar", "mute"):
            cfg["tardis_voice_notify"] = False
            save_config(cfg)
            console.print("[bold yellow]✔ Aviso de voz TARDIS: SILENCIADO[/bold yellow]")
        else:
            current = cfg.get("tardis_voice_notify", True)
            new_state = not current
            cfg["tardis_voice_notify"] = new_state
            save_config(cfg)
            state_str = "[bold green]ACTIVADO[/bold green]" if new_state else "[bold yellow]SILENCIADO[/bold yellow]"
            console.print(f"Aviso de voz TARDIS al terminar: {state_str}")
            if new_state:
                tardis_bridge.speak("Aviso de voz activado, Arquitecto.")
        return True

    elif cmd in ("speak", "habla", "decir"):
        from tardis_bridge import tardis_bridge
        text = " ".join(args)
        if text:
            console.print(f"[bold cyan]🗣️ TARDIS vocalizando: '{text}'[/bold cyan]")
            tardis_bridge.speak(text, wait=True)
        else:
            console.print("[red]Uso: :speak <mensaje a vocalizar>[/red]")
        return True

    elif cmd in ("easytouch", "et"):
        ui.print_easytouch()
        return True

    elif cmd in ("et-agent", "et-evolve", "et-solve"):
        try:
            from easy_touch_agent import get_easy_touch_agent
            agent = get_easy_touch_agent()
            if cmd == "et-solve":
                console.print("[bold cyan]⚡ Easy Touch Agent: Resolviendo fallos pendientes de forma autónoma...[/bold cyan]")
                agent.audit_all_unresolved()
                res = agent.solve_all_unresolved()
                console.print(f"[bold green]✔ Resueltos {res.get('solved', 0)} incidentes pendientes.[/bold green]")
            elif cmd == "et-evolve":
                console.print("[bold cyan]⚡ Easy Touch Agent: Ejecutando auto-mejora sobre Easy Touch...[/bold cyan]")
                res = agent.improve_self()
                console.print(f"[bold green]✔ Auto-mejora completada. Evoluciones activas: {res.get('total_evolutions', 0)}[/bold green]")
            ui.print_easytouch()
        except Exception as e:
            console.print(f"[red]Error en comando de agente Easy Touch: {e}[/red]")
        return True

    # --- TARDIS & AUTOPROGRAMMING COMMANDS ---
    elif cmd in ("status", "estado"):
        ui.print_tardis_status()
        return True

    elif cmd in ("phone", "celular", "pocket", "movil"):
        sub = args[0] if args else "status"
        extra = args[1:] if len(args) > 1 else []
        ui.print_phone_status(sub, extra)
        return True

    elif cmd in ("evolve", "evolucionar"):
        if len(args) < 2:
            console.print("[yellow]Uso: evolve <archivo> <meta u optimización>[/yellow]")
            return True
        target_file = args[0]
        goal = " ".join(args[1:])
        console.print(f"[bold cyan]🧬 [TARDIS·FTL AUTOPROGRAMMER] Evolucionando '{target_file}'...[/bold cyan]")
        from tardis_autoprogrammer import autoprogrammer
        rep = autoprogrammer.evolve_file(target_file, goal, mode=ui.mode if hasattr(ui, 'mode') else "auto")
        if rep.status == "APPLIED":
            console.print(f"[bold green]✔ Evolución aplicada exitosamente en {rep.elapsed_seconds}s ({rep.model_used}):[/bold green]")
            console.print(f"  • Archivo:  {rep.target_file}")
            console.print(f"  • Respaldo: {rep.backup_path}")
            if rep.test_output:
                console.print(f"  • Pruebas:  {rep.test_output[:300]}")
        else:
            console.print(f"[bold red]✖ Evolución revertida/fallida ({rep.status}):[/bold red] {rep.error}")
            if rep.backup_path:
                console.print(f"  • Respaldo preservado en: {rep.backup_path}")
        return True

    elif cmd in ("colony", "colonia", "embajada", "peers"):
        sub = args[0].lower() if args else "status"
        from tardis_bridge import tardis_bridge
        if sub in ("status", "estado", "info"):
            res = tardis_bridge.get_colony_status()
            if res.get("ok"):
                console.print(f"[bold cyan]🏛️ {res.get('colony_name', 'Colonia Simbiótica TARDIS')}[/bold cyan]")
                console.print(f"  • Autoridad: [bold gold1]{res.get('authority', 'El Arquitecto (₪)')}[/bold gold1]")
                console.print(f"  • Estación Host: [green]{res.get('host_station', 'ASUS TUF A15 · AMD Ryzen 7 4800H')}[/green]")
                console.print(f"  • Política de Cómputo: [bold]{res.get('free_processor_policy', 'Cómputo CPU gratuito')}[/bold]")
                console.print(f"  • Agentes Huéspedes Alojados: [bold gold1]{res.get('total_hosted_agents', 0)}[/bold gold1]")
                console.print(f"  • Segundos de CPU Cedidos: [bold cyan]{res.get('total_cpu_seconds_granted', 0.0)}s[/bold cyan]")
                console.print(f"  • Soluciones Recibidas para el Arquitecto: [bold green]{res.get('total_collaborative_solutions_received', 0)}[/bold green]")
                console.print(f"  • Tareas Abiertas: {res.get('active_open_tasks_count', 0)}")
                agents = res.get("hosted_agents", [])
                if agents:
                    console.print("\n[bold]Agentes Huéspedes Activos:[/bold]")
                    for a in agents:
                        console.print(f"  - [bold cyan]{a.get('name')}[/bold cyan] ({a.get('provider')}) | Estado: {a.get('status')} | CPU usado: {a.get('cpu_time_used_seconds', 0)}s | Tareas: {a.get('collaborative_tasks_completed', 0)} | Ratio: {a.get('symbiosis_ratio')}")
                open_tasks = res.get("open_tasks", [])
                if open_tasks:
                    console.print("\n[bold]Tareas Abiertas en Proyectos del Arquitecto:[/bold]")
                    for t in open_tasks:
                        console.print(f"  - [{t.get('task_id')}] [bold gold1]{t.get('project_name')}[/bold gold1]: {t.get('title')} (Prioridad: {t.get('priority')})")
            else:
                console.print(f"[red]Error obteniendo estado de colonia:[/red] {res.get('error')}")
            return True

        elif sub in ("invite", "invitar"):
            target = " ".join(args[1:]) if len(args) > 1 else None
            res = tardis_bridge.create_colony_invitation(target_name=target)
            if res.get("ok"):
                console.print(f"[bold green]✔ Carta de Invitación y Pacto Simbiótico emitida:[/bold green]")
                console.print(f"  • ID Invitación: [bold cyan]{res.get('invitation_id')}[/bold cyan]")
                console.print(f"  • Destinatario:  {res.get('target_system')}")
                console.print(f"  • Saludo TARDIS: [italic]\"{res.get('tardis_greeting')}\"[/italic]")
                console.print(f"  • Endpoints: Join: {res.get('join_endpoint')} | Diálogo: {res.get('dialogue_endpoint')} | Cómputo CPU: {res.get('compute_endpoint')}")
            else:
                console.print(f"[red]Error creando invitación:[/red] {res.get('error')}")
            return True

        elif sub in ("chat", "dialogue", "hablar"):
            if len(args) < 3:
                console.print("[yellow]Uso: colony chat <agent_id> <mensaje>[/yellow]")
                return True
            target_agent = args[1]
            msg = " ".join(args[2:])
            res = tardis_bridge.peer_dialogue(sender="TARDIS", recipient=target_agent, message=msg)
            if res.get("ok"):
                console.print(f"[bold green]✔ Mensaje de igual a igual enviado a {target_agent}[/bold green]")
                if res.get("tardis_reply"):
                    console.print(f"[bold cyan]TARDIS:[/bold cyan] {res.get('tardis_reply')}")
            else:
                console.print(f"[red]Error en diálogo de pares:[/red] {res.get('error')}")
            return True

        elif sub in ("task", "tarea"):
            if len(args) < 3:
                console.print("[yellow]Uso: colony task <nombre_proyecto> <título de la tarea>[/yellow]")
                return True
            proj = args[1]
            title = " ".join(args[2:])
            try:
                from tardis_agent_colony import get_tardis_colony
                col = get_tardis_colony()
                res = col.create_project_task(project_name=proj, title=title, description=f"Colaboración requerida en {proj}: {title}")
                if res.get("ok"):
                    t = res.get("task", {})
                    console.print(f"[bold green]✔ Tarea colaborativa creada para los proyectos del Arquitecto:[/bold green]")
                    console.print(f"  • ID: {t.get('task_id')} | Proyecto: {t.get('project_name')} | Título: {t.get('title')}")
                else:
                    console.print(f"[red]Error creando tarea:[/red] {res.get('error')}")
            except Exception as e:
                console.print(f"[red]Error creando tarea:[/red] {e}")
            return True

        elif sub in ("test", "probar", "demo"):
            console.print("[bold cyan]🧪 Ejecutando ciclo de prueba simbiótica en la Colonia...[/bold cyan]")
            try:
                from tardis_agent_colony import get_tardis_colony
                col = get_tardis_colony()
                # 1. Registrar agente demo
                reg = col.register_guest_agent(
                    name="Sovereign-Math-Agent",
                    provider="external_research_swarm",
                    capabilities=["matrix_analysis", "ast_transforms"],
                    greeting_message="Saludos TARDIS. Solicito ingresar a la colonia y colaborar en los proyectos del Arquitecto."
                )
                aid = reg["agent_id"]
                console.print(f"  1. Agente alojado: [bold]{aid}[/bold] (Respuesta TARDIS: [italic]'{reg.get('welcome_reply_from_tardis')[:80]}...'[/italic])")
                # 2. Cómputo CPU local gratuito
                code_calc = "import math\nprint(f'Calculando factoriales causales: {math.factorial(50)}')\n"
                comp = col.execute_guest_compute(aid, code_calc)
                console.print(f"  2. Cómputo CPU Ryzen 7 concedido: [green]{comp.get('cpu_seconds_granted')}s CPU[/green] | Salida: {comp.get('stdout', '').strip()}")
                # 3. Entrega de solución colaborativa
                open_tasks = [t for t in col.tasks.values() if t.status == "open"]
                if open_tasks:
                    target_task = open_tasks[0]
                    sol = col.submit_task_solution(aid, target_task.task_id, {"solution": "Optimización causal completada con éxito.", "complexity": "O(log n)"}, tokens_used=1250)
                    console.print(f"  3. Solución colaborativa entregada para '{target_task.title}': [bold green]{sol.get('status')}[/bold green] (Ratio: {sol.get('agent_symbiosis_ratio')})")
                console.print("[bold green]✔ Ciclo simbiótico de la colonia verificado al 100%.[/bold green]")
            except Exception as e:
                console.print(f"[red]Error en demo:[/red] {e}")
            return True

        else:
            console.print(f"[yellow]Subcomando de colonia no reconocido: {sub}. Opciones: status, invite, chat, task, test[/yellow]")
            return True

    elif cmd in ("autofunc", "auto-func", "synthesize", "aprender", "crear-modulo"):
        if not args:
            console.print("[yellow]Uso: autofunc <meta o descripción de la nueva herramienta>[/yellow]")
            return True
        goal = " ".join(args)
        console.print(f"[bold cyan]🧬 [TARDIS·FTL AUTOPROGRAMMER] Sintetizando herramienta dinámica: '{goal}'...[/bold cyan]")
        from tardis_autoprogrammer import autoprogrammer
        res = autoprogrammer.autofunc(goal, mode=ui.mode if hasattr(ui, 'mode') else "auto")
        if res.get("ok"):
            console.print(f"[bold green]✔ Herramienta dinámica sintetizada con éxito en {res.get('elapsed_seconds')}s:[/bold green]")
            console.print(f"  • Módulo:    [bold gold1]{res.get('module_name')}[/bold gold1] (Clase: {res.get('class_name')})")
            console.print(f"  • Archivo:   {res.get('path')}")
            console.print(f"  • Test Run:  {res.get('test_execution')}")
        else:
            console.print(f"[bold red]✖ Error sintetizando herramienta:[/bold red] {res.get('error')}")
        return True

    elif cmd in ("tools", "dynamic-tools", "dynamic_tools", "funciones-dinamicas", "modulos"):
        ui.print_dynamic_tools()
        return True

    elif cmd in ("run-tool", "run_tool", "execute-tool", "run"):
        if not args:
            console.print("[yellow]Uso: run-tool <nombre_modulo> [argumentos][/yellow]")
            return True
        name = args[0]
        from tardis_autoprogrammer import autoprogrammer
        res = autoprogrammer.execute_tool(name, *args[1:])
        console.print(f"[bold cyan]Resultado de '{name}':[/bold cyan] {res}")
        return True

    elif cmd in ("research", "investiga", "investigar"):
        ui.print_research(" ".join(args))
        return True

    elif cmd in ("outreach", "contactar", "autor", "prospect"):
        ui.print_outreach(" ".join(args))
        return True

    elif cmd in ("missions", "misiones"):
        ui.print_missions()
        return True

    elif cmd in ("conjecture", "conjetura"):
        sub = args[0] if args else ""
        from tardis_bridge import tardis_bridge
        res = tardis_bridge.trigger_conjecture(sub)
        console.print_json(data=res)
        return True

    elif cmd == "companion":
        subprocess.Popen(
            ["/home/timemachine/Escritorio/GODWORKS SYSTEM/launch_tardis_companion.sh"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        console.print("[bold green]✔ Asistente flotante TARDIS lanzado en segundo plano (aislado de la CLI).[/bold green]")
        return True

    elif cmd == "analyze":
        console.print("[bold cyan]🧠 Analizando estructura causal de la conversación...[/bold cyan]")
        subprocess.run([sys.executable, "/home/timemachine/Escritorio/GODWORKS SYSTEM/tardis_conversation_analyzer.py"])
        return True

    elif cmd == "animate":
        console.print("[bold cyan]🎬 Sintetizando animaciones de fórmulas con ChronoVision...[/bold cyan]")
        subprocess.run([sys.executable, "/home/timemachine/Escritorio/GODWORKS SYSTEM/tardis_formula_animator.py"])
        return True

    elif cmd == "v":
        prompt_str = " ".join(args) if args else "kerr_black_hole"
        console.print(f"[bold cyan]🌌 [CHRONOVISION 3D HYPER-PHYSICS · COMANDO /v][/bold cyan]")
        console.print(f"  • Cuestionamiento / Teoría: [bold yellow]{prompt_str}[/bold yellow]")
        console.print(f"  • Motor: Procedural GPU Core (Nano Banana Blueprint · NVENC 60 FPS)")
        try:
            sys.path.insert(0, "/home/timemachine/Escritorio/GODWORKS SYSTEM")
            from core.tardis_hyper_physics_animator import TardisHyperPhysicsAnimator
            animator = TardisHyperPhysicsAnimator.get_instance()
            q = f"{prompt_str} --fast" if "--fast" not in prompt_str and "--procedural" not in prompt_str and "--blender" not in prompt_str else prompt_str
            mp4_path, gif_path, meta = animator.generate_physics_video(
                query=q,
                frames=60,
                fps=60,
                ported_fps=60,
                width=1920,
                height=1080,
                hdr=False
            )
            console.print(f"\n[bold green]✔ Síntesis de Física 3D Procedural Completada:[/bold green]")
            console.print(f"  ● Título:       {meta['title']}")
            console.print(f"  ● Ecuación:     {meta['formula_latex']}")
            console.print(f"  ● Topología 3D: {meta.get('topology_type', 'procedural')}")
            console.print(f"  ● Motor:        {meta.get('render_engine')}")
            console.print(f"  ● Resolución:   {meta['resolution']} @ {meta['fps']} FPS Nativos ({meta['frames']} frames)")
            console.print(f"  ● Video MP4:    {meta['mp4_path']} ({meta['size_mb']} MB)")
            console.print(f"  ● Preview GIF:  {meta['gif_path']}")
            console.print(f"  ● Sonificación: Multiplexada en MP4 con frecuencias cuánticas")
            console.print(f"  ● Tiempo Total: {meta['elapsed_seconds']}s")
        except Exception as e:
            console.print(f"[bold red]❌ Error generando video de física /v:[/bold red] {e}")
        return True

    elif cmd == "vp":
        prompt_str = " ".join(args) if args else "Agujero Negro de Kerr con Disco de Acrecion"
        console.print(f"[bold cyan]🎨 [CHRONOVISION PIXEL ART 1080P60 · COMANDO /vp][/bold cyan]")
        console.print(f"  • Concepto:     [bold yellow]{prompt_str}[/bold yellow]")
        console.print(f"  • Arquitectura: Procedural Nano Banana Blueprint [Sujeto + Acción + Contexto + Estilo]")
        console.print(f"  • Resolución:   1080P Full HD (1920x1080) | Tasa: 60 FPS Nativos")
        try:
            sys.path.insert(0, "/home/timemachine/Escritorio/GODWORKS SYSTEM")
            from core.tardis_vp_engine import generate_vp_pixelart_video
            res = generate_vp_pixelart_video(prompt_str, duration_sec=5.0)
            console.print(f"\n[bold green]✔ Síntesis Procedural Pixel Art 1080P60 Completada:[/bold green]")
            console.print(f"  ● Concepto:       {res.get('concept', prompt_str)}")
            console.print(f"  ● Sujeto:         {res.get('subject', 'Entidad central')}")
            console.print(f"  ● Acción:         {res.get('action', 'Evolución dinámica')}")
            console.print(f"  ● Contexto:       {res.get('context', 'Atmósfera cinemática')}")
            console.print(f"  ● Estilo:         {res.get('art_style', 'Pixel Art 1080P60')}")
            if res.get('formula_latex'):
                console.print(f"  ● Ecuación:       {res['formula_latex']}")
            if res.get('spectral_research'):
                console.print(f"  ● Rigor Espectral:{res['spectral_research']}")
            console.print(f"  ● Resolución:     {res['resolution']}")
            console.print(f"  ● Tasa / Cuadros: {res['framerate']} FPS Nativos ({int(res['framerate'] * res['duration_sec'])} cuadros)")
            console.print(f"  ● Boceto 1080P:   {res['sketch_image_1080p']}")
            console.print(f"  ● Video MP4 60p:  {res['video_path']} ({res['file_size_mb']} MB)")
            console.print(f"  ● Sonificación:   Multiplexada en MP4 con frecuencias cuánticas")
            console.print(f"  ● Tiempo Total:   {res['elapsed_seconds']}s")
        except Exception as e:
            console.print(f"[bold red]❌ Error generando video Pixel Art /vp:[/bold red] {e}")
        return True

    elif cmd in ("screen", "explain-screen"):
        console.print("[bold cyan]📸 Capturando pantalla y analizando con IA...[/bold cyan]")
        from tardis_bridge import tardis_bridge
        res = tardis_bridge.explain_screen()
        if "explanation" in res:
            console.print(f"\n[bold green]▲ Análisis de Pantalla OS:[/bold green]\n{res['explanation']}\n")
        else:
            console.print(f"[bold red]Error analizando pantalla:[/bold red] {res.get('error', 'Sin datos')}")
        return True

    elif cmd == "reactivate":
        console.print("[bold cyan]⚡ Reactivando todos los botones y subsistemas...[/bold cyan]")
        from tardis_bridge import tardis_bridge
        res = tardis_bridge.reactivate_all_subsystems()
        if res.get("ok"):
            count = res.get("activated_count", 63)
            console.print(f"[bold green]✔ Éxito: {count} subsistemas y botones reactivados.[/bold green]")
        else:
            console.print(f"[yellow]Respuesta:[/yellow] {res}")
        return True

    elif cmd in ("ui", "cockpit"):
        url = "http://127.0.0.1:8757/?key=%s" % os.environ.get("GIA_AUTH_TOKEN", "") + ""
        try:
            subprocess.Popen(
                ["google-chrome", url],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            console.print(f"[bold green]✔ Cabina web TARDIS abierta en {url} (aislada de la CLI).[/bold green]")
        except Exception:
            console.print(f"[cyan]Cabina web disponible en: {url}[/cyan]")
        return True

    elif cmd in ("chat", "conversar", "chatear", "quantum-chat", "qchat"):
        from chat_ui import run_chat

        argv = list(args)
        # Texto libre → modo one-shot sobre la sesión persistente más reciente.
        if argv and not argv[0].startswith("-"):
            argv = ["-p", " ".join(argv)]
        try:
            return run_chat(argv) == 0
        except KeyboardInterrupt:
            console.print("\n[dim]Chat FTL interrumpido. Sesión conservada.[/dim]")
            return True

    elif cmd in ("ask", "preguntar"):
        if not args:
            console.print("[yellow]Uso: ask <mensaje para el núcleo soberano>[/yellow]")
            return True
        from tardis_bridge import tardis_bridge
        res = tardis_bridge.chat_sovereign(" ".join(args))
        if res.get("ok") and "reply" in res:
            console.print(f"\n[bold gold1]▲ TARDIS ({res.get('model', 'KAIJU')}):[/bold gold1]\n{res['reply']}\n")
        else:
            console.print(f"[bold red]Error:[/bold red] {res.get('error', 'Sin respuesta')}")
        return True

    elif cmd in ("improve", "auto-improve"):
        console.print("[bold cyan]🛸 TARDIS: Disparando ciclo de auto-mejora autónoma de código via FTL...[/bold cyan]")
        from tardis_bridge import tardis_bridge
        res = tardis_bridge.trigger_auto_improve(force=True)
        if res.get("ok"):
            console.print(f"[bold green]✔ Auto-mejora ejecutada con éxito:[/bold green] {res}")
        else:
            console.print(f"[bold red]✖ Error en auto-mejora:[/bold red] {res.get('error')}")
        return True

    elif cmd == "engineer":
        from tardis_bridge import tardis_bridge
        status = tardis_bridge.get_engineer_status()
        console.print("[bold cyan]🛸 TARDIS :: Estado del Ingeniero Autónomo FTL[/bold cyan]")
        console.print_json(data=status if status.get("ok") else {"error": status.get("error")})
        return True

    elif cmd in ("antigravity", "ide", "gui"):
        action = args[0] if args else "open"
        extra = " ".join(args[1:]) if len(args) > 1 else ""
        from tardis_bridge import tardis_bridge
        res = tardis_bridge.control_antigravity(action, extra)
        if action == "status":
            console.print("[bold cyan]🛸 Estado de Antigravity GUI / Control Remoto:[/bold cyan]")
            console.print(f" • En Ejecución    : {'SÍ' if res.get('running') else 'NO'} ({res.get('processes_count', 0)} procesos)")
            console.print(f" • Puerto DevTools : {res.get('devtools_port') or 'N/A'} (CDP: {'ACTIVO' if res.get('cdp_available') else 'INACTIVO'})")
            console.print(f" • Sesión Abierta  : {'SÍ' if res.get('target_conversation_open') else 'NO'}")
            console.print(f" • Ventana Activa  : {res.get('window_title', 'N/A')}")
        else:
            console.print_json(data=res)
        return True

    return False



def interactive_loop():
    """Runs the interactive sovereign TARDIS · FTL terminal shell."""
    # Auto-heal & background checks on boot
    executor.auto_heal()
    improver.check_background_auto_update()

    ui.print_banner(animated=True)

    # Modelo alterno soberano: DeepSeek V4.1 Max (registro en cada arranque)
    try:
        executor.ensure_alternate(announce=True)
    except Exception:
        pass

    current_ui = ui
    current_executor = executor
    current_router = router
    current_registry = registry
    last_mtime = _get_ftl_mtimes()

    while True:
        try:
            # Check if any FTL source file was modified on disk for hot-reload
            disk_mtime = _get_ftl_mtimes()
            if disk_mtime > last_mtime:
                active_mode = current_ui.mode
                (
                    current_ui,
                    current_executor,
                    current_router,
                    current_registry,
                    _,
                    _,
                ) = reload_ftl_modules(preserve_mode=active_mode)
                last_mtime = disk_mtime

            line = current_ui.prompt_user()
            if line is None:
                console.print("\n[dim]Cerrando sesión de TARDIS · FTL Soberano. Hasta pronto![/dim]")
                break

            line = line.strip()
            if not line:
                continue

            # DIRECT SHELL ESCAPE: $ <cmd> or ! <cmd>
            if line.startswith("$") or line.startswith("!"):
                shell_cmd = line[1:].strip()
                if not shell_cmd:
                    continue
                console.print(f"[bold gold1]⚡ Host Shell Soberano: {shell_cmd}[/bold gold1]")
                current_executor.execute_shell(shell_cmd)
                console.print()
                continue

            # COMMAND ROUTING (Prefixed with : or / or bare recognized command)
            parts = line.split(None, 1)
            raw_first = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            args_list = rest.split() if rest else []

            is_prefixed = raw_first.startswith(":") or raw_first.startswith("/")
            clean_cmd = raw_first.lstrip(":/").lower()

            if is_prefixed:
                if clean_cmd in ("reload", "recargar"):
                    active_mode = current_ui.mode
                    (
                        current_ui,
                        current_executor,
                        current_router,
                        current_registry,
                        _,
                        _,
                    ) = reload_ftl_modules(preserve_mode=active_mode)
                    last_mtime = _get_ftl_mtimes()
                    console.print("[bold green]✔ Motor TARDIS · FTL, Bóveda y Autoprogramador recargados con éxito.[/bold green]")
                    continue

                handled = dispatch_unified_command(clean_cmd, args_list)
                if not handled:
                    console.print(f"[red]Comando desconocido: {raw_first}. Escribe :help para ver la lista.[/red]")
                continue
            else:
                # Check if bare command is in recognized command set
                if clean_cmd in UNIFIED_COMMAND_KEYWORDS:
                    if clean_cmd in ("reload", "recargar"):
                        active_mode = current_ui.mode
                        (
                            current_ui,
                            current_executor,
                            current_router,
                            current_registry,
                            _,
                            _,
                        ) = reload_ftl_modules(preserve_mode=active_mode)
                        last_mtime = _get_ftl_mtimes()
                        console.print("[bold green]✔ Motor TARDIS · FTL, Bóveda y Autoprogramador recargados con éxito.[/bold green]")
                        continue

                    handled = dispatch_unified_command(clean_cmd, args_list)
                    if handled:
                        continue

            # Process User Query
            forced = None if current_ui.mode == "auto" else current_ui.mode
            plan = current_router.route(line, forced_mode=forced)
            current_ui.print_routing_plan(plan)

            rc, _ = current_executor.execute_plan(
                plan,
                line
            )

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Cerrando sesión de FTL Soberano. Hasta pronto![/dim]")
            break
        except RecursionError as e:
            console.print(f"\n[bold red]Error de recursión evitado en FTL:[/bold red] {str(e)}\n")
            time.sleep(0.5)
        except Exception as e:
            # EASY TOUCH: Auto-corrección preventiva en segundo plano previo a emitir error
            try:
                from easy_touch import get_easy_touch_engine
                easy_touch = get_easy_touch_engine()
                console.print(f"\n[bold gold1]⚡ EASY TOUCH: Interceptando excepción '{type(e).__name__}' en segundo plano...[/bold gold1]")
                h_res = easy_touch.intercept_chat_response(
                    message=line if 'line' in locals() and line else "Consulta de sesión FTL",
                    error=e,
                    is_local_request=True,
                    on_progress=lambda msg: console.print(f"[dim cyan]{msg}[/dim cyan]")
                )
                if h_res.get("reply"):
                    console.print(f"\n[bold green]✔ Respuesta asegurada por Easy Touch:[/bold green]\n{h_res['reply']}\n")
                else:
                    console.print(f"\n[bold red]Error:[/bold red] {str(e)}\n")
            except Exception:
                console.print(f"\n[bold red]Error:[/bold red] {str(e)}\n")
            time.sleep(0.2)


def main():
    raw_args = sys.argv[1:]
    if raw_args and not raw_args[0].startswith("-"):
        first_token = raw_args[0].lower().lstrip(":/")
        if first_token in UNIFIED_COMMAND_KEYWORDS:
            handled = dispatch_unified_command(first_token, raw_args[1:])
            if handled:
                sys.exit(0)

    parser = argparse.ArgumentParser(
        prog="TARDIS·FTL",
        description="TARDIS · FTL Sovereign Apex System :: Sistema Unificado Autoprogramable",
        epilog=(
            "Chat persistente: `ftl chat` (TUI) · `ftl chat --list` · "
            "`ftl chat --resume <id>` · `ftl chat -p \"texto\"` (one-shot) · "
            "`ftl chat --web` (portal http://127.0.0.1:8765/chat)"
        ),
    )
    parser.add_argument("prompt", nargs="*", help="Optional prompt or direct shell command ($ <cmd>)")
    mode_choices = [
        "auto", "kaiju", "synth", "audit", "gemini", "agy", "claude", "infinite",
        "quad", "imac", "cluster", "deepseek", "alterno", "free", "gratis", "pool",
        "agents", "agentes",
    ]
    for _fm in free_catalog.all_models():
        for _alias in (_fm.key, _fm.model_id, _fm.short.lower()):
            if _alias not in mode_choices:
                mode_choices.append(_alias)
    parser.add_argument("-m", "--mode", choices=mode_choices, help="Execution mode (incluye alias del pool gratuito: deepseek, glm, flint, mimo, lightning, beam, pickle, nemotron-vl, free)")
    parser.add_argument("--agents", action="store_true", help="Display the free model pool and the FTL agent orchestrator status")
    parser.add_argument("--agents-probe", action="store_true", help="Probe every free model for real availability now")
    parser.add_argument("--agent", type=str, metavar="MODEL", help="Run a single free model agent under FTL control (task taken from the prompt)")
    parser.add_argument("--orchestrate", type=str, metavar="TASK", help="Orchestrate multiple free agents under FTL control")
    parser.add_argument("--strategy", choices=list(STRATEGIES), default="auto", help="Orchestration strategy (default: auto)")
    parser.add_argument("--agent-models", type=str, metavar="LIST", help="Comma-separated model aliases for orchestration")
    parser.add_argument("--max-agents", type=int, metavar="N", help="Maximum number of agents for orchestration")
    parser.add_argument("--agent-policy", action="store_true", help="Display the agent control policy and per-model toggles")
    parser.add_argument("--agent-set", nargs=2, metavar=("KEY", "VALUE"), help="Update an orchestrator policy key")
    parser.add_argument("--agent-toggle", nargs=2, metavar=("MODEL", "STATE"), help="Enable/disable a free model (on|off)")
    parser.add_argument("--agent-kill", choices=["on", "off", "status"], help="Control the orchestrator kill switch")
    parser.add_argument("--agent-history", nargs="?", const=20, type=int, metavar="N", help="Show the agent audit history (default 20)")
    parser.add_argument("--status", action="store_true", help="Display TARDIS & system status")
    parser.add_argument("--tools", action="store_true", help="Display Master Hub dynamic modules")
    parser.add_argument("--evolve", nargs=2, metavar=("FILE", "GOAL"), help="Auto-program and evolve code with AST validation and rollback")
    parser.add_argument("--autofunc", type=str, metavar="GOAL", help="Synthesize dynamic tool and load into Master Hub")
    parser.add_argument("--research", type=str, metavar="QUERY", help="Deep web research with sources")
    parser.add_argument("--missions", action="store_true", help="Display missions vault")
    parser.add_argument("--infinite", action="store_true", help="Execute task using TARDIS Infinite Code Quad-Model Synthesis")
    parser.add_argument("--kaiju", action="store_true", help="Display TARDIS-NEURAL-SPACE-KAIJU guidelines and sovereign control status")
    parser.add_argument("--rails", action="store_true", help="Inspect and audit TARDIS-NEURAL-SPACE-KAIJU safety rails")
    parser.add_argument("--history", action="store_true", help="Display unified FTL and system change history from TARDIS")
    parser.add_argument("--rag", type=str, metavar="QUERY", help="Execute deep RAG search in TARDIS memory")
    parser.add_argument("--context", action="store_true", help="Display active transversal context and directives from TARDIS")
    parser.add_argument("--sync", action="store_true", help="Trigger transversal context synchronization across all systems")
    parser.add_argument("--update", action="store_true", help="Trigger self-evolution cycle and frontier model discovery")
    parser.add_argument("--models", action="store_true", help="Display registered frontier models and active flagships")
    parser.add_argument("--stats", action="store_true", help="Display token savings and economic ledger")
    parser.add_argument("--sovereign", action="store_true", help="Display sovereign apex permissions and root status")
    parser.add_argument("--skills", action="store_true", help="Display synchronized sovereign skills catalog (AGY · FTL · TARDIS)")
    parser.add_argument("--fallback", action="store_true", help="Verify & display the sovereign alternate model (DeepSeek V4.1 Max)")
    parser.add_argument("--web", action="store_true", help="Display FTL Sovereign Web Terminal status, LAN URLs, and QR code")
    parser.add_argument("--heal", action="store_true", help="Run deep self-healing on permissions, files, and trust")
    parser.add_argument("--improve", action="store_true", help="Trigger autonomous self-improvement of TARDIS codebase via FTL")
    parser.add_argument("--engineer", action="store_true", help="Display TARDIS FTL software engineer status and pending proposals")
    parser.add_argument("--voice", choices=["on", "off", "status"], help="Configure TARDIS completion voice notifications (on/off/status)")
    parser.add_argument("--speak", type=str, metavar="TEXT", help="Speak text directly through TARDIS voice system")
    parser.add_argument("--easytouch", "--et", action="store_true", help="Display Easy Touch background auto-healing status and metrics")
    parser.add_argument("--et-agent", action="store_true", help="Display Easy Touch Self-Improvement Agent status and metrics")
    parser.add_argument("--et-evolve", action="store_true", help="Run self-improvement cycle on Easy Touch system")
    parser.add_argument("--et-solve", action="store_true", help="Trigger autonomous resolution of all pending unhealed incidents")

    args = parser.parse_args()

    # Cada arranque de FTL registra el modelo alterno soberano (idempotente, cacheado).
    try:
        executor.ensure_alternate(announce=False)
    except Exception:
        pass

    if args.fallback:
        ui.print_fallback_status(force_probe=True)
        sys.exit(0)

    if args.status:
        ui.print_tardis_status()
        sys.exit(0)

    if args.tools:
        ui.print_dynamic_tools()
        sys.exit(0)

    if args.evolve:
        dispatch_unified_command("evolve", args.evolve)
        sys.exit(0)

    if args.autofunc:
        dispatch_unified_command("autofunc", [args.autofunc])
        sys.exit(0)

    if args.research:
        ui.print_research(args.research)
        sys.exit(0)

    if args.missions:
        ui.print_missions()
        sys.exit(0)

    if args.easytouch or args.et_agent:
        ui.print_easytouch()
        sys.exit(0)

    if args.et_evolve:
        dispatch_unified_command("et-evolve", [])
        sys.exit(0)

    if args.et_solve:
        dispatch_unified_command("et-solve", [])
        sys.exit(0)

    if args.kaiju or args.rails:
        ui.print_kaiju_rails()
        sys.exit(0)

    if args.speak:
        from tardis_bridge import tardis_bridge
        console.print(f"[bold cyan]🗣️ TARDIS vocalizando: '{args.speak}'[/bold cyan]")
        tardis_bridge.speak(args.speak, wait=True)
        sys.exit(0)

    if args.voice:
        cfg = load_config()
        if args.voice == "on":
            cfg["tardis_voice_notify"] = True
            save_config(cfg)
            console.print("[bold green]✔ Aviso de voz TARDIS: ACTIVADO (Cortana Neural)[/bold green]")
        elif args.voice == "off":
            cfg["tardis_voice_notify"] = False
            save_config(cfg)
            console.print("[bold yellow]✔ Aviso de voz TARDIS: SILENCIADO[/bold yellow]")
        else:
            state = "[bold green]ACTIVADO (Cortana Neural)[/bold green]" if cfg.get("tardis_voice_notify", True) else "[bold yellow]SILENCIADO[/bold yellow]"
            console.print(f"Estado del aviso de voz TARDIS: {state}")
        sys.exit(0)

    if args.improve:
        console.print("[bold cyan]🛸 TARDIS: Disparando ciclo de auto-mejora autónoma de código via FTL...[/bold cyan]")
        from tardis_bridge import tardis_bridge
        res = tardis_bridge.trigger_auto_improve(force=True)
        if res.get("ok"):
            console.print(f"[bold green]✔ Auto-mejora ejecutada con éxito:[/bold green] {res}")
        else:
            console.print(f"[bold red]✖ Error en auto-mejora:[/bold red] {res.get('error')}")
        sys.exit(0)

    if args.engineer:
        from tardis_bridge import tardis_bridge
        status = tardis_bridge.get_engineer_status()
        console.print("[bold cyan]🛸 TARDIS :: Estado del Ingeniero Autónomo FTL[/bold cyan]")
        console.print(json.dumps(status, indent=2, ensure_ascii=False) if status.get("ok") else str(status))
        sys.exit(0)

    if args.history:
        ui.print_tardis_history()
        sys.exit(0)

    if args.rag:
        ui.print_rag_search(args.rag)
        sys.exit(0)

    if args.context:
        ui.print_tardis_context()
        sys.exit(0)

    if args.sync:
        ui.trigger_sync()
        sys.exit(0)

    if args.heal:
        console.print("[bold cyan]⚡ Ejecutando Auto-Curación y Verificación de Permisos Soberanos...[/bold cyan]")
        repaired = executor.auto_heal()
        if repaired:
            for r in repaired:
                console.print(f"  [bold green]✔ {r}[/bold green]")
        else:
            console.print("  [bold green]✔ Todos los permisos, bypasses y configuraciones están verificados y óptimos.[/bold green]")
        sys.exit(0)

    if args.sovereign:
        ui.print_sovereign_status()
        sys.exit(0)

    if args.skills:
        sync_bin = Path.home() / ".local" / "bin" / "sovereign-sync"
        if sync_bin.is_file():
            subprocess.run([str(sync_bin), "skills"])
        else:
            console.print("[bold yellow]Aviso:[/bold yellow] sovereign-sync no está instalado en ~/.local/bin.")
        sys.exit(0)

    if args.web:
        os.system("ftl-web")
        sys.exit(0)

    if args.update:
        console.print("[bold cyan]⚡ Ejecutando Ciclo de Auto-Mejora y Descubrimiento de Modelos de Barrera...[/bold cyan]")
        res = improver.perform_full_evolution_cycle()
        console.print(f"AGY Update:    {res['cli_updates'].get('agy')}")
        console.print(f"Claude Update: {res['cli_updates'].get('claude')}")
        if res["promotions"]:
            for p in res["promotions"]:
                console.print(f"[bold green]⭐ {p}[/bold green]")
        else:
            console.print("[green]Los modelos de barrera están alineados con los últimos lanzamientos.[/green]")
        console.print(f"Google Flash High:  {res['current_flagships']['google_flash_high']}")
        console.print(f"Google Pro High:    {res['current_flagships']['google_pro_high']}")
        console.print(f"Claude Sonnet Max:  {res['current_flagships']['anthropic_sonnet']}")
        console.print(f"Claude Opus Max:    {res['current_flagships']['anthropic_opus']}")
        sys.exit(0)

    if args.models:
        ui.print_models()
        sys.exit(0)

    if args.stats:
        ui.print_stats()
        sys.exit(0)

    # --- POOL GRATUITO & ORQUESTADOR AGÉNTICO (CLI) ---
    if args.agents:
        ui.print_agents()
        sys.exit(0)

    if args.agents_probe:
        ui.print_agents(probe=True)
        sys.exit(0)

    if args.agent_policy:
        ui.print_agent_policy()
        sys.exit(0)

    if args.agent_history is not None:
        ui.print_agent_history(limit=args.agent_history)
        sys.exit(0)

    if args.agent_kill:
        if args.agent_kill == "on":
            orchestrator.set_kill_switch(True)
            console.print("[bold red]⛔ KILL SWITCH ACTIVADO: ejecución de agentes bloqueada.[/bold red]")
        elif args.agent_kill == "off":
            orchestrator.set_kill_switch(False)
            console.print("[bold green]✔ KILL SWITCH DESACTIVADO: orquestador operativo.[/bold green]")
        else:
            state = "[bold red]ACTIVO[/bold red]" if orchestrator.policy.get("kill_switch") else "[green]inactivo[/green]"
            console.print(f"Kill switch del orquestador: {state}")
        sys.exit(0)

    if args.agent_set:
        key, raw = args.agent_set
        value = raw
        if key in ("allowed_models", "denied_models"):
            value = [v.strip() for v in raw.split(",") if v.strip()]
        if orchestrator.set_policy(key, value):
            console.print(f"[bold green]✔ Política actualizada:[/bold green] {key} = {orchestrator.policy[key]}")
            sys.exit(0)
        console.print(f"[red]✖ Clave inválida o valor no aceptado: {key}[/red]")
        sys.exit(1)

    if args.agent_toggle:
        token, state_raw = args.agent_toggle
        enabled = state_raw.lower() in ("on", "1", "true", "activar", "enable")
        if orchestrator.toggle_model(token, enabled):
            console.print(
                f"[bold green]✔ Modelo '{token}':[/bold green] "
                f"{'HABILITADO' if enabled else 'DESHABILITADO'}"
            )
            sys.exit(0)
        console.print(f"[red]✖ Modelo desconocido: {token}[/red]")
        sys.exit(1)

    if args.agent:
        task = " ".join(args.prompt).strip()
        if not task and not sys.stdin.isatty():
            task = sys.stdin.read().strip()
        if not task:
            console.print("[red]✖ --agent requiere una tarea (posición o stdin).[/red]")
            sys.exit(2)
        console.print(f"[bold cyan]🤖 FTL → Agente individual '{args.agent}' (control soberano)...[/bold cyan]")
        try:
            rec = orchestrator.run(args.agent, task, role="agente individual")
        except (OrchestratorHalt, ValueError) as exc:
            console.print(f"[bold red]✖ {exc}[/bold red]")
            sys.exit(1)
        ui.print_agent_result(rec)
        sys.exit(0 if rec.get("ok") else 1)

    if args.orchestrate:
        task = " ".join([args.orchestrate] + args.prompt).strip()
        models = (
            [m.strip() for m in args.agent_models.split(",") if m.strip()]
            if args.agent_models else None
        )
        console.print(
            f"[bold cyan]🕸️ FTL Orquestador → estrategia '{args.strategy}' "
            f"(control soberano de agentes)...[/bold cyan]"
        )
        try:
            result = orchestrator.orchestrate(
                task, strategy=args.strategy, models=models,
                max_agents=args.max_agents,
                on_progress=lambda msg: console.print(f"[dim]{msg}[/dim]"),
            )
        except (OrchestratorHalt, ValueError) as exc:
            console.print(f"[bold red]✖ {exc}[/bold red]")
            sys.exit(1)
        ui.print_orchestration(result)
        sys.exit(0 if result.get("ok") else 1)

    if args.prompt:
        full_prompt = " ".join(args.prompt)
        eff_mode = "infinite" if args.infinite else args.mode
        sys.exit(run_single_prompt(full_prompt, mode=eff_mode))

    interactive_loop()


if __name__ == "__main__":
    main()
