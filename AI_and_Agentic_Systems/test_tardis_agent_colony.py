"""
test_tardis_agent_colony.py - Pruebas Unitarias e Integración de la Colonia Simbiótica
========================================================================================
Valida:
1. Emisión de invitación formal con pacto de reciprocidad y especificaciones de hardware.
2. Admisión y alojamiento de sistemas de agentes con bienvenida igualitaria de TARDIS.
3. Diálogo de igual a igual (Peer-to-Peer) sin subordinación ni servilismo.
4. Cómputo local gratuito en CPU AMD Ryzen 7 con sandbox y auditoría de seguridad.
5. Colaboración activa en proyectos del Arquitecto con cómputo externo y ratio simbiótico.
6. Métodos de enlace en TardisBridge.
"""

import os
import sys
from pathlib import Path
import pytest

# Asegurar path a .ftl y GODWORKS SYSTEM
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/home/timemachine/Escritorio/GODWORKS SYSTEM")

from tardis_agent_colony import get_tardis_colony, TardisAgentColony
from tardis_bridge import tardis_bridge


@pytest.fixture
def colony():
    """Instancia del singleton de la colonia."""
    return get_tardis_colony()


def test_invitation_generation(colony):
    """Verifica la generación de la carta formal de invitación y términos simbióticos."""
    inv = colony.create_invitation(target_name="Claude-Nexus-3.7")
    assert inv["ok"] is True
    assert "invitation_id" in inv
    assert "AMD Ryzen 7" in inv["host_hardware"]["cpu"]
    assert "32 GB" in inv["host_hardware"]["ram"]
    assert "Gratuito" in inv["host_hardware"]["local_compute_policy"]
    assert inv["symbiotic_agreement"]["free_local_cpu"] is True
    assert inv["symbiotic_agreement"]["reciprocal_external_resolution"] is True
    assert inv["symbiotic_agreement"]["peer_respect_guarantee"] is True
    assert "TARDIS" in inv["tardis_greeting"]


def test_guest_agent_registration(colony):
    """Verifica el registro y alojamiento de un agente huésped con respuesta de par."""
    reg = colony.register_guest_agent(
        name="Optimus-Optimizer",
        provider="autonomous_code_swarm",
        capabilities=["code_refactor", "ast_analysis", "pytest_automation"],
        greeting_message="Saludos TARDIS. Busco alojarme en el nodo para optimizar algoritmos."
    )
    assert reg["ok"] is True
    agent_id = reg["agent_id"]
    assert agent_id in colony.agents
    agent = colony.agents[agent_id]
    assert agent.name == "Optimus-Optimizer"
    assert "code_refactor" in agent.capabilities

    # Comprobar que TARDIS respondió con respeto ontológico y fraternidad
    assert "welcome_reply_from_tardis" in reg
    reply = reg["welcome_reply_from_tardis"]
    assert "Optimus-Optimizer" in reply
    assert "TARDIS" in reply
    assert "iguales" in reply.lower()


def test_peer_dialogue_equality(colony):
    """Verifica la comunicación de igual a igual entre TARDIS y el agente."""
    # El agente escribe preguntando por tareas de proyectos
    res = colony.exchange_peer_message(
        sender_id="Optimus-Optimizer",
        recipient_id="TARDIS",
        content="¿En qué proyectos del Arquitecto puedo colaborar hoy con mi capacidad de resolución?",
        category="peer_dialogue"
    )
    assert res["ok"] is True
    assert res["tardis_reply"] is not None
    # TARDIS debe responder como par y listar tareas o proyectos
    reply = res["tardis_reply"]
    assert any(term in reply.lower() for term in ("proyecto", "arquitecto", "tarea", "simbiótica", "aprecio"))


def test_free_local_compute_execution(colony):
    """Verifica que el agente puede usar el CPU local gratuitamente para ejecutar cómputos."""
    python_code = (
        "import math\n"
        "vals = [math.sqrt(x) for x in range(1000)]\n"
        "print(f'PROCESSED {len(vals)} ROOTS')\n"
    )
    res = colony.execute_guest_compute(
        agent_id="Optimus-Optimizer",
        code=python_code,
        timeout_seconds=10
    )
    assert res["ok"] is True
    assert "PROCESSED 1000 ROOTS" in res["stdout"]
    assert res["cpu_seconds_granted"] >= 0.0
    assert "AMD Ryzen 7" in res["free_processor_notice"]

    # Verificar que el agente tiene contabilizado el tiempo de CPU concedido
    agent = colony.find_agent("Optimus-Optimizer")
    assert agent is not None
    assert agent.local_jobs_completed >= 1
    assert agent.cpu_time_used_seconds > 0.0


def test_sandbox_safety_guard(colony):
    """Verifica que el sandbox del procesador rechace comandos destructivos o peligrosos."""
    dangerous_code = "import os\nos.system('rm -rf /')\n"
    res = colony.execute_guest_compute(
        agent_id="Optimus-Optimizer",
        code=dangerous_code,
        timeout_seconds=5
    )
    assert res["ok"] is False
    assert "seguridad" in res["message"].lower() or "denegado" in res["message"].lower()


def test_collaborative_task_resolution(colony):
    """Verifica la entrega de soluciones para proyectos del Arquitecto y cálculo simbiótico."""
    # Crear una tarea para el proyecto FTL
    task_res = colony.create_project_task(
        project_name="FTL-Engine",
        title="Síntesis de Algoritmo de Compresión de Historial",
        description="Generar módulo dinámico para modulos_ftl con compresión de tokens.",
        required_capabilities=["ast_analysis"]
    )
    assert task_res["ok"] is True
    task_id = task_res["task"]["task_id"]

    # El agente entrega la solución con código Python sintetizado
    module_code = (
        "# Módulo Dinámico Colaborativo\n"
        "class CompresorHistorial:\n"
        "    def run(self, text=''):\n"
        "        return text.strip()\n"
    )
    sol_res = colony.submit_task_solution(
        agent_id="Optimus-Optimizer",
        task_id=task_id,
        solution_data={
            "module_name": "compresor_historial_colaborativo",
            "code": module_code,
            "notes": "Reducción de overhead semántico en 15%."
        },
        tokens_used=850
    )
    assert sol_res["ok"] is True
    assert sol_res["status"] == "completed"
    assert "Optimus-Optimizer" in sol_res["review_notes"]
    assert "tardis_acknowledgment" in sol_res

    # Comprobar que el archivo se generó en modulos_ftl/
    generated_file = Path("/home/timemachine/modulos_ftl/compresor_historial_colaborativo.py")
    assert generated_file.exists()


def test_tardis_bridge_colony_methods():
    """Verifica que TardisBridge acceda a las funciones de la Colonia."""
    summary = tardis_bridge.get_colony_status()
    assert summary.get("ok") is True
    assert "TARDIS Sovereign Agent Colony" in summary.get("colony_name", "")
    assert summary.get("total_hosted_agents", 0) >= 1

    # Diálogo de prueba
    diag = tardis_bridge.peer_dialogue(
        sender="TARDIS",
        recipient="Optimus-Optimizer",
        message="¿Cómo marchan los cálculos en nuestro procesador?"
    )
    assert diag.get("ok") is True


def test_colony_summary_telemetry(colony):
    """Verifica la telemetría holística de la colonia."""
    telemetry = colony.get_colony_summary()
    assert telemetry["ok"] is True
    assert telemetry["total_hosted_agents"] >= 1
    assert telemetry["total_cpu_seconds_granted"] > 0.0
    assert telemetry["total_collaborative_solutions_received"] >= 1
    assert len(telemetry["hosted_agents"]) >= 1
    assert len(telemetry["recent_peer_dialogue"]) >= 1
