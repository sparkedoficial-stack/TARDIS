"""
FTL & TARDIS Temporal Progress Bar and Time Estimation System
============================================================
Provides real-time dynamic visual progress bars with high-precision time estimation
for every user petition processed by the sovereign system.
"""

from __future__ import annotations

import json
import math
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rich.box import DOUBLE, ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.text import Text

VAULT_DB_PATH = Path.home() / "vw-control" / "deep_memory_vault" / "vault_master.db"
STATS_FILE = Path.home() / ".config" / "ftl" / "stats.json"


class TimeEstimator:
    """
    Cognitive & Temporal Duration Estimator.
    Combines algorithmic complexity grading, engine latency profiles,
    prompt token volume, and TARDIS historical execution memory.
    """

    # Baseline durations (in seconds) for Level 1 through Level 5 by engine/model tier
    ENGINE_BASELINES: Dict[str, Dict[int, float]] = {
        "gemini_flash": {1: 14.0, 2: 24.0, 3: 45.0, 4: 75.0, 5: 110.0},
        "gemini_pro":   {1: 22.0, 2: 38.0, 3: 65.0, 4: 110.0, 5: 160.0},
        "claude_sonnet":{1: 26.0, 2: 46.0, 3: 78.0, 4: 130.0, 5: 190.0},
        "claude_opus":  {1: 45.0, 2: 80.0, 3: 145.0, 4: 225.0, 5: 320.0},
        "dual_synth":   {1: 35.0, 2: 60.0, 3: 105.0, 4: 180.0, 5: 280.0},
        "dual_audit":   {1: 32.0, 2: 55.0, 3: 98.0, 4: 165.0, 5: 250.0},
        "direct_shell": {1: 1.5, 2: 2.5, 3: 4.0, 4: 6.0, 5: 10.0},
    }

    def _get_engine_key(self, mode: str, model: str) -> str:
        if mode == "shell" or "bash" in model:
            return "direct_shell"
        if mode == "dual_synth":
            return "dual_synth"
        if mode == "dual_audit":
            return "dual_audit"
        if mode == "claude" or "claude" in model or "sonnet" in model or "opus" in model:
            return "claude_opus" if "opus" in model.lower() else "claude_sonnet"
        if "pro" in model.lower():
            return "gemini_pro"
        return "gemini_flash"

    def get_historical_average(self, engine_key: str, complexity: int) -> Optional[float]:
        """Queries TARDIS vault_master.db for recent durations matching the engine and complexity."""
        if not VAULT_DB_PATH.exists():
            return None
        try:
            con = sqlite3.connect(str(VAULT_DB_PATH), timeout=2.0)
            rows = con.execute(
                """SELECT meta FROM vault_events
                   WHERE source LIKE 'ftl%'
                   ORDER BY id DESC LIMIT 30"""
            ).fetchall()
            con.close()

            baseline = self.ENGINE_BASELINES.get(engine_key, {}).get(complexity, 25.0)
            durations = []
            for r in rows:
                if not r[0]:
                    continue
                try:
                    m = json.loads(r[0])
                    dur = float(m.get("duration", 0))
                    c_level = int(m.get("meta", {}).get("complexity", 0) or m.get("complexity", 0))
                    m_mode = m.get("mode", "")
                    m_model = m.get("model", "")
                    ek = self._get_engine_key(m_mode, m_model)
                    if ek == engine_key and dur > 0.5:
                        # Only include historical runs that are plausibly within range of this complexity tier
                        if 0.35 * baseline <= dur <= 3.0 * baseline:
                            durations.append(dur)
                except Exception:
                    continue

            if durations:
                durations.sort()
                trimmed = durations[1:-1] if len(durations) >= 4 else durations
                return sum(trimmed) / len(trimmed)
        except Exception:
            pass
        return None

    def estimate(
        self,
        prompt: str,
        complexity: int = 2,
        mode: str = "gemini",
        model: str = "gemini-3.8-flash-high",
        context_scope: str = "compact"
    ) -> float:
        """
        Calculates high-accuracy estimated duration in seconds.
        """
        engine_key = self._get_engine_key(mode, model)
        baseline_table = self.ENGINE_BASELINES.get(engine_key, self.ENGINE_BASELINES["gemini_flash"])
        complexity_clamped = max(1, min(5, complexity))
        base_seconds = baseline_table.get(complexity_clamped, 25.0)

        # 1. Prompt volume adjustment
        words = len(prompt.split())
        if words > 25:
            # Add ~0.08s per word above 25, capped at +30s
            word_penalty = min(30.0, (words - 25) * 0.08)
            base_seconds += word_penalty

        # 2. Context scope adjustment
        if context_scope == "massive":
            base_seconds += 20.0
        elif context_scope == "medium":
            base_seconds += 6.0

        # 3. Code patterns (e.g. asking to refactor large projects, multi-tool hints)
        prompt_lower = prompt.lower()
        if any(w in prompt_lower for w in ["todo", "todos", "todos los", "completo", "ingenieria inversa", "revisa todo"]):
            base_seconds *= 1.35
        if any(w in prompt_lower for w in ["crea", "genera", "escribe", "desarrolla"]) and len(prompt) > 80:
            base_seconds *= 1.15

        # 4. Synthesize with historical TARDIS memory
        hist_avg = self.get_historical_average(engine_key, complexity_clamped)
        if hist_avg is not None and hist_avg > 2.0:
            # 50% baseline algorithm + 50% actual historical observations
            final_estimate = (base_seconds * 0.5) + (hist_avg * 0.5)
        else:
            final_estimate = base_seconds

        # Guarantee reasonable minimums
        min_sec = 1.0 if engine_key == "direct_shell" else 6.0
        return max(min_sec, round(final_estimate, 1))


time_estimator = TimeEstimator()


class TemporalProgressBar:
    """
    Sovereign Animated Progress Bar for FTL & TARDIS.
    Provides live elapsed/remaining countdowns, real-time tool tracking,
    asymptotic progression, and complete post-execution precision auditing.
    """

    def __init__(
        self,
        prompt: str,
        estimated_duration: float,
        engine_label: str = "GEMINI",
        model_name: str = "gemini-3.8-flash-high",
        complexity_label: str = "Level 2: Standard Implementation",
        console: Optional[Console] = None
    ):
        self.prompt = prompt
        self.estimated_duration = max(1.0, estimated_duration)
        self.engine_label = engine_label
        self.model_name = model_name
        self.complexity_label = complexity_label
        self.console = console or Console()

        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.is_running: bool = False
        self.current_phase: str = "Ingesta de contexto y directivas TARDIS"
        self.current_action: str = "Iniciando motor..."

        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._ticker_thread: Optional[threading.Thread] = None
        self._progress: Optional[Progress] = None
        self._task_id: Optional[TaskID] = None

    def _determine_phase(self, pct: float) -> str:
        if pct < 15.0:
            return "🔍 [1/4] Ingesta RAG & Contexto Sintrópico TARDIS"
        elif pct < 50.0:
            return "🧠 [2/4] Razonamiento Cuántico de Barrera (Inferencia)"
        elif pct < 85.0:
            return "⚡ [3/4] Generación de Código, Mutación & Herramientas"
        elif pct < 99.0:
            return "🛡️ [4/4] Síntesis Sintrópica, Auto-Curación & Cierre"
        return "✔ [Finalizado] Petición Ejecutada Exitosamente"

    def _detect_action(self, line: str) -> Optional[str]:
        """Detects tool actions or status keywords from model output stream."""
        clean = line.strip()
        if not clean:
            return None

        # Check for tool invocations
        if "view_file" in clean:
            return "📖 Inspeccionando archivo..."
        if "replace_file_content" in clean or "write_to_file" in clean:
            return "✍️ Aplicando mutaciones de código en disco..."
        if "run_command" in clean or "[HOST-SHELL]" in clean:
            return "⚡ Ejecutando comando de terminal..."
        if "search_web" in clean or "read_url_content" in clean:
            return "🌐 Explorando fuentes de conocimiento..."
        if "tardis" in clean.lower():
            return "🛸 Sincronizando con Núcleo TARDIS..."
        if "thought" in clean.lower() or "thinking" in clean.lower():
            return "🧠 Razonamiento interno de frontera en curso..."

        return None

    def print_header(self):
        """Displays the sovereign telemetry header before launching the live bar."""
        prompt_snippet = self.prompt.strip()
        if len(prompt_snippet) > 85:
            prompt_snippet = prompt_snippet[:82] + "..."

        table_text = Text()
        table_text.append("🛸 TARDIS SOBERANO :: BARRA DE AVANCE TEMPORAL\n", style="bold gold1")
        table_text.append(f"• Petición:    ", style="cyan")
        table_text.append(f"\"{prompt_snippet}\"\n", style="bold white")
        table_text.append(f"• Motor & Tier: ", style="cyan")
        table_text.append(f"{self.engine_label} ({self.model_name})  |  ", style="bold green")
        table_text.append(f"{self.complexity_label}\n", style="magenta")
        table_text.append(f"• Tiempo Estimado: ", style="bold yellow")
        table_text.append(f"{self.estimated_duration:.1f} segundos", style="bold yellow")
        table_text.append(f" (Cálculo adaptativo de causalidad temporal)", style="dim white")

        self.console.print(Panel(table_text, box=ROUNDED, border_style="gold1"))

    def start(self):
        """Starts the progress bar and background updater."""
        self.start_time = time.time()
        self.is_running = True
        self._stop_event.clear()
        self.print_header()

        self._progress = Progress(
            SpinnerColumn("dots", style="bold cyan"),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=32, style="dim cyan", complete_style="bold cyan", finished_style="bold green"),
            TextColumn("[bold yellow]{task.percentage:>5.1f}%[/bold yellow]"),
            TextColumn("⏱️ [green]{task.fields[elapsed_str]}[/green]"),
            TextColumn("⏳ [bold magenta]{task.fields[rem_str]}[/bold magenta]"),
            console=self.console,
            transient=False
        )
        self._progress.start()
        self._task_id = self._progress.add_task(
            self._determine_phase(0.0),
            total=100.0,
            completed=0.0,
            elapsed_str="0.0s",
            rem_str=f"Restante: {self.estimated_duration:.1f}s"
        )

        def _ticker():
            while not self._stop_event.is_set():
                now = time.time()
                elapsed = now - self.start_time
                rem = max(0.0, self.estimated_duration - elapsed)

                # Asymptotic progress curve
                if elapsed < self.estimated_duration:
                    pct = (elapsed / self.estimated_duration) * 94.0
                else:
                    over = elapsed - self.estimated_duration
                    pct = 94.0 + 5.5 * (1.0 - math.exp(-over / 20.0))
                    # Soft asymptotic remaining time when exceeding estimate
                    rem = max(0.5, 4.0 * math.exp(-over / 15.0))

                phase_desc = self._determine_phase(pct)
                if self.current_action and pct < 98.0:
                    phase_desc = f"{phase_desc} [dim]({self.current_action})[/dim]"

                if self._progress and self._task_id is not None:
                    self._progress.update(
                        self._task_id,
                        completed=min(99.5, pct),
                        description=phase_desc,
                        elapsed_str=f"{elapsed:.1f}s",
                        rem_str=f"Restante: ~{rem:.1f}s"
                    )

                time.sleep(0.08)

        self._ticker_thread = threading.Thread(target=_ticker, daemon=True)
        self._ticker_thread.start()

    def feed_line(self, line: str):
        """Feeds a streaming line of output from the running subprocess."""
        if not self.is_running:
            return

        act = self._detect_action(line)
        if act:
            self.current_action = act

        # Print line cleanly above progress bar
        clean_line = line.rstrip()
        if clean_line and self._progress:
            # Filter out internal verbose delimiter blocks if desired, or stream cleanly
            self._progress.console.print(clean_line)

    def finish(self, returncode: int = 0, summary_msg: str = "") -> float:
        """Stops the progress bar, marks 100%, and outputs precision telemetry."""
        self._stop_event.set()
        if self._ticker_thread and self._ticker_thread.is_alive():
            self._ticker_thread.join(timeout=0.5)

        self.end_time = time.time()
        self.is_running = False
        actual_duration = self.end_time - self.start_time

        if self._progress and self._task_id is not None:
            status_text = "✔ [Finalizado] Petición Ejecutada Exitosamente" if returncode == 0 else "❌ [Error en Ejecución]"
            self._progress.update(
                self._task_id,
                completed=100.0,
                description=status_text,
                elapsed_str=f"{actual_duration:.1f}s",
                rem_str="0.0s"
            )
            self._progress.stop()

        # Calculate time prediction accuracy
        if self.estimated_duration > 0 and actual_duration > 0:
            diff = abs(actual_duration - self.estimated_duration)
            precision = max(0.0, 100.0 - (diff / max(self.estimated_duration, actual_duration) * 100.0))
        else:
            precision = 100.0

        p_color = "green" if precision >= 80 else ("yellow" if precision >= 60 else "cyan")
        stat_color = "bold green" if returncode == 0 else "bold red"

        banner = Text()
        banner.append(f"{'✔' if returncode == 0 else '❌'} ", style=stat_color)
        banner.append(f"Turno Completado en ", style="bold white")
        banner.append(f"{actual_duration:.2f}s", style=stat_color)
        banner.append(f"  |  Estimado Inicial: ", style="dim white")
        banner.append(f"{self.estimated_duration:.1f}s", style="bold yellow")
        banner.append(f"  |  Precisión Temporal: ", style="dim white")
        banner.append(f"{precision:.1f}%\n", style=f"bold {p_color}")
        if summary_msg:
            banner.append(f"• {summary_msg}", style="dim")

        self.console.print(Panel(banner, box=ROUNDED, border_style="green" if returncode == 0 else "red"))
        return actual_duration


def run_command_with_progress(
    cmd: List[str],
    prompt: str,
    estimated_duration: float,
    engine_label: str = "GEMINI",
    model_name: str = "gemini-3.8-flash-high",
    complexity_label: str = "Level 2: Standard Implementation",
    prefix: str = "",
    on_line: Optional[Callable[[str], None]] = None,
    console: Optional[Console] = None
) -> Tuple[int, str, float]:
    """
    Executes a subprocess command wrapped inside a live TemporalProgressBar.
    Streams output in real time, keeps the progress bar active, and returns (rc, output, actual_duration).
    """
    bar = TemporalProgressBar(
        prompt=prompt,
        estimated_duration=estimated_duration,
        engine_label=engine_label,
        model_name=model_name,
        complexity_label=complexity_label,
        console=console
    )
    bar.start()

    full_output: List[str] = []
    returncode = 1
    actual_duration = 0.0

    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["FORCE_COLOR"] = "1"
        env["CLAUDE_CODE_SKIP_PERMISSIONS"] = "1"

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )

        for raw_line in process.stdout:
            full_output.append(raw_line)
            bar.feed_line(raw_line)
            if on_line:
                on_line(raw_line)

        process.wait()
        returncode = process.returncode
    except Exception as e:
        err = f"Error durante la ejecución del proceso: {str(e)}\n"
        full_output.append(err)
        bar.feed_line(err)
        returncode = 1
    finally:
        actual_duration = bar.finish(returncode=returncode)

    return returncode, "".join(full_output), actual_duration
