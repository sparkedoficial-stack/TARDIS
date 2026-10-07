"""
tests/test_web_research_and_coder.py - Tests para Investigación Web Autónoma y Auto-Programador
==============================================================================================
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.autonomous_coder import AutonomousCoder, EvolutionResult, get_autonomous_coder
from core.web_research_engine import (
    PageContent,
    SearchResult,
    WebResearchEngine,
    clean_html_to_text,
    get_web_research_engine,
)


# ==============================================================================
# 1. PRUEBAS PARA WEB RESEARCH ENGINE
# ==============================================================================

def test_clean_html_to_text():
    html_sample = """
    <!DOCTYPE html>
    <html>
    <head><title>Test Page</title><style>.test { color: red; }</style></head>
    <body>
        <nav><a href="/home">Inicio</a></nav>
        <h1>Título Principal de Investigación</h1>
        <p>Este es el primer párrafo con información sustantiva sobre redes neuronales y optimización.</p>
        <pre><code>def compute_loss(y_true, y_pred):\n    return sum((y_true - y_pred)**2)</code></pre>
        <script>console.log("tracking script");</script>
        <footer>Copyright 2026</footer>
    </body>
    </html>
    """
    text, code_blocks = clean_html_to_text(html_sample)

    assert "Título Principal de Investigación" in text
    assert "primer párrafo con información sustantiva" in text
    assert "console.log" not in text
    assert ".test { color: red; }" not in text
    assert len(code_blocks) >= 1
    assert "compute_loss" in code_blocks[0]


def test_decompose_topic():
    engine = get_web_research_engine()
    queries = engine.decompose_topic("investiga sobre la arquitectura de transformers en python")
    assert len(queries) >= 1
    assert any("transformer" in q.lower() for q in queries)


def test_extractive_synthesis():
    engine = get_web_research_engine()
    results = [
        SearchResult(title="PyTorch Optim", url="https://pytorch.org/docs", snippet="Módulo de optimización")
    ]
    pages = [
        PageContent(
            url="https://pytorch.org/docs",
            title="PyTorch Optim",
            text="PyTorch ofrece algoritmos de optimización estocástica como Adam y SGD para entrenar modelos con aceleración por GPU.",
            code_snippets=["import torch.optim as optim\nopt = optim.Adam(model.parameters())"],
            word_count=20,
        )
    ]
    synthesis = engine._generate_extractive_synthesis("optimización de modelos", pages, results)
    assert "PyTorch Optim" in synthesis
    assert "https://pytorch.org/docs" in synthesis
    assert "optim.Adam" in synthesis


# ==============================================================================
# 2. PRUEBAS PARA AUTONOMOUS CODER
# ==============================================================================

def test_autonomous_coder_syntax_validation():
    coder = get_autonomous_coder()
    py_path = Path("sample.py")

    valid_code = "def add(a, b):\n    return a + b\n"
    ok, err = coder._validate_syntax(py_path, valid_code)
    assert ok is True
    assert err == ""

    broken_code = "def broken(:\n    pass\n"
    ok_b, err_b = coder._validate_syntax(py_path, broken_code)
    assert ok_b is False
    assert "SyntaxError" in err_b


def test_autonomous_coder_benchmark():
    coder = get_autonomous_coder()
    def sample_work():
        return sum(i * i for i in range(10000))

    bench = coder.benchmark_code(sample_work, iterations=3)
    assert bench["ok"] is True
    assert bench["iterations"] == 3
    assert bench["avg_ms"] >= 0.0


def test_autonomous_coder_backup_and_restore():
    coder = get_autonomous_coder()
    project_root = Path(__file__).resolve().parent.parent
    test_file = project_root / "_test_dummy_coder.py"

    try:
        test_file.write_text("# version original\nX = 100\n", encoding="utf-8")
        backup = coder._create_backup(test_file)
        assert backup.is_file()

        # Modificar archivo
        test_file.write_text("# version modificada\nX = 999\n", encoding="utf-8")
        assert "999" in test_file.read_text(encoding="utf-8")

        # Restaurar
        res = coder.restore_backup(str(backup))
        assert res["ok"] is True
        assert "100" in test_file.read_text(encoding="utf-8")
    finally:
        if test_file.exists():
            test_file.unlink()


def test_autonomous_coder_rollback_on_syntax_error():
    coder = get_autonomous_coder()
    project_root = Path(__file__).resolve().parent.parent
    test_file = project_root / "_test_dummy_rollback.py"

    try:
        initial_content = "# Codigo Seguro\ndef foo():\n    return 'safe'\n"
        test_file.write_text(initial_content, encoding="utf-8")

        mock_api = MagicMock()
        mock_api.get_status.return_value = {"enabled": True, "has_key": True, "active_provider": "mock"}
        mock_api.chat_completion.return_value = {
            "ok": True,
            "reply": "```python\n# Codigo Roto Con Error Sintactico\ndef foo(:\n    return 'broken'\n```",
            "provider": "mock",
            "model": "mock_model",
        }

        with patch("core.chinese_cloud_api.get_chinese_cloud_api", return_value=mock_api):
            res = coder.evolve_code(
                str(test_file),
                goal="Optimizar función foo",
                verify_tests=False,
            )
            assert res.status == "ROLLED_BACK_SYNTAX"
            # Verificar que el archivo en disco retuvo su código seguro original
            assert test_file.read_text(encoding="utf-8") == initial_content
    finally:
        if test_file.exists():
            test_file.unlink()


def test_autonomous_coder_rollback_on_test_failure():
    coder = get_autonomous_coder()
    project_root = Path(__file__).resolve().parent.parent
    test_file = project_root / "_test_dummy_fail_tests.py"

    try:
        initial_content = "# Codigo Estable\ndef calc():\n    return 42\n"
        test_file.write_text(initial_content, encoding="utf-8")

        mock_api = MagicMock()
        mock_api.get_status.return_value = {"enabled": True, "has_key": True, "active_provider": "mock"}
        mock_api.chat_completion.return_value = {
            "ok": True,
            "reply": "```python\n# Codigo que pasa sintaxis pero rompe logica\ndef calc():\n    return 0\n```",
            "provider": "mock",
            "model": "mock_model",
        }

        with patch("core.chinese_cloud_api.get_chinese_cloud_api", return_value=mock_api):
            with patch.object(coder, "run_tests", return_value=(False, "Regression failure in test_calc")):
                res = coder.evolve_code(
                    str(test_file),
                    goal="Optimizar cálculo",
                    verify_tests=True,
                )
                assert res.status == "ROLLED_BACK_TESTS"
                assert "Regression failure" in res.test_output
                assert test_file.read_text(encoding="utf-8") == initial_content
    finally:
        if test_file.exists():
            test_file.unlink()


def test_evolution_history_logging():
    coder = get_autonomous_coder()
    history = coder.get_evolution_history(limit=10)
    assert isinstance(history, list)


# ==============================================================================
# 3. PRUEBAS PARA ENDPOINTS FASTAPI
# ==============================================================================

def test_api_research_endpoints():
    from starlette.testclient import TestClient
    from server.api import app
    client = TestClient(app)
    auth = {"X-API-Key": "REDACTED_MISTRAL"}

    # 1. Search endpoint
    resp = client.get("/api/research/search?q=python+dataclass&limit=2", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "results" in data

    # 2. Evolution log endpoint
    resp_log = client.get("/api/code/evolution_log?limit=5", headers=auth)
    assert resp_log.status_code == 200
    data_log = resp_log.json()
    assert data_log["ok"] is True
    assert "history" in data_log

    # 3. Backups list endpoint
    resp_bak = client.get("/api/code/backups", headers=auth)
    assert resp_bak.status_code == 200
    data_bak = resp_bak.json()
    assert data_bak["ok"] is True
    assert "backups" in data_bak
