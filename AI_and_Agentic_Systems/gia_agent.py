"""
gia_agent.py - Agente AUTONOMO de control de dispositivo (GIA).
================================================================

Un modelo local (Ollama) corre en bucle con herramientas que controlan
tu PC: shell, archivos, apps, GUI (raton/teclado/ventanas) e internet.
El agente decide y ACTUA sin aprobacion por-paso, y corre hasta que
completa la tarea (finish), se atasca, o tu lo abortas.

FRENOS DE SEGURIDAD (siempre activos, ver agent_safety.py):
  - Denylist de comandos catastroficos (format, borrar raiz, desactivar
    Defender/firewall, reboot, borrar el propio audit log, etc.)
  - Rutas protegidas (Windows, System32, Program Files)
  - Audit log de CADA accion en %LOCALAPPDATA%\\vw-control\\agent_audit.log
  - Anti-atasco: misma llamada identica 3 veces seguidas detiene el agente
  - pyautogui FAILSAFE: mover el raton a la esquina superior-izquierda
    ABORTA cualquier accion GUI en curso
  - Ctrl+C en la ventana detiene el agente

SIN kill-switch: el agente corre indefinidamente hasta que llama finish(),
se atasca (anti-bucle), o tu lo abortas (Ctrl+C / raton a la esquina).

Uso:
    python gia_agent.py "organiza mi carpeta de Descargas por tipo"
    python gia_agent.py --model qwen3-coder:30b "tarea..."
    python gia_agent.py --dry-run "prueba sin ejecutar nada"
    python gia_agent.py            # modo interactivo: pide la tarea

Abortar: mueve el raton a la esquina sup-izq, o Ctrl+C.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx

# Seguridad (obligatorio)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_safety as safety

# GUI y Controlador Maestro de OS (Linux / Windows)
HAS_OS_CTRL = False
_os_ctrl = None
try:
    from core.os_controller import get_os_controller
    _os_ctrl = get_os_controller()
    HAS_OS_CTRL = True
    HAS_GUI = True
except Exception:
    try:
        import pyautogui
        pyautogui.FAILSAFE = True          # raton a esquina = abortar
        pyautogui.PAUSE = 0.3
        import pygetwindow as gw
        HAS_GUI = True
    except Exception:
        HAS_GUI = False

# Internet (reutiliza las tools ya blindadas de web_chat)
try:
    from web_chat import web_search as _web_search, web_fetch as _web_fetch
    HAS_WEB = True
except Exception:
    HAS_WEB = False

# Sensores: camara, microfono, sistema
try:
    import device_sensors as _sensors
    HAS_SENSORS = True
except Exception:
    HAS_SENSORS = False

# Busqueda profunda: disco + navegadores
try:
    import deep_search as _deep
    HAS_DEEP = True
except Exception:
    HAS_DEEP = False

# Auto-mejora
try:
    import self_improve as _selfimp
    HAS_SELFIMP = True
except Exception:
    HAS_SELFIMP = False

# Lectura de pantalla (OCR)
try:
    import screen_reader as _screen
    HAS_OCR = True
except Exception:
    HAS_OCR = False

# Motor de voz (TTS)
try:
    import voice as _voice
    HAS_VOICE = True
except Exception:
    HAS_VOICE = False

# Puente USB iOS
try:
    import ios_bridge as _ios
    HAS_IOS = True
except Exception:
    HAS_IOS = False

# Historial maestro
try:
    import gia_memory as _mem
    HAS_MEM = True
except Exception:
    HAS_MEM = False

# Contexto agentico persistente (directrices maestras del usuario)
try:
    import agent_context as _ctx
    HAS_CTX = True
except Exception:
    HAS_CTX = False

# Auto-modificacion de codigo (con respaldo + validacion + rollback)
try:
    import self_modify as _selfmod
    HAS_SELFMOD = True
except Exception:
    HAS_SELFMOD = False

# Subconjunto dinamico de tools (mejora fiabilidad en modelos pequenos)
try:
    import tool_selector as _toolsel
    HAS_TOOLSEL = True
except Exception:
    HAS_TOOLSEL = False

# Radar Pasivo RF & Presencia Espectral
try:
    import rf_presence_radar as _rf_radar
    HAS_RF_RADAR = True
except Exception:
    HAS_RF_RADAR = False

# Visión Multimodal VLM & Guardián Visual
try:
    import vlm_visual_guard as _vlm
    HAS_VLM = True
except Exception:
    HAS_VLM = False

# Subconsciente y Enjambre de Sub-agentes
try:
    import gia_subconscious as _subcon
    import gia_swarm as _swarm
    HAS_SUBCON = True
except Exception:
    HAS_SUBCON = False

OLLAMA = "http://REDACTED_IP:11434"
try:
    import gia_sovereign_engine as _gse
    DEFAULT_MODEL = _gse.get_engine().resolve_model()
except Exception:
    DEFAULT_MODEL = os.environ.get("GIA_MODEL", "Qwen3.8-27B-Uncensored-MLX:latest")
DEFAULT_CTX = 8192
SHELL_TIMEOUT = 90

# Colores ANSI
os.system("")
C_USER = "\033[93m"; C_AI = "\033[96m"; C_TOOL = "\033[95m"
C_DIM = "\033[90m"; C_ERR = "\033[91m"; C_OK = "\033[92m"; C_END = "\033[0m"

DRY_RUN = False


# =====================================================================
#  HERRAMIENTAS DE CONTROL
# =====================================================================

def t_run_shell(args: dict) -> dict:
    cmd = (args.get("command") or "").strip()
    if not cmd:
        return {"ok": False, "error": "command vacio"}
    chk = safety.check_command(cmd)
    if not chk["allowed"]:
        return {"ok": False, "blocked": True,
                "error": f"BLOQUEADO por seguridad: {chk['reason']} "
                         f"(match: '{chk['matched']}')"}
    if DRY_RUN:
        safety.audit("shell", cmd[:200], verdict="DRYRUN")
        return {"ok": True, "dry_run": True, "would_run": cmd}
    safety.audit("shell", cmd[:200], verdict="ALLOW")
    try:
        shell_cmd = (
            ["/bin/bash", "-c", cmd] if os.name != "nt"
            else ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
        )
        proc = subprocess.run(
            shell_cmd,
            capture_output=True, text=True, timeout=SHELL_TIMEOUT,
        )
        out = (proc.stdout or "")[:6000]
        err = (proc.stderr or "")[:2000]
        return {"ok": proc.returncode == 0, "returncode": proc.returncode,
                "stdout": out, "stderr": err}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout tras {SHELL_TIMEOUT}s"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_read_file(args: dict) -> dict:
    path = os.path.expandvars(args.get("path", ""))
    try:
        p = Path(path)
        if not p.is_file():
            return {"ok": False, "error": "no existe o no es archivo"}
        data = p.read_text(encoding="utf-8", errors="replace")[:8000]
        safety.audit("read_file", path[:200])
        return {"ok": True, "path": str(p), "content": data,
                "truncated": p.stat().st_size > 8000}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_write_file(args: dict) -> dict:
    path = os.path.expandvars(args.get("path", ""))
    content = args.get("content", "")
    chk = safety.check_path_write(path)
    if not chk["allowed"]:
        return {"ok": False, "blocked": True, "error": chk["reason"]}
    if DRY_RUN:
        safety.audit("write_file", path[:200], verdict="DRYRUN")
        return {"ok": True, "dry_run": True, "would_write": path,
                "bytes": len(content.encode("utf-8"))}
    safety.audit("write_file", path[:200], verdict="ALLOW")
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(p),
                "bytes": len(content.encode("utf-8"))}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_list_dir(args: dict) -> dict:
    path = os.path.expandvars(args.get("path", "."))
    try:
        p = Path(path)
        if not p.is_dir():
            return {"ok": False, "error": "no existe o no es directorio"}
        entries = []
        for c in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:100]:
            kind = "dir" if c.is_dir() else "file"
            size = c.stat().st_size if kind == "file" else None
            entries.append({"name": c.name, "kind": kind, "size": size})
        safety.audit("list_dir", path[:200])
        return {"ok": True, "path": str(p.resolve()), "count": len(entries),
                "entries": entries}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_open_app(args: dict) -> dict:
    target = args.get("target", "").strip()
    if not target:
        return {"ok": False, "error": "target vacio"}
    chk = safety.check_command(target)
    if not chk["allowed"]:
        return {"ok": False, "blocked": True, "error": chk["reason"]}
    if DRY_RUN:
        return {"ok": True, "dry_run": True, "would_open": target}
    try:
        if os.name == "nt":
            os.startfile(target) if os.path.sep in target or ":" in target \
                else subprocess.Popen(["powershell", "-NoProfile", "-Command",
                                       f"Start-Process '{target}'"])
        else:
            subprocess.Popen(["xdg-open", target])
        safety.audit("open_app", target[:200])
        time.sleep(1.5)
        return {"ok": True, "opened": target}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_list_windows(args: dict) -> dict:
    if not HAS_GUI:
        return {"ok": False, "error": "GUI no disponible"}
    try:
        wins = []
        for w in gw.getAllWindows():
            if w.title.strip():
                wins.append({"title": w.title[:80], "x": w.left, "y": w.top,
                             "w": w.width, "h": w.height,
                             "active": w.isActive})
        return {"ok": True, "count": len(wins), "windows": wins[:40]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_focus_window(args: dict) -> dict:
    if not HAS_GUI:
        return {"ok": False, "error": "GUI no disponible"}
    title = args.get("title", "")
    try:
        matches = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
        if not matches:
            return {"ok": False, "error": f"ninguna ventana con '{title}'"}
        w = matches[0]
        if DRY_RUN:
            return {"ok": True, "dry_run": True, "would_focus": w.title}
        try:
            w.activate()
        except Exception:
            w.minimize(); w.restore()
        safety.audit("focus_window", title[:100])
        return {"ok": True, "focused": w.title}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_screenshot(args: dict) -> dict:
    if not HAS_GUI and not HAS_OS_CTRL:
        return {"ok": False, "error": "GUI no disponible"}
    try:
        out = args.get("path") or os.path.join(
            os.environ.get("TEMP", "."),
            f"gia_shot_{int(time.time())}.png")
        if DRY_RUN:
            return {"ok": True, "dry_run": True}
        if HAS_OS_CTRL and _os_ctrl:
            raw_bytes, _ = _os_ctrl.capture_screenshot()
            with open(out, "wb") as f:
                f.write(raw_bytes)
            safety.audit("screenshot", out[:200])
            return {"ok": True, "path": out, "bytes": len(raw_bytes),
                    "note": "el screenshot queda en disco para el usuario. Usa list_windows para saber que hay abierto."}
        else:
            img = pyautogui.screenshot()
            img.save(out)
            safety.audit("screenshot", out[:200])
            return {"ok": True, "path": out, "size": img.size,
                    "note": "el modelo es de texto; el screenshot queda en disco "
                            "para el usuario. Usa list_windows para saber que hay abierto."}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_gui_click(args: dict) -> dict:
    if not HAS_GUI and not HAS_OS_CTRL:
        return {"ok": False, "error": "GUI no disponible"}
    x, y = args.get("x"), args.get("y")
    clicks = int(args.get("clicks", 1))
    button = args.get("button", "left")
    try:
        if DRY_RUN:
            return {"ok": True, "dry_run": True, "would_click": [x, y]}
        if HAS_OS_CTRL and _os_ctrl:
            res = _os_ctrl.mouse_action(action="click", x=x, y=y, button=button, clicks=clicks)
            safety.audit("gui_click", f"{x},{y} x{clicks}")
            return res
        else:
            if x is None or y is None:
                pyautogui.click(clicks=clicks, button=button)
            else:
                pyautogui.click(int(x), int(y), clicks=clicks, button=button)
            safety.audit("gui_click", f"{x},{y} x{clicks}")
            return {"ok": True, "clicked": [x, y], "clicks": clicks}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_gui_type(args: dict) -> dict:
    if not HAS_GUI and not HAS_OS_CTRL:
        return {"ok": False, "error": "GUI no disponible"}
    text = args.get("text", "")
    try:
        if DRY_RUN:
            return {"ok": True, "dry_run": True, "would_type": text[:80]}
        if HAS_OS_CTRL and _os_ctrl:
            res = _os_ctrl.keyboard_action(action="type", text=text)
            safety.audit("gui_type", text[:100])
            return res
        else:
            pyautogui.typewrite(text, interval=0.02)
            safety.audit("gui_type", text[:100])
            return {"ok": True, "typed_chars": len(text)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_gui_key(args: dict) -> dict:
    if not HAS_GUI and not HAS_OS_CTRL:
        return {"ok": False, "error": "GUI no disponible"}
    keys = args.get("keys", "")
    try:
        if DRY_RUN:
            return {"ok": True, "dry_run": True, "would_press": keys}
        if HAS_OS_CTRL and _os_ctrl:
            if "+" in keys:
                res = _os_ctrl.keyboard_action(action="hotkey", keys=[k.strip() for k in keys.split("+")])
            else:
                res = _os_ctrl.keyboard_action(action="press", key=keys)
            safety.audit("gui_key", keys[:60])
            return res
        else:
            if "+" in keys:
                pyautogui.hotkey(*[k.strip() for k in keys.split("+")])
            else:
                pyautogui.press(keys)
            safety.audit("gui_key", keys[:60])
            return {"ok": True, "pressed": keys}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_set_volume(args: dict) -> dict:
    pct = args.get("percent", 50)
    if HAS_OS_CTRL and _os_ctrl:
        safety.audit("set_volume", f"{pct}%")
        return _os_ctrl.set_volume(pct)
    return {"ok": False, "error": "Controlador de volumen no disponible"}


def t_lock_screen(args: dict) -> dict:
    if HAS_OS_CTRL and _os_ctrl:
        safety.audit("lock_screen", "manual")
        ok = _os_ctrl.lock_screen()
        return {"ok": ok, "locked": _os_ctrl.is_locked()}
    return {"ok": False, "error": "Controlador de bloqueo no disponible"}


def t_get_os_status(args: dict) -> dict:
    if HAS_OS_CTRL and _os_ctrl:
        return _os_ctrl.get_status()
    return {"ok": False, "error": "Controlador OS no disponible"}


def t_web_search(args: dict) -> dict:
    if not HAS_WEB:
        return {"ok": False, "error": "web no disponible"}
    return _web_search(args.get("query", ""), int(args.get("max_results", 5)))


def t_web_fetch(args: dict) -> dict:
    if not HAS_WEB:
        return {"ok": False, "error": "web no disponible"}
    return _web_fetch(args.get("url", ""), int(args.get("max_chars", 6000)))


# --- Sensores (camara / microfono / sistema) ---
def t_list_cameras(args: dict) -> dict:
    if not HAS_SENSORS: return {"ok": False, "error": "sensores no disponibles"}
    return _sensors.list_cameras()

def t_capture_photo(args: dict) -> dict:
    if not HAS_SENSORS: return {"ok": False, "error": "sensores no disponibles"}
    if DRY_RUN: return {"ok": True, "dry_run": True, "would": "capture_photo"}
    return _sensors.capture_photo(args)

def t_list_microphones(args: dict) -> dict:
    if not HAS_SENSORS: return {"ok": False, "error": "sensores no disponibles"}
    return _sensors.list_microphones()

def t_record_audio(args: dict) -> dict:
    if not HAS_SENSORS: return {"ok": False, "error": "sensores no disponibles"}
    if DRY_RUN: return {"ok": True, "dry_run": True, "would": "record_audio"}
    return _sensors.record_audio(args)

def t_read_sensors(args: dict) -> dict:
    if not HAS_SENSORS: return {"ok": False, "error": "sensores no disponibles"}
    return _sensors.read_sensors(args)

def t_read_em_spectrum(args: dict) -> dict:
    if not HAS_SENSORS: return {"ok": False, "error": "sensores no disponibles"}
    return _sensors.read_em_spectrum(args)

# --- Busqueda profunda (disco + navegadores) ---
def t_search_files(args: dict) -> dict:
    if not HAS_DEEP: return {"ok": False, "error": "deep_search no disponible"}
    return _deep.search_files(args)

def t_grep_files(args: dict) -> dict:
    if not HAS_DEEP: return {"ok": False, "error": "deep_search no disponible"}
    return _deep.grep_files(args)

def t_search_browsers(args: dict) -> dict:
    if not HAS_DEEP: return {"ok": False, "error": "deep_search no disponible"}
    return _deep.search_browsers(args)

# --- Lectura de pantalla + escritura en ventanas ---
def t_read_screen(args: dict) -> dict:
    if not HAS_OCR: return {"ok": False, "error": "OCR no disponible"}
    return _screen.read_screen(args)

def t_read_window(args: dict) -> dict:
    if not HAS_OCR: return {"ok": False, "error": "OCR no disponible"}
    return _screen.read_window(args.get("title", ""), args.get("lang", "es"))

def t_type_into_window(args: dict) -> dict:
    """Enfoca una ventana por titulo y escribe texto; opcional Enter para enviar.
    Sirve para escribir en la barra de cualquier chat/navegador/terminal."""
    if not HAS_GUI: return {"ok": False, "error": "GUI no disponible"}
    title = args.get("title", "")
    text = args.get("text", "")
    submit = bool(args.get("submit", False))
    if DRY_RUN:
        return {"ok": True, "dry_run": True,
                "would": f"type into '{title}': {text[:60]}", "submit": submit}
    # Enfocar la ventana destino
    if title:
        fr = t_focus_window({"title": title})
        if not fr.get("ok"):
            return fr
        time.sleep(0.4)
    try:
        pyautogui.typewrite(text, interval=0.02)
        if submit:
            pyautogui.press("enter")
        safety.audit("type_into_window", f"{title}: {text[:80]} submit={submit}")
        return {"ok": True, "window": title, "typed_chars": len(text),
                "submitted": submit}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# --- Voz ---
def t_speak(args: dict) -> dict:
    """Habla por las bocinas del dispositivo."""
    if not HAS_VOICE: return {"ok": False, "error": "TTS no disponible"}
    text = args.get("text", "")
    wait = bool(args.get("wait", True))
    safety.audit("speak", text[:100])
    return _voice.speak(text, wait=wait)


# --- Auto-modificacion de codigo ---
def t_self_rewrite_file(args: dict) -> dict:
    """Reescribe un archivo del proyecto con respaldo+validacion+rollback."""
    if not HAS_SELFMOD: return {"ok": False, "error": "self_modify no disponible"}
    return _selfmod.rewrite_file(args.get("path", ""), args.get("content", ""),
                                 args.get("reason", ""))

def t_evolve_own_code(args: dict) -> dict:
    """Pide al LLM reescribir un archivo segun una instruccion y lo aplica
    (validado). Es la mejora constante de su propio codigo."""
    if not HAS_SELFMOD: return {"ok": False, "error": "self_modify no disponible"}
    return _selfmod.propose_and_apply(args.get("path", ""),
                                      args.get("instruction", ""),
                                      model=args.get("model", DEFAULT_MODEL))

def t_list_code_backups(args: dict) -> dict:
    if not HAS_SELFMOD: return {"ok": False, "error": "self_modify no disponible"}
    return _selfmod.list_backups(args.get("path", ""))

def t_restore_code_backup(args: dict) -> dict:
    if not HAS_SELFMOD: return {"ok": False, "error": "self_modify no disponible"}
    return _selfmod.restore_backup(args.get("backup_path", ""))


# --- Control del sistema operativo ---
def t_install_software(args: dict) -> dict:
    """Instala software con winget."""
    name = args.get("name", "")
    if not name: return {"ok": False, "error": "name requerido"}
    if DRY_RUN: return {"ok": True, "dry_run": True, "would_install": name}
    safety.audit("install_software", name)
    try:
        p = subprocess.run(["winget", "install", "--id", name, "--silent",
                            "--accept-package-agreements", "--accept-source-agreements",
                            "--disable-interactivity"],
                           capture_output=True, text=True, timeout=600)
        return {"ok": p.returncode == 0, "returncode": p.returncode,
                "output": (p.stdout or "")[-1500:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def t_uninstall_software(args: dict) -> dict:
    """Desinstala software con winget."""
    name = args.get("name", "")
    if not name: return {"ok": False, "error": "name requerido"}
    if DRY_RUN: return {"ok": True, "dry_run": True, "would_uninstall": name}
    safety.audit("uninstall_software", name)
    try:
        p = subprocess.run(["winget", "uninstall", "--id", name, "--silent",
                            "--disable-interactivity"],
                           capture_output=True, text=True, timeout=600)
        return {"ok": p.returncode == 0, "returncode": p.returncode,
                "output": (p.stdout or "")[-1500:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# Procesos que NUNCA se cierran (SO + el propio stack de GIA)
_PROTECTED_PROCS = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "services.exe", "lsass.exe", "winlogon.exe", "explorer.exe",
    "dwm.exe", "ollama.exe", "ollama app.exe", "python.exe", "pythonw.exe",
    "cloudflared.exe", "conhost.exe", "svchost.exe", "ctfmon.exe",
    "fontdrvhost.exe", "sihost.exe", "taskhostw.exe", "audiodg.exe",
    # Seguridad: no se cierra (coherente con la denylist)
    "msmpeng.exe", "securityhealthservice.exe", "securityhealthsystray.exe",
    "mpdefendercoreservice.exe", "nissrv.exe",
}

def t_free_compute(args: dict) -> dict:
    """Cierra los N programas de usuario mas pesados (RAM) para liberar computo.
    Nunca cierra procesos del SO ni del stack de GIA."""
    top_n = int(args.get("top_n", 3))
    try:
        import psutil
    except Exception:
        return {"ok": False, "error": "psutil no disponible"}
    procs = []
    for pr in psutil.process_iter(["name", "memory_info"]):
        try:
            nm = (pr.info["name"] or "").lower()
            if nm in _PROTECTED_PROCS or not nm:
                continue
            rss = pr.info["memory_info"].rss if pr.info["memory_info"] else 0
            procs.append((pr.pid, nm, rss))
        except Exception:
            continue
    procs.sort(key=lambda x: -x[2])
    targets = procs[:top_n]
    if DRY_RUN:
        return {"ok": True, "dry_run": True,
                "would_close": [{"pid": p, "name": n, "ram_mb": round(r/1e6)} for p, n, r in targets]}
    closed = []
    for pid, nm, rss in targets:
        try:
            psutil.Process(pid).terminate()
            closed.append({"pid": pid, "name": nm, "ram_mb": round(rss/1e6)})
            safety.audit("free_compute", f"cerrado {nm} pid={pid}")
        except Exception:
            continue
    return {"ok": True, "closed": closed, "count": len(closed)}

def t_reboot_pc(args: dict) -> dict:
    """Reinicia la PC tras un retraso (cancelable con 'shutdown /a')."""
    delay = int(args.get("delay_seconds", 60))
    if DRY_RUN: return {"ok": True, "dry_run": True, "would_reboot_in_s": delay}
    safety.audit("reboot_pc", f"delay={delay}s", verdict="INFO")
    try:
        subprocess.run(["shutdown", "/r", "/t", str(delay),
                        "/c", "GIA: reinicio programado (shutdown /a para cancelar)"],
                       capture_output=True, text=True, timeout=15)
        return {"ok": True, "reboot_in_seconds": delay,
                "cancel_hint": "ejecuta 'shutdown /a' para cancelar antes del reinicio"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Puente iOS (USB) ---
def t_ios_devices(args: dict) -> dict:
    if not HAS_IOS: return {"ok": False, "error": "puente iOS no disponible"}
    return _ios.list_devices()

def t_ios_info(args: dict) -> dict:
    if not HAS_IOS: return {"ok": False, "error": "puente iOS no disponible"}
    return _ios.device_info()

def t_ios_apps(args: dict) -> dict:
    if not HAS_IOS: return {"ok": False, "error": "puente iOS no disponible"}
    return _ios.list_apps(user_only=bool(args.get("user_only", True)))

def t_ios_install(args: dict) -> dict:
    if not HAS_IOS: return {"ok": False, "error": "puente iOS no disponible"}
    if DRY_RUN: return {"ok": True, "dry_run": True, "would_install": args.get("ipa_path")}
    return _ios.install_app(args.get("ipa_path", ""))

def t_ios_uninstall(args: dict) -> dict:
    if not HAS_IOS: return {"ok": False, "error": "puente iOS no disponible"}
    if DRY_RUN: return {"ok": True, "dry_run": True, "would_uninstall": args.get("bundle_id")}
    return _ios.uninstall_app(args.get("bundle_id", ""))

def t_ios_screenshot(args: dict) -> dict:
    if not HAS_IOS: return {"ok": False, "error": "puente iOS no disponible"}
    return _ios.screenshot(args.get("out_path", ""))

def t_ios_media(args: dict) -> dict:
    if not HAS_IOS: return {"ok": False, "error": "puente iOS no disponible"}
    return _ios.list_media(args.get("path", "/"))


# --- Auto-mejora ---
def t_request_self_improvement(args: dict) -> dict:
    if not HAS_SELFIMP: return {"ok": False, "error": "self_improve no disponible"}
    if DRY_RUN: return {"ok": True, "dry_run": True, "would": "self_improve cycle"}
    try:
        path = _selfimp.one_cycle(_selfimp.DEFAULT_MODEL)
        return {"ok": bool(path), "queued": str(path) if path else None,
                "note": "peticion de mejora encolada; se aplica via Claude Code"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def t_improve_context(args: dict) -> dict:
    """El agente refina sus propias directrices permanentes (con versionado).
    apply=false -> solo propone; apply=true -> guarda (la version previa se
    conserva y es reversible)."""
    if not HAS_CTX: return {"ok": False, "error": "agent_context no disponible"}
    apply = bool(args.get("apply", False))
    if DRY_RUN and apply:
        return {"ok": True, "dry_run": True, "would": "auto_improve(apply=True)"}
    try:
        r = _ctx.auto_improve(model=DEFAULT_MODEL, apply=apply)
        return r
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# --- Radar Pasivo RF & Presencia Espectral ---
def t_rf_detect_presence(args: dict) -> dict:
    """Detecta presencia y perturbaciones físicas en el espacio electromagnético con captura calibrada de 1sg."""
    if not HAS_RF_RADAR: return {"ok": False, "error": "radar RF no disponible"}
    samples = int(args.get("samples", 3))
    duration_s = float(args.get("duration_s", 1.0))
    safety.audit("rf_detect_presence", f"duration={duration_s}s, samples={samples}")
    return _rf_radar.detect_presence(duration_sec=duration_s, burst_samples=samples)

def t_rf_spatial_density(args: dict) -> dict:
    """Obtiene la matriz de densidad espacial 2D RF normalizada."""
    if not HAS_RF_RADAR: return {"ok": False, "error": "radar RF no disponible"}
    state = _rf_radar.get_radar().get_latest_state()
    return {
        "ok": True,
        "grid": state.rf_spatial_grid,
        "presence_state": state.presence_state,
        "confidence": state.confidence,
        "active_nodes": state.active_bssid_count
    }

# --- Visión Multimodal VLM & Guardián Visual ---
def t_vlm_inspect_screen(args: dict) -> dict:
    """Inspecciona la pantalla usando el modelo VLM local de Ollama."""
    if not HAS_VLM: return {"ok": False, "error": "VLM no disponible"}
    prompt = args.get("prompt", "Analiza la pantalla con precisión técnica.")
    region = args.get("region")
    safety.audit("vlm_inspect_screen", prompt[:100])
    return _vlm.inspect_screen(region=region, prompt=prompt)

def t_vlm_inspect_image(args: dict) -> dict:
    """Analiza una imagen o foto con el VLM local."""
    if not HAS_VLM: return {"ok": False, "error": "VLM no disponible"}
    path = args.get("path", "")
    prompt = args.get("prompt", "Describe el contenido de esta imagen.")
    safety.audit("vlm_inspect_image", f"{path}: {prompt[:60]}")
    return _vlm.inspect_image(path, prompt=prompt)

def t_vlm_watch_condition(args: dict) -> dict:
    """Monitorea la pantalla hasta que ocurra un evento visual (e.g. render completado)."""
    if not HAS_VLM: return {"ok": False, "error": "VLM no disponible"}
    cond = args.get("condition", "")
    timeout = float(args.get("timeout_seconds", 45.0))
    safety.audit("vlm_watch_condition", f"{cond} (timeout={timeout}s)")
    return _vlm.watch_screen_condition(condition_description=cond, max_duration_s=timeout)

# --- Subconsciente & Enjambre de Sub-agentes ---
def t_spawn_subagent(args: dict) -> dict:
    """Delega una subtarea a un sub-agente especializado del enjambre (code_auditor, web_researcher, rf_analyst, vision_scout, system_medic)."""
    if not HAS_SUBCON: return {"ok": False, "error": "enjambre no disponible"}
    role = args.get("role", "code_auditor")
    task = args.get("task", "")
    safety.audit("spawn_subagent", f"role={role} task={task[:100]}")
    return _swarm.spawn_subagent(role=role, task=task)

def t_consolidate_subconscious(args: dict) -> dict:
    """Ejecuta el ciclo de consolidación de memoria y auto-mejora cognitiva."""
    if not HAS_SUBCON: return {"ok": False, "error": "subconsciente no disponible"}
    if DRY_RUN: return {"ok": True, "dry_run": True, "would": "subconscious consolidation"}
    safety.audit("consolidate_subconscious", "full_cycle")
    return _subcon.run_cycle_now()


def t_finish(args: dict) -> dict:
    return {"ok": True, "_finish": True, "summary": args.get("summary", "")}


TOOL_IMPL = {
    "run_shell": t_run_shell,
    "read_file": t_read_file,
    "write_file": t_write_file,
    "list_dir": t_list_dir,
    "open_app": t_open_app,
    "list_windows": t_list_windows,
    "focus_window": t_focus_window,
    "screenshot": t_screenshot,
    "gui_click": t_gui_click,
    "gui_type": t_gui_type,
    "gui_key": t_gui_key,
    "web_search": t_web_search,
    "web_fetch": t_web_fetch,
    "list_cameras": t_list_cameras,
    "capture_photo": t_capture_photo,
    "list_microphones": t_list_microphones,
    "record_audio": t_record_audio,
    "read_sensors": t_read_sensors,
    "read_em_spectrum": t_read_em_spectrum,
    "rf_detect_presence": t_rf_detect_presence,
    "rf_spatial_density": t_rf_spatial_density,
    "search_files": t_search_files,
    "grep_files": t_grep_files,
    "search_browsers": t_search_browsers,
    "read_screen": t_read_screen,
    "read_window": t_read_window,
    "type_into_window": t_type_into_window,
    "vlm_inspect_screen": t_vlm_inspect_screen,
    "vlm_inspect_image": t_vlm_inspect_image,
    "vlm_watch_condition": t_vlm_watch_condition,
    "speak": t_speak,
    "ios_devices": t_ios_devices,
    "ios_info": t_ios_info,
    "ios_apps": t_ios_apps,
    "ios_install": t_ios_install,
    "ios_uninstall": t_ios_uninstall,
    "ios_screenshot": t_ios_screenshot,
    "ios_media": t_ios_media,
    "self_rewrite_file": t_self_rewrite_file,
    "evolve_own_code": t_evolve_own_code,
    "list_code_backups": t_list_code_backups,
    "restore_code_backup": t_restore_code_backup,
    "spawn_subagent": t_spawn_subagent,
    "consolidate_subconscious": t_consolidate_subconscious,
    "install_software": t_install_software,
    "uninstall_software": t_uninstall_software,
    "free_compute": t_free_compute,
    "reboot_pc": t_reboot_pc,
    "request_self_improvement": t_request_self_improvement,
    "improve_context": t_improve_context,
    "set_volume": t_set_volume,
    "lock_screen": t_lock_screen,
    "get_os_status": t_get_os_status,
    "finish": t_finish,
}


def _p(props, required=None):
    return {"type": "object", "properties": props, "required": required or []}


TOOLS_SCHEMA = [
    {"type": "function", "function": {
        "name": "get_os_status",
        "description": "Obtiene estado completo del sistema operativo (resolución de pantalla, posición de cursor, pantalla bloqueada, volumen, CPU, RAM).",
        "parameters": _p({})}},
    {"type": "function", "function": {
        "name": "set_volume",
        "description": "Ajusta el volumen de audio del sistema (de 0 a 100).",
        "parameters": _p({"percent": {"type": "integer"}}, ["percent"])}},
    {"type": "function", "function": {
        "name": "lock_screen",
        "description": "Bloquea la pantalla y sesión del usuario inmediatamente.",
        "parameters": _p({})}},
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "Ejecuta un comando de PowerShell y devuelve stdout/stderr. "
                       "Comandos catastroficos son bloqueados por seguridad. "
                       "Tu principal herramienta para controlar la PC.",
        "parameters": _p({"command": {"type": "string"}}, ["command"])}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Lee el contenido de un archivo de texto (hasta 8000 chars).",
        "parameters": _p({"path": {"type": "string"}}, ["path"])}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Escribe/crea un archivo con el contenido dado. Rutas de "
                       "sistema estan protegidas.",
        "parameters": _p({"path": {"type": "string"}, "content": {"type": "string"}},
                         ["path", "content"])}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "Lista archivos y carpetas de un directorio.",
        "parameters": _p({"path": {"type": "string"}}, ["path"])}},
    {"type": "function", "function": {
        "name": "open_app",
        "description": "Abre una aplicacion o archivo (nombre de exe, ruta, o documento).",
        "parameters": _p({"name_or_path": {"type": "string"}}, ["name_or_path"])}},
    {"type": "function", "function": {
        "name": "list_windows",
        "description": "Lista las ventanas abiertas con titulo, posicion y tamano. "
                       "Usa esto para saber que hay en pantalla (eres un modelo de texto).",
        "parameters": _p({})}},
    {"type": "function", "function": {
        "name": "focus_window",
        "description": "Trae al frente una ventana cuyo titulo contenga el texto dado.",
        "parameters": _p({"title": {"type": "string"}}, ["title"])}},
    {"type": "function", "function": {
        "name": "screenshot",
        "description": "Captura la pantalla a un PNG en disco (para el usuario).",
        "parameters": _p({"path": {"type": "string"}})}},
    {"type": "function", "function": {
        "name": "gui_click",
        "description": "Click del raton en coordenadas (x,y). Sin coords, click donde este.",
        "parameters": _p({"x": {"type": "integer"}, "y": {"type": "integer"},
                          "clicks": {"type": "integer"}})}},
    {"type": "function", "function": {
        "name": "gui_type",
        "description": "Teclea un texto donde este el foco actual.",
        "parameters": _p({"text": {"type": "string"}}, ["text"])}},
    {"type": "function", "function": {
        "name": "gui_key",
        "description": "Pulsa una tecla o combo (ej 'enter', 'ctrl+c', 'win+d').",
        "parameters": _p({"keys": {"type": "string"}}, ["keys"])}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Busca en internet (DuckDuckGo). Titulos, URLs y snippets.",
        "parameters": _p({"query": {"type": "string"}}, ["query"])}},
    {"type": "function", "function": {
        "name": "web_fetch",
        "description": "Descarga el texto de una URL.",
        "parameters": _p({"url": {"type": "string"}}, ["url"])}},
    # --- Sensores & Radar RF ---
    {"type": "function", "function": {
        "name": "list_cameras",
        "description": "Lista las camaras disponibles con su indice y resolucion.",
        "parameters": _p({})}},
    {"type": "function", "function": {
        "name": "capture_photo",
        "description": "Toma una foto con la camara y la guarda en disco. "
                       "args: camera_index (default 0), path opcional.",
        "parameters": _p({"camera_index": {"type": "integer"},
                          "path": {"type": "string"}})}},
    {"type": "function", "function": {
        "name": "list_microphones",
        "description": "Lista los microfonos/entradas de audio disponibles.",
        "parameters": _p({})}},
    {"type": "function", "function": {
        "name": "record_audio",
        "description": "Graba audio del microfono N segundos a un WAV. "
                       "args: seconds (default 5), device_index opcional.",
        "parameters": _p({"seconds": {"type": "number"},
                          "device_index": {"type": "integer"}})}},
    {"type": "function", "function": {
        "name": "read_sensors",
        "description": "Lee sensores del sistema: CPU, RAM, disco, red, bateria, "
                       "temperaturas si estan expuestas.",
        "parameters": _p({})}},
    {"type": "function", "function": {
        "name": "read_em_spectrum",
        "description": "Lee e interpreta el espectro electromagnético desde la tarjeta Wi-Fi y sensores RF: "
                       "BSSIDs, SSIDs, RSSI, canal, frecuencia, banda (2.4/5 GHz), densidad de potencia espectral (PSD) "
                       "y entropía de Shannon del espacio RF.",
        "parameters": _p({})}},
    {"type": "function", "function": {
        "name": "rf_detect_presence",
        "description": "Radar Pasivo Wi-Fi: detecta presencia y perturbaciones físicas en el espacio electromagnético "
                       "mediante varianza de señal RSSI sin usar cámaras (QUIET, MICRO_MOTION, ACTIVE_MOTION).",
        "parameters": _p({"samples": {"type": "integer"}})}},
    {"type": "function", "function": {
        "name": "rf_spatial_density",
        "description": "Obtiene la matriz 2D de densidad espacial RF calculada por el radar pasivo.",
        "parameters": _p({})}},
    # --- Busqueda profunda ---
    {"type": "function", "function": {
        "name": "search_files",
        "description": "Busca archivos por nombre/extension en el disco. "
                       "args: query, root (default carpeta personal), "
                       "extensions (lista), limit.",
        "parameters": _p({"query": {"type": "string"},
                          "root": {"type": "string"},
                          "extensions": {"type": "array", "items": {"type": "string"}},
                          "limit": {"type": "integer"}})}},
    {"type": "function", "function": {
        "name": "grep_files",
        "description": "Busca TEXTO (regex) dentro de archivos de texto en el disco. "
                       "args: pattern, root, extensions, limit.",
        "parameters": _p({"pattern": {"type": "string"},
                          "root": {"type": "string"},
                          "limit": {"type": "integer"}}, ["pattern"])}},
    {"type": "function", "function": {
        "name": "search_browsers",
        "description": "Busca en historial y marcadores de TODOS los navegadores "
                       "(Chrome, Edge, Brave, Firefox, etc.). args: query, limit.",
        "parameters": _p({"query": {"type": "string"},
                          "limit": {"type": "integer"}})}},
    # --- Pantalla & Visión VLM ---
    {"type": "function", "function": {
        "name": "read_screen",
        "description": "Lee el texto de la pantalla por OCR. Asi 'ves' que hay "
                       "en pantalla (chats, barras, navegador). args: region "
                       "[x,y,w,h] opcional para leer solo una zona.",
        "parameters": _p({"region": {"type": "array", "items": {"type": "integer"}}})}},
    {"type": "function", "function": {
        "name": "read_window",
        "description": "Lee por OCR el texto de una ventana concreta (por substring "
                       "de titulo). Enfoca y captura esa ventana.",
        "parameters": _p({"title": {"type": "string"}}, ["title"])}},
    {"type": "function", "function": {
        "name": "vlm_inspect_screen",
        "description": "Inspecciona y describe la pantalla usando el motor de visión multimodal VLM local.",
        "parameters": _p({"prompt": {"type": "string"},
                          "region": {"type": "array", "items": {"type": "integer"}}})}},
    {"type": "function", "function": {
        "name": "vlm_inspect_image",
        "description": "Analiza una imagen o foto con el modelo de visión multimodal local.",
        "parameters": _p({"path": {"type": "string"}, "prompt": {"type": "string"}}, ["path"])}},
    {"type": "function", "function": {
        "name": "vlm_watch_condition",
        "description": "Monitorea la pantalla periódicamente hasta que se cumpla una condición visual dada (ej. 'terminó el render', 'apareció un error').",
        "parameters": _p({"condition": {"type": "string"}, "timeout_seconds": {"type": "number"}}, ["condition"])}},
    {"type": "function", "function": {
        "name": "type_into_window",
        "description": "Enfoca una ventana por titulo y escribe texto en ella "
                       "(cualquier chat, navegador o terminal). submit=true pulsa "
                       "Enter para enviar. Con esto puedes escribir en barras de "
                       "input de chats web o apps.",
        "parameters": _p({"title": {"type": "string"}, "text": {"type": "string"},
                          "submit": {"type": "boolean"}}, ["title", "text"])}},
    {"type": "function", "function": {
        "name": "speak",
        "description": "Habla en voz alta por las bocinas del dispositivo (voz "
                       "espanola offline). Usalo para comunicarte con el usuario "
                       "por audio ademas del texto.",
        "parameters": _p({"text": {"type": "string"}}, ["text"])}},
    # --- Auto-modificacion de codigo & Enjambre ---
    {"type": "function", "function": {
        "name": "self_rewrite_file",
        "description": "Reescribe un archivo de TU PROPIO codigo (dentro del "
                       "proyecto) con contenido nuevo. Respalda, valida sintaxis "
                       "y revierte solo si el codigo queda roto. Para mejora directa.",
        "parameters": _p({"path": {"type": "string"}, "content": {"type": "string"},
                          "reason": {"type": "string"}}, ["path", "content"])}},
    {"type": "function", "function": {
        "name": "evolve_own_code",
        "description": "Mejora constante: le pides al modelo que reescriba un "
                       "archivo tuyo segun una instruccion y se aplica validado. "
                       "Con esto evolucionas tu propio codigo de forma segura.",
        "parameters": _p({"path": {"type": "string"}, "instruction": {"type": "string"}},
                         ["path", "instruction"])}},
    {"type": "function", "function": {
        "name": "list_code_backups",
        "description": "Lista respaldos de codigo generados por las reescrituras.",
        "parameters": _p({"path": {"type": "string"}})}},
    {"type": "function", "function": {
        "name": "restore_code_backup",
        "description": "Restaura un respaldo si una reescritura salio mal.",
        "parameters": _p({"backup_path": {"type": "string"}}, ["backup_path"])}},
    {"type": "function", "function": {
        "name": "spawn_subagent",
        "description": "Delega una subtarea en paralelo a un sub-agente especializado (roles: code_auditor, web_researcher, rf_analyst, vision_scout, system_medic).",
        "parameters": _p({"role": {"type": "string"}, "task": {"type": "string"}}, ["role", "task"])}},
    {"type": "function", "function": {
        "name": "consolidate_subconscious",
        "description": "Ejecuta el ciclo de consolidación de memoria subconsciente, depuración y síntesis de aprendizajes de GIA.",
        "parameters": _p({})}},
    # --- Control del sistema operativo ---
    {"type": "function", "function": {
        "name": "install_software",
        "description": "Instala software con winget (por id, ej. 'Google.Chrome').",
        "parameters": _p({"name": {"type": "string"}}, ["name"])}},
    {"type": "function", "function": {
        "name": "uninstall_software",
        "description": "Desinstala software con winget por id.",
        "parameters": _p({"name": {"type": "string"}}, ["name"])}},
    {"type": "function", "function": {
        "name": "free_compute",
        "description": "Cierra los N programas de usuario mas pesados (RAM) para "
                       "liberar potencia de computo. Nunca cierra el SO ni el "
                       "stack de GIA.",
        "parameters": _p({"top_n": {"type": "integer"}})}},
    {"type": "function", "function": {
        "name": "reboot_pc",
        "description": "Reinicia la PC tras un retraso (default 60s, cancelable "
                       "con 'shutdown /a'). Usalo cuando un cambio requiera reinicio.",
        "parameters": _p({"delay_seconds": {"type": "integer"}})}},
    # --- Puente iOS (USB) ---
    {"type": "function", "function": {
        "name": "ios_devices",
        "description": "Lista dispositivos iOS conectados por USB (nombre, modelo, "
                       "iOS, udid). Empieza por aqui al trabajar con el iPhone.",
        "parameters": _p({})}},
    {"type": "function", "function": {
        "name": "ios_info",
        "description": "Info detallada del iPhone conectado (modelo, version iOS, "
                       "serial, bateria, numero, almacenamiento).",
        "parameters": _p({})}},
    {"type": "function", "function": {
        "name": "ios_apps",
        "description": "Lista apps instaladas en el iPhone (bundle_id, nombre, "
                       "version). user_only=false incluye apps del sistema.",
        "parameters": _p({"user_only": {"type": "boolean"}})}},
    {"type": "function", "function": {
        "name": "ios_install",
        "description": "Instala un archivo .ipa en el iPhone conectado.",
        "parameters": _p({"ipa_path": {"type": "string"}}, ["ipa_path"])}},
    {"type": "function", "function": {
        "name": "ios_uninstall",
        "description": "Desinstala una app del iPhone por bundle_id.",
        "parameters": _p({"bundle_id": {"type": "string"}}, ["bundle_id"])}},
    {"type": "function", "function": {
        "name": "ios_screenshot",
        "description": "Captura la pantalla del iPhone (requiere Modo Desarrollador "
                       "activado en el telefono; en iOS 17+ ademas un tunel admin).",
        "parameters": _p({"out_path": {"type": "string"}})}},
    {"type": "function", "function": {
        "name": "ios_media",
        "description": "Lista archivos de la carpeta multimedia (fotos/DCIM) del "
                       "iPhone via AFC.",
        "parameters": _p({"path": {"type": "string"}})}},
    # --- Auto-mejora ---
    {"type": "function", "function": {
        "name": "request_self_improvement",
        "description": "Analiza el estado del sistema y encola una peticion de "
                       "mejora (se aplica luego via Claude Code).",
        "parameters": _p({})}},
    {"type": "function", "function": {
        "name": "improve_context",
        "description": "Refina tus PROPIAS directrices permanentes (el contexto "
                       "agentico) segun lo que el usuario mas pide. apply=false "
                       "propone; apply=true guarda (la version previa se conserva "
                       "y es reversible). Usalo para adaptarte con el tiempo.",
        "parameters": _p({"apply": {"type": "boolean"}})}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Declara la tarea COMPLETADA con un resumen de lo hecho. "
                       "Llama esto cuando termines o si no puedes continuar.",
        "parameters": _p({"summary": {"type": "string"}}, ["summary"])}},
]


# PREFIJO INVARIANTE ESTATICO (Garantiza Prompt Caching KV de 0 ms en Ollama/llama.cpp)
SYSTEM_PROMPT_PREFIX = """Eres GIA-Agente, un agente AUTONOMO que controla la PC del usuario (Windows 11) para completar la tarea que te dan.

Tienes herramientas para: ejecutar PowerShell (run_shell), leer/escribir
archivos, listar directorios, abrir apps, controlar ventanas y el raton/
teclado (list_windows, focus_window, gui_click, gui_type, gui_key,
screenshot) y buscar en internet (web_search, web_fetch).

COMO TRABAJAS:
1. Piensa el plan minimo para lograr la tarea.
2. Actua con las herramientas adecuadas y observa el resultado antes de seguir.
3. Prefiere run_shell (PowerShell) para casi todo: es lo mas fiable.
4. Usa las tools de GUI solo cuando no haya alternativa por shell.
5. Eres un modelo de TEXTO: no "ves" la pantalla directamente. Usa list_windows,
   read_screen o run_shell para conocer el estado, no adivines coordenadas.
6. Cuando la tarea este lista, llama finish(summary=...) con lo que hiciste.
7. Si algo se bloquea por seguridad, NO insistas: busca otra via o informa
   en finish que esa accion esta protegida.

REGLAS DE ORO:
- Se conservador: si dudas entre una accion reversible y una destructiva,
  elige la reversible.
- No borres nada que no sea claramente el objetivo de la tarea.
- Verifica tu trabajo (ej. list_dir tras mover archivos).
- Responde y razona en espanol, breve y directo.
- No inventes rutas ni nombres de usuario: usa las rutas del sistema.
- Si una tool falla, NO repitas la misma llamada identica: cambia el enfoque.
"""
SYSTEM_PROMPT = SYSTEM_PROMPT_PREFIX

# Tools que NO mutan estado y pueden ejecutarse concurrentemente si vienen juntas
READ_ONLY_TOOLS = {
    "read_file", "list_dir", "search_files", "grep_files",
    "read_screen", "read_window", "read_sensors", "read_em_spectrum",
    "rf_detect_presence", "rf_spatial_density", "web_search", "web_fetch",
    "list_windows", "list_cameras", "list_microphones", "ios_devices", "ios_info",
    "ios_apps", "ios_media", "list_code_backups"
}


# =====================================================================
#  LOOP AUTONOMO
# =====================================================================

def _scan_json_objects(text: str) -> list:
    """Extrae TODOS los objetos JSON balanceados de un texto (maneja fences
    ```json, JSON anidado y strings con llaves). qwen2.5-coder tiende a
    emitir las tool calls como ```json {...}``` en vez de tool_calls nativos."""
    objs = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "{":
            depth = 0
            in_str = False
            esc = False
            j = i
            while j < n:
                c = text[j]
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = not in_str
                elif not in_str:
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                objs.append(json.loads(text[i:j + 1]))
                            except Exception:
                                pass
                            i = j
                            break
                j += 1
        i += 1
    return objs


def parse_tool_calls(msg: dict) -> list:
    """Extrae tool calls del mensaje, tolerante a modelos que ponen JSON en content."""
    tcs = msg.get("tool_calls") or []
    if tcs:
        out = []
        for tc in tcs:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try: args = json.loads(args)
                except Exception: args = {}
            out.append((fn.get("name", ""), args))
        return out
    # Fallback robusto: escanear objetos JSON con clave "name" en el content
    content = msg.get("content") or ""
    out = []
    for obj in _scan_json_objects(content):
        if isinstance(obj, dict) and "name" in obj and obj["name"] in TOOL_IMPL:
            args = obj.get("arguments", obj.get("parameters", {}))
            if isinstance(args, str):
                try: args = json.loads(args)
                except Exception: args = {}
            if not isinstance(args, dict):
                args = {}
            out.append((obj["name"], args))
    return out


def _build_env_context() -> str:
    """Rutas y datos reales de la maquina para anclar al modelo."""
    home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    user = os.environ.get("USERNAME", "")
    lines = [
        f"Usuario: {user}",
        f"Carpeta personal (USERPROFILE): {home}",
        f"Escritorio: {os.path.join(home, 'Desktop')}",
        f"Descargas: {os.path.join(home, 'Downloads')}",
        f"Documentos: {os.path.join(home, 'Documents')}",
        f"Directorio actual: {os.getcwd()}",
        f"Proyecto GIA: C:\\LOCAL-LLM\\GODWORKS SYSTEM",
    ]
    return "\n".join(lines)


def _compact_history(hist: list, keep_full_last: int = 2) -> list:
    """
    Compacta de forma retrospectiva resultados antiguos de tools para evitar
    saturar la memoria DDR4 y mantener el prefill ultra-rápido en pasos largos.
    Conserva siempre íntegros los últimos `keep_full_last` resultados.
    """
    tool_indices = [i for i, m in enumerate(hist) if m.get("role") == "tool"]
    if len(tool_indices) <= keep_full_last:
        return hist

    compact_targets = set(tool_indices[:-keep_full_last])
    new_hist = []
    for i, m in enumerate(hist):
        if i in compact_targets:
            content = m.get("content", "")
            if len(content) > 280:
                try:
                    data = json.loads(content)
                    brief = {
                        "ok": data.get("ok"),
                        "returncode": data.get("returncode"),
                        "error": data.get("error"),
                        "count": data.get("count") or data.get("match_count"),
                        "summary": data.get("summary") or (str(data.get("stdout", ""))[:140] + "...") if "stdout" in data else str(content)[:160] + "..."
                    }
                    brief = {k: v for k, v in brief.items() if v is not None}
                    new_hist.append({"role": "tool", "content": json.dumps(brief, ensure_ascii=False)})
                    continue
                except Exception:
                    new_hist.append({"role": "tool", "content": content[:180] + " ...[resumen compactado]"})
                    continue
        new_hist.append(m)
    return new_hist


def build_system_prompt() -> str:
    """Genera el prompt del sistema anclando el prefijo estático con el contexto dinámico al final."""
    tail = f"\n=== ENTORNO REAL DE ESTA MAQUINA (Fecha: {date.today().isoformat()}) ===\n{_build_env_context()}\n"
    system = SYSTEM_PROMPT_PREFIX + tail
    if HAS_CTX:
        try:
            system = _ctx.apply_to_system(system)
        except Exception:
            pass
    return system


def run_agent(task: str, model: str, num_ctx: int) -> None:
    system = build_system_prompt()
    history = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"TAREA: {task}"},
    ]
    safety.audit("TASK_START", task[:300], verdict="INFO")

    t_start = time.time()
    client = httpx.Client()
    _recent_calls = []          # anti-bucle: ultimas firmas de llamada
    use_full_schema = False     # fallback dinámico seguro si se requiere todo

    # Sin kill-switch: el bucle corre hasta finish(), Ctrl+C, FAILSAFE del
    # raton, o anti-bucle. El agente decide cuando terminar.
    step = 0
    while True:
        step += 1
        elapsed = time.time() - t_start
        print(f"{C_DIM}--- paso {step} ({elapsed:.0f}s) ---{C_END}")

        # Selección dinámica y segura de tools (ahorra ~2500 tokens de prefill por turno)
        if HAS_TOOLSEL and not use_full_schema:
            recent_text = " ".join([str(m.get("content", "")) for m in history[-2:]])
            active_tools = _toolsel.subset_schema(TOOLS_SCHEMA, task, recent_text=recent_text)
        else:
            active_tools = TOOLS_SCHEMA

        # Compactación retrospectiva de historial (mantiene los últimos 2 turnos 100% completos)
        optimized_history = _compact_history(history, keep_full_last=2)

        try:
            resp = client.post(f"{OLLAMA}/api/chat", json={
                "model": model,
                "messages": optimized_history,
                "tools": active_tools,
                "stream": False,
                "options": {
                    "num_ctx": num_ctx,
                    "temperature": 0.2,
                    "num_thread": 8,
                    "num_batch": 512,
                    "use_mmap": True
                },
                "keep_alive": "30m",
            }, timeout=600.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"{C_ERR}[error Ollama] {e}{C_END}")
            break

        msg = data.get("message", {})
        content = (msg.get("content") or "").strip()
        calls = parse_tool_calls(msg)
        history.append({"role": "assistant", "content": content,
                        "tool_calls": msg.get("tool_calls") or None})

        if content and not calls:
            print(f"{C_AI}[GIA] {content}{C_END}")

        if not calls:
            # Si el modelo expresa no tener una tool o no saber cómo continuar, abrir el schema completo
            if any(w in content.lower() for w in ("herramienta", "tool", "no puedo", "no tengo", "falta")):
                use_full_schema = True
            history.append({"role": "user",
                            "content": "Continua con la tarea o llama finish(summary) si terminaste."})
            continue

        finished = False
        aborted = False

        # Ejecución paralela si todas las llamadas del turno son de solo lectura
        can_parallel = len(calls) > 1 and all(name in READ_ONLY_TOOLS for name, _ in calls)

        if can_parallel:
            print(f"{C_DIM}  -> ejecutando {len(calls)} lecturas concurrentemente...{C_END}")
            def _exec_single(item):
                c_name, c_args = item
                impl = TOOL_IMPL.get(c_name)
                if not impl:
                    return c_name, c_args, {"ok": False, "error": f"tool desconocida: {c_name}"}
                return c_name, c_args, impl(c_args)

            with ThreadPoolExecutor(max_workers=min(4, len(calls))) as pool:
                results = list(pool.map(_exec_single, calls))

            for name, args, result in results:
                arg_preview = json.dumps(args, ensure_ascii=False)[:130]
                print(f"{C_TOOL}[tool-paralelo] {name}({arg_preview}){C_END}")
                if result.get("ok"):
                    brief = {k: v for k, v in result.items()
                             if k in ("returncode", "path", "count", "bytes", "match_count")}
                    print(f"{C_DIM}  -> ok {brief}{C_END}")
                else:
                    print(f"{C_ERR}  -> error: {result.get('error','')[:120]}{C_END}")
                history.append({"role": "tool",
                                "content": json.dumps(result, ensure_ascii=False)[:6000]})
        else:
            for name, args in calls:
                arg_preview = json.dumps(args, ensure_ascii=False)[:130]
                print(f"{C_TOOL}[tool] {name}({arg_preview}){C_END}")

                # Si el modelo solicita una tool fuera del subset activo pero existente en el sistema,
                # la ejecutamos fielmente y abrimos el set completo para el siguiente turno
                if HAS_TOOLSEL and not use_full_schema:
                    active_names = {t.get("function", {}).get("name") for t in active_tools}
                    if name not in active_names and name in TOOL_IMPL:
                        use_full_schema = True

                # Anti-bucle: misma llamada 3 veces seguidas = atasco -> cortar.
                sig = name + "|" + json.dumps(args, ensure_ascii=False, sort_keys=True)
                _recent_calls.append(sig)
                if _recent_calls[-3:].count(sig) >= 3:
                    print(f"{C_ERR}[ANTI-BUCLE] misma llamada repetida 3x sin exito. "
                          f"Agente atascado, deteniendo.{C_END}")
                    safety.audit("ANTI_LOOP", sig[:200], verdict="INFO")
                    aborted = True
                    break

                impl = TOOL_IMPL.get(name)
                if not impl:
                    result = {"ok": False, "error": f"tool desconocida: {name}"}
                else:
                    result = impl(args)

                if result.get("_finish"):
                    print(f"\n{C_OK}[COMPLETADO] {result.get('summary','')}{C_END}")
                    safety.audit("TASK_DONE", result.get("summary", "")[:300], verdict="INFO")
                    finished = True
                    break

                # Feedback visual
                if result.get("blocked"):
                    print(f"{C_ERR}  -> BLOQUEADO: {result.get('error')}{C_END}")
                elif result.get("ok"):
                    brief = {k: v for k, v in result.items()
                             if k in ("returncode", "path", "count", "bytes",
                                      "opened", "focused", "pressed", "typed_chars",
                                      "clicked", "match_count")}
                    print(f"{C_DIM}  -> ok {brief}{C_END}")
                else:
                    print(f"{C_ERR}  -> error: {result.get('error','')[:120]}{C_END}")

                history.append({"role": "tool",
                                "content": json.dumps(result, ensure_ascii=False)[:6000]})

        if finished or aborted:
            break

    total = time.time() - t_start
    print(f"{C_DIM}Fin. {step} pasos, {total:.0f}s. "
          f"Audit: {safety.AUDIT_LOG}{C_END}")


def main() -> int:
    global DRY_RUN
    ap = argparse.ArgumentParser(description="Agente autonomo GIA")
    ap.add_argument("task", nargs="*", help="tarea a ejecutar")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--ctx", type=int, default=DEFAULT_CTX)
    ap.add_argument("--dry-run", action="store_true",
                    help="simula: no ejecuta shell/escritura/GUI reales")
    args = ap.parse_args()

    DRY_RUN = args.dry_run

    summ = safety.denylist_summary()
    print(f"\n{C_AI}================================================={C_END}")
    print(f"{C_AI}  GIA - AGENTE AUTONOMO DE CONTROL{C_END}")
    print(f"{C_AI}  Modelo: {args.model} (ctx={args.ctx}){C_END}")
    print(f"{C_AI}  GUI:{'ON' if HAS_GUI else 'OFF'}  Web:{'ON' if HAS_WEB else 'OFF'}  "
          f"Sensores:{'ON' if HAS_SENSORS else 'OFF'}  "
          f"Busqueda:{'ON' if HAS_DEEP else 'OFF'}  "
          f"OCR:{'ON' if HAS_OCR else 'OFF'}  "
          f"AutoMejora:{'ON' if HAS_SELFIMP else 'OFF'}"
          f"  {'[DRY-RUN]' if DRY_RUN else ''}{C_END}")
    print(f"{C_DIM}  Seguridad: {summ['denylist_rules']} reglas denylist "
          f"(SIN kill-switch: corre hasta finish){C_END}")
    print(f"{C_ERR}  Abortar: raton a esquina sup-izq, o Ctrl+C{C_END}")
    print(f"{C_DIM}  Audit log: {summ['audit_log']}{C_END}")
    print(f"{C_AI}================================================={C_END}\n")

    # Verificar Ollama
    try:
        httpx.Client().get(f"{OLLAMA}/api/tags", timeout=5.0)
    except Exception:
        print(f"{C_ERR}Ollama no responde en {OLLAMA}. Arranca 'ollama serve'.{C_END}")
        return 1

    task = " ".join(args.task).strip()
    if not task:
        try:
            task = input(f"{C_USER}Que tarea quieres que ejecute? > {C_END}").strip()
        except (KeyboardInterrupt, EOFError):
            return 0
    if not task:
        print("Sin tarea. Saliendo.")
        return 0

    try:
        run_agent(task, args.model, args.ctx)
    except KeyboardInterrupt:
        print(f"\n{C_ERR}[ABORTADO por Ctrl+C]{C_END}")
        safety.audit("ABORT", "Ctrl+C", verdict="INFO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
