"""
self_improve.py - Motor de auto-mejora del sistema GIA.
========================================================

Corre de forma indefinida (daemon). En cada ciclo:
  1. Agrega senales: audit log del agente, gia.log, error_chat.json,
     y estadisticas del propio codebase.
  2. Le pide al modelo local que redacte una PETICION DE MEJORA concreta
     y accionable (que archivo tocar, que problema resuelve, como probarlo).
  3. Escribe la peticion como .md en la carpeta-cola:
       %LOCALAPPDATA%\\vw-control\\improvement_queue\\
  4. Duerme y repite.

Las peticiones NO se auto-aplican al codigo. Se aplican canalizandolas a
una sesion de Claude Code (manual, o programada con /schedule) que lee la
cola. El sistema "pide sus mejoras solo"; el paso de aplicar pasa por una
sesion de Claude Code real (que es donde se revisa y ejecuta).

Uso:
    python self_improve.py                 # ciclo cada 30 min, indefinido
    python self_improve.py --interval 600  # cada 10 min
    python self_improve.py --once          # un solo ciclo y salir
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime
from pathlib import Path

import httpx

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
QUEUE_DIR = CONFIG_DIR / "improvement_queue"
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

PROJECT_DIR = Path(__file__).resolve().parent
OLLAMA = os.environ.get("OLLAMA_HOST", "http://REDACTED_IP:11434")
try:
    import gia_sovereign_engine as _gse
    DEFAULT_MODEL = _gse.get_engine().resolve_model()
except Exception:
    DEFAULT_MODEL = os.environ.get("GIA_MODEL", "hf.co/bartowski/Llama-3.2-3B-Instruct-uncensored-GGUF:Q4_K_M")
DEFAULT_INTERVAL = 1800     # 30 min

AUDIT_LOG = CONFIG_DIR / "agent_audit.log"
GIA_LOG = CONFIG_DIR / "gia.log"
ERROR_CHAT = CONFIG_DIR / "error_chat.json"

C_AI = "\033[96m"; C_DIM = "\033[90m"; C_OK = "\033[92m"; C_ERR = "\033[91m"; C_END = "\033[0m"


# =====================================================================
#  RECOLECCION DE SENALES
# =====================================================================

def _tail(path: Path, n: int) -> str:
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


def slugify(title: str) -> str:
    """Slug canonico de un titulo de peticion (mismo criterio en toda la cola)."""
    s = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    return s.strip().replace(" ", "_").lower()[:40] or "mejora"


def _slug_of(path: Path) -> str:
    """Extrae el slug de improvement_<fecha>_<hora>_<slug>.md"""
    parts = path.stem.split("_", 3)
    return parts[3] if len(parts) > 3 else path.stem


def title_of(content: str) -> str:
    """Primera linea de encabezado markdown del contenido."""
    for line in content.splitlines():
        if line.strip().startswith("#"):
            return line.strip("# ").strip()[:50]
    return "mejora"


def gather_signals() -> dict:
    sig = {}
    sig["audit_tail"] = _tail(AUDIT_LOG, 60)
    sig["gia_log_tail"] = _tail(GIA_LOG, 40)

    # Contar bloqueos y errores en el audit
    blocks = errors = 0
    for line in sig["audit_tail"].splitlines():
        if "BLOCK" in line:
            blocks += 1
    sig["recent_blocks"] = blocks

    # Error chat
    if ERROR_CHAT.is_file():
        try:
            data = json.loads(ERROR_CHAT.read_text(encoding="utf-8"))
            errs = data.get("errors", data if isinstance(data, list) else [])
            sig["error_count"] = len(errs)
            sig["recent_errors"] = [
                (e.get("message", "") if isinstance(e, dict) else str(e))[:160]
                for e in errs[-8:]]
        except Exception:
            sig["error_count"] = 0
            sig["recent_errors"] = []
    else:
        sig["error_count"] = 0
        sig["recent_errors"] = []

    # Inventario del codebase (tamanos = candidatos a refactor)
    files = []
    try:
        for p in PROJECT_DIR.glob("*.py"):
            try:
                loc = sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))
                files.append((p.name, loc))
            except Exception:
                continue
        files.sort(key=lambda x: -x[1])
    except Exception:
        pass
    sig["codebase"] = files[:12]

    # Peticiones ya en la cola (para no repetir). Se le dan al modelo TODOS
    # los temas distintos, no solo los ultimos: con la ventana de 6 se
    # regeneraba el mismo tema una y otra vez.
    existing = sorted(QUEUE_DIR.glob("improvement_*.md"))
    sig["queue_size"] = len(existing)
    sig["existing_slugs"] = sorted({_slug_of(p) for p in existing})
    sig["recent_queue_titles"] = [p.stem for p in existing[-6:]]
    return sig


# =====================================================================
#  GENERACION DE LA PETICION DE MEJORA
# =====================================================================

SYS = """Eres el modulo de auto-mejora de un sistema Python local llamado GIA
(orquestador de Vectorworks + agente autonomo de control de PC). Tu trabajo
es analizar las senales de operacion y redactar UNA peticion de mejora
CONCRETA y accionable para que un ingeniero (o Claude Code) la implemente.

Responde SOLO con la peticion en formato markdown, con estas secciones:
  # Titulo corto
  ## Problema  (que senal lo evidencia)
  ## Propuesta (que archivo/funcion tocar y como)
  ## Como probarlo (comando o verificacion concreta)
  ## Prioridad (alta/media/baja)

Reglas:
- Se especifico: nombra archivos reales del codebase que te doy.
- Propon algo IMPLEMENTABLE en < 1 hora, no reescrituras masivas.
- Si no ves un problema claro, propon una mejora incremental util
  (tests, manejo de errores, logging, rendimiento, UX del agente).
- NO repitas una mejora que ya este en la cola (te doy los titulos).
- Espanol, conciso."""


def build_prompt(sig: dict) -> str:
    codebase = "\n".join(f"  - {n}: {loc} LOC" for n, loc in sig.get("codebase", []))
    errs = "\n".join(f"  - {e}" for e in sig.get("recent_errors", [])) or "  (ninguno)"
    queue = "\n".join(f"  - {t}" for t in sig.get("existing_slugs", [])) or "  (vacia)"
    return f"""SENALES DE OPERACION ({datetime.now().isoformat(timespec='seconds')}):

Bloqueos de seguridad recientes: {sig.get('recent_blocks', 0)}
Errores registrados: {sig.get('error_count', 0)}
Errores recientes:
{errs}

Codebase (archivos y tamano):
{codebase}

AUDIT LOG (cola):
{sig.get('audit_tail', '')[:1500]}

GIA LOG (cola):
{sig.get('gia_log_tail', '')[:800]}

Temas YA presentes en la cola ({sig.get('queue_size', 0)} peticiones).
PROHIBIDO proponer de nuevo cualquiera de estos temas:
{queue}

Redacta la siguiente peticion de mejora, sobre un tema DISTINTO a los de arriba.
Antes de escribir, verifica que tu titulo no coincide con ninguno de la lista.
Solo nombra funciones y archivos que aparezcan literalmente en el codebase que
te di; si no estas seguro de que una funcion exista, no la menciones."""


def generate_request(model: str, sig: dict, timeout: float = 300.0) -> str | None:
    try:
        r = httpx.post(f"{OLLAMA}/api/chat", json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYS},
                {"role": "user", "content": build_prompt(sig)},
            ],
            "stream": False,
            "options": {"num_ctx": 8192, "temperature": 0.5},
            "keep_alive": "30m",
        }, timeout=timeout)
        r.raise_for_status()
        content = (r.json().get("message", {}).get("content") or "").strip()
        return content or None
    except Exception as e:
        print(f"{C_ERR}[error generando] {e}{C_END}")
        return None


def write_request(content: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify(title_of(content))
    path = QUEUE_DIR / f"improvement_{ts}_{slug}.md"
    header = (f"<!-- Generado por self_improve.py el {datetime.now().isoformat()} -->\n"
              f"<!-- Para aplicar: abre una sesion de Claude Code en "
              f"{PROJECT_DIR} y pide que implemente esta peticion. -->\n\n")
    path.write_text(header + content, encoding="utf-8")
    return path


# =====================================================================
#  LOOP
# =====================================================================

def refine_context() -> None:
    """Auto-mejora del contexto agentico (solo si el usuario lo activo).

    Es INDEPENDIENTE de si este ciclo escribio o no una peticion: corre
    siempre. Aplica directamente porque es reversible (versionado en
    agent_context) y porque check_proposal() rechaza toda propuesta que
    erosione la identidad.

    NO se le pasa el `model` del ciclo: ese es un modelo *coder*, que degrada
    la persona. agent_context elige su propio modelo GENERAL por defecto.
    """
    try:
        import agent_context as _ctx
        if not _ctx.get().get("auto_improve"):
            print(f"{C_DIM}  · auto-mejora de contexto desactivada{C_END}")
            return
        r = _ctx.auto_improve(apply=True)
        if r.get("ok") and r.get("applied"):
            print(f"{C_OK}  + contexto agentico refinado: "
                  f"{r.get('cambios','')[:60]}{C_END}")
        elif r.get("rejected"):
            print(f"{C_ERR}  ! contexto NO modificado (guardia) — "
                  f"{r.get('error','')}{C_END}")
        else:
            # Ninguna rama debe quedar muda: un fallo de red/modelo aqui
            # pasaba desapercibido y parecia que el ciclo no hacia nada.
            print(f"{C_ERR}  ! auto-mejora de contexto fallo — "
                  f"{r.get('error','sin detalle')}{C_END}")
    except Exception as e:  # noqa: BLE001
        print(f"{C_ERR}  ! auto-mejora de contexto no ejecutada: "
              f"{type(e).__name__}: {e}{C_END}")


def one_cycle(model: str) -> Path | None:
    print(f"{C_DIM}[{datetime.now().strftime('%H:%M:%S')}] recolectando senales...{C_END}")
    sig = gather_signals()
    print(f"{C_DIM}  errores={sig['error_count']} bloqueos={sig['recent_blocks']} "
          f"cola={sig['queue_size']}{C_END}")
    print(f"{C_DIM}  generando peticion de mejora con {model}...{C_END}")
    content = generate_request(model, sig)

    path = None
    if not content:
        print(f"{C_ERR}  sin peticion generada este ciclo{C_END}")
    else:
        # Guardia de duplicados: el modelo local reincide en el mismo tema pese
        # a la instruccion. Si el slug ya esta en la cola, no se escribe copia.
        slug = slugify(title_of(content))
        if slug in set(sig.get("existing_slugs", [])):
            print(f"{C_ERR}  ~ duplicado descartado: {slug}{C_END}")
        else:
            path = write_request(content)
            first_line = content.splitlines()[0].strip("# ")
            print(f"{C_OK}  + {path.name}{C_END}")
            print(f"{C_DIM}    {first_line[:70]}{C_END}")

    refine_context()
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Motor de auto-mejora GIA")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                    help="segundos entre ciclos (default 1800)")
    ap.add_argument("--once", action="store_true", help="un ciclo y salir")
    args = ap.parse_args()

    print(f"\n{C_AI}================================================={C_END}")
    print(f"{C_AI}  GIA - MOTOR DE AUTO-MEJORA{C_END}")
    print(f"{C_AI}  Modelo: {args.model}{C_END}")
    print(f"{C_AI}  Cola: {QUEUE_DIR}{C_END}")
    print(f"{C_DIM}  Genera peticiones de mejora; se aplican via Claude Code.{C_END}")
    if not args.once:
        print(f"{C_DIM}  Ciclo cada {args.interval}s. Ctrl+C para detener.{C_END}")
    print(f"{C_AI}================================================={C_END}\n")

    try:
        httpx.Client().get(f"{OLLAMA}/api/tags", timeout=5.0)
    except Exception:
        print(f"{C_ERR}Ollama no responde. Arranca 'ollama serve'.{C_END}")
        return 1

    if args.once:
        one_cycle(args.model)
        return 0

    cycle = 0
    try:
        while True:
            cycle += 1
            print(f"{C_DIM}--- ciclo {cycle} ---{C_END}")
            one_cycle(args.model)
            print(f"{C_DIM}  durmiendo {args.interval}s...{C_END}\n")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"\n{C_DIM}Detenido. {cycle} ciclos. Cola en {QUEUE_DIR}{C_END}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
