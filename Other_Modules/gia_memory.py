"""
gia_memory.py - HISTORIAL MAESTRO compartido por todo el sistema GIA.
=====================================================================

Una sola base de datos SQLite (con busqueda de texto FTS5, sin dependencias
externas) a la que se conectan TODAS las variantes del sistema:
  - gia_agent.py (agente autonomo)
  - voice_assistant.py (voz)
  - gia_web_server.py (interfaz web/movil)
  - web_chat.py (chat con internet)
  - self_improve.py (auto-mejora)
  - gia_control.py (control Vectorworks)

Aporta:
  1. VENTANAS DE CONTEXTO MAS AMPLIAS por recuperacion: en vez de mandar
     todo el historial al modelo (imposible en un modelo local chico), se
     recuperan los turnos RECIENTES + los turnos RELEVANTES (FTS5) al tema
     actual y se inyectan como bloque de contexto.
  2. APRENDIZAJE EN CONTEXTO ("entrenarse en lo que mas se le exige"): un
     banco de ejemplos de tareas resueltas con exito. NO reentrena pesos
     (imposible en 4 GB VRAM); recupera los ejemplos mas parecidos y los
     inyecta como few-shot, mejorando en las tareas frecuentes.
  3. ESTADISTICAS de demanda: que fuentes/tareas se usan mas, para priorizar.

Multi-proceso seguro (WAL + busy_timeout): varias variantes escriben a la vez.

Ubicacion: %LOCALAPPDATA%\\vw-control\\gia_master.db

API principal:
    log(source, role, content, session_id=, meta=)
    recent(n=, source=, session_id=)
    search(query, k=)
    record_success(task, solution, tools=, source=)
    few_shot(task, k=)
    context_block(query=, session_id=, n_recent=, n_relevant=)
    stats()
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CONFIG_DIR / "gia_master.db"

_INIT_DONE = False


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH), timeout=15.0, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=8000")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _init():
    global _INIT_DONE
    if _INIT_DONE:
        return
    con = _connect()
    try:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            session_id TEXT,
            source TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            meta TEXT,
            tokens_est INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
        CREATE INDEX IF NOT EXISTS ix_events_src ON events(source);
        CREATE INDEX IF NOT EXISTS ix_events_sess ON events(session_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
            content, event_id UNINDEXED, tokenize='unicode61'
        );

        CREATE TABLE IF NOT EXISTS successes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            source TEXT,
            task TEXT NOT NULL,
            solution TEXT NOT NULL,
            tools TEXT,
            rating INTEGER DEFAULT 1
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS successes_fts USING fts5(
            body, success_id UNINDEXED, tokenize='unicode61'
        );

        CREATE TABLE IF NOT EXISTS demand (
            key TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            last_ts REAL
        );

        CREATE TABLE IF NOT EXISTS l1_cache (
            key TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            response TEXT NOT NULL,
            created_at REAL NOT NULL,
            ttl_seconds REAL NOT NULL,
            hit_count INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_l1_created ON l1_cache(created_at);
        """)
        con.commit()
        _INIT_DONE = True
    finally:
        con.close()


def _tok(s: str) -> int:
    return max(1, len(s) // 4)


def _fts_safe(q: str) -> str:
    """Convierte una consulta libre en algo seguro para FTS5 (OR de terminos)."""
    import re
    terms = re.findall(r"[\wáéíóúñü]+", (q or "").lower())
    terms = [t for t in terms if len(t) > 2][:12]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms)


# =====================================================================
#  ESCRITURA
# =====================================================================

def log(source: str, role: str, content: str,
        session_id: str = "", meta: dict = None) -> int:
    """Registra un evento (mensaje/accion) en el historial maestro y en la Bóveda Akáshica de 250 GB."""
    _init()
    content = content or ""

    # Ingesta completa en la Bóveda de Memoria Profunda de 250 GB (Zero Truncation)
    try:
        from core.deep_memory_vault import get_deep_memory_vault
        get_deep_memory_vault().ingest(
            source=source,
            role=role,
            content=content,
            session_id=session_id or "omni_app",
            meta=meta or {}
        )
    except Exception:
        pass

    con = _connect()
    try:
        cur = con.execute(
            "INSERT INTO events(ts, session_id, source, role, content, meta, tokens_est) "
            "VALUES(?,?,?,?,?,?,?)",
            (time.time(), session_id, source, role, content,
             json.dumps(meta or {}, ensure_ascii=False), _tok(content)))
        eid = cur.lastrowid
        con.execute("INSERT INTO events_fts(content, event_id) VALUES(?,?)",
                    (content[:65536], eid))
        # Demanda por fuente y por rol
        for key in (f"source:{source}", f"role:{role}"):
            con.execute(
                "INSERT INTO demand(key, count, last_ts) VALUES(?,1,?) "
                "ON CONFLICT(key) DO UPDATE SET count=count+1, last_ts=excluded.last_ts",
                (key, time.time()))
        con.commit()
        return eid
    finally:
        con.close()


def record_success(task: str, solution: str, tools: list = None,
                   source: str = "", rating: int = 1) -> int:
    """Guarda una tarea resuelta con exito para reuso como few-shot."""
    _init()
    con = _connect()
    try:
        cur = con.execute(
            "INSERT INTO successes(ts, source, task, solution, tools, rating) "
            "VALUES(?,?,?,?,?,?)",
            (time.time(), source, task[:4000], solution[:8000],
             json.dumps(tools or [], ensure_ascii=False), rating))
        sid = cur.lastrowid
        con.execute("INSERT INTO successes_fts(body, success_id) VALUES(?,?)",
                    (f"{task}\n{solution}"[:8000], sid))
        con.commit()
        return sid
    finally:
        con.close()


# =====================================================================
#  LECTURA
# =====================================================================

def recent(n: int = 20, source: str = "", session_id: str = "") -> list:
    _init()
    con = _connect()
    try:
        q = "SELECT ts, source, role, content, meta FROM events WHERE 1=1"
        args = []
        if source:
            q += " AND source=?"; args.append(source)
        if session_id:
            q += " AND session_id=?"; args.append(session_id)
        q += " ORDER BY id DESC LIMIT ?"; args.append(n)
        rows = con.execute(q, args).fetchall()
        out = [{"ts": r[0], "source": r[1], "role": r[2],
                "content": r[3], "meta": json.loads(r[4] or "{}")} for r in rows]
        out.reverse()
        return out
    finally:
        con.close()


def search(query: str, k: int = 8) -> list:
    """Busqueda FTS5 en todo el historial. Devuelve turnos relevantes."""
    _init()
    fq = _fts_safe(query)
    if not fq:
        return []
    con = _connect()
    try:
        rows = con.execute(
            "SELECT e.ts, e.source, e.role, e.content "
            "FROM events_fts f JOIN events e ON e.id=f.event_id "
            "WHERE events_fts MATCH ? ORDER BY bm25(events_fts) LIMIT ?",
            (fq, k)).fetchall()
        return [{"ts": r[0], "source": r[1], "role": r[2], "content": r[3]}
                for r in rows]
    except Exception:
        return []
    finally:
        con.close()


def few_shot(task: str, k: int = 3) -> list:
    """Recupera tareas exitosas parecidas para inyectar como ejemplos."""
    _init()
    fq = _fts_safe(task)
    if not fq:
        return []
    con = _connect()
    try:
        rows = con.execute(
            "SELECT s.task, s.solution, s.tools FROM successes_fts f "
            "JOIN successes s ON s.id=f.success_id "
            "WHERE successes_fts MATCH ? ORDER BY bm25(successes_fts) LIMIT ?",
            (fq, k)).fetchall()
        return [{"task": r[0], "solution": r[1],
                 "tools": json.loads(r[2] or "[]")} for r in rows]
    except Exception:
        return []
    finally:
        con.close()


def context_block(query: str = "", session_id: str = "",
                  n_recent: int = 15, n_relevant: int = 8,
                  max_chars: int = 16000) -> str:
    """Bloque de contexto maestro de memoria profunda (hasta 250 GB y 16k chars)."""
    try:
        from core.deep_memory_vault import get_deep_memory_vault
        return get_deep_memory_vault().query_deep_context(
            query=query,
            session_id=session_id,
            max_chars=max_chars,
            n_recent=n_recent,
            n_relevant=n_relevant
        )
    except Exception:
        pass

    parts = []
    rec = recent(n_recent, session_id=session_id) if session_id else recent(n_recent)
    if rec:
        parts.append("=== CONTEXTO RECIENTE ===")
        for e in rec:
            parts.append(f"[{e['source']}/{e['role']}] {e['content'][:1500]}")
    if query:
        rel = search(query, k=n_relevant)
        seen = {e["content"][:120] for e in rec}
        rel = [r for r in rel if r["content"][:120] not in seen]
        if rel:
            parts.append("\n=== MEMORIA RELEVANTE (de todo el sistema) ===")
            for r in rel:
                parts.append(f"[{r['source']}/{r['role']}] {r['content'][:1500]}")
    block = "\n".join(parts)
    if len(block) > max_chars:
        block = block[:max_chars] + "\n...[recortado]"
    return block


def stats() -> dict:
    _init()
    con = _connect()
    try:
        total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        succ = con.execute("SELECT COUNT(*) FROM successes").fetchone()[0]
        demand = con.execute(
            "SELECT key, count FROM demand ORDER BY count DESC LIMIT 15").fetchall()
        by_source = con.execute(
            "SELECT source, COUNT(*) c FROM events GROUP BY source ORDER BY c DESC"
        ).fetchall()
        db_mb = round(DB_PATH.stat().st_size / 1e6, 2) if DB_PATH.exists() else 0
        vault_stats = {}
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            vault_stats = get_deep_memory_vault().get_vault_telemetry()
        except Exception:
            pass
        return {
            "total_events": total,
            "total_successes": succ,
            "db_size_mb": db_mb,
            "top_demand": [{"key": k, "count": c} for k, c in demand],
            "by_source": [{"source": s, "count": c} for s, c in by_source],
            "vault_250gb": vault_stats
        }
    finally:
        con.close()


# =====================================================================
#  CACHE DETERMINISTA L1 (< 2ms)
# =====================================================================

def get_l1_cache(key: str) -> str | None:
    """Recupera una respuesta en caché L1 si no ha expirado su TTL (<2ms)."""
    _init()
    con = _connect()
    try:
        now = time.time()
        row = con.execute(
            "SELECT response, created_at, ttl_seconds FROM l1_cache WHERE key = ?",
            (key,)
        ).fetchone()
        if not row:
            return None
        resp, created_at, ttl = row
        if (now - created_at) > ttl:
            con.execute("DELETE FROM l1_cache WHERE key = ?", (key,))
            con.commit()
            return None
        con.execute("UPDATE l1_cache SET hit_count = hit_count + 1 WHERE key = ?", (key,))
        con.commit()
        return resp
    except Exception:
        return None
    finally:
        con.close()


def set_l1_cache(key: str, query: str, response: str, ttl_seconds: float = 120.0) -> None:
    """Guarda una respuesta en la caché L1 determinista."""
    _init()
    con = _connect()
    try:
        now = time.time()
        con.execute(
            """INSERT OR REPLACE INTO l1_cache (key, query, response, created_at, ttl_seconds, hit_count)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (key, query, response, now, ttl_seconds)
        )
        con.commit()
    except Exception:
        pass
    finally:
        con.close()


def purge_expired_l1_cache() -> int:
    """Limpia entradas expiradas de la caché L1."""
    _init()
    con = _connect()
    try:
        now = time.time()
        cur = con.execute("DELETE FROM l1_cache WHERE (? - created_at) > ttl_seconds", (now,))
        con.commit()
        return cur.rowcount
    except Exception:
        return 0
    finally:
        con.close()



# =====================================================================
#  CLI
# =====================================================================

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Historial maestro GIA")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("stats")
    ps = sub.add_parser("search"); ps.add_argument("query")
    pl = sub.add_parser("recent"); pl.add_argument("-n", type=int, default=15)
    pt = sub.add_parser("test")
    args = ap.parse_args()

    if args.cmd == "stats":
        print(json.dumps(stats(), indent=2, ensure_ascii=False))
    elif args.cmd == "search":
        for r in search(args.query, 10):
            print(f"[{r['source']}/{r['role']}] {r['content'][:120]}")
    elif args.cmd == "recent":
        for r in recent(args.n):
            print(f"[{r['source']}/{r['role']}] {r['content'][:120]}")
    elif args.cmd == "test":
        log("test", "user", "Como genero una presentacion corporativa en Vectorworks")
        log("test", "assistant", "Usa generate_corporate_presentation con el titulo y cliente")
        record_success("presentacion corporativa VW",
                       "generate_corporate_presentation(title=..., client_name=...)",
                       tools=["generate_corporate_presentation"], source="test")
        print("Escrito. Busqueda 'presentacion':")
        for r in search("presentacion corporativa", 5):
            print("  ", r["content"][:80])
        print("Few-shot 'como hago una presentacion':")
        for f in few_shot("como hago una presentacion", 2):
            print("  TASK:", f["task"][:60], "-> SOL:", f["solution"][:60])
        print("\nStats:", json.dumps(stats(), ensure_ascii=False)[:300])
    else:
        ap.print_help()
