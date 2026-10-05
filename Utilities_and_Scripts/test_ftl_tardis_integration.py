"""
Unit tests for FTL & TARDIS Sovereign Integration
Verifies that TARDIS takes full responsibility for FTL history, system change tracking,
transversal RAG memory, and context synthesis.
"""

import json
import os
import shutil
import tempfile
import pytest

from core.deep_memory_vault import DeepMemoryVault
from core.auto_context_synchronizer import AutoContextSynchronizer


@pytest.fixture
def temp_vault():
    temp_dir = tempfile.mkdtemp(prefix="test_ftl_vault_")
    vault = DeepMemoryVault(vault_dir=temp_dir, max_vault_gb=0.05)
    yield vault
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_ftl_event_ingestion_and_history(temp_vault):
    # Ingest FTL operation
    evt_id = temp_vault.ingest(
        source="ftl",
        role="assistant",
        content="[FTL SOBERANO :: PLAN COGNITIVO (AUTO)] Modificación de config.py para persistencia.",
        session_id="ftl_sovereign_session",
        meta={
            "prompt": "Optimizar configuraciones del sistema",
            "mode": "auto",
            "model": "gemini-3.8-flash-high",
            "returncode": 0,
            "duration": 1.45,
            "files_changed": ["config.py", "executor.py"]
        },
        importance=1.5
    )
    assert evt_id > 0

    # Retrieve FTL history
    history = temp_vault.get_ftl_history(limit=5)
    assert len(history) == 1
    item = history[0]
    assert item["source"] == "ftl"
    assert item["meta"]["mode"] == "auto"
    assert "config.py" in item["meta"]["files_changed"]


def test_ftl_rag_search(temp_vault):
    temp_vault.ingest(
        source="ftl_shell",
        role="assistant",
        content="[FTL SOBERANO :: SHELL DIRECTO] systemctl restart godworks.service ejecutado exitosamente.",
        meta={"command": "systemctl restart godworks.service", "returncode": 0}
    )
    temp_vault.ingest(
        source="ftl",
        role="assistant",
        content="[FTL SOBERANO :: DUAL-SYNTH] Refactorización de la memoria RAG transversal en TARDIS.",
        meta={"prompt": "Refactorizar memoria RAG transversal", "mode": "synth"}
    )

    results = temp_vault.search("RAG transversal", k=5)
    assert len(results) >= 1
    found_contents = [r["content"] for r in results]
    assert any("Refactorización de la memoria RAG" in c for c in found_contents)


def test_ftl_transversal_context_synthesis(temp_vault):
    temp_vault.ingest(
        source="ftl",
        role="assistant",
        content="[FTL SOBERANO] Implementación del nuevo bus de eventos.",
        meta={"prompt": "Crear bus de eventos", "files_changed": ["event_bus.py"]}
    )

    ctx = temp_vault.query_transversal_ftl_context(prompt="bus de eventos", max_chars=2000)
    assert ctx["ok"] is True
    assert "TARDIS SOBERANO :: CONTEXTO HISTÓRICO & RAG TRANSVERSAL" in ctx["context_text"]
    assert ctx["recent_ftl_count"] >= 1


def test_auto_context_synchronizer_includes_ftl():
    sync = AutoContextSynchronizer.get_instance()
    report = sync.sync_all_systems()
    assert report.get("ok") is True
    assert "ftl_transversal_history" in report.get("updated_subsystems", [])
    assert "ftl" in report
    assert "total_operations" in report["ftl"]
