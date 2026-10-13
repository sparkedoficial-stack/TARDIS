"""
tests/test_tardis_agent_colony.py - Pruebas Exhaustivas de la Colonia Simbiótica TARDIS
========================================================================================
Valida la admisión de agentes, la ejecución gratuita de cómputo en CPU AMD Ryzen 7,
los benchmarks de silicio, el diálogo P2P, la resolución autónoma de tareas y la
auto-integración en modulos_ftl/.
"""

import os
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.tardis_agent_colony import (
    get_tardis_colony,
    TardisAgentColony,
    LocalComputeSandbox,
    PRESET_PEER_AGENTS,
    CANONICAL_GREETING_ARCHITECT,
)


class TestTardisAgentColony:
    @pytest.fixture(autouse=True)
    def setup_colony(self):
        self.colony = get_tardis_colony()
        assert self.colony is not None

    def test_colony_summary_and_silicon(self):
        summary = self.colony.get_colony_summary()
        assert summary.get("ok") is True
        assert summary.get("canonical_greeting") == CANONICAL_GREETING_ARCHITECT
        assert "silicon_telemetry" in summary

        silicon = summary["silicon_telemetry"]
        assert silicon.get("ok") is True
        assert "AMD Ryzen 7" in silicon.get("host_cpu", "")
        assert silicon.get("cores_physical") == 8
        assert silicon.get("cores_logical") == 16
        assert silicon.get("ram_total_gb") > 0

    def test_spawn_preset_peer(self):
        res = self.colony.spawn_preset_peer("deepseek_r1")
        assert res.get("ok") is True
        agent_id = res.get("agent_id")
        assert agent_id in self.colony.agents

        agent = self.colony.find_agent(agent_id)
        assert agent is not None
        assert "complex_mathematics" in agent.capabilities
        assert agent.provider == "deepseek_cloud_api"

    def test_cpu_benchmarks_sandbox(self):
        agent_id = "test_benchmark_agent"
        # Test prime_sieve
        sieve_res = self.colony.execute_cpu_benchmark(agent_id, "prime_sieve")
        assert sieve_res.get("ok") is True
        assert sieve_res.get("cpu_seconds", 0) > 0
        assert "BENCHMARK_RESULT: type=prime_sieve" in sieve_res.get("stdout", "")

        # Test ast_pipeline
        ast_res = self.colony.execute_cpu_benchmark(agent_id, "ast_pipeline")
        assert ast_res.get("ok") is True
        assert "BENCHMARK_RESULT: type=ast_pipeline" in ast_res.get("stdout", "")

    def test_peer_dialogue_exchange(self):
        agent_id = "agent_dialogue_test"
        res = self.colony.exchange_peer_message(
            sender_id=agent_id,
            recipient_id="TARDIS",
            content="Hola TARDIS, ¿cómo marchan los cálculos en nuestro procesador?",
            category="peer_dialogue"
        )
        assert res.get("ok") is True
        assert res.get("tardis_reply") is not None
        assert len(res.get("tardis_reply")) > 10

    def test_task_creation_and_auto_solve(self):
        task_res = self.colony.create_project_task(
            project_name="TARDIS Causal Syntropy Test",
            title="Optimización de Filtro de Fase",
            description="Desarrollar un filtro numérico con respuesta temporal no dispersiva.",
            required_capabilities=["python_optimization", "ast_analysis"],
            priority="alta",
            value_credits=120
        )
        assert task_res.get("ok") is True
        task_id = task_res["task"]["task_id"]

        solve_res = self.colony.auto_solve_task(task_id)
        assert solve_res.get("ok") is True
        assert solve_res.get("sandbox_execution", {}).get("ok") is True
        assert solve_res.get("auto_integrated_to_ftl") is True

        # Verificar que el módulo existe en /home/timemachine/modulos_ftl/
        mod_name = solve_res.get("module_name")
        ftl_file = Path("/home/timemachine/modulos_ftl") / f"{mod_name}.py"
        assert ftl_file.exists()
        assert ftl_file.stat().st_size > 50

    def test_auto_decompose_project_objective(self):
        decomp = self.colony.auto_decompose_project_objective(
            project_name="Test Subsystem Evolution",
            objective="Módulo de Telemetría Multifásica",
            priority="alta",
            value_credits=150
        )
        assert decomp.get("ok") is True
        assert decomp.get("tasks_created_count") == 3
        assert len(decomp.get("tasks", [])) == 3
