"""
web_researcher.py - Motor de Investigación Web y Adquisición de Conocimiento
=============================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4

Busca de manera autónoma en la web (DuckDuckGo, Wikipedia, ArXiv y documentación técnica)
para recopilar conceptos, algoritmos, bibliotecas y código relevante para cualquier
tema de interés (e.g. Arte Computacional, Fractales, Simulación Física, Redes Neuronales).
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import os
import re
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from cognitivo_sistema.config import KNOWLEDGE_DIR, GIA_URL, GIA_TOKEN

logger = logging.getLogger("Cognitivo.WebResearcher")

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/REDACTED_IP Safari/537.36"
)


@dataclass
class SearchSnippet:
    title: str
    url: str
    snippet: str
    source: str = "web"


@dataclass
class KnowledgeDossier:
    topic: str
    timestamp: float
    queries: List[str]
    snippets: List[SearchSnippet]
    extracted_concepts: List[str]
    code_examples: List[str]
    synthesis_markdown: str
    suggested_software_goals: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WebResearcher:
    """
    Investigador Web Autónomo del Sistema Cognitivo.
    """

    def __init__(self):
        self._client = httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            timeout=15.0,
            follow_redirects=True
        )

    def search_duckduckgo_lite(self, query: str, max_results: int = 6) -> List[SearchSnippet]:
        """Búsqueda web directa a través de la interfaz Lite de DuckDuckGo sin javascript."""
        results: List[SearchSnippet] = []
        try:
            url = "https://lite.duckduckgo.com/lite/"
            data = {"q": query}
            resp = self._client.post(url, data=data)
            if resp.status_code == 200:
                html_text = resp.text
                # Buscar enlaces de resultados
                # Los resultados de DDG Lite tienen clases como 'result-link' y snippets en 'result-snippet'
                link_matches = re.findall(
                    r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                    html_text,
                    re.IGNORECASE
                )
                snippet_matches = re.findall(
                    r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>',
                    html_text,
                    re.IGNORECASE
                )

                for i, (href, title_raw) in enumerate(link_matches[:max_results]):
                    # Decodificar redirect
                    actual_url = href
                    if "uddg=" in href:
                        try:
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                            actual_url = parsed.get("uddg", [href])[0]
                        except Exception:
                            pass

                    clean_title = html_lib.unescape(re.sub(r"<[^>]+>", "", title_raw)).strip()
                    clean_snip = ""
                    if i < len(snippet_matches):
                        clean_snip = html_lib.unescape(re.sub(r"<[^>]+>", "", snippet_matches[i])).strip()

                    if clean_title and actual_url.startswith("http"):
                        results.append(SearchSnippet(
                            title=clean_title,
                            url=actual_url,
                            snippet=clean_snip,
                            source="duckduckgo"
                        ))
        except Exception as e:
            logger.warning(f"[RESEARCH] Error en DuckDuckGo: {e}")

        return results

    def search_wikipedia(self, topic: str, lang: str = "es") -> Optional[SearchSnippet]:
        """Consulta directa a la API de Wikipedia para obtener resúmenes enciclopédicos rigurosos."""
        try:
            api_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(topic)}"
            resp = self._client.get(api_url)
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title", topic)
                extract = data.get("extract", "")
                page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                if extract:
                    return SearchSnippet(
                        title=f"Wikipedia: {title}",
                        url=page_url or f"https://{lang}.wikipedia.org/wiki/{topic}",
                        snippet=extract[:1200],
                        source="wikipedia"
                    )
            elif lang == "es":
                # Intentar en inglés como alternativa
                return self.search_wikipedia(topic, lang="en")
        except Exception as e:
            logger.warning(f"[RESEARCH] Error consultando Wikipedia: {e}")
        return None

    def search_arxiv(self, query: str, max_results: int = 3) -> List[SearchSnippet]:
        """Consulta ArXiv para encontrar modelos matemáticos o papers técnicos."""
        results: List[SearchSnippet] = []
        try:
            url = f"http://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(query)}&start=0&max_results={max_results}"
            resp = self._client.get(url)
            if resp.status_code == 200:
                entries = re.findall(r"<entry>(.*?)</entry>", resp.text, re.DOTALL)
                for entry in entries:
                    t_match = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
                    s_match = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
                    id_match = re.search(r"<id>(.*?)</id>", entry)
                    if t_match and s_match:
                        title = re.sub(r"\s+", " ", t_match.group(1)).strip()
                        summary = re.sub(r"\s+", " ", s_match.group(1)).strip()
                        paper_url = id_match.group(1).strip() if id_match else ""
                        results.append(SearchSnippet(
                            title=f"ArXiv: {title}",
                            url=paper_url,
                            snippet=summary[:800],
                            source="arxiv"
                        ))
        except Exception as e:
            logger.warning(f"[RESEARCH] Error consultando ArXiv: {e}")
        return results

    def investigate_topic(self, topic: str) -> KnowledgeDossier:
        """
        Ejecuta una investigación completa sobre un tema de interés y genera un dossier
        de aprendizaje estructurado.
        """
        logger.info(f"[RESEARCH] Iniciando investigación sobre: '{topic}'")
        queries = [
            topic,
            f"{topic} algoritmos python simulacion",
            f"{topic} generative mathematical models"
        ]

        all_snippets: List[SearchSnippet] = []

        # 1. Wikipedia
        wiki_res = self.search_wikipedia(topic)
        if wiki_res:
            all_snippets.append(wiki_res)

        # 2. DuckDuckGo multi-query
        for q in queries[:2]:
            ddg_res = self.search_duckduckgo_lite(q, max_results=4)
            for item in ddg_res:
                if not any(x.url == item.url for x in all_snippets):
                    all_snippets.append(item)
            time.sleep(0.3)

        # 3. ArXiv si es técnico/matemático
        arxiv_res = self.search_arxiv(topic, max_results=2)
        all_snippets.extend(arxiv_res)

        # 4. Extracción de conceptos clave
        extracted_concepts = self._extract_key_concepts(topic, all_snippets)

        # 5. Sugerencias de software a construir
        software_goals = self._derive_software_goals(topic, extracted_concepts)

        # 6. Síntesis markdown
        synthesis = self._build_synthesis_markdown(topic, all_snippets, extracted_concepts, software_goals)

        dossier = KnowledgeDossier(
            topic=topic,
            timestamp=time.time(),
            queries=queries,
            snippets=all_snippets,
            extracted_concepts=extracted_concepts,
            code_examples=[],
            synthesis_markdown=synthesis,
            suggested_software_goals=software_goals
        )

        # Persistir en disco
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic.lower())[:40]
        file_path = KNOWLEDGE_DIR / f"dossier_{safe_name}.json"
        try:
            file_path.write_text(json.dumps(dossier.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"[RESEARCH] Dossier persistido en {file_path}")
        except Exception as e:
            logger.error(f"[RESEARCH] Error guardando dossier: {e}")

        return dossier

    def _extract_key_concepts(self, topic: str, snippets: List[SearchSnippet]) -> List[str]:
        concepts = set()
        topic_lower = topic.lower()

        # Palabras clave especializadas según el dominio
        art_keywords = ["fractal", "voronoi", "turing", "caos", "atractor", "lorenz", "mandelbrot",
                        "bezier", "perlin", "delaunay", "colorimetria", "vectorial", "simetria", "procedural"]
        physics_keywords = ["onda", "wheeler", "feynman", "sintropia", "entropia", "cuantico",
                            "hamiltoniano", "autovalor", "campo", "potencial", "resonancia", "frecuencia"]

        text_corpus = " ".join([s.title + " " + s.snippet for s in snippets]).lower()

        for kw in art_keywords + physics_keywords:
            if kw in text_corpus or kw in topic_lower:
                concepts.add(kw.capitalize())

        if not concepts:
            words = [w for w in re.findall(r"\b[A-Za-záéíóúÁÉÍÓÚ]{5,}\b", text_corpus)]
            for w in words[:6]:
                concepts.add(w.capitalize())

        return sorted(list(concepts))[:8]

    def _derive_software_goals(self, topic: str, concepts: List[str]) -> List[str]:
        goals = []
        c_str = ", ".join(concepts[:3]) if concepts else topic
        goals.append(f"Crear simulador procedural interactivo para modelar '{topic}' utilizando {c_str}.")
        goals.append(f"Generar suite de renderizado visual de alta resolución exportable a PNG/SVG basada en {topic}.")
        goals.append(f"Implementar módulo matemático con aceleración tensorial en PyTorch y optimización de kernel.")
        return goals

    def _build_synthesis_markdown(
        self,
        topic: str,
        snippets: List[SearchSnippet],
        concepts: List[str],
        goals: List[str]
    ) -> str:
        lines = [
            f"# Dossier Cognitivo de Investigación: {topic.title()}",
            f"**Fecha y Registro:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 1. Conceptos Fundamentales Identificados",
            ", ".join([f"`{c}`" for c in concepts]) if concepts else "Exploración inicial de fundamentos.",
            "",
            "## 2. Hallazgos y Fuentes Consultadas",
        ]

        for s in snippets[:6]:
            lines.append(f"- **[{s.title}]({s.url})** ({s.source}):")
            lines.append(f"  > {s.snippet[:280]}...")

        lines.extend([
            "",
            "## 3. Metas de Auto-Programación Derivadas",
        ])
        for g in goals:
            lines.append(f"- [ ] {g}")

        return "\n".join(lines)


def get_web_researcher() -> WebResearcher:
    return WebResearcher()
