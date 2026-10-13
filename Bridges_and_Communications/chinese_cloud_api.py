"""
GODWORKS SYSTEM v26.4 - High-Speed Chinese AI Cloud Engine & Fast Token Gateway
================================================================================
Gestiona la conexión de ultra-baja latencia y alto throughput (tokens/segundo)
hacia los modelos chinos más potentes del momento:
- DeepSeek-R1 (Razonamiento profundo estilo o1)
- DeepSeek-V3 (671B MoE, código y tareas complejas)
- Qwen 2.5 72B / Coder 32B (Alibaba)
- GLM-4-Flash / Plus (Zhipu AI - 100% Free Tier)
- Proveedores de aceleración: SiliconFlow, DeepSeek, Zhipu, OpenRouter, Groq.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("GODWORKS.ChineseCloudAPI")

VAULT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_FILE = VAULT_DIR / "chinese_api_config.json"

PROVIDERS_CATALOG = {
    "siliconflow": {
        "name": "SiliconCloud (SiliconFlow / 硅基流动)",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "available_models": [
            "deepseek-ai/DeepSeek-R1",
            "deepseek-ai/DeepSeek-V3",
            "Qwen/Qwen2.5-72B-Instruct",
            "Qwen/Qwen2.5-Coder-32B-Instruct",
            "Qwen/Qwen2.5-7B-Instruct",
            "THUDM/glm-4-9b-chat"
        ],
        "website": "https://cloud.siliconflow.cn",
        "free_tier_info": "Modelos marcados 'Free' a costo cero + millones de tokens de bienvenida."
    },
    "deepseek": {
        "name": "DeepSeek Oficial",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "available_models": [
            "deepseek-chat",
            "deepseek-reasoner"
        ],
        "website": "https://platform.deepseek.com",
        "free_tier_info": "5,000,000 de tokens gratis al registrarse sin tarjeta."
    },
    "zhipu": {
        "name": "Zhipu AI (BigModel)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "available_models": [
            "glm-4-flash",
            "glm-4-plus",
            "glm-4-long"
        ],
        "website": "https://open.bigmodel.cn",
        "free_tier_info": "GLM-4-Flash 100% gratuito de por vida."
    },
    "groq_deepseek": {
        "name": "Groq LPU (Acelerador Extremo Qwen/DeepSeek/GPT-OSS)",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "openai/gpt-oss-120b",
        "available_models": [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.8-27b"
        ],
        "website": "https://console.groq.com",
        "free_tier_info": "250-350 tokens/segundo gratis permanente."
    },
    "openrouter": {
        "name": "OpenRouter (Pasarela Abierta Gratuita)",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "deepseek/deepseek-r1:free",
        "available_models": [
            "deepseek/deepseek-r1:free",
            "deepseek/deepseek-chat:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "meta-llama/llama-3.3-70b-instruct:free"
        ],
        "website": "https://openrouter.ai",
        "free_tier_info": "Modelos con sufijo :free disponibles con cuota abierta."
    }
}


class ChineseCloudAPI:
    """Controlador soberano para la API china de alta velocidad y razonamiento."""

    _instance: Optional["ChineseCloudAPI"] = None
    _lock = threading.Lock()

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or CONFIG_FILE
        self._db_lock = threading.Lock()
        self._config: Dict[str, Any] = {
            "enabled": True,
            "active_provider": "siliconflow",
            "active_model": "deepseek-ai/DeepSeek-V3",
            "api_keys": {
                "siliconflow": "",
                "deepseek": "",
                "zhipu": "",
                "groq_deepseek": "",
                "openrouter": ""
            },
            "custom_base_urls": {},
            "temperature": 0.3,
            "max_tokens": 4096,
            "auto_route_complex_tasks": True,
            "last_test": {},
            "total_requests": 0,
            "total_tokens": 0,
            "avg_tokens_per_sec": 0.0
        }
        self._load_config()

    @classmethod
    def get_instance(cls) -> "ChineseCloudAPI":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _load_config(self) -> None:
        with self._db_lock:
            if self.config_path.exists():
                try:
                    data = json.loads(self.config_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self._config.update(data)
                except Exception as e:
                    logger.warning(f"Aviso leyendo configuracion china: {e}")
            else:
                self._save_config_unlocked()

            # Auto-promoción: si el proveedor actual no tiene clave, usar el proveedor que sí tenga clave activa
            cur_p = self._config.get("active_provider", "")
            cur_key = self._config.get("api_keys", {}).get(cur_p, "")
            if not cur_key or len(cur_key) < 5:
                for p_name, p_key in self._config.get("api_keys", {}).items():
                    if p_key and len(p_key) > 5 and p_name in PROVIDERS_CATALOG:
                        self._config["active_provider"] = p_name
                        self._config["active_model"] = PROVIDERS_CATALOG[p_name]["default_model"]
                        self._save_config_unlocked()
                        break

    def _save_config_unlocked(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(self._config, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando chinese_api_config.json: {e}")

    def get_status(self) -> Dict[str, Any]:
        with self._db_lock:
            p_id = self._config.get("active_provider", "siliconflow")
            p_info = PROVIDERS_CATALOG.get(p_id, {})
            key = self._config.get("api_keys", {}).get(p_id, "")
            has_key = bool(key and len(key) > 5)
            masked_key = f"{key[:4]}...{key[-4:]}" if has_key else "Sin clave"

            return {
                "ok": True,
                "enabled": self._config.get("enabled", True),
                "active_provider": p_id,
                "provider_name": p_info.get("name", p_id),
                "active_model": self._config.get("active_model", p_info.get("default_model", "")),
                "base_url": self._config.get("custom_base_urls", {}).get(p_id) or p_info.get("base_url", ""),
                "has_key": has_key,
                "masked_key": masked_key,
                "auto_route_complex_tasks": self._config.get("auto_route_complex_tasks", True),
                "providers_catalog": PROVIDERS_CATALOG,
                "last_test": self._config.get("last_test", {}),
                "metrics": {
                    "total_requests": self._config.get("total_requests", 0),
                    "total_tokens": self._config.get("total_tokens", 0),
                    "avg_tokens_per_sec": round(self._config.get("avg_tokens_per_sec", 0.0), 1)
                }
            }

    def configure(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        enabled: Optional[bool] = None,
        auto_route: Optional[bool] = None
    ) -> Dict[str, Any]:
        with self._db_lock:
            if provider and provider in PROVIDERS_CATALOG:
                self._config["active_provider"] = provider
                if not model:
                    self._config["active_model"] = PROVIDERS_CATALOG[provider]["default_model"]
            if model:
                self._config["active_model"] = model
            if api_key is not None:
                p_id = self._config["active_provider"]
                self._config.setdefault("api_keys", {})[p_id] = api_key.strip()
            if enabled is not None:
                self._config["enabled"] = bool(enabled)
            if auto_route is not None:
                self._config["auto_route_complex_tasks"] = bool(auto_route)

            self._save_config_unlocked()

        return self.get_status()

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: float = 35.0
    ) -> Dict[str, Any]:
        """Ejecuta una solicitud de inferencia hacia el proveedor activo con conmutación resiliente multi-modelo."""
        with self._db_lock:
            p_id = provider or self._config.get("active_provider", "siliconflow")
            p_info = PROVIDERS_CATALOG.get(p_id, PROVIDERS_CATALOG["siliconflow"])
            target_model = model or self._config.get("active_model", p_info["default_model"])
            base_url = self._config.get("custom_base_urls", {}).get(p_id) or p_info["base_url"]
            api_key = self._config.get("api_keys", {}).get(p_id, "")
            temp = temperature if temperature is not None else self._config.get("temperature", 0.3)
            max_t = max_tokens if max_tokens is not None else self._config.get("max_tokens", 4096)
            if p_id == "groq_deepseek" and max_t > 3500:
                max_t = 3500

        # Lista de modelos candidatos para failover transparente
        model_candidates = [target_model]
        for alt_m in p_info.get("available_models", []):
            if alt_m not in model_candidates:
                model_candidates.append(alt_m)

        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json"
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        elif p_id == "openrouter":
            headers["Authorization"] = "Bearer free"

        t0 = time.time()
        last_error = "No hay modelos disponibles"

        for cand_model in model_candidates:
            payload = {
                "model": cand_model,
                "messages": messages,
                "temperature": temp,
                "max_tokens": max_t,
                "stream": False
            }
            try:
                with httpx.Client(timeout=timeout) as client:
                    res = client.post(url, json=payload, headers=headers)
                    elapsed = time.time() - t0

                    if res.status_code == 429:
                        last_error = f"HTTP 429 Rate limit en {cand_model}"
                        logger.warning(f"Rate limit en {p_id} ({cand_model}). Probando modelo alternativo...")
                        continue

                    if res.status_code != 200:
                        last_error = f"HTTP {res.status_code}: {res.text[:200]}"
                        logger.warning(f"Fallo en API ({p_id} - {cand_model}): {last_error}")
                        continue

                    data = res.json()
                    choice = data.get("choices", [{}])[0]
                    msg_obj = choice.get("message", {})
                    reply_text = (msg_obj.get("content") or "").strip()
                    # Soporte para modelos de razonamiento si content viene vacío
                    if not reply_text and msg_obj.get("reasoning"):
                        reply_text = msg_obj["reasoning"].strip()

                    usage = data.get("usage", {})
                    completion_tokens = usage.get("completion_tokens", len(reply_text.split()))
                    total_tokens = usage.get("total_tokens", completion_tokens)
                    tok_per_sec = round(completion_tokens / elapsed, 1) if elapsed > 0 else 0.0

                    # Actualizar métricas y auto-fijar modelo exitoso si cambió
                    with self._db_lock:
                        if self._config.get("active_model") != cand_model and not model:
                            self._config["active_model"] = cand_model
                        prev_reqs = self._config.get("total_requests", 0)
                        self._config["total_requests"] = prev_reqs + 1
                        self._config["total_tokens"] = self._config.get("total_tokens", 0) + total_tokens
                        prev_avg = self._config.get("avg_tokens_per_sec", 0.0)
                        self._config["avg_tokens_per_sec"] = ((prev_avg * prev_reqs) + tok_per_sec) / (prev_reqs + 1)
                        self._config["last_test"] = {
                            "timestamp": time.time(),
                            "ok": True,
                            "provider": p_id,
                            "model": cand_model,
                            "tokens_per_sec": tok_per_sec,
                            "elapsed_s": round(elapsed, 2),
                            "tokens": completion_tokens
                        }
                        self._save_config_unlocked()

                    return {
                        "ok": True,
                        "reply": reply_text,
                        "provider": f"{p_info.get('name')} ({p_id})",
                        "model": cand_model,
                        "elapsed_s": round(elapsed, 2),
                        "tokens": completion_tokens,
                        "tokens_per_sec": tok_per_sec,
                        "usage": usage
                    }
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Excepción en {p_id} ({cand_model}): {e}")
                continue

        elapsed = time.time() - t0
        return {
            "ok": False,
            "error": last_error,
            "provider": p_id,
            "model": target_model,
            "elapsed_s": round(elapsed, 2)
        }


def get_chinese_cloud_api() -> ChineseCloudAPI:
    return ChineseCloudAPI.get_instance()
