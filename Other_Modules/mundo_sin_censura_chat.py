"""
core/mundo_sin_censura_chat.py - Motor de Chat Exclusivo "Un Mundo Sin Censura"
===============================================================================
Chat 100% aislado y bloqueado exclusivamente al modelo soberano local
`mundo-sin-censura` (Llama 3.1 8B Q4_K_M, dual-lane TemporalBrain CUDA + Ollama).

Garantías arquitectónicas:
  1. Bloqueo estricto de modelo (`MODEL_LOCK = "mundo-sin-censura"`):
     Cualquier intento de enrutar a otro modelo distinto lanza `ModelLockError`
     (HTTP 403 en la API).
  2. Persistencia aislada en SQLite WAL (`data/mundo_sin_censura_chat.db`)
     compartida entre la interfaz Web (`/mundo-sin-censura`) y el REPL de
     terminal (`mundo-chat`), independiente del historial general de TARDIS.
  3. Streaming token a token con cancelación cooperativa en vuelo (`cancel_event`).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

PROJECT_ROOT = Path("/home/m11/Escritorio/GODWORKS SYSTEM").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.mundo_sin_censura import (
    MODEL_NAME,
    get_mundo_sin_censura,
    is_mundo_sin_censura_model,
)

CHAT_DB_PATH = PROJECT_ROOT / "data" / "mundo_sin_censura_chat.db"
MODEL_LOCK = MODEL_NAME  # "mundo-sin-censura"
VALID_LANES = ("auto", "temporal_brain", "ollama")


class ModelLockError(PermissionError):
    """Se lanza si se intenta usar cualquier modelo distinto a `mundo-sin-censura`."""


def enforce_model_lock(requested_model: Optional[str]) -> str:
    """Valida que la petición sólo apunte a `mundo-sin-censura`."""
    if requested_model is None or str(requested_model).strip() == "":
        return MODEL_LOCK
    if not is_mundo_sin_censura_model(requested_model):
        raise ModelLockError(
            f"Este chat es exclusivo de '{MODEL_LOCK}'. "
            f"Modelo rechazado: '{requested_model}'."
        )
    return MODEL_LOCK


def normalize_lane(lane: Optional[str]) -> str:
    val = (lane or "auto").strip().lower()
    return val if val in VALID_LANES else "auto"


class MundoSinCensuraChatStore:
    """Almacén SQLite WAL y orquestador de sesiones exclusivas de `mundo-sin-censura`."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else CHAT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_lock = threading.RLock()
        self._cancel_lock = threading.Lock()
        self._active_cancels: Dict[str, threading.Event] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._db_lock:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL DEFAULT 'Nueva conversación',
                        model TEXT NOT NULL DEFAULT 'mundo-sin-censura',
                        lane TEXT NOT NULL DEFAULT 'auto',
                        temperature REAL NOT NULL DEFAULT 0.25,
                        max_tokens INTEGER NOT NULL DEFAULT 1024,
                        use_rag INTEGER NOT NULL DEFAULT 0,
                        hardware_control INTEGER NOT NULL DEFAULT 1,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        model TEXT NOT NULL DEFAULT 'mundo-sin-censura',
                        lane TEXT DEFAULT NULL,
                        elapsed_s REAL DEFAULT NULL,
                        approx_tokens INTEGER DEFAULT NULL,
                        cancelled INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_msc_messages_session
                        ON messages(session_id, id);
                    CREATE INDEX IF NOT EXISTS idx_msc_sessions_updated
                        ON sessions(updated_at DESC);
                    """
                )
                # Migración retrocompatible para bases SQLite existentes sin columna hardware_control
                cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
                if "hardware_control" not in cols:
                    conn.execute("ALTER TABLE sessions ADD COLUMN hardware_control INTEGER NOT NULL DEFAULT 1")

    # ------------------------------------------------------------------
    # Control de cancelación de streams en vuelo
    # ------------------------------------------------------------------
    def register_stream(self, request_id: Optional[str] = None) -> tuple[str, threading.Event]:
        rid = request_id or f"msc_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        ev = threading.Event()
        with self._cancel_lock:
            self._active_cancels[rid] = ev
        return rid, ev

    def cancel_stream(self, request_id: str) -> bool:
        with self._cancel_lock:
            ev = self._active_cancels.get(request_id)
            if ev is not None:
                ev.set()
                return True
        return False

    def unregister_stream(self, request_id: str) -> None:
        with self._cancel_lock:
            self._active_cancels.pop(request_id, None)

    # ------------------------------------------------------------------
    # CRUD de sesiones exclusivas
    # ------------------------------------------------------------------
    def create_session(
        self,
        title: Optional[str] = None,
        *,
        lane: str = "auto",
        temperature: float = 0.25,
        max_tokens: int = 1024,
        use_rag: bool = False,
        hardware_control: bool = True,
    ) -> Dict[str, Any]:
        sid = f"msc_{uuid.uuid4().hex[:12]}"
        now = time.time()
        clean_title = (title or "Nueva conversación").strip()[:120] or "Nueva conversación"
        clean_lane = normalize_lane(lane)
        temp = max(0.0, min(1.5, float(temperature)))
        mtok = max(64, min(4096, int(max_tokens)))
        rag_flag = 1 if use_rag else 0
        hw_flag = 1 if hardware_control else 0

        with self._db_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sessions (id, title, model, lane, temperature, max_tokens, use_rag, hardware_control, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sid, clean_title, MODEL_LOCK, clean_lane, temp, mtok, rag_flag, hw_flag, now, now),
                )
        return self.get_session(sid)  # type: ignore[return-value]

    def list_sessions(self, limit: int = 100) -> List[Dict[str, Any]]:
        lim = max(1, min(500, int(limit)))
        with self._db_lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT s.*,
                           COUNT(m.id) AS message_count,
                           (SELECT content FROM messages
                             WHERE session_id = s.id
                             ORDER BY id DESC LIMIT 1) AS last_preview
                      FROM sessions s
                 LEFT JOIN messages m ON m.session_id = s.id
                  GROUP BY s.id
                  ORDER BY s.updated_at DESC
                     LIMIT ?
                    """,
                    (lim,),
                ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["use_rag"] = bool(d.get("use_rag"))
            d["hardware_control"] = bool(d.get("hardware_control", 1))
            d["last_preview"] = str(d.get("last_preview") or "")[:120]
            out.append(d)
        return out

    def get_session(self, session_id: str, include_messages: bool = True) -> Optional[Dict[str, Any]]:
        with self._db_lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
                if row is None:
                    return None
                sess = dict(row)
                sess["use_rag"] = bool(sess.get("use_rag"))
                sess["hardware_control"] = bool(sess.get("hardware_control", 1))
                sess["model"] = MODEL_LOCK
                if include_messages:
                    mrows = conn.execute(
                        "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
                        (session_id,),
                    ).fetchall()
                    msgs = []
                    for mr in mrows:
                        md = dict(mr)
                        md["cancelled"] = bool(md.get("cancelled"))
                        msgs.append(md)
                    sess["messages"] = msgs
                    sess["message_count"] = len(msgs)
        return sess

    def update_session(
        self,
        session_id: str,
        *,
        title: Optional[str] = None,
        lane: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        use_rag: Optional[bool] = None,
        hardware_control: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        sess = self.get_session(session_id, include_messages=False)
        if not sess:
            return None
        new_title = sess["title"] if title is None else ((title.strip()[:120]) or sess["title"])
        new_lane = sess["lane"] if lane is None else normalize_lane(lane)
        new_temp = sess["temperature"] if temperature is None else max(0.0, min(1.5, float(temperature)))
        new_mtok = sess["max_tokens"] if max_tokens is None else max(64, min(4096, int(max_tokens)))
        new_rag = int(sess["use_rag"]) if use_rag is None else (1 if use_rag else 0)
        new_hw = int(sess.get("hardware_control", True)) if hardware_control is None else (1 if hardware_control else 0)
        now = time.time()
        with self._db_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE sessions
                       SET title = ?, lane = ?, temperature = ?, max_tokens = ?, use_rag = ?, hardware_control = ?, updated_at = ?
                     WHERE id = ?
                    """,
                    (new_title, new_lane, new_temp, new_mtok, new_rag, new_hw, now, session_id),
                )
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        with self._db_lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                return cur.rowcount > 0

    def clear_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        sess = self.get_session(session_id, include_messages=False)
        if not sess:
            return None
        now = time.time()
        with self._db_lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return self.get_session(session_id)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        lane: Optional[str] = None,
        elapsed_s: Optional[float] = None,
        approx_tokens: Optional[int] = None,
        cancelled: bool = False,
    ) -> Dict[str, Any]:
        now = time.time()
        with self._db_lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO messages (session_id, role, content, model, lane, elapsed_s, approx_tokens, cancelled, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        role,
                        content,
                        MODEL_LOCK,
                        lane,
                        elapsed_s,
                        approx_tokens,
                        1 if cancelled else 0,
                        now,
                    ),
                )
                msg_id = cur.lastrowid
                conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return {
            "id": msg_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "model": MODEL_LOCK,
            "lane": lane,
            "elapsed_s": elapsed_s,
            "approx_tokens": approx_tokens,
            "cancelled": cancelled,
            "created_at": now,
        }

    def export_session(self, session_id: str, fmt: str = "markdown") -> Optional[Dict[str, Any]]:
        sess = self.get_session(session_id, include_messages=True)
        if not sess:
            return None
        fmt_l = (fmt or "markdown").strip().lower()
        if fmt_l == "json":
            return {
                "ok": True,
                "format": "json",
                "filename": f"{session_id}.json",
                "content": json.dumps(sess, indent=2, ensure_ascii=False),
            }
        lines = [
            f"# {sess['title']}",
            f"- **Modelo exclusivo:** `{MODEL_LOCK}`",
            f"- **Sesión:** `{session_id}`",
            f"- **Carril:** `{sess['lane']}` · **Temperatura:** `{sess['temperature']}`",
            "",
            "---",
            "",
        ]
        for m in sess.get("messages", []):
            who = "Usuario" if m["role"] == "user" else "Un Mundo Sin Censura"
            meta = ""
            if m["role"] == "assistant" and m.get("elapsed_s") is not None:
                meta = f" _({m.get('lane') or 'auto'} · {m['elapsed_s']}s)_"
            lines.append(f"### {who}{meta}\n\n{m['content']}\n")
        return {
            "ok": True,
            "format": "markdown",
            "filename": f"{session_id}.md",
            "content": "\n".join(lines),
        }

    # ------------------------------------------------------------------
    # Ejecución de turno de chat estrictamente bloqueado a mundo-sin-censura
    # ------------------------------------------------------------------
    def _recent_history(self, session_id: str, max_turns: int = 24) -> List[Dict[str, str]]:
        sess = self.get_session(session_id, include_messages=True)
        if not sess:
            return []
        msgs = [
            {"role": m["role"], "content": m["content"]}
            for m in sess.get("messages", [])
            if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()
        ]
        return msgs[-max_turns:]

    def stream_turn(
        self,
        *,
        session_id: Optional[str],
        message: str,
        model: Optional[str] = None,
        lane: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        num_ctx: int = 8192,
        use_rag: Optional[bool] = None,
        hardware_control: Optional[bool] = None,
        is_local_request: bool = True,
        timeout: float = 180.0,
        request_id: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Ejecuta un turno de chat streaming persistiendo usuario y asistente en SQLite,
        con soporte nativo de control absoluto de hardware (`/hw` y directivas `[[HW_ACTION:...]]`)."""
        enforce_model_lock(model)
        prompt = (message or "").strip()
        if not prompt:
            raise ValueError("El mensaje no puede estar vacío.")

        sess = self.get_session(session_id, include_messages=True) if session_id else None
        if sess is None:
            sess = self.create_session(
                title=prompt[:54],
                lane=normalize_lane(lane),
                temperature=0.25 if temperature is None else float(temperature),
                max_tokens=1024 if max_tokens is None else int(max_tokens),
                use_rag=bool(use_rag) if use_rag is not None else False,
                hardware_control=True if hardware_control is None else bool(hardware_control),
            )
            session_id = sess["id"]
        else:
            # Auto-titular en el primer mensaje real
            if sess["title"] == "Nueva conversación" and not sess.get("messages"):
                sess = self.update_session(sess["id"], title=prompt[:54]) or sess

        eff_lane = normalize_lane(lane if lane is not None else sess["lane"])
        eff_temp = max(0.0, min(1.5, float(temperature if temperature is not None else sess["temperature"])))
        eff_mtok = max(64, min(4096, int(max_tokens if max_tokens is not None else sess["max_tokens"])))
        eff_rag = bool(use_rag if use_rag is not None else sess["use_rag"])
        eff_hw = bool(hardware_control if hardware_control is not None else sess.get("hardware_control", True))

        self.update_session(
            sess["id"],
            lane=eff_lane,
            temperature=eff_temp,
            max_tokens=eff_mtok,
            use_rag=eff_rag,
            hardware_control=eff_hw,
        )

        # Guardar turno del usuario antes de inferir
        user_msg = self.add_message(sess["id"], "user", prompt)
        history = self._recent_history(sess["id"], max_turns=24)

        rid, cancel_ev = self.register_stream(request_id)

        # 1. Comando directo `/hw <accion> [params]` (latencia cero, ejecución física inmediata)
        try:
            from core.mundo_sin_censura_hardware import (
                build_hardware_system_context,
                format_hardware_result_markdown,
                get_mundo_hardware_controller,
                parse_hardware_actions,
                parse_slash_hw_command,
            )
            hw_ctrl = get_mundo_hardware_controller()
        except Exception:
            hw_ctrl = None
            build_hardware_system_context = None  # type: ignore[assignment]
            format_hardware_result_markdown = None  # type: ignore[assignment]
            parse_hardware_actions = None  # type: ignore[assignment]
            parse_slash_hw_command = None  # type: ignore[assignment]

        slash_hw = parse_slash_hw_command(prompt) if (parse_slash_hw_command and eff_hw) else None
        if slash_hw is not None and hw_ctrl is not None:
            hw_act, hw_params = slash_hw
            t0 = time.time()
            yield {
                "type": "meta",
                "session_id": sess["id"],
                "title": sess["title"],
                "request_id": rid,
                "user_message_id": user_msg["id"],
                "model": MODEL_LOCK,
                "lane": "hardware_ring0",
                "requested_lane": eff_lane,
                "use_rag": eff_rag,
                "hardware_control": eff_hw,
            }
            yield {
                "type": "hardware_action",
                "action": hw_act,
                "params": hw_params,
                "session_id": sess["id"],
                "request_id": rid,
            }
            hw_res = hw_ctrl.execute_action(
                hw_act,
                hw_params,
                is_local_request=is_local_request,
                source="mundo_chat_direct_hw",
            )
            yield {
                "type": "hardware_result",
                "action": hw_act,
                "params": hw_params,
                "result": hw_res,
                "ok": bool(hw_res.get("ok")),
                "session_id": sess["id"],
                "request_id": rid,
            }
            md_txt = format_hardware_result_markdown(hw_act, hw_res).strip()  # type: ignore[misc]
            yield {
                "type": "token",
                "delta": md_txt,
                "session_id": sess["id"],
                "request_id": rid,
            }
            self.unregister_stream(rid)
            elapsed = round(time.time() - t0, 3)
            saved = self.add_message(
                sess["id"],
                "assistant",
                md_txt,
                lane="hardware_ring0",
                elapsed_s=elapsed,
                approx_tokens=max(1, len(md_txt.split())),
                cancelled=False,
            )
            yield {
                "type": "done",
                "session_id": sess["id"],
                "title": sess["title"],
                "request_id": rid,
                "message_id": saved["id"],
                "model": MODEL_LOCK,
                "lane": "hardware_ring0",
                "elapsed_s": elapsed,
                "approx_tokens": max(1, len(md_txt.split())),
                "cancelled": False,
                "ok": bool(hw_res.get("ok")),
                "hardware_actions": [{"action": hw_act, "ok": bool(hw_res.get("ok"))}],
            }
            return

        agent = get_mundo_sin_censura()
        effective_lane = eff_lane
        if eff_lane == "auto":
            tb_ready = agent.inspect_temporal_brain(timeout=0.8).get("ready")
            effective_lane = "temporal_brain" if tb_ready else "ollama"

        hw_armed = bool(eff_hw and hw_ctrl is not None and hw_ctrl.is_armed() and hw_ctrl._state.get("agentic_hw_in_chat", True))
        extra_sys = build_hardware_system_context(include_snapshot=True) if (hw_armed and build_hardware_system_context) else None

        yield {
            "type": "meta",
            "session_id": sess["id"],
            "title": sess["title"],
            "request_id": rid,
            "user_message_id": user_msg["id"],
            "model": MODEL_LOCK,
            "lane": effective_lane,
            "requested_lane": eff_lane,
            "use_rag": eff_rag,
            "hardware_control": hw_armed,
        }

        t0 = time.time()
        chunks: List[str] = []
        error_text: Optional[str] = None
        executed_hw: List[Dict[str, Any]] = []
        try:
            stream_kwargs: Dict[str, Any] = {
                "lane": eff_lane,
                "temperature": eff_temp,
                "max_tokens": eff_mtok,
                "num_ctx": num_ctx,
                "use_rag": eff_rag,
                "timeout": timeout,
                "cancel_event": cancel_ev,
            }
            if extra_sys:
                stream_kwargs["extra_system"] = extra_sys
            for tok in agent.chat_stream(history, **stream_kwargs):
                if not tok:
                    continue
                chunks.append(tok)
                yield {
                    "type": "token",
                    "delta": tok,
                    "session_id": sess["id"],
                    "request_id": rid,
                }

            # 2. Ejecución agéntica de directivas [[HW_ACTION:{...}]] emitidas por mundo-sin-censura
            if hw_armed and hw_ctrl is not None and parse_hardware_actions and not cancel_ev.is_set():
                raw_reply = "".join(chunks)
                hw_cmds = parse_hardware_actions(raw_reply)[:6]
                for item in hw_cmds:
                    act = item["action"]
                    act_params = item.get("params") or {}
                    yield {
                        "type": "hardware_action",
                        "action": act,
                        "params": act_params,
                        "session_id": sess["id"],
                        "request_id": rid,
                    }
                    hw_res = hw_ctrl.execute_action(
                        act,
                        act_params,
                        is_local_request=is_local_request,
                        source="mundo_chat_agentic",
                    )
                    executed_hw.append({"action": act, "ok": bool(hw_res.get("ok")), "result": hw_res})
                    yield {
                        "type": "hardware_result",
                        "action": act,
                        "params": act_params,
                        "result": hw_res,
                        "ok": bool(hw_res.get("ok")),
                        "session_id": sess["id"],
                        "request_id": rid,
                    }
                    md_piece = format_hardware_result_markdown(act, hw_res)  # type: ignore[misc]
                    chunks.append(md_piece)
                    yield {
                        "type": "token",
                        "delta": md_piece,
                        "session_id": sess["id"],
                        "request_id": rid,
                    }
        except Exception as e:
            error_text = f"[Error de inferencia]: {e}"
            chunks.append(error_text)
            yield {
                "type": "error",
                "error": str(e),
                "session_id": sess["id"],
                "request_id": rid,
            }
        finally:
            self.unregister_stream(rid)

        elapsed = round(time.time() - t0, 3)
        full_reply = "".join(chunks).strip()
        cancelled = bool(cancel_ev.is_set())
        approx_tokens = max(1, len(chunks)) if full_reply else 0

        saved = self.add_message(
            sess["id"],
            "assistant",
            full_reply or "[Sin respuesta]",
            lane=effective_lane,
            elapsed_s=elapsed,
            approx_tokens=approx_tokens,
            cancelled=cancelled,
        )

        yield {
            "type": "done",
            "session_id": sess["id"],
            "title": sess["title"],
            "request_id": rid,
            "message_id": saved["id"],
            "model": MODEL_LOCK,
            "lane": effective_lane,
            "elapsed_s": elapsed,
            "approx_tokens": approx_tokens,
            "cancelled": cancelled,
            "ok": bool(full_reply and not error_text),
            "hardware_actions": [{"action": x["action"], "ok": x["ok"]} for x in executed_hw],
        }


_CHAT_STORE_LOCK = threading.Lock()
_CHAT_STORE: Optional[MundoSinCensuraChatStore] = None


def get_mundo_chat_store() -> MundoSinCensuraChatStore:
    global _CHAT_STORE
    with _CHAT_STORE_LOCK:
        if _CHAT_STORE is None:
            _CHAT_STORE = MundoSinCensuraChatStore()
        return _CHAT_STORE


# ==============================================================================
# REPL INTERACTIVO DE TERMINAL EXCLUSIVO (`mundo-chat`)
# ==============================================================================

_C_RESET = "\033[0m"
_C_BOLD = "\033[1m"
_C_DIM = "\033[2m"
_C_EMERALD = "\033[38;5;48m"
_C_AMBER = "\033[38;5;214m"
_C_CYAN = "\033[38;5;51m"
_C_RED = "\033[38;5;203m"


def run_terminal_chat(
    *,
    session_id: Optional[str] = None,
    lane: str = "auto",
    temperature: float = 0.25,
    max_tokens: int = 1024,
    use_rag: bool = False,
) -> int:
    store = get_mundo_chat_store()
    agent = get_mundo_sin_censura()
    st = agent.get_status()

    if session_id:
        sess = store.get_session(session_id) or store.create_session(
            lane=lane, temperature=temperature, max_tokens=max_tokens, use_rag=use_rag
        )
    else:
        existing = store.list_sessions(limit=1)
        if existing and existing[0].get("message_count", 0) == 0:
            sess = store.get_session(existing[0]["id"])
        else:
            sess = store.create_session(
                lane=lane, temperature=temperature, max_tokens=max_tokens, use_rag=use_rag
            )

    assert sess is not None
    cur_lane = normalize_lane(lane or sess["lane"])
    cur_temp = float(temperature)
    cur_mtok = int(max_tokens)
    cur_rag = bool(use_rag)
    cur_hw = bool(sess.get("hardware_control", True))
    active_rid: Dict[str, Optional[str]] = {"id": None}

    def _on_sigint(_sig, _frame):
        if active_rid["id"]:
            store.cancel_stream(active_rid["id"])
        else:
            print(f"\n{_C_DIM}Usa /exit o Ctrl+D para salir.{_C_RESET}")

    prev_handler = signal.signal(signal.SIGINT, _on_sigint)

    sha_short = st.get("weights", {}).get("sha256_short", "n/a")
    active_lane = st.get("active_lane", "offline")
    print(f"\n{_C_BOLD}{_C_EMERALD}━━━ UN MUNDO SIN CENSURA · CHAT EXCLUSIVO ━━━{_C_RESET}")
    print(
        f"{_C_DIM}Modelo bloqueado:{_C_RESET} {_C_BOLD}{MODEL_LOCK}{_C_RESET} "
        f"{_C_DIM}| Carril activo:{_C_RESET} {_C_CYAN}{active_lane}{_C_RESET} "
        f"{_C_DIM}| SHA-256:{_C_RESET} {sha_short} "
        f"{_C_DIM}| Web:{_C_RESET} http://127.0.0.1:8757/mundo-sin-censura"
    )
    print(f"{_C_DIM}Sesión: {sess['id']} · Comandos: /help /new /sessions /lane /temp /max /rag /clear /status /exit{_C_RESET}\n")

    try:
        while True:
            try:
                user_in = input(f"{_C_BOLD}{_C_AMBER}tú ❯ {_C_RESET}").strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                continue

            if not user_in:
                continue

            if user_in.startswith("/") and not user_in.startswith("/hw ") and user_in != "/hw":
                parts = user_in.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                if cmd in ("/exit", "/quit", "/q"):
                    break
                elif cmd == "/help":
                    print(
                        f"{_C_CYAN}Comandos del Chat Exclusivo ({MODEL_LOCK}):{_C_RESET}\n"
                        "  /new [titulo]                Crear nueva sesión\n"
                        "  /sessions                    Listar sesiones guardadas\n"
                        "  /load <id|indice>            Cargar sesión previa\n"
                        "  /rename <titulo>             Renombrar sesión actual\n"
                        "  /clear                       Vaciar mensajes de sesión actual\n"
                        "  /lane <auto|temporal_brain|ollama>  Cambiar carril de inferencia\n"
                        "  /temp <0.0-1.5>              Ajustar temperatura\n"
                        "  /max <64-4096>               Ajustar max_tokens\n"
                        "  /rag <on|off>                Activar/desactivar RAG TARDIS\n"
                        "  /hwmode <on|off>             Activar/desactivar control absoluto de hardware\n"
                        "  /hw <accion> [params]        Ejecutar acción física/Ring-0 inmediata\n"
                        "  /status                      Ver estado del modelo y carriles\n"
                        "  /exit                        Salir del chat\n"
                    )
                elif cmd == "/new":
                    sess = store.create_session(
                        title=arg or None,
                        lane=cur_lane,
                        temperature=cur_temp,
                        max_tokens=cur_mtok,
                        use_rag=cur_rag,
                    )
                    print(f"{_C_EMERALD}✓ Nueva sesión:{_C_RESET} {sess['id']} ({sess['title']})\n")
                elif cmd == "/sessions":
                    items = store.list_sessions(limit=20)
                    for idx, it in enumerate(items, 1):
                        mark = "●" if it["id"] == sess["id"] else " "
                        print(f"  {mark} [{idx}] {it['id']} · {it['title']} ({it['message_count']} msgs)")
                    print()
                elif cmd == "/load":
                    target_id = arg
                    if arg.isdigit():
                        items = store.list_sessions(limit=50)
                        pos = int(arg) - 1
                        if 0 <= pos < len(items):
                            target_id = items[pos]["id"]
                    loaded = store.get_session(target_id) if target_id else None
                    if loaded:
                        sess = loaded
                        print(f"{_C_EMERALD}✓ Cargada sesión:{_C_RESET} {sess['id']} · {sess['title']} ({sess['message_count']} msgs)\n")
                        for m in sess["messages"][-6:]:
                            tag = f"{_C_AMBER}tú{_C_RESET}" if m["role"] == "user" else f"{_C_EMERALD}mundo{_C_RESET}"
                            print(f"  {tag}: {m['content'][:160]}")
                        if sess["messages"]:
                            print()
                    else:
                        print(f"{_C_RED}Sesión no encontrada: {arg}{_C_RESET}\n")
                elif cmd == "/rename":
                    if arg:
                        sess = store.update_session(sess["id"], title=arg) or sess
                        print(f"{_C_EMERALD}✓ Renombrada a:{_C_RESET} {sess['title']}\n")
                elif cmd == "/clear":
                    sess = store.clear_session(sess["id"]) or sess
                    print(f"{_C_EMERALD}✓ Historial limpiado.{_C_RESET}\n")
                elif cmd == "/lane":
                    if arg in VALID_LANES:
                        cur_lane = arg
                        store.update_session(sess["id"], lane=cur_lane)
                        print(f"{_C_EMERALD}✓ Carril:{_C_RESET} {cur_lane}\n")
                    else:
                        print(f"{_C_RED}Carril inválido. Usa: {', '.join(VALID_LANES)}{_C_RESET}\n")
                elif cmd == "/temp":
                    try:
                        cur_temp = max(0.0, min(1.5, float(arg)))
                        store.update_session(sess["id"], temperature=cur_temp)
                        print(f"{_C_EMERALD}✓ Temperatura:{_C_RESET} {cur_temp}\n")
                    except ValueError:
                        print(f"{_C_RED}Valor inválido.{_C_RESET}\n")
                elif cmd == "/max":
                    try:
                        cur_mtok = max(64, min(4096, int(arg)))
                        store.update_session(sess["id"], max_tokens=cur_mtok)
                        print(f"{_C_EMERALD}✓ max_tokens:{_C_RESET} {cur_mtok}\n")
                    except ValueError:
                        print(f"{_C_RED}Valor inválido.{_C_RESET}\n")
                elif cmd == "/rag":
                    cur_rag = arg.lower() in ("on", "1", "true", "si", "sí")
                    store.update_session(sess["id"], use_rag=cur_rag)
                    print(f"{_C_EMERALD}✓ RAG TARDIS:{_C_RESET} {'ON' if cur_rag else 'OFF'}\n")
                elif cmd == "/hwmode":
                    cur_hw = arg.lower() in ("on", "1", "true", "si", "sí")
                    store.update_session(sess["id"], hardware_control=cur_hw)
                    print(f"{_C_EMERALD}✓ Control Absoluto Hardware Ring-0:{_C_RESET} {'ON' if cur_hw else 'OFF'}\n")
                elif cmd == "/status":
                    print(json.dumps(agent.get_status(), indent=2, ensure_ascii=False))
                    print()
                else:
                    print(f"{_C_RED}Comando desconocido: {cmd} (usa /help){_C_RESET}\n")
                continue

            print(f"{_C_BOLD}{_C_EMERALD}mundo-sin-censura ❯ {_C_RESET}", end="", flush=True)
            for ev in store.stream_turn(
                session_id=sess["id"],
                message=user_in,
                lane=cur_lane,
                temperature=cur_temp,
                max_tokens=cur_mtok,
                use_rag=cur_rag,
                hardware_control=cur_hw,
                is_local_request=True,
            ):
                etype = ev.get("type")
                if etype == "meta":
                    active_rid["id"] = ev.get("request_id")
                elif etype == "token":
                    print(ev.get("delta", ""), end="", flush=True)
                elif etype == "error":
                    print(f"\n{_C_RED}{ev.get('error')}{_C_RESET}", flush=True)
                elif etype == "done":
                    active_rid["id"] = None
                    canc = " [cancelado]" if ev.get("cancelled") else ""
                    print(
                        f"\n{_C_DIM}  [{ev.get('lane')} · {ev.get('elapsed_s')}s · ~{ev.get('approx_tokens')} chunks{canc}]{_C_RESET}\n"
                    )
    finally:
        signal.signal(signal.SIGINT, prev_handler)

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="mundo-chat",
        description="Chat interactivo exclusivo para el modelo Un Mundo Sin Censura",
    )
    p.add_argument("--session", type=str, default=None, help="ID de sesión existente")
    p.add_argument("--lane", choices=list(VALID_LANES), default="auto")
    p.add_argument("--temperature", type=float, default=0.25)
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument("--use-rag", action="store_true")
    args = p.parse_args(argv)
    return run_terminal_chat(
        session_id=args.session,
        lane=args.lane,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        use_rag=bool(args.use_rag),
    )


if __name__ == "__main__":
    raise SystemExit(main())
