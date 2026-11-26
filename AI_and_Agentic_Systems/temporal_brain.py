"""
core/temporal_brain.py - Motor Soberano 'Temporal Brain'
=========================================================
GODWORKS SYSTEM · Suite Soberana GIA

Reemplazo modular y extensible de Ollama:
1. Inferencia Directa Serverless sobre Socket UNIX privado (/tmp/temporal_brain.sock).
2. Cero Dependencia de Servidores o Demonios HTTP en Segundo Plano.
3. Arquitectura Extensible con Hooks de Inferencia (Pre, Post, Stream Filters).
4. Registro Dinámico de Funciones y Herramientas Personalizadas (@tool).
5. Sistema de Adaptadores Modulares para Integración con Subsistemas Propios.
6. Configuración Declarativa en Caliente (temporal_brain_config.json).
"""

from __future__ import annotations

import argparse
import atexit
import inspect
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, Union

import httpx

# Configuración de logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TemporalBrain")

# DIRECTIVA DEL ARQUITECTO: la inferencia puede durar indefinidamente.
# GIA_TEMPORAL_TIMEOUT (segundos) impone un tope sólo si se define > 0.
def _temporal_infer_timeout() -> Optional[float]:
    raw = (os.environ.get("GIA_TEMPORAL_TIMEOUT") or "").strip()
    try:
        val = float(raw) if raw else 0.0
    except ValueError:
        val = 0.0
    return val if val > 0 else None

# Rutas estándar del sistema
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE_PATH = WORKSPACE_DIR / "temporal_brain_config.json"
DEFAULT_SOCKET_PATH = Path("/tmp/temporal_brain.sock")
TEMPORAL_BRAIN_LIB_DIR = Path(os.path.expanduser("~")) / ".local" / "lib" / "temporal_brain"
SOVEREIGN_MODELS_DIR = WORKSPACE_DIR / "data" / "models"
OLLAMA_LIB_DIR = Path(os.path.expanduser("~")) / ".local" / "lib" / "ollama"
OLLAMA_MODELS_DIR = Path(os.path.expanduser("~")) / ".ollama" / "models"


# ==============================================================================
# 1. GESTOR DE CONFIGURACIÓN DINÁMICA (HOT-RELOAD)
# ==============================================================================

class TemporalBrainConfig:
    """Carga y supervisa en caliente la configuración de Temporal Brain."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = Path(config_path or CONFIG_FILE_PATH)
        self._last_mtime: float = 0.0
        self._data: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                mtime = self.config_path.stat().st_mtime
                if mtime != self._last_mtime:
                    self._data = json.loads(self.config_path.read_text(encoding="utf-8"))
                    self._last_mtime = mtime
                    logger.debug(f"⚙️ [TemporalBrain] Configuración recargada desde {self.config_path}")
            except Exception as e:
                logger.error(f"Error cargando {self.config_path}: {e}")
        else:
            self._data = {
                "system_name": "Temporal Brain",
                "model": "TARDIS-NEURAL-SPACE-KAIJU",
                "socket_path": str(DEFAULT_SOCKET_PATH),
                "ctx_size": 16384,
                "gpu_layers": 18,
                "cache_type_k": "q8_0",
                "cache_type_v": "q8_0",
                "threads": 8,
                "threads_batch": 16,
                "temperature": 0.25,
                "max_tokens": 4096,
                "auto_offload_cuda": True,
                "hooks": {
                    "enable_pre_hooks": True,
                    "enable_post_hooks": True,
                    "enable_stream_filters": True,
                },
                "adapters": {},
                "custom_functions": {"enabled": True},
            }
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        self.check_update()
        return self._data.get(key, default)

    def check_update(self):
        if self.config_path.exists():
            try:
                if self.config_path.stat().st_mtime != self._last_mtime:
                    self.reload()
            except Exception:
                pass


# ==============================================================================
# 2. SISTEMA DE ADAPTADORES (EXTENSIBILIDAD MODULAR)
# ==============================================================================

class TemporalBrainAdapter(ABC):
    """
    Clase base para construir adaptadores que conecten Temporal Brain
    con cualquier subsistema local o externo de forma personalizada.
    """

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled

    def on_init(self, brain: "TemporalBrain"):
        """Llamado cuando el adaptador es registrado en Temporal Brain."""
        pass

    def pre_inference(
        self,
        messages: List[Dict[str, str]],
        options: Dict[str, Any]
    ) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
        """Permite interceptar o enriquecer el contexto antes de la inferencia."""
        return messages, options

    def post_inference(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Permite transformar o reaccionar ante el resultado generado."""
        return result

    def on_stream_token(self, token: str) -> Optional[str]:
        """Permite filtrar o procesar tokens en tiempo real durante streaming."""
        return token


# ==============================================================================
# 3. REGISTRO DE FUNCIONES Y HERRAMIENTAS PERSONALIZADAS
# ==============================================================================

class TemporalBrainFunctionRegistry:
    """
    Permite al usuario registrar funciones de Python arbitrarias que Temporal Brain
    puede gestionar, ejecutar dinámicamente o exponer a sus adaptadores.
    """

    def __init__(self):
        self._functions: Dict[str, Callable] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        func: Optional[Callable] = None,
    ) -> Callable:
        """Registra una función directamente o como decorador."""
        def decorator(f: Callable) -> Callable:
            fn_name = name or f.__name__
            fn_doc = description or f.__doc__ or "Sin descripción"
            sig = inspect.signature(f)
            params = {k: str(v.annotation) for k, v in sig.parameters.items()}

            self._functions[fn_name] = f
            self._metadata[fn_name] = {
                "name": fn_name,
                "description": fn_doc.strip(),
                "parameters": params,
            }
            logger.info(f"🧩 [TemporalBrain] Función personalizada registrada: '{fn_name}'")
            return f

        if func is not None:
            return decorator(func)
        return decorator

    def execute(self, name: str, *args, **kwargs) -> Any:
        """Ejecuta una función registrada por nombre."""
        if name not in self._functions:
            raise KeyError(f"Función no registrada en Temporal Brain: '{name}'")
        return self._functions[name](*args, **kwargs)

    def list_functions(self) -> Dict[str, Dict[str, Any]]:
        """Devuelve el catálogo de funciones registradas con sus firmas."""
        return dict(self._metadata)

    def has_function(self, name: str) -> bool:
        return name in self._functions


# ==============================================================================
# 4. MOTOR PRINCIPAL TEMPORAL BRAIN
# ==============================================================================

class TemporalBrain:
    """
    Núcleo de Inteligencia Artificial Soberana 'Temporal Brain'.
    Reemplaza totalmente el servidor de Ollama ejecutando inferencia directa C++
    sobre socket UNIX privado, integrando hooks, funciones personalizadas y adaptadores.
    """

    _instance: Optional["TemporalBrain"] = None
    _lock = threading.Lock()

    def __init__(self, config_path: Optional[Path] = None):
        self.config = TemporalBrainConfig(config_path)
        self.socket_path = Path(self.config.get("socket_path", str(DEFAULT_SOCKET_PATH)))
        self.model_name = self.config.get("model", "TARDIS-NEURAL-SPACE-KAIJU")
        self.ctx_size = self.config.get("ctx_size", 16384)
        self.gpu_layers = self.config.get("gpu_layers", 18)
        self.cache_type_k = self.config.get("cache_type_k", "q8_0")
        self.cache_type_v = self.config.get("cache_type_v", "q8_0")
        self.threads = self.config.get("threads", 8)

        self._process: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._model_info: Optional[Dict[str, Any]] = None
        self._adopted_server: bool = False

        # Registro de funciones personalizadas
        self.functions = TemporalBrainFunctionRegistry()
        self.tool = self.functions.register  # Decorador conveniente @brain.tool

        # Hooks de modificación del usuario
        self._pre_hooks: List[Callable[[List[Dict[str, str]], Dict[str, Any]], Tuple[List[Dict[str, str]], Dict[str, Any]]]] = []
        self._post_hooks: List[Callable[[Dict[str, Any]], Dict[str, Any]]] = []
        self._stream_filters: List[Callable[[str], Optional[str]]] = []

        # Adaptadores modulares
        self._adapters: Dict[str, TemporalBrainAdapter] = {}

        # Hook de aumento cognitivo transversal por defecto (RAG + Graph + RAPTOR)
        def _default_transversal_rag_pre_hook(
            messages: List[Dict[str, str]], options: Dict[str, Any]
        ) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
            if options.get("enable_rag", False) or self.config.get("rag", {}).get("auto_augment", False):
                try:
                    from core.rag_vault import get_rag_vault
                    vault = get_rag_vault()
                    messages = vault.augment_messages(
                        messages,
                        k=options.get("rag_k", 4),
                        allow_web=options.get("rag_allow_web", False),
                        max_chars=options.get("rag_max_chars", 2800),
                    )
                except Exception as e:
                    logger.debug(f"Aviso en pre-hook de aumento RAG transversal: {e}")
            return messages, options

        self._pre_hooks.append(_default_transversal_rag_pre_hook)

        # Registrar apagado limpio
        atexit.register(self.stop)

    @classmethod
    def get_instance(cls, config_path: Optional[Path] = None) -> "TemporalBrain":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config_path)
            return cls._instance

    # --------------------------------------------------------------------------
    # GESTIÓN DE HOOKS Y ADAPTADORES PERSONALIZADOS
    # --------------------------------------------------------------------------

    def register_pre_hook(
        self,
        hook: Callable[[List[Dict[str, str]], Dict[str, Any]], Tuple[List[Dict[str, str]], Dict[str, Any]]]
    ):
        """Registra un hook para modificar mensajes y opciones antes de la inferencia."""
        self._pre_hooks.append(hook)

    def register_post_hook(self, hook: Callable[[Dict[str, Any]], Dict[str, Any]]):
        """Registra un hook para inspeccionar o transformar la salida de la inferencia."""
        self._post_hooks.append(hook)

    def register_stream_filter(self, filter_fn: Callable[[str], Optional[str]]):
        """Registra un filtro para transformar o suprimir tokens en tiempo real."""
        self._stream_filters.append(filter_fn)

    def register_adapter(self, adapter: TemporalBrainAdapter):
        """Registra un adaptador para conectar Temporal Brain a un subsistema propio."""
        self._adapters[adapter.name] = adapter
        adapter.on_init(self)
        logger.info(f"🔌 [TemporalBrain] Adaptador '{adapter.name}' conectado exitosamente.")

    def get_adapter(self, name: str) -> Optional[TemporalBrainAdapter]:
        return self._adapters.get(name)

    # --------------------------------------------------------------------------
    # GESTIÓN DE MODELOS Y ENTORNO HARDWARE CUDA
    # --------------------------------------------------------------------------

    def _resolve_model(self) -> Dict[str, Any]:
        """Resuelve el archivo GGUF desde el almacén soberano de modelos o ruta directa."""
        norm_name = (self.model_name or "").strip().lower()
        # Aliases soberanos que comparten los pesos GGUF residentes de KAIJU
        if norm_name in (
            "mundo-sin-censura",
            "mundo-sin-censura:latest",
            "un-mundo-sin-censura",
            "un_mundo_sin_censura",
            "mundo_sin_censura",
        ):
            kaiju_gguf = SOVEREIGN_MODELS_DIR / "TARDIS-NEURAL-SPACE-KAIJU.gguf"
            if kaiju_gguf.exists() and kaiju_gguf.is_file():
                info = {
                    "name": "mundo-sin-censura",
                    "model_name": "mundo-sin-censura",
                    "tag": "sovereign",
                    "manifest_path": "",
                    "gguf_path": str(kaiju_gguf),
                    "template": "",
                    "system_prompt": "",
                    "params": {"num_ctx": self.ctx_size},
                    "size_bytes": kaiju_gguf.stat().st_size,
                    "size_gb": round(kaiju_gguf.stat().st_size / (1024**3), 2),
                }
                self._model_info = info
                return info

        # 1. Buscar primero en data/models/ de Temporal Brain
        candidate_model_files = [
            SOVEREIGN_MODELS_DIR / f"{self.model_name}.gguf",
            SOVEREIGN_MODELS_DIR / f"{self.model_name}",
            SOVEREIGN_MODELS_DIR / "TARDIS-NEURAL-SPACE-KAIJU.gguf"
        ]
        for cmf in candidate_model_files:
            if cmf.exists() and cmf.is_file():
                info = {
                    "name": cmf.stem,
                    "model_name": cmf.stem,
                    "tag": "sovereign",
                    "manifest_path": "",
                    "gguf_path": str(cmf),
                    "template": "",
                    "system_prompt": "",
                    "params": {"num_ctx": self.ctx_size},
                    "size_bytes": cmf.stat().st_size,
                    "size_gb": round(cmf.stat().st_size / (1024**3), 2),
                }
                self._model_info = info
                return info

        from core.sovereign_local_runner import OllamaModelInspector
        info = OllamaModelInspector.inspect_model(self.model_name)
        if not info:
            p = Path(self.model_name)
            if p.is_file() and p.suffix.lower() == ".gguf":
                info = {
                    "name": p.stem,
                    "model_name": p.stem,
                    "tag": "local",
                    "manifest_path": "",
                    "gguf_path": str(p),
                    "template": "",
                    "system_prompt": "",
                    "params": {"num_ctx": self.ctx_size},
                    "size_bytes": p.stat().st_size,
                    "size_gb": round(p.stat().st_size / (1024**3), 2),
                }
            else:
                available = OllamaModelInspector.list_models()
                if available:
                    info = available[0]
                    logger.info(f"Fallback a modelo disponible: {info['name']}")

        if not info:
            raise FileNotFoundError(f"No se pudo resolver el modelo GGUF para: {self.model_name}")

        self._model_info = info
        return info

    def _get_cuda_environment(self) -> Tuple[Dict[str, str], Optional[str]]:
        """Configura el entorno de ejecución CUDA para la GPU NVIDIA RTX 3050."""
        env = os.environ.copy()
        lib_dir = TEMPORAL_BRAIN_LIB_DIR if TEMPORAL_BRAIN_LIB_DIR.exists() else OLLAMA_LIB_DIR
        cuda_dir = lib_dir / "cuda_v13"
        if not cuda_dir.exists():
            cuda_dir = lib_dir / "cuda_v12"
        if not cuda_dir.exists():
            cuda_dir = OLLAMA_LIB_DIR / "cuda_v13"

        ggml_cuda = cuda_dir / "libggml-cuda.so"
        if ggml_cuda.exists():
            env["GGML_BACKEND_PATH"] = str(ggml_cuda)
            current_ld = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{lib_dir}:{cuda_dir}:{current_ld}".strip(":")
            env["CUDA_VISIBLE_DEVICES"] = "0"
            return env, str(ggml_cuda)

        env["LD_LIBRARY_PATH"] = f"{lib_dir}:{env.get('LD_LIBRARY_PATH', '')}".strip(":")
        return env, None

    # --------------------------------------------------------------------------
    # CICLO DE VIDA DEL SERVICIO SERVERLESS (SOCKET UNIX)
    # --------------------------------------------------------------------------

    def _is_daemon_process_alive(self) -> bool:
        """Verifica en /proc si existe un proceso llama-server escuchando en self.socket_path."""
        target_sock = str(self.socket_path)
        try:
            for pid_dir in Path("/proc").iterdir():
                if not pid_dir.name.isdigit():
                    continue
                try:
                    cmdline = (pid_dir / "cmdline").read_bytes().decode("utf-8", errors="ignore")
                    if "llama-server" in cmdline and target_sock in cmdline:
                        status_file = pid_dir / "status"
                        if status_file.exists() and "State:\tZ" in status_file.read_text(encoding="utf-8", errors="ignore"):
                            continue
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def is_running(self) -> bool:
        if not self.socket_path.exists():
            return False
        if self._process and self._process.poll() is None:
            return True
        if self._is_daemon_process_alive():
            self._adopted_server = True
            return True
        return False

    def _server_n_ctx(self) -> int:
        """Contexto REAL del servidor (cacheado 60 s). La config de la app puede diferir."""
        now = time.time()
        cached = getattr(self, "_nctx_cache", None)
        if cached and now - cached[1] < 60.0:
            return cached[0]
        n = int(getattr(self, "ctx_size", 0) or 8192)
        try:
            transport = httpx.HTTPTransport(uds=str(self.socket_path))
            with httpx.Client(transport=transport, base_url="http://localhost", timeout=2.0) as client:
                n = int(client.get("/props").json().get("default_generation_settings", {}).get("n_ctx") or n)
        except Exception:
            pass
        self._nctx_cache = (n, now)
        return n

    @staticmethod
    def _msg_tokens(msg: Dict[str, Any]) -> int:
        """Estimacion conservadora para espanol/Markdown/JSON (~2.6 chars/token + overhead plantilla)."""
        c = msg.get("content")
        if isinstance(c, list):
            c = " ".join(part.get("text", "") for part in c if isinstance(part, dict))
        return int(len(str(c or "")) / 2.6) + 10

    @staticmethod
    def _trim_text_to_tokens(text: str, max_tokens: int, keep_tail: bool = False) -> str:
        """Recorta un texto garantizando estrictamente que su longitud disminuya para caber en max_tokens."""
        target_chars = max(64, int(max(16, max_tokens - 12) * 2.6))
        if len(text) <= target_chars:
            return text
        marker = "\n[...recortado por limite de contexto...]\n"
        if target_chars <= len(marker) + 32:
            return text[-target_chars:] if keep_tail else text[:target_chars]
        usable = target_chars - len(marker)
        if keep_tail:
            return marker.lstrip() + text[-usable:]
        head = int(usable * 0.65)
        tail = usable - head
        return text[:head] + marker + text[-tail:]

    def _fit_to_context(self, msgs: List[Dict[str, Any]], max_new: int) -> Tuple[List[Dict[str, Any]], int]:
        """
        Recorta el historial (y, si excede el presupuesto, el prompt de sistema) para que
        prompt + respuesta quepan siempre en el n_ctx real de llama-server sin HTTP 400.
        Conserva siempre la identidad central de sistema y el ultimo turno del usuario.
        """
        n_ctx = self._server_n_ctx()
        max_new = max(64, min(int(max_new), n_ctx // 2))
        budget = max(512, n_ctx - max_new - 256)          # margen seguro para la plantilla de chat
        total = sum(self._msg_tokens(m) for m in msgs)
        if total <= budget:
            return msgs, max_new
        original_total = total

        system = [dict(m) for m in msgs if m.get("role") == "system"]
        rest = [dict(m) for m in msgs if m.get("role") != "system"]
        dropped = 0
        while len(rest) > 1 and sum(self._msg_tokens(m) for m in system + rest) > budget:
            rest.pop(0)
            dropped += 1

        # Si los mensajes de sistema por si solos desbordan el presupuesto, recortarlos
        # primero preservando el turno actual del usuario intacto.
        last_toks = self._msg_tokens(rest[-1]) if rest else 0
        user_reserve = min(last_toks, max(256, budget // 3)) if rest else 0
        sys_budget = max(256, budget - user_reserve)
        sys_total = sum(self._msg_tokens(m) for m in system)
        if sys_total > sys_budget and system:
            # Reducir mensajes de sistema empezando por los mas grandes hasta caber en sys_budget
            indexed = sorted(range(len(system)), key=lambda i: self._msg_tokens(system[i]), reverse=True)
            for idx in indexed:
                if sys_total <= sys_budget:
                    break
                cur_tok = self._msg_tokens(system[idx])
                excess = sys_total - sys_budget
                target_tok = max(64, cur_tok - excess)
                content = system[idx].get("content")
                if isinstance(content, str) and target_tok < cur_tok:
                    system[idx]["content"] = self._trim_text_to_tokens(content, target_tok, keep_tail=False)
                    sys_total = sum(self._msg_tokens(m) for m in system)

        out = system + rest
        total = sum(self._msg_tokens(m) for m in out)
        if total > budget and rest and isinstance(rest[-1].get("content"), str):
            # Solo recortar el ultimo turno si por si mismo sigue desbordando el presupuesto
            other_toks = sum(self._msg_tokens(m) for m in system + rest[:-1])
            allowed_last = max(64, budget - other_toks)
            last = dict(rest[-1])
            if self._msg_tokens(last) > allowed_last:
                last["content"] = self._trim_text_to_tokens(last["content"], allowed_last, keep_tail=True)
                out = system + rest[:-1] + [last]

        final_total = sum(self._msg_tokens(m) for m in out)
        logger.warning(
            f"✂️ [TemporalBrain] Historial ajustado al contexto ({n_ctx} tok): "
            f"{dropped} mensajes antiguos descartados, ~{original_total} -> ~{final_total} tok"
        )
        return out, max_new

    def _get_uds_client(self, timeout: Optional[float] = None) -> httpx.Client:
        """Devuelve un cliente HTTP persistente sobre el socket UNIX privado (keep-alive)."""
        client = getattr(self, "_uds_client", None)
        if client is None or client.is_closed:
            transport = httpx.HTTPTransport(uds=str(self.socket_path))
            client = httpx.Client(
                transport=transport,
                base_url="http://localhost",
                timeout=timeout if timeout is not None else _temporal_infer_timeout(),
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=60.0),
            )
            self._uds_client = client
        return client

    def _reset_uds_client(self) -> None:
        client = getattr(self, "_uds_client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
            self._uds_client = None

    def all_slots_busy(self, timeout: float = 0.8) -> bool:
        """True si todos los slots de inferencia local están saturados procesando otras tareas."""
        if not self.socket_path.exists():
            return False
        try:
            r = self._get_uds_client().get("/slots", timeout=timeout)
            if r.status_code == 200:
                slots = r.json()
                if isinstance(slots, list) and slots:
                    return all(bool(s.get("is_processing")) for s in slots)
        except Exception:
            pass
        return False

    def _probe_socket(self, timeout: float = 5.0) -> bool:
        """True si hay un llama-server vivo respondiendo en el socket (con caché TTL 2s)."""
        if not self.socket_path.exists():
            return False
        now = time.monotonic()
        last_ts = float(getattr(self, "_probe_ok_ts", 0.0))
        if (now - last_ts) < 2.0:
            return True
        try:
            ok = self._get_uds_client().get("/health", timeout=timeout).status_code == 200
            if ok:
                self._probe_ok_ts = now
            return ok
        except Exception:
            self._reset_uds_client()
            # Si el servidor está ocupado procesando prefill pesado, verificar en /proc antes de declararlo muerto
            return self._is_daemon_process_alive()

    def is_serverless_ready(self, model_name: Optional[str] = None) -> bool:
        """Verifica disponibilidad del binario C++ y del modelo GGUF sin iniciar el proceso."""
        llama_server_bin = TEMPORAL_BRAIN_LIB_DIR / "llama-server"
        if not llama_server_bin.exists():
            llama_server_bin = OLLAMA_LIB_DIR / "llama-server"
        if not llama_server_bin.exists():
            return False

        # Verificar modelo soberano
        candidate_model_files = [
            SOVEREIGN_MODELS_DIR / f"{self.model_name}.gguf",
            SOVEREIGN_MODELS_DIR / "TARDIS-NEURAL-SPACE-KAIJU.gguf"
        ]
        for cmf in candidate_model_files:
            if cmf.exists():
                return True

        target = model_name or self.model_name
        try:
            from core.sovereign_local_runner import OllamaModelInspector
            info = OllamaModelInspector.inspect_model(target)
            if info and Path(info["gguf_path"]).exists():
                return True
            p = Path(target)
            if p.is_file() and p.suffix.lower() == ".gguf":
                return True
            models = OllamaModelInspector.list_models()
            return len(models) > 0
        except Exception:
            return False

    def start(self, wait_ready: float = 30.0) -> bool:
        """Inicia el ejecutor nativo C++ vinculado exclusivamente al socket UNIX privado."""
        with self._proc_lock:
            if self.is_running():
                return True

            # Varios procesos (supervisor.py, omni_temporal_control, CLIs) usan este
            # motor. Si otro ya levanto el servidor, se adopta: borrar su socket lo
            # dejaria huerfano y un segundo llama-server no cabe en la VRAM.
            if self._probe_socket(timeout=5.0):
                self._adopted_server = True
                logger.info(f"🔗 [TemporalBrain] Servidor existente adoptado en {self.socket_path}")
                return True

            import fcntl
            lock_fh = open(str(self.socket_path) + ".lock", "w")
            try:
                fcntl.flock(lock_fh, fcntl.LOCK_EX)
                # Revalidar tras obtener el lock: otro proceso pudo arrancarlo mientras esperabamos
                if self._probe_socket(timeout=5.0):
                    self._adopted_server = True
                    logger.info(f"🔗 [TemporalBrain] Servidor levantado por otro proceso, adoptado")
                    return True

                # Intentar primero activar el servicio systemd dedicado si está instalado
                if self.socket_path == DEFAULT_SOCKET_PATH:
                    try:
                        res = subprocess.run(
                            ["systemctl", "--user", "start", "tardis-temporal-brain.service"],
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5.0,
                        )
                        if res.returncode == 0:
                            t_wait = time.time()
                            while time.time() - t_wait < wait_ready:
                                if self._probe_socket(timeout=2.0):
                                    self._adopted_server = True
                                    logger.info(f"✅ [TemporalBrain] Servicio systemd tardis-temporal-brain.service activo en {self.socket_path}")
                                    return True
                                time.sleep(0.2)
                    except Exception:
                        pass

                return self._start_locked(wait_ready)
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)
                lock_fh.close()

    def _start_locked(self, wait_ready: float, gpu_layers_override: Optional[int] = None) -> bool:
        """Arranque real con protección anti-colisión VRAM y fallback automático CUDA -> CPU."""
        # Si ya hay un proceso vivo escuchando en este socket, adoptarlo en vez de duplicar
        if self._is_daemon_process_alive() and self.socket_path.exists():
            self._adopted_server = True
            return True

        info = self._resolve_model()
        gguf_path = info["gguf_path"]
        llama_server_bin = TEMPORAL_BRAIN_LIB_DIR / "llama-server"
        if not llama_server_bin.exists():
            llama_server_bin = OLLAMA_LIB_DIR / "llama-server"
        if not llama_server_bin.exists():
            raise FileNotFoundError(f"Binario llama-server no encontrado en: {llama_server_bin}")

        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except Exception:
                pass

        env, cuda_backend = self._get_cuda_environment()
        # Acotar arenas glibc para evitar fragmentación multi-GB / swap-bloat en llama-server (COEV-20261124-5B1F5C)
        env.setdefault("MALLOC_ARENA_MAX", "2")
        env.setdefault("MALLOC_TRIM_THRESHOLD_", "131072")
        env.setdefault("MALLOC_MMAP_THRESHOLD_", "131072")

        ctx = info.get("params", {}).get("num_ctx", self.ctx_size)
        ngl = self.gpu_layers if gpu_layers_override is None else gpu_layers_override

        env_load_mode = os.environ.get("TEMPORAL_LOAD_MODE", "").strip()
        if env_load_mode:
            load_mode = env_load_mode
        else:
            load_mode = self.config.get("load_mode", "mmap+mlock" if self.config.get("mlock", False) else "auto")

        try:
            eff_cpus = len(os.sched_getaffinity(0))
        except Exception:
            eff_cpus = os.cpu_count() or 8
        raw_tb = int(self.config.get("threads_batch", min(8, max(2, eff_cpus))))
        threads_batch = max(int(self.threads), min(raw_tb, max(2, eff_cpus)))

        raw_cache_idle = os.environ.get("TEMPORAL_CACHE_IDLE_SLOTS", "").strip().lower()
        if raw_cache_idle in ("1", "true", "yes"):
            cache_idle_slots = True
        elif raw_cache_idle in ("0", "false", "no"):
            cache_idle_slots = False
        else:
            cache_idle_slots = bool(self.config.get("cache_idle_slots", False))

        cmd = [
            str(llama_server_bin),
            "--model", str(gguf_path),
            "--host", str(self.socket_path),
            "--alias", self.model_name,
            "--ctx-size", str(ctx),
            "--cache-type-k", str(self.cache_type_k),
            "--cache-type-v", str(self.cache_type_v),
            "--n-gpu-layers", str(ngl),
            "--threads", str(self.threads),
            "--threads-batch", str(threads_batch),
            "--poll", str(self.config.get("poll", 0)),
            "--poll-batch", str(self.config.get("poll_batch", 0)),
            "--load-mode", str(load_mode),
            "--batch-size", "2048",
            "--ubatch-size", "512",
            "--flash-attn", "on",
            "--parallel", str(self.config.get("parallel", 2)),
            "--cont-batching",
            "--prio", "0",
            "--prio-batch", "0",
        ]
        if cache_idle_slots:
            cmd.append("--cache-idle-slots")
        cmd.extend([
            "--temp", str(self.config.get("temperature", 0.25)),
            "--top-k", str(self.config.get("top_k", 40)),
            "--top-p", str(self.config.get("top_p", 0.92)),
            "--min-p", str(self.config.get("min_p", 0.05)),
            "--repeat-penalty", str(self.config.get("repeat_penalty", 1.08)),
            "--dry-multiplier", str(self.config.get("dry_multiplier", 0.8)),
            "--no-webui",
            "--offline",
            "--log-disable",
        ])

        logger.info(f"🧠 [TemporalBrain] Iniciando motor en socket UNIX privado: {self.socket_path} (ngl={ngl}, threads={self.threads})")
        if cuda_backend and ngl > 0:
            logger.info(f"⚡ [TemporalBrain] Aceleración CUDA activada ({cuda_backend})")

        log_dir = Path(__file__).resolve().parent.parent / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._stderr_fh = open(log_dir / "temporal_brain_server.log", "ab")
        self._process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_fh,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

        t0 = time.time()
        while time.time() - t0 < wait_ready:
            if self.socket_path.exists():
                try:
                    transport = httpx.HTTPTransport(uds=str(self.socket_path))
                    with httpx.Client(transport=transport, base_url="http://localhost", timeout=2.0) as client:
                        r = client.get("/health")
                        if r.status_code == 200:
                            logger.info(f"✅ [TemporalBrain] Motor listo y modelo cargado ({time.time() - t0:.2f}s) en {self.socket_path}")
                            return True
                except Exception:
                    pass
            if self._process.poll() is not None:
                rc = self._process.returncode
                logger.error(f"❌ [TemporalBrain] Fallo al iniciar con ngl={ngl} (código {rc})")
                # Fallback gradual de capas GPU ante saturación de VRAM (evita bloqueo por SIGABRT/CUDA OOM)
                if ngl > 10:
                    logger.warning("⚠️ [TemporalBrain] Reintentando con --n-gpu-layers 10 por presión de VRAM...")
                    return self._start_locked(wait_ready, gpu_layers_override=10)
                elif ngl > 0:
                    logger.warning("⚠️ [TemporalBrain] Reintentando en modo CPU puro (--n-gpu-layers 0)...")
                    return self._start_locked(wait_ready, gpu_layers_override=0)
                return False
            time.sleep(0.15)

        logger.warning(f"⚠️ [TemporalBrain] Tiempo de espera agotado en {self.socket_path}")
        return False

    def stop(self, force: bool = False):
        """
        Detiene el ejecutor sólo si force=True.
        Por diseño soberano 24/7, los scripts efímeros que salen vía atexit NO deben
        matar el demonio compartido en /tmp/temporal_brain.sock.
        """
        if not force:
            return
        with self._proc_lock:
            if self._process:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=2.0)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None

                if self.socket_path.exists():
                    try:
                        self.socket_path.unlink()
                    except Exception:
                        pass
                logger.info("🛑 [TemporalBrain] Motor detenido y socket liberado.")

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: Optional[float] = None,
        *,
        use_cache: Optional[bool] = None,
        cache_namespace: str = "background",
        cache_ttl_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Método de generación directa compatible con EasyTouchEngine y agentes autónomos."""
        msgs: List[Dict[str, str]] = []
        sys_p = system_prompt or self.config.get("system_prompt")
        if sys_p:
            msgs.append({"role": "system", "content": str(sys_p)})
        msgs.append({"role": "user", "content": str(prompt)})
        res = self.chat(
            msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            use_cache=use_cache,
            cache_namespace=cache_namespace,
            cache_ttl_s=cache_ttl_s,
        )
        if "text" not in res:
            res["text"] = res.get("reply", "")
        if "response" not in res:
            res["response"] = res.get("reply", "")
        return res

    # --------------------------------------------------------------------------
    # PIPELINE DE INFERENCIA SOBERANA (CHAT & STREAM)
    # --------------------------------------------------------------------------

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        num_ctx: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None,
        *,
        bypass_pre_hooks: bool = False,
        bypass_post_hooks: bool = False,
        timeout: Optional[float] = None,
        model_alias: Optional[str] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        min_p: Optional[float] = None,
        repeat_penalty: Optional[float] = None,
        stop: Optional[List[str]] = None,
        use_cache: Optional[bool] = None,
        cache_namespace: str = "default",
        cache_ttl_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Ejecuta inferencia síncrona pasando por caché semántica, adaptadores y hooks personalizados."""
        t0 = time.time()
        options: Dict[str, Any] = {
            "temperature": float(temperature if temperature is not None else self.config.get("temperature", 0.3)),
            "max_tokens": int(max_tokens if max_tokens is not None else self.config.get("max_tokens", 1024)),
            "num_ctx": num_ctx,
        }
        effective_model = model_alias or self.model_name

        # 1. Pipeline Pre-Inferencia: System Prompt Soberano + Caché Semántica L1/L2 (EmbedBrain)
        current_msgs = [dict(m) for m in messages]
        if not any(m.get("role") == "system" for m in current_msgs):
            default_sys = self.config.get("system_prompt")
            if default_sys:
                current_msgs.insert(0, {"role": "system", "content": str(default_sys)})

        cache_enabled = (use_cache is not False) and (cancel_event is None)
        cache_key_msgs = [dict(m) for m in current_msgs]
        if cache_enabled:
            try:
                from core.tardis_semantic_cache import get_semantic_cache

                cache_hit = get_semantic_cache().lookup(
                    cache_key_msgs,
                    model=effective_model,
                    namespace=cache_namespace,
                    temperature=options["temperature"],
                )
                if cache_hit.get("hit"):
                    cached_result: Dict[str, Any] = {
                        "ok": True,
                        "reply": str(cache_hit.get("reply") or ""),
                        "model": effective_model,
                        "usage": {
                            "prompt_tokens": int(cache_hit.get("prompt_tokens_saved", 0)),
                            "completion_tokens": int(cache_hit.get("completion_tokens_saved", 0)),
                            "total_tokens": int(cache_hit.get("tokens_saved", 0)),
                            "cached": True,
                        },
                        "elapsed": round(time.time() - t0, 4),
                        "tokens_per_sec": 0.0,
                        "engine": "semantic_cache",
                        "cache_hit": True,
                        "cache_match_type": str(cache_hit.get("match_type") or "semantic"),
                        "cache_similarity": float(cache_hit.get("similarity", 1.0)),
                        "tokens_saved": int(cache_hit.get("tokens_saved", 0)),
                        "cpu_ms_saved": float(cache_hit.get("cpu_ms_saved", 0.0)),
                        "socket": str(self.socket_path),
                    }
                    if not bypass_post_hooks:
                        if self.config.get("hooks", {}).get("enable_post_hooks", True):
                            for hook in self._post_hooks:
                                try:
                                    cached_result = hook(cached_result)
                                except Exception as e:
                                    logger.error(f"Error en post_hook: {e}")
                        for adapter in self._adapters.values():
                            if adapter.enabled:
                                try:
                                    cached_result = adapter.post_inference(cached_result)
                                except Exception as e:
                                    logger.error(f"Error en post_inference del adaptador '{adapter.name}': {e}")
                    return cached_result
            except Exception as exc_cache:
                logger.debug(f"[TemporalBrain] Aviso en lookup de SemanticCache: {exc_cache}")

        if not bypass_pre_hooks:
            for adapter in self._adapters.values():
                if adapter.enabled:
                    try:
                        current_msgs, options = adapter.pre_inference(current_msgs, options)
                    except Exception as e:
                        logger.error(f"Error en pre_inference del adaptador '{adapter.name}': {e}")

            if self.config.get("hooks", {}).get("enable_pre_hooks", True):
                for hook in self._pre_hooks:
                    try:
                        current_msgs, options = hook(current_msgs, options)
                    except Exception as e:
                        logger.error(f"Error en pre_hook: {e}")

        # 2. Asegurar servicio activo
        if not self.is_running():
            ok = self.start()
            if not ok:
                return {
                    "ok": False,
                    "reply": "[Error: Temporal Brain no pudo iniciar]",
                    "model": model_alias or self.model_name,
                    "elapsed": 0,
                }

        current_msgs, options["max_tokens"] = self._fit_to_context(current_msgs, options["max_tokens"])

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": current_msgs,
            "temperature": options["temperature"],
            "max_tokens": options["max_tokens"],
            "stream": False,
        }
        if top_p is not None:
            payload["top_p"] = float(top_p)
        if top_k is not None:
            payload["top_k"] = int(top_k)
        if min_p is not None:
            payload["min_p"] = float(min_p)
        if repeat_penalty is not None:
            payload["repeat_penalty"] = float(repeat_penalty)
        if stop:
            payload["stop"] = list(stop)

        # 3. Llamada al socket UNIX privado reutilizando conexión keep-alive (con auto-recuperación y espera de warmup 503)
        raw_result: Dict[str, Any] = {}
        infer_timeout = float(timeout) if (timeout is not None and float(timeout) > 0) else _temporal_infer_timeout()
        effective_model = model_alias or self.model_name
        try:
            warmup_budget_s = max(0.0, float(os.environ.get("TEMPORAL_BRAIN_WARMUP_WAIT_SEC", "25.0")))
        except (TypeError, ValueError):
            warmup_budget_s = 25.0
        try:
            warmup_poll_s = max(0.05, float(os.environ.get("TEMPORAL_BRAIN_WARMUP_POLL_SEC", "1.5")))
        except (TypeError, ValueError):
            warmup_poll_s = 1.5
        warmup_deadline = time.monotonic() + warmup_budget_s
        conn_retried = False
        while True:
            try:
                client = self._get_uds_client(timeout=infer_timeout)
                resp = client.post("/v1/chat/completions", json=payload, timeout=infer_timeout)
                elapsed = round(time.time() - t0, 3)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    reply = choices[0].get("message", {}).get("content", "") if choices else ""
                    usage = data.get("usage", {})
                    raw_result = {
                        "ok": True,
                        "reply": reply.strip(),
                        "model": effective_model,
                        "usage": usage,
                        "elapsed": elapsed,
                        "tokens_per_sec": round(usage.get("completion_tokens", 0) / max(elapsed, 0.001), 1),
                        "engine": "temporal_brain",
                        "socket": str(self.socket_path),
                    }
                    break
                elif resp.status_code == 503 and time.monotonic() < warmup_deadline:
                    # Servidor aún cargando modelo GGUF en warmup de arranque
                    time.sleep(min(warmup_poll_s, max(0.05, warmup_deadline - time.monotonic())))
                    continue
                else:
                    raw_result = {
                        "ok": False,
                        "reply": f"Error del motor Temporal Brain (HTTP {resp.status_code}): {resp.text}",
                        "model": effective_model,
                        "elapsed": elapsed,
                    }
                    break
            except Exception as e:
                self._reset_uds_client()
                if not conn_retried:
                    conn_retried = True
                    self._adopted_server = False
                    self._process = None
                    if not self._probe_socket(timeout=2.0):
                        self.start(wait_ready=20.0)
                    else:
                        time.sleep(1.0)
                    continue
                raw_result = {
                    "ok": False,
                    "reply": f"Error en socket IPC: {e}",
                    "model": effective_model,
                    "elapsed": round(time.time() - t0, 3),
                }
                break

        # 4. Pipeline Post-Inferencia: Hooks y Adaptadores
        if not bypass_post_hooks:
            if self.config.get("hooks", {}).get("enable_post_hooks", True):
                for hook in self._post_hooks:
                    try:
                        raw_result = hook(raw_result)
                    except Exception as e:
                        logger.error(f"Error en post_hook: {e}")

            for adapter in self._adapters.values():
                if adapter.enabled:
                    try:
                        raw_result = adapter.post_inference(raw_result)
                    except Exception as e:
                        logger.error(f"Error en post_inference del adaptador '{adapter.name}': {e}")

        # 5. Almacenar respuesta válida en la Caché Semántica L1/L2 (EmbedBrain + SQLite WAL)
        if cache_enabled and raw_result.get("ok") and raw_result.get("reply"):
            try:
                from core.tardis_semantic_cache import get_semantic_cache

                get_semantic_cache().store(
                    cache_key_msgs,
                    str(raw_result.get("reply") or ""),
                    model=effective_model,
                    namespace=cache_namespace,
                    temperature=options["temperature"],
                    ttl_s=cache_ttl_s,
                    usage=raw_result.get("usage") if isinstance(raw_result.get("usage"), dict) else None,
                    elapsed_ms=float(raw_result.get("elapsed", 0.0)) * 1000.0,
                )
            except Exception as exc_store:
                logger.debug(f"[TemporalBrain] Aviso al almacenar en SemanticCache: {exc_store}")

        return raw_result

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        num_ctx: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None,
        *,
        bypass_pre_hooks: bool = False,
        bypass_stream_filters: bool = False,
        timeout: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        min_p: Optional[float] = None,
        repeat_penalty: Optional[float] = None,
        stop: Optional[List[str]] = None,
    ) -> Generator[str, None, str]:
        """Generador streaming que aplica adaptadores y filtros de tokens en tiempo real."""
        options: Dict[str, Any] = {
            "temperature": float(temperature if temperature is not None else self.config.get("temperature", 0.3)),
            "max_tokens": int(max_tokens if max_tokens is not None else self.config.get("max_tokens", 1024)),
            "num_ctx": num_ctx,
        }

        # 1. Pipeline Pre-Inferencia + System Prompt Soberano por defecto
        current_msgs = [dict(m) for m in messages]
        if not any(m.get("role") == "system" for m in current_msgs):
            default_sys = self.config.get("system_prompt")
            if default_sys:
                current_msgs.insert(0, {"role": "system", "content": str(default_sys)})
        if not bypass_pre_hooks:
            for adapter in self._adapters.values():
                if adapter.enabled:
                    try:
                        current_msgs, options = adapter.pre_inference(current_msgs, options)
                    except Exception:
                        pass

            if self.config.get("hooks", {}).get("enable_pre_hooks", True):
                for hook in self._pre_hooks:
                    try:
                        current_msgs, options = hook(current_msgs, options)
                    except Exception:
                        pass

        if not self.is_running():
            self.start()

        current_msgs, options["max_tokens"] = self._fit_to_context(current_msgs, options["max_tokens"])

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": current_msgs,
            "temperature": options["temperature"],
            "max_tokens": options["max_tokens"],
            "stream": True,
        }
        if top_p is not None:
            payload["top_p"] = float(top_p)
        if top_k is not None:
            payload["top_k"] = int(top_k)
        if min_p is not None:
            payload["min_p"] = float(min_p)
        if repeat_penalty is not None:
            payload["repeat_penalty"] = float(repeat_penalty)
        if stop:
            payload["stop"] = list(stop)

        infer_timeout = float(timeout) if (timeout is not None and float(timeout) > 0) else _temporal_infer_timeout()
        try:
            warmup_budget_s = max(0.0, float(os.environ.get("TEMPORAL_BRAIN_WARMUP_WAIT_SEC", "25.0")))
        except (TypeError, ValueError):
            warmup_budget_s = 25.0
        try:
            warmup_poll_s = max(0.05, float(os.environ.get("TEMPORAL_BRAIN_WARMUP_POLL_SEC", "1.5")))
        except (TypeError, ValueError):
            warmup_poll_s = 1.5
        warmup_deadline = time.monotonic() + warmup_budget_s
        transport = httpx.HTTPTransport(uds=str(self.socket_path))
        full_reply = []

        with httpx.Client(transport=transport, base_url="http://localhost", timeout=infer_timeout) as client:
            while True:
                if cancel_event and cancel_event.is_set():
                    msg = "\n[⛔ Inferencia cancelada y proceso cortado por el usuario]"
                    full_reply.append(msg)
                    yield msg
                    return msg
                with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
                    status_code = getattr(resp, "status_code", 200)
                    if isinstance(status_code, int) and status_code == 503 and time.monotonic() < warmup_deadline:
                        time.sleep(min(warmup_poll_s, max(0.05, warmup_deadline - time.monotonic())))
                        continue
                    if isinstance(status_code, int) and status_code >= 400:
                        body = resp.read().decode("utf-8", errors="ignore")[:240]
                        raise RuntimeError(f"Error del motor Temporal Brain (HTTP {status_code}): {body}")
                    for line in resp.iter_lines():
                        if cancel_event and cancel_event.is_set():
                            msg = "\n[⛔ Inferencia cancelada y proceso cortado por el usuario]"
                            full_reply.append(msg)
                            yield msg
                            return msg

                        line_str = line.strip()
                        if not line_str or line_str == "data: [DONE]":
                            continue
                        if line_str.startswith("data: "):
                            try:
                                chunk = json.loads(line_str[6:])
                                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if delta:
                                    # Filtros de tokens
                                    token = delta
                                    if not bypass_stream_filters:
                                        for flt in self._stream_filters:
                                            token = flt(token)
                                            if token is None:
                                                break
                                        for adapter in self._adapters.values():
                                            if adapter.enabled and token is not None:
                                                token = adapter.on_stream_token(token)
                                                if token is None:
                                                    break

                                    if token:
                                        full_reply.append(token)
                                        yield token
                            except Exception:
                                continue
                    break

        return "".join(full_reply)


# ==============================================================================
# 5. ADAPTADORES INCORPORADOS DE EJEMPLO Y SISTEMA
# ==============================================================================

class HardwareControlAdapter(TemporalBrainAdapter):
    """Adaptador para detectar y registrar directivas de hardware del usuario."""

    def __init__(self):
        super().__init__(name="hardware_control")

    def post_inference(self, result: Dict[str, Any]) -> Dict[str, Any]:
        reply = result.get("reply", "")
        # Detección de directivas de hardware
        directives = []
        if re.search(r"(/vol|volumen\s+al?\s*\d+)", reply, re.IGNORECASE):
            directives.append("volume_directive")
        if re.search(r"(/kbd|teclado\s+en\s+nivel\s*\d+)", reply, re.IGNORECASE):
            directives.append("keyboard_directive")

        if directives:
            result["hardware_directives"] = directives
        return result


class SystemTelemetryAdapter(TemporalBrainAdapter):
    """Adaptador para enriquecer prompts con telemetría del nodo local."""

    def __init__(self, include_timestamp: bool = True):
        super().__init__(name="system_telemetry")
        self.include_timestamp = include_timestamp

    def pre_inference(
        self,
        messages: List[Dict[str, str]],
        options: Dict[str, Any]
    ) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
        # Inyecta metadatos contextuales si el último mensaje es del usuario
        if messages and messages[-1].get("role") == "user":
            user_msg = messages[-1]["content"]
            # No modificar si ya contiene telemetría
            if "[Nodo Local]" not in user_msg and self.include_timestamp:
                enriched = f"[Nodo Local: {time.strftime('%Y-%m-%d %H:%M:%S')}]\n{user_msg}"
                new_msgs = list(messages[:-1]) + [{"role": "user", "content": enriched}]
                return new_msgs, options
        return messages, options


# ==============================================================================
# 6. INSTANCIA Y ACCESO GLOBAL
# ==============================================================================

_GLOBAL_BRAIN: Optional[TemporalBrain] = None

def get_temporal_brain(config_path: Optional[Path] = None) -> TemporalBrain:
    """Obtiene el singleton global de Temporal Brain."""
    global _GLOBAL_BRAIN
    if _GLOBAL_BRAIN is None:
        _GLOBAL_BRAIN = TemporalBrain.get_instance(config_path)
        # Registrar adaptadores por defecto
        _GLOBAL_BRAIN.register_adapter(HardwareControlAdapter())
    return _GLOBAL_BRAIN


# ==============================================================================
# 7. CLI Y PUNTO DE ENTRADA
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Temporal Brain - Motor Soberano y Extensible")
    parser.add_argument("--chat", type=str, help="Ejecuta una inferencia síncrona")
    parser.add_argument("--stream", type=str, help="Ejecuta una inferencia en streaming")
    parser.add_argument("--list-functions", action="store_true", help="Lista las funciones personalizadas registradas")
    parser.add_argument("--status", action="store_true", help="Muestra el estado del motor Temporal Brain")
    args = parser.parse_args()

    brain = get_temporal_brain()

    if args.status:
        ready = brain.is_serverless_ready()
        running = brain.is_running()
        print(f"🧠 [Temporal Brain Status]")
        print(f"  • Modelo activo: {brain.model_name}")
        print(f"  • Socket UNIX: {brain.socket_path}")
        print(f"  • Listo para ejecución: {'SÍ' if ready else 'NO'}")
        print(f"  • Proceso en ejecución: {'SÍ' if running else 'NO'}")
        print(f"  • Adaptadores registrados: {list(brain._adapters.keys())}")
        return

    if args.list_functions:
        funcs = brain.functions.list_functions()
        print(f"🧩 Funciones registradas en Temporal Brain ({len(funcs)}):")
        for name, meta in funcs.items():
            print(f"  • {name}: {meta['description']} (Params: {meta['parameters']})")
        return

    if args.chat:
        print(f"🧠 Consultando a Temporal Brain: {args.chat}")
        res = brain.chat([{"role": "user", "content": args.chat}])
        print(f"\nRespuesta:\n{res.get('reply', '')}\n")
        print(f"[Metadatos: {res.get('elapsed')}s, {res.get('tokens_per_sec', 0)} tok/s]")
        return

    if args.stream:
        print(f"🧠 Streaming desde Temporal Brain: {args.stream}")
        for chunk in brain.chat_stream([{"role": "user", "content": args.stream}]):
            sys.stdout.write(chunk)
            sys.stdout.flush()
        print()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
