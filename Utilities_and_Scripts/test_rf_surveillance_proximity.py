"""
tests/test_rf_surveillance_proximity.py
======================================
Valida la detección de proximidad por tomografía RF (<= 2.2 m),
la emisión del saludo canónico de vigilancia activa de TARDIS,
el registro de metadatos y la histéresis/cooldown temporal (45 s).
"""

import time
import pytest
from rf_presence_radar import (
    RFPresenceRadar,
    PROXIMITY_THRESHOLD_M,
    SURVEILLANCE_COOLDOWN_SEC,
    RFIndividual,
    RF3DEnvironmentState,
)


def test_proximity_threshold_value():
    assert PROXIMITY_THRESHOLD_M == 2.2
    assert SURVEILLANCE_COOLDOWN_SEC == 45.0


def test_proximity_detection_triggers_salute():
    radar = RFPresenceRadar()
    
    received_salutes = []
    def on_surveillance(msg, closest_ind, env):
        received_salutes.append((msg, closest_ind))

    radar.set_surveillance_callback(on_surveillance)

    test_ind = RFIndividual(
        id="IND-NEAR-01",
        label="Individuo Cercano",
        x=0.5,
        y=1.0,
        z=1.0,
        distance=1.25,
        is_moving=True,
        velocity=(0.2, 0.1, 0.0),
        speed_mps=0.22,
        state="EN MOVIMIENTO",
        confidence=0.95,
        breathing_bpm=16,
        signal_absorption_db=3.5,
        fresnel_zone=1
    )
    
    # Evaluar la función de proximidad directamente
    radar._last_surveillance_salute_time = 0.0 # reset cooldown
    salute_msg = radar.check_and_trigger_proximity_surveillance([test_ind])

    assert salute_msg is not None
    assert "Saludos." in salute_msg
    assert "Se encuentra bajo la vigilancia activa del sistema de seguridad de TARDIS, sistema de vigilancia y control temporal." in salute_msg
    assert "1.25 metros" in salute_msg
    assert len(received_salutes) >= 1
    assert "TARDIS, sistema de vigilancia y control temporal" in received_salutes[-1][0]


def test_proximity_cooldown_prevents_spam():
    radar = RFPresenceRadar()
    received_salutes = []
    radar.set_surveillance_callback(lambda msg: received_salutes.append(msg))

    test_ind = RFIndividual(
        id="IND-NEAR-02",
        label="Individuo Cercano 2",
        x=0.8,
        y=0.9,
        z=1.1,
        distance=1.5,
        is_moving=False,
        velocity=(0.0, 0.0, 0.0),
        speed_mps=0.0,
        state="ESTACIONARIO",
        confidence=0.90,
        breathing_bpm=14,
        signal_absorption_db=4.0,
        fresnel_zone=1
    )

    # Primer trigger
    radar._last_surveillance_salute_time = 0.0
    msg1 = radar.check_and_trigger_proximity_surveillance([test_ind])
    assert msg1 is not None
    initial_count = len(received_salutes)
    assert initial_count >= 1

    # Segundo trigger inmediato (debe ser bloqueado por cooldown de 45 segundos)
    msg2 = radar.check_and_trigger_proximity_surveillance([test_ind])
    assert msg2 is None
    assert len(received_salutes) == initial_count

    # Si simulamos que pasaron 46 segundos
    radar._last_surveillance_salute_time = time.time() - 46.0
    msg3 = radar.check_and_trigger_proximity_surveillance([test_ind])
    assert msg3 is not None
    assert len(received_salutes) == initial_count + 1


def test_individuals_outside_threshold_do_not_trigger():
    radar = RFPresenceRadar()
    received_salutes = []
    radar.set_surveillance_callback(lambda msg: received_salutes.append(msg))

    far_ind = RFIndividual(
        id="IND-FAR-01",
        label="Individuo Lejano",
        x=3.0,
        y=3.5,
        z=1.0,
        distance=4.6,
        is_moving=True,
        velocity=(0.3, 0.2, 0.0),
        speed_mps=0.36,
        state="EN MOVIMIENTO",
        confidence=0.85,
        breathing_bpm=18,
        signal_absorption_db=2.0,
        fresnel_zone=2
    )

    radar._last_surveillance_salute_time = 0.0
    salute_msg = radar.check_and_trigger_proximity_surveillance([far_ind])
    assert salute_msg is None
    assert len(received_salutes) == 0
