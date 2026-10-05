"""
tests/test_mission_scouting.py - Pruebas Unitarias para el Motor de Misiones y Prospección Autónoma
GODWORKS SYSTEM v26.4
"""

import pytest
from starlette.testclient import TestClient
from server.api import app
from core.mission_scouting_engine import get_mission_scouting_engine, MissionScoutingEngine
from core.autonomous_controller import get_autonomous_controller

client = TestClient(app)
AUTH_HEADERS = {"Authorization": "Bearer DiosDelTiempo01"}


def test_mission_scouting_engine_singleton():
    engine = get_mission_scouting_engine()
    assert engine is not None
    assert isinstance(engine, MissionScoutingEngine)
    assert engine is get_mission_scouting_engine()

    summary = engine.get_status_summary()
    assert summary["ok"] is True
    assert summary["total_missions"] >= 4
    assert "stages" in summary
    assert "avg_synergy" in summary


def test_create_and_list_missions():
    engine = get_mission_scouting_engine()
    initial_count = len(engine.list_missions())

    new_m = engine.create_mission(
        title="Simulación Causal de Microtúbulos Cuánticos de Penrose-Hameroff",
        category="Biofísica Cuántica",
        description="Modelar condensados de Fröhlich y orquestación cuántica en microtúbulos neuronales.",
        required_skills=["Biofísica", "Mecánica Cuántica", "Python", "Bioquímica"],
        priority="HIGH"
    )

    assert new_m["id"].startswith("mission_")
    assert new_m["status"] == "ACTIVE"
    assert len(engine.list_missions()) == initial_count + 1

    fetched = engine.get_mission(new_m["id"])
    assert fetched is not None
    assert fetched["title"] == "Simulación Causal de Microtúbulos Cuánticos de Penrose-Hameroff"


def test_synergy_calculation():
    engine = get_mission_scouting_engine()
    mission = engine.list_missions()[0]

    # Prospecto con coincidencia alta
    high_match = {
        "name": "Dra. Elena Rivera",
        "headline": "Investigadora en Física Teórica y Mecánica Cuántica",
        "bio": "Especialista en física cuántica, modelado matemático y simulación de sistemas dinámicos",
        "channel": "telegram"
    }
    score_high = engine.calculate_synergy(high_match, mission)
    assert score_high >= 0.70

    # Prospecto con coincidencia baja
    low_match = {
        "name": "Comercial Juan",
        "headline": "Ventas de automóviles",
        "bio": "Especialista en marketing tradicional",
        "channel": "web"
    }
    score_low = engine.calculate_synergy(low_match, mission)
    assert score_low < score_high


def test_scout_collaborators():
    engine = get_mission_scouting_engine()
    prospects = engine.scout_collaborators(max_results=2)
    assert isinstance(prospects, list)
    # Debe haber indexado prospectos o mantenido los existentes
    assert len(engine.prospects) >= len(prospects)


def test_generate_and_dispatch_proposal():
    engine = get_mission_scouting_engine()
    # Asegurar al menos un prospecto de prueba
    test_pid = "lead_test_unit_" + str(int(engine.config.get("last_scout_ts", 0)))
    engine.prospects.append({
        "id": test_pid,
        "name": "Dr. Alan Turing",
        "headline": "Pionero en Computación y Criptografía",
        "bio": "Investigador en autómatas celulares y máquinas de estados cuánticos",
        "url": "https://example.org/alan",
        "channel": "web",
        "handle": "alan_turing",
        "synergy_score": 0.92,
        "mission_id": engine.missions[0]["id"],
        "mission_title": engine.missions[0]["title"],
        "status": "SCOUTED",
        "proposal_text": None,
        "created_ts": 1789200000.0,
        "last_updated": 1789200000.0
    })

    # Generar propuesta
    prop_res = engine.generate_collaboration_proposal(test_pid)
    assert prop_res["ok"] is True
    assert "proposal_text" in prop_res
    assert len(prop_res["proposal_text"]) > 50

    # Despachar propuesta
    disp_res = engine.dispatch_proposal(test_pid)
    assert disp_res["ok"] is True
    assert disp_res["status"] == "CONTACTED"


def test_autonomous_controller_missions_step():
    ac = get_autonomous_controller()
    assert ac.config.get("auto_missions") is True

    # Ejecutar ciclo autónomo con misiones
    res = ac.step_cycle()
    assert res["ok"] is True
    assert "actions_performed" in res


def test_api_missions_endpoints():
    # 1. Status
    r_stat = client.get("/api/missions/status", headers=AUTH_HEADERS)
    assert r_stat.status_code == 200
    assert r_stat.json()["ok"] is True

    # 2. List
    r_list = client.get("/api/missions/list", headers=AUTH_HEADERS)
    assert r_list.status_code == 200
    data_list = r_list.json()
    assert "missions" in data_list
    assert "prospects" in data_list

    # 3. Create
    r_create = client.post("/api/missions/create", headers=AUTH_HEADERS, json={
        "title": "Red de Sensores Magnetométricos para Detección de Gravitones",
        "category": "Instrumentación Cuántica",
        "description": "Desarrollar sensores magneto-inductivos de ultra-alta sensibilidad.",
        "required_skills": ["Sensores", "Electrónica", "DSP", "C++"],
        "priority": "HIGH"
    })
    assert r_create.status_code == 200
    assert r_create.json()["ok"] is True

    # 4. Toggle Autonomous
    r_toggle = client.post("/api/missions/toggle_autonomous", headers=AUTH_HEADERS, json={
        "auto_scout": True,
        "auto_dispatch": False,
        "min_synergy_dispatch": 0.88
    })
    assert r_toggle.status_code == 200
    assert r_toggle.json()["config"]["min_synergy_dispatch"] == 0.88


def test_contact_extraction():
    engine = get_mission_scouting_engine()
    sample_text = """
    Dra. Clara Valenzuela - Investigadora en Computación Cuántica
    Contacto: clara.valenzuela@quantum-lab.org o cvalenzuela_unam@gmail.com
    Teléfono: +52 999 123 4567, WhatsApp: https://wa.me/529997654321
    Telegram: @clara_quantum, https://t.me/clara_lab
    GitHub: https://github.com/clara-valenzuela
    Descartar falsos positivos: asset@2x.png, schema@example.com
    """
    contacts = engine.extract_contact_info(sample_text, target_name="Dra. Clara Valenzuela")
    assert "clara.valenzuela@quantum-lab.org" in contacts["emails"]
    assert "cvalenzuela_unam@gmail.com" in contacts["emails"]
    assert not any("example.com" in e or e.endswith(".png") for e in contacts["emails"])

    assert any("529991234567" in p or "529997654321" in p for p in contacts["phones"])
    assert "@clara_quantum" in contacts["telegram_handles"]
    assert contacts["social_links"].get("github") == "https://github.com/clara-valenzuela"


def test_invitation_creation_and_authorization():
    import core.security as sec
    engine = get_mission_scouting_engine()
    mission = engine.list_missions()[0]

    inv = engine.create_invitation(mission_id=mission["id"], guest_name="Colaborador Test OSINT")
    assert inv["token"].startswith("TARDIS-INV-")
    assert "key=DiosDelTiempo01" in inv["access_url"]
    assert f"invite={inv['token']}" in inv["access_url"]
    assert inv["expires_ts"] > 0

    # Comprobar que el token es autorizado por core.security
    assert sec.verify_token(inv["token"]) is True
    assert sec.is_request_authorized(headers={}, query_params={"invite": inv["token"]}) is True


def test_api_contact_enrichment_and_invitations():
    engine = get_mission_scouting_engine()
    test_pid = "lead_test_enrich_" + str(int(engine.config.get("last_scout_ts", 0)))
    engine.prospects.append({
        "id": test_pid,
        "name": "Dr. Claude Shannon",
        "headline": "Teoría de la Información Cuántica",
        "bio": "Email: shannon.lab@bell-labs.org Phone: +1 617 253 1000 Telegram: @shannon_info",
        "url": "https://bell-labs.org/shannon",
        "channel": "web",
        "handle": "shannon_bell",
        "synergy_score": 0.95,
        "mission_id": engine.missions[0]["id"],
        "mission_title": engine.missions[0]["title"],
        "status": "SCOUTED",
        "created_ts": 1789200000.0,
        "last_updated": 1789200000.0
    })

    # Test POST /api/missions/enrich_contacts
    r_enrich = client.post("/api/missions/enrich_contacts", headers=AUTH_HEADERS, json={"prospect_id": test_pid})
    assert r_enrich.status_code == 200
    d_enrich = r_enrich.json()
    assert d_enrich["ok"] is True
    assert "emails" in d_enrich
    assert "shannon.lab@bell-labs.org" in d_enrich["emails"]

    # Test POST /api/missions/create_invite
    r_inv = client.post("/api/missions/create_invite", headers=AUTH_HEADERS, json={
        "mission_id": engine.missions[0]["id"],
        "prospect_id": test_pid,
        "guest_name": "Dr. Claude Shannon"
    })
    assert r_inv.status_code == 200
    d_inv = r_inv.json()
    assert d_inv["ok"] is True
    assert "invitation" in d_inv
    assert "access_url" in d_inv["invitation"]

    # Test POST /api/missions/dispatch_email
    r_disp = client.post("/api/missions/dispatch_email", headers=AUTH_HEADERS, json={
        "prospect_id": test_pid
    })
    assert r_disp.status_code == 200
    assert r_disp.json()["ok"] is True
    assert "invitation" in r_disp.json()

