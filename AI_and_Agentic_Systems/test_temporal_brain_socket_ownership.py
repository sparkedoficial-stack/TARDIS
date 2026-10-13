"""
Regresion: un proceso que no lanzo llama-server no debe borrar su socket.

Caso real (2026-09-22): supervisor.py levanto el motor; omni_temporal_control
creyo que no habia motor, borro el socket vivo y lanzo un duplicado que fallo
por falta de VRAM. El servidor original quedo huerfano e inaccesible.
"""
import os
import socketserver
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from core.temporal_brain import TemporalBrain


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *a):
        pass


class _UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def get_request(self):
        req, _ = super().get_request()
        return req, ("local", 0)


class TestSocketOwnership(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = Path(self.tmp.name) / "brain.sock"
        self.srv = _UnixHTTPServer(str(self.sock), _Health)
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def _brain(self):
        b = TemporalBrain.__new__(TemporalBrain)
        b.socket_path = self.sock
        b._process = None
        b._proc_lock = threading.RLock()
        return b

    def test_start_adopts_live_foreign_server(self):
        b = self._brain()
        ino = os.stat(self.sock).st_ino
        self.assertTrue(b.start(wait_ready=2.0))
        self.assertIsNone(b._process, "no debe lanzar un llama-server duplicado")
        self.assertEqual(os.stat(self.sock).st_ino, ino, "el socket vivo no debe recrearse")

    def test_stop_by_non_owner_keeps_socket(self):
        b = self._brain()
        b.stop()
        self.assertTrue(self.sock.exists(), "stop() de un no-dueno no debe borrar el socket")
        self.assertTrue(b._probe_socket())


if __name__ == "__main__":
    unittest.main()


class TestContextFitting(unittest.TestCase):
    """El historial debe caber en el contexto REAL del servidor (antes: HTTP 400)."""

    def _brain(self, n_ctx=8192):
        b = TemporalBrain.__new__(TemporalBrain)
        b._server_n_ctx = lambda: n_ctx
        return b

    def test_short_conversation_untouched(self):
        msgs = [{"role": "user", "content": "hola"}]
        out, mx = self._brain()._fit_to_context(msgs, 512)
        self.assertEqual(out, msgs)
        self.assertEqual(mx, 512)

    def test_long_history_keeps_system_and_last_turn(self):
        b = self._brain()
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(200):
            msgs.append({"role": "user", "content": f"turno {i} " + "x" * 400})
        msgs.append({"role": "user", "content": "ULTIMO"})
        out, mx = b._fit_to_context(msgs, 1024)
        self.assertEqual(out[0]["content"], "sys")
        self.assertEqual(out[-1]["content"], "ULTIMO")
        self.assertLessEqual(sum(b._msg_tokens(m) for m in out) + mx, 8192)

    def test_single_huge_message_truncated_keeping_tail(self):
        b = self._brain()
        out, mx = b._fit_to_context([{"role": "user", "content": "a" * 100000 + "FINAL"}], 1024)
        self.assertTrue(out[-1]["content"].endswith("FINAL"))
        self.assertLessEqual(sum(b._msg_tokens(m) for m in out) + mx, 8192)

    def test_max_tokens_clamped_to_half_context(self):
        _, mx = self._brain(n_ctx=4096)._fit_to_context([{"role": "user", "content": "hola"}], 999999)
        self.assertEqual(mx, 2048)
