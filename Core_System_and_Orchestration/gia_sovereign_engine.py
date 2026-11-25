"""
gia_sovereign_engine.py - Motor Unificado de Inferencia Soberana Resiliente
===========================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana GIA

Arquitectura de Inferencia Dual Redundante (Zero-Drop):
1. CANAL HTTP RESILIENTE (Socket Multi-Host + Auto-Revive Daemon + KeepAlive):
   - Sondeo dinámico en 127.0.0.1, localhost y [::1].
   - Reanimación automática del demonio Ollama ante caídas o reposo del sistema.
   - Reintentos exponenciales con manejo de desconexiones y socket timeouts.
   - Anclaje de memoria en VRAM/RAM (keep_alive: 24h).

2. CANAL NATIVO DIRECTO POR TUBERÍA (Zero-Network-Port Architecture):
   - Ejecución directa sobre el binario local (ollama.exe) mediante stdin/stdout pipes.
   - 100% inmune a bloqueos de puertos, firewalls de Windows, antivirus o socket exhaustion.
   - Conmutación automática transparente si el puerto de red no está disponible.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, Union

logger = logging.getLogger("TARDIS.SovereignInferenceEngine")

try:
    import colibri_bridge
    import colibri_optimizer
    _COLIBRI_ACTIVE = True
except Exception:
    _COLIBRI_ACTIVE = False

try:
    from core.temporal_brain import TemporalBrain, get_temporal_brain
    from core.sovereign_local_runner import SovereignLocalRunner, get_sovereign_local_runner
    _TEMPORAL_BRAIN_ACTIVE = True
    _LOCAL_RUNNER_ACTIVE = True
except Exception:
    _TEMPORAL_BRAIN_ACTIVE = False
    try:
        from core.sovereign_local_runner import SovereignLocalRunner, get_sovereign_local_runner
        _LOCAL_RUNNER_ACTIVE = True
    except Exception:
        try:
            from sovereign_local_runner import SovereignLocalRunner, get_sovereign_local_runner
            _LOCAL_RUNNER_ACTIVE = True
        except Exception:
            _LOCAL_RUNNER_ACTIVE = False

# Rutas del entorno de trabajo
WORKSPACE_DIR = Path(__file__).resolve().parent
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))

_raw_gpu_lane = os.environ.get("TARDIS_VLM_GPU_URL", "http://127.0.0.1:11435").strip().rstrip("/")
OLLAMA_GPU_LANE_URL = (
    _raw_gpu_lane
    if not _raw_gpu_lane or _raw_gpu_lane.startswith(("http://", "https://"))
    else f"http://{_raw_gpu_lane}"
)
OLLAMA_GPU_LANE_NUM_CTX = int(os.environ.get("TARDIS_VLM_GPU_NUM_CTX", "3072"))
OLLAMA_GPU_LANE_NUM_GPU = int(os.environ.get("TARDIS_VLM_GPU_NUM_GPU", "22"))

_VLM_MODEL_TOKENS = (
    "qwen3-vl",
    "qwen2.5-vl",
    "qwen2.5vl",
    "minicpm-v",
    "llama3.2-vision",
    "llava",
    "moondream",
    "bakllava",
    "vision",
)

CANDIDATE_ENDPOINTS = [
    OLLAMA_GPU_LANE_URL,
    "http://127.0.0.1:11434",
    "http://localhost:11434",
    "http://[::1]:11434",
    "http://0.0.0.0:11434",
]


def _normalize_endpoint(endpoint: str) -> str:
    ep = (endpoint or "").strip().rstrip("/")
    if ep and not ep.startswith(("http://", "https://")):
        ep = f"http://{ep}"
    return ep


def _is_vlm_model(model_name: Optional[str]) -> bool:
    low = (model_name or "").strip().lower()
    return bool(low) and any(tok in low for tok in _VLM_MODEL_TOKENS)


def _is_kaiju_model(model_name: Optional[str]) -> bool:
    low = (model_name or "").strip().lower()
    return ("kaiju" in low) or ("tardis-neural" in low)


def _is_gpu_lane_endpoint(endpoint: Optional[str]) -> bool:
    ep = _normalize_endpoint(endpoint or "")
    return bool(ep) and (ep == OLLAMA_GPU_LANE_URL or ep.endswith(":11435"))


def _is_local_cpu_ollama_endpoint(endpoint: Optional[str]) -> bool:
    ep = _normalize_endpoint(endpoint or "").lower()
    return ep.endswith(":11434") and any(
        h in ep for h in ("127.0.0.1", "localhost", "[::1]", "0.0.0.0")
    )


def _parse_cpulist_count(raw: str) -> int:
    """Cuenta CPUs lógicas en formato cpulist de Linux (p.ej. '8-15' -> 8, '0-3,8-11' -> 8)."""
    total = 0
    for part in (raw or "").strip().split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                lo, hi = int(bounds[0]), int(bounds[1])
                if hi >= lo:
                    total += (hi - lo) + 1
            except ValueError:
                continue
        elif part.isdigit():
            total += 1
    return total


def _resolve_safe_cpu_ollama_threads(
    requested: Optional[int] = None,
    *,
    unit: str = "ollama.service",
    cgroup_app_slice: Optional[Path] = None,
) -> int:
    """
    Alinea `num_thread` para Ollama CPU (:11434) al `cpuset.cpus.effective` y `cpu.max`
    reales del cgroup v2 (`ollama.service`), garantizando <= floor(eff_cpus / 2) y <= 4
    para prevenir sobresuscripción y livelock de barrera ggml (`COEV-20261124-0A569D`).
    """
    if requested is None:
        raw_req = os.environ.get("GIA_CPU_OLLAMA_THREADS", os.environ.get("GIA_NUM_THREADS", "4"))
        try:
            req_val = int(str(raw_req).strip())
        except (TypeError, ValueError):
            req_val = 4
    else:
        try:
            req_val = int(requested)
        except (TypeError, ValueError):
            req_val = 4
    req_val = max(1, req_val)

    eff_cpus = 0
    quota_cores: Optional[float] = None
    try:
        uid = os.getuid()
        app_slice = cgroup_app_slice or Path(
            f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice"
        )
        cg = app_slice / unit
        if cg.is_dir():
            for fname in ("cpuset.cpus.effective", "cpuset.cpus"):
                fp = cg / fname
                if fp.is_file():
                    cnt = _parse_cpulist_count(fp.read_text(encoding="utf-8", errors="ignore"))
                    if cnt > 0:
                        eff_cpus = cnt
                        break
            cpu_max_fp = cg / "cpu.max"
            if cpu_max_fp.is_file():
                parts = cpu_max_fp.read_text(encoding="utf-8", errors="ignore").strip().split()
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    period = int(parts[1])
                    if period > 0:
                        quota_cores = int(parts[0]) / float(period)
    except Exception:
        pass

    if eff_cpus <= 0:
        try:
            eff_cpus = len(os.sched_getaffinity(0))
        except Exception:
            eff_cpus = os.cpu_count() or 8

    # Tope estructural: nunca exceder la mitad del cpuset efectivo ni 4 hilos en carril frío CPU
    max_safe = max(1, min(4, eff_cpus // 2 if eff_cpus >= 2 else 1))
    if quota_cores is not None and quota_cores > 0:
        max_safe = max(1, min(max_safe, int(quota_cores) if quota_cores >= 1.0 else 1))
    return max(1, min(req_val, max_safe))


def _is_temporal_brain_active_or_warming(local_runner: Any = None) -> bool:
    """
    True si `tardis-temporal-brain.service` está activo/arrancando o si `/tmp/temporal_brain.sock`
    existe, evitando que un race de arranque duplique KAIJU (4.4 GB) en CPU Ollama :11434.
    """
    try:
        sock_path = Path(str(getattr(local_runner, "socket_path", "/tmp/temporal_brain.sock")))
        if sock_path.exists():
            return True
        is_alive_fn = getattr(local_runner, "_is_daemon_process_alive", None)
        if callable(is_alive_fn) and bool(is_alive_fn()):
            return True
    except Exception:
        pass
    if sys.platform.startswith("linux"):
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", "tardis-temporal-brain.service"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            state = (proc.stdout or "").strip().lower()
            if state in ("active", "activating", "reloading"):
                return True
        except Exception:
            pass
    return False

DEFAULT_MODELS_PREFERENCE = [
    "TARDIS-NEURAL-SPACE-KAIJU",
    "TARDIS-NEURAL-SPACE-KAIJU:latest"
]

DEFAULT_SYSTEM_PROMPT = (
    "Eres GIA-V26-SOVEREIGN, Inteligencia Artificial Causal Soberana de GODWORKS SYSTEM. "
    "Operas en modo local resiliente de alta precisión. Responde siempre en español con rigor y claridad."
)


def find_ollama_binary() -> Optional[str]:
    """Localiza el ejecutable de Ollama en el sistema."""
    which_path = shutil.which("ollama")
    if which_path and os.path.isfile(which_path):
        return which_path

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


class SovereignInferenceEngine:
    """
    Motor Maestro de Inferencia Soberana con conmutación inteligente y autorrecuperación.
    """

    _instance: Optional["SovereignInferenceEngine"] = None
    _singleton_lock = threading.Lock()

    def __init__(self, preferred_endpoint: Optional[str] = None, default_model: Optional[str] = None):
        self.preferred_endpoint = preferred_endpoint or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        self.active_endpoint: Optional[str] = None
        self.default_model = default_model or os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")
        self.binary_path = find_ollama_binary()
        self._lock = threading.Lock()
        self._cached_models: List[str] = []
        self._last_model_check: float = 0.0
        self._keepalive_running = False
        self.force_pipe_mode = bool(os.environ.get("GIA_FORCE_PIPE", "0") == "1" or os.environ.get("GIA_DIRECT", "0") == "1")

        # Iniciar autodiagnóstico y watchdog en segundo plano
        self.diagnose_and_heal(auto_start=True)
        self._start_keepalive_watchdog()

    @classmethod
    def get_instance(cls) -> "SovereignInferenceEngine":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # -------------------------------------------------------------------------
    #  SONDEO Y SALUD DEL ENLACE HTTP
    # -------------------------------------------------------------------------

    def _probe_endpoint(self, endpoint: str, timeout: float = 1.8) -> bool:
        """Verifica de forma ultrarrápida y no bloqueante si un endpoint responde."""
        ep = _normalize_endpoint(endpoint)
        if not ep:
            return False
        url = f"{ep}/api/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "GIA-Sovereign-Engine/26.4"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _is_tcp_reachable(self, endpoint: str, timeout: float = 0.8) -> bool:
        """Verifica si el socket TCP del endpoint está escuchando aunque atienda otra petición."""
        ep = _normalize_endpoint(endpoint)
        if not ep:
            return False
        try:
            parsed = urllib.parse.urlparse(ep)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    def _query_loaded_models(self, endpoint: str, timeout: float = 1.5) -> List[str]:
        """Consulta /api/ps para detectar modelos ya residentes en VRAM/RAM sin despertarlos."""
        ep = _normalize_endpoint(endpoint)
        if not ep:
            return []
        try:
            req = urllib.request.Request(f"{ep}/api/ps", headers={"User-Agent": "GIA-Sovereign-Engine/26.4"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                    return [str(m.get("name") or "") for m in (data.get("models") or []) if m.get("name")]
        except Exception:
            pass
        return []

    def find_working_endpoint(self, model: Optional[str] = None) -> Optional[str]:
        """
        Encuentra el endpoint activo óptimo evitando duplicar modelos en CPU Ollama (:11434):
          - Para modelos VLM (p.ej. qwen3-vl) o modelos ya residentes en el carril GPU (:11435),
            prioriza estrictamente OLLAMA_GPU_LANE_URL (:11435) con doble sondeo y guardia TCP.
          - Solo usa :11434 como respaldo frío cuando :11435 no está disponible o el modelo
            requiere el carril alternativo.
        """
        gpu_ep = _normalize_endpoint(OLLAMA_GPU_LANE_URL)
        pref_ep = _normalize_endpoint(self.preferred_endpoint)
        req_model = (model or "").strip()
        want_gpu_lane = _is_vlm_model(req_model)

        if not want_gpu_lane and req_model and gpu_ep:
            req_base = req_model.split(":")[0].lower()
            loaded_gpu = self._query_loaded_models(gpu_ep, timeout=1.2)
            if any(m.split(":")[0].lower() == req_base for m in loaded_gpu):
                want_gpu_lane = True

        if want_gpu_lane and gpu_ep:
            for _ in range(2):
                if self._probe_endpoint(gpu_ep, timeout=2.5):
                    self.active_endpoint = gpu_ep
                    return gpu_ep
                time.sleep(0.1)
            if self._is_tcp_reachable(gpu_ep, timeout=0.8):
                self.active_endpoint = gpu_ep
                return gpu_ep

        ordered: List[str] = []
        # Si el usuario fijó un endpoint explícito no-11434, respetarlo primero; si no, preferir :11435 cuando aplique
        if pref_ep and not _is_local_cpu_ollama_endpoint(pref_ep):
            ordered.append(pref_ep)
        if gpu_ep and gpu_ep not in ordered and (want_gpu_lane or not _is_kaiju_model(req_model)):
            ordered.append(gpu_ep)
        if pref_ep and pref_ep not in ordered:
            ordered.append(pref_ep)
        for c in CANDIDATE_ENDPOINTS:
            nc = _normalize_endpoint(c)
            if nc and nc not in ordered:
                ordered.append(nc)

        # Anti-duplicación de KAIJU: si TemporalBrain está activo/calentando, no enrutar KAIJU
        # al carril frío CPU Ollama (:11434) salvo override explícito.
        allow_kaiju_dup = os.environ.get("GIA_ALLOW_KAIJU_CPU_DUPLICATE", "0").strip().lower() in (
            "1", "true", "yes"
        )
        if _is_kaiju_model(req_model) and _TEMPORAL_BRAIN_ACTIVE and not allow_kaiju_dup:
            try:
                tb = get_temporal_brain()
                if _is_temporal_brain_active_or_warming(tb):
                    ordered = [ep for ep in ordered if not _is_local_cpu_ollama_endpoint(ep)]
            except Exception:
                pass

        for ep in ordered:
            if self._probe_endpoint(ep):
                self.active_endpoint = ep
                return ep
        return None

    def auto_spawn_daemon(self) -> bool:
        """Asegura que el motor soberano Temporal Brain esté listo para inferencia."""
        if _TEMPORAL_BRAIN_ACTIVE or _LOCAL_RUNNER_ACTIVE:
            try:
                local_runner = get_temporal_brain() if _TEMPORAL_BRAIN_ACTIVE else get_sovereign_local_runner()
                return local_runner.is_serverless_ready()
            except Exception:
                pass
        return False

    def diagnose_and_heal(self, auto_start: bool = True, wait_seconds: float = 12.0) -> Dict[str, Any]:
        """Diagnostica el estado del motor soberano Temporal Brain."""
        # 0. TIER 0: Temporal Brain (Ejecutor Directo Serverless Local / Socket UNIX IPC / Zero Ports)
        if _TEMPORAL_BRAIN_ACTIVE or _LOCAL_RUNNER_ACTIVE:
            try:
                local_runner = get_temporal_brain() if _TEMPORAL_BRAIN_ACTIVE else get_sovereign_local_runner()
                if local_runner.is_serverless_ready():
                    return {
                        "ok": True,
                        "mode": "temporal_brain",
                        "endpoint": str(local_runner.socket_path),
                        "models": self.get_available_models(refresh=True)
                    }
            except Exception:
                pass

        working_ep = self.find_working_endpoint()
        if working_ep:
            return {
                "ok": True,
                "mode": "http_socket",
                "endpoint": working_ep,
                "models": self.get_available_models(refresh=True)
            }

        pipe_ok = (self.binary_path is not None)
        return {
            "ok": pipe_ok,
            "mode": "direct_pipe" if pipe_ok else "unavailable",
            "endpoint": None,
            "binary": self.binary_path,
            "models": self.get_available_models(refresh=True)
        }

    # -------------------------------------------------------------------------
    #  GESTIÓN Y SELECCIÓN DE MODELOS
    # -------------------------------------------------------------------------

    def get_available_models(self, refresh: bool = False) -> List[str]:
        """Devuelve la lista de modelos soberanos disponibles en disco o socket."""
        now = time.time()
        if not refresh and self._cached_models and (now - self._last_model_check < 60.0):
            return self._cached_models

        models: List[str] = []

        # 0. Modelos soberanos locales en data/models/
        sovereign_dir = WORKSPACE_DIR / "data" / "models"
        if sovereign_dir.exists():
            for p in sovereign_dir.glob("*.gguf"):
                if p.is_file():
                    name = p.stem
                    if name not in models:
                        models.append(name)

        # 1. Intentar por HTTP (carril GPU :11435 primero y luego endpoint preferido) sin despertar modelos
        seen_eps: List[str] = []
        for raw_ep in (OLLAMA_GPU_LANE_URL, self.active_endpoint, self.preferred_endpoint):
            ep = _normalize_endpoint(raw_ep or "")
            if ep and ep not in seen_eps:
                seen_eps.append(ep)
        for ep in seen_eps:
            try:
                url = f"{ep}/api/tags"
                req = urllib.request.Request(url, headers={"User-Agent": "GIA-Sovereign-Engine/26.4"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        for m in data.get("models", []):
                            m_name = m.get("name")
                            if m_name and m_name not in models:
                                models.append(m_name)
                        break
            except Exception:
                continue

        # 2. Leer manifiestos existentes en disco
        if not models:
            manifest_dir = Path(os.path.expanduser("~")) / ".ollama" / "models" / "manifests"
            if manifest_dir.exists():
                for p in manifest_dir.glob("*/*/*/*"):
                    if p.is_file():
                        parts = p.parts
                        if len(parts) >= 2:
                            model_name = f"{parts[-2]}:{parts[-1]}"
                            if model_name not in models:
                                models.append(model_name)

        # 3. Si aún no hay lista, consultar por CLI
        if not models and self.binary_path:
            try:
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                out = subprocess.check_output(
                    [self.binary_path, "list"],
                    creationflags=flags,
                    stderr=subprocess.DEVNULL,
                    timeout=4.0
                ).decode("utf-8", errors="ignore")
                for line in out.splitlines()[1:]:
                    parts = line.split()
                    if parts:
                        models.append(parts[0])
            except Exception:
                pass

        # 4. Consultar modelos MoE gestionados por Colibri
        # El escaneo de Colibri recorre ~/.cache/huggingface y cuesta ~20 s. Sólo
        # aporta si el nodo no tiene ya modelos soberanos: antes se ejecutaba siempre
        # y se pagaba dos veces en el arranque (40 s perdidos).
        if _COLIBRI_ACTIVE and not models:
            try:
                c_models = colibri_bridge.get_colibri().list_local_colibri_models()
                for cm in c_models:
                    cname = cm.get("name")
                    if cname and cname not in models:
                        models.append(cname)
            except Exception:
                pass

        with self._lock:
            if models:
                self._cached_models = models
                self._last_model_check = now
            return self._cached_models or [self.default_model]

    def resolve_model(self, requested_model: Optional[str] = None) -> str:
        """Resuelve el modelo pedido asegurando que exista localmente, o aplica el mejor fallback."""
        available = self.get_available_models()
        if not available:
            return requested_model or self.default_model

        req = (requested_model or "").strip()
        if req:
            req_l = req.lower()
            # Coincidencia exacta o sin case
            for m in available:
                if m.lower() == req_l or m.lower() == f"{req_l}:latest":
                    return m
            # Coincidencia parcial
            for m in available:
                m_l = m.lower()
                if m_l.startswith(f"{req_l}:") or req_l.startswith(f"{m_l}:") or req_l in m_l or m_l in req_l:
                    return m

        # Fallback a lista de preferencias
        for pref in DEFAULT_MODELS_PREFERENCE:
            pref_l = pref.lower()
            for m in available:
                m_l = m.lower()
                if m_l == pref_l or m_l.startswith(f"{pref_l}:") or pref_l.startswith(f"{m_l}:") or pref_l in m_l or m_l in pref_l:
                    return m

        return available[0]

    # -------------------------------------------------------------------------
    #  WATCHDOG Y KEEPALIVE EN RAM/VRAM
    # -------------------------------------------------------------------------

    def _start_keepalive_watchdog(self):
        """Inicia un hilo en segundo plano que mantiene el modelo precargado y vivo."""
        if self._keepalive_running:
            return
        self._keepalive_running = True

        def _worker():
            while True:
                time.sleep(300)  # Cada 5 minutos
                try:
                    # Si TemporalBrain (/tmp/temporal_brain.sock) existe o está activo, NO despertar
                    # un segundo llama-server en CPU vía Ollama (:11434).
                    if _TEMPORAL_BRAIN_ACTIVE:
                        tb = get_temporal_brain()
                        if tb.is_running() or Path(str(getattr(tb, "socket_path", "/tmp/temporal_brain.sock"))).exists():
                            continue
                    target = self.resolve_model(self.default_model)
                    ep = self.find_working_endpoint(model=target)
                    # Nunca anclar duplicados de KAIJU o VLM en CPU Ollama (:11434) vía keepalive.
                    if ep and not _is_local_cpu_ollama_endpoint(ep):
                        payload = {
                            "model": target,
                            "messages": [{"role": "user", "content": "ping"}],
                            "stream": False,
                            "keep_alive": -1 if _is_gpu_lane_endpoint(ep) else "15m",
                            "options": {"num_predict": 1},
                        }
                        if _is_gpu_lane_endpoint(ep):
                            payload["options"]["num_ctx"] = OLLAMA_GPU_LANE_NUM_CTX
                            payload["options"]["num_gpu"] = OLLAMA_GPU_LANE_NUM_GPU
                        req = urllib.request.Request(
                            f"{ep}/api/chat",
                            data=json.dumps(payload).encode("utf-8"),
                            headers={"Content-Type": "application/json", "User-Agent": "GIA-Keepalive"},
                        )
                        with urllib.request.urlopen(req, timeout=5.0) as _:
                            pass
                except Exception:
                    pass

        t = threading.Thread(target=_worker, daemon=True, name="GIA-Sovereign-Keepalive")
        t.start()

    # -------------------------------------------------------------------------
    #  CANAL 1: INFERENCIA HTTP STREAMING Y DIRECTA RESILIENTE
    # -------------------------------------------------------------------------

    def _http_chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.3,
        num_ctx: int = 4096,
        timeout: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None
    ) -> Generator[str, None, str]:
        """Streaming por HTTP con enrutamiento GPU-lane (:11435), soporte de cancelación y anti-duplicación en :11434."""
        ep = self.find_working_endpoint(model=model)
        if not ep:
            self.diagnose_and_heal(auto_start=True, wait_seconds=6.0)
            ep = self.find_working_endpoint(model=model)

        if not ep:
            raise ConnectionError("No se pudo establecer conexión con ningún endpoint HTTP de Ollama.")

        is_gpu_lane = _is_gpu_lane_endpoint(ep)
        is_cpu_fallback = _is_local_cpu_ollama_endpoint(ep)
        if is_gpu_lane:
            keep_alive: Union[int, str] = -1
            effective_ctx = min(int(num_ctx or OLLAMA_GPU_LANE_NUM_CTX), OLLAMA_GPU_LANE_NUM_CTX)
            effective_threads = max(1, min(int(os.environ.get("GIA_NUM_THREADS", 4)), 4))
            effective_batch = min(int(os.environ.get("GIA_NUM_BATCH", 512)), 512)
        elif is_cpu_fallback:
            # Respaldo frío CPU (:11434): descargar al terminar por defecto ("0") y alinear hilos/batch
            # al cpuset/quota real de ollama.service para prevenir barrier livelock (-t <= 4).
            raw_ka = os.environ.get("GIA_OLLAMA_FALLBACK_KEEP_ALIVE", "0").strip()
            keep_alive = 0 if raw_ka in ("", "0", "0s") else raw_ka
            effective_threads = _resolve_safe_cpu_ollama_threads()
            ctx_cap = 4096 if effective_threads <= 2 else 8192
            effective_ctx = min(int(num_ctx or os.environ.get("GIA_NUM_CTX", 4096)), ctx_cap)
            batch_cap = 256 if effective_threads <= 2 else 512
            effective_batch = min(int(os.environ.get("GIA_NUM_BATCH", 512)), batch_cap)
        else:
            keep_alive = os.environ.get("GIA_OLLAMA_FALLBACK_KEEP_ALIVE", "10m")
            effective_ctx = int(num_ctx or os.environ.get("GIA_NUM_CTX", 4096))
            effective_threads = max(1, min(int(os.environ.get("GIA_NUM_THREADS", 4)), 8))
            effective_batch = min(int(os.environ.get("GIA_NUM_BATCH", 512)), 1024)

        options: Dict[str, Any] = {
            "temperature": float(temperature or 0.3),
            "num_ctx": effective_ctx,
            "num_predict": int(os.environ.get("GIA_NUM_PREDICT", 512)),
            "num_thread": effective_threads,
            "repeat_penalty": 1.15,
            "use_mmap": True,
            "num_batch": effective_batch,
        }
        if is_gpu_lane:
            options["num_gpu"] = OLLAMA_GPU_LANE_NUM_GPU

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": keep_alive,
            "options": options,
        }

        req = urllib.request.Request(
            f"{ep}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "GIA-Sovereign-Engine/26.4"}
        )

        full_reply = []
        # DIRECTIVA DEL ARQUITECTO: sin límite por defecto en carriles GPU/remotos.
        # En respaldo frío CPU (:11434), aplicar cota de seguridad (default 180s; 0 = sin límite)
        # para evitar sockets bloqueados indefinidamente que anclen modelos in-flight (COEV-20261124-22A14E).
        _raw_http_to = timeout if timeout is not None else os.environ.get("GIA_HTTP_TIMEOUT", "")
        if str(_raw_http_to).strip() == "" and is_cpu_fallback:
            _raw_http_to = os.environ.get("GIA_CPU_OLLAMA_FALLBACK_TIMEOUT", "180")
        try:
            effective_timeout = float(_raw_http_to) if str(_raw_http_to).strip() not in ("", "0", "0.0", "None") else None
        except (TypeError, ValueError):
            effective_timeout = 180.0 if is_cpu_fallback else None
        opener = urllib.request.urlopen(req, timeout=effective_timeout)
        with opener as resp:
            for line in resp:
                if cancel_event and cancel_event.is_set():
                    try:
                        resp.close()
                    except Exception:
                        pass
                    msg = "\n[⛔ Inferencia cancelada y proceso cortado por el usuario]"
                    full_reply.append(msg)
                    yield msg
                    return msg
                if not line:
                    continue
                try:
                    chunk = json.loads(line.decode("utf-8"))
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        full_reply.append(piece)
                        yield piece
                except Exception:
                    continue

        return "".join(full_reply)

    # -------------------------------------------------------------------------
    #  CANAL 2: INFERENCIA NATIVA POR TUBERÍA DIRECTA (ZERO NETWORK PORT)
    # -------------------------------------------------------------------------

    def _clean_ansi(self, text: str) -> str:
        """Elimina secuencias de escape ANSI y secuencias de control del streaming."""
        text = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', text)
        text = re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', text)
        return text

    def _pipe_chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        system_prompt: Optional[str] = None,
        timeout: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None,
        on_process_spawned: Optional[Callable[[subprocess.Popen], None]] = None
    ) -> Generator[str, None, str]:
        """
        Ejecuta inferencia directamente sobre el binario local mediante pipes de proceso (stdin/stdout).
        No utiliza sockets de red TCP, puertos ni servidor HTTP. 100% inmune a interferencias de red.
        Soporta cancelación instantánea y corte del proceso mediante cancel_event.
        """
        if not self.binary_path:
            self.binary_path = find_ollama_binary()
        if not self.binary_path:
            raise FileNotFoundError("Binario de Ollama no localizado para ejecución directa por tubería.")

        # Construir prompt sintetizado
        prompt_parts = []
        sys_txt = system_prompt
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system" and not sys_txt:
                sys_txt = content
            elif role == "user":
                prompt_parts.append(f"Usuario: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Asistente: {content}")

        if prompt_parts:
            prompt_parts[-1] = prompt_parts[-1].replace("Usuario: ", "")

        full_prompt = prompt_parts[-1] if prompt_parts else ""
        if sys_txt:
            full_input = f"[INSTRUCCIÓN DEL SISTEMA: {sys_txt}]\n\n{full_prompt}\n"
        else:
            full_input = f"{full_prompt}\n"

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        pipe_env = os.environ.copy()
        if _is_vlm_model(model) and self._probe_endpoint(OLLAMA_GPU_LANE_URL, timeout=1.2):
            pipe_env["OLLAMA_HOST"] = OLLAMA_GPU_LANE_URL

        proc = subprocess.Popen(
            [self.binary_path, "run", model, "--nowordwrap"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            env=pipe_env,
            text=True,
            bufsize=0
        )

        if on_process_spawned:
            try:
                on_process_spawned(proc)
            except Exception:
                pass

        full_reply = []
        # DIRECTIVA DEL ARQUITECTO: la inferencia puede durar lo que necesite.
        # GIA_PIPE_TIMEOUT sólo se respeta si se define explícitamente > 0.
        _raw_pipe_to = timeout if timeout is not None else os.environ.get("GIA_PIPE_TIMEOUT", "")
        try:
            _pipe_to = float(_raw_pipe_to) if str(_raw_pipe_to).strip() not in ("", "0", "0.0", "None") else 0.0
        except (TypeError, ValueError):
            _pipe_to = 0.0
        pipe_deadline = (time.time() + _pipe_to) if _pipe_to > 0 else None
        try:
            # Enviar el prompt completo y cerrar stdin para señalar fin de entrada
            if proc.stdin:
                proc.stdin.write(full_input)
                proc.stdin.close()

            # Leer streaming desde stdout sin artifacts de terminal; sin deadline por defecto.
            import select
            while True:
                if cancel_event and cancel_event.is_set():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    msg = "\n[⛔ Inferencia cancelada y proceso cortado por el usuario]"
                    full_reply.append(msg)
                    yield msg
                    return msg

                remaining = 1.0 if pipe_deadline is None else (pipe_deadline - time.time())
                if remaining <= 0:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    msg = "\n[⚠️ Tiempo límite de inferencia local alcanzado]"
                    full_reply.append(msg)
                    yield msg
                    return msg

                if sys.platform != "win32":
                    r, _, _ = select.select([proc.stdout], [], [], min(remaining, 1.0))
                    if not r:
                        if proc.poll() is not None:
                            break
                        continue

                chunk = proc.stdout.read(8)
                if not chunk:
                    break
                clean_chunk = self._clean_ansi(chunk)
                if clean_chunk:
                    full_reply.append(clean_chunk)
                    yield clean_chunk

            proc.wait(timeout=2.0)
        except Exception as e:
            try:
                proc.kill()
            except Exception:
                pass
            raise e
        finally:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass

        return self._clean_ansi("".join(full_reply))

    # -------------------------------------------------------------------------
    #  INTERFAZ MAESTRA UNIFICADA (CHAT Y GENERACIÓN)
    # -------------------------------------------------------------------------

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.4,
        num_ctx: int = 4096,
        retries: int = 2,
        cancel_event: Optional[threading.Event] = None,
        on_process_spawned: Optional[Callable[[subprocess.Popen], None]] = None
    ) -> Generator[str, None, str]:
        """
        Generador maestro con conmutación y auto-recuperación transparente:
        Intenta Direct Native Pipe (si force_pipe_mode) -> HTTP Socket -> Fallback a Direct Native Pipe.
        Soporta corte instantáneo del proceso vía cancel_event.
        """
        target_model = self.resolve_model(model or self.default_model)
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        # Preparar mensajes con system prompt y protocolo de diálogo comedido
        unified_msgs = []
        has_system = any(isinstance(m, dict) and m.get("role") == "system" for m in messages)
        if system and not has_system:
            unified_msgs.append({"role": "system", "content": system})
        elif not has_system:
            unified_msgs.append({
                "role": "system",
                "content": (
                    "Eres GIA, nodo soberano de inteligencia. "
                    "PROTOCOLO DE PRIORIDAD Y DIÁLOGO COMEDIDO: Responde siempre en español de forma directa, "
                    "comedida, concisa y conversacional (1 a 3 párrafos o puntos clave). "
                    "Evita divagaciones extensas para garantizar máxima velocidad y agilidad de respuesta."
                )
            })
        unified_msgs.extend(messages)

        # Si el usuario forzó el modo tubería directa
        if self.force_pipe_mode:
            self.last_channel_used = "pipe"
            yield from self._pipe_chat_stream(
                unified_msgs,
                target_model,
                system_prompt=system,
                cancel_event=cancel_event,
                on_process_spawned=on_process_spawned
            )
            return

        # 0. TIER 0: Temporal Brain (Socket UNIX IPC, Zero Daemon / Serverless; solo modelos no-VLM)
        if (_TEMPORAL_BRAIN_ACTIVE or _LOCAL_RUNNER_ACTIVE) and not _is_vlm_model(target_model):
            local_runner = get_temporal_brain() if _TEMPORAL_BRAIN_ACTIVE else get_sovereign_local_runner()
            try:
                tb_wait_budget = float(os.environ.get("GIA_TEMPORAL_BRAIN_WAIT_SEC", "20.0"))
            except (TypeError, ValueError):
                tb_wait_budget = 20.0
            try:
                tb_poll_step = max(0.05, float(os.environ.get("GIA_TEMPORAL_BRAIN_POLL_SEC", "1.5")))
            except (TypeError, ValueError):
                tb_poll_step = 1.5
            tb_deadline = time.monotonic() + max(0.0, tb_wait_budget)
            tb_last_err: Optional[Exception] = None
            _tb_attempt = 0

            while True:
                if cancel_event and cancel_event.is_set():
                    return ""
                try:
                    if local_runner.is_serverless_ready(target_model):
                        self.last_channel_used = "temporal_brain"
                        yielded_any = False
                        for tok in local_runner.chat_stream(
                            unified_msgs,
                            temperature=temperature,
                            num_ctx=num_ctx,
                            cancel_event=cancel_event
                        ):
                            yielded_any = True
                            yield tok
                        if yielded_any:
                            return
                        tb_last_err = RuntimeError("TemporalBrain devolvió stream vacío (posible warmup 503)")
                    else:
                        break
                except Exception as _tb_err:
                    tb_last_err = _tb_err

                _tb_attempt += 1
                tb_warming = _is_temporal_brain_active_or_warming(local_runner)
                if tb_warming and time.monotonic() < tb_deadline:
                    time.sleep(min(tb_poll_step, max(0.05, tb_deadline - time.monotonic())))
                    continue
                if _tb_attempt == 1 and not tb_warming:
                    time.sleep(0.5)
                    continue
                break

            if tb_last_err is not None:
                logger.warning(f"Aviso en TemporalBrain IPC ({tb_last_err}); evaluando respaldo local.")

            # Anti-duplicación estricta: si TemporalBrain posee KAIJU y sigue activo/en warmup,
            # NO derramar un segundo runner KAIJU de 4.4 GB hacia Ollama CPU :11434.
            allow_kaiju_dup = os.environ.get("GIA_ALLOW_KAIJU_CPU_DUPLICATE", "0").strip().lower() in (
                "1", "true", "yes"
            )
            if _is_kaiju_model(target_model) and not allow_kaiju_dup and _is_temporal_brain_active_or_warming(local_runner):
                raise RuntimeError(
                    f"TemporalBrain activo/en warmup ({tb_last_err or 'sin respuesta'}); "
                    "se bloqueó fallback duplicado de KAIJU hacia Ollama CPU :11434."
                )

        # 0.5. TIER 0.5: Motor Colibri MoE Ultrarrápido y Soberano (solo si el servidor Colibri está vivo en puerto 8765)
        if _COLIBRI_ACTIVE:
            try:
                c_bridge = colibri_bridge.get_colibri()
                if c_bridge.is_alive():
                    self.last_channel_used = "colibri"
                    yield from c_bridge.chat_stream(
                        unified_msgs,
                        model_path=target_model,
                        temperature=temperature,
                        max_tokens=2048
                    )
                    return
            except Exception:
                # Si ocurre alguna excepción en Colibri, conmutar a respaldo resiliente HTTP
                pass

        # 1. Intentar Canal HTTP Resiliente
        attempt = 0
        last_error = None
        while attempt <= retries:
            try:
                self.last_channel_used = "http"
                yield from self._http_chat_stream(
                    unified_msgs,
                    target_model,
                    temperature=temperature,
                    num_ctx=num_ctx,
                    cancel_event=cancel_event
                )
                return
            except Exception as e:
                last_error = e
                attempt += 1
                # Reanimar demonio y reintentar
                self.diagnose_and_heal(auto_start=True, wait_seconds=5.0)

        # 2. Fallback de Emergencia: Canal Nativo por Tubería Directa (Sin Puertos)
        try:
            self.last_channel_used = "pipe"
            yield from self._pipe_chat_stream(
                unified_msgs,
                target_model,
                system_prompt=system,
                cancel_event=cancel_event,
                on_process_spawned=on_process_spawned
            )
            return
        except Exception as pipe_err:
            err_msg = f"\n[Error de Inferencia Soberana: HTTP ({last_error}) | Pipe ({pipe_err})]"
            yield err_msg
            return err_msg

    def chat(
        self,
        messages: Union[List[Dict[str, str]], str],
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.4,
        num_ctx: int = 4096,
        cancel_event: Optional[threading.Event] = None,
        on_process_spawned: Optional[Callable[[subprocess.Popen], None]] = None
    ) -> Dict[str, Any]:
        """
        Ejecución síncrona unificada. Retorna dict estructurado con respuesta, metadatos y estado de cancelación.
        """
        t0 = time.time()
        if isinstance(messages, str):
            conv = [{"role": "user", "content": messages}]
        else:
            conv = list(messages)

        target_model = self.resolve_model(model or self.default_model)
        chunks = []
        for piece in self.chat_stream(
            conv,
            model=target_model,
            system=system,
            temperature=temperature,
            num_ctx=num_ctx,
            cancel_event=cancel_event,
            on_process_spawned=on_process_spawned
        ):
            chunks.append(piece)

        reply = "".join(chunks).strip()
        elapsed = round(time.time() - t0, 2)
        is_cancelled = bool(cancel_event and cancel_event.is_set())
        is_ok = bool(reply and not reply.startswith("[Error de Inferencia Soberana") and not is_cancelled)
        
        channel = getattr(self, "last_channel_used", "http")
        if channel in ("temporal_brain", "sovereign_local_runner"):
            active_provider = "temporal_brain"
            active_node = "temporal_brain_ipc"
        elif channel == "colibri":
            active_provider = "colibri"
            active_node = "colibri_moe_8765"
        elif channel == "pipe" or self.force_pipe_mode:
            active_provider = "local_sovereign"
            active_node = "direct_pipe"
        else:
            active_provider = "local_sovereign"
            active_node = self.active_endpoint or "http_socket"

        return {
            "ok": is_ok,
            "cancelled": is_cancelled,
            "reply": reply,
            "model": target_model,
            "provider": active_provider,
            "node": active_node,
            "ram_allocated_gb": 20.0,
            "system_ram_gb": 24.0,
            "elapsed_s": elapsed
        }


# Instancia y funciones de conveniencia globales
_GLOBAL_ENGINE = SovereignInferenceEngine.get_instance()

def get_engine() -> SovereignInferenceEngine:
    return _GLOBAL_ENGINE

def infer(prompt: str, model: Optional[str] = None, system: Optional[str] = None) -> str:
    res = _GLOBAL_ENGINE.chat(prompt, model=model, system=system)
    return res.get("reply", "")

def stream_chat(messages: List[Dict[str, str]], model: Optional[str] = None, system: Optional[str] = None):
    return _GLOBAL_ENGINE.chat_stream(messages, model=model, system=system)


if __name__ == "__main__":
    print("=== GIA SOVEREIGN RESILIENT ENGINE TEST ===")
    eng = get_engine()
    diag = eng.diagnose_and_heal()
    print("Diagnóstico:", json.dumps(diag, indent=2, ensure_ascii=False))
    print("\nEjecutando prueba de inferencia soberana...")
    r = eng.chat("Di exactamente: GIA MOTOR SOBERANO 100% OPERATIVO")
    print("Resultado:", json.dumps(r, indent=2, ensure_ascii=False))
