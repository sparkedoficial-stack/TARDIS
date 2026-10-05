"""
gia_launcher.py - Lanzador grafico de GIA (compilable a .exe).
==============================================================

Ventana con botones para arrancar cada componente del sistema. Es el
"ejecutable manual" de respaldo si el autostart de Windows falla.

Compilar a .exe:
    pyinstaller --onefile --windowed --name GIA-Launcher gia_launcher.py

El .exe NO requiere que el usuario tenga el venv en PATH: localiza el
Python del venv en %LOCALAPPDATA%\\vw-control\\.venv y lanza los scripts
con el, buscandolos junto al .exe (o en C:\\LOCAL-LLM\\GODWORKS SYSTEM).
"""
from __future__ import annotations

import json          # NO QUITAR: agent_context lo necesita y PyInstaller solo
import datetime      # empaqueta lo que ve importado aqui. Sin estos dos, el
import sqlite3       # .exe fallaba con "No module named 'json'".
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

# ---------------------------------------------------------------------
# Localizacion de rutas (funciona tanto como .py como .exe empaquetado)
# ---------------------------------------------------------------------

def _base_dir() -> Path:
    # Si es .exe (PyInstaller), sys.executable es el .exe; los scripts viven
    # junto a el o en la carpeta del proyecto.
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent)
    candidates.append(Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd())
    candidates.append(Path(r"C:\LOCAL-LLM\GODWORKS SYSTEM"))
    for c in candidates:
        if (c / "supervisor.py").is_file():
            return c
    return candidates[-1]


BASE = _base_dir()
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
VENV = Path(LOCALAPPDATA) / "vw-control" / ".venv" / "Scripts"
PY = VENV / "python.exe"
PYW = VENV / "pythonw.exe"

WEB_PORT = 8757


def _py(hidden: bool = False) -> str:
    if hidden and PYW.exists():
        return str(PYW)
    if PY.exists():
        return str(PY)
    return "pythonw.exe" if hidden else "python.exe"


def run_script(script: str, args=None, hidden: bool = False, new_console: bool = True):
    """Lanza un script del proyecto con el Python del venv o del sistema."""
    args = args or []
    script_path = BASE / script
    cmd = [_py(hidden), str(script_path)] + list(args)
    creationflags = 0
    if new_console and not hidden:
        creationflags = subprocess.CREATE_NEW_CONSOLE
    elif hidden:
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        return subprocess.Popen(cmd, cwd=str(BASE), creationflags=creationflags)
    except Exception as e:  # noqa: BLE001
        messagebox.showerror("GIA", f"No se pudo lanzar {script}:\n{e}")
        return None


def supervisor_running() -> bool:
    try:
        import ctypes
        m = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\GIA_Supervisor_Singleton")
        exists = ctypes.windll.kernel32.GetLastError() == 183
        ctypes.windll.kernel32.CloseHandle(m)   # liberar: solo estabamos sondeando
        return exists
    except Exception:
        return False


def stop_supervisor():
    ps = ('Get-CimInstance Win32_Process -Filter "Name like \'python%\'" | '
          "Where-Object { $_.CommandLine -like '*supervisor.py*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   creationflags=subprocess.CREATE_NO_WINDOW)


def open_browser(url: str):
    import webbrowser
    webbrowser.open(url)


# ---------------------------------------------------------------------
# Acciones de los botones
# ---------------------------------------------------------------------

def act_direct_local():
    run_script("gia_direct_local.py")
    set_status("Ruta Local Directa iniciada (sin servidor web).")


def act_all():
    if not supervisor_running():
        run_script("supervisor.py", hidden=True, new_console=False)
    run_script("omni_temporal_control.py", ["--port", str(WEB_PORT)])
    threading.Thread(target=lambda: (time.sleep(3),
                     open_browser(f"http://REDACTED_IP:{WEB_PORT}")), daemon=True).start()
    set_status("Sistema completo iniciado. Abriendo interfaz...")


def act_supervisor():
    if supervisor_running():
        set_status("El supervisor ya estaba corriendo.")
    else:
        run_script("supervisor.py", hidden=True, new_console=False)
        set_status("Supervisor 24/7 iniciado en segundo plano.")


def act_web_local():
    run_script("gia_web_server.py", ["--port", str(WEB_PORT)])
    threading.Thread(target=lambda: (time.sleep(4),
                     open_browser(f"http://REDACTED_IP:{WEB_PORT}")), daemon=True).start()
    set_status(f"Interfaz web local en http://REDACTED_IP:{WEB_PORT}")


def act_web_lan():
    run_script("gia_web_server.py", ["--lan", "--port", str(WEB_PORT)])
    set_status("Interfaz web LAN iniciada. La URL con token esta en la consola.")


def act_tunnel():
    run_script("start_tunnel.py")
    set_status("Montando tunel de internet... la URL publica aparece en la consola.")


def act_voice():
    run_script("voice_assistant.py")
    set_status("Asistente de voz iniciado en consola.")


def act_agent():
    run_script("gia_agent.py")
    set_status("Agente autonomo iniciado. Abortar: raton a esquina sup-izq.")


def act_stop():
    stop_supervisor()
    set_status("Supervisor detenido.")


def _ctx_rpc(expr: str, timeout: int = 900):
    """Ejecuta una expresion sobre agent_context en el Python del VENV.

    Por que existe: cuando el lanzador corre como .exe congelado, el bundle de
    PyInstaller solo contiene lo que se importa en ESTE archivo. agent_context
    necesita ademas httpx y sqlite3 (para auto_improve). En vez de meter todo
    en el .exe, delegamos al venv, que tiene el entorno completo.
    """
    code = (
        "import json,sys\n"
        f"sys.path.insert(0, r'''{BASE}''')\n"
        "import agent_context as ac\n"
        f"r = {expr}\n"
        "print('<<<GIA>>>' + json.dumps(r, default=str, ensure_ascii=False))\n"
    )
    p = subprocess.run([str(PY), "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    out = p.stdout or ""
    i = out.rfind("<<<GIA>>>")
    if i < 0:
        raise RuntimeError((p.stderr or out or "sin salida").strip()[:300])
    return json.loads(out[i + 9:].strip())


class _CtxProxy:
    """agent_context a traves del venv. Inmune a lo que falte en el .exe."""

    def get(self):
        return _ctx_rpc("ac.get()")

    def list_versions(self):
        return _ctx_rpc("ac.list_versions()")

    def set_directives(self, text, enabled=True, source="user"):
        return _ctx_rpc(f"ac.set_directives({text!r}, enabled={bool(enabled)}, "
                        f"source={source!r})")

    def set_auto_improve(self, flag):
        return _ctx_rpc(f"ac.set_auto_improve({bool(flag)})")

    def revert(self, version=None):
        return _ctx_rpc(f"ac.revert({version!r})")

    def auto_improve(self, apply=False):
        return _ctx_rpc(f"ac.auto_improve(apply={bool(apply)})")


def _load_agent_context():
    """Devuelve agent_context: importado directo si se puede, o via venv.

    Se prueba con una llamada real (get) porque el import puede tener exito y
    fallar despues por una dependencia ausente.
    """
    try:
        import importlib
        if str(BASE) not in sys.path:
            sys.path.insert(0, str(BASE))
        mod = importlib.import_module("agent_context")
        mod.get()                      # verificacion real, no solo el import
        return mod
    except Exception:
        return _CtxProxy()             # respaldo: siempre funciona


def act_context():
    """Ventana editable de las directrices permanentes del sistema."""
    try:
        ac = _load_agent_context()
    except Exception as e:
        messagebox.showerror("GIA", f"No se pudo cargar agent_context:\n{e}")
        return

    win = tk.Toplevel(root)
    win.title("GIA - Contexto agentico")
    win.configure(bg=BG)
    win.geometry("560x520")

    tk.Label(win, text="Directrices permanentes del sistema", bg=BG, fg=GOLD,
             font=("Segoe UI", 13, "bold")).pack(pady=(14, 2), padx=16, anchor="w")
    tk.Label(win, text="Se anteponen automaticamente en chat, voz y agente. "
                       "El sistema puede refinarlas solo (versionado reversible).",
             bg=BG, fg=DIM, font=("Segoe UI", 8), wraplength=520,
             justify="left").pack(padx=16, anchor="w")

    txt = tk.Text(win, bg="#0d1420", fg=TXT, insertbackground=TEAL,
                  relief="flat", font=("Consolas", 10), wrap="word",
                  height=14, padx=8, pady=8)
    txt.pack(fill="both", expand=True, padx=16, pady=10)

    auto_var = tk.BooleanVar(value=False)
    enab_var = tk.BooleanVar(value=True)

    def reload():
        d = ac.get()
        txt.delete("1.0", "end")
        txt.insert("1.0", d.get("directives", ""))
        auto_var.set(bool(d.get("auto_improve", False)))
        enab_var.set(d.get("enabled", True) is not False)
        v = d.get("version", 0)
        ctx_stat.config(text=f"Version {v} | {d.get('last_source','user')} | "
                             f"{d.get('updated_iso','')}")

    def save():
        ac.set_directives(txt.get("1.0", "end").strip(), enabled=enab_var.get(),
                          source="user")
        ac.set_auto_improve(auto_var.get())
        reload()
        ctx_stat.config(text="Guardado. Activo en todo el sistema al instante.")

    def improve():
        ctx_stat.config(text="El modelo esta proponiendo una mejora (~30s)...")
        win.update_idletasks()

        def worker():
            # Siempre por el venv: auto_improve necesita httpx (y gia_memory
            # necesita sqlite3), que no viven dentro del .exe congelado.
            try:
                r = _ctx_rpc("ac.auto_improve(apply=False)")
            except Exception as e:      # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            def show():
                if r.get("ok"):
                    txt.delete("1.0", "end")
                    txt.insert("1.0", r["proposal"])
                    ctx_stat.config(text="Propuesta cargada: " + r.get("cambios", "")[:60]
                                    + "  (revisa y pulsa Guardar)")
                else:
                    ctx_stat.config(text="Auto-mejora fallo: " + str(r.get("error", ""))[:60])
            win.after(0, show)
        threading.Thread(target=worker, daemon=True).start()

    def revert():
        ac.revert()
        reload()
        ctx_stat.config(text="Revertido a la version anterior.")

    row = tk.Frame(win, bg=BG); row.pack(fill="x", padx=16)
    tk.Checkbutton(row, text="activo", variable=enab_var, bg=BG, fg=DIM,
                   selectcolor=PANEL, activebackground=BG,
                   font=("Segoe UI", 8)).pack(side="left")
    tk.Checkbutton(row, text="auto-mejora", variable=auto_var, bg=BG, fg=DIM,
                   selectcolor=PANEL, activebackground=BG,
                   font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))

    btns = tk.Frame(win, bg=BG); btns.pack(fill="x", padx=16, pady=(8, 4))
    for label, cmd, col in (("Guardar", save, TEAL),
                            ("Mejorar con IA", improve, GOLD),
                            ("Revertir", revert, "#5a2530")):
        fg = "#04141a" if col in (TEAL, GOLD) else TXT
        tk.Button(btns, text=label, command=cmd, bg=col, fg=fg, relief="flat",
                  cursor="hand2", font=("Segoe UI", 9, "bold"),
                  height=1).pack(side="left", fill="x", expand=True, padx=3)

    ctx_stat = tk.Label(win, text="", bg=PANEL, fg=DIM, anchor="w",
                        font=("Segoe UI", 8), padx=8, pady=5, wraplength=520,
                        justify="left")
    ctx_stat.pack(fill="x", side="bottom")
    reload()
    set_status("Editor de contexto abierto.")


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------

BG = "#0a0e14"; PANEL = "#111823"; TEAL = "#00d4c8"; TXT = "#d6e0ea"; DIM = "#5f6b7a"
GOLD = "#e8b64a"

root = tk.Tk()
root.title("GIA - Lanzador")
root.configure(bg=BG)
root.geometry("380x640")
root.resizable(False, False)

tk.Label(root, text="G I A", bg=BG, fg=TEAL,
         font=("Segoe UI", 22, "bold")).pack(pady=(14, 2))
tk.Label(root, text="Lanzador manual del sistema", bg=BG, fg=DIM,
         font=("Segoe UI", 9)).pack(pady=(0, 10))

_buttons = [
    ("Iniciar TODO  (supervisor + suite)", act_all, TEAL),
    ("CHAT LOCAL DIRECTO (Sin Web)", act_direct_local, GOLD),
    ("Contexto / Directrices del sistema", act_context, "#1b6f6a"),
    ("Supervisor 24/7  (segundo plano)", act_supervisor, "#1b6f6a"),
    ("Interfaz web  -  este PC", act_web_local, "#1b6f6a"),
    ("Interfaz web  -  LAN / movil", act_web_lan, "#1b6f6a"),
    ("Tunel de INTERNET  (publico)", act_tunnel, GOLD),
    ("Asistente de VOZ", act_voice, "#26313f"),
    ("Agente autonomo  (control PC)", act_agent, "#26313f"),
    ("Detener supervisor", act_stop, "#5a2530"),
]

for text, cmd, color in _buttons:
    fg = "#04141a" if color in (TEAL, GOLD) else TXT
    b = tk.Button(root, text=text, command=cmd, bg=color, fg=fg,
                  activebackground=color, relief="flat", cursor="hand2",
                  font=("Segoe UI", 10, "bold"), height=2, bd=0)
    b.pack(fill="x", padx=18, pady=3)

_status = tk.Label(root, text="Listo. Comprobando dependencias...", bg=PANEL, fg=DIM, anchor="w",
                   font=("Segoe UI", 8), padx=8, pady=6, wraplength=344,
                   justify="left")
_status.pack(fill="x", side="bottom")


def set_status(msg: str):
    _status.config(text=msg)


def _refresh():
    running = supervisor_running()
    root.title(f"GIA - Lanzador  [supervisor: {'ON' if running else 'off'}]")
    root.after(4000, _refresh)


def _boot_autostart():
    """En arranque de Windows (--autostart): levanta el supervisor 24/7 en
    segundo plano, PERO NO el tunel (queda off hasta que pulses el boton)."""
    if not supervisor_running():
        run_script("supervisor.py", hidden=True, new_console=False)
        set_status("Arranque: supervisor 24/7 iniciado. Tunel APAGADO "
                   "(pulsa 'Tunel de INTERNET' para exponerlo).")
    else:
        set_status("Arranque: supervisor ya estaba corriendo. Tunel apagado.")


def _async_bootstrap():
    try:
        import gia_bootstrap
        res = gia_bootstrap.ensure_all_dependencies(verbose=False)
        m = res.get("active_model", "")
        set_status(f"Dependencias OK. Ollama listo ({m}).")
    except Exception:
        pass


threading.Thread(target=_async_bootstrap, daemon=True).start()
_refresh()

if __name__ == "__main__":
    if "--autostart" in sys.argv:
        root.after(1500, _boot_autostart)
    root.mainloop()
