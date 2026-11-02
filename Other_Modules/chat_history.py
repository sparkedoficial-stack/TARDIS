#!/usr/bin/env python3
"""
GODWORKS · FTL Unified History · Historial transversal de interacciones
=======================================================================
Un único flujo de memoria para *todas* las interacciones con FTL:

  chat      → sesiones del chat persistente (web, TUI, CLI, Telegram)
  terminal  → historial de la consola FTL (~/.config/ftl/history)
  tardis    → eventos operativos registrados en vault_master.db (fuente ftl*)
  vault     → peticiones blindadas (bóveda: enviadas, liberadas, expiradas)

API principal
-------------
    unified(query=None, limit=100, offset=0, source="all") -> dict
    stats() -> dict
    export_markdown(path=None, source="all", query=None) -> Path

El módulo es de sólo lectura sobre las fuentes y tolera que cualquiera de
ellas falte o esté bloqueada (SQLite en mantenimiento, portal caído, etc.).
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import chat_store as store
import chat_vault as vault

CONFIG_DIR = Path.home() / ".config" / "ftl"
TERMINAL_HISTORY = CONFIG_DIR / "history"
CHAT_HISTORY = CONFIG_DIR / "chat" / "history"
VAULT_DB = Path.home() / "vw-control" / "deep_memory_vault" / "vault_master.db"

SOURCES = ("chat", "terminal", "tardis", "vault")

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _epoch_from_iso(value: str) -> float:
    if not value:
        return 0.0
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _iso(ts: float) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def _short(text: str, limit: int = 220) -> str:
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def _entry(
    *,
    id_: str,
    ts: float,
    source: str,
    channel: str,
    role: str,
    text: str,
    title: str = "",
    session_id: Optional[str] = None,
    model: str = "",
    meta: Optional[dict] = None,
) -> dict:
    text = _ANSI.sub("", text or "").strip()
    return {
        "id": id_,
        "ts": ts,
        "iso": _iso(ts),
        "source": source,
        "channel": channel,
        "role": role,
        "title": title or _short(text, 90),
        "text": text,
        "preview": _short(text, 240),
        "session_id": session_id,
        "model": model,
        "meta": meta or {},
    }


# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------
def _chat_entries(query: str) -> list[dict]:
    rows: list[dict] = []
    for summary in store.list_sessions():
        session = store.load_session(summary.get("id") or "")
        if not session:
            continue
        title = session.get("title") or "Nueva conversación"
        model = session.get("model") or ""
        for message in session.get("messages") or []:
            role = message.get("role") or "assistant"
            if role == "tool":
                continue
            content = message.get("content") or ""
            ts = _epoch_from_iso(message.get("ts") or session.get("updated_at") or "")
            rows.append(_entry(
                id_=f"chat:{session['id']}:{message.get('id') or ts}",
                ts=ts,
                source="chat",
                channel="chat",
                role=role,
                text=content,
                title=title,
                session_id=session.get("id"),
                model=message.get("model") or model,
                meta={
                    "tools": len(message.get("tools") or []),
                    "opencode_session_id": session.get("opencode_session_id"),
                    "agent": session.get("agent") or "",
                },
            ))
    return rows


def _parse_prompt_history(path: Path, channel: str) -> list[dict]:
    """Lee el formato prompt_toolkit: '# timestamp' seguido de '+texto'."""
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    rows: list[dict] = []
    stamp = 0.0
    buffer: list[str] = []
    order = 0

    def flush() -> None:
        nonlocal buffer, order
        text = "\n".join(buffer).strip()
        buffer = []
        if not text:
            return
        order += 1
        rows.append(_entry(
            id_=f"{channel}:{int(stamp * 1000)}:{order}",
            ts=stamp or time.time(),
            source="terminal",
            channel=channel,
            role="user",
            text=text,
            title="Consola FTL",
            meta={"history_file": str(path)},
        ))

    for line in lines:
        if line.startswith("# "):
            flush()
            stamp = _epoch_from_iso(line[2:].strip()) or _epoch_from_iso(line[2:].strip().split(".")[0])
        elif line.startswith("+"):
            buffer.append(line[1:])
        else:
            buffer.append(line)
    flush()
    return rows


def _tardis_entries(limit: int = 400) -> list[dict]:
    if not VAULT_DB.is_file():
        return []
    rows: list[dict] = []
    try:
        con = sqlite3.connect(f"file:{VAULT_DB}?mode=ro", uri=True, timeout=2.5)
        try:
            cursor = con.execute(
                """SELECT id, ts, iso, source, role, content, meta
                   FROM vault_events
                   WHERE source LIKE 'ftl%' OR source LIKE '%opencode%' OR source LIKE '%tardis%'
                   ORDER BY id DESC LIMIT ?""",
                (int(limit),),
            )
            for row in cursor.fetchall():
                meta_raw = row[6] or "{}"
                try:
                    meta = json.loads(meta_raw)
                except Exception:
                    meta = {}
                ts = float(row[1] or 0) or _epoch_from_iso(row[2] or "")
                if ts > 1e11:
                    ts = ts / 1000.0
                prompt = meta.get("command") or meta.get("prompt") or row[5] or ""
                rows.append(_entry(
                    id_=f"tardis:{row[0]}",
                    ts=ts,
                    source="tardis",
                    channel=row[3] or "ftl",
                    role=row[4] or "assistant",
                    text=prompt,
                    title="Operación TARDIS",
                    model=str(meta.get("model") or ""),
                    meta={
                        "returncode": meta.get("returncode"),
                        "mode": meta.get("mode"),
                        "files_changed": meta.get("files_changed") or [],
                        "response": _short(row[5] or "", 500),
                    },
                ))
        finally:
            con.close()
    except Exception:
        return rows
    return rows


def _vault_entries(limit: int = 120) -> list[dict]:
    rows: list[dict] = []
    for draft in vault.drafts_summary(limit=limit):
        text = draft.get("preview") or ""
        ts = _epoch_from_iso(draft.get("closed_at") or draft.get("created_at") or "")
        state = draft.get("state") or "draft"
        labels = {
            "sent": "Petición enviada",
            "released": "Borrador liberado",
            "expired": "Borrador expirado",
            "superseded": "Bóveda reemplazada",
            "cancelled": "Petición cancelada",
            "discarded": "Borrador descartado",
        }
        rows.append(_entry(
            id_=f"vault:{draft.get('draft_id')}",
            ts=ts,
            source="vault",
            channel="bóveda",
            role="user",
            text=text,
            title=labels.get(state, "Bóveda de petición"),
            session_id=draft.get("session_id"),
            meta={
                "draft_id": draft.get("draft_id"),
                "state": state,
                "chars": draft.get("chars"),
                "run_id": draft.get("run_id"),
                "checksum": draft.get("checksum"),
            },
        ))
    return rows


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def _gather(source: str = "all", query: str = "") -> list[dict]:
    wanted = set(SOURCES) if source in ("", "all", "*") else {source}
    rows: list[dict] = []

    try:
        if "chat" in wanted:
            rows.extend(_chat_entries(query))
    except Exception:
        pass
    try:
        if "terminal" in wanted:
            rows.extend(_parse_prompt_history(TERMINAL_HISTORY, "consola"))
            rows.extend(_parse_prompt_history(CHAT_HISTORY, "chat-cli"))
    except Exception:
        pass
    try:
        if "tardis" in wanted:
            rows.extend(_tardis_entries())
    except Exception:
        pass
    try:
        if "vault" in wanted:
            rows.extend(_vault_entries())
    except Exception:
        pass

    if query:
        needle = query.lower().strip()
        tokens = [t for t in needle.split() if t]
        def matches(row: dict) -> bool:
            haystack = " ".join([
                row.get("title") or "",
                row.get("text") or "",
                row.get("model") or "",
                row.get("channel") or "",
                row.get("session_id") or "",
            ]).lower()
            return all(t in haystack for t in tokens)
        rows = [r for r in rows if matches(r)]

    # Deduplicar por id y ordenar de más reciente a más antiguo.
    unique: dict[str, dict] = {}
    for row in rows:
        unique.setdefault(row["id"], row)
    rows = sorted(unique.values(), key=lambda r: (r.get("ts") or 0), reverse=True)
    return rows


def unified(
    query: Optional[str] = None,
    *,
    limit: int = 100,
    offset: int = 0,
    source: str = "all",
) -> dict:
    rows = _gather(source=source, query=query or "")
    total = len(rows)
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    page = rows[offset: offset + limit]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["source"]] = counts.get(row["source"], 0) + 1
    return {
        "ok": True,
        "total": total,
        "offset": offset,
        "limit": limit,
        "source": source or "all",
        "query": query or "",
        "counts": counts,
        "entries": page,
        "generated_at": _iso(time.time()),
    }


def stats() -> dict:
    data = unified(limit=1)
    return {
        "ok": True,
        "total": data["total"],
        "counts": data["counts"],
        "sources": list(SOURCES),
        "terminal_history": str(TERMINAL_HISTORY),
        "vault_db": str(VAULT_DB),
        "generated_at": data["generated_at"],
    }


def export_markdown(path: Optional[str] = None, *, source: str = "all", query: str = "") -> Path:
    data = unified(query=query, limit=500, source=source)
    lines = [
        "# FTL · Historial Unificado de Interacciones",
        "",
        f"- **Generado:** {data['generated_at']}",
        f"- **Fuente:** `{source}`",
        f"- **Consulta:** {query or '—'}",
        f"- **Entradas:** {data['total']}",
        "",
        "---",
        "",
    ]
    for row in data["entries"]:
        badge = {"chat": "💬", "terminal": "⌨", "tardis": "◉", "vault": "🛡"}.get(row["source"], "·")
        lines += [
            f"## {badge} {row['iso']} · {row['source']} · {row['role']}",
            "",
            f"> {row['title']}",
            "",
            row["text"],
            "",
            "---",
            "",
        ]
    target = Path(path).expanduser() if path else store.EXPORTS_DIR / "historial_ftl_unificado.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="FTL · historial unificado de interacciones")
    parser.add_argument("--query", "-q", default="")
    parser.add_argument("--source", default="all", choices=["all", *SOURCES])
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--export", nargs="?", const="", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.stats:
        print(json.dumps(stats(), indent=2, ensure_ascii=False))
        return 0
    if args.export is not None:
        print(export_markdown(args.export or None, source=args.source, query=args.query))
        return 0
    data = unified(args.query, limit=args.limit, offset=args.offset, source=args.source)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    print(f"— {data['total']} interacciones · fuente={data['source']} · q={data['query'] or '—'} —")
    for row in data["entries"]:
        print(f"[{row['iso']}] ({row['source']}/{row['role']}) {row['preview'][:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
