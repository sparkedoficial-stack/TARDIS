#!/usr/bin/env python3
"""
core/tardis_semantic_cache.py - Semantic Inference Cache & Prompt Router (EmbedBrain + SQLite WAL)
==================================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU

Sistema alterno soberano diseñado para eliminar re-cómputo redundante de inferencia LLM
en agentes de fondo, consultas repetitivas y clasificación sobre TemporalBrain / Ollama:

  1. Arquitectura de caché en 2 niveles (L1 + L2) con persistencia SQLite WAL:
     - L1 Exact Hash (<0.5 ms, 0 llamadas a EmbedBrain): coincidencia exacta normalizada
       por `(namespace, model_family, system_hash, context_hash, prompt_hash)`.
     - L2 Semantic Vector (~5-15 ms vía `/tmp/embed_brain.sock`, multilingual-e5-small 384d):
       similitud coseno >= 0.94 sobre matriz NumPy en memoria sincronizada entre procesos.
  2. Guardas de seguridad anti-obsolescencia:
     - Nunca cachea prompts volátiles/tiempo real (hora, telemetría viva, noticias de hoy,
       precios en vivo, marcador `[NO_CACHE]`), ni respuestas de error/timeout, ni temperaturas
       creativas altas (> 0.75 por defecto).
     - En conversaciones multi-turno incorpora `context_hash` para evitar colisiones entre
       seguimientos cortos ("explica más", "continúa") de hilos distintos.
  3. TTL adaptativo gobernado por Ring 0 (`TardisResourceGovernor`) y frecuencia de aciertos:
     - Extiende TTL bajo presión `YELLOW`/`ORANGE`/`RED` y refuerza entradas calientes.
     - Podado automático de entradas expiradas y evicción LRU acotada (`max_entries=4000`).
  4. Prompt Router consciente de silicio (`route_prompt()`):
     - Decide en <15 ms entre `semantic_cache`, `defer` (bajo llamada Telegram o `RED`),
       `temporal_brain_uds` (Tier 0 CUDA), `ollama_gpu_11435` (VLM/voz) o respaldo frío.
  5. Telemetría durable de ahorro real de tokens, ciclos CPU y latencia P50/media.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import httpx
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_CACHE_DB = DATA_DIR / "semantic_cache.db"
DEFAULT_EMBED_SOCKET = os.environ.get("TARDIS_EMBED_SOCKET", "/tmp/embed_brain.sock")
EMBED_DIM = 384
E5_QUERY_PREFIX = "query: "
MAX_EMBED_CHARS = 1200  # ~300-340 tokens, seguro bajo --ctx-size 512 de embed-e5-small

DEFAULT_SIMILARITY_THRESHOLD = float(os.environ.get("TARDIS_SEMANTIC_CACHE_THRESHOLD", "0.94"))
RED_BACKGROUND_SIMILARITY_THRESHOLD = 0.92
DEFAULT_MAX_ENTRIES = int(os.environ.get("TARDIS_SEMANTIC_CACHE_MAX_ENTRIES", "4000"))
DEFAULT_MAX_TEMP = float(os.environ.get("TARDIS_SEMANTIC_CACHE_MAX_TEMP", "0.75"))
MAX_ADAPTIVE_TTL_S = 14400.0  # 4 horas máximo

NAMESPACE_BASE_TTL_S: Dict[str, float] = {
    "background": 1800.0,
    "autonomy": 1800.0,
    "research": 2400.0,
    "knowledge": 3600.0,
    "classification": 3600.0,
    "summary": 2700.0,
    "default": 1200.0,
    "interactive": 600.0,
    "chat": 600.0,
    "telemetry": 120.0,
    "ephemeral": 120.0,
}

PRESSURE_TTL_MULT: Dict[str, float] = {
    "GREEN": 1.0,
    "YELLOW": 1.25,
    "ORANGE": 1.6,
    "RED": 2.0,
}

_VOLATILE_PATTERNS = re.compile(
    r"(?:\[no_cache\]|\bno_cache\b|"
    r"\b(?:ahora\s+mismo|en\s+este\s+momento|en\s+este\s+instante|tiempo\s+real|"
    r"qu[eé]\s+hora\s+es|hora\s+actual|fecha\s+actual|temperatura\s+actual|"
    r"clima\s+actual|noticias\s+de\s+hoy|precio\s+actual|cotizaci[oó]n\s+actual|"
    r"estado\s+actual\s+del\s+sistema|telemetr[ií]a\s+en\s+vivo|"
    r"right\s+now|current\s+time|live\s+telemetry|today'?s\s+news|current\s+price)\b)",
    re.IGNORECASE,
)

_ERROR_REPLY_PREFIXES = (
    "[error",
    "[⚠️",
    "error del motor",
    "error en socket",
    "traceback (most recent call last)",
)

logger = logging.getLogger("TARDIS.SemanticCache")


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _is_pytest_isolated() -> bool:
    """Evita que pruebas unitarias contaminen data/semantic_cache.db de producción."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and str(
        os.environ.get("TARDIS_SEMANTIC_CACHE_LIVE_TEST", "0")
    ).strip().lower() not in ("1", "true", "yes")


def is_cache_enabled() -> bool:
    return str(os.environ.get("TARDIS_SEMANTIC_CACHE_ENABLED", "1")).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _normalize_text(text: str) -> str:
    """Normaliza espacios y saltos de línea para estabilizar hashing L1 y embeddings L2."""
    return re.sub(r"\s+", " ", (text or "").strip())


def _canonical_model_family(model: Optional[str]) -> str:
    raw = (model or "default").strip().lower()
    if not raw:
        return "default"
    if "kaiju" in raw or "tardis-neural" in raw or "temporal" in raw:
        return "tardis-kaiju"
    return raw.split(":")[0].strip() or "default"


def _sha256_short(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()[:32]


def _estimate_tokens(text: str) -> int:
    clean = (text or "").strip()
    if not clean:
        return 0
    return max(1, int(round(len(clean) / 3.8)))


def _is_volatile_prompt(text: str) -> bool:
    if not text:
        return True
    if _VOLATILE_PATTERNS.search(text):
        return True
    # Detectar marcas de tiempo exactas con segundos (típicas de snapshots puntuales efímeros)
    if re.search(r"\b20\d{2}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\b", text):
        return True
    return False


def _is_error_reply(reply: str) -> bool:
    low = (reply or "").strip().lower()
    if len(low) < 4:
        return True
    return any(low.startswith(pref) for pref in _ERROR_REPLY_PREFIXES)


def _extract_prompt_parts(
    prompt_or_messages: Union[str, Sequence[Dict[str, Any]]],
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extrae de manera determinista:
      - `query_text`: último mensaje de usuario (texto que se vectoriza en EmbedBrain).
      - `system_text`: prompt de sistema concatenado.
      - `context_text`: historial previo de conversación (para aislar seguimientos multi-turno).
      - `has_images`: si algún mensaje transporta contenido multimodal/imágenes.
    """
    if isinstance(prompt_or_messages, str):
        q = _normalize_text(prompt_or_messages)
        s = _normalize_text(system_prompt or "")
        return {
            "query_text": q,
            "system_text": s,
            "context_text": "",
            "user_turns": 1 if q else 0,
            "has_images": False,
        }

    sys_parts: List[str] = []
    if system_prompt:
        sys_parts.append(_normalize_text(system_prompt))
    convo_turns: List[Tuple[str, str]] = []
    has_images = False

    for msg in prompt_or_messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").strip().lower()
        if msg.get("images"):
            has_images = True
        content = msg.get("content")
        if isinstance(content, list):
            txt_bits = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") in ("image", "image_url"):
                        has_images = True
                    elif item.get("text"):
                        txt_bits.append(str(item["text"]))
                elif isinstance(item, str):
                    txt_bits.append(item)
            text = _normalize_text(" ".join(txt_bits))
        else:
            text = _normalize_text(str(content or ""))

        if role == "system":
            if text:
                sys_parts.append(text)
        elif text:
            convo_turns.append((role, text))

    # Último turno de usuario como consulta principal
    last_user_idx = -1
    for i in range(len(convo_turns) - 1, -1, -1):
        if convo_turns[i][0] == "user":
            last_user_idx = i
            break

    if last_user_idx >= 0:
        query_text = convo_turns[last_user_idx][1]
        prior = convo_turns[:last_user_idx]
    elif convo_turns:
        query_text = convo_turns[-1][1]
        prior = convo_turns[:-1]
    else:
        query_text = ""
        prior = []

    context_text = " | ".join(f"{r}:{t[:240]}" for r, t in prior[-4:])
    user_turns = sum(1 for r, _ in convo_turns if r == "user")
    return {
        "query_text": query_text,
        "system_text": "\n".join(p for p in sys_parts if p),
        "context_text": context_text,
        "user_turns": user_turns,
        "has_images": has_images,
    }


def _read_governor_state_fast() -> Dict[str, Any]:
    """Lee instantánea Ring 0 del ResourceGovernor (<0.1 ms en tmpfs) con degradación segura."""
    try:
        from core.tardis_resource_governor import get_resource_governor

        snap = get_resource_governor().read_fast_snapshot(max_age_s=60.0)
        if isinstance(snap, dict) and snap.get("ok"):
            return snap
    except Exception:
        pass
    return {
        "ok": False,
        "level": "GREEN",
        "call_priority_active": False,
        "cpu": {"psi": {"some_avg60": 0.0}, "temp_c": 0.0, "load1": 0.0},
        "gpu": {"available": False, "temp_c": 0.0, "vram_used_pct": 0.0},
    }


class TardisSemanticCache:
    """
    Caché Semántica Soberana (L1 hash exacto + L2 coseno EmbedBrain 384d) sobre SQLite WAL.
    Segura para concurrencia multi-hilo y multi-proceso.
    """

    _instance: Optional["TardisSemanticCache"] = None
    _test_instance: Optional["TardisSemanticCache"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(
        cls,
        db_path: Optional[Path] = None,
        embed_socket: Optional[str] = None,
    ) -> "TardisSemanticCache":
        if db_path is not None or embed_socket is not None:
            return cls(
                db_path=db_path or DEFAULT_CACHE_DB,
                embed_socket=embed_socket or DEFAULT_EMBED_SOCKET,
            )
        with cls._init_lock:
            if _is_pytest_isolated():
                if cls._test_instance is None:
                    test_db = Path(tempfile.gettempdir()) / f"tardis_pytest_semantic_cache_{os.getpid()}.db"
                    cls._test_instance = cls(db_path=test_db, embed_socket=DEFAULT_EMBED_SOCKET)
                return cls._test_instance
            if cls._instance is None:
                cls._instance = cls(db_path=DEFAULT_CACHE_DB, embed_socket=DEFAULT_EMBED_SOCKET)
            return cls._instance

    def __init__(
        self,
        db_path: Path = DEFAULT_CACHE_DB,
        embed_socket: str = DEFAULT_EMBED_SOCKET,
        *,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        embed_timeout_s: float = 2.0,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embed_socket = str(embed_socket)
        self.similarity_threshold = float(similarity_threshold)
        self.max_entries = max(50, int(max_entries))
        self.embed_timeout_s = float(embed_timeout_s)
        self._is_isolated = self.db_path.resolve() != DEFAULT_CACHE_DB.resolve()
        self._lock = threading.RLock()
        self._uds_client: Optional[httpx.Client] = None
        # Caché matricial en RAM por partición (namespace, model_family, system_hash, context_hash)
        # Sincronizada automáticamente con el watermark de SQLite WAL entre procesos.
        self._index_watermark: Tuple[int, int, float] = (0, 0, 0.0)
        self._partitions: Dict[Tuple[str, str, str, str], Tuple[List[int], np.ndarray]] = {}
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=8.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS semantic_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exact_key TEXT NOT NULL UNIQUE,
                    namespace TEXT NOT NULL DEFAULT 'default',
                    model_family TEXT NOT NULL DEFAULT 'tardis-kaiju',
                    system_hash TEXT NOT NULL DEFAULT '',
                    context_hash TEXT NOT NULL DEFAULT '',
                    prompt_preview TEXT NOT NULL,
                    reply TEXT NOT NULL,
                    embedding BLOB,
                    embed_dim INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    origin_elapsed_ms REAL NOT NULL DEFAULT 0.0,
                    base_ttl_s REAL NOT NULL DEFAULT 1200.0,
                    created_ts REAL NOT NULL,
                    last_hit_ts REAL NOT NULL,
                    expires_ts REAL NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_sem_part
                    ON semantic_entries(namespace, model_family, system_hash, context_hash, expires_ts);
                CREATE INDEX IF NOT EXISTS idx_sem_exp ON semantic_entries(expires_ts);
                CREATE INDEX IF NOT EXISTS idx_sem_lru ON semantic_entries(last_hit_ts);

                CREATE TABLE IF NOT EXISTS cache_metrics (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    total_lookups INTEGER NOT NULL DEFAULT 0,
                    exact_hits INTEGER NOT NULL DEFAULT 0,
                    semantic_hits INTEGER NOT NULL DEFAULT 0,
                    misses INTEGER NOT NULL DEFAULT 0,
                    bypasses INTEGER NOT NULL DEFAULT 0,
                    stores INTEGER NOT NULL DEFAULT 0,
                    evictions INTEGER NOT NULL DEFAULT 0,
                    embed_calls INTEGER NOT NULL DEFAULT 0,
                    embed_errors INTEGER NOT NULL DEFAULT 0,
                    embed_latency_ms_sum REAL NOT NULL DEFAULT 0.0,
                    tokens_saved_prompt INTEGER NOT NULL DEFAULT 0,
                    tokens_saved_completion INTEGER NOT NULL DEFAULT 0,
                    cpu_ms_saved REAL NOT NULL DEFAULT 0.0,
                    updated_iso TEXT NOT NULL DEFAULT ''
                );
                INSERT OR IGNORE INTO cache_metrics (id, updated_iso) VALUES (1, '');
                """
            )

    def _record_metrics(self, **deltas: Union[int, float]) -> None:
        if not deltas:
            return
        allowed = {
            "total_lookups",
            "exact_hits",
            "semantic_hits",
            "misses",
            "bypasses",
            "stores",
            "evictions",
            "embed_calls",
            "embed_errors",
            "embed_latency_ms_sum",
            "tokens_saved_prompt",
            "tokens_saved_completion",
            "cpu_ms_saved",
        }
        sets = []
        vals: List[Any] = []
        for k, v in deltas.items():
            if k in allowed and v:
                sets.append(f"{k} = {k} + ?")
                vals.append(v)
        if not sets:
            return
        sets.append("updated_iso = ?")
        vals.append(_now_iso())
        try:
            with self._connect() as conn:
                conn.execute(f"UPDATE cache_metrics SET {', '.join(sets)} WHERE id = 1", vals)
        except Exception:
            pass

    # ------------------------------------------------------------------ EmbedBrain UDS
    def _get_uds_client(self) -> httpx.Client:
        if self._uds_client is None or self._uds_client.is_closed:
            transport = httpx.HTTPTransport(uds=self.embed_socket)
            self._uds_client = httpx.Client(
                transport=transport,
                base_url="http://localhost",
                timeout=self.embed_timeout_s,
            )
        return self._uds_client

    def _reset_uds_client(self) -> None:
        if self._uds_client is not None:
            try:
                self._uds_client.close()
            except Exception:
                pass
            self._uds_client = None

    def is_embed_brain_alive(self) -> bool:
        sock = Path(self.embed_socket)
        if not sock.exists():
            return False
        try:
            r = self._get_uds_client().get("/health", timeout=1.0)
            return r.status_code == 200
        except Exception:
            self._reset_uds_client()
            return False

    def embed_query(self, text: str) -> Optional[np.ndarray]:
        """Vectoriza un texto con EmbedBrain (/tmp/embed_brain.sock) y retorna float32 L2-normalizado."""
        clean = _normalize_text(text)
        if not clean:
            return None
        sock = Path(self.embed_socket)
        if not sock.exists():
            self._record_metrics(embed_errors=1)
            return None

        t0 = time.perf_counter()
        payload = {"input": [E5_QUERY_PREFIX + clean[:MAX_EMBED_CHARS]]}
        try:
            with self._lock:
                client = self._get_uds_client()
                resp = client.post("/v1/embeddings", json=payload, timeout=self.embed_timeout_s)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if resp.status_code != 200:
                self._record_metrics(embed_calls=1, embed_errors=1, embed_latency_ms_sum=elapsed_ms)
                return None
            data = resp.json().get("data") or []
            if not data or not data[0].get("embedding"):
                self._record_metrics(embed_calls=1, embed_errors=1, embed_latency_ms_sum=elapsed_ms)
                return None
            vec = np.asarray(data[0]["embedding"], dtype=np.float32)
            norm = float(np.linalg.norm(vec))
            if norm <= 1e-8 or not np.isfinite(norm):
                self._record_metrics(embed_calls=1, embed_errors=1, embed_latency_ms_sum=elapsed_ms)
                return None
            self._record_metrics(embed_calls=1, embed_latency_ms_sum=elapsed_ms)
            return vec / norm
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.debug("[SemanticCache] Fallo al vectorizar en %s: %s", self.embed_socket, exc)
            self._reset_uds_client()
            self._record_metrics(embed_calls=1, embed_errors=1, embed_latency_ms_sum=elapsed_ms)
            return None

    # ------------------------------------------------------------------ índice matricial
    def _sync_vector_index(self, conn: sqlite3.Connection, now: float) -> None:
        """Recarga la matriz NumPy en memoria solo si SQLite WAL cambió (multi-proceso seguro)."""
        row = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(MAX(id), 0) AS max_id, COALESCE(MAX(created_ts), 0.0) AS max_ts "
            "FROM semantic_entries WHERE embedding IS NOT NULL AND expires_ts > ?",
            (now,),
        ).fetchone()
        wm = (int(row["cnt"]), int(row["max_id"]), round(float(row["max_ts"]), 3))
        if wm == self._index_watermark:
            return

        rows = conn.execute(
            "SELECT id, namespace, model_family, system_hash, context_hash, embedding, embed_dim "
            "FROM semantic_entries WHERE embedding IS NOT NULL AND expires_ts > ?",
            (now,),
        ).fetchall()
        grouped_ids: Dict[Tuple[str, str, str, str], List[int]] = {}
        grouped_vecs: Dict[Tuple[str, str, str, str], List[np.ndarray]] = {}
        for r in rows:
            blob = r["embedding"]
            dim = int(r["embed_dim"] or EMBED_DIM)
            if not blob or len(blob) != dim * 4:
                continue
            vec = np.frombuffer(blob, dtype=np.float32)
            if vec.shape[0] != dim:
                continue
            key = (
                str(r["namespace"]),
                str(r["model_family"]),
                str(r["system_hash"]),
                str(r["context_hash"]),
            )
            grouped_ids.setdefault(key, []).append(int(r["id"]))
            grouped_vecs.setdefault(key, []).append(vec)

        new_parts: Dict[Tuple[str, str, str, str], Tuple[List[int], np.ndarray]] = {}
        for k, vecs in grouped_vecs.items():
            new_parts[k] = (grouped_ids[k], np.vstack(vecs))

        self._partitions = new_parts
        self._index_watermark = wm

    def _compute_adaptive_ttl(
        self,
        namespace: str,
        explicit_ttl_s: Optional[float] = None,
        governor_level: Optional[str] = None,
    ) -> float:
        ns = (namespace or "default").strip().lower()
        base = float(explicit_ttl_s) if (explicit_ttl_s is not None and explicit_ttl_s > 0) else NAMESPACE_BASE_TTL_S.get(ns, 1200.0)
        lvl = (governor_level or str(_read_governor_state_fast().get("level") or "GREEN")).upper()
        mult = PRESSURE_TTL_MULT.get(lvl, 1.0)
        return min(MAX_ADAPTIVE_TTL_S, max(30.0, base * mult))

    def _effective_threshold(
        self,
        namespace: str,
        threshold: Optional[float],
        governor_level: str,
    ) -> float:
        base_th = float(threshold if threshold is not None else self.similarity_threshold)
        ns = (namespace or "default").strip().lower()
        if threshold is None and governor_level == "RED" and ns in ("background", "autonomy", "research", "classification", "summary"):
            return max(RED_BACKGROUND_SIMILARITY_THRESHOLD, base_th - 0.02)
        return max(0.80, min(0.9999, base_th))

    # ------------------------------------------------------------------ lookup & store
    def lookup(
        self,
        prompt_or_messages: Union[str, Sequence[Dict[str, Any]]],
        *,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        namespace: str = "default",
        temperature: float = 0.3,
        threshold: Optional[float] = None,
        allow_volatile: bool = False,
        max_temperature: float = DEFAULT_MAX_TEMP,
        precomputed_embedding: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Busca en L1 (hash exacto) y L2 (similitud coseno >= 0.94 sobre EmbedBrain).
        Retorna `{hit, match_type, similarity, reply, entry_id, tokens_saved, cpu_ms_saved, ...}`.
        """
        t0 = time.perf_counter()
        if not is_cache_enabled():
            return {"ok": True, "hit": False, "reason": "cache_disabled", "lookup_ms": 0.0}

        parts = _extract_prompt_parts(prompt_or_messages, system_prompt=system_prompt)
        query_text = parts["query_text"]
        if not query_text or parts["has_images"]:
            self._record_metrics(bypasses=1)
            return {"ok": True, "hit": False, "reason": "empty_or_multimodal", "lookup_ms": 0.0}

        if float(temperature) > float(max_temperature):
            self._record_metrics(bypasses=1)
            return {"ok": True, "hit": False, "reason": "high_temperature_bypass", "lookup_ms": 0.0}

        if not allow_volatile and _is_volatile_prompt(query_text):
            self._record_metrics(bypasses=1)
            return {"ok": True, "hit": False, "reason": "volatile_prompt_bypass", "lookup_ms": 0.0}

        ns = (namespace or "default").strip().lower()
        model_fam = _canonical_model_family(model)
        sys_hash = _sha256_short(parts["system_text"])
        ctx_hash = _sha256_short(parts["context_text"]) if parts["context_text"] else ""
        prompt_hash = _sha256_short(query_text.lower())
        exact_key = _sha256_short(f"{ns}|{model_fam}|{sys_hash}|{ctx_hash}|{prompt_hash}")

        now = time.time()
        gov_lvl = str(_read_governor_state_fast().get("level") or "GREEN").upper()
        eff_threshold = self._effective_threshold(ns, threshold, gov_lvl)

        with self._lock:
            with self._connect() as conn:
                # 1. Nivel L1: coincidencia exacta normalizada (<0.5 ms, 0 llamadas a EmbedBrain)
                row = conn.execute(
                    "SELECT * FROM semantic_entries WHERE exact_key = ? AND expires_ts > ?",
                    (exact_key, now),
                ).fetchone()
                if row is not None:
                    hit_payload = self._finalize_hit(
                        conn,
                        row,
                        now=now,
                        match_type="exact",
                        similarity=1.0,
                        governor_level=gov_lvl,
                        t0=t0,
                    )
                    return hit_payload

                # 2. Nivel L2: similitud semántica coseno vía EmbedBrain
                self._sync_vector_index(conn, now)
                part_key = (ns, model_fam, sys_hash, ctx_hash)
                partition = self._partitions.get(part_key)

                if partition is not None:
                    ids, mat = partition
                    q_vec = precomputed_embedding if precomputed_embedding is not None else self.embed_query(query_text)
                    if q_vec is not None and q_vec.shape[0] == mat.shape[1]:
                        q_norm = float(np.linalg.norm(q_vec))
                        if q_norm > 1e-8:
                            q_unit = (q_vec.astype(np.float32) / q_norm)
                            sims = mat @ q_unit
                            best_idx = int(np.argmax(sims))
                            best_sim = float(sims[best_idx])
                            if best_sim >= eff_threshold:
                                best_id = ids[best_idx]
                                sem_row = conn.execute(
                                    "SELECT * FROM semantic_entries WHERE id = ? AND expires_ts > ?",
                                    (best_id, now),
                                ).fetchone()
                                if sem_row is not None:
                                    return self._finalize_hit(
                                        conn,
                                        sem_row,
                                        now=now,
                                        match_type="semantic",
                                        similarity=round(best_sim, 5),
                                        governor_level=gov_lvl,
                                        t0=t0,
                                    )

        self._record_metrics(total_lookups=1, misses=1)
        return {
            "ok": True,
            "hit": False,
            "match_type": "miss",
            "similarity": 0.0,
            "threshold": eff_threshold,
            "namespace": ns,
            "model_family": model_fam,
            "governor_level": gov_lvl,
            "lookup_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def _finalize_hit(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        now: float,
        match_type: str,
        similarity: float,
        governor_level: str,
        t0: float,
    ) -> Dict[str, Any]:
        new_hits = int(row["hits"]) + 1
        base_ttl = float(row["base_ttl_s"] or 1200.0)
        mult = PRESSURE_TTL_MULT.get(governor_level, 1.0)
        # Refuerzo adaptativo de TTL por frecuencia de aciertos + presión Ring 0
        adaptive_ext = min(MAX_ADAPTIVE_TTL_S, base_ttl * mult * (1.0 + 0.35 * min(new_hits, 6)))
        new_expires = max(float(row["expires_ts"]), now + adaptive_ext)

        conn.execute(
            "UPDATE semantic_entries SET hits = ?, last_hit_ts = ?, expires_ts = ? WHERE id = ?",
            (new_hits, now, new_expires, int(row["id"])),
        )

        p_tok = int(row["prompt_tokens"] or 0)
        c_tok = int(row["completion_tokens"] or 0)
        est_cpu_ms = float(row["origin_elapsed_ms"] or 0.0)
        if est_cpu_ms <= 0.0:
            est_cpu_ms = round((c_tok / 18.0) * 1000.0 + 150.0, 1)

        self._record_metrics(
            total_lookups=1,
            exact_hits=1 if match_type == "exact" else 0,
            semantic_hits=1 if match_type == "semantic" else 0,
            tokens_saved_prompt=p_tok,
            tokens_saved_completion=c_tok,
            cpu_ms_saved=est_cpu_ms,
        )
        return {
            "ok": True,
            "hit": True,
            "match_type": match_type,
            "similarity": similarity,
            "entry_id": int(row["id"]),
            "reply": str(row["reply"]),
            "namespace": str(row["namespace"]),
            "model_family": str(row["model_family"]),
            "hits": new_hits,
            "ttl_remaining_s": round(max(0.0, new_expires - now), 1),
            "tokens_saved": p_tok + c_tok,
            "prompt_tokens_saved": p_tok,
            "completion_tokens_saved": c_tok,
            "cpu_ms_saved": round(est_cpu_ms, 1),
            "governor_level": governor_level,
            "lookup_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def store(
        self,
        prompt_or_messages: Union[str, Sequence[Dict[str, Any]]],
        reply: str,
        *,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        namespace: str = "default",
        temperature: float = 0.3,
        ttl_s: Optional[float] = None,
        usage: Optional[Dict[str, Any]] = None,
        elapsed_ms: float = 0.0,
        allow_volatile: bool = False,
        max_temperature: float = DEFAULT_MAX_TEMP,
        metadata: Optional[Dict[str, Any]] = None,
        precomputed_embedding: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """Almacena una respuesta válida junto con su embedding L2 en SQLite WAL."""
        if not is_cache_enabled():
            return {"ok": True, "stored": False, "reason": "cache_disabled"}
        if _is_error_reply(reply):
            return {"ok": True, "stored": False, "reason": "error_or_empty_reply"}

        parts = _extract_prompt_parts(prompt_or_messages, system_prompt=system_prompt)
        query_text = parts["query_text"]
        if not query_text or parts["has_images"]:
            return {"ok": True, "stored": False, "reason": "empty_or_multimodal"}
        if float(temperature) > float(max_temperature):
            return {"ok": True, "stored": False, "reason": "high_temperature_bypass"}
        if not allow_volatile and _is_volatile_prompt(query_text):
            return {"ok": True, "stored": False, "reason": "volatile_prompt_bypass"}

        ns = (namespace or "default").strip().lower()
        model_fam = _canonical_model_family(model)
        sys_hash = _sha256_short(parts["system_text"])
        ctx_hash = _sha256_short(parts["context_text"]) if parts["context_text"] else ""
        prompt_hash = _sha256_short(query_text.lower())
        exact_key = _sha256_short(f"{ns}|{model_fam}|{sys_hash}|{ctx_hash}|{prompt_hash}")

        vec = precomputed_embedding if precomputed_embedding is not None else self.embed_query(query_text)
        emb_blob: Optional[bytes] = None
        emb_dim = 0
        if vec is not None:
            v32 = np.asarray(vec, dtype=np.float32)
            vnorm = float(np.linalg.norm(v32))
            if vnorm > 1e-8 and np.isfinite(vnorm):
                v32 = v32 / vnorm
                emb_blob = v32.tobytes()
                emb_dim = int(v32.shape[0])

        usage_dict = usage if isinstance(usage, dict) else {}
        p_tok = int(usage_dict.get("prompt_tokens") or _estimate_tokens(parts["system_text"] + " " + query_text))
        c_tok = int(usage_dict.get("completion_tokens") or _estimate_tokens(reply))
        origin_ms = max(0.0, float(elapsed_ms or 0.0))

        now = time.time()
        gov_lvl = str(_read_governor_state_fast().get("level") or "GREEN").upper()
        base_ttl = float(ttl_s) if (ttl_s is not None and ttl_s > 0) else NAMESPACE_BASE_TTL_S.get(ns, 1200.0)
        eff_ttl = self._compute_adaptive_ttl(ns, explicit_ttl_s=ttl_s, governor_level=gov_lvl)
        expires_ts = now + eff_ttl

        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO semantic_entries (
                        exact_key, namespace, model_family, system_hash, context_hash,
                        prompt_preview, reply, embedding, embed_dim,
                        prompt_tokens, completion_tokens, origin_elapsed_ms,
                        base_ttl_s, created_ts, last_hit_ts, expires_ts, hits, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT(exact_key) DO UPDATE SET
                        reply = excluded.reply,
                        embedding = COALESCE(excluded.embedding, semantic_entries.embedding),
                        embed_dim = CASE WHEN excluded.embed_dim > 0 THEN excluded.embed_dim ELSE semantic_entries.embed_dim END,
                        prompt_tokens = excluded.prompt_tokens,
                        completion_tokens = excluded.completion_tokens,
                        origin_elapsed_ms = excluded.origin_elapsed_ms,
                        base_ttl_s = excluded.base_ttl_s,
                        last_hit_ts = excluded.last_hit_ts,
                        expires_ts = excluded.expires_ts,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        exact_key,
                        ns,
                        model_fam,
                        sys_hash,
                        ctx_hash,
                        query_text[:300],
                        reply.strip(),
                        emb_blob,
                        emb_dim,
                        p_tok,
                        c_tok,
                        origin_ms,
                        base_ttl,
                        now,
                        now,
                        expires_ts,
                        meta_json,
                    ),
                )
                evicted = self._enforce_capacity_locked(conn, now)
                # Invalidar watermark local para reflejar el nuevo vector inmediatamente
                self._index_watermark = (0, 0, 0.0)

        self._record_metrics(stores=1, evictions=evicted)
        return {
            "ok": True,
            "stored": True,
            "exact_key": exact_key,
            "namespace": ns,
            "model_family": model_fam,
            "semantic_indexed": emb_blob is not None,
            "embed_dim": emb_dim,
            "ttl_s": round(eff_ttl, 1),
            "governor_level": gov_lvl,
            "evicted": evicted,
        }

    def _enforce_capacity_locked(self, conn: sqlite3.Connection, now: float) -> int:
        evicted = 0
        cur_exp = conn.execute("DELETE FROM semantic_entries WHERE expires_ts <= ?", (now,))
        evicted += max(0, int(cur_exp.rowcount or 0))
        cnt = int(conn.execute("SELECT COUNT(*) FROM semantic_entries").fetchone()[0])
        if cnt > self.max_entries:
            overflow = cnt - self.max_entries
            cur_lru = conn.execute(
                "DELETE FROM semantic_entries WHERE id IN ("
                "  SELECT id FROM semantic_entries ORDER BY last_hit_ts ASC, hits ASC LIMIT ?"
                ")",
                (overflow,),
            )
            evicted += max(0, int(cur_lru.rowcount or 0))
        return evicted

    def prune(self, *, namespace: Optional[str] = None, clear_all: bool = False) -> Dict[str, Any]:
        """Limpia entradas expiradas, un namespace específico o toda la caché."""
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                if clear_all:
                    cur = conn.execute("DELETE FROM semantic_entries")
                elif namespace:
                    cur = conn.execute(
                        "DELETE FROM semantic_entries WHERE namespace = ?",
                        (namespace.strip().lower(),),
                    )
                else:
                    cur = conn.execute("DELETE FROM semantic_entries WHERE expires_ts <= ?", (now,))
                removed = max(0, int(cur.rowcount or 0))
                remaining = int(conn.execute("SELECT COUNT(*) FROM semantic_entries").fetchone()[0])
                self._index_watermark = (0, 0, 0.0)
        if removed:
            self._record_metrics(evictions=removed)
        return {
            "ok": True,
            "removed": removed,
            "remaining": remaining,
            "iso": _now_iso(),
        }

    def stats(self) -> Dict[str, Any]:
        """Retorna telemetría completa de aciertos, ahorro de tokens/CPU y salud de EmbedBrain."""
        now = time.time()
        with self._connect() as conn:
            m = dict(conn.execute("SELECT * FROM cache_metrics WHERE id = 1").fetchone() or {})
            active_cnt = int(
                conn.execute("SELECT COUNT(*) FROM semantic_entries WHERE expires_ts > ?", (now,)).fetchone()[0]
            )
            indexed_cnt = int(
                conn.execute(
                    "SELECT COUNT(*) FROM semantic_entries WHERE expires_ts > ? AND embedding IS NOT NULL",
                    (now,),
                ).fetchone()[0]
            )
            by_ns_rows = conn.execute(
                "SELECT namespace, COUNT(*) AS entries, COALESCE(SUM(hits), 0) AS hits "
                "FROM semantic_entries WHERE expires_ts > ? GROUP BY namespace ORDER BY hits DESC, entries DESC",
                (now,),
            ).fetchall()
            top_rows = conn.execute(
                "SELECT id, namespace, model_family, prompt_preview, hits, prompt_tokens + completion_tokens AS tokens "
                "FROM semantic_entries WHERE expires_ts > ? AND hits > 0 ORDER BY hits DESC, last_hit_ts DESC LIMIT 5",
                (now,),
            ).fetchall()

        total_lookups = int(m.get("total_lookups", 0))
        exact_hits = int(m.get("exact_hits", 0))
        semantic_hits = int(m.get("semantic_hits", 0))
        total_hits = exact_hits + semantic_hits
        embed_calls = int(m.get("embed_calls", 0))
        tokens_p = int(m.get("tokens_saved_prompt", 0))
        tokens_c = int(m.get("tokens_saved_completion", 0))
        cpu_ms = float(m.get("cpu_ms_saved", 0.0))
        db_kb = round(self.db_path.stat().st_size / 1024.0, 1) if self.db_path.is_file() else 0.0

        return {
            "ok": True,
            "schema": "tardis.semantic_cache.v1",
            "enabled": is_cache_enabled(),
            "embed_socket": self.embed_socket,
            "embed_brain_alive": self.is_embed_brain_alive(),
            "similarity_threshold": self.similarity_threshold,
            "max_entries": self.max_entries,
            "active_entries": active_cnt,
            "semantic_indexed_entries": indexed_cnt,
            "db_path": str(self.db_path),
            "db_size_kb": db_kb,
            "counters": {
                "total_lookups": total_lookups,
                "total_hits": total_hits,
                "exact_hits": exact_hits,
                "semantic_hits": semantic_hits,
                "misses": int(m.get("misses", 0)),
                "bypasses": int(m.get("bypasses", 0)),
                "stores": int(m.get("stores", 0)),
                "evictions": int(m.get("evictions", 0)),
                "embed_calls": embed_calls,
                "embed_errors": int(m.get("embed_errors", 0)),
            },
            "rates": {
                "hit_rate_pct": round((total_hits / total_lookups) * 100.0, 2) if total_lookups > 0 else 0.0,
                "exact_hit_rate_pct": round((exact_hits / total_lookups) * 100.0, 2) if total_lookups > 0 else 0.0,
                "semantic_hit_rate_pct": round((semantic_hits / total_lookups) * 100.0, 2) if total_lookups > 0 else 0.0,
                "avg_embed_ms": round(float(m.get("embed_latency_ms_sum", 0.0)) / embed_calls, 2) if embed_calls > 0 else 0.0,
            },
            "savings": {
                "tokens_saved_prompt": tokens_p,
                "tokens_saved_completion": tokens_c,
                "tokens_saved_total": tokens_p + tokens_c,
                "cpu_ms_saved": round(cpu_ms, 1),
                "cpu_seconds_saved": round(cpu_ms / 1000.0, 2),
            },
            "by_namespace": [dict(r) for r in by_ns_rows],
            "top_cached_queries": [dict(r) for r in top_rows],
            "updated_iso": str(m.get("updated_iso") or _now_iso()),
        }

    # ------------------------------------------------------------------ Prompt Router
    def route_prompt(
        self,
        prompt_or_messages: Union[str, Sequence[Dict[str, Any]]],
        *,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        namespace: str = "background",
        task_class: str = "background",
        temperature: float = 0.3,
        max_tokens: int = 512,
        threshold: Optional[float] = None,
        allow_volatile: bool = False,
        check_cache: bool = True,
        governor_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Enrutador soberano de prompts consciente de caché semántica + telemetría Ring 0:
          1. Si hay acierto en caché semántica (L1/L2) -> `lane="semantic_cache"` (0 cómputo LLM).
          2. Si hay llamada prioritaria de Telegram o presión RED en tareas de fondo -> `lane="defer"`.
          3. Si es multimodal/VLM -> `lane="ollama_gpu_11435"`.
          4. Si `/tmp/temporal_brain.sock` está activo -> `lane="temporal_brain_uds"` (con techo de
             tokens adaptativo bajo `ORANGE`/`RED`).
          5. Respaldo ordenado: `ollama_gpu_11435` -> `ollama_cpu_11434` (`keep_alive=0`).
        """
        parts = _extract_prompt_parts(prompt_or_messages, system_prompt=system_prompt)
        t_cls = (task_class or "background").strip().lower()
        ns = (namespace or t_cls or "default").strip().lower()
        gov = governor_snapshot if isinstance(governor_snapshot, dict) else _read_governor_state_fast()
        gov_lvl = str(gov.get("level") or "GREEN").upper()
        call_active = bool(gov.get("call_priority_active", False))

        # Paso 1: Verificar caché semántica antes de consumir cualquier carril de inferencia
        if check_cache and not parts["has_images"]:
            hit = self.lookup(
                prompt_or_messages,
                model=model,
                system_prompt=system_prompt,
                namespace=ns,
                temperature=temperature,
                threshold=threshold,
                allow_volatile=allow_volatile,
            )
            if hit.get("hit"):
                return {
                    "ok": True,
                    "lane": "semantic_cache",
                    "cache_hit": True,
                    "match_type": hit["match_type"],
                    "similarity": hit["similarity"],
                    "cached_reply": hit["reply"],
                    "tokens_saved": hit["tokens_saved"],
                    "cpu_ms_saved": hit["cpu_ms_saved"],
                    "governor_level": gov_lvl,
                    "should_defer": False,
                    "recommended_max_tokens": int(max_tokens),
                    "reason": f"Acierto {hit['match_type']} (sim={hit['similarity']:.4f}) en caché semántica",
                    "lookup_ms": hit.get("lookup_ms", 0.0),
                }

        # Paso 2: Protección Ring 0 de llamadas prioritarias y presión RED para tareas diferibles
        deferrable = t_cls in ("background", "idle_evolution", "heavy_learning", "autonomy", "research")
        if call_active and deferrable:
            return {
                "ok": True,
                "lane": "defer",
                "cache_hit": False,
                "governor_level": gov_lvl,
                "should_defer": True,
                "defer_seconds": 30.0,
                "recommended_max_tokens": 0,
                "reason": "Llamada prioritaria de Telegram activa: inferencia de fondo diferida",
            }
        if gov_lvl == "RED" and t_cls in ("idle_evolution", "heavy_learning", "background"):
            return {
                "ok": True,
                "lane": "defer",
                "cache_hit": False,
                "governor_level": gov_lvl,
                "should_defer": True,
                "defer_seconds": 45.0,
                "recommended_max_tokens": 0,
                "reason": "Presión Ring 0 en nivel RED: inferencia de fondo diferida",
            }

        # Paso 3: Selección de carril físico óptimo
        model_low = (model or "").strip().lower()
        is_vlm = parts["has_images"] or any(k in model_low for k in ("-vl", "vl:", "vision", "llava"))
        rec_tokens = int(max_tokens)
        if deferrable and gov_lvl == "ORANGE":
            rec_tokens = min(rec_tokens, 320)
        elif deferrable and gov_lvl == "YELLOW":
            rec_tokens = min(rec_tokens, 512)

        if is_vlm:
            return {
                "ok": True,
                "lane": "ollama_gpu_11435",
                "cache_hit": False,
                "governor_level": gov_lvl,
                "should_defer": False,
                "recommended_max_tokens": rec_tokens,
                "keep_alive": -1,
                "reason": "Carga multimodal/VLM enrutada al carril GPU dedicado (:11435)",
            }

        tb_sock = Path(os.environ.get("TEMPORAL_BRAIN_SOCKET", "/tmp/temporal_brain.sock"))
        if tb_sock.exists():
            return {
                "ok": True,
                "lane": "temporal_brain_uds",
                "cache_hit": False,
                "governor_level": gov_lvl,
                "should_defer": False,
                "recommended_max_tokens": rec_tokens,
                "reason": f"Tier 0 TemporalBrain UDS activo (nivel={gov_lvl}, max_tokens={rec_tokens})",
            }

        return {
            "ok": True,
            "lane": "ollama_cpu_11434",
            "cache_hit": False,
            "governor_level": gov_lvl,
            "should_defer": False,
            "recommended_max_tokens": min(rec_tokens, 384),
            "keep_alive": 0,
            "reason": "TemporalBrain UDS ausente: respaldo frío Ollama :11434 con keep_alive=0",
        }


def get_semantic_cache(
    db_path: Optional[Path] = None,
    embed_socket: Optional[str] = None,
) -> TardisSemanticCache:
    return TardisSemanticCache.get_instance(db_path=db_path, embed_socket=embed_socket)


def route_prompt(
    prompt_or_messages: Union[str, Sequence[Dict[str, Any]]],
    **kwargs: Any,
) -> Dict[str, Any]:
    return get_semantic_cache().route_prompt(prompt_or_messages, **kwargs)


# ---------------------------------------------------------------------- CLI Soberana
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tardis-cache",
        description="TARDIS Semantic Inference Cache & Prompt Router (EmbedBrain + SQLite WAL)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="Mostrar métricas de aciertos, ahorro de tokens/CPU y salud de EmbedBrain")

    p_lkp = sub.add_parser("lookup", help="Consultar caché semántica (L1 exact + L2 coseno)")
    p_lkp.add_argument("prompt", help="Texto de consulta")
    p_lkp.add_argument("--namespace", default="default")
    p_lkp.add_argument("--model", default="TARDIS-NEURAL-SPACE-KAIJU")
    p_lkp.add_argument("--threshold", type=float, default=None)
    p_lkp.add_argument("--allow-volatile", action="store_true")

    p_st = sub.add_parser("store", help="Guardar manualmente un par prompt/respuesta en caché")
    p_st.add_argument("prompt", help="Texto de consulta")
    p_st.add_argument("reply", help="Respuesta a almacenar")
    p_st.add_argument("--namespace", default="default")
    p_st.add_argument("--model", default="TARDIS-NEURAL-SPACE-KAIJU")
    p_st.add_argument("--ttl", type=float, default=None)
    p_st.add_argument("--tokens", type=int, default=0)
    p_st.add_argument("--elapsed-ms", type=float, default=0.0)

    p_rt = sub.add_parser("route", help="Evaluar decisión de enrutamiento de un prompt")
    p_rt.add_argument("prompt", help="Texto de consulta")
    p_rt.add_argument("--namespace", default="background")
    p_rt.add_argument("--task-class", default="background")
    p_rt.add_argument("--model", default="TARDIS-NEURAL-SPACE-KAIJU")
    p_rt.add_argument("--max-tokens", type=int, default=512)

    p_pr = sub.add_parser("prune", help="Podar entradas expiradas o limpiar un namespace")
    p_pr.add_argument("--namespace", default=None)
    p_pr.add_argument("--all", action="store_true", dest="clear_all")

    sub.add_parser("benchmark", help="Ejecutar benchmark en vivo contra /tmp/embed_brain.sock en DB temporal")

    args = parser.parse_args(argv)
    cache = get_semantic_cache()

    if args.cmd == "stats":
        print(json.dumps(cache.stats(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "lookup":
        res = cache.lookup(
            args.prompt,
            namespace=args.namespace,
            model=args.model,
            threshold=args.threshold,
            allow_volatile=args.allow_volatile,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "store":
        usage = {"completion_tokens": args.tokens} if args.tokens > 0 else None
        res = cache.store(
            args.prompt,
            args.reply,
            namespace=args.namespace,
            model=args.model,
            ttl_s=args.ttl,
            usage=usage,
            elapsed_ms=args.elapsed_ms,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "route":
        res = cache.route_prompt(
            args.prompt,
            namespace=args.namespace,
            task_class=args.task_class,
            model=args.model,
            max_tokens=args.max_tokens,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "prune":
        res = cache.prune(namespace=args.namespace, clear_all=args.clear_all)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "benchmark":
        with tempfile.TemporaryDirectory(prefix="tardis_semcache_bench_") as td:
            bench = TardisSemanticCache(db_path=Path(td) / "bench.db")
            t_s = time.perf_counter()
            st = bench.store(
                "Explica cómo mitiga el gobernador de recursos la presión CPU PSI en Linux",
                "El TardisResourceGovernor aplica cuotas cgroup v2 y perfil energético adaptativo.",
                namespace="background",
                elapsed_ms=2450.0,
                usage={"prompt_tokens": 64, "completion_tokens": 92},
            )
            store_ms = round((time.perf_counter() - t_s) * 1000.0, 2)
            exact_hit = bench.lookup(
                "Explica cómo mitiga el gobernador de recursos la presión CPU PSI en Linux",
                namespace="background",
            )
            sem_hit = bench.lookup(
                "Explica de qué manera el gobernador de recursos mitiga la presión CPU PSI en Linux",
                namespace="background",
            )
            miss_res = bench.lookup(
                "Receta paso a paso para hornear pan masa madre con centeno",
                namespace="background",
            )
            out = {
                "ok": bool(st.get("stored") and exact_hit.get("hit") and sem_hit.get("hit") and not miss_res.get("hit")),
                "embed_brain_alive": bench.is_embed_brain_alive(),
                "store_ms": store_ms,
                "exact_hit": {
                    "hit": exact_hit.get("hit"),
                    "match_type": exact_hit.get("match_type"),
                    "similarity": exact_hit.get("similarity"),
                    "lookup_ms": exact_hit.get("lookup_ms"),
                },
                "semantic_hit": {
                    "hit": sem_hit.get("hit"),
                    "match_type": sem_hit.get("match_type"),
                    "similarity": sem_hit.get("similarity"),
                    "lookup_ms": sem_hit.get("lookup_ms"),
                },
                "unrelated_miss": {
                    "hit": miss_res.get("hit"),
                    "lookup_ms": miss_res.get("lookup_ms"),
                },
                "stats": bench.stats(),
            }
            print(json.dumps(out, indent=2, ensure_ascii=False))
            return 0 if out["ok"] else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
