"""
Tests for FTL TardisBridge
Verifies communication with TARDIS daemon, fallback mechanisms,
turn recording, RAG search, and context synthesis.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from tardis_bridge import TardisBridge, tardis_bridge


def test_tardis_bridge_status():
    status = tardis_bridge.get_status()
    assert status["online"] is True
    assert status["mode"] in ("daemon_api", "sqlite_direct")
    assert status["events_count"] >= 1


def test_tardis_bridge_history():
    history = tardis_bridge.get_history(limit=5)
    assert isinstance(history, list)
    assert len(history) >= 1
    first = history[0]
    assert "iso" in first
    assert "source" in first


def test_tardis_bridge_transversal_context():
    ctx = tardis_bridge.get_transversal_context(prompt="arquitectura de memoria")
    assert isinstance(ctx, str)
    assert "TARDIS SOBERANO :: CONTEXTO HISTÓRICO & RAG TRANSVERSAL" in ctx


def test_tardis_bridge_rag_search():
    results = tardis_bridge.search_rag("sintropía", limit=3)
    assert isinstance(results, list)
    assert len(results) >= 1
    assert "content" in results[0]


def test_tardis_bridge_record_and_change_detection():
    # Capture state
    snap = tardis_bridge.capture_filesystem_state()
    # Record a test turn
    ok = tardis_bridge.record_turn(
        prompt="Verificación de puente FTL-TARDIS",
        mode="test",
        model="gemini-3.8-flash-high",
        returncode=0,
        duration=0.5,
        output_summary="Prueba unitaria completada con éxito.",
        files_changed=["test_tardis_bridge.py"]
    )
    assert ok is True

    # Verify history has increased or contains the test turn
    history = tardis_bridge.get_history(limit=3)
    prompts = [h.get("meta", {}).get("prompt") for h in history]
    assert any("Verificación de puente FTL-TARDIS" in (p or "") for p in prompts)


def test_tardis_bridge_format_completion_message():
    # Test success with modified files
    msg1 = tardis_bridge.format_completion_message("crea un módulo", returncode=0, files_changed=["a.py", "b.py"])
    assert "Arquitecto, he terminado la tarea que me pediste" in msg1
    assert "2 archivos modificados" in msg1

    # Test success with short prompt and no files
    msg2 = tardis_bridge.format_completion_message("busca ofertas vigentes", returncode=0, files_changed=[])
    assert "Arquitecto, he terminado la tarea: busca ofertas vigentes." in msg2

    # Test shell execution
    msg3 = tardis_bridge.format_completion_message("git status", returncode=0, is_shell=True)
    assert msg3 == "Arquitecto, el comando ha finalizado con éxito."

    # Test error
    msg4 = tardis_bridge.format_completion_message("tarea fallida", returncode=1)
    assert msg4 == "Arquitecto, la tarea ha finalizado con advertencias o error."


def test_tardis_bridge_speak():
    res = tardis_bridge.speak("Verificación de síntesis de voz TARDIS", wait=False)
    assert res is True


def test_tardis_bridge_notify_completion():
    res = tardis_bridge.notify_completion("Verificación de notificación al Arquitecto", returncode=0, files_changed=["test.py"])
    assert res is True


if __name__ == "__main__":
    test_tardis_bridge_status()
    print("✓ test_tardis_bridge_status PASSED")
    test_tardis_bridge_history()
    print("✓ test_tardis_bridge_history PASSED")
    test_tardis_bridge_transversal_context()
    print("✓ test_tardis_bridge_transversal_context PASSED")
    test_tardis_bridge_rag_search()
    print("✓ test_tardis_bridge_rag_search PASSED")
    test_tardis_bridge_record_and_change_detection()
    print("✓ test_tardis_bridge_record_and_change_detection PASSED")
    test_tardis_bridge_format_completion_message()
    print("✓ test_tardis_bridge_format_completion_message PASSED")
    test_tardis_bridge_speak()
    print("✓ test_tardis_bridge_speak PASSED")
    test_tardis_bridge_notify_completion()
    print("✓ test_tardis_bridge_notify_completion PASSED")
    print("\nALL FTL-TARDIS BRIDGE TESTS PASSED!")
