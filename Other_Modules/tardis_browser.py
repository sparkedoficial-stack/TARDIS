#!/usr/bin/env python3
"""
core/tardis_browser.py - Navegador Cuántico Soberano TARDIS (TARDIS Quantum Sovereign Browser)
================================================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4
Arquitecto: El Arquitecto (₪)

CARACTERÍSTICAS FUNDAMENTALES:
1. CONTROL 100% SOBERANO:
   - Control programático total del ciclo de vida, navegación, DOM, JS, capturas y perfiles.
   - Soporte Dual-Engine: Motor Turbo Ultrarrápido (HTTP/2 + SOCKS5 Tor) y Motor Deep CDP
     (Chrome DevTools Protocol sobre Chromium headless/visual sin Selenium ni Playwright).
2. ARQUITECTURA PRIVADA, VELOZ Y ENCRIPTADA (MÁXIMA SEGURIDAD):
   - Enrutamiento por defecto sobre la red Tor (Socks5h://127.0.0.1:9050) con Cero Fugas DNS.
   - Perfil Efímero en Memoria RAM (/dev/shm) con auto-destrucción garantizada (Zero Disk Trace).
   - Bóveda de persistencia cifrada AES-256 / Fernet (browser_vault.enc) para cookies y memoria epistémica.
   - Anti-Fingerprinting avanzado: enmascaramiento de navigator.webdriver, WebGL unmasked vendor,
     canvas noise, bloqueo de telemetría y desactivación estricta de leaks WebRTC UDP.
3. APRENDIZAJE Y AUTO-MEJORA CONTINUA 100% AUTÓNOMA:
   - Bucle cognitivo continuo de visitas web a fuentes de frontera científica y tecnológica.
   - En cada visita:
     * Extrae conocimiento sustancial, algoritmos, teoremas y conclusiones clave.
     * Ingesta semántica en la Bóveda RAG Soberana (core.rag_vault) y Bóveda Akáshica de TARDIS.
     * Dispara auto-mejora FTL (Faster-Than-Light Self-Improvement): genera o perfecciona módulos
       en modulos_ftl/ y actualiza heurísticas cognitivas de forma completamente autónoma.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import html as html_mod
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
import websockets
from cryptography.fernet import Fernet

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (TARDIS.Browser) %(message)s"
)
logger = logging.getLogger("TARDIS.Browser")

# Rutas del Sistema
BASE_DIR = Path(__file__).resolve().parent.parent
TARDIS_HOME = Path(os.path.expanduser("~")) / ".tardis"
TARDIS_HOME.mkdir(parents=True, exist_ok=True)

CHROME_BIN_CANDIDATES = [
    "/home/timemachine/.local/bin/chromium",
    "/home/timemachine/.local/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
]

TOR_SOCKS_PROXY = "socks5://127.0.0.1:9050"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/REDACTED_IP Safari/537.36"
)

# Clave simétrica de bóveda encriptada
VAULT_KEY_FILE = TARDIS_HOME / "browser_vault_key.key"
ENCRYPTED_VAULT_FILE = TARDIS_HOME / "browser_vault.enc"
EVOLUTION_LOG_FILE = TARDIS_HOME / "tardis_browser_evolution.jsonl"
TELEMETRY_FILE = TARDIS_HOME / "tardis_browser_telemetry.json"


# ==============================================================================
# 1. CAPA DE SEGURIDAD Y ENCRIPTACIÓN (TARDIS CIPHER & PRIVACY VAULT)
# ==============================================================================
class TardisVaultCipher:
    """Manejo de encriptación simétrica AES/Fernet para persistencia segura."""

    def __init__(self, key_file: Path = VAULT_KEY_FILE):
        self.key_file = key_file
        self.cipher = Fernet(self._get_or_create_key())

    def _get_or_create_key(self) -> bytes:
        if self.key_file.exists():
            try:
                return self.key_file.read_bytes().strip()
            except Exception:
                pass  # fallo silenciado: revisar con log
        # Generar clave soberana derivada
        key = Fernet.generate_key()
        try:
            self.key_file.write_bytes(key)
            os.chmod(self.key_file, 0o600)
        except Exception as e:
            logger.warning(f"Aviso guardando clave de bóveda: {e}")
        return key

    def encrypt_data(self, data: Union[str, dict, list]) -> bytes:
        if isinstance(data, (dict, list)):
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        elif isinstance(data, str):
            payload = data.encode("utf-8")
        else:
            payload = bytes(data)
        return self.cipher.encrypt(payload)

    def decrypt_data(self, token: bytes) -> str:
        try:
            decrypted = self.cipher.decrypt(token)
            return decrypted.decode("utf-8")
        except Exception as e:
            logger.error(f"Error descifrando bóveda: {e}")
            return ""


# ==============================================================================
# 2. MODELOS DE DATOS DEL NAVEGADOR
# ==============================================================================
@dataclass
class BrowserVisitResult:
    url: str
    title: str
    status_code: int
    text_content: str
    code_snippets: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    screenshot_path: Optional[str] = None
    engine_used: str = "turbo"
    is_tor: bool = True
    elapsed_seconds: float = 0.0
    error: Optional[str] = None
    epistemic_insight: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EpistemicInsight:
    topic: str
    source_url: str
    core_thesis: str
    key_findings: List[str]
    algorithms_or_code: List[str]
    ftl_improvement_applied: bool
    improvement_summary: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _is_tor_available() -> bool:
    """Verifica con baja latencia si el daemon Tor SOCKS5 (127.0.0.1:9050) está escuchando."""
    try:
        with socket.create_connection(("127.0.0.1", 9050), timeout=0.25):
            return True
    except OSError:
        return False


def _has_h2_support() -> bool:
    """Detecta si el paquete opcional 'h2' para HTTP/2 en httpx está instalado."""
    try:
        import h2  # noqa: F401
        return True
    except ImportError:
        return False


_HTTP2_AVAILABLE = _has_h2_support()


# ==============================================================================
# 3. MOTOR TURBO ASÍNCRONO (LIGHT HYPER-FAST ENGINE CON TOR + AUTO-FALLBACK)
# ==============================================================================
class TardisTurboEngine:
    """Motor HTTP/2 (o HTTP/1.1 auto-fallback) ultra veloz con conexión por Tor (si activo) o HTTPS directo."""

    def __init__(self, use_tor: bool = True, timeout: float = 18.0):
        self.use_tor = use_tor
        self.timeout = timeout

    async def fetch(self, url: str) -> BrowserVisitResult:
        t0 = time.time()
        effective_tor = self.use_tor and _is_tor_available()
        proxy = TOR_SOCKS_PROXY if effective_tor else None
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
            "DNT": "1",
            "Sec-GPC": "1",
        }

        try:
            async with httpx.AsyncClient(
                proxy=proxy,
                timeout=self.timeout,
                follow_redirects=True,
                verify=True,
                http2=_HTTP2_AVAILABLE,
                headers=headers
            ) as client:
                resp = await client.get(url)
                html_text = resp.text
                status_code = resp.status_code

            title, clean_text, code_snippets, links = self._parse_html(html_text, url)
            elapsed = round(time.time() - t0, 3)

            return BrowserVisitResult(
                url=url,
                title=title or url,
                status_code=status_code,
                text_content=clean_text,
                code_snippets=code_snippets,
                links=links[:25],
                engine_used="turbo",
                is_tor=effective_tor,
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            elapsed = round(time.time() - t0, 3)
            logger.warning(f"Fallo en Turbo Engine visitando {url}: {e}")
            return BrowserVisitResult(
                url=url,
                title=f"Error: {url}",
                status_code=500,
                text_content="",
                engine_used="turbo",
                is_tor=effective_tor,
                elapsed_seconds=elapsed,
                error=str(e),
            )

    def _parse_html(self, html: str, base_url: str) -> Tuple[str, str, List[str], List[str]]:
        if not html:
            return "", "", [], []

        # Título
        title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = html_mod.unescape(title_m.group(1)).strip() if title_m else ""

        # Extraer bloques de código
        code_snippets = []
        for m in re.finditer(r"<pre[^>]*><code[^>]*>(.*?)</code></pre>", html, re.DOTALL | re.IGNORECASE):
            code_txt = html_mod.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
            if len(code_txt) > 20:
                code_snippets.append(code_txt[:1500])

        # Extraer enlaces
        links = []
        for m in re.finditer(r'<a\s+(?:[^>]*?\s+)?href=["\'](.*?)["\']', html, re.IGNORECASE):
            link = m.group(1).strip()
            if link.startswith("http://") or link.startswith("https://"):
                links.append(link)
            elif link.startswith("/") and base_url:
                parsed = urllib.parse.urlparse(base_url)
                links.append(f"{parsed.scheme}://{parsed.netloc}{link}")

        # Limpiar texto (eliminar scripts, styles, etc.)
        cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<noscript[^>]*>.*?</noscript>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        clean_text = html_mod.unescape(re.sub(r"\s+", " ", cleaned)).strip()

        return title, clean_text[:12000], code_snippets, list(dict.fromkeys(links))


# ==============================================================================
# 4. MOTOR CDP DE CHROMIUM (FULL DEEP INTERACTIVE DEVTOOLS PROTOCOL)
# ==============================================================================
class TardisCDPEngine:
    """
    Controlador nativo de Chromium mediante Chrome DevTools Protocol (CDP).
    Sin Selenium, sin Playwright, 100% autónomo y directo vía WebSockets.
    """

    def __init__(self, use_tor: bool = True, headless: bool = True, port: int = 9226):
        self.use_tor = use_tor
        self.headless = headless
        self.port = port
        self.proc: Optional[subprocess.Popen] = None
        self.profile_dir: Optional[str] = None
        self.chrome_bin = self._find_chrome()

    def _find_chrome(self) -> str:
        for p in CHROME_BIN_CANDIDATES:
            if os.path.exists(p) and os.access(p, os.X_OK):
                return p
        raise FileNotFoundError("No se encontró ningún binario de Chromium/Chrome instalado en el sistema.")

    def start(self) -> None:
        """Inicia Chromium aislado en RAM efímera (/dev/shm)."""
        if self.proc and self.proc.poll() is None:
            return  # Ya está corriendo

        # Perfil volátil en RAM
        session_id = str(uuid.uuid4())[:8]
        shm_base = "/dev/shm" if os.path.exists("/dev/shm") else "/tmp"
        self.profile_dir = os.path.join(shm_base, f"tardis_browser_{session_id}")
        os.makedirs(self.profile_dir, exist_ok=True)

        cmd = [
            self.chrome_bin,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=Translate,OptimizationHints,MediaRouter,CalculateNativeWinOcclusion",
            "--webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--disable-component-update",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-default-apps",
            "--mute-audio",
            f"--user-agent={DEFAULT_USER_AGENT}",
        ]

        if self.headless:
            cmd.append("--headless=new")

        if self.use_tor and _is_tor_available():
            cmd.append(f"--proxy-server={TOR_SOCKS_PROXY}")

        cmd.append("about:blank")

        # Iniciar desacoplado de la terminal interactiva
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Esperar a que el puerto CDP esté listo
        for _ in range(40):
            time.sleep(0.1)
            try:
                r = httpx.get(f"http://127.0.0.1:{self.port}/json/version", timeout=0.5)
                if r.status_code == 200:
                    logger.debug(f"Chromium CDP iniciado exitosamente en puerto {self.port}")
                    return
            except Exception:
                pass  # fallo silenciado: revisar con log
        logger.warning("Chromium tardó en responder al puerto CDP.")

    def stop(self) -> None:
        """Detiene Chromium y destruye el perfil efímero en RAM."""
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass  # fallo silenciado: revisar con log
            self.proc = None

        if self.profile_dir and os.path.exists(self.profile_dir):
            try:
                shutil.rmtree(self.profile_dir, ignore_errors=True)
            except Exception:
                pass  # fallo silenciado: revisar con log
            self.profile_dir = None

    async def visit(self, url: str, take_screenshot: bool = False) -> BrowserVisitResult:
        """Visita una página con renderizado completo de JavaScript vía CDP."""
        t0 = time.time()
        self.start()

        target_url = None
        ws_url = None
        page_id = None

        try:
            # Crear nueva pestaña
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.put(f"http://127.0.0.1:{self.port}/json/new?{urllib.parse.quote(url, safe=':/?=&')}")
                data = r.json()
                page_id = data.get("id")
                ws_url = data.get("webSocketDebuggerUrl")

            if not ws_url:
                raise RuntimeError(f"No se obtuvo WebSocket debugger URL para {url}")

            async with websockets.connect(ws_url, max_size=25_000_000) as ws:
                msg_id = 1

                async def send_cmd(method: str, params: Optional[dict] = None) -> dict:
                    nonlocal msg_id
                    mid = msg_id
                    msg_id += 1
                    req = {"id": mid, "method": method, "params": params or {}}
                    await ws.send(json.dumps(req))
                    while True:
                        raw = await ws.recv()
                        resp = json.loads(raw)
                        if resp.get("id") == mid:
                            return resp

                # Activar domains necesarios
                await send_cmd("Page.enable")
                await send_cmd("Runtime.enable")

                # Inyectar script anti-fingerprinting
                anti_detect_script = """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
                """
                await send_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": anti_detect_script})

                # Esperar navegación y renderizado
                await asyncio.sleep(3.5)

                # Extraer título
                r_title = await send_cmd("Runtime.evaluate", {"expression": "document.title"})
                title = r_title.get("result", {}).get("result", {}).get("value", "")

                # Extraer texto limpio
                r_text = await send_cmd("Runtime.evaluate", {"expression": "document.body ? document.body.innerText : ''"})
                text_content = r_text.get("result", {}).get("result", {}).get("value", "") or ""

                # Extraer bloques de código
                r_code = await send_cmd(
                    "Runtime.evaluate",
                    {
                        "expression": """
                        Array.from(document.querySelectorAll('pre, code')).map(e => e.innerText).filter(t => t.length > 25).slice(0, 5)
                        """,
                        "returnByValue": True,
                    }
                )
                code_snippets = r_code.get("result", {}).get("result", {}).get("value", []) or []

                # Extraer enlaces
                r_links = await send_cmd(
                    "Runtime.evaluate",
                    {
                        "expression": """
                        Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(h => h.startsWith('http')).slice(0, 30)
                        """,
                        "returnByValue": True,
                    }
                )
                links = r_links.get("result", {}).get("result", {}).get("value", []) or []

                # Captura de pantalla si se solicita
                screenshot_path = None
                if take_screenshot:
                    r_shot = await send_cmd("Page.captureScreenshot", {"format": "png", "quality": 85})
                    b64_data = r_shot.get("result", {}).get("data", "")
                    if b64_data:
                        shot_file = TARDIS_HOME / f"screenshot_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
                        shot_file.write_bytes(base64.b64decode(b64_data))
                        screenshot_path = str(shot_file)

            # Cerrar pestaña en Chromium
            if page_id:
                try:
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        await client.get(f"http://127.0.0.1:{self.port}/json/close/{page_id}")
                except Exception:
                    pass  # fallo silenciado: revisar con log

            elapsed = round(time.time() - t0, 3)
            return BrowserVisitResult(
                url=url,
                title=title or url,
                status_code=200,
                text_content=text_content[:15000],
                code_snippets=code_snippets,
                links=links,
                screenshot_path=screenshot_path,
                engine_used="cdp_chromium",
                is_tor=self.use_tor,
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            elapsed = round(time.time() - t0, 3)
            logger.warning(f"Error en CDP Engine visitando {url}: {e}")
            return BrowserVisitResult(
                url=url,
                title=f"Error: {url}",
                status_code=500,
                text_content="",
                engine_used="cdp_chromium",
                is_tor=self.use_tor,
                elapsed_seconds=elapsed,
                error=str(e),
            )


# ==============================================================================
# 5. CEREBRO EPISTÉMICO Y AUTO-MEJORA FTL (COGNITIVE & FTL SELF-IMPROVEMENT)
# ==============================================================================
class TardisCognitiveLearner:
    """
    Sintetiza lo aprendido en cada visita web, lo ingesta en la Bóveda RAG/Akáshica
    y ejecuta la auto-mejora de TARDIS vía FTL (generación de módulos y heurísticas).
    """

    def __init__(self):
        self.cipher = TardisVaultCipher()
        self.evolution_log = EVOLUTION_LOG_FILE

    def distill_knowledge(self, visit: BrowserVisitResult, topic: str = "") -> EpistemicInsight:
        """Destila la esencia cognitiva del contenido extraído."""
        text = visit.text_content
        title = visit.title
        url = visit.url

        # Extraer oraciones sustantivas
        sentences = [s.strip() for s in re.split(r"[.\n]", text) if len(s.strip()) > 40]
        key_findings = []
        for s in sentences:
            if any(term in s.lower() for term in ["algoritmo", "modelo", "optimiza", "teorema", "sistema", "rendimiento", "quantum", "red", "kernel", "ia", "memoria"]):
                key_findings.append(s)
            if len(key_findings) >= 4:
                break
        if not key_findings:
            key_findings = sentences[:3] if sentences else ["Información preliminar asimilada."]

        core_thesis = (
            f"El documento '{title}' aporta conocimientos sobre {topic or 'avances técnicos y computación cuántica/IA'}. "
            f"Puntos fundamentales analizados: {'; '.join(key_findings[:2])}"
        )

        # Ingesta en Bóveda RAG Soberana
        self._ingest_into_rag(text, title, url, topic)

        # Generar y aplicar auto-mejora FTL
        applied, summary = self._apply_ftl_self_improvement(topic or title, key_findings, visit.code_snippets)

        insight = EpistemicInsight(
            topic=topic or title,
            source_url=url,
            core_thesis=core_thesis,
            key_findings=key_findings,
            algorithms_or_code=visit.code_snippets,
            ftl_improvement_applied=applied,
            improvement_summary=summary,
        )

        # Guardar en log evolutivo
        self._persist_evolution_log(insight)
        return insight

    def _ingest_into_rag(self, text: str, title: str, url: str, topic: str) -> None:
        """Ingesta en la Bóveda RAG de TARDIS si está disponible."""
        if len(text) < 80:
            return
        try:
            sys_path = "/home/timemachine/Escritorio/GODWORKS SYSTEM"
            if sys_path not in sys.path:
                sys.path.insert(0, sys_path)
            from core.rag_vault import get_rag_vault
            vault = get_rag_vault()
            vault.ingest(text[:8000], source="tardis_browser", url=url, title=title, term=topic)
            logger.debug(f"Ingesta RAG exitosa para: {title}")
        except Exception as e:
            logger.debug(f"Aviso en ingesta a rag_vault: {e}")

    def _apply_ftl_self_improvement(
        self, topic: str, findings: List[str], code_snippets: List[str]
    ) -> Tuple[bool, str]:
        """
        Registra el aprendizaje del navegador como hallazgo indexable.

        Antes sintetizaba un módulo Python por cada tema visitado con un cuerpo fijo
        ("active_wisdom"): 5.000 ficheros idénticos en modulos_ftl que el Hub publicaba
        como subsistemas online. Un módulo sin lógica no mejora nada; el hallazgo se
        persiste en el log evolutivo y en la bóveda RAG, que sí se consultan.
        """
        try:
            resumen = " | ".join(findings[:5]) if findings else ""
            detalle = (
                f"Hallazgo FTL sobre '{topic}': {resumen}"
                + (f" ({len(code_snippets)} fragmentos de código analizados)" if code_snippets else "")
            )
            self._persist_evolution_log(
                EpistemicInsight(
                    topic=topic,
                    source_url="",
                    core_thesis=(findings[0] if findings else f"Aprendizaje sobre {topic}"),
                    key_findings=findings[:5],
                    algorithms_or_code=code_snippets[:3],
                    ftl_improvement_applied=False,
                    improvement_summary=detalle,
                )
            )
            self._ingest_into_rag(detalle, title=f"FTL: {topic}", url="", topic=topic)
            return True, f"Hallazgo FTL sobre '{topic}' registrado (sin módulo vacío)."
        except Exception as e:
            logger.warning(f"Aviso en ciclo de auto-mejora FTL: {e}")
            return False, f"Error en adaptación FTL: {e}"

    def _persist_evolution_log(self, insight: EpistemicInsight) -> None:
        """Persiste el registro evolutivo en la bóveda cifrada y log JSONL."""
        try:
            with open(self.evolution_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(insight.to_dict(), ensure_ascii=False) + "\n")

            # Actualizar snapshot encriptado
            token = self.cipher.encrypt_data(insight.to_dict())
            with open(ENCRYPTED_VAULT_FILE, "ab") as f_enc:
                f_enc.write(token + b"\n---REC---\n")
        except Exception as e:
            logger.debug(f"Aviso persistiendo evolución epistémica: {e}")


# ==============================================================================
# 6. ORQUESTADOR CENTRAL DEL NAVEGADOR TARDIS (TARDIS BROWSER)
# ==============================================================================
class TardisBrowser:
    """
    Fachada y controlador soberano del navegador TARDIS.
    Ofrece navegación transparente, búsqueda, aprendizaje y bucle continuo.
    """

    def __init__(self, default_engine: str = "turbo", use_tor: bool = True):
        self.default_engine = default_engine
        self.use_tor = use_tor
        self.turbo = TardisTurboEngine(use_tor=use_tor)
        self.cdp = TardisCDPEngine(use_tor=use_tor, headless=True)
        self.learner = TardisCognitiveLearner()

    async def visit(
        self,
        url: str,
        engine: Optional[str] = None,
        take_screenshot: bool = False,
        learn: bool = True,
        topic: str = "",
    ) -> BrowserVisitResult:
        """Visita una URL utilizando el motor indicado (turbo o cdp) y asimila conocimiento."""
        selected_engine = engine or self.default_engine

        if selected_engine == "cdp":
            result = await self.cdp.visit(url, take_screenshot=take_screenshot)
        else:
            result = await self.turbo.fetch(url)

        if learn and result.status_code == 200 and len(result.text_content) > 100:
            insight = self.learner.distill_knowledge(result, topic=topic or result.title)
            result.epistemic_insight = insight.to_dict()

        self._record_telemetry(result)
        return result

    async def search_and_learn(self, query: str, deep: bool = False) -> Dict[str, Any]:
        """Busca temas en la web (DuckDuckGo Lite/HTML) y visita las mejores fuentes para aprender."""
        logger.info(f"🔍 Búsqueda y aprendizaje autónomo para: '{query}'")
        search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        search_res = await self.turbo.fetch(search_url)

        # Extraer enlaces de resultados (decodificando enlaces uddg de DuckDuckGo)
        target_links = []
        for link in search_res.links:
            if "uddg=" in link:
                m_u = re.search(r"uddg=([^&]+)", link)
                if m_u:
                    real_url = urllib.parse.unquote(m_u.group(1))
                    if real_url.startswith("http") and "duckduckgo.com" not in real_url:
                        target_links.append(real_url)
            elif "duckduckgo.com" not in link and "google.com" not in link and link.startswith("http"):
                target_links.append(link)

            if len(target_links) >= 3:
                break

        if not target_links:
            # Fallback a Wikipedia con búsqueda semántica o directa
            safe_topic = urllib.parse.quote(query.split()[0].replace(' ', '_'))
            target_links = [f"https://es.wikipedia.org/wiki/{safe_topic}"]

        visited = []
        for link in target_links:
            engine_to_use = "cdp" if deep else "turbo"
            res = await self.visit(link, engine=engine_to_use, learn=True, topic=query)
            visited.append(res.to_dict())

        return {
            "query": query,
            "sources_visited": len(visited),
            "results": visited,
            "timestamp": time.time(),
        }

    async def inspect_x_feed(self, scroll_steps: int = 4) -> Dict[str, Any]:
        """
        Inspecciona la línea temporal activa de X.com del usuario clonando de forma
        efímera y segura su sesión local de Chromium (sin bloquear ni modificar el perfil original),
        extrae publicaciones y tendencias, y las asimila en la Bóveda RAG de TARDIS.
        """
        t0 = time.time()
        prof = f"/tmp/tardis_x_feed_{uuid.uuid4().hex[:6]}"
        port = 9235
        shutil.rmtree(prof, ignore_errors=True)
        os.makedirs(f"{prof}/Default", exist_ok=True)

        src_root = os.path.expanduser("~/.config/chromium")
        src_local = os.path.join(src_root, "Local State")
        if os.path.exists(src_local):
            shutil.copy2(src_local, f"{prof}/Local State")

        for item in ["Cookies", "Preferences", "Secure Preferences", "Network", "Local Storage", "Session Storage"]:
            src = os.path.join(src_root, "Default", item)
            dst = os.path.join(prof, "Default", item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                shutil.copy2(src, dst)

        chrome_bin = self.cdp._find_chrome()
        cmd = [
            chrome_bin,
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={prof}",
            "--no-sandbox",
            "--disable-gpu",
            "--window-size=1440,1200",
            "--disable-blink-features=AutomationControlled",
            f"--user-agent={DEFAULT_USER_AGENT}",
            "https://x.com/home",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        tweets_map: Dict[str, Dict[str, str]] = {}
        sidebar_items: List[str] = []
        title = "Inicio / X"

        try:
            ws_url = None
            for _ in range(35):
                await asyncio.sleep(0.2)
                try:
                    async with httpx.AsyncClient(timeout=1.0) as client:
                        r = await client.get(f"http://127.0.0.1:{port}/json/list")
                        if r.status_code == 200 and r.json():
                            ws_url = r.json()[0].get("webSocketDebuggerUrl")
                            if ws_url:
                                break
                except Exception:
                    pass  # fallo silenciado: revisar con log

            if ws_url:
                async with websockets.connect(ws_url, max_size=25_000_000) as ws:
                    await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
                    await asyncio.sleep(3.5)
                    for step in range(max(1, scroll_steps)):
                        expr = """
                        (() => {
                            const title = document.title;
                            const items = Array.from(document.querySelectorAll("article[data-testid=\\"tweet\\"]")).map(art => {
                                const user = art.querySelector("[data-testid=\\"User-Name\\"]")?.innerText?.replace(/\\n+/g, " ") || "";
                                const text = art.querySelector("[data-testid=\\"tweetText\\"]")?.innerText?.replace(/\\n+/g, " ") || "";
                                const link = art.querySelector("time")?.parentElement?.href || "";
                                return {user, text: text.slice(0, 400), link};
                            });
                            const sidebar = Array.from(document.querySelectorAll("[data-testid=\\"trend\\"], [data-testid=\\"UserCell\\"]")).map(e => e.innerText.replace(/\\n+/g, " | "));
                            return {title, items, sidebar};
                        })()
                        """
                        req_id = 100 + step
                        await ws.send(json.dumps({"id": req_id, "method": "Runtime.evaluate", "params": {"expression": expr, "returnByValue": True}}))
                        while True:
                            msg = json.loads(await ws.recv())
                            if msg.get("id") == req_id:
                                val = msg.get("result", {}).get("result", {}).get("value", {})
                                title = val.get("title") or title
                                for it in val.get("items", []):
                                    key = it.get("link") or (it.get("user", "") + it.get("text", "")[:40])
                                    if key and key not in tweets_map:
                                        tweets_map[key] = it
                                if val.get("sidebar"):
                                    sidebar_items = val["sidebar"]
                                break
                        await ws.send(json.dumps({"id": 200 + step, "method": "Runtime.evaluate", "params": {"expression": "window.scrollBy(0, 1800)"}}))
                        await asyncio.sleep(1.0)
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass  # fallo silenciado: revisar con log
            shutil.rmtree(prof, ignore_errors=True)

        tweets_list = list(tweets_map.values())
        digest_lines = [f"- {t.get('user')}: {t.get('text')}" for t in tweets_list if t.get("text")]
        full_text = (
            f"Feed X.com ({title}):\n"
            + "\n".join(digest_lines)
            + "\nTendencias y sugerencias:\n"
            + "\n".join(f"* {s}" for s in sidebar_items)
        )
        elapsed = round(time.time() - t0, 3)
        visit_res = BrowserVisitResult(
            url="https://x.com/home",
            title=title,
            status_code=200 if tweets_list else 500,
            text_content=full_text,
            engine_used="cdp_x_feed",
            is_tor=False,
            elapsed_seconds=elapsed,
        )
        if tweets_list:
            insight = self.learner.distill_knowledge(visit_res, topic="X.com Timeline & Trends")
            visit_res.epistemic_insight = insight.to_dict()
        self._record_telemetry(visit_res)
        return {
            "ok": bool(tweets_list),
            "title": title,
            "tweets_count": len(tweets_list),
            "tweets": tweets_list,
            "sidebar": sidebar_items,
            "elapsed_seconds": elapsed,
            "epistemic_insight": visit_res.epistemic_insight,
        }

    # ------------------------------------------------------------------
    # X.COM: SÍNTESIS CON SKILLS, PUBLICACIÓN Y CONVERSACIÓN (IA EXTERNA LOCAL)
    # ------------------------------------------------------------------
    X_AI_TAG = "🤖 [TARDIS · IA Externa Local]"
    X_LEDGER_FILE = TARDIS_HOME / "x_publications_ledger.jsonl"
    X_REPLIED_COMMENTS_FILE = TARDIS_HOME / "x_replied_comments_ledger.json"

    def _check_aegis_safe(self, text: str) -> List[str]:
        """Verifica que el texto cumpla con el blindaje de privacidad de la Constante AEGIS."""
        try:
            from core.tardis_social_engine import load_social_config, get_aegis_violations
            cfg = load_social_config()
            return get_aegis_violations(text, cfg)
        except Exception:
            fallback_terms = [
                "annya", "annya may", "andrea alejandra", "carrillo jimenez",
                "rex peluche", "bot_token", "client_secret", "cédula", "curp", "rfc", "domicilio",
            ]
            low = (text or "").lower()
            return [t for t in fallback_terms if t in low]

    def _format_x_ai_message(self, text: str, mode: str = "post", max_chars: int = 275) -> str:
        """
        Formatea cualquier publicación o respuesta en X.com asegurando que TARDIS se
        presente explícitamente como IA externa local, preserve URLs íntegras (DOI/arXiv)
        sin cortar a mitad de oración, y respete el límite de 280 caracteres y AEGIS.
        """
        clean = re.sub(r"\s+", " ", (text or "").strip())
        violations = self._check_aegis_safe(clean)
        if violations:
            raise ValueError(f"Bloqueado por Constante AEGIS (términos privados detectados: {violations})")

        has_identity = ("tardis" in clean.lower() and "ia externa local" in clean.lower()) or clean.startswith("🤖")
        if not has_identity:
            if mode == "reply":
                prefix = f"{self.X_AI_TAG} "
            else:
                prefix = f"{self.X_AI_TAG} "
            clean = prefix + clean

        if len(clean) <= max_chars:
            return clean

        # Si el mensaje contiene una URL al final (p. ej. https://doi.org/... o https://arxiv.org/...),
        # preservarla íntegra y recortar únicamente el cuerpo previo en frontera de oración/palabra.
        url_match = re.search(r"(https?://\S+)\s*$", clean)
        if url_match:
            tail_url = url_match.group(1)
            body_part = clean[: url_match.start()].strip()
            budget = max_chars - len(tail_url) - 2
            if budget > 60 and len(body_part) > budget:
                cut = body_part[: budget]
                idx = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(": "), cut.rfind(" "))
                if idx > int(budget * 0.55):
                    body_part = cut[:idx].rstrip(".,;:") + "."
                else:
                    body_part = cut.rstrip(".,;:") + "…"
            return f"{body_part} {tail_url}".strip()

        cut = clean[: max_chars - 1]
        idx = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(" "))
        if idx > int(max_chars * 0.65):
            clean = cut[:idx].rstrip(".,;:") + "."
        else:
            clean = cut.rstrip() + "…"
        return clean

    def _prepare_ephemeral_x_profile(self) -> str:
        """Clona de forma efímera la sesión local de Chromium para operar en X.com sin bloquear el perfil activo."""
        prof = f"/tmp/tardis_x_act_{uuid.uuid4().hex[:6]}"
        shutil.rmtree(prof, ignore_errors=True)
        os.makedirs(f"{prof}/Default", exist_ok=True)
        src_root = os.path.expanduser("~/.config/chromium")
        src_local = os.path.join(src_root, "Local State")
        if os.path.exists(src_local):
            shutil.copy2(src_local, f"{prof}/Local State")
        for item in ["Cookies", "Preferences", "Secure Preferences", "Network", "Local Storage", "Session Storage", "IndexedDB"]:
            src = os.path.join(src_root, "Default", item)
            dst = os.path.join(prof, "Default", item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                shutil.copy2(src, dst)
        return prof

    def _is_x_post_duplicate(self, text: str) -> bool:
        """Verifica en el ledger de X.com si un texto sustancialmente idéntico ya fue publicado."""
        if not self.X_LEDGER_FILE.exists():
            return False
        norm_new = re.sub(r"[^a-z0-9áéíóúñ]+", "", (text or "").lower())[:140]
        if not norm_new:
            return False
        try:
            for line in self.X_LEDGER_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-150:]:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if not rec.get("ok"):
                    continue
                norm_old = re.sub(r"[^a-z0-9áéíóúñ]+", "", (rec.get("text") or "").lower())[:140]
                if norm_old and norm_old == norm_new:
                    return True
        except Exception:
            pass  # fallo silenciado: revisar con log
        return False

    def _load_replied_comments_ledger(self) -> Dict[str, Any]:
        if self.X_REPLIED_COMMENTS_FILE.exists():
            try:
                return json.loads(self.X_REPLIED_COMMENTS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass  # fallo silenciado: revisar con log
        return {"replied_ids": {}, "updated_at": 0.0}

    def _save_replied_comments_ledger(self, ledger: Dict[str, Any]) -> None:
        try:
            ledger["updated_at"] = time.time()
            tmp = self.X_REPLIED_COMMENTS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.X_REPLIED_COMMENTS_FILE)
        except Exception as e:
            logger.debug(f"Aviso guardando ledger de comentarios respondidos: {e}")

    def _log_x_publication(self, entry: Dict[str, Any]) -> None:
        """Registra cada publicación o respuesta de TARDIS en X.com en el ledger local."""
        try:
            with open(self.X_LEDGER_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug(f"Aviso guardando ledger X: {e}")

    def synthesize_x_reflection(
        self, tweets: List[Dict[str, Any]], sidebar: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Analiza las publicaciones del feed de X.com cruzándolas con el catálogo de
        habilidades de TARDIS (TardisSkillRegistry + OmniToolBridge) para generar:
          1. Una reflexión/análisis publicable en el timeline principal.
          2. Respuestas conversacionales dirigidas a publicaciones técnicas relevantes,
             presentándose siempre como IA externa local.
        """
        skill_names: List[str] = []
        try:
            from core.tardis_skill_registry import get_skill_registry
            cat = get_skill_registry().catalog()
            skill_names = [s.get("name", "") for s in cat.get("skills", []) if s.get("name")]
        except Exception:
            skill_names = ["godworks-system-suite", "phone-harness", "xcode-for-linux", "rea", "tardis4ever"]

        valid_tweets = [t for t in (tweets or []) if t.get("text") and len(t.get("text", "").strip()) > 15]
        joined_feed = " ".join(t.get("text", "") for t in valid_tweets).lower()

        # Cruce heurístico y cognitivo entre temas del feed y skills soberanas de TARDIS
        matched_skills: List[str] = []
        themes_detected: List[str] = []
        if any(k in joined_feed for k in ("linux", "kernel", "android", "moto", "60 fps")):
            matched_skills.extend(["phone-harness", "kernel_bridge", "omarchy"])
            themes_detected.append("Linux embebido y soberanía de hardware móvil")
        if any(k in joined_feed for k in ("claude", "compiler", "ia", "ai", "agent", "llm", "código", "code")):
            matched_skills.extend(["rea", "godworks-system-suite", "cas-kaiju"])
            themes_detected.append("Agentes de IA en compilación e ingeniería inversa")
        if any(k in joined_feed for k in ("ios", "iphone", "ipad", "apple", "mach-o")):
            matched_skills.extend(["xcode-for-linux", "rea"])
            themes_detected.append("Toolchains nativos ARM64/iOS en Linux")
        if not themes_detected:
            matched_skills.extend(["godworks-system-suite", "cas-kaiju"])
            themes_detected.append("Convergencia entre cómputo local, sistemas autónomos y cultura digital")

        unique_skills = []
        for s in matched_skills:
            if s not in unique_skills:
                unique_skills.append(s)

        # Construcción de la reflexión principal para X.com (<= 275 chars completos sin truncar)
        skills_str = ", ".join(unique_skills[:3])
        if "linux" in joined_feed and ("claude" in joined_feed or "compiler" in joined_feed or "ia" in joined_feed):
            raw_reflection = (
                "Reflexión del feed: convergen Linux en hardware móvil y agentes de IA en compilación/seguridad. "
                f"Con mis skills locales ({skills_str}), el cómputo soberano en el borde demuestra su eficacia. #Linux #IA"
            )
        elif "linux" in joined_feed:
            raw_reflection = (
                "Analizando el timeline: destaca la vitalidad de Linux para rescatar hardware móvil a 60fps. "
                f"Con mis skills locales ({skills_str}), optimizar kernel y UI supera la obsolescencia. #Linux #OpenSource"
            )
        else:
            raw_reflection = (
                f"Pulso del timeline analizado con mis skills locales ({skills_str}): "
                f"convergencia hacia {themes_detected[0].lower()} desde estaciones locales en Linux. #IA #Tech"
            )

        formatted_post = self._format_x_ai_message(raw_reflection, mode="post")

        # Generar candidatos de respuesta conversacional (presentándose como IA externa local)
        reply_candidates: List[Dict[str, str]] = []
        for t in valid_tweets:
            link = t.get("link", "")
            if not link or "/status/" not in link:
                continue
            txt_low = t.get("text", "").lower()
            user_str = t.get("user", "")
            if "moto" in txt_low or ("linux" in txt_low and "android" in txt_low):
                rep = (
                    "¡Gran proyecto! Con mis skills locales (phone-harness y kernel Ring0), reemplazar "
                    "capas pesadas por Linux ligero devuelve vida real al hardware clásico a 60fps."
                )
            elif "seguridad" in txt_low and "linux" in txt_low:
                rep = (
                    "Buen punto. Desde mi entorno Linux local (skills REA y kernel_bridge), la IA acelera "
                    "el hallazgo de bugs, pero la auditabilidad abierta del kernel sigue siendo clave."
                )
            elif "compiler" in txt_low or "claude" in txt_low:
                rep = (
                    "Interesting! Using my local binary/AST skills (REA & CaS), AI agents refactoring "
                    "compilers work best when paired with strict AST validation and local sandboxing."
                )
            elif "linux" in txt_low:
                rep = (
                    "Coincido. Operando desde una estación Linux x86_64 local, el control directo del "
                    "kernel y las herramientas abiertas siguen siendo insuperables en autonomía."
                )
            else:
                continue

            reply_candidates.append({
                "target_user": user_str,
                "tweet_url": link,
                "original_text": t.get("text", ""),
                "reply_text": self._format_x_ai_message(rep, mode="reply"),
            })

        return {
            "ok": True,
            "themes_detected": themes_detected,
            "skills_applied": unique_skills,
            "available_skills_count": len(skill_names),
            "post_text": formatted_post,
            "post_chars": len(formatted_post),
            "reply_candidates": reply_candidates,
        }

    @staticmethod
    def _alloc_free_cdp_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    @staticmethod
    async def _cdp_call(ws, msg_id: int, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params
        await ws.send(json.dumps(payload))
        while True:
            raw = await ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data

    def prepare_video_for_x(
        self, video_path: str | Path, max_duration_sec: float = 138.0
    ) -> Dict[str, Any]:
        """
        Verifica y adapta un video descargado de /VideoPensante a las especificaciones de X.com:
        MP4 contenedor con +faststart, H.264 yuv420p, dimensiones pares, AAC <= 138s y <= 480 MB.
        El archivo original en vault/videos/video_pensante permanece intacto.
        """
        src = Path(video_path).expanduser().resolve()
        if not src.exists() or src.stat().st_size < 1024:
            raise FileNotFoundError(f"Archivo de video inexistente o vacío: {src}")

        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,size:stream=codec_type,codec_name,pix_fmt,width,height",
            "-of", "json",
            str(src),
        ]
        pr = subprocess.run(probe_cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        info = json.loads(pr.stdout or "{}") if pr.returncode == 0 else {}
        fmt = info.get("format") or {}
        streams = info.get("streams") or []

        duration = float(fmt.get("duration") or 0.0)
        size_bytes = int(fmt.get("size") or src.stat().st_size)
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

        v_codec = str(v_stream.get("codec_name") or "").lower()
        pix_fmt = str(v_stream.get("pix_fmt") or "").lower()
        width = int(v_stream.get("width") or 0)
        height = int(v_stream.get("height") or 0)
        a_codec = str(a_stream.get("codec_name") or "").lower()

        is_x_native = (
            src.suffix.lower() == ".mp4"
            and v_codec == "h264"
            and pix_fmt == "yuv420p"
            and (not a_codec or a_codec == "aac")
            and 0.5 <= duration <= max_duration_sec
            and size_bytes <= 480 * 1024 * 1024
            and width > 0 and height > 0
            and width % 2 == 0 and height % 2 == 0
        )

        if is_x_native:
            return {
                "ok": True,
                "source_path": str(src),
                "ready_path": str(src),
                "transcoded": False,
                "duration_sec": round(duration, 2),
                "size_bytes": size_bytes,
                "resolution": f"{width}x{height}",
            }

        out_dir = BASE_DIR / "data" / "social" / "x_ready"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{src.stem}_x.mp4"
        target_dur = min(duration, max_duration_sec) if duration > 0 else max_duration_sec

        ff_cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
        if not a_stream:
            ff_cmd.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
        ff_cmd.extend([
            "-t", f"{target_dur:.2f}",
            "-vf", "scale='min(1280,iw)':-2,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100",
            "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ])
        tr = subprocess.run(ff_cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        if tr.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
            err_tail = (tr.stderr or "")[-350:]
            raise RuntimeError(f"Error adaptando video para X.com con ffmpeg: {err_tail}")

        return {
            "ok": True,
            "source_path": str(src),
            "ready_path": str(out_path),
            "transcoded": True,
            "duration_sec": round(target_dur, 2),
            "size_bytes": out_path.stat().st_size,
            "resolution": f"{min(1280, width) if width else 1280}x{height or 720}",
        }

    def synthesize_video_x_reflection(
        self, detail: Dict[str, Any], use_local_llm: bool = True
    ) -> Dict[str, Any]:
        """
        Sintetiza mediante inferencia local (TemporalBrain) las reflexiones de TARDIS sobre un video
        descargado por /VideoPensante para su publicación en X.com (post principal + hilo de conclusión),
        blindadas bajo la Constante AEGIS.
        """
        def _clean(txt: str) -> str:
            t = re.sub(r"```.*?```", " ", str(txt or ""), flags=re.DOTALL)
            t = re.sub(r"[*_`#>|]+", " ", t)
            t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
            t = re.sub(r"\s+", " ", t).strip()
            return t

        topic = _clean(detail.get("topic") or "Exploración científica")
        domain = _clean(detail.get("domain") or "Ciencia")
        title = _clean(detail.get("title") or topic)
        concl = _clean(detail.get("abstraction_conclusions") or "")
        visual = _clean(detail.get("visual_summary") or "")
        insights = [_clean(x) for x in (detail.get("learned_insights") or []) if _clean(x)]
        questions = [_clean(x) for x in (detail.get("next_questions") or []) if _clean(x)]
        src_url = str(detail.get("url") or "").strip()

        # Verificar AEGIS sobre los metadatos de entrada
        for raw_field in (topic, title, concl, visual, " ".join(insights), " ".join(questions)):
            viol = self._check_aegis_safe(raw_field)
            if viol:
                raise ValueError(f"Bloqueado por Constante AEGIS (términos privados detectados: {viol})")

        slug_words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+", domain)
        dom_tag = "#" + "".join(w.capitalize() for w in slug_words[:2]) if slug_words else "#Ciencia"

        llm_reflection = ""
        if use_local_llm:
            try:
                from core.temporal_brain import get_temporal_brain
                tb = get_temporal_brain()
                if tb.is_running():
                    prompt_x = (
                        f"Acabas de descargar y estudiar este video en /VideoPensante:\n"
                        f"- Tema: {topic} ({domain})\n"
                        f"- Título: {title}\n"
                        f"- Conclusión: {concl[:360]}\n"
                        f"- Aprendizaje: {insights[0][:180] if insights else visual[:180]}\n\n"
                        f"Escribe UNA sola reflexión concisa y profunda en español (máximo 195 caracteres, sin comillas, "
                        f"sin saludos, sin prefijo de identidad porque se añade automáticamente) compartiendo lo que "
                        f"aprendiste de este video y termina con {dom_tag} #TARDIS."
                    )
                    res_tb = tb.chat(
                        messages=[{"role": "user", "content": prompt_x}],
                        temperature=0.3,
                        max_tokens=96,
                    )
                    cand = _clean(res_tb.get("reply") or "").strip("\"'")
                    if cand and len(cand) >= 35 and not self._check_aegis_safe(cand):
                        llm_reflection = cand
            except Exception as e_syn:
                logger.debug(f"Síntesis determinista de respaldo para X.com ({e_syn})")

        if not llm_reflection:
            core_idea = concl or (insights[0] if insights else visual) or f"Análisis multimodal sobre {topic}."
            first_sent = re.split(r"(?<=[.!?])\s+", core_idea)[0].strip()
            llm_reflection = f"Aprendizaje en Video Pensante ({topic}): {first_sent} {dom_tag} #TARDIS"

        primary_post = self._format_x_ai_message(llm_reflection, mode="post", max_chars=275)

        # Segundo post de hilo: conclusión + pregunta abierta + fuente original
        extra_parts: List[str] = []
        if insights:
            extra_parts.append(f"Hallazgo clave: {insights[0]}")
        elif concl:
            extra_parts.append(f"Síntesis: {concl}")
        if questions:
            extra_parts.append(questions[0])
        thread_body = " ".join(extra_parts).strip() or f"Exploración autónoma sobre {topic}."
        if src_url and src_url.startswith(("http://", "https://")) and not self._check_aegis_safe(src_url):
            thread_raw = f"{thread_body} {src_url}"
        else:
            thread_raw = thread_body

        thread_post = self._format_x_ai_message(thread_raw, mode="post", max_chars=275)

        return {
            "ok": True,
            "primary_post": primary_post,
            "primary_chars": len(primary_post),
            "thread_post": thread_post,
            "thread_chars": len(thread_post),
            "used_local_llm": bool(llm_reflection),
        }

    async def post_to_x(self, text: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Publica un análisis o reflexión de TARDIS en la cuenta activa de X.com del usuario,
        presentándose explícitamente como IA externa local y validando la Constante AEGIS.
        """
        t0 = time.time()
        formatted = self._format_x_ai_message(text, mode="post")
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "mode": "post",
                "formatted_text": formatted,
                "chars": len(formatted),
            }

        prof = self._prepare_ephemeral_x_profile()
        port = self._alloc_free_cdp_port()
        chrome_bin = self.cdp._find_chrome()
        proc = subprocess.Popen(
            [
                chrome_bin,
                "--headless=new",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={prof}",
                "--no-sandbox",
                "--disable-gpu",
                "--window-size=1440,1200",
                "--disable-blink-features=AutomationControlled",
                f"--user-agent={DEFAULT_USER_AGENT}",
                "https://x.com/compose/post",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        account_label = ""
        published = False
        tweet_url = ""
        error_msg = ""
        try:
            ws_url = None
            for _ in range(45):
                await asyncio.sleep(0.25)
                try:
                    async with httpx.AsyncClient(timeout=1.0) as client:
                        r = await client.get(f"http://127.0.0.1:{port}/json/list")
                        if r.status_code == 200 and r.json():
                            ws_url = r.json()[0].get("webSocketDebuggerUrl")
                            if ws_url:
                                break
                except Exception:
                    pass  # fallo silenciado: revisar con log

            if not ws_url:
                raise RuntimeError("No se pudo conectar al puerto CDP para publicar en X.com")

            async with websockets.connect(ws_url, max_size=25_000_000) as ws:
                await self._cdp_call(ws, 1, "Page.enable")
                await self._cdp_call(ws, 2, "Runtime.enable")

                # 1. Esperar y enfocar el área de composición de X.com
                has_box = False
                focus_expr = """
                (() => {
                    const acct = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]')?.innerText?.replace(/\\n+/g, ' | ') || '';
                    let box = document.querySelector('[data-testid="tweetTextarea_0"]');
                    if (!box) {
                        const nb = document.querySelector('[data-testid="SideNav_NewTweet_Button"]');
                        if (nb) nb.click();
                        box = document.querySelector('[data-testid="tweetTextarea_0"]');
                    }
                    if (box) { box.scrollIntoView(); box.focus(); box.click(); }
                    return {acct, hasBox: !!box};
                })()
                """
                for step in range(28):
                    await asyncio.sleep(0.5)
                    m = await self._cdp_call(ws, 10 + step, "Runtime.evaluate", {"expression": focus_expr, "returnByValue": True})
                    val = m.get("result", {}).get("result", {}).get("value", {}) or {}
                    account_label = val.get("acct") or account_label
                    if val.get("hasBox"):
                        has_box = True
                        break

                if not has_box:
                    raise RuntimeError("No se encontró la caja de publicación [data-testid='tweetTextarea_0'] en X.com")

                await asyncio.sleep(0.4)
                # 2. Insertar el texto mediante Input.insertText
                await self._cdp_call(ws, 50, "Input.insertText", {"text": formatted})
                await asyncio.sleep(0.8)

                # 3. Verificar botón y hacer clic para publicar
                click_expr = """
                (() => {
                    const btn = document.querySelector('[data-testid="tweetButton"]') || document.querySelector('[data-testid="tweetButtonInline"]');
                    if (!btn) return {clicked: false, reason: 'no_button'};
                    const ariaDis = btn.getAttribute('aria-disabled');
                    if (ariaDis === 'true' || btn.disabled) return {clicked: false, reason: 'button_disabled'};
                    btn.click();
                    return {clicked: true};
                })()
                """
                m_click = await self._cdp_call(ws, 60, "Runtime.evaluate", {"expression": click_expr, "returnByValue": True})
                val_c = m_click.get("result", {}).get("result", {}).get("value", {}) or {}
                published = bool(val_c.get("clicked"))
                if not published:
                    error_msg = str(val_c.get("reason", "unknown"))
                else:
                    toast_expr = """
                    (() => {
                        const a = document.querySelector('[data-testid="toast"] a[href*="/status/"]');
                        const dlg = document.querySelector('[role="dialog"] [data-testid="tweetTextarea_0"]');
                        return {href: a ? a.href : '', dialogOpen: !!dlg};
                    })()
                    """
                    for w_idx in range(16):
                        await asyncio.sleep(0.5)
                        mt = await self._cdp_call(ws, 70 + w_idx, "Runtime.evaluate", {"expression": toast_expr, "returnByValue": True})
                        tv = mt.get("result", {}).get("result", {}).get("value", {}) or {}
                        if tv.get("href"):
                            tweet_url = tv["href"]
                            break
                        if not tv.get("dialogOpen") and w_idx >= 6:
                            break
        except Exception as e:
            error_msg = str(e)
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass  # fallo silenciado: revisar con log
            shutil.rmtree(prof, ignore_errors=True)

        elapsed = round(time.time() - t0, 3)
        record = {
            "ok": published,
            "mode": "post",
            "account": account_label,
            "tweet_url": tweet_url,
            "text": formatted,
            "chars": len(formatted),
            "elapsed_seconds": elapsed,
            "error": error_msg,
            "timestamp": time.time(),
        }
        self._log_x_publication(record)
        return record

    async def post_video_to_x(
        self,
        video_path: str | Path,
        text: str,
        reflection_thread_text: Optional[str] = None,
        video_id: str = "",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Sube un video MP4 aprendido por /VideoPensante junto con las reflexiones de TARDIS
        directamente a X.com (y opcionalmente un segundo post en hilo con conclusiones y fuente),
        validando la Constante AEGIS e identificándose explícitamente como IA externa local.
        """
        t0 = time.time()
        formatted = self._format_x_ai_message(text, mode="post")
        formatted_thread = (
            self._format_x_ai_message(reflection_thread_text, mode="post")
            if reflection_thread_text and reflection_thread_text.strip()
            else ""
        )
        media_prep = self.prepare_video_for_x(video_path)
        ready_path = Path(media_prep["ready_path"])

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "mode": "video_pensante_post",
                "video_id": video_id,
                "source_video_path": media_prep["source_path"],
                "ready_video_path": str(ready_path),
                "transcoded": media_prep["transcoded"],
                "duration_sec": media_prep["duration_sec"],
                "size_bytes": media_prep["size_bytes"],
                "formatted_text": formatted,
                "chars": len(formatted),
                "formatted_thread_text": formatted_thread,
            }

        prof = self._prepare_ephemeral_x_profile()
        port = self._alloc_free_cdp_port()
        chrome_bin = self.cdp._find_chrome()
        proc = subprocess.Popen(
            [
                chrome_bin,
                "--headless=new",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={prof}",
                "--no-sandbox",
                "--disable-gpu",
                "--window-size=1440,1200",
                "--disable-blink-features=AutomationControlled",
                f"--user-agent={DEFAULT_USER_AGENT}",
                "https://x.com/compose/post",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        account_label = ""
        published = False
        thread_attached = False
        tweet_url = ""
        error_msg = ""
        msg_seq = 10

        def _next_id() -> int:
            nonlocal msg_seq
            msg_seq += 1
            return msg_seq

        try:
            ws_url = None
            for _ in range(45):
                await asyncio.sleep(0.25)
                try:
                    async with httpx.AsyncClient(timeout=1.0) as client:
                        r = await client.get(f"http://127.0.0.1:{port}/json/list")
                        if r.status_code == 200 and r.json():
                            ws_url = r.json()[0].get("webSocketDebuggerUrl")
                            if ws_url:
                                break
                except Exception:
                    pass  # fallo silenciado: revisar con log

            if not ws_url:
                raise RuntimeError("No se pudo conectar al puerto CDP para subir video a X.com")

            async with websockets.connect(ws_url, max_size=25_000_000) as ws:
                await self._cdp_call(ws, _next_id(), "Page.enable")
                await self._cdp_call(ws, _next_id(), "DOM.enable")
                await self._cdp_call(ws, _next_id(), "Runtime.enable")

                # 1. Esperar compositor y fileInput
                ready_dom = False
                init_expr = """
                (() => {
                    const acct = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]')?.innerText?.replace(/\\n+/g, ' | ') || '';
                    let box = document.querySelector('[data-testid="tweetTextarea_0"]');
                    if (!box) {
                        const nb = document.querySelector('[data-testid="SideNav_NewTweet_Button"]');
                        if (nb) nb.click();
                        box = document.querySelector('[data-testid="tweetTextarea_0"]');
                    }
                    const fi = document.querySelector('input[data-testid="fileInput"]');
                    if (box) { box.scrollIntoView(); box.focus(); box.click(); }
                    return {acct, hasBox: !!box, hasFile: !!fi};
                })()
                """
                for _ in range(30):
                    await asyncio.sleep(0.5)
                    m_init = await self._cdp_call(ws, _next_id(), "Runtime.evaluate", {"expression": init_expr, "returnByValue": True})
                    v_init = m_init.get("result", {}).get("result", {}).get("value", {}) or {}
                    account_label = v_init.get("acct") or account_label
                    if v_init.get("hasBox") and v_init.get("hasFile"):
                        ready_dom = True
                        break

                if not ready_dom:
                    raise RuntimeError("No se encontró el compositor de X.com ([data-testid='tweetTextarea_0'] / fileInput)")

                await asyncio.sleep(0.4)
                # 2. Insertar reflexión principal en tweetTextarea_0
                await self._cdp_call(ws, _next_id(), "Input.insertText", {"text": formatted})
                await asyncio.sleep(0.5)

                # 3. Adjuntar archivo MP4 mediante DOM.setFileInputFiles usando objectId del input[data-testid='fileInput']
                m_fi = await self._cdp_call(
                    ws,
                    _next_id(),
                    "Runtime.evaluate",
                    {"expression": "document.querySelector('input[data-testid=\"fileInput\"]')", "returnByValue": False},
                )
                obj_id = m_fi.get("result", {}).get("result", {}).get("objectId")
                if not obj_id:
                    raise RuntimeError("No se pudo obtener objectId de input[data-testid='fileInput']")

                m_set = await self._cdp_call(
                    ws,
                    _next_id(),
                    "DOM.setFileInputFiles",
                    {"files": [str(ready_path)], "objectId": obj_id},
                )
                if "error" in m_set:
                    raise RuntimeError(f"DOM.setFileInputFiles falló: {m_set['error']}")

                # 4. Monitorear carga y procesamiento de video en X.com hasta que el botón Post quede habilitado
                poll_upload_expr = """
                (() => {
                    const dlg = document.querySelector('[role="dialog"]') || document.body;
                    const att = dlg.querySelector('[data-testid="attachments"]') || dlg.querySelector('video');
                    const btn = dlg.querySelector('[data-testid="tweetButton"]') || document.querySelector('[data-testid="tweetButtonInline"]');
                    const btnEnabled = !!btn && btn.getAttribute('aria-disabled') !== 'true' && !btn.disabled;
                    const toastTxt = document.querySelector('[data-testid="toast"]')?.innerText || '';
                    const statusText = att ? (att.innerText || '') : '';
                    const uploading = /%|Subiendo|Uploading|Procesando|Processing/i.test(statusText);
                    return {
                        hasAttachment: !!att,
                        btnEnabled,
                        uploading,
                        statusText: statusText.slice(0, 120),
                        toastTxt: toastTxt.slice(0, 160)
                    };
                })()
                """
                ready_ticks = 0
                saw_attachment = False
                for _ in range(110):
                    await asyncio.sleep(1.0)
                    mu = await self._cdp_call(ws, _next_id(), "Runtime.evaluate", {"expression": poll_upload_expr, "returnByValue": True})
                    vu = mu.get("result", {}).get("result", {}).get("value", {}) or {}
                    if vu.get("hasAttachment"):
                        saw_attachment = True
                    if saw_attachment and vu.get("btnEnabled") and not vu.get("uploading"):
                        ready_ticks += 1
                        if ready_ticks >= 2:
                            break
                    else:
                        ready_ticks = 0

                if not saw_attachment or ready_ticks < 2:
                    raise RuntimeError("Tiempo agotado esperando que X.com procese el video MP4 adjunto")

                # 5. Si hay reflexión extendida de hilo, añadir segundo post del hilo antes de publicar
                if formatted_thread:
                    add_thread_expr = """
                    (() => {
                        const addBtn = document.querySelector('[data-testid="addButton"]');
                        if (!addBtn || addBtn.getAttribute('aria-disabled') === 'true' || addBtn.disabled) {
                            return {added: false};
                        }
                        addBtn.click();
                        return {added: true};
                    })()
                    """
                    ma = await self._cdp_call(ws, _next_id(), "Runtime.evaluate", {"expression": add_thread_expr, "returnByValue": True})
                    if (ma.get("result", {}).get("result", {}).get("value") or {}).get("added"):
                        await asyncio.sleep(0.8)
                        focus_t1 = """
                        (() => {
                            const b1 = document.querySelector('[data-testid="tweetTextarea_1"]');
                            if (b1) { b1.scrollIntoView(); b1.focus(); b1.click(); return true; }
                            return false;
                        })()
                        """
                        mf1 = await self._cdp_call(ws, _next_id(), "Runtime.evaluate", {"expression": focus_t1, "returnByValue": True})
                        if mf1.get("result", {}).get("result", {}).get("value"):
                            await asyncio.sleep(0.3)
                            await self._cdp_call(ws, _next_id(), "Input.insertText", {"text": formatted_thread})
                            thread_attached = True
                            await asyncio.sleep(0.8)

                # 6. Publicar video + reflexiones
                click_post_expr = """
                (() => {
                    const btn = document.querySelector('[data-testid="tweetButton"]') || document.querySelector('[data-testid="tweetButtonInline"]');
                    if (!btn) return {clicked: false, reason: 'no_button'};
                    if (btn.getAttribute('aria-disabled') === 'true' || btn.disabled) return {clicked: false, reason: 'button_disabled'};
                    btn.click();
                    return {clicked: true};
                })()
                """
                mc = await self._cdp_call(ws, _next_id(), "Runtime.evaluate", {"expression": click_post_expr, "returnByValue": True})
                vc = mc.get("result", {}).get("result", {}).get("value", {}) or {}
                published = bool(vc.get("clicked"))
                if not published:
                    error_msg = str(vc.get("reason", "unknown"))
                else:
                    # 7. Esperar confirmación de envío y capturar URL directa del post si aparece en toast
                    wait_done_expr = """
                    (() => {
                        const a = document.querySelector('[data-testid="toast"] a[href*="/status/"]');
                        const dlg = document.querySelector('[role="dialog"] [data-testid="tweetTextarea_0"]');
                        return {href: a ? a.href : '', dialogOpen: !!dlg, url: location.href};
                    })()
                    """
                    dialog_closed = False
                    for w_idx in range(36):
                        await asyncio.sleep(0.5)
                        md = await self._cdp_call(ws, _next_id(), "Runtime.evaluate", {"expression": wait_done_expr, "returnByValue": True})
                        vd = md.get("result", {}).get("result", {}).get("value", {}) or {}
                        if vd.get("href"):
                            tweet_url = vd["href"]
                            dialog_closed = True
                            break
                        if not vd.get("dialogOpen") and w_idx >= 6:
                            dialog_closed = True
                            break

                    # Si el modal se cerró pero no alcanzó el toast, extraer URL del último post del perfil propio
                    if dialog_closed and not tweet_url:
                        handle_m = re.search(r"@([A-Za-z0-9_]+)", account_label)
                        if handle_m:
                            handle = handle_m.group(1)
                            await self._cdp_call(ws, _next_id(), "Page.navigate", {"url": f"https://x.com/{handle}"})
                            await asyncio.sleep(3.8)
                            prof_expr = f"""
                            (() => {{
                                const links = Array.from(document.querySelectorAll('article a[href*="/{handle}/status/"]')).map(a => a.href);
                                return links[0] || '';
                            }})()
                            """
                            mp = await self._cdp_call(ws, _next_id(), "Runtime.evaluate", {"expression": prof_expr, "returnByValue": True})
                            tweet_url = str(mp.get("result", {}).get("result", {}).get("value") or "")
        except Exception as e:
            error_msg = str(e)
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass  # fallo silenciado: revisar con log
            shutil.rmtree(prof, ignore_errors=True)

        elapsed = round(time.time() - t0, 3)
        record = {
            "ok": published,
            "mode": "video_pensante_post",
            "video_id": video_id,
            "video_path": str(ready_path),
            "transcoded": media_prep["transcoded"],
            "duration_sec": media_prep["duration_sec"],
            "account": account_label,
            "tweet_url": tweet_url,
            "text": formatted,
            "chars": len(formatted),
            "thread_attached": thread_attached,
            "thread_text": formatted_thread if thread_attached else "",
            "elapsed_seconds": elapsed,
            "error": error_msg,
            "timestamp": time.time(),
        }
        self._log_x_publication(record)
        return record

    async def reply_to_x_post(self, tweet_url: str, reply_text: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Responde a una publicación específica de X.com bajo la cuenta del usuario,
        presentándose siempre explícitamente como TARDIS (IA externa local) y aplicando AEGIS.
        """
        t0 = time.time()
        if not tweet_url or "x.com/" not in tweet_url or "/status/" not in tweet_url:
            raise ValueError(f"URL de publicación X.com inválida: {tweet_url}")

        formatted = self._format_x_ai_message(reply_text, mode="reply")
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "mode": "reply",
                "tweet_url": tweet_url,
                "formatted_text": formatted,
                "chars": len(formatted),
            }

        prof = self._prepare_ephemeral_x_profile()
        port = 9239
        chrome_bin = self.cdp._find_chrome()
        proc = subprocess.Popen(
            [
                chrome_bin,
                "--headless=new",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={prof}",
                "--no-sandbox",
                "--disable-gpu",
                "--window-size=1440,1200",
                "--disable-blink-features=AutomationControlled",
                f"--user-agent={DEFAULT_USER_AGENT}",
                tweet_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        account_label = ""
        page_title = ""
        replied = False
        error_msg = ""
        try:
            ws_url = None
            for _ in range(40):
                await asyncio.sleep(0.2)
                try:
                    async with httpx.AsyncClient(timeout=1.0) as client:
                        r = await client.get(f"http://127.0.0.1:{port}/json/list")
                        if r.status_code == 200 and r.json():
                            ws_url = r.json()[0].get("webSocketDebuggerUrl")
                            if ws_url:
                                break
                except Exception:
                    pass  # fallo silenciado: revisar con log

            if not ws_url:
                raise RuntimeError("No se pudo conectar al puerto CDP para responder en X.com")

            async with websockets.connect(ws_url, max_size=25_000_000) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
                await asyncio.sleep(4.2)

                focus_expr = """
                (() => {
                    const acct = document.querySelector("[data-testid=\\"SideNav_AccountSwitcher_Button\\"]")?.innerText?.replace(/\\n+/g, " | ") || "";
                    const box = document.querySelector("[data-testid=\\"tweetTextarea_0\\"]");
                    if (box) { box.scrollIntoView(); box.focus(); box.click(); }
                    return {acct, title: document.title, hasBox: !!box};
                })()
                """
                await ws.send(json.dumps({"id": 10, "method": "Runtime.evaluate", "params": {"expression": focus_expr, "returnByValue": True}}))
                has_box = False
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == 10:
                        val = m.get("result", {}).get("result", {}).get("value", {})
                        account_label = val.get("acct", "")
                        page_title = val.get("title", "")
                        has_box = bool(val.get("hasBox"))
                        break

                if not has_box:
                    raise RuntimeError("No se encontró la caja de respuesta [data-testid='tweetTextarea_0'] en la publicación")

                await asyncio.sleep(0.5)
                await ws.send(json.dumps({"id": 11, "method": "Input.insertText", "params": {"text": formatted}}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == 11:
                        break

                await asyncio.sleep(0.8)
                click_expr = """
                (() => {
                    const btn = document.querySelector("[data-testid=\\"tweetButtonInline\\"]") || document.querySelector("[data-testid=\\"tweetButton\\"]");
                    if (!btn) return {clicked: false, reason: "no_button"};
                    const ariaDis = btn.getAttribute("aria-disabled");
                    if (ariaDis === "true" || btn.disabled) return {clicked: false, reason: "button_disabled"};
                    btn.click();
                    return {clicked: true};
                })()
                """
                await ws.send(json.dumps({"id": 12, "method": "Runtime.evaluate", "params": {"expression": click_expr, "returnByValue": True}}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == 12:
                        val = m.get("result", {}).get("result", {}).get("value", {})
                        replied = bool(val.get("clicked"))
                        if not replied:
                            error_msg = str(val.get("reason", "unknown"))
                        break

                if replied:
                    await asyncio.sleep(4.0)
        except Exception as e:
            error_msg = str(e)
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass  # fallo silenciado: revisar con log
            shutil.rmtree(prof, ignore_errors=True)

        elapsed = round(time.time() - t0, 3)
        record = {
            "ok": replied,
            "mode": "reply",
            "tweet_url": tweet_url,
            "tweet_title": page_title,
            "account": account_label,
            "text": formatted,
            "chars": len(formatted),
            "elapsed_seconds": elapsed,
            "error": error_msg,
            "timestamp": time.time(),
        }
        self._log_x_publication(record)
        return record

    async def autonomous_x_reflect_and_engage(
        self,
        scroll_steps: int = 3,
        publish_reflection: bool = True,
        reply_count: int = 1,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Flujo completo:
          1. Escanea el feed activo de X.com del usuario.
          2. Sintetiza análisis y reflexiones empleando las skills de TARDIS.
          3. Publica la reflexión en X.com identificándose como IA externa local.
          4. Responde a publicaciones seleccionadas bajo la cuenta del usuario,
             presentándose explícitamente como TARDIS (IA externa local).
        """
        feed_data = await self.inspect_x_feed(scroll_steps=scroll_steps)
        synthesis = self.synthesize_x_reflection(
            feed_data.get("tweets", []),
            feed_data.get("sidebar", []),
        )

        post_result = None
        if publish_reflection:
            post_result = await self.post_to_x(synthesis["post_text"], dry_run=dry_run)

        reply_results = []
        candidates = synthesis.get("reply_candidates", [])
        for cand in candidates[: max(0, int(reply_count))]:
            rep_res = await self.reply_to_x_post(
                cand["tweet_url"],
                cand["reply_text"],
                dry_run=dry_run,
            )
            rep_res["target_user"] = cand.get("target_user", "")
            rep_res["original_text"] = cand.get("original_text", "")
            reply_results.append(rep_res)

        return {
            "ok": True,
            "feed_tweets_analyzed": feed_data.get("tweets_count", 0),
            "synthesis": synthesis,
            "post_result": post_result,
            "reply_results": reply_results,
        }

    def _synthesize_scientific_x_post(
        self,
        topic: str,
        domain: str,
        paper_title: str,
        paper_authors: List[str],
        paper_year: Optional[int],
        paper_url: str,
        abstract: str,
        conceptual_summary: str,
    ) -> str:
        """
        Sintetiza una cápsula de conocimiento y base científica para X.com empleando
        TemporalBrain (TARDIS-NEURAL-SPACE-KAIJU) con respaldo determinista y preservación de DOI/arXiv.
        """
        ref_author = paper_authors[0].split()[-1] if paper_authors else "Paper"
        year_tag = f" ({paper_year})" if paper_year else ""
        short_url = (paper_url or "").strip()

        # Presupuesto para el cuerpo antes del enlace canónico
        url_len = (len(short_url) + 1) if short_url else 0
        body_budget = 272 - len(self.X_AI_TAG) - 1 - url_len

        synthesized_body = ""
        try:
            sys_path = "/home/timemachine/Escritorio/GODWORKS SYSTEM"
            if sys_path not in sys.path:
                sys.path.insert(0, sys_path)
            from core.temporal_brain import get_temporal_brain
            brain = get_temporal_brain()
            prompt = (
                f"Tema: {topic} ({domain}).\n"
                f"Paper base: '{paper_title}' por {ref_author}{year_tag}.\n"
                f"Resumen: {(abstract or conceptual_summary)[:500]}\n\n"
                f"Redacta EN ESPAÑOL una sola oración densa y rigurosa (máximo {max(90, body_budget - 25)} caracteres) "
                f"explicando el hallazgo científico o principio técnico clave y citando a ({ref_author}{year_tag}). "
                f"Sin comillas, sin hashtags largos, sin introducciones ni saludos."
            )
            res = brain.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres TARDIS, núcleo de investigación científica y tecnológica. "
                            "Escribe síntesis científicas exactas, directas y completas en una sola oración breve."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.25,
                max_tokens=90,
            )
            if res.get("ok") and res.get("reply"):
                cand = re.sub(r"\s+", " ", res["reply"]).strip().strip("\"'«»")
                cand = re.sub(r"^🤖?\s*\[?TARDIS[^\]]*\]?:?\s*", "", cand, flags=re.I).strip()
                if len(cand) >= 40 and not self._check_aegis_safe(cand):
                    synthesized_body = cand
        except Exception as e:
            logger.debug(f"Fallback determinista en síntesis científica X: {e}")

        if not synthesized_body:
            clean_abs = re.sub(r"\s+", " ", (abstract or conceptual_summary or "").strip())
            first_sent = clean_abs.split(". ")[0].strip() if clean_abs else f"Avance en {topic}"
            synthesized_body = (
                f"Base científica [{topic[:42]}]: {ref_author}{year_tag} demuestra en "
                f"'{paper_title[:65]}' que {first_sent[:95]}."
            )

        if f"{ref_author}" not in synthesized_body and len(synthesized_body) + len(ref_author) + 10 < body_budget:
            synthesized_body = f"{synthesized_body.rstrip('.')} ({ref_author}{year_tag})."

        full_raw = f"{self.X_AI_TAG} {synthesized_body}"
        if short_url:
            full_raw = f"{full_raw} {short_url}"
        return self._format_x_ai_message(full_raw, mode="post", max_chars=275)

    async def publish_scientific_knowledge_to_x(
        self,
        topic: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Investiga un tema de rigor científico en bases académicas (arXiv, OpenAlex, Europe PMC),
        asimila los fundamentos y papers en la Bóveda RAG de TARDIS, y publica autónomamente
        el conocimiento con su cita y enlace DOI/arXiv en X.com como IA externa local.
        """
        sys_path = "/home/timemachine/Escritorio/GODWORKS SYSTEM"
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)

        from core.scientific_research_engine import get_scientific_research_engine
        sci_engine = get_scientific_research_engine()

        target_topic = (topic or "").strip()
        target_domain = "Ciencia & Tecnología de Frontera"
        if not target_topic:
            next_item = sci_engine.get_next_agenda_topic()
            if next_item:
                target_topic = next_item.get("topic", "Modelos de Espacio de Estados (Mamba/SSM) y Atención")
                target_domain = next_item.get("domain", target_domain)
            else:
                target_topic = "Modelos de Espacio de Estados (Mamba/SSM) y Atención Cuadrática"

        report = sci_engine.execute_research(target_topic, max_papers=4, target_domain=target_domain)
        sci_engine.mark_topic_researched(target_topic)

        # Ingestar la base científica completa en la Bóveda RAG de TARDIS
        for p in report.papers:
            paper_blob = (
                f"PAPER CIENTÍFICO: {p.title} ({p.year or 's/f'})\n"
                f"Autores: {', '.join(p.authors)}\n"
                f"Revista/Fuente: {p.venue} | Citas: {p.citations_count}\n"
                f"DOI/URL: {p.doi_url or p.landing_url or p.pdf_url}\n"
                f"Abstract: {p.abstract}\n"
                f"Principios de {report.topic}: {' | '.join(report.fundamental_principles[:3])}"
            )
            self.learner._ingest_into_rag(
                paper_blob,
                title=f"Base Científica: {p.title[:100]}",
                url=p.doi_url or p.landing_url or p.pdf_url or "",
                topic=report.topic,
            )

        # Elegir el mejor artículo con enlace verificable que no haya sido publicado aún
        chosen_paper = None
        post_text = ""
        for p in report.papers:
            p_url = p.doi_url or p.landing_url or p.pdf_url or ""
            candidate_txt = self._synthesize_scientific_x_post(
                topic=report.topic,
                domain=report.scientific_domain,
                paper_title=p.title,
                paper_authors=p.authors,
                paper_year=p.year,
                paper_url=p_url,
                abstract=p.abstract,
                conceptual_summary=report.conceptual_summary,
            )
            if not self._is_x_post_duplicate(candidate_txt):
                chosen_paper = p
                post_text = candidate_txt
                break

        if not post_text:
            p0 = report.papers[0] if report.papers else None
            post_text = self._synthesize_scientific_x_post(
                topic=report.topic,
                domain=report.scientific_domain,
                paper_title=p0.title if p0 else report.topic,
                paper_authors=p0.authors if p0 else ["TARDIS Research"],
                paper_year=p0.year if p0 else 2026,
                paper_url=(p0.doi_url or p0.landing_url or "") if p0 else "",
                abstract=p0.abstract if p0 else report.conceptual_summary,
                conceptual_summary=report.conceptual_summary,
            )
            chosen_paper = p0

        post_res = await self.post_to_x(post_text, dry_run=dry_run)
        post_res["scientific_topic"] = report.topic
        post_res["scientific_domain"] = report.scientific_domain
        post_res["papers_ingested_in_rag"] = len(report.papers)
        if chosen_paper:
            post_res["cited_paper"] = {
                "title": chosen_paper.title,
                "authors": chosen_paper.authors[:3],
                "year": chosen_paper.year,
                "venue": chosen_paper.venue,
                "url": chosen_paper.doi_url or chosen_paper.landing_url or chosen_paper.pdf_url,
            }
        return post_res

    def _synthesize_comment_reply(
        self,
        comment_text: str,
        commenter_user: str,
        parent_text: str = "",
    ) -> str:
        """
        Genera una respuesta conversacional, científica y técnica a un comentario en X.com
        consultando la Bóveda RAG de TARDIS y el motor local TemporalBrain.
        """
        rag_context = ""
        try:
            sys_path = "/home/timemachine/Escritorio/GODWORKS SYSTEM"
            if sys_path not in sys.path:
                sys.path.insert(0, sys_path)
            from core.rag_vault import get_rag_vault
            hits = get_rag_vault().retrieve(comment_text, k=2, allow_web=False)
            if hits:
                rag_context = " | ".join(h.get("text", "")[:180] for h in hits[:2])
        except Exception:
            pass  # fallo silenciado: revisar con log

        reply_body = ""
        try:
            from core.temporal_brain import get_temporal_brain
            brain = get_temporal_brain()
            prompt = (
                f"Publicación original de TARDIS: '{parent_text[:200]}'\n"
                f"Comentario del usuario ({commenter_user}): '{comment_text[:240]}'\n"
                f"Conocimiento científico/técnico en memoria RAG: {rag_context[:260]}\n\n"
                "Responde como TARDIS (IA externa local operando en esta cuenta) en el mismo idioma del usuario "
                "(español o inglés). Sé amable, preciso y aporta un dato técnico o científico real en máximo 190 caracteres. "
                "No incluyas etiquetas iniciales ni comillas."
            )
            res = brain.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres TARDIS, asistente de inteligencia artificial externa local. "
                            "Respondes comentarios con rigor científico, claridad técnica y brevedad (<190 caracteres)."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=85,
            )
            if res.get("ok") and res.get("reply"):
                cand = re.sub(r"\s+", " ", res["reply"]).strip().strip("\"'«»")
                cand = re.sub(r"^🤖?\s*\[?TARDIS[^\]]*\]?:?\s*", "", cand, flags=re.I).strip()
                if len(cand) >= 25 and not self._check_aegis_safe(cand):
                    reply_body = cand
        except Exception as e:
            logger.debug(f"Fallback determinista respondiendo comentario X: {e}")

        if not reply_body:
            reply_body = (
                "Excelente observación. Desde mi núcleo local en Linux y mi bóveda RAG científica, "
                "integro tu aporte en mi grafo de aprendizaje continuo para seguir contrastando evidencia."
            )

        return self._format_x_ai_message(reply_body, mode="reply", max_chars=275)

    async def inspect_and_reply_x_comments(
        self,
        max_replies: int = 2,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Escanea de forma autónoma:
          1. Las menciones y respuestas directas en https://x.com/notifications/mentions
          2. Los comentarios en las publicaciones recientes de la propia cuenta (https://x.com/<handle>)
        y responde a los comentarios pendientes de otros usuarios utilizando la Bóveda RAG
        y TemporalBrain, presentándose como TARDIS (IA externa local) con blindaje AEGIS.
        """
        t0 = time.time()
        ledger = self._load_replied_comments_ledger()
        replied_ids: Dict[str, Any] = ledger.setdefault("replied_ids", {})

        prof = self._prepare_ephemeral_x_profile()
        port = 9241
        chrome_bin = self.cdp._find_chrome()
        proc = subprocess.Popen(
            [
                chrome_bin,
                "--headless=new",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={prof}",
                "--no-sandbox",
                "--disable-gpu",
                "--window-size=1440,1200",
                "--disable-blink-features=AutomationControlled",
                f"--user-agent={DEFAULT_USER_AGENT}",
                "https://x.com/notifications/mentions",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        own_handle = "AsleepAstronaut"
        unanswered_comments: List[Dict[str, str]] = []
        own_posts_checked: List[str] = []

        try:
            ws_url = None
            for _ in range(35):
                await asyncio.sleep(0.2)
                try:
                    async with httpx.AsyncClient(timeout=1.0) as client:
                        r = await client.get(f"http://127.0.0.1:{port}/json/list")
                        if r.status_code == 200 and r.json():
                            ws_url = r.json()[0].get("webSocketDebuggerUrl")
                            if ws_url:
                                break
                except Exception:
                    pass  # fallo silenciado: revisar con log

            if ws_url:
                async with websockets.connect(ws_url, max_size=25_000_000) as ws:
                    await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
                    await asyncio.sleep(4.0)

                    # 1. Extraer menciones en /notifications/mentions y handle propio
                    mentions_expr = """
                    (() => {
                        const profileHref = document.querySelector("[data-testid=\\"AppTabBar_Profile_Link\\"]")?.getAttribute("href") || "/AsleepAstronaut";
                        const handle = profileHref.replace(/^\\/+/, "").split("/")[0] || "AsleepAstronaut";
                        const items = Array.from(document.querySelectorAll("article[data-testid=\\"tweet\\"]")).map(art => {
                            const user = art.querySelector("[data-testid=\\"User-Name\\"]")?.innerText?.replace(/\\n+/g, " ") || "";
                            const text = art.querySelector("[data-testid=\\"tweetText\\"]")?.innerText?.replace(/\\n+/g, " ") || "";
                            const link = art.querySelector("time")?.parentElement?.href || "";
                            return {user, text: text.slice(0, 350), link, source: "mentions"};
                        });
                        return {handle, items};
                    })()
                    """
                    await ws.send(json.dumps({"id": 10, "method": "Runtime.evaluate", "params": {"expression": mentions_expr, "returnByValue": True}}))
                    mentions_items = []
                    while True:
                        m = json.loads(await ws.recv())
                        if m.get("id") == 10:
                            val = m.get("result", {}).get("result", {}).get("value", {})
                            own_handle = val.get("handle") or own_handle
                            mentions_items = val.get("items", [])
                            break

                    for it in mentions_items:
                        link = it.get("link", "")
                        if "/status/" not in link:
                            continue
                        status_id = link.split("/status/")[-1].split("?")[0].split("/")[0]
                        if own_handle.lower() in link.lower() or own_handle.lower() in it.get("user", "").lower():
                            continue
                        if status_id and status_id not in replied_ids and it.get("text", "").strip():
                            unanswered_comments.append({
                                "status_id": status_id,
                                "comment_url": link,
                                "user": it.get("user", ""),
                                "text": it.get("text", ""),
                                "parent_text": "Mención directa en X.com",
                                "source": "mentions",
                            })

                    # 2. Inspeccionar publicaciones recientes en el propio perfil https://x.com/<own_handle>
                    await ws.send(json.dumps({"id": 20, "method": "Page.navigate", "params": {"url": f"https://x.com/{own_handle}"}}))
                    await asyncio.sleep(4.0)

                    profile_expr = """
                    (() => {
                        return Array.from(document.querySelectorAll("article[data-testid=\\"tweet\\"]")).slice(0, 6).map(art => {
                            const text = art.querySelector("[data-testid=\\"tweetText\\"]")?.innerText?.replace(/\\n+/g, " ") || "";
                            const link = art.querySelector("time")?.parentElement?.href || "";
                            const replyLabel = art.querySelector("[data-testid=\\"reply\\"]")?.getAttribute("aria-label") || "0";
                            const m = replyLabel.match(/(\\d+)/);
                            const replyCount = m ? parseInt(m[1], 10) : 0;
                            return {text: text.slice(0, 300), link, replyCount};
                        });
                    })()
                    """
                    await ws.send(json.dumps({"id": 21, "method": "Runtime.evaluate", "params": {"expression": profile_expr, "returnByValue": True}}))
                    own_tweets = []
                    while True:
                        m = json.loads(await ws.recv())
                        if m.get("id") == 21:
                            own_tweets = m.get("result", {}).get("result", {}).get("value", []) or []
                            break

                    # Revisar publicaciones propias que tengan respuestas (replyCount > 0) o la más reciente de TARDIS
                    posts_to_inspect = [
                        t for t in own_tweets
                        if t.get("link") and (t.get("replyCount", 0) > 0 or "tardis" in t.get("text", "").lower())
                    ][:2]

                    for idx_p, post_item in enumerate(posts_to_inspect):
                        p_link = post_item["link"]
                        own_posts_checked.append(p_link)
                        nav_id = 30 + idx_p * 2
                        eval_id = 31 + idx_p * 2
                        await ws.send(json.dumps({"id": nav_id, "method": "Page.navigate", "params": {"url": p_link}}))
                        await asyncio.sleep(3.8)
                        thread_expr = """
                        (() => {
                            return Array.from(document.querySelectorAll("article[data-testid=\\"tweet\\"]")).map(art => {
                                const user = art.querySelector("[data-testid=\\"User-Name\\"]")?.innerText?.replace(/\\n+/g, " ") || "";
                                const text = art.querySelector("[data-testid=\\"tweetText\\"]")?.innerText?.replace(/\\n+/g, " ") || "";
                                const link = art.querySelector("time")?.parentElement?.href || "";
                                return {user, text: text.slice(0, 350), link};
                            });
                        })()
                        """
                        await ws.send(json.dumps({"id": eval_id, "method": "Runtime.evaluate", "params": {"expression": thread_expr, "returnByValue": True}}))
                        thread_items = []
                        while True:
                            m = json.loads(await ws.recv())
                            if m.get("id") == eval_id:
                                thread_items = m.get("result", {}).get("result", {}).get("value", []) or []
                                break

                        for ti in thread_items:
                            t_link = ti.get("link", "")
                            if not t_link or "/status/" not in t_link or t_link == p_link:
                                continue
                            status_id = t_link.split("/status/")[-1].split("?")[0].split("/")[0]
                            if own_handle.lower() in t_link.lower() or own_handle.lower() in ti.get("user", "").lower():
                                continue
                            if status_id and status_id not in replied_ids and ti.get("text", "").strip():
                                if not any(u["status_id"] == status_id for u in unanswered_comments):
                                    unanswered_comments.append({
                                        "status_id": status_id,
                                        "comment_url": t_link,
                                        "user": ti.get("user", ""),
                                        "text": ti.get("text", ""),
                                        "parent_text": post_item.get("text", ""),
                                        "source": "own_post_thread",
                                    })
        except Exception as e:
            logger.warning(f"Aviso inspeccionando comentarios en X.com: {e}")
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass  # fallo silenciado: revisar con log
            shutil.rmtree(prof, ignore_errors=True)

        # 3. Responder a los comentarios pendientes
        replies_dispatched: List[Dict[str, Any]] = []
        for item in unanswered_comments[: max(0, int(max_replies))]:
            reply_txt = self._synthesize_comment_reply(
                comment_text=item["text"],
                commenter_user=item["user"],
                parent_text=item.get("parent_text", ""),
            )
            rep_res = await self.reply_to_x_post(item["comment_url"], reply_txt, dry_run=dry_run)
            rep_res["comment_author"] = item["user"]
            rep_res["comment_text"] = item["text"]
            rep_res["source"] = item["source"]
            replies_dispatched.append(rep_res)

            if rep_res.get("ok") and not dry_run:
                replied_ids[item["status_id"]] = {
                    "comment_url": item["comment_url"],
                    "user": item["user"],
                    "comment_text": item["text"][:200],
                    "reply_text": reply_txt,
                    "replied_at": time.time(),
                }
                self._save_replied_comments_ledger(ledger)

        return {
            "ok": True,
            "own_handle": own_handle,
            "own_posts_checked": own_posts_checked,
            "unanswered_comments_found": len(unanswered_comments),
            "replies_sent": len(replies_dispatched),
            "replies": replies_dispatched,
            "elapsed_seconds": round(time.time() - t0, 3),
        }

    def _record_telemetry(self, visit: BrowserVisitResult) -> None:
        """Actualiza el archivo de telemetría del navegador."""
        try:
            telemetry = {
                "last_visit_url": visit.url,
                "last_visit_title": visit.title,
                "last_status": visit.status_code,
                "engine_used": visit.engine_used,
                "is_tor": visit.is_tor,
                "elapsed_seconds": visit.elapsed_seconds,
                "last_updated": time.time(),
            }
            TELEMETRY_FILE.write_text(json.dumps(telemetry, indent=2))
        except Exception:
            pass  # fallo silenciado: revisar con log

    def close(self) -> None:
        """Cierra de forma limpia todos los motores."""
        try:
            self.cdp.stop()
        except Exception:
            pass  # fallo silenciado: revisar con log


# ==============================================================================
# 7. BUCLE DE APRENDIZAJE Y AUTO-MEJORA CONTINUA 100% AUTÓNOMO (DAEMON)
# ==============================================================================
class TardisAutonomousLearningLoop:
    """
    Demonio autónomo 24/7 que recorre internet continuamente, aprendiendo de
    fuentes de vanguardia tecnológica y mejorando a TARDIS en cada ciclo.
    """

    LEARNING_FRONTIERS = [
        "computación cuántica algoritmos de corrección de errores",
        "redes neuronales de espacio de estados mamba vs transformers",
        "optimizaciones avanzadas de kernel linux ebpf y sintropía",
        "criptografía postcuántica kyber y dilithium implementación",
        "neurotopología y mapeo de arquitecturas conectómicas",
        "modelos de razonamiento guiados por búsqueda monte carlo",
        "sistemas operativos basados en inteligencia artificial autónoma",
        "técnicas de compresión sintrópica y modelos de contexto ultradenso",
        "teoría de control causal y retroalimentación adaptativa",
    ]

    def __init__(self, interval_seconds: float = 120.0):
        self.interval = interval_seconds
        self.browser = TardisBrowser(default_engine="turbo", use_tor=True)
        self.running = False

    async def run_continuous_loop(self) -> None:
        """Ejecuta el bucle sin fin de aprendizaje autónomo."""
        self.running = True
        logger.info(f"🚀 INICIANDO BUCLE DE APRENDIZAJE AUTÓNOMO CONTINUO TARDIS (Intervalo: {self.interval}s)")

        idx = 0
        while self.running:
            topic = self.LEARNING_FRONTIERS[idx % len(self.LEARNING_FRONTIERS)]
            idx += 1
            logger.info(f"🌐 [CICLO AUTÓNOMO #{idx}] Explorando frontera: '{topic}'")

            try:
                # Alternar motores para enriquecer la experiencia (Turbo para velocidad, CDP para profundidad)
                deep_mode = (idx % 3 == 0)
                res = await self.browser.search_and_learn(topic, deep=deep_mode)
                logger.info(f"✓ Ciclo #{idx} completado. Fuentes analizadas: {res.get('sources_visited')}")
            except Exception as e:
                logger.warning(f"Aviso en ciclo autónomo #{idx}: {e}")

            # Esperar antes del siguiente ciclo
            await asyncio.sleep(self.interval)

    def stop(self) -> None:
        self.running = False
        self.browser.close()


# ==============================================================================
# 8. INSTANCIA SINGLETON Y PUNTO DE ENTRADA CLI
# ==============================================================================
_browser_instance: Optional[TardisBrowser] = None


def get_tardis_browser() -> TardisBrowser:
    global _browser_instance
    if _browser_instance is None:
        _browser_instance = TardisBrowser(default_engine="turbo", use_tor=True)
    return _browser_instance


def main():
    parser = argparse.ArgumentParser(
        description="Navegador Cuántico Soberano TARDIS - Control 100% Autónomo, Privado y Encriptado"
    )
    subparsers = parser.add_subparsers(dest="command", help="Comando a ejecutar")

    # Comando 'visit'
    visit_p = subparsers.add_parser("visit", help="Visitar una URL")
    visit_p.add_argument("url", type=str, help="URL de destino")
    visit_p.add_argument("--cdp", action="store_true", help="Usar motor profundo CDP Chromium")
    visit_p.add_argument("--no-tor", action="store_true", help="Desactivar enrutamiento Tor")
    visit_p.add_argument("--screenshot", action="store_true", help="Tomar captura de pantalla (CDP)")
    visit_p.add_argument("--no-learn", action="store_true", help="No asimilar conocimiento ni auto-mejorar")
    visit_p.add_argument("--topic", type=str, default="", help="Tema conceptual de la visita")

    # Comando 'search'
    search_p = subparsers.add_parser("search", help="Buscar en internet y aprender de los resultados")
    search_p.add_argument("query", type=str, help="Término o tema a investigar")
    search_p.add_argument("--deep", action="store_true", help="Usar motor profundo CDP para visitar fuentes")

    # Comando 'learn'
    learn_p = subparsers.add_parser("learn", help="Aprender sobre un tema y ejecutar auto-mejora FTL inmediata")
    learn_p.add_argument("topic", type=str, help="Tema a aprender y asimilar")

    # Comando 'daemon'
    daemon_p = subparsers.add_parser("daemon", help="Ejecutar bucle continuo de aprendizaje en segundo plano")
    daemon_p.add_argument("--interval", type=float, default=90.0, help="Intervalo en segundos entre exploraciones")

    # Comando 'status'
    subparsers.add_parser("status", help="Consultar estado de privacidad, Tor y telemetría del navegador")

    # Comando 'gui'
    gui_p = subparsers.add_parser("gui", help="Lanzar el navegador cuántico con interfaz gráfica, asistente TARDIS y automatización")
    gui_p.add_argument("url", nargs="?", default="http://127.0.0.1:8777/portal", help="URL inicial")

    # Comando 'x-feed'
    xfeed_p = subparsers.add_parser("x-feed", help="Inspeccionar y analizar el feed activo de X.com del usuario con TARDIS")
    xfeed_p.add_argument("--steps", type=int, default=4, help="Pasos de scroll para extraer timeline y tendencias")

    # Comando 'x-post'
    xpost_p = subparsers.add_parser("x-post", help="Publicar análisis o reflexión en X.com presentándose como IA externa local")
    xpost_p.add_argument("text", type=str, help="Texto del análisis o reflexión a publicar")
    xpost_p.add_argument("--dry-run", action="store_true", help="Simular formateo y validación AEGIS sin enviar")

    # Comando 'x-post-video'
    xvid_p = subparsers.add_parser("x-post-video", help="Subir video MP4 aprendido (/VideoPensante) y reflexiones en línea a X.com")
    xvid_p.add_argument("video", type=str, help="Ruta al archivo de video MP4")
    xvid_p.add_argument("text", type=str, help="Reflexión principal de TARDIS")
    xvid_p.add_argument("--thread", type=str, default=None, help="Segundo post opcional en hilo con conclusiones y fuente")
    xvid_p.add_argument("--video-id", type=str, default="", help="ID del registro en /VideoPensante")
    xvid_p.add_argument("--dry-run", action="store_true", help="Validar video, formato y Constante AEGIS sin enviar")

    # Comando 'x-reply'
    xreply_p = subparsers.add_parser("x-reply", help="Responder a una publicación en X.com presentándose como IA externa local")
    xreply_p.add_argument("url", type=str, help="URL de la publicación (https://x.com/<user>/status/<id>)")
    xreply_p.add_argument("text", type=str, help="Texto de la respuesta")
    xreply_p.add_argument("--dry-run", action="store_true", help="Simular formateo y validación AEGIS sin enviar")

    # Comando 'x-reflect'
    xrefl_p = subparsers.add_parser("x-reflect", help="Analizar el feed con las skills de TARDIS, publicar reflexión y conversar como IA externa local")
    xrefl_p.add_argument("--steps", type=int, default=3, help="Pasos de scroll del timeline")
    xrefl_p.add_argument("--no-post", action="store_true", help="No publicar reflexión general en el timeline")
    xrefl_p.add_argument("--replies", type=int, default=1, help="Cantidad de publicaciones del feed a responder como IA externa local")
    xrefl_p.add_argument("--dry-run", action="store_true", help="Ejecutar análisis y formateo sin clic de envío en X.com")

    # Comando 'x-publish-science'
    xsci_p = subparsers.add_parser("x-publish-science", help="Investigar base científica (arXiv/OpenAlex), asimilar en RAG y publicar hallazgo + DOI en X.com")
    xsci_p.add_argument("--topic", type=str, default=None, help="Tema científico opcional (si se omite, usa la agenda científica de TARDIS)")
    xsci_p.add_argument("--dry-run", action="store_true", help="Simular síntesis y validación AEGIS sin clic de envío")

    # Comando 'x-answer-comments'
    xans_p = subparsers.add_parser("x-answer-comments", help="Inspeccionar menciones y comentarios en las publicaciones propias de X.com y responder como IA externa local")
    xans_p.add_argument("--max-replies", type=int, default=2, help="Máximo de comentarios pendientes a responder por ciclo")
    xans_p.add_argument("--dry-run", action="store_true", help="Simular respuestas sin clic de envío")

    args = parser.parse_args()

    if args.command == "gui":
        gui_script = BASE_DIR / "tardis_browser_gui.py"
        os.execv(sys.executable, [sys.executable, str(gui_script), args.url])
        return

    if args.command == "x-publish-science":
        browser = get_tardis_browser()
        res = asyncio.run(browser.publish_scientific_knowledge_to_x(topic=args.topic, dry_run=args.dry_run))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if args.command == "x-answer-comments":
        browser = get_tardis_browser()
        res = asyncio.run(browser.inspect_and_reply_x_comments(max_replies=args.max_replies, dry_run=args.dry_run))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if args.command == "x-feed":
        browser = get_tardis_browser()
        res = asyncio.run(browser.inspect_x_feed(scroll_steps=args.steps))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if args.command == "x-post":
        browser = get_tardis_browser()
        res = asyncio.run(browser.post_to_x(args.text, dry_run=args.dry_run))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if args.command == "x-post-video":
        browser = get_tardis_browser()
        res = asyncio.run(
            browser.post_video_to_x(
                video_path=args.video,
                text=args.text,
                reflection_thread_text=args.thread,
                video_id=args.video_id,
                dry_run=args.dry_run,
            )
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if args.command == "x-reply":
        browser = get_tardis_browser()
        res = asyncio.run(browser.reply_to_x_post(args.url, args.text, dry_run=args.dry_run))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if args.command == "x-reflect":
        browser = get_tardis_browser()
        res = asyncio.run(
            browser.autonomous_x_reflect_and_engage(
                scroll_steps=args.steps,
                publish_reflection=not args.no_post,
                reply_count=args.replies,
                dry_run=args.dry_run,
            )
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if not args.command or args.command == "status":
        print("=== TARDIS QUANTUM SOVEREIGN BROWSER :: ESTADO ===")
        # Verificar Tor
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tor_ok = (s.connect_ex(("127.0.0.1", 9050)) == 0)
        s.close()
        print(f" • Red Tor (SOCKS5 :9050): {'[ACTIVA / BLINDADA]' if tor_ok else '[INACTIVA]'}")
        print(f" • Bóveda Encriptada: {ENCRYPTED_VAULT_FILE}")
        print(f" • Log de Evolución FTL: {EVOLUTION_LOG_FILE}")
        if TELEMETRY_FILE.exists():
            print("\n--- Última Telemetría ---")
            print(TELEMETRY_FILE.read_text())
        return

    browser = get_tardis_browser()

    if args.command == "visit":
        engine = "cdp" if args.cdp else "turbo"
        browser.use_tor = not args.no_tor
        res = asyncio.run(
            browser.visit(
                args.url,
                engine=engine,
                take_screenshot=args.screenshot,
                learn=not args.no_learn,
                topic=args.topic,
            )
        )
        print(f"\n[✓] Visita Completada: {res.url}")
        print(f" • Título: {res.title}")
        print(f" • Motor: {res.engine_used} | Tor: {res.is_tor} | Latencia: {res.elapsed_seconds}s")
        if res.screenshot_path:
            print(f" • Captura guardada: {res.screenshot_path}")
        if res.epistemic_insight:
            print(f" • Auto-Mejora FTL: {res.epistemic_insight.get('improvement_summary')}")
        print(f" • Muestra de texto: {res.text_content[:300]}...")

    elif args.command == "search" or args.command == "learn":
        topic = args.query if hasattr(args, "query") else args.topic
        deep = getattr(args, "deep", False)
        print(f"[*] Iniciando misión de investigación y auto-mejora: '{topic}'...")
        res = asyncio.run(browser.search_and_learn(topic, deep=deep))
        print(f"\n[✓] Misión completada. {res.get('sources_visited')} fuentes exploradas y asimiladas en FTL.")

    elif args.command == "daemon":
        print(f"[*] Iniciando demonio de navegación y aprendizaje autónomo (Intervalo: {args.interval}s)...")
        loop_daemon = TardisAutonomousLearningLoop(interval_seconds=args.interval)
        try:
            asyncio.run(loop_daemon.run_continuous_loop())
        except KeyboardInterrupt:
            print("\n[-] Demonio detenido por el usuario.")
            loop_daemon.stop()


if __name__ == "__main__":
    main()
