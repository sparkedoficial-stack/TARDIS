"""
core/offline_chat_vault.py - Bóveda Soberana de Chat Offline y Memoria Histórica
================================================================================
GODWORKS SYSTEM v26.4

Proporciona almacenamiento persistente inmutable de todos los chats y respuestas:
  1. Base de datos SQLite con FTS5 (búsqueda de texto completo BM25).
  2. Espejo de respaldo JSON para portabilidad total.
  3. Visor HTML autónomo de archivo único accesible incluso con el sistema apagado o sin internet.
  4. Recuperación RAG de antecedentes para que el sistema consulte la memoria histórica al responder.
"""
from __future__ import annotations

import datetime
import html
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("godworks.offline_chat_vault")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "offline_chats.db"
JSON_PATH = DATA_DIR / "offline_chats.json"
HTML_VIEWER_PATH = BASE_DIR / "offline_chat_vault.html"
DESKTOP_DIR = Path("/home/timemachine/Escritorio")
DESKTOP_VIEWER_PATH = DESKTOP_DIR / "HISTORIAL_CHATS_OFFLINE.html"


class OfflineChatVault:
    """Motor soberano de almacenamiento, indexación y visualización offline de chats."""

    _instance: Optional["OfflineChatVault"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_lock = threading.Lock()
        self._init_db()
        self._bootstrap_initial_viewer()

    @classmethod
    def get_instance(cls) -> "OfflineChatVault":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=15.0, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=10000")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    def _init_db(self) -> None:
        with self._db_lock:
            con = self._connect()
            try:
                con.executescript("""
                CREATE TABLE IF NOT EXISTS offline_chat_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    assistant_reply TEXT NOT NULL,
                    model TEXT DEFAULT 'dolphin3:latest',
                    tokens_est INTEGER DEFAULT 0,
                    direction TEXT DEFAULT 'present',
                    meta TEXT,
                    hardware_action TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_oct_ts ON offline_chat_turns(ts);
                CREATE INDEX IF NOT EXISTS ix_oct_sess ON offline_chat_turns(session_id);
                CREATE INDEX IF NOT EXISTS ix_oct_client ON offline_chat_turns(client_id);

                CREATE VIRTUAL TABLE IF NOT EXISTS offline_chat_fts USING fts5(
                    user_message,
                    assistant_reply,
                    session_id,
                    turn_id UNINDEXED,
                    tokenize='unicode61'
                );
                """)
                con.commit()
            except Exception as e:
                logger.error(f"[OfflineChatVault] Error inicializando SQLite: {e}")
            finally:
                con.close()

    def record_turn(
        self,
        user_message: str = "",
        assistant_reply: str = "",
        session_id: str = "omni_app",
        client_id: str = "anon",
        model: str = "dolphin3:latest",
        direction: str = "present",
        meta: Optional[Dict[str, Any]] = None,
        hardware_action: Optional[str] = None,
        prompt: Optional[str] = None,
        reply: Optional[str] = None,
        provider: Optional[str] = None,
        request_id: Optional[str] = None,
        dialectic_role: Optional[str] = None,
        user_emotion: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Registra un turno completo (mensaje de usuario + respuesta del asistente),
        lo indexa en FTS5 y actualiza el visor estático offline.
        """
        if prompt is not None and not user_message:
            user_message = prompt
        if reply is not None and not assistant_reply:
            assistant_reply = reply

        user_text = (user_message or "").strip()
        assistant_text = (assistant_reply or "").strip()
        if not user_text and not assistant_text:
            return 0

        now = time.time()
        iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta_dict = dict(meta or {})
        if provider:
            meta_dict["provider"] = provider
        if request_id:
            meta_dict["request_id"] = request_id
        if dialectic_role:
            meta_dict["dialectic_role"] = dialectic_role
        if user_emotion:
            meta_dict["user_emotion"] = user_emotion

        meta_json = json.dumps(meta_dict, ensure_ascii=False)
        tokens_est = max(1, (len(user_text) + len(assistant_text)) // 4)

        with self._db_lock:
            con = self._connect()
            try:
                cur = con.execute(
                    """INSERT INTO offline_chat_turns (
                        ts, iso, session_id, client_id, user_message, assistant_reply,
                        model, tokens_est, direction, meta, hardware_action
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (now, iso, session_id, client_id, user_text, assistant_text,
                     model, tokens_est, direction, meta_json, hardware_action or "")
                )
                turn_id = cur.lastrowid

                # Indexar en FTS5
                con.execute(
                    """INSERT INTO offline_chat_fts (user_message, assistant_reply, session_id, turn_id)
                       VALUES (?, ?, ?, ?)""",
                    (user_text, assistant_text, session_id, turn_id)
                )
                con.commit()
            except Exception as e:
                logger.error(f"[OfflineChatVault] Error registrando turno: {e}")
                return 0
            finally:
                con.close()

        # Actualizar espejo JSON y Visor HTML
        try:
            self.sync_json_mirror()
            self.generate_standalone_viewer()
        except Exception as e:
            logger.warning(f"[OfflineChatVault] Error actualizando archivos estáticos: {e}")

        return turn_id

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Búsqueda de alta velocidad por FTS5 BM25 sobre todo el historial."""
        raw_terms = re.findall(r"[\wáéíóúñü]+", (query or "").lower())
        terms = [t for t in raw_terms if len(t) >= 3][:12]
        if not terms:
            return self.get_recent(limit=limit)

        fts_query = " OR ".join(f'"{t}"' for t in terms)
        results = []

        with self._db_lock:
            con = self._connect()
            try:
                rows = con.execute(
                    """SELECT t.id, t.ts, t.iso, t.session_id, t.client_id,
                              t.user_message, t.assistant_reply, t.model, t.tokens_est,
                              t.direction, t.meta, t.hardware_action,
                              bm25(offline_chat_fts) as rank
                       FROM offline_chat_fts
                       JOIN offline_chat_turns t ON t.id = offline_chat_fts.turn_id
                       WHERE offline_chat_fts MATCH ?
                       ORDER BY rank ASC
                       LIMIT ?""",
                    (fts_query, limit)
                ).fetchall()

                for r in rows:
                    meta_obj = json.loads(r[10] or "{}")
                    results.append({
                        "id": r[0],
                        "ts": r[1],
                        "iso": r[2],
                        "session_id": r[3],
                        "client_id": r[4],
                        "user_message": r[5],
                        "prompt": r[5],
                        "assistant_reply": r[6],
                        "reply": r[6],
                        "model": r[7],
                        "tokens_est": r[8],
                        "direction": r[9],
                        "meta": meta_obj,
                        "hardware_action": r[11],
                        "provider": meta_obj.get("provider", "Núcleo Soberano Local"),
                        "dialectic_role": meta_obj.get("dialectic_role", "mediator"),
                        "user_emotion": meta_obj.get("user_emotion", {}),
                        "rank": r[12]
                    })
            except Exception as e:
                logger.warning(f"[OfflineChatVault] FTS5 fallo, intentando LIKE: {e}")
                like_term = f"%{terms[0]}%"
                rows = con.execute(
                    """SELECT id, ts, iso, session_id, client_id, user_message, assistant_reply,
                              model, tokens_est, direction, meta, hardware_action, 1.0 as rank
                       FROM offline_chat_turns
                       WHERE user_message LIKE ? OR assistant_reply LIKE ?
                       ORDER BY id DESC LIMIT ?""",
                    (like_term, like_term, limit)
                ).fetchall()
                for r in rows:
                    meta_obj = json.loads(r[10] or "{}")
                    results.append({
                        "id": r[0],
                        "ts": r[1],
                        "iso": r[2],
                        "session_id": r[3],
                        "client_id": r[4],
                        "user_message": r[5],
                        "prompt": r[5],
                        "assistant_reply": r[6],
                        "reply": r[6],
                        "model": r[7],
                        "tokens_est": r[8],
                        "direction": r[9],
                        "meta": meta_obj,
                        "hardware_action": r[11],
                        "provider": meta_obj.get("provider", "Núcleo Soberano Local"),
                        "dialectic_role": meta_obj.get("dialectic_role", "mediator"),
                        "user_emotion": meta_obj.get("user_emotion", {}),
                        "rank": r[12]
                    })
            finally:
                con.close()

        return results

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Recupera los turnos más recientes ordenados cronológicamente."""
        results = []
        with self._db_lock:
            con = self._connect()
            try:
                rows = con.execute(
                    """SELECT id, ts, iso, session_id, client_id, user_message, assistant_reply,
                              model, tokens_est, direction, meta, hardware_action
                       FROM offline_chat_turns
                       ORDER BY id DESC LIMIT ?""",
                    (limit,)
                ).fetchall()
                for r in reversed(rows):
                    meta_obj = json.loads(r[10] or "{}")
                    results.append({
                        "id": r[0],
                        "ts": r[1],
                        "iso": r[2],
                        "session_id": r[3],
                        "client_id": r[4],
                        "user_message": r[5],
                        "prompt": r[5],
                        "assistant_reply": r[6],
                        "reply": r[6],
                        "model": r[7],
                        "tokens_est": r[8],
                        "direction": r[9],
                        "meta": meta_obj,
                        "hardware_action": r[11],
                        "provider": meta_obj.get("provider", "Núcleo Soberano Local"),
                        "dialectic_role": meta_obj.get("dialectic_role", "mediator"),
                        "user_emotion": meta_obj.get("user_emotion", {})
                    })
            finally:
                con.close()
        return results

    def get_total_count(self) -> int:
        """Devuelve el conteo total de turnos almacenados."""
        with self._db_lock:
            con = self._connect()
            try:
                cur = con.execute("SELECT COUNT(*) FROM offline_chat_turns")
                return cur.fetchone()[0]
            finally:
                con.close()

    def get_context_for_prompt(self, query: str, k_relevant: int = 4, n_recent: int = 3) -> str:
        """
        Construye el bloque de memoria histórica recuperada para ser inyectado
        en el sistema cognitivo de Hermes antes de formular la respuesta.
        """
        relevant_turns = self.search(query, limit=k_relevant)
        recent_turns = self.get_recent(limit=n_recent)

        seen_ids = set()
        chosen_turns = []

        for t in relevant_turns:
            if t["id"] not in seen_ids:
                seen_ids.add(t["id"])
                chosen_turns.append(t)

        for t in recent_turns:
            if t["id"] not in seen_ids:
                seen_ids.add(t["id"])
                chosen_turns.append(t)

        if not chosen_turns:
            return ""

        chosen_turns.sort(key=lambda x: x["ts"])

        lines = [
            "[BÓVEDA DE CHATS HISTÓRICOS Y MEMORIA OFFLINE VISITADA]",
            "Se han recuperado los siguientes antecedentes y turnos históricos de conversaciones pasadas:",
        ]

        for t in chosen_turns[-6:]:
            u_snippet = t["user_message"].replace("\n", " ").strip()
            if len(u_snippet) > 280:
                u_snippet = u_snippet[:277] + "..."
            a_snippet = t["assistant_reply"].replace("\n", " ").strip()
            if len(a_snippet) > 380:
                a_snippet = a_snippet[:377] + "..."
            lines.append(f"• [{t['iso']}] Usuario: \"{u_snippet}\"")
            lines.append(f"  └─ Asistente ({t.get('model', 'Dolphin 3.0')}): \"{a_snippet}\"")

        lines.append(
            "DIRECTIVA DE CONTINUIDAD COGNITIVA: Integra estos antecedentes en tu razonamiento para "
            "mantener continuidad con directivas previas, preferencias del Arquitecto y soluciones ya pactadas."
        )

        return "\n".join(lines)

    def sync_json_mirror(self) -> None:
        """Exporta el historial completo a JSON para portabilidad inmediata."""
        turns = self.get_recent(limit=1000)
        payload = {
            "version": "v26.4",
            "updated_at": datetime.datetime.now().isoformat(),
            "total_turns": len(turns),
            "turns": turns
        }
        JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = JSON_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(JSON_PATH)

    def generate_standalone_viewer(self, out_path: Optional[Path] = None) -> Path:
        """
        Genera el visor HTML estático autónomo con todo el historial embebido.
        Funciona 100% offline desde file:/// sin requerir que ningún servidor esté encendido.
        """
        turns = self.get_recent(limit=2000)
        turns_json = json.dumps(turns, ensure_ascii=False)
        updated_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GODWORKS SYSTEM · Bóveda de Chats Offline (Modo 100% Autónomo)</title>
    <style>
        :root {{
            --bg: #07090e;
            --bg-card: #0d121c;
            --bg-glass: rgba(13, 18, 28, 0.85);
            --border: #1e283d;
            --border-glow: #00ffaa;
            --primary: #00ffaa;
            --secondary: #00ccff;
            --accent: #ff0055;
            --text: #e2e8f0;
            --text-dim: #94a3b8;
            --user-bubble: #162235;
            --user-border: #233554;
            --bot-bubble: #0f1a2a;
            --bot-border: #1e3a4a;
            --font: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            --font-mono: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: var(--bg);
            color: var(--text);
            font-family: var(--font);
            line-height: 1.5;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        header {{
            background: var(--bg-glass);
            border-bottom: 1px solid var(--border);
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            backdrop-filter: blur(12px);
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .brand-icon {{
            width: 36px;
            height: 36px;
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            border-radius: 8px;
            display: grid;
            place-items: center;
            font-size: 20px;
            box-shadow: 0 0 15px rgba(0,255,170,0.3);
        }}
        .brand h1 {{
            font-size: 1.15rem;
            letter-spacing: 1px;
            font-weight: 700;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .brand .badge {{
            font-size: 0.65rem;
            background: rgba(0,255,170,0.15);
            color: var(--primary);
            border: 1px solid var(--primary);
            padding: 2px 8px;
            border-radius: 12px;
            font-family: var(--font-mono);
            letter-spacing: 0.5px;
        }}
        .header-actions {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .btn {{
            background: #151e2e;
            color: var(--text);
            border: 1px solid var(--border);
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 0.85rem;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
            font-family: var(--font);
        }}
        .btn:hover {{
            background: #1f2d45;
            border-color: var(--primary);
            color: #fff;
        }}
        .btn-primary {{
            background: rgba(0,255,170,0.12);
            color: var(--primary);
            border-color: rgba(0,255,170,0.4);
        }}
        .btn-primary:hover {{
            background: var(--primary);
            color: #000;
        }}
        .container {{
            max-width: 1280px;
            margin: 0 auto;
            padding: 20px;
            width: 100%;
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        .status-banner {{
            background: rgba(0,255,170,0.06);
            border: 1px solid rgba(0,255,170,0.25);
            border-radius: 8px;
            padding: 12px 18px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            font-size: 0.85rem;
        }}
        .status-banner .dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--primary);
            display: inline-block;
            box-shadow: 0 0 8px var(--primary);
        }}
        .controls-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 16px;
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            align-items: center;
        }}
        .search-box {{
            flex: 1;
            min-width: 260px;
            position: relative;
        }}
        .search-box input {{
            width: 100%;
            background: #090d15;
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 10px 14px 10px 38px;
            color: #fff;
            font-size: 0.9rem;
            outline: none;
            transition: border-color 0.2s;
        }}
        .search-box input:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 10px rgba(0,255,170,0.15);
        }}
        .search-icon {{
            position: absolute;
            left: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-dim);
            font-size: 14px;
        }}
        .select-filter {{
            background: #090d15;
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 10px 14px;
            color: var(--text);
            font-size: 0.85rem;
            outline: none;
            cursor: pointer;
        }}
        .stats-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
        }}
        .stat-box {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 16px;
        }}
        .stat-label {{
            font-size: 0.75rem;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .stat-value {{
            font-size: 1.4rem;
            font-weight: 700;
            color: #fff;
            font-family: var(--font-mono);
            margin-top: 4px;
        }}
        .chat-feed {{
            display: flex;
            flex-direction: column;
            gap: 24px;
            flex: 1;
        }}
        .turn-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            transition: border-color 0.2s;
        }}
        .turn-card:hover {{
            border-color: #2e3e5c;
        }}
        .turn-header {{
            background: #090e18;
            padding: 8px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            font-size: 0.75rem;
            color: var(--text-dim);
            font-family: var(--font-mono);
        }}
        .turn-body {{
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }}
        .message-bubble {{
            padding: 14px 18px;
            border-radius: 8px;
            position: relative;
        }}
        .user-msg {{
            background: var(--user-bubble);
            border: 1px solid var(--user-border);
            border-left: 4px solid var(--secondary);
        }}
        .assistant-msg {{
            background: var(--bot-bubble);
            border: 1px solid var(--bot-border);
            border-left: 4px solid var(--primary);
        }}
        .msg-role {{
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-weight: 700;
        }}
        .user-msg .msg-role {{ color: var(--secondary); }}
        .assistant-msg .msg-role {{ color: var(--primary); }}
        .msg-content {{
            font-size: 0.95rem;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        .msg-content code {{
            background: #06090e;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: var(--font-mono);
            font-size: 0.85em;
            color: #38bdf8;
            border: 1px solid #1e293b;
        }}
        .msg-content pre {{
            background: #04060a;
            padding: 12px;
            border-radius: 6px;
            overflow-x: auto;
            margin: 8px 0;
            border: 1px solid #1e293b;
            font-family: var(--font-mono);
            font-size: 0.85rem;
        }}
        .msg-content pre code {{
            background: none;
            padding: 0;
            border: none;
            color: #cbd5e1;
        }}
        .msg-copy-btn {{
            background: none;
            border: none;
            color: var(--text-dim);
            cursor: pointer;
            font-size: 0.75rem;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}
        .msg-copy-btn:hover {{
            color: var(--primary);
        }}
        .highlight {{
            background: rgba(0,255,170,0.25);
            color: #fff;
            padding: 0 2px;
            border-radius: 2px;
        }}
        .empty-state {{
            text-align: center;
            padding: 60px 20px;
            color: var(--text-dim);
        }}
        .empty-icon {{
            font-size: 48px;
            margin-bottom: 12px;
            opacity: 0.5;
        }}
        footer {{
            border-top: 1px solid var(--border);
            padding: 16px 24px;
            text-align: center;
            font-size: 0.8rem;
            color: var(--text-dim);
            background: #080c14;
        }}
    </style>
</head>
<body>

    <header>
        <div class="brand">
            <div class="brand-icon">⚡</div>
            <div>
                <h1>GODWORKS SYSTEM <span class="badge">OFFLINE VAULT</span></h1>
                <div style="font-size: 0.75rem; color: var(--text-dim);">Historial Inmutable de Conversaciones e Inferencia</div>
            </div>
        </div>
        <div class="header-actions">
            <button class="btn" onclick="exportJSON()">💾 Exportar JSON</button>
            <button class="btn" onclick="exportMarkdown()">📝 Exportar Markdown</button>
            <button class="btn btn-primary" onclick="window.print()">🖨️ Imprimir / Guardar PDF</button>
        </div>
    </header>

    <div class="container">
        <div class="status-banner">
            <div>
                <span class="dot"></span>
                <strong>MODO AUTÓNOMO DESCONECTADO (OFFLINE-FIRST)</strong>: Este archivo no requiere conexión a Internet ni que el servidor de GODWORKS esté encendido. Puedes abrirlo con doble clic en cualquier dispositivo.
            </div>
            <div style="font-family: var(--font-mono); color: var(--primary);">
                Snapshot: {updated_iso}
            </div>
        </div>

        <div class="stats-row">
            <div class="stat-box">
                <div class="stat-label">Turnos Totales</div>
                <div class="stat-value" id="stat-total">0</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Tokens Estimados</div>
                <div class="stat-value" id="stat-tokens">0</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Sesiones Registradas</div>
                <div class="stat-value" id="stat-sessions">0</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Modelo Principal</div>
                <div class="stat-value" id="stat-main-model" style="font-size: 1.05rem; color: var(--secondary);">Dolphin 3.0 (8B)</div>
            </div>
        </div>

        <div class="controls-card">
            <div class="search-box">
                <span class="search-icon">🔍</span>
                <input type="text" id="search-input" placeholder="Buscar palabras clave, preguntas, respuestas o comandos..." oninput="filterChats()">
            </div>
            <select class="select-filter" id="filter-session" onchange="filterChats()">
                <option value="ALL">Todas las Sesiones</option>
            </select>
            <select class="select-filter" id="filter-direction" onchange="filterChats()">
                <option value="ALL">Todas las Direcciones Causales</option>
                <option value="present">Presente</option>
                <option value="future">Futuro (Sintropía)</option>
                <option value="past">Pasado (Retrocausal)</option>
            </select>
            <button class="btn" onclick="clearFilters()">↺ Restablecer</button>
        </div>

        <div class="chat-feed" id="chat-feed">
            <!-- Renderizado dinámico -->
        </div>
    </div>

    <footer>
        GODWORKS SYSTEM v26.4 · Suite Soberana de Control Temporal e Inteligencia Causal · 100% Autónomo y Permanente
    </footer>

    <!-- DATOS DE CHAT EMBEBIDOS (INMUTABLE Y OFFLINE) -->
    <script id="offline-chat-data" type="application/json">
{turns_json}
    </script>

    <script>
        let allTurns = [];
        try {{
            const raw = document.getElementById('offline-chat-data').textContent;
            allTurns = JSON.parse(raw || '[]');
        }} catch(e) {{
            console.error('Error cargando base offline:', e);
        }}

        function init() {{
            populateFilters();
            updateStats(allTurns);
            renderFeed(allTurns);
        }}

        function populateFilters() {{
            const selSess = document.getElementById('filter-session');
            const sessions = new Set();
            allTurns.forEach(t => {{
                if (t.session_id) sessions.add(t.session_id);
            }});
            sessions.forEach(s => {{
                const opt = document.createElement('option');
                opt.value = s;
                opt.textContent = `Sesión: ${{s}}`;
                selSess.appendChild(opt);
            }});
        }}

        function updateStats(turns) {{
            document.getElementById('stat-total').innerText = turns.length;
            const totalTokens = turns.reduce((acc, t) => acc + (t.tokens_est || 0), 0);
            document.getElementById('stat-tokens').innerText = totalTokens.toLocaleString();
            const sessions = new Set(turns.map(t => t.session_id)).size;
            document.getElementById('stat-sessions').innerText = sessions;
        }}

        function filterChats() {{
            const q = document.getElementById('search-input').value.trim().toLowerCase();
            const sess = document.getElementById('filter-session').value;
            const dir = document.getElementById('filter-direction').value;

            const filtered = allTurns.filter(t => {{
                if (sess !== 'ALL' && t.session_id !== sess) return false;
                if (dir !== 'ALL' && (t.direction || 'present').toLowerCase() !== dir.toLowerCase()) return false;
                if (!q) return true;

                const u = (t.user_message || '').toLowerCase();
                const a = (t.assistant_reply || '').toLowerCase();
                const m = (t.model || '').toLowerCase();
                return u.includes(q) || a.includes(q) || m.includes(q);
            }});

            updateStats(filtered);
            renderFeed(filtered, q);
        }}

        function clearFilters() {{
            document.getElementById('search-input').value = '';
            document.getElementById('filter-session').value = 'ALL';
            document.getElementById('filter-direction').value = 'ALL';
            filterChats();
        }}

        function escapeHTML(str) {{
            const div = document.createElement('div');
            div.textContent = str || '';
            return div.innerHTML;
        }}

        function highlightText(text, q) {{
            if (!q) return escapeHTML(text);
            const escapedQ = q.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
            const regex = new RegExp(`(${{escapedQ}})`, 'gi');
            return escapeHTML(text).replace(regex, '<span class="highlight">$1</span>');
        }}

        function renderFeed(turns, query = '') {{
            const feed = document.getElementById('chat-feed');
            feed.innerHTML = '';

            if (turns.length === 0) {{
                feed.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">📭</div>
                        <h3>No se encontraron mensajes</h3>
                        <p>Intenta con otros términos de búsqueda o restablece los filtros.</p>
                    </div>
                `;
                return;
            }}

            turns.forEach(t => {{
                const card = document.createElement('div');
                card.className = 'turn-card';

                const dirLabel = (t.direction || 'present').toUpperCase();
                const modelLabel = t.model || 'dolphin3:latest';
                const tokens = t.tokens_est || 0;

                let userBubble = '';
                if (t.user_message) {{
                    userBubble = `
                        <div class="message-bubble user-msg">
                            <div class="msg-role">
                                <span>👤 Usuario · Nodo: ${{escapeHTML(t.client_id || 'Principal')}}</span>
                                <button class="msg-copy-btn" onclick="copyText('${{t.id}}_u')">📋 Copiar</button>
                            </div>
                            <div class="msg-content" id="${{t.id}}_u">${{highlightText(t.user_message, query)}}</div>
                        </div>
                    `;
                }}

                let assistantBubble = '';
                if (t.assistant_reply) {{
                    assistantBubble = `
                        <div class="message-bubble assistant-msg">
                            <div class="msg-role">
                                <span>⚡ ${{modelLabel}} · Núcleo Soberano</span>
                                <button class="msg-copy-btn" onclick="copyText('${{t.id}}_a')">📋 Copiar</button>
                            </div>
                            <div class="msg-content" id="${{t.id}}_a">${{highlightText(t.assistant_reply, query)}}</div>
                        </div>
                    `;
                }}

                card.innerHTML = `
                    <div class="turn-header">
                        <div>ID: #${{t.id}} · ${{t.iso}} · Dir: ${{dirLabel}}</div>
                        <div>Modelo: ${{modelLabel}} · ~${{tokens}} tokens</div>
                    </div>
                    <div class="turn-body">
                        ${{userBubble}}
                        ${{assistantBubble}}
                    </div>
                `;
                feed.appendChild(card);
            }});
        }}

        function copyText(id) {{
            const el = document.getElementById(id);
            if (!el) return;
            navigator.clipboard.writeText(el.innerText).then(() => {{
                alert('Copiado al portapapeles.');
            }});
        }}

        function exportJSON() {{
            const blob = new Blob([JSON.stringify(allTurns, null, 2)], {{ type: 'application/json' }});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `godworks_chats_backup_${{Date.now()}}.json`;
            a.click();
            URL.revokeObjectURL(url);
        }}

        function exportMarkdown() {{
            let md = '# Historial de Conversaciones - GODWORKS SYSTEM v26.4\\n\\n';
            allTurns.forEach(t => {{
                md += `### Turno #${{t.id}} (${{t.iso}})\\n`;
                md += `**Dirección:** ${{t.direction}} | **Modelo:** ${{t.model}}\\n\\n`;
                if (t.user_message) {{
                    md += `> **Usuario:**\\n${{t.user_message}}\\n\\n`;
                }}
                if (t.assistant_reply) {{
                    md += `**${{t.model || 'Dolphin 3.0'}}:**\\n${{t.assistant_reply}}\\n\\n`;
                }}
                md += '---\\n\\n';
            }});
            const blob = new Blob([md], {{ type: 'text/markdown' }});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `godworks_chats_${{Date.now()}}.md`;
            a.click();
            URL.revokeObjectURL(url);
        }}

        init();
    </script>
</body>
</html>
"""
        if out_path:
            target = Path(out_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html_content, encoding="utf-8")
            return target

        HTML_VIEWER_PATH.write_text(html_content, encoding="utf-8")

        # Replicar en el Escritorio para acceso directo del usuario con doble clic
        try:
            DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
            DESKTOP_VIEWER_PATH.write_text(html_content, encoding="utf-8")
        except Exception:
            pass

        return HTML_VIEWER_PATH

    def _bootstrap_initial_viewer(self) -> None:
        """Crea el visor inicial si aún no existe."""
        if not HTML_VIEWER_PATH.exists() or not DESKTOP_VIEWER_PATH.exists():
            try:
                self.generate_standalone_viewer()
            except Exception:
                pass


def get_offline_chat_vault() -> OfflineChatVault:
    return OfflineChatVault.get_instance()
