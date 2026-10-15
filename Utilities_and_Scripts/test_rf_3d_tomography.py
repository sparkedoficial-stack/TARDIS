"""
tests/test_rf_3d_tomography.py - Pruebas Unitarias de Tomografía RF y Detección 3D de Presencia Humana
Verifica:
1. analyze_3d_environment() detecta individuos, cuenta exacta y discriminación de movimiento.
2. Atributos de individuos: coordenadas 3D, distancia al host, vectores de velocidad, respiración BPM y absorción RF.
3. generate_3d_environment_mesh() sintetiza Mesh3D completo (perímetro, cuadrícula, Fresnel, avatares 3D y vectores).
4. Integración con core/render_3d_engine.py (preset 'rf_room' y alias).
5. Endpoints REST (/api/sensors/rf_3d_environment y /api/rf_radar/3d).
"""

import time
import pytest
from starlette.testclient import TestClient

from rf_presence_radar import (
    RFPresenceRadar,
    RFRadarState,
    RFIndividual,
    RF3DEnvironmentState,
    get_rf_3d_environment,
    get_rf_3d_mesh,
)
from core.render_3d_engine import get_render_3d_engine
from server.api import app

client = TestClient(app)


def test_analyze_3d_environment_structure():
    """Verifica que el análisis RF 3D devuelva una estructura completa y coherente del entorno."""
    radar = RFPresenceRadar()
    env = radar.analyze_3d_environment(room_dimensions=(6.0, 6.0, 2.8))

    assert isinstance(env, RF3DEnvironmentState)
    assert env.room_dimensions == (6.0, 6.0, 2.8)
    assert env.host_node_position == (0.0, 0.0, 0.85)
    assert env.individuals_count >= 0
    assert len(env.individuals) == env.individuals_count
    assert env.overall_motion_state in ("QUIET", "MICRO_MOTION", "ACTIVE_MOTION", "MULTI_INTRUSION", "STATIONARY_PRESENCE")

    # Si hay individuos detectados, comprobar sus parámetros físicos
    for ind in env.individuals:
        assert isinstance(ind, RFIndividual)
        assert ind.id.startswith("INDIVIDUO_")
        # Dentro de las dimensiones de la habitación (-3 a +3 en X, Y y 0 a 2.8 en Z)
        assert -3.1 <= ind.x <= 3.1
        assert -3.1 <= ind.y <= 3.1
        assert 0.0 <= ind.z <= 2.8
        assert ind.distance >= 0.0
        assert isinstance(ind.is_moving, bool)
        assert len(ind.velocity) == 3
        assert ind.speed_mps >= 0.0
        assert ind.state in ("ESTACIONARIO", "MICROMOVIMIENTO", "EN MOVIMIENTO")
        assert 10 <= ind.breathing_bpm <= 35
        assert 0.5 <= ind.signal_absorption_db <= 15.0


def test_rf_environment_motion_discrimination():
    """Verifica que si la varianza RSSI supera el umbral, se marque movimiento activo."""
    radar = RFPresenceRadar()

    # Simular condiciones de movimiento en el radar
    active_state = RFRadarState(
        timestamp=time.time(),
        active_bssid_count=2,
        primary_bssid="AA:BB:CC:DD:EE:01",
        mean_variance=8.5,
        max_variance=12.0,
        shannon_entropy=2.45,
        total_rf_energy_uw=150.0,
        sample_rate_hz=10.0,
        confidence=0.92,
        presence_state="ACTIVE_MOTION",
        detected_nodes=[
            {"ssid": "Wi-Fi-Office", "bssid": "AA:BB:CC:DD:EE:01", "latest_rssi_dbm": -45, "variance": 9.2},
            {"ssid": "Wi-Fi-Guest", "bssid": "AA:BB:CC:DD:EE:02", "latest_rssi_dbm": -60, "variance": 11.5}
        ]
    )
    with radar._lock:
        radar._last_state = active_state

    env = radar.analyze_3d_environment()
    assert env.individuals_count >= 1
    assert env.has_individuals is True
    assert env.overall_motion_state == "ACTIVE_MOTION"

    # Al menos un individuo debe registrar movimiento activo
    moving_individuals = [ind for ind in env.individuals if ind.is_moving]
    assert len(moving_individuals) >= 1
    for ind in moving_individuals:
        assert ind.speed_mps > 0.1
        assert ind.state == "EN MOVIMIENTO"
        assert ind.velocity != (0.0, 0.0, 0.0)


def test_generate_3d_environment_mesh():
    """Verifica que la generación de la malla 3D contenga vértices, aristas y metadatos correctos."""
    radar = RFPresenceRadar()
    mesh = radar.generate_3d_environment_mesh(room_dimensions=(6.0, 6.0, 2.8))
    
    assert "Entorno RF" in (mesh.title or mesh.name)
    assert len(mesh.vertices) > 20
    assert len(mesh.edges) > 10
    assert mesh.node_labels is not None
    # El nodo principal debe estar etiquetado
    assert any("NODO PRINCIPAL" in lbl for lbl in mesh.node_labels.values())

    # Comprobar que se exporte a diccionario JSON-serializable
    mesh_dict = mesh.to_dict()
    assert "vertices" in mesh_dict
    assert "edges" in mesh_dict


def test_global_helpers():
    """Verifica las funciones globales de conveniencia."""
    env_dict = get_rf_3d_environment()
    assert isinstance(env_dict, dict)
    assert "individuals_count" in env_dict
    assert "host_node_position" in env_dict

    mesh = get_rf_3d_mesh()
    assert mesh is not None
    assert hasattr(mesh, "vertices")
    assert len(mesh.vertices) > 0


def test_render_3d_engine_rf_room_catalog():
    """Verifica que el motor 3D central registre y sirva dinámicamente el preset 'rf_room'."""
    engine = get_render_3d_engine()
    catalog = engine.get_catalog()
    catalog_ids = [m["id"] for m in catalog]
    assert "rf_room" in catalog_ids

    # Obtener el modelo y comprobar síntesis en tiempo real
    mesh = engine.get_mesh("rf_room")
    assert mesh is not None
    assert "Entorno RF" in (mesh.title or mesh.name)
    assert len(mesh.vertices) > 20

    # Comprobar aliases
    for alias in ("rf", "radar", "entorno_rf", "tomografia", "wifi_radar"):
        mesh_alias = engine.get_mesh(alias)
        assert mesh_alias is not None
        assert mesh_alias.name == mesh.name


def test_api_rf_3d_environment_endpoints():
    """Verifica los endpoints REST /api/sensors/rf_3d_environment y /api/rf_radar/3d."""
    # 1. /api/sensors/rf_3d_environment
    resp1 = client.get("/api/sensors/rf_3d_environment")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["ok"] is True
    assert "environment" in data1
    assert "mesh" in data1
    assert "individuals_count" in data1["environment"]
    assert "individuals" in data1["environment"]

    # 2. /api/rf_radar/3d
    resp2 = client.get("/api/rf_radar/3d")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["ok"] is True
    assert "environment" in data2
    assert "mesh" in data2
