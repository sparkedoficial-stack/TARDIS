#!/usr/bin/env python3
"""
GODWORKS · FTL Chat Store
=========================
Persistencia soberana de conversaciones para la interfaz de chat FTL.

Estructura:
  ~/.config/ftl/chat/
    index.json                 índice de sesiones
    history                    historial de prompt_toolkit
    sessions/<id>.json         conversación completa (mensajes, stats, metadata)
    exports/                   exportaciones markdown/json

Cada sesión guarda:
  - id FTL, título, timestamps, cwd
  - modelo y agente activos
  - opencode_session_id (continuidad real en OpenCode)
  - mensajes (user / assistant / tool / system)
  - estadísticas (turnos, tokens, coste, tool calls)
  - settings (thinking, auto)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

CHAT_DIR = Path.home() / ".config" / "ftl" / "chat"
SESSIONS_DIR = CHAT_DIR / "sessions"
EXPORTS_DIR = CHAT_DIR / "exports"
INDEX_FILE = CHAT_DIR / "index.json"
HISTORY_FILE = CHAT_DIR / "history"

INDEX_VERSION = 1


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def ensure_dirs() -> None:
    for path in (CHAT_DIR, SESSIONS_DIR, EXPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _atomic_json(path: Path, data) -> None:
    ensure_dirs()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def _short(text: str, limit: int = 64) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Índice
# ---------------------------------------------------------------------------
def _default_index() -> dict:
    return {"version": INDEX_VERSION, "last_session": None, "sessions": []}


def load_index() -> dict:
    try:
        raw = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw.setdefault("version", INDEX_VERSION)
            raw.setdefault("last_session", None)
            raw.setdefault("sessions", [])
            return raw
    except Exception:
        pass
    return _default_index()


def save_index(index: dict) -> None:
    _atomic_json(INDEX_FILE, index)


def _index_entry(session: dict) -> dict:
    messages = session.get("messages", [])
    last_user = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    return {
        "id": session["id"],
        "title": session.get("title") or "Nueva conversación",
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "model": session.get("model"),
        "agent": session.get("agent", ""),
        "opencode_session_id": session.get("opencode_session_id"),
        "message_count": len(messages),
        "turns": int(session.get("stats", {}).get("turns", 0)),
        "preview": _short(last_user, 90),
    }


def _upsert_index(session: dict) -> None:
    index = load_index()
    entry = _index_entry(session)
    sessions = [s for s in index.get("sessions", []) if s.get("id") != session["id"]]
    sessions.append(entry)
    sessions.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    index["sessions"] = sessions
    index["last_session"] = session["id"]
    save_index(index)


# ---------------------------------------------------------------------------
# Sesiones
# ---------------------------------------------------------------------------
def new_session(
    model: str,
    agent: str = "",
    cwd: Optional[str] = None,
    title: str = "Nueva conversación",
    thinking: bool = False,
    auto: bool = True,
) -> dict:
    ensure_dirs()
    ts = now_iso()
    session = {
        "id": "ftlchat_" + uuid.uuid4().hex[:12],
        "title": title,
        "created_at": ts,
        "updated_at": ts,
        "cwd": str(Path(cwd or os.getcwd()).expanduser()),
        "model": model,
        "agent": agent,
        "opencode_session_id": None,
        "messages": [],
        "stats": {
            "turns": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost": 0.0,
            "tool_calls": 0,
        },
        "settings": {"thinking": bool(thinking), "auto": bool(auto)},
        "version": 1,
    }
    save_session(session)
    return session


def save_session(session: dict) -> None:
    session["updated_at"] = now_iso()
    _atomic_json(_session_path(session["id"]), session)
    _upsert_index(session)


def load_session(session_id: str) -> Optional[dict]:
    if not session_id:
        return None
    candidates = [session_id, session_id if session_id.startswith("ftlchat_") else f"ftlchat_{session_id}"]
    for cand in candidates:
        path = _session_path(cand)
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("id"):
                    data.setdefault("messages", [])
                    data.setdefault("stats", {})
                    data.setdefault("settings", {"thinking": False, "auto": True})
                    return data
        except Exception:
            continue
    return None


def latest_session() -> Optional[dict]:
    index = load_index()
    last_id = index.get("last_session")
    if last_id:
        session = load_session(last_id)
        if session:
            return session
    sessions = list_sessions()
    return load_session(sessions[0]["id"]) if sessions else None


def list_sessions() -> list[dict]:
    index = load_index()
    sessions = list(index.get("sessions", []))
    sessions.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    return sessions


def delete_session(session_id: str) -> bool:
    session = load_session(session_id)
    if not session:
        return False
    try:
        _session_path(session["id"]).unlink(missing_ok=True)
    except Exception:
        pass
    index = load_index()
    index["sessions"] = [s for s in index.get("sessions", []) if s.get("id") != session["id"]]
    if index.get("last_session") == session["id"]:
        remaining = sorted(
            index["sessions"], key=lambda s: s.get("updated_at") or "", reverse=True
        )
        index["last_session"] = remaining[0]["id"] if remaining else None
    save_index(index)
    return True


# ---------------------------------------------------------------------------
# Mensajes y métricas
# ---------------------------------------------------------------------------
def add_message(
    session: dict,
    role: str,
    content: str = "",
    *,
    model: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    meta: Optional[dict] = None,
) -> dict:
    message = {
        "id": "msg_" + uuid.uuid4().hex[:10],
        "role": role,
        "content": content or "",
        "ts": now_iso(),
        "model": model or session.get("model"),
        "tools": tools or [],
        "meta": meta or {},
    }
    session.setdefault("messages", []).append(message)
    is_first_user = (
        role == "user"
        and sum(1 for m in session["messages"] if m.get("role") == "user") == 1
    )
    if is_first_user and (not session.get("title") or session["title"] == "Nueva conversación"):
        session["title"] = _short(content, 58) or "Nueva conversación"
    save_session(session)
    return message


def record_turn(
    session: dict,
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost: float = 0.0,
    tool_calls: int = 0,
) -> None:
    stats = session.setdefault("stats", {})
    stats["turns"] = int(stats.get("turns", 0)) + 1
    stats["tokens_in"] = int(stats.get("tokens_in", 0)) + int(tokens_in or 0)
    stats["tokens_out"] = int(stats.get("tokens_out", 0)) + int(tokens_out or 0)
    stats["cost"] = round(float(stats.get("cost", 0.0)) + float(cost or 0.0), 6)
    stats["tool_calls"] = int(stats.get("tool_calls", 0)) + int(tool_calls or 0)
    save_session(session)


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
def export_markdown(session: dict, output: Optional[str] = None) -> Path:
    ensure_dirs()
    lines = [
        f"# {session.get('title') or 'Conversación FTL'}",
        "",
        f"- **Sesión FTL:** `{session.get('id')}`",
        f"- **Sesión OpenCode:** `{session.get('opencode_session_id') or '—'}`",
        f"- **Modelo:** `{session.get('model')}`",
        f"- **Agente:** `{session.get('agent') or '—'}`",
        f"- **Creada:** {session.get('created_at')}",
        f"- **Actualizada:** {session.get('updated_at')}",
        f"- **Directorio:** `{session.get('cwd')}`",
        f"- **Turnos:** {session.get('stats', {}).get('turns', 0)}",
        f"- **Tokens:** in {session.get('stats', {}).get('tokens_in', 0)} / "
        f"out {session.get('stats', {}).get('tokens_out', 0)}",
        f"- **Coste:** ${session.get('stats', {}).get('cost', 0.0)}",
        "",
        "---",
        "",
    ]
    for msg in session.get("messages", []):
        role = msg.get("role", "?")
        if role == "user":
            lines += ["## 🧑 Arquitecto", "", msg.get("content", ""), ""]
        elif role == "assistant":
            lines += ["## ◉ FTL", "", msg.get("content", ""), ""]
            for tool in msg.get("tools", []):
                lines += [
                    f"<details><summary>⚙ {tool.get('tool', 'tool')} · "
                    f"{tool.get('status', '')}</summary>",
                    "",
                    "```",
                    str(tool.get("output", ""))[:4000],
                    "```",
                    "</details>",
                    "",
                ]
        elif role == "system":
            lines += [f"> {msg.get('content', '')}", ""]
    text = "\n".join(lines)
    path = Path(output).expanduser() if output else EXPORTS_DIR / f"{session['id']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def export_json(session: dict, output: Optional[str] = None) -> Path:
    ensure_dirs()
    path = Path(output).expanduser() if output else EXPORTS_DIR / f"{session['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
