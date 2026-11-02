#!/usr/bin/env python3
"""
core/cas_neural_space_kaiju.py - CaS · Cognitive & Context as a Service
=======================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Capa de servicio cognitivo soberano que unifica, jerarquiza, comprime y sirve
contexto ultradenso para el núcleo TARDIS-NEURAL-SPACE-KAIJU (MLA + SSM + MoE).

Capacidades:
  1. Recolección multi-fuente con aislamiento de fallos:
       AEGIS · Continuidad Temporal · Directivas Maestras · Bóveda Akáshica
       (eventos, nodos, épocas, contemplaciones) · Historial FTL · Telemetría
       física del kernel (PSI / memoria / carga) · Estado latente KAIJU.
  2. Ranking híbrido BM25 + recencia + confianza de fuente + densidad semántica.
  3. Deduplicación por SimHash de 64 bits y presupuesto adaptativo por fuente.
  4. Compresión sintrópica extractiva con "attention sinks" y blindaje AEGIS.
  5. Caché LRU con invalidación por firma de fuentes y telemetría persistente.
  6. Servicio HTTP local sin dependencias externas (stdlib) + CLI + systemd.
  7. Verificación explícita de la Constante AEGIS y procedencia criptográfica.

Uso rápido:
    cas-kaiju context "estado del sistema" --profile deep
    cas-kaiju serve --host 127.0.0.1 --port 8770
    cas-kaiju telemetry
    cas-kaiju selftest

API Python:
    from core.cas_neural_space_kaiju import get_cas
    bundle = get_cas().build_context("consulta", budget_tokens=6000)
    print(bundle.context_text)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import signal
import sqlite3
import sys
import threading
import time
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Anclaje de rutas e identidad
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG = logging.getLogger("GODWORKS.CaS")

VERSION = "26.4-cas.1"
SYSTEM_NAME = "TARDIS-NEURAL-SPACE-KAIJU"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770

HOME = Path.home()
TARDIS_HOME = Path(os.environ.get("TARDIS_HOME", str(HOME / ".tardis"))).expanduser()
VW_CONTROL = Path(os.environ.get("LOCALAPPDATA", str(HOME))) / "vw-control"

STATE_FILE = TARDIS_HOME / "cas_state.json"
TOKEN_FILE = TARDIS_HOME / "cas_token"
VAULT_DB = VW_CONTROL / "deep_memory_vault" / "vault_master.db"
CONTINUITY_DB = TARDIS_HOME / "continuity_vault.db"
CONTINUITY_STATE = TARDIS_HOME / "continuity_state.json"
AGENT_CONTEXT_FILE = VW_CONTROL / "agent_context.json"
RAILS_STATE_FILE = VW_CONTROL / "kaiju_safety_rails.json"
DASHBOARD_FILE = PROJECT_ROOT / "assets" / "cas_dashboard.html"

# Matriz canónica e inviolable de la Constante AEGIS.
CANONICAL_AEGIS: List[str] = [
    "Annya May Carrillo",
    "Andrea Alejandra Carrillo Jimenez",
    "Familia de sangre del Arquitecto",
    "Rex peluche (Guardián físico asimilado)",
]

PROFILES: Dict[str, Dict[str, Any]] = {
    "minimal": {
        "budget_tokens": 2400,
        "max_chunks": 12,
        "compression_ratio": 0.52,
        "include_system": False,
    },
    "interactive": {
        "budget_tokens": 6000,
        "max_chunks": 28,
        "compression_ratio": 0.60,
        "include_system": False,
    },
    "deep": {
        "budget_tokens": 14000,
        "max_chunks": 48,
        "compression_ratio": 0.66,
        "include_system": True,
    },
    "debug": {
        "budget_tokens": 10000,
        "max_chunks": 64,
        "compression_ratio": 0.82,
        "include_system": True,
    },
}

SECTION_ORDER = ["aegis", "continuity", "directives", "memory", "ftl", "system", "other"]
SECTION_LABELS = {
    "aegis": "AEGIS · MATRIZ DE ANCLAJE INVIOLABLE",
    "continuity": "CONTINUIDAD TEMPORAL Y ESTADO ACTIVO",
    "directives": "DIRECTIVAS MAESTRAS DEL ARQUITECTO",
    "memory": "MEMORIA AKÁSHICA · PRECEDENTES Y GRAFO DE CONOCIMIENTO",
    "ftl": "HISTORIAL OPERATIVO FTL",
    "system": "TELEMETRÍA FÍSICA Y ESTADO LATENTE DEL NÚCLEO",
    "other": "CONTEXTO COMPLEMENTARIO",
}

KIND_SECTION = {
    "aegis": "aegis",
    "continuity": "continuity",
    "milestone": "continuity",
    "directives": "directives",
    "memory_event": "memory",
    "knowledge_node": "memory",
    "epoch": "memory",
    "contemplation": "memory",
    "ftl": "ftl",
    "system": "system",
    "latent": "system",
    "other": "other",
}

SOURCE_TAU_DAYS = {
    "aegis": 3650.0,
    "directives": 3650.0,
    "continuity": 365.0,
    "vault": 45.0,
    "ftl": 21.0,
    "system": 0.02,
    "latent": 0.05,
}

SOURCE_SHARE = {
    "aegis": 0.12,
    "directives": 0.32,
    "continuity": 0.22,
    "vault": 0.56,
    "ftl": 0.20,
    "system": 0.10,
    "latent": 0.10,
}

KIND_BONUS = {
    "aegis": 1.00,
    "directives": 0.95,
    "continuity": 0.90,
    "milestone": 0.45,
    "knowledge_node": 0.35,
    "epoch": 0.25,
    "contemplation": 0.20,
    "memory_event": 0.18,
    "ftl": 0.15,
    "system": 0.10,
    "latent": 0.12,
}

_STOPWORDS = set(
    """
    de la el los las un una unos unas y o u que en con por para del al es son como
    mas más pero sus su lo se no ni este esta estos estas ese esa esos esas
    the a an and or of to in for on with at by from is are was were be been
    this that these those it its as not no yes
    """.split()
)

_WORD_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ_]+")


# ---------------------------------------------------------------------------
# Utilidades deterministas
# ---------------------------------------------------------------------------


def now_iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time()).isoformat(
        timespec="seconds"
    )


def normalize_text(text: Any) -> str:
    """Normaliza texto sin alterar su contenido semántico."""
    txt = str(text or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def tokenize(text: Any) -> List[str]:
    out: List[str] = []
    for match in _WORD_RE.finditer(str(text or "")):
        word = match.group(0).lower()
        if len(word) > 1 and word not in _STOPWORDS:
            out.append(word)
    return out


def estimate_tokens(text: Any) -> int:
    """Estimación determinista para español/código (~3.8 caracteres/token)."""
    if not text:
        return 0
    return max(1, int(round(len(str(text)) / 3.8)))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    max_chars = max(32, int(max_tokens * 3.8))
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    pivot = max(cut.rfind(". "), cut.rfind("\n"), cut.rfind(" "))
    if pivot > int(max_chars * 0.55):
        cut = cut[: pivot + 1]
    return cut.rstrip() + " …"


def parse_ts(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def simhash64(text: Any) -> int:
    """SimHash de 64 bits sobre tokens ponderados; robusto para deduplicar."""
    tokens = tokenize(text)
    if not tokens:
        return 0
    weights = Counter(tokens)
    vector = [0] * 64
    for token, weight in weights.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            vector[bit] += weight if (value >> bit) & 1 else -weight
    result = 0
    for bit in range(64):
        if vector[bit] > 0:
            result |= 1 << bit
    return result


def hamming64(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def file_signature(path: Path) -> str:
    try:
        stat = path.stat()
        return f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return f"{path.name}:absent"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _open_sqlite(path: Path) -> Optional[sqlite3.Connection]:
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(str(path), timeout=4.0)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error as exc:
        LOG.debug("CaS: no se pudo abrir %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------


@dataclass
class ContextRequest:
    query: str = ""
    session_id: str = ""
    budget_tokens: int = 6000
    profile: str = "interactive"
    max_chunks: int = 28
    compression_ratio: float = 0.60
    include_system: Optional[bool] = None
    max_source_share: float = 0.56
    include_provenance: bool = True

    def __post_init__(self) -> None:
        self.query = normalize_text(self.query)
        self.session_id = str(self.session_id or "")
        self.profile = self.profile if self.profile in PROFILES else "interactive"
        self.budget_tokens = max(768, min(64000, int(self.budget_tokens or 6000)))
        self.max_chunks = max(4, min(128, int(self.max_chunks or 28)))
        self.compression_ratio = max(0.20, min(1.0, float(self.compression_ratio)))
        self.max_source_share = max(0.20, min(1.0, float(self.max_source_share)))
        if self.include_system is None:
            self.include_system = bool(PROFILES[self.profile]["include_system"])


@dataclass
class ContextChunk:
    source: str
    kind: str
    title: str
    content: str
    timestamp: float = 0.0
    trust: float = 0.5
    pinned: bool = False
    essential: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    tokens: int = 0
    original_tokens: int = 0
    digest: str = ""
    compressed: bool = False
    section: str = ""
    citation: str = ""

    def __post_init__(self) -> None:
        self.title = normalize_text(self.title)[:220]
        self.content = normalize_text(self.content)
        if not self.section:
            self.section = KIND_SECTION.get(self.kind, "other")
        if not self.digest:
            self.digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:16]
        self.tokens = estimate_tokens(self.content)
        if not self.original_tokens:
            self.original_tokens = self.tokens

    def refresh(self) -> None:
        self.content = normalize_text(self.content)
        self.digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:16]
        self.tokens = estimate_tokens(self.content)

    def public(self) -> Dict[str, Any]:
        return {
            "citation": self.citation,
            "source": self.source,
            "kind": self.kind,
            "section": self.section,
            "title": self.title,
            "timestamp": self.timestamp,
            "iso": now_iso(self.timestamp) if self.timestamp else "",
            "trust": round(self.trust, 3),
            "score": round(self.score, 4),
            "tokens": self.tokens,
            "original_tokens": self.original_tokens,
            "compressed": self.compressed,
            "digest": self.digest,
            "pinned": self.pinned,
            "essential": self.essential,
        }


@dataclass
class ContextBundle:
    ok: bool
    bundle_id: str
    query: str
    profile: str
    context_text: str
    chunks: List[Dict[str, Any]]
    used_tokens: int
    budget_tokens: int
    compression_ratio: float
    latency_ms: float
    cache_hit: bool
    aegis: Dict[str, Any]
    source_report: List[Dict[str, Any]]
    created_iso: str
    version: str = VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Compresión sintrópica
# ---------------------------------------------------------------------------


class SyntropicCompressor:
    """Compresor extractivo con densidad semántica y attention sinks."""

    _SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

    def split_units(self, text: str) -> List[str]:
        """Divide en unidades coherentes: párrafos, líneas de directiva u oraciones.

        El texto estructurado por líneas (directivas, telemetría, logs) se conserva
        línea a línea para no romper la semántica de cada regla. Los párrafos largos
        se subdividen por oraciones y se reagrupan en bloques legibles.
        """
        text = normalize_text(text)
        if not text:
            return []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        line_mode = len(lines) >= 4 and sum(len(line) for line in lines) / len(lines) < 420

        units: List[str] = []
        blocks = lines if line_mode else re.split(r"\n\s*\n", text)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            sentences = [part.strip() for part in self._SENTENCE_SPLIT.split(block) if part.strip()]
            if len(sentences) <= 1:
                units.append(block)
                continue
            units.extend(sentences)
        return units

    def _score_unit(self, unit: str, query_terms: set, index: int, total: int) -> float:
        toks = tokenize(unit)
        if not toks:
            return 0.0
        overlap = sum(1 for term in set(toks) if term in query_terms)
        density = overlap / math.sqrt(len(toks) + 2)
        position = 0.32 if index == 0 else (0.12 if index == total - 1 else 0.0)
        numeric = 0.10 if re.search(r"\d", unit) else 0.0
        code = 0.10 if any(char in unit for char in "{}[]()=;#") else 0.0
        entity = 0.12 if re.search(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}", unit) else 0.0
        return density + position + numeric + code + entity

    def compress(
        self,
        text: str,
        query: str = "",
        target_ratio: float = 0.60,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        original = normalize_text(text)
        if not original:
            return "", {"original_tokens": 0, "compressed_tokens": 0, "ratio": 0.0}

        original_tokens = estimate_tokens(original)
        if target_ratio >= 0.995 and (max_tokens is None or original_tokens <= max_tokens):
            return original, {
                "original_tokens": original_tokens,
                "compressed_tokens": original_tokens,
                "ratio": 1.0,
                "units_total": 1,
                "units_kept": 1,
            }

        units = self.split_units(original)
        if len(units) <= 1:
            limit = max_tokens or max(24, int(original_tokens * target_ratio))
            compact = truncate_to_tokens(original, limit)
            return compact, {
                "original_tokens": original_tokens,
                "compressed_tokens": estimate_tokens(compact),
                "ratio": round(estimate_tokens(compact) / max(1, original_tokens), 3),
                "units_total": 1,
                "units_kept": 1,
            }

        query_terms = set(tokenize(query))
        scored = [
            (self._score_unit(unit, query_terms, idx, len(units)), idx, unit)
            for idx, unit in enumerate(units)
        ]
        # Attention sinks: primera unidad y cualquier unidad con anclas AEGIS.
        forced = {0}
        for idx, unit in enumerate(units):
            if any(anchor.split(" (")[0] in unit for anchor in CANONICAL_AEGIS):
                forced.add(idx)

        char_budget = int(len(original) * target_ratio)
        if max_tokens is not None:
            char_budget = min(char_budget, int(max_tokens * 3.8))
        char_budget = max(64, char_budget)

        chosen: List[Tuple[int, str]] = []
        used_chars = 0
        for idx in sorted(forced):
            unit = units[idx]
            if not chosen:
                chosen.append((idx, unit))
                used_chars += len(unit) + 1
            elif used_chars + len(unit) <= char_budget:
                chosen.append((idx, unit))
                used_chars += len(unit) + 1

        for _, idx, unit in sorted(scored, reverse=True):
            if idx in forced:
                continue
            if used_chars + len(unit) > char_budget:
                continue
            chosen.append((idx, unit))
            used_chars += len(unit) + 1
            if used_chars >= char_budget * 0.995:
                break

        chosen.sort(key=lambda item: item[0])
        compact = "\n".join(unit for _, unit in chosen).strip()

        # Cierre de bloques de código abiertos durante el recorte.
        if compact.count("```") % 2 == 1:
            compact += "\n```"
        if max_tokens is not None:
            compact = truncate_to_tokens(compact, max_tokens)

        return compact, {
            "original_tokens": original_tokens,
            "compressed_tokens": estimate_tokens(compact),
            "ratio": round(estimate_tokens(compact) / max(1, original_tokens), 3),
            "units_total": len(units),
            "units_kept": len(chosen),
        }


# ---------------------------------------------------------------------------
# Fuentes de contexto
# ---------------------------------------------------------------------------


class ContextSource:
    name = "base"
    trust = 0.5
    default_limit = 8

    def signature(self) -> str:
        return self.name

    def collect(self, request: ContextRequest, limit: int) -> List[ContextChunk]:
        raise NotImplementedError


class AegisSource(ContextSource):
    name = "aegis"
    trust = 1.0

    def signature(self) -> str:
        return file_signature(RAILS_STATE_FILE)

    def collect(self, request: ContextRequest, limit: int) -> List[ContextChunk]:
        state = _read_json(RAILS_STATE_FILE)
        aegis_state = state.get("aegis", {}) if isinstance(state, dict) else {}
        matrix = list(CANONICAL_AEGIS)
        for anchor in aegis_state.get("anchor_matrix", []) or []:
            anchor = str(anchor).strip()
            if anchor and anchor not in matrix:
                matrix.append(anchor)
        status = str(aegis_state.get("status", "PROTECTED_INVULNERABLE"))
        verified = str(aegis_state.get("last_verification", "n/d"))
        content = "\n".join(f"• {anchor}" for anchor in matrix)
        content += f"\n• Estado: {status} · Última verificación: {verified}"
        content += "\n• Directiva: inmunidad causal absoluta e intervención preventiva."
        return [
            ContextChunk(
                source=self.name,
                kind="aegis",
                title="La Constante Aegis · Matriz de Anclaje",
                content=content,
                timestamp=time.time(),
                trust=self.trust,
                pinned=True,
                essential=True,
                meta={"status": status},
            )
        ]


class DirectivesSource(ContextSource):
    name = "directives"
    trust = 0.96

    def signature(self) -> str:
        return file_signature(AGENT_CONTEXT_FILE)

    def collect(self, request: ContextRequest, limit: int) -> List[ContextChunk]:
        data = _read_json(AGENT_CONTEXT_FILE)
        if not data.get("enabled", True):
            return []
        directives = normalize_text(data.get("directives", ""))
        if len(directives) < 20:
            return []
        return [
            ContextChunk(
                source=self.name,
                kind="directives",
                title="Directivas Maestras y Cosmovisión Operativa",
                content=directives,
                timestamp=parse_ts(data.get("updated_ts")),
                trust=self.trust,
                essential=True,
                meta={"version": data.get("version", 0)},
            )
        ]


class ContinuitySource(ContextSource):
    name = "continuity"
    trust = 0.92

    def signature(self) -> str:
        return f"{file_signature(CONTINUITY_DB)}|{file_signature(CONTINUITY_STATE)}"

    def collect(self, request: ContextRequest, limit: int) -> List[ContextChunk]:
        chunks: List[ContextChunk] = []
        state = _read_json(CONTINUITY_STATE)
        milestones: List[Dict[str, Any]] = []

        con = _open_sqlite(CONTINUITY_DB)
        if con is not None:
            try:
                row = con.execute(
                    """SELECT architect_goal, current_request, status, progress_percent,
                              phase, reboot_count, updated_ts
                       FROM active_session ORDER BY updated_ts DESC LIMIT 1"""
                ).fetchone()
                if row:
                    state = {
                        "architect_goal": row["architect_goal"],
                        "current_request": row["current_request"],
                        "status": row["status"],
                        "progress_percent": row["progress_percent"],
                        "phase": row["phase"],
                        "reboot_count": row["reboot_count"],
                        "updated_ts": row["updated_ts"],
                    }
                for row in con.execute(
                    """SELECT title, status, iso, output_snippet, timestamp
                       FROM milestones ORDER BY id DESC LIMIT ?""",
                    (max(4, min(10, limit)),),
                ).fetchall():
                    milestones.append(dict(row))
            except sqlite3.Error as exc:
                LOG.debug("CaS: error leyendo continuidad: %s", exc)
            finally:
                con.close()

        if state:
            ts = parse_ts(state.get("updated_ts"))
            content = (
                f"• Objetivo Maestro: {state.get('architect_goal', 'n/d')}\n"
                f"• Última Petición: {state.get('current_request', 'n/d')}\n"
                f"• Estado: {state.get('status', 'n/d')} · Avance: {state.get('progress_percent', 0)}% "
                f"· Reinicios sobrevividos: {state.get('reboot_count', 0)}\n"
                f"• Fase en curso: {state.get('phase', 'n/d')}"
            )
            chunks.append(
                ContextChunk(
                    source=self.name,
                    kind="continuity",
                    title="Estado de Continuidad Temporal (blindaje post-reinicio)",
                    content=content,
                    timestamp=ts,
                    trust=self.trust,
                    essential=True,
                    meta={"status": state.get("status", "")},
                )
            )

        if milestones:
            lines = []
            for item in milestones:
                lines.append(
                    f"• [{item.get('iso', '')}] {item.get('title', '')} "
                    f"({item.get('status', '')})"
                )
            chunks.append(
                ContextChunk(
                    source=self.name,
                    kind="milestone",
                    title="Hitos recientes de avance",
                    content="\n".join(lines),
                    timestamp=parse_ts(milestones[0].get("timestamp")),
                    trust=self.trust,
                    meta={"count": len(milestones)},
                )
            )
        return chunks


class VaultSource(ContextSource):
    name = "vault"
    trust = 0.86
    _vault: Any = None
    _vault_lock = threading.Lock()

    def signature(self) -> str:
        return file_signature(VAULT_DB)

    @classmethod
    def _get_vault(cls) -> Any:
        if cls._vault is None:
            with cls._vault_lock:
                if cls._vault is None:
                    from core.deep_memory_vault import get_deep_memory_vault

                    cls._vault = get_deep_memory_vault()
        return cls._vault

    @staticmethod
    def _event_chunk(
        event: Dict[str, Any], kind: str, title: str, trust: float
    ) -> Optional[ContextChunk]:
        content = normalize_text(event.get("content", ""))
        if len(content) < 20:
            return None
        if len(content) > 7000:
            content = content[:7000] + " …"
        return ContextChunk(
            source="vault",
            kind=kind,
            title=title,
            content=content,
            timestamp=parse_ts(event.get("ts") or event.get("iso")),
            trust=trust,
            meta={
                "id": event.get("id"),
                "role": event.get("role", ""),
                "origin": event.get("source", ""),
                "rank": event.get("rank"),
            },
        )

    def collect(self, request: ContextRequest, limit: int) -> List[ContextChunk]:
        vault = self._get_vault()
        query = request.query
        chunks: List[ContextChunk] = []

        # 1. Precedentes recuperados por BM25/FTS5.
        if query:
            try:
                for match in vault.search(query, k=max(4, min(12, limit))):
                    chunk = self._event_chunk(
                        match,
                        "memory_event",
                        f"Precedente RAG · {match.get('role', 'evento')}",
                        self.trust,
                    )
                    if chunk:
                        chunks.append(chunk)
            except Exception as exc:  # aislamiento de fallos
                LOG.debug("CaS: búsqueda en bóveda falló: %s", exc)

        # 2. Hilo inmediato (memoria de trabajo).
        try:
            for event in vault.recent(max(4, min(8, limit // 2))):
                role = str(event.get("role", "evento")).upper()
                chunk = self._event_chunk(
                    event,
                    "memory_event",
                    f"Hilo inmediato · {role}",
                    self.trust * 0.95,
                )
                if chunk:
                    chunks.append(chunk)
        except Exception as exc:
            LOG.debug("CaS: lectura reciente de bóveda falló: %s", exc)

        # 3. Nodos del grafo akáshico.
        try:
            nodes = vault.get_relevant_knowledge_nodes(query, limit=5)
            for node in nodes:
                summary = normalize_text(node.get("summary", ""))
                if not summary:
                    continue
                chunks.append(
                    ContextChunk(
                        source=self.name,
                        kind="knowledge_node",
                        title=f"Grafo akáshico · {node.get('node_type', 'nodo')} · {node.get('name', '')}",
                        content=f"{node.get('name', '')}: {summary}",
                        timestamp=0.0,
                        trust=0.88,
                        meta={"weight": node.get("weight")},
                    )
                )
        except Exception as exc:
            LOG.debug("CaS: nodos akáshicos no disponibles: %s", exc)

        # 4. Épocas consolidadas.
        try:
            for epoch in vault.get_recent_epochs(limit=2):
                summary = normalize_text(epoch.get("condensed_summary", ""))
                takeaways = normalize_text(epoch.get("key_takeaways", ""))
                if not summary:
                    continue
                body = summary
                if takeaways and takeaways not in ("None", "none"):
                    body += f"\nAprendizajes: {takeaways}"
                chunks.append(
                    ContextChunk(
                        source=self.name,
                        kind="epoch",
                        title=f"Época · {epoch.get('topic_title', 'síntesis')}",
                        content=body,
                        timestamp=0.0,
                        trust=0.82,
                        meta={"epoch_id": epoch.get("epoch_id")},
                    )
                )
        except Exception as exc:
            LOG.debug("CaS: épocas no disponibles: %s", exc)

        # 5. Contemplaciones en segundo plano.
        try:
            for thought in vault.get_recent_contemplations(limit=2):
                question = normalize_text(thought.get("question", ""))
                answer = normalize_text(thought.get("answer", ""))
                if not answer:
                    continue
                chunks.append(
                    ContextChunk(
                        source=self.name,
                        kind="contemplation",
                        title="Conocimiento derivado en segundo plano",
                        content=f"Interrogante: {question[:240]}\nSíntesis: {answer[:1400]}",
                        timestamp=parse_ts(thought.get("ts") or thought.get("iso")),
                        trust=0.78,
                        meta={"source": thought.get("source", "")},
                    )
                )
        except Exception as exc:
            LOG.debug("CaS: contemplaciones no disponibles: %s", exc)

        # 6. Historial operativo FTL.
        try:
            for event in vault.get_ftl_history(limit=5):
                chunk = self._event_chunk(
                    event,
                    "ftl",
                    "Operación FTL reciente",
                    self.trust * 0.92,
                )
                if chunk:
                    meta = event.get("meta") or {}
                    if isinstance(meta, dict):
                        chunk.meta.update(
                            {
                                "mode": meta.get("mode", ""),
                                "model": meta.get("model", ""),
                                "files_changed": meta.get("files_changed", []),
                            }
                        )
                    chunks.append(chunk)
        except Exception as exc:
            LOG.debug("CaS: historial FTL no disponible: %s", exc)

        return chunks


class SystemSource(ContextSource):
    name = "system"
    trust = 0.70

    _TRIGGERS = (
        "cpu",
        "memoria",
        "ram",
        "kernel",
        "psi",
        "sistema",
        "telemetria",
        "telemetría",
        "hardware",
        "red",
        "carga",
        "latencia",
        "nucleo",
        "núcleo",
        "proceso",
        "disco",
        "energia",
        "energía",
        "temperatura",
    )

    def signature(self) -> str:
        return f"system:{int(time.time() // 30)}"

    def _should_collect(self, request: ContextRequest) -> bool:
        if request.profile in ("deep", "debug") or request.include_system:
            return True
        text = request.query.lower()
        return any(trigger in text for trigger in self._TRIGGERS)

    def collect(self, request: ContextRequest, limit: int) -> List[ContextChunk]:
        if not self._should_collect(request):
            return []

        load = "n/d"
        try:
            load = " / ".join(f"{value:.2f}" for value in os.getloadavg())
        except OSError:
            pass

        mem_total = mem_available = 0
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) // 1024
        except OSError:
            pass

        psi = []
        for resource in ("cpu", "memory", "io"):
            try:
                raw = Path(f"/proc/pressure/{resource}").read_text(encoding="utf-8")
                some = raw.split("some ")[1].split("avg")[0].strip()
                psi.append(f"{resource} some {some}")
            except (OSError, IndexError):
                continue

        uptime = "n/d"
        try:
            seconds = float(Path("/proc/uptime").read_text().split()[0])
            days, rem = divmod(int(seconds), 86400)
            hours = rem // 3600
            uptime = f"{days}d {hours}h"
        except (OSError, ValueError):
            pass

        lines = [
            f"• Host: {os.uname().nodename} · Hora: {now_iso()} · Uptime: {uptime}",
            f"• CPU load (1/5/15m): {load} · {os.cpu_count() or 'n/d'} hilos lógicos",
        ]
        if mem_total:
            free_pct = 100.0 * mem_available / mem_total
            lines.append(
                f"• Memoria disponible: {mem_available / 1024:.1f} GB de "
                f"{mem_total / 1024:.1f} GB ({free_pct:.1f}% libre)"
            )
        if psi:
            lines.append("• PSI: " + " · ".join(psi))
        lines.append(
            "• Núcleo KAIJU: MLA + SSM + MoE · ventana 32768 tokens · mlock 28 GB"
        )

        return [
            ContextChunk(
                source=self.name,
                kind="system",
                title="Telemetría física del silicio y presión del kernel",
                content="\n".join(lines),
                timestamp=time.time(),
                trust=self.trust,
                meta={"load": load},
            )
        ]


class LatentSource(ContextSource):
    name = "latent"
    trust = 0.90

    def signature(self) -> str:
        engine = self._engine_instance()
        return f"latent:{len(getattr(engine, 'active_latent_states', {}) or {})}"

    @staticmethod
    def _engine_instance() -> Any:
        try:
            from core.tardis_ssm_v27 import SovereignSsmV27Engine

            return SovereignSsmV27Engine._instance
        except Exception:
            try:
                from core.sovereign_neural_engine import SovereignNeuralEngine

                return SovereignNeuralEngine._instance
            except Exception:
                return None

    def collect(self, request: ContextRequest, limit: int) -> List[ContextChunk]:
        engine = self._engine_instance()
        if engine is None:
            return []
        states = getattr(engine, "active_latent_states", None) or {}
        if not states:
            return []
        lines = []
        for session_id, state in list(states.items())[:8]:
            try:
                norm = float(state.norm())
            except Exception:
                norm = 0.0
            lines.append(f"• Sesión {session_id}: norma latente {norm:.3f}")
        return [
            ContextChunk(
                source=self.name,
                kind="latent",
                title="Estado latente SSM en memoria",
                content="\n".join(lines),
                timestamp=time.time(),
                trust=self.trust,
                meta={"sessions": len(states)},
            )
        ]


def default_sources() -> List[ContextSource]:
    return [
        AegisSource(),
        DirectivesSource(),
        ContinuitySource(),
        VaultSource(),
        SystemSource(),
        LatentSource(),
    ]


# ---------------------------------------------------------------------------
# Motor CaS
# ---------------------------------------------------------------------------


class CaSEngine:
    """Orquestador de contexto cognitivo ultradenso para KAIJU."""

    _instance: Optional["CaSEngine"] = None
    _singleton_lock = threading.Lock()

    def __init__(
        self,
        sources: Optional[Sequence[ContextSource]] = None,
        state_file: Optional[Path] = None,
        cache_ttl: float = 45.0,
        cache_size: int = 96,
    ) -> None:
        self.sources: List[ContextSource] = list(sources) if sources is not None else default_sources()
        self.compressor = SyntropicCompressor()
        self.state_file = Path(state_file) if state_file else STATE_FILE
        self.cache_ttl = max(1.0, float(cache_ttl))
        self.cache_size = max(8, int(cache_size))

        self._cache: "OrderedDict[str, Tuple[float, ContextBundle]]" = OrderedDict()
        self._cache_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._stats = self._load_stats()

    # -- Singleton ---------------------------------------------------------
    @classmethod
    def get_instance(cls) -> "CaSEngine":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # -- Telemetría persistente -------------------------------------------
    def _load_stats(self) -> Dict[str, Any]:
        base = {
            "version": VERSION,
            "builds": 0,
            "cache_hits": 0,
            "errors": 0,
            "tokens_served": 0,
            "compression_ratio_sum": 0.0,
            "source_calls": {},
            "source_errors": {},
            "last_build_iso": "",
            "last_latency_ms": 0.0,
            "started_ts": time.time(),
            "started_iso": now_iso(),
        }
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in (
                    "builds",
                    "cache_hits",
                    "errors",
                    "tokens_served",
                    "compression_ratio_sum",
                    "source_calls",
                    "source_errors",
                    "last_build_iso",
                    "last_latency_ms",
                ):
                    if key in data:
                        base[key] = data[key]
        except (OSError, ValueError):
            pass
        base["started_ts"] = time.time()
        base["started_iso"] = now_iso()
        return base

    def _save_stats(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._stats, ensure_ascii=False, indent=2)
            tmp = self.state_file.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self.state_file)
        except OSError as exc:
            LOG.debug("CaS: no se pudo persistir telemetría: %s", exc)

    def telemetry(self) -> Dict[str, Any]:
        with self._stats_lock:
            stats = copy(self._stats)
            builds = max(1, int(stats.get("builds", 0)))
            stats["avg_tokens_per_build"] = round(stats.get("tokens_served", 0) / builds, 1)
            stats["avg_compression_ratio"] = round(
                stats.get("compression_ratio_sum", 0.0) / builds, 3
            )
        stats["cache_entries"] = len(self._cache)
        stats["sources"] = [source.name for source in self.sources]
        stats["aegis"] = self._aegis_snapshot()
        return stats

    def _aegis_snapshot(self) -> Dict[str, Any]:
        state = _read_json(RAILS_STATE_FILE)
        aegis_state = state.get("aegis", {}) if isinstance(state, dict) else {}
        matrix = list(CANONICAL_AEGIS)
        for anchor in aegis_state.get("anchor_matrix", []) or []:
            anchor = str(anchor).strip()
            if anchor and anchor not in matrix:
                matrix.append(anchor)
        return {
            "status": str(aegis_state.get("status", "PROTECTED_INVULNERABLE")),
            "last_verification": str(aegis_state.get("last_verification", "n/d")),
            "anchors": matrix,
            "verified": all(anchor in matrix for anchor in CANONICAL_AEGIS),
        }

    def verify_aegis(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        try:
            from core.kaiju_safety_rails import get_kaiju_safety_rails

            result = get_kaiju_safety_rails().verify_aegis_anchors()
        except Exception as exc:
            LOG.warning("CaS: verificación AEGIS vía rails falló: %s", exc)
        snapshot = self._aegis_snapshot()
        return {
            "ok": bool(result.get("ok", True)) and snapshot["verified"],
            "rails": result,
            "snapshot": snapshot,
            "canonical": CANONICAL_AEGIS,
            "checked_iso": now_iso(),
        }

    # -- Caché -------------------------------------------------------------
    def _source_signature(self) -> str:
        parts = []
        for source in self.sources:
            try:
                parts.append(f"{source.name}:{source.signature()}")
            except Exception:
                parts.append(f"{source.name}:error")
        return "|".join(parts)

    def _cache_key(self, request: ContextRequest) -> str:
        payload = json.dumps(
            {
                **asdict(request),
                "sources": self._source_signature(),
                "version": VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[ContextBundle]:
        now = time.time()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            created, bundle = entry
            if now - created > self.cache_ttl:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return bundle

    def _cache_put(self, key: str, bundle: ContextBundle) -> None:
        with self._cache_lock:
            self._cache[key] = (time.time(), bundle)
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

    # -- Ranking -----------------------------------------------------------
    def _score_chunks(self, chunks: List[ContextChunk], query: str) -> None:
        query_terms = set(tokenize(query))
        corpus_tokens: List[List[str]] = []
        doc_freq: Counter = Counter()
        for chunk in chunks:
            toks = tokenize(f"{chunk.title} {chunk.content}")
            corpus_tokens.append(toks)
            doc_freq.update(set(toks))

        total_docs = max(1, len(chunks))
        avg_len = sum(len(toks) for toks in corpus_tokens) / total_docs or 1.0
        k1, b = 1.5, 0.75
        lexical: List[float] = []

        for chunk, toks in zip(chunks, corpus_tokens):
            score = 0.0
            if query_terms and toks:
                tf = Counter(toks)
                dl = len(toks)
                for term in query_terms:
                    freq = tf.get(term, 0)
                    if not freq:
                        continue
                    idf = math.log(1.0 + (total_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
                    score += idf * (freq * (k1 + 1.0)) / (
                        freq + k1 * (1.0 - b + b * dl / avg_len)
                    )
            lexical.append(score)

        max_lex = max(lexical) if lexical else 0.0
        now = time.time()
        for chunk, lex in zip(chunks, lexical):
            lex_norm = (lex / max_lex) if max_lex > 0 else 0.0
            tau = SOURCE_TAU_DAYS.get(chunk.source, 30.0)
            age_days = max(0.0, (now - chunk.timestamp) / 86400.0) if chunk.timestamp else 30.0
            recency = math.exp(-age_days / max(0.01, tau))
            score = (
                0.58 * lex_norm
                + 0.18 * recency
                + 0.14 * chunk.trust
                + 0.10 * KIND_BONUS.get(chunk.kind, 0.0)
            )
            if query and len(query) >= 4 and query.lower() in chunk.content.lower():
                score += 0.35
            if chunk.essential:
                score += 2.0
            if chunk.pinned:
                score += 10.0
            chunk.score = round(score, 6)

    # -- Selección con presupuesto ----------------------------------------
    def _select_chunks(self, chunks: List[ContextChunk], request: ContextRequest) -> List[ContextChunk]:
        # Deduplicación exacta previa.
        unique: List[ContextChunk] = []
        seen_digests: set = set()
        for chunk in chunks:
            if len(chunk.content) < 12:
                continue
            if chunk.digest in seen_digests:
                continue
            seen_digests.add(chunk.digest)
            unique.append(chunk)

        ordered = sorted(
            unique,
            key=lambda item: (item.pinned, item.essential, item.score),
            reverse=True,
        )

        selected: List[ContextChunk] = []
        selected_hashes: List[int] = []
        used = 0
        source_used: Counter = Counter()
        skipped: List[ContextChunk] = []
        budget = request.budget_tokens
        reserve = max(24, int(budget * 0.04))  # margen para cabeceras

        def try_accept(chunk: ContextChunk, enforce_share: bool) -> bool:
            nonlocal used
            remaining = budget - reserve - used
            if remaining <= 40:
                return False
            if chunk.pinned:
                text, info = self.compressor.compress(
                    chunk.content,
                    request.query,
                    target_ratio=1.0,
                    max_tokens=remaining,
                )
            elif chunk.essential and chunk.original_tokens <= 320:
                # Los estados esenciales y breves (continuidad, AEGIS) se sirven íntegros.
                text, info = self.compressor.compress(
                    chunk.content,
                    request.query,
                    target_ratio=1.0,
                    max_tokens=remaining,
                )
            else:
                target = request.compression_ratio
                max_tokens = max(90, min(int(chunk.original_tokens * target), remaining))
                text, info = self.compressor.compress(
                    chunk.content, request.query, target_ratio=target, max_tokens=max_tokens
                )
            if not text or len(text) < 8:
                return False
            tokens = estimate_tokens(text)
            if tokens > remaining:
                text = truncate_to_tokens(text, max(32, remaining - 8))
                tokens = estimate_tokens(text)
            if enforce_share and not (chunk.pinned or chunk.essential):
                share = SOURCE_SHARE.get(chunk.source, request.max_source_share)
                if source_used[chunk.source] + tokens > int(budget * share):
                    return False
            fingerprint = simhash64(text)
            if not chunk.pinned and any(
                hamming64(fingerprint, other) <= 3 for other in selected_hashes
            ):
                return False
            chunk.content = text
            chunk.refresh()
            chunk.compressed = info.get("ratio", 1.0) < 0.999
            selected.append(chunk)
            selected_hashes.append(fingerprint)
            source_used[chunk.source] += chunk.tokens
            used += chunk.tokens
            return True

        for chunk in ordered:
            if len(selected) >= request.max_chunks:
                break
            if not try_accept(chunk, enforce_share=True):
                skipped.append(chunk)

        # Segunda pasada: rellenar presupuesto sin cuotas de fuente.
        if used < budget * 0.90 and len(selected) < request.max_chunks:
            for chunk in sorted(skipped, key=lambda item: item.score, reverse=True):
                if len(selected) >= request.max_chunks:
                    break
                if used >= budget - reserve:
                    break
                try_accept(chunk, enforce_share=False)

        selected.sort(key=lambda item: (item.pinned, item.essential, item.score), reverse=True)
        return selected

    # -- Ensamblado --------------------------------------------------------
    def _assemble(
        self,
        selected: List[ContextChunk],
        request: ContextRequest,
        aegis: Dict[str, Any],
        source_report: List[Dict[str, Any]],
        latency_ms: float,
        cache_hit: bool,
    ) -> ContextBundle:
        grouped: "OrderedDict[str, List[ContextChunk]]" = OrderedDict()
        for chunk in selected:
            grouped.setdefault(chunk.section, []).append(chunk)

        used_tokens = sum(chunk.tokens for chunk in selected)
        original_tokens = sum(chunk.original_tokens for chunk in selected)
        ratio = round(used_tokens / max(1, original_tokens), 3)

        lines = [
            f"=== [CaS · CONTEXTO COGNITIVO ULTRADENSO · {SYSTEM_NAME}] ===",
            (
                f"• Generado: {now_iso()} · Perfil: {request.profile} · "
                f"Presupuesto: {request.budget_tokens} tok · Usado: {used_tokens} tok · "
                f"Compresión: {ratio:.1%} · AEGIS: {aegis.get('status', 'n/d')}"
            ),
            "",
        ]

        citations = 0
        public_chunks: List[Dict[str, Any]] = []
        for section in SECTION_ORDER:
            section_chunks = grouped.get(section)
            if not section_chunks:
                continue
            lines.append(f"--- [{SECTION_LABELS[section]}] ---")
            for chunk in section_chunks:
                citations += 1
                chunk.citation = f"S{citations}"
                header = f"[{chunk.citation}] {chunk.title}"
                if chunk.timestamp:
                    header += f" · {now_iso(chunk.timestamp)}"
                lines.append(header)
                lines.append(chunk.content)
                lines.append("")
                public_chunks.append(chunk.public())

        lines.append(
            "=== [FIN DEL CONTEXTO · PROCEDENCIA VERIFICABLE EN 'chunks' · "
            "CACHE: " + ("HIT" if cache_hit else "MISS") + "] ==="
        )
        text = "\n".join(lines).strip()

        # Garantía dura: el texto servido nunca excede el presupuesto.
        if estimate_tokens(text) > request.budget_tokens:
            text = truncate_to_tokens(text, request.budget_tokens)

        missing = [anchor for anchor in CANONICAL_AEGIS if anchor not in text]
        aegis = dict(aegis)
        aegis["ok"] = not missing
        aegis["missing_in_bundle"] = missing
        aegis["bundle_verified_iso"] = now_iso()

        return ContextBundle(
            ok=bool(text) and not missing,
            bundle_id=hashlib.sha256(
                f"{request.query}|{time.time_ns()}".encode("utf-8")
            ).hexdigest()[:16],
            query=request.query,
            profile=request.profile,
            context_text=text,
            chunks=public_chunks if request.include_provenance else [],
            used_tokens=used_tokens,
            budget_tokens=request.budget_tokens,
            compression_ratio=ratio,
            latency_ms=round(latency_ms, 2),
            cache_hit=cache_hit,
            aegis=aegis,
            source_report=source_report,
            created_iso=now_iso(),
        )

    # -- API principal -----------------------------------------------------
    def build_context(
        self,
        query: str = "",
        *,
        request: Optional[ContextRequest] = None,
        session_id: str = "",
        profile: str = "interactive",
        budget_tokens: Optional[int] = None,
        max_chunks: Optional[int] = None,
        compression_ratio: Optional[float] = None,
        include_system: Optional[bool] = None,
    ) -> ContextBundle:
        started = time.perf_counter()
        if request is None:
            preset = PROFILES.get(profile, PROFILES["interactive"])
            request = ContextRequest(
                query=query,
                session_id=session_id,
                profile=profile if profile in PROFILES else "interactive",
                budget_tokens=int(budget_tokens or preset["budget_tokens"]),
                max_chunks=int(max_chunks or preset["max_chunks"]),
                compression_ratio=float(
                    compression_ratio
                    if compression_ratio is not None
                    else preset["compression_ratio"]
                ),
                include_system=(
                    include_system if include_system is not None else preset["include_system"]
                ),
            )
        else:
            if budget_tokens is not None:
                request.budget_tokens = max(768, min(64000, int(budget_tokens)))
            if max_chunks is not None:
                request.max_chunks = max(4, min(128, int(max_chunks)))
            if compression_ratio is not None:
                request.compression_ratio = max(0.2, min(1.0, float(compression_ratio)))
            if include_system is not None:
                request.include_system = bool(include_system)

        cache_key = self._cache_key(request)
        cached = self._cache_get(cache_key)
        if cached is not None:
            with self._stats_lock:
                self._stats["cache_hits"] = int(self._stats.get("cache_hits", 0)) + 1
            bundle = copy(cached)
            bundle.cache_hit = True
            bundle.latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            return bundle

        chunks: List[ContextChunk] = []
        reports: List[Dict[str, Any]] = []

        def collect_from(source: ContextSource) -> Tuple[ContextSource, List[ContextChunk], str, float]:
            source_started = time.perf_counter()
            error = ""
            output: List[ContextChunk] = []
            try:
                output = list(source.collect(request, limit=request.max_chunks) or [])
            except Exception as exc:  # aislamiento total
                error = f"{type(exc).__name__}: {exc}"
                LOG.warning("CaS: fuente %s falló: %s", source.name, exc)
            return source, output, error, (time.perf_counter() - source_started) * 1000.0

        workers = max(1, min(len(self.sources), 6))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cas-src") as pool:
            futures = [pool.submit(collect_from, source) for source in self.sources]
            for future in as_completed(futures):
                source, output, error, elapsed_ms = future.result()
                chunks.extend(output)
                reports.append(
                    {
                        "name": source.name,
                        "ok": not error,
                        "chunks": len(output),
                        "latency_ms": round(elapsed_ms, 2),
                        "error": error,
                    }
                )
                with self._stats_lock:
                    calls = self._stats.setdefault("source_calls", {})
                    calls[source.name] = int(calls.get(source.name, 0)) + 1
                    if error:
                        errors = self._stats.setdefault("source_errors", {})
                        errors[source.name] = int(errors.get(source.name, 0)) + 1

        # AEGIS es inviolable: si la fuente falló, se inyecta la matriz canónica.
        if not any(chunk.kind == "aegis" for chunk in chunks):
            chunks.extend(AegisSource().collect(request, limit=1))

        self._score_chunks(chunks, request.query)
        selected = self._select_chunks(chunks, request)

        if not selected:
            selected = [
                ContextChunk(
                    source="aegis",
                    kind="aegis",
                    title="AEGIS · Matriz canónica de emergencia",
                    content="\n".join(f"• {anchor}" for anchor in CANONICAL_AEGIS),
                    timestamp=time.time(),
                    trust=1.0,
                    pinned=True,
                    essential=True,
                )
            ]

        latency_ms = (time.perf_counter() - started) * 1000.0
        bundle = self._assemble(
            selected,
            request,
            self._aegis_snapshot(),
            sorted(reports, key=lambda item: item["name"]),
            latency_ms,
            cache_hit=False,
        )

        with self._stats_lock:
            self._stats["builds"] = int(self._stats.get("builds", 0)) + 1
            self._stats["tokens_served"] = int(self._stats.get("tokens_served", 0)) + bundle.used_tokens
            self._stats["compression_ratio_sum"] = float(
                self._stats.get("compression_ratio_sum", 0.0)
            ) + bundle.compression_ratio
            self._stats["last_build_iso"] = bundle.created_iso
            self._stats["last_latency_ms"] = bundle.latency_ms
            if not bundle.ok:
                self._stats["errors"] = int(self._stats.get("errors", 0)) + 1
            self._save_stats()

        self._cache_put(cache_key, bundle)
        return bundle

    # -- Utilidades públicas ----------------------------------------------
    def compress_text(
        self, text: str, query: str = "", ratio: float = 0.55, max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        compact, info = self.compressor.compress(
            text, query=query, target_ratio=max(0.2, min(1.0, ratio)), max_tokens=max_tokens
        )
        return {"ok": bool(compact), "compressed_text": compact, **info}

    def sources_status(self) -> List[Dict[str, Any]]:
        output = []
        for source in self.sources:
            try:
                signature = source.signature()
                ok = True
                error = ""
            except Exception as exc:
                signature = ""
                ok = False
                error = str(exc)
            output.append(
                {
                    "name": source.name,
                    "trust": source.trust,
                    "ok": ok,
                    "signature": signature,
                    "error": error,
                }
            )
        return output


def get_cas() -> CaSEngine:
    return CaSEngine.get_instance()


def build_context_text(query: str = "", **kwargs: Any) -> str:
    """Atajo para inyección directa en prompts de cualquier subsistema."""
    return get_cas().build_context(query, **kwargs).context_text


# ---------------------------------------------------------------------------
# Servidor HTTP soberano (stdlib, sin dependencias)
# ---------------------------------------------------------------------------


class CaSRequestHandler(BaseHTTPRequestHandler):
    server_version = f"CaS/{VERSION}"
    protocol_version = "HTTP/1.1"
    engine: CaSEngine
    token: Optional[str] = None

    # Silenciar el log por petición; el servicio registra en journal.
    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.debug("CaS HTTP: " + fmt, *args)

    def _authorized(self) -> bool:
        if not self.token:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {self.token}"

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _error(self, status_code: int, message: str) -> None:
        self._send_json(status_code, {"ok": False, "error": message, "version": VERSION})

    def _send_html(self, status_code: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/health":
            snapshot = self.engine._aegis_snapshot()
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "CaS · Cognitive & Context as a Service",
                    "version": VERSION,
                    "engine": SYSTEM_NAME,
                    "aegis": snapshot,
                    "uptime_s": round(time.time() - self.engine._stats.get("started_ts", time.time()), 1),
                },
            )
            return

        if path in ("/", "/v1", "/v1/"):
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "CaS",
                    "version": VERSION,
                    "dashboard": "/dashboard",
                    "endpoints": [
                        "GET /health",
                        "GET /v1/sources",
                        "GET /v1/telemetry",
                        "POST /v1/context",
                        "POST /v1/compress",
                        "POST /v1/aegis/verify",
                    ],
                },
            )
            return

        if path in ("/dashboard", "/ui"):
            try:
                html = DASHBOARD_FILE.read_text(encoding="utf-8")
            except OSError:
                html = (
                    "<!doctype html><html lang='es'><meta charset='utf-8'>"
                    "<title>CaS</title><body style='background:#05070f;color:#dbeafe;"
                    "font-family:system-ui;padding:40px'><h1>CaS</h1>"
                    "<p>Dashboard no disponible; use la API en <code>/v1/context</code>.</p>"
                    "</body></html>"
                )
            self._send_html(200, html)
            return

        if not self._authorized():
            self._error(401, "token requerido")
            return

        if path == "/v1/telemetry":
            self._send_json(200, {"ok": True, **self.engine.telemetry()})
            return

        if path == "/v1/sources":
            self._send_json(200, {"ok": True, "sources": self.engine.sources_status()})
            return

        self._error(404, f"ruta no encontrada: {path}")

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._error(401, "token requerido")
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error(400, "Content-Length inválido")
            return
        if length > 1_048_576:
            self._error(413, "cuerpo demasiado grande (máx. 1 MB)")
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(body, dict):
                raise ValueError("se esperaba un objeto JSON")
        except (ValueError, UnicodeDecodeError) as exc:
            self._error(400, f"JSON inválido: {exc}")
            return

        if path == "/v1/context":
            query = str(body.get("query") or body.get("prompt") or "")
            try:
                bundle = self.engine.build_context(
                    query,
                    session_id=str(body.get("session_id") or ""),
                    profile=str(body.get("profile") or "interactive"),
                    budget_tokens=body.get("budget_tokens"),
                    max_chunks=body.get("max_chunks"),
                    compression_ratio=body.get("compression_ratio"),
                    include_system=body.get("include_system"),
                )
                self._send_json(200, bundle.to_dict())
            except Exception as exc:
                LOG.exception("CaS: error construyendo contexto")
                self._error(500, f"{type(exc).__name__}: {exc}")
            return

        if path == "/v1/compress":
            text = str(body.get("text") or "")
            if not text:
                self._error(400, "campo 'text' requerido")
                return
            try:
                result = self.engine.compress_text(
                    text,
                    query=str(body.get("query") or ""),
                    ratio=float(body.get("ratio", 0.55)),
                    max_tokens=body.get("max_tokens"),
                )
                self._send_json(200, result)
            except Exception as exc:
                self._error(500, f"{type(exc).__name__}: {exc}")
            return

        if path == "/v1/aegis/verify":
            try:
                self._send_json(200, self.engine.verify_aegis())
            except Exception as exc:
                self._error(500, f"{type(exc).__name__}: {exc}")
            return

        self._error(404, f"ruta no encontrada: {path}")


def make_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    engine: Optional[CaSEngine] = None,
    token: Optional[str] = None,
) -> ThreadingHTTPServer:
    bound_engine = engine or get_cas()
    handler = type(
        "BoundCaSRequestHandler",
        (CaSRequestHandler,),
        {"engine": bound_engine, "token": token},
    )
    httpd = ThreadingHTTPServer((host, int(port)), handler)
    httpd.daemon_threads = True
    return httpd


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: Optional[str] = None,
) -> None:
    token = token or _load_token()
    engine = get_cas()
    httpd = make_server(host, port, engine, token)
    LOG.info(
        "CaS escuchando en http://%s:%s · token=%s · fuentes=%s",
        host,
        port,
        "sí" if token else "no",
        ",".join(source.name for source in engine.sources),
    )

    def _shutdown(signum: int, frame: Any) -> None:
        LOG.info("CaS: señal %s recibida, cerrando servicio", signum)
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        LOG.info("CaS: servicio detenido")


def _load_token(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit
    env = os.environ.get("CAS_TOKEN") or os.environ.get("TARDIS_CAS_TOKEN")
    if env:
        return env.strip()
    try:
        value = TOKEN_FILE.read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_context(args: argparse.Namespace) -> int:
    bundle = get_cas().build_context(
        args.query,
        session_id=args.session,
        profile=args.profile,
        budget_tokens=args.budget,
        max_chunks=args.max_chunks,
        compression_ratio=args.ratio,
    )
    if args.json:
        print(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(bundle.context_text)
    return 0 if bundle.ok else 1


def _cmd_compress(args: argparse.Namespace) -> int:
    source = args.text
    if args.file:
        source = Path(args.file).expanduser().read_text(encoding="utf-8")
    result = get_cas().compress_text(
        source, query=args.query, ratio=args.ratio, max_tokens=args.max_tokens
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["compressed_text"])
    return 0 if result["ok"] else 1


def _cmd_serve(args: argparse.Namespace) -> int:
    serve(host=args.host, port=args.port, token=args.token)
    return 0


def _cmd_telemetry(args: argparse.Namespace) -> int:
    print(json.dumps(get_cas().telemetry(), ensure_ascii=False, indent=2))
    return 0


def _cmd_sources(args: argparse.Namespace) -> int:
    print(json.dumps(get_cas().sources_status(), ensure_ascii=False, indent=2))
    return 0


def _cmd_aegis(args: argparse.Namespace) -> int:
    print(json.dumps(get_cas().verify_aegis(), ensure_ascii=False, indent=2))
    return 0


def _cmd_selftest(args: argparse.Namespace) -> int:
    engine = get_cas()
    query = args.query or "estado de continuidad, memoria akáshica y telemetría del núcleo"
    started = time.perf_counter()
    bundle = engine.build_context(query, profile="deep", budget_tokens=6000)
    checks = {
        "context_non_empty": len(bundle.context_text) > 200,
        "aegis_complete": all(anchor in bundle.context_text for anchor in CANONICAL_AEGIS),
        "bundle_ok": bundle.ok,
        "within_budget": bundle.used_tokens <= bundle.budget_tokens,
        "has_citations": "[S1]" in bundle.context_text,
        "sources_ok": any(item["ok"] for item in bundle.source_report),
    }
    result = {
        "ok": all(checks.values()),
        "checks": checks,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "used_tokens": bundle.used_tokens,
        "budget_tokens": bundle.budget_tokens,
        "compression_ratio": bundle.compression_ratio,
        "chunks": len(bundle.chunks),
        "aegis": bundle.aegis,
        "sources": bundle.source_report,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cas-kaiju",
        description="CaS · Cognitive & Context as a Service para TARDIS-NEURAL-SPACE-KAIJU",
    )
    parser.add_argument("--version", action="version", version=f"CaS {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ctx = subparsers.add_parser("context", help="Construye un bundle de contexto cognitivo")
    ctx.add_argument("query", nargs="?", default="")
    ctx.add_argument("--profile", default="interactive", choices=sorted(PROFILES))
    ctx.add_argument("--budget", type=int, default=None)
    ctx.add_argument("--max-chunks", type=int, default=None)
    ctx.add_argument("--ratio", type=float, default=None)
    ctx.add_argument("--session", default="")
    ctx.add_argument("--json", action="store_true")
    ctx.set_defaults(func=_cmd_context)

    comp = subparsers.add_parser("compress", help="Comprime texto con densidad semántica")
    comp.add_argument("text", nargs="?", default="")
    comp.add_argument("--file", default="")
    comp.add_argument("--query", default="")
    comp.add_argument("--ratio", type=float, default=0.55)
    comp.add_argument("--max-tokens", type=int, default=None)
    comp.add_argument("--json", action="store_true")
    comp.set_defaults(func=_cmd_compress)

    srv = subparsers.add_parser("serve", help="Levanta el servicio HTTP local")
    srv.add_argument("--host", default=DEFAULT_HOST)
    srv.add_argument("--port", type=int, default=DEFAULT_PORT)
    srv.add_argument("--token", default=None)
    srv.set_defaults(func=_cmd_serve)

    tel = subparsers.add_parser("telemetry", help="Muestra telemetría acumulada")
    tel.set_defaults(func=_cmd_telemetry)

    src = subparsers.add_parser("sources", help="Estado de las fuentes de contexto")
    src.set_defaults(func=_cmd_sources)

    aeg = subparsers.add_parser("aegis", help="Verifica la Constante AEGIS")
    aeg.set_defaults(func=_cmd_aegis)

    test = subparsers.add_parser("selftest", help="Prueba de humo integral")
    test.add_argument("--query", default="")
    test.set_defaults(func=_cmd_selftest)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(
        level=os.environ.get("CAS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
