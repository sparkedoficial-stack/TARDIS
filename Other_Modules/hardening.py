"""
core/aegis/hardening.py — Endurecimiento del sistema operativo (Ring 0–3).
==========================================================================
AEGIS-Ω aplica una línea base defensiva verificable:

  · Sysctl de kernel: ocultamiento de símbolos, restricción de dmesg,
    YAMA ptrace, randomización, enlaces/fifos protegidos, anti-redirect.
  · Política de core dumps (los volcados filtran claves en claro).
  · auditd: vigilancia de custodia, sudoers, SSH, PAM y montajes.
  · Firewall y superficie de escucha: detección de puertos expuestos.
  · Cifrado de disco (LUKS) y estado de Secure Boot.
  · AppArmor/SELinux y módulos de integridad.

Los cambios persistentes se escriben como drop-ins idempotentes en
/etc/sysctl.d, /etc/audit/rules.d y /etc/security/limits.d.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .classifier import Severity
from .policy import PolicyFinding

SYSCTL_DROPIN = Path("/etc/sysctl.d/99-aegis-hardening.conf")
AUDIT_RULES = Path("/etc/audit/rules.d/99-aegis.rules")
LIMITS_DROPIN = Path("/etc/security/limits.d/99-aegis.conf")
SYSTEMD_LIMITS = Path("/etc/systemd/system.conf.d/99-aegis-limits.conf")
USER_LIMITS = Path("/etc/systemd/user.conf.d/99-aegis-limits.conf")

#: (clave, valor, perfil) — perfil: safe | moderate | aggressive
SYSCTL_BASELINE: Sequence[Tuple[str, str, str]] = (
    # Ocultamiento y memoria
    ("kernel.kptr_restrict", "1", "safe"),
    ("kernel.dmesg_restrict", "1", "safe"),
    ("kernel.yama.ptrace_scope", "1", "safe"),
    ("kernel.randomize_va_space", "2", "safe"),
    ("kernel.kexec_load_disabled", "1", "moderate"),
    ("vm.mmap_min_addr", "65536", "safe"),
    # Sistema de archivos
    ("fs.protected_hardlinks", "1", "safe"),
    ("fs.protected_symlinks", "1", "safe"),
    ("fs.protected_fifos", "2", "safe"),
    ("fs.protected_regular", "2", "safe"),
    ("fs.suid_dumpable", "0", "safe"),
    # Red
    ("net.ipv4.tcp_syncookies", "1", "safe"),
    ("net.ipv4.conf.all.rp_filter", "1", "safe"),
    ("net.ipv4.conf.default.rp_filter", "1", "safe"),
    ("net.ipv4.conf.all.accept_redirects", "0", "safe"),
    ("net.ipv4.conf.default.accept_redirects", "0", "safe"),
    ("net.ipv4.conf.all.secure_redirects", "0", "safe"),
    ("net.ipv4.conf.all.send_redirects", "0", "safe"),
    ("net.ipv4.conf.all.accept_source_route", "0", "safe"),
    ("net.ipv4.conf.all.log_martians", "1", "safe"),
    ("net.ipv4.icmp_echo_ignore_broadcasts", "1", "safe"),
    ("net.ipv4.icmp_ignore_bogus_error_responses", "1", "safe"),
    ("net.ipv6.conf.all.accept_redirects", "0", "safe"),
    ("net.ipv6.conf.all.accept_source_route", "0", "safe"),
    # BPF / perf (moderado: puede afectar perfilado y contenedores rootless)
    ("kernel.unprivileged_bpf_disabled", "1", "aggressive"),
    ("kernel.perf_event_paranoid", "3", "aggressive"),
    ("net.core.bpf_jit_harden", "2", "moderate"),
)

#: Puertos que jamás deben escuchar en 0.0.0.0 sin justificación.
HIGH_RISK_PORTS = {
    22: "SSH",
    2375: "Docker API sin TLS",
    3306: "MySQL",
    5432: "PostgreSQL",
    5900: "VNC",
    6379: "Redis",
    9200: "Elasticsearch",
    11434: "Ollama",
    27017: "MongoDB",
    8757: "GIA",
    8080: "HTTP alterno",
    3000: "Panel Node",
    53317: "LocalSend",
}

_ALLOWED_PUBLIC = {22, 80, 443}

#: Orígenes considerados redes privadas / bucle local.
_PRIVATE_CIDRS = {
    "127.0.0.1/8",
    "REDACTED_IP/8",
    "REDACTED_IP/12",
    "REDACTED_IP/16",
    "fc00::/7",
    "::1/128",
}


def _sysctl_path(key: str) -> Path:
    return Path("/proc/sys") / key.replace(".", "/")


def read_sysctl(key: str) -> Optional[str]:
    try:
        return _sysctl_path(key).read_text(encoding="utf-8").strip()
    except PermissionError:
        proc = _run(["sudo", "-n", "sysctl", "-n", key])
        return proc.stdout.strip() if proc.returncode == 0 else None
    except OSError:
        return None


def _run(cmd: Sequence[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, check=False)


@dataclass
class HardeningResult:
    findings: List[PolicyFinding] = field(default_factory=list)
    applied: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    sysctl_status: Dict[str, Dict[str, str]] = field(default_factory=dict)
    firewall: Dict[str, object] = field(default_factory=dict)
    listeners: List[Dict[str, object]] = field(default_factory=list)
    luks: Dict[str, object] = field(default_factory=dict)
    secure_boot: Optional[bool] = None
    apparmor: Optional[bool] = None
    apparmor_pending: bool = False
    auditd_active: bool = False

    def as_dict(self) -> Dict[str, object]:
        return {
            "findings": [f.as_dict() for f in self.findings],
            "applied": self.applied,
            "failed": self.failed,
            "sysctl": self.sysctl_status,
            "firewall": self.firewall,
            "listeners": self.listeners,
            "luks": self.luks,
            "secure_boot": self.secure_boot,
            "apparmor": self.apparmor,
            "apparmor_pending": self.apparmor_pending,
            "auditd_active": self.auditd_active,
        }


class SystemHardening:
    def __init__(self, home: Optional[Path] = None) -> None:
        self.home = Path(home or Path.home())

    # -- estado -------------------------------------------------------------

    def sysctl_status(self) -> Dict[str, Dict[str, str]]:
        out: Dict[str, Dict[str, str]] = {}
        for key, desired, profile in SYSCTL_BASELINE:
            current = read_sysctl(key)
            out[key] = {
                "current": current if current is not None else "N/D",
                "desired": desired,
                "profile": profile,
                "ok": current == desired,
            }
        return out

    def auditd_active(self) -> bool:
        return _run(["systemctl", "is-active", "--quiet", "auditd"]).returncode == 0

    def secure_boot(self) -> Optional[bool]:
        base = Path("/sys/firmware/efi/efivars")
        if not base.is_dir():
            return False
        for item in base.glob("SecureBoot-*"):
            try:
                data = item.read_bytes()
            except OSError:
                continue
            if len(data) >= 5:
                return data[4] == 1
        return None

    def apparmor_enabled(self) -> bool:
        try:
            return Path("/sys/module/apparmor/parameters/enabled").read_text().strip() == "Y"
        except OSError:
            return False

    def apparmor_configured(self) -> bool:
        """True si AppArmor está instalado y ya declarado en la configuración del
        cargador, pero el LSM aún no se activó (pendiente de reinicio)."""
        tools = shutil.which("apparmor_parser") or Path("/usr/sbin/apparmor_parser").exists()
        if not tools:
            return False
        candidates = (
            Path("/etc/default/limine"),
            Path("/etc/kernel/cmdline"),
            Path("/etc/default/grub"),
            Path("/etc/cmdline.d"),
        )
        for item in candidates:
            try:
                if item.is_file():
                    if "apparmor=1" in item.read_text(encoding="utf-8", errors="ignore"):
                        return True
                elif item.is_dir():
                    for child in item.glob("*.conf"):
                        if "apparmor=1" in child.read_text(encoding="utf-8", errors="ignore"):
                            return True
            except OSError:
                continue
        # Último recurso: la cmdline activa (por si el arranque ya lo incluyó).
        try:
            return "apparmor=1" in Path("/proc/cmdline").read_text(
                encoding="utf-8", errors="ignore"
            )
        except OSError:
            return False

    def luks_status(self) -> Dict[str, object]:
        info: Dict[str, object] = {"crypt_devices": [], "root_encrypted": False, "swap": None}
        try:
            proc = _run(["lsblk", "-J", "-o", "NAME,TYPE,FSTYPE,MOUNTPOINT,SIZE"])
            import json

            data = json.loads(proc.stdout or "{}")
        except (OSError, subprocess.SubprocessError, ValueError):
            return info
        stack = list(data.get("blockdevices", []))
        while stack:
            dev = stack.pop()
            stack.extend(dev.get("children") or [])
            if dev.get("type") == "crypt":
                info["crypt_devices"].append(dev.get("name"))
                for child in dev.get("children") or []:
                    if child.get("mountpoint") == "/":
                        info["root_encrypted"] = True
        if not info["root_encrypted"]:
            try:
                root_source = _run(["findmnt", "-n", "-o", "SOURCE", "/"]).stdout.strip()
                info["root_encrypted"] = "mapper" in root_source or "crypt" in root_source
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            swaps = _run(["swapon", "--show=NAME,TYPE", "--noheadings"]).stdout
            info["swap"] = swaps.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return info

    def firewall_status(self) -> Dict[str, object]:
        out: Dict[str, object] = {
            "backend": None,
            "active": False,
            "verified": False,
            "rules": [],
            "raw": "",
        }
        if shutil.which("ufw"):
            proc = _run(["sudo", "-n", "ufw", "status", "verbose"])
            if proc.returncode != 0:
                proc = _run(["ufw", "status", "verbose"])
            raw = proc.stdout
            out["backend"] = "ufw"
            out["raw"] = raw.strip()
            out["active"] = "Status: active" in raw
            out["verified"] = bool(out["active"])
            if not out["active"]:
                # Sin privilegios (p. ej. user namespace de systemd) `ufw status`
                # no devuelve nada. En ese caso nos apoyamos en la configuración
                # persistente para no declarar una falsa ausencia de firewall.
                enabled = False
                try:
                    for line in Path("/etc/ufw/ufw.conf").read_text(
                        encoding="utf-8", errors="ignore"
                    ).splitlines():
                        if line.strip().upper().startswith("ENABLED="):
                            enabled = line.split("=", 1)[1].strip().lower() == "yes"
                except OSError:
                    enabled = False
                if enabled:
                    out["active"] = True
                    out["verified"] = False
            for line in raw.splitlines():
                if "ALLOW" in line and "Anywhere" in line and "v6" not in line:
                    out["rules"].append(line.strip())
            return out
        if shutil.which("nft"):
            proc = _run(["nft", "list", "ruleset"])
            out["backend"] = "nftables"
            out["active"] = bool(proc.stdout.strip())
            out["verified"] = bool(out["active"])
            out["raw"] = proc.stdout.strip()[:4000]
        return out

    def port_lan_restricted(self, port: int, fw: Optional[Dict[str, object]] = None) -> bool:
        """True si todas las reglas ALLOW IN del puerto provienen de redes privadas.

        Un servicio escuchando en 0.0.0.0 pero alcanzable sólo desde la LAN y
        autenticado no tiene la misma exposición que uno publicado a Internet.
        """
        raw = str((fw or self.firewall_status()).get("raw", ""))
        sources: List[str] = []
        pattern = re.compile(rf"^\s*{port}(?:/(?:tcp|udp))?\s+ALLOW(?:\s+IN)?\s+(\S+)")
        for line in raw.splitlines():
            m = pattern.match(line)
            if m:
                sources.append(m.group(1))
        if not sources:
            return False
        return all(src in _PRIVATE_CIDRS for src in sources)

    @staticmethod
    def process_has_auth(process: str) -> bool:
        """Heurística: el proceso declara un token de autenticación en su entorno."""
        m = re.search(r"pid=(\d+)", process or "")
        if not m:
            return False
        try:
            env = Path(f"/proc/{m.group(1)}/environ").read_bytes().split(b"\0")
        except OSError:
            return False
        for item in env:
            key = item.split(b"=", 1)[0].decode("utf-8", "ignore").upper()
            if "TOKEN" in key or "SECRET" in key or "PASSWORD" in key:
                return True
        return False

    def listening_sockets(self) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        if not shutil.which("ss"):
            return out
        proc = _run(["ss", "-tulpnH"])
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            proto = parts[0]
            local = parts[4]
            addr, _, port = local.rpartition(":")
            if not port.isdigit():
                continue
            process = " ".join(parts[6:]) if len(parts) > 6 else ""
            out.append(
                {
                    "proto": proto,
                    "address": addr,
                    "port": int(port),
                    "process": process.strip(),
                    "exposed": addr in ("0.0.0.0", "[::]", "*", "::"),
                }
            )
        return out

    # -- auditoría ----------------------------------------------------------

    def audit(self) -> HardeningResult:
        res = HardeningResult()
        res.sysctl_status = self.sysctl_status()
        res.auditd_active = self.auditd_active()
        res.secure_boot = self.secure_boot()
        res.apparmor = self.apparmor_enabled()
        if res.apparmor is False:
            res.apparmor_pending = self.apparmor_configured()
        res.firewall = self.firewall_status()
        res.listeners = self.listening_sockets()
        res.luks = self.luks_status()

        for key, data in res.sysctl_status.items():
            if not data["ok"]:
                sev = Severity.MEDIUM if data["profile"] != "aggressive" else Severity.LOW
                res.findings.append(
                    PolicyFinding(
                        "SYSCTL_DEBIL",
                        sev,
                        "Parámetro de kernel sin endurecer",
                        f"/proc/sys/{key.replace('.', '/')}",
                        f"actual={data['current']} deseado={data['desired']}",
                        f"sysctl -w {key}={data['desired']}",
                        auto=True,
                    )
                )

        # Auditd
        if not res.auditd_active:
            res.findings.append(
                PolicyFinding(
                    "AUDITD_INACTIVO",
                    Severity.HIGH,
                    "Auditoría de kernel desactivada",
                    "auditd",
                    "sin traza de accesos privilegiados ni manipulación de custodia",
                    "systemctl enable --now auditd",
                    auto=True,
                )
            )
        if not AUDIT_RULES.exists():
            res.findings.append(
                PolicyFinding(
                    "AUDITD_SIN_REGLAS",
                    Severity.HIGH,
                    "Sin reglas de auditoría AEGIS",
                    str(AUDIT_RULES),
                    "no se vigilan sudoers, SSH, PAM ni la bóveda",
                    "aegis harden --apply",
                    auto=True,
                )
            )

        # Firewall
        fw = res.firewall
        if not fw.get("active"):
            res.findings.append(
                PolicyFinding(
                    "FIREWALL_INACTIVO",
                    Severity.CRITICAL,
                    "Cortafuegos inactivo",
                    str(fw.get("backend") or "sistema"),
                    "todo el tráfico entrante queda sin política",
                    "ufw default deny incoming && ufw enable",
                    auto=False,
                )
            )
        else:
            if not fw.get("verified", True):
                res.findings.append(
                    PolicyFinding(
                        "FIREWALL_NO_VERIFICABLE",
                        Severity.INFO,
                        "Firewall habilitado · estado no verificable sin privilegios",
                        str(fw.get("backend") or "sistema"),
                        "la configuración persistente indica ENABLED=yes; "
                        "ejecute `sudo ufw status verbose` para verificar las reglas",
                        "Auditar el firewall con `aegis audit` desde una sesión con sudo",
                    )
                )
            raw = str(fw.get("raw", ""))
            for line in raw.splitlines():
                m = re.match(r"^(\d+)(?:/(tcp|udp))?\s+ALLOW\s+IN\s+Anywhere", line.strip())
                if not m:
                    continue
                port = int(m.group(1))
                if port not in _ALLOWED_PUBLIC:
                    res.findings.append(
                        PolicyFinding(
                            "PUERTO_PUBLICO",
                            Severity.MEDIUM,
                            "Puerto expuesto a cualquier origen",
                            f"ufw:{port}",
                            f"{line.strip()} — {HIGH_RISK_PORTS.get(port, 'servicio no esencial')}",
                            f"ufw delete allow {port}",
                            auto=False,
                        )
                    )

        # Superficie de escucha
        for sock in res.listeners:
            port = int(sock["port"])  # type: ignore[arg-type]
            if not sock["exposed"]:
                continue
            if port in HIGH_RISK_PORTS and port not in _ALLOWED_PUBLIC:
                lan_only = self.port_lan_restricted(port, fw)
                authed = self.process_has_auth(str(sock.get("process") or ""))
                if lan_only and authed:
                    res.findings.append(
                        PolicyFinding(
                            "SERVICIO_LAN_AUTENTICADO",
                            Severity.INFO,
                            "Servicio expuesto con autenticación, restringido a LAN",
                            f"{sock['address']}:{port}/{sock['proto']}",
                            f"{HIGH_RISK_PORTS[port]} · firewall sólo permite redes privadas",
                            "Mantener el token rotado y el firewall al día",
                        )
                    )
                    continue
                if lan_only or authed:
                    detail = (
                        "firewall restringido a LAN; falta autenticación verificable"
                        if lan_only
                        else "autenticación presente; falta restricción de firewall a LAN"
                    )
                    res.findings.append(
                        PolicyFinding(
                            "SERVICIO_EXPUESTO_PARCIAL",
                            Severity.LOW,
                            "Servicio sensible expuesto parcialmente protegido",
                            f"{sock['address']}:{port}/{sock['proto']}",
                            f"{HIGH_RISK_PORTS[port]} · {detail}",
                            "Completar la otra mitad: firewall LAN + token de autenticación",
                        )
                    )
                    continue
                res.findings.append(
                    PolicyFinding(
                        "SERVICIO_EXPUESTO",
                        Severity.MEDIUM,
                        "Servicio sensible escuchando en todas las interfaces",
                        f"{sock['address']}:{port}/{sock['proto']}",
                        f"{HIGH_RISK_PORTS[port]} · {sock.get('process') or 'proceso no identificado'}",
                        "Vincular a 127.0.0.1 o proteger con autenticación y firewall",
                    )
                )

        # Política de volcados de memoria
        if not LIMITS_DROPIN.exists():
            res.findings.append(
                PolicyFinding(
                    "SIN_POLITICA_CORE",
                    Severity.MEDIUM,
                    "Sin política de core dumps",
                    str(LIMITS_DROPIN),
                    "un volcado de memoria puede contener la clave maestra en claro",
                    "aegis harden --apply",
                    auto=True,
                )
            )
        elif not (SYSTEMD_LIMITS.exists() and USER_LIMITS.exists()):
            res.findings.append(
                PolicyFinding(
                    "SERVICIOS_SIN_LIMITE_CORE",
                    Severity.LOW,
                    "Servicios systemd sin límite de core dump",
                    str(SYSTEMD_LIMITS),
                    "los demonios no heredan pam_limits y podrían escribir volcados",
                    "aegis harden --apply",
                    auto=True,
                )
            )

        # Cifrado de disco
        luks = res.luks
        if not luks.get("root_encrypted"):
            res.findings.append(
                PolicyFinding(
                    "DISCO_SIN_CIFRAR",
                    Severity.CRITICAL,
                    "Raíz del sistema sin cifrado LUKS",
                    "/",
                    "un retiro físico del disco expone toda la información",
                    "Migrar a LUKS2 o mantener datos críticos en la bóveda AEGIS",
                )
            )
        if not luks.get("crypt_devices"):
            res.findings.append(
                PolicyFinding(
                    "SIN_LUKS",
                    Severity.HIGH,
                    "No se detectan volúmenes cifrados",
                    "lsblk",
                    "sin confidencialidad en reposo a nivel de bloque",
                    "cryptsetup luksFormat / crear bóveda AEGIS",
                )
            )

        # Secure Boot / AppArmor
        if res.secure_boot is False:
            res.findings.append(
                PolicyFinding(
                    "SECURE_BOOT_OFF",
                    Severity.LOW,
                    "Secure Boot desactivado",
                    "UEFI",
                    "la cadena de arranque no está verificada por firmware",
                    "Activar Secure Boot y firmar el cargador con sbctl",
                )
            )
        if res.apparmor is False:
            if res.apparmor_pending:
                res.findings.append(
                    PolicyFinding(
                        "APPARMOR_PENDING",
                        Severity.INFO,
                        "AppArmor configurado · pendiente de reinicio",
                        "kernel",
                        "apparmor=1 security=apparmor ya está en la línea de comandos; "
                        "el LSM se activará en el próximo arranque",
                        "Reiniciar el equipo para cargar el módulo de confinamiento",
                    )
                )
            else:
                res.findings.append(
                    PolicyFinding(
                        "APPARMOR_OFF",
                        Severity.MEDIUM,
                        "AppArmor desactivado",
                        "kernel",
                        "sin confinamiento obligatorio de procesos",
                        "Habilitar apparmor=1 security=apparmor en el cargador",
                    )
                )
        return res

    # -- aplicación ---------------------------------------------------------

    def apply(self, *, aggressive: bool = False, apply_sysctl_now: bool = True) -> HardeningResult:
        res = self.audit()
        lines = [
            "# AEGIS-Ω · línea base de endurecimiento del kernel",
            "# Generado automáticamente por `aegis harden --apply`",
            f"# perfil: {'agresivo' if aggressive else 'estándar'}",
            "",
        ]
        for key, desired, profile in SYSCTL_BASELINE:
            if profile == "aggressive" and not aggressive:
                continue
            if key == "net.ipv4.ip_forward" and self._docker_present():
                continue
            lines.append(f"{key} = {desired}")
        content = "\n".join(lines) + "\n"

        if self._install_file(SYSCTL_DROPIN, content, 0o644):
            res.applied.append(str(SYSCTL_DROPIN))
            if apply_sysctl_now:
                proc = _run(["sudo", "-n", "sysctl", "-p", str(SYSCTL_DROPIN)])
                if proc.returncode == 0:
                    res.applied.append("sysctl --apply")
                else:
                    res.failed.append("sysctl: " + (proc.stderr or "").strip()[:300])
        else:
            res.failed.append(f"no se pudo escribir {SYSCTL_DROPIN}")

        # Límites: sin core dumps (fuga de claves en volcados).
        limits = (
            "# AEGIS-Ω · sin volcados de memoria que expongan material criptográfico\n"
            "*        hard    core    0\n"
            "*        soft    core    0\n"
        )
        if self._install_file(LIMITS_DROPIN, limits, 0o644):
            res.applied.append(str(LIMITS_DROPIN))

        # Los servicios systemd no heredan pam_limits: fijamos el límite en el
        # propio gestor para que ningún demonio escriba volcados de memoria.
        limits_units = (
            (
                SYSTEMD_LIMITS,
                "[Manager]\n# AEGIS-Ω · ningún servicio puede volcar memoria (claves en claro)\n"
                "DefaultLimitCORE=0\n",
            ),
            (
                USER_LIMITS,
                "[Manager]\n# AEGIS-Ω · ningún servicio de usuario puede volcar memoria\n"
                "DefaultLimitCORE=0\n",
            ),
        )
        units_changed = False
        for target, content in limits_units:
            if self._install_if_changed(target, content, 0o644):
                units_changed = True
                res.applied.append(str(target))
        if units_changed:
            if _run(["sudo", "-n", "systemctl", "daemon-reexec"], timeout=30).returncode == 0:
                res.applied.append("systemd daemon-reexec")
            _run(["systemctl", "--user", "daemon-reexec"], timeout=30)

        # auditd
        rules = self._audit_rules_content()
        if self._install_file(AUDIT_RULES, rules, 0o640):
            res.applied.append(str(AUDIT_RULES))
            _run(["sudo", "-n", "systemctl", "enable", "--now", "auditd"], timeout=30)
            reload_cmd = shutil.which("augenrules")
            if reload_cmd:
                proc = _run(["sudo", "-n", reload_cmd, "--load"])
                (res.applied if proc.returncode == 0 else res.failed).append("auditd --reload")
            else:
                _run(["sudo", "-n", "systemctl", "restart", "auditd"])

        res.auditd_active = self.auditd_active()
        # Releer estado para reflejar lo aplicado.
        res.sysctl_status = self.sysctl_status()
        for f in res.findings:
            if f.code == "SYSCTL_DEBIL" and res.sysctl_status.get(f.path.replace("/proc/sys/", "").replace("/", "."), {}).get("ok"):
                f.fixed = True
        return res

    # -- helpers ------------------------------------------------------------

    def _docker_present(self) -> bool:
        return Path("/var/run/docker.sock").exists() or Path("/etc/docker").is_dir()

    def _install_file(self, target: Path, content: str, mode: int) -> bool:
        tmp_fd, tmp_name = tempfile.mkstemp(prefix="aegis-", suffix=".conf")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            proc = _run(["sudo", "-n", "install", "-D", "-m", f"{mode:o}", tmp_name, str(target)])
            return proc.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
        finally:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    def _install_if_changed(self, target: Path, content: str, mode: int) -> bool:
        """Instala sólo si el contenido difiere; evita reexecs innecesarios."""
        try:
            if target.is_file() and target.read_text(encoding="utf-8") == content:
                return False
        except OSError:
            pass
        return self._install_file(target, content, mode)

    def _audit_rules_content(self) -> str:
        aegis_home = Path(os.environ.get("AEGIS_HOME", str(self.home / ".aegis"))).resolve()
        rules = [
            "# AEGIS-Ω · reglas de auditoría soberanas",
            "-D",
            "",
            "# Custodia criptográfica AEGIS",
            f"-w {aegis_home} -p wa -k aegis_custody",
        ]
        for extra in (
            Path("/etc/sudoers"),
            Path("/etc/sudoers.d"),
            Path("/etc/ssh/sshd_config"),
            Path("/etc/pam.d"),
            Path("/etc/audit"),
            Path("/etc/systemd/system"),
            Path("/etc/sysctl.d"),
        ):
            if extra.exists():
                rules.append(f"-w {extra} -p wa -k aegis_privilegio")
        rules += [
            "",
            "# Ejecución como root y escalada",
            "-a always,exit -F arch=b64 -S execve -F euid=0 -k aegis_root_exec",
            "",
            "# Montajes y desmontajes",
            "-a always,exit -F arch=b64 -S mount -S umount2 -F auid>=1000 -F auid!=unset -k aegis_mount",
            "",
            "# Módulos del kernel",
            "-a always,exit -F arch=b64 -S init_module -S finit_module -S delete_module -k aegis_module",
            "",
            "# Alteración de atributos extendidos (chattr)",
            "-a always,exit -F arch=b64 -S setxattr -S removexattr -S lsetxattr -S lremovexattr -k aegis_xattr",
            "",
        ]
        return "\n".join(rules)
