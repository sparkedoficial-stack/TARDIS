"""
gia_bootstrap.py - Motor Universal de Autoinicio y Detección de Dependencias
=============================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana GIA
Garantiza que Ollama, modelos locales, tokens y directorios esenciales
arranquen y se encuentren 100% operativos automáticamente antes de cualquier
interacción con el sistema, eliminando fallos de conexión o procesos caídos.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Rutas del entorno de ejecución
WORKSPACE_DIR = Path(__file__).resolve().parent
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
GIA_STORAGE = LOCALAPPDATA / "vw-control"
TOKEN_FILE = WORKSPACE_DIR / "gia_bridge_token.txt"
TOKEN_STORAGE_FILE = GIA_STORAGE / "gia_bridge_token.txt"
def normalize_endpoint(endpoint: Optional[str] = None) -> str:
    """Asegura que el endpoint de Ollama tenga el esquema http:// y formato correcto."""
    if not endpoint:
        endpoint = os.environ.get("OLLAMA_HOST", "http://REDACTED_IP:11434")
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
        endpoint = f"http://{endpoint}"
    return endpoint


DEFAULT_OLLAMA_ENDPOINT = normalize_endpoint(os.environ.get("OLLAMA_HOST", "http://REDACTED_IP:11434"))

DEFAULT_MODELS_PREFERENCE = [
    "dolphin3:latest",
    "dolphin3",
    "dolphin3.0",
    "dolphin",
    "hermes3:8b",
    "hermes3",
    "hermes3:latest"
]


# Asegurar encoding seguro en consolas Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def find_ollama_binary() -> Optional[str]:
    """Descubre el ejecutable de Ollama en el sistema (Windows, Linux, macOS)."""
    # 1. Búsqueda en PATH
    which_path = shutil.which("ollama")
    if which_path and os.path.isfile(which_path):
        return which_path

    # 2. Rutas conocidas en Windows
    if sys.platform == "win32":
        candidates = [
            LOCALAPPDATA / "Programs" / "Ollama" / "ollama.exe",
            LOCALAPPDATA / "Programs" / "Ollama" / "ollama app.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Ollama" / "ollama.exe",
            Path(os.path.expanduser("~")) / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
    else:
        candidates = [
            Path(os.path.expanduser("~")) / ".local" / "bin" / "ollama",
            Path("/usr/local/bin/ollama"),
            Path("/usr/bin/ollama"),
            Path("/opt/ollama/bin/ollama"),
        ]
        for c in candidates:
            if c.is_file():
                return str(c)

    return None


def is_ollama_alive(endpoint: str = DEFAULT_OLLAMA_ENDPOINT, timeout: float = 2.0) -> bool:
    """Comprueba si el servidor de Ollama responde de forma no bloqueante."""
    try:
        import gia_sovereign_engine as _gse
        working = _gse.get_engine().find_working_endpoint()
        if working:
            return True
    except Exception:
        pass

    ep = normalize_endpoint(endpoint)
    url = f"{ep}/api/tags"
    req = urllib.request.Request(url, headers={"User-Agent": "GIA-Bootstrap/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_ollama_service(endpoint: str = DEFAULT_OLLAMA_ENDPOINT) -> bool:
    """Inicia el servicio de Ollama en segundo plano sin ventana."""
    try:
        import gia_sovereign_engine as _gse
        return _gse.get_engine().auto_spawn_daemon()
    except Exception:
        pass

    binary = find_ollama_binary()
    if not binary:
        print("[BOOTSTRAP] [!] No se encontro el binario de Ollama en el sistema.")
        return False

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    try:
        subprocess.Popen(
            [binary, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
            close_fds=(sys.platform != "win32")
        )
        return True
    except Exception as e:
        print(f"[BOOTSTRAP] Error al ejecutar '{binary} serve': {e}")
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                start_new_session=(sys.platform != "win32"),
                close_fds=(sys.platform != "win32")
            )
            return True
        except Exception as e2:
            print(f"[BOOTSTRAP] Error en fallback de inicio Ollama: {e2}")
            return False


def ensure_ollama(endpoint: str = DEFAULT_OLLAMA_ENDPOINT, timeout_seconds: float = 20.0, verbose: bool = True) -> bool:
    """
    Garantiza que el motor Ollama esté en línea. Si está apagado, lo arranca
    y espera hasta que responda saludablemente.
    """
    try:
        import gia_sovereign_engine as _gse
        diag = _gse.get_engine().diagnose_and_heal(auto_start=True, wait_seconds=timeout_seconds)
        if diag.get("ok"):
            if verbose:
                mode_txt = "HTTP Socket" if diag.get("mode") == "http_socket" else "Tubería Directa Nativa"
                print(f"[BOOTSTRAP] [OK] Motor Soberano en línea ({mode_txt} en {diag.get('endpoint') or 'Subprocess'})")
            return True
    except Exception:
        pass

    if is_ollama_alive(endpoint, timeout=1.5):
        if verbose:
            print(f"[BOOTSTRAP] [OK] Ollama activo en {endpoint}")
        return True

    if verbose:
        print(f"[BOOTSTRAP] [*] Ollama no detectado en {endpoint}. Iniciando servicio local en segundo plano...")

    started = start_ollama_service(endpoint)
    if not started:
        if verbose:
            print("[BOOTSTRAP] [X] No fue posible iniciar el servicio Ollama automaticamente.")
        return False

    start_time = time.time()
    sleep_interval = 0.4
    while time.time() - start_time < timeout_seconds:
        time.sleep(sleep_interval)
        if is_ollama_alive(endpoint, timeout=1.0):
            elapsed = time.time() - start_time
            if verbose:
                print(f"[BOOTSTRAP] [OK] Ollama conectado y listo en {elapsed:.1f}s ({endpoint})")
            return True
        sleep_interval = min(1.5, sleep_interval * 1.3)

    if verbose:
        print(f"[BOOTSTRAP] [!] Tiempo de espera agotado ({timeout_seconds}s) esperando a Ollama.")
    return is_ollama_alive(endpoint, timeout=1.5)


def list_local_models(endpoint: str = DEFAULT_OLLAMA_ENDPOINT) -> List[str]:
    """Obtiene la lista de modelos descargados localmente en Ollama."""
    try:
        import gia_sovereign_engine as _gse
        models = _gse.get_engine().get_available_models(refresh=True)
        if models:
            return models
    except Exception:
        pass

    ep = normalize_endpoint(endpoint)
    url = f"{ep}/api/tags"
    req = urllib.request.Request(url, headers={"User-Agent": "GIA-Bootstrap/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                return models
    except Exception:
        pass
    return []


def resolve_best_model(preferred_model: Optional[str] = None, endpoint: str = DEFAULT_OLLAMA_ENDPOINT) -> str:
    """Selecciona el mejor modelo LLM disponible localmente en el nodo."""
    try:
        import gia_sovereign_engine as _gse
        return _gse.get_engine().resolve_model(preferred_model)
    except Exception:
        pass

    models = list_local_models(endpoint)
    if not models:
        return preferred_model or DEFAULT_MODELS_PREFERENCE[0]

    if preferred_model:
        for m in models:
            if m == preferred_model or m.startswith(f"{preferred_model}:") or preferred_model.startswith(f"{m}:"):
                return m

    for pref in DEFAULT_MODELS_PREFERENCE:
        for m in models:
            if m == pref or m.startswith(f"{pref}:") or pref.startswith(f"{m}:") or pref in m:
                return m

    return models[0]


def ensure_storage_and_tokens() -> str:
    """Garantiza la existencia de los directorios de control y el token irrevocable."""
    GIA_STORAGE.mkdir(parents=True, exist_ok=True)
    (GIA_STORAGE / "antigravity_bridge").mkdir(parents=True, exist_ok=True)
    (GIA_STORAGE / "improvement_queue").mkdir(parents=True, exist_ok=True)
    (GIA_STORAGE / "memory").mkdir(parents=True, exist_ok=True)

    token = None
    if TOKEN_FILE.exists():
        try:
            tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if len(tok) >= 8:
                token = tok
        except Exception:
            pass

    if not token and TOKEN_STORAGE_FILE.exists():
        try:
            tok = TOKEN_STORAGE_FILE.read_text(encoding="utf-8").strip()
            if len(tok) >= 8:
                token = tok
        except Exception:
            pass

    if not token:
        token = secrets.token_urlsafe(24)

    try:
        TOKEN_FILE.write_text(token, encoding="utf-8")
    except Exception:
        pass

    try:
        TOKEN_STORAGE_FILE.write_text(token, encoding="utf-8")
    except Exception:
        pass

    return token


def ensure_all_dependencies(preferred_model: Optional[str] = None, verbose: bool = True) -> Dict[str, Any]:
    """
    Función Maestra de Autoinicio: Comprueba e inicializa todas las dependencias
    necesarias para la ejecución inmediata y sin fallos del sistema GIA.
    """
    token = ensure_storage_and_tokens()
    ollama_ok = ensure_ollama(DEFAULT_OLLAMA_ENDPOINT, timeout_seconds=25.0, verbose=verbose)
    models = list_local_models(DEFAULT_OLLAMA_ENDPOINT)
    active_model = resolve_best_model(preferred_model, DEFAULT_OLLAMA_ENDPOINT)

    result = {
        "ok": ollama_ok,
        "ollama_alive": ollama_ok,
        "endpoint": DEFAULT_OLLAMA_ENDPOINT,
        "active_model": active_model,
        "available_models": models,
        "token": token,
        "storage_dir": str(GIA_STORAGE),
        "timestamp": time.time()
    }

    if verbose:
        print(f"[BOOTSTRAP] >> Estado Maestro: Motor={'ONLINE' if ollama_ok else 'OFFLINE'} | Modelo Activo={active_model} | Modelos Disponibles={len(models)}")

    return result


if __name__ == "__main__":
    print("=== GIA Universal Bootstrap Engine ===")
    res = ensure_all_dependencies(verbose=True)
    print(json.dumps(res, indent=2, ensure_ascii=False))
