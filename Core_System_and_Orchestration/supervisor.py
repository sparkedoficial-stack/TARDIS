"""
supervisor.py - Supervisor siempre-encendido con watchdog termico.
===================================================================

Mantiene el sistema GIA "vivo" 24/7 de forma EFICIENTE:
  - Asegura que Ollama este corriendo (lo arranca si no).
  - Corre el motor de auto-mejora (self_improve) en ciclos.
  - WATCHDOG de recursos: lee temp GPU (nvidia-smi), CPU, RAM y bateria.
    * Deja correr con carga alta (permite calor).
    * PAUSA los ciclos si la GPU pasa el umbral critico (evita quemar).
    * Reanuda al enfriar.
    * En bateria, alarga el intervalo (ahorra energia).
  - Reinicia componentes caidos.
  - Registra estado en %LOCALAPPDATA%\\vw-control\\supervisor.log

Filosofia (peticion del usuario): encendido todo el tiempo, puede
calentarse, pero "consciente" para no quemar la maquina y usar recursos
de forma eficiente.

Umbrales (editables por env var):
  GIA_GPU_PAUSE_C   (default 87)  -> por encima: pausa ciclos
  GIA_GPU_RESUME_C  (default 78)  -> por debajo: reanuda
  GIA_MIN_FREE_RAM_GB (default 2) -> menos RAM libre: pausa
  GIA_IDLE_INTERVAL (default 1800 s) ciclo normal
  GIA_HOT_BACKOFF   (default 120 s)  espera cuando esta caliente

Uso:
    python supervisor.py                 # corre indefinido
    python supervisor.py --once          # una pasada de diagnostico
    python supervisor.py --no-improve    # solo mantener vivo, sin auto-mejora
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SUP_LOG = CONFIG_DIR / "supervisor.log"

OLLAMA = "http://REDACTED_IP:11434"

GPU_PAUSE_C = float(os.environ.get("GIA_GPU_PAUSE_C", 87))
GPU_RESUME_C = float(os.environ.get("GIA_GPU_RESUME_C", 78))
MIN_FREE_RAM_GB = float(os.environ.get("GIA_MIN_FREE_RAM_GB", 2))
IDLE_INTERVAL = int(os.environ.get("GIA_IDLE_INTERVAL", 1800))
HOT_BACKOFF = int(os.environ.get("GIA_HOT_BACKOFF", 120))

C_AI = "\033[96m"; C_DIM = "\033[90m"; C_OK = "\033[92m"
C_WARN = "\033[93m"; C_ERR = "\033[91m"; C_END = "\033[0m"

os.system("")


def acquire_single_instance() -> bool:
    """Evita dos supervisores a la vez (Mutex en Windows / flock en Linux).
    Devuelve True si somos la unica instancia, False si ya hay otra."""
    if os.name != "nt":
        try:
            import fcntl
            lock_path = Path("/tmp/gia_supervisor.lock")
            lock_file = open(lock_path, "w")
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            globals()["_SUPERVISOR_LOCK_FILE"] = lock_file
            return True
        except (BlockingIOError, IOError):
            return False
        except Exception:
            return True
    try:
        import ctypes
        # "Local\\" = singleton por sesion de usuario
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\GIA_Supervisor_Singleton")
        ERROR_ALREADY_EXISTS = 183
        last_err = ctypes.windll.kernel32.GetLastError()
        if not mutex or last_err == ERROR_ALREADY_EXISTS:
            return False
        # Mantener el handle vivo (referencia global) mientras corre el proceso
        globals()["_SUPERVISOR_MUTEX"] = mutex
        return True
    except Exception:
        return True   # si el mutex falla, no bloquear el arranque


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | {level:5} | {msg}"
    color = {"OK": C_OK, "WARN": C_WARN, "ERROR": C_ERR, "HOT": C_ERR}.get(level, C_DIM)
    print(f"{color}{line}{C_END}")
    try:
        with open(SUP_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# =====================================================================
#  LECTURA DE RECURSOS
# =====================================================================

def gpu_temp() -> float | None:
    """Temperatura GPU en C via nvidia-smi, o None si no hay NVIDIA."""
    try:
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=10, **kwargs
        ).decode("utf-8", "ignore").strip()
        return float(out.splitlines()[0])
    except Exception:
        return None


def resources() -> dict:
    r = {"gpu_temp": gpu_temp()}
    try:
        import psutil
        r["cpu"] = psutil.cpu_percent(interval=0.2)
        vm = psutil.virtual_memory()
        r["ram_free_gb"] = round(vm.available / 1e9, 1)
        r["ram_pct"] = vm.percent
        try:
            bat = psutil.sensors_battery()
            if bat:
                r["battery"] = bat.percent
                r["plugged"] = bat.power_plugged
        except Exception:
            pass
    except Exception:
        pass
    return r


def should_pause(r: dict) -> tuple[bool, str]:
    """Decide si pausar los ciclos por temperatura/recursos."""
    t = r.get("gpu_temp")
    if t is not None and t >= GPU_PAUSE_C:
        return True, f"GPU {t:.0f}C >= {GPU_PAUSE_C:.0f}C (enfriando)"
    fr = r.get("ram_free_gb")
    if fr is not None and fr < MIN_FREE_RAM_GB:
        return True, f"RAM libre {fr:.1f}GB < {MIN_FREE_RAM_GB:.1f}GB"
    return False, ""


# =====================================================================
#  MANTENER COMPONENTES VIVOS
# =====================================================================

def ollama_alive() -> bool:
    try:
        import gia_bootstrap
        return gia_bootstrap.is_ollama_alive(OLLAMA, timeout=3.0)
    except Exception:
        try:
            httpx.Client().get(f"{OLLAMA}/api/tags", timeout=4.0)
            return True
        except Exception:
            return False


def ensure_ollama():
    if ollama_alive():
        return True
    log("Ollama caído o no iniciado; levantando servicio...", "WARN")
    try:
        import gia_bootstrap
        ok = gia_bootstrap.ensure_ollama(OLLAMA, timeout_seconds=25.0, verbose=False)
        if ok:
            log("Ollama arriba y verificado", "OK")
            return True
    except Exception as e:
        log(f"Error con bootstrap de Ollama: {e}", "ERROR")

    # Fallback tradicional si bootstrap falla
    try:
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    except Exception as e:
        log(f"no se pudo arrancar Ollama: {e}", "ERROR")
        return False
    for _ in range(15):
        time.sleep(2)
        if ollama_alive():
            log("Ollama arriba", "OK")
            return True
    log("Ollama no respondio tras 30s", "ERROR")
    return False


def run_voice_cycle():
    """Emite un mensaje de la voz autonoma (contexto y conversacion continua).

    Se llama desde el bucle del supervisor, asi que hereda el watchdog: si la
    GPU esta caliente o falta RAM, el supervisor pausa y la voz no emite.
    """
    try:
        import autonomous_voice as voz
        r = voz.emit_once()
        if r.get("ok"):
            o = r.get("origin", {})
            log(f"voz autonoma: seq {o.get('sequence')} "
                f"[{o.get('date')} {o.get('time')}] {o.get('place')}", "OK")
        else:
            log(f"voz autonoma sin emision: {r.get('error')}", "WARN")
    except Exception as e:
        log(f"error en voz autonoma: {e}", "ERROR")


def run_improve_cycle(model: str):
    try:
        import self_improve
        path = self_improve.one_cycle(model)
        if path:
            log(f"auto-mejora encolada: {Path(path).name}", "OK")
        else:
            log("ciclo de auto-mejora sin salida", "WARN")
    except Exception as e:
        log(f"error en auto-mejora: {e}", "ERROR")


# =====================================================================
#  LOOP PRINCIPAL
# =====================================================================

def diagnostic():
    r = resources()
    log(f"GPU={r.get('gpu_temp')}C CPU={r.get('cpu')}% RAM_libre={r.get('ram_free_gb')}GB "
        f"bat={r.get('battery')}% plugged={r.get('plugged')} ollama={ollama_alive()}")
    pause, why = should_pause(r)
    if pause:
        log(f"en estas condiciones PAUSARIA: {why}", "WARN")
    else:
        log("condiciones OK para operar", "OK")
    return r


def main() -> int:
    try:
        import gia_sovereign_engine as _gse
        _def_model = _gse.get_engine().resolve_model()
    except Exception:
        _def_model = os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated")
    ap = argparse.ArgumentParser(description="Supervisor GIA siempre-encendido")
    ap.add_argument("--model", default=_def_model)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-improve", action="store_true")
    ap.add_argument("--no-voice", action="store_true",
                    help="no emitir la voz autonoma en cada ciclo")
    ap.add_argument("--voice-interval", type=int, default=0,
                    help="acorta el ciclo del supervisor para emitir la voz "
                         "mas seguido (segundos, minimo 60)")
    args = ap.parse_args()

    print(f"\n{C_AI}================================================={C_END}")
    print(f"{C_AI}  TARDIS - SUPERVISOR SIEMPRE-ENCENDIDO (v26.4){C_END}")
    print(f"{C_AI}  Watchdog: pausa GPU>={GPU_PAUSE_C:.0f}C, reanuda<={GPU_RESUME_C:.0f}C{C_END}")
    print(f"{C_AI}  Centinela de Auto-Corrección y Auto-Notificación: ACTIVO{C_END}")
    print(f"{C_DIM}  Log: {SUP_LOG}   Ctrl+C para detener{C_END}")
    print(f"{C_AI}================================================={C_END}\n")

    if args.once:
        diagnostic()
        return 0

    if not acquire_single_instance():
        log("ya hay un supervisor corriendo; esta instancia sale", "WARN")
        return 0

    # Iniciar Centinela de Detección, Auto-Corrección y Notificación 24/7
    try:
        from core.tardis_error_sentinel import get_sentinel
        get_sentinel().start()
        log("centinela TARDIS auto-corrección y notificación activo", "OK")
    except Exception as e:
        log(f"no se pudo iniciar centinela TARDIS: {e}", "WARN")

    log("supervisor TARDIS iniciado", "OK")
    paused = False
    try:
        while True:
            ensure_ollama()
            r = resources()
            pause, why = should_pause(r)

            # Histeresis: si estaba pausado, esperar a bajar del umbral de reanudar
            if paused:
                t = r.get("gpu_temp")
                if t is not None and t > GPU_RESUME_C:
                    log(f"sigue caliente (GPU {t:.0f}C); espera {HOT_BACKOFF}s", "HOT")
                    time.sleep(HOT_BACKOFF)
                    continue
                paused = False
                log("enfriado; reanudando operacion", "OK")

            if pause:
                paused = True
                log(f"PAUSA por {why}; espera {HOT_BACKOFF}s", "HOT")
                time.sleep(HOT_BACKOFF)
                continue

            # Operacion normal: ciclo de auto-mejora (si esta activado)
            if not args.no_improve:
                run_improve_cycle(args.model)

            # Voz autonoma: emite contexto/conversacion de forma indefinida.
            # Va DESPUES del watchdog, asi que si la maquina esta caliente o
            # sin RAM, no emite (el bucle ya hizo `continue` mas arriba).
            if not args.no_voice:
                run_voice_cycle()

            # Intervalo: mas largo en bateria (eficiencia)
            interval = IDLE_INTERVAL
            if args.voice_interval:
                interval = min(interval, max(60, args.voice_interval))
            if r.get("plugged") is False:
                interval = IDLE_INTERVAL * 2
                log(f"en bateria: intervalo extendido a {interval}s", "DIM")
            log(f"proximo ciclo en {interval}s (GPU={r.get('gpu_temp')}C "
                f"RAM_libre={r.get('ram_free_gb')}GB)")
            time.sleep(interval)
    except KeyboardInterrupt:
        log("supervisor detenido por usuario", "WARN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
