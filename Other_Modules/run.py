"""Reproducible first experiment: causal prompt chaining vs untracked prompting.

Usage:
    python -m experiments.causal_prompt_chaining.run --seed 42
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.causal_prompt_graph import TAGS, CausalPromptGraph
from experiments.causal_prompt_chaining.world import (
    CodingTask,
    compile_code,
    make_tasks,
    noisy_error_class,
    render_code,
)

DEFAULT_SEED = 42
TRAIN_TASKS = 48
TEST_TASKS = 80
MAX_ITERS = 8
ERROR_NOISE = 0.15
REDUCTION_TARGET = 0.30


@dataclass
class TrialResult:
    policy: str
    task_id: int
    required_tag: str
    attempts: int
    failed_attempts: int
    solved: bool
    tags_tried: List[str]


def _attempt(task: CodingTask, tag: str, rng: random.Random, noise: float):
    code = render_code(task.required_tag, tag)
    compiled, err, true_class = compile_code(code)
    observed = noisy_error_class(true_class, rng, noise)
    return compiled, err, observed


def run_untracked_task(task: CodingTask, rng: random.Random, max_iters: int, noise: float) -> TrialResult:
    tried: List[str] = []
    for attempt in range(1, max_iters + 1):
        tag = TAGS[rng.randrange(len(TAGS))]
        tried.append(tag)
        compiled, _, _ = _attempt(task, tag, rng, noise)
        if compiled:
            return TrialResult("untracked", task.task_id, task.required_tag, attempt, attempt - 1, True, tried)
    return TrialResult("untracked", task.task_id, task.required_tag, max_iters, max_iters, False, tried)


def run_causal_task(
    task: CodingTask,
    graph: CausalPromptGraph,
    rng: random.Random,
    max_iters: int,
    noise: float,
) -> TrialResult:
    tried: List[str] = []
    last_error = "other"
    for attempt in range(1, max_iters + 1):
        if attempt == 1:
            tag = TAGS[rng.randrange(len(TAGS))]
        else:
            tag = graph.suggest_tag(last_error, tried)
        tried.append(tag)
        compiled, err, observed = _attempt(task, tag, rng, noise)
        graph.observe((tag,), compiled, observed)
        if compiled:
            return TrialResult("causal", task.task_id, task.required_tag, attempt, attempt - 1, True, tried)
        last_error = observed
    return TrialResult("causal", task.task_id, task.required_tag, max_iters, max_iters, False, tried)


def warmup(graph: CausalPromptGraph, tasks: List[CodingTask], rng: random.Random, noise: float) -> None:
    for task in tasks:
        tag = TAGS[rng.randrange(len(TAGS))]
        compiled, _, observed = _attempt(task, tag, rng, noise)
        graph.observe((tag,), compiled, observed)


def mean_ci(values: List[float]) -> Dict[str, float]:
    n = len(values)
    mu = statistics.fmean(values)
    if n < 2:
        return {"n": n, "mean": mu, "sd": 0.0, "se": 0.0, "ci95_low": mu, "ci95_high": mu}
    sd = statistics.stdev(values)
    se = sd / math.sqrt(n)
    return {
        "n": n,
        "mean": mu,
        "sd": sd,
        "se": se,
        "ci95_low": mu - 1.96 * se,
        "ci95_high": mu + 1.96 * se,
    }


def analyze(control: List[TrialResult], treatment: List[TrialResult]) -> Dict[str, object]:
    c_fail = [float(t.failed_attempts) for t in control]
    t_fail = [float(t.failed_attempts) for t in treatment]
    c_stats = mean_ci(c_fail)
    t_stats = mean_ci(t_fail)
    reduction = (c_stats["mean"] - t_stats["mean"]) / c_stats["mean"] if c_stats["mean"] else 0.0
    # Unpaired z on means (first-experiment approximation; trials are independent by construction).
    se_diff = math.sqrt(c_stats["se"] ** 2 + t_stats["se"] ** 2)
    z = (c_stats["mean"] - t_stats["mean"]) / se_diff if se_diff else 0.0
    return {
        "control_failed_attempts": c_stats,
        "treatment_failed_attempts": t_stats,
        "relative_reduction": reduction,
        "z_mean_diff": z,
        "control_solve_rate": sum(t.solved for t in control) / len(control),
        "treatment_solve_rate": sum(t.solved for t in treatment) / len(treatment),
        "hypothesis_30pct_supported": reduction >= REDUCTION_TARGET and z >= 1.96,
    }


def run_experiment(
    seed: int = DEFAULT_SEED,
    train_tasks: int = TRAIN_TASKS,
    test_tasks: int = TEST_TASKS,
    max_iters: int = MAX_ITERS,
    noise: float = ERROR_NOISE,
) -> Dict[str, object]:
    train = make_tasks(train_tasks, seed)
    test = make_tasks(test_tasks, seed + 1)

    graph = CausalPromptGraph()
    warm_rng = random.Random(seed)
    warmup(graph, train, warm_rng, noise)

    control_rng = random.Random(seed + 11)
    treat_rng = random.Random(seed + 13)
    control = [run_untracked_task(task, control_rng, max_iters, noise) for task in test]
    treatment = [run_causal_task(task, graph, treat_rng, max_iters, noise) for task in test]
    summary = analyze(control, treatment)
    payload = {
        "hypothesis": (
            "If AutonomousCoder tracks prompt-tag → compile-outcome edges and uses them "
            "to rewrite the next prompt, failed compile iterations on held-out tasks drop "
            "by at least 30% versus untracked random prompting."
        ),
        "seed": seed,
        "method": {
            "compiler": "AutonomousCoder._validate_syntax",
            "train_tasks": train_tasks,
            "test_tasks": test_tasks,
            "max_iters": max_iters,
            "error_label_noise": noise,
            "control": "uniform random prompt tag each iteration",
            "treatment": "Laplace causal graph; first tag random, later tags suggested from last error class",
        },
        "expected_result": {
            "relative_reduction_gte": REDUCTION_TARGET,
            "direction": "treatment mean failed_attempts < control",
        },
        "analysis": summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "control_trials": [asdict(t) for t in control],
        "treatment_trials": [asdict(t) for t in treatment],
        "graph": graph.to_dict(),
    }
    return payload


def write_results(payload: Dict[str, object], path: Optional[Path] = None) -> Path:
    out = path or (ROOT / "data" / "experiments" / "causal_prompt_chaining_seed{}.json".format(payload["seed"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    slim = dict(payload)
    # Keep the on-disk report readable; full trials stay in the returned payload for tests.
    slim["control_trials"] = payload["control_trials"]
    slim["treatment_trials"] = payload["treatment_trials"]
    out.write_text(json.dumps(slim, indent=2), encoding="utf-8")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Causal prompt chaining first experiment")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--train-tasks", type=int, default=TRAIN_TASKS)
    parser.add_argument("--test-tasks", type=int, default=TEST_TASKS)
    parser.add_argument("--max-iters", type=int, default=MAX_ITERS)
    parser.add_argument("--noise", type=float, default=ERROR_NOISE)
    args = parser.parse_args(argv)
    payload = run_experiment(
        seed=args.seed,
        train_tasks=args.train_tasks,
        test_tasks=args.test_tasks,
        max_iters=args.max_iters,
        noise=args.noise,
    )
    path = write_results(payload)
    analysis = payload["analysis"]
    print(json.dumps({
        "results_path": str(path),
        "seed": payload["seed"],
        "relative_reduction": analysis["relative_reduction"],
        "hypothesis_30pct_supported": analysis["hypothesis_30pct_supported"],
        "control_mean_failed": analysis["control_failed_attempts"]["mean"],
        "treatment_mean_failed": analysis["treatment_failed_attempts"]["mean"],
        "z_mean_diff": analysis["z_mean_diff"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
