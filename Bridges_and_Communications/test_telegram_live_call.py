import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from aiohttp.test_utils import AioHTTPTestCase

from core.telegram_live_call_server import (
    _extract_ready_sentence,
    build_live_call_url,
    create_app,
    sign_call_token,
    verify_call_token,
    verify_telegram_init_data,
)


class TestTelegramLiveCallCryptoAndSentenceSplit(unittest.TestCase):
    def test_sign_and_verify_call_token(self):
        token = sign_call_token(chat_id=REDACTED_PHONE, user_name="Arquitecto")
        parsed = verify_call_token(token)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["c"], "REDACTED_PHONE")
        self.assertEqual(parsed["n"], "Arquitecto")
        self.assertIsNone(verify_call_token(token + "x"))
        self.assertIsNone(verify_call_token("invalid"))

    def test_verify_telegram_webapp_init_data(self):
        bot_token = "REDACTED"
        user_json = json.dumps({"id": REDACTED_PHONE, "first_name": "Arquitecto"}, separators=(",", ":"))
        fields = {"auth_date": "REDACTED_PHONE", "query_id": "AAHdF6IQAAAAAN0XohDhrOrc", "user": user_json}
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        sig = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
        init_data = urlencode({**fields, "hash": sig})

        verified = verify_telegram_init_data(init_data, bot_token=bot_token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["user"]["id"], REDACTED_PHONE)
        self.assertIsNone(verify_telegram_init_data(init_data + "0", bot_token=bot_token))

    def test_extract_ready_sentence(self):
        s, rem = _extract_ready_sentence("Hola Arquitecto, te escucho perfectamente. ¿Cómo estás?", is_first=True)
        self.assertEqual(s, "Hola Arquitecto, te escucho perfectamente.")
        self.assertEqual(rem, "¿Cómo estás?")

    def test_build_live_call_url(self):
        url = build_live_call_urlREDACTED_PHONE, "Arquitecto")
        if url:
            self.assertIn("/tg-call?ct=", url)


class TestTelegramLiveCallHTTP(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_health_and_call_page(self):
        resp = await self.client.request("GET", "/tg-call/health")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ok"])

        bad = await self.client.request("GET", "/tg-call?ct=bad.token")
        self.assertEqual(bad.status, 403)

        good_ct = sign_call_tokenREDACTED_PHONE, "Arquitecto")
        ok = await self.client.request("GET", f"/tg-call?ct={good_ct}")
        self.assertEqual(ok.status, 200)
        html = await ok.text()
        self.assertIn("INICIAR LLAMADA EN VIVO", html)


if __name__ == "__main__":
    unittest.main()
