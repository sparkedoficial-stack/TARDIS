import pytest
from core.config import get_settings

def test_settings_load():
    settings = get_settings()
    assert settings.port == 8757
    assert settings.model in ("dolphin3:latest", "hermes3:8b", "huihui_ai/llama3.1-8b-instruct-abliterated")
    assert settings.num_ctx in (4096, 16384, 32768)
    assert settings.num_predict in (512, 2048)
    assert settings.host == "127.0.0.1"
    assert len(settings.token) > 0
    assert settings.token not in ("DiosDelTiempo01", "REDACTED_TOKEN", "0")
    assert settings.ollama_flash_attention is True
    assert settings.ram_budget_gb == 18.0
    assert settings.num_threads in (12, 16)

def test_settings_to_dict():
    settings = get_settings()
    d = settings.to_dict()
    assert d["model"] in ("dolphin3:latest", "hermes3:8b", "huihui_ai/llama3.1-8b-instruct-abliterated")
    assert d["port"] == 8757
