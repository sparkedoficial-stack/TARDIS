#!/usr/bin/env python3
"""
GODWORKS · FTL Agent Orchestrator
=================================
Capa de control agéntico de FTL sobre TODOS los modelos gratuitos.

Permite:
  • Usar cada modelo de forma INDIVIDUAL (`run`).
  • Orquestar varios modelos bajo control de FTL (`orchestrate`):
      - auto      : enruta al especialista adecuado
      - single    : un solo agente
      - fanout    : todos en paralelo + juez que sintetiza
      - compare   : todos en paralelo, respuestas lado a lado
      - pipeline  : planificador → constructor → revisor
      - race      : carrera secuencial por latencia (primer éxito gana)
  • Control: kill switch, concurrencia máxima, timeouts, presupuesto de
    caracteres, allow/deny por modelo, verificación obligatoria, auditoría JSONL
    y métricas por modelo.

Estado:  ~/.config/ftl/orchestrator/{policy.json,state.json,audit.jsonl}
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, Optional

import free_models as fm
import runtime_env

ORCH_DIR = Path.home() / ".config" / "ftl" / "orchestrator"
POLICY_FILE = ORCH_DIR / "policy.json"
STATE_FILE = ORCH_DIR / "state.json"
AUDIT_FILE = ORCH_DIR / "audit.jsonl"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

DEFAULT_POLICY = {
    "enabled": True,
    "kill_switch": False,
    "max_concurrency": 4,
    "max_agents": 8,
    "default_timeout": 300,
    "max_prompt_chars": 120000,
    "max_output_chars": 200000,
    "allowed_models": ["*"],
    "denied_models": ["nemotron-ultra"],
    "require_verified": True,
    "audit_enabled": True,
    "workdir": "",
    "default_strategy": "auto",
}

STRATEGIES = ("auto", "single", "fanout", "compare", "pipeline", "race")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _clean(text: str) -> str:
    clean = ANSI_RE.sub("", text or "")
    return "\n".join(
        line for line in clean.splitlines()
        if not line.strip().startswith("> build ·")
    ).strip()


def _atomic_write(path: Path, data: dict, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


class OrchestratorHalt(RuntimeError):
    """Se lanza cuando el kill switch o el control de política bloquean la ejecución."""


class AgentOrchestrator:
    def __init__(self):
        self._lock = threading.RLock()
        ORCH_DIR.mkdir(parents=True, exist_ok=True)
        self.policy = self._load_policy()
        self.state = self._load_state()

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    def _load_policy(self) -> dict:
        policy = dict(DEFAULT_POLICY)
        try:
            raw = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                policy.update(raw)
        except Exception:
            _atomic_write(POLICY_FILE, policy)
        return policy

    def save_policy(self) -> None:
        _atomic_write(POLICY_FILE, self.policy)

    def _load_state(self) -> dict:
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw.setdefault("by_model", {})
                raw.setdefault("runs", 0)
                return raw
        except Exception:
            pass
        return {"runs": 0, "by_model": {}, "last_run": None, "created_at": _now()}

    def _save_state(self) -> None:
        _atomic_write(STATE_FILE, self.state)

    def _audit(self, record: dict) -> None:
        if not self.policy.get("audit_enabled", True):
            return
        try:
            ORCH_DIR.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    def set_policy(self, key: str, value) -> bool:
        if key not in DEFAULT_POLICY:
            return False
        if key in ("max_concurrency", "max_agents"):
            try:
                value = max(1, int(value))
            except Exception:
                return False
        elif key == "default_timeout":
            try:
                value = max(15, int(value))
            except Exception:
                return False
        elif key in ("max_prompt_chars", "max_output_chars"):
            try:
                value = max(64, int(value))
            except Exception:
                return False
        elif key in ("enabled", "kill_switch", "require_verified", "audit_enabled"):
            if isinstance(value, str):
                value = value.strip().lower() not in ("0", "off", "false", "no", "disabled", "no")
            else:
                value = bool(value)
        elif key == "default_strategy":
            value = str(value).strip().lower()
            if value not in STRATEGIES:
                return False
        elif key == "allowed_models":
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            elif isinstance(value, (list, tuple)):
                value = [str(v).strip() for v in value if str(v).strip()]
            else:
                return False
            value = value or ["*"]
        elif key == "denied_models":
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            elif isinstance(value, (list, tuple)):
                value = [str(v).strip() for v in value if str(v).strip()]
            else:
                return False
        elif key == "workdir":
            value = str(value) if value else ""
        self.policy[key] = value
        self.save_policy()
        return True

    def set_kill_switch(self, active: bool) -> None:
        self.set_policy("kill_switch", bool(active))

    def toggle_model(self, token: str, enabled: bool) -> bool:
        model = fm.resolve(token)
        if not model:
            return False
        fm.set_enabled(model.key, enabled)
        denied = set(self.policy.get("denied_models", []))
        if enabled:
            denied.discard(model.key)
        else:
            denied.add(model.key)
        self.policy["denied_models"] = sorted(denied)
        self.save_policy()
        return True

    def _check_ready(self) -> None:
        if not self.policy.get("enabled", True):
            raise OrchestratorHalt("Orquestador deshabilitado por política.")
        if self.policy.get("kill_switch"):
            raise OrchestratorHalt("KILL SWITCH ACTIVO: ejecución de agentes bloqueada.")

    # ------------------------------------------------------------------
    # Selección de modelos
    # ------------------------------------------------------------------
    def _allowed(self, model: fm.FreeModel) -> bool:
        allowed = self.policy.get("allowed_models", ["*"])
        denied = set(self.policy.get("denied_models", []))
        if model.key in denied:
            return False
        if "*" in allowed or model.key in allowed or model.ref in allowed:
            return True
        return False

    def select(self, tokens: Optional[Iterable[str]] = None,
               max_agents: Optional[int] = None) -> list[fm.FreeModel]:
        limit = int(max_agents or self.policy.get("max_agents", 8))
        limit = max(1, min(limit, int(self.policy.get("max_agents", 8))))

        if tokens:
            models: list[fm.FreeModel] = []
            for token in tokens:
                if not str(token).strip():
                    continue
                model = fm.resolve(str(token))
                if not model:
                    raise ValueError(f"Modelo desconocido: {token}")
                models.append(model)
        else:
            models = fm.available_models() or fm.pool_models()

        filtered = [m for m in models if self._allowed(m)]
        if self.policy.get("require_verified", True):
            verified = [m for m in filtered if fm.model_state(m.key).get("available") is True]
            # Si aún no hay sondas, no bloqueamos el trabajo.
            if verified:
                filtered = verified

        # Deduplicar preservando prioridad
        seen, unique = set(), []
        for m in sorted(filtered, key=lambda x: x.priority):
            if m.key not in seen:
                seen.add(m.key)
                unique.append(m)
        if not unique:
            raise OrchestratorHalt("No hay modelos disponibles que cumplan la política.")
        return unique[:limit]

    # ------------------------------------------------------------------
    # Ejecución de un agente
    # ------------------------------------------------------------------
    def _workdir(self, override: Optional[str] = None) -> str:
        candidate = override or self.policy.get("workdir") or os.getcwd()
        path = Path(candidate).expanduser()
        return str(path if path.is_dir() else Path.cwd())

    def run(
        self,
        token: str,
        prompt: str,
        role: str = "agente",
        timeout: Optional[int] = None,
        workdir: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> dict:
        self._check_ready()
        model = fm.resolve(token)
        if not model:
            raise ValueError(f"Modelo desconocido: {token}")
        if not self._allowed(model):
            raise OrchestratorHalt(f"Modelo '{model.key}' denegado por política.")

        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("Prompt vacío.")
        max_chars = int(self.policy.get("max_prompt_chars", 120000))
        if len(prompt) > max_chars:
            raise ValueError(f"Prompt excede el presupuesto ({len(prompt)} > {max_chars} caracteres).")

        exe = runtime_env.which("opencode")
        if not exe:
            raise OrchestratorHalt(
                "No se encontró el binario 'opencode'. Añade ~/.opencode/bin al PATH "
                "o ejecuta `ftl --heal`."
            )
        ref = model.ref
        full_prompt = (
            "=== [FTL AGENT ORCHESTRATOR :: AGENTE CONTROLADO] ===\n"
            f"Rol asignado: {role}\n"
            f"Modelo: {model.name} ({ref})\n"
            "Operas bajo la soberanía de FTL. Entrega la respuesta final directamente, "
            "sin meta-comentarios de coordinación.\n"
            "=== [TAREA] ===\n"
            f"{prompt}"
        )

        rid = run_id or uuid.uuid4().hex[:12]
        started = time.time()
        timeout = int(timeout or self.policy.get("default_timeout", 300))
        cwd = self._workdir(workdir)
        rec = {
            "run_id": rid, "model": model.key, "ref": ref, "role": role,
            "started_at": _now(), "timeout_s": timeout, "workdir": cwd,
            "prompt_chars": len(full_prompt), "ok": False, "rc": None,
            "duration_s": 0.0, "output_chars": 0, "error": "",
        }

        proc = None
        try:
            proc = subprocess.Popen(
                [exe, "run", "-m", ref, "--auto", full_prompt],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, stdin=subprocess.DEVNULL, cwd=cwd,
                start_new_session=True,
                env=runtime_env.augment_path({**os.environ, "PYTHONUNBUFFERED": "1"}),
            )
            out, _ = proc.communicate(timeout=timeout)
            text = _clean(out)
            max_out = int(self.policy.get("max_output_chars", 200000))
            if len(text) > max_out:
                text = text[:max_out] + "\n… [salida truncada por política]"
            rec["rc"] = proc.returncode
            rec["ok"] = proc.returncode == 0 and bool(text)
            rec["output"] = text
            rec["output_chars"] = len(text)
            if not rec["ok"]:
                rec["error"] = text[:400] or f"rc={proc.returncode} sin salida"
        except subprocess.TimeoutExpired:
            if proc:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    proc.communicate(timeout=5)
                except Exception:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        pass
            rec["rc"] = 124
            rec["error"] = f"timeout tras {timeout}s"
            rec["output"] = ""
        except Exception as exc:
            rec["rc"] = -1
            rec["error"] = str(exc)[:400]
            rec["output"] = ""
        finally:
            rec["duration_s"] = round(time.time() - started, 2)
            with self._lock:
                self._record(rec)
        return rec

    def _record(self, rec: dict) -> None:
        key = rec.get("model", "?")
        stats = self.state.setdefault("by_model", {}).setdefault(
            key, {"runs": 0, "ok": 0, "fail": 0, "total_s": 0.0}
        )
        stats["runs"] += 1
        stats["ok" if rec.get("ok") else "fail"] += 1
        stats["total_s"] = round(stats.get("total_s", 0.0) + rec.get("duration_s", 0.0), 2)
        self.state["runs"] = int(self.state.get("runs", 0)) + 1
        self.state["last_run"] = {k: v for k, v in rec.items() if k != "output"}
        self._save_state()
        self._audit({k: v for k, v in rec.items() if k != "output"} | {"event": "agent_run"})

    # ------------------------------------------------------------------
    # Orquestación
    # ------------------------------------------------------------------
    def orchestrate(
        self,
        task: str,
        strategy: str = "auto",
        models: Optional[Iterable[str]] = None,
        max_agents: Optional[int] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> dict:
        self._check_ready()
        strategy = (strategy or "auto").lower().strip()
        if strategy not in STRATEGIES:
            raise ValueError(f"Estrategia inválida: {strategy}. Válidas: {', '.join(STRATEGIES)}")
        if not (task or "").strip():
            raise ValueError("Tarea vacía.")

        run_id = uuid.uuid4().hex[:12]
        t0 = time.time()

        def progress(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        if strategy == "auto":
            specialist = fm.specialist_for(task)
            if not self._allowed(specialist):
                candidates = self.select(models, max_agents)
                specialist = candidates[0]
            progress(f"🧭 FTL Orquestador: especialista seleccionado → {specialist.name}")
            result = self.run(specialist.key, task, role="especialista", run_id=run_id)
            return self._finish(run_id, strategy, task, [result], None, t0)

        if strategy == "single":
            chosen = self.select(models, max_agents)[0]
            progress(f"🎯 FTL Orquestador: agente único → {chosen.name}")
            result = self.run(chosen.key, task, role="agente único", run_id=run_id)
            return self._finish(run_id, strategy, task, [result], None, t0)

        if strategy == "race":
            return self._race(run_id, task, models, max_agents, progress, t0)

        if strategy == "pipeline":
            return self._pipeline(run_id, task, models, max_agents, progress, t0)

        # fanout / compare
        candidates = self.select(models, max_agents)
        progress(f"🕸️ FTL Orquestador: {len(candidates)} agentes en paralelo → "
                 + ", ".join(m.key for m in candidates))
        results = self._parallel(run_id, task, candidates, progress)

        if strategy == "compare":
            return self._finish(run_id, strategy, task, results, None, t0)

        synthesis = self._synthesize(run_id, task, results, progress)
        return self._finish(run_id, strategy, task, results, synthesis, t0)

    def _parallel(self, run_id: str, task: str, candidates: list[fm.FreeModel],
                  progress: Callable[[str], None]) -> list[dict]:
        concurrency = max(1, min(int(self.policy.get("max_concurrency", 4)), len(candidates)))
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(
                    self.run, m.key, task, role=f"agente-{m.key}",
                    run_id=f"{run_id}-{m.key[:8]}",
                ): m for m in candidates
            }
            for fut in as_completed(futures):
                model = futures[fut]
                try:
                    rec = fut.result()
                except Exception as exc:
                    rec = {"model": model.key, "ref": model.ref, "role": f"agente-{model.key}",
                           "ok": False, "error": str(exc)[:300], "output": "", "duration_s": 0.0}
                results.append(rec)
                progress(f"   {'✓' if rec.get('ok') else '✗'} {model.key} "
                         f"({rec.get('duration_s', 0)}s)")
        return sorted(results, key=lambda r: (not r.get("ok"), r.get("model", "")))

    def _race(self, run_id: str, task: str, models, max_agents, progress, t0) -> dict:
        candidates = self.select(models, max_agents)
        # Orden por latencia observada (los más rápidos primero).
        def latency(m: fm.FreeModel) -> float:
            return float(fm.model_state(m.key).get("latency_s") or 999)
        candidates.sort(key=latency)
        results = []
        for model in candidates:
            progress(f"🏁 Carrera: probando {model.name}…")
            rec = self.run(model.key, task, role="carrera", run_id=f"{run_id}-{model.key[:8]}")
            results.append(rec)
            if rec.get("ok"):
                break
        return self._finish(run_id, "race", task, results, None, t0)

    def _pipeline(self, run_id: str, task: str, models, max_agents, progress, t0) -> dict:
        candidates = self.select(models, max_agents)
        if len(candidates) < 3:
            picks = (candidates + candidates + candidates)[:3]
        else:
            picks = candidates[:3]

        planner, builder, reviewer = picks[0], picks[1], picks[2]
        steps: list[dict] = []

        progress(f"🧠 Fase 1/3 · Planificación → {planner.name}")
        plan_rec = self.run(
            planner.key,
            f"Diseña el plan de ejecución para esta tarea, en pasos concretos y verificables:\n\n{task}",
            role="planificador", run_id=f"{run_id}-plan",
        )
        steps.append(plan_rec)

        progress(f"🛠️ Fase 2/3 · Implementación → {builder.name}")
        build_rec = self.run(
            builder.key,
            f"Ejecuta la tarea usando este plan. Entrega el resultado completo y listo para usar.\n\n"
            f"TAREA:\n{task}\n\nPLAN:\n{plan_rec.get('output', '')[:8000]}",
            role="constructor", run_id=f"{run_id}-build",
        )
        steps.append(build_rec)

        progress(f"🔍 Fase 3/3 · Revisión → {reviewer.name}")
        review_rec = self.run(
            reviewer.key,
            f"Revisa críticamente el resultado. Detecta errores, omisiones o riesgos y entrega "
            f"la versión final corregida.\n\nTAREA:\n{task}\n\nRESULTADO:\n{build_rec.get('output', '')[:12000]}",
            role="revisor", run_id=f"{run_id}-review",
        )
        steps.append(review_rec)

        final = {
            "ok": bool(review_rec.get("ok") or build_rec.get("ok")),
            "provider": review_rec.get("model") if review_rec.get("ok") else build_rec.get("model"),
            "ref": review_rec.get("ref") if review_rec.get("ok") else build_rec.get("ref"),
            "output": review_rec.get("output") or build_rec.get("output") or plan_rec.get("output", ""),
            "phases": [
                {"phase": "plan", "model": planner.key, "ok": plan_rec.get("ok")},
                {"phase": "build", "model": builder.key, "ok": build_rec.get("ok")},
                {"phase": "review", "model": reviewer.key, "ok": review_rec.get("ok")},
            ],
        }
        return self._finish(run_id, "pipeline", task, steps, final, t0)

    def _synthesize(self, run_id: str, task: str, results: list[dict],
                    progress: Callable[[str], None]) -> dict:
        valid = [r for r in results if r.get("ok") and r.get("output")]
        if not valid:
            return {"ok": False, "output": "", "model": None, "ref": None,
                    "error": "Ningún agente produjo salida válida."}
        if len(valid) == 1:
            return {"ok": True, "output": valid[0]["output"], "model": valid[0]["model"],
                    "ref": valid[0].get("ref"), "judge": False}

        judge = fm.resolve("deepseek")
        if not judge or not self._allowed(judge):
            judge = next((m for m in self.select(None, 1) if m.key != valid[0]["model"]), None)
        if not judge:
            return {"ok": True, "output": "\n\n".join(
                f"### {r['model']}\n{r['output']}" for r in valid), "model": None, "ref": None,
                "judge": False}

        progress(f"⚖️ Síntesis final → {judge.name}")
        blocks = "\n\n".join(
            f"--- RESPUESTA DE {r['model']} ({r.get('ref','')}) ---\n{r['output'][:9000]}"
            for r in valid
        )
        judge_rec = self.run(
            judge.key,
            "Eres el juez-orquestador de FTL. Sintetiza la mejor respuesta final a partir de "
            "las respuestas de los agentes. Corrige contradicciones, integra lo mejor de cada una "
            "y entrega una sola respuesta definitiva, sin mencionar el proceso interno.\n\n"
            f"TAREA ORIGINAL:\n{task}\n\n{blocks}",
            role="juez", run_id=f"{run_id}-judge",
        )
        if judge_rec.get("ok") and judge_rec.get("output"):
            return {"ok": True, "output": judge_rec["output"], "model": judge.key,
                    "ref": judge.ref, "judge": True}
        return {"ok": True, "output": "\n\n".join(
            f"### {r['model']}\n{r['output']}" for r in valid), "model": None,
            "ref": None, "judge": False}

    def _finish(self, run_id: str, strategy: str, task: str, results: list[dict],
                synthesis: Optional[dict], t0: float) -> dict:
        valid = [r for r in results if r.get("ok")]
        if synthesis and synthesis.get("ok"):
            output = synthesis["output"]
            winner = synthesis.get("model") or synthesis.get("provider")
            ok = True
        elif valid:
            output = valid[0].get("output", "")
            winner = valid[0].get("model")
            ok = True
        else:
            output = ""
            winner = None
            ok = False

        payload = {
            "ok": ok,
            "run_id": run_id,
            "strategy": strategy,
            "task": task[:500],
            "agents": [
                {k: v for k, v in r.items() if k in
                 ("model", "ref", "role", "ok", "rc", "duration_s", "output_chars", "error")}
                for r in results
            ],
            "winner": winner,
            "synthesis": synthesis if synthesis else None,
            "output": output,
            "elapsed_s": round(time.time() - t0, 2),
            "agents_used": len(results),
            "agents_ok": len(valid),
        }
        with self._lock:
            self.state["last_run"] = {k: v for k, v in payload.items() if k != "output"}
            self._save_state()
            self._audit({"event": "orchestration", "run_id": run_id, "strategy": strategy,
                         "agents": payload["agents"], "winner": winner,
                         "agents_ok": len(valid), "elapsed_s": payload["elapsed_s"]})
        return payload

    # ------------------------------------------------------------------
    # Introspección
    # ------------------------------------------------------------------
    def status(self) -> dict:
        return {
            "policy": self.policy,
            "catalog": fm.summary(),
            "state": {
                "runs": self.state.get("runs", 0),
                "by_model": self.state.get("by_model", {}),
                "last_run": self.state.get("last_run"),
            },
        }

    def history(self, limit: int = 20) -> list[dict]:
        try:
            lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        records = []
        for line in lines[-max(1, limit):]:
            try:
                records.append(json.loads(line))
            except Exception:
                continue
        return records


orchestrator = AgentOrchestrator()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(orchestrator.status(), indent=2, ensure_ascii=False))
    elif cmd == "history":
        print(json.dumps(orchestrator.history(20), indent=2, ensure_ascii=False))
    elif cmd == "run" and len(sys.argv) >= 4:
        print(json.dumps(orchestrator.run(sys.argv[2], " ".join(sys.argv[3:])),
                         indent=2, ensure_ascii=False))
    elif cmd == "orchestrate" and len(sys.argv) >= 4:
        print(json.dumps(orchestrator.orchestrate(" ".join(sys.argv[3:]), strategy=sys.argv[2]),
                         indent=2, ensure_ascii=False))
    else:
        print(__doc__)
