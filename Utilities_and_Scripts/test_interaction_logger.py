"""
GODWORKS SYSTEM v26.4 - Unit Tests for Interaction Logger
Verifica:
1. Creación de directorios locales (~/vw-control/interactions/photos/).
2. Formateo de fecha y hora cronológica en español (Día, YYYY-MM-DD, HH:MM:SS).
3. Guardado físico de fotos en disco local (JPEG) a partir de recortes o capturas.
4. Generación automática y actualización de la galería HTML autónoma local.
5. Consulta de historial y eliminación segura de registros y archivos en disco.
"""

import os
import base64
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from core.interaction_logger import (
    InteractionLogger,
    DAYS_ES,
    MONTHS_ES
)


@pytest.fixture
def temp_logger():
    """Instancia aislada de InteractionLogger con directorio temporal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir) / "interactions"
        logger = InteractionLogger(base_dir=base_dir)
        yield logger


def test_interaction_logger_initialization(temp_logger):
    """Verifica que los directorios y archivos base se inicialicen en disco."""
    assert temp_logger.interactions_dir.exists()
    assert temp_logger.photos_dir.exists()
    # Log file and gallery are generated when saving
    interactions = temp_logger.list_interactions()
    assert isinstance(interactions, list)
    assert len(interactions) == 0


def test_spanish_day_and_time_formatting(temp_logger):
    """Verifica que el día de la semana, fecha y hora estén en español y con formato exacto."""
    interaction = temp_logger.record_interaction(
        interaction_type="test",
        title="Prueba de Sistema",
        details="Verificando formato de día y hora",
        individual={"id": "indiv_01", "name": "Usuario de Prueba", "role": "Operador"},
        capture_system_screenshot=False
    )

    assert "id" in interaction
    assert "day_name" in interaction
    assert interaction["day_name"] in DAYS_ES.values()
    assert "date" in interaction
    assert len(interaction["date"].split("-")) == 3
    assert "time" in interaction
    assert len(interaction["time"].split(":")) == 3
    assert interaction["individual_name"] == "Usuario de Prueba"
    assert interaction["title"] == "Prueba de Sistema"


def test_log_interaction_with_synthetic_photo(temp_logger):
    """Verifica el guardado físico de fotos JPEG en disco decodificadas desde base64."""
    # JPEG sintético mínimo en base64
    minimal_jpeg_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="

    interaction = temp_logger.record_interaction(
        interaction_type="presence_detection",
        title="Presencia Detectada",
        details="Individuo detectado frente a la cámara",
        individual={"id": "indiv_test_01", "name": "Visitante Detectado", "role": "Visitante"},
        photo_b64=minimal_jpeg_b64,
        capture_system_screenshot=False
    )

    assert interaction["photo_filename"] != ""
    assert interaction["photo_filename"].endswith(".jpg")

    photo_path = temp_logger.photos_dir / interaction["photo_filename"]
    assert photo_path.exists()
    assert photo_path.stat().st_size > 0

    history = temp_logger.list_interactions()
    assert len(history) == 1
    assert history[0]["id"] == interaction["id"]


def test_html_gallery_generation(temp_logger):
    """Verifica que la galería autónoma HTML local se genere con diseño y datos de interacciones."""
    minimal_jpeg_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="

    temp_logger.record_interaction(
        interaction_type="chat",
        title="Interacción con GIA",
        details="Consulta sobre modelos de IA",
        individual={"id": "indiv_creator", "name": "Miguel Angel May Canche", "role": "Creador"},
        photo_b64=minimal_jpeg_b64,
        capture_system_screenshot=False
    )

    assert temp_logger.gallery_html.exists()
    content = temp_logger.gallery_html.read_text(encoding="utf-8")

    assert "<!DOCTYPE html>" in content
    assert "TARDIS v26.4" in content
    assert "Miguel Angel May Canche" in content
    assert "Consulta sobre modelos de IA" in content
    assert "photos/" in content


def test_delete_interaction_removes_photo_and_record(temp_logger):
    """Verifica que al borrar una interacción se remueva tanto del JSON como el archivo físico."""
    minimal_jpeg_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="

    interaction = temp_logger.record_interaction(
        interaction_type="manual_snapshot",
        title="Captura Manual",
        details="Foto para prueba de borrado",
        individual={"id": "indiv_op", "name": "Operador", "role": "Controlador"},
        photo_b64=minimal_jpeg_b64,
        capture_system_screenshot=False
    )

    photo_path = temp_logger.photos_dir / interaction["photo_filename"]
    assert photo_path.exists()

    deleted = temp_logger.delete_interaction(interaction["id"])
    assert deleted is True

    history = temp_logger.list_interactions()
    assert len(history) == 0
    assert not photo_path.exists()


@patch("subprocess.Popen")
def test_open_local_folder(mock_popen, temp_logger):
    """Verifica que open_local_folder invoque xdg-open con la ruta absoluta en Linux."""
    res = temp_logger.open_local_folder()
    assert res["ok"] is True
    assert str(temp_logger.photos_dir) in res["folder"]
    mock_popen.assert_called_once()
