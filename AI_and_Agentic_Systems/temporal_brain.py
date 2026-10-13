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
                "ctx_size": 8192,
                "gpu_layers": 20,
                "cache_type_k": "q8_0",
                "cache_type_v": "q8_0",
                "threads": 16,
                "temperature": 0.3,
                "max_tokens": 2048,
                "auto_offload_cuda": true,
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
        self.ctx_size = self.config.get("ctx_size", 8192)
        self.gpu_layers = self.config.get("gpu_layers", 20)
        self.cache_type_k = self.config.get("cache_type_k", "q8_0")
        self.cache_type_v = self.config.get("cache_type_v", "q8_0")
        self.threads = self.config.get("threads", 16)

        self._process: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._model_info: Optional[Dict[str, Any]] = None

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

    def is_running(self) -> bool:
        if not self._process or self._process.poll() is not None:
            return False
        return self.socket_path.exists()

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
        """Estimacion conservadora: Llama 3 promedia ~3.5-4 caracteres por token en espanol."""
        c = msg.get("content")
        if isinstance(c, list):
            c = " ".join(part.get("text", "") for part in c if isinstance(part, dict))
        return len(str(c or "")) // 3 + 6

    def _fit_to_context(self, msgs: List[Dict[str, Any]], max_new: int) -> Tuple[List[Dict[str, Any]], int]:
        """
        Recorta el historial para que prompt + respuesta quepan en el contexto real.
        Sin esto, pasar de n_ctx devolvia HTTP 400 y la respuesta se perdia.
        Conserva los mensajes de sistema y el ultimo turno; descarta lo mas antiguo.
        """
        n_ctx = self._server_n_ctx()
        max_new = max(64, min(int(max_new), n_ctx // 2))
        budget = n_ctx - max_new - 192          # margen para la plantilla de chat
        total = sum(self._msg_tokens(m) for m in msgs)
        if total <= budget:
            return msgs, max_new
        original_total = total

        system = [m for m in msgs if m.get("role") == "system"]
        rest = [m for m in msgs if m.get("role") != "system"]
        dropped = 0
        while len(rest) > 1 and sum(self._msg_tokens(m) for m in system + rest) > budget:
            rest.pop(0)
            dropped += 1

        out = system + rest
        total = sum(self._msg_tokens(m) for m in out)
        if total > budget and rest and isinstance(rest[-1].get("content"), str):
            # Un unico mensaje enorme: se conserva el final, que suele ser lo pertinente
            last = dict(rest[-1])
            cut = (total - budget) * 3 + 64
            last["content"] = "[...contenido anterior recortado por limite de contexto...]\n" + last["content"][cut:]
            out = system + rest[:-1] + [last]

        logger.warning(
            f"✂️ [TemporalBrain] Historial ajustado al contexto ({n_ctx} tok): "
            f"{dropped} mensajes antiguos descartados, ~{original_total} -> ~{sum(self._msg_tokens(m) for m in out)} tok"
        )
        return out, max_new

    def _probe_socket(self, timeout: float = 1.5) -> bool:
        """True si hay un llama-server vivo respondiendo en el socket (sea de quien sea)."""
        if not self.socket_path.exists():
            return False
        try:
            transport = httpx.HTTPTransport(uds=str(self.socket_path))
            with httpx.Client(transport=transport, base_url="http://localhost", timeout=timeout) as client:
                return client.get("/health").status_code == 200
        except Exception:
            return False

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
            if self._probe_socket():
                logger.info(f"🔗 [TemporalBrain] Servidor existente adoptado en {self.socket_path}")
                return True

            import fcntl
            lock_fh = open(str(self.socket_path) + ".lock", "w")
            try:
                fcntl.flock(lock_fh, fcntl.LOCK_EX)
                # Revalidar tras obtener el lock: otro proceso pudo arrancarlo mientras esperabamos
                if self._probe_socket(timeout=3.0):
                    logger.info(f"🔗 [TemporalBrain] Servidor levantado por otro proceso, adoptado")
                    return True
                return self._start_locked(wait_ready)
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)
                lock_fh.close()

    def _start_locked(self, wait_ready: float) -> bool:
        """Arranque real. Requiere el lock entre procesos."""
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
        ctx = info.get("params", {}).get("num_ctx", self.ctx_size)

        cmd = [
            str(llama_server_bin),
            "--model", str(gguf_path),
            "--host", str(self.socket_path),
            "--alias", self.model_name,
            "--ctx-size", str(ctx),
            "--cache-type-k", str(self.cache_type_k),
            "--cache-type-v", str(self.cache_type_v),
            "--n-gpu-layers", str(self.gpu_layers),
            # Generacion: un hilo por nucleo fisico. Con 16 (SMT) en un CPU cargado,
            # la barrera de sincronizacion de llama.cpp colapsaba a ~1 tok/s.
            "--threads", str(self.threads),
            # Prefill (lotes grandes) si aprovecha todos los hilos logicos
            "--threads-batch", str(self.config.get("threads_batch", os.cpu_count() or self.threads)),
            # mlock requiere subir RLIMIT_MEMLOCK (root); desactivado por defecto
            *(["--mlock"] if self.config.get("mlock", False) else []),
            "--batch-size", "2048",
            "--ubatch-size", "512",
            "--flash-attn", "on",
            # Un solo slot: con -np auto (4) el cache KV se reparte y un pedido
            # largo fallaba con "Context size has been exceeded" pese a caber.
            "--parallel", "1",
            "--no-webui",
            "--offline",
            "--log-disable",
        ]

        logger.info(f"🧠 [TemporalBrain] Iniciando motor en socket UNIX privado: {self.socket_path}")
        if cuda_backend:
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
                    with httpx.Client(transport=transport, base_url="http://localhost", timeout=1.5) as client:
                        r = client.get("/health")
                        if r.status_code == 200:
                            logger.info(f"✅ [TemporalBrain] Motor listo y modelo cargado ({time.time() - t0:.2f}s) en {self.socket_path}")
                            return True
                except Exception:
                    pass
            if self._process.poll() is not None:
                logger.error(f"❌ [TemporalBrain] Fallo al iniciar (código {self._process.returncode})")
                return False
            time.sleep(0.15)

        logger.warning(f"⚠️ [TemporalBrain] Tiempo de espera agotado en {self.socket_path}")
        return False

    def stop(self):
        """Detiene el ejecutor y remueve el socket UNIX privado."""
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

                # Solo el proceso que lanzo el servidor libera el socket: stop() corre
                # via atexit en cualquier proceso que instancie el motor.
                if self.socket_path.exists():
                    try:
                        self.socket_path.unlink()
                    except Exception:
                        pass
                logger.info("🛑 [TemporalBrain] Motor detenido y socket liberado.")

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
    ) -> Dict[str, Any]:
        """Ejecuta inferencia síncrona pasando por adaptadores y hooks personalizados."""
        t0 = time.time()
        options = {
            "temperature": float(temperature if temperature is not None else self.config.get("temperature", 0.3)),
            "max_tokens": int(max_tokens if max_tokens is not None else self.config.get("max_tokens", 2048)),
            "num_ctx": num_ctx,
        }

        # 1. Pipeline Pre-Inferencia: Adaptadores y Hooks
        current_msgs = list(messages)
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
                return {"ok": False, "reply": "[Error: Temporal Brain no pudo iniciar]", "elapsed": 0}

        current_msgs, options["max_tokens"] = self._fit_to_context(current_msgs, options["max_tokens"])

        payload = {
            "model": self.model_name,
            "messages": current_msgs,
            "temperature": options["temperature"],
            "max_tokens": options["max_tokens"],
            "stream": False,
        }

        # 3. Llamada al socket UNIX privado
        transport = httpx.HTTPTransport(uds=str(self.socket_path))
        raw_result: Dict[str, Any] = {}
        try:
            with httpx.Client(transport=transport, base_url="http://localhost", timeout=90.0) as client:
                resp = client.post("/v1/chat/completions", json=payload)
                elapsed = round(time.time() - t0, 3)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    reply = choices[0].get("message", {}).get("content", "") if choices else ""
                    usage = data.get("usage", {})
                    raw_result = {
                        "ok": True,
                        "reply": reply.strip(),
                        "usage": usage,
                        "elapsed": elapsed,
                        "tokens_per_sec": round(usage.get("completion_tokens", 0) / max(elapsed, 0.001), 1),
                        "engine": "temporal_brain",
                        "socket": str(self.socket_path),
                    }
                else:
                    raw_result = {
                        "ok": False,
                        "reply": f"Error del motor Temporal Brain (HTTP {resp.status_code}): {resp.text}",
                        "elapsed": elapsed,
                    }
        except Exception as e:
            raw_result = {"ok": False, "reply": f"Error en socket IPC: {e}", "elapsed": round(time.time() - t0, 3)}

        # 4. Pipeline Post-Inferencia: Hooks y Adaptadores
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

        return raw_result

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        num_ctx: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Generator[str, None, str]:
        """Generador streaming que aplica adaptadores y filtros de tokens en tiempo real."""
        options = {
            "temperature": float(temperature if temperature is not None else self.config.get("temperature", 0.3)),
            "max_tokens": int(max_tokens if max_tokens is not None else self.config.get("max_tokens", 2048)),
            "num_ctx": num_ctx,
        }

        # 1. Pipeline Pre-Inferencia
        current_msgs = list(messages)
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

        payload = {
            "model": self.model_name,
            "messages": current_msgs,
            "temperature": options["temperature"],
            "max_tokens": options["max_tokens"],
            "stream": True,
        }

        transport = httpx.HTTPTransport(uds=str(self.socket_path))
        full_reply = []

        with httpx.Client(transport=transport, base_url="http://localhost", timeout=120.0) as client:
            with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
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
