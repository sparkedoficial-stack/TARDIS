"""
core/sovereign_local_runner.py - Motor Local Directo de Inferencia Soberana (Serverless)
======================================================================================
GODWORKS SYSTEM · Suite Soberana TARDIS

Este módulo implementa el ejecutor local directo de modelos GGUF, realizando ingeniería
inversa a la arquitectura interna de Ollama para:
1. Inspeccionar y resolver modelos desde el almacén de blobs y manifiestos OCI de Ollama.
2. Ejecutar inferencia de forma directa y nativa utilizando el backend C++ de llama.cpp
   (/home/timemachine/.local/lib/ollama/llama-server + libggml-cuda.so) comunicándose
   estrictamente a través de un socket UNIX local privado (IPC), SIN exponer puertos TCP
   ni requerir que 'ollama serve' esté activo.
3. Proveer streaming en tiempo real, cancelación instantánea de turnos y métricas de velocidad.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, Union

import httpx

logger = logging.getLogger("SovereignLocalRunner")

# Rutas estándar del sistema
HOME_DIR = Path(os.path.expanduser("~"))
OLLAMA_MODELS_DIR = HOME_DIR / ".ollama" / "models"
OLLAMA_MANIFESTS_DIR = OLLAMA_MODELS_DIR / "manifests"
OLLAMA_BLOBS_DIR = OLLAMA_MODELS_DIR / "blobs"
OLLAMA_LIB_DIR = HOME_DIR / ".local" / "lib" / "ollama"
TEMPORAL_BRAIN_LIB_DIR = HOME_DIR / ".local" / "lib" / "temporal_brain"
SOVEREIGN_MODELS_DIR = Path(__file__).resolve().parent.parent / "data" / "models"
DEFAULT_SOCKET_PATH = Path("/tmp/tardis_sovereign_runner.sock")


# ==============================================================================
# 1. INSPECTOR DE MODELOS Y MANIFIESTOS DE OLLAMA
# ==============================================================================

class OllamaModelInspector:
    """
    Inspecciona la estructura interna de almacenamiento de Ollama (manifiestos OCI y blobs)
    para resolver rutas a archivos GGUF, plantillas de chat y parámetros de inferencia.
    """

    @staticmethod
    def list_models() -> List[Dict[str, Any]]:
        """Lista todos los modelos disponibles en el almacén local de Ollama."""
        models = []
        if not OLLAMA_MANIFESTS_DIR.exists():
            return models

        for manifest_file in OLLAMA_MANIFESTS_DIR.glob("*/*/*/*"):
            if manifest_file.is_file():
                try:
                    parts = manifest_file.parts
                    # e.g., manifests/registry.ollama.ai/library/TARDIS-NEURAL-SPACE-KAIJU/latest
                    model_name = f"{parts[-2]}:{parts[-1]}" if len(parts) >= 2 else manifest_file.name
                    info = OllamaModelInspector.inspect_model(model_name)
                    if info:
                        models.append(info)
                except Exception as e:
                    logger.debug(f"Error leyendo manifiesto {manifest_file}: {e}")
        return models

    @staticmethod
    def inspect_model(model_name: str) -> Optional[Dict[str, Any]]:
        """
        Lee el manifiesto de un modelo y resuelve las rutas a sus capas (GGUF, plantilla, sistema, parámetros).
        """
        clean_name = model_name.strip()
        tag = "latest"
        if ":" in clean_name:
            clean_name, tag = clean_name.split(":", 1)

        # Buscar manifiesto en registry.ollama.ai/library o directo
        candidates = [
            OLLAMA_MANIFESTS_DIR / "registry.ollama.ai" / "library" / clean_name / tag,
            OLLAMA_MANIFESTS_DIR / clean_name / tag,
        ]
        # Búsqueda insensible a mayúsculas si no se encuentra
        manifest_path = None
        for c in candidates:
            if c.exists() and c.is_file():
                manifest_path = c
                break

        if not manifest_path and OLLAMA_MANIFESTS_DIR.exists():
            for p in OLLAMA_MANIFESTS_DIR.glob(f"**/{clean_name}/{tag}"):
                if p.is_file():
                    manifest_path = p
                    break

        if not manifest_path:
            return None

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            layers = data.get("layers", [])
            gguf_path = None
            template_str = ""
            system_prompt = ""
            params_dict: Dict[str, Any] = {}
            total_size = 0

            for layer in layers:
                media_type = layer.get("mediaType", "")
                digest = layer.get("digest", "")
                size = layer.get("size", 0)
                total_size += size

                if not digest.startswith("sha256:"):
                    continue
                blob_hash = digest.split(":", 1)[1]
                blob_file = OLLAMA_BLOBS_DIR / f"sha256-{blob_hash}"

                if not blob_file.exists():
                    continue

                if "image.model" in media_type:
                    gguf_path = blob_file
                elif "image.template" in media_type:
                    try:
                        template_str = blob_file.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        pass
                elif "image.system" in media_type:
                    try:
                        system_prompt = blob_file.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        pass
                elif "image.params" in media_type:
                    try:
                        params_dict = json.loads(blob_file.read_text(encoding="utf-8", errors="ignore"))
                    except Exception:
                        pass

            if not gguf_path:
                return None

            return {
                "name": f"{clean_name}:{tag}",
                "model_name": clean_name,
                "tag": tag,
                "manifest_path": str(manifest_path),
                "gguf_path": str(gguf_path),
                "template": template_str,
                "system_prompt": system_prompt,
                "params": params_dict,
                "size_bytes": total_size,
                "size_gb": round(total_size / (1024**3), 2),
            }
        except Exception as e:
            logger.error(f"Error procesando manifiesto de {model_name}: {e}")
            return None


# ==============================================================================
# 2. EJECUTOR LOCAL DIRECTO (SERVERLESS / IPC POR SOCKET UNIX)
# ==============================================================================

class SovereignLocalRunner:
    """
    Ejecutor nativo de inferencia local sin servidor de fondo.
    Ejecuta el binario C++ llama-server vinculado exclusivamente a un socket UNIX privado,
    eliminando toda dependencia de 'ollama serve' y puertos TCP de red.
    """

    _instance: Optional["SovereignLocalRunner"] = None
    _lock = threading.Lock()

    def __init__(
        self,
        model_name: str = "TARDIS-NEURAL-SPACE-KAIJU",
        socket_path: Optional[Path] = None,
        ctx_size: int = 8192,
        gpu_layers: int = 20,
        threads: int = 16,
        cache_type_k: str = "q8_0",
        cache_type_v: str = "q8_0",
    ):
        self.model_name = model_name
        self.socket_path = Path(socket_path or DEFAULT_SOCKET_PATH)
        self.ctx_size = ctx_size
        self.gpu_layers = gpu_layers
        self.threads = threads
        self.cache_type_k = cache_type_k
        self.cache_type_v = cache_type_v

        self._process: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._client: Optional[httpx.Client] = None
        self._model_info: Optional[Dict[str, Any]] = None

        # Registrar apagado limpio
        atexit.register(self.stop)

    @classmethod
    def get_instance(cls, **kwargs) -> "SovereignLocalRunner":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(**kwargs)
            return cls._instance

    def _resolve_model(self) -> Dict[str, Any]:
        """Resuelve el archivo GGUF e hiperparámetros del modelo."""
        # 1. Buscar primero en data/models/
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

        info = OllamaModelInspector.inspect_model(self.model_name)
        if not info:
            # Intentar buscar como archivo GGUF directo
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
                # Fallback al primer modelo disponible en el almacén de Ollama
                available = OllamaModelInspector.list_models()
                if available:
                    info = available[0]
                    logger.info(f"Fallback a modelo disponible: {info['name']}")

        if not info:
            raise FileNotFoundError(f"No se pudo resolver el modelo GGUF para: {self.model_name}")

        self._model_info = info
        return info

    def _get_cuda_environment(self) -> Tuple[Dict[str, str], Optional[str]]:
        """Configura el entorno dinámico para aceleración CUDA en RTX 3050."""
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

        # Fallback a librerías CPU optimizadas
        env["LD_LIBRARY_PATH"] = f"{lib_dir}:{env.get('LD_LIBRARY_PATH', '')}".strip(":")
        return env, None

    def start(self, wait_ready: float = 30.0) -> bool:
        """Inicia el ejecutor local C++ vinculado al socket UNIX sin puertos de red."""
        with self._proc_lock:
            if self.is_running():
                return True

            info = self._resolve_model()
            gguf_path = info["gguf_path"]

            llama_server_bin = TEMPORAL_BRAIN_LIB_DIR / "llama-server"
            if not llama_server_bin.exists():
                llama_server_bin = OLLAMA_LIB_DIR / "llama-server"
            if not llama_server_bin.exists():
                raise FileNotFoundError(f"Binario llama-server no encontrado en: {llama_server_bin}")

            # Limpiar socket previo si existe
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
                "--threads", str(self.threads),
                "--batch-size", "2048",
                "--ubatch-size", "512",
                "--flash-attn", "on",
                "--no-webui",
                "--offline",
                "--log-disable",
            ]

            logger.info(f"🦖 [SovereignLocalRunner] Iniciando ejecutor directo en socket UNIX: {self.socket_path}")
            if cuda_backend:
                logger.info(f"⚡ [SovereignLocalRunner] Aceleración CUDA activada ({cuda_backend})")

            self._process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )

            # Esperar a que el socket UNIX esté listo y responda
            t0 = time.time()
            while time.time() - t0 < wait_ready:
                if self.socket_path.exists():
                    try:
                        # Verificar salud a través del socket
                        if self._check_socket_health():
                            logger.info(f"✅ [SovereignLocalRunner] Ejecutor listo ({time.time() - t0:.2f}s) en {self.socket_path}")
                            return True
                    except Exception:
                        pass
                if self._process.poll() is not None:
                    logger.error(f"❌ [SovereignLocalRunner] Proceso terminó inesperadamente con código {self._process.returncode}")
                    return False
                time.sleep(0.15)

            logger.warning(f"⚠️ [SovereignLocalRunner] Tiempo de espera agotado iniciando socket {self.socket_path}")
            return False

    def _check_socket_health(self) -> bool:
        """Comprueba si el socket UNIX responde al endpoint /health."""
        try:
            transport = httpx.HTTPTransport(uds=str(self.socket_path))
            with httpx.Client(transport=transport, base_url="http://localhost", timeout=1.5) as client:
                r = client.get("/health")
                return r.status_code == 200
        except Exception:
            return False

    def is_running(self) -> bool:
        """Indica si el ejecutor local está activo y el socket está vivo."""
        if not self._process or self._process.poll() is not None:
            return False
        return self.socket_path.exists()

    def is_serverless_ready(self, model_name: Optional[str] = None) -> bool:
        """Comprueba si el binario local y el modelo GGUF están listos para ejecución serverless."""
        llama_server_bin = TEMPORAL_BRAIN_LIB_DIR / "llama-server"
        if not llama_server_bin.exists():
            llama_server_bin = OLLAMA_LIB_DIR / "llama-server"
        if not llama_server_bin.exists():
            return False

        # Verificar modelo soberano en data/models/
        candidate_model_files = [
            SOVEREIGN_MODELS_DIR / f"{self.model_name}.gguf",
            SOVEREIGN_MODELS_DIR / "TARDIS-NEURAL-SPACE-KAIJU.gguf"
        ]
        for cmf in candidate_model_files:
            if cmf.exists():
                return True

        target = model_name or self.model_name
        try:
            info = OllamaModelInspector.inspect_model(target)
            if info and Path(info["gguf_path"]).exists():
                return True
            p = Path(target)
            if p.is_file() and p.suffix.lower() == ".gguf":
                return True
            # Fallback a cualquier modelo en el almacén
            models = OllamaModelInspector.list_models()
            return len(models) > 0
        except Exception:
            return False

    def get_client(self) -> httpx.Client:
        """Obtiene o inicializa el cliente HTTP sobre socket UNIX."""
        if not self.is_running():
            self.start()
        transport = httpx.HTTPTransport(uds=str(self.socket_path))
        return httpx.Client(transport=transport, base_url="http://localhost", timeout=120.0)

    # --------------------------------------------------------------------------
    # INFERENCIA Y CHAT SOBERANO
    # --------------------------------------------------------------------------

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        num_ctx: Optional[int] = None,
        max_tokens: int = 2048,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """Ejecuta una petición de chat síncrona completa contra el motor local directo."""
        t0 = time.time()
        if not self.is_running():
            ok = self.start()
            if not ok:
                return {"ok": False, "reply": "[Error: no se pudo iniciar el ejecutor local directo]", "elapsed": 0}

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": max_tokens,
            "stream": False,
        }

        transport = httpx.HTTPTransport(uds=str(self.socket_path))
        with httpx.Client(transport=transport, base_url="http://localhost", timeout=90.0) as client:
            try:
                resp = client.post("/v1/chat/completions", json=payload)
                elapsed = round(time.time() - t0, 3)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    reply = choices[0].get("message", {}).get("content", "") if choices else ""
                    usage = data.get("usage", {})
                    return {
                        "ok": True,
                        "reply": reply.strip(),
                        "usage": usage,
                        "elapsed": elapsed,
                        "tokens_per_sec": round(usage.get("completion_tokens", 0) / max(elapsed, 0.001), 1),
                        "engine": "sovereign_direct_ipc",
                        "socket": str(self.socket_path),
                    }
                else:
                    return {
                        "ok": False,
                        "reply": f"Error del motor C++ (HTTP {resp.status_code}): {resp.text}",
                        "elapsed": elapsed,
                    }
            except Exception as e:
                return {"ok": False, "reply": f"Error en socket IPC: {e}", "elapsed": round(time.time() - t0, 3)}

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        num_ctx: Optional[int] = None,
        max_tokens: int = 2048,
        cancel_event: Optional[threading.Event] = None,
    ) -> Generator[str, None, str]:
        """Generador de streaming SSE contra el ejecutor local directo."""
        if not self.is_running():
            self.start()

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": max_tokens,
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
                                full_reply.append(delta)
                                yield delta
                        except Exception:
                            continue

        return "".join(full_reply)

    def stop(self):
        """Detiene el ejecutor local y limpia el socket UNIX."""
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
            logger.info("🛑 [SovereignLocalRunner] Ejecutor directo detenido y socket liberado.")


# Función de acceso global
def get_local_runner(model_name: Optional[str] = None) -> SovereignLocalRunner:
    name = model_name or os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")
    return SovereignLocalRunner.get_instance(model_name=name)


get_sovereign_local_runner = get_local_runner

# Re-exportar componentes de Temporal Brain para acceso transversal
try:
    from core.temporal_brain import (
        TemporalBrain,
        get_temporal_brain,
        TemporalBrainAdapter,
        TemporalBrainConfig,
        TemporalBrainFunctionRegistry,
    )
except ImportError:
    pass


if __name__ == "__main__":
    print("=== INSPECTOR DE MODELOS OLLAMA ===")
    models = OllamaModelInspector.list_models()
    for m in models:
        print(f"• {m['name']} -> {m['gguf_path']} ({m['size_gb']} GB)")

    print("\n=== PRUEBA DE INFERENCIA DIRECTA SERVERLESS ===")
    runner = get_local_runner()
    print(f"Iniciando ejecutor directo en {runner.socket_path}...")
    res = runner.chat([
        {"role": "system", "content": "Responde en 1 oración."},
        {"role": "user", "content": "Identifícate brevemente."}
    ])
    print("Respuesta:", res)
    runner.stop()
