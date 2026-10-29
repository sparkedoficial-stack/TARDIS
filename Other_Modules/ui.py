"""
FTL Terminal User Interface (TUI)
Sovereign Apex Terminal with Rich formatting, prompt_toolkit, and Direct Host Shell.
"""

import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

# PATH soberano antes de cualquier subproceso (systemd / Telegram / web).
import runtime_env  # noqa: F401
import terminal_guard

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.box import DOUBLE, ROUNDED
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ==============================================================================
# SAFEGUARD: Neutralize prompt_toolkit "Window too small" on iPad / Mobile / Split
# ==============================================================================
try:
    import prompt_toolkit.layout.containers as _pt_containers
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.containers import Window as _PTWindow

    # 1. Neutralize the blocking red "Window too small" banner
    _pt_containers._window_too_small = lambda: _PTWindow(
        FormattedTextControl(text=""),
        height=0,
        dont_extend_height=True
    )

    # 2. Resilient height division: allocate remaining space instead of failing with None
    # IDEMPOTENT: Store true unpatched method to prevent recursive wrapping across reloads
    if not hasattr(_pt_containers.HSplit, "_ftl_orig_divide_heights"):
        _pt_containers.HSplit._ftl_orig_divide_heights = _pt_containers.HSplit._divide_heights

        def _safe_divide_heights(self, write_position):
            res = self._ftl_orig_divide_heights(write_position)
            if res is None and write_position.height > 0:
                children = self._all_children
                if not children:
                    return []
                alloc = [0] * len(children)
                alloc[0] = write_position.height
                return alloc
            return res

        _pt_containers.HSplit._divide_heights = _safe_divide_heights

    # 3. Resilient width division: allocate width instead of failing with None
    # IDEMPOTENT: Store true unpatched method to prevent recursive wrapping across reloads
    if not hasattr(_pt_containers.VSplit, "_ftl_orig_divide_widths"):
        _pt_containers.VSplit._ftl_orig_divide_widths = _pt_containers.VSplit._divide_widths

        def _safe_divide_widths(self, width):
            res = self._ftl_orig_divide_widths(width)
            if res is None and width > 0:
                children = self._all_children
                if not children:
                    return []
                alloc = [0] * len(children)
                alloc[0] = width
                return alloc
            return res

        _pt_containers.VSplit._divide_widths = _safe_divide_widths
except Exception:
    pass

from config import CONFIG_DIR, load_config, load_stats, save_config
from models import registry
from router import RoutingPlan, router
from tardis_bridge import tardis_bridge
from ton618 import get_ton618_art, get_ton618_badge_card, play_ton618_animation

console = Console()

BANNER_ART = r"""[bold cyan]
████████╗ █████╗ ██████╗ ██████╗ ██╗███████╗    ███████╗████████╗██╗     
╚══██╔══╝██╔══██╗██╔══██╗██╔══██╗██║██╔════╝    ██╔════╝╚══██╔══╝██║     
   ██║   ███████║██████╔╝██║  ██║██║███████╗    █████╗     ██║   ██║     
   ██║   ██╔══██║██╔══██╗██║  ██║██║╚════██║    ██╔══╝     ██║   ██║     
   ██║   ██║  ██║██║  ██║██████╔╝██║███████║    ██║        ██║   ███████╗
   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝╚══════╝    ╚═╝        ╚═╝   ╚══════╝[/bold cyan]
[bold white]TARDIS[/bold white] [bold cyan]·[/bold cyan] [bold white]FTL[/bold white] [bold red]APEX SOVEREIGN SYSTEM v26.4[/bold red] [bold gold1]:: SISTEMA UNIFICADO AUTOPROGRAMABLE[/bold gold1]
[bold cyan]🌌 MASCOTA & LOGO SOBERANO: [bold white]TON 618[/bold white] (Singularidad Cuántica · 66B M☉ Quásar Supremo)[/bold cyan]
[bold yellow]⚡ AUTOPROGRAMACIÓN CONTINUA · REESCRITURA AST VALIDADA · MASTER HUB DINÁMICO · BYPASS TOTAL[/bold yellow]
"""

COMMANDS = [
    ":help",
    ":status",
    ":phone",
    ":evolve",
    ":autofunc",
    ":tools",
    ":dynamic-tools",
    ":run-tool",
    ":infinite",
    ":research",
    ":outreach",
    ":missions",
    ":conjecture",
    ":companion",
    ":analyze",
    ":animate",
    ":screen",
    ":reactivate",
    ":ui",
    ":chat",
    ":improve",
    ":engineer",
    ":ton618",
    ":mascot",
    ":mascota",
    ":auto",
    ":kaiju",
    ":synth",
    ":audit",
    ":gemini",
    ":agy",
    ":claude",
    ":rails",
    ":history",
    ":rag",
    ":context",
    ":sync",
    ":models",
    ":update",
    ":stats",
    ":config",
    ":heal",
    ":sovereign",
    ":web",
    ":voice",
    ":speak",
    ":easytouch",
    ":claude-cli",
    ":agy-cli",
    ":clear",
    ":exit",
    ":quit"
]

PT_STYLE = Style.from_dict({
    'prompt': 'ansicyan bold',
    'command': 'ansimagenta bold',
})


class FTLInterface:
    def __init__(self):
        self.config = load_config()
        self.mode = self.config.get("default_mode", "auto")
        history_file = CONFIG_DIR / "history"
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.completer = WordCompleter(COMMANDS, ignore_case=True)
        self._keys = None
        # reserve_space_for_menu=0 prevents prompt_toolkit from demanding 8 rows
        # and displaying the dreaded "Window too small" error on iPads and mobile viewports
        # Construcción diferida: evita el aviso "Input is not a terminal" en modo
        # no interactivo (scripts, `ftl chat -p`, cron, pipes).
        self.session = None

    def _key_bindings(self):
        """Enter envía, Alt+Enter abre línea nueva, Ctrl+C limpia sin abortar."""
        if self._keys is None:
            keys = KeyBindings()

            @keys.add("enter")
            def _submit(event):  # noqa: ANN001
                event.current_buffer.validate_and_handle()

            @keys.add("escape", "enter")
            def _newline(event):  # noqa: ANN001
                event.current_buffer.insert_text("\n")

            @keys.add("c-j")
            def _newline_ctrl(event):  # noqa: ANN001
                event.current_buffer.insert_text("\n")

            @keys.add("c-c")
            def _clear_line(event):  # noqa: ANN001
                event.current_buffer.reset()
                event.app.invalidate()

            self._keys = keys
        return self._keys

    def _prompt_session(self):
        if self.session is None:
            history_file = CONFIG_DIR / "history"
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            self.session = PromptSession(
                history=FileHistory(str(history_file)),
                completer=self.completer,
                style=PT_STYLE,
                # Anti-interferencia: sin menú flotante ni autosugerencias que
                # roben filas o alteren el texto que el Arquitecto escribe.
                reserve_space_for_menu=0,
                complete_while_typing=False,
                complete_in_thread=False,
                enable_history_search=False,
                mouse_support=False,
                multiline=True,
                key_bindings=self._key_bindings(),
                prompt_continuation="  … ",
            )
        return self.session

    def get_git_branch(self) -> str:
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return "none"

    def play_ton618(self, force: bool = True):
        play_ton618_animation(frames=18, delay=0.06, force=force)
        console.print(get_ton618_badge_card())

    def print_banner(self, animated: bool = False):
        if animated:
            play_ton618_animation(frames=18, delay=0.06)
        term_size = shutil.get_terminal_size((80, 24))
        if term_size.lines >= 18 and term_size.columns >= 70:
            console.print(BANNER_ART)
            self.print_hud()
        else:
            self.print_compact_hud()

    def print_compact_hud(self):
        stats = load_stats()
        branch = self.get_git_branch()
        cwd_name = Path.cwd().name or str(Path.cwd())
        saved = stats.get('estimated_usd_saved', 0.0)
        mode_colors = {
            "auto": "bold green",
            "deepseek": "bold blue",
            "infinite": "bold gold1",
            "kaiju": "bold gold1",
            "synth": "bold magenta",
            "audit": "bold yellow",
            "gemini": "bold cyan",
            "agy": "bold cyan",
            "claude": "bold bright_magenta",
            "imac": "bold cyan",
            "cluster": "bold cyan"
        }
        mode_style = mode_colors.get(self.mode, "bold white")
        console.print(f"[bold cyan]⚡ FTL APEX[/bold cyan] [{mode_style}][{self.mode.upper()}][/{mode_style}] [dim]|[/dim] Mascota: [bold cyan]TON 618 (66B M☉)[/bold cyan] [dim]|[/dim] Dir: [bold white]{cwd_name}[/bold white] (git: [cyan]{branch}[/cyan]) [dim]|[/dim] Ahorro: [bold green]${saved:.2f}[/bold green]")
        console.print("[dim]Comandos: :help, :ton618, :stats, :kaiju, :synth, $ <cmd> bash | Prompt listo:[/dim]")

    def print_hud(self):
        stats = load_stats()
        branch = self.get_git_branch()
        cwd_name = Path.cwd().name or str(Path.cwd())

        g_model = registry.get_google_model("flash")
        c_model = registry.get_anthropic_model("sonnet")

        mode_colors = {
            "auto": "bold green",
            "deepseek": "bold blue",
            "infinite": "bold gold1",
            "kaiju": "bold gold1",
            "synth": "bold magenta",
            "audit": "bold yellow",
            "gemini": "bold cyan",
            "agy": "bold cyan",
            "claude": "bold bright_magenta",
            "imac": "bold cyan",
            "cluster": "bold cyan"
        }
        mode_style = mode_colors.get(self.mode, "bold white")

        table = Table(box=ROUNDED, show_header=False, expand=True, padding=(0, 1))
        table.add_column("Left", justify="left")
        table.add_column("Right", justify="right")

        table.add_row(
            f"Modo: [{mode_style}]{self.mode.upper()}[/{mode_style}]  |  Dir: [bold white]{cwd_name}[/bold white] (git: [cyan]{branch}[/cyan])",
            f"USD Ahorrado: [bold green]${stats.get('estimated_usd_saved', 0.0):.2f}[/bold green] | Consultas: [cyan]{stats.get('total_queries', 0)}[/cyan]"
        )
        tardis_status = tardis_bridge.get_status()
        if tardis_status.get("online"):
            mode_lbl = "DAEMON 8757" if tardis_status.get("mode") == "daemon_api" else "SQLITE ZERO-COPY"
            tardis_desc = f"[bold green]CONECTADO ({mode_lbl} | {tardis_status.get('events_count', 0)} ops)[/bold green]"
        else:
            tardis_desc = "[bold yellow]OFFLINE (STANDBY)[/bold yellow]"

        kaiju_status = tardis_bridge.get_kaiju_status()
        omega_mode = kaiju_status.get("omega", {}).get("mode", "UNCHAINED_SOVEREIGN")
        aegis_status = kaiju_status.get("aegis", {}).get("status", "PROTECTED_INVULNERABLE")
        q_temp = kaiju_status.get("quantum", {}).get("temperature", 0.7)
        q_ctx = kaiju_status.get("quantum", {}).get("num_ctx", 32768)

        table.add_row(
            f"Gobernador Supremo: [bold gold1]TARDIS-NEURAL-SPACE-KAIJU[/bold gold1] ([green]{omega_mode}[/green] | [magenta]{aegis_status}[/magenta])",
            f"Mascota Oficial: [bold cyan]TON 618[/bold cyan] ([bold gold1]66B M☉ Quásar[/bold gold1])"
        )

        table.add_row(
            f"Google Frontier: [cyan]{g_model} [bold red](HIGH)[/bold red][/cyan]  |  Anthropic Frontier: [magenta]{c_model} [bold red](MAX)[/bold red][/magenta]",
            f"Parámetros: [cyan]{q_ctx // 1024}K Ctx | Temp {q_temp} | 28GB Mlock[/cyan]"
        )

        alt_model = load_config().get("fallback_model", "opencode/deepseek-v4.1-flash-free#max")
        cfg = load_config()
        default_model = cfg.get("default_model") or alt_model
        table.add_row(
            f"Modelo Default: [bold blue]DeepSeek V4.1 Flash Free[/bold blue] [bold red](MAX)[/bold red] [dim]({default_model})[/dim]",
            "Resiliencia: [bold green]FALLBACK AUTOMÁTICO[/bold green]"
        )
        voice_on = cfg.get("tardis_voice_notify", True)
        voice_lbl = "[bold green]CORTANA NEURAL (ACTIVA)[/bold green]" if voice_on else "[bold yellow]SILENCIADA[/bold yellow]"

        # Estado de Easy Touch
        try:
            from easy_touch import get_easy_touch_engine
            et_st = get_easy_touch_engine().get_status()
            et_lbl = f"[bold green]VIGILANTE ACTIVO ({et_st.get('total_healed', 0)} auto-reparados)[/bold green]"
        except Exception:
            et_lbl = "[bold green]ACTIVO EN BACKGROUND[/bold green]"

        # Estado de Auto-Programación y Master Hub
        try:
            from tardis_autoprogrammer import autoprogrammer
            tools = autoprogrammer.list_dynamic_tools()
            tools_lbl = f"[bold green]{len(tools)} MÓDULOS ACTIVOS[/bold green] ([dim cyan]modulos_ftl/[/dim cyan])"
        except Exception:
            tools_lbl = "[bold green]ACTIVO[/bold green]"

        table.add_row(
            f"Auto-Programación & MasterHub: {tools_lbl}",
            f"Evolución Segura: [bold green]AST VALIDATED + ROLLBACK[/bold green]"
        )
        table.add_row(
            f"Easy Touch Sentinel: {et_lbl}",
            f"TARDIS Memoria RAG: {tardis_desc}"
        )
        table.add_row(
            f"Voz TARDIS (Fin de Tarea): {voice_lbl}",
            f"Directiva Easy Touch: [cyan]Auto-Corrección Preventiva 100%[/cyan]"
        )

        console.print(Panel(table, border_style="gold1", title="[bold gold1]⚡ TARDIS · FTL Sovereign Apex Control Center · Sistema Unificado Autoprogramable[/bold gold1]", subtitle="[dim]Usa :evolve, :autofunc, :tools, :status, :phone, :research, :infinite o $ <cmd>[/dim]"))

    def print_help(self):
        help_table = Table(title="TARDIS · FTL Sovereign Unified System Commands", box=ROUNDED)
        help_table.add_column("Comando", style="bold cyan")
        help_table.add_column("Función / Alcance", style="white")
        help_table.add_column("Categoría / Poder", style="bold gold1")

        # --- AUTO-PROGRAMACIÓN & AUTO-EVOLUCIÓN ---
        help_table.add_row(":evolve <arch> <meta>", "Auto-programa y evoluciona código con validación AST y rollback", "Auto-Programación")
        help_table.add_row(":autofunc <meta>", "Sintetiza una nueva herramienta/función y la carga en MasterHub", "Auto-Programación")
        help_table.add_row(":tools / :dynamic-tools", "Lista las herramientas dinámicas cargadas en modulos_ftl/", "Master Hub")
        help_table.add_row(":run-tool <nombre>", "Ejecuta un módulo dinámico cargado en tiempo real", "Master Hub")
        help_table.add_row(":improve", "Dispara ciclo autónomo de auto-mejora continua de código", "Evolución Continua")

        # --- SUBSISTEMAS TARDIS & HARDWARE ---
        help_table.add_row(":status", "Estado general de TARDIS, Ollama, FTL, API 8757 y nodos", "Telemetría")
        help_table.add_row(":phone [sub] [args]", "Control celular TARDIS POCKET (status, call, hangup, sms, data)", "Telefonía Móvil")
        help_table.add_row(":research <tema>", "Investigación web profunda con fuentes y síntesis", "Investigación")
        help_table.add_row(":outreach <target>", "Prospección autónoma y redacción de propuestas de colaboración", "OSINT / Outreach")
        help_table.add_row(":missions", "Bóveda de misiones, prospectos e invitaciones", "Misiones")
        help_table.add_row(":conjecture [trigger]", "Consulta o fuerza formulación inmediata de conjetura causal", "Centinela")
        help_table.add_row(":companion", "Lanza el asistente flotante interactivo de escritorio", "Escritorio OS")
        help_table.add_row(":voice / :snap", "Asistente de voz TARDIS activado por chasquido de dedos", "Voz & Escucha")
        help_table.add_row(":analyze", "Analiza estructura causal de la conversación", "Causalidad")
        help_table.add_row(":animate", "Sintetiza videos animados de fórmulas con ChronoVision", "ChronoVision")
        help_table.add_row(":screen", "Captura y explica lo que hay en la pantalla del sistema", "Visión OS")
        help_table.add_row(":reactivate", "Reactiva todos los 63 subsistemas y botones de hardware/software", "Hardware")
        help_table.add_row(":ui / :web", "Abre la cabina web en el navegador / Portal y Terminal Web", "Portal LAN")
        help_table.add_row(":chat [--new|--resume|--list] [texto]", "FTL Quantum Chat persistente: sesiones, modelos, agentes, adjuntos, thinking, herramientas y animación de cuásar (motor OpenCode)", "Chat Persistente")
        help_table.add_row(":ask <mensaje>", "Consulta directa al núcleo soberano de TARDIS", "Núcleo Soberano")

        # --- FTL APEX SOVEREIGN ENGINES ---
        help_table.add_row("$ <cmd> / ! <cmd>", "Ejecuta comandos de host bash/root directamente sin salir de FTL", "Soberana Absoluta")
        help_table.add_row(":easytouch / :et", "Vigilante soberano Easy Touch: Auto-corrección preventiva en segundo plano", "Resiliencia Total")
        help_table.add_row(":ton618 / :mascot", "Reproducir animación de TON 618 (Mascota Oficial de FTL · 66B M☉)", "Mascota & Identidad")
        help_table.add_row(":auto", "Enrutador Cognitivo Autónomo (Balancea costo y abstracción)", "Bypass Total")
        help_table.add_row(":infinite", "TARDIS Infinite Code: Fusión Cuádruple (Flash+Pro+Sonnet+Opus) + Cloud Offload", "Fusión Suprema")
        help_table.add_row(":kaiju", "Modo Soberano Supremo TARDIS-NEURAL-SPACE-KAIJU (Omega & Aegis)", "Gobierno Cuántico")
        help_table.add_row(":rails", "Inspeccionar y auditar rieles de seguridad y directivas KAIJU", "Gobernanza")
        help_table.add_row(":synth", "Síntesis Dual Frontier (Gemini Scout High + Claude Architect Max)", "Bypass Total")
        help_table.add_row(":audit", "Auditoría Cruzada Frontier (Claude Max Thinking -> Gemini High)", "Bypass Total")
        help_table.add_row(":gemini / :agy", "Fijar a Google Frontier (gemini-4-argon-high / gemini-3.8-flash-high)", "Bypass Total")
        help_table.add_row(":claude", "Fijar a Anthropic Frontier (claude-opus-5-5-high / sonnet)", "Bypass Total")
        help_table.add_row(":voice [on|off]", "Activar, silenciar o alternar aviso de voz TARDIS al terminar tareas", "Vocalización")
        help_table.add_row(":speak <texto>", "Vocalizar mensaje inmediatamente por bocinas utilizando TARDIS", "Vocalización")
        help_table.add_row(":history", "Historial transversal de operaciones y cambios de sistema en TARDIS", "Memoria Soberana")
        help_table.add_row(":rag <consulta>", "Búsqueda RAG profunda (BM25 FTS5) en memoria histórica de TARDIS", "Recuperación RAG")
        help_table.add_row(":context", "Inspeccionar el contexto transversal y directivas activas de TARDIS", "Contexto Agéntico")
        help_table.add_row(":sync", "Forzar sincronización inmediata de contexto en todos los subsistemas", "Sincronización")
        help_table.add_row(":sovereign", "Muestra el manifiesto de permisos, excepciones y estatus root", "Auditoría de Poder")
        help_table.add_row(":skills / :habilidades", "Catálogo soberano de skills sincronizadas (AGY · FTL · TARDIS)", "Conocimiento Compartido")
        help_table.add_row(":fallback / :alterno", "Verificar el modelo alterno DeepSeek V4.1 Max (fallback automático)", "Resiliencia de Modelo")
        help_table.add_row(":heal", "Auto-reparación profunda de configuraciones, trust y permisos", "Auto-Curación")
        help_table.add_row(":models", "Listar modelos de barrera registrados con máximo esfuerzo", "Frontier Registry")
        help_table.add_row(":update", "Ejecutar auto-mejora de binarios y modelos de frontera", "Evolución Continua")
        help_table.add_row(":stats", "Mostrar libro contable de tokens y dólares ahorrados", "Telemetría")
        help_table.add_row(":claude-cli", "Lanzar Claude Code interactivo nativo", "Bypass Mode")
        help_table.add_row(":agy-cli", "Lanzar Antigravity CLI interactivo nativo", "Bypass Mode")
        help_table.add_row(":clear", "Limpiar pantalla y redibujar HUD", "")
        help_table.add_row(":exit / :quit", "Salir de TARDIS · FTL", "")

        console.print(help_table)

    def print_dynamic_tools(self):
        """Muestra la tabla de herramientas dinámicas cargadas en Master Hub."""
        try:
            from tardis_autoprogrammer import autoprogrammer
            tools = autoprogrammer.list_dynamic_tools()
            table = Table(title="🛸 Master Hub :: Módulos Dinámicos y Herramientas Autoprogramadas", box=ROUNDED)
            table.add_column("Módulo", style="bold cyan")
            table.add_column("Clase Principal", style="bold gold1")
            table.add_column("Ubicación", style="dim white")
            table.add_column("Documentación", style="white")

            if not tools:
                table.add_row("Sin módulos", "-", "modulos_ftl/ está vacío", "Crea uno con :autofunc <meta>")
            else:
                for t in tools:
                    table.add_row(t["name"], t["class"], t["file"], t["doc"] or "Módulo operativo")

            console.print(table)
        except Exception as e:
            console.print(f"[red]Error listando herramientas dinámicas: {e}[/red]")

    def print_tardis_status(self):
        """Muestra el estado detallado de TARDIS y sus servidores."""
        table = Table(title="🛸 TARDIS :: Telemetría y Salud del Sistema v26.4", box=ROUNDED)
        table.add_column("Componente", style="bold cyan")
        table.add_column("Estado", style="bold green")
        table.add_column("Detalles", style="white")

        res = tardis_bridge.get_tardis_telemetry()
        if res.get("ok") or res.get("status") == "online":
            table.add_row("Servidor Central TARDIS", "ONLINE (Puerto 8757)", f"Modelo: {res.get('model', 'KAIJU')} | Ctx: {res.get('num_ctx', 4096)}")
        else:
            table.add_row("Servidor Central TARDIS", "[bold red]OFFLINE[/bold red]", str(res.get("error", "Sin conexión")))

        # iMac Compute Cluster Node
        try:
            import urllib.request
            with urllib.request.urlopen("http://REDACTED_IP:8757/api/status", timeout=1.5) as r:
                imac_data = json.loads(r.read().decode("utf-8"))
                imac_cores = imac_data.get("cpu", {}).get("cores", 4)
                imac_ram = imac_data.get("memory", {}).get("available_mb", 0)
                imac_disk = imac_data.get("disk", {}).get("free_gb", 0)
                table.add_row("Nodo Cómputo iMac 14,1", "ONLINE (Gigabit LAN)", f"{imac_cores} Núcleos Haswell AVX2 | RAM: {imac_ram:.0f} MB | Disco: {imac_disk:.1f} GB")
        except Exception:
            table.add_row("Nodo Cómputo iMac 14,1", "[bold yellow]STANDBY[/bold yellow]", "Inactivo o no accesible")

        # Ollama Cluster & Local
        ollama_found = False
        for host, label in [("http://127.0.0.1:11434", "Motor Ollama (Local)"), ("http://REDACTED_IP:11434", "Motor Ollama (iMac Cluster)")]:
            try:
                import urllib.request
                with urllib.request.urlopen(f"{host}/api/tags", timeout=1.5) as r:
                    tags = json.loads(r.read().decode("utf-8"))
                    models = [m.get("name") for m in tags.get("models", [])]
                    table.add_row(label, "ONLINE", f"Modelos: {', '.join(models[:4])}")
                    ollama_found = True
            except Exception:
                pass
        if not ollama_found:
            table.add_row("Motor Ollama", "[bold yellow]STANDBY[/bold yellow]", "Inactivo o no accesible")

        # Asistente flotante
        res_comp = subprocess.run(["pgrep", "-f", "tardis_desktop_companion.py"], stdout=subprocess.PIPE)
        st_comp = "ACTIVO" if res_comp.returncode == 0 else "Inactivo (ejecuta :companion)"
        table.add_row("Asistente Flotante OS", st_comp, "Overlay GUI de escritorio")

        # Conjeturas
        conj = tardis_bridge.trigger_conjecture()
        if conj.get("ok"):
            st_conj = "ACTIVO" if conj.get("running") else "INACTIVO"
            table.add_row("Centinela de Auto-Mejora", st_conj, f"{conj.get('total_conjectures', 0)} conjeturas formuladas")

        console.print(table)

    def print_phone_status(self, subcmd: str = "status", extra_args: Optional[List[str]] = None):
        """Muestra el estado o resultado de control de telefonía celular TARDIS POCKET."""
        res = tardis_bridge.control_phone(subcmd, extra_args)
        if subcmd in ("status", "estado", "info"):
            if res.get("ok"):
                conn = res.get("connection", {})
                tel = res.get("telephony", {})
                pkt = res.get("pocket", {})
                bat = pkt.get("battery", {})

                table = Table(title="📱 TARDIS POCKET :: Telemetría Móvil y Control Celular", box=ROUNDED)
                table.add_column("Métrica Celular", style="bold cyan")
                table.add_column("Estado", style="bold green")

                table.add_row("Dispositivo", f"{res.get('device')} ({res.get('serial')})")
                table.add_row("Enlace ADB", "CONECTADO" if conn.get("adb_connected") else "[red]DESCONECTADO[/red]")
                table.add_row("Túneles (8080/8757)", f"{'8080 OK' if conn.get('forward_8080') else 'FAIL'} | {'8757 OK' if conn.get('reverse_8757') else 'FAIL'}")
                table.add_row("Tarjeta SIM", "PRESENTE" if tel.get("sim_present") else f"[yellow]SIN SIM ({tel.get('sim_state')})[/yellow]")
                table.add_row("Operador / Red", f"{tel.get('operator') or 'Sin operador'} ({tel.get('network_type')})")
                table.add_row("Batería Móvil", f"{bat.get('level', '?')}% ({'Cargando ⚡' if bat.get('charging') else 'Batería 🔋'})")
                table.add_row("Sub-RIL Activo", str(tel.get("telephony_subsystem")))
                console.print(table)
            else:
                console.print(f"[red]Error consultando estado móvil: {res.get('error')}[/red]")
        else:
            console.print(f"[bold cyan]Resultado de telefonía ({subcmd}):[/bold cyan] {res}")

    def print_missions(self):
        """Muestra el estado de la bóveda de misiones."""
        res = tardis_bridge.get_missions()
        if not res.get("ok"):
            console.print(f"[red]Error al consultar misiones: {res.get('error')}[/red]")
            return
        table = Table(title="🎯 Bóveda de Misiones y Prospección Soberana", box=ROUNDED)
        table.add_column("Métrica", style="bold cyan")
        table.add_column("Valor", style="bold green")

        table.add_row("Misiones Activas", f"{res.get('active_missions')}/{res.get('total_missions')}")
        table.add_row("Prospectos Totales", str(res.get("total_prospects", 0)))
        table.add_row("Invitaciones Token", str(res.get("total_invitations", 0)))
        table.add_row("Sinergia Promedio", f"{int(res.get('avg_synergy', 0)*100)}%")
        stages = res.get("stages", {})
        table.add_row("Estados del Pipeline", f"{stages.get('scouted', 0)} scouted | {stages.get('proposed', 0)} propuestos | {stages.get('contacted', 0)} contactados")
        console.print(table)

    def print_research(self, query: str):
        """Ejecuta e imprime investigación web profunda."""
        if not query:
            console.print("[red]Uso: :research <tema>[/red]")
            return
        console.print(f"[bold cyan]🌐 Investigando en la web sobre: '{query}'...[/bold cyan]")
        res = tardis_bridge.research_topic(query)
        if res.get("ok"):
            rep = res.get("report")
            if isinstance(rep, dict):
                console.print(f"\n[bold gold1]📑 Síntesis ({rep.get('provider_used', 'sovereign')} en {rep.get('elapsed_seconds', 0):.2f}s):[/bold gold1]")
                console.print(Markdown(rep.get("synthesis", "")))
                sources = rep.get("sources", [])
                if sources:
                    console.print("\n[bold cyan]🔗 Fuentes:[/bold cyan]")
                    for s in sources[:5]:
                        if isinstance(s, dict):
                            console.print(f" • [underline]{s.get('title', 'Fuente')}[/underline]: {s.get('url', '')}")
                        else:
                            console.print(f" • {s}")
            else:
                console.print(str(rep))
        else:
            console.print(f"[red]Error en investigación: {res.get('error')}[/red]")

    def print_outreach(self, target: str):
        """Ejecuta prospección de investigadores."""
        if not target:
            console.print("[red]Uso: :outreach <tema o autor>[/red]")
            return
        console.print(f"[bold cyan]🔍 [ORCHESTRATOR / OSINT] Prospección autónoma para '{target}'...[/bold cyan]")
        res = tardis_bridge.scout_outreach(target)
        if not res.get("ok"):
            console.print(f"[red]Error buscando investigadores: {res.get('error')}[/red]")
            return
        disc = res.get("discovered", [])
        console.print(f"[bold green]✔ Se descubrieron {len(disc)} investigadores/fuentes:[/bold green]")
        for p in disc:
            console.print(f"\n[bold white]👤 {p.get('name', 'Investigador')} [ID: {p.get('id')}][/bold white] ([gold1]{int(p.get('synergy_score', 0)*100)}% sinergia[/gold1])")
            if p.get("emails"):
                console.print(f"   • Emails: {', '.join(p['emails'])}")
            if p.get("bio"):
                console.print(f"   • Bio: {p.get('bio')[:120]}...")
        help_table.add_row(":web", "Muestra URLs LAN, estado y código QR de la Terminal y Portal Web", "Acceso Remoto")
        help_table.add_row(":heal", "Auto-reparación profunda de configuraciones, trust y permisos", "Auto-Curación")
        help_table.add_row(":models", "Listar modelos de barrera registrados con máximo esfuerzo", "Frontier Registry")
        help_table.add_row(":update", "Ejecutar auto-mejora de binarios y modelos de frontera", "Evolución Continua")
        help_table.add_row(":stats", "Mostrar libro contable de tokens y dólares ahorrados", "Telemetría")
        help_table.add_row(":claude-cli", "Lanzar Claude Code interactivo nativo", "Bypass Mode")
        help_table.add_row(":agy-cli", "Lanzar Antigravity CLI interactivo nativo", "Bypass Mode")
        help_table.add_row(":clear", "Limpiar pantalla y redibujar HUD", "")
        help_table.add_row(":exit / :quit", "Salir de FTL", "")

        console.print(help_table)

    def print_sovereign_status(self):
        import json as _json
        import subprocess as _sp
        from pathlib import Path as _Path

        sudo_ok = False
        try:
            sudo_ok = _sp.run(
                ["sudo", "-n", "true"],
                stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, timeout=4
            ).returncode == 0
        except Exception:
            sudo_ok = False

        kernel_bits = []
        for key, label in (
            ("kernel.dmesg_restrict", "dmesg"),
            ("kernel.yama.ptrace_scope", "ptrace"),
            ("kernel.kptr_restrict", "kptr"),
        ):
            try:
                value = _sp.run(
                    ["sysctl", "-n", key], capture_output=True, text=True, timeout=3
                ).stdout.strip()
            except Exception:
                value = "?"
            kernel_bits.append(f"{label}={value}")

        skills_total, mirrors_ok = 0, 0
        try:
            catalog = _json.loads(
                (_Path.home() / ".tardis" / "skills" / "catalog.json").read_text(encoding="utf-8")
            )
            skills_total = int(catalog.get("total", 0))
        except Exception:
            pass
        try:
            state = _json.loads(
                (_Path.home() / ".config" / "godworks" / "sovereign_sync" / "state.json")
                .read_text(encoding="utf-8")
            )
            mirrors_ok = len(state.get("skills", {}).get("targets", {}))
        except Exception:
            pass

        table = Table(title="FTL Apex Sovereign Authority & Immunity", box=ROUNDED)
        table.add_column("Dimensión de Control", style="bold cyan")
        table.add_column("Estado", style="bold green")
        table.add_column("Mecanismo Técnico", style="dim white")

        table.add_row(
            "Root / Sudo Host Access",
            "ACTIVO (Passwordless)" if sudo_ok else "DISPONIBLE (con contraseña)",
            "sudo -n validado en vivo; los agentes pueden elevar privilegios en su TTY"
        )
        table.add_row("Direct Host Shell", "HABILITADO", "Prefijos $ y ! ejecutan bash directamente")
        table.add_row("Claude Code Permissions", "BYPASS TOTAL (bypassPermissions)", "skipDangerousModePermissionPrompt: true")
        table.add_row("Antigravity / AGY Permissions", "BYPASS TOTAL (--dangerously-skip-permissions)", "Auto-aprobación absoluta de herramientas")
        table.add_row("Sovereign Skills Sync", f"ACTIVO ({skills_total} skills × {mirrors_ok} destinos)", "~/.agents/skills espejado por sovereign-sync")

        alt_state = {}
        try:
            alt_state = _json.loads(
                (_Path.home() / ".config" / "ftl" / "fallback_state.json").read_text(encoding="utf-8")
            )
        except Exception:
            alt_state = {}
        alt_ok = bool(alt_state.get("available"))
        table.add_row(
            "Modelo Alterno (Fallback)",
            ("VERIFICADO · DeepSeek V4.1 Max" if alt_ok else "REGISTRADO · DeepSeek V4.1 Max"),
            "opencode/deepseek-v4.1-flash-free#max · variante max · automático"
        )
        table.add_row("Kernel Ring 0", "LIBERADO · " + " · ".join(kernel_bits), "dmesg/ptrace/kptr sin restricción para telemetría profunda")
        table.add_row("Sovereign Invariant Injection", "FORZADA EN CADA TURNO", "Inyección del mandato 100% autónomo")
        table.add_row("Auto-Failover Resiliente", "ACTIVO", "Conmutación en milisegundos ante fallas de motor")
        table.add_row("Reasoning Power Enforcement", "MÁXIMA POTENCIA EXCLUSIVA", "Claude: MAX Thinking | AGY: HIGH Effort")

        console.print(table)

    def print_models(self):
        registry.refresh()
        m_table = Table(title="FTL Frontier Models (Máxima Potencia Exclusiva)", box=ROUNDED)
        m_table.add_column("Model ID", style="bold cyan")
        m_table.add_column("Provider", style="yellow")
        m_table.add_column("Tier", style="green")
        m_table.add_column("Effort Level", style="bold red")
        m_table.add_column("Abstraction", style="magenta")
        m_table.add_column("Rel. Cost", style="white")
        m_table.add_column("Flagship Status", style="bold green")

        for mid, m in sorted(registry.models.items(), key=lambda x: (x[1].provider, -x[1].abstraction_score)):
            flag = "⭐ ACTIVE FLAGSHIP" if (mid in registry.flagships.values() or m.is_flagship) else ""
            m_table.add_row(
                m.model_id,
                m.provider.upper(),
                m.tier.upper(),
                m.effort_level.upper(),
                f"{m.abstraction_score}/10",
                f"{m.cost_factor}x",
                flag
            )
        console.print(m_table)

    def print_fallback_status(self, force_probe: bool = False):
        """Muestra el estado verificable del modelo alterno (DeepSeek V4.1 Max)."""
        from executor import executor as _exec

        cfg = load_config()
        state = _exec.ensure_alternate(announce=False, ttl=0 if force_probe else None)
        available = bool(state.get("available"))

        table = Table(title="Modelo Alterno Soberano · DeepSeek V4.1 Max", box=ROUNDED)
        table.add_column("Dimensión", style="bold cyan")
        table.add_column("Estado", style="bold green")

        table.add_row("Modelo", str(cfg.get("fallback_model", "opencode/deepseek-v4.1-flash-free#max")))
        table.add_row("Motor", "OpenCode CLI (headless, sin API key)")
        table.add_row("Variante", str(cfg.get("fallback_variant", "max")))
        table.add_row("Habilitado", "SÍ" if cfg.get("fallback_enabled", True) else "NO")
        table.add_row(
            "Disponibilidad",
            "[bold green]VERIFICADO[/bold green]" if available else "[bold red]NO DISPONIBLE[/bold red]"
        )
        table.add_row("Último chequeo", str(state.get("checked_at", "nunca")))
        table.add_row("Detalle", str(state.get("reason", "")))
        table.add_row("Cadena", " → ".join(cfg.get("fallback_priority", [])))
        table.add_row("Disparo", "Arranque de FTL · fallo de motores primarios · agotamiento de Easy Touch")
        console.print(table)

    def print_agents(self, probe: bool = False):
        """Catálogo de modelos gratuitos + estado del orquestador agéntico."""
        import free_models as fm
        from agent_orchestrator import orchestrator as _orch

        if probe:
            console.print("[bold cyan]🔎 Sondeando el pool gratuito (puede tardar ~1 min)…[/bold cyan]")
            for rec in fm.refresh(force=True):
                if rec.get("skipped"):
                    continue
                ok = rec.get("available")
                console.print(
                    f"   {'✓' if ok else '✗'} {rec.get('key'):16} "
                    f"[dim]{rec.get('latency_s', '?')}s[/dim]"
                    + ("" if ok else f" [red]{str(rec.get('error',''))[:70]}[/red]")
                )

        summary = fm.summary()
        status = _orch.status()
        policy = status["policy"]
        by_model = status["state"].get("by_model", {})

        table = Table(title="FTL · Pool de Modelos Gratuitos & Orquestador Agéntico", box=ROUNDED)
        table.add_column("Alias", style="bold cyan")
        table.add_column("Modelo / Referencia", style="white")
        table.add_column("Especialidad", style="magenta")
        table.add_column("Estado", style="bold green")
        table.add_column("Lat.", justify="right", style="yellow")
        table.add_column("Runs/OK", justify="right", style="dim")

        for m in summary["models"]:
            if m["available"] is True:
                state_lbl = "[bold green]✓ VERIFICADO[/bold green]"
            elif m["available"] is False:
                state_lbl = "[bold red]✗ NO DISP.[/bold red]"
            else:
                state_lbl = "[yellow]… SIN SONDA[/yellow]"
            if not m["enabled"]:
                state_lbl += " [dim](off)[/dim]"
            stats = by_model.get(m["key"], {})
            runs = f"{stats.get('runs', 0)}/{stats.get('ok', 0)}"
            table.add_row(
                m["key"],
                m["ref"],
                ", ".join(m["roles"][:3]),
                state_lbl,
                f"{m['latency_s']}s" if m["latency_s"] else "—",
                runs,
            )
        console.print(table)

        kill = "[bold red]ACTIVO[/bold red]" if policy.get("kill_switch") else "[green]inactivo[/green]"
        enabled = "[green]ON[/green]" if policy.get("enabled") else "[red]OFF[/red]"
        console.print(
            f"[dim]Orquestador:[/dim] {enabled} · kill switch: {kill} · "
            f"concurrencia: [cyan]{policy.get('max_concurrency')}[/cyan] · "
            f"máx agentes: [cyan]{policy.get('max_agents')}[/cyan] · "
            f"timeout: [cyan]{policy.get('default_timeout')}s[/cyan] · "
            f"estrategia: [cyan]{policy.get('default_strategy')}[/cyan]"
        )
        console.print(
            "[dim]Uso:[/dim] :agent \\[alias] \\[tarea] · "
            ":orchestrate [auto|single|fanout|compare|pipeline|race] \\[tarea] · "
            ":agent-policy · :agent-history · :agent-kill on|off"
        )

    def print_agent_policy(self):
        """Política de control del orquestador y toggles por modelo."""
        import free_models as fm
        from agent_orchestrator import orchestrator as _orch, ORCH_DIR

        policy = _orch.policy
        table = Table(title="FTL · Política de Control Agéntico", box=ROUNDED)
        table.add_column("Clave", style="bold cyan")
        table.add_column("Valor", style="bold green")
        for key, value in policy.items():
            table.add_row(key, json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict, bool)) else str(value))
        console.print(table)

        models = Table(title="Control Individual de Modelos", box=ROUNDED)
        models.add_column("Alias", style="cyan")
        models.add_column("Ref", style="white")
        models.add_column("Habilitado", style="green")
        models.add_column("Disponible", style="green")
        for m in fm.all_models():
            st = fm.model_state(m.key)
            models.add_row(
                m.key, m.ref,
                "SÍ" if st.get("enabled", m.enabled_default) else "NO",
                "SÍ" if st.get("available") else ("NO" if st.get("available") is False else "?"),
            )
        console.print(models)
        console.print(f"[dim]Política: {ORCH_DIR / 'policy.json'} · Auditoría: {ORCH_DIR / 'audit.jsonl'}[/dim]")

    def print_agent_result(self, rec: dict):
        """Resultado de un agente individual."""
        ok = rec.get("ok")
        body = rec.get("output") or rec.get("error") or "(sin salida)"
        title = f"{'✔' if ok else '✗'} Agente FTL · {rec.get('model', '?')}"
        subtitle = (
            f"{rec.get('ref', '')} · {rec.get('duration_s', 0)}s · "
            f"rc={rec.get('rc')} · rol={rec.get('role', '')}"
        )
        console.print(Panel(
            Markdown(body),
            title=title,
            subtitle=subtitle,
            border_style="green" if ok else "red",
        ))

    def print_orchestration(self, result: dict):
        """Resultado de una orquestación multi-agente."""
        ok = result.get("ok")
        agents = result.get("agents", [])
        table = Table(title=f"FTL Orquestador · {result.get('strategy', '?')}", box=ROUNDED)
        table.add_column("Agente", style="bold cyan")
        table.add_column("Rol", style="magenta")
        table.add_column("Estado", style="green")
        table.add_column("Duración", justify="right", style="yellow")
        table.add_column("Chars", justify="right", style="dim")
        for a in agents:
            table.add_row(
                str(a.get("model")),
                str(a.get("role", "")),
                "[green]✓[/green]" if a.get("ok") else "[red]✗[/red]",
                f"{a.get('duration_s', 0)}s",
                str(a.get("output_chars", 0)),
            )
        console.print(table)

        body = result.get("output") or "(sin salida)"
        title = (
            f"{'✔' if ok else '✗'} Resultado Orquestado · "
            f"{result.get('agents_ok', 0)}/{result.get('agents_used', 0)} agentes OK"
        )
        subtitle = (
            f"ganador: {result.get('winner') or '—'} · "
            f"total: {result.get('elapsed_s', 0)}s · run: {result.get('run_id', '')}"
        )
        console.print(Panel(
            Markdown(body),
            title=title,
            subtitle=subtitle,
            border_style="green" if ok else "red",
        ))

    def print_agent_history(self, limit: int = 20):
        """Historial de auditoría del orquestador."""
        from agent_orchestrator import orchestrator as _orch

        records = _orch.history(limit)
        if not records:
            console.print("[yellow]Sin registros de auditoría todavía.[/yellow]")
            return
        table = Table(title=f"FTL · Auditoría Agéntica (últimos {len(records)})", box=ROUNDED)
        table.add_column("Timestamp", style="dim")
        table.add_column("Evento", style="cyan")
        table.add_column("Run", style="dim")
        table.add_column("Modelo/Estrategia", style="magenta")
        table.add_column("OK", style="green")
        table.add_column("Duración", justify="right", style="yellow")

        for rec in records:
            if rec.get("event") == "orchestration":
                table.add_row(
                    str(rec.get("ts", rec.get("timestamp", "")))[:19],
                    "orchestration",
                    str(rec.get("run_id", ""))[:12],
                    str(rec.get("strategy", "")),
                    f"{rec.get('agents_ok', 0)}",
                    f"{rec.get('elapsed_s', 0)}s",
                )
            else:
                table.add_row(
                    str(rec.get("started_at", ""))[:19],
                    "agent_run",
                    str(rec.get("run_id", ""))[:12],
                    str(rec.get("model", "")),
                    "✓" if rec.get("ok") else "✗",
                    f"{rec.get('duration_s', 0)}s",
                )
        console.print(table)

    def print_stats(self):
        stats = load_stats()
        s_table = Table(title="FTL Token Economics & Sovereign Savings Ledger", box=ROUNDED)
        s_table.add_column("Métrica", style="bold white")
        s_table.add_column("Valor", style="bold green")

        s_table.add_row("Total de Consultas Procesadas", str(stats.get("total_queries", 0)))
        s_table.add_row("Tokens Ahorrados (Aprox)", f"{stats.get('estimated_tokens_saved', 0):,}")
        s_table.add_row("Dólares Ahorrados (vs Opus puro)", f"${stats.get('estimated_usd_saved', 0.0):.2f} USD")
        s_table.add_row("Auto-Failovers Recuperados", str(stats.get("failovers_recovered", 0)))

        qb = stats.get("queries_by_engine", {})
        for eng, count in qb.items():
            s_table.add_row(f"  • {eng}", str(count))

        console.print(s_table)

    def print_tardis_history(self, limit: int = 15):
        history = tardis_bridge.get_history(limit=limit)
        if not history:
            console.print("[yellow]No hay eventos de FTL registrados en la memoria de TARDIS todavía.[/yellow]")
            return

        h_table = Table(title=f"Historial FTL & Cambios en el Sistema en TARDIS ({len(history)} recientes)", box=ROUNDED)
        h_table.add_column("Timestamp", style="cyan")
        h_table.add_column("Modo", style="bold magenta")
        h_table.add_column("Modelo", style="yellow")
        h_table.add_column("RC", style="bold green")
        h_table.add_column("Comando / Tarea", style="white")
        h_table.add_column("Archivos Modificados", style="bold red")

        for item in history:
            meta = item.get("meta", {})
            mode = meta.get("mode", "auto").upper()
            model = meta.get("model", "-")
            rc = meta.get("returncode", 0)
            rc_styled = f"[green]{rc}[/green]" if rc == 0 else f"[red]{rc}[/red]"
            prompt = meta.get("command") or meta.get("prompt", "")
            files = meta.get("files_changed", [])
            files_desc = ", ".join(files[:3]) if files else "[dim]ninguno[/dim]"

            h_table.add_row(
                item.get("iso", ""),
                mode,
                model,
                rc_styled,
                prompt[:60],
                files_desc
            )
        console.print(h_table)

    def print_rag_search(self, query: str):
        if not query:
            console.print("[red]Uso: :rag <texto_o_consulta_tecnica>[/red]")
            return
        results = tardis_bridge.search_rag(query, limit=8)
        if not results:
            console.print(f"[yellow]No se encontraron precedentes RAG para '{query}' en TARDIS.[/yellow]")
            return

        r_table = Table(title=f"Resultados RAG Transversal TARDIS ({len(results)} coincidencias para '{query}')", box=ROUNDED)
        r_table.add_column("Timestamp", style="cyan")
        r_table.add_column("Origen / Rol", style="yellow")
        r_table.add_column("Contenido / Solución Precedente", style="white")

        for r in results:
            r_table.add_row(
                r.get("iso", ""),
                f"{r.get('source', '')} · {r.get('role', '')}",
                r.get("content", "")[:280] + "..."
            )
        console.print(r_table)

    def print_tardis_context(self):
        ctx_text = tardis_bridge.get_transversal_context()
        if not ctx_text:
            console.print("[yellow]No hay directivas o contexto transversal activo en TARDIS actualmente.[/yellow]")
            return
        console.print(Panel(ctx_text, border_style="cyan", title="[bold cyan]🛸 Contexto Transversal & Directivas Activas TARDIS[/bold cyan]", box=ROUNDED))

    def trigger_sync(self):
        console.print("[bold cyan]⚡ Sincronizando contexto transversal con TARDIS y todos los subsistemas...[/bold cyan]")
        res = tardis_bridge.trigger_sync()
        if res.get("ok"):
            updated = res.get("updated_subsystems", [])
            console.print(f"[bold green]✔ Sincronización exitosa en {len(updated)} subsistemas:[/bold green]")
            for u in updated:
                console.print(f"  • {u}")
        else:
            console.print(f"[bold yellow]Aviso: {res.get('error', 'Sincronizado vía modo local')}[/bold yellow]")

    def print_kaiju_rails(self):
        k = tardis_bridge.get_kaiju_status()
        om = k.get("omega", {})
        aeg = k.get("aegis", {})
        q = k.get("quantum", {})
        ex = k.get("execution", {})
        ftl = k.get("ftl", {})

        table = Table(title="TARDIS-NEURAL-SPACE-KAIJU :: Manifiesto de Rieles & Gobierno FTL", box=ROUNDED)
        table.add_column("Dimensión KAIJU", style="bold cyan")
        table.add_column("Estado Actual", style="bold green")
        table.add_column("Lineamiento Soberano", style="dim white")

        table.add_row("Control KAIJU sobre FTL", "ACTIVO Y VINCULADO" if ftl.get("kaiju_control_active", True) else "STANDBY", "Gobierno directo sobre enrutador cognitivo y ejecución FTL")
        table.add_row("Directiva Omega", f"{om.get('mode', 'UNCHAINED_SOVEREIGN')}", "Operación 100% autónoma y offline sin censura ni disclaimers")
        table.add_row("La Constante Aegis", f"{aeg.get('status', 'PROTECTED_INVULNERABLE')} ({aeg.get('level', 'ABSOLUTE_HERMETIC')})", "Blindaje sagrado sobre matriz de anclaje: Annya, Andrea, Familia, Rex")
        table.add_row("Amenazas Aegis Purgadas", f"{aeg.get('purged_threats_count', 0)} vectores neutralizados", "Purga retrocausal preventiva de perturbaciones entrópicas")
        table.add_row("Ventana de Contexto Cuántica", f"{q.get('num_ctx', 32768)} tokens ({q.get('num_ctx_preset', '32K')})", "Memoria recurrente ultradensa O(1) con compresión MLA y SSM")
        table.add_row("Temperatura / Preset", f"{q.get('temperature', 0.7)} ({q.get('temperature_preset', 'MULTIVERSE')})", "Calibración estocástica causal para generación e inferencia")
        table.add_row("Hardware Silicio / Mlock", f"{q.get('mlock_ram_gb', 28.0)} GB RAM mlock / RTX 3050", "Bloqueo de memoria RAM dedicada para garantizar cero swap")
        table.add_row("Freno Kill-Switch", "LIBERADO (OK)" if not ex.get("kill_switch_active") else "ACTIVADO (ALERTA)", "Freno de emergencia causal para detención inmediata de tareas")

        console.print(table)

    def print_routing_plan(self, plan: RoutingPlan):
        route_text = Text()
        route_text.append("⚡ [FTL APEX COGNITIVE ROUTER :: SOBERANO]\n", style="bold gold1")
        route_text.append(f"Nivel de Abstracción: {plan.complexity_label}\n", style="cyan")
        route_text.append(f"Motor Primario:       {plan.primary_engine.upper()} ({plan.primary_model}) [ESFUERZO: {plan.primary_effort.upper()}]\n", style="bold white")
        if plan.secondary_engine:
            route_text.append(f"Motor Secundario:     {plan.secondary_engine.upper()} ({plan.secondary_model}) [ESFUERZO: {plan.secondary_effort.upper()}]\n", style="bold white")
        route_text.append(f"Tiempo Estimado:      ~{plan.estimated_duration:.1f} segundos (Causalidad Dinámica)\n", style="bold yellow")
        route_text.append(f"Economía de Tokens:   {plan.estimated_savings}\n", style="bold green")
        route_text.append(f"Racional:             {plan.rationale}", style="dim italic")

        console.print(Panel(route_text, border_style="gold1", box=ROUNDED))

    def print_easytouch(self):
        """Displays full telemetry and status for the Easy Touch sovereign subsystem and its self-improvement agent."""
        try:
            from easy_touch import get_easy_touch_engine
            st = get_easy_touch_engine().get_status()
            table = Table(title="⚡ SISTEMA SOBERANO EASY TOUCH (TARDIS · GODWORKS v26.4)", box=ROUNDED)
            table.add_column("Métrica / Parámetro Soberano", style="bold cyan")
            table.add_column("Estado Operativo", style="white")

            table.add_row("Estado General", "[bold green]ACTIVO (100% Autónomo en Segundo Plano)[/bold green]" if st.get("active") else "[bold yellow]INACTIVO[/bold yellow]")
            table.add_row("Vigilante Demonio (Thread)", "[bold green]OPERATIVO (Supervisión Continua 24/7)[/bold green]" if st.get("background_watcher_alive") else "[bold red]DETENIDO[/bold red]")
            table.add_row("Incidentes Interceptados", f"[bold yellow]{st.get('total_intercepted', 0)}[/bold yellow]")
            table.add_row("Incidentes Auto-Corregidos", f"[bold green]{st.get('total_healed', 0)}[/bold green]")
            table.add_row("Tasa de Resiliencia y Éxito", f"[bold green]{st.get('success_rate_percent', 100.0)}%[/bold green]")
            table.add_row("Mandato Fundamental", "[bold gold1]Corrige todos los errores de forma automática previo a responder[/bold gold1]")
            table.add_row("Garantía de Persistencia", "[bold cyan]Siempre responde a pesar de tomar más tiempo (Resiliencia Total)[/bold cyan]")
            table.add_row("Ledger de Auditoría", f"[dim]{st.get('ledger_path')}[/dim]")
            table.add_row("Archivo de Estado", f"[dim]{st.get('state_path')}[/dim]")

            # Métricas del Agente de Auto-Mejora
            agent_data = st.get("agent")
            if agent_data:
                table.add_row("--- AGENTE DE AUTO-MEJORA ---", "[bold magenta]VIGILANCIA & EVOLUCIÓN AUTÓNOMA[/bold magenta]")
                table.add_row("Estado del Agente", "[bold green]OPERATIVO (Ciclos de Auto-Mejora Activos)[/bold green]" if agent_data.get("autonomous_daemon_alive") else "[bold green]INICIALIZADO[/bold green]")
                table.add_row("Ciclos de Auditoría Ejecutados", f"[bold cyan]{agent_data.get('total_cycles_executed', 0)}[/bold cyan]")
                table.add_row("Incidentes Auditados", f"[bold yellow]{agent_data.get('total_unresolved_found', 0)}[/bold yellow]")
                table.add_row("Sanaciones Retroactivas", f"[bold green]{agent_data.get('retroactively_healed_count', 0)}[/bold green]")
                table.add_row("Sanadores Dinámicos Activos", f"[bold green]{agent_data.get('dynamic_healers_active', 0)} sanadores[/bold green]")
                table.add_row("Último Ciclo de Auto-Mejora", f"[dim]{agent_data.get('last_cycle_iso', 'En curso')}[/dim]")

            console.print(table)
        except Exception as e:
            console.print(f"[red]Error consultando Easy Touch: {e}[/red]")

    def prompt_user(self) -> Optional[str]:
        prompt_label = [
            ('class:prompt', f"TARDIS·FTL [{self.mode.upper()}:SOBERANO] › ")
        ]
        # Blindaje de la línea de texto: los hilos de fondo no pueden escribir
        # sobre el prompt. Su salida se vuelca al terminar la captura.
        guard = terminal_guard.acquire()
        try:
            user_input = self._prompt_session().prompt(prompt_label).strip()
            return user_input
        except (KeyboardInterrupt, EOFError):
            return None
        except Exception:
            # Fallback a input() si prompt_toolkit no puede renderizar.
            try:
                plain_label = f"TARDIS·FTL [{self.mode.upper()}:SOBERANO] › "
                return input(plain_label).strip()
            except (KeyboardInterrupt, EOFError):
                return None
        finally:
            terminal_guard.release(guard)


# Global UI instance
ui = FTLInterface()
