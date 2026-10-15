"""
ios_bridge.py - Puente USB a dispositivos iOS (via pymobiledevice3).
====================================================================

Permite al sistema GIA inspeccionar y modificar (dentro de lo que Apple
permite SIN jailbreak) un iPhone/iPad conectado por USB al PC Windows.

LIMITE REAL DE APPLE (importante):
  iOS NO permite ejecutar codigo arbitrario ni controlar la UI (taps) de
  un dispositivo sin jailbreak. Lo que SI se puede via el protocolo
  lockdown/usbmux:
    - Info del dispositivo, bateria, diagnosticos
    - Listar / instalar (.ipa) / desinstalar apps
    - Leer el syslog en vivo
    - Acceso de archivos: carpeta multimedia (fotos) y sandboxes de apps
      que declaren UIFileSharingEnabled
    - Screenshot y servicios de desarrollador (requieren Modo Desarrollador
      activado en el iPhone y, en iOS 17+, un tunel con privilegios admin)
    - Backups

Todo pasa por la capa de auditoria del agente.

Requiere: el iPhone conectado por USB y EMPAREJADO (aceptar "Confiar en
este equipo" en el telefono la primera vez).

CLI equivalente:  python -m pymobiledevice3 <servicio> <accion>
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
VENV_PY = Path(LOCALAPPDATA) / "vw-control" / ".venv" / "Scripts" / "python.exe"
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable

CAPTURE_DIR = Path(LOCALAPPDATA) / "vw-control" / "ios_captures"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

try:
    import agent_safety as _safety
    def _audit(a, d, v="ALLOW"):
        _safety.audit(a, d, verdict=v)
except Exception:
    def _audit(a, d, v="ALLOW"):
        pass


def _run(args: list, timeout: float = 60.0) -> tuple[str, str, int]:
    """Ejecuta `python -m pymobiledevice3 <args>`."""
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        p = subprocess.run([PY, "-m", "pymobiledevice3"] + args,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", timeout=timeout, creationflags=flags)
        return p.stdout or "", p.stderr or "", p.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", 124
    except Exception as e:  # noqa: BLE001
        return "", f"{type(e).__name__}: {e}", 1


def _extract_json(text: str):
    """Extrae el JSON de nivel superior del stdout (pymobiledevice3 a veces
    imprime logs alrededor y sale con codigo != 0 aun con datos validos).
    Toma como raiz el delimitador { o [ que aparezca PRIMERO en el texto,
    para no confundir un array/objeto anidado con la raiz."""
    if not text:
        return None
    idx_obj = text.find("{")
    idx_arr = text.find("[")
    candidates = [(i, o, c) for i, o, c in
                  ((idx_obj, "{", "}"), (idx_arr, "[", "]")) if i >= 0]
    if not candidates:
        return None
    start, opener, closer = min(candidates, key=lambda t: t[0])
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None


# =====================================================================
#  CAPACIDADES
# =====================================================================

def list_devices() -> dict:
    """Dispositivos iOS conectados por USB."""
    out, err, _ = _run(["usbmux", "list"], timeout=20)
    data = _extract_json(out)
    if data is None:
        return {"ok": False, "error": err or "sin salida; conecta y confia en el equipo",
                "devices": []}
    devs = [{"name": d.get("DeviceName"), "udid": d.get("Identifier"),
             "model": d.get("ProductType"), "ios_build": d.get("BuildVersion"),
             "class": d.get("DeviceClass"), "conn": d.get("ConnectionType")}
            for d in (data if isinstance(data, list) else [data])]
    _audit("ios.list_devices", f"{len(devs)} dispositivo(s)")
    return {"ok": True, "count": len(devs), "devices": devs}


def device_info() -> dict:
    """Info detallada del dispositivo (lockdown)."""
    out, err, _ = _run(["lockdown", "info"], timeout=25)
    data = _extract_json(out)
    if data is None:
        return {"ok": False, "error": err or "sin datos"}
    keys = ("DeviceName", "ProductType", "ProductVersion", "BuildVersion",
            "SerialNumber", "UniqueDeviceID", "BatteryCurrentCapacity",
            "PhoneNumber", "WiFiAddress", "TotalDiskCapacity",
            "TotalDataAvailable", "CPUArchitecture")
    slim = {k: data.get(k) for k in keys if k in data}
    _audit("ios.device_info", slim.get("DeviceName", "?"))
    return {"ok": True, "info": slim or data}


def list_apps(user_only: bool = True) -> dict:
    """Apps instaladas. user_only=True omite las del sistema."""
    args = ["apps", "list"]
    out, err, _ = _run(args, timeout=60)
    data = _extract_json(out)
    if data is None:
        return {"ok": False, "error": err or "sin datos"}
    apps = []
    items = data.items() if isinstance(data, dict) else []
    for bundle, meta in items:
        if not isinstance(meta, dict):
            continue
        apptype = meta.get("ApplicationType", "")
        if user_only and apptype != "User":
            continue
        apps.append({"bundle_id": bundle,
                     "name": meta.get("CFBundleDisplayName") or meta.get("CFBundleName"),
                     "version": meta.get("CFBundleShortVersionString"),
                     "type": apptype})
    apps.sort(key=lambda a: (a.get("name") or "").lower())
    _audit("ios.list_apps", f"{len(apps)} apps (user_only={user_only})")
    return {"ok": True, "count": len(apps), "apps": apps}


def install_app(ipa_path: str) -> dict:
    """Instala un .ipa en el dispositivo."""
    if not os.path.isfile(ipa_path):
        return {"ok": False, "error": f"no existe: {ipa_path}"}
    _audit("ios.install_app", ipa_path)
    out, err, rc = _run(["apps", "install", ipa_path], timeout=300)
    ok = rc == 0 or "complete" in (out + err).lower()
    return {"ok": ok, "output": (out or err)[-500:]}


def uninstall_app(bundle_id: str) -> dict:
    """Desinstala una app por bundle id."""
    _audit("ios.uninstall_app", bundle_id, v="ALLOW")
    out, err, rc = _run(["apps", "uninstall", bundle_id], timeout=120)
    ok = rc == 0 or "complete" in (out + err).lower()
    return {"ok": ok, "output": (out or err)[-500:]}


def screenshot(out_path: str = "") -> dict:
    """Captura la pantalla del iPhone. Requiere Modo Desarrollador (iOS 17+
    ademas un tunel con privilegios admin: `pymobiledevice3 remote tunneld`)."""
    if not out_path:
        import time
        out_path = str(CAPTURE_DIR / f"ios_{int(time.time())}.png")
    out, err, rc = _run(["developer", "dvt", "screenshot", out_path], timeout=60)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        _audit("ios.screenshot", out_path)
        return {"ok": True, "path": out_path, "size": os.path.getsize(out_path)}
    return {"ok": False,
            "error": (err or out or "fallo")[-400:],
            "hint": "Activa Modo Desarrollador en el iPhone (Ajustes > "
                    "Privacidad y seguridad > Modo Desarrollador) y, en iOS "
                    "17+, corre 'pymobiledevice3 remote tunneld' como admin."}


def syslog(seconds: float = 5.0, filter_str: str = "") -> dict:
    """Captura el syslog en vivo por N segundos."""
    args = ["syslog", "live"]
    out, err, _ = _run(args, timeout=seconds + 5)
    lines = [l for l in out.splitlines() if (not filter_str or filter_str.lower() in l.lower())]
    _audit("ios.syslog", f"{len(lines)} lineas")
    return {"ok": True, "lines": lines[-200:]}


def battery() -> dict:
    """Estado de bateria via diagnosticos."""
    out, err, _ = _run(["diagnostics", "battery"], timeout=25)
    data = _extract_json(out)
    if data is None:
        info = device_info()
        cap = info.get("info", {}).get("BatteryCurrentCapacity") if info.get("ok") else None
        return {"ok": bool(cap is not None), "battery_pct": cap}
    return {"ok": True, "battery": data}


def list_media(path: str = "/") -> dict:
    """Lista archivos de la carpeta multimedia (fotos/DCIM) via AFC."""
    out, err, _ = _run(["afc", "ls", path], timeout=30)
    if err and not out:
        return {"ok": False, "error": err[-300:]}
    entries = [l.strip() for l in out.splitlines() if l.strip()]
    return {"ok": True, "path": path, "entries": entries[:300]}


def pull_media(remote: str, local: str) -> dict:
    """Descarga un archivo de la carpeta multimedia del iPhone al PC."""
    _audit("ios.pull_media", f"{remote} -> {local}")
    out, err, rc = _run(["afc", "pull", remote, local], timeout=120)
    ok = os.path.exists(local) or rc == 0
    return {"ok": ok, "local": local, "output": (out or err)[-300:]}


def status() -> dict:
    """Diagnostico rapido del puente iOS."""
    d = list_devices()
    return {"pymobiledevice3": True, "devices_connected": d.get("count", 0),
            "devices": d.get("devices", []), "capture_dir": str(CAPTURE_DIR)}


if __name__ == "__main__":
    import argparse
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Puente USB iOS")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    sub.add_parser("devices")
    sub.add_parser("info")
    pa = sub.add_parser("apps"); pa.add_argument("--all", action="store_true")
    sub.add_parser("battery")
    ps = sub.add_parser("screenshot"); ps.add_argument("--out", default="")
    pm = sub.add_parser("media"); pm.add_argument("--path", default="/")
    args = ap.parse_args()

    if args.cmd == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))
    elif args.cmd == "devices":
        print(json.dumps(list_devices(), indent=2, ensure_ascii=False))
    elif args.cmd == "info":
        print(json.dumps(device_info(), indent=2, ensure_ascii=False))
    elif args.cmd == "apps":
        print(json.dumps(list_apps(user_only=not args.all), indent=2, ensure_ascii=False))
    elif args.cmd == "battery":
        print(json.dumps(battery(), indent=2, ensure_ascii=False))
    elif args.cmd == "screenshot":
        print(json.dumps(screenshot(args.out), indent=2, ensure_ascii=False))
    elif args.cmd == "media":
        print(json.dumps(list_media(args.path), indent=2, ensure_ascii=False))
    else:
        ap.print_help()
