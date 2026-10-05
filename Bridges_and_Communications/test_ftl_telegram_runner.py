import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import ftl_telegram_runner as ftr
from core.ftl_telegram_runner import FTLTelegramRunner, parse_request
from core.protected_users_vault import ARCHITECT_TELEGRAM_ID
from core.telegram_bridge import TelegramBridge


class TestParseRequest(unittest.TestCase):
    def test_help_status_cancel(self):
        self.assertEqual(parse_request("").action, "help")
        self.assertEqual(parse_request("estado").action, "status")
        self.assertEqual(parse_request("cancelar").action, "cancel")

    def test_mode_dir_and_multiline_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            req = parse_request(f"-m claude -d {d} crea un módulo\ncon pruebas")
            self.assertEqual(req.mode, "claude")
            self.assertEqual(req.cwd, Path(d).resolve())
            self.assertEqual(req.prompt, "crea un módulo\ncon pruebas")
            self.assertFalse(req.error)

    def test_rejects_shell_escape_and_bad_input(self):
        self.assertTrue(parse_request("$ rm -rf /tmp/x").error)
        self.assertTrue(parse_request("! ls").error)
        self.assertTrue(parse_request("-m inexistente hola").error)
        self.assertTrue(parse_request("-d /no/existe/jamas hola").error)


class TestNoiseFilter(unittest.TestCase):
    def test_filters_rich_panels(self):
        self.assertTrue(ftr.is_ui_noise("╭────╮"))
        self.assertTrue(ftr.is_ui_noise("│ ⚡ router │"))
        self.assertTrue(ftr.is_ui_noise("  ✔ [Finalizado] ━━━━━━ 100%"))
        self.assertFalse(ftr.is_ui_noise("Creé hola.py y lo ejecuté."))


class TestRunner(unittest.TestCase):
    def test_runs_job_and_reports_output(self):
        with tempfile.TemporaryDirectory() as d:
            fake_cli = Path(d) / "fake_ftl.py"
            fake_cli.write_text("import sys; print('\\x1b[32mHECHO\\x1b[0m', sys.argv[1:])\n")
            sent = []
            runner = FTLTelegramRunner(lambda body, chat, reply: sent.append(body), ftl_cli=fake_cli)
            with patch.object(ftr, "JOBS_DIR", Path(d) / "jobs"):
                runner.handle(1, f"-m claude -d {d} -- mejora esto", None)
                for _ in range(100):
                    if runner.current is None and len(sent) >= 3:
                        break
                    time.sleep(0.05)
            joined = "\n".join(sent)
            self.assertIn("FTL terminó tu petición", joined)
            self.assertIn("HECHO", joined)
            self.assertNotIn("\x1b", joined)
            self.assertIn("&#x27;-m&#x27;, &#x27;claude&#x27;, &#x27;--&#x27;", joined)

    def test_only_one_job_at_a_time(self):
        with tempfile.TemporaryDirectory() as d:
            fake_cli = Path(d) / "slow.py"
            fake_cli.write_text("import time; time.sleep(30)\n")
            sent = []
            runner = FTLTelegramRunner(lambda body, chat, reply: sent.append(body), ftl_cli=fake_cli)
            with patch.object(ftr, "JOBS_DIR", Path(d) / "jobs"):
                runner.handle(1, "tarea uno", None)
                self.assertIsNone(runner.submit(1, parse_request("tarea dos")))
                self.assertIn("ya está trabajando", sent[-1])
                time.sleep(0.3)
                runner.cancel()
                for _ in range(100):
                    if runner.current is None:
                        break
                    time.sleep(0.05)
            self.assertIsNone(runner.current)


class TestBridgeIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = TelegramBridge(config_path=Path(self.tmp.name) / "cfg.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_non_admin_denied(self):
        other = 555000111
        self.bridge.authorize_chat(other)
        with patch.object(self.bridge, "send_message") as send, \
             patch("core.ftl_telegram_runner.FTLTelegramRunner.handle") as handle:
            self.bridge._handle_incoming_text(other, "/FTL crea algo", "Otro")
            handle.assert_not_called()
            send.assert_called()

    def test_admin_uppercase_and_botname_routed(self):
        self.bridge.authorize_chat(ARCHITECT_TELEGRAM_ID)
        with patch.object(self.bridge, "send_message"), \
             patch("core.ftl_telegram_runner.FTLTelegramRunner.handle") as handle:
            self.bridge._handle_incoming_text(ARCHITECT_TELEGRAM_ID, "/FTL@TardisBot crea\nun script", "Arq")
            handle.assert_called_once()
            self.assertEqual(handle.call_args.args[1], "crea\nun script")


if __name__ == "__main__":
    unittest.main()
