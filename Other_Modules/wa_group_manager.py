"""
core/wa_group_manager.py - Gestión de grupos de WhatsApp por TARDIS
==================================================================
Lógica pura (sin neonize) para que TARDIS administre los grupos de WhatsApp
a los que fue añadido, SOLO después de que el Arquitecto lo autorice desde la
consola local (tardis-whatsapp autorizar ...).

  - Grupos no autorizados: TARDIS no lee, no responde y no actúa.
  - Niveles de permiso por grupo: chat < moderacion < completo.
  - Gestores: números que pueden dar órdenes a TARDIS dentro del grupo.
  - Moderación: antilink, antiflood, advertencias, expulsión automática opcional.
  - Bienvenida y reglas; conversación con TARDIS al mencionarlo.

El acceso a WhatsApp se hace a través de un adaptador (ver WAAdapter) que
implementa whatsapp_group_service.py con neonize; en pruebas se usa uno falso.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Protocol, Tuple

LEVELS = ("chat", "moderacion", "completo")
LEVEL_PERMS = {
    "chat": {"chat"},
    "moderacion": {"chat", "moderate"},
    "completo": {"chat", "moderate", "admin"},
}
REPLY_MODES = ("menciones", "todo", "off")

DEFAULT_WELCOME = "👋 ¡Bienvenido(a) {mencion} a *{grupo}*! Lee las reglas con /reglas."

DEFAULT_GROUP: Dict[str, Any] = {
    "name": "",
    "authorized": False,
    "level": "completo",
    "authorized_at": "",
    "authorized_via": "",
    "managers": [],
    "reply_mode": "menciones",
    "welcome": {"enabled": False, "text": DEFAULT_WELCOME},
    "rules": "",
    "antilink": False,
    "antiflood": {"enabled": False, "max_msgs": 8, "window_sec": 20},
    "max_warnings": 0,
    "warnings": {},
    "first_seen": "",
    "added_by": "",
}

URL_RE = re.compile(
    r"(https?://|www\.|chat\.whatsapp\.com/|wa\.me/|t\.me/)\S+"
    r"|\b[a-z0-9-]{2,}\.(com|net|org|io|me|ly|gg|xyz|info|mx|es|co|app|link|site|online|shop)(/\S*)?\b",
    re.IGNORECASE,
)
TARDIS_CALL_RE = re.compile(r"^\s*@?tardis\b[\s,:;.!?-]*", re.IGNORECASE)


def digits(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


def same_phone(a: str, b: str) -> bool:
    """Compara teléfonos tolerando prefijos de país (p. ej. MX 52 / 521)."""
    da, db = digits(a), digits(b)
    if len(da) < 8 or len(db) < 8:
        return False
    if da == db:
        return True
    return len(da) >= 10 and len(db) >= 10 and da[-10:] == db[-10:]


def jid_user(jid: str) -> str:
    return (jid or "").split("@", 1)[0].split(":", 1)[0]


def jid_server(jid: str) -> str:
    return (jid or "").split("@", 1)[1] if "@" in (jid or "") else ""


def now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------------
# Tipos de intercambio con el adaptador
# ----------------------------------------------------------------------------

@dataclass
class Participant:
    jid: str                 # JID principal (puede ser @lid)
    phone: str = ""          # dígitos del número si se conocen
    lid: str = ""
    is_admin: bool = False
    is_super_admin: bool = False
    name: str = ""

    def matches(self, ident: str) -> bool:
        ident = ident or ""
        if "@" in ident:
            u = jid_user(ident)
            return u in (jid_user(self.jid), jid_user(self.lid), digits(self.phone)) and bool(u)
        return same_phone(ident, self.phone) or (bool(digits(ident)) and digits(ident) == jid_user(self.jid))


@dataclass
class GroupSnapshot:
    jid: str
    name: str = ""
    topic: str = ""
    announce: bool = False
    locked: bool = False
    owner: str = ""
    participants: List[Participant] = field(default_factory=list)

    def find(self, ident: str) -> Optional[Participant]:
        for p in self.participants:
            if p.matches(ident):
                return p
        return None


@dataclass
class IncomingMessage:
    chat: str
    msg_id: str
    sender: str                    # JID del remitente (puede ser @lid)
    sender_phone: str = ""         # dígitos resueltos (vacío si no se pudo)
    push_name: str = ""
    text: str = ""
    is_from_me: bool = False
    is_group: bool = True
    mentions: List[str] = field(default_factory=list)
    quoted_id: str = ""
    quoted_sender: str = ""
    raw: Any = None


class WAAdapter(Protocol):
    def me(self) -> List[str]: ...
    def send_text(self, chat: str, text: str, reply_to: Optional[IncomingMessage] = None,
                  mentions: Optional[List[str]] = None) -> Optional[str]: ...
    def group_info(self, chat: str) -> GroupSnapshot: ...
    def joined_groups(self) -> List[GroupSnapshot]: ...
    def update_participants(self, chat: str, jids: List[str], action: str) -> List[Tuple[str, int]]: ...
    def set_name(self, chat: str, name: str) -> None: ...
    def set_topic(self, chat: str, topic: str) -> None: ...
    def set_announce(self, chat: str, value: bool) -> None: ...
    def set_locked(self, chat: str, value: bool) -> None: ...
    def invite_link(self, chat: str, revoke: bool = False) -> str: ...
    def revoke(self, chat: str, sender: str, msg_id: str) -> None: ...
    def ask_tardis(self, prompt: str, client_id: str) -> str: ...


# ----------------------------------------------------------------------------
# Persistencia
# ----------------------------------------------------------------------------

class GroupStore:
    """Estado persistente (JSON 0600, escritura atómica)."""

    def __init__(self, path: Path, seed_managers: Optional[List[str]] = None):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.data: Dict[str, Any] = {"version": 1, "global_managers": [], "groups": {}}
        self._load()
        if not self.data["global_managers"] and seed_managers:
            self.data["global_managers"] = [d for d in (digits(m) for m in seed_managers) if len(d) >= 8]
            self.save()

    def _load(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception:
                # Un archivo corrupto no debe conceder permisos: se conserva aparte
                self.path.rename(self.path.with_suffix(f".corrupto.{int(time.time())}"))
        self.data.setdefault("global_managers", [])
        self.data.setdefault("groups", {})
        for jid, g in list(self.data["groups"].items()):
            self.data["groups"][jid] = self._with_defaults(g)

    @staticmethod
    def _with_defaults(g: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(DEFAULT_GROUP)
        for k, v in (g or {}).items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
        if merged.get("level") not in LEVELS:
            merged["level"] = "chat"
        if merged.get("reply_mode") not in REPLY_MODES:
            merged["reply_mode"] = "menciones"
        return merged

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".groups.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    # -- grupos --
    def group(self, jid: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            g = self.data["groups"].get(jid)
            return g

    def ensure_group(self, jid: str, name: str = "", added_by: str = "") -> Dict[str, Any]:
        with self._lock:
            g = self.data["groups"].get(jid)
            if g is None:
                g = self._with_defaults({"name": name, "first_seen": now_iso(), "added_by": added_by})
                self.data["groups"][jid] = g
                self.save()
            elif name and g.get("name") != name:
                g["name"] = name
                self.save()
            return g

    def is_authorized(self, jid: str) -> bool:
        g = self.group(jid)
        return bool(g and g.get("authorized"))

    def authorize(self, jid: str, name: str, level: str, via: str = "consola-local") -> Dict[str, Any]:
        if level not in LEVELS:
            raise ValueError(f"Nivel inválido: {level}. Usa: {', '.join(LEVELS)}")
        with self._lock:
            g = self.ensure_group(jid, name)
            g.update({"authorized": True, "level": level, "authorized_at": now_iso(), "authorized_via": via})
            self.save()
            return g

    def revoke(self, jid: str) -> bool:
        with self._lock:
            g = self.data["groups"].get(jid)
            if not g or not g.get("authorized"):
                return False
            g["authorized"] = False
            self.save()
            return True

    def update(self, jid: str, fn: Callable[[Dict[str, Any]], Any]) -> Any:
        with self._lock:
            g = self.data["groups"][jid]
            res = fn(g)
            self.save()
            return res

    # -- gestores --
    def global_managers(self) -> List[str]:
        return list(self.data.get("global_managers", []))

    def set_manager(self, phone: str, add: bool, group_jid: Optional[str] = None) -> List[str]:
        d = digits(phone)
        if len(d) < 8:
            raise ValueError("Número inválido (mínimo 8 dígitos, con lada de país)")
        with self._lock:
            target = self.data["global_managers"] if group_jid is None else self.data["groups"][group_jid]["managers"]
            present = [m for m in target if same_phone(m, d)]
            if add and not present:
                target.append(d)
            elif not add:
                for m in present:
                    target.remove(m)
            self.save()
            return list(target)

    def is_manager(self, phone: str, group_jid: Optional[str] = None) -> bool:
        if not phone:
            return False
        if any(same_phone(phone, m) for m in self.data.get("global_managers", [])):
            return True
        g = self.group(group_jid) if group_jid else None
        return bool(g and any(same_phone(phone, m) for m in g.get("managers", [])))

    def is_global_manager(self, phone: str) -> bool:
        return bool(phone) and any(same_phone(phone, m) for m in self.data.get("global_managers", []))


# ----------------------------------------------------------------------------
# Registro de eventos (sin contenido de conversaciones)
# ----------------------------------------------------------------------------

class EventLog:
    def __init__(self, path: Path, keep: int = 5000):
        self.path = Path(path)
        self.keep = keep
        self._lock = threading.Lock()

    def add(self, kind: str, group: str = "", **info: Any) -> None:
        entry = {"ts": now_iso(), "kind": kind, "group": group, **info}
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                os.chmod(self.path, 0o600)
                if self.path.stat().st_size > 4_000_000:
                    lines = self.path.read_text(encoding="utf-8").splitlines()[-self.keep:]
                    self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except Exception:
                pass

    def tail(self, n: int = 50) -> List[Dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
            return [json.loads(l) for l in lines if l.strip()]
        except Exception:
            return []


# ----------------------------------------------------------------------------
# Gestor
# ----------------------------------------------------------------------------

@dataclass
class Command:
    names: Tuple[str, ...]
    perm: str                 # public | manager | chat | moderate | admin
    needs_admin: bool         # TARDIS debe ser administrador del grupo
    usage: str
    help: str


COMMANDS: List[Command] = [
    Command(("ayuda", "help", "comandos"), "public", False, "/ayuda", "Lista de comandos"),
    Command(("reglas", "rules"), "public", False, "/reglas [texto]", "Ver reglas (gestores: definirlas)"),
    Command(("estado", "tardis_estado"), "manager", False, "/estado", "Configuración de TARDIS en este grupo"),
    Command(("info",), "manager", False, "/info", "Información del grupo"),
    Command(("admins",), "manager", False, "/admins", "Lista de administradores"),
    Command(("miembros",), "manager", False, "/miembros", "Número de miembros"),
    Command(("tardis",), "manager", False, "/tardis menciones|todo|off", "Cuándo responde TARDIS en el chat"),
    Command(("nombre",), "admin", True, "/nombre <texto>", "Cambiar nombre del grupo"),
    Command(("descripcion", "descripción"), "admin", True, "/descripcion <texto>", "Cambiar descripción"),
    Command(("cerrar",), "admin", True, "/cerrar", "Solo administradores pueden escribir"),
    Command(("abrir",), "admin", True, "/abrir", "Todos pueden escribir"),
    Command(("bloquear_ajustes",), "admin", True, "/bloquear_ajustes", "Solo administradores editan la info"),
    Command(("desbloquear_ajustes",), "admin", True, "/desbloquear_ajustes", "Todos editan la info"),
    Command(("enlace", "link"), "admin", True, "/enlace", "Enlace de invitación"),
    Command(("nuevo_enlace",), "admin", True, "/nuevo_enlace", "Revocar y generar nuevo enlace"),
    Command(("agregar", "añadir", "anadir"), "admin", True, "/agregar <número> [...]", "Añadir miembros"),
    Command(("expulsar", "sacar", "kick"), "moderate", True, "/expulsar <@mención|número|respuesta>", "Expulsar miembro"),
    Command(("promover",), "admin", True, "/promover <@mención|número|respuesta>", "Hacer administrador"),
    Command(("degradar",), "admin", True, "/degradar <@mención|número|respuesta>", "Quitar administrador"),
    Command(("borrar", "eliminar"), "moderate", True, "/borrar (respondiendo a un mensaje)", "Borrar un mensaje"),
    Command(("advertir", "warn"), "moderate", False, "/advertir <@mención|respuesta> [motivo]", "Advertir a un miembro"),
    Command(("advertencias",), "moderate", False, "/advertencias", "Ver advertencias"),
    Command(("perdonar",), "moderate", False, "/perdonar <@mención|número|respuesta>", "Borrar advertencias"),
    Command(("max_advertencias",), "moderate", False, "/max_advertencias <n>", "Expulsar al llegar a n (0 = nunca)"),
    Command(("bienvenida",), "manager", False, "/bienvenida on|off|<texto>", "Mensaje de bienvenida ({mencion}, {grupo})"),
    Command(("antilink",), "moderate", False, "/antilink on|off", "Borrar enlaces de no administradores"),
    Command(("antiflood",), "moderate", False, "/antiflood on|off [mensajes] [segundos]", "Limitar ráfagas de mensajes"),
]
_CMD_INDEX = {name: c for c in COMMANDS for name in c.names}

PERM_ORDER = {"public": 0, "manager": 1, "chat": 1, "moderate": 2, "admin": 3}


class GroupManager:
    def __init__(self, adapter: WAAdapter, store: GroupStore, log: EventLog,
                 notify: Optional[Callable[[str], None]] = None,
                 chat_cooldown_sec: float = 4.0):
        self.wa = adapter
        self.store = store
        self.log = log
        self.notify = notify or (lambda _t: None)
        self.chat_cooldown_sec = chat_cooldown_sec
        self._sent_ids: Deque[str] = deque(maxlen=500)
        self._flood: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._flood_warned: Dict[Tuple[str, str], float] = {}
        self._last_chat: Dict[Tuple[str, str], float] = {}
        self._chat_busy: set = set()
        self._lock = threading.Lock()
        self._capture = threading.local()

    # ------------------------------------------------------------------ util
    def _send(self, chat: str, text: str, reply_to: Optional[IncomingMessage] = None,
              mentions: Optional[List[str]] = None) -> None:
        captured = getattr(self._capture, "lines", None)
        if captured is not None:
            captured.append(text)
        mid = self.wa.send_text(chat, text, reply_to=reply_to, mentions=mentions)
        if mid:
            self._sent_ids.append(mid)

    def run_console_command(self, group_jid: str, text: str) -> List[str]:
        """Ejecuta un comando de grupo ordenado desde la consola local; devuelve lo publicado."""
        if not self.store.is_authorized(group_jid):
            raise PermissionError("El grupo no está autorizado. Usa: tardis-whatsapp autorizar <grupo>")
        text = text.strip()
        if not text.startswith("/"):
            text = "/" + text
        msg = IncomingMessage(chat=group_jid, msg_id="", sender="", text=text, is_from_me=True)
        self._capture.lines = []
        try:
            if not self.handle_command(msg, from_console=True):
                raise ValueError(f"Comando desconocido: {text.split()[0]}. Usa /ayuda")
            return list(self._capture.lines)
        finally:
            self._capture.lines = None

    def _me_users(self) -> set:
        return {jid_user(j) for j in self.wa.me() if j}

    def _is_me(self, jid: str) -> bool:
        return bool(jid) and jid_user(jid) in self._me_users()

    def _perms(self, group_jid: str) -> set:
        g = self.store.group(group_jid) or {}
        return LEVEL_PERMS.get(g.get("level", "chat"), set()) if g.get("authorized") else set()

    def _i_am_admin(self, snap: GroupSnapshot) -> bool:
        me = self._me_users()
        return any(p.is_admin or p.is_super_admin for p in snap.participants
                   if jid_user(p.jid) in me or jid_user(p.lid) in me or digits(p.phone) in me)

    def _is_group_admin(self, snap: Optional[GroupSnapshot], msg: IncomingMessage) -> bool:
        if not snap:
            return False
        p = snap.find(msg.sender) or (snap.find(msg.sender_phone) if msg.sender_phone else None)
        return bool(p and (p.is_admin or p.is_super_admin))

    def _is_manager(self, msg: IncomingMessage) -> bool:
        # Mensajes de la propia cuenta vinculada: los envía su dueño (o TARDIS, filtrado antes)
        if msg.is_from_me:
            return True
        return self.store.is_manager(msg.sender_phone, msg.chat)

    def _is_protected(self, snap: GroupSnapshot, target: Participant) -> bool:
        """TARDIS, el creador del grupo y los gestores globales no pueden ser atacados por comandos."""
        if self._is_me(target.jid) or self._is_me(target.lid) or (target.phone and digits(target.phone) in self._me_users()):
            return True
        if target.is_super_admin:
            return True
        return self.store.is_global_manager(target.phone)

    # ------------------------------------------------------------ entradas
    def on_joined_group(self, snap: GroupSnapshot, added_by: str = "") -> None:
        g = self.store.ensure_group(snap.jid, snap.name, added_by=added_by)
        self.log.add("tardis_añadido", snap.jid, name=snap.name, added_by=added_by)
        if not g.get("authorized"):
            self.notify(
                f"📲 TARDIS fue añadido al grupo de WhatsApp *{snap.name or snap.jid}*.\n"
                "No hará nada ahí hasta que lo autorices desde la consola local:\n"
                "`tardis-whatsapp grupos` y luego `tardis-whatsapp autorizar <n>`"
            )

    def on_participants_joined(self, group_jid: str, jids: List[str]) -> None:
        if "chat" not in self._perms(group_jid):
            return
        g = self.store.group(group_jid) or {}
        new = [j for j in jids if not self._is_me(j)]
        if not new:
            return
        self.log.add("miembros_nuevos", group_jid, count=len(new))
        if not g.get("welcome", {}).get("enabled"):
            return
        mention_txt = " ".join(f"@{jid_user(j)}" for j in new)
        text = (g["welcome"].get("text") or DEFAULT_WELCOME)
        text = text.replace("{mencion}", mention_txt).replace("{grupo}", g.get("name") or "el grupo")
        self._send(group_jid, text, mentions=new)

    def on_message(self, msg: IncomingMessage) -> None:
        if not msg.is_group or msg.msg_id in self._sent_ids:
            return
        if not self.store.is_authorized(msg.chat):
            # Solo se registra que existe; nunca se procesa el contenido
            self.store.ensure_group(msg.chat)
            return
        text = (msg.text or "").strip()
        perms = self._perms(msg.chat)

        if text.startswith("/"):
            if self.handle_command(msg):
                return
        if msg.is_from_me:
            return  # nunca moderar ni conversar consigo mismo

        if "moderate" in perms and self._moderate(msg):
            return
        if "chat" in perms and self._should_answer(msg):
            self._answer(msg)

    # ------------------------------------------------------------ moderación
    def _moderate(self, msg: IncomingMessage) -> bool:
        g = self.store.group(msg.chat) or {}
        if self._is_manager(msg):
            return False
        antilink = g.get("antilink") and URL_RE.search(msg.text or "")
        flood_cfg = g.get("antiflood", {})
        flooding = False
        if flood_cfg.get("enabled"):
            key = (msg.chat, msg.sender)
            now = time.time()
            window = max(3, int(flood_cfg.get("window_sec", 20)))
            with self._lock:
                q = self._flood[key]
                q.append(now)
                while q and now - q[0] > window:
                    q.popleft()
                flooding = len(q) > max(2, int(flood_cfg.get("max_msgs", 8)))
        if not (antilink or flooding):
            return False

        try:
            snap = self.wa.group_info(msg.chat)
        except Exception:
            return False
        if self._is_group_admin(snap, msg):
            return False
        i_am_admin = self._i_am_admin(snap)

        if antilink:
            if i_am_admin:
                try:
                    self.wa.revoke(msg.chat, msg.sender, msg.msg_id)
                except Exception:
                    pass
            self.log.add("antilink", msg.chat, sender=msg.sender_phone or msg.sender, deleted=i_am_admin)
            self._warn(msg.chat, snap, msg.sender, msg.sender_phone, "enviar enlaces", reply_to=msg)
            return True

        key = (msg.chat, msg.sender)
        if time.time() - self._flood_warned.get(key, 0) > int(flood_cfg.get("window_sec", 20)):
            self._flood_warned[key] = time.time()
            self.log.add("antiflood", msg.chat, sender=msg.sender_phone or msg.sender)
            self._warn(msg.chat, snap, msg.sender, msg.sender_phone, "enviar mensajes en ráfaga", reply_to=msg)
        elif i_am_admin:
            try:
                self.wa.revoke(msg.chat, msg.sender, msg.msg_id)
            except Exception:
                pass
        return True

    def _warn_key(self, sender: str, phone: str) -> str:
        return digits(phone) or jid_user(sender)

    def _warn(self, chat: str, snap: GroupSnapshot, sender: str, phone: str, reason: str,
              reply_to: Optional[IncomingMessage] = None) -> str:
        key = self._warn_key(sender, phone)

        def _inc(g):
            g["warnings"][key] = int(g["warnings"].get(key, 0)) + 1
            return g["warnings"][key], int(g.get("max_warnings", 0))

        count, max_w = self.store.update(chat, _inc)
        text = f"⚠️ @{jid_user(sender)} advertencia {count}" + (f"/{max_w}" if max_w else "") + f" por {reason}."
        self._send(chat, text, reply_to=reply_to, mentions=[sender])
        if max_w and count >= max_w:
            target = snap.find(sender) or (snap.find(phone) if phone else None)
            if target and not self._is_protected(snap, target) and self._i_am_admin(snap):
                try:
                    self.wa.update_participants(chat, [target.jid], "remove")
                    self.store.update(chat, lambda g: g["warnings"].pop(key, None))
                    self._send(chat, f"🚫 @{jid_user(sender)} fue expulsado al llegar a {max_w} advertencias.", mentions=[sender])
                    self.log.add("expulsion_automatica", chat, target=phone or sender)
                except Exception as e:
                    self.log.add("error", chat, action="expulsion_automatica", error=str(e))
        return text

    # ------------------------------------------------------------ conversación
    def _should_answer(self, msg: IncomingMessage) -> bool:
        g = self.store.group(msg.chat) or {}
        mode = g.get("reply_mode", "menciones")
        if mode == "off" or not (msg.text or "").strip():
            return False
        if mode == "todo":
            return True
        if any(self._is_me(m) for m in msg.mentions):
            return True
        if msg.quoted_sender and self._is_me(msg.quoted_sender):
            return True
        return bool(TARDIS_CALL_RE.match(msg.text or ""))

    def _clean_prompt(self, text: str) -> str:
        me = self._me_users()
        for u in me:
            text = text.replace(f"@{u}", " ")
        text = TARDIS_CALL_RE.sub("", text, count=1)
        return re.sub(r"\s+", " ", text).strip()

    def _answer(self, msg: IncomingMessage) -> None:
        key = (msg.chat, msg.sender)
        with self._lock:
            if msg.chat in self._chat_busy or time.time() - self._last_chat.get(key, 0) < self.chat_cooldown_sec:
                return
            self._chat_busy.add(msg.chat)
            self._last_chat[key] = time.time()
        try:
            question = self._clean_prompt(msg.text)
            if not question:
                self._send(msg.chat, "🛸 ¿En qué te ayudo?", reply_to=msg)
                return
            g = self.store.group(msg.chat) or {}
            prompt = (
                f"[Mensaje en el grupo de WhatsApp \"{g.get('name') or 'grupo'}\". "
                f"Lo escribe {msg.push_name or 'un miembro'}. Responde breve, en el idioma del mensaje, "
                f"apto para un chat grupal.]\n{question}"
            )
            reply = self.wa.ask_tardis(prompt, client_id=f"wa_grupo_{jid_user(msg.chat)}")
            if reply:
                self._send(msg.chat, reply[:3500], reply_to=msg)
        except Exception as e:
            self.log.add("error", msg.chat, action="chat", error=str(e))
            self._send(msg.chat, "⚠️ TARDIS no está disponible en este momento.", reply_to=msg)
        finally:
            with self._lock:
                self._chat_busy.discard(msg.chat)

    # ------------------------------------------------------------ comandos
    def handle_command(self, msg: IncomingMessage, from_console: bool = False) -> bool:
        """Devuelve True si el texto era un comando de TARDIS (aunque se deniegue)."""
        text = (msg.text or "").strip()
        head, _, rest = text.partition(" ")
        name = head[1:].lower().split("@", 1)[0]
        cmd = _CMD_INDEX.get(name)
        if cmd is None:
            return False
        args = rest.strip()
        perms = self._perms(msg.chat)
        is_manager = from_console or self._is_manager(msg)

        if cmd.perm != "public":
            if not is_manager:
                self.log.add("comando_denegado", msg.chat, cmd=name, sender=msg.sender_phone or msg.sender)
                self._send(msg.chat, "🔒 Solo los gestores autorizados de TARDIS pueden usar ese comando.", reply_to=msg)
                return True
            if cmd.perm in ("moderate", "admin") and cmd.perm not in perms:
                need = "moderacion" if cmd.perm == "moderate" else "completo"
                self._send(msg.chat, f"🔒 En este grupo TARDIS tiene nivel *{(self.store.group(msg.chat) or {}).get('level')}*; "
                           f"ese comando requiere nivel *{need}* (se cambia desde la consola local).", reply_to=msg)
                return True

        snap: Optional[GroupSnapshot] = None
        if cmd.needs_admin or name in ("info", "admins", "miembros"):
            try:
                snap = self.wa.group_info(msg.chat)
            except Exception as e:
                self._send(msg.chat, f"⚠️ No pude leer la información del grupo: {e}", reply_to=msg)
                return True
            if cmd.needs_admin and not self._i_am_admin(snap):
                self._send(msg.chat, "⚠️ Necesito ser *administrador del grupo* para hacer eso. Hazme admin y repite el comando.", reply_to=msg)
                return True

        try:
            out = getattr(self, f"_cmd_{cmd.names[0]}")(msg, args, snap, is_manager)
        except Exception as e:
            out = f"⚠️ Error ejecutando /{name}: {e}"
            self.log.add("error", msg.chat, cmd=name, error=str(e))
        else:
            if cmd.perm not in ("public",):
                self.log.add("comando", msg.chat, cmd=name, by="consola-local" if from_console else (msg.sender_phone or msg.sender))
        if out:
            self._send(msg.chat, out, reply_to=None if from_console else msg)
        return True

    def _targets(self, msg: IncomingMessage, args: str, snap: GroupSnapshot) -> Tuple[List[Participant], List[str]]:
        idents: List[str] = [m for m in msg.mentions if not self._is_me(m)]
        if msg.quoted_sender and not idents:
            idents.append(msg.quoted_sender)
        # Las @menciones ya llegan en msg.mentions; sus dígitos (a veces un LID) no son teléfonos
        plain = re.sub(r"@\d+", " ", args)
        idents += [d for d in (digits(t) for t in re.findall(r"\+?[\d][\d\s-]{6,}\d", plain)) if len(d) >= 8]
        found, missing = [], []
        for ident in dict.fromkeys(idents):
            p = snap.find(ident)
            if p and p not in found:
                found.append(p)
            elif not p:
                missing.append(ident)
        return found, missing

    def _cmd_ayuda(self, msg, args, snap, is_manager):
        lines = ["🛸 *TARDIS · gestión del grupo*"]
        perms = self._perms(msg.chat)
        for c in COMMANDS:
            if c.perm == "public" or (is_manager and (c.perm == "manager" or c.perm in perms)):
                lines.append(f"• {c.usage} — {c.help}")
        lines.append("\nMenciona a TARDIS o empieza con «TARDIS,» para hablar con él.")
        return "\n".join(lines)

    def _cmd_reglas(self, msg, args, snap, is_manager):
        if args and is_manager:
            self.store.update(msg.chat, lambda g: g.__setitem__("rules", args[:3000]))
            return "📜 Reglas actualizadas."
        rules = (self.store.group(msg.chat) or {}).get("rules")
        return f"📜 *Reglas del grupo*\n{rules}" if rules else "📜 Aún no hay reglas definidas."

    def _cmd_estado(self, msg, args, snap, is_manager):
        g = self.store.group(msg.chat) or {}
        af = g["antiflood"]
        return (
            "🛸 *TARDIS en este grupo*\n"
            f"• Nivel: {g['level']} (autorizado {g['authorized_at']} vía {g['authorized_via']})\n"
            f"• Responde: {g['reply_mode']}\n"
            f"• Bienvenida: {'on' if g['welcome']['enabled'] else 'off'}\n"
            f"• Antilink: {'on' if g['antilink'] else 'off'}\n"
            f"• Antiflood: {'on' if af['enabled'] else 'off'} ({af['max_msgs']} msgs / {af['window_sec']} s)\n"
            f"• Expulsión automática: {g['max_warnings'] or 'desactivada'}"
        )

    def _cmd_info(self, msg, args, snap, is_manager):
        admins = sum(1 for p in snap.participants if p.is_admin or p.is_super_admin)
        return (
            f"ℹ️ *{snap.name}*\n"
            f"• Miembros: {len(snap.participants)} · Administradores: {admins}\n"
            f"• Solo admins escriben: {'sí' if snap.announce else 'no'}\n"
            f"• Solo admins editan info: {'sí' if snap.locked else 'no'}\n"
            f"• TARDIS es administrador: {'sí' if self._i_am_admin(snap) else 'no'}\n"
            + (f"• Descripción: {snap.topic[:300]}" if snap.topic else "")
        ).strip()

    def _cmd_admins(self, msg, args, snap, is_manager):
        admins = [p for p in snap.participants if p.is_admin or p.is_super_admin]
        mentions = [p.jid for p in admins]
        body = "\n".join(f"• @{jid_user(p.jid)}" + (" (creador)" if p.is_super_admin else "") for p in admins)
        self._send(msg.chat, f"👮 *Administradores* ({len(admins)})\n{body}", reply_to=msg, mentions=mentions)
        return ""

    def _cmd_miembros(self, msg, args, snap, is_manager):
        return f"👥 El grupo tiene {len(snap.participants)} miembros."

    def _cmd_tardis(self, msg, args, snap, is_manager):
        mode = args.lower().strip()
        if mode not in REPLY_MODES:
            return "Uso: /tardis menciones|todo|off"
        self.store.update(msg.chat, lambda g: g.__setitem__("reply_mode", mode))
        return {"menciones": "🛸 Responderé cuando me mencionen o me respondan.",
                "todo": "🛸 Responderé a todos los mensajes del grupo.",
                "off": "🛸 Dejo de conversar en el grupo (sigo gestionando)."}[mode]

    def _cmd_nombre(self, msg, args, snap, is_manager):
        if not args:
            return "Uso: /nombre <nuevo nombre>"
        self.wa.set_name(msg.chat, args[:100])
        self.store.ensure_group(msg.chat, args[:100])
        return f"✏️ Nombre cambiado a *{args[:100]}*."

    def _cmd_descripcion(self, msg, args, snap, is_manager):
        if not args:
            return "Uso: /descripcion <texto>"
        self.wa.set_topic(msg.chat, args[:2000])
        return "✏️ Descripción actualizada."

    def _cmd_cerrar(self, msg, args, snap, is_manager):
        self.wa.set_announce(msg.chat, True)
        return "🔒 Grupo cerrado: solo los administradores pueden escribir."

    def _cmd_abrir(self, msg, args, snap, is_manager):
        self.wa.set_announce(msg.chat, False)
        return "🔓 Grupo abierto: todos pueden escribir."

    def _cmd_bloquear_ajustes(self, msg, args, snap, is_manager):
        self.wa.set_locked(msg.chat, True)
        return "🔒 Solo los administradores pueden editar la información del grupo."

    def _cmd_desbloquear_ajustes(self, msg, args, snap, is_manager):
        self.wa.set_locked(msg.chat, False)
        return "🔓 Todos pueden editar la información del grupo."

    def _cmd_enlace(self, msg, args, snap, is_manager):
        return f"🔗 Enlace de invitación:\n{self.wa.invite_link(msg.chat)}"

    def _cmd_nuevo_enlace(self, msg, args, snap, is_manager):
        return f"🔗 Enlace anterior revocado. Nuevo enlace:\n{self.wa.invite_link(msg.chat, revoke=True)}"

    def _cmd_agregar(self, msg, args, snap, is_manager):
        nums = [d for d in (digits(t) for t in re.split(r"[\s,;]+", args)) if len(d) >= 8]
        if not nums:
            return "Uso: /agregar <número con lada de país> [...]  (ej. /agregar 5215512345678)"
        results = self.wa.update_participants(msg.chat, [f"{n}@s.whatsapp.net" for n in nums], "add")
        lines = []
        for jid, code in results:
            u = jid_user(jid)
            if code in (0, 200):
                lines.append(f"✅ {u} añadido")
            elif code == 403:
                lines.append(f"📨 {u} no permite que lo añadan; comparte /enlace con esa persona")
            elif code == 409:
                lines.append(f"ℹ️ {u} ya está en el grupo")
            else:
                lines.append(f"❌ {u} no se pudo añadir (código {code})")
        return "\n".join(lines) or "Sin cambios."

    def _participant_action(self, msg, args, snap, action: str, verb: str) -> str:
        targets, missing = self._targets(msg, args, snap)
        if not targets:
            return (f"No encontré a quién {verb} en el grupo: {', '.join(missing)}" if missing
                    else f"Indica a quién {verb}: @mención, número o responde a su mensaje.")
        allowed = []
        lines = []
        for t in targets:
            if action in ("remove", "demote") and self._is_protected(snap, t):
                lines.append(f"🛡️ @{jid_user(t.jid)} está protegido")
            elif action == "promote" and (t.is_admin or t.is_super_admin):
                lines.append(f"ℹ️ @{jid_user(t.jid)} ya es administrador")
            elif action == "demote" and not t.is_admin:
                lines.append(f"ℹ️ @{jid_user(t.jid)} no es administrador")
            else:
                allowed.append(t)
        if allowed:
            results = dict(self.wa.update_participants(msg.chat, [t.jid for t in allowed], action))
            for t in allowed:
                code = results.get(t.jid, 200)
                ok = code in (0, 200)
                lines.append(("✅ " if ok else "❌ ") + f"@{jid_user(t.jid)} " + (verb + "do" if ok else f"no se pudo {verb} (código {code})"))
                if ok and action == "remove":
                    key = self._warn_key(t.jid, t.phone)
                    self.store.update(msg.chat, lambda g: g["warnings"].pop(key, None))
        for m in missing:
            lines.append(f"❓ {jid_user(m)} no está en el grupo")
        self._send(msg.chat, "\n".join(lines), reply_to=msg, mentions=[t.jid for t in targets])
        return ""

    def _cmd_expulsar(self, msg, args, snap, is_manager):
        return self._participant_action(msg, args, snap, "remove", "expulsa")

    def _cmd_promover(self, msg, args, snap, is_manager):
        return self._participant_action(msg, args, snap, "promote", "promovi")

    def _cmd_degradar(self, msg, args, snap, is_manager):
        return self._participant_action(msg, args, snap, "demote", "degrada")

    def _cmd_borrar(self, msg, args, snap, is_manager):
        if not msg.quoted_id:
            return "Responde al mensaje que quieres borrar con /borrar."
        self.wa.revoke(msg.chat, msg.quoted_sender, msg.quoted_id)
        return ""

    def _cmd_advertir(self, msg, args, snap, is_manager):
        snap = snap or self.wa.group_info(msg.chat)
        targets, _ = self._targets(msg, args, snap)
        if not targets:
            return "Indica a quién advertir: @mención, número o responde a su mensaje."
        reason = re.sub(r"@\d+|\+?[\d][\d\s-]{6,}\d", "", args).strip() or "incumplir las reglas"
        for t in targets:
            if self._is_protected(snap, t):
                self._send(msg.chat, f"🛡️ @{jid_user(t.jid)} está protegido.", mentions=[t.jid])
                continue
            self._warn(msg.chat, snap, t.jid, t.phone, reason)
        return ""

    def _cmd_advertencias(self, msg, args, snap, is_manager):
        g = self.store.group(msg.chat) or {}
        w = g.get("warnings", {})
        if not w:
            return "✅ Nadie tiene advertencias."
        body = "\n".join(f"• +{k}: {v}" for k, v in sorted(w.items(), key=lambda kv: -kv[1]))
        return f"⚠️ *Advertencias* (máx: {g.get('max_warnings') or '∞'})\n{body}"

    def _cmd_perdonar(self, msg, args, snap, is_manager):
        snap = snap or self.wa.group_info(msg.chat)
        targets, _ = self._targets(msg, args, snap)
        if not targets:
            return "Indica a quién perdonar: @mención, número o responde a su mensaje."
        for t in targets:
            for key in {self._warn_key(t.jid, t.phone), jid_user(t.jid), jid_user(t.lid)}:
                self.store.update(msg.chat, lambda g, k=key: g["warnings"].pop(k, None))
        return "🕊️ Advertencias borradas."

    def _cmd_max_advertencias(self, msg, args, snap, is_manager):
        if not args.strip().isdigit():
            return "Uso: /max_advertencias <n>  (0 = nunca expulsar)"
        n = min(int(args.strip()), 50)
        self.store.update(msg.chat, lambda g: g.__setitem__("max_warnings", n))
        return f"⚙️ Expulsión automática {'desactivada' if n == 0 else f'al llegar a {n} advertencias'}."

    def _cmd_bienvenida(self, msg, args, snap, is_manager):
        low = args.lower().strip()
        if low in ("on", "off"):
            self.store.update(msg.chat, lambda g: g["welcome"].__setitem__("enabled", low == "on"))
            return f"👋 Bienvenida {'activada' if low == 'on' else 'desactivada'}."
        if args:
            def _set(g):
                g["welcome"]["text"] = args[:1000]
                g["welcome"]["enabled"] = True
            self.store.update(msg.chat, _set)
            return "👋 Mensaje de bienvenida actualizado y activado."
        return "Uso: /bienvenida on|off|<texto con {mencion} y {grupo}>"

    def _cmd_antilink(self, msg, args, snap, is_manager):
        low = args.lower().strip()
        if low not in ("on", "off"):
            return "Uso: /antilink on|off"
        self.store.update(msg.chat, lambda g: g.__setitem__("antilink", low == "on"))
        return f"🔗 Antilink {'activado' if low == 'on' else 'desactivado'}."

    def _cmd_antiflood(self, msg, args, snap, is_manager):
        parts = args.lower().split()
        if not parts or parts[0] not in ("on", "off"):
            return "Uso: /antiflood on|off [mensajes] [segundos]"

        def _set(g):
            g["antiflood"]["enabled"] = parts[0] == "on"
            if len(parts) > 1 and parts[1].isdigit():
                g["antiflood"]["max_msgs"] = max(3, min(int(parts[1]), 100))
            if len(parts) > 2 and parts[2].isdigit():
                g["antiflood"]["window_sec"] = max(3, min(int(parts[2]), 600))
            return g["antiflood"]

        af = self.store.update(msg.chat, _set)
        return (f"🌊 Antiflood activado: más de {af['max_msgs']} mensajes en {af['window_sec']} s = advertencia."
                if af["enabled"] else "🌊 Antiflood desactivado.")
