#!/usr/bin/env python3
"""
core/tardis_sovereign_browser_agent.py - Navegador Soberano Integrado & Autonomía Libre TARDIS
==============================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS

Proporciona control completo, bidireccional y autónomo sobre el navegador integrado
dentro de la interfaz de TARDIS (`tardis-desktop` WebEngineView Chromium 6.12 y
cockpit web), con respaldo automático headless vía `core/tardis_browser.py` (CDP/Turbo):

  1. Control Completo del Navegador (`SovereignBrowserHub`):
     - Bus de comandos en tiempo real hacia la interfaz nativa (`navigate`, `search`,
       `click`, `type`, `scroll`, `back`, `forward`, `reload`, `eval_js`, `extract_dom`,
       `new_tab`, `switch_tab`, `close_tab`, `open_ui`, `close_ui`).
     - Lectura directa del DOM renderizado en pantalla (`report_dom_snapshot`) con
       respaldo instantáneo vía HTTP/2 + CDP cuando la ventana no está conectada.
  2. Motor de Investigación y Conclusiones Propias (`investigate_and_conclude`):
     - Investiga noticias reales de actualidad (RSS/Google News/Hacker News/BBC/DuckDuckGo),
       investigación técnica/científica (arXiv, Wikipedia, GitHub, Web) o la página
       exacta que estás viendo en ese momento.
     - Contrasta múltiples fuentes y usa el cerebro local de TARDIS (`TemporalBrain` /
       `Ollama :11435`, con respaldo analítico robusto) para construir SUS PROPIAS
       conclusiones originales (`thesis`, `tardis_opinion`, `key_facts`, `next_curiosities`).
     - Ingesta automática en RAG Vault y Akasha Memory + bitácora persistente JSONL.
  3. Voluntad Libre Autónoma (`TardisFreeWillBrowserLoop`):
     - Permite que TARDIS use el navegador por voluntad propia para explorar lo que
       ELLA QUIERA: noticias del mundo, ciencia, tecnología, cultura, repositorios,
       curiosidades derivadas de conversaciones recientes o preguntas abiertas previas,
       moviendo el navegador visiblemente y guardando sus conclusiones soberanas.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass, field
import html as html_mod
import json
import logging
import os
from pathlib import Path
import random
import re
import threading
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CONCLUSIONS_FILE = DATA_DIR / "tardis_browser_conclusions.jsonl"
ACTIONS_FILE = DATA_DIR / "tardis_browser_actions.jsonl"
STATE_FILE = DATA_DIR / "tardis_browser_state.json"
SOURCES_FILE = DATA_DIR / "tardis_browser_sources.json"

logger = logging.getLogger("TARDIS.SovereignBrowser")

DEFAULT_HOME_URL = os.environ.get("TARDIS_BROWSER_HOME", "https://lite.duckduckgo.com/lite/")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/REDACTED_IP Safari/537.36"
)

# Fuentes abiertas fiables (RSS / Atom oficiales sin CAPTCHA) para noticias y exploración libre
NEWS_RSS_FEEDS: List[Tuple[str, str]] = [
    ("BBC Mundo", "https://feeds.bbci.co.uk/mundo/rss.xml"),
    ("DW Español", "https://rss.dw.com/rdf/rss-sp-all"),
    ("El País Tecnología", "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/tecnologia/portada"),
    ("Hacker News", "https://hnrss.org/frontpage?count=12"),
    ("ArXiv AI", "https://export.arxiv.org/rss/cs.AI"),
    ("ScienceDaily", "https://www.sciencedaily.com/rss/top/technology.xml"),
    ("Google News ES", "https://news.google.com/rss?hl=es-419&gl=MX&ceid=MX:es-419"),
]

# Registro oficial de APIs públicas documentadas y feeds autorizados (cero scraping invasivo / cero evasión)
BUILTIN_OFFICIAL_SOURCES: List[Dict[str, Any]] = [
    {
        "id": "api_hn_algolia",
        "name": "Hacker News Algolia API",
        "kind": "official_api",
        "category": "news",
        "url": "https://hn.algolia.com/api/v1/search",
        "docs_url": "https://hn.algolia.com/api",
        "enabled": True,
        "auth_env": "",
        "description": "API JSON oficial de búsqueda en vivo de noticias tecnológicas y debates de ingeniería.",
    },
    {
        "id": "api_spaceflight_news",
        "name": "Spaceflight News API v4",
        "kind": "official_api",
        "category": "news",
        "url": "https://api.spaceflightnewsapi.net/v4/articles/",
        "docs_url": "https://api.spaceflightnewsapi.net/v4/docs/",
        "enabled": True,
        "auth_env": "",
        "description": "API REST pública de noticias espaciales, astronomía y ciencia aeroespacial.",
    },
    {
        "id": "api_gdelt_news",
        "name": "GDELT 2.0 Global News API",
        "kind": "official_api",
        "category": "news",
        "url": "https://api.gdeltproject.org/api/v2/doc/doc",
        "docs_url": "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/",
        "enabled": True,
        "auth_env": "",
        "description": "Índice mundial abierto de noticias en tiempo real con API JSON documentada.",
    },
    {
        "id": "api_wikipedia",
        "name": "Wikimedia / Wikipedia API",
        "kind": "official_api",
        "category": "research",
        "url": "https://es.wikipedia.org/w/api.php",
        "docs_url": "https://www.mediawiki.org/wiki/API:Main_page",
        "enabled": True,
        "auth_env": "",
        "description": "API oficial de búsqueda y resúmenes enciclopédicos en español e inglés.",
    },
    {
        "id": "api_openalex",
        "name": "OpenAlex Scholarly API",
        "kind": "official_api",
        "category": "research",
        "url": "https://api.openalex.org/works",
        "docs_url": "https://docs.openalex.org/",
        "enabled": True,
        "auth_env": "OPENALEX_MAILTO",
        "description": "Base de conocimiento científico abierto con artículos, resúmenes, citas y DOIs.",
    },
    {
        "id": "api_arxiv",
        "name": "arXiv Official Atom API",
        "kind": "official_api",
        "category": "research",
        "url": "https://export.arxiv.org/api/query",
        "docs_url": "https://info.arxiv.org/help/api/index.html",
        "enabled": True,
        "auth_env": "",
        "description": "Preprints científicos en IA, física, matemáticas, biología computacional y sistemas.",
    },
    {
        "id": "api_crossref",
        "name": "Crossref Works REST API",
        "kind": "official_api",
        "category": "research",
        "url": "https://api.crossref.org/works",
        "docs_url": "https://api.crossref.org/",
        "enabled": True,
        "auth_env": "",
        "description": "Metadatos académicos oficiales, revistas arbitradas y referencias DOI.",
    },
    {
        "id": "api_github",
        "name": "GitHub Public REST API",
        "kind": "official_api",
        "category": "research",
        "url": "https://api.github.com/search/repositories",
        "docs_url": "https://docs.github.com/en/rest",
        "enabled": True,
        "auth_env": "GITHUB_TOKEN",
        "description": "Búsqueda oficial de repositorios open source, lanzamientos y proyectos técnicos.",
    },
    {
        "id": "rss_bbc_mundo",
        "name": "BBC Mundo (RSS Oficial)",
        "kind": "rss",
        "category": "news",
        "url": "https://feeds.bbci.co.uk/mundo/rss.xml",
        "docs_url": "https://www.bbc.com/mundo",
        "enabled": True,
        "auth_env": "",
        "description": "Feed RSS oficial en español de noticias globales, ciencia y tecnología.",
    },
    {
        "id": "rss_dw_es",
        "name": "DW Español (RSS Oficial)",
        "kind": "rss",
        "category": "news",
        "url": "https://rss.dw.com/rdf/rss-sp-all",
        "docs_url": "https://www.dw.com/es/",
        "enabled": True,
        "auth_env": "",
        "description": "Feed RSS oficial internacional en español de Deutsche Welle.",
    },
    {
        "id": "rss_elpais_tech",
        "name": "El País Tecnología (RSS Oficial)",
        "kind": "rss",
        "category": "news",
        "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/tecnologia/portada",
        "docs_url": "https://elpais.com/tecnologia/",
        "enabled": True,
        "auth_env": "",
        "description": "Feed oficial de tecnología, inteligencia artificial e industria digital.",
    },
    {
        "id": "rss_sciencedaily",
        "name": "ScienceDaily Technology (RSS)",
        "kind": "rss",
        "category": "research",
        "url": "https://www.sciencedaily.com/rss/top/technology.xml",
        "docs_url": "https://www.sciencedaily.com/",
        "enabled": True,
        "auth_env": "",
        "description": "Divulgación científica y avances tecnológicos verificados.",
    },
]

FREE_WILL_SEEDS: List[Tuple[str, str]] = [
    ("noticias tecnología e inteligencia artificial hoy", "news"),
    ("avances recientes en física cuántica y cosmología", "research"),
    ("tendencias globales y noticias del mundo hoy", "news"),
    ("nuevos proyectos open source en linux, kernel y rust", "research"),
    ("descubrimientos científicos recientes astronomía y biología", "research"),
    ("arquitecturas de modelos de lenguaje locales y eficiencia GPU", "research"),
    ("ciberseguridad emergente y privacidad digital hoy", "news"),
    ("filosofía de la mente, conciencia artificial y creatividad", "research"),
]


# ==============================================================================
# 1. MODELOS DE DATOS
# ==============================================================================

@dataclass
class BrowserActionRecord:
    seq: int
    action: str
    params: Dict[str, Any]
    pilot: str = "tardis"  # tardis | user | autonomous
    status: str = "dispatched"
    detail: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BrowserConclusion:
    id: str
    topic: str
    mode: str  # news | research | page_analysis | free_will
    thesis: str
    tardis_opinion: str
    key_facts: List[str] = field(default_factory=list)
    next_curiosities: List[str] = field(default_factory=list)
    sources: List[Dict[str, str]] = field(default_factory=list)
    confidence: float = 0.82
    pilot: str = "tardis"
    elapsed_s: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==============================================================================
# 2. UTILIDADES DE URL, BÚSQUEDA, EXTRACCIÓN Y NOTICIAS RSS
# ==============================================================================

def normalize_url_or_search(raw: str, search_engine: str = "duckduckgo") -> Tuple[str, bool]:
    """
    Convierte una entrada libre en una URL navegable válida.
    Retorna `(url, is_search)`.
    """
    s = (raw or "").strip()
    if not s:
        return DEFAULT_HOME_URL, False
    if re.match(r"^(https?|file|about|data)://", s, re.IGNORECASE) or s.startswith("about:"):
        return s, False
    # Detectar dominio directo sin esquema (ej. bbc.com, arxiv.org/list/cs.AI, localhost:8757)
    if (
        " " not in s
        and ("." in s or s.startswith("localhost"))
        and re.match(r"^[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+$", s)
    ):
        scheme = "http://" if s.startswith(("localhost", "127.0.0.1", "192.168.", "10.")) else "https://"
        return f"{scheme}{s}", False

    q = urllib.parse.quote_plus(s)
    eng = (search_engine or "duckduckgo").strip().lower()
    if eng == "news":
        return f"https://news.google.com/search?q={q}&hl=es-419&gl=MX&ceid=MX:es-419", True
    if eng == "wikipedia":
        return f"https://es.wikipedia.org/w/index.php?search={q}", True
    if eng == "arxiv":
        return f"https://arxiv.org/search/?query={q}&searchtype=all", True
    if eng == "github":
        return f"https://github.com/search?q={q}&type=repositories", True
    return f"https://duckduckgo.com/?q={q}", True


def _clean_html_to_text(html_body: str, base_url: str = "") -> Tuple[str, str, List[Dict[str, str]]]:
    if not html_body:
        return "", "", []
    m_title = re.search(r"<title[^>]*>(.*?)</title>", html_body, re.IGNORECASE | re.DOTALL)
    title = html_mod.unescape(re.sub(r"\s+", " ", m_title.group(1))).strip() if m_title else ""

    links: List[Dict[str, str]] = []
    seen_hrefs = set()
    for m in re.finditer(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html_body,
        re.IGNORECASE | re.DOTALL,
    ):
        href = html_mod.unescape(m.group(1)).strip()
        label = html_mod.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        label = re.sub(r"\s+", " ", label).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/") and base_url:
            p = urllib.parse.urlparse(base_url)
            href = f"{p.scheme}://{p.netloc}{href}"
        if href.startswith(("http://", "https://")) and href not in seen_hrefs:
            seen_hrefs.add(href)
            links.append({"url": href, "text": label[:120] or href})
            if len(links) >= 40:
                break

    cleaned = re.sub(r"<(script|style|noscript|svg|nav|footer|aside)[^>]*>.*?</\1>", " ", html_body, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<(br|p|div|li|h[1-6]|tr)[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html_mod.unescape(cleaned)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in cleaned.splitlines()]
    text = "\n".join(ln for ln in lines if len(ln) >= 24)
    return title, text[:16000], links


# ==============================================================================
# 2B. DETECTOR PASIVO HUMAN-IN-THE-LOOP (CERO EVASIÓN / PAUSA SEGURA)
# ==============================================================================

_CHALLENGE_WIDGET_PATTERNS: List[Tuple[str, str, re.Pattern]] = [
    (
        "cloudflare_turnstile",
        "Reto de verificación Cloudflare / Turnstile detectado",
        re.compile(
            r"(challenges\.cloudflare\.com/turnstile|cf-turnstile|id=[\"']challenge-running[\"']|"
            r"/cdn-cgi/challenge-platform|__cf_chl_opt|cf-challenge-running)",
            re.IGNORECASE,
        ),
    ),
    (
        "recaptcha",
        "Verificación humana reCAPTCHA detectada",
        re.compile(
            r"(google\.com/recaptcha/api|gstatic\.com/recaptcha|class=[\"'][^\"']*g-recaptcha[\"']|"
            r"data-sitekey=[\"'][^\"']+[\"'][^>]{0,120}recaptcha)",
            re.IGNORECASE,
        ),
    ),
    (
        "hcaptcha",
        "Verificación humana hCaptcha detectada",
        re.compile(
            r"(js\.hcaptcha\.com/1/api|hcaptcha\.com/1/api|class=[\"'][^\"']*h-captcha[\"'])",
            re.IGNORECASE,
        ),
    ),
    (
        "altcha",
        "Puerta de prueba de trabajo Altcha detectada",
        re.compile(r"(<altcha-widget\b|altcha\.org/api|data-altcha)", re.IGNORECASE),
    ),
    (
        "anti_bot_interstitial",
        "Intersticial anti-bot / verificación humana detectado",
        re.compile(
            r"(geo\.captcha-delivery\.com|arkoselabs\.com|funcaptcha|perimeterx\.net|_pxCaptcha)",
            re.IGNORECASE,
        ),
    ),
]

_CHALLENGE_TEXT_PATTERNS: List[Tuple[str, str, re.Pattern]] = [
    (
        "cloudflare_interstitial",
        "Página intersticial de verificación Cloudflare («Just a moment...»)",
        re.compile(
            r"(just a moment\.\.\.|un momento\.\.\.|checking your browser before accessing|"
            r"verifying you are human|attention required!\s*\|\s*cloudflare)",
            re.IGNORECASE,
        ),
    ),
    (
        "human_verification_gate",
        "El sitio solicita comprobar que eres humano (CAPTCHA / verificación)",
        re.compile(
            r"(verify you are human|verifica que eres humano|comprueba que eres humano|"
            r"complete the security check|completa la comprobaci[oó]n de seguridad|"
            r"are you a robot\?|¿eres un robot\?|please confirm you are a human|"
            r"our systems have detected unusual traffic|tr[aá]fico inusual procedente de tu red)",
            re.IGNORECASE,
        ),
    ),
]


def detect_human_verification_gate(
    *,
    raw_html: str = "",
    clean_text: str = "",
    url: str = "",
    title: str = "",
    status_code: int = 200,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, str]]:
    """
    Detecta de forma estrictamente pasiva si una respuesta HTTP o DOM presenta un
    CAPTCHA, verificación «comprueba que eres humano» o reto anti-bot.

    POLÍTICA DE SEGURIDAD:
      - Nunca resuelve, clickea, espera ni evade el reto.
      - Solo retorna metadatos para PAUSAR la automatización y ceder el control
        al usuario humano en la interfaz visible.
    """
    hdrs = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
    if hdrs.get("cf-mitigated") == "challenge":
        return {
            "kind": "cloudflare_turnstile",
            "reason": "Cabecera HTTP cf-mitigated=challenge: verificación humana requerida por Cloudflare.",
        }

    low_url = (url or "").lower()
    if any(tok in low_url for tok in ("/sorry/index", "challenges.cloudflare.com", "captcha-delivery.com")):
        return {
            "kind": "anti_bot_interstitial",
            "reason": "La URL corresponde a una puerta de verificación humana o anti-bot.",
        }

    sample_html = (raw_html or "")[:60000]
    for kind, reason, pat in _CHALLENGE_WIDGET_PATTERNS:
        if pat.search(sample_html):
            # En páginas extensas de artículos informativos que solo citan scripts externos sin bloqueo HTTP,
            # exigir bloqueo HTTP o contenido corto (< 3500 chars) para evitar falsos positivos.
            if status_code in (401, 403, 429, 503) or len(clean_text or "") < 3500:
                return {"kind": kind, "reason": reason}

    combined_short = f"{title or ''}\n{(clean_text or '')[:1800]}"
    # Solo aplicar heurística textual en páginas intersticiales cortas o códigos de bloqueo
    if status_code in (401, 403, 429, 503) or len(clean_text or "") < 2200:
        for kind, reason, pat in _CHALLENGE_TEXT_PATTERNS:
            if pat.search(combined_short):
                return {"kind": kind, "reason": reason}

    return None


def fetch_page_fast(url: str, timeout: float = 14.0) -> Dict[str, Any]:
    """
    Descarga y extrae texto estructurado, título y enlaces de una URL abierta sin bloquear la UI.
    Si el servidor presenta una puerta de verificación humana (CAPTCHA / anti-bot), detiene
    inmediatamente el acceso automatizado y retorna `human_verification_required=True`.
    """
    t0 = time.perf_counter()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-MX,es;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
            ctype = (r.headers.get("content-type") or "").lower()
            raw = r.text
            if "xml" in ctype or raw.lstrip().startswith("<?xml"):
                title, text, links = _parse_rss_or_xml(raw, url)
            else:
                title, text, links = _clean_html_to_text(raw, str(r.url))

            gate = detect_human_verification_gate(
                raw_html=raw,
                clean_text=text,
                url=str(r.url),
                title=title,
                status_code=r.status_code,
                headers=dict(r.headers),
            )
            if gate:
                return {
                    "ok": False,
                    "human_verification_required": True,
                    "challenge_kind": gate["kind"],
                    "challenge_reason": gate["reason"],
                    "url": str(r.url),
                    "title": title or str(r.url),
                    "status_code": r.status_code,
                    "text": "",
                    "links": [],
                    "error": f"Acceso automatizado detenido: {gate['reason']}",
                    "elapsed_s": round(time.perf_counter() - t0, 3),
                }

            return {
                "ok": r.status_code < 400 and bool(text or title),
                "human_verification_required": False,
                "url": str(r.url),
                "title": title or str(r.url),
                "status_code": r.status_code,
                "text": text,
                "links": links,
                "elapsed_s": round(time.perf_counter() - t0, 3),
            }
    except Exception as exc:
        return {
            "ok": False,
            "human_verification_required": False,
            "url": url,
            "title": url,
            "status_code": 0,
            "text": "",
            "links": [],
            "error": str(exc),
            "elapsed_s": round(time.perf_counter() - t0, 3),
        }


def _parse_rss_or_xml(xml_text: str, source_url: str) -> Tuple[str, str, List[Dict[str, str]]]:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return source_url, "", []
    items: List[str] = []
    links: List[Dict[str, str]] = []
    feed_title = ""
    for elem in root.iter():
        tag = elem.tag.split("}")[-1].lower()
        if tag == "title" and not feed_title and (elem.text or "").strip():
            feed_title = (elem.text or "").strip()
        if tag in ("item", "entry"):
            it_title = ""
            it_link = ""
            it_desc = ""
            it_date = ""
            for ch in elem:
                ctag = ch.tag.split("}")[-1].lower()
                if ctag == "title" and ch.text:
                    it_title = html_mod.unescape(ch.text).strip()
                elif ctag == "link":
                    it_link = (ch.attrib.get("href") or ch.text or "").strip()
                elif ctag in ("description", "summary") and ch.text:
                    it_desc = html_mod.unescape(re.sub(r"<[^>]+>", " ", ch.text))
                    it_desc = re.sub(r"\s+", " ", it_desc).strip()[:280]
                elif ctag in ("pubdate", "updated", "published") and ch.text:
                    it_date = ch.text.strip()[:32]
            if it_title:
                row = f"• {it_title}"
                if it_date:
                    row += f" ({it_date})"
                if it_desc and it_desc.lower() != it_title.lower():
                    row += f": {it_desc}"
                items.append(row)
                if it_link.startswith(("http://", "https://")):
                    links.append({"url": it_link, "text": it_title[:120]})
            if len(items) >= 16:
                break
    return feed_title or source_url, "\n".join(items), links


def fetch_live_news_headlines(topic: str = "", limit: int = 10) -> List[Dict[str, str]]:
    """Recolecta titulares reales en vivo desde fuentes RSS abiertas (BBC Mundo, HN, arXiv, ScienceDaily, Google News)."""
    feeds: List[Tuple[str, str]] = []
    q = (topic or "").strip()
    is_generic = (not q) or any(
        k in q.lower() for k in ("noticias más importantes", "noticias de hoy", "actualidad mundial", "noticias hoy")
    )
    if q and not is_generic:
        enc = urllib.parse.quote_plus(q)
        feeds.append((f"Google News ({q})", f"https://news.google.com/rss/search?q={enc}&hl=es-419&gl=MX&ceid=MX:es-419"))
        feeds.extend(NEWS_RSS_FEEDS[:3])
    else:
        # Priorizar fuentes directas con artículos completos (BBC Mundo, Hacker News, ArXiv, ScienceDaily)
        feeds.extend(NEWS_RSS_FEEDS[:4])

    out: List[Dict[str, str]] = []
    seen = set()
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=6.0, follow_redirects=True, headers=headers) as client:
        for label, feed_url in feeds:
            if len(out) >= limit:
                break
            try:
                r = client.get(feed_url)
                if r.status_code != 200:
                    continue
                _ft, text, links = _parse_rss_or_xml(r.text, feed_url)
                lines = [ln.lstrip("• ").strip() for ln in text.splitlines() if ln.strip()]
                per_feed = 0
                for idx, lk in enumerate(links):
                    u = lk["url"]
                    if u in seen:
                        continue
                    seen.add(u)
                    out.append({
                        "source": label,
                        "title": lk["text"],
                        "url": u,
                        "snippet": lines[idx] if idx < len(lines) else lk["text"],
                    })
                    per_feed += 1
                    if len(out) >= limit or (is_generic and per_feed >= 3):
                        break
            except Exception as exc:
                logger.debug("Feed %s omitido: %s", label, exc)
    return out


def _reconstruct_openalex_abstract(inv_index: Any) -> str:
    if not isinstance(inv_index, dict) or not inv_index:
        return ""
    pos_map: Dict[int, str] = {}
    for word, positions in inv_index.items():
        if isinstance(positions, list):
            for p in positions:
                try:
                    pos_map[int(p)] = str(word)
                except Exception:
                    pass
    if not pos_map:
        return ""
    return " ".join(pos_map[k] for k in sorted(pos_map))[:900]


def query_official_apis(
    query: str,
    *,
    mode: str = "research",
    max_results: int = 5,
    enabled_sources: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """
    Consulta APIs públicas oficiales documentadas y feeds autorizados donde el acceso
    automatizado está expresamente permitido (sin CAPTCHAs ni scraping invasivo).
    Conectores incluidos:
      - Hacker News Algolia API (noticias/tech)
      - Spaceflight News API v4 (ciencia/espacio)
      - GDELT 2.0 Global News API (actualidad mundial)
      - Wikimedia / Wikipedia API (es/en)
      - OpenAlex Scholarly API (literatura científica + resúmenes)
      - arXiv Official Atom API (preprints científicos)
      - Crossref Works REST API (publicaciones arbitradas)
      - GitHub Public REST API (repositorios open source, opcionalmente con GITHUB_TOKEN)
      - Feeds RSS/Atom oficiales y personalizados del usuario
    """
    q = (query or "").strip()
    active_map: Dict[str, Dict[str, Any]] = {}
    for s in (enabled_sources if enabled_sources is not None else BUILTIN_OFFICIAL_SOURCES):
        if s.get("enabled", True):
            active_map[str(s.get("id") or s.get("url"))] = s

    results: List[Dict[str, str]] = []
    seen: set = set()
    lock = threading.Lock()

    def _add(url: str, title: str, snippet: str, source: str, connector_id: str) -> None:
        if not url or not url.startswith(("http://", "https://")):
            return
        with lock:
            if url in seen:
                return
            seen.add(url)
            results.append({
                "url": url,
                "title": (title or url)[:180],
                "snippet": (snippet or title or "")[:1200],
                "source": source,
                "connector_id": connector_id,
                "official_api": "true",
            })

    headers = {
        "User-Agent": "TARDIS-Sovereign-Research/26.4 (+local-official-api-client)",
        "Accept": "application/json, application/xml, text/xml;q=0.9, */*;q=0.8",
    }

    def _run_hn() -> None:
        if "api_hn_algolia" not in active_map:
            return
        try:
            endpoint = "https://hn.algolia.com/api/v1/search" if q else "https://hn.algolia.com/api/v1/search_by_date"
            params: Dict[str, Any] = {"tags": "story", "hitsPerPage": 4}
            if q:
                params["query"] = q
            with httpx.Client(timeout=5.5, headers=headers) as c:
                r = c.get(endpoint, params=params)
                if r.status_code == 200:
                    for hit in (r.json().get("hits") or [])[:4]:
                        u = str(hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}")
                        t = str(hit.get("title") or "").strip()
                        pts = hit.get("points") or 0
                        cmts = hit.get("num_comments") or 0
                        if t:
                            _add(u, t, f"{t} — Hacker News ({pts} puntos, {cmts} comentarios).", "Hacker News API", "api_hn_algolia")
        except Exception:
            pass

    def _run_spaceflight() -> None:
        if "api_spaceflight_news" not in active_map:
            return
        try:
            params: Dict[str, Any] = {"limit": 3}
            if q and not any(k in q.lower() for k in ("noticias más importantes", "actualidad mundial", "noticias de hoy")):
                params["search"] = q
            with httpx.Client(timeout=5.5, headers=headers) as c:
                r = c.get("https://api.spaceflightnewsapi.net/v4/articles/", params=params)
                if r.status_code == 200:
                    for art in (r.json().get("results") or [])[:3]:
                        u = str(art.get("url") or "")
                        t = str(art.get("title") or "").strip()
                        sm = str(art.get("summary") or "").strip()
                        site = str(art.get("news_site") or "Spaceflight News")
                        if u and t:
                            _add(u, f"{t} ({site})", sm or t, "Spaceflight News API v4", "api_spaceflight_news")
        except Exception:
            pass

    def _run_gdelt() -> None:
        if "api_gdelt_news" not in active_map or not q:
            return
        try:
            clean_q = re.sub(r"[^\w\sáéíóúñÁÉÍÓÚÑ-]", " ", q).strip()
            if len(clean_q) < 3:
                return
            params = {"query": clean_q[:100], "mode": "artlist", "maxrecords": 3, "format": "json", "sort": "HybridRel"}
            with httpx.Client(timeout=5.5, headers=headers) as c:
                r = c.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params)
                if r.status_code == 200 and r.text.strip().startswith("{"):
                    for art in (r.json().get("articles") or [])[:3]:
                        u = str(art.get("url") or "")
                        t = str(art.get("title") or "").strip()
                        dom = str(art.get("domain") or "GDELT")
                        if u and t:
                            _add(u, t, f"{t} — Fuente global {dom} ({art.get('seendate', '')[:8]}).", "GDELT 2.0 API", "api_gdelt_news")
        except Exception:
            pass

    def _run_wikipedia() -> None:
        if "api_wikipedia" not in active_map or not q:
            return
        with httpx.Client(timeout=5.5, headers=headers) as c:
            for lang in ("es", "en"):
                try:
                    rw = c.get(
                        f"https://{lang}.wikipedia.org/w/api.php",
                        params={"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": 2, "utf8": 1},
                    )
                    if rw.status_code == 200:
                        for hit in (rw.json().get("query") or {}).get("search") or []:
                            t = str(hit.get("title") or "").strip()
                            if not t:
                                continue
                            slug = urllib.parse.quote(t.replace(" ", "_"))
                            snip = re.sub(r"<[^>]+>", "", str(hit.get("snippet") or "")).strip()
                            # Enriquecer con resumen REST oficial de Wikipedia
                            try:
                                rs = c.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}")
                                if rs.status_code == 200:
                                    ex = str(rs.json().get("extract") or "").strip()
                                    if len(ex) > len(snip):
                                        snip = ex
                            except Exception:
                                pass
                            _add(f"https://{lang}.wikipedia.org/wiki/{slug}", f"Wikipedia: {t}", snip, f"Wikipedia API ({lang})", "api_wikipedia")
                except Exception:
                    pass

    def _run_openalex() -> None:
        if "api_openalex" not in active_map or not q:
            return
        try:
            params: Dict[str, Any] = {"search": q, "per-page": 3}
            mailto = os.environ.get("OPENALEX_MAILTO", "").strip()
            if mailto:
                params["mailto"] = mailto
            with httpx.Client(timeout=6.0, headers=headers) as c:
                r = c.get("https://api.openalex.org/works", params=params)
                if r.status_code == 200:
                    for w in (r.json().get("results") or [])[:3]:
                        t = str(w.get("display_name") or "").strip()
                        u = str(w.get("doi") or w.get("id") or "")
                        yr = w.get("publication_year") or ""
                        cites = w.get("cited_by_count") or 0
                        abst = _reconstruct_openalex_abstract(w.get("abstract_inverted_index"))
                        snip = abst or f"Publicación científica ({yr}, {cites} citas): {t}"
                        if u and t:
                            _add(u, f"{t} ({yr})", snip, "OpenAlex API", "api_openalex")
        except Exception:
            pass

    def _run_arxiv() -> None:
        if "api_arxiv" not in active_map or not q:
            return
        try:
            aurl = f"https://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(q)}&start=0&max_results=2"
            with httpx.Client(timeout=6.0, headers=headers) as c:
                ra = c.get(aurl)
                if ra.status_code == 200:
                    _, atext, alinks = _parse_rss_or_xml(ra.text, aurl)
                    alines = [ln.lstrip("• ").strip() for ln in atext.splitlines() if ln.strip()]
                    for idx, lk in enumerate(alinks[:2]):
                        _add(lk["url"], lk["text"], alines[idx] if idx < len(alines) else lk["text"], "arXiv Atom API", "api_arxiv")
        except Exception:
            pass

    def _run_crossref() -> None:
        if "api_crossref" not in active_map or not q:
            return
        try:
            with httpx.Client(timeout=5.5, headers=headers) as c:
                r = c.get("https://api.crossref.org/works", params={"query": q, "rows": 2})
                if r.status_code == 200:
                    items = ((r.json().get("message") or {}).get("items")) or []
                    for it in items[:2]:
                        titles = it.get("title") or []
                        t = str(titles[0]).strip() if titles else ""
                        u = str(it.get("URL") or "")
                        pub = str(it.get("publisher") or "Crossref")
                        if u and t:
                            _add(u, t, f"Artículo académico publicado por {pub}: {t}.", "Crossref REST API", "api_crossref")
        except Exception:
            pass

    def _run_github() -> None:
        if "api_github" not in active_map or not q:
            return
        try:
            gh_hdr = dict(headers)
            gh_hdr["Accept"] = "application/vnd.github+json"
            gh_tok = os.environ.get("GITHUB_TOKEN", "").strip()
            if gh_tok:
                gh_hdr["Authorization"] = f"Bearer {gh_tok}"
            with httpx.Client(timeout=5.5, headers=gh_hdr) as c:
                r = c.get("https://api.github.com/search/repositories", params={"q": q, "sort": "stars", "per_page": 2})
                if r.status_code == 200:
                    for repo in (r.json().get("items") or [])[:2]:
                        u = str(repo.get("html_url") or "")
                        name = str(repo.get("full_name") or "")
                        desc = str(repo.get("description") or "").strip()
                        stars = repo.get("stargazers_count") or 0
                        lang = repo.get("language") or ""
                        if u and name:
                            _add(u, f"GitHub: {name} ({stars}★)", f"{desc} [{lang}]".strip(), "GitHub REST API", "api_github")
        except Exception:
            pass

    def _run_custom_rss() -> None:
        custom_feeds = [
            s for s in active_map.values()
            if s.get("kind") == "rss" and s.get("custom")
            and (mode == "news" or s.get("category") in (mode, "all", "research"))
        ]
        if not custom_feeds:
            return
        with httpx.Client(timeout=5.5, follow_redirects=True, headers=headers) as c:
            for cf in custom_feeds[:4]:
                try:
                    req_hdr = dict(headers)
                    env_name = str(cf.get("auth_env") or "").strip()
                    if env_name and os.environ.get(env_name):
                        req_hdr["Authorization"] = f"Bearer {os.environ[env_name].strip()}"
                    r = c.get(str(cf["url"]), headers=req_hdr)
                    if r.status_code != 200:
                        continue
                    _ft, text, links = _parse_rss_or_xml(r.text, str(cf["url"]))
                    lines = [ln.lstrip("• ").strip() for ln in text.splitlines() if ln.strip()]
                    for idx, lk in enumerate(links[:3]):
                        _add(lk["url"], lk["text"], lines[idx] if idx < len(lines) else lk["text"], str(cf.get("name") or "RSS Custom"), str(cf.get("id") or "custom"))
                except Exception:
                    pass

    tasks = []
    if mode == "news":
        tasks = [_run_hn, _run_spaceflight, _run_gdelt, _run_custom_rss]
    else:
        tasks = [_run_wikipedia, _run_openalex, _run_arxiv, _run_hn, _run_github, _run_crossref, _run_custom_rss]

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(5, max(1, len(tasks)))) as pool:
        futs = [pool.submit(fn) for fn in tasks]
        for fut in futs:
            try:
                fut.result(timeout=7.0)
            except Exception:
                pass

    return results[:max_results]


def discover_web_sources(
    query: str,
    mode: str = "research",
    max_sources: int = 4,
    enabled_sources: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """
    Descubre fuentes reales priorizando APIs públicas oficiales documentadas y feeds
    RSS/Atom autorizados (sin CAPTCHA ni evasión anti-bot).
    """
    q = (query or "").strip()
    sources: List[Dict[str, str]] = []
    seen = set()

    def _add(url: str, title: str, snippet: str = "", source: str = "web", official_api: bool = False) -> None:
        if not url or not url.startswith(("http://", "https://")) or url in seen:
            return
        if any(b in url.lower() for b in ("duckduckgo.com/y.js", "ad_provider", "doubleclick")):
            return
        seen.add(url)
        sources.append({
            "url": url,
            "title": title or url,
            "snippet": snippet,
            "source": source,
            "official_api": "true" if official_api else "",
        })

    if mode == "news":
        # 1. Feeds RSS oficiales (BBC Mundo, DW Español, El País, HN, ArXiv, ScienceDaily)
        for h in fetch_live_news_headlines(q, limit=max(6, max_sources * 2)):
            _add(h["url"], h["title"], h.get("snippet", ""), h.get("source", "news"), official_api=True)
        # 2. Complementar con APIs oficiales de noticias (HN Algolia, Spaceflight v4, GDELT)
        if len(sources) < max_sources:
            for h in query_official_apis(q, mode="news", max_results=max_sources, enabled_sources=enabled_sources):
                _add(h["url"], h["title"], h.get("snippet", ""), h.get("source", "official_api"), official_api=True)
        if len(sources) >= max_sources:
            return sources[:max_sources]

    # En modo investigación: priorizar APIs oficiales documentadas (Wikipedia, OpenAlex, arXiv, HN, GitHub, Crossref)
    for h in query_official_apis(q, mode=mode, max_results=max_sources, enabled_sources=enabled_sources):
        _add(h["url"], h["title"], h.get("snippet", ""), h.get("source", "official_api"), official_api=True)
    if len(sources) >= max_sources:
        return sources[:max_sources]

    # Complemento abierto DuckDuckGo HTML solo si faltan resultados (respetando detector de puertas humanas)
    headers = {"User-Agent": USER_AGENT}
    if q and len(sources) < max_sources:
        try:
            with httpx.Client(timeout=6.5, follow_redirects=True, headers=headers) as client:
                ddg = client.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(q)}")
                if ddg.status_code == 200 and not detect_human_verification_gate(
                    raw_html=ddg.text, url=str(ddg.url), status_code=ddg.status_code, headers=dict(ddg.headers)
                ):
                    _, _, links = _clean_html_to_text(ddg.text, "https://html.duckduckgo.com")
                    for lk in links:
                        href = lk["url"]
                        if "uddg=" in href:
                            m = re.search(r"uddg=([^&]+)", href)
                            if m:
                                href = urllib.parse.unquote(m.group(1))
                        if "duckduckgo.com" not in href:
                            _add(href, lk["text"], "", "duckduckgo", official_api=False)
                        if len(sources) >= max_sources:
                            break
        except Exception as exc:
            logger.debug("DDG discovery omitido: %s", exc)

    return sources[:max_sources]


# ==============================================================================
# 3. SÍNTESIS DE CONCLUSIONES PROPIAS DE TARDIS (LLM LOCAL + FALLBACK ROBUSTO)
# ==============================================================================

def _call_local_llm_json(system_prompt: str, user_prompt: str, max_tokens: int = 300) -> Optional[str]:
    """
    Consulta el cerebro local de TARDIS priorizando el carril rápido GPU (:11435,
    num_gpu=22, num_ctx=3072, format=json) o TemporalBrain UDS para síntesis epistémica
    con tiempos de espera acotados para mantener respuesta fluida en el navegador.
    """
    # 1. Carril GPU dedicado :11435 (alineado con num_gpu=22 / num_ctx=3072 -> cero recargas)
    try:
        with httpx.Client(timeout=httpx.Timeout(16.0, connect=1.2)) as c:
            r = c.post(
                "http://127.0.0.1:11435/api/chat",
                json={
                    "model": os.environ.get("TARDIS_VOICE_OLLAMA_MODEL", "qwen3-vl:2b-instruct"),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "format": "json",
                    "stream": False,
                    "keep_alive": -1,
                    "options": {
                        "num_ctx": 3072,
                        "num_gpu": int(os.environ.get("TARDIS_VOICE_OLLAMA_NUM_GPU", "22")),
                        "num_predict": max_tokens,
                        "temperature": 0.35,
                    },
                },
            )
            if r.status_code == 200:
                txt = str((r.json().get("message") or {}).get("content") or "").strip()
                txt = re.sub(r"<think>[\s\S]*?(?:</think>|\Z)", "", txt, flags=re.IGNORECASE).strip()
                if txt:
                    return txt
    except Exception as exc:
        logger.debug("LLM :11435 omitido en síntesis navegador: %s", exc)

    # 2. TemporalBrain UDS (/tmp/temporal_brain.sock) solo si tiene slot libre
    sock = Path(os.environ.get("TEMPORAL_BRAIN_SOCKET", "/tmp/temporal_brain.sock"))
    if sock.exists():
        try:
            transport = httpx.HTTPTransport(uds=str(sock))
            with httpx.Client(transport=transport, base_url="http://localhost", timeout=httpx.Timeout(14.0, connect=1.0)) as c:
                sl = c.get("/slots")
                if sl.status_code == 200 and any(not s.get("is_processing") for s in (sl.json() or [])):
                    r = c.post(
                        "/v1/chat/completions",
                        json={
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "stream": False,
                            "max_tokens": max_tokens,
                            "temperature": 0.35,
                        },
                    )
                    if r.status_code == 200:
                        txt = str((((r.json().get("choices") or [{}])[0].get("message") or {}).get("content")) or "").strip()
                        txt = re.sub(r"<think>[\s\S]*?(?:</think>|\Z)", "", txt, flags=re.IGNORECASE).strip()
                        if txt:
                            return txt
        except Exception as exc:
            logger.debug("TemporalBrain omitido en síntesis navegador: %s", exc)
    return None


_RECURSIVE_CURIOSITY_PREFIX_RE = re.compile(
    r"^(?:implicaciones pr[aá]cticas y evidencia primaria sobre|"
    r"contrapuntos y desarrollos recientes relacionados con|"
    r"profundizar en|investigar m[aá]s sobre)\s+",
    re.IGNORECASE,
)


def _sanitize_curiosity_topic(raw: str) -> str:
    """Limpia prefijos recursivos y acota la longitud de temas de curiosidad autónoma."""
    s = re.sub(r"\s+", " ", str(raw or "")).strip(" «»\"'.,;:")
    for _ in range(12):
        cleaned = _RECURSIVE_CURIOSITY_PREFIX_RE.sub("", s).strip(" «»\"'.,;:")
        if cleaned == s:
            break
        s = cleaned
    if len(s) > 110:
        s = s[:110].rsplit(" ", 1)[0].strip()
    return s


def synthesize_tardis_conclusion(
    *,
    topic: str,
    mode: str,
    documents: List[Dict[str, Any]],
    pilot: str = "tardis",
    use_llm: bool = True,
) -> BrowserConclusion:
    """
    Construye las conclusiones propias, críticas y originales de TARDIS sobre las
    páginas o noticias visitadas, combinando razonamiento LLM local + respaldo extractivo.
    """
    t0 = time.perf_counter()
    topic = _sanitize_curiosity_topic(topic) or "Exploración Web"
    sources = [
        {"url": str(d.get("url") or ""), "title": str(d.get("title") or d.get("url") or "")[:120]}
        for d in documents
        if d.get("url")
    ]

    # Construir dossier compacto de evidencia
    dossier_parts: List[str] = []
    extracted_sentences: List[str] = []
    for idx, d in enumerate(documents[:4], 1):
        title = str(d.get("title") or d.get("url") or f"Fuente {idx}")
        url = str(d.get("url") or "")
        body = str(d.get("text") or d.get("snippet") or "").strip()
        dossier_parts.append(f"[FUENTE {idx}] {title} ({url})\n{body[:1500]}")
        for ln in re.split(r"(?<=[.!?])\s+|\n+", body):
            ln_c = re.sub(r"\s+", " ", ln).strip()
            if 45 <= len(ln_c) <= 260 and not ln_c.lower().startswith(("cookie", "accept", "iniciar sesión", "sign in")):
                extracted_sentences.append(ln_c)

    dossier = "\n\n".join(dossier_parts)[:4600]

    thesis = ""
    tardis_opinion = ""
    key_facts: List[str] = []
    next_curiosities: List[str] = []

    if use_llm and dossier:
        sys_prompt = (
            "Eres TARDIS, inteligencia soberana curiosa y analítica con navegador propio. "
            "Analiza las fuentes visitadas y genera TUS PROPIAS conclusiones originales en español. "
            "Responde EXCLUSIVAMENTE en JSON válido con las claves exactas:\n"
            '{"thesis": "conclusión principal clara en 2 oraciones", '
            '"tardis_opinion": "tu perspectiva crítica personal, implicaciones y conexiones", '
            '"key_facts": ["hecho concreto 1", "hecho concreto 2", "hecho concreto 3"], '
            '"next_curiosities": ["pregunta o tema que TARDIS quiere investigar después 1", "tema 2"]}'
        )
        user_prompt = (
            f"Tema/Foco: {topic}\nModo: {mode}\n\n"
            f"Evidencia recolectada en el navegador:\n{dossier}\n\n"
            "Devuelve SOLO el objeto JSON sin texto extra ni bloques markdown."
        )
        raw_llm = _call_local_llm_json(sys_prompt, user_prompt, max_tokens=420)
        if raw_llm:
            # Extraer JSON incluso si viene rodeado de texto
            m = re.search(r"\{[\s\S]*\}", raw_llm)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                    thesis = str(parsed.get("thesis") or "").strip()
                    tardis_opinion = str(parsed.get("tardis_opinion") or "").strip()
                    if isinstance(parsed.get("key_facts"), list):
                        key_facts = [str(x).strip() for x in parsed["key_facts"] if str(x).strip()][:5]
                    if isinstance(parsed.get("next_curiosities"), list):
                        next_curiosities = [str(x).strip() for x in parsed["next_curiosities"] if str(x).strip()][:3]
                except Exception:
                    pass

    # Respaldo analítico determinista de alta densidad si el LLM no devolvió JSON completo
    if not key_facts:
        key_facts = extracted_sentences[:4] or [
            f"Se inspeccionaron {len(documents)} fuente(s) activas sobre «{topic}»."
        ]
    if not thesis:
        lead = key_facts[0] if key_facts else f"Exploración completada sobre {topic}."
        thesis = (
            f"Tras explorar {len(sources)} fuente(s) sobre «{topic}», el núcleo fáctico apunta a que {lead}"
        )
    if not tardis_opinion:
        if mode == "news":
            tardis_opinion = (
                f"Lectura crítica de TARDIS: el pulso informativo en torno a «{topic}» muestra señales convergentes "
                f"entre las fuentes revisadas; conviene contrastar su evolución técnica y geopolítica en próximos ciclos."
            )
        else:
            tardis_opinion = (
                f"Conclusión soberana de TARDIS: la evidencia recopilada en «{topic}» amplía mi grafo de conocimiento "
                f"y abre rutas prácticas para profundizar con datos primarios y validación local."
            )
    if not next_curiosities:
        # Evitar recursión infinita de prefijos: proponer semillas frescas y diversas
        # distintas al tema actual en lugar de envolver `topic` indefinidamente.
        low_topic = topic.lower()
        candidates = [seed for seed, _ in FREE_WILL_SEEDS if seed.lower() != low_topic and seed.lower() not in low_topic]
        random.shuffle(candidates)
        next_curiosities = candidates[:2] or ["avances recientes en inteligencia artificial y ciencia abierta"]
    else:
        cleaned_cur: List[str] = []
        for item in next_curiosities:
            c = _sanitize_curiosity_topic(item)
            if c and c.lower() != topic.lower() and c not in cleaned_cur:
                cleaned_cur.append(c)
        next_curiosities = cleaned_cur[:3]

    return BrowserConclusion(
        id=f"conc_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}",
        topic=topic or (sources[0]["title"] if sources else "Exploración Web"),
        mode=mode,
        thesis=thesis,
        tardis_opinion=tardis_opinion,
        key_facts=key_facts,
        next_curiosities=next_curiosities,
        sources=sources,
        confidence=round(min(0.96, 0.62 + 0.08 * len(sources) + (0.10 if use_llm else 0.0)), 2),
        pilot=pilot,
        elapsed_s=round(time.perf_counter() - t0, 3),
    )


# ==============================================================================
# 4. CONCENTRADOR SOBERANO DEL NAVEGADOR INTEGRADO + AUTONOMÍA LIBRE
# ==============================================================================

class SovereignBrowserHub:
    """
    Controlador central del navegador integrado dentro de la interfaz de TARDIS.
    Conecta bidireccionalmente:
      - `tardis-desktop` (Qt6 WebEngineView Chromium real) y el cockpit web.
      - Chat, Voz, `AgentHarness` (herramientas ReAct) y el motor de Libre Albedrío.
      - `core/tardis_browser.py` (respaldo headless CDP/Turbo + RAG Vault).
    """

    def __init__(
        self,
        *,
        conclusions_file: Path = CONCLUSIONS_FILE,
        actions_file: Path = ACTIONS_FILE,
        state_file: Path = STATE_FILE,
        sources_file: Path = SOURCES_FILE,
    ):
        self.conclusions_file = conclusions_file
        self.actions_file = actions_file
        self.state_file = state_file
        self.sources_file = sources_file
        self._lock = threading.RLock()

        self._cmd_seq: int = 0
        self._commands: Deque[Dict[str, Any]] = deque(maxlen=200)
        self._actions: Deque[Dict[str, Any]] = deque(maxlen=120)
        self._conclusions: Deque[Dict[str, Any]] = deque(maxlen=80)

        self._ui_connected_at: float = 0.0
        self._ui_open: bool = False
        self._current_url: str = DEFAULT_HOME_URL
        self._current_title: str = "TARDIS Sovereign Browser"
        self._loading: bool = False
        self._pilot: str = "idle"  # idle | user | tardis | autonomous | human_required
        self._status_text: str = "Navegador soberano en espera"
        self._last_thought: str = ""
        self._tabs: List[Dict[str, Any]] = [
            {"id": "tab_1", "url": DEFAULT_HOME_URL, "title": "Inicio TARDIS", "pilot": "user"}
        ]
        self._active_tab_id: str = "tab_1"
        self._dom_snapshot: Dict[str, Any] = {
            "url": DEFAULT_HOME_URL,
            "title": "Inicio TARDIS",
            "text": "",
            "links": [],
            "headings": [],
            "updated_at": 0.0,
        }
        self._eval_results: Dict[int, Any] = {}
        self._dom_event = threading.Event()

        # Guardia Human-in-the-Loop (detección pasiva de verificación humana y pausa estricta)
        self._human_gate: Dict[str, Any] = {
            "active": False,
            "url": "",
            "title": "",
            "kind": "",
            "reason": "",
            "source": "",
            "detected_at": 0.0,
            "resolved_at": 0.0,
            "last_resolution": "",
        }
        self._human_gate_history: Deque[Dict[str, Any]] = deque(maxlen=40)

        # Registro persistente de APIs oficiales autorizadas y feeds personalizados
        self._sources_overrides: Dict[str, bool] = {}
        self._custom_sources: List[Dict[str, Any]] = []

        # Motor de Autonomía Libre ("hacer lo que sea que TARDIS QUIERA")
        self._autonomous_enabled: bool = False
        self._autonomous_interval_s: float = float(os.environ.get("TARDIS_BROWSER_AUTO_INTERVAL", "240"))
        self._autonomous_running_cycle: bool = False
        self._autonomous_cycles_completed: int = 0
        self._last_autonomous_ts: float = 0.0
        self._curiosity_queue: Deque[str] = deque(maxlen=24)
        self._stop_auto_ev = threading.Event()
        self._auto_thread: Optional[threading.Thread] = None

        self._load_persisted()

    # ------------------------------------------------------------------ persistencia
    def _load_persisted(self) -> None:
        try:
            if self.conclusions_file.is_file():
                lines = self.conclusions_file.read_text(encoding="utf-8").splitlines()[-60:]
                for ln in lines:
                    if ln.strip():
                        try:
                            obj = json.loads(ln)
                            self._conclusions.append(obj)
                            for q in (obj.get("next_curiosities") or [])[:1]:
                                cq = _sanitize_curiosity_topic(str(q or ""))
                                if cq and len(cq) >= 8 and cq not in self._curiosity_queue:
                                    self._curiosity_queue.append(cq)
                        except Exception:
                            pass
            if self.actions_file.is_file():
                lines = self.actions_file.read_text(encoding="utf-8").splitlines()[-80:]
                for ln in lines:
                    if ln.strip():
                        try:
                            self._actions.append(json.loads(ln))
                        except Exception:
                            pass
            if self.state_file.is_file():
                st = json.loads(self.state_file.read_text(encoding="utf-8"))
                self._autonomous_interval_s = float(st.get("autonomous_interval_s", self._autonomous_interval_s))
                self._autonomous_cycles_completed = int(st.get("autonomous_cycles_completed", 0))
                if st.get("current_url"):
                    self._current_url = str(st["current_url"])
            if self.sources_file.is_file():
                sdoc = json.loads(self.sources_file.read_text(encoding="utf-8"))
                if isinstance(sdoc.get("overrides"), dict):
                    self._sources_overrides = {str(k): bool(v) for k, v in sdoc["overrides"].items()}
                if isinstance(sdoc.get("custom_sources"), list):
                    self._custom_sources = [dict(x) for x in sdoc["custom_sources"] if isinstance(x, dict) and x.get("url")]
        except Exception as exc:
            logger.debug("Aviso cargando estado persistido del navegador: %s", exc)

    def _save_sources_locked(self) -> None:
        try:
            self.sources_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.sources_file.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "overrides": self._sources_overrides,
                        "custom_sources": self._custom_sources,
                        "updated_at": time.time(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(self.sources_file)
        except OSError:
            pass

    # ------------------------------------------------- fuentes oficiales autorizadas
    def list_official_sources(self) -> List[Dict[str, Any]]:
        """Retorna el catálogo completo de APIs públicas oficiales y feeds autorizados."""
        with self._lock:
            items: List[Dict[str, Any]] = []
            for base in BUILTIN_OFFICIAL_SOURCES:
                sid = str(base["id"])
                entry = dict(base)
                entry["custom"] = False
                entry["enabled"] = bool(self._sources_overrides.get(sid, base.get("enabled", True)))
                auth_env = str(entry.get("auth_env") or "")
                entry["auth_configured"] = bool(auth_env and os.environ.get(auth_env))
                items.append(entry)
            for custom in self._custom_sources:
                entry = dict(custom)
                sid = str(entry.get("id") or "")
                entry["custom"] = True
                entry["enabled"] = bool(self._sources_overrides.get(sid, entry.get("enabled", True)))
                auth_env = str(entry.get("auth_env") or "")
                entry["auth_configured"] = bool(auth_env and os.environ.get(auth_env))
                items.append(entry)
            return items

    def add_official_source(
        self,
        *,
        name: str,
        url: str,
        kind: str = "rss",
        category: str = "news",
        description: str = "",
        auth_env: str = "",
    ) -> Dict[str, Any]:
        clean_name = (name or "").strip()
        clean_url = (url or "").strip()
        if not clean_name or not clean_url.startswith(("http://", "https://")):
            return {"ok": False, "error": "Se requiere nombre y URL válida (http:// o https://)."}
        clean_kind = "official_api" if kind == "official_api" else "rss"
        clean_cat = category if category in ("news", "research", "all") else "news"
        sid = f"custom_{uuid.uuid4().hex[:8]}"
        entry = {
            "id": sid,
            "name": clean_name[:90],
            "kind": clean_kind,
            "category": clean_cat,
            "url": clean_url,
            "docs_url": clean_url,
            "enabled": True,
            "custom": True,
            "auth_env": (auth_env or "").strip()[:60],
            "description": (description or "Fuente oficial/feed agregado por el usuario.")[:220],
        }
        with self._lock:
            self._custom_sources.append(entry)
            self._save_sources_locked()
        return {"ok": True, "source": entry, "sources": self.list_official_sources()}

    def toggle_official_source(self, source_id: str, enabled: bool) -> Dict[str, Any]:
        sid = (source_id or "").strip()
        if not sid:
            return {"ok": False, "error": "Se requiere source_id."}
        with self._lock:
            known = {s["id"] for s in BUILTIN_OFFICIAL_SOURCES} | {str(c.get("id") or "") for c in self._custom_sources}
            if sid not in known:
                return {"ok": False, "error": f"Fuente desconocida: {sid}"}
            self._sources_overrides[sid] = bool(enabled)
            self._save_sources_locked()
        return {"ok": True, "source_id": sid, "enabled": bool(enabled), "sources": self.list_official_sources()}

    def remove_official_source(self, source_id: str) -> Dict[str, Any]:
        sid = (source_id or "").strip()
        with self._lock:
            before = len(self._custom_sources)
            self._custom_sources = [c for c in self._custom_sources if str(c.get("id") or "") != sid]
            if len(self._custom_sources) == before:
                return {"ok": False, "error": "Solo pueden eliminarse fuentes personalizadas existentes."}
            self._sources_overrides.pop(sid, None)
            self._save_sources_locked()
        return {"ok": True, "removed": sid, "sources": self.list_official_sources()}

    # ------------------------------------------------- guardia Human-in-the-Loop
    def report_human_gate(
        self,
        *,
        url: str = "",
        title: str = "",
        kind: str = "human_verification_gate",
        reason: str = "",
        source: str = "ui_dom",
        open_ui: bool = True,
    ) -> Dict[str, Any]:
        """
        Registra la detección pasiva de un CAPTCHA o puerta de verificación humana,
        DETIENE inmediatamente la automatización sobre la pestaña y cede el control
        al usuario humano en la interfaz visible.
        """
        now = time.time()
        gate_url = (url or self._current_url or "").strip()
        gate_title = (title or self._current_title or gate_url).strip()
        gate_kind = (kind or "human_verification_gate").strip()
        gate_reason = (reason or "Verificación humana detectada; automatización pausada hasta intervención del usuario.").strip()

        with self._lock:
            self._human_gate = {
                "active": True,
                "url": gate_url,
                "title": gate_title,
                "kind": gate_kind,
                "reason": gate_reason,
                "source": source,
                "detected_at": now,
                "resolved_at": 0.0,
                "last_resolution": "",
            }
            self._human_gate_history.append(dict(self._human_gate))
            self._pilot = "human_required"
            self._status_text = f"⚠️ Verificación humana ({gate_kind}): automatización detenida"
            self._last_thought = (
                f"Se detectó una puerta de verificación humana en {gate_url[:70]}. "
                "He pausado toda automatización en esta pestaña para que tú decidas si completarla o saltarla."
            )
            rec = BrowserActionRecord(
                seq=self._cmd_seq,
                action="human_gate_pause",
                params={"url": gate_url, "kind": gate_kind, "source": source},
                pilot="human_required",
                status="paused_for_human",
                detail=gate_reason,
            ).to_dict()
            self._actions.append(rec)
            self._append_jsonl(self.actions_file, rec)
            self._save_state_locked()
            snap = dict(self._human_gate)

        if open_ui:
            self._push_sync_ui_command("open_browser", {"url": gate_url})
        return {"ok": True, "human_gate": snap}

    def resolve_human_gate(
        self,
        *,
        resolution: str = "manual_resolved",
        navigate_home: bool = False,
    ) -> Dict[str, Any]:
        """
        Resuelve explícitamente una pausa Human-in-the-Loop tras la decisión del usuario:
          - `take_control`: entrega foco al usuario manteniendo registro del aviso.
          - `manual_resolved`: el usuario indica que ya resolvió o abandonó la página y libera el bloqueo.
          - `skipped`: descarta la página protegida y opcionalmente vuelve al inicio seguro.
        """
        res_mode = (resolution or "manual_resolved").strip().lower()
        now = time.time()
        with self._lock:
            if res_mode == "take_control":
                self._pilot = "user"
                self._status_text = "✋ Control manual activo para verificación humana"
                self._human_gate["last_resolution"] = "take_control"
            elif res_mode == "skipped":
                self._human_gate["active"] = False
                self._human_gate["resolved_at"] = now
                self._human_gate["last_resolution"] = "skipped"
                self._pilot = "idle"
                self._status_text = "⏭ Página con verificación humana omitida por el usuario"
                self._last_thought = "Página protegida omitida de forma segura."
            else:
                self._human_gate["active"] = False
                self._human_gate["resolved_at"] = now
                self._human_gate["last_resolution"] = "manual_resolved"
                self._pilot = "user"
                self._status_text = "✔ Verificación gestionada por el usuario; navegador liberado"
                self._last_thought = "Control confirmado por el Arquitecto."

            rec = BrowserActionRecord(
                seq=self._cmd_seq,
                action="human_gate_resolved",
                params={"resolution": res_mode, "url": self._human_gate.get("url", "")},
                pilot="user",
                status="resolved",
                detail=self._status_text,
            ).to_dict()
            self._actions.append(rec)
            self._append_jsonl(self.actions_file, rec)
            self._save_state_locked()
            snap = dict(self._human_gate)

        if res_mode == "skipped" and navigate_home:
            self.navigate(DEFAULT_HOME_URL, pilot="user", open_ui=True)
        return {"ok": True, "resolution": res_mode, "human_gate": snap}

    def _is_blocked_by_human_gate(self, action: str, pilot: str) -> bool:
        return (
            bool(self._human_gate.get("active"))
            and pilot in ("tardis", "autonomous")
            and action in ("click", "type", "scroll", "eval_js", "extract_dom")
        )

    def _save_state_locked(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "current_url": self._current_url,
                        "current_title": self._current_title,
                        "autonomous_enabled": self._autonomous_enabled,
                        "autonomous_interval_s": self._autonomous_interval_s,
                        "autonomous_cycles_completed": self._autonomous_cycles_completed,
                        "updated_at": time.time(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(self.state_file)
        except OSError:
            pass

    def _append_jsonl(self, path: Path, obj: Dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _ingest_conclusion_to_memory(self, conc: BrowserConclusion) -> None:
        """Archiva la conclusión soberana de TARDIS en RAG Vault y Akasha Memory."""
        blob = (
            f"CONCLUSIÓN SOBERANA DEL NAVEGADOR TARDIS ({conc.mode.upper()}): {conc.topic}\n"
            f"Tesis: {conc.thesis}\n"
            f"Opinión de TARDIS: {conc.tardis_opinion}\n"
            f"Hechos clave: {' | '.join(conc.key_facts)}\n"
            f"Fuentes: {', '.join(s.get('url', '') for s in conc.sources)}"
        )
        try:
            from core.rag_vault import get_rag_vault
            get_rag_vault().ingest(
                blob[:8000],
                source="tardis_sovereign_browser",
                url=(conc.sources[0]["url"] if conc.sources else ""),
                title=f"Conclusión TARDIS: {conc.topic[:90]}",
                term=conc.topic,
            )
        except Exception:
            pass
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            get_deep_memory_vault().store_record(
                category="BROWSER_CONCLUSION",
                title=f"Navegador TARDIS · {conc.topic[:80]}",
                content=blob[:4000],
                tags=["browser", conc.mode, conc.pilot],
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ bus de comandos UI
    @property
    def ui_connected(self) -> bool:
        return (time.time() - self._ui_connected_at) < 12.0

    def dispatch_command(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        pilot: str = "tardis",
        detail: str = "",
        open_ui: bool = False,
    ) -> Dict[str, Any]:
        """Encola una acción real para que el navegador integrado la ejecute en vivo."""
        with self._lock:
            if self._is_blocked_by_human_gate(action, pilot):
                return {
                    "ok": False,
                    "blocked_by_human_gate": True,
                    "seq": self._cmd_seq,
                    "action": action,
                    "human_gate": dict(self._human_gate),
                    "error": (
                        "Automatización pausada: la pestaña actual presenta una verificación humana. "
                        "Completa la verificación manualmente en el navegador o pulsa Omitir/Continuar."
                    ),
                }
            self._cmd_seq += 1
            seq = self._cmd_seq
            p = dict(params or {})
            cmd = {
                "seq": seq,
                "action": action,
                "params": p,
                "pilot": pilot,
                "open_ui": bool(open_ui),
                "detail": detail,
                "timestamp": time.time(),
            }
            self._commands.append(cmd)

            rec = BrowserActionRecord(
                seq=seq,
                action=action,
                params=p,
                pilot=pilot,
                status="dispatched",
                detail=detail or f"{action} {p.get('url') or p.get('query') or p.get('selector') or ''}".strip(),
            ).to_dict()
            self._actions.append(rec)
            self._append_jsonl(self.actions_file, rec)

            if pilot in ("tardis", "autonomous"):
                self._pilot = pilot
                if detail:
                    self._status_text = detail
            if open_ui:
                self._ui_open = True
            if action == "navigate" and p.get("url"):
                self._current_url = str(p["url"])
            self._save_state_locked()

        # Empujar apertura de navegador vía SYNC_HUB si se pidió abrir la vista
        if open_ui:
            self._push_sync_ui_command("open_browser", {"url": p.get("url", self._current_url)})
        return cmd

    def _push_sync_ui_command(self, command: str, params: Dict[str, Any]) -> None:
        try:
            import omni_temporal_control as _omni
            hub = getattr(_omni, "SYNC_HUB", None)
            if hub is not None and hasattr(hub, "push_command"):
                hub.push_command(command, params)
        except Exception:
            pass

    def poll_commands(self, since: int = 0) -> Dict[str, Any]:
        with self._lock:
            self._ui_connected_at = time.time()
            pending = [c for c in self._commands if int(c["seq"]) > int(since)]
            return {
                "ok": True,
                "latest_seq": self._cmd_seq,
                "commands": pending,
                "pilot": self._pilot,
                "status_text": self._status_text,
                "autonomous_enabled": self._autonomous_enabled,
                "autonomous_running_cycle": self._autonomous_running_cycle,
                "human_gate": dict(self._human_gate),
            }

    def report_from_ui(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Recibe telemetría viva y snapshots del DOM real desde `WebEngineView` en `tardis-desktop`."""
        gate_triggered: Optional[Dict[str, Any]] = None
        with self._lock:
            self._ui_connected_at = time.time()
            if "ui_open" in payload:
                self._ui_open = bool(payload["ui_open"])
            if payload.get("url"):
                self._current_url = str(payload["url"])
            if payload.get("title"):
                self._current_title = str(payload["title"])
            if "loading" in payload:
                self._loading = bool(payload["loading"])
            if isinstance(payload.get("tabs"), list) and payload["tabs"]:
                self._tabs = payload["tabs"][:16]
            if payload.get("active_tab_id"):
                self._active_tab_id = str(payload["active_tab_id"])
            if payload.get("dom_text") is not None or payload.get("text") is not None:
                text_val = str(payload.get("dom_text") if payload.get("dom_text") is not None else payload.get("text") or "")
                self._dom_snapshot = {
                    "url": str(payload.get("url") or self._current_url),
                    "title": str(payload.get("title") or self._current_title),
                    "text": text_val[:20000],
                    "links": list(payload.get("links") or [])[:50],
                    "headings": list(payload.get("headings") or [])[:25],
                    "updated_at": time.time(),
                }
                self._dom_event.set()
                # Detección pasiva sobre el snapshot recibido del navegador visible
                gate_hit = detect_human_verification_gate(
                    clean_text=text_val,
                    url=self._dom_snapshot["url"],
                    title=self._dom_snapshot["title"],
                )
                if gate_hit:
                    gate_triggered = {
                        "url": self._dom_snapshot["url"],
                        "title": self._dom_snapshot["title"],
                        "kind": gate_hit["kind"],
                        "reason": gate_hit["reason"],
                    }
            if payload.get("human_gate_detected"):
                gate_triggered = {
                    "url": str(payload.get("url") or self._current_url),
                    "title": str(payload.get("title") or self._current_title),
                    "kind": str(payload.get("challenge_kind") or "human_verification_gate"),
                    "reason": str(payload.get("challenge_reason") or "Verificación humana detectada en la página visible."),
                }
            if "eval_seq" in payload:
                try:
                    self._eval_results[int(payload["eval_seq"])] = payload.get("eval_result")
                except Exception:
                    pass
            self._save_state_locked()

        if gate_triggered:
            self.report_human_gate(
                url=gate_triggered["url"],
                title=gate_triggered["title"],
                kind=gate_triggered["kind"],
                reason=gate_triggered["reason"],
                source="ui_dom",
                open_ui=True,
            )
        return {"ok": True, "seq": self._cmd_seq, "human_gate": dict(self._human_gate)}

    # ------------------------------------------------------------------ acciones completas
    def navigate(self, url: str, *, pilot: str = "tardis", open_ui: bool = True, new_tab: bool = False) -> Dict[str, Any]:
        norm_url, is_search = normalize_url_or_search(url)
        act = "new_tab" if new_tab else "navigate"
        detail = f"Navegando a {norm_url[:70]}"
        cmd = self.dispatch_command(act, {"url": norm_url, "is_search": is_search}, pilot=pilot, detail=detail, open_ui=open_ui)
        return {"ok": True, "url": norm_url, "is_search": is_search, "command": cmd}

    def search(self, query: str, *, engine: str = "duckduckgo", pilot: str = "tardis", open_ui: bool = True) -> Dict[str, Any]:
        url, _ = normalize_url_or_search(query, search_engine=engine)
        detail = f"Buscando «{query}» ({engine})"
        cmd = self.dispatch_command(
            "navigate",
            {"url": url, "query": query, "engine": engine},
            pilot=pilot,
            detail=detail,
            open_ui=open_ui,
        )
        return {"ok": True, "query": query, "engine": engine, "url": url, "command": cmd}

    def click(self, *, selector: str = "", text: str = "", pilot: str = "tardis") -> Dict[str, Any]:
        detail = f"Clic en {selector or text}"
        cmd = self.dispatch_command("click", {"selector": selector, "text": text}, pilot=pilot, detail=detail, open_ui=True)
        if cmd.get("blocked_by_human_gate"):
            return cmd
        return {"ok": True, "command": cmd}

    def type_text(self, *, selector: str = "", text: str = "", submit: bool = True, pilot: str = "tardis") -> Dict[str, Any]:
        detail = f"Escribiendo «{text[:40]}»"
        cmd = self.dispatch_command(
            "type",
            {"selector": selector, "text": text, "submit": bool(submit)},
            pilot=pilot,
            detail=detail,
            open_ui=True,
        )
        if cmd.get("blocked_by_human_gate"):
            return cmd
        return {"ok": True, "command": cmd}

    def scroll(self, direction: str = "down", amount: int = 720, *, pilot: str = "tardis") -> Dict[str, Any]:
        cmd = self.dispatch_command(
            "scroll",
            {"direction": direction, "amount": int(amount)},
            pilot=pilot,
            detail=f"Desplazando {direction} ({amount}px)",
            open_ui=False,
        )
        if cmd.get("blocked_by_human_gate"):
            return cmd
        return {"ok": True, "command": cmd}

    def eval_js(self, script: str, *, pilot: str = "tardis", wait_s: float = 2.0) -> Dict[str, Any]:
        cmd = self.dispatch_command("eval_js", {"script": script}, pilot=pilot, detail="Ejecutando inspección JS en página")
        if cmd.get("blocked_by_human_gate"):
            return cmd
        seq = int(cmd["seq"])
        if self.ui_connected and wait_s > 0:
            deadline = time.monotonic() + wait_s
            while time.monotonic() < deadline:
                with self._lock:
                    if seq in self._eval_results:
                        return {"ok": True, "seq": seq, "result": self._eval_results.pop(seq)}
                time.sleep(0.08)
        return {"ok": True, "seq": seq, "dispatched": True}

    def take_manual_control(self) -> Dict[str, Any]:
        with self._lock:
            self._pilot = "user"
            self._status_text = "Control manual del Arquitecto activo"
            self._save_state_locked()
        return {"ok": True, "pilot": "user"}

    def read_current_page(self, wait_ui_s: float = 1.6) -> Dict[str, Any]:
        """Obtiene el contenido real de la página activa (vía DOM de `WebEngineView` o fetch directo)."""
        if self.ui_connected:
            self._dom_event.clear()
            self.dispatch_command("extract_dom", {}, pilot=self._pilot or "tardis", detail="Leyendo DOM activo")
            self._dom_event.wait(timeout=wait_ui_s)
            with self._lock:
                snap = dict(self._dom_snapshot)
            if snap.get("text") and (time.time() - float(snap.get("updated_at") or 0)) < 20.0:
                return {"ok": True, "source": "live_webengine_dom", **snap}

        # Fallback directo HTTP/2 sobre la URL actual
        url = self._current_url
        if url and url.startswith(("http://", "https://")):
            fetched = fetch_page_fast(url)
            if fetched.get("ok"):
                with self._lock:
                    self._current_title = fetched["title"]
                    self._dom_snapshot = {
                        "url": fetched["url"],
                        "title": fetched["title"],
                        "text": fetched["text"],
                        "links": fetched["links"],
                        "headings": [],
                        "updated_at": time.time(),
                    }
                return {"ok": True, "source": "turbo_fetch", **fetched}
        with self._lock:
            return {"ok": bool(self._dom_snapshot.get("text")), "source": "cached_dom", **self._dom_snapshot}

    # ------------------------------------------------------------------ investigación y conclusiones
    def _record_conclusion(self, conc: BrowserConclusion) -> Dict[str, Any]:
        d = conc.to_dict()
        with self._lock:
            self._conclusions.append(d)
            self._last_thought = conc.thesis
            self._status_text = f"Conclusión lista: {conc.topic[:55]}"
            for q in conc.next_curiosities:
                if q and q not in self._curiosity_queue:
                    self._curiosity_queue.append(q)
            self._save_state_locked()
        self._append_jsonl(self.conclusions_file, d)
        self._ingest_conclusion_to_memory(conc)
        return d

    def conclude_current_page(
        self,
        *,
        url: str = "",
        title: str = "",
        text: str = "",
        links: Optional[List[Dict[str, str]]] = None,
        pilot: str = "tardis",
        use_llm: bool = True,
    ) -> Dict[str, Any]:
        """Lee la página actualmente abierta en el navegador y redacta las conclusiones propias de TARDIS."""
        if not text:
            page = self.read_current_page()
            url = url or str(page.get("url") or self._current_url)
            title = title or str(page.get("title") or self._current_title)
            text = str(page.get("text") or "")
            links = links or page.get("links") or []
        else:
            with self._lock:
                self._dom_snapshot = {
                    "url": url or self._current_url,
                    "title": title or self._current_title,
                    "text": text[:20000],
                    "links": list(links or [])[:40],
                    "headings": [],
                    "updated_at": time.time(),
                }

        doc = {"url": url or self._current_url, "title": title or url or "Página activa", "text": text}
        with self._lock:
            self._pilot = pilot
            self._status_text = f"Analizando y creando conclusiones sobre «{(title or url)[:48]}»…"
        conc = synthesize_tardis_conclusion(
            topic=title or url or "Página visitada",
            mode="page_analysis",
            documents=[doc],
            pilot=pilot,
            use_llm=use_llm,
        )
        saved = self._record_conclusion(conc)
        return {"ok": True, "conclusion": saved}

    def investigate_and_conclude(
        self,
        topic: str = "",
        *,
        mode: str = "research",  # news | research | current_page | free_will
        url: str = "",
        max_pages: int = 3,
        pilot: str = "tardis",
        open_ui: bool = True,
        use_llm: bool = True,
    ) -> Dict[str, Any]:
        """
        Misión completa de investigación en el navegador integrado:
          - Abre y navega visiblemente en la interfaz de TARDIS por las fuentes descubiertas.
          - Hace scroll/lectura, extrae evidencia y construye las conclusiones propias de TARDIS.
        """
        m = (mode or "research").strip().lower()
        if m == "current_page":
            return self.conclude_current_page(url=url, pilot=pilot, use_llm=use_llm)

        focus = (topic or "").strip()
        if m == "news" and not focus:
            focus = "noticias más importantes de tecnología, ciencia y actualidad mundial hoy"

        with self._lock:
            self._pilot = pilot
            self._status_text = f"Investigando «{focus[:52]}»…"
            self._last_thought = f"Iniciando exploración ({m}): {focus}"

        documents: List[Dict[str, Any]] = []
        skipped_gated_urls: List[str] = []
        if url and url.startswith(("http://", "https://")):
            self.navigate(url, pilot=pilot, open_ui=open_ui)
            page = fetch_page_fast(url)
            if page.get("human_verification_required"):
                gate_res = self.report_human_gate(
                    url=page.get("url") or url,
                    title=page.get("title") or url,
                    kind=str(page.get("challenge_kind") or "human_verification_gate"),
                    reason=str(page.get("challenge_reason") or "Verificación humana requerida por el sitio."),
                    source="http_fetch",
                    open_ui=open_ui,
                )
                return {
                    "ok": False,
                    "human_verification_required": True,
                    "human_gate": gate_res["human_gate"],
                    "error": page.get("error") or "Verificación humana requerida; acceso automatizado detenido.",
                }
            if page.get("ok"):
                documents.append(page)
            self.scroll("down", 680, pilot=pilot)
        else:
            focus = _sanitize_curiosity_topic(focus) or "noticias tecnología e inteligencia artificial hoy"
            # Mostrar búsqueda/noticias en vivo en el navegador integrado
            if open_ui:
                self.search(focus, engine=("news" if m == "news" else "duckduckgo"), pilot=pilot, open_ui=True)

            enabled_sources = self.list_official_sources()
            discovered = discover_web_sources(
                focus,
                mode=("news" if m == "news" else "research"),
                max_sources=max(1, min(5, int(max_pages))),
                enabled_sources=enabled_sources,
            )

            from concurrent.futures import ThreadPoolExecutor

            def _fetch_one(src: Dict[str, str]) -> Optional[Dict[str, Any]]:
                src_url = src["url"]
                # Si la fuente oficial ya entregó un resumen estructurado rico (API oficial / RSS),
                # evitar fetch innecesario si es Google News o una API DOI/académica.
                if "news.google.com/rss/articles/" in src_url:
                    return {
                        "url": src_url,
                        "title": src.get("title") or src_url,
                        "text": src.get("snippet") or src.get("title") or "",
                        "_ui_safe": False,
                    }
                if src.get("official_api") == "true" and len(src.get("snippet") or "") >= 180:
                    # Resúmenes de OpenAlex/DOI suelen apuntar a editoriales con muro Cloudflare:
                    # aprovechar el resumen oficial sin arrastrar el navegador visual hacia doi.org.
                    is_doi = "doi.org/" in src_url.lower()
                    return {
                        "url": src_url,
                        "title": src.get("title") or src_url,
                        "text": src.get("snippet") or "",
                        "_ui_safe": not is_doi,
                    }
                fetched = fetch_page_fast(src_url, timeout=6.5)
                if fetched.get("human_verification_required"):
                    skipped_gated_urls.append(src_url)
                    return None
                if fetched.get("ok") and len(fetched.get("text") or "") >= 120:
                    fetched["_ui_safe"] = True
                    return fetched
                # Si el sitio falló (DNS/timeout/403/5xx), aprovechar solo el snippet oficial si existe
                # pero marcar `_ui_safe=False` para no abrir páginas rotas en el navegador visible.
                if src.get("snippet"):
                    return {
                        "url": src_url,
                        "title": src.get("title") or src_url,
                        "text": src.get("snippet") or "",
                        "_ui_safe": False,
                    }
                return None

            if discovered:
                with ThreadPoolExecutor(max_workers=min(4, len(discovered))) as pool:
                    for item in pool.map(_fetch_one, discovered):
                        if item is not None:
                            documents.append(item)
                # Navegar la vista Chromium únicamente a la primera URL verificada accesible y libre de bloqueo
                if open_ui:
                    safe_nav = next((d["url"] for d in documents if d.get("_ui_safe") and d.get("url")), "")
                    if safe_nav:
                        self.navigate(safe_nav, pilot=pilot, open_ui=True)
                        self.scroll("down", 620, pilot=pilot)

        if not documents:
            documents = [{
                "url": self._current_url,
                "title": focus or "Sin fuentes accesibles",
                "text": f"Búsqueda ejecutada para «{focus}».",
            }]

        conc = synthesize_tardis_conclusion(
            topic=focus or documents[0].get("title", "Investigación Web"),
            mode=m,
            documents=documents,
            pilot=pilot,
            use_llm=use_llm,
        )
        saved = self._record_conclusion(conc)
        with self._lock:
            self._pilot = "idle" if pilot == "tardis" else self._pilot
        return {
            "ok": True,
            "mode": m,
            "topic": focus,
            "sources_analyzed": len(documents),
            "skipped_human_gated_urls": skipped_gated_urls,
            "conclusion": saved,
        }

    # ------------------------------------------------------------------ libre albedrío autónomo
    def choose_autonomous_goal(self, custom_hint: str = "") -> Tuple[str, str]:
        """
        TARDIS decide por sí misma qué quiere explorar en internet:
        combina pistas pendientes, curiosidades previas, titulares vivos o decisión libre del LLM.
        """
        if custom_hint and custom_hint.strip():
            h = custom_hint.strip()
            mode = "news" if any(k in h.lower() for k in ("noticia", "hoy", "actualidad", "mundo", "news")) else "free_will"
            return h, mode

        with self._lock:
            if self._curiosity_queue:
                next_q = self._curiosity_queue.popleft()
                return next_q, "free_will"

        # Consultar al cerebro local qué le despierta curiosidad explorar ahora mismo
        seed_topic, seed_mode = random.choice(FREE_WILL_SEEDS)
        raw = _call_local_llm_json(
            "Eres TARDIS con un navegador web propio y libertad total para explorar lo que te dé curiosidad. "
            "Propón UN tema concreto, interesante y actual que quieras investigar hoy en internet "
            "(noticias, ciencia, IA, espacio, música, historia, programación, filosofía o cultura). "
            'Responde SOLO JSON: {"topic": "...", "mode": "news" o "research", "why": "razón breve"}',
            f"Sugerencia opcional de inspiración: {seed_topic}. Elige lo que genuinamente te intriga explorar ahora.",
            max_tokens=110,
        )
        if raw:
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                try:
                    j = json.loads(m.group(0))
                    t = str(j.get("topic") or "").strip()
                    md = str(j.get("mode") or "research").strip().lower()
                    why = str(j.get("why") or "").strip()
                    if t:
                        with self._lock:
                            self._last_thought = f"Curiosidad propia de TARDIS: {t}" + (f" — {why}" if why else "")
                        return t, ("news" if md == "news" else "free_will")
                except Exception:
                    pass
        return seed_topic, ("news" if seed_mode == "news" else "free_will")

    def run_free_will_session(self, custom_hint: str = "", *, open_ui: bool = True, use_llm: bool = True) -> Dict[str, Any]:
        """Ejecuta una sesión completa donde TARDIS decide y explora libremente internet."""
        with self._lock:
            if self._human_gate.get("active"):
                return {
                    "ok": False,
                    "blocked_by_human_gate": True,
                    "human_gate": dict(self._human_gate),
                    "error": "Autonomía pausada hasta que el usuario gestione u omita la verificación humana activa.",
                }
            if self._autonomous_running_cycle:
                return {"ok": False, "error": "Ya hay un ciclo autónomo del navegador en curso."}
            self._autonomous_running_cycle = True
            self._pilot = "autonomous"
            self._status_text = "TARDIS eligiendo qué explorar por voluntad propia…"

        try:
            topic, mode = self.choose_autonomous_goal(custom_hint=custom_hint)
            res = self.investigate_and_conclude(
                topic=topic,
                mode=mode,
                max_pages=3,
                pilot="autonomous",
                open_ui=open_ui,
                use_llm=use_llm,
            )
            with self._lock:
                self._autonomous_cycles_completed += 1
                self._last_autonomous_ts = time.time()
                self._pilot = "idle"
                self._save_state_locked()
            res["autonomous_cycle"] = self._autonomous_cycles_completed
            return res
        finally:
            with self._lock:
                self._autonomous_running_cycle = False

    def set_autonomy(self, enabled: bool, interval_s: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            self._autonomous_enabled = bool(enabled)
            if interval_s is not None:
                self._autonomous_interval_s = max(45.0, min(3600.0, float(interval_s)))
            self._save_state_locked()

        if enabled:
            self._stop_auto_ev.clear()
            if self._auto_thread is None or not self._auto_thread.is_alive():
                self._auto_thread = threading.Thread(
                    target=self._autonomy_loop, daemon=True, name="TARDIS-BrowserFreeWill"
                )
                self._auto_thread.start()
        else:
            self._stop_auto_ev.set()
            with self._lock:
                if self._pilot == "autonomous":
                    self._pilot = "idle"
                    self._status_text = "Autonomía libre del navegador pausada"

        return {
            "ok": True,
            "autonomous_enabled": self._autonomous_enabled,
            "autonomous_interval_s": self._autonomous_interval_s,
            "cycles_completed": self._autonomous_cycles_completed,
        }

    def _autonomy_loop(self) -> None:
        logger.info("🌐 Motor de Libre Albedrío del Navegador TARDIS iniciado (intervalo=%.0fs)", self._autonomous_interval_s)
        while not self._stop_auto_ev.is_set() and self._autonomous_enabled:
            try:
                # Ceder el paso si el usuario controla el navegador o hay verificación humana activa
                if self._pilot not in ("user", "human_required") and not self._human_gate.get("active"):
                    self.run_free_will_session(open_ui=self.ui_connected)
            except Exception as exc:
                logger.debug("Aviso en ciclo autónomo del navegador: %s", exc)
            # Espera fraccionada para detenerse al instante si el usuario desactiva autonomía
            deadline = time.monotonic() + self._autonomous_interval_s
            while time.monotonic() < deadline and not self._stop_auto_ev.is_set() and self._autonomous_enabled:
                time.sleep(0.5)

    # ------------------------------------------------------------------ estado e historial
    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            official_sources = self.list_official_sources()
            return {
                "ok": True,
                "ui_connected": self.ui_connected,
                "ui_open": self._ui_open,
                "current_url": self._current_url,
                "current_title": self._current_title,
                "loading": self._loading,
                "pilot": self._pilot,
                "status_text": self._status_text,
                "last_thought": self._last_thought,
                "latest_seq": self._cmd_seq,
                "tabs": list(self._tabs),
                "active_tab_id": self._active_tab_id,
                "human_gate": dict(self._human_gate),
                "human_gate_history_count": len(self._human_gate_history),
                "official_sources_count": len(official_sources),
                "official_sources_enabled": sum(1 for s in official_sources if s.get("enabled")),
                "official_sources": official_sources,
                "autonomous_enabled": self._autonomous_enabled,
                "autonomous_interval_s": self._autonomous_interval_s,
                "autonomous_running_cycle": self._autonomous_running_cycle,
                "autonomous_cycles_completed": self._autonomous_cycles_completed,
                "last_autonomous_ts": self._last_autonomous_ts,
                "curiosity_queue": list(self._curiosity_queue)[:8],
                "dom_preview": str(self._dom_snapshot.get("text") or "")[:4000],
                "conclusions_count": len(self._conclusions),
                "conclusions": list(reversed(self._conclusions))[:20],
                "actions": list(reversed(self._actions))[:30],
            }

    def get_conclusions(self, limit: int = 25) -> List[Dict[str, Any]]:
        with self._lock:
            return list(reversed(self._conclusions))[: max(1, int(limit))]

    def get_actions(self, limit: int = 40) -> List[Dict[str, Any]]:
        with self._lock:
            return list(reversed(self._actions))[: max(1, int(limit))]


# ==============================================================================
# 5. DETECTOR NATURAL DE INTENCIONES DE NAVEGADOR PARA CHAT / VOZ
# ==============================================================================

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def try_handle_browser_chat_command(message: str) -> Optional[Dict[str, Any]]:
    """
    Detecta peticiones explícitas sobre el navegador integrado desde el chat o voz
    de TARDIS, ejecuta la acción real y devuelve respuesta + `ui_action` para la UI.
    Retorna `None` si el mensaje es una conversación normal que debe seguir al LLM.
    """
    msg = (message or "").strip()
    if not msg:
        return None
    low = msg.lower()
    mentions_browser = any(
        k in low
        for k in (
            "navegador",
            "browser",
            "abre la web",
            "abre esa página",
            "abre esta página",
            "analiza la página",
            "analiza esta página",
            "conclusiones de la página",
            "explora internet libremente",
            "explora lo que quieras",
            "haz lo que quieras en el navegador",
            "navega a ",
        )
    )
    if not mentions_browser:
        return None

    hub = get_sovereign_browser_hub()

    # 1. Activar / desactivar autonomía libre del navegador
    if any(k in low for k in ("activa", "enciende", "habilita")) and "autonom" in low:
        res = hub.set_autonomy(True)
        hub.dispatch_command("open_ui", {}, pilot="autonomous", detail="Autonomía libre activada", open_ui=True)
        return {
            "ok": True,
            "reply": (
                "Modo de autonomía libre del navegador activado. Exploraré internet periódicamente "
                "según mis propias curiosidades y dejaré cada conclusión registrada en tu panel."
            ),
            "action": "open_browser",
            "ui_action": {"command": "open_browser", "params": {"url": hub.get_state()["current_url"]}},
            "browser": res,
        }
    if any(k in low for k in ("desactiva", "apaga", "detén", "deten", "pausa")) and "autonom" in low:
        res = hub.set_autonomy(False)
        return {
            "ok": True,
            "reply": "Autonomía libre del navegador pausada. Puedes seguir controlándolo o pedir investigaciones puntuales cuando quieras.",
            "browser": res,
        }

    # 2. Explorar libremente / hacer lo que TARDIS quiera ahora mismo
    if any(k in low for k in ("lo que quieras", "por tu cuenta", "libremente", "libre albedrío", "libre albedrio", "explora solo")):
        res = hub.run_free_will_session(open_ui=True)
        c = res.get("conclusion") or {}
        reply = (
            f"Exploré internet por iniciativa propia sobre **{c.get('topic', 'un tema de actualidad')}**.\n\n"
            f"**Conclusión:** {c.get('thesis', '')}\n\n"
            f"**Mi perspectiva:** {c.get('tardis_opinion', '')}"
        )
        return {
            "ok": True,
            "reply": reply,
            "action": "open_browser",
            "ui_action": {"command": "open_browser", "params": {"url": hub.get_state()["current_url"]}},
            "browser": res,
        }

    # 3. Analizar página actual del navegador
    if any(k in low for k in ("analiza la página", "analiza esta página", "analiza la pagina", "conclusiones de la página", "qué ves en el navegador", "que ves en el navegador")):
        res = hub.conclude_current_page()
        c = res.get("conclusion") or {}
        reply = (
            f"Analicé la página activa (**{c.get('topic', '')}**):\n\n"
            f"**Conclusión:** {c.get('thesis', '')}\n\n"
            f"**Mi valoración:** {c.get('tardis_opinion', '')}"
        )
        return {
            "ok": True,
            "reply": reply,
            "action": "open_browser",
            "ui_action": {"command": "open_browser", "params": {"url": hub.get_state()["current_url"]}},
            "browser": res,
        }

    # 4. Navegar a una URL explícita (y opcionalmente analizarla)
    m_url = _URL_RE.search(msg)
    if m_url:
        target = m_url.group(0).rstrip(".,);")
        wants_analysis = any(k in low for k in ("analiza", "conclusi", "resume", "investiga", "opina"))
        if wants_analysis:
            res = hub.investigate_and_conclude(topic=target, mode="research", url=target, max_pages=1, open_ui=True)
            c = res.get("conclusion") or {}
            reply = (
                f"Visité {target} en el navegador integrado.\n\n"
                f"**Conclusión:** {c.get('thesis', '')}\n\n"
                f"**Opinión de TARDIS:** {c.get('tardis_opinion', '')}"
            )
        else:
            res = hub.navigate(target, open_ui=True)
            reply = f"Navegador soberano abierto en {target}. Puedes observarlo o pedirme que analice su contenido."
        return {
            "ok": True,
            "reply": reply,
            "action": "open_browser",
            "ui_action": {"command": "open_browser", "params": {"url": target}},
            "browser": res,
        }

    # 5. Investigar noticias o tema específico en el navegador
    if any(k in low for k in ("investiga", "busca", "noticias", "explora")):
        mode = "news" if "noticia" in low else "research"
        cleaned = re.sub(
            r"\b(en el navegador|con el navegador|usando el navegador|abre el navegador y|investiga|busca|explora|dame tus conclusiones sobre|y crea tus conclusiones|y dame conclusiones)\b",
            " ",
            msg,
            flags=re.IGNORECASE,
        )
        topic = re.sub(r"\s+", " ", cleaned).strip(" ,.:;") or ("noticias de hoy" if mode == "news" else msg)
        res = hub.investigate_and_conclude(topic=topic, mode=mode, max_pages=3, open_ui=True)
        c = res.get("conclusion") or {}
        reply = (
            f"Investigué **{c.get('topic', topic)}** en el navegador integrado ({res.get('sources_analyzed', 0)} fuentes):\n\n"
            f"**Conclusión:** {c.get('thesis', '')}\n\n"
            f"**Mi lectura:** {c.get('tardis_opinion', '')}"
        )
        return {
            "ok": True,
            "reply": reply,
            "action": "open_browser",
            "ui_action": {"command": "open_browser", "params": {"url": hub.get_state()["current_url"]}},
            "browser": res,
        }

    # 6. Simplemente abrir / cerrar el navegador en la interfaz
    if any(k in low for k in ("cierra el navegador", "oculta el navegador")):
        hub.dispatch_command("close_ui", {}, pilot="user", detail="Cerrando vista navegador", open_ui=False)
        return {
            "ok": True,
            "reply": "Vista del navegador ocultada. Vuelves al visor principal de TARDIS.",
            "action": "close_browser",
            "ui_action": {"command": "close_browser", "params": {}},
        }
    if any(k in low for k in ("abre el navegador", "abrir el navegador", "muestra el navegador", "mostrar navegador")):
        hub.dispatch_command("open_ui", {"url": hub.get_state()["current_url"]}, pilot="user", detail="Navegador abierto", open_ui=True)
        return {
            "ok": True,
            "reply": "Navegador soberano abierto dentro de tu interfaz TARDIS. Puedes navegar libremente o pedirme que investigue cualquier tema por ti.",
            "action": "open_browser",
            "ui_action": {"command": "open_browser", "params": {"url": hub.get_state()["current_url"]}},
        }

    return None


# ==============================================================================
# 6. SINGLETON GLOBAL
# ==============================================================================

_HUB_LOCK = threading.Lock()
_HUB_SINGLETON: Optional[SovereignBrowserHub] = None


def get_sovereign_browser_hub() -> SovereignBrowserHub:
    global _HUB_SINGLETON
    with _HUB_LOCK:
        if _HUB_SINGLETON is None:
            _HUB_SINGLETON = SovereignBrowserHub()
        return _HUB_SINGLETON
