import os
import shutil
import tempfile
import pytest
from starlette.testclient import TestClient

from core.deep_memory_vault import DeepMemoryVault
import gia_memory
from server.api import app

AUTH_HEADERS = {"X-API-Key": "REDACTED_MISTRAL"}


@pytest.fixture
def temp_vault():
    temp_dir = tempfile.mkdtemp(prefix="test_vault_")
    vault = DeepMemoryVault(vault_dir=temp_dir, max_vault_gb=0.05)  # 50 MB
    yield vault
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_vault_ingestion_and_zero_truncation(temp_vault):
    # Ingest a large payload (>35,000 chars) that would previously be truncated
    large_user_msg = "SISTEMA_COGNITIVO_AVANZADO_" + ("A" * 35000)
    evt_id = temp_vault.ingest(
        role="user",
        content=large_user_msg,
        meta={"source": "test_suite", "complexity": "hyper_omega"},
        direction="present"
    )
    assert evt_id > 0

    recent_events = temp_vault.recent(k=5)
    assert len(recent_events) >= 1
    stored = recent_events[0]
    assert stored["role"] == "user"
    assert len(stored["content"]) == len(large_user_msg)
    assert stored["content"] == large_user_msg
    assert stored["is_compressed"] == 1


def test_fts5_bm25_search(temp_vault):
    temp_vault.ingest("user", "Explicación de la arquitectura sintrópica del geón causal v26.4", meta={})
    temp_vault.ingest("assistant", "El geón causal sincroniza la sintropía temporal con el operador cuántico.", meta={})
    temp_vault.ingest("user", "Receta para hacer pan de chocolate.", meta={})

    results = temp_vault.search("sintrópica geón", k=5)
    assert len(results) >= 1
    found_contents = [r["content"] for r in results]
    assert any("arquitectura sintrópica" in c for c in found_contents)
    # Ensure unrelated event is not top match
    assert "Receta para hacer pan de chocolate." not in found_contents[:1]


def test_knowledge_graph_extraction(temp_vault):
    complex_text = "La entidad GIA y el Arquitecto coordinan la arquitectura sintrópica mediante el puente cuántico."
    temp_vault.ingest("user", complex_text, meta={"extract_graph": True})

    nodes = temp_vault.get_knowledge_nodes(limit=20)
    assert len(nodes) > 0
    node_names = [n["name"] for n in nodes]
    assert any(name in node_names for name in ["GIA", "ARQUITECTO", "SISTEMA", "GEÓN"])


def test_epoch_consolidation(temp_vault):
    for i in range(15):
        temp_vault.ingest("user", f"Consulta técnica de ontología recursiva paso {i}", meta={})
        temp_vault.ingest("assistant", f"Formulación matemática del paso {i} para el hipergrafo akáshico.", meta={})

    epoch_res = temp_vault.consolidate_epoch(title="Época de Ontología Recursiva")
    assert epoch_res["ok"] is True
    assert epoch_res["consolidated_events"] == 30

    epochs = temp_vault.get_epochs(limit=5)
    assert len(epochs) >= 1
    assert epochs[0]["title"] == "Época de Ontología Recursiva"
    assert "ontología recursiva" in epochs[0]["summary"].lower()


def test_query_deep_context_and_progressive_complexity(temp_vault):
    temp_vault.ingest("user", "Configuración de redes de tensores neuronales en 18 GB de RAM.", meta={})
    temp_vault.ingest("assistant", "Respuesta exhaustiva sobre optimización de tensores y mlock en memoria física.", meta={})

    ctx_block = temp_vault.query_deep_context(
        current_query="tensores neuronales y memoria RAM",
        max_chars=8000
    )
    assert "BÓVEDA DE MEMORIA PROFUNDA Y GRAFO AKÁSHICO" in ctx_block
    assert "DIRECTIVA DE COMPLEJIDAD COGNITIVA ESCALONADA" in ctx_block
    assert "HILO INMEDIATO DE CONVERSACIÓN" in ctx_block
    assert len(ctx_block) <= 8000

    # Verificar que precedentes profundos se extraen cuando están fuera del hilo inmediato
    for i in range(5):
        temp_vault.ingest("user", f"Conversación intermedia número {i}", meta={})
    ctx_block_deep = temp_vault.query_deep_context(
        current_query="tensores neuronales y memoria RAM",
        n_recent=2,
        n_relevant=5
    )
    assert "PRECEDENTES Y CONOCIMIENTO RECUPERADO" in ctx_block_deep


def test_vault_telemetry(temp_vault):
    telem = temp_vault.get_vault_telemetry()
    assert "vault_dir" in telem
    assert telem["max_capacity_gb"] == pytest.approx(0.1, abs=0.1)
    assert "total_events" in telem
    assert "vault_usage_pct" in telem
    assert "complexity_level" in telem


def test_gia_memory_integration():
    # Test that gia_memory.log correctly interacts with vault without throwing
    res = gia_memory.log("pytest_suite", "user", "Test integration zero-truncation payload " * 50)
    assert res > 0

    ctx = gia_memory.context_block("Test integration query")
    assert isinstance(ctx, str)
    assert len(ctx) > 0

    stats = gia_memory.stats()
    assert "vault_250gb" in stats
    assert stats["vault_250gb"]["max_capacity_gb"] == 250.0


def test_fastapi_endpoints():
    client = TestClient(app)

    # 1. Vault Status
    resp = client.get("/api/memory/vault_status", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "total_events" in data
    assert data["max_capacity_gb"] == 250.0

    # 2. Deep Search
    resp = client.get("/api/memory/deep_search?q=sistema&k=5", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "results" in data

    # 3. Consolidate Epoch
    resp = client.post("/api/memory/consolidate", json={"title": "Test Suite Consolidation"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
