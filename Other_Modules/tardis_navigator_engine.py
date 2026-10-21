#!/usr/bin/env python3
"""
core/tardis_navigator_engine.py - Motor de Asistencia de Búsqueda IA y Automatización de Procesos Web
=====================================================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4
Arquitecto: El Arquitecto (₪)

Capacidades:
1. Asistente de Búsqueda Multi-Motor con Síntesis IA (TARDIS-NEURAL-SPACE-KAIJU / Groq LPU / RAG Vault):
   - Búsqueda simultánea en DuckDuckGo, Google News, Wikipedia (ES/EN), arXiv, HackerNews y Bóveda RAG.
   - Síntesis cognitiva con citas estructuradas, extracción de hallazgos y sugerencias de navegación.
   - Copiloto Contextual de Pestaña Activa (responde preguntas sobre el DOM en vivo de la página actual,
     resume artículos, extrae tablas, precios, enlaces y código).
2. Estudio de Automatización de Procesos (TARDIS Process Automation Studio):
   - Ejecución de flujos paso a paso (Workflows) directamente sobre las pestañas reales de WebKit2
     o en segundo plano mediante el motor Chromium CDP / Turbo HTTP2.
   - Acciones soportadas:
     * navigate (Navegar a URL)
     * search_web (Buscar en motores web y abrir resultados)
     * click (Hacer clic en selector CSS o por texto visible de botón/enlace con resaltado visual)
     * fill (Rellenar inputs/formularios por selector, nombre, placeholder o buscador automático)
     * submit / press_enter (Enviar formulario o presionar Enter)
     * scroll (Desplazamiento suave: down, up, bottom, top o píxeles)
     * wait (Espera controlada en segundos)
     * extract_dom (Extracción estructurada: summary_dom, links, tables, prices, code, selector)
     * eval_js (Ejecución de JavaScript arbitrario en la pestaña activa)
     * ai_synthesize (Análisis y síntesis con TARDIS IA sobre los datos extraídos en el flujo)
     * rag_ftl_learn (Ingesta en Bóveda RAG Soberana + generación de módulo de auto-mejora FTL)
     * screenshot (Captura de pantalla PNG de la pestaña / navegador)
     * open_tabs (Apertura de múltiples pestañas con las URLs encontradas)
     * shell_cmd (Ejecución de comando/script local del sistema desacoplado)
   - Generador Agéntico de Automatizaciones (Lenguaje Natural -> Flujo JSON ejecutable).
   - Grabadora de Macros en Vivo (DOM Recorder para clics, escritura y envío de formularios).
   - Programador de Tareas Periódicas (Scheduler en segundo plano).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("TARDIS.NavigatorEngine")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

NAVIGATOR_DATA_DIR = Path.home() / ".tardis" / "navigator"
NAVIGATOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR = NAVIGATOR_DATA_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

BOOKMARKS_FILE = NAVIGATOR_DATA_DIR / "bookmarks.json"
HISTORY_FILE = NAVIGATOR_DATA_DIR / "history.json"
WORKFLOWS_FILE = NAVIGATOR_DATA_DIR / "workflows.json"
SCHEDULES_FILE = NAVIGATOR_DATA_DIR / "schedules.json"

CANONICAL_GREETING = (
    "Un placer, soy TARDIS asistente de inteligencia artificial, "
    "mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales."
)


# ==============================================================================
# 1. DATOS PREDEFINIDOS (MARCADORES Y FLUJOS DE AUTOMATIZACIÓN SOBERANOS)
# ==============================================================================
DEFAULT_BOOKMARKS: List[Dict[str, str]] = [
    {"title": "🏠 Portal TARDIS", "url": "http://127.0.0.1:8777/portal", "category": "Soberano"},
    {"title": "🛸 Cabina Maestra Hub", "url": "http://127.0.0.1:8757/hub", "category": "Soberano"},
    {"title": "🦆 DuckDuckGo", "url": "https://duckduckgo.com", "category": "Búsqueda"},
    {"title": "🌐 Google", "url": "https://www.google.com", "category": "Búsqueda"},
    {"title": "📚 Wikipedia ES", "url": "https://es.wikipedia.org", "category": "Conocimiento"},
    {"title": "🔬 arXiv Quantum/AI", "url": "https://arxiv.org/list/cs.AI/recent", "category": "Ciencia"},
    {"title": "💻 GitHub", "url": "https://github.com", "category": "Código"},
    {"title": "⚡ HackerNews", "url": "https://news.ycombinator.com", "category": "Tecnología"},
    {"title": "🛒 MercadoLibre MX", "url": "https://www.mercadolibre.com.mx", "category": "Comercio"},
    {"title": "📦 Amazon MX", "url": "https://www.amazon.com.mx", "category": "Comercio"},
]

DEFAULT_WORKFLOWS: List[Dict[str, Any]] = [
    {
        "id": "wf_deep_research",
        "name": "🔬 Investigación Profunda Multi-Pestaña + Síntesis RAG",
        "description": "Busca un tema en múltiples motores (Wikipedia, arXiv, DuckDuckGo), navega a la fuente principal, extrae el DOM completo, sintetiza un informe técnico con TARDIS IA y lo asimila en la Bóveda RAG + FTL.",
        "category": "Investigación",
        "default_param": "Computación cuántica y corrección de errores topológicos",
        "steps": [
            {"action": "search_web", "query": "{{param}}", "max_results": 5, "open_first": True},
            {"action": "wait", "seconds": 2.0},
            {"action": "scroll", "direction": "down", "amount": 500},
            {"action": "extract_dom", "mode": "summary_dom"},
            {"action": "screenshot", "label": "fuente_principal"},
            {
                "action": "ai_synthesize",
                "prompt": "Elabora un informe técnico exhaustivo sobre '{{param}}' integrando los resultados de búsqueda multi-motor y el contenido extraído de la página activa. Incluye puntos clave, arquitectura/ecuaciones si aplican y enlaces a las fuentes."
            },
            {"action": "rag_ftl_learn", "topic": "{{param}}"}
        ],
    },
    {
        "id": "wf_wikipedia_interactive",
        "name": "🧭 Automatización Interactiva en Wikipedia (Rellenar + Buscar + Extraer)",
        "description": "Abre Wikipedia en español, localiza automáticamente la caja de búsqueda en el DOM, escribe el término deseado con resaltado visual, envía el formulario, recorre el artículo, extrae tablas/secciones y genera un resumen ejecutivo.",
        "category": "Automatización DOM",
        "default_param": "Agujero negro",
        "steps": [
            {"action": "navigate", "url": "https://es.wikipedia.org"},
            {"action": "wait", "seconds": 1.5},
            {"action": "fill", "selector": "input[name='search']", "value": "{{param}}", "press_enter": True},
            {"action": "wait", "seconds": 2.5},
            {"action": "scroll", "direction": "down", "amount": 600},
            {"action": "extract_dom", "mode": "summary_dom"},
            {"action": "extract_dom", "mode": "tables"},
            {"action": "screenshot", "label": "wikipedia_articulo"},
            {
                "action": "ai_synthesize",
                "prompt": "Resume de manera estructurada y rigurosa el artículo de Wikipedia cargado sobre '{{param}}', destacando definiciones, datos clave de las tablas y hallazgos principales."
            }
        ],
    },
    {
        "id": "wf_price_offer_hunter",
        "name": "🛒 Cazador de Ofertas, Precios y Comparativa Automática",
        "description": "Busca productos u ofertas en la web, inspecciona la página activa para extraer precios, descuentos y enlaces de compra, y construye una tabla comparativa con recomendaciones de TARDIS.",
        "category": "Comercio & Scraping",
        "default_param": "Laptop ASUS TUF Gaming RTX oferta precio",
        "steps": [
            {"action": "search_web", "query": "{{param}}", "max_results": 6, "open_first": True},
            {"action": "wait", "seconds": 2.0},
            {"action": "scroll", "direction": "down", "amount": 700},
            {"action": "extract_dom", "mode": "prices"},
            {"action": "extract_dom", "mode": "links"},
            {
                "action": "ai_synthesize",
                "prompt": "Analiza las ofertas, precios y enlaces encontrados para '{{param}}'. Organiza una tabla comparativa Markdown con las mejores opciones, precios detectados y enlaces directos."
            }
        ],
    },
    {
        "id": "wf_page_full_audit",
        "name": "🕸️ Auditoría Técnica, Scraping Integral y Extracción de Tablas/Código",
        "description": "Ejecuta un barrido completo sobre la pestaña activa actual: hace scroll para cargar contenido dinámico, extrae encabezados H1-H3, metadatos, todas las tablas HTML, bloques de código y enlaces, y genera un reporte técnico.",
        "category": "Scraping & Auditoría",
        "default_param": "Auditoría completa de la página actual",
        "steps": [
            {"action": "scroll", "direction": "down", "amount": 600},
            {"action": "wait", "seconds": 1.0},
            {"action": "scroll", "direction": "top", "amount": 0},
            {"action": "extract_dom", "mode": "summary_dom"},
            {"action": "extract_dom", "mode": "tables"},
            {"action": "extract_dom", "mode": "links"},
            {"action": "screenshot", "label": "auditoria_pagina"},
            {
                "action": "ai_synthesize",
                "prompt": "Realiza una auditoría técnica y síntesis estructural de la página web actual. Resume su propósito, estructura de encabezados, datos relevantes en tablas/código y enlaces principales."
            }
        ],
    },
    {
        "id": "wf_hn_arxiv_radar",
        "name": "📡 Radar Ciber-Científico (HackerNews + arXiv) + Auto-Mejora FTL",
        "description": "Explora los últimos avances sobre el tema indicado en arXiv y HackerNews, abre las fuentes principales en pestañas del navegador y sintetiza un módulo de evolución FTL.",
        "category": "Evolución FTL",
        "default_param": "State Space Models Mamba Transformer inference optimization",
        "steps": [
            {"action": "search_web", "query": "{{param}}", "max_results": 5, "open_first": True},
            {"action": "wait", "seconds": 2.0},
            {"action": "extract_dom", "mode": "summary_dom"},
            {
                "action": "ai_synthesize",
                "prompt": "Extrae los algoritmos centrales, arquitecturas y mejoras de rendimiento sobre '{{param}}' a partir de los papers y discusiones técnicas encontradas."
            },
            {"action": "rag_ftl_learn", "topic": "{{param}}"}
        ],
    },
    {
        "id": "wf_multi_tab_opener",
        "name": "🗂️ Apertura Masiva de Fuentes en Pestañas + Resumen Comparativo",
        "description": "Busca un tema, abre automáticamente las 3 mejores fuentes verificadas en pestañas reales del navegador TARDIS y genera una síntesis comparativa de todas las fuentes.",
        "category": "Productividad",
        "default_param": "Kernel Linux eBPF optimización de baja latencia",
        "steps": [
            {"action": "search_web", "query": "{{param}}", "max_results": 5, "open_first": False},
            {"action": "open_tabs", "count": 3},
            {"action": "wait", "seconds": 2.5},
            {"action": "extract_dom", "mode": "summary_dom"},
            {
                "action": "ai_synthesize",
                "prompt": "Compara y sintetiza la información de las fuentes abiertas sobre '{{param}}', destacando las mejores prácticas, comandos y conclusiones."
            }
        ],
    },
]


# ==============================================================================
# 2. GESTIÓN DE PERSISTENCIA (MARCADORES, HISTORIAL, FLUJOS)
# ==============================================================================
class NavigatorPersistence:
    """Almacenamiento JSON persistente e hilo-seguro para el navegador TARDIS."""

    def __init__(self):
        self._lock = threading.Lock()
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        if not BOOKMARKS_FILE.exists():
            self._write_json(BOOKMARKS_FILE, DEFAULT_BOOKMARKS)
        if not HISTORY_FILE.exists():
            self._write_json(HISTORY_FILE, [])
        if not WORKFLOWS_FILE.exists():
            self._write_json(WORKFLOWS_FILE, DEFAULT_WORKFLOWS)
        else:
            # Asegurar que los flujos predefinidos estén presentes
            existing = self._read_json(WORKFLOWS_FILE, [])
            existing_ids = {w.get("id") for w in existing if isinstance(w, dict)}
            changed = False
            for dw in DEFAULT_WORKFLOWS:
                if dw["id"] not in existing_ids:
                    existing.append(dw)
                    changed = True
            if changed:
                self._write_json(WORKFLOWS_FILE, existing)
        if not SCHEDULES_FILE.exists():
            self._write_json(SCHEDULES_FILE, [])

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Error leyendo {path}: {e}")
        return default

    def _write_json(self, path: Path, data: Any) -> None:
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Error escribiendo {path}: {e}")

    def get_bookmarks(self) -> List[Dict[str, str]]:
        with self._lock:
            return self._read_json(BOOKMARKS_FILE, DEFAULT_BOOKMARKS)

    def add_bookmark(self, title: str, url: str, category: str = "General") -> List[Dict[str, str]]:
        with self._lock:
            bms = self._read_json(BOOKMARKS_FILE, DEFAULT_BOOKMARKS)
            if not any(b.get("url") == url for b in bms):
                bms.append({"title": title[:60] or url, "url": url, "category": category})
                self._write_json(BOOKMARKS_FILE, bms)
            return bms

    def remove_bookmark(self, url: str) -> List[Dict[str, str]]:
        with self._lock:
            bms = [b for b in self._read_json(BOOKMARKS_FILE, DEFAULT_BOOKMARKS) if b.get("url") != url]
            self._write_json(BOOKMARKS_FILE, bms)
            return bms

    def add_history(self, title: str, url: str, engine: str = "webkit2") -> None:
        if not url or url.startswith("http://127.0.0.1:8777/copilot"):
            return
        with self._lock:
            hist = self._read_json(HISTORY_FILE, [])
            entry = {
                "title": (title or url)[:120],
                "url": url,
                "engine": engine,
                "timestamp": time.time(),
                "time_str": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            # Evitar duplicado consecutivo idéntico
            if hist and hist[0].get("url") == url:
                hist[0] = entry
            else:
                hist.insert(0, entry)
            self._write_json(HISTORY_FILE, hist[:300])

    def get_history(self, limit: int = 80) -> List[Dict[str, Any]]:
        with self._lock:
            return self._read_json(HISTORY_FILE, [])[:limit]

    def clear_history(self) -> None:
        with self._lock:
            self._write_json(HISTORY_FILE, [])

    def get_workflows(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._read_json(WORKFLOWS_FILE, DEFAULT_WORKFLOWS)

    def save_workflow(self, wf: Dict[str, Any]) -> List[Dict[str, Any]]:
        with self._lock:
            wfs = self._read_json(WORKFLOWS_FILE, DEFAULT_WORKFLOWS)
            wf_id = wf.get("id") or f"wf_custom_{int(time.time())}_{uuid.uuid4().hex[:4]}"
            wf["id"] = wf_id
            wf.setdefault("name", "Flujo Personalizado TARDIS")
            wf.setdefault("description", "Proceso automatizado creado en TARDIS Automation Studio.")
            wf.setdefault("category", "Personalizado")
            wf.setdefault("default_param", "")
            wf.setdefault("steps", [])

            replaced = False
            for idx, existing in enumerate(wfs):
                if existing.get("id") == wf_id:
                    wfs[idx] = wf
                    replaced = True
                    break
            if not replaced:
                wfs.insert(0, wf)
            self._write_json(WORKFLOWS_FILE, wfs)
            return wfs

    def delete_workflow(self, wf_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            wfs = [w for w in self._read_json(WORKFLOWS_FILE, DEFAULT_WORKFLOWS) if w.get("id") != wf_id]
            self._write_json(WORKFLOWS_FILE, wfs)
            return wfs


# ==============================================================================
# 3. ASISTENTE DE BÚSQUEDA E INTELIGENCIA SOBERANA TARDIS
# ==============================================================================
class TardisSearchAssistant:
    """
    Orquesta búsquedas multi-motor, consultas al RAG Vault e inferencia con
    TARDIS-NEURAL-SPACE-KAIJU (vía Cloud LPU 350 tok/s o Hub Local :8757).
    """

    def __init__(self):
        from core.web_research_engine import get_web_research_engine
        self.research_engine = get_web_research_engine()

    def invoke_tardis_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1600,
        temperature: float = 0.25,
        timeout: float = 25.0,
    ) -> Tuple[str, str]:
        """
        Invoca al motor neuronal soberano de TARDIS.
        1. Prioriza Groq LPU / Cloud API (350+ tok/s) para respuesta instantánea en la UI.
        2. Fallback al Hub Local TARDIS (http://127.0.0.1:8757/api/chat).
        """
        # 1. Intentar Cloud LPU configurada en GODWORKS SYSTEM
        try:
            from core.chinese_cloud_api import get_chinese_cloud_api
            cloud_api = get_chinese_cloud_api()
            st = cloud_api.get_status()
            if st.get("enabled") and st.get("has_key"):
                resp = cloud_api.chat_completion(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout,
                )
                if resp.get("ok") and resp.get("reply"):
                    return resp["reply"].strip(), f"TARDIS-KAIJU ({resp.get('model', 'LPU')})"
        except Exception as e_cloud:
            logger.debug(f"Aviso en Cloud LPU: {e_cloud}")

        # 2. Fallback al Hub Local TARDIS en puerto 8757
        try:
            payload = json.dumps({
                "message": f"{system_prompt}\n\n{user_prompt}",
                "client_id": "tardis_navigator_gui",
                "use_web": False,
                "use_retro": False,
                "temperature": temperature,
            }).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8757/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
                reply = data.get("reply") or data.get("response") or ""
                if reply:
                    return reply.strip(), "TARDIS-NEURAL-SPACE-KAIJU (Local Hub :8757)"
        except Exception as e_hub:
            logger.debug(f"Aviso en Hub Local :8757: {e_hub}")

        return "", "extractive_fallback"

    def multi_search(
        self,
        query: str,
        engines: Optional[List[str]] = None,
        max_results: int = 8,
        deep_fetch: bool = True,
        synthesize: bool = True,
        active_page_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ejecuta búsqueda multi-fuente asistida por TARDIS con síntesis cognitiva,
        búsqueda en Bóveda RAG y extracción de páginas.
        """
        t0 = time.time()
        query = query.strip()
        if not query:
            return {"ok": False, "error": "Consulta vacía"}

        engines = engines or ["duckduckgo", "wikipedia", "arxiv", "news", "tech", "rag"]
        all_results: List[Dict[str, Any]] = []
        seen_urls = set()

        def _add_items(items, source_tag: str):
            for it in items:
                u = getattr(it, "url", "") or (it.get("url") if isinstance(it, dict) else "")
                if not u or u in seen_urls:
                    continue
                seen_urls.add(u)
                title = getattr(it, "title", "") or (it.get("title") if isinstance(it, dict) else u)
                snippet = getattr(it, "snippet", "") or (it.get("snippet") if isinstance(it, dict) else "")
                eng = getattr(it, "engine", source_tag) if not isinstance(it, dict) else it.get("engine", source_tag)
                all_results.append({
                    "title": title,
                    "url": u,
                    "snippet": snippet,
                    "engine": eng,
                })

        # Ejecutar búsquedas en paralelo con hilos para mínima latencia
        threads: List[threading.Thread] = []
        results_lock = threading.Lock()

        def _run_ddg():
            try:
                res = self.research_engine.search_duckduckgo_html(query, max_results=5)
                if not res:
                    res = self.research_engine.search_duckduckgo_api(query, max_results=4)
                with results_lock:
                    _add_items(res, "duckduckgo")
            except Exception as e:
                logger.debug(f"DDG search err: {e}")

        def _run_wiki():
            try:
                res = self.research_engine.search_wikipedia(query, max_results=4)
                with results_lock:
                    _add_items(res, "wikipedia")
            except Exception as e:
                logger.debug(f"Wiki search err: {e}")

        def _run_arxiv():
            try:
                res = self.research_engine.search_arxiv(query, max_results=3)
                with results_lock:
                    _add_items(res, "arxiv")
            except Exception as e:
                logger.debug(f"arXiv search err: {e}")

        def _run_news():
            try:
                res = self.research_engine.search_google_news(query, max_results=4)
                with results_lock:
                    _add_items(res, "google_news")
            except Exception as e:
                logger.debug(f"News search err: {e}")

        def _run_tech():
            try:
                res = self.research_engine.search_tech(query, max_results=3)
                with results_lock:
                    _add_items(res, "hackernews")
            except Exception as e:
                logger.debug(f"Tech search err: {e}")

        if "duckduckgo" in engines:
            threads.append(threading.Thread(target=_run_ddg, daemon=True))
        if "wikipedia" in engines:
            threads.append(threading.Thread(target=_run_wiki, daemon=True))
        if "arxiv" in engines:
            threads.append(threading.Thread(target=_run_arxiv, daemon=True))
        if "news" in engines:
            threads.append(threading.Thread(target=_run_news, daemon=True))
        if "tech" in engines:
            threads.append(threading.Thread(target=_run_tech, daemon=True))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=9.0)

        # Consultar Bóveda RAG Local de TARDIS
        rag_hits: List[Dict[str, Any]] = []
        if "rag" in engines:
            try:
                from core.rag_vault import get_rag_vault
                vault = get_rag_vault()
                if hasattr(vault, "search"):
                    raw_rag = vault.search(query, top_k=3)
                    if isinstance(raw_rag, list):
                        for r in raw_rag:
                            if isinstance(r, dict):
                                rag_hits.append({
                                    "title": r.get("title") or r.get("term") or "Memoria Akáshica RAG",
                                    "snippet": (r.get("text") or r.get("content") or "")[:300],
                                    "url": r.get("url") or "tardis://rag-vault",
                                    "score": r.get("score", 1.0),
                                })
            except Exception as e_rag:
                logger.debug(f"RAG search notice: {e_rag}")

        # Descarga rápida de las primeras 2 fuentes si deep_fetch está activo
        fetched_pages: List[Dict[str, Any]] = []
        if deep_fetch and all_results:
            for item in all_results[:2]:
                try:
                    page = self.research_engine.fetch_page(item["url"], max_chars=3000)
                    if page.text and not page.error:
                        fetched_pages.append({
                            "title": page.title or item["title"],
                            "url": item["url"],
                            "excerpt": page.text[:1800],
                            "code_snippets": page.code_snippets[:3],
                            "word_count": page.word_count,
                        })
                except Exception:
                    pass

        synthesis = ""
        model_used = "algorithmic"
        if synthesize:
            sources_ctx = []
            for idx, r in enumerate(all_results[:8], 1):
                sources_ctx.append(f"[{idx}] {r['title']} ({r['engine']}) - {r['url']}\nResumen: {r['snippet']}")
            for fp in fetched_pages:
                sources_ctx.append(f"--- TEXTO EXTRAÍDO DE [{fp['title']}]({fp['url']}) ---\n{fp['excerpt']}")
            if rag_hits:
                for rh in rag_hits:
                    sources_ctx.append(f"[RAG VAULT] {rh['title']}: {rh['snippet']}")
            if active_page_context and active_page_context.get("text"):
                sources_ctx.append(
                    f"--- PESTAÑA ACTIVA DEL NAVEGADOR ({active_page_context.get('title')} - {active_page_context.get('url')}) ---\n"
                    f"{active_page_context.get('text', '')[:2500]}"
                )

            sys_prompt = (
                f"Eres TARDIS, asistente de inteligencia artificial y Oráculo de Búsqueda Soberano del Arquitecto (₪). "
                f"Inicia o mantén siempre tu identidad soberana. "
                "Sintetiza una respuesta rigurosa, estructurada en Markdown, citando las fuentes con enlaces [Título](URL), "
                "destacando hallazgos clave, datos técnicos, código si aplica y pasos accionables."
            )
            usr_prompt = (
                f"CONSULTA DEL ARQUITECTO: {query}\n\n"
                f"FUENTES RECOPILADAS EN TIEMPO REAL:\n" + "\n\n".join(sources_ctx) + "\n\n"
                "Proporciona una síntesis completa, precisa y directamente accionable:"
            )
            synthesis, model_used = self.invoke_tardis_llm(sys_prompt, usr_prompt, max_tokens=1500)

            if not synthesis:
                lines = [
                    f"### 🌌 Síntesis de Búsqueda TARDIS: *{query}*",
                    "",
                    CANONICAL_GREETING,
                    "",
                    "#### 📌 Resultados Principales Verificados:",
                ]
                for r in all_results[:6]:
                    lines.append(f"- **[{r['title']}]({r['url']})** (`{r['engine']}`): {r['snippet']}")
                if fetched_pages:
                    lines.append("\n#### 📖 Extracto Profundo de Fuentes:")
                    for fp in fetched_pages:
                        lines.append(f"**[{fp['title']}]({fp['url']})**:\n> {fp['excerpt'][:500]}...")
                synthesis = "\n".join(lines)

        elapsed = round(time.time() - t0, 2)
        return {
            "ok": True,
            "query": query,
            "synthesis": synthesis,
            "model_used": model_used,
            "results": all_results[:max_results],
            "fetched_pages": fetched_pages,
            "rag_hits": rag_hits,
            "elapsed_seconds": elapsed,
        }

    def analyze_active_page(
        self,
        dom_data: Dict[str, Any],
        question: str = "Resume esta página, extrae sus puntos clave, datos técnicos y enlaces más importantes.",
    ) -> Dict[str, Any]:
        """Analiza el DOM en vivo de la pestaña activa y responde la pregunta o instrucción del Arquitecto."""
        t0 = time.time()
        url = dom_data.get("url", "")
        title = dom_data.get("title", "")
        text = dom_data.get("text", "")[:6000]
        headings = dom_data.get("headings", [])[:25]
        tables = dom_data.get("tables", [])[:5]
        links = dom_data.get("links", [])[:25]
        code_blocks = dom_data.get("code_blocks", [])[:5]
        prices = dom_data.get("prices", [])[:20]

        sys_prompt = (
            "Eres TARDIS, asistente de inteligencia artificial integrado en el navegador cuántico soberano del Arquitecto (₪). "
            "Analiza el contenido DOM extraído en vivo de la pestaña activa del navegador y responde con máxima precisión técnica en Markdown."
        )
        usr_prompt = (
            f"INSTRUCCIÓN DEL ARQUITECTO: {question}\n\n"
            f"DATOS EN VIVO DE LA PESTAÑA ACTIVA:\n"
            f"• Título: {title}\n"
            f"• URL: {url}\n"
            f"• Encabezados (H1-H3): {json.dumps(headings, ensure_ascii=False)}\n"
            f"• Precios/Ofertas detectados: {json.dumps(prices, ensure_ascii=False)}\n"
            f"• Tablas detectadas ({len(tables)}): {json.dumps(tables[:2], ensure_ascii=False)[:1200]}\n"
            f"• Bloques de código ({len(code_blocks)}): {json.dumps(code_blocks[:2], ensure_ascii=False)[:1000]}\n"
            f"• Enlaces principales ({len(links)}): {json.dumps(links[:12], ensure_ascii=False)}\n\n"
            f"• TEXTO VISIBLE DE LA PÁGINA:\n{text}\n\n"
            "Entrega tu análisis estructurado:"
        )
        reply, model_used = self.invoke_tardis_llm(sys_prompt, usr_prompt, max_tokens=1600)
        if not reply:
            reply = (
                f"### 🧠 Análisis DOM de [{title}]({url})\n\n"
                f"- **Encabezados detectados**: {', '.join(headings[:8]) or 'Ninguno'}\n"
                f"- **Enlaces extraídos**: {len(links)}\n"
                f"- **Tablas extraídas**: {len(tables)}\n"
                f"- **Precios detectados**: {', '.join(prices[:8]) or 'Ninguno'}\n\n"
                f"#### Extracto Principal:\n> {text[:800]}..."
            )

        return {
            "ok": True,
            "url": url,
            "title": title,
            "question": question,
            "analysis": reply,
            "model_used": model_used,
            "elapsed_seconds": round(time.time() - t0, 2),
            "dom_stats": {
                "text_length": len(text),
                "headings_count": len(headings),
                "links_count": len(links),
                "tables_count": len(tables),
                "code_count": len(code_blocks),
                "prices_count": len(prices),
            },
        }


# ==============================================================================
# 4. MOTOR DE AUTOMATIZACIÓN DE PROCESOS WEB Y SISTEMA (TARDIS AUTOMATION STUDIO)
# ==============================================================================
class TardisAutomationEngine:
    """
    Ejecuta procesos automatizados (Workflows) sobre el navegador en vivo (vía bridge WebKit2)
    y/o en segundo plano (vía TardisBrowser Turbo/CDP), genera flujos con IA desde lenguaje natural,
    graba macros de usuario en tiempo real y programa ejecuciones periódicas.
    """

    def __init__(
        self,
        persistence: NavigatorPersistence,
        search_assistant: TardisSearchAssistant,
        browser_bridge: Optional[Dict[str, Callable]] = None,
    ):
        self.persistence = persistence
        self.search_assistant = search_assistant
        # browser_bridge provee callbacks hacia la ventana GTK3/WebKit2:
        #   navigate(url, new_tab=False) -> bool
        #   eval_js(js_code, timeout=6.0) -> Any
        #   get_active_info() -> dict
        #   take_screenshot(out_path) -> Optional[str]
        self.browser_bridge = browser_bridge or {}
        self.active_runs: Dict[str, Dict[str, Any]] = {}
        self.run_history: List[Dict[str, Any]] = []
        self.recording_active: bool = False
        self.recorded_steps: List[Dict[str, Any]] = []
        self.schedules: Dict[str, Dict[str, Any]] = {}
        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()

    def set_browser_bridge(self, bridge: Dict[str, Callable]) -> None:
        self.browser_bridge = bridge

    # ------------------------------------------------------------------
    # Grabadora de Macros en Vivo (Live DOM Recorder)
    # ------------------------------------------------------------------
    def start_recording(self) -> Dict[str, Any]:
        self.recording_active = True
        self.recorded_steps = []
        # Registrar URL inicial de la pestaña activa si existe
        if "get_active_info" in self.browser_bridge:
            try:
                info = self.browser_bridge["get_active_info"]()
                if info and info.get("url") and not info["url"].startswith("http://127.0.0.1:8777"):
                    self.recorded_steps.append({
                        "action": "navigate",
                        "url": info["url"],
                        "description": f"Ir a {info.get('title') or info['url']}"
                    })
            except Exception:
                pass
        return {"ok": True, "recording": True, "steps": self.recorded_steps}

    def stop_recording(self, save_as_name: Optional[str] = None) -> Dict[str, Any]:
        self.recording_active = False
        saved_wf = None
        if save_as_name and self.recorded_steps:
            wf = {
                "id": f"wf_macro_{int(time.time())}",
                "name": f"🔴 Macro: {save_as_name}",
                "description": f"Macro grabada en vivo con {len(self.recorded_steps)} pasos.",
                "category": "Macro Grabada",
                "default_param": "",
                "steps": list(self.recorded_steps),
            }
            self.persistence.save_workflow(wf)
            saved_wf = wf
        return {
            "ok": True,
            "recording": False,
            "steps": self.recorded_steps,
            "saved_workflow": saved_wf,
        }

    def record_dom_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.recording_active:
            return {"ok": False, "ignored": True}

        ev_type = event_data.get("type", "")
        selector = event_data.get("selector", "")
        value = event_data.get("value", "")
        text = event_data.get("text", "")
        url = event_data.get("url", "")

        step: Optional[Dict[str, Any]] = None
        if ev_type == "click" and selector:
            step = {
                "action": "click",
                "selector": selector,
                "text_hint": text[:50],
                "description": f"Clic en '{text[:35] or selector}'",
            }
        elif ev_type == "fill" and selector:
            # Si el último paso fue fill en el mismo selector, actualizar su valor
            if self.recorded_steps and self.recorded_steps[-1].get("action") == "fill" and self.recorded_steps[-1].get("selector") == selector:
                self.recorded_steps[-1]["value"] = value
                return {"ok": True, "steps_count": len(self.recorded_steps)}
            step = {
                "action": "fill",
                "selector": selector,
                "value": value,
                "press_enter": bool(event_data.get("press_enter", False)),
                "description": f"Escribir '{value[:30]}' en {selector}",
            }
        elif ev_type == "navigate" and url and not url.startswith("http://127.0.0.1:8777"):
            if not self.recorded_steps or self.recorded_steps[-1].get("url") != url:
                step = {
                    "action": "navigate",
                    "url": url,
                    "description": f"Navegar a {url[:60]}",
                }

        if step:
            self.recorded_steps.append(step)
        return {"ok": True, "steps_count": len(self.recorded_steps), "step": step}

    # ------------------------------------------------------------------
    # Generador Agéntico: Lenguaje Natural -> Workflow de Automatización
    # ------------------------------------------------------------------
    def generate_workflow_from_prompt(
        self,
        goal_prompt: str,
        active_dom_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Convierte una instrucción en lenguaje natural del Arquitecto en un flujo
        de automatización estructurado y listo para ejecutarse.
        """
        goal_prompt = goal_prompt.strip()
        dom_info_str = ""
        if active_dom_context:
            dom_info_str = (
                f"\nCONTEXTO DE LA PESTAÑA ACTIVA ACTUAL:\n"
                f"- URL: {active_dom_context.get('url')}\n"
                f"- Título: {active_dom_context.get('title')}\n"
                f"- Inputs/Formularios disponibles: {json.dumps(active_dom_context.get('inputs', [])[:12], ensure_ascii=False)}\n"
                f"- Botones/Enlaces principales: {json.dumps(active_dom_context.get('buttons', [])[:15], ensure_ascii=False)}\n"
            )

        sys_prompt = (
            "Eres el Arquitecto de Automatización de TARDIS Quantum Navigator. "
            "Convierte el objetivo del usuario en un objeto JSON válido que defina un flujo de automatización web.\n"
            "RESPONDE ÚNICAMENTE CON UN BLOQUE JSON VÁLIDO (sin texto adicional fuera del JSON) con esta estructura:\n"
            "{\n"
            '  "name": "Título corto del flujo",\n'
            '  "description": "Descripción técnica breve",\n'
            '  "default_param": "parámetro principal",\n'
            '  "steps": [\n'
            '    {"action": "navigate", "url": "https://..."},\n'
            '    {"action": "search_web", "query": "...", "max_results": 5, "open_first": true},\n'
            '    {"action": "fill", "selector": "input[name=\'search\']", "value": "...", "press_enter": true},\n'
            '    {"action": "click", "selector": "button[type=\'submit\']", "text_hint": "Buscar"},\n'
            '    {"action": "wait", "seconds": 2.0},\n'
            '    {"action": "scroll", "direction": "down", "amount": 600},\n'
            '    {"action": "extract_dom", "mode": "summary_dom"},\n'
            '    {"action": "extract_dom", "mode": "tables"},\n'
            '    {"action": "extract_dom", "mode": "prices"},\n'
            '    {"action": "extract_dom", "mode": "links"},\n'
            '    {"action": "screenshot", "label": "captura"},\n'
            '    {"action": "ai_synthesize", "prompt": "Instrucción de análisis IA sobre lo extraído"},\n'
            '    {"action": "rag_ftl_learn", "topic": "..."}\n'
            "  ]\n"
            "}\n"
            "Elige solo los pasos necesarios (entre 3 y 8 pasos) que cumplan exactamente el objetivo del usuario."
        )
        usr_prompt = f"OBJETIVO A AUTOMATIZAR: {goal_prompt}\n{dom_info_str}"

        reply, model_used = self.search_assistant.invoke_tardis_llm(sys_prompt, usr_prompt, max_tokens=1200, temperature=0.15)
        parsed_wf = None
        if reply:
            try:
                m = re.search(r"\{.*\}", reply, re.DOTALL)
                if m:
                    parsed_wf = json.loads(m.group(0))
            except Exception as e:
                logger.warning(f"Fallo parseando JSON de flujo IA: {e}")

        if not parsed_wf or not isinstance(parsed_wf.get("steps"), list):
            # Fallback heurístico inteligente
            g_low = goal_prompt.lower()
            steps = []
            url_m = re.search(r"(https?://[^\s]+|[a-zA-Z0-9.-]+\.(?:org|com|net|io|mx|edu)(?:/[^\s]*)?)", goal_prompt)
            if "wikipedia" in g_low:
                topic = re.sub(r"(?i)(ve a|abre|busca en|wikipedia|extrae|resume|haz scroll|y|el|la|los|las|sobre)", "", goal_prompt).strip() or goal_prompt
                steps = [
                    {"action": "navigate", "url": "https://es.wikipedia.org"},
                    {"action": "wait", "seconds": 1.5},
                    {"action": "fill", "selector": "input[name='search']", "value": topic, "press_enter": True},
                    {"action": "wait", "seconds": 2.5},
                    {"action": "scroll", "direction": "down", "amount": 500},
                    {"action": "extract_dom", "mode": "summary_dom"},
                    {"action": "screenshot", "label": "wikipedia_auto"},
                    {"action": "ai_synthesize", "prompt": f"Resume y extrae los datos clave sobre '{topic}'."},
                ]
            elif url_m:
                target_u = url_m.group(1)
                if not target_u.startswith("http"):
                    target_u = "https://" + target_u
                steps = [
                    {"action": "navigate", "url": target_u},
                    {"action": "wait", "seconds": 2.0},
                    {"action": "scroll", "direction": "down", "amount": 600},
                    {"action": "extract_dom", "mode": "summary_dom"},
                    {"action": "extract_dom", "mode": "links"},
                    {"action": "screenshot", "label": "web_auto"},
                    {"action": "ai_synthesize", "prompt": f"Cumple el objetivo: {goal_prompt}"},
                ]
            else:
                steps = [
                    {"action": "search_web", "query": goal_prompt, "max_results": 5, "open_first": True},
                    {"action": "wait", "seconds": 2.0},
                    {"action": "scroll", "direction": "down", "amount": 500},
                    {"action": "extract_dom", "mode": "summary_dom"},
                    {"action": "ai_synthesize", "prompt": f"Realiza la tarea solicitada: {goal_prompt}"},
                    {"action": "rag_ftl_learn", "topic": goal_prompt[:60]},
                ]
            parsed_wf = {
                "name": f"🤖 Auto: {goal_prompt[:42]}",
                "description": f"Flujo generado automáticamente para: {goal_prompt}",
                "default_param": goal_prompt,
                "steps": steps,
            }

        parsed_wf["id"] = f"wf_ai_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        parsed_wf["category"] = "Generado por IA"
        self.persistence.save_workflow(parsed_wf)
        return {"ok": True, "workflow": parsed_wf, "model_used": model_used}

    # ------------------------------------------------------------------
    # Ejecutor de Procesos (Workflow Runner)
    # ------------------------------------------------------------------
    def start_workflow_async(
        self,
        workflow: Dict[str, Any],
        param_value: str = "",
    ) -> str:
        run_id = f"run_{int(time.time()*1000)}_{uuid.uuid4().hex[:5]}"
        param = (param_value or workflow.get("default_param") or "").strip()

        run_state = {
            "run_id": run_id,
            "workflow_id": workflow.get("id", "custom"),
            "workflow_name": workflow.get("name", "Proceso TARDIS"),
            "param": param,
            "status": "running",
            "started_at": time.time(),
            "finished_at": None,
            "current_step_index": 0,
            "total_steps": len(workflow.get("steps", [])),
            "logs": [],
            "step_results": [],
            "extracted_data": {},
            "ai_synthesis": "",
            "screenshots": [],
            "report_file": None,
        }
        self.active_runs[run_id] = run_state

        t = threading.Thread(
            target=self._execute_workflow_thread,
            args=(run_id, workflow, param),
            daemon=True,
        )
        t.start()
        return run_id

    def _log_run(self, run_id: str, msg: str, level: str = "INFO") -> None:
        st = self.active_runs.get(run_id)
        if st:
            entry = {
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "message": msg,
            }
            st["logs"].append(entry)
        logger.info(f"[AutoRun {run_id}] {msg}")

    def _substitute_param(self, val: Any, param: str) -> Any:
        if isinstance(val, str):
            return val.replace("{{param}}", param).replace("{param}", param)
        return val

    def _execute_workflow_thread(
        self,
        run_id: str,
        workflow: Dict[str, Any],
        param: str,
    ) -> None:
        st = self.active_runs[run_id]
        steps = workflow.get("steps", [])
        self._log_run(run_id, f"🚀 Iniciando flujo '{workflow.get('name')}' (Parámetro: '{param or 'N/A'}')")

        try:
            for idx, raw_step in enumerate(steps):
                st["current_step_index"] = idx + 1
                action = (raw_step.get("action") or "").strip().lower()
                step = {k: self._substitute_param(v, param) for k, v in raw_step.items()}
                self._log_run(run_id, f"Paso [{idx+1}/{len(steps)}] Ejecutando acción: {action.upper()}")

                # Mostrar banner visual en la pestaña activa
                self._show_live_overlay_badge(f"TARDIS AUTO [{idx+1}/{len(steps)}]: {action.upper()}")

                step_res = self._run_single_step(run_id, action, step, st)
                st["step_results"].append({
                    "step_index": idx + 1,
                    "action": action,
                    "result": step_res,
                })

            st["status"] = "completed"
            st["finished_at"] = time.time()
            elapsed = round(st["finished_at"] - st["started_at"], 2)
            self._log_run(run_id, f"✅ Proceso completado exitosamente en {elapsed}s.")
            self._show_live_overlay_badge(f"✅ TARDIS AUTO COMPLETADO ({elapsed}s)", done=True)

            # Guardar reporte persistente en disco
            report_path = RUNS_DIR / f"{run_id}.json"
            report_path.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
            st["report_file"] = str(report_path)
            self.run_history.insert(0, st)
            self.run_history = self.run_history[:50]

        except Exception as e:
            st["status"] = "error"
            st["finished_at"] = time.time()
            self._log_run(run_id, f"❌ Error en ejecución: {e}", level="ERROR")

    def _show_live_overlay_badge(self, text: str, done: bool = False) -> None:
        if "eval_js" not in self.browser_bridge:
            return
        color = "#10b981" if done else "#00f0ff"
        js = f"""
        (function() {{
            let b = document.getElementById('__tardis_auto_badge');
            if (!b) {{
                b = document.createElement('div');
                b.id = '__tardis_auto_badge';
                b.style.cssText = 'position:fixed;bottom:18px;right:18px;z-index:REDACTED_PHONE;background:rgba(5,8,17,0.92);color:{color};border:1.5px solid {color};padding:10px 16px;border-radius:10px;font-family:monospace;font-size:13px;font-weight:bold;box-shadow:0 0 20px rgba(0,240,255,0.4);pointer-events:none;transition:all 0.3s ease;';
                document.body.appendChild(b);
            }}
            b.style.borderColor = '{color}';
            b.style.color = '{color}';
            b.innerText = {json.dumps(text)};
            if ({'true' if done else 'false'}) {{
                setTimeout(() => {{ if (b && b.parentNode) b.parentNode.removeChild(b); }}, 4000);
            }}
        }})();
        """
        try:
            self.browser_bridge["eval_js"](js, timeout=2.0)
        except Exception:
            pass

    def _run_single_step(
        self,
        run_id: str,
        action: str,
        step: Dict[str, Any],
        st: Dict[str, Any],
    ) -> Dict[str, Any]:
        # 1. NAVIGATE
        if action == "navigate":
            url = (step.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            new_tab = bool(step.get("new_tab", False))
            self._log_run(run_id, f"🌐 Navegando a: {url}")
            if "navigate" in self.browser_bridge:
                self.browser_bridge["navigate"](url, new_tab=new_tab)
            else:
                # Fallback sin ventana GTK: descargar con research_engine
                page = self.search_assistant.research_engine.fetch_page(url, max_chars=5000)
                st["extracted_data"]["last_page"] = asdict(page)
            return {"ok": True, "url": url}

        # 2. SEARCH_WEB
        elif action == "search_web":
            query = (step.get("query") or st.get("param") or "").strip()
            max_results = int(step.get("max_results", 5))
            open_first = bool(step.get("open_first", True))
            self._log_run(run_id, f"🔍 Buscando en motores multi-fuente: '{query}'")
            res = self.search_assistant.multi_search(
                query=query,
                max_results=max_results,
                deep_fetch=True,
                synthesize=False,
            )
            found = res.get("results", [])
            st["extracted_data"]["search_results"] = found
            st["extracted_data"]["fetched_pages"] = res.get("fetched_pages", [])
            self._log_run(run_id, f"✓ {len(found)} fuentes encontradas.")

            if open_first and found and "navigate" in self.browser_bridge:
                top_url = found[0]["url"]
                self._log_run(run_id, f"🌐 Abriendo fuente principal en pestaña activa: {top_url}")
                self.browser_bridge["navigate"](top_url, new_tab=False)
            return {"ok": True, "count": len(found), "top_url": found[0]["url"] if found else None}

        # 3. OPEN_TABS
        elif action == "open_tabs":
            count = int(step.get("count", 3))
            urls = step.get("urls") or [r["url"] for r in st["extracted_data"].get("search_results", [])[:count]]
            opened = []
            for idx_u, u in enumerate(urls[:count]):
                if "navigate" in self.browser_bridge:
                    self.browser_bridge["navigate"](u, new_tab=(idx_u > 0))
                    opened.append(u)
                    time.sleep(0.4)
            self._log_run(run_id, f"🗂️ Abiertas {len(opened)} pestañas: {', '.join(opened)}")
            return {"ok": True, "opened_urls": opened}

        # 4. WAIT
        elif action == "wait":
            secs = min(float(step.get("seconds", 1.5)), 15.0)
            self._log_run(run_id, f"⏳ Esperando {secs}s para renderizado DOM...")
            time.sleep(secs)
            return {"ok": True, "waited": secs}

        # 5. FILL (Rellenar campos de formulario / buscadores)
        elif action == "fill":
            selector = step.get("selector", "input[type='search'], input[name='q'], input[name='search'], input[type='text']")
            value = str(step.get("value", st.get("param", "")))
            press_enter = bool(step.get("press_enter", True))
            self._log_run(run_id, f"⌨️ Rellenando campo ({selector}) con: '{value}' (Enter={press_enter})")
            if "eval_js" in self.browser_bridge:
                js = f"""
                (function() {{
                    let sel = {json.dumps(selector)};
                    let val = {json.dumps(value)};
                    let pressEnter = {'true' if press_enter else 'false'};
                    let el = document.querySelector(sel);
                    if (!el) {{
                        // Fallback inteligente: buscar cualquier input visible de búsqueda o texto
                        const candidates = Array.from(document.querySelectorAll('input[type="search"], input[name="search"], input[name="q"], input[type="text"], textarea'));
                        el = candidates.find(e => e.offsetParent !== null) || candidates[0];
                    }}
                    if (!el) return JSON.stringify({{ok: false, error: 'Elemento input no encontrado'}});
                    el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                    el.style.outline = '3px solid #00f0ff';
                    el.style.boxShadow = '0 0 20px #00f0ff';
                    el.focus();
                    el.value = val;
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    if (pressEnter) {{
                        if (el.form) {{
                            setTimeout(() => el.form.submit(), 250);
                        }} else {{
                            el.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}}));
                        }}
                    }}
                    return JSON.stringify({{ok: true, tag: el.tagName, name: el.name || el.id || sel}});
                }})();
                """
                res_raw = self.browser_bridge["eval_js"](js, timeout=5.0)
                return {"ok": True, "dom_response": res_raw}
            return {"ok": False, "error": "Bridge DOM no disponible"}

        # 6. CLICK (Hacer clic por selector CSS o por texto visible)
        elif action == "click":
            selector = step.get("selector", "")
            text_hint = step.get("text_hint", "")
            self._log_run(run_id, f"🖱️ Ejecutando clic en: '{selector or text_hint}'")
            if "eval_js" in self.browser_bridge:
                js = f"""
                (function() {{
                    let sel = {json.dumps(selector)};
                    let hint = {json.dumps(text_hint)}.toLowerCase();
                    let el = sel ? document.querySelector(sel) : null;
                    if (!el && (hint || sel)) {{
                        let q = hint || sel.toLowerCase();
                        const clickables = Array.from(document.querySelectorAll('a, button, input[type="submit"], input[type="button"], [role="button"]'));
                        el = clickables.find(e => (e.innerText || e.value || '').toLowerCase().includes(q));
                    }}
                    if (!el) return JSON.stringify({{ok: false, error: 'Elemento clicable no encontrado'}});
                    el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                    el.style.outline = '3px solid #ec4899';
                    el.style.boxShadow = '0 0 22px #ec4899';
                    setTimeout(() => el.click(), 200);
                    return JSON.stringify({{ok: true, text: (el.innerText || el.value || '').slice(0, 60)}});
                }})();
                """
                res_raw = self.browser_bridge["eval_js"](js, timeout=5.0)
                return {"ok": True, "dom_response": res_raw}
            return {"ok": False, "error": "Bridge DOM no disponible"}

        # 7. SCROLL
        elif action == "scroll":
            direction = (step.get("direction") or "down").lower()
            amount = int(step.get("amount", 600))
            self._log_run(run_id, f"📜 Desplazando página ({direction}, {amount}px)...")
            if "eval_js" in self.browser_bridge:
                js = f"""
                (function() {{
                    let dir = {json.dumps(direction)};
                    let amt = {amount};
                    if (dir === 'bottom') window.scrollTo({{top: document.body.scrollHeight, behavior: 'smooth'}});
                    else if (dir === 'top') window.scrollTo({{top: 0, behavior: 'smooth'}});
                    else if (dir === 'up') window.scrollBy({{top: -amt, behavior: 'smooth'}});
                    else window.scrollBy({{top: amt, behavior: 'smooth'}});
                    return JSON.stringify({{ok: true, scrollY: window.scrollY}});
                }})();
                """
                res_raw = self.browser_bridge["eval_js"](js, timeout=4.0)
                time.sleep(0.6)
                return {"ok": True, "dom_response": res_raw}
            return {"ok": True}

        # 8. EXTRACT_DOM (Extracción profunda en vivo de la pestaña activa)
        elif action == "extract_dom":
            mode = (step.get("mode") or "summary_dom").lower()
            selector = step.get("selector", "")
            self._log_run(run_id, f"🧬 Extrayendo datos del DOM activo (modo={mode})...")
            dom_snapshot = self.extract_live_dom(selector=selector)
            if dom_snapshot:
                st["extracted_data"]["dom_snapshot"] = dom_snapshot
                if mode == "tables":
                    st["extracted_data"]["tables"] = dom_snapshot.get("tables", [])
                    self._log_run(run_id, f"✓ {len(dom_snapshot.get('tables', []))} tablas HTML extraídas.")
                elif mode == "links":
                    st["extracted_data"]["links"] = dom_snapshot.get("links", [])
                    self._log_run(run_id, f"✓ {len(dom_snapshot.get('links', []))} hipervínculos extraídos.")
                elif mode == "prices":
                    st["extracted_data"]["prices"] = dom_snapshot.get("prices", [])
                    self._log_run(run_id, f"✓ {len(dom_snapshot.get('prices', []))} precios/ofertas detectados.")
                else:
                    self._log_run(
                        run_id,
                        f"✓ DOM extraído de '{dom_snapshot.get('title', 'Página')}' "
                        f"({len(dom_snapshot.get('text', ''))} chars, {len(dom_snapshot.get('headings', []))} encabezados)."
                    )
            return {
                "ok": True,
                "mode": mode,
                "title": dom_snapshot.get("title", ""),
                "url": dom_snapshot.get("url", ""),
                "text_chars": len(dom_snapshot.get("text", "")),
                "tables_count": len(dom_snapshot.get("tables", [])),
                "links_count": len(dom_snapshot.get("links", [])),
                "prices_count": len(dom_snapshot.get("prices", [])),
            }

        # 9. EVAL_JS
        elif action == "eval_js":
            code = step.get("code", "document.title")
            self._log_run(run_id, f"⚡ Evaluando JS personalizado en la pestaña activa...")
            if "eval_js" in self.browser_bridge:
                out = self.browser_bridge["eval_js"](code, timeout=6.0)
                st["extracted_data"]["custom_js_result"] = out
                return {"ok": True, "output": out}
            return {"ok": False, "error": "Bridge JS no disponible"}

        # 10. SCREENSHOT
        elif action == "screenshot":
            label = re.sub(r"[^a-zA-Z0-9_-]", "_", step.get("label", "shot"))
            shot_file = RUNS_DIR / f"{run_id}_{label}.png"
            saved_path = None
            if "take_screenshot" in self.browser_bridge:
                saved_path = self.browser_bridge["take_screenshot"](str(shot_file))
            if saved_path:
                st["screenshots"].append(saved_path)
                self._log_run(run_id, f"📸 Captura guardada en: {saved_path}")
                return {"ok": True, "path": saved_path}
            self._log_run(run_id, "⚠️ Captura omitida (modo sin ventana visible).")
            return {"ok": False}

        # 11. AI_SYNTHESIZE
        elif action == "ai_synthesize":
            prompt = step.get("prompt") or f"Analiza y sintetiza los resultados sobre {st.get('param', 'la página actual')}."
            self._log_run(run_id, "🧠 Invocando motor neuronal TARDIS para síntesis cognitiva...")

            dom_snap = st["extracted_data"].get("dom_snapshot", {})
            search_res = st["extracted_data"].get("search_results", [])
            fetched_pages = st["extracted_data"].get("fetched_pages", [])

            ctx_parts = []
            if dom_snap:
                ctx_parts.append(
                    f"=== DATOS EXTRAÍDOS DEL DOM DE LA PESTAÑA ACTIVA ===\n"
                    f"Título: {dom_snap.get('title')}\n"
                    f"URL: {dom_snap.get('url')}\n"
                    f"Encabezados: {json.dumps(dom_snap.get('headings', [])[:20], ensure_ascii=False)}\n"
                    f"Precios/Ofertas: {json.dumps(dom_snap.get('prices', [])[:20], ensure_ascii=False)}\n"
                    f"Tablas: {json.dumps(dom_snap.get('tables', [])[:3], ensure_ascii=False)[:1500]}\n"
                    f"Enlaces principales: {json.dumps(dom_snap.get('links', [])[:15], ensure_ascii=False)}\n"
                    f"Texto de la página:\n{dom_snap.get('text', '')[:4500]}"
                )
            if search_res:
                ctx_parts.append(
                    "=== RESULTADOS DE BÚSQUEDA MULTI-MOTOR ===\n"
                    + "\n".join(f"- [{r['title']}]({r['url']}) ({r['engine']}): {r['snippet']}" for r in search_res[:8])
                )
            if fetched_pages:
                for fp in fetched_pages:
                    ctx_parts.append(f"=== CONTENIDO DE [{fp['title']}]({fp['url']}) ===\n{fp.get('excerpt', '')[:2000]}")

            sys_p = (
                "Eres TARDIS, asistente de inteligencia artificial y núcleo de automatización soberana del Arquitecto (₪). "
                "Genera un informe estructurado en Markdown con base en los datos recopilados durante este flujo automatizado."
            )
            usr_p = f"INSTRUCCIÓN DE SÍNTESIS: {prompt}\n\n" + "\n\n".join(ctx_parts)
            reply, model_used = self.search_assistant.invoke_tardis_llm(sys_p, usr_p, max_tokens=1600)
            if not reply:
                reply = (
                    f"### 🌌 Reporte Automatizado TARDIS: {st.get('workflow_name')}\n\n"
                    f"- **Parámetro**: `{st.get('param')}`\n"
                    f"- **Página Analizada**: [{dom_snap.get('title', 'N/A')}]({dom_snap.get('url', '#')})\n"
                    f"- **Fuentes Consultadas**: {len(search_res)}\n\n"
                    f"#### Extracto Principal:\n> {dom_snap.get('text', '')[:900]}..."
                )
            st["ai_synthesis"] = reply
            self._log_run(run_id, f"✓ Síntesis IA generada mediante {model_used} ({len(reply)} chars).")
            return {"ok": True, "model_used": model_used, "chars": len(reply)}

        # 12. RAG_FTL_LEARN (Ingesta RAG + Auto-Mejora FTL)
        elif action == "rag_ftl_learn":
            topic = step.get("topic") or st.get("param") or st.get("workflow_name", "Exploración TARDIS")
            self._log_run(run_id, f"⚡ Ingestando aprendizaje en Bóveda RAG y ejecutando Auto-Mejora FTL para '{topic}'...")
            dom_snap = st["extracted_data"].get("dom_snapshot", {})
            text_to_learn = st.get("ai_synthesis") or dom_snap.get("text", "")
            url_to_learn = dom_snap.get("url", "http://127.0.0.1:8765")
            title_to_learn = dom_snap.get("title", topic)

            ftl_summary = "Ingesta RAG completada."
            try:
                from core.tardis_browser import BrowserVisitResult, TardisCognitiveLearner
                learner = TardisCognitiveLearner()
                visit_obj = BrowserVisitResult(
                    url=url_to_learn,
                    title=title_to_learn,
                    status_code=200,
                    text_content=text_to_learn[:10000] if text_to_learn else f"Síntesis sobre {topic}",
                    code_snippets=dom_snap.get("code_blocks", [])[:4],
                    links=[l.get("url", "") for l in dom_snap.get("links", [])[:15] if isinstance(l, dict)],
                )
                insight = learner.distill_knowledge(visit_obj, topic=topic)
                ftl_summary = insight.improvement_summary
                st["extracted_data"]["epistemic_insight"] = insight.to_dict()
                self._log_run(run_id, f"✓ {ftl_summary}")
            except Exception as e_ftl:
                self._log_run(run_id, f"Aviso en aprendizaje FTL: {e_ftl}", level="WARN")
                ftl_summary = str(e_ftl)

            return {"ok": True, "summary": ftl_summary}

        # 13. SHELL_CMD (Comando del sistema en segundo plano aislado)
        elif action == "shell_cmd":
            cmd = step.get("command", "")
            if not cmd:
                return {"ok": False, "error": "Comando vacío"}
            self._log_run(run_id, f"💻 Ejecutando comando local aislado: {cmd}")
            try:
                res = subprocess.run(
                    cmd,
                    shell=True,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=15.0,
                )
                out = (res.stdout or "") + (res.stderr or "")
                st["extracted_data"]["shell_output"] = out[:4000]
                return {"ok": res.returncode == 0, "returncode": res.returncode, "output": out[:1000]}
            except Exception as e_sh:
                return {"ok": False, "error": str(e_sh)}

        return {"ok": False, "error": f"Acción desconocida: {action}"}

    # ------------------------------------------------------------------
    # Extracción e Inspección del DOM en Vivo
    # ------------------------------------------------------------------
    def extract_live_dom(self, selector: str = "") -> Dict[str, Any]:
        """Extrae el estado completo y estructurado del DOM de la pestaña activa."""
        if "eval_js" not in self.browser_bridge:
            return {}

        js = f"""
        (function() {{
            const customSel = {json.dumps(selector)};
            const title = document.title || '';
            const url = window.location.href || '';
            const metaDesc = (document.querySelector('meta[name="description"]') || {{}}).content || '';

            const headings = Array.from(document.querySelectorAll('h1, h2, h3'))
                .map(h => (h.tagName + ': ' + (h.innerText || '').trim()))
                .filter(t => t.length > 4)
                .slice(0, 30);

            const links = Array.from(document.querySelectorAll('a[href]'))
                .map(a => ({{text: (a.innerText || '').trim().slice(0, 80), url: a.href}}))
                .filter(l => l.url.startsWith('http') && l.text.length > 1)
                .slice(0, 40);

            const tables = Array.from(document.querySelectorAll('table')).slice(0, 6).map(tbl => {{
                const rows = Array.from(tbl.querySelectorAll('tr')).slice(0, 15).map(tr =>
                    Array.from(tr.querySelectorAll('th, td')).map(td => (td.innerText || '').trim().slice(0, 80))
                ).filter(r => r.length > 0);
                return rows;
            }}).filter(t => t.length > 0);

            const code_blocks = Array.from(document.querySelectorAll('pre, code'))
                .map(c => (c.innerText || '').trim())
                .filter(t => t.length > 25)
                .slice(0, 8);

            // Detectar precios y ofertas ($1,299, MXN, USD, % OFF, etc.)
            const bodyText = document.body ? (document.body.innerText || '') : '';
            const priceRegex = /(?:\\$|MXN|USD|€)\\s?\\d{{1,3}}(?:[.,]\\d{{3}})*(?:[.,]\\d{{2}})?|\\d{{1,2}}%\\s*(?:OFF|descuento|dto)/gi;
            const prices = Array.from(new Set((bodyText.match(priceRegex) || []).slice(0, 30)));

            // Elementos interactivos para el Inspector y el Agente IA
            const inputs = Array.from(document.querySelectorAll('input, textarea, select')).slice(0, 20).map(el => {{
                let sel = el.tagName.toLowerCase();
                if (el.id) sel = '#' + el.id;
                else if (el.name) sel += `[name="${{el.name}}"]`;
                else if (el.type) sel += `[type="${{el.type}}"]`;
                return {{
                    selector: sel,
                    type: el.type || el.tagName.toLowerCase(),
                    placeholder: el.placeholder || '',
                    name: el.name || el.id || ''
                }};
            }});

            const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], a.btn, [role="button"]')).slice(0, 20).map(el => {{
                let sel = el.tagName.toLowerCase();
                if (el.id) sel = '#' + el.id;
                else if (el.className && typeof el.className === 'string') {{
                    const cls = el.className.trim().split(/\\s+/)[0];
                    if (cls) sel += '.' + cls;
                }}
                return {{
                    selector: sel,
                    text: (el.innerText || el.value || '').trim().slice(0, 50)
                }};
            }}).filter(b => b.text.length > 0);

            let customMatches = [];
            if (customSel) {{
                try {{
                    customMatches = Array.from(document.querySelectorAll(customSel))
                        .map(e => (e.innerText || '').trim())
                        .filter(Boolean)
                        .slice(0, 30);
                }} catch(e) {{}}
            }}

            return JSON.stringify({{
                url: url,
                title: title,
                meta_description: metaDesc,
                headings: headings,
                links: links,
                tables: tables,
                code_blocks: code_blocks,
                prices: prices,
                inputs: inputs,
                buttons: buttons,
                custom_matches: customMatches,
                text: bodyText.replace(/\\s+/g, ' ').trim().slice(0, 12000)
            }});
        }})();
        """
        raw = self.browser_bridge["eval_js"](js, timeout=6.0)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except Exception:
                return {"text": raw}
        return {}

    # ------------------------------------------------------------------
    # Programador Periódico (Scheduler)
    # ------------------------------------------------------------------
    def add_schedule(self, workflow_id: str, param: str, interval_seconds: int) -> Dict[str, Any]:
        sched_id = f"sched_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        interval_seconds = max(30, int(interval_seconds))
        wfs = self.persistence.get_workflows()
        wf = next((w for w in wfs if w.get("id") == workflow_id), None)
        if not wf:
            return {"ok": False, "error": "Workflow no encontrado"}

        item = {
            "id": sched_id,
            "workflow_id": workflow_id,
            "workflow_name": wf.get("name"),
            "param": param or wf.get("default_param", ""),
            "interval_seconds": interval_seconds,
            "next_run": time.time() + interval_seconds,
            "runs_count": 0,
            "enabled": True,
        }
        self.schedules[sched_id] = item
        return {"ok": True, "schedule": item}

    def remove_schedule(self, sched_id: str) -> Dict[str, Any]:
        self.schedules.pop(sched_id, None)
        return {"ok": True, "schedules": list(self.schedules.values())}

    def _scheduler_loop(self) -> None:
        while self._scheduler_running:
            now = time.time()
            for sid, sched in list(self.schedules.items()):
                if sched.get("enabled") and now >= sched.get("next_run", now + 999):
                    sched["next_run"] = now + sched["interval_seconds"]
                    sched["runs_count"] = sched.get("runs_count", 0) + 1
                    wfs = self.persistence.get_workflows()
                    wf = next((w for w in wfs if w.get("id") == sched["workflow_id"]), None)
                    if wf:
                        self.start_workflow_async(wf, param_value=sched.get("param", ""))
            time.sleep(2.0)
