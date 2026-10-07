"""
core/web_research_engine.py - Motor de Exploración Web e Investigación Profunda Autónoma
========================================================================================

Permite a GODWORKS SYSTEM v26.4 investigar temas en internet de manera completamente autónoma:
  1. Expansión y descomposición de temas en consultas de búsqueda optimizadas.
  2. Búsqueda multi-fuente (DuckDuckGo HTML, DuckDuckGo Lite, scraping seguro).
  3. Extracción profunda y limpia del contenido de páginas web (eliminación de scripts,
     estilos, publicidad y cookies; retención de texto sustantivo y bloques de código).
  4. Síntesis y análisis inteligente utilizando Cloud API (Groq LPU a 350+ tok/s) o motor
     local de respaldo, con citas bibliográficas estructuradas [Título](URL).
  5. Caché de resultados para minimizar consumo de ancho de banda y latencia.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("GODWORKS.WebResearch")

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/REDACTED_IP Safari/537.36"
)

_EGRESS_LOG = Path(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
) / "vw-control" / "web_egress.log"


def _log_egress(kind: str, payload: str) -> None:
    try:
        _EGRESS_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_EGRESS_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {kind} | {payload}\n")
    except Exception:
        pass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str = "duckduckgo"


@dataclass
class PageContent:
    url: str
    title: str
    text: str
    code_snippets: List[str] = field(default_factory=list)
    word_count: int = 0
    status_code: int = 200
    error: Optional[str] = None


@dataclass
class ResearchReport:
    topic: str
    queries_used: List[str]
    sources: List[Dict[str, Any]]
    synthesis: str
    elapsed_seconds: float
    provider_used: str = "algorithmic"
    key_findings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def clean_html_to_text(html_content: str, max_chars: int = 6000) -> Tuple[str, List[str]]:
    """Extrae texto limpio y fragmentos de código de una página HTML."""
    if not html_content:
        return "", []

    # Extraer bloques de código antes de limpiar etiquetas
    code_blocks = []
    for m in re.finditer(r"<pre[^>]*><code[^>]*>(.*?)</code></pre>", html_content, re.DOTALL | re.IGNORECASE):
        clean_code = html_mod.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        if len(clean_code) > 20:
            code_blocks.append(clean_code[:1200])

    # Remover scripts, estilos, comentarios y svg
    cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", html_content, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<svg[^>]*>.*?</svg>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<noscript[^>]*>.*?</noscript>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<nav[^>]*>.*?</nav>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<footer[^>]*>.*?</footer>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<header[^>]*>.*?</header>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)

    # Convertir saltos y párrafos en saltos de línea legibles
    cleaned = re.sub(r"<(?:p|div|h1|h2|h3|h4|h5|h6|li|tr|blockquote)[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)

    # Remover todas las demás etiquetas HTML
    text = re.sub(r"<[^>]+>", " ", cleaned)
    text = html_mod.unescape(text)

    # Limpiar espacios en blanco excesivos
    lines = [line.strip() for line in text.splitlines()]
    clean_lines = [l for l in lines if l and len(l) > 3]
    full_text = "\n".join(clean_lines)
    full_text = re.sub(r"[ \t]+", " ", full_text)
    full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()

    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n...[Contenido truncado por límite de contexto]..."

    return full_text, code_blocks[:5]


class WebResearchEngine:
    """Motor integral de búsqueda, extracción y síntesis web."""

    _instance: Optional["WebResearchEngine"] = None
    _lock = threading.Lock()

    def __init__(self, cache_ttl: int = 3600):
        self.cache_ttl = cache_ttl
        self._search_cache: Dict[str, Tuple[float, List[SearchResult]]] = {}
        self._page_cache: Dict[str, Tuple[float, PageContent]] = {}
        self._cache_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "WebResearchEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def search_yahoo(self, query: str, max_results: int = 6) -> List[SearchResult]:
        """Busca en Yahoo Search con extracción limpia de enlaces orgánicos y snippets sin bloqueos."""
        query = query.strip()
        if not query:
            return []

        now = time.time()
        with self._cache_lock:
            if f"yh:{query}" in self._search_cache:
                ts, results = self._search_cache[f"yh:{query}"]
                if now - ts < self.cache_ttl:
                    return results

        _log_egress("SEARCH_YAHOO", query)
        results: List[SearchResult] = []

        try:
            with httpx.Client(timeout=14.0, follow_redirects=True) as client:
                url = f"https://search.yahoo.com/search?p={urllib.parse.quote(query)}"
                resp = client.get(url, headers={"User-Agent": _UA})
                if resp.status_code == 200:
                    html_txt = resp.text
                    # Extraer bloques de resultados orgánicos
                    blocks = re.findall(
                        r'<div class="compTitle[^"]*">.*?<a[^>]+href="([^"]+)"[^>]*>.*?<h3[^>]*>(.*?)</h3>',
                        html_txt,
                        re.DOTALL
                    )
                    # Extraer snippets asociados
                    snippets = re.findall(
                        r'<div class="compText aAbs[^"]*"[^>]*>(.*?)</div>',
                        html_txt,
                        re.DOTALL
                    )

                    for i, (href, h3) in enumerate(blocks):
                        # Yahoo envuelve las URLs reales en /RU=.../
                        m_ru = re.search(r'/RU=([^/]+)/', href)
                        target_url = urllib.parse.unquote(m_ru.group(1)) if m_ru else href

                        if not target_url.startswith("http") or "search.yahoo.com" in target_url:
                            continue

                        title = html_mod.unescape(re.sub(r"<[^>]+>", "", h3)).strip()
                        snip = ""
                        if i < len(snippets):
                            snip = html_mod.unescape(re.sub(r"<[^>]+>", "", snippets[i])).strip()

                        if not any(r.url == target_url for r in results):
                            results.append(SearchResult(
                                title=title or "Fuente Web",
                                url=target_url,
                                snippet=snip,
                                engine="yahoo"
                            ))
                            if len(results) >= max_results:
                                break
        except Exception as e:
            logger.warning(f"Aviso en búsqueda Yahoo: {e}")

        with self._cache_lock:
            self._search_cache[f"yh:{query}"] = (now, results)

        return results

    def search_wikipedia(self, query: str, max_results: int = 4) -> List[SearchResult]:
        """Busca artículos enciclopédicos en Wikipedia API en español e inglés."""
        query = query.strip()
        if not query:
            return []

        _log_egress("SEARCH_WIKIPEDIA", query)
        results: List[SearchResult] = []
        clean_q = re.sub(r"\b(investiga|busca|sobre|acerca de|que es|qué es|quien es|quién es)\b", "", query, flags=re.I).strip()
        if not clean_q:
            clean_q = query

        headers = {"User-Agent": "GodworksSystem/26.4 (research_agent@godworks.local)"}
        for lang in ("es", "en"):
            try:
                with httpx.Client(timeout=8.0) as client:
                    api_url = f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={urllib.parse.quote(clean_q)}&limit={max_results}&format=json"
                    r = client.get(api_url, headers=headers)
                    if r.status_code == 200:
                        data = r.json()
                        titles = data[1] if len(data) > 1 else []
                        snippets = data[2] if len(data) > 2 else []
                        urls = data[3] if len(data) > 3 else []
                        for t, s, u in zip(titles, snippets, urls):
                            if u and not any(res.url == u for res in results):
                                results.append(SearchResult(
                                    title=f"{t} (Wikipedia)",
                                    url=u,
                                    snippet=s or f"Artículo enciclopédico sobre {t}.",
                                    engine=f"wikipedia_{lang}"
                                ))
                                if len(results) >= max_results:
                                    return results
            except Exception:
                pass

        return results

    def search_duckduckgo_api(self, query: str, max_results: int = 4) -> List[SearchResult]:
        """Consulta la API de respuestas instantáneas de DuckDuckGo."""
        query = query.strip()
        if not query:
            return []

        _log_egress("SEARCH_DDG_API", query)
        results: List[SearchResult] = []
        try:
            with httpx.Client(timeout=8.0) as client:
                api_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json"
                r = client.get(api_url, headers={"User-Agent": _UA})
                if r.status_code == 200:
                    d = r.json()
                    abstract = d.get("AbstractText") or d.get("Abstract")
                    abstract_url = d.get("AbstractURL")
                    source = d.get("AbstractSource") or "DuckDuckGo"
                    heading = d.get("Heading") or query

                    if abstract and abstract_url:
                        results.append(SearchResult(
                            title=f"{heading} ({source})",
                            url=abstract_url,
                            snippet=abstract,
                            engine="duckduckgo_api"
                        ))

                    for topic in d.get("RelatedTopics", []):
                        if isinstance(topic, dict) and topic.get("FirstURL") and topic.get("Text"):
                            t_url = topic["FirstURL"]
                            if not any(res.url == t_url for res in results):
                                results.append(SearchResult(
                                    title=topic.get("Text")[:70],
                                    url=t_url,
                                    snippet=topic.get("Text"),
                                    engine="duckduckgo_api"
                                ))
                                if len(results) >= max_results:
                                    break
        except Exception as e:
            logger.warning(f"Aviso en DDG API: {e}")

        return results

    def search(self, query: str, max_results: int = 6) -> List[SearchResult]:
        """Búsqueda web orquestada: Yahoo -> DuckDuckGo API -> Wikipedia -> DDG HTML/Lite."""
        query = query.strip()
        if not query:
            return []

        # 1. Intentar Yahoo (máxima cobertura de páginas reales y blogs técnicos)
        results = self.search_yahoo(query, max_results=max_results)
        if len(results) >= max_results:
            return results

        # 2. Complementar con DuckDuckGo API
        ddg_api_res = self.search_duckduckgo_api(query, max_results=max_results - len(results))
        for r in ddg_api_res:
            if not any(existing.url == r.url for existing in results):
                results.append(r)

        if len(results) >= max_results:
            return results

        # 3. Complementar con Wikipedia para rigor documental
        wiki_res = self.search_wikipedia(query, max_results=max_results - len(results))
        for r in wiki_res:
            if not any(existing.url == r.url for existing in results):
                results.append(r)

        if len(results) >= max_results:
            return results

        # 4. Fallback a DuckDuckGo HTML scraping
        ddg_html_res = self.search_duckduckgo_html(query, max_results=max_results - len(results))
        for r in ddg_html_res:
            if not any(existing.url == r.url for existing in results):
                results.append(r)

        return results

    def search_duckduckgo_html(self, query: str, max_results: int = 6) -> List[SearchResult]:
        """Busca en DuckDuckGo HTML scraping directo sin API key."""
        query = query.strip()
        if not query:
            return []

        now = time.time()
        with self._cache_lock:
            if query in self._search_cache:
                ts, results = self._search_cache[query]
                if now - ts < self.cache_ttl:
                    return results

        _log_egress("SEARCH_DDG_HTML", query)
        results: List[SearchResult] = []

        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                resp = client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": query},
                    headers={
                        "User-Agent": _UA,
                        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                    },
                )
                if resp.status_code == 200:
                    page = resp.text
                    blocks = re.findall(
                        r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*</div>',
                        page,
                        re.DOTALL | re.IGNORECASE,
                    )
                    for block in blocks:
                        m_link = re.search(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
                        if not m_link:
                            continue
                        raw_href, raw_title = m_link.group(1), m_link.group(2)
                        url = raw_href
                        uddg = re.search(r"[?&]uddg=([^&]+)", raw_href)
                        if uddg:
                            url = urllib.parse.unquote(uddg.group(1))

                        title = html_mod.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()

                        snippet = ""
                        m_snip = re.search(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
                        if m_snip:
                            snippet = html_mod.unescape(re.sub(r"<[^>]+>", "", m_snip.group(1))).strip()

                        if url.startswith("http") and not any(r.url == url for r in results):
                            results.append(SearchResult(title=title, url=url, snippet=snippet, engine="duckduckgo_html"))
                            if len(results) >= max_results:
                                break
        except Exception as e:
            logger.warning(f"Error en DDG HTML para '{query}': {e}")

        # Fallback a DDG Lite si HTML devolvió 0
        if not results:
            results = self.search_duckduckgo_lite(query, max_results)

        with self._cache_lock:
            self._search_cache[query] = (now, results)

        return results

    def search_duckduckgo_lite(self, query: str, max_results: int = 6) -> List[SearchResult]:
        """Búsqueda alternativa en DuckDuckGo Lite para mayor resiliencia."""
        _log_egress("SEARCH_DDG_LITE", query)
        results: List[SearchResult] = []
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.post(
                    "https://lite.duckduckgo.com/lite/",
                    data={"q": query},
                    headers={"User-Agent": _UA},
                )
                if resp.status_code == 200:
                    page = resp.text
                    matches = re.findall(
                        r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                        page,
                        re.DOTALL | re.IGNORECASE,
                    )
                    snippets = re.findall(
                        r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>',
                        page,
                        re.DOTALL | re.IGNORECASE,
                    )
                    for i, (raw_href, raw_title) in enumerate(matches):
                        url = raw_href
                        uddg = re.search(r"[?&]uddg=([^&]+)", raw_href)
                        if uddg:
                            url = urllib.parse.unquote(uddg.group(1))

                        title = html_mod.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
                        snippet = ""
                        if i < len(snippets):
                            snippet = html_mod.unescape(re.sub(r"<[^>]+>", "", snippets[i])).strip()

                        if url.startswith("http") and not any(r.url == url for r in results):
                            results.append(SearchResult(title=title, url=url, snippet=snippet, engine="duckduckgo_lite"))
                            if len(results) >= max_results:
                                break
        except Exception as e:
            logger.warning(f"Error en DDG Lite para '{query}': {e}")

        return results

    def fetch_page(self, url: str, max_chars: int = 6000) -> PageContent:
        """Descarga una URL y devuelve su contenido de texto limpio y fragmentos."""
        now = time.time()
        with self._cache_lock:
            if url in self._page_cache:
                ts, cached = self._page_cache[url]
                if now - ts < self.cache_ttl:
                    return cached

        _log_egress("FETCH_PAGE", url)
        try:
            with httpx.Client(timeout=18.0, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": _UA})
                status_code = resp.status_code
                if status_code != 200:
                    return PageContent(
                        url=url,
                        title="",
                        text="",
                        status_code=status_code,
                        error=f"HTTP {status_code}",
                    )

                html_content = resp.text
                m_title = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
                title = html_mod.unescape(m_title.group(1)).strip() if m_title else url

                clean_text, code_snippets = clean_html_to_text(html_content, max_chars=max_chars)
                word_count = len(clean_text.split())

                page = PageContent(
                    url=url,
                    title=title,
                    text=clean_text,
                    code_snippets=code_snippets,
                    word_count=word_count,
                    status_code=status_code,
                )

                with self._cache_lock:
                    self._page_cache[url] = (now, page)

                return page

        except Exception as e:
            logger.warning(f"Error descargando {url}: {e}")
            return PageContent(
                url=url,
                title="",
                text="",
                status_code=0,
                error=str(e),
            )

    def decompose_topic(self, topic: str) -> List[str]:
        """Genera consultas complementarias para una investigación profunda."""
        queries = [topic]
        t_clean = topic.strip().lower()

        if "investiga" in t_clean or "buscar" in t_clean:
            cleaned = re.sub(r"\b(investiga|investigar|busca|buscar|sobre|acerca de|en internet)\b", "", t_clean, flags=re.I).strip()
            if cleaned:
                queries[0] = cleaned

        main_q = queries[0]
        if any(w in main_q for w in ("error", "bug", "exception", "failed", "crash")):
            queries.append(f"{main_q} solution fix github stackoverflow")
        elif any(w in main_q for w in ("api", "libreria", "biblioteca", "framework", "sdk", "modulo")):
            queries.append(f"{main_q} documentation example python")
        elif any(w in main_q for w in ("precio", "costo", "comprar", "valor")):
            queries.append(f"{main_q} 2026 comparativa precio")
        elif not any(w in main_q for w in ("2025", "2026", "actual")):
            queries.append(f"{main_q} 2026")

        return list(dict.fromkeys(queries))[:3]

    def deep_research(
        self,
        topic: str,
        max_sources: int = 4,
        max_chars_per_page: int = 4000,
        use_llm_synthesis: bool = True,
    ) -> ResearchReport:
        """Ejecuta una investigación web completa: búsqueda multi-query, descarga profunda y síntesis."""
        t0 = time.time()
        queries = self.decompose_topic(topic)
        all_results: List[SearchResult] = []
        seen_urls = set()

        for q in queries:
            results = self.search(q, max_results=max_sources)
            for r in results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)
            if len(all_results) >= max_sources * 2:
                break

        selected_sources = all_results[:max_sources]
        downloaded_pages: List[PageContent] = []
        for src in selected_sources:
            page = self.fetch_page(src.url, max_chars=max_chars_per_page)
            if page.text and not page.error:
                downloaded_pages.append(page)

        sources_meta = []
        for p in downloaded_pages:
            sources_meta.append({
                "title": p.title,
                "url": p.url,
                "word_count": p.word_count,
                "snippets_count": len(p.code_snippets),
            })

        synthesis = ""
        provider_used = "extractive"
        key_findings = []

        if use_llm_synthesis:
            try:
                from core.chinese_cloud_api import get_chinese_cloud_api
                cloud_api = get_chinese_cloud_api()
                st = cloud_api.get_status()

                context_blocks = []
                for p in downloaded_pages:
                    snippet = p.text[:2500]
                    context_blocks.append(f"### Fuente: [{p.title}]({p.url})\n{snippet}")

                context_str = "\n\n".join(context_blocks)
                system_prompt = (
                    "Eres el Motor de Investigación Profunda de GODWORKS SYSTEM v26.4. "
                    "Tu tarea es analizar y sintetizar la información web obtenida sobre el tema solicitado. "
                    "Genera una síntesis técnica, clara, precisa y directa al punto.\n"
                    "REGLAS:\n"
                    "1. Cita siempre las fuentes utilizadas usando enlaces markdown [Título](URL).\n"
                    "2. Si hay código relevante, inclúyelo en bloques con sintaxis.\n"
                    "3. Destaca 3 a 5 hallazgos clave o conclusiones al inicio.\n"
                    "4. Responde en español con rigor técnico."
                )
                user_msg = (
                    f"TEMA DE INVESTIGACIÓN: {topic}\n\n"
                    f"INFORMACIÓN EXTRAÍDA DE LA WEB:\n{context_str}\n\n"
                    "Sintetiza la respuesta completa y estructurada:"
                )

                if st.get("enabled") and st.get("has_key"):
                    max_toks = 1000 if "groq" in st.get("active_provider", "") else 2048
                    resp = cloud_api.chat_completion([
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ], max_tokens=max_toks, timeout=25.0)

                    if resp.get("ok") and resp.get("reply"):
                        synthesis = resp["reply"].strip()
                        provider_used = f"cloud_api ({resp.get('model')})"
            except Exception as e_llm:
                logger.warning(f"Aviso en síntesis LLM de investigación: {e_llm}")

        if not synthesis:
            synthesis = self._generate_extractive_synthesis(topic, downloaded_pages, selected_sources)
            provider_used = "algorithmic_extractive"

        for line in synthesis.splitlines():
            clean_l = line.strip()
            if clean_l.startswith(("- ", "* ", "1.", "2.", "3.", "• ")):
                key_findings.append(clean_l.lstrip("-*•123456789. "))
            if len(key_findings) >= 5:
                break

        elapsed = round(time.time() - t0, 2)
        return ResearchReport(
            topic=topic,
            queries_used=queries,
            sources=sources_meta,
            synthesis=synthesis,
            elapsed_seconds=elapsed,
            provider_used=provider_used,
            key_findings=key_findings,
        )

    def _generate_extractive_synthesis(
        self,
        topic: str,
        pages: List[PageContent],
        search_results: List[SearchResult],
    ) -> str:
        """Genera una síntesis estructurada sin depender de inferencia externa."""
        lines = [
            f"# Informe de Investigación: {topic}",
            "",
            "## Fuentes Consultadas y Respaldo Web",
        ]
        for src in search_results:
            lines.append(f"- **[{src.title}]({src.url})**: {src.snippet}")

        lines.append("")
        lines.append("## Contenido y Hallazgos Extraídos")

        for p in pages:
            lines.append(f"### De [{p.title}]({p.url})")
            paragraphs = [p_txt for p_txt in p.text.split("\n\n") if len(p_txt) > 80]
            for p_txt in paragraphs[:3]:
                lines.append(f"> {p_txt[:400]}...")
            if p.code_snippets:
                lines.append("#### Código o Comando Relevante:")
                lines.append(f"```text\n{p.code_snippets[0]}\n```")
            lines.append("")

        return "\n".join(lines)


def get_web_research_engine() -> WebResearchEngine:
    return WebResearchEngine.get_instance()
