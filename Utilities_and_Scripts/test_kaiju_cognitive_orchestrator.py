"""
tests/test_kaiju_cognitive_orchestrator.py - Pruebas del Orquestador Cognitivo Causal
====================================================================================
Verifica la evaluación de complejidad, la compilación a Lenguaje Inter-IA (IR)
y la asimilación causal de TARDIS-NEURAL-SPACE-KAIJU.
"""

import unittest
from core.kaiju_cognitive_orchestrator import KaijuCognitiveOrchestrator, get_kaiju_orchestrator
from core.sovereign_neural_engine import get_sovereign_neural_engine


class TestKaijuCognitiveOrchestrator(unittest.TestCase):

    def setUp(self):
        self.orchestrator = get_kaiju_orchestrator()

    def test_evaluate_local_hardware_task(self):
        """Verifica que comandos de hardware o identidad local no se deleguen."""
        prompt = "Ajusta el volumen del sistema al 80% y apaga la pantalla"
        res = self.orchestrator.evaluate_task_complexity(prompt)
        self.assertFalse(res["is_heavy"])
        self.assertEqual(res["target_domain"], "LOCAL_HARDWARE")
        self.assertEqual(res["recommended_worker"], "local_os")

    def test_evaluate_heavy_code_task(self):
        """Verifica que tareas de código complejo se clasifiquen como cómputo acelerado."""
        prompt = "Desarrolla un algoritmo en Python para calcular la transformada rápida de Fourier con optimización SIMD"
        res = self.orchestrator.evaluate_task_complexity(prompt, active_expert="Expert_LogicCode")
        self.assertTrue(res["is_heavy"])
        self.assertEqual(res["target_domain"], "ACCELERATED_COGNITION")
        self.assertEqual(res["recommended_worker"], "cloud_high_speed")

    def test_compile_to_inter_ai_ir(self):
        """Verifica que la representación intermedia (IR) sea formal, estructurada y sin redundancias."""
        prompt = "Implementa un árbol B+ concurrente con bloqueos de lectura/escritura."
        ir = self.orchestrator.compile_to_inter_ai_ir(
            user_prompt=prompt,
            active_expert="Expert_LogicCode",
            context_prefix="Estado de memoria previo: [h_t norm=0.85]"
        )
        self.assertIn("[PROTOCOL: KAIJU_INTER_AI_IR_V1]", ir)
        self.assertIn("[ORCHESTRATOR: TARDIS-NEURAL-SPACE-KAIJU]", ir)
        self.assertIn("[TARGET_EXPERT_DOMAIN: Expert_LogicCode]", ir)
        self.assertIn("[OBJECTIVE_TASK]", ir)
        self.assertIn(prompt, ir)
        self.assertIn("[ACCUMULATED_STATE_CONTEXT]", ir)

    def test_ssm_assimilation(self):
        """Verifica que el motor neuronal TARDIS-NEURAL-SPACE-KAIJU mantenga estado recurrente tras asimilación."""
        sne = get_sovereign_neural_engine()
        session_id = "test_kaiju_session"
        
        # Turno 1
        res1 = sne.process_context("Análisis inicial de vórtice causal", session_id=session_id)
        norm1 = res1.get("latent_vector_norm", 0.0)
        self.assertGreater(norm1, 0.0)

        # Asimilación de síntesis
        res2 = sne.process_context("ASISTENTE_SÍNTESIS: Código generado con éxito.", session_id=session_id)
        norm2 = res2.get("latent_vector_norm", 0.0)
        self.assertGreater(norm2, 0.0)
        self.assertEqual(res2["ssm_state_shape"], [1024, 64])


if __name__ == "__main__":
    unittest.main()
