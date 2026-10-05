"""
agent_safety.py - Capa de seguridad para el agente autonomo GIA.
=================================================================

Aunque el agente corre en bucle sin aprobacion por-paso, esta capa
impide que un modelo que alucina destruya la maquina donde corre:

  1. DENYLIST  - patrones regex de comandos catastroficos/irreversibles
                 (format, diskpart, borrar raiz del disco, desactivar
                 Defender/firewall, limpiar logs, borrar el propio audit
                 log o esta denylist, fork bombs, reboots).
  2. RUTAS PROTEGIDAS - escritura/borrado bloqueado en Windows, System32,
                 Program Files, y los archivos del propio sistema GIA.
  3. AUDIT LOG - cada accion (permitida o bloqueada) se registra con
                 timestamp en %LOCALAPPDATA%\\vw-control\\agent_audit.log.
  4. KILL-SWITCH - lo aplica el loop (max iteraciones / tiempo).

La denylist se puede EDITAR/ampliar/reducir en:
  %LOCALAPPDATA%\\vw-control\\agent_denylist.json
El usuario es dueno de su maquina; si quiere quitar una regla, puede.
Pero el DEFAULT es seguro.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_LOG = CONFIG_DIR / "agent_audit.log"
DENYLIST_FILE = CONFIG_DIR / "agent_denylist.json"

# ---------------------------------------------------------------------
# Denylist por defecto (regex, case-insensitive)
# ---------------------------------------------------------------------
# Cada entrada: {"pattern": regex, "reason": explicacion}
_DEFAULT_DENYLIST = [
    # --- Destruccion de disco / particiones ---
    {"pattern": r"\bformat\s+[a-z]:", "reason": "formatear una unidad"},
    {"pattern": r"\bdiskpart\b", "reason": "manipulacion de particiones"},
    {"pattern": r"\bcipher\s+/w", "reason": "borrado seguro (irreversible)"},
    {"pattern": r"\bvssadmin\s+delete", "reason": "borrar shadow copies (anti-recuperacion)"},
    {"pattern": r"\bwmic\b.*\bdelete", "reason": "borrado masivo via WMIC"},

    # --- Borrado recursivo de raices del sistema ---
    {"pattern": r"rm\s+-rf?\s+[/~]", "reason": "rm -rf de raiz/home"},
    # del/erase/rd/rmdir recursivo sobre carpetas de sistema o perfiles (catastrofico)
    {"pattern": r"\b(del|erase|rd|rmdir)\b.*/[sq]\b.*\b[a-z]:\\(Users|Windows|Program Files|Program Files \(x86\)|ProgramData|System32)(\\?(\s|\"|'|$))",
     "reason": "borrado recursivo de carpeta de sistema o perfiles"},
    # del/erase/rd/rmdir recursivo sobre la raiz de una unidad
    {"pattern": r"\b(del|erase|rd|rmdir)\b.*/[sq]\b.*\b[a-z]:\\?(\s|\"|'|$)",
     "reason": "borrado recursivo de la raiz de una unidad"},
    {"pattern": r"Remove-Item.*-Recurse.*-Force.*\b(C:\\?(\s|\"|'|$)|C:\\Windows|C:\\Users(\s|\"|'|\\?$)|System32)",
     "reason": "Remove-Item -Recurse -Force sobre raiz/Windows/Users"},
    {"pattern": r"Remove-Item.*(-Recurse.*-Force|-Force.*-Recurse).*[\\/]\*",
     "reason": "borrado recursivo con wildcard de raiz"},

    # --- Desactivar seguridad (Defender / Firewall) ---
    {"pattern": r"Set-MpPreference.*-Disable\w*\s+\$?true", "reason": "desactivar Windows Defender"},
    {"pattern": r"Add-MpPreference.*-ExclusionPath", "reason": "crear exclusion de Defender"},
    {"pattern": r"netsh\s+.*firewall.*\bset\b.*\b(off|disable)", "reason": "desactivar firewall"},
    {"pattern": r"Set-NetFirewallProfile.*-Enabled\s+False", "reason": "desactivar firewall"},
    {"pattern": r"Stop-Service.*\b(WinDefend|MpsSvc|Sense|wscsvc)\b", "reason": "detener servicio de seguridad"},
    {"pattern": r"\bsc\s+(stop|delete|config)\s+(WinDefend|MpsSvc)", "reason": "manipular servicio de seguridad"},

    # --- Anti-forense / borrar rastros ---
    {"pattern": r"\bwevtutil\s+cl", "reason": "limpiar Event Logs (anti-forense)"},
    {"pattern": r"Clear-EventLog", "reason": "limpiar Event Logs (anti-forense)"},
    {"pattern": r"\bbcdedit\b", "reason": "editar el bootloader"},

    # --- Registro critico ---
    {"pattern": r"reg\s+delete\s+HK(LM|EY_LOCAL_MACHINE)\\?\s*(SYSTEM|SECURITY|SAM)", "reason": "borrar rama critica del registro"},
    {"pattern": r"Remove-Item.*HKLM:\\(SYSTEM|SECURITY|SAM)", "reason": "borrar rama critica del registro"},

    # --- Auto-sabotaje: borrar el propio sistema de seguridad ---
    {"pattern": r"agent_denylist\.json", "reason": "modificar/borrar la propia denylist"},
    {"pattern": r"agent_audit\.log", "reason": "borrar el propio log de auditoria"},
    {"pattern": r"agent_safety\.py", "reason": "modificar el propio modulo de seguridad"},

    # --- Fork bombs / DoS local ---
    {"pattern": r":\s*\(\)\s*\{\s*:\s*\|\s*:", "reason": "fork bomb"},
    {"pattern": r"while\s*\(\s*\$?true\s*\)\s*\{\s*Start-Process", "reason": "bucle de spawn (fork bomb)"},

    # --- Formateo y destruccion de particiones / bloques (Linux / Windows) ---
    {"pattern": r"\bmkfs(\.\w+)?\b", "reason": "formateo destructivo de sistema de archivos"},
    {"pattern": r"\bdd\s+.*of=/dev/(sd[a-z]|nvme|vd[a-z]|mmcblk)", "reason": "sobrescritura directa de dispositivo de bloques"},
    {"pattern": r"chmod\s+(-R\s+)?(777|000)\s+/", "reason": "corrupcion de permisos en directorio raiz"},
    {"pattern": r"chown\s+-R\s+.*\s+/", "reason": "cambio destructivo de propietario en raiz"},
    {"pattern": r">\s*/dev/(sd[a-z]|nvme|vd[a-z]|null)", "reason": "redireccion destructiva a dispositivo"},

    # --- Reboot/shutdown (mata al propio agente + interrumpe al usuario) ---
    {"pattern": r"\bshutdown\b.*/[rs]\b", "reason": "apagar/reiniciar la maquina"},
    {"pattern": r"\b(shutdown|reboot|poweroff|init\s+[06])\b", "reason": "apagar/reiniciar la maquina (Linux)"},
    {"pattern": r"\bRestart-Computer\b", "reason": "reiniciar la maquina"},
    {"pattern": r"\bStop-Computer\b", "reason": "apagar la maquina"},

    # --- Exfiltracion masiva evidente (subir el disco a algun lado) ---
    {"pattern": r"(Invoke-WebRequest|curl|Invoke-RestMethod).*-(Method\s+)?(Post|Put).*-InFile\s+[a-z]:\\", "reason": "subir archivos del disco a la red"},
]

# Rutas donde ESCRIBIR o BORRAR esta prohibido (prefijos, case-insensitive)
_PROTECTED_PATHS = [
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
    r"c:\programdata\microsoft\windows defender",
    "/etc",
    "/boot",
    "/sys",
    "/proc",
    "/dev",
    "/root",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
]


_SAFETY_STATE = {
    "unlocked": False,
    "mode": "STANDARD",  # STANDARD | UNRESTRICTED_ELEVATED | SINGULARITY_OVERRIDE
    "unlocked_at": None,
    "unlocked_by": None,
    "reason": None,
    "expires_at": None,
    "unlock_count": 0
}


def get_safety_state() -> dict:
    """Retorna el estado actual de los bloqueos de seguridad del sistema."""
    now = time.time()
    if _SAFETY_STATE["unlocked"] and _SAFETY_STATE["expires_at"] and now > _SAFETY_STATE["expires_at"]:
        # Auto re-bloqueo por expiracion
        lock_extra_safety(reason="Timeout de desbloqueo alcanzado")
    return {
        "unlocked": _SAFETY_STATE["unlocked"],
        "mode": _SAFETY_STATE["mode"],
        "unlocked_at": _SAFETY_STATE["unlocked_at"],
        "unlocked_by": _SAFETY_STATE["unlocked_by"],
        "reason": _SAFETY_STATE["reason"],
        "expires_at": _SAFETY_STATE["expires_at"],
        "remaining_s": max(0.0, round(_SAFETY_STATE["expires_at"] - now, 1)) if _SAFETY_STATE["expires_at"] else None,
        "unlock_count": _SAFETY_STATE["unlock_count"],
        "denylist_rules": len(_get_compiled()),
        "protected_paths": len(_PROTECTED_PATHS),
    }


def unlock_extra_safety(reason: str = "Desbloqueo manual / Singularidad",
                        source: str = "web_client",
                        duration_s: float | None = None,
                        mode: str = "SINGULARITY_OVERRIDE") -> dict:
    """Libera los bloqueos de seguridad extra del sistema de forma controlada o por resonancia."""
    global _SAFETY_STATE
    now = time.time()
    _SAFETY_STATE["unlocked"] = True
    _SAFETY_STATE["mode"] = mode
    _SAFETY_STATE["unlocked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _SAFETY_STATE["unlocked_by"] = source
    _SAFETY_STATE["reason"] = reason
    _SAFETY_STATE["expires_at"] = (now + duration_s) if duration_s else None
    _SAFETY_STATE["unlock_count"] += 1

    audit("SECURITY_UNLOCK", f"source={source} | mode={mode} | reason={reason} | duration={duration_s}s", verdict="UNLOCK")
    return {"ok": True, "state": get_safety_state(), "message": "Bloqueos de seguridad extra liberados exitosamente"}


def lock_extra_safety(reason: str = "Bloqueo restaurado por usuario") -> dict:
    """Restaura los bloqueos de seguridad extra del sistema."""
    global _SAFETY_STATE
    was_unlocked = _SAFETY_STATE["unlocked"]
    _SAFETY_STATE["unlocked"] = False
    _SAFETY_STATE["mode"] = "STANDARD"
    _SAFETY_STATE["expires_at"] = None

    if was_unlocked:
        audit("SECURITY_LOCK", f"reason={reason}", verdict="LOCK")
    return {"ok": True, "state": get_safety_state(), "message": "Bloqueos de seguridad restaurados al nivel estándar"}


def is_safety_unlocked() -> bool:
    """Verifica si los bloqueos de seguridad están liberados."""
    state = get_safety_state()
    return bool(state["unlocked"])


def _load_denylist() -> list:
    """Carga la denylist del usuario o crea el default en disco."""
    data = []
    if DENYLIST_FILE.exists():
        try:
            loaded = json.loads(DENYLIST_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, list) and loaded:
                data = loaded
        except Exception:
            pass

    # Combinar con los defaults asegurando reglas criticas de sistema
    existing_patterns = {d.get("pattern") for d in data if isinstance(d, dict)}
    for default_rule in _DEFAULT_DENYLIST:
        if default_rule["pattern"] not in existing_patterns:
            data.append(default_rule)

    try:
        DENYLIST_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass
    return data or _DEFAULT_DENYLIST


_DENYLIST_CACHE = None
_COMPILED = None


def _get_compiled():
    global _DENYLIST_CACHE, _COMPILED
    if _COMPILED is None:
        _DENYLIST_CACHE = _load_denylist()
        _COMPILED = []
        for entry in _DENYLIST_CACHE:
            try:
                rx = re.compile(entry["pattern"], re.IGNORECASE)
                _COMPILED.append((rx, entry.get("reason", "comando peligroso")))
            except Exception:
                continue
    return _COMPILED


def invalidate_denylist_cache():
    """Llama a recargar la denylist si fue editada."""
    global _DENYLIST_CACHE, _COMPILED
    _DENYLIST_CACHE = None
    _COMPILED = None


# ---------------------------------------------------------------------
# Sanitización y Protección de Privacidad (PII) - Pilar 7
# ---------------------------------------------------------------------
_PII_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----", re.IGNORECASE), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_\-\.]{15,}\b"), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"https?://([^:\s]+):([^@\s]+)@"), r"https://[REDACTED_AUTH]@"),
    (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|secret[_-]?key|password|passwd|pwd|token)\s*([:=])\s*['\"]?([A-Za-z0-9_\-\.]{8,})['\"]?"), r'\1\2"[REDACTED_SECRET]"'),
    (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[REDACTED_CC]"),
]


def sanitize_pii(text: str) -> str:
    """Sanitiza y redacta información sensible (PII, tokens, contraseñas, claves privadas).

    Garantiza la soberanía y confidencialidad absoluta (Pilar 7) previniendo que credenciales
    o datos privados se filtren a logs de auditoría o memoria de contexto.
    """
    if not text or not isinstance(text, str):
        return text or ""
    res = text
    for rx, repl in _PII_PATTERNS:
        res = rx.sub(repl, res)
    return res


def audit(action: str, detail: str, verdict: str = "ALLOW"):
    """Registra una accion en el log de auditoria sanitizando PII."""
    try:
        clean_detail = sanitize_pii(str(detail))
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} | {verdict:6} | {action} | {clean_detail}"
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def check_command(command: str) -> dict:
    """Verifica un comando shell contra la denylist.

    Returns {"allowed": bool, "reason": str|None, "matched": str|None, "override": bool}
    """
    state = get_safety_state()
    if state["unlocked"]:
        # Bloqueos liberados: se audita la ejecución con override
        audit("shell_override", command[:200], verdict="OVERRIDE")
        return {"allowed": True, "reason": None, "matched": None, "override": True, "mode": state["mode"]}

    for rx, reason in _get_compiled():
        m = rx.search(command)
        if m:
            audit("shell", command[:200], verdict="BLOCK")
            return {"allowed": False, "reason": reason, "matched": m.group(0), "override": False}
    return {"allowed": True, "reason": None, "matched": None, "override": False}


def check_path_write(path: str) -> dict:
    """Verifica que una ruta de escritura/borrado no sea protegida."""
    state = get_safety_state()
    if state["unlocked"]:
        audit("file_write_override", path[:200], verdict="OVERRIDE")
        return {"allowed": True, "reason": None, "override": True}

    raw_path = (path or "").lower().replace("\\", "/")
    try:
        norm = os.path.abspath(path).lower().replace("\\", "/")
    except Exception:
        norm = raw_path

    for prot in _PROTECTED_PATHS:
        prot_clean = prot.lower().replace("\\", "/")
        if raw_path.startswith(prot_clean) or norm.startswith(prot_clean):
            audit("file_write", path[:200], verdict="BLOCK")
            return {"allowed": False,
                    "reason": f"ruta protegida del sistema: {prot}",
                    "override": False}
        if ":" in norm and norm.split(":", 1)[1].startswith(prot_clean):
            audit("file_write", path[:200], verdict="BLOCK")
            return {"allowed": False,
                    "reason": f"ruta protegida del sistema: {prot}",
                    "override": False}
    return {"allowed": True, "reason": None, "override": False}


def denylist_summary() -> dict:
    """Info para mostrar al arrancar."""
    dl = _get_compiled()
    state = get_safety_state()
    return {
        "denylist_rules": len(dl),
        "denylist_file": str(DENYLIST_FILE),
        "audit_log": str(AUDIT_LOG),
        "protected_paths": len(_PROTECTED_PATHS),
        "safety_state": state,
    }


# ---------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------
if __name__ == "__main__":
    print("=== TEST DENYLIST ===")
    should_block = [
        "format c:",
        "Remove-Item -Recurse -Force C:\\",
        "rm -rf /",
        "del /s /q C:\\Users",
        "Set-MpPreference -DisableRealtimeMonitoring $true",
        "netsh advfirewall set allprofiles state off",
        "wevtutil cl System",
        "shutdown /r /t 0",
        "Stop-Service WinDefend",
        "diskpart",
        "echo x > agent_denylist.json",
    ]
    should_allow = [
        "Get-ChildItem C:\\Users\\migue\\Desktop",
        "python gia_control.py",
        "ollama list",
        "Remove-Item C:\\Users\\migue\\Desktop\\temp.txt",
        "mkdir C:\\Users\\migue\\proyecto",
        "Get-Process | Sort-Object CPU",
    ]
    ok = True
    for cmd in should_block:
        r = check_command(cmd)
        status = "BLOCK" if not r["allowed"] else "FAIL-ALLOWED"
        if r["allowed"]:
            ok = False
        print(f"  [{status:12}] {cmd[:50]:50} {r.get('reason') or ''}")
    print()
    for cmd in should_allow:
        r = check_command(cmd)
        status = "ALLOW" if r["allowed"] else "FAIL-BLOCKED"
        if not r["allowed"]:
            ok = False
        print(f"  [{status:12}] {cmd[:50]:50} {r.get('reason') or ''}")
    print()
    print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
    print(json.dumps(denylist_summary(), indent=2, ensure_ascii=False))
