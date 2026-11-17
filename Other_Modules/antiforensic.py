"""
core/aegis/antiforensic.py — Borrado seguro, zeroización y protocolo de pánico.
==============================================================================
Sobrescritura multi-pasada (aleatorio → ceros → aleatorio) con fsync,
truncado, renombrado opaco y desenlace. Diseñado para filesystems
tradicionales; en Btrfs/SSD el desgaste y el copy-on-write pueden conservar
copias, por lo que AEGIS documenta y combina:

  · Cifrado de disco completo LUKS2 (la defensa real en reposo).
  · Destrucción criptográfica: `cryptsetup luksErase` inutiliza la clave.
  · TRIM seguro (`blkdiscard`) para sanear celdas NAND.

El protocolo de pánico corta la exposición en segundos: bloquea la sesión,
vacía portapapeles, descarga agentes, borra temporales y, opcionalmente,
apaga el equipo.
"""
from __future__ import annotations

import os
import random
import secrets
import shutil
import string
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .classifier import Severity
from .policy import PolicyFinding

CHUNK = 1 << 20


class AntiforensicError(RuntimeError):
    pass


def _random_name(length: int = 18) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _overwrite(fd: int, size: int, mode: str, passes: int) -> None:
    for pass_no in range(passes):
        os.lseek(fd, 0, os.SEEK_SET)
        remaining = size
        if mode == "zero":
            block = b"\x00" * CHUNK
            while remaining > 0:
                n = min(CHUNK, remaining)
                os.write(fd, block[:n])
                remaining -= n
        else:
            while remaining > 0:
                n = min(CHUNK, remaining)
                os.write(fd, secrets.token_bytes(n))
                remaining -= n
        os.fsync(fd)


def shred_file(path: os.PathLike | str, *, passes: int = 3, remove: bool = True) -> Dict[str, object]:
    """Sobrescribe y elimina un archivo regular. No sigue enlaces simbólicos."""
    p = Path(path)
    info: Dict[str, object] = {"path": str(p), "ok": False, "passes": passes, "bytes": 0}
    if p.is_symlink():
        info["error"] = "enlace simbólico rechazado"
        return info
    if not p.exists() or not p.is_file():
        info["error"] = "no es un archivo regular"
        return info
    st = p.stat()
    if st.st_size == 0:
        if remove:
            p.unlink()
        info.update(ok=True, bytes=0)
        return info

    flags = os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(p, flags)
    except OSError as exc:
        info["error"] = f"apertura fallida: {exc.errno}"
        return info
    try:
        size = os.fstat(fd).st_size
        info["bytes"] = size
        # Patrón: aleatorio, ceros, aleatorio... terminando en aleatorio.
        for i in range(passes):
            pattern = "zero" if (passes >= 3 and i == 1) else "random"
            _overwrite(fd, size, pattern, 1)
        os.ftruncate(fd, 0)
        os.fsync(fd)
    except OSError as exc:
        info["error"] = f"sobrescritura fallida: {exc.errno}"
        return info
    finally:
        os.close(fd)

    if remove:
        try:
            # Renombrado opaco antes de desenlazar (difumina el nombre en journals).
            tmp = p.with_name(f".{_random_name()}")
            os.rename(p, tmp)
            os.unlink(tmp)
        except OSError as exc:
            info["error"] = f"desenlace fallido: {exc.errno}"
            return info
    info["ok"] = True
    info["warning"] = (
        "En Btrfs/SSD con CoW el bloque físico puede persistir; "
        "use LUKS2 + destrucción criptográfica para garantía absoluta."
    )
    return info


def shred_path(path: os.PathLike | str, *, passes: int = 3) -> Dict[str, object]:
    p = Path(path)
    if p.is_dir() and not p.is_symlink():
        removed = 0
        errors: List[str] = []
        for base, dirs, files in os.walk(p, topdown=False, followlinks=False):
            for name in files:
                res = shred_file(Path(base) / name, passes=passes)
                if res.get("ok"):
                    removed += 1
                else:
                    errors.append(f"{res.get('path')}: {res.get('error')}")
            for name in dirs:
                try:
                    (Path(base) / name).rmdir()
                except OSError:
                    pass
        try:
            p.rmdir()
        except OSError:
            pass
        return {"path": str(p), "ok": not errors, "files_removed": removed, "errors": errors}
    return shred_file(p, passes=passes)


def zeroize(buf: bytearray) -> None:
    """Borra material sensible en memoria (mejor esfuerzo en CPython)."""
    for i in range(len(buf)):
        buf[i] = 0


def generate_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{};:,.?"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class PanicProtocol:
    """Protocolo de emergencia: reduce la ventana de exposición a segundos."""

    def __init__(self, home: Path, ledger=None) -> None:
        self.home = Path(home)
        self.ledger = ledger

    def _run(self, cmd: List[str], timeout: int = 8) -> bool:
        try:
            return subprocess.run(
                cmd, capture_output=True, timeout=timeout, check=False
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def execute(
        self,
        *,
        reason: str = "protocolo de pánico",
        poweroff: bool = False,
        offline: bool = False,
    ) -> Dict[str, object]:
        actions: List[str] = []
        failed: List[str] = []

        # 1) Bloqueo inmediato de sesiones.
        if self._run(["loginctl", "lock-sessions"]):
            actions.append("sesiones bloqueadas")
        else:
            failed.append("loginctl lock-sessions")

        # 2) Portapapeles.
        if shutil.which("wl-copy"):
            if self._run(["wl-copy", "--clear"]):
                actions.append("portapapeles Wayland vaciado")
        if shutil.which("xclip"):
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=b"",
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                actions.append("portapapeles X11 vaciado")
            except (OSError, subprocess.SubprocessError):
                failed.append("xclip")

        # 3) Agentes criptográficos.
        if shutil.which("ssh-add") and self._run(["ssh-add", "-D"]):
            actions.append("agente SSH descargado")
        if shutil.which("gpgconf") and self._run(["gpgconf", "--kill", "gpg-agent"]):
            actions.append("gpg-agent terminado")

        # 4) Temporales de la bóveda.
        tmp = self.home / "tmp"
        if tmp.is_dir():
            res = shred_path(tmp)
            (actions if res.get("ok") else failed).append("temporales AEGIS destruidos")

        # 5) Registro inmutable del evento.
        if self.ledger is not None:
            try:
                self.ledger.append(
                    "panic",
                    {"reason": reason, "actions": actions, "offline": offline, "poweroff": poweroff},
                )
                actions.append("evento sellado en ledger")
            except Exception:
                failed.append("ledger")

        # 6) Aislamiento de red (explícito).
        if offline and shutil.which("nmcli"):
            if self._run(["nmcli", "networking", "off"]):
                actions.append("red desactivada")
            else:
                failed.append("nmcli networking off")

        # 7) Apagado (explícito).
        if poweroff:
            actions.append("apagado solicitado")
            try:
                subprocess.Popen(
                    ["systemctl", "poweroff"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError:
                failed.append("poweroff")

        return {"ok": not failed, "actions": actions, "failed": failed, "ts": time.time()}


def forensic_findings(paths: Iterable[Path]) -> List[PolicyFinding]:
    """Detecta archivos que deberían estar cifrados o destruidos."""
    findings: List[PolicyFinding] = []
    for p in paths:
        if not p.exists():
            continue
        if p.suffix.lower() in {".aegis", ".enc"}:
            continue
        if any(tag in p.name.lower() for tag in ("secret", "token", "credential", ".env")):
            findings.append(
                PolicyFinding(
                    "PLAINTEXT_CRITICO",
                    Severity.HIGH,
                    "Secreto almacenado en claro",
                    str(p),
                    "material sensible fuera de contenedor cifrado",
                    f"aegis seal {p} --shred-source",
                )
            )
    return findings
