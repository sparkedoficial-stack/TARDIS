"""
core/aegis/crypto.py — Núcleo criptográfico de AEGIS-Ω.
======================================================
Cifrado autenticado en flujo (streaming) con:

  · AES-256-GCM por bloques de 1 MiB, nonce de 96 bits = contador de 64 bits
    + separador de dominio de 32 bits.
  · Clave por archivo derivada con HKDF-SHA256 a partir de la clave maestra,
    un salt aleatorio de 128 bits y un identificador de archivo de 128 bits.
  · AAD que liga cabecera + índice de bloque + marca de bloque final:
    impide truncado, reordenamiento, sustitución de cabecera y splicing.
  · Cabecera binaria de 50 bytes con MAGIC "AGS1", versión, cifrado,
    tamaño de bloque, salt, file_id y tamaño original.

Custodia de claves:

  ~/.aegis/keys/master.key        32 bytes, modo 0400, lectura O_NOFOLLOW.
  ~/.aegis/keys/master.pass.enc   envoltura Argon2id + AES-256-GCM (portable).
  ~/.aegis/keys/recovery.enc     envoltura con código de recuperación.

Ningún secreto se registra en logs: los errores sólo exponen rutas y códigos.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Dict, Iterable, Iterator, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"AGS1"
VERSION = 1
CIPHER_AES256_GCM = 1
CHUNK_SIZE = 1 << 20  # 1 MiB

#: 4s magia · B versión · B cifrado · I tamaño bloque · 16s salt · 16s file_id · Q tamaño
HEADER = struct.Struct(">4sBBI16s16sQ")
HEADER_SIZE = HEADER.size  # 50

NONCE_DOMAIN = b"\x00\x00\x00\x01"  # separador de dominio (32 bits)
KDF_INFO_FILE = b"aegis/file-key/v1"
KDF_INFO_LEDGER = b"aegis/ledger-key/v1"
KDF_INFO_MANIFEST = b"aegis/manifest-key/v1"
KDF_INFO_WRAP = b"aegis/master-wrap/v1"

ARGON2_ITERATIONS = 3
ARGON2_LANES = 4
ARGON2_MEMORY_KIB = 262_144  # 256 MiB — coste deliberado para atacante

MASTER_KEY_BYTES = 32


class AegisCryptoError(RuntimeError):
    """Error criptográfico controlado (nunca contiene material secreto)."""


# ---------------------------------------------------------------------------
# Utilidades de bajo nivel
# ---------------------------------------------------------------------------


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def _hkdf(master: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(master)


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Escritura atómica con permisos restrictivos y fsync de archivo y directorio."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=".aegis-", dir=str(path.parent))
    tmp_path = Path(tmp)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        os.chmod(path, mode)
        try:
            dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            return
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _read_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        chunks = []
        while True:
            block = os.read(fd, 65536)
            if not block:
                break
            chunks.append(block)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _nonce(counter: int) -> bytes:
    return counter.to_bytes(8, "big") + NONCE_DOMAIN


def _aad(header: bytes, counter: int, final: bool) -> bytes:
    return header + counter.to_bytes(8, "big") + (b"\x01" if final else b"\x00")


# ---------------------------------------------------------------------------
# Custodia de claves
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeyInfo:
    fingerprint: str
    created: float
    path: str
    mode: int


class Keyring:
    """Custodia de la clave maestra y sus envolturas (passphrase / recuperación)."""

    def __init__(self, home: Optional[Path] = None) -> None:
        root = home or Path(os.environ.get("AEGIS_HOME", str(Path.home() / ".aegis")))
        self.home = Path(root).expanduser().resolve()
        self.key_dir = self.home / "keys"
        self.master_path = self.key_dir / "master.key"
        self.meta_path = self.key_dir / "master.meta.json"
        self.pass_path = self.key_dir / "master.pass.enc"
        self.recovery_path = self.key_dir / "recovery.enc"

    # -- creación / carga ---------------------------------------------------

    def ensure(self) -> bytes:
        """Garantiza la existencia de la clave maestra con permisos correctos."""
        self.key_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.home, 0o700)
            os.chmod(self.key_dir, 0o700)
        except OSError:
            pass

        if not self.master_path.exists():
            master = secrets.token_bytes(MASTER_KEY_BYTES)
            try:
                # O_EXCL evita carreras entre procesos.
                fd = os.open(self.master_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
                try:
                    os.write(fd, master)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                meta = {
                    "version": VERSION,
                    "created": time.time(),
                    "fingerprint": fingerprint(master),
                    "algorithm": "AES-256-GCM / HKDF-SHA256",
                    "custody": "0400",
                }
                _atomic_write(self.meta_path, json.dumps(meta, indent=2).encode(), 0o400)
                return master
            except FileExistsError:
                pass  # otro proceso la creó; se carga abajo

        info = self._enforce_permissions()
        if info.mode & 0o077:
            raise AegisCryptoError(
                f"Clave maestra con permisos inseguros ({oct(info.mode)}): {self.master_path}"
            )
        master = _read_nofollow(self.master_path)
        if len(master) != MASTER_KEY_BYTES:
            raise AegisCryptoError("Clave maestra corrupta: longitud inválida")
        return master

    def _enforce_permissions(self) -> KeyInfo:
        st = self.master_path.stat()
        mode = st.st_mode & 0o777
        if mode & 0o077:
            try:
                os.chmod(self.master_path, 0o400)
                mode = 0o400
            except OSError:
                pass
        master = _read_nofollow(self.master_path)
        return KeyInfo(fingerprint(master), st.st_ctime, str(self.master_path), mode)

    def load(self) -> bytes:
        return self.ensure()

    def info(self) -> KeyInfo:
        master = self.ensure()
        st = self.master_path.stat()
        return KeyInfo(fingerprint(master), st.st_ctime, str(self.master_path), st.st_mode & 0o777)

    def fingerprint(self) -> str:
        return fingerprint(self.ensure())

    def derive(self, salt: bytes, info: bytes, length: int = 32) -> bytes:
        return _hkdf(self.load(), salt, info, length)

    # -- envoltura con passphrase ------------------------------------------

    def wrap_with_passphrase(self, passphrase: str) -> Dict[str, object]:
        if len(passphrase) < 12:
            raise AegisCryptoError("La passphrase debe tener al menos 12 caracteres")
        master = self.ensure()
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        kek = Argon2id(
            salt=salt,
            length=32,
            iterations=ARGON2_ITERATIONS,
            lanes=ARGON2_LANES,
            memory_cost=ARGON2_MEMORY_KIB,
        ).derive(passphrase.encode("utf-8"))
        fp = fingerprint(master).encode("ascii")
        ct = AESGCM(kek).encrypt(nonce, master, KDF_INFO_WRAP + fp)
        blob = {
            "v": VERSION,
            "kdf": "argon2id",
            "salt": _b64e(salt),
            "iterations": ARGON2_ITERATIONS,
            "lanes": ARGON2_LANES,
            "memory_kib": ARGON2_MEMORY_KIB,
            "nonce": _b64e(nonce),
            "ct": _b64e(ct),
            "fingerprint": fingerprint(master),
            "created": time.time(),
        }
        _atomic_write(self.pass_path, json.dumps(blob, indent=2).encode(), 0o400)
        return blob

    def unwrap_with_passphrase(self, passphrase: str) -> bytes:
        if not self.pass_path.exists():
            raise AegisCryptoError("No existe envoltura con passphrase")
        blob = json.loads(self.pass_path.read_text(encoding="utf-8"))
        salt = _b64d(blob["salt"])
        nonce = _b64d(blob["nonce"])
        ct = _b64d(blob["ct"])
        kek = Argon2id(
            salt=salt,
            length=32,
            iterations=int(blob.get("iterations", ARGON2_ITERATIONS)),
            lanes=int(blob.get("lanes", ARGON2_LANES)),
            memory_cost=int(blob.get("memory_kib", ARGON2_MEMORY_KIB)),
        ).derive(passphrase.encode("utf-8"))
        try:
            master = AESGCM(kek).decrypt(nonce, ct, KDF_INFO_WRAP + str(blob["fingerprint"]).encode())
        except InvalidTag as exc:
            raise AegisCryptoError("Passphrase incorrecta o envoltura manipulada") from exc
        if len(master) != MASTER_KEY_BYTES:
            raise AegisCryptoError("Envoltura corrupta")
        return master

    # -- kit de recuperación ------------------------------------------------

    def create_recovery_kit(self, out_path: Optional[Path] = None) -> Tuple[Path, str]:
        """Genera un kit de recuperación de un solo uso.

        El código de recuperación sólo se retorna en memoria para que el
        operador lo imprima/guarde fuera de la máquina. No se registra.
        """
        master = self.ensure()
        code = base64.b32encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        kek = Argon2id(
            salt=salt, length=32, iterations=2, lanes=4, memory_cost=131_072
        ).derive(code.encode("ascii"))
        fp = fingerprint(master)
        ct = AESGCM(kek).encrypt(nonce, master, KDF_INFO_WRAP + fp.encode())
        blob = {
            "v": VERSION,
            "type": "recovery",
            "kdf": "argon2id",
            "salt": _b64e(salt),
            "iterations": 2,
            "lanes": 4,
            "memory_kib": 131_072,
            "nonce": _b64e(nonce),
            "ct": _b64e(ct),
            "fingerprint": fp,
            "created": time.time(),
        }
        target = out_path or self.recovery_path
        _atomic_write(target, json.dumps(blob, indent=2).encode(), 0o400)
        grouped = "-".join(code[i : i + 8] for i in range(0, len(code), 8))
        return target, grouped

    def unwrap_recovery_code(self, code: str, kit_path: Optional[Path] = None) -> bytes:
        path = kit_path or self.recovery_path
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
        normal = "".join(ch for ch in code.upper() if ch.isalnum())
        kek = Argon2id(
            salt=_b64d(blob["salt"]),
            length=32,
            iterations=int(blob.get("iterations", 2)),
            lanes=int(blob.get("lanes", 4)),
            memory_cost=int(blob.get("memory_kib", 131_072)),
        ).derive(normal.encode("ascii"))
        try:
            master = AESGCM(kek).decrypt(
                _b64d(blob["nonce"]), _b64d(blob["ct"]), KDF_INFO_WRAP + str(blob["fingerprint"]).encode()
            )
        except InvalidTag as exc:
            raise AegisCryptoError("Código de recuperación inválido") from exc
        return master


def fingerprint(master: bytes) -> str:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(b"AEGIS-FP-v1")
    digest.update(master)
    return digest.finalize().hex()[:32].upper()


# ---------------------------------------------------------------------------
# Cifrado de archivos
# ---------------------------------------------------------------------------


@dataclass
class EnvelopeMeta:
    file_id: str
    salt: str
    plaintext_sha256: str
    ciphertext_sha256: str
    size: int
    ciphertext_size: int


def _iter_plaintext(fh: BinaryIO, chunk_size: int) -> Iterator[bytes]:
    while True:
        block = fh.read(chunk_size)
        if not block:
            return
        yield block


def encrypt_stream(
    src_fh: BinaryIO,
    dst_fh: BinaryIO,
    master: bytes,
    size: int,
    chunk_size: int = CHUNK_SIZE,
) -> EnvelopeMeta:
    """Cifra un flujo completo y devuelve metadatos de integridad."""
    if size < 0:
        raise AegisCryptoError("Tamaño negativo")
    salt = secrets.token_bytes(16)
    file_id = secrets.token_bytes(16)
    header = HEADER.pack(MAGIC, VERSION, CIPHER_AES256_GCM, chunk_size, salt, file_id, size)
    file_key = _hkdf(master, salt, KDF_INFO_FILE)
    aead = AESGCM(file_key)

    dst_fh.write(header)
    plain_hash = hashes.Hash(hashes.SHA256())
    cipher_hash = hashes.Hash(hashes.SHA256())
    cipher_hash.update(header)

    remaining = size
    counter = 0
    while remaining > 0 or counter == 0:
        want = min(chunk_size, remaining)
        block = src_fh.read(want)
        if len(block) != want:
            raise AegisCryptoError("Lectura incompleta del origen")
        remaining -= want
        final = remaining == 0
        plain_hash.update(block)
        ct = aead.encrypt(_nonce(counter), block, _aad(header, counter, final))
        dst_fh.write(ct)
        cipher_hash.update(ct)
        counter += 1
        if final:
            break

    dst_fh.flush()
    return EnvelopeMeta(
        file_id=file_id.hex(),
        salt=salt.hex(),
        plaintext_sha256=plain_hash.finalize().hex(),
        ciphertext_sha256=cipher_hash.finalize().hex(),
        size=size,
        ciphertext_size=HEADER_SIZE + size + 16 * counter,
    )


def decrypt_stream(src_fh: BinaryIO, dst_fh: BinaryIO, master: bytes) -> EnvelopeMeta:
    """Descifra un contenedor .aegis validando cabecera, orden y truncado."""
    header = src_fh.read(HEADER_SIZE)
    if len(header) != HEADER_SIZE:
        raise AegisCryptoError("Contenedor truncado: cabecera incompleta")
    magic, version, cipher, chunk_size, salt, file_id, size = HEADER.unpack(header)
    if magic != MAGIC:
        raise AegisCryptoError("Firma de contenedor inválida")
    if version != VERSION:
        raise AegisCryptoError(f"Versión de contenedor no soportada: {version}")
    if cipher != CIPHER_AES256_GCM:
        raise AegisCryptoError("Cifrado no soportado")
    if not (4096 <= chunk_size <= (64 << 20)):
        raise AegisCryptoError("Tamaño de bloque fuera de rango")
    if size > (1 << 50):
        raise AegisCryptoError("Tamaño declarado fuera de rango")

    file_key = _hkdf(master, salt, KDF_INFO_FILE)
    aead = AESGCM(file_key)
    plain_hash = hashes.Hash(hashes.SHA256())
    cipher_hash = hashes.Hash(hashes.SHA256())
    cipher_hash.update(header)

    remaining = size
    counter = 0
    while remaining > 0 or counter == 0:
        want = min(chunk_size, remaining)
        final = want == remaining
        blob = src_fh.read(want + 16)
        if len(blob) != want + 16:
            raise AegisCryptoError("Contenedor truncado: bloque incompleto")
        cipher_hash.update(blob)
        try:
            block = aead.decrypt(_nonce(counter), blob, _aad(header, counter, final))
        except InvalidTag as exc:
            raise AegisCryptoError("Autenticación fallida: datos alterados o clave incorrecta") from exc
        if len(block) != want:
            raise AegisCryptoError("Bloque con longitud inconsistente")
        dst_fh.write(block)
        plain_hash.update(block)
        remaining -= want
        counter += 1
        if final:
            break

    extra = src_fh.read(1)
    if extra:
        raise AegisCryptoError("Datos residuales tras el bloque final (posible inyección)")

    dst_fh.flush()
    return EnvelopeMeta(
        file_id=file_id.hex(),
        salt=salt.hex(),
        plaintext_sha256=plain_hash.finalize().hex(),
        ciphertext_sha256=cipher_hash.finalize().hex(),
        size=size,
        ciphertext_size=HEADER_SIZE + size + 16 * counter,
    )


def encrypt_file(
    src: Path,
    dst: Path,
    keyring: Keyring,
    *,
    remove_source: bool = False,
    chunk_size: int = CHUNK_SIZE,
) -> EnvelopeMeta:
    src = Path(src)
    dst = Path(dst)
    if not src.is_file():
        raise AegisCryptoError(f"Origen inexistente: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".aegis-enc-", dir=str(dst.parent))
    tmp_path = Path(tmp)
    try:
        os.fchmod(fd, 0o600)
        with open(src, "rb") as sfh, os.fdopen(fd, "wb") as dfh:
            meta = encrypt_stream(sfh, dfh, keyring.load(), src.stat().st_size, chunk_size)
            dfh.flush()
            os.fsync(dfh.fileno())
        os.replace(tmp_path, dst)
        os.chmod(dst, 0o600)
        if remove_source:
            from .antiforensic import shred_file

            shred_file(src)
        return meta
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def decrypt_file(
    src: Path,
    dst: Path,
    keyring: Keyring,
) -> EnvelopeMeta:
    src = Path(src)
    dst = Path(dst)
    if not src.is_file():
        raise AegisCryptoError(f"Contenedor inexistente: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".aegis-dec-", dir=str(dst.parent))
    tmp_path = Path(tmp)
    try:
        os.fchmod(fd, 0o600)
        with open(src, "rb") as sfh, os.fdopen(fd, "wb") as dfh:
            meta = decrypt_stream(sfh, dfh, keyring.load())
            dfh.flush()
            os.fsync(dfh.fileno())
        os.replace(tmp_path, dst)
        os.chmod(dst, 0o600)
        return meta
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def encrypt_bytes(payload: bytes, keyring: Keyring) -> bytes:
    import io

    out = io.BytesIO()
    encrypt_stream(io.BytesIO(payload), out, keyring.load(), len(payload))
    return out.getvalue()


def decrypt_bytes(blob: bytes, keyring: Keyring) -> bytes:
    import io

    out = io.BytesIO()
    decrypt_stream(io.BytesIO(blob), out, keyring.load())
    return out.getvalue()
