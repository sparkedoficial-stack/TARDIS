"""
tests/test_offline_chat_vault.py - Suite de pruebas para la Bóveda de Chats Offline
y Recuperación Cognitiva RAG (GODWORKS SYSTEM v26.4)
"""

import json
import os
import shutil
import tempfile
import pytest
from pathlib import Path
from starlette.testclient import TestClient

from core.offline_chat_vault import OfflineChatVault, get_offline_chat_vault
from server.api import app
from omni_temporal_control import process_hardware_chat_intent

AUTH_HEADERS = {"X-API-Key": "REDACTED_MISTRAL"}


@pytest.fixture
def temp_vault():
    temp_dir = Path(tempfile.mkdtemp(prefix="test_offline_vault_"))
    db_file = temp_dir / "test_offline.db"
    vault = OfflineChatVault(db_path=db_file)
    yield vault
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_vault_init_and_tables(temp_vault):
    """Verifica la creación del archivo SQLite y las tablas FTS5."""
    assert temp_vault.db_path.exists()
    with temp_vault._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        assert "offline_chat_turns" in tables
        assert "offline_chat_fts" in tables


def test_record_turn_and_zero_truncation(temp_vault):
    """Verifica el almacenamiento integral sin truncamiento de prompt ni respuesta."""
    long_prompt = "CONSULTA_ARQUITECTURA_SISTEMA_" + ("P" * 12000)
    long_reply = "RESPUESTA_SOBERANA_DETALLADA_" + ("R" * 15000)

    turn_id = temp_vault.record_turn(
        prompt=long_prompt,
        reply=long_reply,
        provider="Hermes 3 Local",
        model="hermes3:8b",
        client_id="test_client_01",
        request_id="req_test_999",
        direction="past",
        dialectic_role="architect",
        user_emotion={"primary": "focused", "attention": "maximum"}
    )
    assert turn_id > 0

    recent = temp_vault.get_recent(limit=5)
    assert len(recent) == 1
    t = recent[0]
    assert t["id"] == turn_id
    assert t["prompt"] == long_prompt
    assert t["reply"] == long_reply
    assert len(t["prompt"]) == len(long_prompt)
    assert len(t["reply"]) == len(long_reply)
    assert t["provider"] == "Hermes 3 Local"
    assert t["model"] == "hermes3:8b"
    assert t["dialectic_role"] == "architect"
    assert t["user_emotion"]["primary"] == "focused"


def test_fts5_bm25_search_and_ranking(temp_vault):
    """Verifica la búsqueda semántica e indexación FTS5 con cálculo BM25."""
    temp_vault.record_turn(
        prompt="¿Cómo auditar la red Wi-Fi y evitar espionaje o rastreo?",
        reply="Para auditar la red Wi-Fi utilizamos nmap, tshark y NetworkShield analizando tráfico en la interfaz wlan0.",
        model="hermes3:8b"
    )
    temp_vault.record_turn(
        prompt="Ajustar volumen del sistema a 70%",
        reply="Volumen multimedia configurado exitosamente al 70% mediante PipeWire.",
        model="llama3.2:3b"
    )
    temp_vault.record_turn(
        prompt="Explicación del geón sintrópico y coherencia temporal",
        reply="El operador sintrópico geon_causal minimiza la entropía cognitiva transversal.",
        model="hermes3:8b"
    )

    # Búsqueda específica
    results_wifi = temp_vault.search("auditar red Wi-Fi espionaje")
    assert len(results_wifi) >= 1
    assert "auditar la red Wi-Fi" in results_wifi[0]["prompt"]

    # Búsqueda de audio
    results_audio = temp_vault.search("PipeWire volumen")
    assert len(results_audio) >= 1
    assert "PipeWire" in results_audio[0]["reply"]

    # Búsqueda sintrópica
    results_sintropia = temp_vault.search("sintrópico entropía")
    assert len(results_sintropia) >= 1
    assert "geón sintrópico" in results_sintropia[0]["prompt"]


def test_cognitive_context_injection_for_prompt(temp_vault):
    """Verifica la inyección estructurada de memoria histórica para el prompt del LLM."""
    temp_vault.record_turn(
        prompt="Mi clave de cifrado local preferida es SINTROPICA_OMEGA_2026",
        reply="Entendido, registraré que tu protocolo de cifrado es SINTROPICA_OMEGA_2026.",
        model="hermes3:8b"
    )
    temp_vault.record_turn(
        prompt="El servidor TimeMachine opera en la subred REDACTED_IP",
        reply="Registrado el direccionamiento IP soberano REDACTED_IP.",
        model="hermes3:8b"
    )

    # Cuando el usuario pregunta sobre la clave, el contexto RAG debe incluirlo
    rag_context = temp_vault.get_context_for_prompt("¿Cuál era mi protocolo de cifrado?", k_relevant=2, n_recent=2)
    assert "BÓVEDA DE CHATS HISTÓRICOS Y MEMORIA OFFLINE VISITADA" in rag_context
    assert "SINTROPICA_OMEGA_2026" in rag_context


def test_standalone_html_viewer_generation(temp_vault):
    """Verifica que el visor HTML generado sea 100% autónomo y autocontenido."""
    temp_vault.record_turn(
        prompt="Prueba de generación de visor offline",
        reply="El visor HTML no depende de ningún servidor ni CDN externo.",
        model="hermes3:8b"
    )

    out_file = temp_vault.db_path.parent / "test_viewer.html"
    generated_path = temp_vault.generate_standalone_viewer(out_path=out_file)

    assert generated_path.exists()
    content = generated_path.read_text(encoding="utf-8")

    # Validar integridad del archivo HTML
    assert "<!DOCTYPE html>" in content
    assert "Bóveda de Chats Offline" in content
    assert 'id="offline-chat-data"' in content
    assert "Prueba de generación de visor offline" in content

    # Validar ausencia de CDNs externos (seguridad y autonomía offline)
    assert "https://cdn." not in content
    assert "https://unpkg.com" not in content
    assert "https://cdnjs." not in content
    assert "https://fonts.googleapis.com" not in content


def test_api_endpoints_offline_chat():
    """Verifica los endpoints HTTP públicos y protegidos de la bóveda offline."""
    client = TestClient(app)

    # 1. Visor público HTML (sin token obligatorio)
    res_html = client.get("/offline_chat_vault.html")
    assert res_html.status_code == 200
    assert "text/html" in res_html.headers.get("content-type", "")
    assert "Bóveda de Chats Offline" in res_html.text

    # 2. Rutas alternas
    res_offline = client.get("/offline")
    assert res_offline.status_code == 200

    res_boveda = client.get("/boveda")
    assert res_boveda.status_code == 200

    # 3. Endpoint de historial JSON
    res_history = client.get("/api/chat/offline/history?limit=10", headers=AUTH_HEADERS)
    assert res_history.status_code == 200
    data_hist = res_history.json()
    assert data_hist["ok"] is True
    assert "turns" in data_hist
    assert isinstance(data_hist["turns"], list)

    # 4. Endpoint de búsqueda
    res_search = client.get("/api/chat/offline/search?q=test&limit=5", headers=AUTH_HEADERS)
    assert res_search.status_code == 200
    data_search = res_search.json()
    assert data_search["ok"] is True
    assert "results" in data_search


def test_slash_offline_commands():
    """Verifica los comandos rápidos /offline y /boveda en el orquestador."""
    res_off = process_hardware_chat_intent("/offline")
    assert res_off is not None
    assert res_off.get("action") == "offline_chat_vault_status"
    assert res_off.get("direct_return") is True
    assert "BÓVEDA SOBERANA DE CHATS OFFLINE" in res_off.get("system_feedback", "")
    assert "/offline_chat_vault.html" in res_off.get("system_feedback", "")

    res_bov = process_hardware_chat_intent("/boveda")
    assert res_bov is not None
    assert res_bov.get("action") == "offline_chat_vault_status"
    assert res_bov.get("direct_return") is True
