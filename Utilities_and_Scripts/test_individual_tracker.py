"""
GODWORKS SYSTEM v26.4 - Unit Tests for Individual Tracker & Biometric Recognition
Verifica:
1. Inicialización y persistencia de identidades en bóveda (known_individuals.json).
2. Extracción de firmas biométricas (LBP + HSV) y similitud coseno.
3. Detección simultánea de múltiples individuos y estimación de cercanía (near, desk, room).
4. Asignación de nombres (bautismo) y actualización de roles.
5. Reconocimiento de identidades guardadas en frames posteriores.
6. Integración con telemetría de frontend.
"""

import tempfile
import time
from pathlib import Path
import numpy as np
import pytest

from core.individual_tracker import (
    IndividualTracker,
    extract_face_signature,
    cosine_similarity,
    get_individual_tracker
)


@pytest.fixture
def temp_tracker():
    """Instancia de IndividualTracker aislada con base de datos temporal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_individuals.json"
        tracker = IndividualTracker(db_path=db_file)
        yield tracker


def test_initial_db_creation_and_creator(temp_tracker):
    """Verifica que al crearse la base se siembre automáticamente al Creador."""
    known = temp_tracker.list_known_individuals()
    assert len(known) >= 1
    creator = temp_tracker.get_individual("indiv_creator")
    assert creator is not None
    assert "Miguel Angel May Canche" in creator["name"]
    assert "Creador" in creator["role"] or "Arquitecto" in creator["role"]


def test_face_signature_extraction():
    """Verifica que la extracción de firma LBP + HSV retorne el vector de 176 dimensiones."""
    crop = np.zeros((80, 80, 3), dtype=np.uint8)
    crop[:, :] = (110, 140, 200) # Tono de piel sintético
    sig = extract_face_signature(crop)
    assert len(sig) == 176
    assert isinstance(sig[0], float)

    # Similaridad con sí mismo debe ser 1.0
    sim_self = cosine_similarity(sig, sig)
    assert pytest.approx(sim_self, abs=1e-3) == 1.0


def test_signature_similarity_distinguishes_different_tones():
    """Verifica que tonos y texturas marcadamente diferentes tengan baja similitud."""
    crop1 = np.zeros((80, 80, 3), dtype=np.uint8)
    crop1[::2, ::2] = (110, 140, 200)
    crop1[1::2, 1::2] = (80, 100, 150)

    crop2 = np.zeros((80, 80, 3), dtype=np.uint8)
    crop2[:, ::3] = (220, 20, 20)
    crop2[:, 1::3] = (20, 220, 20)

    sig1 = extract_face_signature(crop1)
    sig2 = extract_face_signature(crop2)

    sim = cosine_similarity(sig1, sig2)
    assert sim < 0.70


def test_multi_individual_synthetic_frame_detection(temp_tracker):
    """Verifica la detección y conteo de múltiples individuos en una misma escena."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # Individuo 1: Cercano a la cámara (caja grande)
    frame[50:260, 80:240] = (110, 140, 200) # BGR compatible piel humana

    # Individuo 2: Al fondo / fondo de habitación (caja mediana)
    frame[120:220, 420:510] = (110, 140, 200)

    res = temp_tracker.process_frame(frame)
    assert res["ok"] is True
    assert res["count"] == 2
    assert "Múltiples Individuos" in res["occupancy_label"]

    indivs = res["individuals"]
    assert len(indivs) == 2
    proximities = [ind["proximity"] for ind in indivs]
    assert any("cercano" in p.lower() or "escritorio" in p.lower() for p in proximities)


def test_name_and_recognize_individual(temp_tracker):
    """Verifica que se pueda bautizar/nombrar a un individuo y reconocerlo posteriormente."""
    crop_alice = np.full((80, 80, 3), (110, 140, 200), dtype=np.uint8)
    sig_alice = extract_face_signature(crop_alice)

    # 1. Bautizar a Alice
    name_res = temp_tracker.name_individual(
        target_id="unknown_1",
        name="Alice Smith",
        role="Investigadora Cuántica",
        signature=sig_alice
    )
    assert name_res["ok"] is True
    alice_id = name_res["individual"]["id"]
    assert alice_id.startswith("indiv_")

    # 2. Verificar lista de conocidos
    known = temp_tracker.list_known_individuals()
    alice_entry = next((k for k in known if k["id"] == alice_id), None)
    assert alice_entry is not None
    assert alice_entry["name"] == "Alice Smith"
    assert alice_entry["role"] == "Investigadora Cuántica"

    # 3. Presentar un frame que contiene a Alice
    frame_with_alice = np.zeros((480, 640, 3), dtype=np.uint8)
    frame_with_alice[100:260, 200:330] = (110, 140, 200)

    res_alice = temp_tracker.process_frame(frame_with_alice)
    assert res_alice["count"] >= 1
    matched = res_alice["individuals"][0]
    assert matched["is_known"] is True
    assert matched["name"] == "Alice Smith"
    assert matched["role"] == "Investigadora Cuántica"
    assert matched["confidence"] >= 0.70


def test_delete_individual(temp_tracker):
    """Verifica la eliminación de una identidad registrada."""
    name_res = temp_tracker.name_individual(
        target_id="unknown_temp",
        name="Invitado Temporal",
        role="Visitante"
    )
    temp_id = name_res["individual"]["id"]

    del_ok = temp_tracker.delete_individual(temp_id)
    assert del_ok is True
    assert temp_tracker.get_individual(temp_id) is None

    # Intentar borrar de nuevo debe retornar False
    assert temp_tracker.delete_individual(temp_id) is False


def test_update_from_frontend_telemetry(temp_tracker):
    """Verifica que la telemetría del navegador actualice el estado de presencia."""
    telemetry = {
        "detected": True,
        "face_box": {"x": 100, "y": 80, "w": 180, "h": 220},
        "primary": "enfocado",
        "mood_state": "Enfocado en terminal"
    }

    state = temp_tracker.update_from_frontend_telemetry(telemetry)
    assert state["count"] == 1
    assert "1 Individuo" in state["occupancy_label"]
    assert len(state["individuals"]) == 1
    indiv = state["individuals"][0]
    assert indiv["name"] == "Miguel Angel May Canche" # Reconocido como creador/operador único
    assert indiv["is_known"] is True
