import pytest
import time
from pathlib import Path
from starlette.testclient import TestClient

from core.deep_memory_vault import DeepMemoryVault
from core.background_thought_engine import BackgroundThoughtEngine, get_background_thought_engine
from server.api import app


def test_extract_questions():
    engine = BackgroundThoughtEngine()

    # 1. Punctuation with question marks
    text1 = "¿Cómo funciona la compresión de 250 GB en SQLite? También me pregunto si el hardware está protegido."
    q1 = engine.extract_questions(text1)
    assert len(q1) >= 1
    assert any("250 GB" in q for q in q1)

    # 2. Interrogative words without question marks
    text2 = "Por qué la sintropía temporal reduce la entropía del sistema en tiempo real."
    q2 = engine.extract_questions(text2)
    assert len(q2) >= 1
    assert "sintropía" in q2[0].lower()

    # 3. Inquiry / imperative request
    text3 = "Explica la integración entre la memoria RAM física de 18 GB y el modelo local."
    q3 = engine.extract_questions(text3)
    assert len(q3) >= 1
    assert "memoria ram" in q3[0].lower()

    # 4. Empty or whitespace
    assert engine.extract_questions("") == []
    assert engine.extract_questions("   ") == []


def test_background_thought_processing_and_vault_enrichment(tmp_path):
    vault = DeepMemoryVault(vault_dir=tmp_path / "test_vault")
    engine = BackgroundThoughtEngine(vault=vault)

    # Question to contemplate in background
    test_q = "¿Cuál es el rol del atractor sintrópico en la estabilidad del sistema?"
    res = engine.process_question(
        question=test_q,
        source="unit_test",
        session_id="test_sess"
    )

    assert res["ok"] is True
    assert res["question"] == test_q
    assert len(res["answer"]) > 50
    assert res["contemplation_id"] > 0
    assert res["vault_event_id"] > 0

    # Verify presence in vault database
    contemplations = vault.get_recent_contemplations(limit=5)
    assert len(contemplations) == 1
    assert contemplations[0]["question"] == test_q
    assert contemplations[0]["source"] == "unit_test"

    # Verify telemetry count
    telemetry = vault.get_vault_telemetry()
    assert telemetry["background_contemplations"] == 1
    assert telemetry["complexity_level"] > 1

    # Verify injection into query_deep_context
    ctx = vault.query_deep_context(query="atractor sintropico")
    assert "CONOCIMIENTO PROFUNDO DERIVADO EN SEGUNDO PLANO" in ctx
    assert test_q in ctx


def test_background_worker_queue(tmp_path):
    vault = DeepMemoryVault(vault_dir=tmp_path / "test_worker_vault")
    engine = BackgroundThoughtEngine(vault=vault)
    engine.start()
    assert engine.is_running() is True

    # Enqueue question
    q_text = "¿Cómo interactúa el radar RF pasivo con los estados de presencia del usuario?"
    enqueued = engine.enqueue_question(q_text, source="queue_test")
    assert enqueued is True

    # Wait briefly for worker to process
    for _ in range(30):
        stats = engine.get_stats()
        if stats["total_processed_thoughts"] >= 1:
            break
        time.sleep(0.1)

    stats = engine.get_stats()
    assert stats["total_processed_thoughts"] >= 1
    assert stats["last_thought"]["question"] == q_text

    engine.stop()


def test_api_endpoints_thoughts():
    client = TestClient(app)
    master_key = "REDACTED"

    # 1. GET /api/deep_memory/thoughts
    r1 = client.get("/api/deep_memory/thoughts", headers={"x-api-key": master_key})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["ok"] is True
    assert "stats" in d1
    assert "thoughts" in d1

    # 2. POST /api/deep_memory/contemplate
    payload = {
        "question": "¿De qué manera el mlock garantiza cero latencia de paginación?",
        "source": "api_test"
    }
    r2 = client.post("/api/deep_memory/contemplate", json=payload, headers={"x-api-key": master_key})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["ok"] is True
    assert d2["enqueued"] is True
    assert "mlock" in d2["question"]
