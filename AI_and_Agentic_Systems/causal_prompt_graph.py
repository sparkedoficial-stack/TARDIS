"""Causal prompt graph: prompt features → compile outcomes.

Records discrete prompt tags against compile success/error class and
suggests the next tag to try. Used by the first causal-prompt-chaining
experiment and as an optional observer on AutonomousCoder.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GRAPH_PATH = PROJECT_ROOT / "data" / "causal_prompt_graph.json"

TAGS: Tuple[str, ...] = ("fix_imports", "fix_parens", "fix_indent", "fix_quotes")
ERROR_CLASSES: Tuple[str, ...] = ("ImportSyntax", "UnclosedParen", "Indent", "UnclosedString", "ok", "other")


def classify_syntax_error(message: str) -> str:
    text = (message or "").lower()
    if not message:
        return "ok"
    if "import" in text:
        return "ImportSyntax"
    if "never closed" in text or "unmatched" in text or "was never closed" in text:
        return "UnclosedParen"
    if "indent" in text:
        return "Indent"
    if "unterminated" in text or "eol while scanning" in text:
        return "UnclosedString"
    # CPython reports `from import os` as bare "invalid syntax" (no "import" in the msg).
    if "invalid syntax" in text:
        return "ImportSyntax"
    return "other"


def extract_tags_from_text(text: str) -> Tuple[str, ...]:
    found = [tag for tag in TAGS if tag in (text or "").lower()]
    return tuple(found)


@dataclass(frozen=True)
class GraphObservation:
    tags: Tuple[str, ...]
    error_class: str
    compiled: bool
    timestamp: str


class CausalPromptGraph:
    """Laplace-smoothed counts of (error_class, tag) → {success, fail}."""

    def __init__(self, smoothing: float = 1.0) -> None:
        self.smoothing = float(smoothing)
        self._success: DefaultDict[str, DefaultDict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._fail: DefaultDict[str, DefaultDict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.history: List[GraphObservation] = []

    def observe(
        self,
        tags: Iterable[str],
        compiled: bool,
        error_class: str,
        timestamp: Optional[str] = None,
    ) -> None:
        tag_tuple = tuple(t for t in tags if t in TAGS)
        klass = error_class if error_class in ERROR_CLASSES else "other"
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        self.history.append(GraphObservation(tag_tuple, klass, compiled, ts))
        bucket = self._success if compiled else self._fail
        context = "ok" if compiled else klass
        if not tag_tuple:
            bucket[context]["_none"] += 1
            return
        for tag in tag_tuple:
            bucket[context][tag] += 1

    def observe_text(self, prompt: str, compiled: bool, error: Optional[str]) -> None:
        tags = extract_tags_from_text(prompt)
        klass = "ok" if compiled else classify_syntax_error(error or "")
        self.observe(tags, compiled, klass)

    def p_success_given(self, error_class: str, tag: str) -> float:
        s = self._success[error_class][tag] + self._success["ok"][tag]
        f = self._fail[error_class][tag]
        # Also credit global success of the tag (helps transfer).
        s_global = sum(self._success[k][tag] for k in self._success)
        f_global = sum(self._fail[k][tag] for k in self._fail)
        alpha = self.smoothing
        return (s + 0.25 * s_global + alpha) / (s + f + 0.25 * (s_global + f_global) + 2 * alpha)

    def p_error_given(self, error_class: str, tag: str) -> float:
        f = self._fail[error_class][tag]
        s = self._success[error_class][tag] + self._success["ok"][tag]
        alpha = self.smoothing
        return (f + alpha) / (s + f + 2 * alpha)

    def suggest_tag(
        self,
        last_error_class: str,
        tried: Sequence[str],
        available: Sequence[str] = TAGS,
    ) -> str:
        """Pick the unused tag with the best success-minus-error score for this failure."""
        remaining = [t for t in available if t not in tried]
        if not remaining:
            remaining = list(available)
        scored = []
        for tag in remaining:
            score = self.p_success_given(last_error_class, tag) - self.p_error_given(last_error_class, tag)
            scored.append((score, tag))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][1]

    def to_dict(self) -> Dict[str, object]:
        return {
            "smoothing": self.smoothing,
            "success": {k: dict(v) for k, v in self._success.items()},
            "fail": {k: dict(v) for k, v in self._fail.items()},
            "n_observations": len(self.history),
        }

    def save(self, path: Path = GRAPH_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


_GRAPH: Optional[CausalPromptGraph] = None


def get_causal_prompt_graph() -> CausalPromptGraph:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = CausalPromptGraph()
    return _GRAPH
