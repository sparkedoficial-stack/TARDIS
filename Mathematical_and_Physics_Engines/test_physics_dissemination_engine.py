"""
tests/test_physics_dissemination_engine.py - Tests para el Motor de Diseminación de Física en Foros Internacionales
====================================================================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4
"""

import json
import os
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.physics_dissemination_engine import (
    PhysicsAdvance,
    PhysicsDisseminationEngine,
    PublicationRecord,
    get_physics_dissemination_engine,
)


@pytest.fixture
def temp_engine(tmp_path):
    """Crea una instancia de PhysicsDisseminationEngine en un directorio temporal limpio."""
    return PhysicsDisseminationEngine(base_dir=tmp_path)


def test_physics_advance_dataclass():
    adv = PhysicsAdvance(
        advance_id="test_advance_1",
        title="Exact Solitonic Invariants in Curved Spacetime",
        title_es="Invariantes Solitónicos Exactos en Espaciotiempo Curvo",
        authors=["TARDIS Core", "El Arquitecto (₪)"],
        affiliations=["TARDIS Temporal Physics Lab"],
        abstract="We demonstrate solitonic stability across Cauchy horizons.",
        abstract_es="Demostramos estabilidad solitónica a través de horizontes de Cauchy.",
        keywords=["Solitons", "General Relativity", "Clean Energy"],
        primary_equations=[
            {"latex": r"\nabla_\mu F^{\mu\nu} = 0", "description": "Ecuaciones de campo"}
        ],
        theoretical_derivation="Derivación analítica del lagrangiano.",
        numerical_validation={"coherence": 0.99},
        humanitarian_benefits=[
            {"domain": "Energía Limpia", "impact": "Generación sin emisiones térmicas."}
        ],
        references=[{"citation": "Wheeler (1955). Geons."}],
        created_at="2026-10-12T00:00:00Z"
    )
    d = adv.to_dict()
    assert d["advance_id"] == "test_advance_1"
    assert len(d["primary_equations"]) == 1
    assert len(d["humanitarian_benefits"]) == 1
    assert "Clean Energy" in d["keywords"]


def test_cataloged_advances(temp_engine):
    catalog = temp_engine.get_cataloged_advances()
    assert len(catalog) >= 3
    assert "geon_retrocausal_mechanics" in catalog
    assert "syntropic_thermodynamics_solitons" in catalog
    assert "ecca_harmonic_resonance" in catalog

    geon = catalog["geon_retrocausal_mechanics"]
    assert "Wheeler-Feynman" in geon.title
    assert len(geon.primary_equations) >= 2
    assert len(geon.humanitarian_benefits) >= 3
    # Comprobar que contiene la integral retrocausal
    assert any(r"\Psi_{Retro}" in eq["latex"] for eq in geon.primary_equations)


def test_synthesize_new_advance(temp_engine):
    adv = temp_engine.synthesize_new_advance(
        topic="Superconductividad a Temperatura Ambiente Mediante Resonancia Geónica",
        domain="Física de la Materia Condensada",
        humanitarian_goal="Erradicar pérdidas eléctricas en redes de transmisión mundial"
    )
    assert adv.advance_id.startswith("adv_")
    assert "Superconductividad" in adv.title
    assert adv.domain == "Física de la Materia Condensada"
    assert len(adv.humanitarian_benefits) >= 1
    assert "Erradicar pérdidas" in adv.humanitarian_benefits[0]["impact"]

    # Verificar que se guardó en disco
    saved_file = temp_engine.advances_dir / f"{adv.advance_id}.json"
    assert saved_file.exists()


def test_generate_latex_and_bibtex(temp_engine):
    adv = temp_engine.get_advance("geon_retrocausal_mechanics")
    assert adv is not None

    tex = temp_engine.generate_latex_manuscript(adv)
    assert "\\documentclass" in tex
    assert "\\begin{abstract}" in tex
    assert "\\begin{equation}" in tex
    assert "Humanitarian Benefits" in tex
    assert "\\end{document}" in tex

    bib = temp_engine.generate_bibtex(adv)
    assert "@article{" in bib
    assert "TARDIS Sovereign Open Science Preprints" in bib


def test_generate_arxiv_bundle(temp_engine):
    adv = temp_engine.get_advance("geon_retrocausal_mechanics")
    tar_path = temp_engine.generate_arxiv_bundle(adv)

    assert tar_path.exists()
    assert tar_path.name.endswith(".tar.gz")

    # Inspeccionar contenido del tarball
    with tarfile.open(tar_path, "r:gz") as tar:
        names = tar.getnames()
        assert any(n.endswith(".tex") for n in names)
        assert any(n.endswith(".bib") for n in names)
        assert "00README.XXX" in names


def test_generate_pdf_preprint(temp_engine):
    adv = temp_engine.get_advance("geon_retrocausal_mechanics")
    pdf_path = temp_engine.generate_pdf_preprint(adv)

    assert pdf_path.exists()
    assert pdf_path.name.endswith(".pdf")
    file_size = pdf_path.stat().st_size
    assert file_size > 1000  # Archivo PDF sustancial generado


def test_generate_forum_markdown(temp_engine):
    adv = temp_engine.get_advance("syntropic_thermodynamics_solitons")
    md = temp_engine.generate_forum_markdown(adv)

    assert md.startswith(f"# {adv.title}")
    assert "## Abstract" in md
    assert "$$" in md  # Ecuaciones MathJax para foros
    assert "Direct Humanitarian Impact" in md
    assert "Open Science for Humanity" in md


def test_publish_to_zenodo_staged(temp_engine):
    adv = temp_engine.get_advance("geon_retrocausal_mechanics")
    pdf_path = temp_engine.generate_pdf_preprint(adv)

    # Con token vacío, debe generar depósito staged listo con manifiesto y DOI
    rec = temp_engine.publish_to_zenodo(adv, pdf_path)
    assert rec.success is True
    assert rec.target_platform == "zenodo_staged"
    assert rec.doi is not None
    assert rec.doi.startswith("10.5281/zenodo.")

    staged_dir = Path(rec.details["staged_dir"])
    assert staged_dir.exists()
    assert (staged_dir / "zenodo_manifest.json").exists()
    assert (staged_dir / pdf_path.name).exists()


def test_publish_to_discourse_forum(temp_engine):
    adv = temp_engine.get_advance("ecca_harmonic_resonance")
    rec = temp_engine.publish_to_discourse_forum(adv)

    assert rec.success is True
    assert rec.target_platform == "discourse_staged"
    forum_file = Path(rec.details["file"])
    assert forum_file.exists()
    assert forum_file.stat().st_size > 500


def test_publish_physics_advance_complete(temp_engine):
    with patch.object(temp_engine, "send_advance_to_telegram", return_value={"ok": True}):
        res = temp_engine.publish_physics_advance_complete(
            advance_id_or_topic="geon_retrocausal_mechanics",
            send_telegram=True
        )

    assert res["ok"] is True
    assert "Wheeler-Feynman" in res["title"]
    assert res["doi"].startswith("10.5281/zenodo.")
    assert Path(res["pdf_path"]).exists()
    assert Path(res["arxiv_package"]).exists()
    assert res["telegram_result"]["ok"] is True
