"""Tests de la red de 5 divisiones del Frontier Lab (TARDIS)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tardis_frontier_lab import DIVISIONS, FrontierLab


def test_schema_and_blackboard(tmp_path: Path) -> None:
    lab = FrontierLab(db_path=tmp_path / "lab.db")
    lab._blackboard_set("demo", {"x": 1})
    assert lab.blackboard_get("demo") == {"x": 1}

    with sqlite3.connect(tmp_path / "lab.db") as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"cycles", "findings", "proposals", "metrics", "negative_results", "blackboard"} <= tables


def test_run_division_persists_cycle(tmp_path: Path) -> None:
    lab = FrontierLab(db_path=tmp_path / "lab.db")
    out = lab.run_division("silicon")
    assert out["ok"] is True
    assert out["division"] == "silicon"

    with sqlite3.connect(tmp_path / "lab.db") as con:
        row = con.execute("SELECT division, status FROM cycles ORDER BY id DESC LIMIT 1").fetchone()
    assert row == ("silicon", "OK")


def test_status_shape(tmp_path: Path) -> None:
    lab = FrontierLab(db_path=tmp_path / "lab.db")
    lab.run_division("memory")
    status = lab.status()
    assert status["ok"] is True
    assert status["counts"]["cycles"] >= 1
    assert isinstance(status["last_cycles"], list)


def test_all_divisions_declared() -> None:
    assert set(DIVISIONS) == {
        "silicon", "abstraction", "skills", "memory", "self_improvement"
    }
    for meta in DIVISIONS.values():
        assert meta["label"] and meta["task_class"]
