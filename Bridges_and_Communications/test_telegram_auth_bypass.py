"""
Regresion: bypass de autenticacion por telefono en el bot de Telegram.

Antes, si los digitos del mensaje eran un SUFIJO del telefono permitido, el chat
quedaba autorizado: un solo digito daba control total de TARDIS.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.telegram_bridge import TelegramBridge

ALLOWED = "+52 999 123 4567"
ATTACKER = 555000111
OWNER = 777000222


def _bridge(tmpdir):
    cfg = Path(tmpdir) / "telegram_config.json"
    cfg.write_text(json.dumps({
        "allowed_chats": [], "allowed_phones": [ALLOWED],
        "master_password": "", "master_key": "k" * 64, "bot_token": "", "enabled": False,
    }))
    b = TelegramBridge(config_path=cfg)
    b.send_message = lambda *a, **k: None
    b._print_incoming_request = lambda *a, **k: None
    return b


def _update(chat_id, text="", contact=None, from_id=None):
    msg = {"message_id": 1, "chat": {"id": chat_id},
           "from": {"id": from_id or chat_id, "first_name": "x"}, "text": text}
    if contact:
        msg["contact"] = contact
    return {"update_id": 1, "message": msg}


class TestTelegramPhoneAuth(unittest.TestCase):
    def _run(self, upd):
        with tempfile.TemporaryDirectory() as td:
            b = _bridge(td)
            with patch.object(TelegramBridge, "active_model_label", "test"):
                b._handle_update(upd)
            return [c for c in b.config.get("allowed_chats", [])]

    def test_single_digit_suffix_rejected(self):
        for d in "0123456789":
            self.assertEqual(self._run(_update(ATTACKER, d)), [], f"el digito {d} no debe autorizar")

    def test_typed_full_number_rejected(self):
        self.assertEqual(self._run(_update(ATTACKER, "529991234567")), [])

    def test_someone_elses_contact_rejected(self):
        c = {"phone_number": "529991234567", "user_id": OWNER}
        self.assertEqual(self._run(_update(ATTACKER, contact=c, from_id=ATTACKER)), [])

    def test_short_contact_rejected(self):
        c = {"phone_number": "4567", "user_id": ATTACKER}
        self.assertEqual(self._run(_update(ATTACKER, contact=c, from_id=ATTACKER)), [])

    def test_owner_sharing_own_contact_accepted(self):
        c = {"phone_number": "+529991234567", "user_id": OWNER}
        self.assertEqual(self._run(_update(OWNER, contact=c, from_id=OWNER)), [OWNER])

    def test_master_key_still_works(self):
        self.assertEqual(self._run(_update(OWNER, "k" * 64)), [OWNER])


if __name__ == "__main__":
    unittest.main()
