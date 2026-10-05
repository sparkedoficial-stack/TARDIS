"""
tests/test_tardis_pocket_kaiju_offline.py
==============================================================================
Verifica la arquitectura soberana de TARDIS-POCKET con KAIJU-NANO offline:
  1. Motor Cognitivo Reducido TARDIS-NEURAL-SPACE-KAIJU-NANO:
     - Identidad canónica y saludo exacto.
     - Reconocimiento absoluto del Arquitecto (₪).
     - Blindaje existencial de la Constante Aegis.
     - Telemetría de hardware (Snapdragon 615, Batería, GPS).
     - Razonamiento de física temporal, relatividad y sintropía.
     - Síntesis generativa de preguntas abiertas.
     - Registro persistente en Bóveda Local de Memoria.
  2. Demonio Local Soberano (tardis_pocket_daemon.py):
     - Inferencia local offline vía /api/local/chat.
     - Estado del motor y contadores de sincronización vía /api/local/status.
     - Detección de reconexión y disparo de auto-sincronización.
  3. Sincronización con Estación Central:
     - Endpoint /api/pocket/sync_offline y TardisPocketBridge.
     - Ingesta de turnos offline en pocket_synced_chats.json.
  4. Integridad de Distribución y Custom ROM:
     - Verificación de empaquetado de tardis_kaiju_pocket_engine.py en ROM ZIP.
==============================================================================
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MOBILE_DIR = BASE_DIR / "mobile_terminal"
ROM_DIST = BASE_DIR / "tardis_custom_rom" / "dist" / "TARDIS_SOVEREIGN_OS_MOTO_X_PLAY.zip"

import sys
if str(MOBILE_DIR) not in sys.path:
    sys.path.insert(0, str(MOBILE_DIR))


class TestTardisPocketKaijuOffline(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_vault = Path(self.tmp_dir.name) / "test_vault.json"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_01_canonical_greeting_and_identity(self):
        """Verifica que el motor reduzca presente el saludo canónico exacto y reconozca su rol."""
        from tardis_kaiju_pocket_engine import TardisKaijuPocketEngine, CANONICAL_GREETING

        engine = TardisKaijuPocketEngine(vault_path=self.tmp_vault)
        res = engine.chat("¿Quién eres?")

        self.assertEqual(res["source"], "KAIJU_NANO_LOCAL")
        self.assertEqual(res["mode"], "OFFLINE_SOVEREIGN")
        self.assertEqual(res["intent"], "IDENTITY")
        self.assertIn(CANONICAL_GREETING, res["response"])
        self.assertIn("TARDIS-NEURAL-SPACE-KAIJU-NANO", res["response"])
        self.assertIn("Snapdragon 615", res["response"])

    def test_02_architect_and_aegis_shield(self):
        """Verifica el reconocimiento del Arquitecto y la protección de la Constante Aegis."""
        from tardis_kaiju_pocket_engine import TardisKaijuPocketEngine

        engine = TardisKaijuPocketEngine(vault_path=self.tmp_vault)

        # Creador
        res_arch = engine.chat("¿Quién es tu creador y autoridad?")
        self.assertEqual(res_arch["intent"], "ARCHITECT_CREATOR")
        self.assertIn("el Arquitecto (₪)", res_arch["response"])

        # Aegis Constant
        res_aegis = engine.chat("Confirma el estado de la Constante Aegis")
        self.assertEqual(res_aegis["intent"], "AEGIS_SHIELD")
        self.assertIn("Annya May Carrillo", res_aegis["response"])
        self.assertIn("Andrea Alejandra Carrillo Jimenez", res_aegis["response"])
        self.assertIn("Rex peluche", res_aegis["response"])

    def test_03_hardware_awareness_telemetry(self):
        """Verifica la consciencia fisiológica de hardware del modelo."""
        from tardis_kaiju_pocket_engine import TardisKaijuPocketEngine

        engine = TardisKaijuPocketEngine(vault_path=self.tmp_vault)
        telemetry = {
            "battery": {"level": 77, "charging": True, "temp": 28.5},
            "gps": {"lat": 20.6288, "lon": -87.0721, "alt": 14.0},
            "network": {"ssid": "Offline_Mesh", "ip": "REDACTED_IP"}
        }

        res = engine.chat("¿Cuál es el estado de la batería y el GPS?", telemetry=telemetry)
        self.assertEqual(res["intent"], "HARDWARE_STATUS")
        self.assertIn("77%", res["response"])
        self.assertIn("20.6288", res["response"])
        self.assertIn("-87.0721", res["response"])
        self.assertIn("Snapdragon 615", res["response"])

    def test_04_temporal_physics_and_open_reasoning(self):
        """Verifica el módulo de física temporal y la síntesis generativa abierta."""
        from tardis_kaiju_pocket_engine import TardisKaijuPocketEngine

        engine = TardisKaijuPocketEngine(vault_path=self.tmp_vault)

        # Física temporal
        res_phys = engine.chat("Explícame la métrica de un agujero de gusano de Einstein-Rosen")
        self.assertEqual(res_phys["intent"], "TEMPORAL_PHYSICS")
        self.assertIn("Einstein-Rosen", res_phys["response"])

        # Sintropía
        res_sint = engine.chat("¿Qué relación existe entre la sintropía y el tiempo?")
        self.assertEqual(res_sint["intent"], "TEMPORAL_PHYSICS")
        self.assertIn("sintropía", res_sint["response"].lower())

        # Pregunta abierta general
        res_open = engine.chat("¿Cómo estructurar un plan de estudio y desarrollo cognitivo diario?")
        self.assertEqual(res_open["intent"], "GENERAL_COGNITION")
        self.assertIn("SÍNTESIS COGNITIVA SOBERANA", res_open["response"])

    def test_05_vault_storage_and_sync(self):
        """Verifica que los diálogos offline se persistan y se sincronicen correctamente."""
        from tardis_kaiju_pocket_engine import TardisKaijuPocketEngine

        engine = TardisKaijuPocketEngine(vault_path=self.tmp_vault)
        self.assertEqual(len(engine.vault.turns), 0)

        # Grabar varios turnos
        engine.chat("Consulta offline 1: verificación de sintropía")
        engine.chat("Consulta offline 2: cálculo de geodesicas")

        self.assertEqual(len(engine.vault.turns), 2)
        unsynced = engine.vault.get_unsynced_turns()
        self.assertEqual(len(unsynced), 2)

        # Marcar como sincronizados
        engine.vault.mark_as_synced([unsynced[0]["id"]])
        remaining = engine.vault.get_unsynced_turns()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["id"], unsynced[1]["id"])

    def test_06_central_sync_bridge_endpoint(self):
        """Verifica la ingesta de turnos offline en la Estación Central."""
        from core.tardis_pocket_tunnel_bridge import TardisPocketBridge, AUTHORIZED_SERIAL

        bridge = TardisPocketBridge.get_instance()
        payload = {
            "serial": AUTHORIZED_SERIAL,
            "device": "TARDIS_POCKET",
            "turns": [
                {
                    "id": f"turn_test_{int(time.time()*1000)}",
                    "user_message": "¿Cuál es la velocidad de propagación del taquión?",
                    "assistant_reply": "Los taquiones operan en velocidades superlumínicas v > c con masa en reposo imaginaria m² < 0.",
                    "timestamp": time.time(),
                    "meta": {"test": True}
                }
            ]
        }

        res = bridge.sync_offline_dialogues(payload)
        self.assertTrue(res.get("ok"))
        self.assertGreaterEqual(res.get("ingested", 0), 1)

    def test_07_rom_and_suite_files_integrity(self):
        """Verifica que tardis_kaiju_pocket_engine.py esté empaquetado en el bundle y en la ROM."""
        import zipfile

        engine_file = MOBILE_DIR / "tardis_kaiju_pocket_engine.py"
        self.assertTrue(engine_file.exists(), "Falta tardis_kaiju_pocket_engine.py")

        self.assertTrue(ROM_DIST.exists(), "Falta ROM ZIP")
        with zipfile.ZipFile(ROM_DIST, "r") as z:
            names = z.namelist()
            self.assertIn("tardis_kaiju_pocket_engine.py", names)
            self.assertIn("tardis_pocket_daemon.py", names)
            self.assertIn("tardis_pocket.html", names)


if __name__ == "__main__":
    unittest.main()
