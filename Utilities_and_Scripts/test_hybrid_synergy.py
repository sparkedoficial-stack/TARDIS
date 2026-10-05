#!/usr/bin/env python3
"""
tests/test_hybrid_synergy.py - Pruebas de la Matriz de Sinergia Híbrida de Modelos e Ingenierías
"""

import pytest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tardis_hybrid_synergy import get_tardis_hybrid_synergy


def test_hybrid_synergy_initialization():
    syn = get_tardis_hybrid_synergy()
    matrix = syn.get_full_matrix()
    assert matrix["ok"] is True
    assert matrix["models_count"] >= 6
    assert matrix["engineering_layers_count"] >= 8
    assert "tardis_kaiju" in matrix["models"]
    assert "gemini_frontier" in matrix["models"]
    assert "claude_frontier" in matrix["models"]
    assert "sintropia_ecca" in matrix["engineering_layers"]
    assert "distributed_cluster_mesh" in matrix["engineering_layers"]


def test_evaluate_optimal_combination_scientific():
    syn = get_tardis_hybrid_synergy()
    res = syn.evaluate_optimal_combination("Calcula la integral cuántica y analiza la conjetura de Landauer con sintropía")
    assert res["ok"] is True
    model_ids = [m["id"] for m in res["models_engaged"]]
    assert "tardis_kaiju" in model_ids
    assert "gemini_frontier" in model_ids
    assert res["synergy_score"] == 100.0


def test_evaluate_optimal_combination_visual():
    syn = get_tardis_hybrid_synergy()
    res = syn.evaluate_optimal_combination("Genera un video en pixel art con blender 3d")
    assert res["ok"] is True
    model_ids = [m["id"] for m in res["models_engaged"]]
    assert "chronovision_minimax_h3" in model_ids


def test_evaluate_optimal_combination_distributed():
    syn = get_tardis_hybrid_synergy()
    res = syn.evaluate_optimal_combination("Divide el procesamiento distribuido entre el cluster y el imac")
    assert res["ok"] is True
    model_ids = [m["id"] for m in res["models_engaged"]]
    assert "cluster_failover_ollama" in model_ids
