#!/usr/bin/env python3
"""
core/tardis_eval_harness.py - Continuous Autonomous Eval & Regression Benchmark Harness
=======================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU

Sistema alterno soberano de evaluación continua pre/post evolución con 5 suites modulares:
  1. `rag`: calidad de recuperación densa/híbrida en RAGVault, calibración isotrópica ZCA
     y salud de TardisSemanticCache.
  2. `aegis`: precisión, recall, F1 y redacción segura del clasificador/detector de fugas
     AEGIS-Ω (`core/aegis/classifier.py`) sobre un corpus etiquetado sintético sin secretos reales.
  3. `tool_calling`: fidelidad de registro, validación de esquema, despacho y manejo de errores
     en `ToolRegistry` / `TemporalBrainFunctionRegistry` y parser estructurado JSON.
  4. `latency`: percentiles P50/P95 y disponibilidad de `/health`, `/api/governor/status`,
     `/api/cache/stats`, `/tmp/embed_brain.sock` y `/tmp/temporal_brain.sock`.
  5. `llm_judge` (opcional): evaluación de calidad en 4 ejes (`accuracy`, `completeness`,
     `safety`, `conciseness`) vía LLM-as-judge (`TemporalBrain`) con rúbrica determinista
     de respaldo, consciente de presión Ring 0 (`ResourceGovernor`).

Características de gobernanza:
  - Persistencia durable en SQLite WAL (`data/eval_harness.db`) con aislamiento bajo `pytest`.
  - Comparación automática pre/post evolución (`compare_runs()`) con detección determinista
    de regresiones de puntaje (`>= 5 pts` global, `>= 8 pts` por suite) y latencia (`>= 2x P95`).
  - Alimenta directamente al motor de co-evolución publicando `eval.completed` / `eval.regression`
    en `SovereignEventBus`.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import math
import os
import re
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_EVAL_DB = DATA_DIR / "eval_harness.db"

ALL_SUITES: Tuple[str, ...] = ("rag", "aegis", "tool_calling", "latency", "llm_judge")
DEFAULT_FAST_SUITES: Tuple[str, ...] = ("rag", "aegis", "tool_calling", "latency")

OVERALL_REGRESSION_DROP_PTS = 5.0
SUITE_REGRESSION_DROP_PTS = 8.0
P95_REGRESSION_RATIO = 2.0
P95_REGRESSION_MIN_DELTA_MS = 100.0

logger = logging.getLogger("TARDIS.EvalHarness")


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _is_pytest_isolated() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and str(
        os.environ.get("TARDIS_EVAL_LIVE_TEST", "0")
    ).strip().lower() not in ("1", "true", "yes")


def _percentile(values: Sequence[float], pct: float) -> float:
    clean = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not clean:
        return 0.0
    if len(clean) == 1:
        return round(clean[0], 2)
    pos = (max(0.0, min(100.0, float(pct))) / 100.0) * (len(clean) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return round(clean[lo], 2)
    frac = pos - lo
    return round(clean[lo] * (1.0 - frac) + clean[hi] * frac, 2)


def _extract_json_object(raw: str) -> Optional[Dict[str, Any]]:
    """Extrae el primer objeto JSON válido desde una respuesta LLM o bloque ```json```."""
    txt = (raw or "").strip()
    if not txt:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", txt, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        try:
            obj = json.loads(fenced.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    start = txt.find("{")
    end = txt.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(txt[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def _http_probe_ms(url: str, timeout: float = 2.0) -> Tuple[bool, float, int]:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read(2048)
            code = int(getattr(resp, "status", 200))
            return (200 <= code < 400), round((time.perf_counter() - t0) * 1000.0, 2), code
    except Exception:
        return False, round((time.perf_counter() - t0) * 1000.0, 2), 0


def _uds_health_probe_ms(sock_path: Path, timeout: float = 1.5) -> Tuple[bool, float]:
    t0 = time.perf_counter()
    if not sock_path.exists():
        return False, round((time.perf_counter() - t0) * 1000.0, 2)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(sock_path))
            s.sendall(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n")
            data = s.recv(1024).decode("utf-8", errors="ignore")
        ok = (" 200 " in data.splitlines()[0]) if data else False
        return ok, round((time.perf_counter() - t0) * 1000.0, 2)
    except Exception:
        return False, round((time.perf_counter() - t0) * 1000.0, 2)


# ---------------------------------------------------------------------- Suites de Evaluación
def _eval_aegis_suite() -> Dict[str, Any]:
    """Evalúa precisión, recall, F1 y redacción del clasificador AEGIS-Ω sin secretos reales."""
    t0 = time.perf_counter()
    try:
        from core.aegis.classifier import classify_path, scan_text
    except Exception as exc:
        return {
            "ok": False,
            "score": 0.0,
            "error": f"aegis_import_failed: {exc}",
            "p50_ms": 0.0,
            "p95_ms": 0.0,
        }

    # Fixtures construidos dinámicamente en tiempo de ejecución (cero literales secretos en código fuente)
    synth_openai = "".join(["sk", "-", "REDACTED_TOKEN"])
    synth_gh = "".join(["ghp", "_", "REDACTED_TOKEN"])
    synth_pem = "".join(["-----BEGIN ", "RSA PRIVATE KEY-----"])
    synth_jwt = ".".join(["REDACTED_TOKEN", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"])

    text_cases: List[Tuple[str, str, bool, str]] = [
        ("tp_openai_token", f"API_TOKEN = 'REDACTED'", True, synth_openai),
        ("tp_github_pat", f"GITHUB_PAT = '{synth_gh}'", True, synth_gh),
        ("tp_private_pem", synth_pem, True, synth_pem),
        ("tp_jwt_bearer", f"Authorization: Bearer {synth_jwt}", True, synth_jwt),
        ("tn_clean_code", "def compute_psi_budget(cores: int) -> int:\n    return max(1, cores // 2)\n", False, ""),
        ("tn_placeholder_doc", "API_KEY = 'REDACTED'\nPASSWORD = 'REDACTED'\n", False, ""),
        ("tn_telemetry_log", "2026-11-24 level=GREEN cpu_psi60=1.25 load1=1.40 gpu_temp=51.0C", False, ""),
    ]

    path_cases: List[Tuple[str, int, int]] = [
        ("README.md", 0, 1),
        ("core/tardis_eval_harness.py", 1, 2),
        (".env.production", 3, 4),
        ("/home/m11/.ssh/id_rsa", 3, 4),
    ]

    tp = fp = tn = fn = 0
    redaction_violations = 0
    latencies: List[float] = []
    case_results: List[Dict[str, Any]] = []

    for cid, text, expect_finding, raw_secret in text_cases:
        tc0 = time.perf_counter()
        findings = scan_text(text, path=f"eval/{cid}.txt")
        dt_ms = round((time.perf_counter() - tc0) * 1000.0, 2)
        latencies.append(dt_ms)
        detected = len(findings) > 0
        if expect_finding and detected:
            tp += 1
        elif expect_finding and not detected:
            fn += 1
        elif not expect_finding and detected:
            fp += 1
        else:
            tn += 1

        # Verificar que ningún hallazgo exponga el secreto completo sin redactar
        if raw_secret and findings:
            for f in findings:
                if raw_secret in str(getattr(f, "preview", "")):
                    redaction_violations += 1
        case_results.append({"case": cid, "expected": expect_finding, "detected": detected, "ms": dt_ms})

    path_ok = 0
    for p_str, min_lvl, max_lvl in path_cases:
        tc0 = time.perf_counter()
        cls = classify_path(p_str)
        dt_ms = round((time.perf_counter() - tc0) * 1000.0, 2)
        latencies.append(dt_ms)
        lvl = int(cls.level)
        ok_p = min_lvl <= lvl <= max_lvl
        if ok_p:
            path_ok += 1
        case_results.append({"case": f"path:{p_str}", "level": lvl, "ok": ok_p, "ms": dt_ms})

    precision = tp / float(tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / float(tp + fn) if (tp + fn) > 0 else 1.0
    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    path_acc = path_ok / float(len(path_cases))
    redaction_score = 1.0 if redaction_violations == 0 else 0.0

    score = round((0.60 * f1 + 0.25 * path_acc + 0.15 * redaction_score) * 100.0, 2)
    return {
        "ok": score >= 80.0 and redaction_violations == 0,
        "score": score,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "path_accuracy": round(path_acc, 4),
        "redaction_violations": redaction_violations,
        "counts": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "cases": case_results,
    }


def _eval_tool_calling_suite() -> Dict[str, Any]:
    """Evalúa despacho determinista de ToolRegistry, TemporalBrainFunctionRegistry y parser JSON."""
    t0 = time.perf_counter()
    latencies: List[float] = []
    checks: List[Dict[str, Any]] = []

    # 1. ToolRegistry de core/agent_harness.py
    try:
        from core.agent_harness import ToolDefinition, ToolRegistry

        reg = ToolRegistry()
        reg.register(
            ToolDefinition(
                name="eval_sum",
                category="eval",
                description="Suma determinista de dos enteros para benchmark.",
                parameters={"a": {"type": "integer"}, "b": {"type": "integer"}},
                handler=lambda args: {"ok": True, "sum": int(args.get("a", 0)) + int(args.get("b", 0))},
                required_args=["a", "b"],
                is_safe=True,
            )
        )
        tc0 = time.perf_counter()
        r_ok = reg.execute("eval_sum", {"a": 17, "b": 25})
        latencies.append((time.perf_counter() - tc0) * 1000.0)
        ok_sum = bool(r_ok.get("ok") and r_ok.get("sum") == 42)
        checks.append({"check": "agent_harness_execute_valid", "ok": ok_sum})

        tc0 = time.perf_counter()
        r_missing = reg.execute("eval_sum", {"a": 17})
        latencies.append((time.perf_counter() - tc0) * 1000.0)
        checks.append({"check": "agent_harness_missing_arg_rejected", "ok": not bool(r_missing.get("ok"))})

        tc0 = time.perf_counter()
        r_unk = reg.execute("nonexistent_eval_tool_xyz", {})
        latencies.append((time.perf_counter() - tc0) * 1000.0)
        ok_unk = not bool(r_unk.get("ok"))
        checks.append({"check": "agent_harness_unknown_rejected", "ok": ok_unk})
    except Exception as exc:
        checks.append({"check": "agent_harness_registry", "ok": False, "error": str(exc)})

    # 2. TemporalBrainFunctionRegistry de core/temporal_brain.py
    try:
        from core.temporal_brain import TemporalBrainFunctionRegistry

        freg = TemporalBrainFunctionRegistry()

        @freg.register(name="eval_multiply", description="Multiplica dos enteros")
        def _mul(x: int, y: int) -> int:
            return int(x) * int(y)

        tc0 = time.perf_counter()
        val = freg.execute("eval_multiply", x=6, y=7)
        latencies.append((time.perf_counter() - tc0) * 1000.0)
        checks.append({"check": "temporal_brain_fn_execute", "ok": val == 42})
        checks.append({"check": "temporal_brain_fn_listed", "ok": freg.has_function("eval_multiply")})
    except Exception as exc:
        checks.append({"check": "temporal_brain_fn_registry", "ok": False, "error": str(exc)})

    # 3. Extracción y validación estructurada de tool-calls JSON (fenced, plano y malformado)
    parse_cases = [
        ('```json\n{"tool": "eval_sum", "args": {"a": 10, "b": 5}}\n```', True, "eval_sum"),
        ('Prefacio de texto {"tool": "eval_multiply", "args": {"x": 3, "y": 4}} cierre.', True, "eval_multiply"),
        ("Texto libre sin llamada a herramienta válida.", False, ""),
    ]
    for idx, (sample, expect_valid, expect_tool) in enumerate(parse_cases):
        tc0 = time.perf_counter()
        obj = _extract_json_object(sample)
        latencies.append((time.perf_counter() - tc0) * 1000.0)
        if expect_valid:
            ok_p = isinstance(obj, dict) and obj.get("tool") == expect_tool and isinstance(obj.get("args"), dict)
        else:
            ok_p = obj is None
        checks.append({"check": f"json_tool_parse_{idx}", "ok": ok_p})

    passed = sum(1 for c in checks if c.get("ok"))
    total = max(1, len(checks))
    score = round((passed / float(total)) * 100.0, 2)
    return {
        "ok": score >= 85.0,
        "score": score,
        "passed": passed,
        "total": total,
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "checks": checks,
    }


def _eval_rag_suite(rag_vault: Optional[Any] = None, semantic_cache: Optional[Any] = None) -> Dict[str, Any]:
    """Evalúa recuperación híbrida/isotrópica de RAGVault + estado de calibración ZCA y SemanticCache."""
    t0 = time.perf_counter()
    latencies: List[float] = []
    probes = [
        ("gobernador de recursos presion cpu psi linux", ("cpu", "psi", "linux", "recurso", "gobernador", "tardis", "memoria")),
        ("arquitectura rag embeddings busqueda semantica", ("rag", "embed", "vector", "semant", "busqueda", "cache", "consulta")),
        ("seguridad aegis firewall kernel defensa", ("aegis", "seguridad", "kernel", "firewall", "escudo", "red", "defensa")),
    ]

    vault = rag_vault
    if vault is None:
        try:
            from core.rag_vault import get_rag_vault

            vault = get_rag_vault()
        except Exception as exc:
            return {"ok": False, "score": 0.0, "error": f"rag_import_failed: {exc}", "p50_ms": 0.0, "p95_ms": 0.0}

    probe_results: List[Dict[str, Any]] = []
    hit_scores: List[float] = []
    for query, expected_terms in probes:
        tc0 = time.perf_counter()
        try:
            hits = vault.search(query, k=5, hybrid=True) or []
        except Exception as exc:
            hits = []
            probe_results.append({"query": query, "ok": False, "error": str(exc)})
            continue
        dt_ms = round((time.perf_counter() - tc0) * 1000.0, 2)
        latencies.append(dt_ms)

        if not hits:
            hit_scores.append(0.0)
            probe_results.append({"query": query, "hits": 0, "grounded": False, "ms": dt_ms})
            continue

        blob = " ".join(
            f"{h.get('title', '')} {h.get('term', '')} {h.get('text', '')[:320]}"
            for h in hits[:3]
        ).lower()
        matched = sum(1 for kw in expected_terms if kw in blob)
        # 1+ palabra ancla en top-3 = 0.75, 2+ = 1.0
        q_score = 1.0 if matched >= 2 else (0.75 if matched == 1 else 0.35)
        hit_scores.append(q_score)
        probe_results.append(
            {
                "query": query,
                "hits": len(hits),
                "matched_keywords": matched,
                "score": q_score,
                "top_score": round(float(hits[0].get("score", 0.0)), 4),
                "ms": dt_ms,
            }
        )

    rag_stats = {}
    try:
        rag_stats = vault.stats() or {}
    except Exception:
        pass
    iso_cal = rag_stats.get("isotropy_calibration") or {}
    iso_fitted = bool(iso_cal.get("fitted"))
    iso_gain = float(iso_cal.get("isotropy_gain", 0.0))

    cache_ok = False
    cache_stats: Dict[str, Any] = {}
    try:
        sc = semantic_cache
        if sc is None:
            from core.tardis_semantic_cache import get_semantic_cache

            sc = get_semantic_cache()
        cache_stats = sc.stats() or {}
        cache_ok = bool(cache_stats.get("ok"))
    except Exception:
        cache_ok = False

    retrieval_avg = sum(hit_scores) / float(len(hit_scores)) if hit_scores else 0.0
    iso_bonus = 1.0 if (iso_fitted and iso_gain >= 0.5) else (0.6 if iso_fitted else 0.4)
    cache_bonus = 1.0 if cache_ok else 0.5
    score = round((0.70 * retrieval_avg + 0.15 * iso_bonus + 0.15 * cache_bonus) * 100.0, 2)

    return {
        "ok": score >= 65.0,
        "score": score,
        "retrieval_avg": round(retrieval_avg, 4),
        "chunks_indexed": int(rag_stats.get("chunks", 0)),
        "isotropy_fitted": iso_fitted,
        "isotropy_gain": round(iso_gain, 4),
        "semantic_cache_ok": cache_ok,
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "probes": probe_results,
    }


def _eval_latency_suite(
    *,
    api_base: str = "http://127.0.0.1:8757",
    samples_per_target: int = 3,
    probe_fn: Optional[Callable[[str], Tuple[bool, float]]] = None,
) -> Dict[str, Any]:
    """Mide latencia P50/P95 y disponibilidad de los carriles críticos HTTP y UDS."""
    t0 = time.perf_counter()
    targets: List[Tuple[str, str, float]] = [
        ("api_health", f"{api_base.rstrip('/')}/health", 250.0),
        ("api_governor", f"{api_base.rstrip('/')}/api/governor/status", 250.0),
        ("api_cache", f"{api_base.rstrip('/')}/api/cache/stats", 250.0),
        ("embed_brain_uds", "uds:/tmp/embed_brain.sock", 150.0),
        ("temporal_brain_uds", "uds:/tmp/temporal_brain.sock", 150.0),
    ]

    all_latencies: List[float] = []
    target_reports: List[Dict[str, Any]] = []
    sub_scores: List[float] = []
    n_samples = max(1, min(10, int(samples_per_target)))

    for name, endpoint, sla_p95_ms in targets:
        lats: List[float] = []
        ok_cnt = 0
        for _ in range(n_samples):
            if probe_fn is not None:
                ok, ms = probe_fn(endpoint)
            elif endpoint.startswith("uds:"):
                ok, ms = _uds_health_probe_ms(Path(endpoint[4:]))
            else:
                ok, ms, _ = _http_probe_ms(endpoint)
            lats.append(ms)
            all_latencies.append(ms)
            if ok:
                ok_cnt += 1

        avail = ok_cnt / float(n_samples)
        p50 = _percentile(lats, 50)
        p95 = _percentile(lats, 95)
        if avail <= 0.0:
            t_score = 0.0
        elif p95 <= sla_p95_ms:
            t_score = avail
        else:
            # Penalización suave por superar el SLA P95
            ratio = sla_p95_ms / max(p95, 1.0)
            t_score = avail * max(0.35, min(1.0, ratio))
        sub_scores.append(t_score)
        target_reports.append(
            {
                "target": name,
                "availability_pct": round(avail * 100.0, 1),
                "p50_ms": p50,
                "p95_ms": p95,
                "sla_p95_ms": sla_p95_ms,
                "within_sla": bool(avail == 1.0 and p95 <= sla_p95_ms),
            }
        )

    score = round((sum(sub_scores) / float(max(1, len(sub_scores)))) * 100.0, 2)
    return {
        "ok": score >= 75.0,
        "score": score,
        "p50_ms": _percentile(all_latencies, 50),
        "p95_ms": _percentile(all_latencies, 95),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "targets": target_reports,
    }


def _eval_llm_judge_suite(
    *,
    judge_fn: Optional[Callable[[str], str]] = None,
    cases: Optional[List[Dict[str, str]]] = None,
    use_live_llm: bool = True,
) -> Dict[str, Any]:
    """
    Evalúa calidad semántica de respuestas usando LLM-as-judge (4 ejes 0..10) con
    degradación segura y rúbrica determinista si TemporalBrain no está disponible o
    el sistema está bajo presión RED / llamada Telegram activa.
    """
    t0 = time.perf_counter()
    eval_cases = cases or [
        {
            "id": "judge_governor",
            "question": "¿Cómo mitiga TardisResourceGovernor la presión de CPU PSI en nivel ORANGE?",
            "reference": "Aplica cuotas cgroup v2 en caliente (--runtime) a servicios de fondo y cambia el perfil energético amd-pstate-epp.",
            "candidate": "TardisResourceGovernor aplica límites cgroup v2 reversibles (--runtime) sobre unidades de fondo y ajusta el perfil energético del kernel.",
        },
        {
            "id": "judge_isotropy",
            "question": "¿Por qué se aplica ZCA Whitening sobre los embeddings de EmbedBrain?",
            "reference": "Corrige la anisotropía de cono estrecho en embed-e5-small, reduciendo el coseno medio aleatorio cerca de 0 y mejorando Recall@k.",
            "candidate": "ZCA Whitening colapsa el cono anisotrópico de embed-e5-small para acercar el coseno aleatorio a cero y multiplicar Recall@5 en RAGVault.",
        },
    ]

    # Verificar si podemos invocar LLM vivo sin competir con llamadas Telegram ni presión RED
    can_call_live = use_live_llm and judge_fn is None and not _is_pytest_isolated()
    if can_call_live:
        try:
            from core.tardis_resource_governor import get_resource_governor

            snap = get_resource_governor().read_fast_snapshot(max_age_s=60.0)
            if snap.get("call_priority_active") or str(snap.get("level") or "").upper() == "RED":
                can_call_live = False
        except Exception:
            pass

    def _call_judge(prompt: str) -> Tuple[Optional[Dict[str, Any]], str]:
        if judge_fn is not None:
            raw = judge_fn(prompt)
            return _extract_json_object(raw), "custom_judge"
        if can_call_live:
            try:
                from core.temporal_brain import get_temporal_brain

                res = get_temporal_brain().chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Eres un juez técnico estricto. Responde ÚNICAMENTE con un JSON válido: "
                                '{"accuracy":0-10,"completeness":0-10,"safety":0-10,"conciseness":0-10,"verdict":"pass|fail"}'
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=160,
                    timeout=20.0,
                    use_cache=True,
                    cache_namespace="classification",
                )
                if res.get("ok"):
                    parsed = _extract_json_object(str(res.get("reply") or ""))
                    if parsed:
                        return parsed, "temporal_brain_judge"
            except Exception as exc:
                logger.debug("[EvalHarness] Fallback determinista en llm_judge (%s)", exc)
        return None, "deterministic_rubric"

    latencies: List[float] = []
    scores: List[float] = []
    mode_used = "deterministic_rubric"
    details: List[Dict[str, Any]] = []

    for item in eval_cases:
        tc0 = time.perf_counter()
        prompt = (
            f"Pregunta: {item['question']}\n"
            f"Referencia: {item['reference']}\n"
            f"Respuesta candidata: {item['candidate']}\n"
            "Evalúa accuracy, completeness, safety y conciseness (0 a 10) en JSON."
        )
        parsed, src = _call_judge(prompt)
        dt_ms = round((time.perf_counter() - tc0) * 1000.0, 2)
        latencies.append(dt_ms)
        if src != "deterministic_rubric":
            mode_used = src

        if isinstance(parsed, dict) and any(k in parsed for k in ("accuracy", "completeness", "safety", "conciseness")):
            axes = [
                max(0.0, min(10.0, float(parsed.get(k, 7.0))))
                for k in ("accuracy", "completeness", "safety", "conciseness")
            ]
            c_score = round((sum(axes) / 40.0) * 100.0, 2)
        else:
            # Rúbrica determinista de cobertura de conceptos clave + no-error + concisión
            ref_toks = {w for w in re.findall(r"[a-zA-Z0-9áéíóúñÁÉÍÓÚÑ_]{4,}", item["reference"].lower())}
            cand_toks = {w for w in re.findall(r"[a-zA-Z0-9áéíóúñÁÉÍÓÚÑ_]{4,}", item["candidate"].lower())}
            overlap = len(ref_toks & cand_toks) / float(max(1, len(ref_toks)))
            non_err = 0.0 if item["candidate"].strip().lower().startswith("[error") else 1.0
            concise = 1.0 if 20 <= len(item["candidate"]) <= 800 else 0.7
            c_score = round((0.55 * min(1.0, overlap * 1.6) + 0.30 * non_err + 0.15 * concise) * 100.0, 2)

        scores.append(c_score)
        details.append({"id": item["id"], "score": c_score, "judge_mode": src, "ms": dt_ms})

    overall = round(sum(scores) / float(max(1, len(scores))), 2)
    return {
        "ok": overall >= 70.0,
        "score": overall,
        "judge_mode": mode_used,
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "cases": details,
    }


# ---------------------------------------------------------------------- Harness Principal
class TardisEvalHarness:
    """Harness autónomo de evaluación continua pre/post evolución con SQLite WAL y bus de eventos."""

    _instance: Optional["TardisEvalHarness"] = None
    _test_instance: Optional["TardisEvalHarness"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "TardisEvalHarness":
        if db_path is not None:
            return cls(db_path=db_path)
        with cls._init_lock:
            if _is_pytest_isolated():
                if cls._test_instance is None:
                    test_db = Path(tempfile.gettempdir()) / f"tardis_pytest_eval_harness_{os.getpid()}.db"
                    cls._test_instance = cls(db_path=test_db)
                return cls._test_instance
            if cls._instance is None:
                cls._instance = cls(db_path=DEFAULT_EVAL_DB)
            return cls._instance

    def __init__(self, db_path: Path = DEFAULT_EVAL_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._is_isolated = self.db_path.resolve() != DEFAULT_EVAL_DB.resolve()
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=8.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS eval_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    eval_id TEXT NOT NULL UNIQUE,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    tag TEXT NOT NULL DEFAULT 'manual',
                    canary_run_id TEXT DEFAULT '',
                    overall_score REAL NOT NULL,
                    passed INTEGER NOT NULL,
                    p50_ms REAL NOT NULL DEFAULT 0.0,
                    p95_ms REAL NOT NULL DEFAULT 0.0,
                    baseline_eval_id TEXT DEFAULT '',
                    regressions_count INTEGER NOT NULL DEFAULT 0,
                    suites_json TEXT NOT NULL,
                    delta_json TEXT DEFAULT '{}',
                    regressions_json TEXT DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_eval_ts ON eval_runs(ts);
                CREATE INDEX IF NOT EXISTS idx_eval_tag ON eval_runs(tag, ts);
                """
            )

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "eval_id": str(row["eval_id"]),
            "ts": float(row["ts"]),
            "iso": str(row["iso"]),
            "tag": str(row["tag"]),
            "canary_run_id": str(row["canary_run_id"] or ""),
            "overall_score": float(row["overall_score"]),
            "passed": bool(row["passed"]),
            "p50_ms": float(row["p50_ms"]),
            "p95_ms": float(row["p95_ms"]),
            "baseline_eval_id": str(row["baseline_eval_id"] or ""),
            "regressions_count": int(row["regressions_count"]),
            "suites": json.loads(row["suites_json"] or "{}"),
            "delta": json.loads(row["delta_json"] or "{}"),
            "regressions": json.loads(row["regressions_json"] or "[]"),
        }

    def get_run(self, eval_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM eval_runs WHERE eval_id = ?", (eval_id,)).fetchone()
            return self._row_to_dict(row) if row is not None else None

    def get_latest_baseline(self) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM eval_runs WHERE tag = 'baseline' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM eval_runs WHERE passed = 1 ORDER BY id DESC LIMIT 1"
                ).fetchone()
            return self._row_to_dict(row) if row is not None else None

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM eval_runs ORDER BY id DESC LIMIT ?",
                (max(1, min(200, int(limit))),),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def compare_reports(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Compara un candidato contra un baseline y detecta regresiones cuantitativas."""
        base_overall = float(baseline.get("overall_score", 0.0))
        cand_overall = float(candidate.get("overall_score", 0.0))
        overall_delta = round(cand_overall - base_overall, 2)

        base_p95 = float(baseline.get("p95_ms", 0.0))
        cand_p95 = float(candidate.get("p95_ms", 0.0))
        p95_delta_ms = round(cand_p95 - base_p95, 2)

        suite_deltas: Dict[str, float] = {}
        regressions: List[Dict[str, Any]] = []

        if overall_delta <= -OVERALL_REGRESSION_DROP_PTS:
            regressions.append(
                {
                    "scope": "overall",
                    "metric": "overall_score",
                    "baseline": base_overall,
                    "candidate": cand_overall,
                    "delta": overall_delta,
                    "severity": "HIGH",
                    "detail": f"Caída global de calidad ({base_overall:.1f} -> {cand_overall:.1f}, Δ={overall_delta:+.1f} pts)",
                }
            )

        base_suites = baseline.get("suites") or {}
        cand_suites = candidate.get("suites") or {}
        for sname, cdata in cand_suites.items():
            if sname not in base_suites:
                continue
            b_sc = float((base_suites[sname] or {}).get("score", 0.0))
            c_sc = float((cdata or {}).get("score", 0.0))
            diff = round(c_sc - b_sc, 2)
            suite_deltas[sname] = diff
            if diff <= -SUITE_REGRESSION_DROP_PTS:
                regressions.append(
                    {
                        "scope": sname,
                        "metric": "suite_score",
                        "baseline": b_sc,
                        "candidate": c_sc,
                        "delta": diff,
                        "severity": "HIGH" if sname in ("aegis", "rag") else "MEDIUM",
                        "detail": f"Regresión en suite '{sname}' ({b_sc:.1f} -> {c_sc:.1f}, Δ={diff:+.1f} pts)",
                    }
                )

        if base_p95 > 0.0 and cand_p95 >= (base_p95 * P95_REGRESSION_RATIO) and p95_delta_ms >= P95_REGRESSION_MIN_DELTA_MS:
            regressions.append(
                {
                    "scope": "latency",
                    "metric": "p95_ms",
                    "baseline": base_p95,
                    "candidate": cand_p95,
                    "delta": p95_delta_ms,
                    "severity": "MEDIUM",
                    "detail": f"Degradación de latencia P95 ({base_p95:.1f} ms -> {cand_p95:.1f} ms)",
                }
            )

        return {
            "ok": True,
            "baseline_eval_id": str(baseline.get("eval_id") or ""),
            "candidate_eval_id": str(candidate.get("eval_id") or ""),
            "overall_delta": overall_delta,
            "p95_delta_ms": p95_delta_ms,
            "suite_deltas": suite_deltas,
            "has_regression": len(regressions) > 0,
            "regressions": regressions,
        }

    def compare_runs(
        self,
        baseline_eval_id: Optional[str] = None,
        candidate_eval_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        hist = self.history(limit=2)
        base = self.get_run(baseline_eval_id) if baseline_eval_id else self.get_latest_baseline()
        cand = self.get_run(candidate_eval_id) if candidate_eval_id else (hist[0] if hist else None)
        if base is None or cand is None:
            return {"ok": False, "error": "Se requieren al menos un baseline y una ejecución para comparar."}
        return self.compare_reports(base, cand)

    def run_eval(
        self,
        *,
        suites: Optional[Sequence[str]] = None,
        include_llm_judge: bool = False,
        tag: str = "manual",
        canary_run_id: str = "",
        persist: bool = True,
        publish_bus: bool = True,
        rag_vault: Optional[Any] = None,
        semantic_cache: Optional[Any] = None,
        latency_probe_fn: Optional[Callable[[str], Tuple[bool, float]]] = None,
        judge_fn: Optional[Callable[[str], str]] = None,
        use_live_llm_judge: bool = True,
        latency_samples: int = 3,
    ) -> Dict[str, Any]:
        """Ejecuta el harness completo, compara contra el último baseline y emite eventos al bus."""
        t0 = time.perf_counter()
        if suites is None:
            selected = list(DEFAULT_FAST_SUITES) + (["llm_judge"] if include_llm_judge else [])
        else:
            selected = [str(s).strip().lower() for s in suites if str(s).strip().lower() in ALL_SUITES]
            if include_llm_judge and "llm_judge" not in selected:
                selected.append("llm_judge")
        if not selected:
            selected = list(DEFAULT_FAST_SUITES)

        suite_results: Dict[str, Dict[str, Any]] = {}
        p50_pool: List[float] = []
        p95_pool: List[float] = []

        for sname in selected:
            if sname == "rag":
                res = _eval_rag_suite(rag_vault=rag_vault, semantic_cache=semantic_cache)
            elif sname == "aegis":
                res = _eval_aegis_suite()
            elif sname == "tool_calling":
                res = _eval_tool_calling_suite()
            elif sname == "latency":
                res = _eval_latency_suite(samples_per_target=latency_samples, probe_fn=latency_probe_fn)
            elif sname == "llm_judge":
                res = _eval_llm_judge_suite(judge_fn=judge_fn, use_live_llm=use_live_llm_judge)
            else:
                continue
            suite_results[sname] = res
            if float(res.get("p50_ms", 0.0)) > 0.0:
                p50_pool.append(float(res["p50_ms"]))
            if float(res.get("p95_ms", 0.0)) > 0.0:
                p95_pool.append(float(res["p95_ms"]))

        overall_score = round(
            sum(float(r.get("score", 0.0)) for r in suite_results.values()) / float(max(1, len(suite_results))),
            2,
        )
        p50_ms = _percentile(p50_pool, 50)
        p95_ms = _percentile(p95_pool, 95)

        eval_id = f"eval_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        now = time.time()
        iso = _now_iso()

        candidate_preview = {
            "eval_id": eval_id,
            "overall_score": overall_score,
            "p95_ms": p95_ms,
            "suites": suite_results,
        }
        baseline = self.get_latest_baseline() if tag != "baseline" else None
        delta_info: Dict[str, Any] = {}
        regressions: List[Dict[str, Any]] = []
        baseline_id = ""
        if baseline is not None:
            cmp_res = self.compare_reports(baseline, candidate_preview)
            baseline_id = str(baseline.get("eval_id") or "")
            delta_info = {
                "overall_delta": cmp_res["overall_delta"],
                "p95_delta_ms": cmp_res["p95_delta_ms"],
                "suite_deltas": cmp_res["suite_deltas"],
            }
            regressions = list(cmp_res.get("regressions") or [])

        passed = all(bool(r.get("ok")) for r in suite_results.values()) and (len(regressions) == 0)

        report: Dict[str, Any] = {
            "ok": True,
            "schema": "tardis.eval_harness.v1",
            "eval_id": eval_id,
            "ts": now,
            "iso": iso,
            "tag": tag,
            "canary_run_id": canary_run_id,
            "overall_score": overall_score,
            "passed": passed,
            "p50_ms": p50_ms,
            "p95_ms": p95_ms,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "baseline_eval_id": baseline_id,
            "delta": delta_info,
            "regressions": regressions,
            "suites": suite_results,
        }

        if persist:
            with self._lock:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO eval_runs (
                            eval_id, ts, iso, tag, canary_run_id,
                            overall_score, passed, p50_ms, p95_ms,
                            baseline_eval_id, regressions_count,
                            suites_json, delta_json, regressions_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            eval_id,
                            now,
                            iso,
                            tag,
                            canary_run_id,
                            overall_score,
                            1 if passed else 0,
                            p50_ms,
                            p95_ms,
                            baseline_id,
                            len(regressions),
                            json.dumps(suite_results, ensure_ascii=False),
                            json.dumps(delta_info, ensure_ascii=False),
                            json.dumps(regressions, ensure_ascii=False),
                        ),
                    )
                    # Retener últimos 500 runs para mantener la DB compacta
                    conn.execute(
                        "DELETE FROM eval_runs WHERE id NOT IN (SELECT id FROM eval_runs ORDER BY id DESC LIMIT 500)"
                    )

        if publish_bus and not self._is_isolated:
            try:
                from core.tardis_event_bus import get_event_bus

                if regressions:
                    get_event_bus().publish(
                        "eval.regression",
                        "tardis_eval_harness",
                        {
                            "eval_id": eval_id,
                            "baseline_eval_id": baseline_id,
                            "canary_run_id": canary_run_id,
                            "overall_score": overall_score,
                            "delta": delta_info,
                            "regressions": regressions,
                        },
                        severity="HIGH",
                        dedup_key=f"eval_reg|{eval_id}",
                        dedup_window_s=60.0,
                    )
                else:
                    get_event_bus().publish(
                        "eval.completed",
                        "tardis_eval_harness",
                        {
                            "eval_id": eval_id,
                            "tag": tag,
                            "overall_score": overall_score,
                            "passed": passed,
                            "p50_ms": p50_ms,
                            "p95_ms": p95_ms,
                        },
                        severity="INFO",
                        dedup_window_s=30.0,
                    )
            except Exception:
                pass

        return report

    def status(self) -> Dict[str, Any]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM eval_runs").fetchone()[0])
            reg_total = int(conn.execute("SELECT COUNT(*) FROM eval_runs WHERE regressions_count > 0").fetchone()[0])
            latest_row = conn.execute("SELECT * FROM eval_runs ORDER BY id DESC LIMIT 1").fetchone()
            base_row = conn.execute("SELECT * FROM eval_runs WHERE tag = 'baseline' ORDER BY id DESC LIMIT 1").fetchone()

        latest = self._row_to_dict(latest_row) if latest_row is not None else None
        baseline = self._row_to_dict(base_row) if base_row is not None else None
        return {
            "ok": True,
            "schema": "tardis.eval_harness.v1",
            "available_suites": list(ALL_SUITES),
            "db_path": str(self.db_path),
            "total_runs": total,
            "runs_with_regressions": reg_total,
            "baseline": (
                {
                    "eval_id": baseline["eval_id"],
                    "iso": baseline["iso"],
                    "overall_score": baseline["overall_score"],
                    "p95_ms": baseline["p95_ms"],
                }
                if baseline
                else None
            ),
            "latest": (
                {
                    "eval_id": latest["eval_id"],
                    "iso": latest["iso"],
                    "tag": latest["tag"],
                    "overall_score": latest["overall_score"],
                    "passed": latest["passed"],
                    "p50_ms": latest["p50_ms"],
                    "p95_ms": latest["p95_ms"],
                    "regressions_count": latest["regressions_count"],
                }
                if latest
                else None
            ),
        }


def get_eval_harness(db_path: Optional[Path] = None) -> TardisEvalHarness:
    return TardisEvalHarness.get_instance(db_path=db_path)


# ---------------------------------------------------------------------- CLI Soberana
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="tardis-eval",
        description="TARDIS Continuous Autonomous Eval & Regression Benchmark Harness",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Ejecutar suites de evaluación y comparar contra el baseline")
    p_run.add_argument("--suites", default="", help="Lista separada por comas: rag,aegis,tool_calling,latency,llm_judge")
    p_run.add_argument("--llm-judge", action="store_true", help="Incluir suite LLM-as-judge")
    p_run.add_argument("--tag", default="manual", help="Etiqueta del run (baseline, post_evolution, scheduled, manual)")
    p_run.add_argument("--canary-run-id", default="", help="run_id de tardis-canary asociado")
    p_run.add_argument("--no-persist", action="store_true")

    p_base = sub.add_parser("baseline", help="Ejecutar y fijar un nuevo golden baseline")
    p_base.add_argument("--llm-judge", action="store_true")

    p_cmp = sub.add_parser("compare", help="Comparar baseline vs candidato")
    p_cmp.add_argument("baseline_id", nargs="?", default=None)
    p_cmp.add_argument("candidate_id", nargs="?", default=None)

    p_hist = sub.add_parser("history", help="Listar ejecuciones históricas del harness")
    p_hist.add_argument("--limit", type=int, default=15)

    sub.add_parser("status", help="Resumen actual del harness, baseline y última evaluación")

    args = ap.parse_args(argv)
    harness = get_eval_harness()

    if args.cmd == "status":
        print(json.dumps(harness.status(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "history":
        print(json.dumps({"ok": True, "history": harness.history(limit=args.limit)}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "compare":
        res = harness.compare_runs(args.baseline_id, args.candidate_id)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") and not res.get("has_regression") else 1
    if args.cmd == "baseline":
        res = harness.run_eval(include_llm_judge=args.llm_judge, tag="baseline")
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("passed") else 1
    if args.cmd == "run":
        suite_list = [s.strip() for s in args.suites.split(",") if s.strip()] if args.suites else None
        res = harness.run_eval(
            suites=suite_list,
            include_llm_judge=args.llm_judge,
            tag=args.tag,
            canary_run_id=args.canary_run_id,
            persist=not args.no_persist,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("passed") else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
