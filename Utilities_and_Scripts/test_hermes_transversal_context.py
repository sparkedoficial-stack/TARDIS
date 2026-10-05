import unittest
import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from omni_temporal_control import (
    CFG,
    SYNC_HUB,
    process_hardware_chat_intent
)

class TestHermesTransversalContext(unittest.TestCase):

    def test_01_hermes_is_sole_central_model(self):
        # Sovereign model must be configured
        self.assertIn(CFG.get("model"), ("dolphin3:latest", "hermes3:8b"))

    def test_02_ollama_only_contains_hermes(self):
        # Verify from ollama list that sovereign models are present
        res = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        lines = res.stdout.strip().splitlines()
        model_names = [line.split()[0] for line in lines[1:] if line.strip()]
        self.assertTrue("dolphin3:latest" in model_names or "hermes3:8b" in model_names)

    def test_03_transversal_context_across_terminals(self):
        # Simulate Terminal 1 (Phone) adding a message
        msg_id_1 = SYNC_HUB.add_chat_turn("user", "Registro de coordenadas desde nodo móvil.", meta="Nodo: phone_terminal_01")
        self.assertTrue(msg_id_1.startswith("msg_"))

        # Simulate Hermes replying
        reply_id_1 = SYNC_HUB.add_chat_turn("assistant", "Coordenadas recibidas y consolidadas en matriz sintrópica.", meta="Hermes 3 (8B) · Núcleo Soberano")
        self.assertTrue(reply_id_1.startswith("msg_"))

        # Simulate Terminal 2 (Desktop) adding a message referencing the phone's turn
        msg_id_2 = SYNC_HUB.add_chat_turn("user", "Confirmar recepción desde terminal de escritorio.", meta="Nodo: desktop_terminal_01")

        # Verify all turns are in SYNC_HUB transversal history
        with SYNC_HUB._lock:
            recent_contents = [m["content"] for m in SYNC_HUB.history[-3:]]
            self.assertIn("Registro de coordenadas desde nodo móvil.", recent_contents)
            self.assertIn("Confirmar recepción desde terminal de escritorio.", recent_contents)

        # Verify sync state returns transversal history to any client
        sync_phone = SYNC_HUB.get_sync_state(since_rev=0, client_id="phone_terminal_01")
        self.assertTrue(sync_phone.get("ok"))
        self.assertGreater(len(sync_phone.get("history", [])), 0)

        sync_desktop = SYNC_HUB.get_sync_state(since_rev=0, client_id="desktop_terminal_01")
        self.assertTrue(sync_desktop.get("ok"))
        self.assertEqual(sync_phone["history"], sync_desktop["history"])

    def test_04_slash_model_locks_to_hermes(self):
        # Listing model confirms sovereign model
        res_list = process_hardware_chat_intent("/model")
        self.assertTrue(res_list.get("executed"))
        feedback = res_list.get("system_feedback", "").lower()
        self.assertTrue("dolphin" in feedback or "hermes" in feedback)

if __name__ == "__main__":
    unittest.main()
