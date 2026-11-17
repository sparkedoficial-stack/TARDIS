"""
core/aegis/policy.py — Auditoría de política, permisos y fugas de información.
=============================================================================
Comprueba la postura real del sistema de archivos:

  · Permisos de archivos C3/C4 (nunca 0644 para un secreto).
  · Directorios de custodia (0700 obligatorio).
  · Secretos rastreados por Git (fuga histórica y de repositorio).
  · Credenciales/PII en configuraciones, historiales y documentación.
  · Archivos mundialmente escribibles y enlaces peligrosos.
  · Permisos de claves SSH y del perímetro AEGIS.

La remediación automática es conservadora: corrige permisos, nunca borra
contenido. La expulsión de un secreto del índice Git requiere `--fix-git`.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .classifier import (
    Level,
    Severity,
    classify_path,
    scan_file,
    should_skip,
)

_SKIP_EXTRA = {".claude/worktrees", "_selfmod_backups", "vault/images", "vault/videos"}
_CONTENT_SUFFIXES = {
    ".env", ".json", ".jsonl", ".yaml", ".yml", ".ini", ".cfg", ".toml",
    ".txt", ".md", ".log", ".sh", ".py", ".conf", ".properties", ".xml",
    ".csv", ".sql", ".bak", ".example",
}
_MAX_CONTENT_FILES = 1200
_MAX_CONTENT_BYTES = 2 << 20


@dataclass
class PolicyFinding:
    code: str
    severity: Severity
    title: str
    path: str
    detail: str = ""
    remediation: str = ""
    auto: bool = False
    fixed: bool = False

    def as_dict(self) -> Dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity.label,
            "severity_value": int(self.severity),
            "title": self.title,
            "path": self.path,
            "detail": self.detail,
            "remediation": self.remediation,
            "auto": self.auto,
            "fixed": self.fixed,
        }


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _mode(path: Path) -> int:
    try:
        return path.stat().st_mode & 0o777
    except OSError:
        return 0


@dataclass
class AuditResult:
    root: str
    scanned_files: int = 0
    scanned_dirs: int = 0
    findings: List[PolicyFinding] = field(default_factory=list)
    level_counts: Dict[str, int] = field(default_factory=lambda: {f"C{i}": 0 for i in range(5)})
    duration_s: float = 0.0

    @property
    def counts(self) -> Dict[str, int]:
        out = {"crítico": 0, "alto": 0, "medio": 0, "bajo": 0, "info": 0}
        for f in self.findings:
            if f.fixed:
                continue
            out[f.severity.label] += 1
        return out

    @property
    def score(self) -> int:
        penalty = (
            self.counts["crítico"] * 25
            + self.counts["alto"] * 10
            + self.counts["medio"] * 3
            + self.counts["bajo"] * 0.5
        )
        score = max(0, int(round(100 - min(100, penalty))))
        if self.counts["crítico"]:
            score = min(score, 45)
        elif self.counts["alto"]:
            score = min(score, 75)
        return score

    def as_dict(self) -> Dict[str, object]:
        return {
            "root": self.root,
            "scanned_files": self.scanned_files,
            "scanned_dirs": self.scanned_dirs,
            "duration_s": round(self.duration_s, 3),
            "score": self.score,
            "counts": self.counts,
            "level_counts": self.level_counts,
            "findings": [f.as_dict() for f in self.findings],
        }


class PolicyAuditor:
    def __init__(self, root: Path, *, home: Optional[Path] = None) -> None:
        self.root = Path(root).resolve()
        self.home = Path(home or Path.home())

    # -- utilidades ---------------------------------------------------------

    def _is_skipped(self, path: Path) -> bool:
        if should_skip(path):
            return True
        rel = _rel(path, self.root)
        return any(rel.startswith(extra) for extra in _SKIP_EXTRA)

    def _walk(self) -> Iterable[Tuple[Path, bool]]:
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            base = Path(dirpath)
            dirnames[:] = [d for d in dirnames if not self._is_skipped(base / d)]
            yield base, True
            for name in filenames:
                yield base / name, False

    # -- auditoría ----------------------------------------------------------

    def audit(
        self,
        *,
        deep: bool = True,
        include_home: bool = True,
        remediation: bool = False,
        fix_git: bool = False,
    ) -> AuditResult:
        import time

        started = time.time()
        result = AuditResult(root=str(self.root))
        tracked = self._tracked_files() if deep else set()
        content_budget = _MAX_CONTENT_FILES
        git_flagged: set[str] = set()

        for path, is_dir in self._walk():
            if path.is_symlink():
                try:
                    target = path.resolve()
                except OSError:
                    target = path
                if not str(target).startswith(str(self.home)) and not str(target).startswith(str(self.root)):
                    result.findings.append(
                        PolicyFinding(
                            "SYMLINK_EXTERNO",
                            Severity.MEDIUM,
                            "Enlace simbólico hacia fuera del perímetro",
                            _rel(path, self.root),
                            f"destino: {target}",
                            "Eliminar el enlace o restringir su destino",
                        )
                    )
                continue

            if is_dir:
                result.scanned_dirs += 1
                mode = _mode(path)
                cls = classify_path(path)
                if cls.level >= 3 and mode & 0o077:
                    finding = PolicyFinding(
                        "DIR_PERM_ABIERTOS",
                        Severity.HIGH,
                        "Directorio sensible con permisos abiertos",
                        _rel(path, self.root),
                        f"modo {oct(mode)}",
                        "chmod 700 <directorio>",
                        auto=True,
                    )
                    if remediation:
                        try:
                            os.chmod(path, 0o700)
                            finding.fixed = True
                        except OSError:
                            pass
                    result.findings.append(finding)
                continue

            result.scanned_files += 1
            try:
                st = path.stat()
            except OSError:
                continue
            mode = st.st_mode & 0o777
            cls = classify_path(path)
            result.level_counts[f"C{cls.level}"] += 1
            rel = _rel(path, self.root)

            # 1) Permisos de secretos.
            if cls.level >= 3 and mode & 0o077:
                finding = PolicyFinding(
                    "PERM_SECRETO_ABIERTO",
                    Severity.CRITICAL if cls.level >= 4 else Severity.HIGH,
                    "Secreto accesible por otros usuarios",
                    rel,
                    f"modo {oct(mode)} · clasificación {cls.code}",
                    "chmod 600 <archivo>",
                    auto=True,
                )
                if remediation:
                    try:
                        os.chmod(path, 0o600)
                        finding.fixed = True
                    except OSError:
                        pass
                result.findings.append(finding)

            # 2) Archivos mundialmente escribibles.
            if mode & 0o002 and not path.name.startswith(".aegis"):
                result.findings.append(
                    PolicyFinding(
                        "WORLD_WRITABLE",
                        Severity.HIGH,
                        "Archivo modificable por cualquier usuario",
                        rel,
                        f"modo {oct(mode)}",
                        "chmod o-w <archivo>",
                        auto=True,
                    )
                )

            # 3) Secretos rastreados por Git.
            if deep and rel in tracked and cls.level >= 3:
                sev = Severity.CRITICAL if cls.level >= 4 else Severity.HIGH
                finding = PolicyFinding(
                    "GIT_SECRETO_RASTREADO",
                    sev,
                    "Secreto versionado en Git",
                    rel,
                    f"clasificación {cls.code}; el contenido queda en el historial",
                    "git rm --cached <archivo>; añadir a .gitignore; rotar el secreto",
                    auto=False,
                )
                if fix_git and rel not in git_flagged:
                    if self._git_untrack(rel):
                        finding.fixed = True
                        git_flagged.add(rel)
                result.findings.append(finding)

            # 4) Inspección de contenido (presupuesto limitado).
            if deep and content_budget > 0 and path.suffix.lower() in _CONTENT_SUFFIXES:
                if st.st_size <= _MAX_CONTENT_BYTES and cls.level >= 2:
                    content_budget -= 1
                    hits = scan_file(path)
                    custodied = (mode & 0o077) == 0 or remediation
                    result.findings.extend(self._content_findings(rel, hits, custodied=custodied))
                    if (
                        deep
                        and rel in tracked
                        and any(h.severity >= Severity.HIGH for h in hits)
                    ):
                        finding = PolicyFinding(
                            "GIT_SECRETO_RASTREADO",
                            Severity.CRITICAL,
                            "Credencial versionada en Git",
                            rel,
                            "el contenido sensible está en el índice y en el historial",
                            "git rm --cached <archivo>; rotar la credencial; purgar historial",
                        )
                        if fix_git and rel not in git_flagged and self._git_untrack(rel):
                            finding.fixed = True
                            git_flagged.add(rel)
                        result.findings.append(finding)
                elif st.st_size <= _MAX_CONTENT_BYTES and cls.level == 1:
                    # En código fuente sólo credenciales de alta confianza.
                    is_test = rel.startswith("tests/") or "/tests/" in rel or path.name.startswith("test_")
                    if is_test:
                        continue
                    hits = scan_file(path, include_pii=False, high_confidence=True)
                    result.findings.extend(self._content_findings(rel, hits, code="CREDENCIAL_EN_CODIGO"))

        # 5) Perímetro AEGIS y claves.
        result.findings.extend(self._audit_custody())

        # 6) Historiales de shell.
        result.findings.extend(self._audit_history())

        # 7) Repositorio: secretos presentes en el historial de Git.
        if deep:
            result.findings.extend(self._audit_git_history(tracked))

        # Orden por severidad descendente.
        result.findings.sort(key=lambda f: (-int(f.severity), f.path, f.line if hasattr(f, "line") else 0))
        result.duration_s = time.time() - started
        return result

    # -- componentes --------------------------------------------------------

    def _tracked_files(self) -> set[str]:
        try:
            proc = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=self.root,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return set()
        if proc.returncode != 0:
            return set()
        return {p for p in proc.stdout.decode("utf-8", "ignore").split("\x00") if p}

    def _git_untrack(self, rel: str) -> bool:
        try:
            proc = subprocess.run(
                ["git", "rm", "--cached", "--quiet", "--", rel],
                cwd=self.root,
                capture_output=True,
                timeout=30,
                check=False,
            )
            return proc.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _content_findings(
        self,
        rel: str,
        hits: Iterable,
        *,
        code: str = "SECRETO_EN_CONTENIDO",
        custodied: bool = False,
    ) -> List[PolicyFinding]:
        """Agrupa coincidencias por regla para evitar miles de filas repetidas.

        `custodied=True` indica que el archivo ya vive en un perímetro 0600:
        el hallazgo se degrada a informativo porque el riesgo residual es la
        rotación, no la exposición local.
        """
        grouped: Dict[str, List] = {}
        for hit in hits:
            if hit.rule == "high_entropy" and code == "SECRETO_EN_CONTENIDO":
                continue
            grouped.setdefault(hit.rule, []).append(hit)

        findings: List[PolicyFinding] = []
        for rule, group in grouped.items():
            first = group[0]
            severity = Severity.LOW if custodied else first.severity
            title = f"Posible fuga: {first.kind}" if not custodied else f"Credencial/dato en custodia: {first.kind}"
            remediation = (
                "Rotar la credencial si estuvo expuesta y mantenerla cifrada 0600"
                if custodied
                else (
                    "Rotar la credencial, moverla a la bóveda cifrada AEGIS y purgar el origen"
                    if first.severity >= Severity.HIGH
                    else "Minimizar el dato, restringir permisos o cifrar el archivo"
                )
            )
            for hit in group[:2]:
                findings.append(
                    PolicyFinding(
                        code,
                        severity,
                        title,
                        rel,
                        f"línea {hit.line}: {hit.preview}",
                        remediation,
                    )
                )
            if len(group) > 2:
                findings.append(
                    PolicyFinding(
                        code,
                        severity,
                        title + " (recurrente)",
                        rel,
                        f"{len(group)} ocurrencias entre las líneas {group[0].line} y {group[-1].line}",
                        remediation,
                    )
                )
        return findings

    def _audit_custody(self) -> List[PolicyFinding]:
        findings: List[PolicyFinding] = []
        aegis_home = Path(os.environ.get("AEGIS_HOME", str(self.home / ".aegis")))
        checks = [
            (aegis_home, 0o700, Severity.HIGH, "PERIMETRO_AEGIS_PERMISOS"),
            (aegis_home / "keys", 0o700, Severity.CRITICAL, "DIR_CLAVES_PERMISOS"),
            (aegis_home / "keys" / "master.key", 0o400, Severity.CRITICAL, "CLAVE_MAESTRA_PERMISOS"),
        ]
        for path, expected, severity, code in checks:
            if not path.exists():
                continue
            mode = _mode(path)
            if mode & (0o777 ^ expected):
                findings.append(
                    PolicyFinding(
                        code,
                        severity,
                        "Permisos de custodia incorrectos",
                        str(path),
                        f"modo {oct(mode)}; esperado {oct(expected)}",
                        f"chmod {oct(expected)[2:]} {path}",
                        auto=True,
                    )
                )

        ssh_dir = self.home / ".ssh"
        if ssh_dir.is_dir():
            if _mode(ssh_dir) & 0o077:
                findings.append(
                    PolicyFinding(
                        "SSH_DIR_PERMISOS",
                        Severity.CRITICAL,
                        "Directorio ~/.ssh accesible por terceros",
                        str(ssh_dir),
                        f"modo {oct(_mode(ssh_dir))}",
                        "chmod 700 ~/.ssh",
                        auto=True,
                    )
                )
            for key in ssh_dir.iterdir():
                if key.is_file() and key.suffix != ".pub":
                    if _mode(key) & 0o077:
                        findings.append(
                            PolicyFinding(
                                "SSH_CLAVE_PERMISOS",
                                Severity.CRITICAL,
                                "Clave SSH con permisos laxos",
                                str(key),
                                f"modo {oct(_mode(key))}",
                                "chmod 600 " + str(key),
                                auto=True,
                            )
                        )
        return findings

    def _audit_history(self) -> List[PolicyFinding]:
        findings: List[PolicyFinding] = []
        candidates = [
            self.home / ".bash_history",
            self.home / ".zsh_history",
            self.home / ".local/share/fish/fish_history",
        ]
        for hist in candidates:
            if not hist.is_file():
                continue
            try:
                text = hist.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if len(text) > (2 << 20):
                text = text[-(2 << 20) :]
            for hit in scan_file(hist, include_pii=False):
                findings.append(
                    PolicyFinding(
                        "SECRETO_EN_HISTORIAL",
                        Severity.HIGH,
                        f"Credencial en historial de shell: {hit.kind}",
                        str(hist),
                        f"línea {hit.line}: {hit.preview}",
                        "Truncar el historial y rotar la credencial",
                    )
                )
        return findings

    def _audit_git_history(self, tracked: set[str]) -> List[PolicyFinding]:
        findings: List[PolicyFinding] = []
        risky = [p for p in tracked if classify_path(p).level >= 3]
        if not risky:
            return findings
        # ¿Están presentes en el HEAD? ¿O sólo en el historial?
        for rel in risky[:20]:
            try:
                proc = subprocess.run(
                    ["git", "log", "--oneline", "--all", "--", rel],
                    cwd=self.root,
                    capture_output=True,
                    timeout=20,
                    check=False,
                )
                commits = len([l for l in proc.stdout.decode("utf-8", "ignore").splitlines() if l.strip()])
            except (OSError, subprocess.SubprocessError):
                commits = 0
            if commits:
                findings.append(
                    PolicyFinding(
                        "GIT_HISTORIAL_SECRETO",
                        Severity.CRITICAL,
                        "Secreto persistente en el historial de Git",
                        rel,
                        f"{commits} confirmación(es) contienen el archivo",
                        "Rotar el secreto; purgar con git-filter-repo/BFG y forzar el push",
                    )
                )
        return findings


def remediate(result: AuditResult) -> List[str]:
    """Aplica correcciones automáticas declaradas por el auditor."""
    applied: List[str] = []
    for finding in result.findings:
        if not finding.auto or finding.fixed:
            continue
        path = Path(finding.path)
        if not path.is_absolute():
            path = Path(result.root) / path
        try:
            if path.is_dir():
                os.chmod(path, 0o700)
            elif path.suffix in {".key", ".enc", ".pem"} or finding.code.startswith(("PERM_", "SSH_")):
                os.chmod(path, 0o600)
            else:
                os.chmod(path, 0o600)
            finding.fixed = True
            applied.append(str(path))
        except OSError:
            continue
    return applied
