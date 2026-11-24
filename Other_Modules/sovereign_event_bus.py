#!/usr/bin/env python3
"""
core/sovereign_event_bus.py - Sistema Nervioso Soberano y Bus de Eventos Causales (SQLite WAL)
==============================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Unifica la telemetría, alertas, regresiones, descubrimientos y respuestas entre los 35+
demonios de TARDIS, FTL, Zero-Error Shield, Resource Governor, Canary Verifier y el motor
de Co-Evolución Continua TARDIS ↔ AGY.

Propiedades de Ingeniería:
  1. SQLite WAL multi-proceso (seguro para acceso concurrente entre servicios systemd).
  2. Tópicos tipados jerárquicos (`resource.*`, `health.*`, `anomaly.*`, `discovery.*`,
     `coevolution.*`, `canary.*`, `security.*`, `evolution.*`).
  3. Deduplicación determinista por firma SHA-256 con ventana de supresión configurable
     (elimina tormentas de alertas repetidas y contabiliza `suppressed_count`).
  4. Cursores duraderos por consumidor (`consume(consumer, topics=...)`) con semántica
     at-least-once resistente a reinicios.
  5. Trazabilidad causal (`correlation_id`, `parent_event_id`) y poda automática
     (retiene los últimos 10,000 eventos).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("TARDIS.EventBus")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
BUS_DB = DATA_DIR / "sovereign_event_bus.db"
MAX_EVENTS_RETAINED = 10000

VALID_SEVERITIES = ("DEBUG", "INFO", "WARN", "HIGH", "CRITICAL")


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class SovereignEventBus:
    """Bus de Eventos Causales persistente sobre SQLite WAL con deduplicación y cursores."""

    _instance: Optional["SovereignEventBus"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "SovereignEventBus":
        if db_path is not None:
            return cls(db_path=db_path)
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls(db_path=BUS_DB)
            return cls._instance

    def __init__(self, db_path: Path = BUS_DB) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=15.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=10000")
        return con

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    source TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    correlation_id TEXT,
                    parent_event_id TEXT,
                    signature TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    suppressed_count INTEGER DEFAULT 0
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS consumer_cursors (
                    consumer TEXT PRIMARY KEY,
                    last_seq INTEGER NOT NULL DEFAULT 0,
                    updated_ts REAL NOT NULL,
                    updated_iso TEXT NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_topic_seq ON events(topic, seq)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_sig_ts ON events(signature, ts)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_sev_seq ON events(severity, seq)")

    @staticmethod
    def _compute_signature(topic: str, source: str, severity: str, payload: Dict[str, Any]) -> str:
        # Normalizar payload removiendo timestamps volátiles para deduplicar alertas repetidas
        clean = {
            k: v
            for k, v in sorted(payload.items())
            if k not in ("ts", "timestamp", "iso", "elapsed", "elapsed_s", "latency_ms")
        }
        raw = json.dumps({"t": topic, "s": source, "v": severity, "p": clean}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def publish(
        self,
        topic: str,
        source: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        severity: str = "INFO",
        correlation_id: Optional[str] = None,
        parent_event_id: Optional[str] = None,
        dedup_window_s: float = 0.0,
    ) -> Dict[str, Any]:
        """Publica un evento tipado en el bus con deduplicación opcional."""
        topic_clean = (topic or "general.info").strip().lower()
        source_clean = (source or "tardis").strip()
        sev = (severity or "INFO").strip().upper()
        if sev not in VALID_SEVERITIES:
            sev = "INFO"
        body = dict(payload or {})
        now = time.time()
        iso = _now_iso()
        sig = self._compute_signature(topic_clean, source_clean, sev, body)

        with self._lock:
            with self._connect() as con:
                if dedup_window_s > 0:
                    cutoff = now - float(dedup_window_s)
                    row = con.execute(
                        "SELECT seq, event_id, suppressed_count FROM events WHERE signature = ? AND ts >= ? ORDER BY seq DESC LIMIT 1",
                        (sig, cutoff),
                    ).fetchone()
                    if row is not None:
                        new_count = int(row["suppressed_count"] or 0) + 1
                        con.execute(
                            "UPDATE events SET suppressed_count = ? WHERE seq = ?",
                            (new_count, row["seq"]),
                        )
                        return {
                            "ok": True,
                            "deduplicated": True,
                            "seq": int(row["seq"]),
                            "event_id": row["event_id"],
                            "suppressed_count": new_count,
                            "topic": topic_clean,
                        }

                event_id = f"ev_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
                corr = correlation_id or event_id
                cur = con.execute(
                    """
                    INSERT INTO events (
                        event_id, ts, iso, topic, source, severity,
                        correlation_id, parent_event_id, signature, payload_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event_id,
                        now,
                        iso,
                        topic_clean,
                        source_clean,
                        sev,
                        corr,
                        parent_event_id or "",
                        sig,
                        json.dumps(body, ensure_ascii=False),
                    ),
                )
                seq = int(cur.lastrowid or 0)

                # Poda periódica para mantener tamaño acotado
                if seq % 200 == 0:
                    con.execute(
                        "DELETE FROM events WHERE seq <= (SELECT COALESCE(MAX(seq), 0) - ? FROM events)",
                        (MAX_EVENTS_RETAINED,),
                    )

                return {
                    "ok": True,
                    "deduplicated": False,
                    "seq": seq,
                    "event_id": event_id,
                    "correlation_id": corr,
                    "topic": topic_clean,
                    "source": source_clean,
                    "severity": sev,
                    "iso": iso,
                }

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            payload = {}
        return {
            "seq": int(row["seq"]),
            "event_id": row["event_id"],
            "ts": float(row["ts"]),
            "iso": row["iso"],
            "topic": row["topic"],
            "source": row["source"],
            "severity": row["severity"],
            "correlation_id": row["correlation_id"],
            "parent_event_id": row["parent_event_id"],
            "suppressed_count": int(row["suppressed_count"] or 0),
            "payload": payload,
        }

    def query(
        self,
        *,
        topic_prefix: Optional[str] = None,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        since_seq: int = 0,
        since_ts: float = 0.0,
        limit: int = 50,
        ascending: bool = False,
    ) -> List[Dict[str, Any]]:
        """Consulta eventos con filtros combinables."""
        clauses = ["seq > ?"]
        params: List[Any] = [int(since_seq)]

        if since_ts > 0:
            clauses.append("ts >= ?")
            params.append(float(since_ts))
        if topic_prefix:
            pref = topic_prefix.strip().lower().rstrip("*")
            if pref.endswith(".") or pref:
                clauses.append("(topic = ? OR topic LIKE ?)")
                params.extend([pref, f"{pref}%"])
        if severity:
            clauses.append("severity = ?")
            params.append(severity.strip().upper())
        if source:
            clauses.append("source = ?")
            params.append(source.strip())

        order = "ASC" if ascending else "DESC"
        sql = f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY seq {order} LIMIT ?"
        params.append(max(1, min(500, int(limit))))

        with self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def consume(
        self,
        consumer: str,
        *,
        topic_prefixes: Optional[Sequence[str]] = None,
        severities: Optional[Sequence[str]] = None,
        limit: int = 50,
        advance_cursor: bool = True,
    ) -> Dict[str, Any]:
        """Lee eventos nuevos desde el cursor duradero del consumidor y avanza el offset."""
        cname = (consumer or "default").strip()
        with self._lock:
            with self._connect() as con:
                row = con.execute(
                    "SELECT last_seq FROM consumer_cursors WHERE consumer = ?",
                    (cname,),
                ).fetchone()
                last_seq = int(row["last_seq"]) if row else 0

                rows = con.execute(
                    "SELECT * FROM events WHERE seq > ? ORDER BY seq ASC LIMIT ?",
                    (last_seq, max(1, min(500, int(limit) * 3))),
                ).fetchall()

                matched: List[Dict[str, Any]] = []
                max_seen = last_seq
                prefixes = [p.strip().lower().rstrip("*") for p in (topic_prefixes or []) if p]
                sevs = {s.strip().upper() for s in (severities or []) if s}

                for r in rows:
                    ev = self._row_to_event(r)
                    max_seen = max(max_seen, ev["seq"])
                    if prefixes and not any(ev["topic"].startswith(p) for p in prefixes):
                        continue
                    if sevs and ev["severity"] not in sevs:
                        continue
                    matched.append(ev)
                    if len(matched) >= limit:
                        break

                if advance_cursor and max_seen > last_seq:
                    con.execute(
                        """
                        INSERT INTO consumer_cursors (consumer, last_seq, updated_ts, updated_iso)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(consumer) DO UPDATE SET
                            last_seq = excluded.last_seq,
                            updated_ts = excluded.updated_ts,
                            updated_iso = excluded.updated_iso
                        """,
                        (cname, max_seen, time.time(), _now_iso()),
                    )

                return {
                    "ok": True,
                    "consumer": cname,
                    "previous_seq": last_seq,
                    "new_seq": max_seen if advance_cursor else last_seq,
                    "count": len(matched),
                    "events": matched,
                }

    def get_topics(self) -> List[Dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT topic, COUNT(*) AS count, MAX(iso) AS last_iso,
                       SUM(suppressed_count) AS suppressed_total
                FROM events
                GROUP BY topic
                ORDER BY count DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_cursors(self) -> List[Dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM consumer_cursors ORDER BY updated_ts DESC").fetchall()
        return [dict(r) for r in rows]

    def get_status(self) -> Dict[str, Any]:
        with self._connect() as con:
            total = int(con.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            max_seq = int(con.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0])
            cutoff_1h = time.time() - 3600.0
            last_1h = int(con.execute("SELECT COUNT(*) FROM events WHERE ts >= ?", (cutoff_1h,)).fetchone()[0])
            high_1h = int(
                con.execute(
                    "SELECT COUNT(*) FROM events WHERE ts >= ? AND severity IN ('HIGH', 'CRITICAL')",
                    (cutoff_1h,),
                ).fetchone()[0]
            )
            cursors = self.get_cursors()
            topics = self.get_topics()
        return {
            "ok": True,
            "db_path": str(self.db_path),
            "total_events": total,
            "latest_seq": max_seq,
            "events_last_1h": last_1h,
            "high_severity_last_1h": high_1h,
            "topics_count": len(topics),
            "top_topics": topics[:12],
            "cursors": cursors,
            "iso": _now_iso(),
        }


def get_event_bus(db_path: Optional[Path] = None) -> SovereignEventBus:
    return SovereignEventBus.get_instance(db_path=db_path)


def main() -> int:
    ap = argparse.ArgumentParser(prog="tardis-bus", description="TARDIS Sovereign Causal Event Bus")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Estado global del bus de eventos")
    sub.add_parser("topics", help="Lista de tópicos activos y conteos")
    sub.add_parser("cursors", help="Estado de cursores de consumidores")

    p_tail = sub.add_parser("tail", help="Últimos eventos registrados")
    p_tail.add_argument("--topic", default=None)
    p_tail.add_argument("--severity", default=None)
    p_tail.add_argument("--limit", type=int, default=20)

    p_pub = sub.add_parser("publish", help="Publicar un evento manual")
    p_pub.add_argument("topic")
    p_pub.add_argument("--source", default="cli")
    p_pub.add_argument("--severity", default="INFO")
    p_pub.add_argument("--payload", default="{}")
    p_pub.add_argument("--dedup", type=float, default=0.0)

    args = ap.parse_args()
    bus = get_event_bus()

    if args.cmd == "status":
        print(json.dumps(bus.get_status(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "topics":
        print(json.dumps({"ok": True, "topics": bus.get_topics()}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "cursors":
        print(json.dumps({"ok": True, "cursors": bus.get_cursors()}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "tail":
        evs = bus.query(topic_prefix=args.topic, severity=args.severity, limit=args.limit)
        print(json.dumps({"ok": True, "count": len(evs), "events": evs}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "publish":
        try:
            pl = json.loads(args.payload)
        except Exception:
            pl = {"message": args.payload}
        res = bus.publish(args.topic, args.source, pl, severity=args.severity, dedup_window_s=args.dedup)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
