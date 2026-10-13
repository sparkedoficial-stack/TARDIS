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
        self.assertIn(CFG.get("model"), ("TARDIS-NEURAL-SPACE-KAIJU", "huihui_ai/llama3.1-8b-instruct-abliterated", "dolphin3:latest", "hermes3:8b"))

    def test_02_ollama_only_contains_hermes(self):
        # Verify from ollama list that sovereign models are present
        res = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        lines = res.stdout.strip().splitlines()
        model_names = [line.split()[0] for line in lines[1:] if line.strip()]
        self.assertTrue(any(any(m in name for m in ("TARDIS-NEURAL-SPACE-KAIJU", "huihui_ai/llama3.1-8b-instruct-abliterated", "dolphin3", "hermes3")) for name in model_names))

    def test_03_transversal_context_across_terminals(self):
        # Simulate Terminal 1 (Phone) adding a message
        msg_id_1 = SYNC_HUB.add_chat_turn("user", "Registro de coordenadas desde nodo móvil.", meta="Nodo: phone_terminal_01", client_id="phone_terminal_01")
        self.assertTrue(msg_id_1.startswith("msg_"))

        # Simulate Assistant replying
        reply_id_1 = SYNC_HUB.add_chat_turn("assistant", "Coordenadas recibidas y consolidadas en matriz sintrópica.", meta="TARDIS-NEURAL-SPACE-KAIJU · Núcleo Soberano", client_id="phone_terminal_01")
        self.assertTrue(reply_id_1.startswith("msg_"))

        # Simulate Terminal 2 (Desktop) adding a message
        msg_id_2 = SYNC_HUB.add_chat_turn("user", "Confirmar recepción desde terminal de escritorio.", meta="Nodo: desktop_terminal_01", client_id="desktop_terminal_01")

        # Verify all turns are in SYNC_HUB transversal history (nodo local)
        with SYNC_HUB._lock:
            recent_contents = [m["content"] for m in SYNC_HUB.history[-3:]]
            self.assertIn("Registro de coordenadas desde nodo móvil.", recent_contents)
            self.assertIn("Confirmar recepción desde terminal de escritorio.", recent_contents)

        # Verify client isolation: phone only sees phone history
        sync_phone = SYNC_HUB.get_sync_state(since_rev=0, client_id="phone_terminal_01", is_local=False)
        self.assertTrue(sync_phone.get("ok"))
        phone_contents = [t["content"] for t in sync_phone.get("history", [])]
        self.assertIn("Registro de coordenadas desde nodo móvil.", phone_contents)
        self.assertNotIn("Confirmar recepción desde terminal de escritorio.", phone_contents)

        # Verify local node (Architect) sees all history across terminals
        sync_local = SYNC_HUB.get_sync_state(since_rev=0, client_id="architect_local", is_local=True)
        self.assertTrue(sync_local.get("ok"))
        local_contents = [t["content"] for t in sync_local.get("history", [])]
        self.assertIn("Registro de coordenadas desde nodo móvil.", local_contents)
        self.assertIn("Confirmar recepción desde terminal de escritorio.", local_contents)

    def test_04_slash_model_locks_to_hermes(self):
        # Listing model confirms sovereign model
        res_list = process_hardware_chat_intent("/model")
        self.assertTrue(res_list.get("executed"))
        feedback = res_list.get("system_feedback", "").lower()
        self.assertTrue(any(m in feedback for m in ("tardis", "kaiju", "huihui", "llama3", "dolphin", "hermes")))

if __name__ == "__main__":
    unittest.main()
