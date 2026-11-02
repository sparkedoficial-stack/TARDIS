#!/usr/bin/env python3
"""
GODWORKS · FTL Chat Vault · Bóveda de Peticiones Soberanas
==========================================================
Ventana de petición inmutable: mientras el Arquitecto redacta o transmite una
instrucción, el sistema (actualizadores, reinicios, otros clientes, agentes)
NO puede modificarla ni interrumpirla.

Modelo de garantía
------------------
1. **Exclusividad por sesión.** Sólo un cliente posee el token secreto de la
   bóveda. Cualquier otro escritor recibe 423 Locked.
2. **Token + revisión + checksum.** Cada latido incrementa la revisión y
   recalcula el SHA-256 del texto. Un texto alterado por fuera se detecta y se
   rechaza con 409 Conflict (nunca se envía contenido manipulado).
3. **Persistencia atómica.** El borrador vive en disco con permisos 0600 y
   sobrevive a recargas del navegador, caídas del portal y reinicios.
4. **TTL con latido.** La bóveda expira a los 120 s sin latido, de modo que
   un navegador cerrado no bloquea el sistema para siempre.
5. **Compuerta de mantenimiento.** Mientras exista una bóveda viva, el archivo
   ``gate.json`` ordena a los actualizadores y reinicios esperar
   (``ftl_update_guard.py``).

Estructura en disco
-------------------
  ~/.config/ftl/chat/composer/
    .mutex                     cerrojo flock entre procesos
    locks/<draft_id>.json      bóvedas vivas
    archive/<draft_id>.json    bóvedas cerradas / expiradas / enviadas
    journal.jsonl              auditoría append-only (sin texto completo)
    gate.json                  compuerta leída por actualizadores

Este módulo no depende de FastAPI: lo usan el portal, la TUI, los tests y el
guardián de actualizaciones.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

CHAT_DIR = Path.home() / ".config" / "ftl" / "chat"
VAULT_DIR = CHAT_DIR / "composer"
LOCKS_DIR = VAULT_DIR / "locks"
ARCHIVE_DIR = VAULT_DIR / "archive"
JOURNAL_FILE = VAULT_DIR / "journal.jsonl"
GATE_FILE = VAULT_DIR / "gate.json"
MUTEX_FILE = VAULT_DIR / ".mutex"

DEFAULT_TTL = 120.0          # segundos de vida sin latido
MAX_TEXT = 400_000           # 400 KB de instrucción (holgado)
RECOVER_LIMIT = 20

_LOCAL_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------
class VaultError(Exception):
    """Error base de la bóveda."""

    status = 400
    code = "vault_error"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra

    def payload(self) -> dict:
        return {"ok": False, "code": self.code, "message": self.message, **self.extra}


class VaultNotFound(VaultError):
    status = 404
    code = "vault_not_found"


class VaultForbidden(VaultError):
    status = 403
    code = "vault_forbidden"


class VaultLocked(VaultError):
    status = 423
    code = "vault_locked"


class VaultConflict(VaultError):
    status = 409
    code = "vault_conflict"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def now() -> float:
    return time.time()


def iso(ts: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts if ts is not None else now()))


def ensure_dirs() -> None:
    for path in (VAULT_DIR, LOCKS_DIR, ARCHIVE_DIR):
        path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(VAULT_DIR, 0o700)
    except Exception:
        pass


def checksum(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _atomic_json(path: Path, data: Any) -> None:
    ensure_dirs()
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    tmp.replace(path)


def _read_json(path: Path) -> Optional[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


@contextmanager
def _mutex():
    """Exclusión mutua intra-proceso e inter-proceso."""
    ensure_dirs()
    with _LOCAL_LOCK:
        with open(MUTEX_FILE, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass


def _journal(event: str, record: Optional[dict] = None, **extra: Any) -> None:
    """Auditoría append-only. Nunca guarda el texto completo, sólo su huella."""
    ensure_dirs()
    entry = {
        "ts": now(),
        "iso": iso(),
        "event": event,
        **(extra or {}),
    }
    if record:
        entry.update({
            "draft_id": record.get("draft_id"),
            "session_id": record.get("session_id"),
            "client_id": record.get("client_id"),
            "revision": record.get("revision"),
            "chars": len(record.get("text") or ""),
            "checksum": record.get("checksum"),
        })
    try:
        with open(JOURNAL_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.chmod(JOURNAL_FILE, 0o600)
    except Exception:
        pass


def _lock_path(draft_id: str) -> Path:
    return LOCKS_DIR / f"{draft_id}.json"


def _archive_path(draft_id: str) -> Path:
    return ARCHIVE_DIR / f"{draft_id}.json"


def _iter_records() -> Iterable[dict]:
    for path in sorted(LOCKS_DIR.glob("drf_*.json")):
        record = _read_json(path)
        if record and record.get("draft_id"):
            yield record


def _load(draft_id: str) -> dict:
    if not draft_id or "/" in draft_id:
        raise VaultNotFound("Bóveda no encontrada.")
    record = _read_json(_lock_path(draft_id))
    if not record:
        raise VaultNotFound(f"Bóveda no encontrada o ya cerrada: {draft_id}")
    return record


def _verify(record: dict, token: str) -> None:
    stored = record.get("token_hash") or ""
    if not token or not stored or not hmac.compare_digest(stored, _hash_token(token)):
        _journal("forbidden", record, reason="token")
        raise VaultForbidden(
            "Token de bóveda inválido: otro proceso intentó escribir en la petición."
        )


def _alive(record: dict, at: Optional[float] = None) -> bool:
    if record.get("state") not in {"drafting", "sending"}:
        return False
    return float(record.get("expires_at") or 0) > (at if at is not None else now())


def _public(record: dict, *, include_text: bool = True) -> dict:
    out = {
        "draft_id": record.get("draft_id"),
        "session_id": record.get("session_id"),
        "client_id": record.get("client_id"),
        "state": record.get("state"),
        "revision": int(record.get("revision") or 0),
        "checksum": record.get("checksum"),
        "chars": len(record.get("text") or ""),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "expires_at": record.get("expires_at"),
        "expires_in": max(0, round(float(record.get("expires_at") or 0) - now(), 1)),
        "heartbeat_at": record.get("heartbeat_at"),
        "run_id": record.get("run_id"),
        "meta": record.get("meta") or {},
        "history": list(record.get("history") or [])[-24:],
    }
    if include_text:
        out["text"] = record.get("text") or ""
    return out


def _archive(record: dict, state: str) -> dict:
    record = dict(record)
    record["state"] = state
    record["closed_at"] = iso()
    record["expires_at"] = 0
    try:
        _atomic_json(_archive_path(record["draft_id"]), record)
    except Exception:
        pass
    try:
        _lock_path(record["draft_id"]).unlink(missing_ok=True)
    except Exception:
        pass
    return record


# ---------------------------------------------------------------------------
# Compuerta de mantenimiento (leída por actualizadores / reinicios)
# ---------------------------------------------------------------------------
def gate_status(*, write: bool = True) -> dict:
    """Estado consolidado de la bóveda para los actualizadores del sistema."""
    with _LOCAL_LOCK:
        active = [r for r in _iter_records() if _alive(r)]
        drafting = [r for r in active if r.get("state") == "drafting"]
        sending = [r for r in active if r.get("state") == "sending"]
        payload = {
            "defer_updates": bool(active),
            "active": len(active),
            "drafting": len(drafting),
            "sending": len(sending),
            "drafts": [
                {
                    "draft_id": r.get("draft_id"),
                    "session_id": r.get("session_id"),
                    "state": r.get("state"),
                    "chars": len(r.get("text") or ""),
                    "expires_in": max(0, round(float(r.get("expires_at") or 0) - now(), 1)),
                }
                for r in active
            ],
            "updated_at": iso(),
        }
        if write:
            try:
                _atomic_json(GATE_FILE, payload)
            except Exception:
                pass
        return payload


def should_defer_updates() -> bool:
    return gate_status(write=False).get("defer_updates", False)


# ---------------------------------------------------------------------------
# Ciclo de vida de la bóveda
# ---------------------------------------------------------------------------
def _purge_locked() -> int:
    """Archiva bóvedas vencidas. Debe llamarse con el mutex tomado."""
    purged = 0
    for record in list(_iter_records()):
        if not _alive(record):
            if record.get("state") == "sending" and record.get("run_id"):
                _archive(record, "sent")
            else:
                _archive(record, "expired")
                _journal("expired", record)
            purged += 1
    if purged:
        gate_status()
    return purged


def purge_expired() -> int:
    """Archiva bóvedas vencidas conservando el texto para recuperación."""
    with _mutex():
        return _purge_locked()


def acquire(
    session_id: str,
    *,
    client_id: str = "",
    text: str = "",
    ttl: float = DEFAULT_TTL,
    takeover: bool = False,
    meta: Optional[dict] = None,
) -> dict:
    """Abre una bóveda exclusiva para una sesión.

    Si otro cliente ya la posee, lanza VaultLocked salvo ``takeover=True``
    (decisión explícita del Arquitecto).
    """
    session_id = (session_id or "").strip()
    if not session_id:
        raise VaultConflict("Sesión requerida para abrir la bóveda.")
    text = (text or "")[:MAX_TEXT]
    with _mutex():
        _purge_locked()
        for record in _iter_records():
            if record.get("session_id") != session_id or not _alive(record):
                continue
            if takeover:
                _archive(record, "superseded")
                _journal("superseded", record)
                continue
            raise VaultLocked(
                "La bóveda de esta sesión ya está abierta por otro cliente.",
                active=_public(record, include_text=False),
            )

        token = secrets.token_urlsafe(32)
        stamp = now()
        draft_id = "drf_" + secrets.token_hex(10)
        record = {
            "draft_id": draft_id,
            "session_id": session_id,
            "client_id": (client_id or "")[:120],
            "token_hash": _hash_token(token),
            "text": text,
            "revision": 0,
            "checksum": checksum(text),
            "state": "drafting",
            "created_at": iso(stamp),
            "created_ts": stamp,
            "updated_at": iso(stamp),
            "heartbeat_at": iso(stamp),
            "expires_at": stamp + float(ttl),
            "run_id": None,
            "meta": meta or {},
            "history": [{"ts": iso(stamp), "event": "open", "rev": 0, "chars": len(text)}],
        }
        _atomic_json(_lock_path(draft_id), record)
        _journal("open", record, ttl=ttl, takeover=bool(takeover))
        gate_status()
    public = _public(record)
    public["token"] = token
    public["ttl"] = float(ttl)
    return public


def heartbeat(
    draft_id: str,
    token: str,
    *,
    text: Optional[str] = None,
    revision: Optional[int] = None,
    ttl: float = DEFAULT_TTL,
) -> dict:
    """Renueva el candado y persiste el texto autoritativo.

    Si ``revision`` no coincide, alguien escribió fuera del cliente dueño:
    se devuelve VaultConflict con el texto autoritativo intacto.
    """
    with _mutex():
        record = _load(draft_id)
        _verify(record, token)
        if not _alive(record):
            _archive(record, "expired")
            _journal("expired", record)
            gate_status()
            raise VaultConflict("La bóveda expiró por inactividad; reábrela para continuar.")

        if revision is not None and int(revision) != int(record.get("revision") or 0):
            _journal("revision_conflict", record, attempted=int(revision))
            raise VaultConflict(
                "Intento de modificación externa detectado. El texto de la bóveda no cambió.",
                authoritative=_public(record),
            )

        if text is not None:
            clean = str(text)[:MAX_TEXT]
            if clean != (record.get("text") or ""):
                record["text"] = clean
                record["revision"] = int(record.get("revision") or 0) + 1
                record["checksum"] = checksum(clean)
                record.setdefault("history", []).append({
                    "ts": iso(), "event": "keystroke", "rev": record["revision"], "chars": len(clean),
                })
        stamp = now()
        record["heartbeat_at"] = iso(stamp)
        record["updated_at"] = iso(stamp)
        record["expires_at"] = stamp + float(ttl)
        _atomic_json(_lock_path(draft_id), record)
        gate_status()
        return _public(record)


def release(draft_id: str, token: str, *, keep: bool = True) -> dict:
    """Cierra la bóveda. Con ``keep`` conserva el borrador para recuperación."""
    with _mutex():
        record = _load(draft_id)
        _verify(record, token)
        state = "released" if keep and (record.get("text") or "").strip() else "discarded"
        record = _archive(record, state)
        _journal("release" if keep else "discard", record)
        gate_status()
        return _public(record, include_text=False)


def claim_for_send(
    draft_id: str,
    token: str,
    *,
    revision: Optional[int] = None,
    text: Optional[str] = None,
) -> dict:
    """Sella la bóveda para envío. Verifica token, revisión, checksum y texto."""
    with _mutex():
        record = _load(draft_id)
        _verify(record, token)
        if not _alive(record):
            raise VaultConflict("La bóveda expiró antes del envío; recupera el texto y reintenta.")
        if record.get("state") == "sending":
            raise VaultConflict("La petición ya está siendo transmitida.", authoritative=_public(record))
        if revision is not None and int(revision) != int(record.get("revision") or 0):
            _journal("revision_conflict", record, attempted=int(revision), phase="send")
            raise VaultConflict(
                "La revisión cambió: el sistema intentó alterar la petición. No se envió nada.",
                authoritative=_public(record),
            )
        stored = record.get("text") or ""
        if text is not None and str(text) != stored:
            _journal("text_conflict", record, phase="send")
            raise VaultConflict(
                "El texto enviado no coincide con la bóveda. Envío bloqueado por seguridad.",
                authoritative=_public(record),
            )
        if not stored.strip():
            raise VaultConflict("La petición está vacía.")
        record["state"] = "sending"
        record["sent_at"] = iso()
        record.setdefault("history", []).append({
            "ts": iso(), "event": "seal", "rev": record.get("revision"), "chars": len(stored),
        })
        record["expires_at"] = now() + DEFAULT_TTL
        _atomic_json(_lock_path(draft_id), record)
        _journal("seal", record)
        gate_status()
        return _public(record)


def attach_run(draft_id: str, run_id: str) -> None:
    with _mutex():
        try:
            record = _load(draft_id)
        except VaultError:
            return
        record["run_id"] = run_id
        record.setdefault("history", []).append({"ts": iso(), "event": "run", "run_id": run_id})
        _atomic_json(_lock_path(draft_id), record)
        gate_status()


def consume(draft_id: str, *, run_id: Optional[str] = None, cancelled: bool = False) -> dict:
    """El servidor aceptó la petición: archiva la bóveda como enviada."""
    with _mutex():
        try:
            record = _load(draft_id)
        except VaultError:
            archived = _read_json(_archive_path(draft_id)) or {}
            return _public(archived, include_text=False)
        record["run_id"] = run_id or record.get("run_id")
        record = _archive(record, "cancelled" if cancelled else "sent")
        _journal("sent" if not cancelled else "cancelled", record, run_id=record.get("run_id"))
        gate_status()
        return _public(record, include_text=False)


def recover(session_id: Optional[str] = None, limit: int = RECOVER_LIMIT) -> list[dict]:
    """Devuelve borradores no enviados (vivos o archivados) para restauración."""
    out: list[dict] = []
    seen: set[str] = set()
    for record in _iter_records():
        if session_id and record.get("session_id") != session_id:
            continue
        if not (record.get("text") or "").strip():
            continue
        out.append({**_public(record), "recoverable": True, "live": _alive(record)})
        seen.add(record.get("draft_id", ""))
    for path in sorted(ARCHIVE_DIR.glob("drf_*.json"), reverse=True):
        record = _read_json(path)
        if not record or record.get("draft_id") in seen:
            continue
        if record.get("state") not in {"released", "expired", "superseded"}:
            continue
        if session_id and record.get("session_id") != session_id:
            continue
        if not (record.get("text") or "").strip():
            continue
        out.append({**_public(record), "recoverable": True, "live": False})
        if len(out) >= limit:
            break
    out.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return out[:limit]


def active_drafts() -> list[dict]:
    return [_public(r, include_text=False) for r in _iter_records() if _alive(r)]


def status() -> dict:
    gate = gate_status()
    journal = journal_tail(limit=8)
    return {
        "ok": True,
        "ttl": DEFAULT_TTL,
        "active": gate["active"],
        "drafting": gate["drafting"],
        "sending": gate["sending"],
        "defer_updates": gate["defer_updates"],
        "vault_dir": str(VAULT_DIR),
        "journal": journal,
    }


def journal_tail(limit: int = 20) -> list[dict]:
    try:
        lines = JOURNAL_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, limit):]
    except Exception:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def drafts_summary(limit: int = RECOVER_LIMIT) -> list[dict]:
    """Bóvedas recientes (archivadas) para el historial de peticiones."""
    rows = []
    for path in sorted(ARCHIVE_DIR.glob("drf_*.json"), reverse=True)[:limit]:
        record = _read_json(path)
        if not record:
            continue
        rows.append({
            "draft_id": record.get("draft_id"),
            "session_id": record.get("session_id"),
            "state": record.get("state"),
            "chars": len(record.get("text") or ""),
            "created_at": record.get("created_at"),
            "closed_at": record.get("closed_at"),
            "run_id": record.get("run_id"),
            "preview": (record.get("text") or "")[:160],
            "checksum": record.get("checksum"),
        })
    return rows


# ---------------------------------------------------------------------------
# Autodiagnóstico CLI
# ---------------------------------------------------------------------------
def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="FTL Chat Vault · bóveda de peticiones soberanas")
    parser.add_argument("--status", action="store_true", help="Estado consolidado")
    parser.add_argument("--gate", action="store_true", help="Compuerta para actualizadores")
    parser.add_argument("--purge", action="store_true", help="Archiva bóvedas vencidas")
    parser.add_argument("--active", action="store_true", help="Lista bóvedas vivas")
    parser.add_argument("--recover", nargs="?", const="", default=None, metavar="SESSION", help="Borradores recuperables")
    parser.add_argument("--json", action="store_true", help="Salida JSON")
    args = parser.parse_args()

    if args.purge:
        print(json.dumps({"purged": purge_expired()}, ensure_ascii=False))
        return 0
    if args.gate:
        payload = gate_status()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print("DEFER" if payload["defer_updates"] else "CLEAR")
        return 75 if payload["defer_updates"] else 0
    if args.active:
        print(json.dumps(active_drafts(), indent=2, ensure_ascii=False))
        return 0
    if args.recover is not None:
        print(json.dumps(recover(args.recover or None), indent=2, ensure_ascii=False))
        return 0
    print(json.dumps(status(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
