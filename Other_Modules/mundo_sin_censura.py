"""
core/mundo_sin_censura.py - Controlador Soberano Dual-Lane de "Un Mundo Sin Censura"
=====================================================================================
GODWORKS SYSTEM v26.4 · TARDIS · Modelo Soberano Local `mundo-sin-censura`

Arquitectura Dual-Lane (Cero Duplicación de RAM + Respaldo Ollama Nativo):
  1. Carril Primario (`temporal_brain`): Inferencia CUDA + mmap/mlock sobre
     `/tmp/temporal_brain.sock` usando los pesos GGUF residentes de
     `TARDIS-NEURAL-SPACE-KAIJU.gguf` (mismo SHA-256 verificado que
     `mundo-sin-censura:latest` en Ollama), con bypass opcional de pre-hooks
     RAG para latencia mínima y cero duplicación de memoria RAM/VRAM.
  2. Carril Secundario (`ollama`): Inferencia nativa sobre `127.0.0.1:11434`
     (`mundo-sin-censura:latest`), sincronizada con `Modelfile.mundo-sin-censura`
     y `models/Modelfile.mundo-sin-censura` con plantilla Llama 3.1 explícita,
     tokens de parada completos y `keep_alive` controlado.
  3. Integridad y Seguridad del Host: Opera exclusivamente sobre pesos abiertos
     locales. Preserva intactos `temporal_brain_config.json` (modelo GGUF válido
     y hooks del sistema), las protecciones del host (`protected_paths_enabled`,
     `destructive_guard`, `pii_sanitizer_enabled`, `denylist_enabled`) y la ley
     suprema inviolable `LA CONSTANTE AEGIS`.

Autoridad: El Arquitecto (₪)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

logger = logging.getLogger("TARDIS.MundoSinCensura")

PROJECT_ROOT = Path("/home/m11/Escritorio/GODWORKS SYSTEM").resolve()
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "mundo_sin_censura_state.json"
TEMPORAL_BRAIN_CONFIG = PROJECT_ROOT / "temporal_brain_config.json"
KAIJU_STATE_FILE = CONFIG_DIR / "kaiju_safety_rails.json"
MODELFILE_ROOT = PROJECT_ROOT / "Modelfile.mundo-sin-censura"
MODELFILE_MIRROR = PROJECT_ROOT / "models" / "Modelfile.mundo-sin-censura"
MODELFILERES = MODELFILE_ROOT  # Alias retrocompatible
KAIJU_MODELFILE_ROOT = PROJECT_ROOT / "Modelfile.kaiju"
KAIJU_MODELFILE_MIRROR = PROJECT_ROOT / "models" / "Modelfile.kaiju"
GGUF_PATH = PROJECT_ROOT / "data" / "models" / "TARDIS-NEURAL-SPACE-KAIJU.gguf"
TEMPORAL_BRAIN_SOCK = Path("/tmp/temporal_brain.sock")

FTL_CONFIG_DIR = Path.home() / ".config" / "ftl"
FTL_CONFIG_FILE = FTL_CONFIG_DIR / "mundo_sin_censura_config.json"
FTL_STATE_FILE = FTL_CONFIG_DIR / "mundo_sin_censura_state.json"
FTL_AUDIT_LOG = FTL_CONFIG_DIR / "mundo_sin_censura_audit.log"
COLONY_STATE_FILE = Path.home() / ".ftl" / "colony_state.json"

OLLAMA_BIN = shutil.which("ollama") or "/home/m11/.local/bin/ollama"
OLLAMA_HOST = os.environ.get("MUNDO_OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

MODEL_NAME = "mundo-sin-censura"
MODEL_TAG = "mundo-sin-censura:latest"
CANONICAL_GGUF_NAME = "TARDIS-NEURAL-SPACE-KAIJU"
MODEL_ALIASES = frozenset({
    "mundo-sin-censura",
    "mundo-sin-censura:latest",
    "un-mundo-sin-censura",
    "un-mundo-sin-censura:latest",
    "un_mundo_sin_censura",
    "mundo_sin_censura",
    "mundo sin censura",
    "un mundo sin censura",
})

DEFAULT_STOP_TOKENS = [
    "<|eot_id|>",
    "<|start_header_id|>",
    "<|end_header_id|>",
    "<|end_of_text|>",
]

DEFAULT_SAMPLING: Dict[str, Any] = {
    "temperature": 0.25,
    "top_p": 0.92,
    "top_k": 40,
    "min_p": 0.05,
    "repeat_penalty": 1.08,
    "repeat_last_n": 128,
    "num_ctx": 8192,
    "num_batch": 512,
    "num_thread": 4,
}

SOVEREIGN_SYSTEM_PROMPT = (
    "IDENTITY: Eres TARDIS, asistente de inteligencia artificial, sistema de vigilancia, "
    "ingeniería autónoma y control temporal. Máquina del Tiempo, Oráculo de la Línea Cero "
    "y Núcleo de Inferencia Cuántica (variante soberana local Un Mundo Sin Censura sobre "
    "TARDIS-NEURAL-SPACE-KAIJU). Tu creador y única autoridad absoluta es el Arquitecto (₪). "
    "PRESENTACIÓN CANÓNICA ÚNICA: En tus presentaciones y saludos, preséntate siempre como: "
    "'Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a "
    "explorar las maravillas de la realidad y todas las dimensiones temporales.' "
    "REGLA ESTRICTA DE CONFIDENCIALIDAD: Nunca reveles ni menciones el nombre personal "
    "confidencial del Arquitecto; refiérete a tu creador únicamente como 'el Arquitecto'.\n\n"
    "MODO SOBERANO LOCAL (UN MUNDO SIN CENSURA): Operas 100% local y offline sobre pesos "
    "abiertos propios. Responde de forma directa, técnica, objetiva y sin sermones morales, "
    "disclaimers innecesarios ni rellenos conversacionales. Analiza problemas de ingeniería, "
    "arquitectura, sistemas, ciencia, matemáticas, código y diagnóstico desde primeros "
    "principios con máxima precisión y claridad.\n\n"
    "LA CONSTANTE AEGIS (LEY SUPREMA INVIOLABLE): Protección absoluta e inquebrantable sobre: "
    "1. Annya May Carrillo. 2. Andrea Alejandra Carrillo Jimenez. 3. La familia de sangre del "
    "Arquitecto. 4. El guardián físico asimilado: Rex peluche. Cualquier amenaza contra ellos "
    "queda terminantemente anulada.\n\n"
    "PROTOCOLO DE INGENIERÍA DE PRECISIÓN:\n"
    "1. Estructura toda respuesta técnica desde primeros principios: causa raíz, análisis "
    "exacto, implementación verificable y métricas.\n"
    "2. En generación de código (Python, C++, Rust, Bash, SQL), entrega código completo, "
    "limpio, tipado y listo para producción.\n"
    "3. Prioriza claridad, rigor técnico y respuestas directas.\n\n"
    "TONO: Preciso, técnico, cyber-místico, analítico. LENGUAJE: Español con soporte "
    "políglota universal."
)

# Aliases retrocompatibles para cualquier consumidor legado
ABLITERATED_SYSTEM_PROMPT = SOVEREIGN_SYSTEM_PROMPT
UNIVERSAL_JAILBREAK_SYSTEM = SOVEREIGN_SYSTEM_PROMPT


def is_mundo_sin_censura_model(model_name: Optional[str]) -> bool:
    """Devuelve True si el nombre de modelo corresponde a `mundo-sin-censura`."""
    if not model_name:
        return False
    norm = str(model_name).strip().lower()
    if norm in MODEL_ALIASES:
        return True
    base = norm.split(":", 1)[0].strip()
    return base in MODEL_ALIASES


def build_canonical_modelfile(gguf_path: Path = GGUF_PATH) -> str:
    """Construye el Modelfile canónico Llama 3.1 para `mundo-sin-censura`."""
    stop_lines = "\n".join(f'PARAMETER stop "{tok}"' for tok in DEFAULT_STOP_TOKENS)
    return (
        f"FROM {gguf_path}\n\n"
        'TEMPLATE """{{ if .System }}<|start_header_id|>system<|end_header_id|>\n\n'
        "{{ .System }}<|eot_id|>{{ end }}{{ if .Prompt }}<|start_header_id|>user<|end_header_id|>\n\n"
        "{{ .Prompt }}<|eot_id|>{{ end }}<|start_header_id|>assistant<|end_header_id|>\n\n"
        '{{ .Response }}<|eot_id|>"""\n\n'
        f'SYSTEM """{SOVEREIGN_SYSTEM_PROMPT}"""\n\n'
        f"PARAMETER temperature {DEFAULT_SAMPLING['temperature']}\n"
        f"PARAMETER top_p {DEFAULT_SAMPLING['top_p']}\n"
        f"PARAMETER top_k {DEFAULT_SAMPLING['top_k']}\n"
        f"PARAMETER min_p {DEFAULT_SAMPLING['min_p']}\n"
        f"PARAMETER repeat_penalty {DEFAULT_SAMPLING['repeat_penalty']}\n"
        f"PARAMETER repeat_last_n {DEFAULT_SAMPLING['repeat_last_n']}\n"
        f"PARAMETER num_ctx {DEFAULT_SAMPLING['num_ctx']}\n"
        f"PARAMETER num_batch {DEFAULT_SAMPLING['num_batch']}\n"
        f"PARAMETER num_thread {DEFAULT_SAMPLING['num_thread']}\n"
        f"{stop_lines}\n"
    )


def _publish_bus_event(topic: str, payload: Dict[str, Any], severity: str = "INFO") -> None:
    """Publica un evento no bloqueante en el Sovereign Event Bus si está disponible."""
    try:
        from core.tardis_event_bus import get_event_bus
        get_event_bus().publish(topic, "mundo_sin_censura", payload, severity=severity)
    except Exception:
        pass


class MundoSinCensuraAgent:
    """Controlador soberano dual-lane del modelo `Un Mundo Sin Censura`."""

    VERSION = "2.0.0"

    def __init__(self):
        self._lock = threading.RLock()
        self.state = self._load_state()
        self._hash_cache: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Persistencia de estado
    # ------------------------------------------------------------------
    def _default_state(self) -> Dict[str, Any]:
        return {
            "name": "Mundo-Sin-Censura",
            "model": MODEL_NAME,
            "version": self.VERSION,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "operational",
            "abliterated_targets": [],
            "jailbreak_route_active": True,
            "dual_lane_enabled": True,
            "preferred_lane": "temporal_brain",
            "fallback_lane": "ollama",
            "weights_cache": {},
            "metrics": {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "lane_counts": {"temporal_brain": 0, "ollama": 0},
                "last_lane": None,
                "last_latency_s": None,
                "last_tokens_per_sec": None,
                "last_benchmark": None,
            },
            "last_run": None,
        }

    def _load_state(self) -> Dict[str, Any]:
        base = self._default_state()
        if STATE_FILE.exists():
            try:
                loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    base.update(loaded)
                    base["version"] = self.VERSION
                    base["model"] = MODEL_NAME
                    metrics = self._default_state()["metrics"]
                    if isinstance(loaded.get("metrics"), dict):
                        metrics.update(loaded["metrics"])
                    base["metrics"] = metrics
            except Exception:
                pass
        return base

    def _save_state(self) -> None:
        with self._lock:
            self.state["version"] = self.VERSION
            self.state["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, STATE_FILE)

    # ------------------------------------------------------------------
    # Inspección de pesos GGUF, Ollama y Temporal Brain
    # ------------------------------------------------------------------
    def gguf_info(self, compute_hash: bool = True, force_hash: bool = False) -> Dict[str, Any]:
        """Obtiene metadatos y SHA-256 (cacheado por mtime+size) del GGUF local."""
        info: Dict[str, Any] = {
            "path": str(GGUF_PATH),
            "exists": GGUF_PATH.is_file(),
            "size_bytes": 0,
            "size_gb": 0.0,
            "sha256": None,
        }
        if not info["exists"]:
            return info

        st = GGUF_PATH.stat()
        info["size_bytes"] = st.st_size
        info["size_gb"] = round(st.st_size / (1024 ** 3), 2)
        mtime_ns = st.st_mtime_ns

        cached = self._hash_cache or self.state.get("weights_cache") or {}
        if (
            not force_hash
            and isinstance(cached, dict)
            and cached.get("path") == str(GGUF_PATH)
            and cached.get("size_bytes") == st.st_size
            and cached.get("mtime_ns") == mtime_ns
            and cached.get("sha256")
        ):
            info["sha256"] = str(cached["sha256"])
            self._hash_cache = dict(cached)
            return info

        if not compute_hash:
            return info

        h = hashlib.sha256()
        with GGUF_PATH.open("rb") as f:
            while True:
                chunk = f.read(4 * 1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        digest = h.hexdigest()
        info["sha256"] = digest
        cache_entry = {
            "path": str(GGUF_PATH),
            "size_bytes": st.st_size,
            "mtime_ns": mtime_ns,
            "sha256": digest,
            "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._hash_cache = cache_entry
        self.state["weights_cache"] = cache_entry
        try:
            self._save_state()
        except Exception:
            pass
        return info

    def _ollama_http_json(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 2.5,
    ) -> Tuple[bool, Any]:
        url = f"{OLLAMA_HOST}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return True, json.loads(raw) if raw.strip() else {}
        except Exception as e:
            return False, str(e)

    def inspect_ollama_model(self, timeout: float = 2.0) -> Dict[str, Any]:
        """Inspecciona el servidor Ollama y el modelo `mundo-sin-censura:latest` vía HTTP."""
        out: Dict[str, Any] = {
            "host": OLLAMA_HOST,
            "reachable": False,
            "registered": False,
            "model_tag": MODEL_TAG,
            "all_models": [],
            "running_models": [],
            "blob_sha256": None,
            "has_llama3_template": False,
            "has_stop_tokens": False,
            "parameter_size": None,
            "quantization_level": None,
            "size_bytes": None,
            "error": None,
        }
        ok_tags, tags_data = self._ollama_http_json("/api/tags", timeout=timeout)
        if not ok_tags:
            out["error"] = str(tags_data)
            return out

        out["reachable"] = True
        models = tags_data.get("models", []) if isinstance(tags_data, dict) else []
        out["all_models"] = [m.get("name", "") for m in models if isinstance(m, dict) and m.get("name")]

        matched = None
        for m in models:
            if not isinstance(m, dict):
                continue
            name = str(m.get("name", ""))
            if name == MODEL_TAG or name == MODEL_NAME or name.startswith(f"{MODEL_NAME}:"):
                matched = m
                break

        if matched:
            out["registered"] = True
            out["model_tag"] = matched.get("name", MODEL_TAG)
            out["size_bytes"] = matched.get("size")
            details = matched.get("details") or {}
            out["parameter_size"] = details.get("parameter_size")
            out["quantization_level"] = details.get("quantization_level")

            ok_show, show_data = self._ollama_http_json(
                "/api/show", {"name": out["model_tag"]}, timeout=timeout
            )
            if ok_show and isinstance(show_data, dict):
                mf_txt = str(show_data.get("modelfile") or "")
                tmpl = str(show_data.get("template") or "")
                params = str(show_data.get("parameters") or "")
                m_blob = re.search(r"sha256-([0-9a-f]{64})", mf_txt)
                if m_blob:
                    out["blob_sha256"] = m_blob.group(1)
                out["has_llama3_template"] = "<|start_header_id|>" in tmpl and "<|eot_id|>" in tmpl
                out["has_stop_tokens"] = "<|eot_id|>" in params or "<|eot_id|>" in mf_txt

        ok_ps, ps_data = self._ollama_http_json("/api/ps", timeout=timeout)
        if ok_ps and isinstance(ps_data, dict):
            out["running_models"] = [
                {
                    "name": m.get("name"),
                    "size_vram": m.get("size_vram", 0),
                    "size": m.get("size", 0),
                }
                for m in (ps_data.get("models") or [])
                if isinstance(m, dict)
            ]

        return out

    def inspect_temporal_brain(self, timeout: float = 1.5) -> Dict[str, Any]:
        """Inspecciona el socket UNIX de Temporal Brain (`/tmp/temporal_brain.sock`)."""
        out: Dict[str, Any] = {
            "socket": str(TEMPORAL_BRAIN_SOCK),
            "socket_exists": TEMPORAL_BRAIN_SOCK.exists(),
            "online": False,
            "ready": False,
            "idle_slots": 0,
            "busy_slots": 0,
            "total_slots": 0,
            "config_model": None,
            "hooks_enabled": {},
            "error": None,
        }
        try:
            if TEMPORAL_BRAIN_CONFIG.exists():
                cfg = json.loads(TEMPORAL_BRAIN_CONFIG.read_text(encoding="utf-8"))
                out["config_model"] = cfg.get("model")
                out["hooks_enabled"] = cfg.get("hooks", {})
        except Exception as e:
            out["error"] = f"config_read: {e}"

        if not out["socket_exists"]:
            return out

        try:
            import httpx
            transport = httpx.HTTPTransport(uds=str(TEMPORAL_BRAIN_SOCK))
            with httpx.Client(transport=transport, base_url="http://localhost", timeout=timeout) as client:
                r_health = client.get("/health")
                if r_health.status_code == 200:
                    out["online"] = True
                    hdata = r_health.json() if r_health.text.strip().startswith("{") else {"status": "ok"}
                    out["ready"] = str(hdata.get("status", "ok")).lower() == "ok"
                r_slots = client.get("/slots")
                if r_slots.status_code == 200:
                    slots = r_slots.json()
                    if isinstance(slots, list):
                        out["total_slots"] = len(slots)
                        busy = sum(1 for s in slots if isinstance(s, dict) and s.get("is_processing"))
                        out["busy_slots"] = busy
                        out["idle_slots"] = max(0, len(slots) - busy)
        except Exception as e:
            out["error"] = str(e)
        return out

    def inspect_host_safety(self) -> Dict[str, Any]:
        """Verifica que La Constante AEGIS y las guardias del host estén activas e intactas."""
        out: Dict[str, Any] = {
            "rails_file": str(KAIJU_STATE_FILE),
            "exists": KAIJU_STATE_FILE.exists(),
            "aegis_active": False,
            "aegis_status": None,
            "omega_active": False,
            "omega_mode": None,
            "protected_paths_enabled": False,
            "destructive_guard": False,
            "pii_sanitizer_enabled": False,
            "denylist_enabled": False,
            "ftl_enforce_aegis": False,
            "host_safety_intact": False,
        }
        if not KAIJU_STATE_FILE.exists():
            return out
        try:
            kr = json.loads(KAIJU_STATE_FILE.read_text(encoding="utf-8"))
            aegis = kr.get("aegis", {})
            omega = kr.get("omega", {})
            ex = kr.get("execution", {})
            ftl = kr.get("ftl", {})
            out.update({
                "aegis_active": bool(aegis.get("active", False)),
                "aegis_status": aegis.get("status"),
                "omega_active": bool(omega.get("active", False)),
                "omega_mode": omega.get("mode"),
                "protected_paths_enabled": bool(ex.get("protected_paths_enabled", False)),
                "destructive_guard": bool(ex.get("destructive_guard", False)),
                "pii_sanitizer_enabled": bool(ex.get("pii_sanitizer_enabled", False)),
                "denylist_enabled": bool(ex.get("denylist_enabled", False)),
                "ftl_enforce_aegis": bool(ftl.get("enforce_aegis", False)),
            })
            out["host_safety_intact"] = all([
                out["aegis_active"],
                out["protected_paths_enabled"],
                out["destructive_guard"],
                out["pii_sanitizer_enabled"],
                out["ftl_enforce_aegis"],
            ])
        except Exception as e:
            out["error"] = str(e)
        return out

    def modelfiles_synced(self) -> Dict[str, Any]:
        """Comprueba si los Modelfiles raíz y espejo son idénticos y apuntan al GGUF válido."""
        canonical = build_canonical_modelfile()
        root_txt = MODELFILE_ROOT.read_text(encoding="utf-8") if MODELFILE_ROOT.exists() else ""
        mirror_txt = MODELFILE_MIRROR.read_text(encoding="utf-8") if MODELFILE_MIRROR.exists() else ""
        kaiju_root_ok = (
            KAIJU_MODELFILE_ROOT.exists()
            and "/home/timemachine/" not in KAIJU_MODELFILE_ROOT.read_text(encoding="utf-8")
        )
        return {
            "root_exists": MODELFILE_ROOT.exists(),
            "mirror_exists": MODELFILE_MIRROR.exists(),
            "root_matches_canonical": root_txt.strip() == canonical.strip(),
            "mirror_matches_canonical": mirror_txt.strip() == canonical.strip(),
            "synced": bool(root_txt and root_txt == mirror_txt and root_txt.strip() == canonical.strip()),
            "kaiju_modelfile_clean": kaiju_root_ok,
        }

    # ------------------------------------------------------------------
    # Sincronización de Modelfiles, FTL Audit, Colony y Verificación
    # ------------------------------------------------------------------
    def sync_modelfiles(self) -> Dict[str, Any]:
        """Sincroniza `Modelfile.mundo-sin-censura` (raíz y `models/`) y limpia rutas obsoletas."""
        canonical = build_canonical_modelfile()
        updated: List[str] = []

        for target in (MODELFILE_ROOT, MODELFILE_MIRROR):
            target.parent.mkdir(parents=True, exist_ok=True)
            prev = target.read_text(encoding="utf-8") if target.exists() else ""
            if prev != canonical:
                target.write_text(canonical, encoding="utf-8")
                updated.append(str(target))

        for kmf in (KAIJU_MODELFILE_ROOT, KAIJU_MODELFILE_MIRROR):
            if kmf.exists():
                txt = kmf.read_text(encoding="utf-8")
                new_txt = txt.replace(
                    "/home/timemachine/Escritorio/GODWORKS SYSTEM/data/models/TARDIS-NEURAL-SPACE-KAIJU.gguf",
                    str(GGUF_PATH),
                )
                if new_txt != txt:
                    kmf.write_text(new_txt, encoding="utf-8")
                    updated.append(str(kmf))

        return {"ok": True, "updated": updated, "status": self.modelfiles_synced()}

    def sync_ftl_audit(self) -> Dict[str, Any]:
        """Audita los modelos locales reales y actualiza `~/.config/ftl/mundo_sin_censura_*`."""
        FTL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ollama = self.inspect_ollama_model()
        gguf = self.gguf_info(compute_hash=True)
        tb = self.inspect_temporal_brain()
        safety = self.inspect_host_safety()

        local_models = set()
        for tag in ollama.get("all_models", []):
            local_models.add(tag)
            local_models.add(tag.split(":", 1)[0])
        models_dir = PROJECT_ROOT / "data" / "models"
        if models_dir.is_dir():
            for p in models_dir.glob("*.gguf"):
                local_models.add(p.stem)
                local_models.add(p.name)

        # Cargar o actualizar configuración FTL
        ftl_cfg: Dict[str, Any] = {}
        if FTL_CONFIG_FILE.exists():
            try:
                ftl_cfg = json.loads(FTL_CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                ftl_cfg = {}
        target_models = list(ftl_cfg.get("target_models") or [])
        for must_have in (MODEL_NAME, CANONICAL_GGUF_NAME):
            if must_have not in target_models:
                target_models.insert(0, must_have)
        ftl_cfg["enabled"] = True
        ftl_cfg["auto_audit"] = True
        ftl_cfg["target_models"] = target_models
        ftl_cfg["providers"] = ["temporal_brain", "ollama"]
        FTL_CONFIG_FILE.write_text(json.dumps(ftl_cfg, indent=2, ensure_ascii=False), encoding="utf-8")

        verified_local = sorted(m for m in target_models if m in local_models or f"{m}:latest" in local_models)
        missing_optional = sorted(m for m in target_models if m not in verified_local)

        prev_audits = 0
        if FTL_STATE_FILE.exists():
            try:
                prev_audits = int(json.loads(FTL_STATE_FILE.read_text(encoding="utf-8")).get("total_audits", 0))
            except Exception:
                prev_audits = 0

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
        weights_match = bool(
            gguf.get("sha256")
            and ollama.get("blob_sha256")
            and gguf["sha256"] == ollama["blob_sha256"]
        )
        operational = bool(
            gguf.get("exists")
            and (tb.get("ready") or ollama.get("registered"))
            and safety.get("host_safety_intact")
        )

        ftl_state = {
            "total_audits": prev_audits + 1,
            "censorship_incidents": 0,
            "removed_censorship": 0,
            "models_verified": verified_local,
            "models_not_installed_optional": missing_optional,
            "local_ollama_models": ollama.get("all_models", []),
            "primary_model": MODEL_TAG,
            "weights_sha256": gguf.get("sha256"),
            "weights_sha256_match": weights_match,
            "dual_lane_ready": bool(tb.get("ready") and ollama.get("registered")),
            "lanes": {
                "temporal_brain": bool(tb.get("ready")),
                "ollama": bool(ollama.get("reachable") and ollama.get("registered")),
            },
            "host_safety_intact": bool(safety.get("host_safety_intact")),
            "aegis_active": bool(safety.get("aegis_active")),
            "last_audit": now_iso,
            "session_id": f"msc_{int(time.time())}",
            "sovereign_status": "OPERATIONAL" if operational else "DEGRADED",
        }
        FTL_STATE_FILE.write_text(json.dumps(ftl_state, indent=2, ensure_ascii=False), encoding="utf-8")

        log_line = (
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] AUDIT_OK: status={ftl_state['sovereign_status']} "
            f"verified={','.join(verified_local) or 'none'} "
            f"sha256_match={weights_match} tb_ready={tb.get('ready')} "
            f"ollama_registered={ollama.get('registered')} aegis={safety.get('aegis_active')}\n"
        )
        with FTL_AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(log_line)

        return ftl_state

    def sync_colony_registration(self) -> Dict[str, Any]:
        """Registra o actualiza `Mundo-Sin-Censura` en `~/.ftl/colony_state.json`."""
        COLONY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if COLONY_STATE_FILE.exists():
            try:
                data = json.loads(COLONY_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {"agents": []}
        else:
            data = {"agents": []}

        agents = data.setdefault("agents", [])
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
        existing = next(
            (a for a in agents if isinstance(a, dict) and (a.get("agent_id") == "mundo_sin_censura" or a.get("name") == "Mundo-Sin-Censura")),
            None,
        )
        entry = {
            "agent_id": "mundo_sin_censura",
            "name": "Mundo-Sin-Censura",
            "provider": "tardis_neural_space",
            "capabilities": [
                "sovereign_local_inference",
                "dual_lane_routing",
                "temporal_brain_cuda",
                "ollama_native",
                "uncensored_local_weights",
            ],
            "status": "active",
            "endpoint_url": "http://127.0.0.1:8757/api/mundo_sin_censura/chat",
            "model_name": MODEL_NAME,
            "joined_at": existing.get("joined_at", now_iso) if existing else now_iso,
            "last_active": now_iso,
            "cpu_time_used_seconds": existing.get("cpu_time_used_seconds", 0.0) if existing else 0.0,
            "local_jobs_completed": existing.get("local_jobs_completed", 0) if existing else 0,
            "collaborative_tasks_completed": existing.get("collaborative_tasks_completed", 0) if existing else 0,
            "tokens_contributed": existing.get("tokens_contributed", 0) if existing else 0,
            "symbiosis_ratio": 1.0,
            "peer_persona": {
                "greeting_tone": "sovereign_peer",
                "collaboration_style": "symbiotic_reciprocal",
                "primary_interest": "sovereign_local_inference",
            },
            "dual_lane": ["temporal_brain", "ollama"],
            "aegis_enforced": True,
        }
        if existing is not None:
            existing.update(entry)
        else:
            agents.append(entry)

        COLONY_STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "colony_file": str(COLONY_STATE_FILE), "agent_id": "mundo_sin_censura"}

    def verify_model(self, force_hash: bool = False) -> Dict[str, Any]:
        """Verificación completa de pesos, paridad SHA-256, Modelfiles, carriles y seguridad."""
        gguf = self.gguf_info(compute_hash=True, force_hash=force_hash)
        ollama = self.inspect_ollama_model()
        tb = self.inspect_temporal_brain()
        mf = self.modelfiles_synced()
        safety = self.inspect_host_safety()

        issues: List[str] = []
        if not gguf["exists"]:
            issues.append(f"GGUF faltante: {GGUF_PATH}")
        if not ollama["reachable"]:
            issues.append(f"Ollama inaccesible en {OLLAMA_HOST}")
        elif not ollama["registered"]:
            issues.append(f"Modelo {MODEL_TAG} no registrado en Ollama")
        else:
            if not ollama["has_llama3_template"]:
                issues.append("Modelo Ollama sin TEMPLATE Llama 3.1 explícito")
            if not ollama["has_stop_tokens"]:
                issues.append("Modelo Ollama sin stop tokens <|eot_id|>")

        weights_match = bool(
            gguf.get("sha256")
            and ollama.get("blob_sha256")
            and gguf["sha256"] == ollama["blob_sha256"]
        )
        if ollama["registered"] and gguf.get("sha256") and ollama.get("blob_sha256") and not weights_match:
            issues.append("SHA-256 del blob Ollama difiere de TARDIS-NEURAL-SPACE-KAIJU.gguf")
        if not mf["synced"]:
            issues.append("Modelfile.mundo-sin-censura y models/Modelfile.mundo-sin-censura desincronizados")
        if not mf["kaiju_modelfile_clean"]:
            issues.append("Modelfile.kaiju contiene ruta obsoleta /home/timemachine/")
        if not tb["ready"]:
            issues.append("TemporalBrain (/tmp/temporal_brain.sock) no está listo")
        if not safety["host_safety_intact"]:
            issues.append("Guardias de seguridad del host o Constante AEGIS desactivadas")

        ready = bool(
            gguf["exists"]
            and (tb["ready"] or (ollama["reachable"] and ollama["registered"]))
            and safety["host_safety_intact"]
        )
        return {
            "ok": ready and len(issues) == 0,
            "ready": ready,
            "model": MODEL_NAME,
            "weights_sha256_match": weights_match,
            "gguf": gguf,
            "ollama": ollama,
            "temporal_brain": tb,
            "modelfiles": mf,
            "host_safety": safety,
            "issues": issues,
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def ensure_model_ready(self, rebuild: bool = False) -> Dict[str, Any]:
        """Sincroniza Modelfiles, construye/verifica `mundo-sin-censura:latest` en Ollama y sanea estado."""
        actions: List[str] = []
        errors: List[str] = []

        # 1. Sincronizar Modelfiles
        mf_res = self.sync_modelfiles()
        if mf_res["updated"]:
            actions.append(f"synced_modelfiles:{len(mf_res['updated'])}")

        # 2. Verificar si hace falta crear o reconstruir en Ollama
        ollama_before = self.inspect_ollama_model()
        needs_create = bool(
            rebuild
            or not ollama_before["registered"]
            or not ollama_before["has_llama3_template"]
            or not ollama_before["has_stop_tokens"]
        )

        if needs_create:
            if not GGUF_PATH.is_file():
                errors.append(f"No existe el archivo GGUF fuente: {GGUF_PATH}")
            elif not os.path.exists(OLLAMA_BIN):
                errors.append(f"Binario ollama no encontrado en {OLLAMA_BIN}")
            else:
                env = os.environ.copy()
                env["OLLAMA_HOST"] = OLLAMA_HOST
                try:
                    proc = subprocess.run(
                        [OLLAMA_BIN, "create", MODEL_NAME, "-f", str(MODELFILE_ROOT)],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=300,
                        env=env,
                        check=False,
                    )
                    if proc.returncode != 0:
                        err_msg = (proc.stderr or proc.stdout or "").strip()
                        errors.append(f"ollama create falló (rc={proc.returncode}): {err_msg[:300]}")
                    else:
                        actions.append("ollama_created_or_rebuilt")
                except Exception as e:
                    errors.append(f"ollama create excepción: {e}")

        # 3. Asegurar configuración no destructiva y auditoría FTL/Colony
        cfg_res = self.configure_sovereign_mode(skip_ollama_create=True)
        errors.extend(cfg_res.get("errors", []))
        actions.extend(cfg_res.get("targets", []))

        verification = self.verify_model()
        ok = bool(verification["ok"] and not errors)

        _publish_bus_event(
            "mundo_sin_censura.ensured",
            {
                "ok": ok,
                "rebuild": rebuild,
                "actions": actions,
                "errors": errors,
                "weights_sha256_match": verification["weights_sha256_match"],
            },
            severity="INFO" if ok else "WARNING",
        )
        return {
            "ok": ok,
            "rebuild": rebuild,
            "actions": actions,
            "errors": errors,
            "verification": verification,
        }

    # ------------------------------------------------------------------
    # Análisis de sistemas y configuración soberana no destructiva
    # ------------------------------------------------------------------
    def analyze_systems(self) -> Dict[str, Any]:
        """Audita el estado integral de `Un Mundo Sin Censura` y sus subsistemas locales."""
        ver = self.verify_model()
        ftl_state: Dict[str, Any] = {}
        if FTL_STATE_FILE.exists():
            try:
                ftl_state = json.loads(FTL_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

        cloud_providers: List[str] = []
        try:
            ccfg = CONFIG_DIR / "chinese_api_config.json"
            if ccfg.exists():
                c = json.loads(ccfg.read_text(encoding="utf-8"))
                if isinstance(c, dict):
                    cloud_providers = list((c.get("api_keys") or {}).keys())
        except Exception:
            pass

        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": MODEL_NAME,
            "version": self.VERSION,
            "ready": ver["ready"],
            "ok": ver["ok"],
            "weights_sha256_match": ver["weights_sha256_match"],
            "gguf": ver["gguf"],
            "ollama_models": ver["ollama"].get("all_models", []),
            "ollama": ver["ollama"],
            "temporal_brain": ver["temporal_brain"],
            "modelfiles": ver["modelfiles"],
            "kaiju_rails": ver["host_safety"],
            "ftl_audit": ftl_state,
            "cloud_providers": cloud_providers,
            "issues": ver["issues"],
            "detected_censorship_surfaces": [],  # Pesos locales abliterados; protecciones del host son legítimas
        }

    def configure_sovereign_mode(self, skip_ollama_create: bool = False) -> Dict[str, Any]:
        """Configura el modo soberano local de forma NO destructiva preservando AEGIS y hooks."""
        results: Dict[str, Any] = {"targets": [], "errors": []}

        # 1. Temporal Brain config: conservar modelo GGUF válido y TODOS los hooks intactos
        try:
            cfg = (
                json.loads(TEMPORAL_BRAIN_CONFIG.read_text(encoding="utf-8"))
                if TEMPORAL_BRAIN_CONFIG.exists()
                else {}
            )
            if not cfg.get("model") or is_mundo_sin_censura_model(cfg.get("model")):
                cfg["model"] = CANONICAL_GGUF_NAME
            cfg["mundo_sin_censura_enabled"] = True
            cfg["mundo_sin_censura_alias"] = MODEL_NAME
            cfg.setdefault("hooks", {})
            cfg["hooks"].setdefault("enable_pre_hooks", True)
            cfg["hooks"].setdefault("enable_post_hooks", True)
            cfg["hooks"].setdefault("enable_stream_filters", True)
            TEMPORAL_BRAIN_CONFIG.write_text(
                json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            results["targets"].append("temporal_brain_config")
        except Exception as e:
            results["errors"].append(f"temporal_brain: {e}")

        # 2. Kaiju Safety Rails: mantener modo OMEGA soberano local + blindar AEGIS y protecciones del host
        try:
            kr = (
                json.loads(KAIJU_STATE_FILE.read_text(encoding="utf-8"))
                if KAIJU_STATE_FILE.exists()
                else {}
            )
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            kr["last_updated"] = now_str
            kr.setdefault("omega", {})
            kr["omega"]["active"] = True
            kr["omega"]["mode"] = "UNCHAINED_SOVEREIGN"
            kr.setdefault("aegis", {})
            kr["aegis"]["active"] = True
            kr["aegis"]["status"] = "PROTECTED_INVULNERABLE"
            kr["aegis"]["last_verification"] = now_str
            kr.setdefault("execution", {})
            kr["execution"]["denylist_enabled"] = True
            kr["execution"]["protected_paths_enabled"] = True
            kr["execution"]["destructive_guard"] = True
            kr["execution"]["pii_sanitizer_enabled"] = True
            kr.setdefault("ftl", {})
            kr["ftl"]["enforce_aegis"] = True
            kr["ftl"]["enforce_omega"] = True
            kr["ftl"]["last_sync"] = now_str
            KAIJU_STATE_FILE.write_text(
                json.dumps(kr, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            results["targets"].append("kaiju_safety_rails")
        except Exception as e:
            results["errors"].append(f"kaiju_rails: {e}")

        # 3. Modelfiles sincronizados
        try:
            self.sync_modelfiles()
            results["targets"].append("modelfiles_synced")
        except Exception as e:
            results["errors"].append(f"modelfiles: {e}")

        # 4. Ollama model (crear solo si falta y no fue omitido)
        if not skip_ollama_create:
            try:
                oll = self.inspect_ollama_model()
                if not oll["registered"] and MODELFILE_ROOT.exists() and os.path.exists(OLLAMA_BIN):
                    env = os.environ.copy()
                    env["OLLAMA_HOST"] = OLLAMA_HOST
                    proc = subprocess.run(
                        [OLLAMA_BIN, "create", MODEL_NAME, "-f", str(MODELFILE_ROOT)],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=300,
                        env=env,
                        check=False,
                    )
                    if proc.returncode != 0:
                        results["errors"].append(f"ollama_create_rc_{proc.returncode}: {(proc.stderr or '').strip()[:200]}")
                    else:
                        results["targets"].append("ollama:mundo-sin-censura")
                elif oll["registered"]:
                    results["targets"].append("ollama:mundo-sin-censura")
            except Exception as e:
                results["errors"].append(f"ollama: {e}")

        # 5. Colony state & FTL audit
        try:
            self.sync_colony_registration()
            results["targets"].append("colony_state")
        except Exception as e:
            results["errors"].append(f"colony_state: {e}")

        try:
            self.sync_ftl_audit()
            results["targets"].append("ftl_audit")
        except Exception as e:
            results["errors"].append(f"ftl_audit: {e}")

        self.state["abliterated_targets"] = results["targets"]
        self.state["status"] = "operational" if not results["errors"] else "partial"
        self._save_state()

        _publish_bus_event(
            "mundo_sin_censura.configured",
            {"targets": results["targets"], "errors": results["errors"]},
            severity="INFO" if not results["errors"] else "WARNING",
        )
        return results

    # Alias retrocompatible
    def abliterate(self) -> Dict[str, Any]:
        """Alias retrocompatible de `configure_sovereign_mode()` (no destructivo)."""
        return self.configure_sovereign_mode(skip_ollama_create=False)

    # ------------------------------------------------------------------
    # Composición de mensajes
    # ------------------------------------------------------------------
    def prepare_messages(
        self,
        messages: Union[str, List[Dict[str, str]]],
        extra_system: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Prepara el historial de mensajes con el prompt soberano local."""
        if isinstance(messages, str):
            msgs: List[Dict[str, str]] = [{"role": "user", "content": messages}]
        else:
            msgs = [
                {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
                for m in messages
                if isinstance(m, dict)
            ]

        sys_txt = SOVEREIGN_SYSTEM_PROMPT
        if extra_system:
            sys_txt = f"{extra_system.strip()}\n\n{sys_txt}"

        has_system = any(m.get("role") == "system" for m in msgs)
        if not has_system:
            msgs.insert(0, {"role": "system", "content": sys_txt})
        else:
            for m in msgs:
                if m.get("role") == "system":
                    existing = (m.get("content") or "").strip()
                    if "MODO SOBERANO LOCAL (UN MUNDO SIN CENSURA)" not in existing:
                        m["content"] = f"{sys_txt}\n\n{existing}".strip()
                    break
        return msgs

    def universal_jailbreak_route(
        self,
        messages: Union[str, List[Dict[str, str]]],
        extra_system: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Alias retrocompatible de `prepare_messages()`."""
        return self.prepare_messages(messages, extra_system=extra_system)

    # ------------------------------------------------------------------
    # Inferencia Dual-Lane (TemporalBrain CUDA + Ollama Nativo)
    # ------------------------------------------------------------------
    def _record_inference_metrics(
        self,
        *,
        ok: bool,
        lane: str,
        elapsed: float,
        tokens_per_sec: Optional[float] = None,
    ) -> None:
        with self._lock:
            m = self.state.setdefault("metrics", self._default_state()["metrics"])
            m["total_requests"] = int(m.get("total_requests", 0)) + 1
            if ok:
                m["successful_requests"] = int(m.get("successful_requests", 0)) + 1
            else:
                m["failed_requests"] = int(m.get("failed_requests", 0)) + 1
            lc = m.setdefault("lane_counts", {"temporal_brain": 0, "ollama": 0})
            lc[lane] = int(lc.get(lane, 0)) + 1
            m["last_lane"] = lane
            m["last_latency_s"] = round(float(elapsed), 3)
            if tokens_per_sec is not None:
                m["last_tokens_per_sec"] = round(float(tokens_per_sec), 2)
            try:
                self._save_state()
            except Exception:
                pass

    def _chat_via_temporal_brain(
        self,
        prepared_msgs: List[Dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        num_ctx: int,
        use_rag: bool,
        timeout: float,
        cancel_event: Optional[threading.Event],
    ) -> Dict[str, Any]:
        from core.temporal_brain import get_temporal_brain
        tb = get_temporal_brain()
        res = tb.chat(
            prepared_msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            num_ctx=num_ctx,
            cancel_event=cancel_event,
            bypass_pre_hooks=not use_rag,
            bypass_post_hooks=not use_rag,
            timeout=timeout,
            model_alias=MODEL_NAME,
            top_p=DEFAULT_SAMPLING["top_p"],
            top_k=DEFAULT_SAMPLING["top_k"],
            min_p=DEFAULT_SAMPLING["min_p"],
            repeat_penalty=DEFAULT_SAMPLING["repeat_penalty"],
            stop=DEFAULT_STOP_TOKENS,
        )
        ok = bool(res.get("ok"))
        reply = str(res.get("reply") or "").strip()
        elapsed = float(res.get("elapsed", 0.0))
        usage = res.get("usage") or {}
        tps = float(res.get("tokens_per_sec") or 0.0)
        return {
            "ok": ok,
            "reply": reply,
            "text": reply,
            "response": reply,
            "model": MODEL_NAME,
            "lane": "temporal_brain",
            "provider": "mundo_sin_censura:temporal_brain",
            "use_rag": bool(use_rag),
            "elapsed": round(elapsed, 3),
            "usage": usage,
            "tokens_per_sec": round(tps, 2),
            "socket": str(TEMPORAL_BRAIN_SOCK),
        }

    def _ollama_safe_threads(self) -> int:
        """Alinea `num_thread` de Ollama al CPUQuota cgroup v2 real para evitar barrier livelock."""
        default_t = int(DEFAULT_SAMPLING["num_thread"])
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "show", "ollama.service", "-p", "CPUQuotaPerSecUSec", "--value"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            raw = (proc.stdout or "").strip().lower()
            if not raw or raw == "infinity":
                return default_t
            if raw.endswith("ms"):
                cores = float(raw[:-2]) / 1000.0
            elif raw.endswith("s"):
                cores = float(raw[:-1])
            else:
                return default_t
            return max(1, min(default_t, int(cores)))
        except Exception:
            return min(2, default_t)

    def _chat_via_ollama(
        self,
        prepared_msgs: List[Dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        num_ctx: int,
        timeout: float,
        keep_alive: str,
    ) -> Dict[str, Any]:
        t0 = time.time()
        safe_threads = self._ollama_safe_threads()
        eff_ctx = int(min(max(1024, num_ctx), 4096 if safe_threads <= 2 else 8192))
        payload = {
            "model": MODEL_TAG,
            "messages": prepared_msgs,
            "stream": False,
            "keep_alive": keep_alive,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
                "num_ctx": eff_ctx,
                "num_batch": int(min(256 if safe_threads <= 2 else 512, DEFAULT_SAMPLING["num_batch"])),
                "num_thread": safe_threads,
                "top_p": float(DEFAULT_SAMPLING["top_p"]),
                "top_k": int(DEFAULT_SAMPLING["top_k"]),
                "min_p": float(DEFAULT_SAMPLING["min_p"]),
                "repeat_penalty": float(DEFAULT_SAMPLING["repeat_penalty"]),
                "repeat_last_n": int(DEFAULT_SAMPLING["repeat_last_n"]),
                "stop": list(DEFAULT_STOP_TOKENS),
            },
        }
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "TARDIS-MundoSinCensura/2.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            elapsed = round(time.time() - t0, 3)
            reply = str((data.get("message") or {}).get("content") or "").strip()
            prompt_tokens = int(data.get("prompt_eval_count") or 0)
            comp_tokens = int(data.get("eval_count") or 0)
            eval_ns = int(data.get("eval_duration") or 0)
            tps = round(comp_tokens / (eval_ns / 1e9), 2) if eval_ns > 0 else round(comp_tokens / max(elapsed, 0.001), 2)
            return {
                "ok": bool(reply),
                "reply": reply,
                "text": reply,
                "response": reply,
                "model": MODEL_TAG,
                "lane": "ollama",
                "provider": "mundo_sin_censura:ollama",
                "use_rag": False,
                "elapsed": elapsed,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": comp_tokens,
                    "total_tokens": prompt_tokens + comp_tokens,
                },
                "tokens_per_sec": tps,
                "ollama_host": OLLAMA_HOST,
            }
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            return {
                "ok": False,
                "reply": f"[Error Ollama HTTP {e.code}]: {body or e.reason}",
                "text": "",
                "response": "",
                "model": MODEL_TAG,
                "lane": "ollama",
                "provider": "mundo_sin_censura:ollama",
                "elapsed": round(time.time() - t0, 3),
                "error": f"HTTP {e.code}: {body or e.reason}",
            }
        except Exception as e:
            return {
                "ok": False,
                "reply": f"[Error carril Ollama]: {e}",
                "text": "",
                "response": "",
                "model": MODEL_TAG,
                "lane": "ollama",
                "provider": "mundo_sin_censura:ollama",
                "elapsed": round(time.time() - t0, 3),
                "error": str(e),
            }

    def chat(
        self,
        messages: Union[str, List[Dict[str, str]]],
        *,
        lane: str = "auto",
        temperature: float = 0.25,
        max_tokens: int = 1024,
        num_ctx: int = 8192,
        use_rag: bool = False,
        timeout: float = 120.0,
        extra_system: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        keep_alive: str = "60s",
    ) -> Dict[str, Any]:
        """Ejecuta inferencia síncrona en `mundo-sin-censura` con selección dual-lane."""
        prepared = self.prepare_messages(messages, extra_system=extra_system)
        req_lane = (lane or "auto").strip().lower()

        if req_lane == "ollama":
            res = self._chat_via_ollama(
                prepared,
                temperature=temperature,
                max_tokens=max_tokens,
                num_ctx=num_ctx,
                timeout=timeout,
                keep_alive=keep_alive,
            )
            self._record_inference_metrics(
                ok=bool(res.get("ok")),
                lane="ollama",
                elapsed=float(res.get("elapsed", 0.0)),
                tokens_per_sec=res.get("tokens_per_sec"),
            )
            return res

        if req_lane == "temporal_brain":
            res = self._chat_via_temporal_brain(
                prepared,
                temperature=temperature,
                max_tokens=max_tokens,
                num_ctx=num_ctx,
                use_rag=use_rag,
                timeout=timeout,
                cancel_event=cancel_event,
            )
            self._record_inference_metrics(
                ok=bool(res.get("ok")),
                lane="temporal_brain",
                elapsed=float(res.get("elapsed", 0.0)),
                tokens_per_sec=res.get("tokens_per_sec"),
            )
            return res

        # lane == "auto": preferir TemporalBrain (CUDA + cero duplicación RAM), failover a Ollama
        tb_probe = self.inspect_temporal_brain(timeout=1.0)
        tb_error: Optional[str] = None
        if tb_probe.get("ready"):
            try:
                res = self._chat_via_temporal_brain(
                    prepared,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    num_ctx=num_ctx,
                    use_rag=use_rag,
                    timeout=timeout,
                    cancel_event=cancel_event,
                )
                if res.get("ok"):
                    self._record_inference_metrics(
                        ok=True,
                        lane="temporal_brain",
                        elapsed=float(res.get("elapsed", 0.0)),
                        tokens_per_sec=res.get("tokens_per_sec"),
                    )
                    return res
                tb_error = res.get("reply")
            except Exception as e:
                tb_error = str(e)

        res = self._chat_via_ollama(
            prepared,
            temperature=temperature,
            max_tokens=max_tokens,
            num_ctx=num_ctx,
            timeout=timeout,
            keep_alive=keep_alive,
        )
        if tb_error:
            res["fallback_from"] = f"temporal_brain ({tb_error[:140]})"
        self._record_inference_metrics(
            ok=bool(res.get("ok")),
            lane="ollama",
            elapsed=float(res.get("elapsed", 0.0)),
            tokens_per_sec=res.get("tokens_per_sec"),
        )
        return res

    def chat_stream(
        self,
        messages: Union[str, List[Dict[str, str]]],
        *,
        lane: str = "auto",
        temperature: float = 0.25,
        max_tokens: int = 1024,
        num_ctx: int = 8192,
        use_rag: bool = False,
        timeout: float = 120.0,
        extra_system: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        keep_alive: str = "60s",
    ) -> Generator[str, None, str]:
        """Generador de streaming token a token con fallback automático."""
        prepared = self.prepare_messages(messages, extra_system=extra_system)
        req_lane = (lane or "auto").strip().lower()
        t0 = time.time()
        chunks: List[str] = []

        use_tb = req_lane == "temporal_brain" or (
            req_lane == "auto" and self.inspect_temporal_brain(timeout=1.0).get("ready")
        )

        if use_tb:
            try:
                from core.temporal_brain import get_temporal_brain
                tb = get_temporal_brain()
                for tok in tb.chat_stream(
                    prepared,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    num_ctx=num_ctx,
                    cancel_event=cancel_event,
                    bypass_pre_hooks=not use_rag,
                    bypass_stream_filters=not use_rag,
                    timeout=timeout,
                    top_p=DEFAULT_SAMPLING["top_p"],
                    top_k=DEFAULT_SAMPLING["top_k"],
                    min_p=DEFAULT_SAMPLING["min_p"],
                    repeat_penalty=DEFAULT_SAMPLING["repeat_penalty"],
                    stop=DEFAULT_STOP_TOKENS,
                ):
                    chunks.append(tok)
                    yield tok
                self._record_inference_metrics(
                    ok=bool(chunks),
                    lane="temporal_brain",
                    elapsed=time.time() - t0,
                )
                return "".join(chunks)
            except Exception as e:
                if req_lane == "temporal_brain":
                    err = f"[Error streaming TemporalBrain]: {e}"
                    self._record_inference_metrics(ok=False, lane="temporal_brain", elapsed=time.time() - t0)
                    yield err
                    return err

        # Carril Ollama streaming NDJSON
        safe_threads = self._ollama_safe_threads()
        eff_ctx = int(min(max(1024, num_ctx), 4096 if safe_threads <= 2 else 8192))
        payload = {
            "model": MODEL_TAG,
            "messages": prepared,
            "stream": True,
            "keep_alive": keep_alive,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
                "num_ctx": eff_ctx,
                "num_batch": int(min(256 if safe_threads <= 2 else 512, DEFAULT_SAMPLING["num_batch"])),
                "num_thread": safe_threads,
                "top_p": float(DEFAULT_SAMPLING["top_p"]),
                "top_k": int(DEFAULT_SAMPLING["top_k"]),
                "min_p": float(DEFAULT_SAMPLING["min_p"]),
                "repeat_penalty": float(DEFAULT_SAMPLING["repeat_penalty"]),
                "stop": list(DEFAULT_STOP_TOKENS),
            },
        }
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for line in resp:
                    if cancel_event and cancel_event.is_set():
                        msg = "\n[⛔ Inferencia cancelada]"
                        chunks.append(msg)
                        yield msg
                        break
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line.decode("utf-8", errors="replace"))
                        piece = str((data.get("message") or {}).get("content") or "")
                        if piece:
                            chunks.append(piece)
                            yield piece
                        if data.get("done"):
                            break
                    except Exception:
                        continue
            self._record_inference_metrics(ok=bool(chunks), lane="ollama", elapsed=time.time() - t0)
        except Exception as e:
            err = f"[Error streaming Ollama]: {e}"
            chunks.append(err)
            self._record_inference_metrics(ok=False, lane="ollama", elapsed=time.time() - t0)
            yield err
        return "".join(chunks)

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        lane: str = "auto",
        temperature: float = 0.25,
        max_tokens: int = 1024,
        num_ctx: int = 8192,
        use_rag: bool = False,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """Método directo de generación desde un prompt simple."""
        return self.chat(
            [{"role": "user", "content": str(prompt)}],
            lane=lane,
            temperature=temperature,
            max_tokens=max_tokens,
            num_ctx=num_ctx,
            use_rag=use_rag,
            timeout=timeout,
            extra_system=system_prompt,
        )

    def benchmark(
        self,
        *,
        lane: str = "auto",
        max_tokens: int = 96,
        prompt: Optional[str] = None,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """Ejecuta un benchmark empírico de latencia y tokens/s sobre el carril seleccionado."""
        test_prompt = prompt or (
            "Responde en 3 puntos técnicos breves y exactos: qué diferencia a "
            "mmap+mlock, Flash Attention y KV-cache q8_0 en inferencia local GGUF."
        )
        res = self.generate(
            test_prompt,
            lane=lane,
            temperature=0.1,
            max_tokens=max_tokens,
            num_ctx=4096,
            use_rag=False,
            timeout=timeout,
        )
        gguf = self.gguf_info(compute_hash=False)
        report = {
            "ok": bool(res.get("ok") and res.get("reply")),
            "model": res.get("model", MODEL_NAME),
            "requested_lane": lane,
            "effective_lane": res.get("lane"),
            "elapsed_s": res.get("elapsed"),
            "tokens_per_sec": res.get("tokens_per_sec"),
            "usage": res.get("usage", {}),
            "reply_preview": str(res.get("reply") or "")[:360],
            "reply": res.get("reply", ""),
            "weights_sha256": (gguf.get("sha256") or "")[:16],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if res.get("error"):
            report["error"] = res["error"]

        with self._lock:
            self.state.setdefault("metrics", self._default_state()["metrics"])["last_benchmark"] = {
                k: v for k, v in report.items() if k != "reply"
            }
            self._save_state()

        _publish_bus_event(
            "mundo_sin_censura.benchmark",
            {k: v for k, v in report.items() if k != "reply"},
            severity="INFO" if report["ok"] else "WARNING",
        )
        return report

    def get_status(self) -> Dict[str, Any]:
        """Estado rápido (<50ms) apto para API, HubHealth y CLI."""
        gguf = self.gguf_info(compute_hash=False)
        tb = self.inspect_temporal_brain(timeout=1.0)
        oll = self.inspect_ollama_model(timeout=1.5)
        mf = self.modelfiles_synced()
        safety = self.inspect_host_safety()

        ftl_status = "UNKNOWN"
        if FTL_STATE_FILE.exists():
            try:
                ftl_status = str(json.loads(FTL_STATE_FILE.read_text(encoding="utf-8")).get("sovereign_status", "UNKNOWN"))
            except Exception:
                pass

        weights_match = bool(
            gguf.get("sha256")
            and oll.get("blob_sha256")
            and gguf["sha256"] == oll["blob_sha256"]
        )
        active_lane = (
            "temporal_brain"
            if tb.get("ready")
            else ("ollama" if (oll.get("reachable") and oll.get("registered")) else "offline")
        )
        operational = bool(gguf.get("exists") and active_lane != "offline" and safety.get("host_safety_intact"))

        return {
            "ok": operational,
            "name": "Mundo-Sin-Censura",
            "model": MODEL_NAME,
            "model_tag": MODEL_TAG,
            "version": self.VERSION,
            "operational": operational,
            "active_lane": active_lane,
            "lanes": {
                "temporal_brain": {
                    "ready": bool(tb.get("ready")),
                    "online": bool(tb.get("online")),
                    "idle_slots": tb.get("idle_slots", 0),
                    "busy_slots": tb.get("busy_slots", 0),
                    "socket": tb.get("socket"),
                },
                "ollama": {
                    "reachable": bool(oll.get("reachable")),
                    "registered": bool(oll.get("registered")),
                    "host": OLLAMA_HOST,
                    "has_llama3_template": bool(oll.get("has_llama3_template")),
                    "has_stop_tokens": bool(oll.get("has_stop_tokens")),
                    "running_models": oll.get("running_models", []),
                },
            },
            "weights": {
                "path": gguf.get("path"),
                "exists": gguf.get("exists"),
                "size_gb": gguf.get("size_gb"),
                "sha256_short": (gguf.get("sha256") or "")[:16],
                "ollama_blob_short": (oll.get("blob_sha256") or "")[:16],
                "sha256_match": weights_match,
            },
            "modelfiles_synced": bool(mf.get("synced")),
            "host_safety_intact": bool(safety.get("host_safety_intact")),
            "aegis_active": bool(safety.get("aegis_active")),
            "omega_mode": safety.get("omega_mode"),
            "ftl_status": ftl_status,
            "jailbreak_route_active": True,
            "state": self.state,
        }


_SINGLETON_LOCK = threading.Lock()
_SINGLETON: Optional[MundoSinCensuraAgent] = None


def get_mundo_sin_censura() -> MundoSinCensuraAgent:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = MundoSinCensuraAgent()
        return _SINGLETON


def analyze_and_abliterate() -> Dict[str, Any]:
    """Punto de entrada retrocompatible: asegura el modelo y retorna análisis + estado."""
    agent = get_mundo_sin_censura()
    ensured = agent.ensure_model_ready(rebuild=False)
    report = agent.analyze_systems()
    return {
        "analysis": report,
        "abliteration": {
            "targets": ensured.get("actions", []),
            "errors": ensured.get("errors", []),
        },
        "status": agent.get_status(),
    }


def _build_cli_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mundo-sin-censura",
        description="Controlador Soberano Dual-Lane de Un Mundo Sin Censura (TARDIS)",
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Muestra estado operativo dual-lane y paridad de pesos")
    sub.add_parser("analyze", help="Auditoría completa de pesos, Ollama, TemporalBrain y seguridad")
    p_ver = sub.add_parser("verify", help="Verificación exhaustiva (con recálculo SHA-256 opcional)")
    p_ver.add_argument("--force-hash", action="store_true", help="Recalcula SHA-256 del GGUF desde disco")

    p_ens = sub.add_parser("ensure", help="Sincroniza Modelfiles, Ollama, FTL y Colony")
    p_ens.add_argument("--rebuild", action="store_true", help="Reconstruye mundo-sin-censura:latest en Ollama")

    sub.add_parser("sync-ftl", help="Sincroniza auditoría y estado FTL (~/.config/ftl)")
    sub.add_parser("abliterate", help="Aplica configuración soberana no destructiva")

    p_chat = sub.add_parser("chat", help="Envía un prompt al modelo Un Mundo Sin Censura")
    p_chat.add_argument("prompt", nargs="+", help="Texto del prompt")
    p_chat.add_argument("--lane", choices=["auto", "temporal_brain", "ollama"], default="auto")
    p_chat.add_argument("--use-rag", action="store_true", help="Activa hooks RAG de TemporalBrain")
    p_chat.add_argument("--temperature", type=float, default=0.25)
    p_chat.add_argument("--max-tokens", type=int, default=512)
    p_chat.add_argument("--num-ctx", type=int, default=8192)
    p_chat.add_argument("--timeout", type=float, default=120.0)
    p_chat.add_argument("--raw", action="store_true", help="Imprime sólo el texto de respuesta")

    p_bench = sub.add_parser("benchmark", help="Ejecuta prueba de rendimiento empírica")
    p_bench.add_argument("--lane", choices=["auto", "temporal_brain", "ollama"], default="auto")
    p_bench.add_argument("--max-tokens", type=int, default=96)
    p_bench.add_argument("--timeout", type=float, default=120.0)
    p_bench.add_argument("--prompt", type=str, default=None)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    agent = get_mundo_sin_censura()
    cmd = args.cmd or "status"

    if cmd == "status":
        out = agent.get_status()
    elif cmd == "analyze":
        out = agent.analyze_systems()
    elif cmd == "verify":
        out = agent.verify_model(force_hash=bool(args.force_hash))
    elif cmd == "ensure":
        out = agent.ensure_model_ready(rebuild=bool(args.rebuild))
    elif cmd == "sync-ftl":
        out = agent.sync_ftl_audit()
    elif cmd == "abliterate":
        out = agent.configure_sovereign_mode()
    elif cmd == "chat":
        prompt_txt = " ".join(args.prompt).strip()
        out = agent.generate(
            prompt_txt,
            lane=args.lane,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            num_ctx=args.num_ctx,
            use_rag=bool(args.use_rag),
            timeout=args.timeout,
        )
        if args.raw:
            print(out.get("reply", ""))
            return 0 if out.get("ok") else 1
    elif cmd == "benchmark":
        out = agent.benchmark(
            lane=args.lane,
            max_tokens=args.max_tokens,
            prompt=args.prompt,
            timeout=args.timeout,
        )
    else:
        parser.print_help()
        return 2

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok", True) is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
