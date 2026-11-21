#!/usr/bin/env python3
"""
core/cyber_recursive_agent.py - TARDIS CyberEvolve
==================================================
Agente autónomo de auto-mejora recursiva enfocado en ciberseguridad para
GODWORKS SYSTEM / TARDIS.

Ciclo recursivo (Observe -> Harden -> Verify -> Evolve):
  1. Observe:
     - Superficie de red (puertos 0.0.0.0/::, UFW, conntrack, interfaces promiscuas).
     - Endurecimiento de kernel (sysctl de red y sistema de archivos) e integridad
       (/etc/ld.so.preload).
     - Permisos de secretos, llaves, bóvedas y configuraciones sensibles.
     - Escaneo estático AST de seguridad en código Python de TARDIS/FTL
       (shell=True, eval/exec, yaml.load inseguro, verify=False, bind 0.0.0.0).
     - Higiene de unidades systemd de usuario.
  2. Harden & Verify:
     - Aplica remediaciones deterministas seguras (chmod 0600/0700 en secretos,
       sysctl de red/fs seguros) y verifica empíricamente el resultado.
  3. Evolve (Auto-Mejora Recursiva):
     - Ajusta dinámicamente los pesos/prioridades de cada regla según hallazgos
       reales y remediaciones verificadas.
     - Promueve objetivos recurrentes a `high_watch_targets`.
     - Registra telemetría generacional en JSON/JSONL y genera un reporte
       continuo en Markdown.
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
VAULT_DIR = Path(os.environ.get("LOCALAPPDATA", str(HOME))) / "vw-control"
VAULT_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = VAULT_DIR / "cyber_recursive_state.json"
LEDGER_FILE = VAULT_DIR / "cyber_recursive_ledger.jsonl"
REPORT_FILE = VAULT_DIR / "cyber_recursive_report.md"
LOG_FILE = VAULT_DIR / "cyber_recursive.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [CYBER-EVOLVE] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("tardis.cyber_recursive_agent")

# Parámetros sysctl de red y FS que endurecen sin restringir Ring 0 (ptrace/dmesg/kptr)
SAFE_SYSCTLS: Dict[str, str] = {
    "fs.protected_hardlinks": "1",
    "fs.protected_symlinks": "1",
    "fs.protected_fifos": "2",
    "fs.protected_regular": "2",
    "net.ipv4.tcp_syncookies": "1",
    "net.ipv4.tcp_rfc1337": "1",
    "net.ipv4.conf.all.accept_redirects": "0",
    "net.ipv4.conf.default.accept_redirects": "0",
    "net.ipv4.conf.all.accept_source_route": "0",
    "net.ipv4.conf.default.accept_source_route": "0",
    "net.ipv4.icmp_echo_ignore_broadcasts": "1",
}

SENSITIVE_SECRET_FILES: List[Path] = [
    PROJECT_ROOT / "akashic_secret.key",
    PROJECT_ROOT / "browser_vault_key.key",
    PROJECT_ROOT / "client_gateway_secrets.json",
    PROJECT_ROOT / "tapo_c310_config.json",
    PROJECT_ROOT / "telegram_config.json",
    PROJECT_ROOT / "whatsapp_config.json",
    PROJECT_ROOT / "data" / "terminal_captures" / "captures_index.json",
    VAULT_DIR / "gia_bridge_token.txt",
    HOME / ".ssh" / "authorized_keys",
]

# Puertos que legítimamente escuchan en 0.0.0.0 con autenticación + firewall UFW
EXPECTED_PUBLIC_PORTS = {7690, 8757, 8765}

DEFAULT_RULE_WEIGHTS: Dict[str, float] = {
    "unexpected_wildcard_port": 1.5,
    "ufw_inactive": 2.0,
    "sysctl_drift": 1.2,
    "ld_preload_anomaly": 2.0,
    "promiscuous_iface": 1.5,
    "permissive_secret_file": 1.4,
    "ast_shell_true": 1.3,
    "ast_unsafe_eval_exec": 1.3,
    "ast_tls_verify_false": 1.4,
    "ast_unsafe_yaml": 1.3,
    "ast_wildcard_bind": 1.1,
    "systemd_stale_or_writable": 1.2,
}


@dataclass
class CyberFinding:
    rule: str
    severity: str  # critical | high | medium | low | info
    target: str
    detail: str
    autofixable: bool = False
    remediated: bool = False


@dataclass
class RecursiveState:
    generation: int = 0
    last_run_iso: str = ""
    security_score: int = 100
    best_score: int = 0
    total_remediations: int = 0
    rule_weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_RULE_WEIGHTS))
    high_watch_targets: List[str] = field(default_factory=list)
    ast_scan_cursor: int = 0
    recent_scores: List[int] = field(default_factory=list)


def load_state() -> RecursiveState:
    if STATE_FILE.exists():
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            st = RecursiveState(**{
                k: raw[k] for k in RecursiveState.__dataclass_fields__ if k in raw
            })
            for k, v in DEFAULT_RULE_WEIGHTS.items():
                st.rule_weights.setdefault(k, v)
            return st
        except Exception as e:
            logger.warning(f"Estado corrupto, reiniciando estado limpio: {e}")
    return RecursiveState()


def save_state(state: RecursiveState) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE_FILE)


def run_cmd(cmd: List[str], timeout: float = 5.0) -> Tuple[int, str, str]:
    try:
        res = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return 1, "", str(e)


class CyberRecursiveAgent:
    """Agente de auto-mejora recursiva especializado en ciberseguridad."""

    def __init__(self, ast_batch_size: int = 25) -> None:
        self.state = load_state()
        self.ast_batch_size = ast_batch_size

    # ------------------------------------------------------------------
    # 1. OBSERVE: Sensores de red, kernel, secretos, AST y systemd
    # ------------------------------------------------------------------
    def scan_network_surface(self) -> List[CyberFinding]:
        findings: List[CyberFinding] = []
        rc, out, _ = run_cmd(["ss", "-tulpn"], timeout=4.0)
        if rc == 0:
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) < 5:
                    continue
                proto = parts[0]
                local_addr = parts[4]
                if not (local_addr.startswith("0.0.0.0:") or local_addr.startswith("[::]:") or local_addr.startswith("*:")):
                    continue
                port_str = local_addr.rsplit(":", 1)[-1]
                if not port_str.isdigit():
                    continue
                port = int(port_str)
                if port in (53, 5353) or port in EXPECTED_PUBLIC_PORTS:
                    continue
                proc = parts[-1] if len(parts) > 5 else "unknown"
                findings.append(CyberFinding(
                    rule="unexpected_wildcard_port",
                    severity="high" if proto.startswith("tcp") else "medium",
                    target=f"{proto}/{local_addr}",
                    detail=f"Socket {proto} expuesto en todas las interfaces ({local_addr}) por {proc}",
                ))

        rc, ufw_out, _ = run_cmd(["sudo", "-n", "ufw", "status"], timeout=4.0)
        if rc == 0 and "Status: active" not in ufw_out and "Estado: activo" not in ufw_out:
            findings.append(CyberFinding(
                rule="ufw_inactive",
                severity="critical",
                target="ufw",
                detail="El firewall UFW no está activo",
            ))

        # Interfaces en modo promiscuo
        net_dir = Path("/sys/class/net")
        if net_dir.exists():
            for iface in net_dir.iterdir():
                flags_file = iface / "flags"
                try:
                    flags = int(flags_file.read_text().strip(), 16)
                    if flags & 0x100:  # IFF_PROMISC
                        findings.append(CyberFinding(
                            rule="promiscuous_iface",
                            severity="high",
                            target=iface.name,
                            detail=f"Interfaz {iface.name} en modo promiscuo (posible sniffer)",
                        ))
                except Exception:
                    continue
        return findings

    def scan_kernel_and_integrity(self) -> List[CyberFinding]:
        findings: List[CyberFinding] = []
        for key, expected in SAFE_SYSCTLS.items():
            rc, out, _ = run_cmd(["sysctl", "-n", key], timeout=2.0)
            if rc == 0 and out.strip() != expected:
                findings.append(CyberFinding(
                    rule="sysctl_drift",
                    severity="medium",
                    target=key,
                    detail=f"sysctl {key}={out.strip()} (esperado {expected})",
                    autofixable=True,
                ))

        preload = Path("/etc/ld.so.preload")
        if preload.exists():
            try:
                content = preload.read_text(encoding="utf-8", errors="ignore").strip()
                if content:
                    findings.append(CyberFinding(
                        rule="ld_preload_anomaly",
                        severity="critical",
                        target=str(preload),
                        detail=f"/etc/ld.so.preload no vacío: {content[:120]}",
                    ))
            except OSError:
                pass
        return findings

    def scan_secret_permissions(self) -> List[CyberFinding]:
        findings: List[CyberFinding] = []
        targets = list(SENSITIVE_SECRET_FILES)
        aegis_keys = HOME / ".aegis" / "keys"
        if aegis_keys.exists():
            targets.extend(aegis_keys.glob("*"))

        for p in targets:
            if not p.exists():
                continue
            try:
                mode = stat.S_IMODE(p.stat().st_mode)
                if mode & 0o077:
                    findings.append(CyberFinding(
                        rule="permissive_secret_file",
                        severity="high",
                        target=str(p),
                        detail=f"Permisos excesivos {oct(mode)} en archivo sensible (debe ser <= 0o600)",
                        autofixable=True,
                    ))
            except OSError:
                continue
        return findings

    def scan_systemd_hygiene(self) -> List[CyberFinding]:
        findings: List[CyberFinding] = []
        unit_dir = HOME / ".config" / "systemd" / "user"
        if not unit_dir.exists():
            return findings
        for unit in sorted(unit_dir.glob("*.service")):
            if unit.is_symlink():
                continue
            try:
                mode = stat.S_IMODE(unit.stat().st_mode)
                if mode & 0o022:
                    findings.append(CyberFinding(
                        rule="systemd_stale_or_writable",
                        severity="high",
                        target=str(unit),
                        detail=f"Unidad systemd escribible por grupo/otros ({oct(mode)})",
                        autofixable=True,
                    ))
                txt = unit.read_text(encoding="utf-8", errors="ignore")
                if "/home/m11" in txt:
                    findings.append(CyberFinding(
                        rule="systemd_stale_or_writable",
                        severity="medium",
                        target=str(unit),
                        detail="Contiene ruta obsoleta /home/m11",
                    ))
            except OSError:
                continue
        return findings

    def scan_ast_security_batch(self) -> List[CyberFinding]:
        findings: List[CyberFinding] = []
        py_files: List[Path] = []
        for base in (PROJECT_ROOT / "core", HOME / ".ftl"):
            if base.exists():
                py_files.extend(sorted(
                    p for p in base.rglob("*.py")
                    if "__pycache__" not in p.parts and ".bak" not in p.name
                ))
        if not py_files:
            return findings

        start = self.state.ast_scan_cursor % len(py_files)
        batch = py_files[start:start + self.ast_batch_size]
        if len(batch) < self.ast_batch_size and len(py_files) > self.ast_batch_size:
            batch += py_files[:self.ast_batch_size - len(batch)]
        self.state.ast_scan_cursor = (start + self.ast_batch_size) % len(py_files)

        for path in batch:
            try:
                src = path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(src)
            except Exception:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = getattr(fn, "attr", getattr(fn, "id", ""))
                mod = getattr(getattr(fn, "value", None), "id", "")

                if mod == "subprocess" and name in ("run", "Popen", "call", "check_output"):
                    for kw in node.keywords:
                        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            findings.append(CyberFinding(
                                rule="ast_shell_true",
                                severity="medium",
                                target=f"{path.name}:{node.lineno}",
                                detail=f"subprocess.{name}(..., shell=True) en {path}",
                            ))
                elif name in ("eval", "exec") and isinstance(fn, ast.Name):
                    findings.append(CyberFinding(
                        rule="ast_unsafe_eval_exec",
                        severity="medium",
                        target=f"{path.name}:{node.lineno}",
                        detail=f"Uso de {name}() dinámico en {path}",
                    ))
                elif mod == "yaml" and name == "load":
                    has_loader = any(kw.arg == "Loader" for kw in node.keywords)
                    if not has_loader:
                        findings.append(CyberFinding(
                            rule="ast_unsafe_yaml",
                            severity="high",
                            target=f"{path.name}:{node.lineno}",
                            detail=f"yaml.load() sin Loader explícito en {path}",
                        ))
                elif mod == "requests" and name in ("get", "post", "put", "delete", "request"):
                    for kw in node.keywords:
                        if kw.arg == "verify" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                            findings.append(CyberFinding(
                                rule="ast_tls_verify_false",
                                severity="high",
                                target=f"{path.name}:{node.lineno}",
                                detail=f"requests.{name}(..., verify=False) desactiva TLS en {path}",
                            ))
        return findings

    # ------------------------------------------------------------------
    # 2. HARDEN & VERIFY: Remediación determinista segura
    # ------------------------------------------------------------------
    def remediate_and_verify(self, findings: List[CyberFinding]) -> int:
        remediated_count = 0
        for f in findings:
            if not f.autofixable:
                continue
            if f.rule == "permissive_secret_file":
                p = Path(f.target)
                try:
                    os.chmod(p, 0o600)
                    new_mode = stat.S_IMODE(p.stat().st_mode)
                    if (new_mode & 0o077) == 0:
                        f.remediated = True
                        remediated_count += 1
                        logger.info(f"[REMEDIATED] chmod 0600 aplicado y verificado en {p}")
                except OSError as e:
                    logger.warning(f"No se pudo endurecer {p}: {e}")

            elif f.rule == "systemd_stale_or_writable":
                p = Path(f.target)
                if p.exists() and "escribible" in f.detail:
                    try:
                        os.chmod(p, 0o644)
                        if (stat.S_IMODE(p.stat().st_mode) & 0o022) == 0:
                            f.remediated = True
                            remediated_count += 1
                            logger.info(f"[REMEDIATED] chmod 0644 verificado en {p}")
                    except OSError as e:
                        logger.warning(f"No se pudo corregir permisos en {p}: {e}")

            elif f.rule == "sysctl_drift":
                key = f.target
                expected = SAFE_SYSCTLS.get(key)
                if expected is not None:
                    rc, _, _ = run_cmd(["sudo", "-n", "sysctl", "-w", f"{key}={expected}"], timeout=3.0)
                    if rc == 0:
                        rc2, out2, _ = run_cmd(["sysctl", "-n", key], timeout=2.0)
                        if rc2 == 0 and out2.strip() == expected:
                            f.remediated = True
                            remediated_count += 1
                            logger.info(f"[REMEDIATED] sysctl {key}={expected} aplicado y verificado")
        return remediated_count

    # ------------------------------------------------------------------
    # 3. EVOLVE: Puntuación, ajuste recursivo de pesos y memoria
    # ------------------------------------------------------------------
    def compute_score(self, findings: List[CyberFinding]) -> int:
        penalties = {"critical": 15, "high": 7, "medium": 3, "low": 1, "info": 0}
        score = 100.0
        for f in findings:
            if f.remediated:
                continue
            w = self.state.rule_weights.get(f.rule, 1.0)
            score -= penalties.get(f.severity, 1) * min(w, 1.5)
        return max(0, min(100, int(round(score))))

    def evolve_heuristics(self, findings: List[CyberFinding]) -> Dict[str, Any]:
        seen_rules: Dict[str, int] = {}
        remediated_rules: Dict[str, int] = {}
        target_counts: Dict[str, int] = {}

        for f in findings:
            seen_rules[f.rule] = seen_rules.get(f.rule, 0) + 1
            if f.remediated:
                remediated_rules[f.rule] = remediated_rules.get(f.rule, 0) + 1
            if f.severity in ("critical", "high") and not f.remediated:
                target_counts[f.target] = target_counts.get(f.target, 0) + 1

        weight_updates: Dict[str, float] = {}
        for rule, w in list(self.state.rule_weights.items()):
            if rule in remediated_rules:
                new_w = min(2.5, round(w + 0.10, 3))
            elif rule in seen_rules:
                new_w = min(2.5, round(w + 0.05, 3))
            else:
                new_w = max(0.5, round(w - 0.02, 3))
            if new_w != w:
                self.state.rule_weights[rule] = new_w
                weight_updates[rule] = new_w

        for t in target_counts:
            if t not in self.state.high_watch_targets:
                self.state.high_watch_targets.append(t)
        self.state.high_watch_targets = self.state.high_watch_targets[-30:]

        return {
            "weight_updates": weight_updates,
            "high_watch_count": len(self.state.high_watch_targets),
        }

    def write_report(self, findings: List[CyberFinding], score: int, remediated: int, evo: Dict[str, Any]) -> None:
        lines = [
            f"# TARDIS CyberEvolve — Reporte de Auto-Mejora Recursiva (Gen #{self.state.generation})",
            f"- **Timestamp**: {self.state.last_run_iso}",
            f"- **Security Score**: {score}/100 (Mejor histórico: {self.state.best_score}/100)",
            f"- **Hallazgos activos**: {sum(1 for f in findings if not f.remediated)} | **Remediados en este ciclo**: {remediated} | **Total remediaciones**: {self.state.total_remediations}",
            f"- **Objetivos en vigilancia prioritaria**: {evo['high_watch_count']}",
            "",
            "## Hallazgos del Ciclo",
        ]
        if not findings:
            lines.append("- Sin hallazgos de seguridad en este ciclo.")
        else:
            for f in findings[:40]:
                tag = "REMEDIADO" if f.remediated else f.severity.upper()
                lines.append(f"- `[{tag}]` **{f.rule}** (`{f.target}`): {f.detail}")
        REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_cycle(self) -> Dict[str, Any]:
        t0 = time.time()
        self.state.generation += 1
        self.state.last_run_iso = datetime.now(timezone.utc).isoformat()

        findings: List[CyberFinding] = []
        findings.extend(self.scan_network_surface())
        findings.extend(self.scan_kernel_and_integrity())
        findings.extend(self.scan_secret_permissions())
        findings.extend(self.scan_systemd_hygiene())
        findings.extend(self.scan_ast_security_batch())

        remediated = self.remediate_and_verify(findings)
        self.state.total_remediations += remediated

        score = self.compute_score(findings)
        prev_score = self.state.security_score
        self.state.security_score = score
        self.state.best_score = max(self.state.best_score, score)
        self.state.recent_scores = (self.state.recent_scores + [score])[-50:]

        evo = self.evolve_heuristics(findings)
        save_state(self.state)
        self.write_report(findings, score, remediated, evo)

        entry = {
            "generation": self.state.generation,
            "iso": self.state.last_run_iso,
            "duration_s": round(time.time() - t0, 3),
            "score": score,
            "score_delta": score - prev_score,
            "findings_total": len(findings),
            "remediated": remediated,
            "high_watch_count": evo["high_watch_count"],
        }
        with LEDGER_FILE.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.info(
            f"Gen #{self.state.generation} completada en {entry['duration_s']}s | "
            f"Score={score}/100 (delta={entry['score_delta']:+d}) | "
            f"Hallazgos={len(findings)} | Remediados={remediated}"
        )
        return entry


def main() -> None:
    parser = argparse.ArgumentParser(description="TARDIS CyberEvolve - Recursive Cybersecurity Agent")
    parser.add_argument("--daemon", action="store_true", help="Ejecutar en bucle recursivo continuo")
    parser.add_argument("--interval", type=int, default=180, help="Intervalo entre generaciones (segundos)")
    parser.add_argument("--once", action="store_true", help="Ejecutar una sola generación y salir")
    args = parser.parse_args()

    agent = CyberRecursiveAgent()
    if args.daemon and not args.once:
        logger.info(f"Iniciando demonio recursivo de ciberseguridad (intervalo={args.interval}s)")
        while True:
            try:
                agent.run_cycle()
            except Exception as e:
                logger.exception(f"Error en ciclo recursivo: {e}")
            time.sleep(max(30, args.interval))
    else:
        res = agent.run_cycle()
        print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
