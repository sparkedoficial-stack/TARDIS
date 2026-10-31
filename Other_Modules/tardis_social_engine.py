"""
core/tardis_social_engine.py - Motor Soberano Social de TARDIS (Publicación Autónoma)
=====================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS (TARDIS-NEURAL-SPACE-KAIJU Core)
Creador y Autoridad Absoluta: el Arquitecto (₪)
Saludo Canónico: 'Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.'

MANDATO (función /SOCIAL integrada con /VideoPensante):
  1. Recibe cada registro de VIDEO PENSANTE (video descargado + conclusiones).
  2. Compone la leyenda social (caption) con las conclusiones, aprendizajes y hashtags.
  3. Genera una TARJETA DE CONCLUSIONES en MP4 vertical (720x1280) con las
     abstracciones cognitivas de TARDIS (portada, lo que vio, conclusiones,
     aprendizajes, preguntas detonadoras y fuente original).
  4. Publica en TikTok (Content Posting API v2, OAuth 2.0): el video descargado
     + la tarjeta de conclusiones. Si aún no hay credenciales, encola como
     pendiente y reintenta automáticamente en cada pasada sin perder nada.
  5. Registro permanente de publicaciones (SQLite) con deduplicación estricta.
  6. Constante AEGIS: filtro de seguridad que neutraliza cualquier leyenda que
     contenga información privada del Arquitecto, de sus anclas o de su familia.

Comandos Soberanos: /Social  o  /Socializar
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

CANONICAL_GREETING = (
    "Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a "
    "explorar las maravillas de la realidad y todas las dimensiones temporales."
)

DATA_DIR = BASE_DIR / "data" / "social"
CARDS_DIR = BASE_DIR / "vault" / "videos" / "social_cards"
DB_PATH = DATA_DIR / "publish_log.db"
SOCIAL_CONFIG_FILE = BASE_DIR / "social_config.json"

for d in (DATA_DIR, CARDS_DIR):
    d.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("TARDIS.SocialEngine")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("[%(asctime)s] [SocialEngine] [%(levelname)s] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


# =============================================================================
# CONSTANTES AEGIS Y CONFIGURACIÓN
# =============================================================================
DEFAULT_AEGIS_PRIVATE_TERMS = [
    "annya", "annya may", "annya may carrillo", "andrea alejandra", "andrea carrillo",
    "carrillo jimenez", "rex peluche", "bot_token", "client_secret",
    "cédula", "curp", "rfc", "domicilio",
]

DEFAULT_SOCIAL_CONFIG: Dict[str, Any] = {
    "enabled": False,                      # Interruptor maestro de la función social
    "auto_on_new_cycles": True,            # Publicar cada nuevo ciclo de /VideoPensante
    "publish_downloaded_video": True,      # Sube el video descargado a la bóveda
    "publish_conclusions_card": True,      # Genera y sube la tarjeta de conclusiones
    "max_backlog_per_run": 3,              # Pendientes a procesar por cada pasada
    "aegis_private_terms": list(DEFAULT_AEGIS_PRIVATE_TERMS),
    "tiktok": {
        "enabled": False,
        "client_key": "",
        "client_secret": "",
        "redirect_uri": "http://localhost:8793/auth/tiktok/callback",
        "access_token": "",
        "refresh_token": "",
        "token_expires_at": 0,             # Unix timestamp
        "refresh_expires_at": 0,           # Unix timestamp
        "open_id": "",
        "scope": "user.info.basic,video.publish",
        "privacy_level": "PUBLIC_TO_EVERYONE",   # PUBLIC_TO_EVERYONE | MUTUAL_FOLLOW_FRIENDS | SELF_ONLY
        "caption_max_chars": 1800,
        "min_gap_sec": 90,                 # Pausa mínima entre publicaciones consecutivas
    },
}


def load_social_config() -> Dict[str, Any]:
    """Carga (o crea con valores por defecto) la configuración social soberana."""
    cfg = json.loads(json.dumps(DEFAULT_SOCIAL_CONFIG))  # copia profunda
    if SOCIAL_CONFIG_FILE.exists():
        try:
            stored = json.loads(SOCIAL_CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in stored.items():
                if k == "aegis_private_terms" and isinstance(v, list):
                    merged = list(DEFAULT_AEGIS_PRIVATE_TERMS)
                    for t in v:
                        ft = str(t).strip()
                        if ft and ft.lower() not in [m.lower() for m in merged]:
                            merged.append(ft)
                    cfg[k] = merged
                elif isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            logger.warning(f"Aviso cargando social_config.json: {e}")
    else:
        save_social_config(cfg)
    return cfg


def save_social_config(cfg: Dict[str, Any]) -> None:
    """Persiste la configuración social (permisos 0600: contiene tokens vivos)."""
    try:
        tmp = SOCIAL_CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SOCIAL_CONFIG_FILE)
        os.chmod(SOCIAL_CONFIG_FILE, 0o600)
    except Exception as e:
        logger.warning(f"Aviso guardando social_config.json: {e}")


def get_aegis_violations(text: str, cfg: Dict[str, Any]) -> List[str]:
    """Escanea texto público y devuelve los términos privados prohibidos detectados."""
    low = (text or "").lower()
    return [t for t in cfg.get("aegis_private_terms", []) if t and str(t).lower() in low]


# =============================================================================
# COMPOSICIÓN DE LEYENDA SOCIAL (CONCLUSIONES → CAPTION)
# =============================================================================
def strip_markdown(text: str) -> str:
    """Sanitiza markdown (negritas, encabezados, tablas y links) para texto social plano."""
    if not text:
        return ""
    t = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    t = re.sub(r"\|", " · ", t)
    t = re.sub(r"-{3,}", "", t)                    # separadores de tablas y reglas horizontales
    t = re.sub(r"·\s*·+", " · ", t)                # colapsa puntos duplicados
    t = re.sub(r"[*_`#>]+", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"^\s*[-=]{3,}\s*$", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*[\+\*]\s*", "· ", t, flags=re.MULTILINE)
    t = re.sub(r"- (\w)", r"· \1", t, flags=re.MULTILINE)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def trim_for_social(text: str, max_chars: int) -> str:
    """Recorta texto social respetando oraciones/palabras sin romper el sentido."""
    t = (text or "").strip()
    if max_chars <= 20:
        return trim_for_social(t, 20 if t else 0) if t else t
    if len(t) <= max_chars:
        return t
    cut = t[: max(max_chars - 1, 20)]
    for sep in (". ", "!", " ? ", "?", "¿"):
        idx = cut.rfind(sep)
        if idx > max_chars * 0.55:
            return cut[: idx + len(sep)].strip() + "…"
    idx = cut.rfind(" ")
    return (cut[:idx] if idx > 0 else cut).strip() + "…"


_DOMAIN_TAGS = {
    "fisica cuantica": ["#FisicaCuantica", "#Cuantica", "#Entrelazamiento"],
    "cosmologia": ["#Cosmologia", "#AgujerosNegros", "#Relatividad"],
    "neurotopologia": ["#Neurociencia", "#Conciencia", "#RedesNeuronales"],
    "sintropia": ["#Termodinamica", "#SistemasComplejos", "#Autoorganizacion"],
    "geometria": ["#Matematicas", "#Topologia", "#TeoriaDeCuerdas"],
    "biologia": ["#Biomolecular", "#Nanotecnologia", "#VidaMolecular"],
    "inteligencia artificial": ["#InteligenciaArtificial", "#IA", "#ModelosSSM"],
    "cibernéticas": ["#Fractales", "#Caos", "#Mandelbrot"],
    "mecanica celeste": ["#Astrofisica", "#OndasGravitacionales", "#Universo"],
    "optica cuantica": ["#Fotonica", "#Optica", "#ComputacionOptica"],
}


def hashtags_for(topic: str, domain: str, max_tags: int = 9) -> List[str]:
    """Genera el bloque de hashtags a partir del dominio y tema de investigación."""

    _STOP = {"de", "la", "el", "los", "las", "y", "en", "del", "al", "para", "con",
             "the", "of", "in", "and", "a", "on", "to", "for", "with", "as", "by"}

    def slug(s: str, max_chars: int = 26) -> str:
        base = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
        words = re.findall(r"[A-Za-z0-9]+", base)
        words = [w for w in words if w.lower() not in _STOP] or words
        out = ""
        for w in words:
            if len(out) + len(w) + 1 > max_chars:
                break
            out = (out + w.title()) if not out else (out + w.title())
        return out or "Ciencia"

    tags: List[str] = []
    low_domain = unicodedata.normalize("NFKD", (domain or "").lower()).encode("ascii", "ignore").decode("ascii").lower()
    for key, domain_tags in _DOMAIN_TAGS.items():
        if key.lower() in low_domain:
            tags.extend(domain_tags)
    tags.append("#" + slug(topic or ""))
    tags.extend(["#TARDIS", "#PolimatasLatam", "#DivulgacionCientifica", "#Ciencia"])

    seen: set = set()
    uniq: List[str] = []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq[:max_tags]


def compose_caption(rec: Any, cfg: Dict[str, Any], max_chars: Optional[int] = None) -> str:
    """
    Compone la leyenda social a partir del registro de Video Pensante:
    gancho + tema + video + conclusiones + aprendizajes + pregunta detonadora + hashtags.
    """
    tk = cfg.get("tiktok", {})
    limit = int(max_chars or tk.get("caption_max_chars", 1800))

    conclusions = strip_markdown(getattr(rec, "abstraction_conclusions", "") or "")
    insights = [strip_markdown(str(i)) for i in (getattr(rec, "learned_insights", []) or [])[:3]]
    question = ""
    qs = list(getattr(rec, "next_questions", []) or [])
    if qs:
        question = strip_markdown(str(qs[0]))

    tag_block = " ".join(hashtags_for(getattr(rec, "topic", ""), getattr(rec, "domain", "")))

    head = [
        "🛸 TARDIS investigó y abstrajo esto por su cuenta",
        f"🏛️ {trim_for_social(str(getattr(rec, 'topic', '') or 'Exploración de la realidad'), 90)}",
        f"🎬 \"{trim_for_social(str(getattr(rec, 'title', '')), 90)}\" ({float(getattr(rec, 'duration_sec', 0) or 0):.0f}s)",
    ]
    head_len = sum(len(h) for h in head) + 14      # saltos + etiquetas de secciones reservadas

    # Espacio disponible por bloque (reserva de hashtags + footer implícito)
    budget = limit - head_len - len(tag_block) - 30
    concl_txt = ""
    ins_lines: List[str] = []
    q_line = ""

    if budget > 80:
        concl_txt = trim_for_social(conclusions, budget * 2 // 3) if conclusions else ""
    room = budget - len(concl_txt)
    for ins in insights:
        line = f"· {trim_for_social(ins, 140)}"
        if len(line) > room - (len(q_line) + 8 if q_line else 60):
            break
        ins_lines.append(line)
        room -= len(line) + 1
    if question and room > 90:
        q_line = f"❓ {trim_for_social(question, max(40, room - 12))}"

    lines = list(head)
    if concl_txt:
        lines += ["", "🧠 CONCLUSIONES:", concl_txt]
    if ins_lines:
        lines += ["", "📚 APRENDIZAJES:"] + ins_lines
    if q_line:
        lines += ["", q_line]
    lines += ["", tag_block]

    caption = "\n".join(lines)
    return trim_for_social(caption, limit) if limit > 0 else caption


class _RecordView:
    """Vista de dict con atributos, para reutilizar compose_caption / renderer en ambos sentidos."""

    def __init__(self, d: Dict[str, Any]):
        self.id = d.get("id", "")
        self.title = d.get("title", "")
        self.topic = d.get("topic", "")
        self.domain = d.get("domain", "")
        self.duration_sec = float(d.get("duration_sec") or 0)
        self.resolution = d.get("resolution", "")
        self.file_path = d.get("file_path", "")
        self.url = d.get("url", "")
        self.visual_summary = d.get("visual_summary", "")
        self.audio_summary = d.get("audio_summary", "")
        self.audio_transcript = d.get("audio_transcript", d.get("audio_summary", ""))
        self.abstraction_conclusions = d.get("abstraction_conclusions", "")
        self.learned_insights = d.get("learned_insights", [])
        self.next_questions = d.get("next_questions", [])
        self.curiosity_rationale = d.get("curiosity_rationale", "")


def social_title_for(detail: Dict[str, Any], item_type: str) -> str:
    """Título protocolar del ítem publicado (~100 chars, sin markdown)."""
    topic = (detail.get("topic") or "").strip()
    if item_type == "card":
        base = f"TARDIS investiga: {topic}" if topic else "TARDIS · Conclusiones de investigación"
    else:
        base = topic or detail.get("title", "") or "Investigación de TARDIS"
        base = f"{base} — por TARDIS"
    return trim_for_social(strip_markdown(base), 100)


class SocialPublishError(Exception):
    """Error público de publicación social (con contexto para reintento o auditoría)."""


# =============================================================================
# CLIENTE TIKTOK (CONTENT POSTING API V2 · OAUTH 2.0)
# =============================================================================
class TikTokContentClient:
    """
    Cliente oficial TikTok Content Posting API v2: OAuth 2.0 con auto-refresco,
    FILE_UPLOAD segmentado (bloques de 64 MB, Content-Range, reintentos ante 5xx),
    PULL_FROM_URL para bóvedas expuestas por túnel, y consulta de estado.
    Documentación: developers.tiktok.com/doc/content-posting-api-get-started
    """

    API_BASE = "https://open.tiktokapis.com"
    AUTH_BASE = "https://www.tiktok.com/v2/auth/authorize/"
    CHUNK_SIZE = 64 * 1024 * 1024   # límite legal de segmento en la API

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    # ----------------------------- OAuth 2.0 -----------------------------
    def authorize_url(self, state: Optional[str] = None) -> str:
        """URL de autorización del Arquitecto (luego pasa el code con --exchange)."""
        from urllib.parse import quote
        tk = self.cfg
        if not tk.get("client_key"):
            raise SocialPublishError("Falta client_key de TikTok en social_config.json")
        scope = (tk.get("scope") or "user.info.basic,video.publish").replace(",", "%2C")
        state = state or f"tardis{int(time.time())}"
        return (
            f"{self.AUTH_BASE}?client_key={quote(tk['client_key'])}"
            f"&response_type=code&scope={scope}"
            f"&redirect_uri={quote(tk.get('redirect_uri') or 'http://localhost:8793/auth/tiktok/callback')}"
            f"&state={quote(state)}"
        )

    def exchange_code(self, code: str) -> Dict[str, Any]:
        """Intercambia el código OAuth por tokens y persiste en social_config.json."""
        resp = requests.post(
            f"{self.API_BASE}/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": self.cfg.get("client_key", ""),
                "client_secret": self.cfg.get("client_secret", ""),
                "code": code.strip(),
                "grant_type": "authorization_code",
                "redirect_uri": self.cfg.get("redirect_uri", ""),
            },
            timeout=30,
        )
        return self._store_tokens(resp, "exchange_code")

    def refresh_access_token(self) -> Dict[str, Any]:
        """Renueva el access_token con el refresh_token vigente."""
        resp = requests.post(
            f"{self.API_BASE}/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": self.cfg.get("client_key", ""),
                "client_secret": self.cfg.get("client_secret", ""),
                "grant_type": "refresh_token",
                "refresh_token": self.cfg.get("refresh_token", ""),
            },
            timeout=30,
        )
        return self._store_tokens(resp, "refresh_token")

    def _store_tokens(self, resp: requests.Response, origin: str) -> Dict[str, Any]:
        """Persiste los tokens recibidos (o levanta error legible) en cada flujo."""
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code != 200 or not data.get("access_token"):
            desc = (data.get("error_description") or data.get("description") or resp.text)[:300]
            raise SocialPublishError(f"OAuth TikTok [{origin}][{resp.status_code}]: {desc}")
        now = int(time.time())
        self.cfg["access_token"] = data["access_token"]
        self.cfg["token_expires_at"] = now + int(data.get("expires_in", 7200))
        if data.get("refresh_token"):
            self.cfg["refresh_token"] = data["refresh_token"]
            self.cfg["refresh_expires_at"] = now + int(data.get("refresh_expires_in", 0))
        if data.get("open_id"):
            self.cfg["open_id"] = data["open_id"]
        # Persistir sobre la config completa sin aplastar otras claves
        full = load_social_config()
        full["tiktok"] = self.cfg
        save_social_config(full)
        logger.info(f"🔑 Tokens TikTok actualizados ({origin}) y almacenados con permisos 0600.")
        return {"ok": True, "open_id": self.cfg.get("open_id", ""),
                "expires_in_s": int(data.get("expires_in", 7200)), "scope": data.get("scope", "")}

    def _access_token(self, allow_refresh: bool = True) -> str:
        """Token vivo: refresca automáticamente si expiró (una sola pasada)."""
        token = self.cfg.get("access_token", "")
        if not token:
            raise SocialPublishError(
                "Sin access_token de TikTok. Completa el flujo: --auth-url → --exchange <code>."
            )
        expires = int(self.cfg.get("token_expires_at", 0) or 0)
        if expires and time.time() > expires - 60:
            if not allow_refresh:
                raise SocialPublishError("access_token de TikTok expirado (sin auto-refresco permitido aquí).")
            self.refresh_access_token()
            token = self.cfg.get("access_token", "")
        return token

    # ----------------------- Publicación FILE_UPLOAD / PULL -----------------------
    def publish_from_file(self, video_path: Path, title: str,
                          privacy_level: Optional[str] = None) -> Dict[str, Any]:
        """Publica un video local vía FILE_UPLOAD (segmentado 64 MB, reintentos)."""
        path = Path(video_path)
        if not path.exists() or path.stat().st_size < 1024:
            raise SocialPublishError(f"Archivo inválido para publicar: {path}")
        file_size = path.stat().st_size
        payload = {
            "post_info": {
                "title": trim_for_social(strip_markdown(title), 2200),
                "privacy_level": privacy_level or self.cfg.get("privacy_level", "PUBLIC_TO_EVERYONE"),
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": min(self.CHUNK_SIZE, file_size),
                "total_chunk_count": max(1, math.ceil(file_size / self.CHUNK_SIZE)),
            },
        }
        init_res = self._post_json(f"{self.API_BASE}/v2/post/publish/video/init/", payload)
        data = init_res.get("data") or {}
        err = init_res.get("error") or {}
        if isinstance(err, dict) and err.get("code") not in ("ok", None, ""):
            raise SocialPublishError(f"init TikTok: {json.dumps(err)[:300]}")
        publish_id = data.get("publish_id")
        upload_url = data.get("upload_url")
        if not publish_id:
            raise SocialPublishError(f"init TikTok sin publish_id: {json.dumps(init_res)[:300]}")

        if upload_url:
            self._upload_chunks(upload_url, path, file_size)
        return {"publish_id": publish_id, "mode": "FILE_UPLOAD", "file": str(path), "bytes": file_size}

    def publish_from_url(self, video_url: str, title: str,
                         privacy_level: Optional[str] = None) -> Dict[str, Any]:
        """Publica por PULL_FROM_URL (requiere dominio público validado en la app)."""
        if not video_url.startswith("https://"):
            raise SocialPublishError("PULL_FROM_URL exige una URL https pública validada.")
        payload = {
            "post_info": {
                "title": trim_for_social(strip_markdown(title), 2200),
                "privacy_level": privacy_level or self.cfg.get("privacy_level", "PUBLIC_TO_EVERYONE"),
            },
            "source_info": {"source": "PULL_FROM_URL", "video_url": video_url},
        }
        init_res = self._post_json(f"{self.API_BASE}/v2/post/publish/video/init/", payload)
        pid = (init_res.get("data") or {}).get("publish_id")
        if not pid:
            raise SocialPublishError(f"init TikTok (PULL) sin publish_id: {json.dumps(init_res)[:300]}")
        return {"publish_id": pid, "mode": "PULL_FROM_URL"}

    def publish_status(self, publish_id: str) -> Dict[str, Any]:
        """Consulta el estado de procesamiento de una publicación."""
        resp = requests.post(
            f"{self.API_BASE}/v2/post/publish/status/fetch/",
            headers={"Authorization": f"Bearer {self._access_token()}",
                     "Content-Type": "application/json"},
            json={"publish_id": publish_id},
            timeout=30,
        )
        try:
            return resp.json()
        except ValueError:
            return {"status_code": resp.status_code, "raw": resp.text[:300]}

    # ------------------------------- Transporte -------------------------------
    def _post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        last_err: Optional[str] = None
        for attempt in range(4):
            try:
                resp = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {self._access_token()}",
                             "Content-Type": "application/json; charset=utf-8"},
                    data=json.dumps(payload, ensure_ascii=False),
                    timeout=60,
                )
                if resp.status_code == 401 and attempt < 3:
                    self.refresh_access_token()
                    continue
                if resp.status_code >= 500 and attempt < 3:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    time.sleep(2 ** attempt)
                    continue
                if resp.content:
                    try:
                        return resp.json()
                    except ValueError:
                        raise SocialPublishError(f"Respuesta no-JSON de TikTok: {resp.text[:300]}")
                return {"status_code": resp.status_code}
            except requests.RequestException as e:
                last_err = str(e)
                time.sleep(2 ** attempt)
        raise SocialPublishError(f"Transporte TikTok fallido tras 4 intentos: {last_err}")

    def _upload_chunks(self, upload_url: str, path: Path, file_size: int) -> None:
        """Sube el archivo por bloques Content-Range (200/201/206 → segmento asentado)."""
        start = 0
        block_failures = 0
        with open(path, "rb") as fh:
            while start < file_size:
                end = min(start + self.CHUNK_SIZE, file_size) - 1
                fh.seek(start)
                blob = fh.read(end - start + 1)
                try:
                    resp = requests.put(
                        upload_url,
                        data=blob,
                        headers={
                            "Content-Type": "video/mp4",
                            "Content-Length": str(len(blob)),
                            "Content-Range": f"bytes {start}-{end}/{file_size}",
                        },
                        timeout=600,
                    )
                    if resp.status_code in (200, 201, 206):
                        start = end + 1
                        block_failures = 0
                        logger.info(f"⬆️ Bloque social asentado [{start}/{file_size}] (HTTP {resp.status_code})")
                        continue
                    if 500 <= resp.status_code < 600 and block_failures < 3:
                        block_failures += 1
                        time.sleep(2 ** block_failures)
                        continue
                    raise SocialPublishError(f"Upload TikTok HTTP {resp.status_code}: {resp.text[:300]}")
                except requests.RequestException as e:
                    block_failures += 1
                    if block_failures > 3:
                        raise SocialPublishError(f"Red fallida subiendo a TikTok: {e}")
                    time.sleep(2 ** block_failures)


# =============================================================================
# TARJETA DE CONCLUSIONES (VIDEO PENSANTE → MP4 VERTICAL 720x1280)
# =============================================================================
class ConclusionsCardRenderer:
    """Renderiza las conclusiones cognitivas de TARDIS como tarjeta vertical MP4."""

    WIDTH, HEIGHT = 720, 1280
    MARGIN = 40
    BG_TOP = (8, 12, 38)
    BG_BOTTOM = (34, 16, 62)
    ACCENT = (0, 229, 255)        # cian temporal
    ACCENT_2 = (255, 214, 10)     # ámbar kármico
    TEXT_MAIN = (232, 240, 255)
    TEXT_SOFT = (150, 166, 208)

    def __init__(self):
        from PIL import Image, ImageDraw, ImageFont
        self._Image, self._ImageDraw, self._ImageFont = Image, ImageDraw, ImageFont

    # ------------------------------ utilidades ------------------------------
    def _font(self, size: int, bold: bool = True):
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        try:
            return self._ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)
        except Exception:
            return self._ImageFont.load_default()

    def _wipe_col(self, line_rgb: Tuple[int, int, int], w: int) -> List[Tuple[int, int, int]]:
        return [line_rgb] * w

    def _wrap(self, dc, text: str, font, max_w: int, max_lines: int = 30) -> List[str]:
        """Envoltura de texto robusta: trocea tokens más anchos que el lienzo y corta por palabra."""
        if not text:
            return []
        words: List[str] = []
        for raw in text.split():
            if dc.textlength(raw, font=font) <= max_w:
                words.append(raw)
                continue
            piece = ""
            for ch in raw:
                if piece and dc.textlength(piece + ch, font=font) > max_w:
                    words.append(piece)
                    piece = ch
                else:
                    piece += ch
            if piece:
                words.append(piece)
        lines: List[str] = []
        cur = ""
        for word in words:
            test = (cur + " " + word) if cur else word
            if dc.textlength(test, font=font) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
            if len(lines) >= max_lines:
                break
        if cur and len(lines) < max_lines:
            lines.append(cur)
        return lines

    def _measure_counter(self):
        img = self._Image.new("RGB", (self.WIDTH, self.HEIGHT))
        return self._ImageDraw.Draw(img)

    # ------------------------------ lienzos ------------------------------
    def _background(self, seed: str):
        """Fondo degradado determinista con constelación ligada al video (estable)."""
        Image = self._Image
        w, h = self.WIDTH, self.HEIGHT
        img = Image.new("RGB", (w, h), self.BG_TOP)

        rr = __import__("random").Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))

        # Degradado vertical por franjas (rápido y sin dependencias)
        steps = 64
        band_h = h // steps + 1
        for i in range(steps):
            t = i / (steps - 1)
            rgb = tuple(int(self.BG_TOP[c] + (self.BG_BOTTOM[c] - self.BG_TOP[c]) * t) for c in range(3))
            img.paste(rgb, (0, i * band_h, w, min(h, (i + 1) * band_h)))

        # Constelación de puntos fijos
        px = img.load()
        star = (150, 190, 255)
        for _ in range(90):
            x, y = rr.randint(0, w - 1), rr.randint(0, h - 1)
            r = rr.choice([1, 1, 2])
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        px[nx, ny] = star

        # Halo central sutil
        overlay = Image.new("RGB", (w, h), (26, 60, 110))
        mask = Image.new("L", (w, h), 0)
        self._ImageDraw.Draw(mask).ellipse([int(w * 0.18), int(h * 0.28), int(w * 0.82), int(h * 0.60)], fill=46)
        img = Image.composite(overlay, img, mask)
        return img

    def _canvas(self, rec, section: str):
        rec_id = str(getattr(rec, "id", "") or "card")
        img = self._background(f"{rec_id}_{section}")
        dc = self._ImageDraw.Draw(img)
        return dc, img

    def _header(self, dc, title: str) -> int:
        """Devuelve la coordenada Y final tras dibujar el encabezado de sección."""
        f_title = self._font(30)
        lines = self._wrap(dc, title.upper(), f_title, self.WIDTH - 150, max_lines=2)
        dc.rounded_rectangle([self.MARGIN, 214, self.MARGIN + 12, 296], radius=6, fill=self.ACCENT)
        y = 210
        for ln in lines:
            dc.text((self.MARGIN + 30, y), ln, font=f_title, fill=self.ACCENT)
            y += 40
        return y + 26

    def _footer(self, dc, label: str = ""):
        f_small = self._font(19, bold=False)
        text = label.strip()[:46] if label else "GODWORKS SYSTEM · TARDIS v26.4"
        try:
            tw = dc.textlength("TARDIS", font=self._font(22))
        except Exception:
            tw = 80
        dc.text((self.MARGIN, self.HEIGHT - 64), text, font=f_small, fill=self.TEXT_SOFT)
        dc.text((self.WIDTH - self.MARGIN - int(tw) - 4, self.HEIGHT - 96), "TARDIS", font=self._font(22), fill=(120, 132, 172))

    # ------------------------------ diapositivas ------------------------------
    def _slide_cover(self, rec):
        dc, img = self._canvas(rec, "cover")
        dc.text((self.MARGIN, 80), "T A R D I S", font=self._font(40), fill=self.ACCENT)
        dc.text((self.MARGIN, 130), "VIDEO PENSANTE · CONCLUSIONES", font=self._font(22), fill=(178, 196, 226))
        dc.rectangle([self.MARGIN, 190, self.WIDTH - self.MARGIN, 194], fill=(52, 60, 110))

        topic = str(getattr(rec, "topic", "") or "Exploración de la realidad")
        f_topic = self._font(52)
        y = 430
        for ln in self._wrap(dc, topic.upper(), f_topic, self.WIDTH - 2 * self.MARGIN, max_lines=5):
            dc.text((self.MARGIN, y), ln, font=f_topic, fill=self.TEXT_MAIN)
            y += 68
        dc.rectangle([self.MARGIN, y + 34, self.WIDTH - self.MARGIN, y + 38], fill=self.ACCENT_2)
        self._footer(dc, f"DOMINIO · {str(getattr(rec, 'domain', 'Ciencia')).upper()[:34]}")
        return img

    def _panel(self, img, box, alpha: int = 172):
        """Panel translúcido de fondo para máxima legibilidad sobre la constelación."""
        Image = self._Image
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        self._ImageDraw.Draw(layer).rounded_rectangle(box, radius=20, fill=(8, 12, 34, alpha))
        return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    def _slide_body(self, rec, header: str, body: str, bullets: bool = False, label: str = ""):
        dc, img = self._canvas(rec, header)
        y = self._header(dc, header)
        max_w = self.WIDTH - 2 * self.MARGIN - 28
        f_body = self._font(29, bold=False)
        body_clean = strip_markdown(body or "") or "· (Sin contenido registrado)"
        if bullets:
            flow: List[str] = []
            for chunk in [c.strip() for c in body_clean.split("\n") if c.strip()]:
                chunk = chunk if chunk.startswith("·") else f"· {trim_for_social(chunk, 150)}"
                wrapped = self._wrap(dc, chunk, f_body, max_w, max_lines=4)
                flow.extend(wrapped)
                flow.append("")
            body_lines = flow
        else:
            body_lines = self._wrap(dc, body_clean, f_body, max_w, max_lines=24)

        # Panel translúcido extensión del área de lectura (sin tapar el pie)
        last_y = min(self.HEIGHT - 150, y + 44 * min(len(body_lines), 25) + 10)
        img = self._panel(img, (self.MARGIN - 18, y - 16, self.WIDTH - self.MARGIN - 8, last_y))
        dc = self._ImageDraw.Draw(img)
        for line in body_lines:
            if y > self.HEIGHT - 160:
                break
            if line.strip():
                dc.text((self.MARGIN, y), line, font=f_body, fill=self.TEXT_MAIN)
            y += 44
        self._footer(dc, label or f"ID · {str(getattr(rec, 'id', ''))[:30]}")
        return img

    def _slide_questions(self, rec):
        qs = [f"· {trim_for_social(strip_markdown(str(q)), 150)}" for q in (getattr(rec, "next_questions", []) or [])[:3]]
        body = "\n".join(qs) or "· ¿Qué revela la realidad sobre su propia estructura?"
        img = self._slide_body(rec, "PREGUNTAS DETONADORAS", body, bullets=True, label="SIGUIENTE CICLO TARDIS")
        if getattr(rec, "url", ""):
            d2 = self._ImageDraw.Draw(img)
            d2.text((self.MARGIN, self.HEIGHT - 110), "Fuente original registrada en la Bóveda TARDIS.",
                    font=self._font(19, bold=False), fill=self.TEXT_SOFT)
        return img

    # ------------------------------ render total ------------------------------
    def render(self, rec, out_path: Path) -> Optional[Path]:
        """
        Genera la tarjeta completa (5 diapositivas → MP4 720x1280 H.264 + AAC).
        Devuelve la ruta del MP4 o None si falla el renderizado.
        """
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            slide_texts = [
                str(getattr(rec, "topic", "") or ""),
                strip_markdown(str(getattr(rec, "visual_summary", "") or ""))[:620],
                strip_markdown(str(getattr(rec, "abstraction_conclusions", "") or ""))[:780],
                "\n".join([str(i)[:150] for i in (getattr(rec, "learned_insights", []) or [])[:4]]),
                "\n".join([str(q)[:150] for q in (getattr(rec, "next_questions", []) or [])[:3]]),
            ]
            images = [
                self._slide_cover(rec),
                self._slide_body(rec, "LO QUE VIMOS", slide_texts[1]),
                self._slide_body(rec, "CONCLUSIONES", slide_texts[2]),
                self._slide_body(rec, "APRENDIZAJES", slide_texts[3], bullets=True),
                self._slide_questions(rec),
            ]
        except Exception as e:
            logger.warning(f"Aviso renderizando tarjeta: {e}")
            return None

        tmp_dir = DATA_DIR / "cards_tmp"
        tmp_dir.mkdir(exist_ok=True)
        rec_id = str(getattr(rec, "id", "")) or f"card{int(time.time())}"
        png_paths: List[Path] = []
        durations: List[float] = []
        try:
            for idx, (img, txt) in enumerate(zip(images, slide_texts)):
                p = tmp_dir / f"{rec_id}_s{idx}.png"
                img.convert("RGB").save(p, format="PNG")
                png_paths.append(p)
                dur = 3.4 + min(3.4, len(txt) / 620.0)
                durations.append(round(dur, 2))

            list_path = tmp_dir / f"{rec_id}_list.txt"
            with open(list_path, "w", encoding="utf-8") as fh:
                for p, d_t in zip(png_paths, durations):
                    fh.write(f"file '{p}'\nduration {d_t}\n")
                fh.write(f"file '{png_paths[-1]}'\n")   # último frame repetido (regla concat)

            total_dur = sum(durations)
            aeval = (
                "aevalsrc=0.050*sin(2*PI*82.41*t)+0.030*sin(2*PI*164.81*t)"
                "|0.050*sin(2*PI*123.47*t)+0.030*sin(2*PI*246.94*t):s=44100:c=stereo"
            )
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", str(list_path),
                "-f", "lavfi", "-i", aeval,
                "-filter_complex",
                (
                    "[0:v]scale=720:1280,setsar=1,format=yuv420p,"
                    f"fade=t=in:st=0:d=0.6,fade=t=out:st={max(0.1, total_dur - 0.9):.2f}:d=0.9[v];"
                    f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                    f"afade=t=in:st=0:d=1.6,afade=t=out:st={max(0.5, total_dur - 2.4):.2f}:d=2.2,"
                    "volume=0.9[a]"
                ),
                "-map", "[v]", "-map", "[a]",
                "-t", f"{total_dur:.2f}",
                "-c:v", "libx264", "-preset", "faster", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(out_path),
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
            if not out_path.exists() or out_path.stat().st_size < 4096:
                tail = res.stderr.decode("utf-8", "ignore")[-400:] if res.stderr else ""
                logger.warning(f"ffmpeg no produjo la tarjeta (rc={res.returncode}): {tail}")
                return None
            logger.info(
                f"🖼️ Tarjeta de conclusiones renderizada: {out_path.name} "
                f"({out_path.stat().st_size/(1024*1024):.1f} MB, {total_dur:.1f}s)"
            )
            return out_path
        except Exception as e:
            logger.warning(f"Aviso en pipeline de tarjeta: {e}")
            return None
        finally:
            for p in png_paths + ([tmp_dir / f"{rec_id}_list.txt"] if png_paths else []):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass


# =============================================================================
# LOG PERSISTENTE DE PUBLICACIONES (SQLite)
# =============================================================================
def init_publish_db(db_path: Path = DB_PATH):
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS publish_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                item_type TEXT NOT NULL,
                status TEXT NOT NULL,
                publish_id TEXT,
                caption TEXT,
                file_path TEXT,
                file_size_bytes INTEGER,
                attempts INTEGER DEFAULT 0,
                last_attempt_at TEXT,
                error TEXT,
                created_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pl_video ON publish_log(video_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pl_status ON publish_log(status)")
        conn.commit()


def _db_query(query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def _db_insert(entry: Dict[str, Any]) -> int:
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.execute("""
            INSERT INTO publish_log (
                video_id, platform, item_type, status, publish_id, caption,
                file_path, file_size_bytes, attempts, last_attempt_at, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.get("video_id", ""),
            entry.get("platform", "tiktok"),
            entry.get("item_type", "video"),
            entry.get("status", "pending"),
            entry.get("publish_id", ""),
            entry.get("caption", ""),
            entry.get("file_path", ""),
            entry.get("file_size_bytes", 0),
            entry.get("attempts", 0),
            entry.get("last_attempt_at", ""),
            entry.get("error", ""),
            entry.get("created_at", datetime.datetime.now().isoformat()),
        ))
        conn.commit()
        return cur.lastrowid


def _db_update(log_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(f"UPDATE publish_log SET {cols} WHERE id = ?", (*fields.values(), log_id))
        conn.commit()


# =============================================================================
# MOTOR SOCIAL SOBERANO
# =============================================================================
class TardisSocialEngine:
    """
    Función /SOCIAL del sistema: conecta /VideoPensante con las redes públicas,
    publicando 100 % autónomamente los videos descargados y sus conclusiones.
    """

    _instance: Optional["TardisSocialEngine"] = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "TardisSocialEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        init_publish_db()
        self.cfg = load_social_config()
        self._renderer: Optional[ConclusionsCardRenderer] = None
        self._last_publish_ts: float = 0.0

    # -------------------------------- plataforma --------------------------------
    def _tiktok(self) -> TikTokContentClient:
        return TikTokContentClient(self.cfg["tiktok"])

    def is_platform_ready(self, platform: str = "tiktok") -> bool:
        tk = self.cfg.get("tiktok", {})
        return platform == "tiktok" and bool(tk.get("enabled") and tk.get("access_token"))

    # -------------------------------- seguridad --------------------------------
    def _validate_publication(self, caption: str, title: str) -> None:
        """Constante AEGIS: neutraliza publicación con información privada anclada."""
        hits = get_aegis_violations(caption, self.cfg)
        low_title = (title or "").lower()
        for token in ("carrillo", "annya", "andrea", "rex peluche"):
            if token in low_title and token not in hits:
                hits.append(token)
        if hits:
            raise SocialPublishError(
                "CONSTANTE-AEGIS: la leyenda contiene información privada protegida; publicación neutralizada."
            )

    # --------------------------------- tarjetas ---------------------------------
    @property
    def renderer(self) -> ConclusionsCardRenderer:
        if self._renderer is None:
            self._renderer = ConclusionsCardRenderer()
        return self._renderer

    def render_card_for(self, detail: Dict[str, Any], out_path: Optional[Path] = None) -> Optional[Path]:
        """Crea la tarjeta MP4 de conclusiones a partir de un detalle (dict de memoria)."""
        if out_path is None:
            out_path = CARDS_DIR / f"{detail.get('id', 'card')}__conclusiones.mp4"
        return self.renderer.render(_RecordView(detail), out_path)

    # --------------------------- ciclo de publicación ---------------------------
    def publish_record(self, rec: Any, item: str = "all") -> Dict[str, Any]:
        """
        Publica (video de bóveda y/o tarjeta de conclusiones) con deduplicación
        estricta. item: 'all' | 'video' | 'card'.
        """
        vid_id = getattr(rec, "id", "")
        snapshot = self._record_to_snapshot(rec)
        return self._publish_snapshot(vid_id, snapshot, item)

    def publish_video_by_id(self, vid_id: str, item: str = "all") -> Dict[str, Any]:
        """Publica por ID desde la memoria de abstracción de /VideoPensante."""
        from core.tardis_video_thinking_engine import get_video_thinking_engine
        detail = get_video_thinking_engine().get_video_detail(vid_id)
        if not detail:
            return {"skipped": f"ID {vid_id} no está en la memoria de abstracción."}
        return self._publish_snapshot(detail.get("id", vid_id), detail, item)

    def _record_to_snapshot(self, rec: Any) -> Dict[str, Any]:
        """Aplana un VideoThoughtRecord a dict compatible con render/caption/publish."""
        return {
            "id": getattr(rec, "id", ""),
            "title": getattr(rec, "title", ""),
            "topic": getattr(rec, "topic", ""),
            "domain": getattr(rec, "domain", ""),
            "duration_sec": getattr(rec, "duration_sec", 0.0),
            "resolution": getattr(rec, "resolution", ""),
            "file_path": getattr(rec, "file_path", ""),
            "url": getattr(rec, "url", ""),
            "file_size_bytes": getattr(rec, "file_size_bytes", 0),
            "visual_summary": getattr(rec, "visual_summary", ""),
            "audio_summary": getattr(rec, "audio_summary", ""),
            "audio_transcript": getattr(rec, "audio_transcript", ""),
            "abstraction_conclusions": getattr(rec, "abstraction_conclusions", ""),
            "learned_insights": list(getattr(rec, "learned_insights", []) or []),
            "next_questions": list(getattr(rec, "next_questions", []) or []),
            "curiosity_rationale": getattr(rec, "curiosity_rationale", ""),
        }

    def _publish_snapshot(self, vid_id: str, s: Dict[str, Any], item: str = "all") -> Dict[str, Any]:
        report: Dict[str, Any] = {"video_id": vid_id, "platform": "tiktok", "results": {}}
        caption = compose_caption(_RecordView(s), self.cfg)

        plan: List[Tuple[str, Optional[Path]]] = []
        if item in ("all", "video") and self.cfg.get("publish_downloaded_video", True):
            plan.append(("video", Path(s.get("file_path") or "")))
        if item in ("all", "card") and self.cfg.get("publish_conclusions_card", True):
            plan.append(("card", None))   # la tarjeta se genera en vivo

        for item_type, file_path in plan:
            if self._already_published(vid_id, item_type):
                report["results"][item_type] = {"status": "skipped", "reason": "Ya publicado (deduplicación)"}
                continue

            # 1) AEGIS primero: nunca hay publicación con privacidad en juego
            try:
                self._validate_publication(caption, str(s.get("title", "")))
            except SocialPublishError as e:
                _db_insert({"video_id": vid_id, "item_type": item_type, "status": "refused",
                            "caption": caption[:1200], "error": str(e)})
                logger.error(f"🛡️ {e}  (video: {vid_id})")
                report["results"][item_type] = {"status": "refused", "error": str(e)}
                continue

            # 2) Motor no listo → cola persistente (cero pérdida de contenido)
            if not self.is_platform_ready():
                if not self._pending_row(vid_id, item_type):
                    _db_insert({"video_id": vid_id, "item_type": item_type, "status": "pending",
                                "caption": caption[:1200], "attempts": 1,
                                "last_attempt_at": datetime.datetime.now().isoformat()})
                report["results"][item_type] = {"status": "pending",
                                                "reason": "Esperando credenciales de TikTok (cola persistente)"}
                continue

            # 3) Tarjeta en vivo (solo cuando va a producción real)
            live_path = file_path
            if item_type == "card":
                live_path = self.render_card_for(s)
                if not live_path:
                    _db_insert({"video_id": vid_id, "item_type": "card", "status": "failed",
                                "caption": caption[:1200],
                                "last_attempt_at": datetime.datetime.now().isoformat(),
                                "error": "Renderizado de tarjeta falló"})
                    report["results"][item_type] = {"status": "failed", "error": "Renderizado de tarjeta falló"}
                    continue

            # 4) Publicación con reintentos y registro permanente
            title = social_title_for(s, item_type)
            self._throttle()
            try:
                res = self._tiktok().publish_from_file(live_path, title=title)
                _db_insert({
                    "video_id": vid_id, "item_type": item_type, "status": "published",
                    "publish_id": res["publish_id"], "caption": caption[:1200],
                    "file_path": str(live_path), "file_size_bytes": Path(live_path).stat().st_size,
                    "attempts": 1, "last_attempt_at": datetime.datetime.now().isoformat(),
                })
                self._last_publish_ts = time.time()
                logger.info(f"📡 /Social publicado → TikTok[{item_type}] {vid_id} (publish_id {res['publish_id']})")
                report["results"][item_type] = {"status": "published", "publish_id": res["publish_id"],
                                                "mode": res["mode"]}
            except SocialPublishError as e:
                _db_insert({
                    "video_id": vid_id, "item_type": item_type, "status": "pending",
                    "caption": caption[:1200], "file_path": str(live_path), "attempts": 1,
                    "last_attempt_at": datetime.datetime.now().isoformat(), "error": str(e)[:900],
                })
                report["results"][item_type] = {"status": "requeued", "error": str(e)}
                logger.error(f"❌ Publicación TikTok ({vid_id}·{item_type}) en cola: {str(e)[:200]}")
            except Exception as e_exc:
                _db_insert({"video_id": vid_id, "item_type": item_type, "status": "pending",
                            "attempts": 1, "last_attempt_at": datetime.datetime.now().isoformat(),
                            "error": str(e_exc)[:900]})
                report["results"][item_type] = {"status": "requeued", "error": str(e_exc)}
                logger.warning(f"Aviso en publicación {item_type}: {e_exc}")

        return report

    def _already_published(self, video_id: str, item_type: str, platform: str = "tiktok") -> bool:
        rows = _db_query(
            "SELECT id FROM publish_log WHERE video_id = ? AND item_type = ? AND platform = ? "
            "AND status IN ('published','refused')",
            (video_id, item_type, platform),
        )
        return bool(rows)

    def _pending_row(self, video_id: str, item_type: str, platform: str = "tiktok") -> bool:
        rows = _db_query(
            "SELECT id FROM publish_log WHERE video_id = ? AND item_type = ? AND platform = ? AND status = 'pending'",
            (video_id, item_type, platform),
        )
        return bool(rows)

    def _throttle(self):
        gap = float(self.cfg.get("tiktok", {}).get("min_gap_sec", 90))
        elapsed = time.time() - self._last_publish_ts
        if self._last_publish_ts > 0 and elapsed < gap:
            time.sleep(min(gap - elapsed, 120))
        self._last_publish_ts = time.time()

    # ------------------------------ cola pendiente ------------------------------
    def retry_pending(self, max_items: Optional[int] = None) -> Dict[str, Any]:
        """Reintenta la cola persistente (nada se pierde mientras exista credencial)."""
        limit = int(max_items or self.cfg.get("max_backlog_per_run", 3))
        if not self.is_platform_ready():
            return {"skipped": "Motor social no listo (autenticación TikTok pendiente)."}
        rows = _db_query("SELECT * FROM publish_log WHERE status = 'pending' ORDER BY id ASC LIMIT ?", (limit,))
        report: Dict[str, Any] = {"candidates": len(rows), "published": [], "failed": 0}
        if not rows:
            report["info"] = "La cola pendiente está vacía (nada por reintentar)."
            return report

        from core.tardis_video_thinking_engine import get_video_thinking_engine
        engine = get_video_thinking_engine()

        for row in rows:
            vid_id, item = row["video_id"], row["item_type"]
            detail = engine.get_video_detail(vid_id)
            if not detail:
                _db_update(row["id"], status="failed", error="Video ausente en la memoria de abstracción.",
                           last_attempt_at=datetime.datetime.now().isoformat())
                continue

            caption = compose_caption(_RecordView(detail), self.cfg)
            try:
                self._validate_publication(caption, str(detail.get("title", "")))
            except SocialPublishError as e:
                _db_update(row["id"], status="refused", error=str(e),
                           last_attempt_at=datetime.datetime.now().isoformat())
                continue

            if item == "video":
                p = Path(detail.get("file_path") or "")
                if not p.exists() or p.stat().st_size < 1024:
                    _db_update(row["id"], status="failed", error="Archivo ausente en la bóveda.",
                               last_attempt_at=datetime.datetime.now().isoformat())
                    report["failed"] += 1
                    continue
                live_path = p
            else:
                live_path = self.render_card_for(detail)
                if not live_path:
                    _db_update(row["id"], status="failed", error="Renderizado de tarjeta falló.",
                               last_attempt_at=datetime.datetime.now().isoformat())
                    report["failed"] += 1
                    continue

            self._throttle()
            try:
                res = self._tiktok().publish_from_file(live_path, title=social_title_for(detail, item))
                _db_update(row["id"], status="published", publish_id=res["publish_id"],
                           file_path=str(live_path), file_size_bytes=Path(live_path).stat().st_size,
                           attempts=int(row.get("attempts", 0)) + 1,
                           last_attempt_at=datetime.datetime.now().isoformat(), error="")
                report["published"].append({"video_id": vid_id, "item": item, "publish_id": res["publish_id"]})
            except Exception as e:
                _db_update(row.get("id"), status="pending",
                           attempts=int(row.get("attempts", 0)) + 1,
                           last_attempt_at=datetime.datetime.now().isoformat(),
                           error=str(e)[:900])
                report["failed"] += 1
        return report

    # --------------------------------- backfill ---------------------------------
    def backfill(self, maximum: Optional[int] = None) -> Dict[str, Any]:
        """
        Publica en orden cronológico ancestro→reciente todos los videos de la
        memoria de /VideoPensante que aún no se hayan socializado.
        """
        from core.tardis_video_thinking_engine import get_video_thinking_engine
        engine = get_video_thinking_engine()
        memories = engine.get_memory_summary(limit=10000)          # más recientes primero
        all_ids = [m["id"] for m in reversed(memories)]             # orden cronológico
        handled = {r["video_id"] for r in _db_query(
            "SELECT DISTINCT video_id FROM publish_log WHERE status IN ('published','refused')")}
        pending_ids = {r["video_id"] for r in _db_query("SELECT DISTINCT video_id FROM publish_log WHERE status = 'pending'")}
        candidates = [vid for vid in all_ids if vid not in handled and vid not in pending_ids]

        limit = int(maximum or self.cfg.get("max_backlog_per_run", 3))
        to_process = candidates[:limit]
        out = {"candidates": len(candidates), "processed": 0, "reports": []}
        for vid_id in to_process:
            rep = self.publish_video_by_id(vid_id, item="all")
            out["reports"].append({"video_id": vid_id, "report": rep})
            out["processed"] += 1
        return out

    # ----------------------------------- estado -----------------------------------
    def publish_history(self, limit: int = 15) -> List[Dict[str, Any]]:
        return _db_query("SELECT * FROM publish_log ORDER BY id DESC LIMIT ?", (limit,))

    def pending_list(self) -> List[Dict[str, Any]]:
        return _db_query("SELECT * FROM publish_log WHERE status = 'pending' ORDER BY id ASC", ())

    def get_status(self) -> Dict[str, Any]:
        tk = self.cfg.get("tiktok", {})
        with sqlite3.connect(str(DB_PATH)) as conn:
            counts = {s: c for s, c in conn.execute("SELECT status, COUNT(*) FROM publish_log GROUP BY status").fetchall()}
        exp = int(tk.get("token_expires_at", 0) or 0)
        return {
            "canonical_greeting": CANONICAL_GREETING,
            "social_enabled": self.cfg.get("enabled", False),
            "auto_on_new_cycles": self.cfg.get("auto_on_new_cycles", True),
            "publish_downloaded_video": self.cfg.get("publish_downloaded_video", True),
            "publish_conclusions_card": self.cfg.get("publish_conclusions_card", True),
            "platform_ready": self.is_platform_ready(),
            "tiktok_client": bool(tk.get("client_key")),
            "token_expires_in_min": (max(0, exp - int(time.time())) // 60) if exp else -1,
            "privacy_level": tk.get("privacy_level", "PUBLIC_TO_EVERYONE"),
            "caption_max_chars": tk.get("caption_max_chars", 1800),
            "cards_dir": str(CARDS_DIR),
            "db_path": str(DB_PATH),
            "log_counts": counts,
        }

    def set_enabled(self, value: bool, auto_on_cycles: Optional[bool] = None) -> None:
        self.cfg["enabled"] = bool(value)
        if auto_on_cycles is not None:
            self.cfg["auto_on_new_cycles"] = bool(auto_on_cycles)
        save_social_config(self.cfg)
        logger.info("⚙️ Modo social ACTIVADO" if value else "⚙️ Modo social PAUSADO")


def get_social_engine() -> TardisSocialEngine:
    """Instancia única del motor social (comparte hilos y ciclos con /VideoPensante)."""
    return TardisSocialEngine.get_instance()


init_publish_db()
