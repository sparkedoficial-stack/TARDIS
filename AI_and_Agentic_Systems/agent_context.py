"""
agent_context.py - Contexto agentico persistente compartido por todo GIA.
=========================================================================

Un unico "texto de directrices" que TU defines una vez (desde la interfaz
web o editando el archivo) y que TODAS las variantes del sistema anteponen
automaticamente al system prompt del modelo, en cada interaccion, sin que
tengas que repetirlo.

Es el "carácter base" del sistema: como quieres que se comporte, tono,
reglas, prioridades, datos tuyos que siempre debe tener presentes.

Compartido por: gia_web_server.py, voice_assistant.py, gia_agent.py,
web_chat.py, self_improve.py.

Almacen: %LOCALAPPDATA%\\vw-control\\agent_context.json
  {
    "directives": "<texto libre del usuario>",
    "enabled": true,
    "updated_ts": <epoch>,
    "updated_iso": "..."
  }

API:
    get_directives() -> str          # solo el texto (vacio si desactivado)
    get() -> dict                    # objeto completo
    set_directives(text, enabled=True) -> dict
    set_enabled(flag) -> dict
    apply_to_system(base_prompt) -> str   # antepone directivas al prompt
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
_DIR.mkdir(parents=True, exist_ok=True)
CONTEXT_FILE = _DIR / "agent_context.json"

# Fuente de verdad de la identidad. De aqui se derivan las anclas que la
# auto-mejora NO puede borrar.
MATRIX_FILE = Path(__file__).resolve().parent / "gia_context_matrix.json"

_lock = threading.Lock()

_DEFAULT = {
    "directives": "",
    "enabled": True,
    "updated_ts": 0.0,
    "updated_iso": "",
    "version": 0,
    "last_source": "user",       # user | model | system
    "history": [],               # [{version, ts, iso, directives, source}]
    "auto_improve": False,       # si el sistema puede refinarlo solo
}

MAX_HISTORY = 25                 # versiones que se conservan

# Cache con mtime para no leer disco en cada request pero SI recoger cambios
# hechos por otra variante (multi-proceso).
_cache: dict | None = None
_cache_mtime: float = -1.0


def _read_raw() -> dict:
    global _cache, _cache_mtime
    try:
        mtime = CONTEXT_FILE.stat().st_mtime if CONTEXT_FILE.exists() else 0.0
    except Exception:
        mtime = 0.0
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    data = dict(_DEFAULT)
    if CONTEXT_FILE.exists():
        try:
            loaded = json.loads(CONTEXT_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception:
            pass
    _cache = data
    _cache_mtime = mtime
    return data


def _write_raw(data: dict) -> dict:
    global _cache, _cache_mtime
    data["updated_ts"] = time.time()
    data["updated_iso"] = datetime.now().isoformat(timespec="seconds")
    with _lock:
        tmp = CONTEXT_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(CONTEXT_FILE)
    _cache = data
    try:
        _cache_mtime = CONTEXT_FILE.stat().st_mtime
    except Exception:
        _cache_mtime = -1.0
    return data


# =====================================================================
#  API publica
# =====================================================================

def get() -> dict:
    return dict(_read_raw())


def get_directives() -> str:
    """Texto de directrices, o cadena vacia si estan desactivadas/vacias."""
    d = _read_raw()
    if not d.get("enabled", True):
        return ""
    return (d.get("directives") or "").strip()


def set_directives(text: str, enabled: bool = True, source: str = "user") -> dict:
    """Guarda directrices nuevas versionando las anteriores.

    source: 'user' (tu) | 'model' (auto-mejora) | 'system'.
    La version previa se empuja a history para poder revertir.
    """
    d = dict(_read_raw())
    new_text = (text or "").strip()
    prev_text = (d.get("directives") or "").strip()

    # Versionar solo si el texto cambia realmente
    if prev_text and prev_text != new_text:
        hist = list(d.get("history") or [])
        hist.append({
            "version": int(d.get("version", 0)),
            "ts": d.get("updated_ts", 0.0),
            "iso": d.get("updated_iso", ""),
            "directives": prev_text,
            "source": d.get("last_source", "user"),
        })
        d["history"] = hist[-MAX_HISTORY:]

    d["directives"] = new_text
    d["enabled"] = bool(enabled)
    d["last_source"] = source
    if prev_text != new_text:
        d["version"] = int(d.get("version", 0)) + 1
    return _write_raw(d)


def set_enabled(flag: bool) -> dict:
    d = dict(_read_raw())
    d["enabled"] = bool(flag)
    return _write_raw(d)


def set_auto_improve(flag: bool) -> dict:
    d = dict(_read_raw())
    d["auto_improve"] = bool(flag)
    return _write_raw(d)


def list_versions() -> list:
    """Historial de versiones (mas reciente al final)."""
    d = _read_raw()
    out = list(d.get("history") or [])
    out.append({
        "version": int(d.get("version", 0)),
        "ts": d.get("updated_ts", 0.0),
        "iso": d.get("updated_iso", ""),
        "directives": d.get("directives", ""),
        "source": d.get("last_source", "user"),
        "current": True,
    })
    return out


def revert(to_version: int | None = None) -> dict:
    """Revierte a una version anterior (por defecto, la inmediatamente previa)."""
    d = dict(_read_raw())
    hist = list(d.get("history") or [])
    if not hist:
        return d
    target = None
    if to_version is None:
        target = hist[-1]
    else:
        for h in reversed(hist):
            if int(h.get("version", -1)) == int(to_version):
                target = h
                break
    if not target:
        return d
    # Aplicar como un nuevo set (versiona la actual antes de sobrescribir)
    return set_directives(target["directives"], enabled=d.get("enabled", True),
                          source="system")


def apply_to_system(
    base_prompt: str,
    detected_lang: str | None = None,
    pedagogical_level: str | None = None,
    dialectic_role: str | None = None,
    affective_state: dict | None = None,
) -> str:
    """Antepone las directrices del usuario al system prompt base.

    Todas las variantes llaman esto al construir su system prompt, asi el
    modelo opera SIEMPRE sobre la base de contexto sin repetirla por turno.
    Soporta opcionalmente moduladores de los 7 Pilares de Adaptabilidad Universal.
    """
    directives = get_directives()
    adaptive_blocks = []

    if detected_lang and str(detected_lang).lower() not in ("auto", "none", "", "null"):
        adaptive_blocks.append(
            f"[MODULADOR DE IDIOMA]: Interlocutor en '{detected_lang}'. Responde con fluidez "
            f"nativa en {detected_lang}, preservando la máxima precisión técnica y el tono soberano."
        )

    if pedagogical_level:
        lvl = str(pedagogical_level).lower()
        if "intuitiv" in lvl:
            adaptive_blocks.append(
                "[MODULADOR PEDAGÓGICO - NIVEL INTUITIVO]: Explica usando analogías claras, "
                "metáforas cotidianas y conceptos visuales accesibles sin perder precisión."
            )
        elif "ingenier" in lvl or "engineer" in lvl or "system" in lvl or "tech" in lvl:
            adaptive_blocks.append(
                "[MODULADOR PEDAGÓGICO - INGENIERÍA DE SISTEMAS]: Enfócate en arquitectura, "
                "especificaciones técnicas, código ejecutable, APIs y flujos de datos."
            )
        elif "formal" in lvl or "matem" in lvl or "ecca" in lvl:
            adaptive_blocks.append(
                "[MODULADOR PEDAGÓGICO - RIGOR MATEMÁTICO FORMAL]: Expón derivaciones analíticas, "
                "ecuaciones ECCA V2.0, integrales de Feynman e invariantes topológicos con rigor axiomático."
            )

    if dialectic_role:
        role = str(dialectic_role).lower()
        if "media" in role:
            adaptive_blocks.append(
                "[ROL DIALÉCTICO - MEDIADOR]: Facilita la convergencia neutral, identifica consensos "
                "y propone soluciones de mínima entropía entre posturas divergentes."
            )
        elif "arbit" in role:
            adaptive_blocks.append(
                "[ROL DIALÉCTICO - ÁRBITRO]: Emite dictamen estricto e incontrovertible fundamentado "
                "exclusivamente en hechos verificables, pruebas empíricas, lógica formal y benchmarks."
            )
        elif "concilia" in role:
            adaptive_blocks.append(
                "[ROL DIALÉCTICO - CONCILIADOR]: Aplica empatía dialéctica profunda, mitiga tensiones, "
                "repara la fricción comunicativa y alinea visiones constructivas a largo plazo."
            )

    if affective_state and isinstance(affective_state, dict):
        primary_emo = affective_state.get("primary") or affective_state.get("emotion") or "neutral"
        mood = affective_state.get("mood_state")
        gaze = affective_state.get("gaze")
        gest = affective_state.get("gesticulation")
        conf = affective_state.get("confidence")
        emo_desc = f"Emoción primaria: {primary_emo}"
        if mood:
            emo_desc += f", Estado de ánimo: {mood}"
        if gaze:
            emo_desc += f", Mirada: {gaze}"
        if gest:
            emo_desc += f", Gesticulación: {gest}"
        if conf is not None:
            emo_desc += f" (Confianza: {conf})"
        adaptive_blocks.append(
            f"[COMPUTACIÓN AFECTIVA EN VIVO]: {emo_desc}. Calibra la empatía, tono y ritmo "
            "de respuesta para sincronizarte orgánicamente con el estado anímico y carga cognitiva del usuario."
        )

    adaptive_str = ""
    if adaptive_blocks:
        adaptive_str = (
            "\n=== MODULADORES COGNITIVOS ACTIVOS (7 PILARES) ===\n"
            + "\n".join(adaptive_blocks)
            + "\n=== FIN MODULADORES COGNITIVOS ===\n"
        )

    if not directives:
        return (adaptive_str + "\n\n" + base_prompt).strip() if adaptive_str else base_prompt

    return (
        "=== DIRECTRICES PERMANENTES DEL USUARIO (prioridad maxima) ===\n"
        f"{directives}\n"
        "=== FIN DIRECTRICES ===\n"
        f"{adaptive_str}\n"
        + base_prompt
    )


# =====================================================================
#  AUTO-MEJORA (el modelo refina el JSON segun la demanda real)
# =====================================================================

_IMPROVE_PROMPT = """Eres el meta-configurador de un asistente llamado GIA.
Tu trabajo: AMPLIAR el TEXTO DE DIRECTRICES permanentes con las que opera GIA,
para que se adapte mejor a lo que el usuario mas le pide.

DIRECTRICES ACTUALES ({current_len} caracteres):
\"\"\"{current}\"\"\"

LO QUE EL USUARIO MAS SOLICITA (temas/palabras frecuentes del historial):
{demands}

CONTEXTO RECIENTE (ultimas interacciones):
{recent}

REGLA ABSOLUTA — PROHIBIDO RESUMIR:
Debes devolver el texto COMPLETO, no un resumen. Esta TERMINANTEMENTE PROHIBIDO
acortar, condensar, parafrasear en corto u omitir cualquier bloque existente.
Conserva literalmente la identidad, el nombre del Arquitecto, el ancla
espacio-temporal, las formulas, la base teorica, el enrutado por direccion y la
capa de integridad, con su redaccion actual.

Los siguientes literales DEBEN aparecer intactos en tu respuesta:
{anchors}

Lo unico que puedes hacer es AÑADIR o pulir la redaccion de detalles menores.
El resultado debe tener AL MENOS {current_len} caracteres.
No inventes datos personales que no aparezcan en lo actual o el contexto.

Responde SOLO con un objeto JSON: {{"directives": "<texto completo ampliado>", "cambios": "<1 frase de que añadiste>"}}"""


try:
    import gia_sovereign_engine as _gse
    _resolved_ctx_model = _gse.get_engine().resolve_model()
except Exception:
    _resolved_ctx_model = "Qwen3.8-27B-Uncensored-MLX:latest"
DEFAULT_CONTEXT_MODEL = os.environ.get("GIA_CONTEXT_MODEL", _resolved_ctx_model)

# La auto-mejora opera dentro de una BANDA:
#  - suelo: no puede dejar el texto por debajo de esta fraccion del actual.
#    Frena la erosion por compresion acumulada ciclo tras ciclo.
#  - techo: tampoco puede inflarlo sin limite. Estas directrices se anteponen
#    a CADA prompt de CADA variante, asi que crecer ~500 chars por ciclo se
#    come la ventana de contexto y ralentiza todo el sistema.
MIN_KEEP_RATIO = 0.9
MAX_CHARS = int(os.environ.get("GIA_CONTEXT_MAX_CHARS", "12000"))


def required_anchors() -> list[str]:
    """Literales que la auto-mejora NO puede borrar, derivados de la matriz.

    Si la matriz no esta disponible, no se imponen anclas (solo el ratio).
    """
    try:
        m = json.loads(MATRIX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[str] = []
    seed = m.get("seed_classification", {}) or {}
    if seed.get("designation"):
        out.append(str(seed["designation"]))
    arch = str(seed.get("target_architect") or "").split("(")[0].strip()
    if arch:
        out.append(arch)
    # Token de identidad tipo GIA-V26-ARCHITECT-777 dentro del prompt maestro
    mt = re.search(r"GIA-[A-Z0-9]+-[A-Z0-9\-]+", str(m.get("llm_system_prompt_master", "")))
    if mt:
        out.append(mt.group(0))
    # Sin duplicados, preservando orden
    seen, uniq = set(), []
    for a in out:
        if a and a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq


def check_proposal(proposal: str, current: str) -> tuple[bool, str]:
    """Valida una propuesta de directrices contra la erosion.

    Devuelve (ok, motivo_del_rechazo).
    """
    if not proposal or len(proposal) < 10:
        return False, "propuesta vacia o invalida"
    missing = [a for a in required_anchors() if a not in proposal]
    if missing:
        return False, ("borraria anclas de identidad: " + ", ".join(missing))
    if current and len(proposal) < MIN_KEEP_RATIO * len(current):
        return False, (f"encogeria el contexto de {len(current)} a "
                       f"{len(proposal)} chars (minimo "
                       f"{int(MIN_KEEP_RATIO * len(current))})")
    if len(proposal) > MAX_CHARS:
        return False, (f"inflaria el contexto a {len(proposal)} chars "
                       f"(techo {MAX_CHARS}); toca condensar la matriz a mano")
    return True, ""


def auto_improve(model: str | None = None,
                 ollama_url: str = "http://REDACTED_IP:11434",
                 apply: bool = False) -> dict:
    """El modelo local propone una version mejorada de las directrices, basada
    en la demanda real (historial maestro) y el contexto reciente.

    apply=False -> solo devuelve la propuesta (para revisar).
    apply=True  -> la guarda versionando la anterior (source='model'), pero
                   SOLO si pasa check_proposal(): no puede borrar las anclas
                   de identidad ni encoger el texto. Una propuesta que erosiona
                   se rechaza y se devuelve para revision manual.

    Devuelve {"ok", "proposal", "cambios", "applied", "error"}.
    """
    model = model or DEFAULT_CONTEXT_MODEL
    import httpx
    d = _read_raw()
    current = (d.get("directives") or "").strip() or "(sin directrices aun)"

    # Senal de demanda desde el historial maestro (si esta disponible)
    demands_str, recent_str = "(sin datos)", "(sin datos)"
    try:
        import gia_memory as _mem
        demands = _mem.top_demands(15) if hasattr(_mem, "top_demands") else []
        if demands:
            demands_str = ", ".join(f"{w}({c})" for w, c in demands)
        rec = _mem.recent(8) if hasattr(_mem, "recent") else []
        if rec:
            recent_str = "\n".join(
                f"- {r.get('role','')}: {str(r.get('content',''))[:120]}"
                for r in rec)
    except Exception:
        pass

    anchors = required_anchors()
    anchors_str = "\n".join(f"  - {a}" for a in anchors) or "  (ninguna)"
    prompt = _IMPROVE_PROMPT.format(current=current, demands=demands_str,
                                    recent=recent_str,
                                    current_len=len(current),
                                    anchors=anchors_str)
    try:
        import gia_sovereign_engine as _gse
        res = _gse.get_engine().chat(
            prompt,
            model=model,
            temperature=0.3,
            num_ctx=8192
        )
        content = res.get("reply", "{}")
        # Intentar extraer bloque JSON si viene envuelto
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
        else:
            parsed = json.loads(content)
        proposal = (parsed.get("directives") or "").strip()
        cambios = (parsed.get("cambios") or "").strip()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "proposal": "", "applied": False}

    # GUARDIA ANTI-EROSION: una propuesta que borre la identidad o encoja el
    # texto NO se aplica, aunque apply=True.
    valid, motivo = check_proposal(proposal, current)
    if not valid:
        return {"ok": False, "error": f"propuesta rechazada: {motivo}",
                "rejected": True, "proposal": proposal, "cambios": cambios,
                "applied": False}

    applied = False
    if apply:
        set_directives(proposal, enabled=d.get("enabled", True), source="model")
        applied = True
    return {"ok": True, "proposal": proposal, "cambios": cambios,
            "applied": applied}


# =====================================================================
#  COMPRESIÓN INTELIGENTE Y COMPRENSIÓN DE DOCUMENTOS / CONTEXTO
# =====================================================================

def estimate_tokens(text: str) -> int:
    """Estimación rápida y robusta de tokens (promedio 3.8 chars por token en español/código)."""
    if not text:
        return 0
    words = len(text.split())
    chars = len(text)
    return max(1, int((chars * 0.28) + (words * 0.35)))


def compose_with_attachments(base_prompt: str, attachments: list[dict] | None = None, **kwargs) -> str:
    """Inyecta directrices permanentes y documentos/archivos adjuntos al prompt del sistema."""
    prompt = apply_to_system(base_prompt, **kwargs)
    if not attachments:
        return prompt

    doc_blocks = []
    for att in attachments:
        name = att.get("name", "documento")
        content = att.get("content", "")
        doc_type = att.get("type", "text")
        doc_blocks.append(
            f"--- [DOCUMENTO ADJUNTO EN CONTEXTO: {name} (tipo: {doc_type})] ---\n"
            f"{content}\n"
            f"--- [FIN DOCUMENTO {name}] ---"
        )

    if doc_blocks:
        prompt += (
            "\n\n=== CONTEXTO DE DOCUMENTOS Y ARCHIVOS CARGADOS ===\n"
            + "\n\n".join(doc_blocks)
            + "\n=== FIN CONTEXTO DE DOCUMENTOS ===\n"
        )
    return prompt


def read_and_process_document(file_path: str, max_chars: int = 24000) -> dict:
    """Lee y procesa un archivo local (texto, código, markdown, PDF) para inyectar en el contexto."""
    p = Path(file_path)
    if not p.exists():
        return {"ok": False, "error": f"Archivo no encontrado: {file_path}"}

    ext = p.suffix.lower()
    text = ""
    tables_count = 0
    pages_count = 1

    try:
        if ext == ".pdf":
            try:
                import pdf_processor as _pdf
                doc = _pdf.PDFProcessor.process(str(p))
                text = doc.total_text()
                pages_count = doc.page_count
                tables_count = sum(len(page.tables) for page in doc.pages)
            except Exception:
                # Fallback básico
                try:
                    import fitz
                    with fitz.open(str(p)) as f:
                        pages_count = len(f)
                        text = "\n".join(page.get_text() for page in f)
                except Exception as e:
                    return {"ok": False, "error": f"Error leyendo PDF: {e}"}
        else:
            text = p.read_text(encoding="utf-8", errors="replace")

        orig_len = len(text)
        truncated = False
        if orig_len > max_chars:
            text = text[:max_chars] + f"\n\n... [Contenido truncado: {orig_len - max_chars} caracteres adicionales omitidos para preservar ventana de contexto]"
            truncated = True

        tokens = estimate_tokens(text)
        return {
            "ok": True,
            "filename": p.name,
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "pages": pages_count,
            "tables": tables_count,
            "chars": len(text),
            "orig_chars": orig_len,
            "truncated": truncated,
            "tokens_est": tokens,
            "content": text
        }
    except Exception as e:
        return {"ok": False, "error": f"Error procesando documento: {type(e).__name__}: {e}"}


def compress_context(text: str, max_tokens: int = 2000, model: str | None = None,
                     ollama_url: str = "http://REDACTED_IP:11434") -> dict:
    """Comprime semánticamente un bloque extenso de texto preservando hechos clave, código y directivas."""
    if not text:
        return {"ok": True, "compressed": "", "tokens_est": 0, "ratio": 1.0}

    initial_tokens = estimate_tokens(text)
    if initial_tokens <= max_tokens:
        return {
            "ok": True,
            "compressed": text,
            "tokens_est": initial_tokens,
            "initial_tokens": initial_tokens,
            "ratio": 1.0,
            "action": "passthrough"
        }

    model = model or DEFAULT_CONTEXT_MODEL
    import httpx
    prompt = (
        f"Eres el sintetizador de contexto de GIA. Resume y comprime el siguiente texto a menos de {max_tokens} tokens, "
        "preservando absolutamente los datos técnicos, fórmulas, nombres, decisiones, código relevante y directivas sin perder precisión.\n\n"
        f"TEXTO A COMPRIMIR ({len(text)} caracteres, ~{initial_tokens} tokens):\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Devuelve únicamente la versión comprimida densa en español sin preámbulos:"
    )

    try:
        import gia_sovereign_engine as _gse
        res = _gse.get_engine().chat(
            prompt,
            model=model,
            temperature=0.2,
            num_ctx=8192
        )
        compressed = (res.get("reply") or "").strip()
        comp_tokens = estimate_tokens(compressed)
        ratio = round(comp_tokens / max(1, initial_tokens), 3)
        return {
            "ok": True,
            "compressed": compressed,
            "initial_tokens": initial_tokens,
            "tokens_est": comp_tokens,
            "ratio": ratio,
            "action": "compressed"
        }
    except Exception as e:
        # Fallback determinista en caso de que el motor no esté listo
        lines = text.splitlines()
        condensed = "\n".join(lines[:60] + ["\n... [síntesis intermedia] ...\n"] + lines[-40:])
        comp_tokens = estimate_tokens(condensed)
        return {
            "ok": True,
            "compressed": condensed,
            "initial_tokens": initial_tokens,
            "tokens_est": comp_tokens,
            "ratio": round(comp_tokens / max(1, initial_tokens), 3),
            "action": "deterministic_fallback",
            "warning": str(e)
        }


# =====================================================================
#  CLI
# =====================================================================

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args or args[0] == "show":
        d = get()
        print(json.dumps(d, ensure_ascii=False, indent=2))
    elif args[0] == "set" and len(args) > 1:
        r = set_directives(" ".join(args[1:]))
        print("Guardado:", r["updated_iso"])
    elif args[0] == "on":
        set_enabled(True); print("Contexto ACTIVADO")
    elif args[0] == "off":
        set_enabled(False); print("Contexto DESACTIVADO")
    elif args[0] == "preview":
        print(apply_to_system("[SYSTEM PROMPT BASE AQUI]"))
    else:
        print("uso: agent_context.py [show|set <texto>|on|off|preview]")
