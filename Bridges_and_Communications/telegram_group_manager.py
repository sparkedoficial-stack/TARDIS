"""
core/telegram_group_manager.py - Gestor Soberano de Grupos y Miembros de Telegram
================================================================================
GODWORKS SYSTEM v26.4 & TARDIS

Permite gestionar grupos de Telegram a los que TARDIS es añadido:
  1. Almacenamiento persistente de miembros (ID, nombre, apellidos, alias, username, actividad).
  2. Identificación para responder a cada persona por su nombre en el grupo.
  3. Sincronización automática de metadatos del grupo y administradores con Telegram Bot API.
  4. Mensajes de bienvenida y gestión activa del grupo.
"""

from __future__ import annotations

import copy
import datetime
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from core.protected_users_vault import ARCHITECT_TELEGRAM_ID, is_architect

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "telegram_group_members.json"
logger = logging.getLogger("GODWORKS.TelegramGroupManager")

DEFAULT_WELCOME_TEXT = (
    "👋 ¡Bienvenido/a {nombre} al grupo *{grupo}*! "
    "Soy TARDIS, asistente de inteligencia artificial y sistema de control temporal. "
    "Un placer tenerte aquí."
)


class TelegramGroupManager:
    """Gestor soberano de grupos y miembros de Telegram."""

    _instance: Optional[TelegramGroupManager] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> TelegramGroupManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, data_path: Optional[Path | str] = None):
        self.data_path = Path(data_path) if data_path else DATA_FILE
        self.groups: Dict[str, Dict[str, Any]] = {}
        self.direct_users: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """Carga el registro de grupos y miembros desde disco."""
        if self.data_path.exists():
            try:
                data = json.loads(self.data_path.read_text(encoding="utf-8"))
                self.groups = data.get("groups", {})
                self.direct_users = data.get("direct_users", {})
            except Exception as e:
                logger.error(f"Error cargando {self.data_path}: {e}")
                self.groups = {}
                self.direct_users = {}
        else:
            self.groups = {}
            self.direct_users = {}

    def _save(self):
        """Guarda atómicamente el registro en disco."""
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.data_path.with_suffix(".tmp")
            payload = {
                "groups": self.groups,
                "direct_users": self.direct_users,
                "last_updated": datetime.datetime.now().isoformat()
            }
            temp_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            temp_file.replace(self.data_path)
        except Exception as e:
            logger.error(f"Error guardando {self.data_path}: {e}")

    def get_group(self, chat_id: int | str) -> Dict[str, Any]:
        """Obtiene o inicializa el objeto del grupo."""
        cid = str(chat_id)
        if cid not in self.groups:
            self.groups[cid] = {
                "chat_id": int(chat_id) if cid.lstrip("-").isdigit() else chat_id,
                "title": "",
                "type": "group",
                "authorized": True,
                "authorized_at": datetime.datetime.now().isoformat(),
                "reply_mode": "todo",
                "address_by_name": True,
                "welcome_enabled": True,
                "welcome_text": DEFAULT_WELCOME_TEXT,
                "created_at": datetime.datetime.now().isoformat(),
                "updated_at": datetime.datetime.now().isoformat(),
                "members": {}
            }
            self._save()
        return self.groups[cid]

    def register_or_update_member(
        self,
        chat_id: int | str,
        user_dict: Dict[str, Any],
        chat_title: str = "",
        chat_type: str = "group"
    ) -> Dict[str, Any]:
        """Registra o actualiza la información de un miembro que envió mensaje o interactuó en el grupo."""
        with self._lock:
            grp = self.get_group(chat_id)
            if chat_title and not grp.get("title"):
                grp["title"] = chat_title
            if chat_type:
                grp["type"] = chat_type

            user_id = user_dict.get("id")
            if not user_id:
                return {}

            uid_str = str(user_id)
            members = grp.setdefault("members", {})

            first_name = (user_dict.get("first_name") or "").strip()
            last_name = (user_dict.get("last_name") or "").strip()
            username = (user_dict.get("username") or "").strip()
            full_name = f"{first_name} {last_name}".strip() or first_name or username or "Usuario"
            display_name = first_name or username or "Usuario"
            is_arch = is_architect(user_id)

            now_iso = datetime.datetime.now().isoformat()

            if uid_str in members:
                m = members[uid_str]
                m["first_name"] = first_name or m.get("first_name", "")
                m["last_name"] = last_name or m.get("last_name", "")
                m["full_name"] = full_name
                m["username"] = username or m.get("username", "")
                m["display_name"] = display_name
                m["last_seen"] = now_iso
                m["message_count"] = m.get("message_count", 0) + 1
            else:
                m = {
                    "user_id": user_id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "full_name": full_name,
                    "display_name": display_name,
                    "username": username,
                    "is_bot": bool(user_dict.get("is_bot", False)),
                    "is_architect": is_arch,
                    "role": "creator" if is_arch else ("administrator" if user_dict.get("is_admin") else "member"),
                    "first_seen": now_iso,
                    "last_seen": now_iso,
                    "message_count": 1
                }
                members[uid_str] = m

            grp["updated_at"] = now_iso
            self._save()
            return m

    def get_member_name(self, chat_id: int | str, user_id: int | str) -> str:
        """Devuelve el nombre con el que TARDIS debe dirigirse a la persona."""
        if is_architect(user_id):
            return "Arquitecto"
        with self._lock:
            cid = str(chat_id)
            uid = str(user_id)
            if cid in self.groups and uid in self.groups[cid].get("members", {}):
                m = self.groups[cid]["members"][uid]
                return m.get("first_name") or m.get("display_name") or "Usuario"
            return "Usuario"

    def get_all_members(self, chat_id: int | str) -> List[Dict[str, Any]]:
        """Devuelve la lista de miembros conocidos del grupo."""
        with self._lock:
            cid = str(chat_id)
            if cid in self.groups:
                return list(self.groups[cid].get("members", {}).values())
            return []

    def sync_group_from_api(self, chat_id: int | str, bot_token: str) -> Dict[str, Any]:
        """Sincroniza información del grupo y administradores desde la API de Telegram."""
        if not bot_token:
            return {"ok": False, "error": "No bot token"}

        results = {"chat": False, "admins": 0}
        cid = str(chat_id)

        # 1. Obtener detalles del chat
        try:
            url_chat = f"https://api.telegram.org/bot{bot_token}/getChat?chat_id={chat_id}"
            r_chat = requests.get(url_chat, timeout=8.0).json()
            if r_chat.get("ok"):
                c_res = r_chat.get("result", {})
                with self._lock:
                    grp = self.get_group(chat_id)
                    grp["title"] = c_res.get("title", grp.get("title", "T.A.R.D.I.S"))
                    grp["type"] = c_res.get("type", "group")
                    if c_res.get("invite_link"):
                        grp["invite_link"] = c_res.get("invite_link")
                    grp["description"] = c_res.get("description", "")
                    grp["updated_at"] = datetime.datetime.now().isoformat()
                    self._save()
                results["chat"] = True
        except Exception as e:
            logger.warning(f"Error en sync_group getChat: {e}")

        # 2. Obtener administradores y creador
        try:
            url_admins = f"https://api.telegram.org/bot{bot_token}/getChatAdministrators?chat_id={chat_id}"
            r_admins = requests.get(url_admins, timeout=8.0).json()
            if r_admins.get("ok"):
                admins = r_admins.get("result", [])
                with self._lock:
                    grp = self.get_group(chat_id)
                    members = grp.setdefault("members", {})
                    now_iso = datetime.datetime.now().isoformat()

                    for adm in admins:
                        u = adm.get("user", {})
                        uid = u.get("id")
                        if not uid:
                            continue
                        uid_str = str(uid)
                        first_name = (u.get("first_name") or "").strip()
                        last_name = (u.get("last_name") or "").strip()
                        username = (u.get("username") or "").strip()
                        full_name = f"{first_name} {last_name}".strip() or first_name or username or "Usuario"
                        display_name = first_name or username or "Usuario"
                        status = adm.get("status", "administrator")
                        is_arch = is_architect(uid)

                        if uid_str in members:
                            m = members[uid_str]
                            m["role"] = status
                            m["first_name"] = first_name or m.get("first_name", "")
                            m["last_name"] = last_name or m.get("last_name", "")
                            m["full_name"] = full_name
                            m["username"] = username or m.get("username", "")
                            m["display_name"] = display_name
                        else:
                            members[uid_str] = {
                                "user_id": uid,
                                "first_name": first_name,
                                "last_name": last_name,
                                "full_name": full_name,
                                "display_name": display_name,
                                "username": username,
                                "is_bot": bool(u.get("is_bot", False)),
                                "is_architect": is_arch,
                                "role": status,
                                "first_seen": now_iso,
                                "last_seen": now_iso,
                                "message_count": 0
                            }
                    grp["updated_at"] = now_iso
                    self._save()
                results["admins"] = len(admins)
        except Exception as e:
            logger.warning(f"Error en sync_group getChatAdministrators: {e}")

        return {"ok": True, "details": results}

    def format_group_summary(self, chat_id: int | str) -> str:
        """Genera un reporte en markdown de la información y miembros del grupo."""
        with self._lock:
            cid = str(chat_id)
            if cid not in self.groups:
                return "ℹ️ No hay registros previos de este grupo en TARDIS."

            grp = self.groups[cid]
            title = grp.get("title", "Grupo")
            members = grp.get("members", {})

            lines = [
                f"👥 **[GESTIÓN SOBERANA DEL GRUPO · {title.upper()}]**",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"• **Chat ID:** `{chat_id}`",
                f"• **Tipo:** `{grp.get('type', 'group')}`",
                f"• **Estado:** 🟢 AUTORIZADO PARA HABLAR",
                f"• **Miembros Registrados:** `{len(members)}`",
                ""
            ]

            if members:
                lines.append("📋 **Miembros Detectados & Nombres:**")
                for uid, m in members.items():
                    tag = "👑 Creador / Arquitecto" if m.get("is_architect") else ("🤖 Bot" if m.get("is_bot") else f"👤 {m.get('role', 'miembro').capitalize()}")
                    u_handle = f" (@{m['username']})" if m.get("username") else ""
                    lines.append(f"   • **{m.get('full_name')}**{u_handle} — {tag} (`{m.get('message_count', 0)} msgs`)")
            else:
                lines.append("ℹ️ Aún no se han registrado mensajes de miembros en este grupo.")

            return "\n".join(lines)

    def register_or_update_direct_user(
        self,
        chat_id: int | str,
        user_dict: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Registra o actualiza la información de un usuario que conversa en privado con TARDIS."""
        with self._lock:
            cid_str = str(chat_id)
            user_id = user_dict.get("id") or (int(chat_id) if cid_str.isdigit() else chat_id)
            first_name = (user_dict.get("first_name") or "").strip()
            last_name = (user_dict.get("last_name") or "").strip()
            username = (user_dict.get("username") or "").strip()
            full_name = f"{first_name} {last_name}".strip() or first_name or username or f"Usuario {cid_str}"
            display_name = first_name or username or f"Usuario {cid_str}"
            is_arch = is_architect(user_id)
            now_iso = datetime.datetime.now().isoformat()

            if cid_str in self.direct_users:
                u = self.direct_users[cid_str]
                u["first_name"] = first_name or u.get("first_name", "")
                u["last_name"] = last_name or u.get("last_name", "")
                u["full_name"] = full_name
                u["username"] = username or u.get("username", "")
                u["display_name"] = display_name
                u["last_seen"] = now_iso
                u["message_count"] = u.get("message_count", 0) + 1
            else:
                u = {
                    "chat_id": int(chat_id) if cid_str.isdigit() else chat_id,
                    "user_id": user_id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "full_name": full_name,
                    "display_name": display_name,
                    "username": username,
                    "is_bot": bool(user_dict.get("is_bot", False)),
                    "is_architect": is_arch,
                    "first_seen": now_iso,
                    "last_seen": now_iso,
                    "message_count": 1
                }
                self.direct_users[cid_str] = u

            self._save()
            return u

    def find_recipient(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Localiza un destinatario por chat_id numérico, nombre, username o título de grupo.
        Devuelve dict con chat_id, name, target_type ('user', 'group', 'chat').
        """
        if not query or not query.strip():
            return None
        q = query.strip()
        q_clean = q.lstrip("@").lower()

        # 1. Si es ID numérico exacto (positivo usuario o negativo grupo)
        if (q.isdigit()) or (q.startswith("-") and q[1:].isdigit()):
            cid = int(q)
            # Buscar si conocemos su nombre
            cid_str = str(cid)
            if cid_str in self.groups:
                return {"chat_id": cid, "name": self.groups[cid_str].get("title", f"Grupo {cid}"), "type": "group"}
            if cid_str in self.direct_users:
                return {"chat_id": cid, "name": self.direct_users[cid_str].get("display_name", f"Usuario {cid}"), "type": "user"}
            for grp in self.groups.values():
                if cid_str in grp.get("members", {}):
                    m = grp["members"][cid_str]
                    return {"chat_id": cid, "name": m.get("display_name", f"Usuario {cid}"), "type": "user", "group_id": grp.get("chat_id")}
            return {"chat_id": cid, "name": f"Chat {cid}", "type": "chat"}

        with self._lock:
            # 2. Buscar en usuarios directos
            for cid_str, u in self.direct_users.items():
                u_uname = (u.get("username") or "").lower()
                u_first = (u.get("first_name") or "").lower()
                u_full = (u.get("full_name") or "").lower()
                u_disp = (u.get("display_name") or "").lower()
                if q_clean == u_uname or q_clean == u_first or q_clean == u_full or q_clean == u_disp:
                    return {"chat_id": u.get("chat_id"), "name": u.get("display_name"), "type": "user", "username": u.get("username")}

            # 3. Buscar en miembros de grupos
            for grp in self.groups.values():
                for uid_str, m in grp.get("members", {}).items():
                    m_uname = (m.get("username") or "").lower()
                    m_first = (m.get("first_name") or "").lower()
                    m_full = (m.get("full_name") or "").lower()
                    m_disp = (m.get("display_name") or "").lower()
                    if q_clean == m_uname or q_clean == m_first or q_clean == m_full or q_clean == m_disp:
                        return {
                            "chat_id": m.get("user_id"),
                            "name": m.get("display_name"),
                            "type": "user",
                            "username": m.get("username"),
                            "group_id": grp.get("chat_id")
                        }

            # 4. Buscar por título de grupo
            for cid_str, grp in self.groups.items():
                g_title = (grp.get("title") or "").lower()
                if q_clean in g_title or g_title in q_clean:
                    return {"chat_id": grp.get("chat_id"), "name": grp.get("title", f"Grupo {cid_str}"), "type": "group"}

            # 5. Búsqueda por subcadena en usuarios directos y miembros
            for cid_str, u in self.direct_users.items():
                u_full = (u.get("full_name") or "").lower()
                if q_clean in u_full:
                    return {"chat_id": u.get("chat_id"), "name": u.get("display_name"), "type": "user", "username": u.get("username")}
            for grp in self.groups.values():
                for uid_str, m in grp.get("members", {}).items():
                    m_full = (m.get("full_name") or "").lower()
                    if q_clean in m_full:
                        return {
                            "chat_id": m.get("user_id"),
                            "name": m.get("display_name"),
                            "type": "user",
                            "username": m.get("username"),
                            "group_id": grp.get("chat_id")
                        }

        return None

    def get_all_active_destinations(self) -> List[Dict[str, Any]]:
        """Devuelve todos los chats y grupos conocidos donde TARDIS puede despachar mensajes."""
        destinations: List[Dict[str, Any]] = []
        seen_ids = set()

        with self._lock:
            # 1. Grupos registrados
            for cid_str, grp in self.groups.items():
                cid = grp.get("chat_id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    destinations.append({
                        "chat_id": cid,
                        "name": grp.get("title", f"Grupo {cid}"),
                        "type": "group"
                    })

            # 2. Chats directos registrados
            for cid_str, u in self.direct_users.items():
                cid = u.get("chat_id") or u.get("user_id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    destinations.append({
                        "chat_id": cid,
                        "name": u.get("display_name", f"Usuario {cid}"),
                        "type": "user"
                    })

        return destinations

    def format_all_contacts_summary(self) -> str:
        """Formatea un resumen amigable de personas y grupos conocidos con quienes TARDIS conversa."""
        with self._lock:
            lines = [
                "👥 **[DIRECTORIO SOBERANO DE CONTACTOS Y GRUPOS · TARDIS]**",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            ]
            if self.groups:
                lines.append(f"🏰 **Grupos Activos ({len(self.groups)}):**")
                for cid_str, grp in self.groups.items():
                    m_count = len(grp.get("members", {}))
                    lines.append(f"   • **{grp.get('title', 'Grupo')}** (`ID: {grp.get('chat_id')}`) — {m_count} miembros")
                lines.append("")

            # Miembros y usuarios directos
            people_map: Dict[str, Dict[str, Any]] = {}
            for cid_str, u in self.direct_users.items():
                uid_k = str(u.get("user_id", cid_str))
                people_map[uid_k] = u

            for grp in self.groups.values():
                for uid_str, m in grp.get("members", {}).items():
                    if uid_str not in people_map:
                        people_map[uid_str] = m

            if people_map:
                lines.append(f"👤 **Personas y Miembros Registrados ({len(people_map)}):**")
                for uid, p in people_map.items():
                    tag = "👑 Arquitecto" if p.get("is_architect") else ("🤖 Bot" if p.get("is_bot") else "👤 Miembro")
                    u_h = f" (@{p['username']})" if p.get("username") else ""
                    lines.append(f"   • **{p.get('full_name')}**{u_h} — {tag} (`ID: {uid}`)")
            else:
                lines.append("ℹ️ Aún no hay personas registradas en el directorio.")

            lines.append("")
            lines.append("💡 *Para enviarles algo:* `/enviar <nombre|id> <mensaje>` o `/enviar_dibujo <nombre|id> [tema]`")
            return "\n".join(lines)


def get_telegram_group_manager() -> TelegramGroupManager:
    return TelegramGroupManager.get_instance()
