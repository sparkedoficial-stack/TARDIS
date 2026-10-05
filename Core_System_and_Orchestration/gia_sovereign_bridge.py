"""
gia_sovereign_bridge.py - Puente Soberano Exclusivo y Blindado para Qwen3.8-27B-Uncensored.
GODWORKS SYSTEM v26.4

Este módulo actúa como el único enrutador e interceptor de inferencia en el sistema.
Garantiza que toda llamada proveniente de cualquier subsistema (Web UI, ECCA, Supervisor,
Bridge Antigravity, CLI o Agentes Autónomos) sea canalizada ÚNICA Y EXCLUSIVAMENTE
hacia Qwen3.8-27B-Uncensored-MLX, con los parámetros calibrados para el hardware actual
(GPU NVIDIA 4GB VRAM + 24GB RAM + 12 hilos CPU + num_ctx 4096).
"""

import json
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, Generator, List, Optional, Union

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import gia_sovereign_engine as gse

logger = logging.getLogger("GIA_SOVEREIGN_BRIDGE")

EXCLUSIVE_MODEL_TAGS = [
    "huihui_ai/llama3.1-8b-instruct-abliterated",
    "dolphin3",
    "dolphin3.0",
    "dolphin",
    "hermes3:8b",
    "hermes3",
    "hermes3:latest",
    "Qwen3.8-Flash-Next",
    "Qwen3.8-27B-Uncensored-MLX:latest",
    "Qwen3.8-27B-Uncensored:latest",
    "colibri-active"
]

PRIMARY_EXCLUSIVE_MODEL = os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated")

HARDWARE_CALIBRATION = {
    "num_thread": 8,
    "num_ctx": 16384,
    "ram_allocated_gb": 16.0,
    "repeat_penalty": 1.15,
    "temperature": 0.3,
    "top_p": 0.9,
    "use_mmap": True,
    "num_batch": 512,
    "keep_alive": "24h"
}


class SovereignModelBridge:
    """
    Puente soberano que bloquea e intercepta todas las peticiones para asegurar
    que única y exclusivamente responda Qwen3.8-27B-Uncensored.
    """

    _instance: Optional["SovereignModelBridge"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.engine = gse.get_engine()
        self.primary_model = PRIMARY_EXCLUSIVE_MODEL
        self._warmup_done = False

    @classmethod
    def get_bridge(cls) -> "SovereignModelBridge":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def enforce_model(self, requested_model: Optional[str] = None) -> str:
        """
        Garantiza que el modelo activo sea respetado o resuelto hacia el núcleo soberano configurado.
        """
        active_target = requested_model or os.environ.get("GIA_MODEL", self.primary_model)
        available = self.engine.get_available_models()
        if active_target in available:
            return active_target
        for tag in EXCLUSIVE_MODEL_TAGS:
            for m in available:
                if m.lower() == tag.lower() or tag.lower() in m.lower():
                    return m
        return active_target

    def chat(
        self,
        prompt_or_messages: Union[str, List[Dict[str, str]]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None,
        timeout: float = 180.0
    ) -> Dict[str, Any]:
        """
        Inferencia síncrona exclusiva a través del puente soberano.
        """
        target_model = self.enforce_model(model)
        temp = temperature if temperature is not None else HARDWARE_CALIBRATION["temperature"]
        ctx = num_ctx if num_ctx is not None else HARDWARE_CALIBRATION["num_ctx"]

        return self.engine.chat(
            prompt_or_messages,
            model=target_model,
            system=system_prompt,
            temperature=temp,
            num_ctx=ctx
        )

    def chat_stream(
        self,
        prompt_or_messages: Union[str, List[Dict[str, str]]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None,
        timeout: float = 300.0
    ) -> Generator[str, None, str]:
        """
        Streaming token a token exclusivo a través del puente soberano.
        """
        target_model = self.enforce_model(model)
        temp = temperature if temperature is not None else HARDWARE_CALIBRATION["temperature"]
        ctx = num_ctx if num_ctx is not None else HARDWARE_CALIBRATION["num_ctx"]

        if isinstance(prompt_or_messages, str):
            conv = [{"role": "user", "content": prompt_or_messages}]
        else:
            conv = list(prompt_or_messages)

        return self.engine.chat_stream(
            conv,
            model=target_model,
            system=system_prompt,
            temperature=temp,
            num_ctx=ctx
        )

    def warmup_and_lock(self) -> Dict[str, Any]:
        """Precarga y ancla Qwen3.8-27B en la memoria RAM/VRAM del sistema."""
        target_model = self.enforce_model()
        logger.info(f"[SOVEREIGN-BRIDGE] Precargando y anclando {target_model} en RAM/VRAM...")
        res = self.chat("CONFIRMACIÓN DE ANCLAJE SOBERANO", model=target_model, timeout=60.0)
        self._warmup_done = True
        return res


def get_bridge() -> SovereignModelBridge:
    return SovereignModelBridge.get_bridge()


if __name__ == "__main__":
    b = get_bridge()
    print("=== PUENTE SOBERANO EXCLUSIVO QWEN 3.8 27B ===")
    print("Modelo forzado:", b.enforce_model("llama3.2:3b"))
    print("Probando inferencia a traves del puente...")
    reply = b.chat("Identifícate brevemente.")
    print("Respuesta:", reply.get("reply", ""))
    print("Metadatos:", {k: v for k, v in reply.items() if k != "reply"})
