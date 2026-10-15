"""Seeded synthetic coding world compiled by AutonomousCoder._validate_syntax."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from core.autonomous_coder import get_autonomous_coder
from core.causal_prompt_graph import TAGS, classify_syntax_error

TAG_TO_ERROR = {
    "fix_imports": "ImportSyntax",
    "fix_parens": "UnclosedParen",
    "fix_indent": "Indent",
    "fix_quotes": "UnclosedString",
}

BROKEN_SNIPPETS: Dict[str, str] = {
    "fix_imports": "from import os\n",
    "fix_parens": "def value():\n    return (1\n",
    "fix_indent": "def value():\nreturn 1\n",
    "fix_quotes": 'def value():\n    return "hello\n',
}

VALID_SNIPPET = "def value():\n    return 1\n"

ERROR_TO_TAG = {error: tag for tag, error in TAG_TO_ERROR.items()}


@dataclass(frozen=True)
class CodingTask:
    task_id: int
    required_tag: str


def make_tasks(n: int, seed: int) -> List[CodingTask]:
    # Deterministic round-robin so train/test splits stay balanced.
    tasks = []
    for i in range(n):
        tag = TAGS[(i + seed) % len(TAGS)]
        tasks.append(CodingTask(task_id=i, required_tag=tag))
    return tasks


def render_code(required_tag: str, chosen_tag: str) -> str:
    if chosen_tag == required_tag:
        return VALID_SNIPPET
    return BROKEN_SNIPPETS[required_tag]


def compile_code(code: str) -> Tuple[bool, str, str]:
    coder = get_autonomous_coder()
    ok, err = coder._validate_syntax(Path("experiment_snippet.py"), code)
    error_class = "ok" if ok else classify_syntax_error(err)
    return ok, err, error_class


def noisy_error_class(true_class: str, rng, noise: float) -> str:
    if true_class == "ok" or rng.random() >= noise:
        return true_class
    others = [c for c in TAG_TO_ERROR.values() if c != true_class]
    return others[rng.randrange(len(others))]
