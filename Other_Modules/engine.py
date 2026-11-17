"""
core/aegis/engine.py — Orquestador soberano de AEGIS-Ω.
======================================================
Une criptografía, custodia, clasificación, auditoría de política,
endurecimiento, antiforense y vigilancia en un único motor operable.

Rutas por defecto:
    ~/.aegis/                     perímetro de custodia (0700)
    ~/.aegis/keys/master.key      clave maestra (0400)
    ~/.aegis/ledger.jsonl         cadena de custodia
    ~/.aegis/manifests/           metadatos de sellado
    ~/.aegis/vault/               bóveda cifrada de objetos
    <repo>/reports/aegis/         informes (JSON + HTML)

Sobrescribible con AEGIS_HOME / AEGIS_PROJECT_ROOT.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .antiforensic import PanicProtocol, shred_file, shred_path
from .classifier import (
    LEVELS,
    Level,
    Severity,
    classify_path,
    scan_file,
    scan_text,
    should_skip,
)
from .crypto import (
    CHUNK_SIZE,
    MAGIC,
    Keyring,
    decrypt_file,
    encrypt_bytes,
    decrypt_bytes,
    encrypt_file,
)
from .hardening import SystemHardening
from .ledger import IntegrityLedger
from .policy import AuditResult, PolicyAuditor, PolicyFinding, remediate

AEGIS_VERSION = "1.0.0"
_CODENAME = "AEGIS-Ω"


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


@dataclass
class SealRecord:
    path: str
    container: str
    level: str
    size: int
    plaintext_sha256: str
    ciphertext_sha256: str
    file_id: str
    ts: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "container": self.container,
            "level": self.level,
            "size": self.size,
            "plaintext_sha256": self.plaintext_sha256,
            "ciphertext_sha256": self.ciphertext_sha256,
            "file_id": self.file_id,
            "ts": self.ts,
        }


class AegisEngine:
    def __init__(
        self,
        *,
        home: Optional[Path] = None,
        project_root: Optional[Path] = None,
    ) -> None:
        self.home = Path(home or _env_path("AEGIS_HOME", Path.home() / ".aegis")).expanduser().resolve()
        self.project_root = Path(
            project_root or _env_path("AEGIS_PROJECT_ROOT", Path(__file__).resolve().parents[2])
        ).expanduser().resolve()
        self.manifest_path = self.home / "manifests" / "sealed.jsonl"
        self.vault_dir = self.home / "vault"
        self.alerts_path = self.home / "alerts.jsonl"
        self.state_path = self.home / "state.json"
        self.report_dir = self.project_root / "reports" / "aegis"

        self.home.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.home, 0o700)
        except OSError:
            pass
        self.keyring = Keyring(self.home)
        self.ledger = IntegrityLedger(self.home, self.keyring)
        self.hardening = SystemHardening(home=Path.home())

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        ledger = self.ledger.verify()
        key_info = self.keyring.info()
        sealed = self._manifest_records()
        last_audit = self._read_state().get("last_audit", {})
        vault_objects = list((self.vault_dir / "objects").glob("*.aegis")) if self.vault_dir.exists() else []
        return {
            "version": AEGIS_VERSION,
            "codename": _CODENAME,
            "home": str(self.home),
            "project_root": str(self.project_root),
            "key": {
                "fingerprint": key_info.fingerprint,
                "mode": oct(key_info.mode),
                "path": key_info.path,
                "passphrase_wrapped": self.keyring.pass_path.exists(),
                "recovery_kit": self.keyring.recovery_path.exists(),
            },
            "ledger": {
                "ok": ledger.ok,
                "entries": ledger.entries,
                "head": ledger.head,
                "broken_at": ledger.broken_at,
                "reason": ledger.reason,
                "anchor_ok": ledger.anchor_ok,
                "last_ts": ledger.last_ts,
            },
            "sealed_files": len(sealed),
            "sealed_bytes": sum(int(r.get("size", 0)) for r in sealed),
            "vault_objects": len(vault_objects),
            "last_audit": last_audit,
            "classification": LEVELS,
        }

    # ------------------------------------------------------------------
    # Auditoría
    # ------------------------------------------------------------------

    def audit(
        self,
        *,
        root: Optional[Path] = None,
        deep: bool = True,
        fix: bool = False,
        fix_git: bool = False,
    ) -> Dict[str, Any]:
        auditor = PolicyAuditor(Path(root or self.project_root), home=Path.home())
        result = auditor.audit(deep=deep, remediation=fix, fix_git=fix_git)
        if fix:
            remediate(result)
        hard = self.hardening.audit()

        findings = result.findings + hard.findings
        counts = {"crítico": 0, "alto": 0, "medio": 0, "bajo": 0, "info": 0}
        for f in findings:
            if f.fixed:
                continue
            counts[f.severity.label] += 1
        penalty = (
            counts["crítico"] * 25
            + counts["alto"] * 10
            + counts["medio"] * 3
            + counts["bajo"] * 0.5
        )
        score = max(0, int(round(100 - min(100, penalty))))
        if counts["crítico"]:
            score = min(score, 45)
        elif counts["alto"]:
            score = min(score, 75)

        payload = {
            "generated": time.time(),
            "version": AEGIS_VERSION,
            "root": str(result.root),
            "score": score,
            "counts": counts,
            "policy": result.as_dict(),
            "hardening": hard.as_dict(),
            "key_fingerprint": self.keyring.fingerprint(),
            "ledger": self.ledger.verify().__dict__,
        }
        self._write_state(
            {
                "last_audit": {
                    "ts": payload["generated"],
                    "score": score,
                    "counts": counts,
                    "root": str(result.root),
                }
            }
        )
        self.ledger.append(
            "audit",
            {"score": score, "counts": counts, "root": str(result.root), "findings": len(findings)},
        )
        self.report_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.report_dir / "aegis_status.json"
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.chmod(json_path, 0o600)

        from .report import render_html

        html_path = self.report_dir / "aegis_report.html"
        html_path.write_text(render_html(payload), encoding="utf-8")
        os.chmod(html_path, 0o600)

        payload["report_json"] = str(json_path)
        payload["report_html"] = str(html_path)
        return payload

    # ------------------------------------------------------------------
    # Sellado / descifrado
    # ------------------------------------------------------------------

    def seal(
        self,
        paths: Sequence[Path | str],
        *,
        in_place: bool = True,
        shred_source: bool = False,
        force: bool = False,
    ) -> Dict[str, Any]:
        records: List[SealRecord] = []
        errors: List[str] = []
        targets: List[Path] = []
        for raw in paths:
            p = Path(raw).expanduser()
            if p.is_dir():
                for base, dirs, files in os.walk(p, followlinks=False):
                    dirs[:] = [d for d in dirs if not should_skip(Path(base) / d) and d != ".git"]
                    targets.extend(Path(base) / f for f in files)
            elif p.is_file():
                targets.append(p)
            else:
                errors.append(f"inexistente: {p}")

        for src in targets:
            if src.suffix == ".aegis" or src.name.endswith(".aegis"):
                continue
            dst = src.with_name(src.name + ".aegis")
            if dst.exists() and not force:
                errors.append(f"contenedor ya existe: {dst}")
                continue
            cls = classify_path(src)
            try:
                meta = encrypt_file(
                    src, dst, self.keyring, remove_source=shred_source, chunk_size=CHUNK_SIZE
                )
            except Exception as exc:  # ruta y tipo, sin material
                errors.append(f"{src}: {type(exc).__name__}")
                continue
            rec = SealRecord(
                path=str(src),
                container=str(dst),
                level=cls.code,
                size=meta.size,
                plaintext_sha256=meta.plaintext_sha256,
                ciphertext_sha256=meta.ciphertext_sha256,
                file_id=meta.file_id,
                ts=time.time(),
            )
            records.append(rec)
            self._append_manifest(rec)
            self.ledger.append(
                "seal",
                {
                    "path": rec.path,
                    "container": rec.container,
                    "level": rec.level,
                    "size": rec.size,
                    "file_id": rec.file_id,
                    "plaintext_sha256": rec.plaintext_sha256,
                    "ciphertext_sha256": rec.ciphertext_sha256,
                },
            )
        if in_place and shred_source:
            pass  # encrypt_file ya destruyó el origen
        return {
            "ok": not errors,
            "sealed": [r.as_dict() for r in records],
            "errors": errors,
        }

    def unseal(
        self,
        container: Path | str,
        *,
        output: Optional[Path | str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        src = Path(container).expanduser()
        if not src.is_file():
            return {"ok": False, "error": "contenedor inexistente"}
        if output:
            dst = Path(output).expanduser()
        else:
            name = src.name[:-6] if src.name.endswith(".aegis") else src.stem
            dst = src.with_name(name + ".restored")
        if dst.exists() and not overwrite:
            return {"ok": False, "error": f"destino existente: {dst}"}
        try:
            meta = decrypt_file(src, dst, self.keyring)
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}
        self.ledger.append(
            "unseal",
            {
                "container": str(src),
                "output": str(dst),
                "plaintext_sha256": meta.plaintext_sha256,
                "size": meta.size,
            },
        )
        return {"ok": True, "output": str(dst), "meta": meta.__dict__}

    # ------------------------------------------------------------------
    # Verificación de integridad
    # ------------------------------------------------------------------

    def verify(self, *, deep: bool = False) -> Dict[str, Any]:
        ledger = self.ledger.verify()
        records = self._manifest_records()
        tampered: List[Dict[str, Any]] = []
        missing: List[str] = []
        checked = 0
        for rec in records:
            container = Path(rec.get("container", ""))
            if not container.is_file():
                missing.append(str(container))
                continue
            checked += 1
            try:
                with open(container, "rb") as fh:
                    if fh.read(4) != MAGIC:
                        tampered.append({"container": str(container), "reason": "firma inválida"})
                        continue
                    fh.seek(0)
                    digest = hashlib.sha256()
                    while True:
                        block = fh.read(1 << 20)
                        if not block:
                            break
                        digest.update(block)
                if digest.hexdigest() != rec.get("ciphertext_sha256"):
                    tampered.append({"container": str(container), "reason": "hash de cifrado alterado"})
                    continue
                if deep:
                    import tempfile

                    with tempfile.NamedTemporaryFile(delete=True) as tmp:
                        meta = decrypt_file(container, Path(tmp.name), self.keyring)
                        if meta.plaintext_sha256 != rec.get("plaintext_sha256"):
                            tampered.append({"container": str(container), "reason": "contenido no coincide"})
            except Exception as exc:
                tampered.append({"container": str(container), "reason": type(exc).__name__})
        ok = ledger.ok and not tampered and not missing
        return {
            "ok": ok,
            "ledger": ledger.__dict__,
            "manifests": len(records),
            "checked": checked,
            "tampered": tampered,
            "missing": missing,
            "ts": time.time(),
        }

    # ------------------------------------------------------------------
    # Bóveda cifrada de objetos
    # ------------------------------------------------------------------

    def _vault_index(self) -> Dict[str, Any]:
        index_file = self.vault_dir / "index.aegis"
        if not index_file.exists():
            return {}
        try:
            return json.loads(decrypt_bytes(index_file.read_bytes(), self.keyring).decode("utf-8"))
        except Exception:
            return {}

    def _save_vault_index(self, index: Dict[str, Any]) -> None:
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.vault_dir, 0o700)
        blob = encrypt_bytes(json.dumps(index, ensure_ascii=False).encode(), self.keyring)
        index_file = self.vault_dir / "index.aegis"
        fd = os.open(index_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(index_file, 0o600)

    def vault_put(self, src: Path | str, name: Optional[str] = None) -> Dict[str, Any]:
        src = Path(src).expanduser()
        if not src.is_file():
            return {"ok": False, "error": "origen inexistente"}
        logical = name or src.name
        objects = self.vault_dir / "objects"
        objects.mkdir(parents=True, exist_ok=True)
        os.chmod(objects, 0o700)
        object_id = hashlib.blake2b(logical.encode(), digest_size=16).hexdigest()
        container = objects / f"{object_id}.aegis"
        meta = encrypt_file(src, container, self.keyring)
        index = self._vault_index()
        index[logical] = {
            "object": container.name,
            "size": meta.size,
            "sha256": meta.plaintext_sha256,
            "added": time.time(),
            "origin": str(src),
        }
        self._save_vault_index(index)
        self.ledger.append("vault_put", {"name": logical, "size": meta.size, "sha256": meta.plaintext_sha256})
        return {"ok": True, "name": logical, "object": str(container), "size": meta.size}

    def vault_list(self) -> List[Dict[str, Any]]:
        index = self._vault_index()
        return [
            {"name": name, **{k: v for k, v in meta.items() if k != "object"}, "object": meta.get("object")}
            for name, meta in sorted(index.items())
        ]

    def vault_get(self, name: str, output: Optional[Path | str] = None) -> Dict[str, Any]:
        index = self._vault_index()
        if name not in index:
            return {"ok": False, "error": "objeto no encontrado"}
        container = self.vault_dir / "objects" / index[name]["object"]
        dst = Path(output).expanduser() if output else Path.cwd() / name
        if dst.exists():
            return {"ok": False, "error": f"destino existente: {dst}"}
        meta = decrypt_file(container, dst, self.keyring)
        self.ledger.append("vault_get", {"name": name, "sha256": meta.plaintext_sha256})
        return {"ok": True, "output": str(dst), "size": meta.size}

    def vault_rm(self, name: str, *, shred: bool = True) -> Dict[str, Any]:
        index = self._vault_index()
        if name not in index:
            return {"ok": False, "error": "objeto no encontrado"}
        container = self.vault_dir / "objects" / index[name]["object"]
        if shred and container.exists():
            shred_file(container)
        elif container.exists():
            container.unlink()
        index.pop(name, None)
        self._save_vault_index(index)
        self.ledger.append("vault_rm", {"name": name})
        return {"ok": True, "name": name}

    # ------------------------------------------------------------------
    # Escaneo de contenido
    # ------------------------------------------------------------------

    def scan(self, paths: Sequence[Path | str], *, include_pii: bool = True) -> Dict[str, Any]:
        findings: List[Dict[str, Any]] = []
        scanned = 0
        for raw in paths:
            p = Path(raw)
            if p.is_file():
                candidates = [p]
            else:
                candidates = []
                for base, dirs, files in os.walk(p, followlinks=False):
                    dirs[:] = [d for d in dirs if not should_skip(Path(base) / d) and d != ".git"]
                    candidates.extend(Path(base) / f for f in files)
            for f in candidates:
                scanned += 1
                for hit in scan_file(f, include_pii=include_pii):
                    findings.append(hit.as_dict())
        return {"ok": not findings, "scanned": scanned, "findings": findings}

    def scan_staged(self) -> Dict[str, Any]:
        try:
            proc = subprocess.run(
                ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
                cwd=self.project_root,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return {"ok": True, "scanned": 0, "findings": [], "error": "git no disponible"}
        files = [self.project_root / p for p in proc.stdout.decode("utf-8", "ignore").split("\x00") if p]
        result = self.scan(files, include_pii=False)
        # El gancho pre-commit sólo bloquea credenciales de alta confianza.
        blocking = [
            hit
            for hit in result["findings"]
            if int(hit.get("severity_value", 0)) >= int(Severity.HIGH)
            and hit.get("rule") not in {"credit_card", "high_entropy"}
        ]
        result["findings"] = blocking
        result["ok"] = not blocking
        self.ledger.append(
            "scan_staged",
            {"files": len(files), "findings": len(blocking), "blocked": not result["ok"]},
        )
        return result

    # ------------------------------------------------------------------
    # Endurecimiento y pánico
    # ------------------------------------------------------------------

    def harden(self, *, apply: bool = False, aggressive: bool = False) -> Dict[str, Any]:
        result = self.hardening.apply(aggressive=aggressive) if apply else self.hardening.audit()
        self.ledger.append(
            "harden",
            {"apply": apply, "aggressive": aggressive, "applied": len(result.applied), "failed": len(result.failed)},
        )
        return result.as_dict()

    def panic(self, *, reason: str = "protocolo de pánico", poweroff: bool = False, offline: bool = False) -> Dict[str, Any]:
        protocol = PanicProtocol(self.home, ledger=self.ledger)
        return protocol.execute(reason=reason, poweroff=poweroff, offline=offline)

    # ------------------------------------------------------------------
    # Vigilancia
    # ------------------------------------------------------------------

    def watch_once(self) -> Dict[str, Any]:
        ledger = self.ledger.verify()
        auditor = PolicyAuditor(self.project_root, home=Path.home())
        result = auditor.audit(deep=False)
        hard = self.hardening.audit()
        critical = [f for f in result.findings + hard.findings if f.severity >= Severity.CRITICAL]
        payload = {
            "ts": time.time(),
            "ledger_ok": ledger.ok,
            "score": result.score,
            "findings": len(result.findings) + len(hard.findings),
            "critical": [f.as_dict() for f in critical[:20]],
        }
        fingerprint = hashlib.blake2b(
            json.dumps(payload["critical"], sort_keys=True).encode(), digest_size=12
        ).hexdigest()
        state = self._read_state()
        alerted = state.get("watch_fingerprint")
        if critical and fingerprint != alerted:
            self._alert(payload)
            state["watch_fingerprint"] = fingerprint
            self._write_state(state)
        return payload

    def _alert(self, payload: Dict[str, Any]) -> None:
        self.alerts_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.alerts_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            os.fsync(fh.fileno())
        try:
            os.chmod(self.alerts_path, 0o600)
        except OSError:
            pass
        title = "AEGIS-Ω · alerta crítica"
        body = "\n".join(f"• {f['title']}\n  {f['path']}" for f in payload.get("critical", [])[:4])
        if shutil.which("notify-send"):
            subprocess.Popen(
                ["notify-send", "-u", "critical", "-a", _CODENAME, title, body or "Hallazgos críticos"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        self.ledger.append("alert", {"critical": len(payload.get("critical", [])), "score": payload.get("score")})

    def watch(self, *, interval: int = 300, iterations: Optional[int] = None) -> None:
        count = 0
        while True:
            self.watch_once()
            count += 1
            if iterations is not None and count >= iterations:
                return
            time.sleep(max(15, interval))

    # ------------------------------------------------------------------
    # Baseline e informes
    # ------------------------------------------------------------------

    def baseline(self, paths: Optional[Sequence[Path | str]] = None) -> Dict[str, Any]:
        targets = paths or [
            self.home / "keys" / "master.key",
            self.project_root / ".env",
            self.project_root / "telegram_config.json",
            self.project_root / "akashic_secret.key",
        ]
        entries = []
        for raw in targets:
            p = Path(raw)
            if not p.is_file():
                continue
            entries.append({"path": str(p), "sha256": _sha256_file(p), "size": p.stat().st_size})
        self.ledger.append("baseline", {"entries": entries})
        return {"ok": True, "entries": entries}

    def export_chain(self, out: Path | str) -> str:
        path = self.ledger.export_chain(Path(out).expanduser())
        return str(path)

    def recover_key(self, code: str) -> Dict[str, Any]:
        master = self.keyring.unwrap_recovery_code(code)
        fp = hashlib.sha256(b"AEGIS-FP-v1" + master).hexdigest()[:32].upper()
        return {"ok": True, "fingerprint": fp}

    # ------------------------------------------------------------------
    # Instalación de servicios
    # ------------------------------------------------------------------

    def install_services(self, *, user: Optional[str] = None) -> Dict[str, Any]:
        """Instala unidad systemd de vigilancia y gancho pre-commit."""
        user = user or os.environ.get("USER") or "m11"
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        # Preferimos el intérprete del venv con PYTHONPATH explícito: evita
        # depender de la resolución de rutas de un lanzador intermedio y hace
        # la unidad reproducible aunque el binario se invoque por symlink.
        q = lambda value: '"' + str(value).replace('"', '\\"') + '"'
        venv_python = self.project_root / ".venv-linux" / "bin" / "python3"
        if venv_python.is_file() and os.access(venv_python, os.X_OK):
            exec_start = f"{q(venv_python)} -m core.aegis.cli watch --once"
        else:
            exe = shutil.which("aegis") or str(self.project_root / "bin" / "aegis")
            exec_start = f"{q(exe)} watch --once"
        service = f"""[Unit]
Description=AEGIS-Ω · vigilancia de integridad y secretos
After=default.target

[Service]
Type=oneshot
WorkingDirectory={self.project_root}
ExecStart={exec_start}
Environment={q('AEGIS_HOME=' + str(self.home))}
Environment={q('AEGIS_PROJECT_ROOT=' + str(self.project_root))}
Environment={q('PYTHONPATH=' + str(self.project_root))}
Nice=10
IOSchedulingClass=idle
# Sin PrivateTmp: en unidades de usuario systemd monta un user namespace para
# el /tmp privado y, dentro de él, la raíz del host aparece como uid 65534.
# Eso hace que `sudo` rechace ejecutarse y la auditoría de firewall/AppArmor
# produzca falsos críticos.
SuccessExitStatus=0 1
"""
        timer = """[Unit]
Description=AEGIS-Ω · temporizador de vigilancia (cada 15 minutos)
Requires=aegis-watch.service

[Timer]
OnBootSec=3min
OnUnitActiveSec=15min
AccuracySec=30s
Unit=aegis-watch.service

[Install]
WantedBy=timers.target
"""
        (unit_dir / "aegis-watch.service").write_text(service, encoding="utf-8")
        (unit_dir / "aegis-watch.timer").write_text(timer, encoding="utf-8")
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"], capture_output=True, check=False, timeout=20
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "aegis-watch.timer"],
            capture_output=True,
            check=False,
            timeout=30,
        )
        hook_result = self.install_git_hook()
        self.ledger.append("install_services", {"unit_dir": str(unit_dir), "git_hook": hook_result})
        return {
            "ok": True,
            "service": str(unit_dir / "aegis-watch.service"),
            "timer": str(unit_dir / "aegis-watch.timer"),
            "git_hook": hook_result,
        }

    def install_git_hook(self) -> Dict[str, Any]:
        git_dir = self.project_root / ".git"
        if not git_dir.is_dir():
            return {"ok": False, "error": "no es un repositorio git"}
        hooks = git_dir / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        hook = hooks / "pre-commit"
        if hook.exists() and "AEGIS-Ω" not in hook.read_text(encoding="utf-8", errors="ignore"):
            backup = hooks / "pre-commit.aegis-backup"
            if not backup.exists():
                shutil.copy2(hook, backup)
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "# AEGIS-Ω · bloqueo de secretos antes de confirmar\n"
            'set -euo pipefail\n'
            'if [ "${AEGIS_BYPASS:-0}" = "1" ]; then\n'
            '  echo "[AEGIS] bypass explícito: AEGIS_BYPASS=1" >&2\n'
            "  exit 0\n"
            "fi\n"
            'AEGIS_BIN="$(command -v aegis || true)"\n'
            'if [ -z "$AEGIS_BIN" ]; then\n'
            '  echo "[AEGIS] binario aegis no encontrado; se omite el escaneo" >&2\n'
            "  exit 0\n"
            "fi\n"
            '"$AEGIS_BIN" scan --staged\n',
            encoding="utf-8",
        )
        os.chmod(hook, 0o755)
        return {"ok": True, "hook": str(hook)}

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _append_manifest(self, rec: SealRecord) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.manifest_path.parent, 0o700)
        with open(self.manifest_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec.as_dict(), ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(self.manifest_path, 0o600)

    def _manifest_records(self) -> List[Dict[str, Any]]:
        if not self.manifest_path.exists():
            return []
        out = []
        for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def _read_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, patch: Dict[str, Any]) -> None:
        state = self._read_state()
        state.update(patch)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.state_path)


_ENGINE: Optional[AegisEngine] = None


def get_engine() -> AegisEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = AegisEngine()
    return _ENGINE
