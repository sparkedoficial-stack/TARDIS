#!/usr/bin/env python3
"""
GODWORKS · FTL Free Model Catalog
=================================
Catálogo canónico de TODOS los modelos gratuitos accesibles desde este host
(vía OpenCode, sin API key) con sonda de disponibilidad real, variantes de
máximo esfuerzo y control individual.

Fuente de descubrimiento: `opencode models` (proveedor `opencode`).
Estado persistente:       ~/.config/ftl/free_models_state.json
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

import runtime_env

CONFIG_DIR = Path.home() / ".config" / "ftl"
STATE_FILE = CONFIG_DIR / "free_models_state.json"
PROBE_TTL = 3600
DISCOVERY_TTL = 3600
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass(frozen=True)
class FreeModel:
    key: str                     # alias corto e invocable
    model_id: str                # id completo del proveedor
    name: str                    # nombre legible
    variant: str                 # variante de máximo esfuerzo ("" si no aplica)
    roles: tuple[str, ...]       # especialidades para el orquestador
    vision: bool = False
    priority: int = 50           # menor = antes en la cadena
    enabled_default: bool = True
    notes: str = ""

    @property
    def ref(self) -> str:
        return f"{self.model_id}#{self.variant}" if self.variant else self.model_id

    @property
    def short(self) -> str:
        return self.model_id.split("/", 1)[-1]

    def as_dict(self) -> dict:
        return asdict(self) | {"ref": self.ref}


# ---------------------------------------------------------------------------
# Catálogo (verificado empíricamente el 2026-10-27)
# ---------------------------------------------------------------------------
CATALOG: tuple[FreeModel, ...] = (
    FreeModel(
        key="deepseek",
        model_id="opencode/deepseek-v4.1-flash-free",
        name="DeepSeek V4.1 Max",
        variant="max",
        roles=("razonamiento", "código", "auditoría", "general"),
        priority=10,
        notes="Alterno soberano primario. Razonamiento profundo y código.",
    ),
    FreeModel(
        key="glm",
        model_id="opencode/glm-5.3-flash-free",
        name="GLM-5.3 Flash Max",
        variant="max",
        roles=("razonamiento", "contexto-largo", "multilingüe", "general"),
        priority=20,
        notes="Excelente en contexto largo y redacción técnica; latencia alta en frío.",
    ),
    FreeModel(
        key="flint",
        model_id="opencode/flint-40b-free",
        name="Flint 40B Max",
        variant="max",
        roles=("código", "refactor", "debug", "tests"),
        priority=30,
        notes="Especialista en código y refactorización.",
    ),
    FreeModel(
        key="nemotron-vl",
        model_id="opencode/nemotron-3.5-super-vl-free",
        name="Nemotron 3.5 Super VL",
        variant="xhigh",
        roles=("visión", "multimodal", "análisis", "ui"),
        vision=True,
        priority=40,
        notes="Modelo visión-lenguaje: capturas, diagramas, UI, PDFs renderizados.",
    ),
    FreeModel(
        key="mimo",
        model_id="opencode/mimo-v2.6-flash-free",
        name="MiMo V2.6 Flash",
        variant="",
        roles=("código", "rápido", "extracción"),
        priority=50,
        notes="Rápido y competente en código; sin variantes de esfuerzo.",
    ),
    FreeModel(
        key="lightning",
        model_id="opencode/nemotron-3.5-lightning-free",
        name="Nemotron 3.5 Lightning",
        variant="",
        roles=("rápido", "clasificación", "resumen", "extracción"),
        priority=60,
        notes="El más veloz del pool; ideal para tareas deterministas y resúmenes.",
    ),
    FreeModel(
        key="beam",
        model_id="opencode/beam-free",
        name="Beam Free",
        variant="max",
        roles=("general", "rápido", "redacción"),
        priority=70,
        notes="Propósito general con variantes low→max.",
    ),
    FreeModel(
        key="pickle",
        model_id="opencode/big-pickle",
        name="Big Pickle",
        variant="",
        roles=("general", "creatividad", "ideación"),
        priority=80,
        notes="Modelo general/creativo; sin variantes.",
    ),
    FreeModel(
        key="nemotron-ultra",
        model_id="opencode/nemotron-3-ultra-free",
        name="Nemotron 3 Ultra",
        variant="",
        roles=("contexto-largo", "razonamiento"),
        priority=90,
        enabled_default=False,
        notes="Deshabilitado: upstream devuelve 'Model is unavailable' (verificado 2026-10-27).",
    ),
)

BY_KEY = {m.key: m for m in CATALOG}
BY_ID = {m.model_id: m for m in CATALOG}
ALIASES = {
    "deepseek": "deepseek", "v4.1": "deepseek", "alterno": "deepseek",
    "glm": "glm", "glm5": "glm", "zhipu": "glm",
    "flint": "flint", "flint40b": "flint",
    "nemotron-vl": "nemotron-vl", "vl": "nemotron-vl", "vision": "nemotron-vl",
    "mimo": "mimo",
    "lightning": "lightning", "rayo": "lightning", "fast": "lightning",
    "beam": "beam",
    "pickle": "pickle", "big-pickle": "pickle",
    "ultra": "nemotron-ultra", "nemotron-ultra": "nemotron-ultra",
}
DEFAULT_POOL = tuple(m.key for m in sorted(CATALOG, key=lambda x: x.priority))


# ---------------------------------------------------------------------------
# Descubrimiento dinámico: TODOS los modelos gratuitos del proveedor
# ---------------------------------------------------------------------------
_DYN_CACHE: dict = {"ts": 0.0, "models": []}
_KNOWN_IDS = {m.model_id.split("#", 1)[0] for m in CATALOG}


def _pretty_name(model_id: str) -> str:
    base = model_id.split("/", 1)[-1].split("#", 1)[0]
    for suffix in ("-flash-free", "-free"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    words = re.split(r"[-_.]+", base)
    return " ".join(w.upper() if len(w) <= 3 and w.isalpha() else w.capitalize() for w in words if w)


def _slugify(model_id: str) -> str:
    base = model_id.split("/", 1)[-1].split("#", 1)[0]
    for suffix in ("-flash-free", "-free"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return slug or "modelo"


def discover(timeout: int = 30, save: bool = True) -> list[str]:
    """
    Pregunta a `opencode models` por el catálogo real del proveedor.

    Devuelve referencias canónicas (sin `#variante`) y las persiste para que
    Telegram, la TUI y el portal compartan exactamente el mismo pool.
    """
    exe = _bin()
    if not exe:
        return []
    try:
        proc = subprocess.run(
            [exe, "models"],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []

    refs: list[str] = []
    for line in _clean(proc.stdout).splitlines():
        candidate = line.strip()
        if not candidate or "/" not in candidate or " " in candidate:
            continue
        if candidate.startswith(("-", "#", ">")):
            continue
        base = candidate.split("#", 1)[0]
        if "free" not in base.lower() and not base.startswith("opencode/"):
            continue
        if base not in refs:
            refs.append(base)

    if save:
        state = _load_state()
        state["discovered_refs"] = refs
        state["discovered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        state["discovered_epoch"] = time.time()
        _save_state(state)
        _DYN_CACHE["ts"] = 0.0
    return refs


def dynamic_models(ttl: int = DISCOVERY_TTL) -> list["FreeModel"]:
    """Modelos gratuitos descubiertos que no están en el catálogo canónico."""
    now = time.time()
    if now - float(_DYN_CACHE["ts"]) < ttl:
        return list(_DYN_CACHE["models"])

    state = _load_state()
    refs = list(state.get("discovered_refs") or [])
    models: list[FreeModel] = []
    for idx, ref in enumerate(refs):
        if ref in _KNOWN_IDS:
            continue
        slug = _slugify(ref)
        key = slug
        suffix = 2
        while key in BY_KEY or any(m.key == key for m in models):
            key = f"{slug}-{suffix}"
            suffix += 1
        models.append(
            FreeModel(
                key=key,
                model_id=ref,
                name=_pretty_name(ref),
                variant="",
                roles=("general", "descubierto"),
                priority=90 + idx,
                enabled_default=True,
                notes="Descubierto dinámicamente desde `opencode models`.",
            )
        )
    _DYN_CACHE.update({"ts": now, "models": models})
    return list(models)


def refresh_discovery_if_stale(ttl: int = DISCOVERY_TTL) -> list[str]:
    """Descubre el catálogo sólo si la caché persistida está vencida."""
    state = _load_state()
    age = time.time() - float(state.get("discovered_epoch") or 0)
    if state.get("discovered_refs") and age < ttl:
        return list(state["discovered_refs"])
    return discover()


def pool_models() -> list["FreeModel"]:
    """Pool operable para failover: verificados o, si no hay sondas, el catálogo."""
    pool = available_models()
    if pool:
        return pool
    return [m for m in all_models(include_disabled=False) if m.enabled_default]


def aliases() -> dict[str, str]:
    """Mapa alias/atajo/id → key canónica, incluyendo modelos descubiertos."""
    table: dict[str, str] = dict(ALIASES)
    for model in all_models():
        table.setdefault(model.key.lower(), model.key)
        table.setdefault(model.short.lower(), model.key)
        table.setdefault(model.model_id.lower(), model.key)
    return table


# ---------------------------------------------------------------------------
# Estado persistente
# ---------------------------------------------------------------------------
def _load_state() -> dict:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw.setdefault("models", {})
            return raw
    except Exception:
        pass
    return {"models": {}, "updated_at": None}


def _save_state(state: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        pass


def _bin() -> Optional[str]:
    """Binario real de OpenCode, incluso con el PATH reducido de systemd."""
    return runtime_env.which("opencode")


def _clean(text: str) -> str:
    clean = ANSI_RE.sub("", text or "")
    return "\n".join(
        line for line in clean.splitlines()
        if not line.strip().startswith("> build ·")
    ).strip()


# ---------------------------------------------------------------------------
# Resolución y metadatos
# ---------------------------------------------------------------------------
def resolve(token: str) -> Optional[FreeModel]:
    """Resuelve alias, key, nombre corto o id completo (con o sin #variante)."""
    if not token:
        return None
    t = token.strip().lower()
    base = t.split("#", 1)[0]
    if base in BY_ID:
        return BY_ID[base]
    if base in BY_KEY:
        return BY_KEY[base]
    if base in ALIASES:
        return BY_KEY[ALIASES[base]]
    short = base.split("/", 1)[-1]
    for m in CATALOG:
        if short in (m.short.lower(), m.key.lower(), m.name.lower()):
            return m
    # Modelos descubiertos dinámicamente (todos los gratuitos del proveedor).
    for m in dynamic_models():
        if base in (m.key.lower(), m.model_id.lower(), m.short.lower(), m.name.lower()):
            return m
    # Coincidencia difusa por prefijo (p. ej. "nemotron")
    catalog = list(CATALOG) + dynamic_models()
    matches = [m for m in catalog if m.key.startswith(base) or m.short.lower().startswith(base)]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    # Varios candidatos: gana el primero disponible (evita modelos caídos)
    for m in matches:
        try:
            if is_available(m):
                return m
        except Exception:
            continue
    return matches[0]


def best_ref(model: FreeModel) -> str:
    return model.ref


def model_state(key: str) -> dict:
    return _load_state().get("models", {}).get(key, {})


def is_available(model: FreeModel, use_state: bool = True) -> bool:
    if not model.enabled_default:
        return False
    st = model_state(model.key)
    if st.get("enabled") is False:
        return False
    if not use_state:
        return True
    if st.get("available") is None:
        return True  # sin sonda todavía: se asume disponible
    return bool(st.get("available"))


def all_models(include_disabled: bool = True) -> list[FreeModel]:
    models = sorted(list(CATALOG) + dynamic_models(), key=lambda m: m.priority)
    if include_disabled:
        return list(models)
    return [m for m in models if is_available(m)]


def available_models() -> list[FreeModel]:
    return [m for m in all_models(include_disabled=False) if is_available(m)]


# ---------------------------------------------------------------------------
# Sonda de disponibilidad real
# ---------------------------------------------------------------------------
def probe(model: FreeModel, timeout: int = 150) -> dict:
    t0 = time.time()
    state = _load_state()
    entry = state.setdefault("models", {}).setdefault(model.key, {})

    if entry.get("enabled") is False:
        entry.update({"available": False, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                      "checked_epoch": time.time(), "error": "deshabilitado por el operador"})
        _save_state(state)
        return entry

    exe = _bin()
    if not exe:
        entry.update({"available": False, "error": "binario 'opencode' no encontrado (PATH soberano agotado)",
                      "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checked_epoch": time.time()})
        _save_state(state)
        return entry

    try:
        proc = subprocess.run(
            [exe, "run", "-m", model.ref, "--auto",
             "Responde únicamente con la palabra: OK"],
            capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
        txt = _clean(proc.stdout)
        ok = proc.returncode == 0 and bool(txt)
        entry.update({
            "available": ok,
            "rc": proc.returncode,
            "latency_s": round(time.time() - t0, 2),
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "checked_epoch": time.time(),
            "error": "" if ok else _clean(proc.stderr)[:300] or txt[:300] or "sin respuesta",
        })
    except subprocess.TimeoutExpired:
        entry.update({
            "available": False, "rc": 124, "latency_s": round(time.time() - t0, 2),
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checked_epoch": time.time(),
            "error": f"timeout tras {timeout}s",
        })
    except Exception as exc:
        entry.update({
            "available": False, "rc": -1, "latency_s": round(time.time() - t0, 2),
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checked_epoch": time.time(),
            "error": str(exc)[:300],
        })
    _save_state(state)
    return entry


def refresh(force: bool = False, ttl: int = PROBE_TTL,
            on_progress: Optional[Callable[[str], None]] = None) -> list[dict]:
    """Sondea todos los modelos cuyo estado esté vencido (secuencial, conservador)."""
    # 1. Refrescar el catálogo real del proveedor (todos los gratuitos).
    try:
        if on_progress:
            on_progress("🧭 Descubriendo modelos gratuitos en `opencode models`…")
        discover()
    except Exception:
        pass

    results = []
    now = time.time()
    for model in all_models():
        st = model_state(model.key)
        fresh = (now - float(st.get("checked_epoch", 0))) < ttl
        if not force and fresh and "available" in st:
            results.append({"key": model.key, "skipped": True, **st})
            continue
        if on_progress:
            on_progress(f"🔎 Sondeando {model.name} ({model.ref})…")
        rec = probe(model)
        results.append({"key": model.key, **rec})
    return results


def set_enabled(key: str, enabled: bool) -> bool:
    model = resolve(key)
    if not model:
        return False
    state = _load_state()
    entry = state.setdefault("models", {}).setdefault(model.key, {})
    entry["enabled"] = bool(enabled)
    if not enabled:
        entry["available"] = False
    _save_state(state)
    return True


def set_state(key: str, **fields) -> None:
    model = resolve(key)
    if not model:
        return
    state = _load_state()
    state.setdefault("models", {}).setdefault(model.key, {}).update(fields)
    _save_state(state)


def summary() -> dict:
    state = _load_state()
    models = []
    for m in all_models():
        st = state.get("models", {}).get(m.key, {})
        models.append({
            "key": m.key, "name": m.name, "ref": m.ref, "roles": list(m.roles),
            "vision": m.vision, "priority": m.priority,
            "enabled": st.get("enabled", m.enabled_default),
            "available": st.get("available"),
            "latency_s": st.get("latency_s"),
            "checked_at": st.get("checked_at"),
            "error": st.get("error", ""),
        })
    return {
        "total": len(models),
        "verified": sum(1 for m in models if m["available"] is True),
        "enabled": sum(1 for m in models if m["enabled"]),
        "models": models,
        "updated_at": state.get("updated_at"),
    }


def specialist_for(task: str) -> FreeModel:
    """Selecciona el especialista más adecuado según la tarea."""
    t = (task or "").lower()
    def pick(*keys: str) -> Optional[FreeModel]:
        for k in keys:
            m = BY_KEY.get(k)
            if m and is_available(m):
                return m
        return None

    if any(w in t for w in ("imagen", "image", "captura", "screenshot", "diagrama", "ui ", "pdf", "visión", "vision")):
        m = pick("nemotron-vl")
        if m: return m
    if any(w in t for w in ("refactor", "código", "codigo", "bug", "test", "implementa", "función", "funcion", "python", "typescript", "debug")):
        m = pick("flint", "mimo", "deepseek")
        if m: return m
    if any(w in t for w in ("arquitectura", "auditoría", "auditoria", "diseña", "disena", "razona", "analiza", "estrategia", "seguridad")):
        m = pick("deepseek", "glm", "flint")
        if m: return m
    if any(w in t for w in ("resume", "resumen", "clasifica", "extrae", "lista", "rápido", "rapido", "simple")):
        m = pick("lightning", "beam", "mimo")
        if m: return m
    if any(w in t for w in ("creativo", "idea", "brainstorm", "historia", "nombre")):
        m = pick("pickle", "beam", "glm")
        if m: return m
    return pick("deepseek", "glm", "flint", "beam") or all_models()[0]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        for r in refresh(force=True, on_progress=lambda s: print(s, flush=True)):
            print(json.dumps(r, ensure_ascii=False))
    elif len(sys.argv) > 1 and sys.argv[1] == "--discover":
        for ref in discover():
            print(ref)
    elif len(sys.argv) > 1 and sys.argv[1] == "--json":
        refresh_discovery_if_stale()
        print(json.dumps(summary(), indent=2, ensure_ascii=False))
    else:
        for m in all_models():
            st = model_state(m.key)
            flag = "✓" if st.get("available") else ("…" if st.get("available") is None else "✗")
            print(f"{flag} {m.key:16} {m.ref:52} {','.join(m.roles)}")
