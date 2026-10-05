import unittest
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.os_controller import get_os_controller
from core.hardware_controller import get_hardware_controller
from omni_temporal_control import process_hardware_chat_intent

class TestScreenUnlockUinput(unittest.TestCase):

    def setUp(self):
        self.os_ctrl = get_os_controller()
        self.hw_ctrl = get_hardware_controller()

    def test_01_is_locked_returns_bool(self):
        locked = self.os_ctrl.is_locked()
        self.assertIsInstance(locked, bool)

    def test_02_uinput_access(self):
        if os.path.exists("/dev/uinput") and os.access("/dev/uinput", os.W_OK):
            success = self.os_ctrl.type_keystrokes_uinput(text="0", press_enter=False, wake_shield=False)
            self.assertTrue(success)

    def test_03_unlock_screen_execution(self):
        res = self.os_ctrl.unlock_screen(password = "REDACTED")
        self.assertIsInstance(res, bool)

    def test_04_hardware_dispatch_unlock(self):
        res = self.hw_ctrl.dispatch_action("unlock_screen", {"password": "0"})
        self.assertIn("ok", res)
        self.assertIn("locked", res)
        self.assertIn("unlocked", res)

    def test_05_chat_slash_unlock(self):
        res = process_hardware_chat_intent("/unlock")
        self.assertIsNotNone(res)
        self.assertEqual(res.get("action"), "unlock_screen")
        self.assertTrue(res.get("direct_return"))
        self.assertIn("desbloqueada", res.get("system_feedback", "").lower())

    def test_06_chat_natural_language_unlock(self):
        res = process_hardware_chat_intent("desbloquea mi dispositivo")
        self.assertIsNotNone(res)
        self.assertEqual(res.get("action"), "unlock_screen")
        self.assertTrue(res.get("direct_return"))

        res2 = process_hardware_chat_intent("desbloquear pantalla")
        self.assertIsNotNone(res2)
        self.assertEqual(res2.get("action"), "unlock_screen")

if __name__ == "__main__":
    unittest.main()
