#!/usr/bin/env python3
"""
core/tardis_event_bus.py - Sistema Nervioso Soberano (Unified Event Bus SQLite WAL)
===================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU

Unifica la comunicación asíncrona entre los 37+ demonios de TARDIS, FTL, Easy Touch,
Zero-Error Shield, Resource Governor, Canary Verifier y el Canal de Co-Evolución AGY.

Características:
  1. Persistencia atómica en SQLite WAL (`data/sovereign_event_bus.db`), segura para
     múltiples procesos concurrentes sin pérdidas ante reinicios.
  2. Deduplicación SHA-256 configurable por ventana de tiempo (elimina tormentas de alertas).
  3. Cursores durables por consumidor (`consume(consumer_id, topics=...)`) para que ningún
     subsistema ni sesión AGY pierda regresiones, anomalías o hallazgos.
  4. Cadenas causales mediante `correlation_id` y retención automática acotada.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_BUS_DB = DATA_DIR / "sovereign_event_bus.db"


def _is_pytest_isolated() -> bool:
    """Evita que pruebas pytest contaminen data/sovereign_event_bus.db de producción."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and str(
        os.environ.get("TARDIS_EVENT_BUS_LIVE_TEST", "0")
    ).strip().lower() not in ("1", "true", "yes")

CANONICAL_TOPICS = (
    "telemetry.pressure",
    "health.regression",
    "health.recovered",
    "sentinel.anomaly",
    "shield.intercept",
    "code.finding",
    "discovery.system",
    "agy.request",
    "agy.response",
    "evolution.applied",
    "evolution.verified",
    "evolution.rollback",
    "governor.reclaim",
)


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class SovereignEventBus:
    """Bus de eventos pub/sub persistente basado en SQLite WAL con cursores durables."""

    _instance: Optional["SovereignEventBus"] = None
    _test_instance: Optional["SovereignEventBus"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "SovereignEventBus":
        if db_path is not None:
            return cls(db_path=db_path)
        with cls._init_lock:
            if _is_pytest_isolated():
                if cls._test_instance is None:
                    test_db = Path(tempfile.gettempdir()) / f"tardis_pytest_event_bus_{os.getpid()}.db"
                    cls._test_instance = cls(db_path=test_db)
                return cls._test_instance
            if cls._instance is None:
                cls._instance = cls(db_path=DEFAULT_BUS_DB)
            return cls._instance

    def __init__(self, db_path: Path = DEFAULT_BUS_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        ts REAL NOT NULL,
                        iso TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        source TEXT NOT NULL,
                        severity TEXT NOT NULL DEFAULT 'INFO',
                        correlation_id TEXT DEFAULT '',
                        dedup_hash TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_events_topic_id ON events(topic, id);
                    CREATE INDEX IF NOT EXISTS idx_events_dedup_ts ON events(dedup_hash, ts);
                    CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

                    CREATE TABLE IF NOT EXISTS consumers (
                        consumer_id TEXT PRIMARY KEY,
                        last_event_id INTEGER NOT NULL DEFAULT 0,
                        updated_ts REAL NOT NULL,
                        updated_iso TEXT NOT NULL
                    );
                    """
                )

    def publish(
        self,
        topic: str,
        source: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        severity: str = "INFO",
        correlation_id: Optional[str] = None,
        dedup_key: Optional[str] = None,
        dedup_window_s: float = 120.0,
    ) -> Dict[str, Any]:
        """Publica un evento con deduplicación opcional por ventana temporal."""
        clean_topic = (topic or "system.generic").strip().lower()
        clean_source = (source or "unknown").strip()
        clean_sev = (severity or "INFO").strip().upper()
        body = payload if isinstance(payload, dict) else {"value": payload}
        payload_json = json.dumps(body, ensure_ascii=False, sort_keys=True)
        corr = (correlation_id or "").strip()

        raw_dedup = dedup_key if dedup_key is not None else f"{clean_topic}|{clean_source}|{clean_sev}|{payload_json}"
        dedup_hash = hashlib.sha256(raw_dedup.encode("utf-8")).hexdigest()[:32]
        now = time.time()
        iso = _now_iso()
        event_id = f"ev_{int(now * 1000)}_{uuid.uuid4().hex[:6]}"

        with self._lock:
            with self._connect() as conn:
                if dedup_window_s > 0:
                    row = conn.execute(
                        "SELECT id, event_id, ts FROM events WHERE dedup_hash = ? AND ts >= ? ORDER BY id DESC LIMIT 1",
                        (dedup_hash, now - float(dedup_window_s)),
                    ).fetchone()
                    if row is not None:
                        return {
                            "ok": True,
                            "published": False,
                            "duplicate": True,
                            "id": int(row["id"]),
                            "event_id": row["event_id"],
                            "topic": clean_topic,
                        }

                cur = conn.execute(
                    """
                    INSERT INTO events (event_id, ts, iso, topic, source, severity, correlation_id, dedup_hash, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (event_id, now, iso, clean_topic, clean_source, clean_sev, corr, dedup_hash, payload_json),
                )
                row_id = int(cur.lastrowid or 0)

                # Retención liviana ocasional para mantener el bus rápido
                if row_id % 250 == 0:
                    self._prune_conn(conn, max_rows=10000, max_age_days=14)

        return {
            "ok": True,
            "published": True,
            "duplicate": False,
            "id": row_id,
            "event_id": event_id,
            "topic": clean_topic,
            "severity": clean_sev,
            "iso": iso,
        }

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            payload = {"raw": row["payload_json"]}
        return {
            "id": int(row["id"]),
            "event_id": row["event_id"],
            "ts": float(row["ts"]),
            "iso": row["iso"],
            "topic": row["topic"],
            "source": row["source"],
            "severity": row["severity"],
            "correlation_id": row["correlation_id"],
            "payload": payload,
        }

    def query(
        self,
        *,
        topic: Optional[str] = None,
        topics: Optional[Sequence[str]] = None,
        since_id: int = 0,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        reverse: bool = True,
    ) -> List[Dict[str, Any]]:
        """Consulta eventos históricos filtrados por tópico, severidad o cursor."""
        clauses = ["id > ?"]
        params: List[Any] = [int(since_id)]

        topic_list: List[str] = []
        if topic:
            topic_list.append(topic.strip().lower())
        if topics:
            topic_list.extend(t.strip().lower() for t in topics if t and t.strip())
        if topic_list:
            placeholders = ", ".join(["?"] * len(topic_list))
            clauses.append(f"topic IN ({placeholders})")
            params.extend(topic_list)
        if severity:
            clauses.append("severity = ?")
            params.append(severity.strip().upper())
        if source:
            clauses.append("source = ?")
            params.append(source.strip())

        order = "DESC" if reverse else "ASC"
        sql = f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY id {order} LIMIT ?"
        params.append(max(1, min(500, int(limit))))

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        events = [self._row_to_dict(r) for r in rows]
        if reverse:
            events.reverse()
        return events

    def consume(
        self,
        consumer_id: str,
        *,
        topics: Optional[Sequence[str]] = None,
        limit: int = 50,
        advance: bool = True,
    ) -> List[Dict[str, Any]]:
        """Lee eventos no procesados para un consumidor con cursor durable."""
        cid = (consumer_id or "default").strip()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT last_event_id FROM consumers WHERE consumer_id = ?",
                    (cid,),
                ).fetchone()
                last_id = int(row["last_event_id"]) if row else 0

                clauses = ["id > ?"]
                params: List[Any] = [last_id]
                if topics:
                    clean_topics = [t.strip().lower() for t in topics if t and t.strip()]
                    if clean_topics:
                        placeholders = ", ".join(["?"] * len(clean_topics))
                        clauses.append(f"topic IN ({placeholders})")
                        params.extend(clean_topics)

                params.append(max(1, min(500, int(limit))))
                rows = conn.execute(
                    f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY id ASC LIMIT ?",
                    params,
                ).fetchall()
                events = [self._row_to_dict(r) for r in rows]

                if advance and events:
                    new_last = int(events[-1]["id"])
                    now = time.time()
                    conn.execute(
                        """
                        INSERT INTO consumers (consumer_id, last_event_id, updated_ts, updated_iso)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(consumer_id) DO UPDATE SET
                            last_event_id = excluded.last_event_id,
                            updated_ts = excluded.updated_ts,
                            updated_iso = excluded.updated_iso
                        """,
                        (cid, new_last, now, _now_iso()),
                    )
        return events

    def stats(self) -> Dict[str, Any]:
        """Telemetría global del Sovereign Event Bus."""
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            by_topic = {
                r["topic"]: int(r["cnt"])
                for r in conn.execute("SELECT topic, COUNT(*) AS cnt FROM events GROUP BY topic ORDER BY cnt DESC").fetchall()
            }
            by_sev = {
                r["severity"]: int(r["cnt"])
                for r in conn.execute("SELECT severity, COUNT(*) AS cnt FROM events GROUP BY severity").fetchall()
            }
            consumers = [
                dict(r)
                for r in conn.execute("SELECT consumer_id, last_event_id, updated_iso FROM consumers ORDER BY updated_ts DESC").fetchall()
            ]
            latest = conn.execute("SELECT id, iso, topic, source, severity FROM events ORDER BY id DESC LIMIT 1").fetchone()
        size_kb = round(self.db_path.stat().st_size / 1024.0, 1) if self.db_path.is_file() else 0.0
        return {
            "ok": True,
            "db_path": str(self.db_path),
            "db_size_kb": size_kb,
            "total_events": total,
            "by_topic": by_topic,
            "by_severity": by_sev,
            "consumers": consumers,
            "latest_event": dict(latest) if latest else None,
            "canonical_topics": list(CANONICAL_TOPICS),
            "iso": _now_iso(),
        }

    @staticmethod
    def _prune_conn(conn: sqlite3.Connection, max_rows: int = 10000, max_age_days: int = 14) -> int:
        cutoff = time.time() - (max(1, int(max_age_days)) * 86400.0)
        c1 = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,)).rowcount
        c2 = conn.execute(
            "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
            (max(100, int(max_rows)),),
        ).rowcount
        return int(c1 or 0) + int(c2 or 0)

    def prune(self, max_rows: int = 10000, max_age_days: int = 14) -> Dict[str, Any]:
        with self._lock:
            with self._connect() as conn:
                removed = self._prune_conn(conn, max_rows=max_rows, max_age_days=max_age_days)
        return {"ok": True, "removed": removed}


def get_event_bus(db_path: Optional[Path] = None) -> SovereignEventBus:
    return SovereignEventBus.get_instance(db_path=db_path)


def main() -> int:
    ap = argparse.ArgumentParser(prog="tardis-bus", description="TARDIS Sovereign Nervous System (Event Bus)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="Estadísticas del bus de eventos")
    sub.add_parser("topics", help="Lista tópicos canónicos")

    p_tail = sub.add_parser("tail", help="Últimos eventos publicados")
    p_tail.add_argument("--topic", default=None)
    p_tail.add_argument("--severity", default=None)
    p_tail.add_argument("--limit", type=int, default=20)

    p_pub = sub.add_parser("publish", help="Publica un evento manual")
    p_pub.add_argument("topic")
    p_pub.add_argument("message")
    p_pub.add_argument("--source", default="cli")
    p_pub.add_argument("--severity", default="INFO")
    p_pub.add_argument("--dedup-window", type=float, default=0.0)

    p_unr = sub.add_parser("unread", help="Consulta eventos sin leer para un consumidor")
    p_unr.add_argument("consumer")
    p_unr.add_argument("--advance", action="store_true")
    p_unr.add_argument("--limit", type=int, default=30)

    args = ap.parse_args()
    bus = get_event_bus()

    if args.cmd == "stats":
        print(json.dumps(bus.stats(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "topics":
        print(json.dumps({"ok": True, "topics": list(CANONICAL_TOPICS)}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "tail":
        print(json.dumps({"ok": True, "events": bus.query(topic=args.topic, severity=args.severity, limit=args.limit)}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "publish":
        print(json.dumps(bus.publish(args.topic, args.source, {"message": args.message}, severity=args.severity, dedup_window_s=args.dedup_window), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "unread":
        evs = bus.consume(args.consumer, limit=args.limit, advance=args.advance)
        print(json.dumps({"ok": True, "consumer": args.consumer, "count": len(evs), "events": evs}, indent=2, ensure_ascii=False))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
