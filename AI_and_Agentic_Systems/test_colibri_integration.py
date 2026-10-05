"""
test_colibri_integration.py - Suite de Pruebas de Integración y Validación de Colibri MoE
========================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana GIA
========================================================================================
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent
COLIBRI_DIR = WORKSPACE_DIR / "colibri"


class TestColibriIntegration(unittest.TestCase):

    def test_01_colibri_binaries_present(self):
        """Verifica que los binarios y scripts oficiales de Colibri estén presentes."""
        self.assertTrue(COLIBRI_DIR.exists(), f"El directorio {COLIBRI_DIR} no existe.")
        
        required_files = [
            "colibri.exe",
            "qwen38.exe",
            "deepseek_v4.exe",
            "qwen36.exe",
            "kimi_k3.exe",
            "openai_server.py",
            "coli",
            "coli.cmd",
            "resource_plan.py"
        ]
        
        for fname in required_files:
            fpath = COLIBRI_DIR / fname
            self.assertTrue(fpath.exists(), f"Archivo requerido ausente: {fname}")

    def test_02_optimizer_hardware_detection(self):
        """Verifica la detección de hardware y el cálculo de parámetros optimizados."""
        import colibri_optimizer
        opt = colibri_optimizer.ColibriParameterOptimizer()
        matrix = opt.calculate_tuning_matrix()

        # Verificar hardware detectado
        hw = matrix.get("hardware", {})
        self.assertIn("cpu", hw)
        self.assertIn("memory", hw)
        self.assertIn("gpu", hw)
        self.assertIn("storage", hw)

        # En AMD Ryzen 7 4800H debe detectar 8 núcleos físicos
        self.assertGreaterEqual(hw["cpu"]["physical_cores"], 2)

        # Verificar variables de entorno optimizadas calculadas
        env = matrix.get("environment_variables", {})
        self.assertIn("OMP_NUM_THREADS", env)
        self.assertIn("RAM_GB", env)
        self.assertEqual(env.get("RAM_GB"), "20.0")
        self.assertEqual(env.get("DIRECT"), "1")
        self.assertEqual(env.get("PIPE"), "1")
        self.assertEqual(env.get("PILOT"), "1")
        self.assertEqual(env.get("AUTOPIN"), "1")
        self.assertEqual(env.get("KVSAVE"), "1")
        self.assertEqual(env.get("MTP"), "1")

        # Verificar generación de perfil
        profile_path = opt.save_profile()
        self.assertTrue(profile_path.exists())

    def test_03_bridge_initialization(self):
        """Verifica que ColibriBridge se instancie y exponga los endpoints correctos."""
        import colibri_bridge
        bridge = colibri_bridge.get_colibri()
        self.assertIsNotNone(bridge)
        self.assertEqual(bridge.port, 8765)
        self.assertEqual(bridge.endpoint_url, "http://REDACTED_IP:8765")

        # Debe permitir listar modelos locales sin arrojar excepciones
        local_models = bridge.list_local_colibri_models()
        self.assertIsInstance(local_models, list)

    def test_04_gia_sovereign_engine_integration(self):
        """Verifica que gia_sovereign_engine tenga Colibri activo y mantenga zero-drop."""
        import gia_sovereign_engine as gse

        # Verificar flag de integración activa
        self.assertTrue(getattr(gse, "_COLIBRI_ACTIVE", False), "Colibri no está marcado como activo en gia_sovereign_engine.")

        eng = gse.get_engine()
        self.assertIsNotNone(eng)

        # Verificar preferencias de modelos que incluyen la familia MoE
        self.assertIn("Qwen3.8-Flash-Next", gse.DEFAULT_MODELS_PREFERENCE)
        self.assertIn("Qwen3.6-35B-A3B", gse.DEFAULT_MODELS_PREFERENCE)
        self.assertIn("DeepSeek-V4-Flash", gse.DEFAULT_MODELS_PREFERENCE)

        # Verificar resolución de modelos y diagnóstico
        models = eng.get_available_models()
        self.assertIsInstance(models, list)
        self.assertGreater(len(models), 0)

        resolved = eng.resolve_model()
        self.assertTrue(bool(resolved))

    def test_05_environment_injector(self):
        """Verifica que el optimizador inyecte variables en subprocess sin corromper el entorno."""
        import colibri_optimizer
        opt = colibri_optimizer.ColibriParameterOptimizer()
        applied = opt.get_applied_env()

        self.assertEqual(applied["DIRECT"], "1")
        self.assertEqual(applied["PIPE"], "1")
        self.assertIn(str(COLIBRI_DIR), applied["PATH"])

    def test_06_colibri_redirection_and_ram_allocation(self):
        """Verifica que el procesamiento se redirija por Colibri y use 20 de 24 GB de RAM."""
        import colibri_bridge
        import gia_sovereign_engine as gse

        bridge = colibri_bridge.get_colibri()
        self.assertEqual(bridge.ram_gb, 20.0, "La memoria RAM asignada a Colibri debe ser exactamente 20.0 GB.")

        eng = gse.get_engine()
        res = eng.chat("Test ping Colibri", model="Qwen3.8-27B-Uncensored-MLX:latest")
        self.assertTrue(res.get("ok"), "La inferencia soberana debe completarse exitosamente.")
        self.assertEqual(res.get("provider"), "colibri", "El proveedor de inferencia debe ser Colibri.")
        self.assertEqual(res.get("ram_allocated_gb"), 20.0, "La memoria RAM reservada debe ser 20.0 GB.")
        self.assertEqual(res.get("system_ram_gb"), 24.0, "La memoria RAM total del sistema debe ser 24.0 GB.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
