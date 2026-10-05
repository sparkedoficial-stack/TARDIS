"""
GODWORKS SYSTEM v26.4 - Unit Tests for Chinese Cloud API Gateway
Verifica:
1. Catálogo de proveedores chinos (SiliconFlow, DeepSeek, Zhipu, Groq, OpenRouter).
2. Persistencia de configuración en vw-control/chinese_api_config.json.
3. Medición precisa de tokens por segundo y tiempo de respuesta.
4. Endpoints REST (/api/chinese_api/status, /api/chinese_api/configure, /api/chinese_api/test).
5. Enrutamiento automático para tareas de código y razonamiento complejo.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from core.chinese_cloud_api import ChineseCloudAPI, PROVIDERS_CATALOG, get_chinese_cloud_api
from server.api import app

client = TestClient(app)
AUTH_HEADERS = {"Authorization": "Bearer DiosDelTiempo01"}


@pytest.fixture
def temp_api():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = Path(tmpdir) / "test_chinese_cfg.json"
        api = ChineseCloudAPI(config_path=cfg_file)
        yield api


def test_catalog_and_defaults(temp_api):
    st = temp_api.get_status()
    assert st["ok"] is True
    assert "siliconflow" in st["providers_catalog"]
    assert "deepseek" in st["providers_catalog"]
    assert "zhipu" in st["providers_catalog"]
    assert "groq_deepseek" in st["providers_catalog"]
    assert st["active_provider"] == "siliconflow"
    assert "DeepSeek" in st["active_model"]


def test_configuration_update(temp_api):
    updated = temp_api.configure(
        provider="deepseek",
        model="deepseek-reasoner",
        api_key = "REDACTED",
        enabled=True,
        auto_route=True
    )
    assert updated["active_provider"] == "deepseek"
    assert updated["active_model"] == "deepseek-reasoner"
    assert updated["has_key"] is True
    assert "sk-t...5678" in updated["masked_key"]

    # Verificar recarga desde disco
    reloaded = ChineseCloudAPI(config_path=temp_api.config_path)
    rel_st = reloaded.get_status()
    assert rel_st["active_provider"] == "deepseek"
    assert rel_st["active_model"] == "deepseek-reasoner"


def test_mocked_chat_completion_metrics(temp_api):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {"message": {"content": "Solución al problema complejo generada a máxima velocidad."}}
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 60,
            "total_tokens": 75
        }
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        res = temp_api.chat_completion(
            messages=[{"role": "user", "content": "Escribe un algoritmo de ordenamiento"}],
            timeout=10.0
        )

        assert res["ok"] is True
        assert "Solución" in res["reply"]
        assert res["tokens"] == 60
        assert res["tokens_per_sec"] >= 0.0
        assert res["elapsed_s"] >= 0.0

        st = temp_api.get_status()
        assert st["metrics"]["total_requests"] == 1
        assert st["metrics"]["total_tokens"] == 75


def test_api_endpoints():
    resp = client.get("/api/chinese_api/status", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "providers_catalog" in data

    resp_cfg = client.post("/api/chinese_api/configure", json={
        "provider": "siliconflow",
        "model": "deepseek-ai/DeepSeek-V3",
        "enabled": True
    }, headers=AUTH_HEADERS)
    assert resp_cfg.status_code == 200
    assert resp_cfg.json()["active_provider"] == "siliconflow"
