"""
core/aegis/ledger.py — Cadena de custodia a prueba de manipulación.
====================================================================
Cada evento se serializa en JSON canónico y se encadena:

    prev_i     = BLAKE2b-256(registro_{i-1} serializado)
    mac_i      = HMAC-SHA256(clave_custodia, registro_i sin "mac")
    registro_i = {seq, ts, event, data, prev, mac}

La clave de custodia se deriva de la clave maestra con HKDF-SHA256
(dominio "aegis/ledger-key/v1"), por lo que un atacante sin la clave no
puede reescribir la historia. Un archivo ancla (`ledger.head`) guarda el
último seq + hash: detecta truncamiento aunque el atacante borre la cola.

El ledger es append-only y usa flock() para serializar escritores.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from cryptography.hazmat.primitives import hashes

from .crypto import KDF_INFO_LEDGER, Keyring, _atomic_write

GENESIS = "0" * 64


class LedgerError(RuntimeError):
    pass


def _canonical(obj: Dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hash_record(record: Dict[str, Any]) -> str:
    h = hashlib.blake2b(digest_size=32)
    h.update(_canonical(record))
    return h.hexdigest()


@dataclass
class LedgerState:
    ok: bool
    entries: int
    head: str = GENESIS
    broken_at: Optional[int] = None
    reason: str = ""
    anchor_ok: bool = True
    last_ts: float = 0.0


class IntegrityLedger:
    """Bitácora criptográfica de integridad y cadena de custodia."""

    def __init__(self, home: Path, keyring: Keyring) -> None:
        self.home = Path(home)
        self.keyring = keyring
        self.path = self.home / "ledger.jsonl"
        self.anchor_path = self.home / "ledger.head"
        self.home.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.home, 0o700)
        except OSError:
            pass
        salt = b"aegis-ledger-static-salt-v1"
        self._key = keyring.derive(salt, KDF_INFO_LEDGER)

    # -- lectura ------------------------------------------------------------

    def records(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise LedgerError(f"Registro ilegible en línea {len(out) + 1}") from exc
        return out

    def last(self) -> Optional[Dict[str, Any]]:
        recs = self.records()
        return recs[-1] if recs else None

    # -- escritura ----------------------------------------------------------

    def append(self, event: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = data or {}
        self.home.mkdir(parents=True, exist_ok=True)
        lock_path = self.home / "ledger.lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                recs = self.records()
                prev = _hash_record(recs[-1]) if recs else GENESIS
                seq = (recs[-1]["seq"] + 1) if recs else 1
                record: Dict[str, Any] = {
                    "seq": seq,
                    "ts": round(time.time(), 6),
                    "event": event,
                    "data": data,
                    "prev": prev,
                }
                record["mac"] = self._mac(record)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                head = _hash_record(record)
                anchor = {"seq": seq, "head": head, "updated": time.time(), "entries": seq}
                _atomic_write(self.anchor_path, json.dumps(anchor, indent=2).encode(), 0o400)
                return record
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _mac(self, record: Dict[str, Any]) -> str:
        payload = {k: v for k, v in record.items() if k != "mac"}
        return hmac.new(self._key, _canonical(payload), hashlib.sha256).hexdigest()

    # -- verificación -------------------------------------------------------

    def verify(self) -> LedgerState:
        try:
            recs = self.records()
        except LedgerError as exc:
            return LedgerState(False, 0, reason=str(exc), broken_at=0, anchor_ok=False)

        anchor: Dict[str, Any] = {}
        if self.anchor_path.exists():
            try:
                anchor = json.loads(self.anchor_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return LedgerState(False, len(recs), reason="Ancla corrupta", anchor_ok=False)

        prev = GENESIS
        for idx, rec in enumerate(recs, start=1):
            need = {"seq", "ts", "event", "data", "prev", "mac"}
            if not need.issubset(rec):
                return LedgerState(False, len(recs), broken_at=idx, reason="Registro incompleto")
            if rec["seq"] != idx:
                return LedgerState(False, len(recs), broken_at=idx, reason="Secuencia alterada")
            if rec["prev"] != prev:
                return LedgerState(False, len(recs), broken_at=idx, reason="Cadena rota")
            if not hmac.compare_digest(rec["mac"], self._mac(rec)):
                return LedgerState(False, len(recs), broken_at=idx, reason="MAC inválida")
            prev = _hash_record(rec)

        last_ts = recs[-1]["ts"] if recs else 0.0
        if anchor:
            if anchor.get("entries") != len(recs) or anchor.get("head") != prev:
                return LedgerState(
                    False,
                    len(recs),
                    head=prev,
                    broken_at=len(recs),
                    reason="Ancla no coincide: posible truncamiento o reescritura",
                    anchor_ok=False,
                    last_ts=last_ts,
                )
        elif recs:
            return LedgerState(
                False,
                len(recs),
                head=prev,
                reason="Falta ancla de integridad",
                anchor_ok=False,
                last_ts=last_ts,
            )

        return LedgerState(True, len(recs), head=prev, last_ts=last_ts)

    # -- utilidades ---------------------------------------------------------

    def events(self, name: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        recs = self.records()
        if name:
            recs = [r for r in recs if r.get("event") == name]
        return recs[-limit:]

    def merkle_root(self, values: Iterable[str]) -> str:
        """Raíz Merkle sobre hashes hexadecimales (hojas ordenadas)."""
        level = [bytes.fromhex(v) for v in sorted(values) if v]
        if not level:
            return GENESIS
        while len(level) > 1:
            if len(level) % 2:
                level.append(level[-1])
            level = [
                hashlib.blake2b(level[i] + level[i + 1], digest_size=32).digest()
                for i in range(0, len(level), 2)
            ]
        return level[0].hex()

    def export_chain(self, out_path: Path) -> Path:
        recs = self.records()
        payload = {
            "exported": time.time(),
            "entries": len(recs),
            "head": _hash_record(recs[-1]) if recs else GENESIS,
            "records": recs,
        }
        _atomic_write(Path(out_path), json.dumps(payload, indent=2).encode(), 0o400)
        return Path(out_path)
