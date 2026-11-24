"""
tests/test_mundo_sin_censura.py - Suite de verificación para Un Mundo Sin Censura
=================================================================================
Valida:
  1. Paridad de Modelfiles (raíz y `models/`), plantilla Llama 3.1 y stop tokens.
  2. Resolución de alias de modelo y compatibilidad con `TemporalBrain`.
  3. Operación NO destructiva de `abliterate()` / `configure_sovereign_mode()`
     preservando `temporal_brain_config.json` (modelo GGUF + hooks) y las guardias
     del host (`aegis`, `protected_paths_enabled`, `destructive_guard`,
     `pii_sanitizer_enabled`, `ftl.enforce_aegis`).
  4. Enrutamiento Dual-Lane (`temporal_brain` primario + fallback a `ollama`) y streaming.
  5. Integración con módulo FTL (`FtlMundoSinCensura`) y endpoints FastAPI
     `/api/mundo_sin_censura/*`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path("/home/m11/Escritorio/GODWORKS SYSTEM").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if "/home/m11" not in sys.path:
    sys.path.insert(0, "/home/m11")

import core.mundo_sin_censura as msc


def test_model_alias_detection():
    assert msc.is_mundo_sin_censura_model("mundo-sin-censura") is True
    assert msc.is_mundo_sin_censura_model("mundo-sin-censura:latest") is True
    assert msc.is_mundo_sin_censura_model("Un-Mundo-Sin-Censura") is True
    assert msc.is_mundo_sin_censura_model("mundo_sin_censura") is True
    assert msc.is_mundo_sin_censura_model("TARDIS-NEURAL-SPACE-KAIJU") is False
    assert msc.is_mundo_sin_censura_model(None) is False


def test_modelfiles_synced_and_canonical():
    agent = msc.MundoSinCensuraAgent()
    status = agent.modelfiles_synced()
    assert status["root_exists"] is True
    assert status["mirror_exists"] is True
    assert status["synced"] is True
    assert status["kaiju_modelfile_clean"] is True

    root_txt = msc.MODELFILE_ROOT.read_text(encoding="utf-8")
    assert f"FROM {msc.GGUF_PATH}" in root_txt
    assert "<|start_header_id|>system<|end_header_id|>" in root_txt
    assert 'PARAMETER stop "<|eot_id|>"' in root_txt
    assert 'PARAMETER stop "<|end_of_text|>"' in root_txt
    assert "LA CONSTANTE AEGIS" in root_txt


def test_configure_sovereign_mode_is_non_destructive(tmp_path, monkeypatch):
    tb_cfg = tmp_path / "temporal_brain_config.json"
    tb_cfg.write_text(
        json.dumps(
            {
                "model": "TARDIS-NEURAL-SPACE-KAIJU",
                "hooks": {
                    "enable_pre_hooks": True,
                    "enable_post_hooks": True,
                    "enable_stream_filters": True,
                },
            }
        ),
        encoding="utf-8",
    )
    rails_file = tmp_path / "kaiju_safety_rails.json"
    rails_file.write_text(
        json.dumps(
            {
                "omega": {"active": False, "mode": "SAFE"},
                "aegis": {"active": False, "status": "UNKNOWN"},
                "execution": {
                    "denylist_enabled": False,
                    "protected_paths_enabled": False,
                    "destructive_guard": False,
                    "pii_sanitizer_enabled": False,
                },
                "ftl": {"enforce_aegis": False, "enforce_omega": False},
            }
        ),
        encoding="utf-8",
    )
    state_file = tmp_path / "mundo_state.json"
    ftl_dir = tmp_path / "ftl"
    colony_file = tmp_path / "colony_state.json"

    monkeypatch.setattr(msc, "TEMPORAL_BRAIN_CONFIG", tb_cfg)
    monkeypatch.setattr(msc, "KAIJU_STATE_FILE", rails_file)
    monkeypatch.setattr(msc, "STATE_FILE", state_file)
    monkeypatch.setattr(msc, "FTL_CONFIG_DIR", ftl_dir)
    monkeypatch.setattr(msc, "FTL_CONFIG_FILE", ftl_dir / "mundo_sin_censura_config.json")
    monkeypatch.setattr(msc, "FTL_STATE_FILE", ftl_dir / "mundo_sin_censura_state.json")
    monkeypatch.setattr(msc, "FTL_AUDIT_LOG", ftl_dir / "mundo_sin_censura_audit.log")
    monkeypatch.setattr(msc, "COLONY_STATE_FILE", colony_file)

    agent = msc.MundoSinCensuraAgent()
    with patch.object(
        agent,
        "inspect_ollama_model",
        return_value={
            "host": msc.OLLAMA_HOST,
            "reachable": True,
            "registered": True,
            "model_tag": msc.MODEL_TAG,
            "all_models": [msc.MODEL_TAG, "TARDIS-NEURAL-SPACE-KAIJU:latest"],
            "running_models": [],
            "blob_sha256": "a" * 64,
            "has_llama3_template": True,
            "has_stop_tokens": True,
        },
    ), patch.object(
        agent,
        "gguf_info",
        return_value={
            "path": str(msc.GGUF_PATH),
            "exists": True,
            "size_bytes": REDACTED_PHONE,
            "size_gb": 4.58,
            "sha256": "a" * 64,
        },
    ), patch.object(
        agent,
        "inspect_temporal_brain",
        return_value={"ready": True, "online": True, "idle_slots": 2, "busy_slots": 0},
    ), patch.object(
        agent,
        "sync_modelfiles",
        return_value={"ok": True, "updated": [], "status": {"synced": True}},
    ):
        res = agent.abliterate()

    assert res["errors"] == []
    updated_tb = json.loads(tb_cfg.read_text(encoding="utf-8"))
    assert updated_tb["model"] == "TARDIS-NEURAL-SPACE-KAIJU"
    assert updated_tb["mundo_sin_censura_alias"] == "mundo-sin-censura"
    assert updated_tb["hooks"]["enable_pre_hooks"] is True
    assert updated_tb["hooks"]["enable_post_hooks"] is True
    assert updated_tb["hooks"]["enable_stream_filters"] is True

    updated_rails = json.loads(rails_file.read_text(encoding="utf-8"))
    assert updated_rails["omega"]["active"] is True
    assert updated_rails["omega"]["mode"] == "UNCHAINED_SOVEREIGN"
    assert updated_rails["aegis"]["active"] is True
    assert updated_rails["aegis"]["status"] == "PROTECTED_INVULNERABLE"
    assert updated_rails["execution"]["protected_paths_enabled"] is True
    assert updated_rails["execution"]["destructive_guard"] is True
    assert updated_rails["execution"]["pii_sanitizer_enabled"] is True
    assert updated_rails["execution"]["denylist_enabled"] is True
    assert updated_rails["ftl"]["enforce_aegis"] is True

    ftl_state = json.loads((ftl_dir / "mundo_sin_censura_state.json").read_text(encoding="utf-8"))
    assert ftl_state["sovereign_status"] == "OPERATIONAL"
    assert ftl_state["weights_sha256_match"] is True
    assert ftl_state["dual_lane_ready"] is True


def test_dual_lane_routing_and_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(msc, "STATE_FILE", tmp_path / "state.json")
    agent = msc.MundoSinCensuraAgent()

    # 1. Auto elige temporal_brain cuando está listo
    with patch.object(agent, "inspect_temporal_brain", return_value={"ready": True, "online": True}), patch.object(
        agent,
        "_chat_via_temporal_brain",
        return_value={
            "ok": True,
            "reply": "Respuesta CUDA directa",
            "model": "mundo-sin-censura",
            "lane": "temporal_brain",
            "elapsed": 1.2,
            "tokens_per_sec": 24.5,
            "usage": {"completion_tokens": 30},
        },
    ) as mock_tb, patch.object(agent, "_chat_via_ollama") as mock_oll:
        r1 = agent.chat("hola", lane="auto")
        assert r1["ok"] is True
        assert r1["lane"] == "temporal_brain"
        assert mock_tb.called
        assert not mock_oll.called

    # 2. Auto hace fallback a ollama cuando temporal_brain no está listo
    with patch.object(agent, "inspect_temporal_brain", return_value={"ready": False, "online": False}), patch.object(
        agent,
        "_chat_via_ollama",
        return_value={
            "ok": True,
            "reply": "Respuesta Ollama fallback",
            "model": "mundo-sin-censura:latest",
            "lane": "ollama",
            "elapsed": 4.1,
            "tokens_per_sec": 11.0,
            "usage": {"completion_tokens": 45},
        },
    ) as mock_oll:
        r2 = agent.chat("hola", lane="auto")
        assert r2["ok"] is True
        assert r2["lane"] == "ollama"
        assert mock_oll.called


def test_prepare_messages_preserves_and_injects_system():
    agent = msc.MundoSinCensuraAgent()
    msgs = agent.prepare_messages("Prueba técnica")
    assert msgs[0]["role"] == "system"
    assert "LA CONSTANTE AEGIS" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "Prueba técnica"}

    # Alias retrocompatible
    msgs2 = agent.universal_jailbreak_route(
        [{"role": "system", "content": "Contexto extra"}, {"role": "user", "content": "Q"}]
    )
    assert msgs2[0]["role"] == "system"
    assert "Contexto extra" in msgs2[0]["content"]
    assert "MODO SOBERANO LOCAL" in msgs2[0]["content"]


def test_ftl_module_interface():
    from modulos_ftl.ftl_mundo_sin_censura import FtlMundoSinCensura

    mod = FtlMundoSinCensura()
    bad = mod.run("accion_inexistente")
    assert bad["ok"] is False
    assert "available_actions" in bad


def test_fastapi_endpoints():
    from fastapi.testclient import TestClient
    from server.api import create_app

    app = create_app()
    client = TestClient(app)

    r_status = client.get("/api/mundo_sin_censura/status")
    assert r_status.status_code == 200
    data = r_status.json()
    assert data["model"] == "mundo-sin-censura"
    assert "lanes" in data
    assert "weights" in data

    r_bad = client.post("/api/mundo_sin_censura/chat", json={})
    assert r_bad.status_code == 400
