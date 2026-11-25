#!/usr/bin/env python3
"""
Pruebas integrales del Navegador Soberano Integrado de TARDIS:
  - Normalización inteligente URL/búsqueda y limpieza HTML.
  - Bus de comandos, telemetría UI/DOM, eval_js y persistencia de SovereignBrowserHub.
  - Motor de conclusiones propias (determinístico + estructura completa).
  - Voluntad libre autónoma y protección de control manual.
  - Detector de intención natural en chat (`try_handle_browser_chat_command`).
  - Registro completo en `ToolRegistry` (`SOVEREIGN_BROWSER` + regresión `MUSIC_SOUNDTRACK`).
"""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import tardis_sovereign_browser_agent as sba
from core.tardis_sovereign_browser_agent import (
    SovereignBrowserHub,
    _clean_html_to_text,
    normalize_url_or_search,
    synthesize_tardis_conclusion,
    try_handle_browser_chat_command,
)


class TestUrlAndHtmlUtilities(unittest.TestCase):
    def test_normalize_direct_urls_and_domains(self):
        url, is_search = normalize_url_or_search("https://arxiv.org/list/cs.AI/recent")
        self.assertEqual(url, "https://arxiv.org/list/cs.AI/recent")
        self.assertFalse(is_search)

        url2, is_search2 = normalize_url_or_search("bbc.com/mundo")
        self.assertEqual(url2, "https://bbc.com/mundo")
        self.assertFalse(is_search2)

        url3, is_search3 = normalize_url_or_search("localhost:8757/api/health")
        self.assertEqual(url3, "http://localhost:8757/api/health")
        self.assertFalse(is_search3)

    def test_normalize_search_engines(self):
        url_ddg, is_s = normalize_url_or_search("computación cuántica hoy", "duckduckgo")
        self.assertTrue(is_s)
        self.assertIn("duckduckgo.com", url_ddg)

        url_news, is_n = normalize_url_or_search("inteligencia artificial", "news")
        self.assertTrue(is_n)
        self.assertIn("news.google.com/search", url_news)

        url_arxiv, _ = normalize_url_or_search("state space models", "arxiv")
        self.assertIn("arxiv.org/search", url_arxiv)

        url_wiki, _ = normalize_url_or_search("relatividad general", "wikipedia")
        self.assertIn("es.wikipedia.org", url_wiki)

    def test_clean_html_extracts_title_text_and_absolute_links(self):
        sample = """
        <html>
          <head><title>Noticias Ciencia · Hoy</title><script>var secret=1;</script></head>
          <body>
            <h1>Avance histórico en fusión nuclear controlada</h1>
            <p>Un equipo internacional logró sostener plasma estable durante varios minutos con ganancia energética neta.</p>
            <a href="/articulo/fusion">Leer informe completo</a>
            <a href="https://example.org/paper.pdf">Paper técnico</a>
          </body>
        </html>
        """
        title, text, links = _clean_html_to_text(sample, base_url="https://ciencia.test/portada")
        self.assertEqual(title, "Noticias Ciencia · Hoy")
        self.assertIn("fusión nuclear", text)
        self.assertNotIn("secret=1", text)
        hrefs = [lk["url"] for lk in links]
        self.assertIn("https://ciencia.test/articulo/fusion", hrefs)
        self.assertIn("https://example.org/paper.pdf", hrefs)


class TestSovereignBrowserHub(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        self.hub = SovereignBrowserHub(
            conclusions_file=base / "conclusions.jsonl",
            actions_file=base / "actions.jsonl",
            state_file=base / "state.json",
        )

    def tearDown(self):
        self.hub.set_autonomy(False)
        self.tmpdir.cleanup()

    def test_command_queue_polling_and_actions(self):
        res_nav = self.hub.navigate("arxiv.org", open_ui=True)
        self.assertTrue(res_nav["ok"])
        self.assertEqual(res_nav["url"], "https://arxiv.org")

        self.hub.click(selector="a.primary", text="AI")
        self.hub.type_text(selector="input[name=q]", text="transformers", submit=True)
        self.hub.scroll("down", 600)

        polled = self.hub.poll_commands(since=0)
        self.assertTrue(polled["ok"])
        actions = [c["action"] for c in polled["commands"]]
        self.assertEqual(actions, ["navigate", "click", "type", "scroll"])
        self.assertEqual(polled["latest_seq"], 4)

        polled_delta = self.hub.poll_commands(since=4)
        self.assertEqual(polled_delta["commands"], [])

    def test_ui_report_dom_and_eval_js_roundtrip(self):
        # Conectar UI simulada y responder eval_js en hilo paralelo
        self.hub.report_from_ui({
            "ui_open": True,
            "url": "https://example.org/news",
            "title": "Example World News",
            "dom_text": "Las energías renovables superaron un nuevo récord de generación eléctrica global este trimestre.",
            "links": [{"text": "Detalle", "url": "https://example.org/detail"}],
        })
        self.assertTrue(self.hub.ui_connected)
        state = self.hub.get_state()
        self.assertEqual(state["current_url"], "https://example.org/news")
        self.assertIn("energías renovables", state["dom_preview"])

        def responder():
            time.sleep(0.12)
            polled = self.hub.poll_commands(since=0)
            for cmd in polled["commands"]:
                if cmd["action"] == "eval_js":
                    self.hub.report_from_ui({"eval_seq": cmd["seq"], "eval_result": {"answer": 42}})

        t = threading.Thread(target=responder, daemon=True)
        t.start()
        ev = self.hub.eval_js("({answer: 42})", wait_s=1.5)
        t.join(timeout=2.0)
        self.assertTrue(ev["ok"])
        self.assertEqual(ev.get("result"), {"answer": 42})

    def test_conclude_current_page_persists_and_reloads(self):
        res = self.hub.conclude_current_page(
            url="https://news.example.org/quantum",
            title="Computación Cuántica Tolerante a Fallos",
            text=(
                "Investigadores demostraron un nuevo código de corrección de errores cuánticos que reduce "
                "en un 60 por ciento la sobrecarga de qubits físicos. Esto acerca las aplicaciones prácticas "
                "en simulación molecular y optimización logística antes del final de la década."
            ),
            use_llm=False,
        )
        self.assertTrue(res["ok"])
        c = res["conclusion"]
        self.assertTrue(c["thesis"])
        self.assertTrue(c["tardis_opinion"])
        self.assertGreaterEqual(len(c["key_facts"]), 1)
        self.assertTrue(self.hub.conclusions_file.is_file())

        # Verificar recarga desde disco
        reloaded = SovereignBrowserHub(
            conclusions_file=self.hub.conclusions_file,
            actions_file=self.hub.actions_file,
            state_file=self.hub.state_file,
        )
        self.assertEqual(len(reloaded.get_conclusions()), 1)
        self.assertEqual(reloaded.get_conclusions()[0]["id"], c["id"])

    def test_free_will_session_with_mocked_web_sources(self):
        fake_sources = [
            {"title": "Avance IA Open Source", "url": "https://example.org/ai-open", "summary": "Nuevos modelos locales eficientes."},
            {"title": "Kernel Linux 6.x", "url": "https://example.org/linux-kernel", "summary": "Mejoras de latencia y GPU."},
        ]
        fake_page = {
            "ok": True,
            "url": "https://example.org/ai-open",
            "title": "Avance IA Open Source",
            "text": "Los nuevos modelos abiertos cuantizados alcanzan calidad sobresaliente en GPUs de consumo con menos de 4 GB de VRAM.",
            "links": [],
        }
        with patch.object(sba, "discover_web_sources", return_value=fake_sources), \
             patch.object(sba, "fetch_page_fast", return_value=fake_page), \
             patch.object(sba, "_call_local_llm_json", return_value=None):
            res = self.hub.run_free_will_session(custom_hint="modelos locales eficientes", open_ui=False, use_llm=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["autonomous_cycle"], 1)
        self.assertEqual(res["conclusion"]["pilot"], "autonomous")
        self.assertGreaterEqual(len(self.hub.get_conclusions()), 1)

    def test_take_manual_control_sets_user_pilot(self):
        self.hub.navigate("https://wikipedia.org", pilot="tardis", open_ui=False)
        self.assertEqual(self.hub.get_state()["pilot"], "tardis")
        self.hub.take_manual_control()
        self.assertEqual(self.hub.get_state()["pilot"], "user")


class TestChatIntentAndAgentHarness(unittest.TestCase):
    def test_chat_intent_non_browser_returns_none(self):
        self.assertIsNone(try_handle_browser_chat_command("Hola TARDIS, explícame la entropía termodinámica"))

    def test_chat_intent_open_and_close_browser(self):
        res_open = try_handle_browser_chat_command("Abre el navegador por favor")
        self.assertIsNotNone(res_open)
        self.assertEqual(res_open["action"], "open_browser")
        self.assertEqual(res_open["ui_action"]["command"], "open_browser")

        res_close = try_handle_browser_chat_command("Cierra el navegador ahora")
        self.assertIsNotNone(res_close)
        self.assertEqual(res_close["action"], "close_browser")

    def test_agent_harness_registers_browser_and_music_tools(self):
        from core.agent_harness import ToolRegistry

        reg = ToolRegistry()
        expected_browser = {
            "browser_navigate",
            "browser_search",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_eval_js",
            "browser_read_page",
            "browser_investigate_and_conclude",
            "browser_autonomous_explore",
        }
        for name in expected_browser:
            tool = reg.get_tool(name)
            self.assertIsNotNone(tool, f"Falta herramienta {name} en ToolRegistry")
            self.assertEqual(tool.category, "SOVEREIGN_BROWSER")

        # Verificar no-regresión en MUSIC_SOUNDTRACK tras reubicar registro
        for music_tool in ("music_status", "music_queue", "music_favorite"):
            self.assertIsNotNone(reg.get_tool(music_tool), f"Regresión en {music_tool}")


if __name__ == "__main__":
    unittest.main()
