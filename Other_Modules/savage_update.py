"""
modulos_ftl/savage_update.py — /SavageUpdate · Agente Soberano de Auto-Mejora Continua
=====================================================================================
GODWORKS SYSTEM v26.4 · TARDIS · FTL · Easy Touch
Arquitecto: El Arquitecto (₪)

MISIÓN
------
``/SavageUpdate`` mantiene a todos los sistemas del Arquitecto aprendiendo de forma
permanente. Cada ciclo:

  1. **Investiga** tecnología nueva en fuentes primarias (releases de motores de
     inferencia, modelos en tendencia, preprint servers, registro de REA).
  2. **Puntúa relevancia** contra la doctrina del sistema (local-first, soberanía,
     eficiencia de VRAM, agentes, contexto largo, voz, visión, seguridad).
  3. **Deduplica** lo ya visto para no repetir ruido.
  4. **Genera propuestas de experimento** con evidencia, riesgo, validación y
     rollback para TARDIS, FTL y Easy Touch.
  5. **Ejecuta la parte segura**: actualiza el perfil de adaptación REA, escribe
     planes de experimento y encola investigación; nunca aplica código de terceros
     ni ejecuta artefactos descargados.

GARANTÍAS
---------
* Sin ejecución de código remoto. Sin ``pip install`` automático. Sin descargas de
  modelos. Sin escritura fuera de ``data/rea``.
* Red acotada: timeout, tamaño máximo, User-Agent identificable, reintentos simples.
* Si una fuente falla, el ciclo continúa (degradación elegante).
* Todo queda auditado en ``data/rea/audit.jsonl``.

USO
---
    python3 -m modulos_ftl.savage_update once
    python3 -m modulos_ftl.savage_update once --offline
    python3 -m modulos_ftl.savage_update daemon --interval 21600
    python3 -m modulos_ftl.savage_update status
    python3 -m modulos_ftl.savage_update queue --limit 20
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import random
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .rea_learning_engine import (
    DATA_DIR,
    EXPERIMENTS_DIR,
    LearningEngine,
    _append_jsonl,
    _atomic_write,
    _now,
    _read_json,
    _safe_int,
)

REPORT_PATH = DATA_DIR / "savage_update_report.json"
STATE_PATH = DATA_DIR / "savage_state.json"
SEEN_PATH = DATA_DIR / "savage_seen.json"
QUEUE_PATH = DATA_DIR / "research_queue.jsonl"
PROPOSALS_PATH = DATA_DIR / "savage_proposals.json"

SCHEMA = "tardis.savage_update/1.0"
USER_AGENT = "TARDIS-SavageUpdate/26.4 (+sovereign-local-agent)"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
HTTP_TIMEOUT_S = 14
MAX_SEEN = 50_000

# Fuentes primarias. Cada una devuelve elementos normalizados.
GITHUB_REPOS = [
    ("ggml-org/llama.cpp", "inference-engine"),
    ("ollama/ollama", "local-runtime"),
    ("vllm-project/vllm", "inference-engine"),
    ("huggingface/transformers", "ml-framework"),
    ("ggml-org/whisper.cpp", "speech"),
    ("Aider-AI/aider", "coding-agent"),
]

ARXIV_QUERIES = [
    ("cat:cs.AI", "ai-research"),
    ("cat:cs.CL", "nlp-research"),
    ("cat:cs.LG", "ml-research"),
]

# Pesos de relevancia por dominio doctrinal
KEYWORD_WEIGHTS: Dict[str, float] = {
    "quantization": 3.0, "quantized": 3.0, "gguf": 3.0, "q4": 2.5, "q8": 2.0,
    "lora": 2.5, "qlora": 2.5, "fine-tun": 2.0, "distill": 2.0,
    "mixture of experts": 3.0, "moe": 2.5, "sparse": 2.0,
    "speculative decoding": 3.0, "kv cache": 3.0, "paged attention": 3.0,
    "flash attention": 2.5, "attention": 1.5,
    "long context": 3.0, "context window": 2.5, "rope": 2.0, "million token": 3.0,
    "agent": 2.5, "agentic": 2.5, "tool use": 2.5, "function calling": 2.5,
    "mcp": 2.0, "orchestrat": 2.0,
    "rag": 2.0, "retrieval": 2.0, "embedding": 2.0, "vector": 1.5,
    "vision": 2.0, "multimodal": 2.5, "vlm": 2.5, "ocr": 1.5,
    "speech": 2.0, "whisper": 2.0, "tts": 2.0, "asr": 2.0, "audio": 1.5,
    "reasoning": 2.5, "chain of thought": 2.0, "test-time compute": 3.0,
    "safety": 2.0, "alignment": 2.0, "guardrail": 2.0, "red team": 1.5,
    "privacy": 2.0, "local": 2.0, "on-device": 2.5, "edge": 2.0,
    "cuda": 1.5, "rocm": 1.5, "vulkan": 1.5, "metal": 1.0, "cpu": 1.0,
    "benchmark": 1.5, "latency": 1.5, "throughput": 1.5, "memory": 1.5,
    "open source": 1.0, "release": 0.5, "update": 0.3,
}

TAG_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("quantization", ("quant", "gguf", "q4", "q8", "int4", "int8", "awq", "gptq")),
    ("moe", ("mixture of experts", "moe", "expert")),
    ("long-context", ("long context", "context window", "rope", "million token", "128k", "1m")),
    ("agents", ("agent", "tool use", "function calling", "mcp", "orchestrat")),
    ("rag", ("rag", "retrieval", "embedding", "vector")),
    ("vision", ("vision", "multimodal", "vlm", "image", "ocr")),
    ("speech", ("speech", "whisper", "tts", "asr", "audio", "voice")),
    ("reasoning", ("reasoning", "chain of thought", "test-time", "inference scaling")),
    ("efficiency", ("speculative", "kv cache", "paged", "flash attention", "throughput", "latency")),
    ("safety", ("safety", "alignment", "guardrail", "jailbreak", "red team")),
    ("local", ("local", "on-device", "edge", "offline", "privacy")),
]

# Plantillas de propuesta por etiqueta
PROPOSAL_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "quantization": {
        "target": "ftl", "title": "Benchmark de cuantización para el modelo soberano",
        "experiment": "quantization_benchmark",
        "validation": "Medir tokens/s, VRAM pico y perplejidad en 20 prompts; aceptar sólo si la pérdida es <2%.",
        "rollback": "Mantener el GGUF Q4_K actual y descartar el artefacto candidato.",
    },
    "moe": {
        "target": "tardis", "title": "Ruteo por expertos activos (top-k)",
        "experiment": "moe_routing",
        "validation": "Comparar costo por token activo vs. modelo denso equivalente.",
        "rollback": "Volver al ruteo denso por defecto.",
    },
    "long-context": {
        "target": "tardis", "title": "Perfil de contexto extendido con chunking alineado",
        "experiment": "long_context_profile",
        "validation": "Prueba de recuperación en documento de 128k tokens; medir latencia y precisión.",
        "rollback": "Restaurar ctx_size=4096.",
    },
    "agents": {
        "target": "ftl", "title": "Política de agentes y tool-calling",
        "experiment": "agent_tool_policy",
        "validation": "Suite de 30 tareas con herramientas; medir tasa de éxito y pasos.",
        "rollback": "Reactivar la política anterior en coding_router.json.",
    },
    "rag": {
        "target": "tardis", "title": "Mejora del pipeline RAG y embeddings",
        "experiment": "rag_pipeline",
        "validation": "Recall@10 sobre 100 consultas doradas.",
        "rollback": "Conservar el índice actual.",
    },
    "vision": {
        "target": "tardis", "title": "Integración de capacidades visión/multimodal",
        "experiment": "vision_pipeline",
        "validation": "Evaluar 50 imágenes con ground truth; medir exactitud y latencia.",
        "rollback": "Desactivar el pipeline visual nuevo.",
    },
    "speech": {
        "target": "tardis", "title": "Actualización de voz (ASR/TTS) local",
        "experiment": "speech_pipeline",
        "validation": "WER en 20 audios y latencia de síntesis.",
        "rollback": "Mantener el motor de voz actual.",
    },
    "reasoning": {
        "target": "tardis", "title": "Presupuesto de razonamiento adaptativo",
        "experiment": "reasoning_budget",
        "validation": "Comparar exactitud/costo en 40 problemas; elegir el punto de Pareto.",
        "rollback": "Volver al esfuerzo por defecto.",
    },
    "efficiency": {
        "target": "ftl", "title": "Optimización de inferencia (caché y decodificación)",
        "experiment": "inference_efficiency",
        "validation": "Medir tokens/s y VRAM antes/después con el mismo prompt.",
        "rollback": "Restaurar cache_type_k/v=f16.",
    },
    "safety": {
        "target": "easy_touch", "title": "Endurecimiento de guardrails y auto-reparación",
        "experiment": "safety_guardrails",
        "validation": "Batería de 25 casos adversarios; cero ejecuciones no autorizadas.",
        "rollback": "Restaurar la política de seguridad previa.",
    },
    "local": {
        "target": "tardis", "title": "Refuerzo del perfil local-first",
        "experiment": "local_first",
        "validation": "Verificar que las tareas privadas no salgan del dispositivo.",
        "rollback": "Reactivar ruteo híbrido.",
    },
}


# ---------------------------------------------------------------------------
# HTTP acotado
# ---------------------------------------------------------------------------
def _http_get(url: str, accept: str = "application/json", timeout: int = HTTP_TIMEOUT_S) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Encoding": "identity",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                return None
            return data
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def _http_json(url: str) -> Any:
    raw = _http_get(url)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------
@dataclass
class ResearchItem:
    id: str
    source: str
    category: str
    title: str
    url: str
    published_at: str = ""
    summary: str = ""
    tags: List[str] = field(default_factory=list)
    relevance: float = 0.0
    targets: List[str] = field(default_factory=list)


def _score(text: str) -> Tuple[float, List[str]]:
    low = text.lower()
    score = 0.0
    tags: List[str] = []
    for keyword, weight in KEYWORD_WEIGHTS.items():
        if keyword in low:
            score += weight
    for tag, needles in TAG_RULES:
        for needle in needles:
            # Los acrónimos cortos exigen límite de palabra para evitar falsos positivos.
            if len(needle) <= 4 and needle.isalpha():
                if re.search(rf"\b{re.escape(needle)}\b", low):
                    tags.append(tag)
                    break
            elif needle in low:
                tags.append(tag)
                break
    # Bonus por múltiples señales
    score += min(4.0, 0.6 * len(tags))
    return round(min(score, 25.0), 2), tags


def _item_id(source: str, key: str) -> str:
    return hashlib.sha1(f"{source}|{key}".encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Recolectores
# ---------------------------------------------------------------------------
def collect_github(repos: Sequence[Tuple[str, str]]) -> List[ResearchItem]:
    items: List[ResearchItem] = []
    for repo, category in repos:
        payload = _http_json(f"https://api.github.com/repos/{repo}/releases/latest")
        if not isinstance(payload, dict) or not payload.get("tag_name"):
            continue
        title = f"{repo} {payload.get('tag_name')}"
        body = str(payload.get("body") or "")[:4000]
        text = f"{title} {body}"
        score, tags = _score(text)
        items.append(ResearchItem(
            id=_item_id("github", f"{repo}:{payload.get('tag_name')}"),
            source=f"github:{repo}",
            category=category,
            title=title[:240],
            url=str(payload.get("html_url") or f"https://github.com/{repo}/releases"),
            published_at=str(payload.get("published_at") or ""),
            summary=body[:700],
            tags=tags,
            relevance=score,
        ))
    return items


def collect_huggingface(limit: int = 20) -> List[ResearchItem]:
    payload = _http_json(
        f"https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit={limit}"
        "&full=false&config=false"
    )
    if not isinstance(payload, list):
        return []
    items: List[ResearchItem] = []
    for model in payload:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("modelId") or model.get("id") or "")
        if not model_id:
            continue
        tags_raw = model.get("tags") or []
        pipeline = str(model.get("pipeline_tag") or "")
        text = f"{model_id} {pipeline} {' '.join(map(str, tags_raw))}"
        score, tags = _score(text)
        items.append(ResearchItem(
            id=_item_id("hf", model_id),
            source="huggingface:trending",
            category="model",
            title=model_id[:240],
            url=f"https://huggingface.co/{model_id}",
            published_at=str(model.get("lastModified") or model.get("createdAt") or ""),
            summary=f"pipeline={pipeline} downloads={model.get('downloads', 'n/d')} likes={model.get('likes', 'n/d')}",
            tags=tags,
            relevance=score,
        ))
    return items


def collect_arxiv(queries: Sequence[Tuple[str, str]], per_query: int = 12) -> List[ResearchItem]:
    items: List[ResearchItem] = []
    for query, category in queries:
        url = (
            "https://export.arxiv.org/api/query?"
            f"search_query={urllib.parse.quote(query)}&sortBy=submittedDate"
            f"&sortOrder=descending&max_results={per_query}"
        )
        raw = _http_get(url, accept="application/atom+xml")
        if not raw:
            continue
        text = raw.decode("utf-8", "replace")
        for entry in re.findall(r"<entry>(.*?)</entry>", text, re.S):
            title_m = re.search(r"<title>(.*?)</title>", entry, re.S)
            id_m = re.search(r"<id>(.*?)</id>", entry, re.S)
            summary_m = re.search(r"<summary>(.*?)</summary>", entry, re.S)
            published_m = re.search(r"<published>(.*?)</published>", entry, re.S)
            if not (title_m and id_m):
                continue
            title = re.sub(r"\s+", " ", title_m.group(1)).strip()
            summary = re.sub(r"\s+", " ", summary_m.group(1)).strip() if summary_m else ""
            score, tags = _score(f"{title} {summary}")
            items.append(ResearchItem(
                id=_item_id("arxiv", id_m.group(1).strip()),
                source="arxiv",
                category=category,
                title=title[:240],
                url=id_m.group(1).strip(),
                published_at=published_m.group(1).strip() if published_m else "",
                summary=summary[:700],
                tags=tags,
                relevance=score,
            ))
    return items


def collect_npm(package: str = "rea-agents") -> List[ResearchItem]:
    payload = _http_json(f"https://registry.npmjs.org/{package}/latest")
    if not isinstance(payload, dict) or not payload.get("version"):
        return []
    version = str(payload["version"])
    desc = str(payload.get("description") or "")
    score, tags = _score(f"{package} {version} {desc}")
    return [ResearchItem(
        id=_item_id("npm", f"{package}:{version}"),
        source=f"npm:{package}",
        category="tooling",
        title=f"{package} {version}",
        url=f"https://www.npmjs.com/package/{package}",
        summary=desc[:700],
        tags=tags or ["agents"],
        relevance=max(score, 4.0),
    )]


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------
class SavageUpdateAgent:
    def __init__(self, offline: bool = False, verbose: bool = True):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.verbose = verbose
        self._stop = False

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[SavageUpdate] {msg}", file=sys.stderr, flush=True)

    # -- estado ----------------------------------------------------------
    def _load_seen(self) -> Dict[str, Any]:
        payload = _read_json(SEEN_PATH, default={}) or {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("ids", [])
        payload.setdefault("updated_at", None)
        return payload

    def _save_seen(self, seen: Dict[str, Any], new_ids: Iterable[str]) -> None:
        ids = list(dict.fromkeys(list(seen.get("ids", [])) + list(new_ids)))
        if len(ids) > MAX_SEEN:
            ids = ids[-MAX_SEEN:]
        _atomic_write(SEEN_PATH, {"ids": ids, "updated_at": _now(), "count": len(ids)})

    # -- recolección -----------------------------------------------------
    def collect(self) -> Tuple[List[ResearchItem], Dict[str, Any]]:
        if self.offline:
            return [], {"offline": True, "sources": {}}
        items: List[ResearchItem] = []
        sources: Dict[str, Any] = {}

        for name, fn in (
            ("github", lambda: collect_github(GITHUB_REPOS)),
            ("huggingface", collect_huggingface),
            ("arxiv", lambda: collect_arxiv(ARXIV_QUERIES)),
            ("npm", collect_npm),
        ):
            started = time.time()
            try:
                batch = fn()
            except Exception as exc:  # noqa: BLE001
                sources[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "count": 0}
                continue
            sources[name] = {
                "ok": True,
                "count": len(batch),
                "elapsed_ms": round((time.time() - started) * 1000, 1),
            }
            items.extend(batch)
            self.log(f"{name}: {len(batch)} elementos")
        # Deduplicar por id (una misma entrada puede aparecer en varias consultas)
        items = list({item.id: item for item in items}.values())
        return items, {"offline": False, "sources": sources}

    # -- propuestas ------------------------------------------------------
    def build_proposals(self, items: Sequence[ResearchItem]) -> List[Dict[str, Any]]:
        proposals: Dict[str, Dict[str, Any]] = {}
        for item in items:
            for tag in item.tags:
                template = PROPOSAL_TEMPLATES.get(tag)
                if not template:
                    continue
                key = (template["target"], template["experiment"])
                pid = "savage-" + hashlib.sha1(json.dumps(key).encode("utf-8")).hexdigest()[:12]
                if pid not in proposals:
                    proposals[pid] = {
                        "id": pid,
                        "title": template["title"],
                        "target": template["target"],
                        "tag": tag,
                        "risk": "low",
                        "kind": "experiment",
                        "experiment": template["experiment"],
                        "evidence": [],
                        "rationale": (
                            f"Señal tecnológica detectada en {len([i for i in items if tag in i.tags])} "
                            f"fuentes; la doctrina exige evaluar antes de adoptar."
                        ),
                        "validation": template["validation"],
                        "rollback": template["rollback"],
                        "status": "proposed",
                        "created_at": _now(),
                    }
                if len(proposals[pid]["evidence"]) < 8:
                    proposals[pid]["evidence"].append({
                        "title": item.title,
                        "url": item.url,
                        "source": item.source,
                        "relevance": item.relevance,
                    })
        return sorted(proposals.values(), key=lambda p: (-len(p["evidence"]), p["id"]))

    def write_experiment_plans(self, proposals: Sequence[Dict[str, Any]]) -> List[str]:
        written: List[str] = []
        for proposal in proposals:
            if proposal.get("status") == "planned":
                continue
            target = EXPERIMENTS_DIR / f"{proposal['experiment']}.json"
            existing = _read_json(target, default=None)
            if isinstance(existing, dict):
                merged = existing.get("evidence", [])
                known = {e.get("url") for e in merged if isinstance(e, dict)}
                for ev in proposal.get("evidence", []):
                    if ev.get("url") not in known:
                        merged.append(ev)
                existing["evidence"] = merged[-16:]
                existing["updated_at"] = _now()
                _atomic_write(target, existing)
            else:
                _atomic_write(target, {
                    "schema": "tardis.savage.experiment/1.0",
                    "proposal_id": proposal["id"],
                    "experiment": proposal["experiment"],
                    "target": proposal["target"],
                    "hypothesis": proposal["title"],
                    "validation": proposal["validation"],
                    "rollback": proposal["rollback"],
                    "evidence": proposal.get("evidence", []),
                    "status": "planned",
                    "created_at": _now(),
                })
            proposal["status"] = "planned"
            written.append(str(target))
        return written

    # -- ciclo -----------------------------------------------------------
    def run_cycle(self, scan: bool = True) -> Dict[str, Any]:
        started = time.time()
        self.log("iniciando ciclo")
        items, source_status = self.collect()

        # Deduplicar contra lo ya visto y ordenar por relevancia
        seen = self._load_seen()
        seen_ids = set(seen.get("ids", []))
        fresh = [i for i in items if i.id not in seen_ids]
        fresh.sort(key=lambda i: i.relevance, reverse=True)
        self.log(f"nuevos: {len(fresh)} / {len(items)}")

        # Aprendizaje local REA
        rea_result: Dict[str, Any] = {}
        if scan:
            try:
                engine = LearningEngine(use_rea=False, verbose=False)
                scan_result = engine.scan(max_files=64)
                report = engine.build_report()
                rea_proposals = engine.build_proposals()
                rea_result = {
                    "ok": True,
                    "artifacts": scan_result.get("scanned", 0),
                    "report_artifacts": report.get("artifacts_analyzed", 0),
                    "proposals": len(rea_proposals.get("proposals", [])),
                }
            except Exception as exc:  # noqa: BLE001
                rea_result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                self.log(f"REA scan falló: {exc}")

        proposals = self.build_proposals(fresh)
        plans = self.write_experiment_plans(proposals)

        # Persistencia
        for item in fresh:
            _append_jsonl(QUEUE_PATH, asdict(item))
        _atomic_write(PROPOSALS_PATH, {
            "schema": SCHEMA,
            "generated_at": _now(),
            "proposals": proposals,
            "items_considered": len(fresh),
        })
        self._save_seen(seen, [i.id for i in fresh])

        report = {
            "schema": SCHEMA,
            "generated_at": _now(),
            "cycle": {
                "items_collected": len(items),
                "items_fresh": len(fresh),
                "proposals": len(proposals),
                "experiment_plans": len(plans),
                "elapsed_s": round(time.time() - started, 2),
            },
            "sources": source_status,
            "rea": rea_result,
            "top_items": [asdict(i) for i in fresh[:15]],
            "proposals": proposals,
            "offline": self.offline,
        }
        _atomic_write(REPORT_PATH, report)

        state = _read_json(STATE_PATH, default={}) or {}
        state.update({
            "last_cycle_at": _now(),
            "cycles": _safe_int(state.get("cycles")) + 1,
            "last_items": len(fresh),
            "last_proposals": len(proposals),
            "engine_version": "26.4.0",
        })
        _atomic_write(STATE_PATH, state)
        _append_jsonl(DATA_DIR / "audit.jsonl", {
            "at": _now(), "action": "savage_cycle",
            "items": len(items), "fresh": len(fresh),
            "proposals": len(proposals), "offline": self.offline,
        })
        self.log(f"ciclo completo en {report['cycle']['elapsed_s']}s")
        return report

    # -- daemon ----------------------------------------------------------
    def daemon(self, interval: int = 6 * 3600, jitter: int = 900) -> None:
        def _handle(signum, frame):  # noqa: ANN001, ARG001
            self._stop = True
            self.log(f"señal {signum}: detención solicitada")

        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)
        while not self._stop:
            try:
                self.run_cycle(scan=True)
            except Exception as exc:  # noqa: BLE001
                self.log(f"ciclo falló: {exc}")
                _append_jsonl(DATA_DIR / "audit.jsonl", {
                    "at": _now(), "action": "savage_cycle_failed", "error": str(exc),
                })
            delay = max(300, interval + random.randint(-jitter, jitter))
            self.log(f"próximo ciclo en {delay}s")
            slept = 0
            while slept < delay and not self._stop:
                time.sleep(min(30, delay - slept))
                slept += 30

    # -- estado ----------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        state = _read_json(STATE_PATH, default={}) or {}
        report = _read_json(REPORT_PATH, default={}) or {}
        proposals = _read_json(PROPOSALS_PATH, default={}) or {}
        queue_lines = 0
        if QUEUE_PATH.exists():
            try:
                with open(QUEUE_PATH, "r", encoding="utf-8") as fh:
                    queue_lines = sum(1 for _ in fh)
            except OSError:
                pass
        return {
            "ok": True,
            "agent": "/SavageUpdate",
            "version": "26.4.0",
            "offline_mode": self.offline,
            "cycles": state.get("cycles", 0),
            "last_cycle_at": state.get("last_cycle_at"),
            "last_items": state.get("last_items", 0),
            "last_proposals": state.get("last_proposals", 0),
            "queue_records": queue_lines,
            "report": {
                "path": str(REPORT_PATH),
                "generated_at": report.get("generated_at"),
                "sources": report.get("sources", {}),
                "rea": report.get("rea", {}),
            },
            "proposals": {
                "path": str(PROPOSALS_PATH),
                "total": len(proposals.get("proposals", [])),
                "planned": sum(1 for p in proposals.get("proposals", []) if p.get("status") == "planned"),
            },
            "experiments_dir": str(EXPERIMENTS_DIR),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="savage-update", description="/SavageUpdate · auto-mejora continua")
    sub = parser.add_subparsers(dest="command", required=False)

    p_once = sub.add_parser("once", help="Ejecutar un ciclo")
    p_once.add_argument("--offline", action="store_true")
    p_once.add_argument("--no-scan", action="store_true")
    p_once.add_argument("--json", action="store_true")

    p_daemon = sub.add_parser("daemon", help="Ejecutar en bucle")
    p_daemon.add_argument("--interval", type=int, default=6 * 3600)
    p_daemon.add_argument("--jitter", type=int, default=900)
    p_daemon.add_argument("--offline", action="store_true")

    p_queue = sub.add_parser("queue", help="Ver cola de investigación")
    p_queue.add_argument("--limit", type=int, default=20)

    sub.add_parser("status", help="Estado del agente")

    args = parser.parse_args(argv)
    cmd = args.command or "status"
    agent = SavageUpdateAgent(offline=getattr(args, "offline", False), verbose=True)

    if cmd == "once":
        report = agent.run_cycle(scan=not getattr(args, "no_scan", False))
        if getattr(args, "json", False):
            _print(report)
        else:
            print(f"✔ /SavageUpdate ciclo completado: {report['cycle']}")
            print(f"  Fuentes: { {k: v.get('count') for k, v in report['sources'].get('sources', {}).items()} }")
            print(f"  REA: {report['rea']}")
            print(f"  Propuestas: {len(report['proposals'])}")
            for p in report["proposals"][:10]:
                print(f"    · [{p['target']}] {p['title']} ({len(p['evidence'])} señales)")
        return 0

    if cmd == "daemon":
        agent.daemon(interval=args.interval, jitter=args.jitter)
        return 0

    if cmd == "queue":
        if not QUEUE_PATH.exists():
            print("Cola vacía.")
            return 0
        with open(QUEUE_PATH, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        for line in lines[-max(1, args.limit):]:
            try:
                item = json.loads(line)
            except Exception:
                continue
            print(f"{item.get('relevance', 0):5.1f} | {item.get('source')} | {item.get('title')}")
        print(f"\nTotal: {len(lines)}")
        return 0

    _print(agent.status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
