"""
core/knowledge_graph.py - Grafo de Conocimiento Soberano de TARDIS
=================================================================
GODWORKS SYSTEM

Grafo de conocimiento ligero, persistente sobre SQLite puro (sin Neo4j ni dependencias
pesadas), diseñado para habilitar el razonamiento transversal y multi-salto:

  * Nodos: Entidades, conceptos, subsistemas, terminologías y leyes.
  * Aristas: Relaciones semánticas estructuradas (causa, depende_de, optimiza,
    análogo_a, parte_de, implementa).
  * Algoritmos Soberanos:
      - Búsqueda de caminos transversales (Shortest Path / Multi-Hop BFS).
      - Expansión de vecindades conceptuales (ego-graph expansion).
      - Detección de puentes conceptuales (nodos que conectan dominios disjuntos).
      - Detección de comunidades por propagación de etiquetas (Label Propagation).
  * 0 Consumo de VRAM: Todo opera sobre RAM de sistema y SQLite con WAL.
"""

from __future__ import annotations

import collections
import json
import logging
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("GODWORKS.KnowledgeGraph")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
KG_DB_PATH = DATA_DIR / "knowledge_graph.db"


class KnowledgeGraph:
    _instance: Optional["KnowledgeGraph"] = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "KnowledgeGraph":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path=db_path)
            return cls._instance

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or KG_DB_PATH
        self._init_db()

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
            CREATE TABLE IF NOT EXISTS kg_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                entity_type TEXT NOT NULL DEFAULT 'concept',
                description TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                ts REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS kg_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                relation TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                evidence TEXT DEFAULT '',
                ts REAL NOT NULL,
                FOREIGN KEY (source_id) REFERENCES kg_nodes(id) ON DELETE CASCADE,
                FOREIGN KEY (target_id) REFERENCES kg_nodes(id) ON DELETE CASCADE,
                UNIQUE(source_id, target_id, relation)
            );

            CREATE INDEX IF NOT EXISTS idx_kg_nodes_name ON kg_nodes(name);
            CREATE INDEX IF NOT EXISTS idx_kg_nodes_type ON kg_nodes(entity_type);
            CREATE INDEX IF NOT EXISTS idx_kg_edges_src ON kg_edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_kg_edges_tgt ON kg_edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_kg_edges_rel ON kg_edges(relation);

            CREATE TABLE IF NOT EXISTS kg_communities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                summary TEXT NOT NULL,
                level INTEGER DEFAULT 0,
                node_ids TEXT NOT NULL,
                ts REAL NOT NULL
            );
            """)
            con.commit()
        finally:
            con.close()

    # ---------------------------------------------------------------- Nodos
    def add_node(
        self,
        name: str,
        entity_type: str = "concept",
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Node name cannot be empty")
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        now = time.time()
        con = self._connect()
        try:
            con.execute(
                """
                INSERT INTO kg_nodes (name, entity_type, description, metadata, ts)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = CASE WHEN excluded.description != '' THEN excluded.description ELSE kg_nodes.description END,
                    entity_type = CASE WHEN excluded.entity_type != 'concept' THEN excluded.entity_type ELSE kg_nodes.entity_type END,
                    metadata = excluded.metadata,
                    ts = excluded.ts
                """,
                (clean_name, entity_type, description, meta_json, now),
            )
            con.commit()
            row = con.execute("SELECT id FROM kg_nodes WHERE name = ?", (clean_name,)).fetchone()
            return int(row[0])
        finally:
            con.close()

    def get_node(self, name_or_id: str | int) -> Optional[Dict[str, Any]]:
        con = self._connect()
        try:
            if isinstance(name_or_id, int):
                row = con.execute(
                    "SELECT id, name, entity_type, description, metadata, ts FROM kg_nodes WHERE id = ?",
                    (name_or_id,),
                ).fetchone()
            else:
                row = con.execute(
                    "SELECT id, name, entity_type, description, metadata, ts FROM kg_nodes WHERE name = ?",
                    (name_or_id.strip(),),
                ).fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "name": row[1],
                "entity_type": row[2],
                "description": row[3],
                "metadata": json.loads(row[4] or "{}"),
                "ts": row[5],
            }
        finally:
            con.close()

    def find_matching_nodes(self, text: str, max_nodes: int = 10) -> List[Dict[str, Any]]:
        """Busca nodos cuyos nombres o conceptos aparezcan dentro del texto o consulta."""
        clean_text = text.strip()
        if not clean_text:
            return []
        con = self._connect()
        try:
            # 1. Búsqueda de contención directa (instr)
            rows = con.execute(
                """
                SELECT id, name, entity_type, description, metadata, ts
                FROM kg_nodes
                WHERE instr(lower(?), lower(name)) > 0 AND length(name) >= 3
                ORDER BY length(name) DESC LIMIT ?
                """,
                (clean_text, max_nodes),
            ).fetchall()
            matched = []
            seen_ids = set()
            for r in rows:
                seen_ids.add(r[0])
                matched.append({
                    "id": r[0], "name": r[1], "entity_type": r[2],
                    "description": r[3], "metadata": json.loads(r[4] or "{}"), "ts": r[5]
                })

            # 2. Búsqueda por palabras individuales significativas
            if len(matched) < max_nodes:
                words = [w.lower() for w in re.findall(r"\b[A-Za-z0-9_\-]{4,}\b", clean_text)
                         if w.lower() not in ("para", "como", "hacer", "este", "esta", "sistema", "analiza", "sobre")]
                for w in words:
                    if len(matched) >= max_nodes:
                        break
                    row = con.execute(
                        "SELECT id, name, entity_type, description, metadata, ts FROM kg_nodes WHERE lower(name) = ? LIMIT 1",
                        (w,)
                    ).fetchone()
                    if row and row[0] not in seen_ids:
                        seen_ids.add(row[0])
                        matched.append({
                            "id": row[0], "name": row[1], "entity_type": row[2],
                            "description": row[3], "metadata": json.loads(row[4] or "{}"), "ts": row[5]
                        })
            return matched
        finally:
            con.close()

    # ---------------------------------------------------------------- Aristas
    def add_edge(
        self,
        source: str | int,
        target: str | int,
        relation: str = "relates_to",
        weight: float = 1.0,
        evidence: str = "",
    ) -> int:
        src_id = source if isinstance(source, int) else self.add_node(source)
        tgt_id = target if isinstance(target, int) else self.add_node(target)
        if src_id == tgt_id:
            return -1  # Evitar bucles directos reflexivos innecesarios

        clean_rel = relation.strip().lower().replace(" ", "_")
        now = time.time()
        con = self._connect()
        try:
            con.execute(
                """
                INSERT INTO kg_edges (source_id, target_id, relation, weight, evidence, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, target_id, relation) DO UPDATE SET
                    weight = excluded.weight,
                    evidence = excluded.evidence,
                    ts = excluded.ts
                """,
                (src_id, tgt_id, clean_rel, weight, evidence, now),
            )
            con.commit()
            row = con.execute(
                "SELECT id FROM kg_edges WHERE source_id = ? AND target_id = ? AND relation = ?",
                (src_id, tgt_id, clean_rel),
            ).fetchone()
            return int(row[0])
        finally:
            con.close()

    # ------------------------------------------------------ Expansión y Caminos
    def get_neighbors(
        self, node: str | int, direction: str = "both", max_neighbors: int = 50
    ) -> List[Dict[str, Any]]:
        target_node = self.get_node(node)
        if not target_node:
            return []
        nid = target_node["id"]
        con = self._connect()
        try:
            results = []
            if direction in ("out", "both"):
                rows = con.execute(
                    """
                    SELECT e.id, e.relation, e.weight, e.evidence, n.id, n.name, n.entity_type, n.description
                    FROM kg_edges e
                    JOIN kg_nodes n ON e.target_id = n.id
                    WHERE e.source_id = ?
                    ORDER BY e.weight DESC LIMIT ?
                    """,
                    (nid, max_neighbors),
                ).fetchall()
                for r in rows:
                    results.append({
                        "edge_id": r[0],
                        "relation": r[1],
                        "weight": r[2],
                        "evidence": r[3],
                        "direction": "outgoing",
                        "target_id": r[4],
                        "target_name": r[5],
                        "target_type": r[6],
                        "target_description": r[7],
                    })

            if direction in ("in", "both"):
                rows = con.execute(
                    """
                    SELECT e.id, e.relation, e.weight, e.evidence, n.id, n.name, n.entity_type, n.description
                    FROM kg_edges e
                    JOIN kg_nodes n ON e.source_id = n.id
                    WHERE e.target_id = ?
                    ORDER BY e.weight DESC LIMIT ?
                    """,
                    (nid, max_neighbors),
                ).fetchall()
                for r in rows:
                    results.append({
                        "edge_id": r[0],
                        "relation": r[1],
                        "weight": r[2],
                        "evidence": r[3],
                        "direction": "incoming",
                        "target_id": r[4],
                        "target_name": r[5],
                        "target_type": r[6],
                        "target_description": r[7],
                    })
            return results
        finally:
            con.close()

    def find_shortest_path(
        self, source: str | int, target: str | int, max_depth: int = 4
    ) -> Optional[List[Dict[str, Any]]]:
        """Encuentra el camino conceptual más corto entre dos nodos disjuntos (BFS)."""
        src = self.get_node(source)
        tgt = self.get_node(target)
        if not src or not tgt:
            return None
        if src["id"] == tgt["id"]:
            return [{"node": src, "relation": None}]

        queue: collections.deque[Tuple[int, List[Dict[str, Any]]]] = collections.deque()
        queue.append((src["id"], [{"node": src, "relation": None}]))
        visited: Set[int] = {src["id"]}

        con = self._connect()
        try:
            while queue:
                curr_id, path = queue.popleft()
                if len(path) > max_depth:
                    continue

                # Consultar vecinos bidireccionales
                rows = con.execute(
                    """
                    SELECT target_id, relation, 'out' FROM kg_edges WHERE source_id = ?
                    UNION
                    SELECT source_id, relation, 'in' FROM kg_edges WHERE target_id = ?
                    """,
                    (curr_id, curr_id),
                ).fetchall()

                for next_id, rel, direction in rows:
                    if next_id == tgt["id"]:
                        next_node = self.get_node(next_id)
                        return path + [{"node": next_node, "relation": rel, "direction": direction}]

                    if next_id not in visited and len(path) < max_depth:
                        visited.add(next_id)
                        next_node = self.get_node(next_id)
                        queue.append(
                            (next_id, path + [{"node": next_node, "relation": rel, "direction": direction}])
                        )
            return None
        finally:
            con.close()

    def find_conceptual_bridges(
        self, domain_a_nodes: List[str], domain_b_nodes: List[str], max_bridges: int = 5
    ) -> List[Dict[str, Any]]:
        """Descubre nodos que conectan dos dominios conceptuales aparentemente independientes."""
        bridges = []
        for node_a in domain_a_nodes:
            for node_b in domain_b_nodes:
                path = self.find_shortest_path(node_a, node_b, max_depth=3)
                if path and len(path) >= 3:
                    intermediate_nodes = path[1:-1]
                    bridges.append({
                        "source": node_a,
                        "target": node_b,
                        "hops": len(path) - 1,
                        "intermediate": [step["node"]["name"] for step in intermediate_nodes],
                        "full_path": path,
                    })
                    if len(bridges) >= max_bridges:
                        return bridges
        return bridges

    # ---------------------------------------------------- Detección de Comunidades
    def detect_communities(self, max_iterations: int = 10) -> Dict[str, List[str]]:
        """
        Algoritmo de propagación de etiquetas (Label Propagation) soberano en Python puro
        para agrupar nodos en comunidades temáticas transversales sin dependencias externas.
        """
        con = self._connect()
        try:
            nodes = [r[0] for r in con.execute("SELECT name FROM kg_nodes").fetchall()]
            if not nodes:
                return {}

            edges = con.execute(
                """
                SELECT n1.name, n2.name, e.weight
                FROM kg_edges e
                JOIN kg_nodes n1 ON e.source_id = n1.id
                JOIN kg_nodes n2 ON e.target_id = n2.id
                """
            ).fetchall()
        finally:
            con.close()

        # Construir adyacencia no dirigida
        adj: Dict[str, Dict[str, float]] = collections.defaultdict(dict)
        for u, v, w in edges:
            adj[u][v] = max(adj[u].get(v, 0.0), float(w))
            adj[v][u] = max(adj[v].get(u, 0.0), float(w))

        # Inicializar cada nodo con su propia etiqueta
        labels = {n: n for n in nodes}

        for _ in range(max_iterations):
            changed = False
            for n in nodes:
                neighbors = adj.get(n, {})
                if not neighbors:
                    continue
                # Ponderar etiquetas vecinas
                label_weights: Dict[str, float] = collections.defaultdict(float)
                for neighbor, weight in neighbors.items():
                    label_weights[labels[neighbor]] += weight
                if label_weights:
                    best_label = max(label_weights.items(), key=lambda x: x[1])[0]
                    if best_label != labels[n]:
                        labels[n] = best_label
                        changed = True
            if not changed:
                break

        # Agrupar por comunidad
        communities: Dict[str, List[str]] = collections.defaultdict(list)
        for node, comm in labels.items():
            communities[comm].append(node)
        return dict(communities)

    def stats(self) -> Dict[str, Any]:
        con = self._connect()
        try:
            num_nodes = con.execute("SELECT COUNT(*) FROM kg_nodes").fetchone()[0]
            num_edges = con.execute("SELECT COUNT(*) FROM kg_edges").fetchone()[0]
            by_type = dict(
                con.execute("SELECT entity_type, COUNT(*) FROM kg_nodes GROUP BY entity_type").fetchall()
            )
            by_rel = dict(
                con.execute("SELECT relation, COUNT(*) FROM kg_edges GROUP BY relation").fetchall()
            )
            return {
                "nodes": num_nodes,
                "edges": num_edges,
                "node_types": by_type,
                "relations": by_rel,
            }
        finally:
            con.close()


def get_knowledge_graph() -> KnowledgeGraph:
    return KnowledgeGraph.get_instance()
