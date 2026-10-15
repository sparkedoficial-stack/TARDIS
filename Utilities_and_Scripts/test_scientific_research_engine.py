"""
tests/test_scientific_research_engine.py - Tests para el Motor de Investigación Científica
==========================================================================================
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.scientific_research_engine import (
    ScientificPaper,
    ScientificResearchEngine,
    ScientificResearchReport,
    get_scientific_research_engine,
)


def test_scientific_paper_dataclass():
    paper = ScientificPaper(
        title="Nonlinear Optics in Quantum Cavities",
        authors=["Alice Quantum", "Bob Photons"],
        year=2025,
        venue="Physical Review Letters",
        doi="10.1103/PhysRevLett.123.456",
        doi_url="https://doi.org/10.1103/PhysRevLett.123.456",
        landing_url="https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.123.456",
        pdf_url="https://arxiv.org/pdf/2501.12345.pdf",
        abstract="We observe high-harmonic generation in topological polaritons.",
        source_engine="arxiv",
        citations_count=42,
        peer_reviewed=True
    )
    d = paper.to_dict()
    assert d["title"] == "Nonlinear Optics in Quantum Cavities"
    assert d["citations_count"] == 42
    assert d["pdf_url"].endswith(".pdf")
    assert d["doi_url"].startswith("https://doi.org/")


def test_formulate_academic_queries():
    engine = get_scientific_research_engine()

    # Tema de Física Cuántica
    domain, queries, en_topic = engine.formulate_academic_queries("investiga sobre entrelazamiento cuántico y teorema de bell")
    assert "Física Cuántica" in domain
    assert len(queries) >= 1
    assert any("quantum" in q.lower() or "entrelazamiento" in q.lower() for q in queries)

    # Tema de Sintropía / Termodinámica
    domain2, queries2, en_topic2 = engine.formulate_academic_queries("termodinámica de no equilibrio y sintropía")
    assert "Física Teórica" in domain2 or "Termodinámica" in domain2
    assert len(queries2) >= 1

    # Tema de IA
    domain3, queries3, _ = engine.formulate_academic_queries("comparativa de transformers vs mamba")
    assert "Inteligencia Artificial" in domain3


def test_agenda_lifecycle(tmp_path):
    agenda_file = tmp_path / "test_agenda.json"
    engine = ScientificResearchEngine(agenda_path=agenda_file)

    # Debe crearse por defecto
    agenda = engine.load_agenda()
    assert len(agenda.get("topics", [])) >= 5

    # Agregar nuevo tema
    res = engine.add_topic_to_agenda("Superconductividad a Temperatura Ambiente", domain="Física de Materiales", priority=1)
    assert res["ok"] is True
    assert res["action"] in ("created", "updated")

    # Obtener siguiente
    next_t = engine.get_next_agenda_topic()
    assert next_t is not None
    assert "Superconductividad" in next_t["topic"]

    # Marcar como investigado
    engine.mark_topic_researched("Superconductividad a Temperatura Ambiente")
    updated_agenda = engine.load_agenda()
    matching = [t for t in updated_agenda["topics"] if "Superconductividad" in t["topic"]]
    assert len(matching) == 1
    assert matching[0]["status"] == "completed"
    assert matching[0]["researched_count"] == 1


def test_format_telegram_report():
    engine = get_scientific_research_engine()
    papers = [
        ScientificPaper(
            title="Discovery of Superconducting Phase at 295 K",
            authors=["J. Bardeen", "L. Cooper", "J. Schrieffer"],
            year=2026,
            venue="Nature Physics",
            doi="10.1038/s41567-026-001",
            doi_url="https://doi.org/10.1038/s41567-026-001",
            landing_url="https://nature.com/articles/s41567-026-001",
            pdf_url="https://nature.com/articles/s41567-026-001.pdf",
            abstract="Experimental observation of zero electrical resistance under room temperature.",
            source_engine="nature",
            citations_count=150,
            peer_reviewed=True
        )
    ]
    report = ScientificResearchReport(
        topic="Superconductividad a Temperatura Ambiente",
        scientific_domain="Física de la Materia Condensada",
        conceptual_summary="La superconductividad implica la resistencia eléctrica cero y expulsión del campo magnético.",
        fundamental_principles=["Efecto Meissner: B = 0 en el interior del superconductor."],
        papers=papers,
        learning_roadmap=["1. Estudiar pares de Cooper y teoría BCS."],
        open_questions=["¿Cuál es el mecanismo de acoplamiento fonónico exacto?"],
        generated_at="2026-09-26 12:00:00",
        elapsed_seconds=1.25
    )

    formatted = engine.format_telegram_report(report)
    assert "INVESTIGACIÓN DE RIGOR CIENTÍFICO" in formatted
    assert "Superconductividad a Temperatura Ambiente" in formatted
    assert "Discovery of Superconducting Phase at 295 K" in formatted
    assert "[🔗 Enlace DOI]" in formatted
    assert "[📥 Descargar PDF]" in formatted
    assert "Efecto Meissner" in formatted


def test_search_openalex_live_or_mock():
    engine = get_scientific_research_engine()
    # Ejecutamos una búsqueda corta
    results = engine.search_openalex("quantum computing", max_results=2)
    assert len(results) >= 1
    assert results[0].title != ""
    assert results[0].landing_url != ""


def test_search_arxiv_live_or_mock():
    engine = get_scientific_research_engine()
    results = engine.search_arxiv("entropy", max_results=2)
    assert len(results) >= 1
    assert results[0].source_engine == "arxiv"
    assert "arxiv.org" in results[0].landing_url
