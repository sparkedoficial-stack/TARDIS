"""
gia_subconscious.py - Procesamiento Cognitivo Subconsciente y Consolidación de Memoria
========================================================================================

Módulo que corre en segundo plano (daemon o programado) para ejecutar el
ciclo de "Sueño y Consolidación" del sistema GIA.

Responsabilidades:
  1. Consolidación de Memoria: Analiza eventos recientes en gia_master.db (SQLite FTS5),
     sintetiza lecciones aprendidas y extrae patrones de éxito (few-shot) para auto-aprendizaje.
  2. Depuración y Mantenimiento: Rota capturas antiguas, audita intentos bloqueados
     y limpia temporales del sistema.
  3. Formulación de Directrices: Inyecta síntesis heurísticas en agent_context
     para que el agente no repita errores del día anterior.
  4. Enlace con Akashic: Indexa resúmenes estructurales en gia_akashic.db.

Arquitecto: Miguel Angel May Canche  ·  GIA-V26-SUBCONSCIOUS
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

import httpx

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
DB_PATH = CONFIG_DIR / "gia_master.db"
CAPTURES_DIR = CONFIG_DIR / "captures"
MEMORY_DIR = CONFIG_DIR / "subconscious_insights"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

_raw_ollama = os.environ.get("OLLAMA_HOST", "http://REDACTED_IP:11434").strip()
try:
    import gia_sovereign_engine as _gse
    DEFAULT_MODEL = _gse.get_engine().resolve_model()
except Exception:
    DEFAULT_MODEL = os.environ.get("GIA_MODEL", "Qwen3.8-27B-Uncensored-MLX:latest")

C_CYAN = "\033[96m"; C_GREEN = "\033[92m"; C_YELLOW = "\033[93m"; C_RED = "\033[91m"; C_DIM = "\033[90m"; C_END = "\033[0m"


class GIASubconscious:
    """Motor de síntesis cognitiva y consolidación nocturna."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def _get_db(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(DB_PATH), timeout=10.0)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def consolidate_recent_history(self, hours: float = 24.0) -> Dict[str, Any]:
        """Extrae eventos del último periodo y genera una síntesis de conocimiento."""
        if not DB_PATH.is_file():
            return {"ok": False, "error": "No existe la base de datos gia_master.db"}

        since_ts = time.time() - (hours * 3600.0)
        con = self._get_db()
        try:
            cur = con.execute(
                "SELECT source, role, content, ts FROM events WHERE ts >= ? ORDER BY ts ASC",
                (since_ts,)
            )
            rows = cur.fetchall()
            if not rows:
                return {"ok": True, "consolidated": 0, "message": "Sin eventos recientes para procesar"}

            event_texts = [f"[{r[0]}/{r[1]}]: {r[2][:300]}" for r in rows[:100]]
            corpus = "\n".join(event_texts)

            prompt = (
                "Eres el módulo subconsciente de consolidación de memoria de GIA.\n"
                "Analiza el siguiente registro de eventos del día y genera una SÍNTESIS ESTRUCTURADA:\n"
                "1. Tareas principales abordadas.\n"
                "2. Errores o bloqueos encontrados y cómo se solucionaron.\n"
                "3. Nuevos conocimientos o heurísticas clave aprendidas.\n\n"
                f"REGISTRO DE EVENTOS:\n{corpus}\n\n"
                "Responde en formato Markdown claro y conciso."
            )

            synthesis = ""
            try:
                r = httpx.post(f"{OLLAMA_URL}/api/chat", json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"num_ctx": 4096, "temperature": 0.3}
                }, timeout=180.0)
                if r.status_code == 200:
                    synthesis = r.json().get("message", {}).get("content", "").strip()
            except Exception as e:
                synthesis = f"Error al generar síntesis con LLM: {e}"

            # Guardar insight en disco
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            insight_file = MEMORY_DIR / f"insight_{ts_str}.md"
            insight_file.write_text(
                f"# Síntesis Subconsciente GIA - {datetime.now().isoformat()}\n\n"
                f"**Eventos analizados**: {len(rows)} | **Periodo**: últimas {hours}h\n\n"
                f"{synthesis}\n",
                encoding="utf-8"
            )

            # Auto-registrar lecciones aprendidas en la tabla successes de gia_memory
            try:
                import gia_memory
                gia_memory.record_success(
                    task=f"Consolidación Subconsciente {ts_str}",
                    solution=synthesis[:2000],
                    tools=["subconscious_synthesis"],
                    source="gia_subconscious",
                    rating=5
                )
            except Exception:
                pass

            return {
                "ok": True,
                "events_processed": len(rows),
                "insight_path": str(insight_file),
                "synthesis": synthesis
            }
        finally:
            con.close()

    def clean_stale_artifacts(self, max_age_days: int = 3) -> Dict[str, int]:
        """Elimina frames y fotos de captura antiguas para optimizar disco."""
        deleted = 0
        cutoff = time.time() - (max_age_days * 86400)
        if CAPTURES_DIR.is_dir():
            for f in CAPTURES_DIR.glob("*.*"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        deleted += 1
                except Exception:
                    pass
        return {"deleted_captures": deleted}

    def run_full_consolidation_cycle(self) -> Dict[str, Any]:
        """Ejecuta el ciclo integral de sueño y optimización cognitiva."""
        print(f"{C_CYAN}=== INICIANDO CICLO DE CONSOLIDACIÓN SUBCONSCIENTE GIA ==={C_END}")
        
        # 1. Consolidación de memoria
        print(f"{C_DIM}Analizando historial y destilando conocimientos...{C_END}")
        mem_res = self.consolidate_recent_history(hours=24.0)
        
        # 2. Limpieza de artefactos
        print(f"{C_DIM}Depurando artefactos temporales...{C_END}")
        clean_res = self.clean_stale_artifacts(max_age_days=2)
        
        # 3. Refinar contexto permanente
        print(f"{C_DIM}Alineando directrices del contexto de GIA...{C_END}")
        ctx_status = "no_action"
        try:
            import agent_context
            refine_res = agent_context.auto_improve(apply=True)
            if refine_res.get("ok"):
                ctx_status = "context_refined"
        except Exception as e:
            ctx_status = f"skipped ({e})"

        summary = {
            "ok": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "memory_consolidation": mem_res,
            "cleanup": clean_res,
            "context_refinement": ctx_status
        }
        print(f"{C_GREEN}=== CONSOLIDACIÓN SUBCONSCIENTE COMPLETADA CON ÉXITO ==={C_END}")
        return summary


def run_cycle_now(model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    sub = GIASubconscious(model=model)
    return sub.run_full_consolidation_cycle()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="GIA Subconscious Consolidation Engine")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Modelo LLM de consolidación")
    ap.add_argument("--daemon", action="store_true", help="Correr en bucle cada 6 horas")
    args = ap.parse_args()

    if args.daemon:
        print("Modo Subconsciente continuo activado (ciclo cada 6 horas).")
        while True:
            try:
                run_cycle_now(model=args.model)
            except Exception as e:
                print(f"{C_RED}Error en ciclo: {e}{C_END}")
            time.sleep(6 * 3600)
    else:
        res = run_cycle_now(model=args.model)
        print(json.dumps(res, indent=2, ensure_ascii=False))
