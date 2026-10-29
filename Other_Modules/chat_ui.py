#!/usr/bin/env python3
"""
GODWORKS · FTL Quantum Chat
===========================
Interfaz de chat persistente de FTL sobre el motor de OpenCode.

Características:
  • Permanencia real: sesiones FTL en ~/.config/ftl/chat/sessions/*.json
    y continuidad nativa de OpenCode mediante --session.
  • Animaciones del sistema: núcleo cuásar TON 618, anillo de acreción,
    onda de telemetría, radar de herramientas y pulso de estado.
  • Mismas funciones que OpenCode: modelo, agente, sesiones, adjuntos,
    thinking, auto-aprobación, herramientas y flujo JSON estructurado.
  • Comandos slash: /new /sessions /resume /model /models /agent /file
    /thinking /auto /skills /orchestrate /export /status /help /quit.

Uso:
  ftl chat                     # reanuda la última sesión o crea una nueva
  ftl chat --new               # fuerza sesión nueva
  ftl chat --resume <id>       # reanuda una sesión concreta
  ftl chat --list              # lista sesiones persistentes
  ftl chat -p "Hola"           # modo one-shot (scripting / pruebas)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from rich.align import Align
from rich.box import DOUBLE, HEAVY, ROUNDED
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Resolver PATH soberano ANTES de cualquier import que lance subprocesos:
# los servicios systemd (Telegram, portal web) no heredan ~/.opencode/bin.
import runtime_env  # noqa: F401  (amplía os.environ["PATH"] al importar)
import terminal_guard

import chat_store as store
from chat_engine import (
    ChatConfig,
    ChatRunner,
    is_free_limit,
    is_missing_session,
    is_transient_error,
    model_pool,
    next_free_model,
    resolve_model,
    short_model,
)
import free_models as fm

CYAN = "#00ffcc"
GOLD = "#ffb86c"
PURPLE = "#bd93f9"
BLUE = "#7aa2f7"
GREEN = "#50fa7b"
RED = "#ff5555"
DIM = "#6272a4"

SPIN_FRAMES = [
    "◉·········",
    "·◉········",
    "··◉·······",
    "···◉······",
    "····◉·····",
    "·····◉····",
    "······◉···",
    "·······◉··",
    "········◉·",
    "·········◉",
    "········◉·",
    "·······◉··",
    "······◉···",
    "·····◉····",
    "····◉·····",
    "···◉······",
    "··◉·······",
    "·◉········",
]

WAVE_FRAMES = [
    "▁▂▃▄▅▆▇█▇▆▅▄▃▂▁",
    "▂▃▄▅▆▇█▇▆▅▄▃▂▁▂",
    "▃▄▅▆▇█▇▆▅▄▃▂▁▂▃",
    "▄▅▆▇█▇▆▅▄▃▂▁▂▃▄",
    "▅▆▇█▇▆▅▄▃▂▁▂▃▄▅",
    "▆▇█▇▆▅▄▃▂▁▂▃▄▅▆",
    "▇█▇▆▅▄▃▂▁▂▃▄▅▆▇",
    "█▇▆▅▄▃▂▁▂▃▄▅▆▇█",
]

COMMANDS = [
    "/help", "/new", "/sessions", "/resume", "/rename", "/delete",
    "/model", "/models", "/agent", "/agents", "/file", "/files",
    "/thinking", "/auto", "/skills", "/orchestrate", "/export",
    "/status", "/history", "/clear", "/quit", "/exit",
]


# ---------------------------------------------------------------------------
# Animación de estado
# ---------------------------------------------------------------------------
class QuasarStatus:
    def __init__(self, model: str, session_id: str, console: Optional[Console] = None):
        self.model = model
        self.session_id = session_id
        self.console = console
        self.start = time.time()
        self.frame = 0
        self.stage = "Sincronizando núcleo cuásar"
        self.tokens_in = 0
        self.tokens_out = 0
        self.tools = 0
        self.last_tool = ""

    def tick(self) -> None:
        self.frame += 1

    def consume(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "step_start":
            self.stage = "Analizando intención"
        elif kind == "thinking":
            self.stage = "Razonando en el horizonte de sucesos"
        elif kind == "tool":
            self.tools += 1
            tool = event.get("tool", "tool")
            inp = event.get("input") or {}
            command = inp.get("command") if isinstance(inp, dict) else None
            self.last_tool = f"{tool}: {command}" if command else tool
            self.stage = f"Ejecutando herramienta · {tool}"
        elif kind == "step_finish":
            tokens = event.get("tokens") or {}
            self.tokens_in += int(tokens.get("input") or 0)
            self.tokens_out += int(tokens.get("output") or 0)
            self.stage = "Integrando resultado"
        elif kind == "text":
            self.stage = "Redactando respuesta"
        elif kind == "error":
            self.stage = "Anomalía detectada"

    def render(self) -> Panel:
        elapsed = time.time() - self.start
        spin = SPIN_FRAMES[self.frame % len(SPIN_FRAMES)]
        wave = WAVE_FRAMES[(self.frame // 2) % len(WAVE_FRAMES)]
        try:
            width = self.console.size.width
        except Exception:
            width = 80
        stage = self.stage
        max_stage = max(18, width - 26)
        if len(stage) > max_stage:
            stage = stage[: max_stage - 1] + "…"

        text = Text(no_wrap=True, overflow="ellipsis")
        text.append(spin, style=f"bold {CYAN}")
        text.append("  ")
        text.append(stage, style=f"bold {PURPLE}")
        text.append(f"  {elapsed:05.1f}s", style=f"bold {GOLD}")
        if self.tokens_in or self.tokens_out:
            text.append(f"  ↑{self.tokens_in} ↓{self.tokens_out}", style=f"dim {GREEN}")
        text.append("\n")
        text.append(wave, style=f"dim {CYAN}")
        text.append("  ")
        text.append(short_model(self.model), style=f"dim {BLUE}")
        if self.last_tool:
            tool = self.last_tool
            max_tool = max(10, width - len(short_model(self.model)) - 24)
            if len(tool) > max_tool:
                tool = tool[: max_tool - 1] + "…"
            text.append(f"  ⚙ {tool}", style=f"dim {GOLD}")
        return Panel(text, border_style=CYAN, box=ROUNDED, padding=(0, 1))


# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------
class ChatTUI:
    def __init__(self, session: dict, animated: Optional[bool] = None):
        self.console = Console()
        self.session = session
        self.animated = (
            sys.stdout.isatty()
            if animated is None
            else animated
        ) and os.environ.get("FTL_CHAT_NO_ANIM", "").lower() not in ("1", "true", "yes")
        self.files: list[str] = []
        self.prompt_session = None
        self._runner: Optional[ChatRunner] = None

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def print_header(self) -> None:
        s = self.session
        logo = Text(justify="center")
        logo.append("◉  TON 618 · QUASAR CORE\n", style=f"bold {GOLD}")
        logo.append("FTL QUANTUM CHAT\n", style=f"bold {CYAN}")
        logo.append("interfaz persistente · motor OpenCode · soberanía FTL", style=f"dim {PURPLE}")
        self.console.print()
        self.console.print(
            Panel(
                Align.center(logo),
                border_style=CYAN,
                box=ROUNDED,
                padding=(0, 2),
                subtitle=f"[dim {DIM}]⚡ núcleo de acreción activo[/]",
            )
        )
        self.console.print(
            f"[dim {DIM}]sesión[/] [bold {CYAN}]{s['id']}[/] "
            f"[dim {DIM}]· modelo[/] [bold {BLUE}]{short_model(s.get('model', ''))}[/] "
            f"[dim {DIM}]· opencode[/] [dim]{s.get('opencode_session_id') or 'pendiente'}[/]"
        )
        self.console.print()

    def print_status(self) -> None:
        s = self.session
        st = s.get("stats", {})
        table = Table(box=ROUNDED, show_header=False, expand=False, padding=(0, 1))
        table.add_column("k", style=f"bold {CYAN}")
        table.add_column("v", style="white")
        table.add_row("Título", s.get("title") or "Nueva conversación")
        table.add_row("Sesión FTL", s.get("id", ""))
        table.add_row("Sesión OpenCode", s.get("opencode_session_id") or "— (se crea al primer mensaje)")
        table.add_row("Modelo", s.get("model", ""))
        table.add_row("Agente", s.get("agent") or "—")
        table.add_row("Directorio", s.get("cwd", ""))
        table.add_row("Turnos", str(st.get("turns", 0)))
        table.add_row("Tokens", f"↑ {st.get('tokens_in', 0)}  ↓ {st.get('tokens_out', 0)}")
        table.add_row("Coste", f"${st.get('cost', 0.0)}")
        table.add_row("Herramientas", str(st.get("tool_calls", 0)))
        table.add_row("Thinking", "ON" if s.get("settings", {}).get("thinking") else "OFF")
        table.add_row("Auto-aprobación", "ON" if s.get("settings", {}).get("auto", True) else "OFF")
        self.console.print(table)

    def render_user(self, text: str) -> Panel:
        return Panel(
            Text(text or "", style="white"),
            title="🧑 ARQUITECTO",
            title_align="right",
            border_style=BLUE,
            box=ROUNDED,
            padding=(0, 1),
        )

    def render_assistant(self, text: str) -> Panel:
        return Panel(
            Markdown(text or "*(sin texto final)*"),
            title="◉ FTL · RESPUESTA",
            border_style=CYAN,
            box=ROUNDED,
            padding=(0, 1),
        )

    def render_tool(self, tool: dict) -> Panel:
        name = tool.get("tool", "tool")
        status = tool.get("status", "")
        inp = tool.get("input") or {}
        out = str(tool.get("output") or "")
        body = Text()
        if isinstance(inp, dict) and "command" in inp:
            body.append("$ ", style=f"bold {GREEN}")
            body.append(str(inp["command"]), style=f"bold {GOLD}")
            body.append("\n")
        elif isinstance(inp, dict) and (inp.get("path") or inp.get("filePath")):
            body.append("path: ", style=f"bold {GREEN}")
            body.append(str(inp.get("path") or inp.get("filePath")), style=f"bold {GOLD}")
            body.append("\n")
        elif inp:
            body.append(json.dumps(inp, indent=2, ensure_ascii=False)[:1200], style=f"dim {BLUE}")
            body.append("\n")
        if out:
            body.append(out[:2200], style="white")
            if len(out) > 2200:
                body.append(f"\n… [{len(out) - 2200} caracteres truncados]", style=f"dim {DIM}")
        if not body.plain:
            body.append("(sin salida)", style=f"dim {DIM}")
        border = GREEN if status in ("completed", "success", "ok") else GOLD
        return Panel(
            body,
            title=f"⚙ {name} · {status or 'tool'}",
            border_style=border,
            box=ROUNDED,
            padding=(0, 1),
        )

    def render_thinking(self, text: str, max_chars: int = 1800) -> Panel:
        body = Text()
        body.append(text[:max_chars], style=f"dim {PURPLE}")
        if len(text) > max_chars:
            body.append(
                f"\n… [{len(text) - max_chars} caracteres de razonamiento omitidos]",
                style=f"dim {DIM}",
            )
        return Panel(
            body,
            title="🧠 RAZONAMIENTO · horizonte de sucesos",
            border_style=PURPLE,
            box=ROUNDED,
            padding=(0, 1),
        )

    def print_history(self, limit: int = 12, show_all: bool = False) -> None:
        messages = self.session.get("messages", [])
        if not messages:
            self.console.print(
                f"[dim {DIM}]Sesión nueva. Escribe tu primer mensaje o usa[/] "
                f"[bold {CYAN}]/help[/] [dim {DIM}]para ver los comandos.[/]"
            )
            self.console.print()
            return
        if not show_all and len(messages) > limit:
            hidden = len(messages) - limit
            self.console.print(
                f"[dim {DIM}]… {hidden} mensajes anteriores ocultos · "
                f"usa /history all para verlos.[/]"
            )
            messages = messages[-limit:]
        for msg in messages:
            role = msg.get("role")
            if role == "user":
                self.console.print(self.render_user(msg.get("content", "")))
            elif role == "assistant":
                for tool in msg.get("tools", []):
                    self.console.print(self.render_tool(tool))
                    self.console.print()
                think = (msg.get("meta") or {}).get("thinking")
                if think:
                    self.console.print(self.render_thinking(think))
                    self.console.print()
                if msg.get("content"):
                    self.console.print(self.render_assistant(msg.get("content", "")))
            elif role == "system":
                self.console.print(
                    Panel(
                        Text(msg.get("content", ""), style=f"dim {GOLD}"),
                        border_style=GOLD,
                        box=ROUNDED,
                        title="SISTEMA",
                    )
                )
            self.console.print()

    # ------------------------------------------------------------------
    # Motor
    # ------------------------------------------------------------------
    def _config(self) -> ChatConfig:
        return ChatConfig(
            model=self.session.get("model") or "opencode/deepseek-v4.1-flash-free#max",
            agent=self.session.get("agent") or "",
            thinking=bool(self.session.get("settings", {}).get("thinking")),
            auto=bool(self.session.get("settings", {}).get("auto", True)),
            cwd=self.session.get("cwd") or os.getcwd(),
            files=list(self.files),
            title=self.session.get("title", "") if not self.session.get("opencode_session_id") else "",
        )

    def send(self, text: str) -> bool:
        text = (text or "").strip()
        if not text:
            return True

        store.add_message(self.session, "user", text)
        self.console.print(self.render_user(text))
        self.console.print()

        attempted: set[str] = set()
        attempts = 0
        # Recorre todo el pool gratuito antes de rendirse con un modelo.
        max_attempts = max(2, min(len(model_pool()), 8))
        outcome_ok = False
        while attempts < max_attempts:
            attempts += 1
            current = self.session.get("model", "")
            attempted.add(current)
            outcome_ok = self._send_once(text, retry=attempts > 1)
            if outcome_ok:
                break
            last_error = self._last_error or {}
            if is_transient_error(last_error) and attempts < max_attempts:
                next_model = next_free_model(current, attempted)
                if next_model:
                    old = short_model(current)
                    self.session["model"] = next_model.ref
                    attempted.add(next_model.key)
                    attempted.add(next_model.ref)
                    store.save_session(self.session)
                    self.console.print(
                        Panel(
                            Text(
                                f"{'Límite gratuito agotado' if is_free_limit(last_error) else 'Fallo del modelo'} "
                                f"en {old}. Conmutando a {next_model.name} ({next_model.ref})…",
                                style=f"bold {GOLD}",
                            ),
                            border_style=GOLD,
                            box=ROUNDED,
                            title="RESILIENCIA FTL · POOL GRATUITO",
                        )
                    )
                    continue
            if is_missing_session(last_error) and self.session.get("opencode_session_id"):
                self.console.print(
                    Panel(
                        Text(
                            "La sesión de OpenCode ya no existe. Se creará una nueva "
                            "sesión manteniendo el historial FTL.",
                            style=f"bold {GOLD}",
                        ),
                        border_style=GOLD,
                        box=ROUNDED,
                        title="CONTINUIDAD",
                    )
                )
                self.session["opencode_session_id"] = None
                store.save_session(self.session)
                continue
            break
        self.files.clear()
        return outcome_ok

    def _next_free_model(self):
        return next_free_model(self.session.get("model", ""))

    def _send_once(self, text: str, retry: bool = False) -> bool:
        cfg = self._config()
        runner = ChatRunner(
            text,
            cfg,
            opencode_session_id=self.session.get("opencode_session_id"),
        )
        self._runner = runner
        status = QuasarStatus(cfg.model, self.session.get("id", ""), self.console)
        collected: list[dict] = []
        assistant_parts: list[str] = []
        thinking_parts: list[str] = []
        tools: list[dict] = []
        tokens_in = tokens_out = 0
        cost = 0.0
        rc: Optional[int] = None
        session_id = self.session.get("opencode_session_id")
        self._last_error = None

        try:
            if self.animated:
                with Live(
                    status.render(),
                    console=self.console,
                    refresh_per_second=12,
                    transient=True,
                ) as live:
                    for event in runner.run():
                        if event.get("kind") == "tick":
                            status.tick()
                            live.update(status.render())
                            continue
                        status.consume(event)
                        live.update(status.render())
                        self._collect(
                            event, collected, assistant_parts, tools, thinking_parts
                        )
                        if event.get("kind") == "step_finish":
                            tokens = event.get("tokens") or {}
                            tokens_in += int(tokens.get("input") or 0)
                            tokens_out += int(tokens.get("output") or 0)
                            cost += float(event.get("cost") or 0.0)
                        elif event.get("kind") == "process_end":
                            rc = event.get("rc")
                            session_id = event.get("session_id") or session_id
                        elif event.get("kind") == "error":
                            self._last_error = event
            else:
                for event in runner.run():
                    if event.get("kind") == "tick":
                        continue
                    status.consume(event)
                    self._collect(event, collected, assistant_parts, tools, thinking_parts)
                    if event.get("kind") == "step_finish":
                        tokens = event.get("tokens") or {}
                        tokens_in += int(tokens.get("input") or 0)
                        tokens_out += int(tokens.get("output") or 0)
                        cost += float(event.get("cost") or 0.0)
                    elif event.get("kind") == "process_end":
                        rc = event.get("rc")
                        session_id = event.get("session_id") or session_id
                    elif event.get("kind") == "error":
                        self._last_error = event
        except KeyboardInterrupt:
            runner.cancel()
            self.console.print(
                Panel(
                    Text("Ejecución cancelada por el Arquitecto.", style=f"bold {GOLD}"),
                    border_style=GOLD,
                    box=ROUNDED,
                    title="INTERRUPCIÓN",
                )
            )
            store.add_message(self.session, "system", "Turno cancelado por el usuario.")
            return False
        finally:
            self._runner = None

        # Persistir la sesión OpenCode real
        if session_id and session_id != self.session.get("opencode_session_id"):
            self.session["opencode_session_id"] = session_id
            store.save_session(self.session)

        error = self._last_error
        if error:
            self.console.print(
                Panel(
                    Text(
                        f"{error.get('message', 'Error desconocido')}"
                        + (
                            f"\n\nReintenta en ~{round((error.get('retry_after_ms') or 0) / 60000, 1)} min "
                            f"o cambia de modelo con /model."
                            if error.get("retry_after_ms") else ""
                        ),
                        style=f"bold {RED}",
                    ),
                    border_style=RED,
                    box=ROUNDED,
                    title="ANOMALÍA DEL NÚCLEO",
                )
            )
            store.add_message(
                self.session, "system",
                f"Error: {error.get('message', 'desconocido')}",
            )
            return False

        # Renderizar razonamiento, herramientas y respuesta final
        thinking_text = "\n\n".join(p for p in thinking_parts if p.strip()).strip()
        for tool in tools:
            self.console.print(self.render_tool(tool))
            self.console.print()
        if thinking_text:
            self.console.print(self.render_thinking(thinking_text))
            self.console.print()
        answer = "\n\n".join(part for part in assistant_parts if part.strip()).strip()
        if answer:
            self.console.print(self.render_assistant(answer))
        elif tools:
            answer = "*(El agente ejecutó herramientas sin emitir texto final.)*"
            self.console.print(self.render_assistant(answer))
        else:
            answer = ""
            self.console.print(
                Panel(
                    Text("OpenCode no devolvió texto ni herramientas.", style=f"dim {DIM}"),
                    border_style=GOLD,
                    box=ROUNDED,
                )
            )
        self.console.print()

        store.add_message(
            self.session,
            "assistant",
            answer,
            tools=tools,
            meta={
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost": cost,
                "rc": rc,
                "retry": retry,
                "thinking": thinking_text[:20000],
            },
        )
        if answer or tools:
            store.record_turn(
                self.session,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=cost,
                tool_calls=len(tools),
            )
        try:
            self.console.show_cursor(True)
            self.console.file.flush()
        except Exception:
            pass
        return rc == 0 or bool(answer) or bool(tools)

    @staticmethod
    def _collect(
        event: dict,
        collected: list[dict],
        assistant_parts: list[str],
        tools: list[dict],
        thinking_parts: Optional[list[str]] = None,
    ) -> None:
        collected.append(event)
        kind = event.get("kind")
        if kind == "text":
            text = event.get("text") or ""
            if text:
                assistant_parts.append(text)
        elif kind == "tool":
            tool = {
                "tool": event.get("tool", "tool"),
                "status": event.get("status", ""),
                "input": event.get("input") or {},
                "output": (event.get("output") or "")[:4000],
                "title": event.get("title") or event.get("tool") or "tool",
            }
            tools.append(tool)
        elif kind == "thinking" and event.get("text"):
            if thinking_parts is not None:
                thinking_parts.append(event["text"])

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------
    def handle_command(self, line: str) -> str:
        parts = line.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/salir"):
            return "quit"

        if cmd in ("/help", "/ayuda"):
            self.print_help()
            return "ok"

        if cmd in ("/status", "/sesion", "/session"):
            self.print_status()
            return "ok"

        if cmd in ("/history", "/historial"):
            self.print_history(limit=12, show_all=(arg.lower() in ("all", "todo", "completo")))
            return "ok"

        if cmd == "/clear":
            self.console.clear()
            self.print_header()
            return "ok"

        if cmd == "/new":
            self.session = store.new_session(
                model=self.session.get("model") or self._default_model(),
                agent=self.session.get("agent") or "",
                cwd=self.session.get("cwd") or os.getcwd(),
                title=arg or "Nueva conversación",
                thinking=bool(self.session.get("settings", {}).get("thinking")),
                auto=bool(self.session.get("settings", {}).get("auto", True)),
            )
            self.files.clear()
            self.console.print(
                Panel(
                    Text(f"Nueva sesión creada: {self.session['id']}", style=f"bold {GREEN}"),
                    border_style=GREEN,
                    box=ROUNDED,
                )
            )
            self.print_header()
            return "ok"

        if cmd in ("/sessions", "/sesiones"):
            self.print_sessions()
            return "ok"

        if cmd == "/resume":
            self.resume(arg)
            return "ok"

        if cmd == "/rename":
            if not arg:
                self.console.print(f"[{RED}]Uso: /rename <nuevo título>[/]")
            else:
                self.session["title"] = arg
                store.save_session(self.session)
                self.console.print(f"[{GREEN}]✔ Título actualizado.[/]")
            return "ok"

        if cmd == "/delete":
            old = self.session["id"]
            store.delete_session(old)
            self.session = store.new_session(
                model=self.session.get("model") or self._default_model(),
                agent=self.session.get("agent") or "",
                cwd=self.session.get("cwd") or os.getcwd(),
                thinking=bool(self.session.get("settings", {}).get("thinking")),
                auto=bool(self.session.get("settings", {}).get("auto", True)),
            )
            self.console.print(f"[{GOLD}]Sesión {old} eliminada. Nueva sesión: {self.session['id']}[/]")
            self.print_header()
            return "ok"

        if cmd == "/model":
            self.change_model(arg)
            return "ok"

        if cmd == "/models":
            self.print_models()
            return "ok"

        if cmd == "/agent":
            if not arg:
                self.console.print(
                    f"Agente actual: [bold {CYAN}]{self.session.get('agent') or '—'}[/]\n"
                    f"[dim]Uso: /agent build | /agent plan | /agent off[/]"
                )
            elif arg.lower() in ("off", "none", "ninguno"):
                self.session["agent"] = ""
                store.save_session(self.session)
                self.console.print(f"[{GREEN}]✔ Agente desactivado.[/]")
            else:
                self.session["agent"] = arg
                store.save_session(self.session)
                self.console.print(f"[{GREEN}]✔ Agente: {arg}[/]")
            return "ok"

        if cmd == "/agents":
            self.print_agents()
            return "ok"

        if cmd == "/file":
            self.add_file(arg)
            return "ok"

        if cmd == "/files":
            if arg.lower() in ("clear", "limpiar"):
                self.files.clear()
            if self.files:
                self.console.print(f"[bold {CYAN}]Adjuntos pendientes:[/]")
                for path in self.files:
                    self.console.print(f"  • {path}")
            else:
                self.console.print(f"[dim {DIM}]Sin adjuntos pendientes.[/]")
            return "ok"

        if cmd == "/thinking":
            self.toggle_setting("thinking", arg)
            return "ok"

        if cmd == "/auto":
            self.toggle_setting("auto", arg)
            return "ok"

        if cmd in ("/skills", "/habilidades"):
            self.print_skills()
            return "ok"

        if cmd in ("/orchestrate", "/orquestar"):
            self.run_orchestration(arg)
            return "ok"

        if cmd == "/export":
            self.export(arg)
            return "ok"

        self.console.print(f"[{RED}]Comando desconocido: {cmd}[/] · usa /help")
        return "ok"

    # ------------------------------------------------------------------
    def print_help(self) -> None:
        table = Table(title="FTL Quantum Chat · Comandos", box=ROUNDED)
        table.add_column("Comando", style=f"bold {CYAN}")
        table.add_column("Función", style="white")
        rows = [
            ("/help", "Esta ayuda"),
            ("/new [título]", "Nueva sesión persistente"),
            ("/sessions", "Lista sesiones guardadas"),
            ("/resume <id|n>", "Reanuda una sesión"),
            ("/rename <título>", "Renombra la sesión actual"),
            ("/delete", "Elimina la sesión actual y crea otra"),
            ("/model [alias]", "Consulta o cambia el modelo"),
            ("/models", "Catálogo de modelos gratuitos"),
            ("/agent [nombre|off]", "Agente OpenCode"),
            ("/agents", "Pool de agentes FTL"),
            ("/file <ruta>", "Adjunta un archivo al próximo mensaje"),
            ("/files [clear]", "Lista o limpia adjuntos"),
            ("/thinking [on|off]", "Razonamiento visible"),
            ("/auto [on|off]", "Auto-aprobación de herramientas"),
            ("/skills", "Skills soberanas disponibles"),
            ("/orchestrate [estrategia] <tarea>", "Orquestación multi-agente FTL"),
            ("/export [md|json] [ruta]", "Exporta la conversación"),
            ("/status", "Métricas de la sesión"),
            ("/history [all]", "Reimprime el historial"),
            ("/clear", "Limpia la pantalla"),
            ("/quit", "Sale conservando la sesión"),
        ]
        for cmd, desc in rows:
            table.add_row(cmd, desc)
        self.console.print(table)
        self.console.print(
            f"[dim {DIM}]Escribe texto normal para conversar. "
            f"Las sesiones se guardan en ~/.config/ftl/chat/sessions/[/]"
        )

    def print_sessions(self) -> None:
        sessions = store.list_sessions()
        if not sessions:
            self.console.print(f"[dim {DIM}]No hay sesiones guardadas.[/]")
            return
        self.console.print(build_sessions_table(sessions, self.session.get("id", ""), self.console.width))
        self.console.print(
            f"[dim {DIM}]Usa /resume <id|n> para cargar una sesión.[/]"
        )

    def resume(self, arg: str) -> None:
        sessions = store.list_sessions()
        if not sessions:
            self.console.print(f"[dim {DIM}]No hay sesiones guardadas.[/]")
            return
        target = None
        if not arg:
            target = sessions[0]
        elif arg.isdigit() and 1 <= int(arg) <= len(sessions):
            target = sessions[int(arg) - 1]
        else:
            for s in sessions:
                if s.get("id") == arg or s.get("id", "").endswith(arg):
                    target = s
                    break
        if not target:
            self.console.print(f"[{RED}]Sesión no encontrada: {arg}[/]")
            return
        loaded = store.load_session(target["id"])
        if not loaded:
            self.console.print(f"[{RED}]No se pudo cargar la sesión.[/]")
            return
        self.session = loaded
        self.console.clear()
        self.print_header()
        self.print_history(limit=8)
        self.console.print(f"[{GREEN}]✔ Sesión reanudada.[/]")

    def change_model(self, arg: str) -> None:
        if not arg:
            self.console.print(
                f"Modelo actual: [bold {CYAN}]{self.session.get('model')}[/]"
            )
            self.print_models()
            return
        try:
            ref = resolve_model(arg)
        except ValueError as exc:
            self.console.print(f"[{RED}]✖ {exc}[/]")
            return
        self.session["model"] = ref
        store.save_session(self.session)
        self.console.print(
            f"[{GREEN}]✔ Modelo cambiado a:[/] [bold {CYAN}]{ref}[/]"
        )
        self.console.print(
            f"[dim {DIM}]La continuidad de OpenCode se conserva; "
            f"el próximo turno usará el nuevo modelo.[/]"
        )

    def print_models(self) -> None:
        summary = fm.summary()
        table = Table(title="Modelos gratuitos disponibles", box=ROUNDED)
        table.add_column("Alias", style=f"bold {CYAN}")
        table.add_column("Referencia", style="white")
        table.add_column("Especialidad", style=f"dim {PURPLE}")
        table.add_column("Estado", style=GREEN)
        table.add_column("Latencia", justify="right", style=GOLD)
        current = self.session.get("model")
        for m in summary["models"]:
            marker = " ◀" if m["ref"] == current else ""
            state = "✓" if m["available"] is True else ("✗" if m["available"] is False else "…")
            if not m["enabled"]:
                state += " off"
            table.add_row(
                m["key"] + marker,
                m["ref"],
                ", ".join(m["roles"][:2]),
                state,
                f"{m['latency_s']}s" if m["latency_s"] else "—",
            )
        self.console.print(table)

    def print_agents(self) -> None:
        try:
            import agent_orchestrator as ao
            orch = ao.orchestrator
            policy = orch.policy
            runs = orch.state.get("by_model", {})
        except Exception:
            policy, runs = {}, {}
        table = Table(title="Agentes FTL · pool gratuito", box=ROUNDED)
        table.add_column("Alias", style=f"bold {CYAN}")
        table.add_column("Ref", style="white")
        table.add_column("Runs/OK", justify="right", style=GOLD)
        for m in fm.all_models():
            stats = runs.get(m.key, {})
            table.add_row(m.key, m.ref, f"{stats.get('runs', 0)}/{stats.get('ok', 0)}")
        self.console.print(table)
        if policy:
            self.console.print(
                f"[dim {DIM}]orquestador: {'ON' if policy.get('enabled') else 'OFF'} · "
                f"kill switch: {'ON' if policy.get('kill_switch') else 'off'} · "
                f"concurrencia: {policy.get('max_concurrency')} · "
                f"máx agentes: {policy.get('max_agents')}[/]"
            )

    def add_file(self, arg: str) -> None:
        if not arg:
            self.console.print(f"[{GOLD}]Uso: /file <ruta>[/]")
            return
        path = Path(arg).expanduser()
        if not path.is_file():
            self.console.print(f"[{RED}]Archivo no encontrado: {path}[/]")
            return
        resolved = str(path.resolve())
        if resolved not in self.files:
            self.files.append(resolved)
        self.console.print(f"[{GREEN}]✔ Adjunto:[/] {resolved}")

    def toggle_setting(self, key: str, arg: str) -> None:
        settings = self.session.setdefault("settings", {})
        current = bool(settings.get(key))
        if arg.lower() in ("on", "1", "true", "activar", "si", "sí"):
            value = True
        elif arg.lower() in ("off", "0", "false", "desactivar", "no"):
            value = False
        else:
            value = not current
        settings[key] = value
        store.save_session(self.session)
        self.console.print(f"[{GREEN}]✔ {key}: {'ON' if value else 'OFF'}[/]")

    def print_skills(self) -> None:
        roots = [Path.home() / ".agents" / "skills", Path.home() / ".ftl" / "skills"]
        found = {}
        for root in roots:
            if root.is_dir():
                for entry in sorted(root.iterdir()):
                    if entry.is_dir() and (entry / "SKILL.md").is_file():
                        found[entry.name] = entry
        table = Table(title="Skills soberanas disponibles", box=ROUNDED)
        table.add_column("Skill", style=f"bold {CYAN}")
        table.add_column("Ruta", style=f"dim {DIM}")
        for name, path in found.items():
            table.add_row(name, str(path))
        self.console.print(table)
        self.console.print(
            f"[dim {DIM}]{len(found)} skills · usa `sovereign-sync verify` para auditar destinos.[/]"
        )

    def run_orchestration(self, arg: str) -> None:
        try:
            from agent_orchestrator import orchestrator, OrchestratorHalt, STRATEGIES
        except Exception as exc:
            self.console.print(f"[{RED}]Orquestador no disponible: {exc}[/]")
            return
        parts = arg.split(maxsplit=1)
        strategy = "auto"
        task = arg
        if parts and parts[0].lower() in STRATEGIES:
            strategy = parts[0].lower()
            task = parts[1] if len(parts) > 1 else ""
        if not task.strip():
            self.console.print(
                f"[{GOLD}]Uso: /orchestrate [auto|single|fanout|compare|pipeline|race] <tarea>[/]"
            )
            return
        self.console.print(
            f"[bold {CYAN}]🕸️ FTL Orquestador · {strategy} · control soberano…[/]"
        )
        try:
            result = orchestrator.orchestrate(
                task,
                strategy=strategy,
                on_progress=lambda msg: self.console.print(f"[dim {DIM}]{msg}[/]"),
            )
        except (OrchestratorHalt, ValueError) as exc:
            self.console.print(f"[{RED}]✖ {exc}[/]")
            return
        output = result.get("output") or "(sin salida)"
        self.console.print(
            Panel(
                Markdown(output),
                title=f"◉ ORQUESTACIÓN · {strategy} · "
                      f"{result.get('agents_ok', 0)}/{result.get('agents_used', 0)} OK",
                border_style=CYAN,
                box=ROUNDED,
            )
        )
        store.add_message(
            self.session,
            "assistant",
            output,
            meta={"orchestration": True, "strategy": strategy,
                  "agents": result.get("agents", []), "elapsed_s": result.get("elapsed_s")},
        )

    def export(self, arg: str) -> None:
        parts = arg.split(maxsplit=1)
        fmt = parts[0].lower() if parts and parts[0].lower() in ("md", "markdown", "json") else "md"
        output = parts[1] if len(parts) > 1 else (parts[0] if parts and parts[0] not in ("md", "markdown", "json") else None)
        try:
            path = store.export_json(self.session, output) if fmt == "json" else store.export_markdown(self.session, output)
        except Exception as exc:
            self.console.print(f"[{RED}]Error exportando: {exc}[/]")
            return
        self.console.print(f"[{GREEN}]✔ Exportado:[/] {path}")

    # ------------------------------------------------------------------
    # Prompt e interacción
    # ------------------------------------------------------------------
    def _prompt(self):
        if self.prompt_session is None:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.completion import WordCompleter
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.styles import Style

            aliases = [m.key for m in fm.all_models()]
            completer = WordCompleter(COMMANDS + aliases, ignore_case=True, sentence=True)
            style = Style.from_dict({
                "prompt": "ansicyan bold",
                "bottom-toolbar": "bg:#12121f #00ffcc",
                "completion-menu.completion": "bg:#12121f #a8b8d8",
                "completion-menu.completion.current": "bg:#00ffcc #0a0e17 bold",
            })

            # Teclado determinista: Enter envía, Alt+Enter abre línea nueva.
            # Nada de autocompletado automático que pueda alterar el texto.
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
                # Limpia la línea en silencio: jamás aborta ni imprime encima.
                event.current_buffer.reset()
                event.app.invalidate()

            @keys.add("c-l")
            def _redraw(event):  # noqa: ANN001
                event.app.renderer.clear()
                event.app.invalidate()

            store.ensure_dirs()
            self.prompt_session = PromptSession(
                history=FileHistory(str(store.HISTORY_FILE)),
                completer=completer,
                style=style,
                # ── Anti-interferencia ──────────────────────────────────
                # reserve_space_for_menu=0 evita que el menú de completado
                # robe filas y desplace el prompt en pantallas pequeñas.
                reserve_space_for_menu=0,
                complete_while_typing=False,   # completar sólo con Tab
                complete_in_thread=False,      # sin hilos escribiendo en la TTY
                enable_history_search=False,   # sin autosugerencias fantasma
                mouse_support=False,
                multiline=True,                # Alt+Enter = salto de línea
                key_bindings=keys,
                prompt_continuation="  … ",
            )
        return self.prompt_session

    def _toolbar(self) -> Optional[str]:
        """Barra inferior sólo si hay altura suficiente; nunca roba la línea de texto."""
        try:
            if self.console.size.height < 16 or self.console.size.width < 60:
                return None
        except Exception:
            return None
        return (
            f"sesión {self.session.get('id')} · "
            f"{len(self.session.get('messages', []))} mensajes · "
            f"Enter envía · Alt+Enter línea nueva · /help"
        )

    def _read_line(self) -> str:
        """
        Captura de texto blindada.

        Mientras el Arquitecto escribe, cualquier `print()` de un hilo de fondo
        (vigilantes, telemetría, auto-curación, voz) queda retenido y se vuelca
        después de enviar el prompt. Así el texto escrito nunca se corrompe.
        """
        guard = terminal_guard.acquire()
        try:
            line = self._prompt().prompt(
                [("class:prompt", f"◉ {short_model(self.session.get('model', ''))} › ")],
                bottom_toolbar=self._toolbar(),
            )
        finally:
            terminal_guard.release(guard)
        return line or ""

    def loop(self) -> int:
        self.print_header()
        self.print_history()
        while True:
            try:
                line = self._read_line()
            except KeyboardInterrupt:
                # Sólo ocurre en terminales sin el binding c-c; sin ruido.
                continue
            except EOFError:
                break
            line = (line or "").strip()
            if not line:
                continue
            if line.startswith("/"):
                if self.handle_command(line) == "quit":
                    break
                continue
            self.send(line)
        self.console.print(
            f"[dim {DIM}]Sesión guardada: {self.session.get('id')} · "
            f"reanuda con `ftl chat --resume {self.session.get('id')}`[/]"
        )
        return 0

    @staticmethod
    def _default_model() -> str:
        try:
            from config import load_config
            cfg = load_config()
            return cfg.get("default_model") or cfg.get("fallback_model") or "opencode/deepseek-v4.1-flash-free#max"
        except Exception:
            return "opencode/deepseek-v4.1-flash-free#max"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_sessions_table(sessions: list[dict], current_id: str = "", width: int = 100) -> Table:
    """Tabla de sesiones adaptable: omite columnas cuando el terminal es estrecho."""
    compact = width < 104
    table = Table(title="Sesiones FTL Quantum Chat", box=ROUNDED, padding=(0, 1))
    table.add_column("#", justify="right", style=f"dim {DIM}")
    if not compact:
        table.add_column("ID", style=f"bold {CYAN}", no_wrap=True)
    table.add_column("Título", style="white", no_wrap=True, overflow="ellipsis",
                     max_width=28 if compact else 38)
    if not compact:
        table.add_column("Modelo", style=f"dim {BLUE}", no_wrap=True, overflow="ellipsis", max_width=12)
        table.add_column("Msj", justify="right", style=GOLD, min_width=3)
    table.add_column("Actualizada", style=f"dim {DIM}", no_wrap=True)
    for idx, sess in enumerate(sessions, 1):
        sid = sess.get("id", "")
        marker = " ◀" if sid == current_id else ""
        row = [str(idx)]
        if not compact:
            row.append(sid + marker)
        row.append((sess.get("title") or "Nueva conversación")[:52])
        if not compact:
            row.append(_model_key(sess.get("model", "")))
            row.append(str(sess.get("message_count", 0)))
        row.append((sess.get("updated_at") or "").replace("T", " ")[5:16])
        table.add_row(*row)
    return table


def _model_key(ref: str) -> str:
    """Etiqueta corta de modelo para tablas: base#variant sin proveedor."""
    ref = ref or ""
    try:
        hit = fm.resolve(ref)
        if hit:
            return hit.key
    except Exception:
        pass
    base, _, variant = ref.partition("#")
    base = base.split("/")[-1]
    for suffix in ("-flash-free", "-free"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return f"{base}#{variant}" if variant else base


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ftl chat", description="FTL Quantum Chat persistente sobre OpenCode")
    parser.add_argument("--new", action="store_true", help="Fuerza una sesión nueva")
    parser.add_argument("--resume", nargs="?", const="__latest__", metavar="ID",
                        help="Reanuda una sesión (sin ID = la última)")
    parser.add_argument("--session", dest="session_id", metavar="ID", help="ID exacto de sesión FTL")
    parser.add_argument("--model", "-m", metavar="ALIAS", help="Modelo para la sesión")
    parser.add_argument("--agent", metavar="NAME", help="Agente OpenCode")
    parser.add_argument("--file", "-f", action="append", default=[], metavar="PATH",
                        help="Adjunta un archivo al mensaje (repetible)")
    parser.add_argument("--thinking", action="store_true", help="Activa razonamiento visible")
    parser.add_argument("--no-thinking", action="store_true", help="Desactiva razonamiento visible")
    parser.add_argument("--no-auto", action="store_true", help="Desactiva auto-aprobación")
    parser.add_argument("--auto", action="store_true", help="Fuerza auto-aprobación de herramientas")
    parser.add_argument("--cwd", metavar="DIR", help="Directorio de trabajo de la sesión")
    parser.add_argument("--one-shot", "-p", dest="prompt", metavar="TEXT",
                        help="Envía un mensaje y sale (scripting/pruebas)")
    parser.add_argument("--list", "-l", action="store_true", help="Lista sesiones persistentes")
    parser.add_argument("--web", action="store_true", help="Abre la interfaz web (portal :8765/chat)")
    parser.add_argument("--delete", metavar="ID", help="Elimina una sesión")
    parser.add_argument("--export", metavar="ID", help="Exporta una sesión a Markdown")
    parser.add_argument("--output", "-o", metavar="PATH", help="Ruta de exportación")
    return parser


def _print_sessions_table(console: Console) -> None:
    sessions = store.list_sessions()
    if not sessions:
        console.print("[dim]No hay sesiones guardadas todavía.[/]")
        return
    console.print(build_sessions_table(sessions, width=console.width))


def _open_web(console: Console) -> int:
    """Abre la interfaz web FTL Quantum Chat (:8765/chat)."""
    import subprocess
    import urllib.request

    base = os.environ.get("FTL_WEB_URL", "http://127.0.0.1:8765").rstrip("/")
    url = f"{base}/chat"
    try:
        with urllib.request.urlopen(f"{base}/api/chat/bootstrap", timeout=3) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
    except Exception:
        console.print(
            f"[{GOLD}]El portal web no responde en {base}. "
            f"Arráncalo con: systemctl --user start ftl-web-portal[/]"
        )
        return 1
    console.print(f"[{GREEN}]✔ FTL Quantum Chat web:[/] [bold {CYAN}]{url}[/]")
    try:
        subprocess.Popen(
            ["xdg-open", url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        console.print(f"[dim {DIM}]Abre manualmente la URL en tu navegador.[/]")
    return 0


def run_chat(argv: Optional[list[str]] = None) -> int:
    opts = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    console = Console()
    store.ensure_dirs()

    if opts.list:
        _print_sessions_table(console)
        return 0

    if opts.web:
        return _open_web(console)

    if opts.delete:
        if store.delete_session(opts.delete):
            console.print(f"[{GREEN}]✔ Sesión eliminada: {opts.delete}[/]")
            return 0
        console.print(f"[{RED}]✖ Sesión no encontrada: {opts.delete}[/]")
        return 1

    if opts.export:
        session = store.load_session(opts.export)
        if not session:
            console.print(f"[{RED}]✖ Sesión no encontrada: {opts.export}[/]")
            return 1
        path = store.export_markdown(session, opts.output)
        console.print(f"[{GREEN}]✔ Exportado:[/] {path}")
        return 0

    session: Optional[dict] = None
    if opts.session_id:
        session = store.load_session(opts.session_id)
        if not session:
            console.print(f"[{RED}]✖ Sesión no encontrada: {opts.session_id}[/]")
            return 1
    elif opts.resume is not None:
        if opts.resume == "__latest__":
            session = store.latest_session()
            if not session:
                console.print(f"[{GOLD}]No hay sesiones previas; creando una nueva.[/]")
        else:
            session = store.load_session(opts.resume)
            if not session:
                console.print(f"[{RED}]✖ Sesión no encontrada: {opts.resume}[/]")
                return 1
    elif not opts.new:
        session = store.latest_session()

    default_model = opts.model or ChatTUI._default_model()
    if session is None:
        session = store.new_session(
            model=resolve_model(default_model),
            agent=opts.agent or "",
            cwd=opts.cwd or os.getcwd(),
            thinking=bool(opts.thinking and not opts.no_thinking),
            auto=not opts.no_auto,
        )
    else:
        if opts.model:
            session["model"] = resolve_model(opts.model)
        if opts.agent is not None:
            session["agent"] = opts.agent
        if opts.thinking:
            session.setdefault("settings", {})["thinking"] = True
        if opts.no_thinking:
            session.setdefault("settings", {})["thinking"] = False
        if opts.no_auto:
            session.setdefault("settings", {})["auto"] = False
        if opts.auto:
            session.setdefault("settings", {})["auto"] = True
        if opts.cwd:
            session["cwd"] = str(Path(opts.cwd).expanduser())
        store.save_session(session)

    tui = ChatTUI(session, animated=(opts.prompt is None))
    for raw_path in opts.file or []:
        p = Path(raw_path).expanduser().resolve()
        if p.is_file():
            tui.files.append(str(p))
        else:
            console.print(f"[{RED}]✖ Adjunto ignorado (no existe): {p}[/]")
    if opts.prompt:
        ok = tui.send(opts.prompt)
        console.print(
            f"[dim]Sesión: {tui.session.get('id')} · "
            f"OpenCode: {tui.session.get('opencode_session_id') or '—'}[/]"
        )
        return 0 if ok else 1
    return tui.loop()


if __name__ == "__main__":
    sys.exit(run_chat())
