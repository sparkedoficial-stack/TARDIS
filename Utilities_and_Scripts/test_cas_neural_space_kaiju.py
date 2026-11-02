"""
Pruebas del servicio CaS · Cognitive & Context as a Service.
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from core.cas_neural_space_kaiju import (
    CANONICAL_AEGIS,
    AegisSource,
    CaSEngine,
    ContextChunk,
    ContextSource,
    SyntropicCompressor,
    estimate_tokens,
    hamming64,
    make_server,
    simhash64,
)


class StaticSource(ContextSource):
    """Fuente determinista para pruebas de ranking, presupuesto y caché."""

    def __init__(self, name: str, payload: list[tuple[str, str]], trust: float = 0.8):
        self.name = name
        self.trust = trust
        self.payload = payload

    def signature(self) -> str:
        return f"static:{self.name}:{len(self.payload)}"

    def collect(self, request, limit):
        chunks = []
        for index, (title, content) in enumerate(self.payload):
            chunks.append(
                ContextChunk(
                    source=self.name,
                    kind="memory_event",
                    title=title,
                    content=content,
                    timestamp=1_700_000_000 + index,
                    trust=self.trust,
                )
            )
        return chunks


def _engine(tmp_path: Path, chunks: list[tuple[str, str]] | None = None) -> CaSEngine:
    payload = chunks or [
        ("Precedente de kernel", "El kernel PSI muestra presión de memoria baja y carga estable."),
        ("Precedente de red", "El router físico y la malla multi-subred operan sin pérdida de paquetes."),
        ("Precedente de memoria", "La bóveda akáshica conserva 4540 eventos y 14 nodos de conocimiento."),
        ("Precedente de continuidad", "El estado de continuidad sobrevive 281 reinicios sin perder contexto."),
        ("Precedente de AEGIS", "La matriz de anclaje permanece protegida e inviolable."),
    ]
    return CaSEngine(
        sources=[AegisSource(), StaticSource("vault", payload)],
        state_file=tmp_path / "cas_state.json",
    )


def test_estimate_tokens_is_deterministic():
    assert estimate_tokens("") == 0
    short = estimate_tokens("TARDIS soberano")
    long = estimate_tokens("TARDIS soberano " * 40)
    assert 0 < short < long
    assert long == estimate_tokens("TARDIS soberano " * 40)


def test_simhash_detects_near_duplicates():
    a = simhash64("El kernel reporta presión de memoria baja y carga estable en el sistema")
    b = simhash64("El kernel reporta presión de memoria baja y carga estable del sistema")
    c = simhash64("La bóveda akáshica conserva eventos históricos y nodos de conocimiento")
    assert hamming64(a, b) <= 8
    assert hamming64(a, c) > 8


def test_compressor_preserves_query_and_reduces_tokens():
    text = "\n".join(
        [
            "La Constante Aegis protege la matriz de anclaje.",
            "El kernel reporta presión de memoria baja.",
            "El router físico opera sin pérdida de paquetes.",
            "La bóveda akáshica conserva eventos históricos.",
            "La telemetría de PSI confirma carga estable del kernel.",
        ]
    )
    compact, info = SyntropicCompressor().compress(
        text, query="kernel memoria", target_ratio=0.55
    )
    assert "kernel" in compact.lower()
    assert info["compressed_tokens"] < info["original_tokens"]
    assert 0.2 <= info["ratio"] < 1.0


def test_engine_injects_aegis_and_respects_budget(tmp_path):
    engine = _engine(tmp_path)
    bundle = engine.build_context(
        "kernel memoria continuidad", profile="interactive", budget_tokens=900
    )
    assert bundle.ok is True
    assert bundle.used_tokens <= bundle.budget_tokens
    for anchor in CANONICAL_AEGIS:
        assert anchor in bundle.context_text
    assert "[S1]" in bundle.context_text
    assert bundle.aegis["ok"] is True
    assert bundle.chunks


def test_engine_cache_hit_is_deterministic(tmp_path):
    engine = _engine(tmp_path)
    first = engine.build_context("continuidad", profile="interactive", budget_tokens=900)
    second = engine.build_context("continuidad", profile="interactive", budget_tokens=900)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.context_text == first.context_text
    assert engine.telemetry()["cache_hits"] >= 1


def test_source_failure_does_not_break_bundle(tmp_path):
    class BrokenSource(ContextSource):
        name = "broken"
        trust = 0.1

        def signature(self):
            return "broken"

        def collect(self, request, limit):
            raise RuntimeError("fuente caída")

    engine = CaSEngine(
        sources=[AegisSource(), BrokenSource()],
        state_file=tmp_path / "cas_state.json",
    )
    bundle = engine.build_context("estado", budget_tokens=900)
    assert bundle.ok is True
    assert any(item["name"] == "broken" and item["ok"] is False for item in bundle.source_report)


def test_http_service_health_and_context(tmp_path):
    engine = _engine(tmp_path)
    httpd = make_server("127.0.0.1", 0, engine, token="REDACTED")
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert health["ok"] is True
        assert health["aegis"]["verified"] is True

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/context",
            data=json.dumps({"query": "kernel", "budget_tokens": 900}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer secret"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            bundle = json.loads(response.read().decode("utf-8"))
        assert bundle["ok"] is True
        assert bundle["used_tokens"] <= bundle["budget_tokens"]

        unauthorized = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/context",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(unauthorized, timeout=5)
        assert excinfo.value.code == 401
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_compress_endpoint_contract(tmp_path):
    engine = _engine(tmp_path)
    result = engine.compress_text("kernel " * 100, query="kernel", ratio=0.4)
    assert result["ok"] is True
    assert result["compressed_tokens"] <= result["original_tokens"]
