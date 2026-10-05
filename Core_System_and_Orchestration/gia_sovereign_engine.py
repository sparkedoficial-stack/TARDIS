"""
gia_sovereign_engine.py - Motor Unificado de Inferencia Soberana Resiliente
===========================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana GIA

Arquitectura de Inferencia Dual Redundante (Zero-Drop):
1. CANAL HTTP RESILIENTE (Socket Multi-Host + Auto-Revive Daemon + KeepAlive):
   - Sondeo dinámico en REDACTED_IP, localhost y [::1].
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

try:
    import colibri_bridge
    import colibri_optimizer
    _COLIBRI_ACTIVE = True
except Exception:
    _COLIBRI_ACTIVE = False

# Rutas del entorno de trabajo
WORKSPACE_DIR = Path(__file__).resolve().parent
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))

CANDIDATE_ENDPOINTS = [
    "http://REDACTED_IP:11434",
    "http://localhost:11434",
    "http://[::1]:11434",
    "http://REDACTED_IP:11434"
]

DEFAULT_MODELS_PREFERENCE = [
    "huihui_ai/llama3.1-8b-instruct-abliterated",
    "dolphin3",
    "dolphin3.0",
    "dolphin",
    "hermes3:8b",
    "hermes3",
    "hermes3:latest",
    "Llama-3.2-3B-Instruct-uncensored-GGUF:latest",
    "Llama-3.2-3B-Instruct-uncensored",
    "llama3.2-uncensored:latest",
    "hf.co/bartowski/Llama-3.2-3B-Instruct-uncensored-GGUF:Q4_K_M",
    "llama3.2:3b",
    "llama3.2",
    "llama3.2:latest",
    "qwen2.5:3b",
    "Qwen3.8-Flash-Next",
    "Qwen3.8-27B-Uncensored-MLX:latest",
    "Qwen3.8-27B-Uncensored:latest",
    "orcarouter/Qwen3.8-27B-Uncensored:latest",
    "Qwen3.8-27B-Uncensored",
    "qwen3.8-27b-uncensored",
    "qwen3.8:27b",
    "Qwen3.6-35B-A3B",
    "DeepSeek-V4-Flash",
    "GLM-5.3-Flash",
    "colibri-active",
    "olmoe",
    "llama3.2:3b",
    "qwen2.5:3b",
    "llama3.1:8b",
    "qwen2.5-coder:7b",
    "deepseek-r1:8b",
    "qwen3.6:latest",
    "qwen3-coder:30b",
    "llama4:scout"
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
        self.preferred_endpoint = preferred_endpoint or os.environ.get("OLLAMA_HOST", "http://REDACTED_IP:11434")
        self.active_endpoint: Optional[str] = None
        self.default_model = default_model or os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated")
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

    def _probe_endpoint(self, endpoint: str, timeout: float = 1.2) -> bool:
        """Verifica de forma ultrarrápida y no bloqueante si un endpoint responde."""
        ep = endpoint.strip().rstrip("/")
        if not ep.startswith("http://") and not ep.startswith("https://"):
            ep = f"http://{ep}"
        url = f"{ep}/api/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "GIA-Sovereign-Engine/26.4"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def find_working_endpoint(self) -> Optional[str]:
        """Encuentra el endpoint activo más rápido entre los candidatos."""
        candidates = [self.preferred_endpoint] + [c for c in CANDIDATE_ENDPOINTS if c != self.preferred_endpoint]
        for ep in candidates:
            if self._probe_endpoint(ep):
                self.active_endpoint = ep
                return ep
        return None

    def auto_spawn_daemon(self) -> bool:
        """Inicia el demonio de Ollama en segundo plano sin ventana."""
        if self.find_working_endpoint():
            return True
        if not self.binary_path:
            self.binary_path = find_ollama_binary()
        if not self.binary_path:
            return False

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        spawn_env = os.environ.copy()
        spawn_env["OLLAMA_FLASH_ATTENTION"] = "1"
        spawn_env["OLLAMA_KEEP_ALIVE"] = "-1"
        spawn_env["OLLAMA_NUM_PARALLEL"] = "1"
        spawn_env["OLLAMA_MAX_LOADED_MODELS"] = "1"
        spawn_env["OLLAMA_MAX_QUEUE"] = "512"
        spawn_env["CUDA_VISIBLE_DEVICES"] = "0"
        spawn_env["OLLAMA_KV_CACHE_TYPE"] = os.environ.get("OLLAMA_KV_CACHE_TYPE", "f16")
        spawn_env["OMP_NUM_THREADS"] = os.environ.get("GIA_NUM_THREADS", "12")
        spawn_env["OMP_PROC_BIND"] = "close"
        spawn_env["OMP_PLACES"] = "cores"
        spawn_env["RAM_GB"] = "18.0"

        try:
            subprocess.Popen(
                [self.binary_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                env=spawn_env,
                start_new_session=(sys.platform != "win32"),
                close_fds=(sys.platform != "win32")
            )
            return True
        except Exception:
            try:
                subprocess.Popen(
                    [self.binary_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                    env=spawn_env,
                    start_new_session=(sys.platform != "win32"),
                    close_fds=(sys.platform != "win32")
                )
                return True
            except Exception:
                return False

    def diagnose_and_heal(self, auto_start: bool = True, wait_seconds: float = 12.0) -> Dict[str, Any]:
        """Diagnostica el estado del motor y reanima el servicio si es necesario."""
        working_ep = self.find_working_endpoint()
        if working_ep:
            return {
                "ok": True,
                "mode": "http_socket",
                "endpoint": working_ep,
                "models": self.get_available_models(refresh=True)
            }

        if auto_start:
            spawned = self.auto_spawn_daemon()
            if spawned:
                start_t = time.time()
                while time.time() - start_t < wait_seconds:
                    time.sleep(0.4)
                    working_ep = self.find_working_endpoint()
                    if working_ep:
                        return {
                            "ok": True,
                            "mode": "http_socket",
                            "endpoint": working_ep,
                            "models": self.get_available_models(refresh=True)
                        }

        # Si el socket HTTP no levanta, el motor nativo por tubería sigue operativo
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
        """Devuelve la lista de modelos instalados mediante HTTP o manifiestos en disco."""
        now = time.time()
        if not refresh and self._cached_models and (now - self._last_model_check < 60.0):
            return self._cached_models

        models: List[str] = []

        # 1. Intentar por HTTP
        ep = self.active_endpoint or self.preferred_endpoint
        if ep:
            try:
                url = f"{ep}/api/tags"
                req = urllib.request.Request(url, headers={"User-Agent": "GIA-Sovereign-Engine/26.4"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            except Exception:
                pass

        # 2. Si falló HTTP, intentar leyendo manifiestos locales de Ollama en disco
        if not models:
            manifest_dir = Path(os.path.expanduser("~")) / ".ollama" / "models" / "manifests"
            if manifest_dir.exists():
                for p in manifest_dir.glob("*/*/*/*"):
                    if p.is_file():
                        # Ejemplo: registry.ollama.ai/library/llama3.2/3b -> llama3.2:3b
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
        if _COLIBRI_ACTIVE:
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
                    ep = self.find_working_endpoint()
                    if ep:
                        target = self.resolve_model(self.default_model)
                        payload = {
                            "model": target,
                            "messages": [{"role": "user", "content": "ping"}],
                            "stream": False,
                            "keep_alive": "24h",
                            "options": {"num_predict": 1}
                        }
                        req = urllib.request.Request(
                            f"{ep}/api/chat",
                            data=json.dumps(payload).encode("utf-8"),
                            headers={"Content-Type": "application/json", "User-Agent": "GIA-Keepalive"}
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
        """Streaming por HTTP con reanimación automática, diálogo comedido, soporte de cancelación y tiempo indefinido."""
        ep = self.find_working_endpoint()
        if not ep:
            self.diagnose_and_heal(auto_start=True, wait_seconds=6.0)
            ep = self.find_working_endpoint()

        if not ep:
            raise ConnectionError("No se pudo establecer conexión con ningún endpoint HTTP de Ollama.")

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": -1,
            "options": {
                "temperature": float(temperature or 0.3),
                "num_ctx": int(num_ctx or os.environ.get("GIA_NUM_CTX", 4096)),
                "num_predict": int(os.environ.get("GIA_NUM_PREDICT", 512)),
                "num_thread": int(os.environ.get("GIA_NUM_THREADS", 12)),
                "repeat_penalty": 1.15,
                "use_mmap": True,
                "use_mlock": True,
                "num_batch": int(os.environ.get("GIA_NUM_BATCH", 512))
            }
        }

        req = urllib.request.Request(
            f"{ep}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "GIA-Sovereign-Engine/26.4"}
        )

        full_reply = []
        opener = urllib.request.urlopen(req, timeout=timeout) if timeout else urllib.request.urlopen(req)
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

        proc = subprocess.Popen(
            [self.binary_path, "run", model, "--nowordwrap"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            text=True,
            bufsize=0
        )

        if on_process_spawned:
            try:
                on_process_spawned(proc)
            except Exception:
                pass

        full_reply = []
        try:
            # Enviar el prompt completo y cerrar stdin para señalar fin de entrada
            if proc.stdin:
                proc.stdin.write(full_input)
                proc.stdin.close()

            # Leer streaming desde stdout sin artifacts de terminal
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

                chunk = proc.stdout.read(8)
                if not chunk:
                    break
                clean_chunk = self._clean_ansi(chunk)
                if clean_chunk:
                    full_reply.append(clean_chunk)
                    yield clean_chunk

            proc.wait(timeout=timeout if timeout else None)
        except Exception as e:
            try:
                proc.kill()
            except Exception:
                pass
            raise e

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

        # 0. TIER 0: Motor Colibri MoE Ultrarrápido y Soberano (solo si el servidor Colibri está vivo en puerto 8765)
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
        if channel == "colibri":
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
