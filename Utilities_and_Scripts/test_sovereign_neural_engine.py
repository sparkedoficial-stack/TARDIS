"""
tests/test_sovereign_neural_engine.py - Pruebas del Motor Neuronal Soberano (MLA + SSM + MoE)
"""

import unittest
import numpy as np

from core.sovereign_neural_engine import (
    NeuralConfig,
    MultiHeadLatentAttention,
    SelectiveStateSpaceCompressor,
    SparseContextMoE,
    SovereignNeuralEngine,
    get_sovereign_neural_engine
)


class TestSovereignNeuralEngine(unittest.TestCase):

    def setUp(self):
        self.cfg = NeuralConfig(
            d_model=256,
            n_heads=4,
            d_head=64,
            d_latent_kv=32,
            d_rope=16,
            d_state=16,
            d_inner=512,
            n_experts=4,
            top_k_experts=2,
            seed=42
        )
        self.engine = SovereignNeuralEngine(self.cfg)

    def test_singleton_instance(self):
        eng1 = get_sovereign_neural_engine()
        eng2 = get_sovereign_neural_engine()
        self.assertIs(eng1, eng2)

    def test_mla_compression_and_forward(self):
        """Verifica que MLA comprima la caché KV reduciendo drásticamente su tamaño."""
        mla = MultiHeadLatentAttention(self.cfg)
        L = 8
        x = np.random.randn(L, self.cfg.d_model).astype(np.float32)

        out, cache = mla.forward(x)

        # Forma de salida debe coincidir con [L, d_model]
        self.assertEqual(out.shape, (L, self.cfg.d_model))

        # La caché solo debe almacenar c_kv [L, d_latent_kv] y k_rope [L, d_rope]
        self.assertIn("c_kv", cache)
        self.assertEqual(cache["c_kv"].shape, (L, self.cfg.d_latent_kv))
        self.assertIn("k_rope", cache)
        self.assertEqual(cache["k_rope"].shape, (L, self.cfg.d_rope))

        # Tasa de compresión debe ser superior al 80% (ratio >= 5.0)
        self.assertGreater(cache["compression_ratio"], 5.0)

    def test_ssm_linear_recurrence(self):
        """Verifica que SSM mantenga una memoria de estado O(1) independientemente de L."""
        ssm = SelectiveStateSpaceCompressor(self.cfg)
        L = 16
        x = np.random.randn(L, self.cfg.d_model).astype(np.float32)

        out, state = ssm.forward(x)

        self.assertEqual(out.shape, (L, self.cfg.d_model))
        self.assertEqual(state.shape, (self.cfg.d_model, self.cfg.d_state))

        # Probar paso continuo con estado previo
        x_next = np.random.randn(4, self.cfg.d_model).astype(np.float32)
        out_next, state_next = ssm.forward(x_next, prev_state=state)

        self.assertEqual(out_next.shape, (4, self.cfg.d_model))
        self.assertEqual(state_next.shape, (self.cfg.d_model, self.cfg.d_state))
        self.assertFalse(np.allclose(state, state_next))

    def test_moe_top_k_routing(self):
        """Verifica el enrutamiento disperso de tokens entre los expertos especializados."""
        moe = SparseContextMoE(self.cfg)
        L = 10
        x = np.random.randn(L, self.cfg.d_model).astype(np.float32)

        out, info = moe.forward(x)

        self.assertEqual(out.shape, (L, self.cfg.d_model))
        self.assertIn("expert_load", info)

        total_activations = sum(info["expert_load"].values())
        # Cada token activa top_k expertos: total = L * top_k
        self.assertEqual(total_activations, L * self.cfg.top_k_experts)

    def test_process_context_end_to_end(self):
        """Verifica el procesamiento de texto a través del pipeline híbrido completo."""
        text = "TARDIS analiza las líneas temporales y computa sintropía causal"
        res = self.engine.process_context(text, session_id="test_sess")

        self.assertTrue(res["ok"])
        self.assertGreater(res["seq_len"], 0)
        self.assertGreater(res["tokens_per_sec"], 0)
        self.assertIn("ssm_state_shape", res)
        self.assertIn("moe_expert_load", res)

    def test_compress_conversation_to_latent_prefix(self):
        """Verifica que una conversación larga se comprima sin perder contexto."""
        messages = [
            {"role": "system", "content": "Eres TARDIS."},
            {"role": "user", "content": "Turno 1: Definir objetivo."},
            {"role": "assistant", "content": "Turno 1: Objetivo definido."},
            {"role": "user", "content": "Turno 2: Investigar causalidad."},
            {"role": "assistant", "content": "Turno 2: Causalidad analizada."},
            {"role": "user", "content": "Turno 3: Parámetros cuánticos."},
            {"role": "assistant", "content": "Turno 3: Cuánticos listos."},
            {"role": "user", "content": "Turno 4: Pregunta final actual."}
        ]

        compact_msgs, info = self.engine.compress_conversation_to_latent_prefix(messages, max_retained_turns=2)

        self.assertTrue(info["compressed"])
        self.assertEqual(info["retained_turns"], 2)
        self.assertIn("MEMORIA LATENTE SOBERANA SINTETIZADA", compact_msgs[0]["content"])
        self.assertEqual(compact_msgs[-1]["content"], "Turno 4: Pregunta final actual.")

    def test_benchmark_context_efficiency(self):
        """Verifica que el benchmark de eficiencia demuestre el ahorro masivo de RAM."""
        bench = self.engine.benchmark_context_efficiency([1024, 4096, 16384])
        results = bench["benchmark_results"]

        self.assertEqual(len(results), 3)
        for r in results:
            self.assertLess(r["mla_latent_cache_mb"], r["mha_kv_cache_mb"])
            self.assertEqual(r["ssm_scaling"], "O(1) CONSTANTE")


if __name__ == "__main__":
    unittest.main()
