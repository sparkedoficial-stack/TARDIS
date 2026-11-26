#!/usr/bin/env python3
"""
core/tardis_memory_compactor.py - Autonomous Memory Compactor & Knowledge Graph Deduplicator
============================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU

Compactador nocturno y deduplicador autónomo para las bóvedas SQLite de TARDIS:
  1. **RAGVault (`data/rag_vault.db`)**:
     - Detección de duplicados exactos y cuasi-duplicados mediante SimHash-64 con LSH en 4 bandas
       de 16 bits (garantía matemática de hallar toda distancia de Hamming <= 3 en O(N)) +
       verificación opcional de similitud coseno en `rag_vectors` (>= 0.985).
     - Eliminación segura con mantenimiento íntegro de FTS5 contentless (`rag_fts`) y re-enlazado
       de `rag_relations.chunk_id` hacia el fragmento canónico sobreviviente.
     - Consolidación jerárquica de episodios (resúmenes extractivos L1 en `rag_summaries`) y
       re-calibración isotrópica automática (`core/embed_isotropy.py`).
  2. **KnowledgeGraph (`data/knowledge_graph.db`)**:
     - Fusión determinista de nodos duplicados por mayúsculas/acentos/viñetas/guiones,
       re-enrutamiento de `kg_edges` acumulando pesos, poda de auto-lazos y consolidación de
       comunidades en `kg_communities`.
  3. **DeepMemoryVault (`~/vw-control/deep_memory_vault/vault_master.db`)**:
     - Deduplicación de `knowledge_nodes`, poda de eco-duplicados consecutivos en `vault_events`
       (misma sesión/rol/contenido en ventana <= 60 s), compresión `zlib` de eventos antiguos
       > 4 KB e `incremental_vacuum` + `ANALYZE`.
  4. **OfflineChatVault (`data/offline_chats.db`)**:
     - Poda de turnos duplicados consecutivos (reintentos <= 120 s) preservando el 100 % del
       historial genuino + sincronización `offline_chat_fts` + `VACUUM`/`ANALYZE`.
  5. **Checkpoint & Optimize de bóvedas WAL auxiliares**:
     - `PRAGMA wal_checkpoint(TRUNCATE)` y `PRAGMA optimize` en `sovereign_event_bus.db`,
       `resource_governor.db`, `coevolution_vault.db`, `semantic_cache.db`, `eval_harness.db`
       y `canary_verifications.db`.

Gobernanza Ring 0:
  - Difiere automáticamente ante llamada prioritaria de Telegram o presión `RED` (salvo `--force`).
  - Soporta modo `dry_run=True` (auditoría sin mutaciones) y registra cada corrida en SQLite WAL
    (`data/memory_compactor.db`, aislada automáticamente durante `pytest`).
"""
from __future__ import annotations

import argparse
import collections
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
import unicodedata
import uuid
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_COMPACTOR_DB = DATA_DIR / "memory_compactor.db"
DEFAULT_RAG_DB = DATA_DIR / "rag_vault.db"
DEFAULT_KG_DB = DATA_DIR / "knowledge_graph.db"
DEFAULT_OFFLINE_CHAT_DB = DATA_DIR / "offline_chats.db"
DEFAULT_SUBSYSTEM_AGENTS_DB = DATA_DIR / "subsystem_agents.db"
DEFAULT_GODS_EYE_DB = DATA_DIR / "gods_eye.db"
DEFAULT_DEEP_MEMORY_DB = (
    Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
    / "vw-control"
    / "deep_memory_vault"
    / "vault_master.db"
)

DEFAULT_SUBSYSTEM_RETENTION_DAYS = float(os.environ.get("TARDIS_SUBSYSTEM_RETENTION_DAYS", "14"))
DEFAULT_GODS_EYE_DETECTIONS_RETENTION_DAYS = float(os.environ.get("TARDIS_GODS_EYE_DETECTIONS_RETENTION_DAYS", "7"))
DEFAULT_GODS_EYE_EVENTS_RETENTION_DAYS = float(os.environ.get("TARDIS_GODS_EYE_EVENTS_RETENTION_DAYS", "14"))

AUX_WAL_DBS: Tuple[Path, ...] = (
    DATA_DIR / "sovereign_event_bus.db",
    DATA_DIR / "resource_governor.db",
    DATA_DIR / "coevolution_vault.db",
    DATA_DIR / "semantic_cache.db",
    DATA_DIR / "eval_harness.db",
    DATA_DIR / "canary_verifications.db",
    DATA_DIR / "frontier_lab.db",
)

ALL_TARGETS: Tuple[str, ...] = ("rag", "kg", "deep_memory", "offline_chats", "subsystem_agents", "gods_eye", "wal")

logger = logging.getLogger("TARDIS.MemoryCompactor")


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _is_pytest_isolated() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and str(
        os.environ.get("TARDIS_COMPACTOR_LIVE_TEST", "0")
    ).strip().lower() not in ("1", "true", "yes")


def _db_total_bytes(db_path: Path) -> int:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _normalize_entity(name: str) -> str:
    """Normaliza una entidad del grafo eliminando viñetas iniciales, acentos, mayúsculas y guiones."""
    raw = (name or "").strip()
    raw = re.sub(r"^[\-\*•·\d\.\)\s]+", "", raw)
    folded = unicodedata.normalize("NFKD", raw.lower()).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[\s_\-]+", " ", folded).strip()


def _normalize_text_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def simhash64(text: str) -> int:
    """Calcula huella SimHash de 64 bits sobre tokens alfanuméricos normalizados."""
    folded = unicodedata.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode("ascii")
    toks = re.findall(r"[a-z0-9_]{3,}", folded)
    if not toks:
        toks = re.findall(r"[a-z0-9_]+", folded)
    if not toks:
        return 0
    acc = [0] * 64
    for tok in toks[:220]:
        h = int.from_bytes(hashlib.blake2b(tok.encode("ascii", "ignore"), digest_size=8).digest(), "big")
        for b in range(64):
            acc[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(64):
        if acc[b] > 0:
            out |= 1 << b
    return out


def hamming_distance(a: int, b: int) -> int:
    return int((int(a) ^ int(b)).bit_count())


def _safe_sqlite_maintain(
    con: sqlite3.Connection,
    *,
    do_vacuum: bool = False,
    incremental_pages: int = 0,
    non_blocking: bool = False,
    fts_tables: Sequence[str] = (),
    enable_incremental_vacuum: bool = False,
) -> Dict[str, Any]:
    """
    Ejecuta mantenimiento seguro de SQLite:
      - En modo `non_blocking=True`: WAL checkpoint `PASSIVE` (no bloquea lectores),
        optimización de tablas FTS5, `PRAGMA incremental_vacuum(N)` y `PRAGMA analysis_limit=400; PRAGMA optimize`.
      - En modo offline/completo: WAL checkpoint `TRUNCATE`, `ANALYZE`, `PRAGMA optimize`,
        migración opcional `auto_vacuum=INCREMENTAL` + `VACUUM`.
    """
    res: Dict[str, Any] = {
        "checkpoint": False,
        "checkpoint_mode": "PASSIVE" if non_blocking else "TRUNCATE",
        "analyze": False,
        "vacuum": False,
        "fts_optimized": [],
        "non_blocking": bool(non_blocking),
    }
    for tbl in fts_tables:
        tname = re.sub(r"[^a-zA-Z0-9_]", "", str(tbl or ""))
        if not tname:
            continue
        try:
            con.execute(f"INSERT INTO {tname}({tname}) VALUES ('optimize')")
            con.commit()
            res["fts_optimized"].append(tname)
        except Exception:
            pass
    try:
        jm = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if jm == "wal":
            chk_mode = "PASSIVE" if non_blocking else "TRUNCATE"
            chk_row = con.execute(f"PRAGMA wal_checkpoint({chk_mode})").fetchone()
            res["checkpoint"] = True
            if chk_row is not None:
                res["wal_checkpoint"] = {
                    "busy": int(chk_row[0]),
                    "log": int(chk_row[1]),
                    "checkpointed": int(chk_row[2]),
                }
    except Exception:
        pass
    try:
        con.execute("PRAGMA analysis_limit=400")
        if not non_blocking:
            con.execute("ANALYZE")
        con.execute("PRAGMA optimize")
        res["analyze"] = True
    except Exception:
        pass
    try:
        av_cur = int(con.execute("PRAGMA auto_vacuum").fetchone()[0])
    except Exception:
        av_cur = 0
    if enable_incremental_vacuum and av_cur != 2 and not non_blocking:
        try:
            con.commit()
            con.execute("PRAGMA auto_vacuum=INCREMENTAL")
            do_vacuum = True
            res["migrated_auto_vacuum_incremental"] = True
        except Exception:
            pass
    if incremental_pages > 0 and (av_cur == 2 or res.get("migrated_auto_vacuum_incremental")):
        try:
            con.execute(f"PRAGMA incremental_vacuum({int(incremental_pages)})")
            res["incremental_vacuum"] = True
        except Exception:
            pass
    if do_vacuum and not non_blocking:
        try:
            con.commit()
            con.execute("VACUUM")
            res["vacuum"] = True
            if str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal":
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as exc:
            res["vacuum_error"] = str(exc)
    try:
        res["auto_vacuum_after"] = int(con.execute("PRAGMA auto_vacuum").fetchone()[0])
    except Exception:
        pass
    return res


def _build_extractive_summary(texts: Sequence[str], title: str, max_chars: int = 420) -> str:
    """Genera un resumen extractivo determinista de episodios/documentos sin gasto LLM."""
    sentences: List[str] = []
    seen: Set[str] = set()
    for t in texts[:12]:
        for seg in re.split(r"(?<=[\.\!\?])\s+|\n+", (t or "").strip()):
            clean = re.sub(r"\s+", " ", seg).strip()
            if len(clean) < 28 or len(clean) > 220:
                continue
            key = clean[:60].lower()
            if key in seen:
                continue
            seen.add(key)
            sentences.append(clean)
            if len(sentences) >= 4:
                break
        if len(sentences) >= 4:
            break
    if not sentences:
        joined = " ".join((t or "").strip()[:120] for t in texts[:3]).strip()
        return f"Consolidación de {len(texts)} fragmentos sobre '{title}': {joined[:max_chars]}"
    body = " ".join(sentences)
    return f"[{len(texts)} fragmentos · {title[:64]}] {body}"[:max_chars]


class TardisMemoryCompactor:
    """Compactador soberano de bóvedas SQLite y deduplicador del Grafo de Conocimiento."""

    _instance: Optional["TardisMemoryCompactor"] = None
    _test_instance: Optional["TardisMemoryCompactor"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "TardisMemoryCompactor":
        if db_path is not None:
            return cls(db_path=db_path)
        with cls._init_lock:
            if _is_pytest_isolated():
                if cls._test_instance is None:
                    test_db = Path(tempfile.gettempdir()) / f"tardis_pytest_compactor_{os.getpid()}.db"
                    cls._test_instance = cls(db_path=test_db)
                return cls._test_instance
            if cls._instance is None:
                cls._instance = cls(db_path=DEFAULT_COMPACTOR_DB)
            return cls._instance

    def __init__(self, db_path: Path = DEFAULT_COMPACTOR_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._is_isolated = self.db_path.resolve() != DEFAULT_COMPACTOR_DB.resolve()
        self._lock = threading.Lock()
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
                CREATE TABLE IF NOT EXISTS compaction_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    deferred INTEGER NOT NULL DEFAULT 0,
                    bytes_before INTEGER NOT NULL DEFAULT 0,
                    bytes_after INTEGER NOT NULL DEFAULT 0,
                    bytes_reclaimed INTEGER NOT NULL DEFAULT 0,
                    duplicates_pruned INTEGER NOT NULL DEFAULT 0,
                    kg_nodes_merged INTEGER NOT NULL DEFAULT 0,
                    episodes_consolidated INTEGER NOT NULL DEFAULT 0,
                    elapsed_ms REAL NOT NULL DEFAULT 0.0,
                    report_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_comp_ts ON compaction_runs(ts);
                """
            )

    # ------------------------------------------------------------------ 1. RAGVault
    def compact_rag_vault(
        self,
        db_path: Path = DEFAULT_RAG_DB,
        *,
        dry_run: bool = False,
        max_hamming: int = 3,
        min_cosine: float = 0.985,
        consolidate_episodes: bool = True,
        max_new_summaries: int = 40,
        vacuum_threshold: int = 25,
    ) -> Dict[str, Any]:
        """Deduplica chunks en RAGVault por SimHash-64 + coseno, consolida episodios RAPTOR y compacta."""
        t0 = time.perf_counter()
        p = Path(db_path)
        if not p.is_file():
            return {"ok": True, "skipped": True, "reason": "db_not_found", "path": str(p)}

        bytes_before = _db_total_bytes(p)
        con = sqlite3.connect(str(p), timeout=20.0)
        con.execute("PRAGMA busy_timeout=15000")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            rows = con.execute(
                "SELECT id, doc_id, source, title, term, text, ts FROM rag_chunks ORDER BY id ASC"
            ).fetchall()
            vec_map: Dict[int, np.ndarray] = {}
            for cid, blob in con.execute("SELECT chunk_id, vec FROM rag_vectors").fetchall():
                if blob and len(blob) % 4 == 0:
                    v = np.frombuffer(blob, dtype=np.float32)
                    n = float(np.linalg.norm(v))
                    if n > 1e-8 and np.isfinite(n):
                        vec_map[int(cid)] = v / n

            # Detección O(N) con LSH 4 bandas x 16 bits + verificación coseno cuando haya vectores
            buckets: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = {}
            exact_seen: Dict[str, int] = {}
            # (dup_id, canonical_id, title, term, text, reason)
            duplicates: List[Tuple[int, int, str, str, str, str]] = []
            exact_dups = 0
            simhash_dups = 0

            for cid, _doc_id, _src, title, term, text, _ts in rows:
                cid_i = int(cid)
                txt_s = str(text or "")
                norm_k = _normalize_text_key(txt_s)
                if norm_k in exact_seen:
                    exact_dups += 1
                    duplicates.append((cid_i, exact_seen[norm_k], str(title or ""), str(term or ""), txt_s, "exact_norm"))
                    continue

                sh = simhash64(txt_s)
                canon_match: Optional[int] = None
                if sh != 0 and len(txt_s) >= 48:
                    cand_ids: Set[int] = set()
                    for band in range(4):
                        bkey = (band, (sh >> (band * 16)) & 0xFFFF)
                        for prev_id, prev_sh, prev_len in buckets.get(bkey, ()):
                            if prev_id in cand_ids:
                                continue
                            # Evitar comparar fragmentos de longitudes muy distintas
                            if abs(len(txt_s) - prev_len) > max(80, int(max(len(txt_s), prev_len) * 0.25)):
                                continue
                            if hamming_distance(sh, prev_sh) <= max_hamming:
                                cand_ids.add(prev_id)
                                v_cur = vec_map.get(cid_i)
                                v_prev = vec_map.get(prev_id)
                                if v_cur is not None and v_prev is not None and v_cur.shape == v_prev.shape:
                                    if float(np.dot(v_cur, v_prev)) >= min_cosine:
                                        canon_match = prev_id
                                        break
                                else:
                                    canon_match = prev_id
                                    break
                        if canon_match is not None:
                            break

                if canon_match is not None:
                    simhash_dups += 1
                    duplicates.append((cid_i, canon_match, str(title or ""), str(term or ""), txt_s, "simhash_cosine"))
                else:
                    exact_seen[norm_k] = cid_i
                    if sh != 0 and len(txt_s) >= 48:
                        for band in range(4):
                            bkey = (band, (sh >> (band * 16)) & 0xFFFF)
                            buckets.setdefault(bkey, []).append((cid_i, sh, len(txt_s)))

            # Plan de consolidación jerárquica de episodios (RAPTOR L1 en rag_summaries)
            dup_id_set = {d[0] for d in duplicates}
            existing_sum_titles = {
                str(r[0]) for r in con.execute("SELECT title FROM rag_summaries WHERE level = 1").fetchall()
            }
            by_doc: Dict[str, List[Tuple[int, str, str, str]]] = collections.defaultdict(list)
            for cid, doc_id, src, title, _term, text, _ts in rows:
                if int(cid) in dup_id_set:
                    continue
                by_doc[str(doc_id or src)].append((int(cid), str(src or ""), str(title or doc_id or src), str(text or "")))

            new_summaries: List[Tuple[str, str, str, str]] = []
            if consolidate_episodes:
                for doc_key, items in sorted(by_doc.items(), key=lambda kv: len(kv[1]), reverse=True):
                    if len(items) < 6:
                        continue
                    s_title = f"Episodio L1 · {items[0][2][:80]}"
                    if s_title in existing_sum_titles:
                        continue
                    summary_txt = _build_extractive_summary([x[3] for x in items], items[0][2])
                    cids_json = json.dumps([x[0] for x in items[:50]])
                    new_summaries.append((s_title, summary_txt, items[0][1][:40], cids_json))
                    if len(new_summaries) >= max_new_summaries:
                        break

            pruned = 0
            summaries_added = 0
            maint: Dict[str, Any] = {}
            if not dry_run:
                for dup_id, canon_id, d_title, d_term, d_text, _reason in duplicates:
                    # Re-enlazar relaciones hacia el chunk canónico
                    try:
                        con.execute("UPDATE rag_relations SET chunk_id = ? WHERE chunk_id = ?", (canon_id, dup_id))
                    except Exception:
                        pass
                    # Eliminar del índice contentless FTS5 con la sintaxis oficial 'delete'
                    try:
                        con.execute(
                            "INSERT INTO rag_fts(rag_fts, rowid, text, title, term) VALUES ('delete', ?, ?, ?, ?)",
                            (dup_id, d_text, d_title, d_term),
                        )
                    except Exception:
                        pass
                    cur = con.execute("DELETE FROM rag_chunks WHERE id = ?", (dup_id,))
                    pruned += max(0, int(cur.rowcount or 0))

                now_ts = time.time()
                for s_title, s_txt, c_tag, cids_json in new_summaries:
                    con.execute(
                        "INSERT INTO rag_summaries (level, title, summary, cluster_tag, chunk_ids, ts) VALUES (1, ?, ?, ?, ?, ?)",
                        (s_title, s_txt, c_tag, cids_json, now_ts),
                    )
                    summaries_added += 1
                con.commit()

                do_vac = pruned >= vacuum_threshold
                maint = _safe_sqlite_maintain(con, do_vacuum=do_vac)
            else:
                pruned = len(duplicates)
                summaries_added = len(new_summaries)
        finally:
            con.close()

        # Re-calibrar isotropía si se podaron >= 50 vectores en producción
        isotropy_refit = False
        if not dry_run and pruned >= 50 and p.resolve() == DEFAULT_RAG_DB.resolve():
            try:
                from core.embed_isotropy import fit_from_rag_db

                refit_res = fit_from_rag_db(db_path=p, save_artifact=True)
                isotropy_refit = bool(refit_res.get("fitted"))
            except Exception:
                pass

        bytes_after = _db_total_bytes(p)
        return {
            "ok": True,
            "target": "rag",
            "path": str(p),
            "dry_run": dry_run,
            "total_chunks_scanned": len(rows),
            "exact_duplicates": exact_dups,
            "simhash_cosine_duplicates": simhash_dups,
            "duplicates_pruned": pruned,
            "episodes_consolidated": summaries_added,
            "isotropy_refit": isotropy_refit,
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
            "bytes_reclaimed": max(0, bytes_before - bytes_after),
            "maintenance": maint,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # ------------------------------------------------------------------ 2. KnowledgeGraph
    def deduplicate_knowledge_graph(
        self,
        db_path: Path = DEFAULT_KG_DB,
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Fusiona nodos duplicados en KnowledgeGraph, consolida pesos de aristas y elimina auto-lazos."""
        t0 = time.perf_counter()
        p = Path(db_path)
        if not p.is_file():
            return {"ok": True, "skipped": True, "reason": "db_not_found", "path": str(p)}

        bytes_before = _db_total_bytes(p)
        con = sqlite3.connect(str(p), timeout=15.0)
        con.execute("PRAGMA busy_timeout=10000")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            nodes = con.execute(
                "SELECT id, name, entity_type, description, metadata, ts FROM kg_nodes ORDER BY id ASC"
            ).fetchall()
            edges = con.execute(
                "SELECT id, source_id, target_id, relation, weight, evidence, ts FROM kg_edges"
            ).fetchall()

            groups: Dict[str, List[Tuple[int, str, str, str, str, float]]] = collections.defaultdict(list)
            for row in nodes:
                nk = _normalize_entity(str(row[1]))
                if nk:
                    groups[nk].append((int(row[0]), str(row[1]), str(row[2] or "concept"), str(row[3] or ""), str(row[4] or "{}"), float(row[5] or 0.0)))

            merge_plans: List[Tuple[int, List[int], str]] = []
            for nk, members in groups.items():
                if len(members) <= 1:
                    continue
                # Elegir nodo canónico: sin viñeta inicial, mayor descripción, menor id
                def _canon_rank(m: Tuple[int, str, str, str, str, float]) -> Tuple[int, int, int]:
                    starts_bullet = 1 if re.match(r"^[\-\*•·]", m[1].strip()) else 0
                    return (starts_bullet, -len(m[3]), m[0])

                ordered = sorted(members, key=_canon_rank)
                canon = ordered[0]
                dups = [m[0] for m in ordered[1:]]
                merge_plans.append((canon[0], dups, nk))

            self_loops_existing = sum(1 for e in edges if int(e[1]) == int(e[2]))
            nodes_merged = sum(len(dups) for _, dups, _ in merge_plans)
            edges_relinked = 0
            self_loops_removed = self_loops_existing
            communities_created = 0
            maint: Dict[str, Any] = {}

            if not dry_run:
                # Re-enlazar todas las aristas de nodos duplicados hacia su nodo canónico
                dup_to_canon: Dict[int, int] = {}
                for canon_id, dup_ids, _nk in merge_plans:
                    for did in dup_ids:
                        dup_to_canon[did] = canon_id

                if dup_to_canon or self_loops_existing > 0:
                    for eid, src, tgt, rel, weight, ev, ts in edges:
                        new_src = dup_to_canon.get(int(src), int(src))
                        new_tgt = dup_to_canon.get(int(tgt), int(tgt))
                        if new_src == new_tgt:
                            con.execute("DELETE FROM kg_edges WHERE id = ?", (int(eid),))
                            self_loops_removed += 1
                            continue
                        if new_src != int(src) or new_tgt != int(tgt):
                            existing = con.execute(
                                "SELECT id, weight FROM kg_edges WHERE source_id = ? AND target_id = ? AND relation = ?",
                                (new_src, new_tgt, rel),
                            ).fetchone()
                            if existing is not None and int(existing[0]) != int(eid):
                                con.execute(
                                    "UPDATE kg_edges SET weight = ? WHERE id = ?",
                                    (float(existing[1] or 1.0) + float(weight or 1.0), int(existing[0])),
                                )
                                con.execute("DELETE FROM kg_edges WHERE id = ?", (int(eid),))
                            else:
                                con.execute(
                                    "UPDATE kg_edges SET source_id = ?, target_id = ? WHERE id = ?",
                                    (new_src, new_tgt, int(eid)),
                                )
                            edges_relinked += 1

                    # Borrar nodos duplicados ya desconectados
                    for did in dup_to_canon.keys():
                        con.execute("DELETE FROM kg_nodes WHERE id = ?", (did,))

                # Poblar comunidades conexas principales si kg_communities está vacía
                cur_comm_cnt = int(con.execute("SELECT COUNT(*) FROM kg_communities").fetchone()[0])
                if cur_comm_cnt == 0:
                    adj: Dict[int, Set[int]] = collections.defaultdict(set)
                    node_names = {int(r[0]): str(r[1]) for r in con.execute("SELECT id, name FROM kg_nodes").fetchall()}
                    for src, tgt in con.execute("SELECT source_id, target_id FROM kg_edges").fetchall():
                        adj[int(src)].add(int(tgt))
                        adj[int(tgt)].add(int(src))
                    visited: Set[int] = set()
                    comps: List[List[int]] = []
                    for nid in adj.keys():
                        if nid in visited:
                            continue
                        comp: List[int] = []
                        q = collections.deque([nid])
                        visited.add(nid)
                        while q:
                            u = q.popleft()
                            comp.append(u)
                            for v in adj.get(u, ()):
                                if v not in visited:
                                    visited.add(v)
                                    q.append(v)
                        if len(comp) >= 3:
                            comps.append(comp)
                    comps.sort(key=len, reverse=True)
                    now_ts = time.time()
                    for idx, comp in enumerate(comps[:12], start=1):
                        top_nodes = sorted(comp, key=lambda x: len(adj.get(x, ())), reverse=True)[:5]
                        labels = [node_names.get(x, str(x)) for x in top_nodes]
                        cname = f"comunidad_{idx:02d}_{_normalize_entity(labels[0])[:28] or idx}"
                        summary = f"Clúster semántico ({len(comp)} nodos): {', '.join(labels)}"
                        con.execute(
                            "INSERT OR IGNORE INTO kg_communities (name, summary, level, node_ids, ts) VALUES (?, ?, 0, ?, ?)",
                            (cname, summary, json.dumps(comp[:100]), now_ts),
                        )
                        communities_created += 1

                con.commit()
                maint = _safe_sqlite_maintain(con, do_vacuum=(nodes_merged > 0))
        finally:
            con.close()

        bytes_after = _db_total_bytes(p)
        return {
            "ok": True,
            "target": "kg",
            "path": str(p),
            "dry_run": dry_run,
            "nodes_scanned": len(nodes),
            "duplicate_groups": len(merge_plans),
            "nodes_merged": nodes_merged,
            "edges_relinked": edges_relinked,
            "self_loops_removed": self_loops_removed,
            "communities_created": communities_created,
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
            "bytes_reclaimed": max(0, bytes_before - bytes_after),
            "maintenance": maint,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # ------------------------------------------------------------------ 3. DeepMemoryVault
    def compact_deep_memory(
        self,
        db_path: Path = DEFAULT_DEEP_MEMORY_DB,
        *,
        dry_run: bool = False,
        compress_age_days: float = 7.0,
        compress_min_bytes: int = 4096,
    ) -> Dict[str, Any]:
        """Compacta DeepMemoryVault: poda ecos duplicados consecutivos, comprime antiguos y hace incremental_vacuum."""
        t0 = time.perf_counter()
        p = Path(db_path)
        if not p.is_file():
            return {"ok": True, "skipped": True, "reason": "db_not_found", "path": str(p)}

        bytes_before = _db_total_bytes(p)
        con = sqlite3.connect(str(p), timeout=20.0)
        con.execute("PRAGMA busy_timeout=15000")
        try:
            events = con.execute(
                "SELECT id, ts, session_id, source, role, content, is_compressed FROM vault_events ORDER BY id ASC"
            ).fetchall()
            last_seen: Dict[Tuple[str, str, str, str], float] = {}
            dup_event_ids: List[int] = []
            compress_targets: List[Tuple[int, str]] = []
            age_cutoff = time.time() - (compress_age_days * 86400.0)

            for eid, ts, sess, src, role, content, is_comp in events:
                txt = str(content or "")
                key = (str(sess or ""), str(src or ""), str(role or ""), _normalize_text_key(txt)[:240])
                prev_ts = last_seen.get(key)
                if prev_ts is not None and abs(float(ts or 0.0) - prev_ts) <= 60.0 and len(txt.strip()) >= 8:
                    dup_event_ids.append(int(eid))
                else:
                    last_seen[key] = float(ts or 0.0)
                    if int(is_comp or 0) == 0 and float(ts or 0.0) < age_cutoff and len(txt.encode("utf-8", errors="ignore")) >= compress_min_bytes:
                        compress_targets.append((int(eid), txt))

            compressed_cnt = 0
            pruned_cnt = 0
            maint: Dict[str, Any] = {}
            if not dry_run:
                for eid in dup_event_ids:
                    try:
                        con.execute("DELETE FROM vault_fts WHERE content_rowid = ?", (eid,))
                    except Exception:
                        pass
                    cur = con.execute("DELETE FROM vault_events WHERE id = ?", (eid,))
                    pruned_cnt += max(0, int(cur.rowcount or 0))
                for eid, txt in compress_targets[:500]:
                    raw_b = txt.encode("utf-8", errors="ignore")
                    comp_b = zlib.compress(raw_b, level=6)
                    if len(comp_b) < int(len(raw_b) * 0.80):
                        con.execute(
                            "UPDATE vault_events SET content_compressed = ?, is_compressed = 1, content = ? WHERE id = ?",
                            (comp_b, txt[:512] + " [compressed]", eid),
                        )
                        compressed_cnt += 1
                con.commit()
                maint = _safe_sqlite_maintain(con, do_vacuum=False, incremental_pages=500)
            else:
                pruned_cnt = len(dup_event_ids)
                compressed_cnt = len(compress_targets[:500])
        finally:
            con.close()

        bytes_after = _db_total_bytes(p)
        return {
            "ok": True,
            "target": "deep_memory",
            "path": str(p),
            "dry_run": dry_run,
            "events_scanned": len(events),
            "duplicates_pruned": pruned_cnt,
            "events_compressed": compressed_cnt,
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
            "bytes_reclaimed": max(0, bytes_before - bytes_after),
            "maintenance": maint,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # ------------------------------------------------------------------ 4. OfflineChatVault
    def compact_offline_chats(
        self,
        db_path: Path = DEFAULT_OFFLINE_CHAT_DB,
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Poda turnos eco-duplicados consecutivos (<=120s) en OfflineChatVault, sincroniza FTS5 y compacta."""
        t0 = time.perf_counter()
        p = Path(db_path)
        if not p.is_file():
            return {"ok": True, "skipped": True, "reason": "db_not_found", "path": str(p)}

        bytes_before = _db_total_bytes(p)
        con = sqlite3.connect(str(p), timeout=15.0)
        con.execute("PRAGMA busy_timeout=10000")
        try:
            turns = con.execute(
                "SELECT id, ts, session_id, user_message, assistant_reply FROM offline_chat_turns ORDER BY id ASC"
            ).fetchall()
            last_seen: Dict[Tuple[str, str, str], float] = {}
            dup_ids: List[int] = []
            for tid, ts, sess, umsg, areply in turns:
                key = (str(sess or ""), _normalize_text_key(str(umsg or ""))[:200], _normalize_text_key(str(areply or ""))[:200])
                prev_ts = last_seen.get(key)
                if prev_ts is not None and abs(float(ts or 0.0) - prev_ts) <= 120.0:
                    dup_ids.append(int(tid))
                else:
                    last_seen[key] = float(ts or 0.0)

            pruned = 0
            maint: Dict[str, Any] = {}
            freelist = int(con.execute("PRAGMA freelist_count").fetchone()[0])
            if not dry_run:
                for tid in dup_ids:
                    try:
                        con.execute("DELETE FROM offline_chat_fts WHERE turn_id = ?", (tid,))
                    except Exception:
                        pass
                    cur = con.execute("DELETE FROM offline_chat_turns WHERE id = ?", (tid,))
                    pruned += max(0, int(cur.rowcount or 0))
                con.commit()
                maint = _safe_sqlite_maintain(con, do_vacuum=(pruned > 0 or freelist >= 16))
            else:
                pruned = len(dup_ids)
        finally:
            con.close()

        bytes_after = _db_total_bytes(p)
        return {
            "ok": True,
            "target": "offline_chats",
            "path": str(p),
            "dry_run": dry_run,
            "turns_scanned": len(turns),
            "duplicates_pruned": pruned,
            "freelist_pages_before": freelist,
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
            "bytes_reclaimed": max(0, bytes_before - bytes_after),
            "maintenance": maint,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # ------------------------------------------------------------------ 5. Telemetry TTL + WAL (subsystem_agents & gods_eye)
    def compact_subsystem_agents(
        self,
        db_path: Path = DEFAULT_SUBSYSTEM_AGENTS_DB,
        *,
        dry_run: bool = False,
        retention_days: float = DEFAULT_SUBSYSTEM_RETENTION_DAYS,
    ) -> Dict[str, Any]:
        """
        Retención TTL para `subsystem_agents.db`:
          - Consolida ciclos antiguos (> retention_days) en `cycles_daily_rollup` (sin pérdida estadística).
          - Poda el JSON crudo expirado, migra `journal_mode=delete -> WAL`, crea `idx_cycles_ts` y hace VACUUM.
        """
        t0 = time.perf_counter()
        p = Path(db_path)
        if not p.is_file():
            return {"ok": True, "skipped": True, "reason": "db_not_found", "path": str(p)}

        bytes_before = _db_total_bytes(p)
        cutoff = time.time() - max(1.0, float(retention_days)) * 86400.0
        con = sqlite3.connect(str(p), timeout=20.0)
        con.execute("PRAGMA busy_timeout=15000")
        try:
            jm_before = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            total_rows = int(con.execute("SELECT COUNT(*) FROM cycles").fetchone()[0])
            expired_rows = int(con.execute("SELECT COUNT(*) FROM cycles WHERE ts < ?", (cutoff,)).fetchone()[0])

            rollup_groups = 0
            pruned = 0
            jm_after = jm_before
            maint: Dict[str, Any] = {}

            if not dry_run:
                con.execute("PRAGMA journal_mode=WAL")
                con.execute("PRAGMA synchronous=NORMAL")
                con.execute("CREATE INDEX IF NOT EXISTS idx_cycles_ts ON cycles(ts)")
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cycles_daily_rollup (
                        day TEXT NOT NULL,
                        subsystem TEXT NOT NULL,
                        cycles_count INTEGER NOT NULL DEFAULT 0,
                        ok_count INTEGER NOT NULL DEFAULT 0,
                        degraded_count INTEGER NOT NULL DEFAULT 0,
                        total_findings INTEGER NOT NULL DEFAULT 0,
                        first_ts REAL NOT NULL,
                        last_ts REAL NOT NULL,
                        updated_iso TEXT NOT NULL,
                        UNIQUE(day, subsystem)
                    )
                    """
                )
                if expired_rows > 0:
                    agg_rows = con.execute(
                        """
                        SELECT date(ts, 'unixepoch', 'localtime') AS day,
                               COALESCE(subsystem, 'unknown') AS subsystem,
                               COUNT(*) AS cnt,
                               SUM(CASE WHEN lower(COALESCE(health, '')) IN ('online', 'ok', 'healthy') THEN 1 ELSE 0 END) AS ok_cnt,
                               SUM(CASE WHEN lower(COALESCE(health, '')) NOT IN ('online', 'ok', 'healthy') THEN 1 ELSE 0 END) AS deg_cnt,
                               COALESCE(SUM(COALESCE(findings, 0)), 0) AS tot_find,
                               MIN(ts) AS f_ts,
                               MAX(ts) AS l_ts
                        FROM cycles
                        WHERE ts < ?
                        GROUP BY day, subsystem
                        """,
                        (cutoff,),
                    ).fetchall()
                    now_iso = _now_iso()
                    for day, sub, cnt, ok_c, deg_c, tot_f, f_ts, l_ts in agg_rows:
                        con.execute(
                            """
                            INSERT INTO cycles_daily_rollup (
                                day, subsystem, cycles_count, ok_count, degraded_count,
                                total_findings, first_ts, last_ts, updated_iso
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(day, subsystem) DO UPDATE SET
                                cycles_count = cycles_daily_rollup.cycles_count + excluded.cycles_count,
                                ok_count = cycles_daily_rollup.ok_count + excluded.ok_count,
                                degraded_count = cycles_daily_rollup.degraded_count + excluded.degraded_count,
                                total_findings = cycles_daily_rollup.total_findings + excluded.total_findings,
                                first_ts = MIN(cycles_daily_rollup.first_ts, excluded.first_ts),
                                last_ts = MAX(cycles_daily_rollup.last_ts, excluded.last_ts),
                                updated_iso = excluded.updated_iso
                            """,
                            (str(day or "unknown"), str(sub), int(cnt), int(ok_c or 0), int(deg_c or 0), int(tot_f or 0), float(f_ts), float(l_ts), now_iso),
                        )
                        rollup_groups += 1
                    cur = con.execute("DELETE FROM cycles WHERE ts < ?", (cutoff,))
                    pruned = max(0, int(cur.rowcount or 0))
                con.commit()
                maint = _safe_sqlite_maintain(con, do_vacuum=(pruned > 0 or jm_before != "wal"))
                jm_after = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            else:
                pruned = expired_rows
        finally:
            con.close()

        bytes_after = _db_total_bytes(p)
        return {
            "ok": True,
            "target": "subsystem_agents",
            "path": str(p),
            "dry_run": dry_run,
            "retention_days": retention_days,
            "journal_mode_before": jm_before,
            "journal_mode_after": jm_after,
            "rows_scanned": total_rows,
            "duplicates_pruned": pruned,
            "expired_rows_pruned": pruned,
            "rollup_groups_saved": rollup_groups,
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
            "bytes_reclaimed": max(0, bytes_before - bytes_after),
            "maintenance": maint,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def compact_gods_eye(
        self,
        db_path: Path = DEFAULT_GODS_EYE_DB,
        *,
        dry_run: bool = False,
        detections_retention_days: float = DEFAULT_GODS_EYE_DETECTIONS_RETENTION_DAYS,
        events_retention_days: float = DEFAULT_GODS_EYE_EVENTS_RETENTION_DAYS,
    ) -> Dict[str, Any]:
        """
        Retención TTL y migración WAL para `gods_eye.db`:
          - Consolida `detections` antiguas (> detections_retention_days) en `detections_daily_rollup`
            y `events` antiguos (> events_retention_days) en `events_daily_rollup`.
          - Migra `journal_mode=delete -> WAL` y ejecuta VACUUM + ANALYZE.
        """
        t0 = time.perf_counter()
        p = Path(db_path)
        if not p.is_file():
            return {"ok": True, "skipped": True, "reason": "db_not_found", "path": str(p)}

        bytes_before = _db_total_bytes(p)
        now = time.time()
        det_cutoff = now - max(1.0, float(detections_retention_days)) * 86400.0
        evt_cutoff = now - max(1.0, float(events_retention_days)) * 86400.0

        con = sqlite3.connect(str(p), timeout=20.0)
        con.execute("PRAGMA busy_timeout=15000")
        try:
            jm_before = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            det_total = int(con.execute("SELECT COUNT(*) FROM detections").fetchone()[0])
            evt_total = int(con.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            det_expired = int(con.execute("SELECT COUNT(*) FROM detections WHERE ts < ?", (det_cutoff,)).fetchone()[0])
            evt_expired = int(con.execute("SELECT COUNT(*) FROM events WHERE ts < ?", (evt_cutoff,)).fetchone()[0])

            det_pruned = 0
            evt_pruned = 0
            det_rollups = 0
            evt_rollups = 0
            jm_after = jm_before
            maint: Dict[str, Any] = {}

            if not dry_run:
                con.execute("PRAGMA journal_mode=WAL")
                con.execute("PRAGMA synchronous=NORMAL")
                con.execute("CREATE INDEX IF NOT EXISTS idx_det_ts ON detections(ts)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_evt_ts ON events(ts)")
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS detections_daily_rollup (
                        day TEXT NOT NULL,
                        terminal_id TEXT NOT NULL,
                        detections_count INTEGER NOT NULL DEFAULT 0,
                        sum_motion REAL NOT NULL DEFAULT 0.0,
                        max_motion REAL NOT NULL DEFAULT 0.0,
                        total_objects INTEGER NOT NULL DEFAULT 0,
                        first_ts REAL NOT NULL,
                        last_ts REAL NOT NULL,
                        updated_iso TEXT NOT NULL,
                        UNIQUE(day, terminal_id)
                    )
                    """
                )
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events_daily_rollup (
                        day TEXT NOT NULL,
                        terminal_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        events_count INTEGER NOT NULL DEFAULT 0,
                        sum_confidence REAL NOT NULL DEFAULT 0.0,
                        first_ts REAL NOT NULL,
                        last_ts REAL NOT NULL,
                        updated_iso TEXT NOT NULL,
                        UNIQUE(day, terminal_id, kind)
                    )
                    """
                )
                now_iso = _now_iso()
                if det_expired > 0:
                    d_aggs = con.execute(
                        """
                        SELECT date(ts, 'unixepoch', 'localtime') AS day,
                               COALESCE(terminal_id, 'unknown') AS tid,
                               COUNT(*) AS cnt,
                               COALESCE(SUM(COALESCE(motion, 0.0)), 0.0) AS s_mot,
                               COALESCE(MAX(COALESCE(motion, 0.0)), 0.0) AS m_mot,
                               COALESCE(SUM(COALESCE(objects, 0)), 0) AS tot_obj,
                               MIN(ts) AS f_ts,
                               MAX(ts) AS l_ts
                        FROM detections
                        WHERE ts < ?
                        GROUP BY day, tid
                        """,
                        (det_cutoff,),
                    ).fetchall()
                    for day, tid, cnt, s_mot, m_mot, tot_obj, f_ts, l_ts in d_aggs:
                        con.execute(
                            """
                            INSERT INTO detections_daily_rollup (
                                day, terminal_id, detections_count, sum_motion, max_motion,
                                total_objects, first_ts, last_ts, updated_iso
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(day, terminal_id) DO UPDATE SET
                                detections_count = detections_daily_rollup.detections_count + excluded.detections_count,
                                sum_motion = detections_daily_rollup.sum_motion + excluded.sum_motion,
                                max_motion = MAX(detections_daily_rollup.max_motion, excluded.max_motion),
                                total_objects = detections_daily_rollup.total_objects + excluded.total_objects,
                                first_ts = MIN(detections_daily_rollup.first_ts, excluded.first_ts),
                                last_ts = MAX(detections_daily_rollup.last_ts, excluded.last_ts),
                                updated_iso = excluded.updated_iso
                            """,
                            (str(day or "unknown"), str(tid), int(cnt), float(s_mot), float(m_mot), int(tot_obj), float(f_ts), float(l_ts), now_iso),
                        )
                        det_rollups += 1
                    cur_d = con.execute("DELETE FROM detections WHERE ts < ?", (det_cutoff,))
                    det_pruned = max(0, int(cur_d.rowcount or 0))

                if evt_expired > 0:
                    e_aggs = con.execute(
                        """
                        SELECT date(ts, 'unixepoch', 'localtime') AS day,
                               COALESCE(terminal_id, 'unknown') AS tid,
                               COALESCE(kind, 'event') AS kind,
                               COUNT(*) AS cnt,
                               COALESCE(SUM(COALESCE(confidence, 0.0)), 0.0) AS s_conf,
                               MIN(ts) AS f_ts,
                               MAX(ts) AS l_ts
                        FROM events
                        WHERE ts < ?
                        GROUP BY day, tid, kind
                        """,
                        (evt_cutoff,),
                    ).fetchall()
                    for day, tid, kind, cnt, s_conf, f_ts, l_ts in e_aggs:
                        con.execute(
                            """
                            INSERT INTO events_daily_rollup (
                                day, terminal_id, kind, events_count, sum_confidence,
                                first_ts, last_ts, updated_iso
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(day, terminal_id, kind) DO UPDATE SET
                                events_count = events_daily_rollup.events_count + excluded.events_count,
                                sum_confidence = events_daily_rollup.sum_confidence + excluded.sum_confidence,
                                first_ts = MIN(events_daily_rollup.first_ts, excluded.first_ts),
                                last_ts = MAX(events_daily_rollup.last_ts, excluded.last_ts),
                                updated_iso = excluded.updated_iso
                            """,
                            (str(day or "unknown"), str(tid), str(kind), int(cnt), float(s_conf), float(f_ts), float(l_ts), now_iso),
                        )
                        evt_rollups += 1
                    cur_e = con.execute("DELETE FROM events WHERE ts < ?", (evt_cutoff,))
                    evt_pruned = max(0, int(cur_e.rowcount or 0))

                con.commit()
                maint = _safe_sqlite_maintain(con, do_vacuum=((det_pruned + evt_pruned) > 0 or jm_before != "wal"))
                jm_after = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            else:
                det_pruned = det_expired
                evt_pruned = evt_expired
        finally:
            con.close()

        bytes_after = _db_total_bytes(p)
        total_pruned = det_pruned + evt_pruned
        return {
            "ok": True,
            "target": "gods_eye",
            "path": str(p),
            "dry_run": dry_run,
            "detections_retention_days": detections_retention_days,
            "events_retention_days": events_retention_days,
            "journal_mode_before": jm_before,
            "journal_mode_after": jm_after,
            "detections_scanned": det_total,
            "events_scanned": evt_total,
            "detections_pruned": det_pruned,
            "events_pruned": evt_pruned,
            "duplicates_pruned": total_pruned,
            "rollup_groups_saved": det_rollups + evt_rollups,
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
            "bytes_reclaimed": max(0, bytes_before - bytes_after),
            "maintenance": maint,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # ------------------------------------------------------------------ 6. Auxiliary WAL checkpoint
    def checkpoint_auxiliary_dbs(
        self,
        db_paths: Sequence[Path] = AUX_WAL_DBS,
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Trunca archivos WAL acumulados y ejecuta PRAGMA optimize en bóvedas de soporte."""
        t0 = time.perf_counter()
        items: List[Dict[str, Any]] = []
        tot_before = 0
        tot_after = 0
        for p in db_paths:
            db_p = Path(p)
            if not db_p.is_file():
                continue
            b0 = _db_total_bytes(db_p)
            tot_before += b0
            if not dry_run:
                try:
                    con = sqlite3.connect(str(db_p), timeout=8.0)
                    con.execute("PRAGMA busy_timeout=5000")
                    try:
                        _safe_sqlite_maintain(con, do_vacuum=False)
                    finally:
                        con.close()
                except Exception as exc:
                    items.append({"db": db_p.name, "ok": False, "error": str(exc)})
                    tot_after += b0
                    continue
            b1 = _db_total_bytes(db_p)
            tot_after += b1
            items.append({"db": db_p.name, "ok": True, "bytes_before": b0, "bytes_after": b1, "bytes_reclaimed": max(0, b0 - b1)})
        return {
            "ok": True,
            "target": "wal",
            "dry_run": dry_run,
            "dbs_checked": len(items),
            "bytes_before": tot_before,
            "bytes_after": tot_after,
            "bytes_reclaimed": max(0, tot_before - tot_after),
            "items": items,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # ------------------------------------------------------------------ Orquestador principal
    def run_compaction(
        self,
        *,
        targets: Optional[Sequence[str]] = None,
        dry_run: bool = False,
        force: bool = False,
        rag_db: Path = DEFAULT_RAG_DB,
        kg_db: Path = DEFAULT_KG_DB,
        deep_memory_db: Path = DEFAULT_DEEP_MEMORY_DB,
        offline_chat_db: Path = DEFAULT_OFFLINE_CHAT_DB,
        subsystem_agents_db: Path = DEFAULT_SUBSYSTEM_AGENTS_DB,
        gods_eye_db: Path = DEFAULT_GODS_EYE_DB,
        aux_dbs: Sequence[Path] = AUX_WAL_DBS,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Ejecuta el ciclo autónomo de compactación respetando la gobernanza Ring 0."""
        t0 = time.perf_counter()
        run_id = f"comp_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        # Guarda Ring 0: nunca competir con llamada Telegram ni presión crítica RED (salvo --force o dry_run)
        if not dry_run and not force and not self._is_isolated:
            try:
                from core.tardis_resource_governor import get_resource_governor

                snap = get_resource_governor().read_fast_snapshot(max_age_s=60.0)
                if snap.get("call_priority_active") or str(snap.get("level") or "").upper() == "RED":
                    deferred_rep = {
                        "ok": True,
                        "schema": "tardis.memory_compactor.v1",
                        "run_id": run_id,
                        "iso": _now_iso(),
                        "dry_run": False,
                        "deferred": True,
                        "reason": f"Diferido por ResourceGovernor (level={snap.get('level')}, call={snap.get('call_priority_active')})",
                        "targets": {},
                    }
                    return deferred_rep
            except Exception:
                pass

        selected = (
            [str(t).strip().lower() for t in targets if str(t).strip().lower() in ALL_TARGETS]
            if targets
            else list(ALL_TARGETS)
        )
        if not selected:
            selected = list(ALL_TARGETS)

        results: Dict[str, Any] = {}
        for tgt in selected:
            if tgt == "rag":
                results["rag"] = self.compact_rag_vault(rag_db, dry_run=dry_run)
            elif tgt == "kg":
                results["kg"] = self.deduplicate_knowledge_graph(kg_db, dry_run=dry_run)
            elif tgt == "deep_memory":
                results["deep_memory"] = self.compact_deep_memory(deep_memory_db, dry_run=dry_run)
            elif tgt == "offline_chats":
                results["offline_chats"] = self.compact_offline_chats(offline_chat_db, dry_run=dry_run)
            elif tgt == "subsystem_agents":
                results["subsystem_agents"] = self.compact_subsystem_agents(subsystem_agents_db, dry_run=dry_run)
            elif tgt == "gods_eye":
                results["gods_eye"] = self.compact_gods_eye(gods_eye_db, dry_run=dry_run)
            elif tgt == "wal":
                results["wal"] = self.checkpoint_auxiliary_dbs(aux_dbs, dry_run=dry_run)

        bytes_before = sum(int(r.get("bytes_before", 0)) for r in results.values())
        bytes_after = sum(int(r.get("bytes_after", 0)) for r in results.values())
        bytes_reclaimed = sum(int(r.get("bytes_reclaimed", 0)) for r in results.values())
        dups_pruned = sum(int(r.get("duplicates_pruned", 0)) for r in results.values())
        kg_merged = int((results.get("kg") or {}).get("nodes_merged", 0))
        episodes_cons = int((results.get("rag") or {}).get("episodes_consolidated", 0))
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        now_ts = time.time()
        iso = _now_iso()

        report = {
            "ok": all(bool(r.get("ok", True)) for r in results.values()),
            "schema": "tardis.memory_compactor.v1",
            "run_id": run_id,
            "ts": now_ts,
            "iso": iso,
            "dry_run": dry_run,
            "deferred": False,
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
            "bytes_reclaimed": bytes_reclaimed,
            "mb_reclaimed": round(bytes_reclaimed / (1024.0 * 1024.0), 3),
            "duplicates_pruned": dups_pruned,
            "kg_nodes_merged": kg_merged,
            "episodes_consolidated": episodes_cons,
            "elapsed_ms": elapsed_ms,
            "targets": results,
        }

        if persist:
            with self._lock:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO compaction_runs (
                            run_id, ts, iso, dry_run, deferred,
                            bytes_before, bytes_after, bytes_reclaimed,
                            duplicates_pruned, kg_nodes_merged, episodes_consolidated,
                            elapsed_ms, report_json
                        )
                        VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            now_ts,
                            iso,
                            1 if dry_run else 0,
                            bytes_before,
                            bytes_after,
                            bytes_reclaimed,
                            dups_pruned,
                            kg_merged,
                            episodes_cons,
                            elapsed_ms,
                            json.dumps(report, ensure_ascii=False),
                        ),
                    )
                    conn.execute(
                        "DELETE FROM compaction_runs WHERE id NOT IN (SELECT id FROM compaction_runs ORDER BY id DESC LIMIT 200)"
                    )

        if not dry_run and not self._is_isolated:
            try:
                from core.tardis_event_bus import get_event_bus

                get_event_bus().publish(
                    "memory.compacted",
                    "tardis_memory_compactor",
                    {
                        "run_id": run_id,
                        "mb_reclaimed": report["mb_reclaimed"],
                        "duplicates_pruned": dups_pruned,
                        "kg_nodes_merged": kg_merged,
                        "episodes_consolidated": episodes_cons,
                        "elapsed_ms": elapsed_ms,
                    },
                    severity="INFO",
                    dedup_window_s=60.0,
                )
            except Exception:
                pass

        return report

    def history(self, limit: int = 15) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, iso, dry_run, deferred, bytes_reclaimed, duplicates_pruned, kg_nodes_merged, episodes_consolidated, elapsed_ms "
                "FROM compaction_runs ORDER BY id DESC LIMIT ?",
                (max(1, min(100, int(limit))),),
            ).fetchall()
        return [
            {
                "run_id": str(r["run_id"]),
                "iso": str(r["iso"]),
                "dry_run": bool(r["dry_run"]),
                "deferred": bool(r["deferred"]),
                "mb_reclaimed": round(int(r["bytes_reclaimed"]) / (1024.0 * 1024.0), 3),
                "duplicates_pruned": int(r["duplicates_pruned"]),
                "kg_nodes_merged": int(r["kg_nodes_merged"]),
                "episodes_consolidated": int(r["episodes_consolidated"]),
                "elapsed_ms": float(r["elapsed_ms"]),
            }
            for r in rows
        ]

    def status(self) -> Dict[str, Any]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM compaction_runs").fetchone()[0])
            real_runs = int(conn.execute("SELECT COUNT(*) FROM compaction_runs WHERE dry_run = 0").fetchone()[0])
            tot_bytes = int(conn.execute("SELECT COALESCE(SUM(bytes_reclaimed), 0) FROM compaction_runs WHERE dry_run = 0").fetchone()[0])
            tot_dups = int(conn.execute("SELECT COALESCE(SUM(duplicates_pruned), 0) FROM compaction_runs WHERE dry_run = 0").fetchone()[0])
            tot_kg = int(conn.execute("SELECT COALESCE(SUM(kg_nodes_merged), 0) FROM compaction_runs WHERE dry_run = 0").fetchone()[0])
        hist = self.history(limit=1)
        vault_sizes_mb = {
            "rag_vault": round(_db_total_bytes(DEFAULT_RAG_DB) / (1024.0 * 1024.0), 2),
            "knowledge_graph": round(_db_total_bytes(DEFAULT_KG_DB) / (1024.0 * 1024.0), 2),
            "deep_memory": round(_db_total_bytes(DEFAULT_DEEP_MEMORY_DB) / (1024.0 * 1024.0), 2),
            "offline_chats": round(_db_total_bytes(DEFAULT_OFFLINE_CHAT_DB) / (1024.0 * 1024.0), 2),
            "subsystem_agents": round(_db_total_bytes(DEFAULT_SUBSYSTEM_AGENTS_DB) / (1024.0 * 1024.0), 2),
            "gods_eye": round(_db_total_bytes(DEFAULT_GODS_EYE_DB) / (1024.0 * 1024.0), 2),
        }
        return {
            "ok": True,
            "schema": "tardis.memory_compactor.v1",
            "targets": list(ALL_TARGETS),
            "db_path": str(self.db_path),
            "total_runs": total,
            "applied_runs": real_runs,
            "cumulative_mb_reclaimed": round(tot_bytes / (1024.0 * 1024.0), 3),
            "cumulative_duplicates_pruned": tot_dups,
            "cumulative_kg_nodes_merged": tot_kg,
            "vault_sizes_mb": vault_sizes_mb,
            "latest": hist[0] if hist else None,
        }


def get_memory_compactor(db_path: Optional[Path] = None) -> TardisMemoryCompactor:
    return TardisMemoryCompactor.get_instance(db_path=db_path)


# ---------------------------------------------------------------------- CLI Soberana
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="tardis-compact",
        description="TARDIS Autonomous Memory Compactor & Knowledge Graph Deduplicator",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="Estado del compactador y tamaño actual de las bóvedas")
    sub.add_parser("audit", help="Ejecutar auditoría dry-run segura sin modificar ninguna bóveda")
    p_run = sub.add_parser("run", help="Ejecutar compactación y deduplicación en bóvedas SQLite")
    p_run.add_argument("--targets", default="", help="Lista separada por comas: rag,kg,deep_memory,offline_chats,subsystem_agents,gods_eye,wal")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--force", action="store_true", help="Ignorar diferimiento Ring 0 en RED")
    p_hist = sub.add_parser("history", help="Histórico de ejecuciones de compactación")
    p_hist.add_argument("--limit", type=int, default=15)

    args = ap.parse_args(argv)
    comp = get_memory_compactor()

    if args.cmd == "status":
        print(json.dumps(comp.status(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "history":
        print(json.dumps({"ok": True, "history": comp.history(limit=args.limit)}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "audit":
        res = comp.run_compaction(dry_run=True, persist=True)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    if args.cmd == "run":
        t_list = [t.strip() for t in args.targets.split(",") if t.strip()] if args.targets else None
        res = comp.run_compaction(targets=t_list, dry_run=args.dry_run, force=args.force, persist=True)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
