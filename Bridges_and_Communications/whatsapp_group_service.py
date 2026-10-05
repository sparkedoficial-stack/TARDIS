#!/usr/bin/env python3
"""
whatsapp_group_service.py - TARDIS en grupos de WhatsApp (dispositivo vinculado)
===============================================================================
TARDIS se conecta como *dispositivo vinculado* de la cuenta de WhatsApp que se
añadió al grupo (igual que WhatsApp Web), usando neonize/whatsmeow. La Cloud API
de Meta no permite que una cuenta de empresa sea añadida a grupos normales.

  - Servicio:  systemctl --user start tardis-whatsapp   (ejecuta este archivo)
  - Consola:   tardis-whatsapp ...   (habla con el servicio por un socket Unix
               accesible solo por el usuario local; nada se expone a la red)
  - Vincular:  tardis-whatsapp vincular [--telefono 52XXXXXXXXXX]

Toda la lógica de gestión vive en core/wa_group_manager.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import socketserver
import sqlite3
import struct
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from core.wa_group_manager import (  # noqa: E402
    LEVELS,
    EventLog,
    GroupManager,
    GroupSnapshot,
    GroupStore,
    IncomingMessage,
    Participant,
    digits,
    jid_server,
    jid_user,
)

DATA_DIR = BASE_DIR / "data" / "whatsapp"
SESSION_DB = DATA_DIR / "session.sqlite3"
STORE_FILE = DATA_DIR / "groups.json"
EVENTS_FILE = DATA_DIR / "events.jsonl"
SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "tardis-whatsapp.sock"
TARDIS_API = os.environ.get("GIA_API_URL", "http://REDACTED_IP:8757")
LEGACY_WA_CONFIG = BASE_DIR / "whatsapp_config.json"
MAX_MESSAGE_AGE_SEC = 300

log = logging.getLogger("TardisWhatsApp")


def session_exists() -> bool:
    if not SESSION_DB.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{SESSION_DB}?mode=ro", uri=True, timeout=5)
        try:
            return con.execute("SELECT count(*) FROM whatsmeow_device").fetchone()[0] > 0
        finally:
            con.close()
    except sqlite3.Error:
        return False


def seed_managers() -> List[str]:
    """El Arquitecto (admin_number del puente de WhatsApp) es gestor global por defecto."""
    try:
        cfg = json.loads(LEGACY_WA_CONFIG.read_text(encoding="utf-8"))
        return [n for n in [cfg.get("admin_number", "")] if len(digits(n)) >= 8]
    except Exception:
        return []


def tardis_post(path: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(
        f"{TARDIS_API}{path}", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def notify_architect(text: str) -> None:
    try:
        tardis_post("/api/telegram/send", {"text": text}, timeout=15)
    except Exception as e:
        log.warning("No se pudo notificar por Telegram: %s", e)


# ----------------------------------------------------------------------------
# Adaptador neonize -> GroupManager
# ----------------------------------------------------------------------------

def jid_str(j) -> str:
    if j is None or not getattr(j, "User", ""):
        return ""
    return f"{j.User}@{j.Server}"


def to_jid(s: str):
    from neonize.utils.jid import build_jid
    return build_jid(jid_user(s), jid_server(s) or "s.whatsapp.net")


class NeonizeAdapter:
    def __init__(self, client):
        self.c = client
        self._me: List[str] = []
        self._me_ts = 0.0

    def me(self) -> List[str]:
        if not self._me or time.time() - self._me_ts > 300:
            try:
                d = self.c.get_me()
                self._me = [x for x in (jid_str(d.JID), jid_str(d.LID)) if x]
                self._me_ts = time.time()
            except Exception:
                pass
        return self._me

    def phone_of(self, j) -> str:
        if j is None or not j.User:
            return ""
        if j.Server == "s.whatsapp.net":
            return j.User
        if j.Server == "lid":
            try:
                pn = self.c.get_pn_from_lid(j)
                if pn and pn.User:
                    return pn.User
            except Exception:
                pass
        return ""

    def snapshot(self, info) -> GroupSnapshot:
        parts = []
        for p in info.Participants:
            phone = p.PhoneNumber.User if p.PhoneNumber.User else (p.JID.User if p.JID.Server == "s.whatsapp.net" else "")
            parts.append(Participant(
                jid=jid_str(p.JID), phone=phone, lid=jid_str(p.LID),
                is_admin=p.IsAdmin, is_super_admin=p.IsSuperAdmin, name=p.DisplayName,
            ))
        return GroupSnapshot(
            jid=jid_str(info.JID), name=info.GroupName.Name, topic=info.GroupTopic.Topic,
            announce=info.GroupAnnounce.IsAnnounce, locked=info.GroupLocked.isLocked,
            owner=jid_str(info.OwnerJID), participants=parts,
        )

    def send_text(self, chat: str, text: str, reply_to: Optional[IncomingMessage] = None,
                  mentions: Optional[List[str]] = None) -> Optional[str]:
        from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import ContextInfo, ExtendedTextMessage, Message
        from neonize.utils.jid import Jid2String, JIDToNonAD

        ctx = ContextInfo(mentionedJID=[m for m in (mentions or []) if m and f"@{jid_user(m)}" in text])
        raw = reply_to.raw if reply_to is not None else None
        if raw is not None:
            ctx.stanzaID = raw.Info.ID
            ctx.participant = Jid2String(JIDToNonAD(raw.Info.MessageSource.Sender))
            ctx.quotedMessage.CopyFrom(raw.Message)
        if ctx.ListFields():
            msg = Message(extendedTextMessage=ExtendedTextMessage(text=text, contextInfo=ctx))
        else:
            msg = Message(conversation=text)
        resp = self.c.send_message(to_jid(chat), msg)
        return getattr(resp, "ID", None)

    def group_info(self, chat: str) -> GroupSnapshot:
        return self.snapshot(self.c.get_group_info(to_jid(chat)))

    def joined_groups(self) -> List[GroupSnapshot]:
        return [self.snapshot(g) for g in self.c.get_joined_groups()]

    def update_participants(self, chat: str, jids: List[str], action: str) -> List[Tuple[str, int]]:
        from neonize.utils.enum import ParticipantChange
        res = self.c.update_group_participants(to_jid(chat), [to_jid(j) for j in jids], ParticipantChange(action))
        out = []
        for p in res:
            out.append((jid_str(p.JID), int(p.Error) or 200))
        # Si el servidor devolvió JIDs en otra forma (LID vs teléfono), conservar los pedidos
        returned = {jid_user(j) for j, _ in out}
        for j in jids:
            if jid_user(j) not in returned and len(out) < len(jids):
                out.append((j, 200))
        return out

    def set_name(self, chat: str, name: str) -> None:
        self.c.set_group_name(to_jid(chat), name)

    def set_topic(self, chat: str, topic: str) -> None:
        self.c.set_group_topic(to_jid(chat), "", "", topic)

    def set_announce(self, chat: str, value: bool) -> None:
        self.c.set_group_announce(to_jid(chat), value)

    def set_locked(self, chat: str, value: bool) -> None:
        self.c.set_group_locked(to_jid(chat), value)

    def invite_link(self, chat: str, revoke: bool = False) -> str:
        return self.c.get_group_invite_link(to_jid(chat), revoke)

    def revoke(self, chat: str, sender: str, msg_id: str) -> None:
        self.c.revoke_message(to_jid(chat), to_jid(sender), msg_id)

    def ask_tardis(self, prompt: str, client_id: str) -> str:
        # client_mode: historial aislado por grupo y sin datos privados del Arquitecto
        res = tardis_post("/api/chat", {
            "message": prompt, "client_mode": True, "client_id": client_id,
            "stream": False, "use_voice": False,
        }, timeout=240)
        return (res.get("reply") or "").strip()


def extract_text_and_context(m) -> Tuple[str, Any]:
    if m.conversation:
        return m.conversation, None
    for field in ("extendedTextMessage", "imageMessage", "videoMessage", "documentMessage"):
        if m.HasField(field):
            sub = getattr(m, field)
            text = getattr(sub, "text", "") if field == "extendedTextMessage" else getattr(sub, "caption", "")
            return text or "", sub.contextInfo if sub.HasField("contextInfo") else None
    return "", None


def to_incoming(adapter: NeonizeAdapter, ev) -> Optional[IncomingMessage]:
    src = ev.Info.MessageSource
    if ev.IsEdit or not src.IsGroup:
        return None
    ts = int(ev.Info.Timestamp or 0)
    if ts > 10**12:
        ts //= 1000
    if ts and time.time() - ts > MAX_MESSAGE_AGE_SEC:
        return None  # mensajes atrasados (TARDIS estaba desconectado): no ejecutar órdenes viejas
    text, ctx = extract_text_and_context(ev.Message)
    phone = ""
    if src.SenderAlt.User and src.SenderAlt.Server == "s.whatsapp.net":
        phone = src.SenderAlt.User
    else:
        phone = adapter.phone_of(src.Sender)
    return IncomingMessage(
        chat=jid_str(src.Chat), msg_id=ev.Info.ID, sender=jid_str(src.Sender), sender_phone=phone,
        push_name=ev.Info.Pushname, text=text or "", is_from_me=src.IsFromMe, is_group=True,
        mentions=list(ctx.mentionedJID) if ctx is not None else [],
        quoted_id=ctx.stanzaID if ctx is not None else "",
        quoted_sender=ctx.participant if ctx is not None else "",
        raw=ev,
    )


# ----------------------------------------------------------------------------
# Servicio
# ----------------------------------------------------------------------------

class Service:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(DATA_DIR, 0o700)
        self.store = GroupStore(STORE_FILE, seed_managers=seed_managers())
        self.events = EventLog(EVENTS_FILE)
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="wa")
        self.client = None
        self.adapter: Optional[NeonizeAdapter] = None
        self.manager: Optional[GroupManager] = None
        self.state = "sin_vincular"
        self.state_detail = ""
        self.connected_since = 0.0

    # -- cliente --
    def run_client(self) -> None:
        from neonize.client import NewClient
        from neonize.events import (ConnectedEv, DisconnectedEv, GroupInfoEv, JoinedGroupEv,
                                    LoggedOutEv, MessageEv, StreamReplacedEv, TemporaryBanEv)

        client = NewClient(str(SESSION_DB))
        self.client = client
        self.adapter = NeonizeAdapter(client)
        self.manager = GroupManager(self.adapter, self.store, self.events, notify=notify_architect)
        self.state = "conectando"

        def safe(fn, *a):
            def run():
                try:
                    fn(*a)
                except Exception:
                    log.exception("Error procesando evento")
            self.pool.submit(run)

        def on_qr(_c, _data):
            # Sin sesión válida: no se muestran QR en el servicio; se vincula desde la consola
            self.state, self.state_detail = "sin_vincular", "La sesión no es válida. Ejecuta: tardis-whatsapp vincular"
            log.warning(self.state_detail)
            threading.Thread(target=client.disconnect, daemon=True).start()

        client.event.qr(on_qr)

        @client.event(ConnectedEv)
        def _connected(_c, _ev):
            self.state, self.state_detail, self.connected_since = "conectado", "", time.time()
            log.info("Conectado a WhatsApp como %s", self.adapter.me())
            safe(self.sync_groups)

        @client.event(DisconnectedEv)
        def _disconnected(_c, _ev):
            if self.state == "conectado":
                self.state = "reconectando"

        @client.event(StreamReplacedEv)
        def _replaced(_c, _ev):
            self.state, self.state_detail = "reemplazado", "Otra instancia abrió la misma sesión"
            log.error(self.state_detail)

        @client.event(TemporaryBanEv)
        def _ban(_c, ev):
            self.state, self.state_detail = "bloqueo_temporal", str(ev)
            notify_architect(f"⚠️ WhatsApp bloqueó temporalmente la cuenta de TARDIS: {ev}")

        @client.event(LoggedOutEv)
        def _logged_out(_c, ev):
            self.state, self.state_detail = "sin_vincular", "WhatsApp cerró la sesión (dispositivo desvinculado)"
            self.events.add("sesion_cerrada")
            notify_architect("⚠️ La sesión de WhatsApp de TARDIS se cerró. Vuelve a vincular con `tardis-whatsapp vincular`.")

        @client.event(MessageEv)
        def _message(_c, ev):
            msg = to_incoming(self.adapter, ev)
            if msg is not None:
                safe(self.manager.on_message, msg)

        @client.event(JoinedGroupEv)
        def _joined(_c, ev):
            snap = self.adapter.snapshot(ev.GroupInfo)
            added_by = ev.SenderPN.User or ev.Sender.User
            safe(self.manager.on_joined_group, snap, added_by)

        @client.event(GroupInfoEv)
        def _group_info(_c, ev):
            gjid = jid_str(ev.JID)
            if ev.Name.Name:
                safe(self.store.ensure_group, gjid, ev.Name.Name)
            joins = [jid_str(j) for j in ev.Join]
            if joins:
                safe(self.manager.on_participants_joined, gjid, joins)
            if ev.Leave and any(jid_user(jid_str(j)) in {jid_user(x) for x in self.adapter.me()} for j in ev.Leave):
                self.events.add("tardis_salio_o_expulsado", gjid)

        client.connect()  # bloqueante

    def sync_groups(self) -> None:
        for snap in self.adapter.joined_groups():
            self.store.ensure_group(snap.jid, snap.name)

    # -- control --
    def require_client(self) -> None:
        if self.client is None or self.manager is None:
            raise RuntimeError("WhatsApp no está vinculado. Ejecuta: tardis-whatsapp vincular")
        if self.state != "conectado":
            raise RuntimeError(f"WhatsApp no está conectado (estado: {self.state}). {self.state_detail}".strip())

    def groups_listing(self) -> List[Dict[str, Any]]:
        self.require_client()
        me = {jid_user(j) for j in self.adapter.me()}
        rows = []
        for snap in sorted(self.adapter.joined_groups(), key=lambda s: (s.name or "").lower()):
            g = self.store.ensure_group(snap.jid, snap.name)
            i_am_admin = any((p.is_admin or p.is_super_admin) and
                             (jid_user(p.jid) in me or jid_user(p.lid) in me) for p in snap.participants)
            rows.append({
                "jid": snap.jid, "name": snap.name, "members": len(snap.participants),
                "tardis_admin": i_am_admin, "authorized": bool(g.get("authorized")),
                "level": g.get("level") if g.get("authorized") else "", "managers": g.get("managers", []),
            })
        for i, r in enumerate(rows, 1):
            r["n"] = i
        return rows

    def resolve_group(self, ident: str) -> Dict[str, Any]:
        ident = (ident or "").strip()
        rows = self.groups_listing()
        if not ident:
            raise ValueError("Indica el grupo: número de la lista, nombre o JID")
        if ident.endswith("@g.us"):
            for r in rows:
                if r["jid"] == ident:
                    return r
            raise ValueError(f"TARDIS no está en el grupo {ident}")
        if ident.isdigit() and 1 <= int(ident) <= len(rows):
            return rows[int(ident) - 1]
        exact = [r for r in rows if (r["name"] or "").lower() == ident.lower()]
        matches = exact or [r for r in rows if ident.lower() in (r["name"] or "").lower()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f"No encontré ningún grupo que coincida con «{ident}». Usa: tardis-whatsapp grupos")
        raise ValueError("Varios grupos coinciden: " + ", ".join(f"{r['n']}) {r['name']}" for r in matches))

    def status(self) -> Dict[str, Any]:
        groups = self.store.data.get("groups", {})
        me = self.adapter.me() if self.adapter and self.state == "conectado" else []
        return {
            "ok": True, "state": self.state, "detail": self.state_detail, "account": me,
            "session_file": str(SESSION_DB), "global_managers": self.store.global_managers(),
            "authorized_groups": [{"jid": j, "name": g.get("name"), "level": g.get("level")}
                                  for j, g in groups.items() if g.get("authorized")],
            "connected_since": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.connected_since)) if self.connected_since else "",
        }

    def handle_api(self, method: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        if path == "/status":
            return self.status()
        if path == "/groups":
            return {"ok": True, "groups": self.groups_listing()}
        if path == "/log":
            return {"ok": True, "events": self.events.tail(int(body.get("n", 50)))}
        if path == "/managers" and method == "GET":
            return {"ok": True, "global": self.store.global_managers(),
                    "groups": {g.get("name") or j: g.get("managers", []) for j, g in self.store.data["groups"].items()
                               if g.get("authorized")}}
        if method != "POST":
            raise ValueError("Método no permitido")
        if path == "/authorize":
            level = body.get("level") or "completo"
            if level not in LEVELS:
                raise ValueError(f"Nivel inválido: {level}. Usa: {', '.join(LEVELS)}")
            r = self.resolve_group(body.get("group", ""))
            self.store.authorize(r["jid"], r["name"], level, via="consola-local")
            self.events.add("grupo_autorizado", r["jid"], name=r["name"], level=level)
            warning = "" if r["tardis_admin"] or level == "chat" else (
                "TARDIS no es administrador de ese grupo: podrá conversar, pero para moderar o "
                "administrar hazlo admin desde WhatsApp.")
            return {"ok": True, "group": r["name"], "jid": r["jid"], "level": level, "warning": warning}
        if path == "/revoke":
            r = self.resolve_group(body.get("group", ""))
            changed = self.store.revoke(r["jid"])
            self.events.add("grupo_revocado", r["jid"], name=r["name"])
            return {"ok": True, "group": r["name"], "changed": changed}
        if path == "/managers":
            gjid = None
            if body.get("group"):
                r = self.resolve_group(body["group"])
                if not r["authorized"]:
                    raise ValueError("Primero autoriza el grupo")
                gjid = r["jid"]
            lst = self.store.set_manager(body.get("phone", ""), bool(body.get("add", True)), gjid)
            self.events.add("gestores", gjid or "", phone=digits(body.get("phone", "")), add=bool(body.get("add", True)))
            return {"ok": True, "managers": lst}
        if path == "/send":
            r = self.resolve_group(body.get("group", ""))
            if not r["authorized"]:
                raise ValueError("El grupo no está autorizado")
            text = (body.get("text") or "").strip()
            if not text:
                raise ValueError("Texto vacío")
            self.adapter.send_text(r["jid"], text)
            self.events.add("mensaje_consola", r["jid"])
            return {"ok": True, "group": r["name"]}
        if path == "/command":
            r = self.resolve_group(body.get("group", ""))
            out = self.manager.run_console_command(r["jid"], body.get("text", ""))
            return {"ok": True, "group": r["name"], "output": out}
        if path == "/logout":
            self.require_client()
            self.client.logout()
            self.state = "sin_vincular"
            self.events.add("sesion_cerrada_consola")
            return {"ok": True}
        raise ValueError(f"Ruta desconocida: {path}")


class ControlHandler(BaseHTTPRequestHandler):
    service: Service = None  # type: ignore

    def address_string(self):
        return "local"

    def log_message(self, fmt, *args):
        log.debug("control: " + fmt, *args)

    def _peer_ok(self) -> bool:
        try:
            creds = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _pid, uid, _gid = struct.unpack("3i", creds)
            return uid == os.getuid()
        except OSError:
            return False

    def _reply(self, code: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method: str) -> None:
        if not self._peer_ok():
            self._reply(403, {"ok": False, "error": "Solo el usuario local puede controlar TARDIS-WhatsApp"})
            return
        parsed = urllib.parse.urlparse(self.path)
        body: Dict[str, Any] = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            try:
                body.update(json.loads(self.rfile.read(length).decode("utf-8")))
            except Exception:
                self._reply(400, {"ok": False, "error": "JSON inválido"})
                return
        try:
            self._reply(200, self.service.handle_api(method, parsed.path, body))
        except (ValueError, PermissionError, RuntimeError) as e:
            self._reply(400, {"ok": False, "error": str(e)})
        except Exception as e:
            log.exception("Error en control")
            self._reply(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def start_control(service: Service) -> UnixHTTPServer:
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        SOCKET_PATH.unlink()
    except FileNotFoundError:
        pass
    ControlHandler.service = service
    old_umask = os.umask(0o177)
    try:
        server = UnixHTTPServer(str(SOCKET_PATH), ControlHandler)
    finally:
        os.umask(old_umask)
    os.chmod(SOCKET_PATH, 0o600)
    threading.Thread(target=server.serve_forever, name="control", daemon=True).start()
    return server


# ----------------------------------------------------------------------------
# Vinculación (se ejecuta desde la consola local con el servicio detenido)
# ----------------------------------------------------------------------------

def pair(phone: Optional[str] = None, timeout: int = 240) -> int:
    import segno
    from neonize.client import NewClient
    from neonize.events import ConnectedEv, PairStatusEv

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    if session_exists():
        print("ℹ️  Ya hay una sesión vinculada. Usa `tardis-whatsapp desvincular` antes de vincular otra cuenta.")
        return 1

    client = NewClient(str(SESSION_DB))
    paired = threading.Event()
    connected = threading.Event()
    state = {"qr_count": 0, "error": ""}

    def request_code():
        try:
            code = client.PairPhone(digits(phone), True)
            code = f"{code[:4]}-{code[4:]}" if len(code) == 8 else code
            print("\n🔑 Código de vinculación:  " + code)
            print("   En el teléfono de TARDIS: WhatsApp → Ajustes → Dispositivos vinculados →")
            print("   Vincular un dispositivo → «Vincular con el número de teléfono» e ingresa el código.\n", flush=True)
        except Exception as e:
            state["error"] = f"No se pudo pedir el código: {e}"
            paired.set()

    def on_qr(_c, data: bytes):
        state["qr_count"] += 1
        if phone:
            if state["qr_count"] == 1:
                threading.Thread(target=request_code, daemon=True).start()
            return
        os.system("clear")
        print("📲 Escanea este código con el teléfono cuya cuenta de WhatsApp está en el grupo:")
        print("   WhatsApp → Ajustes → Dispositivos vinculados → Vincular un dispositivo\n")
        segno.make_qr(data).terminal(compact=True)
        print(f"\n(El código se renueva solo; intento {state['qr_count']}. Ctrl+C para cancelar)", flush=True)

    client.event.qr(on_qr)

    @client.event(PairStatusEv)
    def _pair(_c, ev):
        if ev.Status == 2:  # SUCCESS
            print(f"\n✅ Vinculado con la cuenta +{ev.ID.User}", flush=True)
        else:
            state["error"] = ev.Error or "Error de vinculación"
        paired.set()

    @client.event(ConnectedEv)
    def _conn(_c, _ev):
        connected.set()

    threading.Thread(target=client.connect, daemon=True).start()
    try:
        if not paired.wait(timeout):
            print("\n⏱️  Tiempo agotado sin vincular.")
            return 1
        if state["error"]:
            print(f"\n❌ {state['error']}")
            return 1
        connected.wait(30)
        time.sleep(3)  # dejar que whatsmeow termine de guardar las llaves
        return 0 if session_exists() else 1
    except KeyboardInterrupt:
        print("\nCancelado.")
        return 1


# ----------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="TARDIS · servicio de grupos de WhatsApp")
    ap.add_argument("--vincular", action="store_true", help="Vincular la cuenta (desde la consola local)")
    ap.add_argument("--telefono", help="Vincular con código en lugar de QR (número con lada de país)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    for noisy in ("whatsmeow", "neonize"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.vincular:
        os._exit(pair(args.telefono))

    service = Service()
    start_control(service)
    log.info("Control local en %s", SOCKET_PATH)

    def _term(*_a):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _term)
    try:
        while not session_exists():
            service.state = "sin_vincular"
            service.state_detail = "Ejecuta en la consola local: tardis-whatsapp vincular"
            time.sleep(10)
        service.run_client()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            SOCKET_PATH.unlink()
        except OSError:
            pass
        os._exit(0)


if __name__ == "__main__":
    main()
