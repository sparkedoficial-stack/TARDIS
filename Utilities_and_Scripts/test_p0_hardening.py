"""Tests de endurecimiento P0 identificados por las Divisiones 3-5 del Frontier Lab."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_harness import AgentHarness
from core.deep_memory_vault import DeepMemoryVault
from core.rag_vault import RAGVault


def test_nested_tool_directive_is_parsed() -> None:
    harness = AgentHarness.__new__(AgentHarness)  # sin construir registros pesados
    text = 'Voy a ejecutar [[TOOL_CALL: {"tool": "x", "params": {"a": {"b": [1, 2]}, "s": "}"}}]] ahora.'
    calls = harness._extract_tool_directives(text)
    assert calls == [("x", {"a": {"b": [1, 2]}, "s": "}"})]


def test_fenced_nested_tool_directive_is_parsed() -> None:
    harness = AgentHarness.__new__(AgentHarness)
    text = '```json\n{"function": "y", "arguments": {"n": {"m": 3}}}\n```'
    calls = harness._extract_tool_directives(text)
    assert calls == [("y", {"n": {"m": 3}})]


def test_store_record_compatibility(tmp_path: Path) -> None:
    vault = DeepMemoryVault(vault_dir=tmp_path / "vault")
    res = vault.store_record(
        category="BROWSER_CONCLUSION",
        title="Prueba",
        content="Contenido de prueba con memoria profunda",
        tags=["test"],
    )
    assert res["ok"] is True
    assert res["id"] > 0


def test_chunk_merges_tiny_tail() -> None:
    body = ("frase completa. " * 120) + "cola"
    chunks = RAGVault._chunk(body)
    assert chunks
    assert all(len(c) >= 160 or len(chunks) == 1 for c in chunks)
    assert all(c.strip() for c in chunks)


def test_evolve_code_signature_uses_target_path() -> None:
    import inspect

    from core.autonomous_coder import AutonomousCoder

    params = inspect.signature(AutonomousCoder.evolve_code).parameters
    assert "target_path" in params
    assert "target_file" not in params
