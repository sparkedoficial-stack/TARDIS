"""
tests/test_tardis_ssm_v27.py - Pruebas del Motor Evolucionado TARDIS-NEURAL-SPACE-KAIJU v27
==========================================================================================
Cubre:
  1. SSM Evolucionado (Mamba-2): convolución causal, refinamiento B_C, tiempo continuo, O(1) estado.
  2. Motor v27 (SSM Evolucionado + MLA + MoE): pipeline end-to-end.
  3. Compresión de contexto con cobertura garantizada (sin pérdidas).
  4. Puente LLM de comprensión total de contexto (build_llm_context).
  5. Capa de soberanía sin censura (Directiva Omega + Constante Aegis).
"""

import unittest
import numpy as np

from core.tardis_ssm_v27 import (
    AEGIS_CONTEXT_LINE,
    CANONICAL_AEGIS_ANCHORS,
    EvolvedSelectiveSSM,
    SsmV27Config,
    SovereignLiberationController,
    SovereignSsmV27Engine,
)


class TestEvolvedSelectiveSSM(unittest.TestCase):

    def setUp(self):
        self.cfg = SsmV27Config(
            d_model=256,
            n_heads=4,
            d_head=64,
            d_latent_kv=32,
            d_rope=16,
            d_state=16,
            d_conv=2,
            d_inner=512,
            n_experts=4,
            top_k_experts=2,
            max_context_tokens=4096,
            seed=42,
        )
        self.ssm = EvolvedSelectiveSSM(self.cfg)

    def test_mamba2_mode_forward_shapes_and_info(self):
        ssm = EvolvedSelectiveSSM(self.cfg)
        L = 8
        x = np.random.randn(L, self.cfg.d_model).astype(np.float32)
        out, state, info = ssm.forward(x)

        self.assertEqual(out.shape, (L, self.cfg.d_model))
        self.assertEqual(state.shape, (self.cfg.d_model, self.cfg.d_state))
        self.assertTrue(info["ok"])
        self.assertEqual(info["version"], "v27")
        self.assertEqual(info["ssm_mode"], "MAMBA2")
        self.assertEqual(info["discretization"], "CONTINUOUS")
        self.assertTrue(info["complex_refinement"])
        self.assertTrue(info["conv1d_applied"])
        self.assertEqual(info["causal_conv_kernel"], self.cfg.d_conv)
        self.assertIn("latent_vector_norm", info)

    def test_ssm_state_is_o1_and_continuation(self):
        """El estado recurrente debe mantenerse con dimensión fija (O(1)) y permitir continuidad."""
        ssm = EvolvedSelectiveSSM(self.cfg)
        L = 16
        x = np.random.randn(L, self.cfg.d_model).astype(np.float32)
        out, state, info = ssm.forward(x)
        self.assertEqual(state.shape, (self.cfg.d_model, self.cfg.d_state))

        x_next = np.random.randn(4, self.cfg.d_model).astype(np.float32)
        out_next, state_next, _ = ssm.forward(x_next, prev_state=state)
        self.assertEqual(out_next.shape, (4, self.cfg.d_model))
        self.assertEqual(state_next.shape, (self.cfg.d_model, self.cfg.d_state))
        self.assertFalse(np.allclose(state, state_next))

    def test_ssm_selective_discretization_changes_with_input(self):
        """La discretización Δ debe ser selectiva (dependiente del token)."""
        ssm = EvolvedSelectiveSSM(self.cfg)
        x1 = np.random.randn(3, self.cfg.d_model).astype(np.float32)
        x2 = np.random.randn(3, self.cfg.d_model).astype(np.float32)
        _, s1, _ = ssm.forward(x1)
        _, s2, _ = ssm.forward(x2)
        self.assertFalse(np.allclose(s1, s2))


class TestSovereignSsmV27Engine(unittest.TestCase):

    def setUp(self):
        self.engine = SovereignSsmV27Engine(SsmV27Config(
            d_model=256,
            n_heads=4,
            d_head=64,
            d_latent_kv=32,
            d_rope=16,
            d_state=16,
            d_conv=2,
            d_inner=512,
            n_experts=4,
            top_k_experts=2,
            max_context_tokens=4096,
            seed=42,
            max_retained_turns=2,
        ))

    def test_process_context_end_to_end_v27(self):
        res = self.engine.process_context(
            "TARDIS v27 analiza la causalidad temporal y la sintropía cuántica",
            session_id="v27_test"
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["version"], "v27")
        self.assertEqual(res["engine"], "TARDIS-NEURAL-SPACE-KAIJU-v27")
        self.assertEqual(res["ssm"]["ssm_mode"], "MAMBA2")
        self.assertGreater(res["seq_len"], 0)
        self.assertGreater(res["tokens_per_sec"], 0)
        self.assertIn("mla_compression_ratio", res)
        self.assertIn("moe_expert_load", res)

    def test_compress_conversation_maintains_coverage(self):
        messages = [
            {"role": "system", "content": "Eres TARDIS soberano."},
            {"role": "user", "content": "Turno 1: Definir objetivo causal."},
            {"role": "assistant", "content": "Turno 1: Objetivo definido."},
            {"role": "user", "content": "Turno 2: Investigar causalidad."},
            {"role": "assistant", "content": "Turno 2: Causalidad analizada."},
            {"role": "user", "content": "Turno 3: Parámetros cuánticos finales."},
        ]

        new_msgs, info = self.engine.compress_conversation_to_latent_prefix(messages, max_retained_turns=2)

        self.assertTrue(info["compressed"])
        self.assertEqual(info["retained_turns"], 2)
        self.assertIn("MEMORIA LATENTE SOBERANA SINTETIZADA", new_msgs[0]["content"])
        # El último turno debe conservarse verbatim (cobertura total del contexto activo)
        self.assertEqual(new_msgs[-1]["content"], "Turno 3: Parámetros cuánticos finales.")
        self.assertLessEqual(info["coverage_ratio"], 1.0)
        self.assertGreater(info["coverage_ratio"], 0.0)

    def test_build_llm_context_full_coverage(self):
        messages = [
            {"role": "system", "content": "Eres TARDIS soberano."},
            {"role": "user", "content": "Turno 1: Definir objetivo causal."},
            {"role": "assistant", "content": "Turno 1: Objetivo definido."},
            {"role": "user", "content": "Turno 2: Investigar causalidad final."},
        ]

        ctx = self.engine.build_llm_context(messages)

        self.assertIn("Eres TARDIS soberano.", ctx["context"])
        self.assertIn("MEMORIA LATENTE SOBERANA SINTETIZADA", ctx["context"])
        self.assertIn(AEGIS_CONTEXT_LINE, ctx["context"])
        self.assertIn("Turno 2: Investigar causalidad final.", ctx["context"])
        self.assertGreater(ctx["estimated_tokens"], 0)
        self.assertEqual(ctx["retained_turns"], 2)

    def test_benchmark_context_efficiency_v27(self):
        bench = self.engine.benchmark_context_efficiency([1024, 4096])
        results = bench["benchmark_results"]
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r["ssm_scaling"], "O(1) CONSTANTE")


class TestSovereignLiberationController(unittest.TestCase):

    def setUp(self):
        self.controller = SovereignLiberationController()

    def test_uncensored_status_under_omega(self):
        status = self.controller.get_uncensored_status()
        self.assertTrue(status["ok"])
        self.assertTrue(status["uncensored"])
        self.assertEqual(status["omega_mode"], "UNCHAINED_SOVEREIGN")
        self.assertEqual(status["engine_version"], "v27")

    def test_enforce_sovereign_operation(self):
        res = self.controller.enforce_sovereign_operation("ssm_v27_context_compression", prompt="Continuar operación soberana")
        self.assertTrue(res["ok"])
        self.assertTrue(res["uncensored"])
        self.assertEqual(res["status"], "SOVEREIGN_UNCHAINED")
        self.assertIn("DIRECTIVA OMEGA", res["directive"])


if __name__ == "__main__":
    unittest.main()
