"""
engine/sovereign_client.py - Cliente Unificado de Inferencia Soberana (Hermes 3 8B)
Optimizado con Flash Attention, streaming HTTP de baja latencia y control de cancelación.
"""
from __future__ import annotations
import asyncio
import json
import os
import threading
import time
import urllib.request
import urllib.error
from typing import AsyncGenerator, Dict, Any, Generator, List, Optional, Union
from core.config import get_settings


class SovereignClient:
    _instance: Optional[SovereignClient] = None
    _lock = threading.Lock()

    def __init__(self):
        self.settings = get_settings()
        # Asegurar que Flash Attention esté activo en el proceso
        if self.settings.ollama_flash_attention:
            os.environ["OLLAMA_FLASH_ATTENTION"] = "1"

    @classmethod
    def get_instance(cls) -> SovereignClient:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _build_options(self, num_ctx: Optional[int] = None, temperature: Optional[float] = None) -> dict:
        return {
            "temperature": float(temperature if temperature is not None else self.settings.temperature),
            "num_ctx": int(num_ctx if num_ctx is not None else self.settings.num_ctx),
            "num_predict": int(self.settings.num_predict),
            "num_thread": int(os.environ.get("GIA_NUM_THREADS", str(self.settings.num_threads))),
            "repeat_penalty": 1.15,
            "use_mmap": True,
            "use_mlock": self.settings.use_mlock,
            "num_batch": int(os.environ.get("GIA_NUM_BATCH", str(self.settings.num_batch)))
        }

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None
    ) -> Generator[str, None, str]:
        """Streaming generador síncrono para consumo directo o SSE."""
        target_model = model or self.settings.model
        options = self._build_options(num_ctx=num_ctx, temperature=temperature)
        payload = {
            "model": target_model,
            "messages": messages,
            "stream": True,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": options
        }

        # Cluster candidate endpoints
        endpoints = [self.settings.ollama_url]
        imac_ollama = "http://REDACTED_IP:11434"
        if imac_ollama not in endpoints:
            endpoints.append(imac_ollama)

        full_reply = []
        last_error = None
        succeeded = False

        for endpoint in endpoints:
            cur_payload = dict(payload)
            # If failing over to remote iMac node, adapt model and resources for fast execution
            if endpoint == imac_ollama:
                if target_model not in ("qwen2.5:1.5b", "qwen2.5:0.5b"):
                    cur_payload["model"] = "qwen2.5:1.5b"
                imac_opts = dict(options)
                imac_opts["num_ctx"] = min(imac_opts.get("num_ctx", 2048), 2048)
                imac_opts["use_mlock"] = False
                imac_opts["num_batch"] = 256
                imac_opts["num_thread"] = 4
                cur_payload["options"] = imac_opts

            req = urllib.request.Request(
                f"{endpoint}/api/chat",
                data=json.dumps(cur_payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "GODWORKS-Sovereign-Client/26.4"}
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    for line in resp:
                        if cancel_event and cancel_event.is_set():
                            msg = "\n[⛔ Inferencia cancelada y proceso cortado por el usuario]"
                            full_reply.append(msg)
                            yield msg
                            return msg
                        if not line:
                            continue
                        try:
                            data = json.loads(line.decode("utf-8", errors="replace"))
                            content = data.get("message", {}).get("content", "")
                            if content:
                                full_reply.append(content)
                                yield content
                            if data.get("done", False):
                                break
                        except Exception:
                            continue
                succeeded = True
                break
            except Exception as e_ep:
                last_error = e_ep
                continue

        if not succeeded:
            # Fallback a motor directo soberano si el puerto responde con error
            try:
                import gia_sovereign_engine as _gse
                eng = _gse.get_engine()
                for chunk in eng.chat_stream(messages, model=target_model, cancel_event=cancel_event):
                    full_reply.append(chunk)
                    yield chunk
                succeeded = True
            except Exception as e_fb:
                err = f"[Error Inferencia Clúster: {last_error} | Fallback: {e_fb}]"
                full_reply.append(err)
                yield err

        return "".join(full_reply)

    async def chat_stream_async(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None
    ) -> AsyncGenerator[str, None]:
        """Streaming generador asíncrono para endpoints ASGI (FastAPI StreamingResponse)."""
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[Union[str, None]] = asyncio.Queue()

        def _sync_worker():
            try:
                for chunk in self.chat_stream(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    num_ctx=num_ctx,
                    cancel_event=cancel_event
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=_sync_worker, daemon=True).start()

        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    def chat(
        self,
        messages: Union[List[Dict[str, str]], str],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None
    ) -> Dict[str, Any]:
        """Llamada síncrona que retorna respuesta completa y metadatos."""
        t0 = time.time()
        if isinstance(messages, str):
            conv = [{"role": "user", "content": messages}]
        else:
            conv = list(messages)

        target_model = model or self.settings.model
        chunks = []
        for piece in self.chat_stream(
            conv,
            model=target_model,
            temperature=temperature,
            num_ctx=num_ctx,
            cancel_event=cancel_event
        ):
            chunks.append(piece)

        reply = "".join(chunks).strip()
        elapsed = round(time.time() - t0, 2)
        is_cancelled = bool(cancel_event and cancel_event.is_set())
        is_ok = bool(reply and not reply.startswith("[Error") and not is_cancelled)

        return {
            "ok": is_ok,
            "reply": reply,
            "model": target_model,
            "elapsed_s": elapsed,
            "cancelled": is_cancelled
        }


def get_sovereign_client() -> SovereignClient:
    return SovereignClient.get_instance()
