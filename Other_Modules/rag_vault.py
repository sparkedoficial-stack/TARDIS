"""
core/rag_vault.py - Boveda RAG Semantica y Ontologica de TARDIS
===============================================================
GODWORKS SYSTEM

Recuperacion aumentada (RAG) y memoria cognitiva transversal para el modelo local,
sin dependencias pesadas (solo numpy + sqlite3 + httpx):

  * Embeddings densos multilingues (multilingual-e5-small) servidos por un
    llama-server dedicado en CPU (socket /tmp/embed_brain.sock), sin tocar la VRAM.
  * Busqueda HIBRIDA: coseno denso (comprension semantica) fusionado con BM25 via
    FTS5 de SQLite (coincidencia exacta de terminologia), por Reciprocal Rank Fusion.
  * Grafo de Conocimiento Soberano (GraphRAG): extraccion automatica de tripletas
    relacionales (sujeto, predicado, objeto) integradas con core.knowledge_graph.
  * Abstraccion Jerarquica (RAPTOR): almacenamiento y recuperacion multi-escala
    (fragmentos micro, sintesis meso de cluster, y vision macro global).
  * Auto-Cosecha y Evaluacion Correctiva (CRAG): evaluacion de confianza local; si la
    boveda no tiene la informacion, investiga en internet (core.web_research_engine),
    la fragmenta, extrae terminos/relaciones, la vectoriza y la persiste.
  * Cache de terminologia y conceptos: definiciones aprendidas se guardan y reutilizan
    con latencia de 0 ms en turnos posteriores.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import struct
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
import numpy as np

from core.knowledge_graph import get_knowledge_graph

logger = logging.getLogger("GODWORKS.RAGVault")

BASE_DIR = Path(__file__).resolve().parent.parent
VAULT_DIR = BASE_DIR / "data"
VAULT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = VAULT_DIR / "rag_vault.db"

EMBED_SOCKET = "/tmp/embed_brain.sock"
EMBED_DIM = 384

# e5 exige prefijos: las consultas van con "query:" y los pasajes con "passage:"
Q_PREFIX = "query: "
P_PREFIX = "passage: "

CHUNK_CHARS = 1100          # ~300 tokens por fragmento
CHUNK_OVERLAP = 180
RRF_K = 60                  # constante de Reciprocal Rank Fusion
WEB_FALLBACK_MIN_SCORE = 0.032   # score fusionado por debajo del cual se busca en web


class RAGVault:
    _instance: Optional["RAGVault"] = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "RAGVault":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self.db_path = DB_PATH
        self.embed_socket = EMBED_SOCKET
        self._mat: Optional[np.ndarray] = None       # matriz (N, dim) cacheada
        self._ids: List[int] = []                     # chunk_id por fila de la matriz
        self._mat_dirty = True
        self.kg = get_knowledge_graph()
        self._init_db()

    # ---------------------------------------------------------------- sqlite
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=20.0, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_db(self) -> None:
        con = self._connect()
        try:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL,
                source TEXT NOT NULL,
                url TEXT,
                title TEXT,
                term TEXT,
                text TEXT NOT NULL,
                ts REAL NOT NULL,
                chunk_hash TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS rag_vectors (
                chunk_id INTEGER PRIMARY KEY,
                vec BLOB NOT NULL,
                FOREIGN KEY (chunk_id) REFERENCES rag_chunks(id) ON DELETE CASCADE
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(
                text, title, term, content=''
            );
            CREATE TABLE IF NOT EXISTS rag_terms (
                term TEXT PRIMARY KEY,
                definition TEXT NOT NULL,
                sources TEXT,
                updated_ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rag_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_term TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_term TEXT NOT NULL,
                evidence TEXT,
                chunk_id INTEGER,
                weight REAL DEFAULT 1.0,
                ts REAL NOT NULL,
                UNIQUE(source_term, relation, target_term)
            );
            CREATE TABLE IF NOT EXISTS rag_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level INTEGER NOT NULL DEFAULT 1,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                cluster_tag TEXT DEFAULT '',
                chunk_ids TEXT DEFAULT '[]',
                ts REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_doc ON rag_chunks(doc_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_term ON rag_chunks(term);
            CREATE INDEX IF NOT EXISTS idx_rag_rel_src ON rag_relations(source_term);
            CREATE INDEX IF NOT EXISTS idx_rag_rel_tgt ON rag_relations(target_term);
            CREATE INDEX IF NOT EXISTS idx_rag_rel_rel ON rag_relations(relation);
            CREATE INDEX IF NOT EXISTS idx_rag_sum_level ON rag_summaries(level);
            """)
            con.commit()
        finally:
            con.close()

    # -------------------------------------------------------------- embeddings
    def embed(self, texts: List[str], kind: str = "passage", timeout: float = 30.0) -> np.ndarray:
        """Vectoriza una lista de textos. kind: 'query' o 'passage' (prefijo e5). Conmutación distribuida a iMac 14,1."""
        if not texts:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)

        # 1. Intentar servidor local por socket UDS
        try:
            prefix = Q_PREFIX if kind == "query" else P_PREFIX
            payload = {"input": [prefix + (t or "").strip() for t in texts]}
            transport = httpx.HTTPTransport(uds=self.embed_socket)
            with httpx.Client(transport=transport, base_url="http://localhost", timeout=timeout) as client:
                r = client.post("/v1/embeddings", json=payload)
                r.raise_for_status()
                data = r.json()["data"]
            vecs = np.array([d["embedding"] for d in data], dtype=np.float32)
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            return vecs / norms
        except Exception as e_local:
            logger.debug(f"[RAGVault] Socket UDS no disponible ({e_local}). Conmutando vectorización a iMac 14,1...")

        # 2. Conmutación a nodo satélite iMac 14,1 (all-minilm:latest 384-dim)
        try:
            from core.tardis_distributed_mesh import get_mesh
            return get_mesh().distribute_embeddings(texts, timeout_sec=timeout)
        except Exception as e_imac:
            logger.warning(f"[RAGVault] Fallo en embeddings locales y distribuidos ({e_imac})")
            return np.zeros((len(texts), EMBED_DIM), dtype=np.float32)

    def embed_available(self) -> bool:
        try:
            transport = httpx.HTTPTransport(uds=self.embed_socket)
            with httpx.Client(transport=transport, base_url="http://localhost", timeout=2.0) as c:
                if c.get("/health").status_code == 200:
                    return True
        except Exception:
            pass
        # Comprobar si iMac 14,1 está disponible
        try:
            with httpx.Client(timeout=1.5) as c:
                return c.get("http://REDACTED_IP:11434/api/tags").status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------- fragmentado
    @staticmethod
    def _chunk(text: str) -> List[str]:
        text = re.sub(r"\s+", " ", (text or "")).strip()
        if not text:
            return []
        if len(text) <= CHUNK_CHARS:
            return [text]
        chunks, start = [], 0
        while start < len(text):
            end = start + CHUNK_CHARS
            # cortar en un limite de oracion cercano para no partir ideas
            if end < len(text):
                dot = text.rfind(". ", start + CHUNK_CHARS - 300, end)
                if dot > start:
                    end = dot + 1
            chunks.append(text[start:end].strip())
            start = end - CHUNK_OVERLAP
        return [c for c in chunks if c]

    # ----------------------------------------- extraccion ontologica y semantica
    @staticmethod
    def extract_relations_and_terms(text: str) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
        """
        Extractor semantico rapido y determinista basado en patrones sintacticos:
        - Detecta relaciones: conecta_con, depende_de, implementa, optimiza, causa, parte_de, analogo_a.
        - Detecta definiciones terminologicas: X es ..., X se define como ..., X consiste en ...
        """
        relations: List[Dict[str, Any]] = []
        definitions: List[Tuple[str, str]] = []

        # 1. Definiciones terminologicas: Termino es / se define como ...
        def_patterns = [
            r"([A-Z][a-zA-Z0-9_\-\s]{2,40}?)\s+(?:se define como|es un|es una|consiste en|refers to|is defined as)\s+([^.\n]{15,300}\.)",
            r"([A-Z][a-zA-Z0-9_\-\s]{2,40}?):\s+([^.\n]{15,300}\.)",
        ]
        for pat in def_patterns:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                t = m.group(1).strip()
                d = m.group(2).strip()
                if len(t.split()) <= 5 and not t.lower().startswith(("el ", "la ", "los ", "las ", "un ", "una ")):
                    definitions.append((t, d))

        # 2. Relaciones estructurales y causales
        rel_rules = [
            (r"([A-Za-z0-9_\-\s]{3,35})\s+(?:conecta con|se conecta a|connects to|interconecta con)\s+([A-Za-z0-9_\-\s]{3,35})", "conecta_con"),
            (r"([A-Za-z0-9_\-\s]{3,35})\s+(?:depende de|requiere de|depends on|relies on)\s+([A-Za-z0-9_\-\s]{3,35})", "depende_de"),
            (r"([A-Za-z0-9_\-\s]{3,35})\s+(?:implementa|is implemented by|implements)\s+([A-Za-z0-9_\-\s]{3,35})", "implementa"),
            (r"([A-Za-z0-9_\-\s]{3,35})\s+(?:optimiza|acelera|reduces|improves|mejora)\s+([A-Za-z0-9_\-\s]{3,35})", "optimiza"),
            (r"([A-Za-z0-9_\-\s]{3,35})\s+(?:causa|genera|provoca|triggers|causes)\s+([A-Za-z0-9_\-\s]{3,35})", "causa"),
            (r"([A-Za-z0-9_\-\s]{3,35})\s+(?:forma parte de|es componente de|is part of)\s+([A-Za-z0-9_\-\s]{3,35})", "parte_de"),
            (r"([A-Za-z0-9_\-\s]{3,35})\s+(?:es analogo a|es semejante a|is analogous to)\s+([A-Za-z0-9_\-\s]{3,35})", "analogo_a"),
        ]

        sentences = [s.strip() for s in re.split(r"[.\n]", text) if len(s.strip()) > 15]
        for s in sentences:
            for pat, rel_type in rel_rules:
                match = re.search(pat, s, flags=re.IGNORECASE)
                if match:
                    src = match.group(1).strip()
                    tgt = match.group(2).strip()
                    # Filtrar palabras vacias o fragmentos invalidos
                    if 3 <= len(src) <= 35 and 3 <= len(tgt) <= 35 and src.lower() != tgt.lower():
                        relations.append({
                            "source": src,
                            "relation": rel_type,
                            "target": tgt,
                            "evidence": s[:240],
                        })

        return relations, definitions

    # ------------------------------------------------------------------ ingesta
    def ingest(self, text: str, source: str = "manual", url: str = "",
               title: str = "", term: str = "") -> Dict[str, Any]:
        """Fragmenta, vectoriza, extrae relaciones e indexa en la boveda y el grafo."""
        chunks = self._chunk(text)
        if not chunks:
            return {"ok": False, "reason": "texto vacio", "stored": 0}
        doc_id = hashlib.sha256((url or title or text[:200]).encode()).hexdigest()[:16]
        now = time.time()

        # filtrar duplicados por hash antes de vectorizar (ahorra computo)
        con = self._connect()
        fresh: List[Tuple[str, str]] = []
        try:
            for c in chunks:
                h = hashlib.sha256(c.encode()).hexdigest()
                if not con.execute("SELECT 1 FROM rag_chunks WHERE chunk_hash=?", (h,)).fetchone():
                    fresh.append((c, h))
        finally:
            con.close()

        if not fresh:
            return {"ok": True, "stored": 0, "reason": "ya indexado", "doc_id": doc_id}

        vecs = self.embed([c for c, _ in fresh], kind="passage")

        con = self._connect()
        stored = 0
        inserted_chunk_ids = []
        try:
            for (c, h), v in zip(fresh, vecs):
                cur = con.execute(
                    "INSERT OR IGNORE INTO rag_chunks(doc_id,source,url,title,term,text,ts,chunk_hash) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (doc_id, source, url, title, term, c, now, h),
                )
                if cur.lastrowid and cur.rowcount:
                    cid = cur.lastrowid
                    inserted_chunk_ids.append(cid)
                    con.execute("INSERT OR REPLACE INTO rag_vectors(chunk_id,vec) VALUES (?,?)",
                                (cid, v.astype(np.float32).tobytes()))
                    con.execute("INSERT INTO rag_fts(rowid,text,title,term) VALUES (?,?,?,?)",
                                (cid, c, title, term))
                    stored += 1
            con.commit()
        finally:
            con.close()

        self._mat_dirty = True

        # Extraer relaciones y terminos para poblar la red ontologica
        extracted_rels, extracted_defs = self.extract_relations_and_terms(text)
        con = self._connect()
        try:
            # Guardar definiciones
            for t_name, t_def in extracted_defs:
                con.execute(
                    "INSERT OR REPLACE INTO rag_terms (term, definition, sources, updated_ts) VALUES (?, ?, ?, ?)",
                    (t_name.lower().strip(), t_def, url or title or source, now)
                )
            # Guardar relaciones y alimentar KnowledgeGraph
            for rel in extracted_rels:
                con.execute(
                    """
                    INSERT OR IGNORE INTO rag_relations (source_term, relation, target_term, evidence, chunk_id, weight, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (rel["source"].lower(), rel["relation"], rel["target"].lower(),
                     rel["evidence"], inserted_chunk_ids[0] if inserted_chunk_ids else None, 1.0, now)
                )
                # Sincronizar con el Grafo de Conocimiento Soberano
                self.kg.add_edge(
                    rel["source"],
                    rel["target"],
                    relation=rel["relation"],
                    evidence=rel["evidence"],
                )
            con.commit()
        finally:
            con.close()

        logger.info(f"[RAG] Ingeridos {stored} fragmentos, {len(extracted_defs)} terminos y {len(extracted_rels)} relaciones de '{title or url or source}'")
        return {
            "ok": True,
            "stored": stored,
            "doc_id": doc_id,
            "source": source,
            "extracted_terms": len(extracted_defs),
            "extracted_relations": len(extracted_rels),
        }

    # ---------------------------------------------------- resúmenes jerárquicos (RAPTOR)
    def add_summary(self, title: str, summary: str, level: int = 1,
                    cluster_tag: str = "", chunk_ids: Optional[List[int]] = None) -> int:
        """Almacena un resumen jerarquico (RAPTOR) para comprension macro y sintesis global."""
        now = time.time()
        c_ids_json = json.dumps(chunk_ids or [])
        con = self._connect()
        try:
            cur = con.execute(
                """
                INSERT INTO rag_summaries (level, title, summary, cluster_tag, chunk_ids, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (level, title, summary, cluster_tag, c_ids_json, now)
            )
            con.commit()
            sid = cur.lastrowid
        finally:
            con.close()
        # Registrar tambien como nodo conceptual clave en el grafo
        self.kg.add_node(title, entity_type=f"macro_summary_lvl{level}", description=summary[:300])
        return int(sid)

    def get_summaries(self, level: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        con = self._connect()
        try:
            if level is not None:
                rows = con.execute(
                    "SELECT id, level, title, summary, cluster_tag, ts FROM rag_summaries WHERE level = ? ORDER BY ts DESC LIMIT ?",
                    (level, limit)
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT id, level, title, summary, cluster_tag, ts FROM rag_summaries ORDER BY level DESC, ts DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [
                {"id": r[0], "level": r[1], "title": r[2], "summary": r[3], "cluster_tag": r[4], "ts": r[5]}
                for r in rows
            ]
        finally:
            con.close()

    # ----------------------------------------------------------- matriz densa
    def _load_matrix(self) -> None:
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT chunk_id, vec FROM rag_vectors ORDER BY chunk_id"
            ).fetchall()
        finally:
            con.close()
        if not rows:
            self._mat = np.zeros((0, EMBED_DIM), dtype=np.float32)
            self._ids = []
        else:
            self._ids = [r[0] for r in rows]
            self._mat = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), EMBED_DIM)
        self._mat_dirty = False

    # --------------------------------------------------------------- busqueda
    def _dense_search(self, query: str, k: int) -> List[Tuple[int, float]]:
        if self._mat is None or self._mat_dirty:
            self._load_matrix()
        if self._mat is None or self._mat.shape[0] == 0:
            return []
        qv = self.embed([query], kind="query")[0]
        sims = self._mat @ qv                     # coseno (todo normalizado)
        top = np.argsort(-sims)[:k]
        return [(self._ids[i], float(sims[i])) for i in top]

    def _bm25_search(self, query: str, k: int) -> List[Tuple[int, float]]:
        terms = re.findall(r"\w+", query, flags=re.UNICODE)
        if not terms:
            return []
        match = " OR ".join(terms)
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT rowid, rank FROM rag_fts WHERE rag_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, k),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        finally:
            con.close()
        return [(int(r[0]), float(r[1])) for r in rows]

    def search(self, query: str, k: int = 6, hybrid: bool = True) -> List[Dict[str, Any]]:
        """Busqueda hibrida (denso + BM25) fusionada por Reciprocal Rank Fusion."""
        dense = self._dense_search(query, k * 3) if self.embed_available() else []
        bm25 = self._bm25_search(query, k * 3) if hybrid else []

        fused: Dict[int, float] = {}
        for rank, (cid, _) in enumerate(dense):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
        for rank, (cid, _) in enumerate(bm25):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
        if not fused:
            return []

        dense_map = dict(dense)
        order = sorted(fused.items(), key=lambda x: -x[1])[:k]
        ids = [cid for cid, _ in order]
        con = self._connect()
        try:
            qmarks = ",".join("?" * len(ids))
            meta = {r[0]: r for r in con.execute(
                f"SELECT id, text, title, url, source, term FROM rag_chunks WHERE id IN ({qmarks})", ids
            ).fetchall()}
        finally:
            con.close()

        out = []
        for cid, score in order:
            if cid not in meta:
                continue
            _, text, title, url, source, term = meta[cid]
            out.append({
                "chunk_id": cid, "text": text, "title": title, "url": url,
                "source": source, "term": term,
                "fused_score": round(score, 5),
                "dense_score": round(dense_map.get(cid, 0.0), 4),
            })
        return out

    # --------------------------------------------- evaluador de confianza (CRAG)
    def evaluate_confidence(self, hits: List[Dict[str, Any]],
                            min_score: float = WEB_FALLBACK_MIN_SCORE) -> Dict[str, Any]:
        """
        Evaluador Correctivo RAG (CRAG):
        - CORRECT: Confianza solida para responder directamente con memoria local.
        - AMBIGUOUS: Coincidencias debiles o difusas; se sugiere enriquecer con busqueda.
        - MISSING: Ausencia de informacion en la memoria local; requiere fallback web inmediato.
        """
        if not hits:
            return {"status": "MISSING", "confidence": 0.0, "action": "web_fallback"}

        best_score = hits[0].get("fused_score", 0.0)
        dense_score = hits[0].get("dense_score", 0.0)

        if best_score >= min_score and dense_score >= 0.70:
            return {"status": "CORRECT", "confidence": round(best_score, 4), "action": "generate"}
        elif best_score >= (min_score * 0.75):
            return {"status": "AMBIGUOUS", "confidence": round(best_score, 4), "action": "refine_or_web"}
        else:
            return {"status": "MISSING", "confidence": round(best_score, 4), "action": "web_fallback"}

    # -------------------------------------------------- recuperar o investigar
    def retrieve(self, query: str, k: int = 6, allow_web: bool = True,
                 min_score: float = WEB_FALLBACK_MIN_SCORE) -> Dict[str, Any]:
        """
        Busca en la boveda. Si la confianza es insuficiente y allow_web=True,
        investiga en internet mediante CRAG, lo almacena y vuelve a buscar.
        """
        hits = self.search(query, k=k)
        crag = self.evaluate_confidence(hits, min_score=min_score)
        researched = False

        if allow_web and crag["action"] == "web_fallback":
            logger.info(f"[RAG-CRAG] Confianza insuficiente ({crag['status']} score={crag['confidence']}). Activando fallback web para: {query[:80]}")
            researched = self._research_and_store(query)
            if researched:
                self._mat_dirty = True
                hits = self.search(query, k=k)
                crag = self.evaluate_confidence(hits, min_score=min_score)

        return {
            "query": query,
            "hits": hits,
            "researched_web": researched,
            "crag_status": crag["status"],
            "confidence": crag["confidence"],
            "grounded": bool(hits),
        }

    def _research_and_store(self, query: str) -> bool:
        try:
            from core.web_research_engine import get_web_research_engine
            eng = get_web_research_engine()
            report = eng.deep_research(query, max_sources=3, max_chars_per_page=3500,
                                       use_llm_synthesis=False)
        except Exception as e:
            logger.warning(f"[RAG] Investigacion web fallida: {e}")
            return False

        stored_any = False
        for src in getattr(report, "sources", []) or []:
            content = src.get("content") or src.get("snippet") or ""
            if len(content) < 120:
                continue
            res = self.ingest(content, source="web",
                              url=src.get("url", ""), title=src.get("title", query))
            stored_any = stored_any or res.get("stored", 0) > 0

        syn = getattr(report, "synthesis", "") or ""
        if len(syn) > 120:
            r = self.ingest(syn, source="web_synthesis", title=query, term=query)
            stored_any = stored_any or r.get("stored", 0) > 0
        return stored_any

    # --------------------------------- recuperacion transversal (GraphRAG + RAPTOR)
    def transversal_retrieve(self, query: str, k: int = 5, allow_web: bool = True,
                             explore_graph: bool = True) -> Dict[str, Any]:
        """
        Recuperacion cognitiva transversal:
        1. Recupera fragmentos puntuales (Hojas del arbol / Hybrid RAG).
        2. Extrae entidades y expande relaciones en el Grafo de Conocimiento (GraphRAG).
        3. Recupera sintesis jerarquicas de alto nivel (RAPTOR).
        4. Cruza definiciones canónicas ancladas.
        """
        base_res = self.retrieve(query, k=k, allow_web=allow_web)
        hits = base_res.get("hits", [])

        graph_connections: List[Dict[str, Any]] = []
        matched_terms: List[Dict[str, Any]] = []
        summaries: List[Dict[str, Any]] = []

        if explore_graph:
            # Buscar nodos existentes en el Grafo mediante coincidencia de frases y conceptos
            matching_nodes = self.kg.find_matching_nodes(query, max_nodes=6)
            found_nodes = [n["name"] for n in matching_nodes]

            # Enriquecer con terminos presentes en los mejores hits recuperados
            for h in hits[:2]:
                if h.get("term") and h["term"] not in found_nodes:
                    node_h = self.kg.get_node(h["term"])
                    if node_h:
                        found_nodes.append(node_h["name"])

            # Si hay 2 o más nodos identificados, buscar caminos transversales entre ellos
            if len(found_nodes) >= 2:
                for i in range(len(found_nodes) - 1):
                    src_name = found_nodes[i]
                    tgt_name = found_nodes[i + 1]
                    path = self.kg.find_shortest_path(src_name, tgt_name, max_depth=3)
                    if path:
                        graph_connections.append({
                            "type": "transversal_path",
                            "source": src_name,
                            "target": tgt_name,
                            "hops": len(path) - 1,
                            "path": [
                                f"{step['node']['name']}" + (f" --[{step['relation']}]--> " if step.get("relation") else "")
                                for step in path
                            ]
                        })

            # Explorar vecindades de los nodos principales
            for node_name in found_nodes[:3]:
                neighbors = self.kg.get_neighbors(node_name, max_neighbors=4)
                for nb in neighbors:
                    graph_connections.append({
                        "type": "relational_edge",
                        "source": node_name,
                        "relation": nb["relation"],
                        "target": nb["target_name"],
                        "evidence": nb.get("evidence", ""),
                    })

            # Consultar definiciones canónicas coincidentes
            con = self._connect()
            try:
                for w in found_nodes[:4]:
                    row = con.execute("SELECT term, definition, sources FROM rag_terms WHERE term = ?", (w.lower(),)).fetchone()
                    if row:
                        matched_terms.append({"term": row[0], "definition": row[1], "sources": row[2]})
            finally:
                con.close()

            # Resúmenes macro RAPTOR
            summaries = self.get_summaries(limit=2)

        return {
            "query": query,
            "hits": hits,
            "graph_connections": graph_connections,
            "terms": matched_terms,
            "summaries": summaries,
            "crag_status": base_res.get("crag_status", "UNKNOWN"),
            "confidence": base_res.get("confidence", 0.0),
            "researched_web": base_res.get("researched_web", False),
        }

    # ---------------------------------------------------------- terminologia
    def define(self, term: str, allow_web: bool = True) -> Dict[str, Any]:
        """Devuelve la definicion de un termino; la investiga y cachea si falta."""
        con = self._connect()
        try:
            row = con.execute("SELECT definition, sources, updated_ts FROM rag_terms WHERE term=?",
                              (term.lower().strip(),)).fetchone()
        finally:
            con.close()
        if row:
            return {"term": term, "definition": row[0], "cached": True, "sources": row[1]}

        res = self.retrieve(f"Definicion y explicacion de: {term}", k=4, allow_web=allow_web)
        if not res["hits"]:
            return {"term": term, "definition": "", "cached": False, "found": False}

        definition = "\n\n".join(h["text"] for h in res["hits"][:3])
        sources = "; ".join(sorted({h["url"] for h in res["hits"] if h["url"]}))
        now = time.time()
        con = self._connect()
        try:
            con.execute("INSERT OR REPLACE INTO rag_terms(term,definition,sources,updated_ts) VALUES (?,?,?,?)",
                        (term.lower().strip(), definition, sources, now))
            con.commit()
        finally:
            con.close()

        # Registrar en Grafo de Conocimiento
        self.kg.add_node(term, entity_type="terminology", description=definition[:300])

        return {"term": term, "definition": definition, "cached": False,
                "found": True, "sources": sources, "researched_web": res["researched_web"]}

    # ------------------------------------------------ inyeccion en el prompt
    def augment_messages(self, messages: List[Dict[str, Any]], k: int = 5,
                          allow_web: bool = False, max_chars: int = 2800) -> List[Dict[str, Any]]:
        """
        Recupera contexto transversal para el ultimo turno del usuario y lo inyecta
        como mensaje de sistema estructurado con grafo, definiciones y fragmentos.
        """
        last_user = next((m for m in reversed(messages)
                          if m.get("role") == "user" and isinstance(m.get("content"), str)), None)
        if not last_user or not self.embed_available():
            return messages

        t_res = self.transversal_retrieve(last_user["content"][:512], k=k, allow_web=allow_web, explore_graph=True)
        hits = t_res.get("hits", [])
        graph = t_res.get("graph_connections", [])
        terms = t_res.get("terms", [])
        summaries = t_res.get("summaries", [])

        if not hits and not graph and not terms and not summaries:
            return messages

        sections = []
        total_len = 0

        # 1. Definiciones ontológicas clave
        if terms:
            term_lines = [f"• {t['term'].upper()}: {t['definition']}" for t in terms[:3]]
            sec = "[DEFINICIONES TERMINOLÓGICAS ANCLADAS]\n" + "\n".join(term_lines)
            sections.append(sec)
            total_len += len(sec)

        # 2. Conexiones relacionales del grafo
        if graph:
            graph_lines = []
            for g in graph[:5]:
                if g.get("type") == "transversal_path":
                    graph_lines.append(f"• CAMINO TRANSVERSAL: {''.join(g['path'])}")
                else:
                    graph_lines.append(f"• RELACIÓN: {g['source']} --[{g['relation']}]--> {g['target']}" + (f" (Evidencia: {g['evidence']})" if g.get('evidence') else ""))
            sec = "[VÍNCULOS ONTO-LÓGICOS Y GRAFO COGNITIVO]\n" + "\n".join(graph_lines)
            if total_len + len(sec) <= max_chars:
                sections.append(sec)
                total_len += len(sec)

        # 3. Resúmenes macro RAPTOR
        if summaries:
            sum_lines = [f"• {s['title']} (Nivel {s['level']}): {s['summary']}" for s in summaries[:2]]
            sec = "[VISIÓN MACRO-JERÁRQUICA RAPTOR]\n" + "\n".join(sum_lines)
            if total_len + len(sec) <= max_chars:
                sections.append(sec)
                total_len += len(sec)

        # 4. Fragmentos técnicos específicos
        frag_pieces = []
        for h in hits:
            frag = h["text"].strip()
            src = f" (fuente: {h['url']})" if h.get("url") else ""
            piece = f"[{h.get('title') or 'memoria'}]{src}\n{frag}"
            if total_len + len(piece) > max_chars:
                break
            frag_pieces.append(piece)
            total_len += len(piece)
        if frag_pieces:
            sections.append("[EVIDENCIAS ESPECÍFICAS Y FRAGMENTOS TÉCNICOS]\n" + "\n\n---\n\n".join(frag_pieces))

        if not sections:
            return messages

        context = (
            "=== CONTEXTO COGNITIVO TRANSVERSAL DE LA BÓVEDA SOBERANA ===\n"
            "Utiliza la siguiente red de evidencias, relaciones y definiciones para formular un análisis riguroso y transversal:\n\n"
            + "\n\n".join(sections)
        )
        out = list(messages)
        insert_at = 1 if out and out[0].get("role") == "system" else 0
        out.insert(insert_at, {"role": "system", "content": context})
        return out

    # ------------------------------------------------------------- telemetria
    def stats(self) -> Dict[str, Any]:
        con = self._connect()
        try:
            n_chunks = con.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
            n_terms = con.execute("SELECT COUNT(*) FROM rag_terms").fetchone()[0]
            n_rels = con.execute("SELECT COUNT(*) FROM rag_relations").fetchone()[0]
            n_sums = con.execute("SELECT COUNT(*) FROM rag_summaries").fetchone()[0]
            by_src = dict(con.execute("SELECT source, COUNT(*) FROM rag_chunks GROUP BY source").fetchall())
        finally:
            con.close()
        kg_stats = self.kg.stats()
        return {
            "chunks": n_chunks,
            "terms": n_terms,
            "relations": n_rels,
            "summaries": n_sums,
            "by_source": by_src,
            "embed_online": self.embed_available(),
            "dim": EMBED_DIM,
            "knowledge_graph": kg_stats,
        }


def get_rag_vault() -> RAGVault:
    return RAGVault.get_instance()
