#!/usr/bin/env python3
"""
core/tardis_music_maestro.py — TARDIS MUSIC MAESTRO · Soundtrack Soberano
=========================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Subsistema musical de TARDIS:

  * Conector nativo a YouTube Music (Innertube WEB_REMIX, sin credenciales).
  * Búsqueda de canciones, vídeos, álbumes, playlists y artistas.
  * Radio infinita (relacionados) para soundtracks sin fin.
  * Motor de reproducción mpv con control IPC (play/pause/next/seek/volume).
  * Director de soundtrack: escenas (focus, epic, calm, doctor, kaiju, night…)
    que TARDIS elige automáticamente según la hora y el estado de continuidad.
  * API HTTP local (127.0.0.1:8794) + dashboard soberano.
  * CLI `tardis-music` y puente para AgentHarness / Omni-Tool Bridge.

Uso rápido:
    python3 core/tardis_music_maestro.py status
    python3 core/tardis_music_maestro.py search "Hans Zimmer Time"
    python3 core/tardis_music_maestro.py play "Interstellar soundtrack"
    python3 core/tardis_music_maestro.py soundtrack doctor --auto
    python3 core/tardis_music_maestro.py serve --autopilot

Sin dependencias de terceros: urllib, http.server, subprocess y la stdlib.
Requiere `yt-dlp` y `mpv` en PATH (presentes en este sistema).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Rutas y constantes
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "music"
ASSETS_DIR = BASE_DIR / "assets"
CONFIG_DIR = Path.home() / ".config" / "tardis-music"
STATE_FILE = DATA_DIR / "state.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"
FAVORITES_FILE = DATA_DIR / "favorites.json"
MPV_LOG = DATA_DIR / "mpv.log"
COOKIES_FILE = CONFIG_DIR / "cookies.txt"
CONFIG_FILE = CONFIG_DIR / "config.json"
DASHBOARD_FILE = ASSETS_DIR / "tardis_music_dashboard.html"

DEFAULT_PORT = int(os.environ.get("TARDIS_MUSIC_PORT", "8794"))
API_BASE = os.environ.get("TARDIS_MUSIC_API", f"http://127.0.0.1:{DEFAULT_PORT}")

YT_BASE = "https://music.youtube.com"
CLIENT_NAME = "WEB_REMIX"
CLIENT_VERSION = "1.20241127.01.00"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/REDACTED_IP Safari/537.36"
)

SEARCH_FILTERS = {
    "songs": "EgWKAQIIAWoKEAkQBRAKEAMQBA%3D%3D",
    "videos": "EgWKAQIQAWoKEAkQChAFEAMQBA%3D%3D",
    "albums": "EgWKAQIYAWoKEAkQChAFEAMQBA%3D%3D",
    "playlists": "EgWKAQIoAWoKEAkQChAFEAMQBA%3D%3D",
    "artists": "EgWKAQIgAWoKEAkQChAFEAMQBA%3D%3D",
}

_TYPE_WORDS = {
    "canción": "song",
    "cancion": "song",
    "song": "song",
    "tema": "song",
    "track": "song",
    "vídeo": "video",
    "video": "video",
    "álbum": "album",
    "album": "album",
    "artista": "artist",
    "artist": "artist",
    "playlist": "playlist",
    "lista de reproducción": "playlist",
    "lista de reproduccion": "playlist",
}

logger = logging.getLogger("TARDIS.MusicMaestro")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("[%(asctime)s] [%(levelname)s] [TARDIS.Music] %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Escenas de soundtrack decididas por TARDIS
# ---------------------------------------------------------------------------
SCENES: Dict[str, Dict[str, Any]] = {
    "focus": {
        "name": "Enfoque Profundo",
        "emoji": "🎯",
        "description": "Piano minimalista, ambient y post-rock para trabajar sin fricción.",
        "keywords": ["focus", "enfoque", "trabajo", "código", "codigo", "productividad"],
        "queries": [
            "Hans Zimmer Interstellar",
            "Ludovico Einaudi",
            "Max Richter",
            "Ólafur Arnalds",
            "ambient focus music",
            "This Will Destroy You",
            "Explosions in the Sky",
            "Brian Eno ambient",
        ],
    },
    "epic": {
        "name": "Épica Cinematográfica",
        "emoji": "⚔️",
        "description": "Orquesta épica y tráilers para momentos de alta intensidad.",
        "keywords": ["epic", "épica", "batalla", "misión", "mision", "lanzamiento"],
        "queries": [
            "Two Steps From Hell",
            "Hans Zimmer epic",
            "Interstellar soundtrack",
            "epic orchestral trailer music",
            "Audiomachine",
            "Thomas Bergersen",
        ],
    },
    "calm": {
        "name": "Calma Temporal",
        "emoji": "🌙",
        "description": "Texturas suaves para bajar revoluciones y reparar el sistema.",
        "keywords": ["calm", "calma", "error", "reposo", "descanso", "reparación"],
        "queries": [
            "Max Richter Sleep",
            "Ólafur Arnalds",
            "Ludovico Einaudi",
            "ambient piano",
            "Hiroshi Yoshimura",
            "Brian Eno",
        ],
    },
    "night": {
        "name": "Nocturno Synthwave",
        "emoji": "🌃",
        "description": "Neón, sintetizadores y carreteras infinitas.",
        "keywords": ["night", "noche", "synthwave", "nocturno"],
        "queries": [
            "The Midnight synthwave",
            "Gunship synthwave",
            "Blade Runner 2049 soundtrack",
            "Vangelis Blade Runner",
            "FM-84",
            "synthwave night drive",
        ],
    },
    "doctor": {
        "name": "TARDIS · Doctor Who",
        "emoji": "🛸",
        "description": "La banda sonora canónica del viaje temporal.",
        "keywords": ["doctor", "tardis", "who", "regeneración", "regeneracion", "viaje"],
        "queries": [
            "Doctor Who Murray Gold",
            "I Am The Doctor Murray Gold",
            "The Shepherd's Boy Doctor Who",
            "Doctor Who theme",
            "Clara's Theme",
            "Twelve's Theme",
            "Doctor Who Series 9 soundtrack",
        ],
    },
    "kaiju": {
        "name": "KAIJU Protocol",
        "emoji": "🦖",
        "description": "Monstruos, percusión y escala titánica.",
        "keywords": ["kaiju", "godzilla", "monstruo", "titán", "titan"],
        "queries": [
            "Godzilla soundtrack",
            "Pacific Rim soundtrack",
            "kaiju epic music",
            "Godzilla Minus One soundtrack",
            "Bear McCreary Godzilla",
        ],
    },
    "creative": {
        "name": "Creatividad Cósmica",
        "emoji": "🎨",
        "description": "Electrónica orgánica y bandas sonoras para crear.",
        "keywords": ["creative", "creatividad", "diseño", "diseno", "idea"],
        "queries": [
            "Jóhann Jóhannsson Arrival",
            "Daft Punk Tron Legacy",
            "Trent Reznor Atticus Ross",
            "Cliff Martinez",
            "experimental ambient",
            "Jon Hopkins",
        ],
    },
    "discovery": {
        "name": "Descubrimiento Espacial",
        "emoji": "🌌",
        "description": "Ambient espacial y cosmos para explorar lo desconocido.",
        "keywords": ["discovery", "descubrimiento", "espacio", "cosmos", "investigación"],
        "queries": [
            "space ambient music",
            "Cosmos soundtrack",
            "Vangelis",
            "Interstellar",
            "Sun Ra space",
            "Stellardrone",
        ],
    },
    "battle": {
        "name": "Protocolo de Combate",
        "emoji": "🔥",
        "description": "Alta energía para ejecuciones críticas.",
        "keywords": ["battle", "combate", "ejecución", "ejecucion", "urgencia"],
        "queries": [
            "Doom Eternal soundtrack",
            "Two Steps From Hell",
            "epic battle music",
            "Mick Gordon",
            "Hans Zimmer Dunkirk",
        ],
    },
    "jazz": {
        "name": "Jazz Noir",
        "emoji": "🎷",
        "description": "Saxofón, contrabajo y misterio.",
        "keywords": ["jazz", "noir", "detective", "misterio"],
        "queries": [
            "Cowboy Bebop soundtrack",
            "jazz noir",
            "Chet Baker",
            "Bill Evans",
            "lo-fi jazz",
            "SEATBELTS Tank",
        ],
    },
    "synthwave": {
        "name": "Synthwave 80s",
        "emoji": "🕹️",
        "description": "Retrowave, arpegios y estética ochentera.",
        "keywords": ["synthwave", "retrowave", "80s", "ochentas"],
        "queries": [
            "The Midnight",
            "Gunship",
            "FM-84",
            "Kavinsky",
            "synthwave retrowave",
            "Timecop1983",
        ],
    },
    "rain": {
        "name": "Lluvia y Lo-Fi",
        "emoji": "🌧️",
        "description": "Lluvia, vinilo y beats para concentrarse.",
        "keywords": ["rain", "lluvia", "lofi", "lo-fi"],
        "queries": [
            "lofi rain",
            "rain sounds for studying",
            "lofi hip hop radio",
            "chillhop",
            "Nujabes",
        ],
    },
    "regeneration": {
        "name": "Regeneración",
        "emoji": "✨",
        "description": "Catarsis orquestal para cerrar y volver a empezar.",
        "keywords": ["regeneration", "regeneración", "reinicio", "reboot", "renacer"],
        "queries": [
            "Doctor Who regeneration",
            "The Shepherd's Boy",
            "Hans Zimmer Time",
            "Max Richter On the Nature of Daylight",
            "emotional orchestral",
        ],
    },
}

DEFAULT_STATE: Dict[str, Any] = {
    "version": 2,
    "queue": [],
    "index": -1,
    "volume": 45,
    "repeat": "off",
    "shuffle": False,
    "autoplay_radio": True,
    "autopilot": False,
    "scene": "focus",
    "last_scene": "",
    "user_paused": False,
    "created_ts": 0.0,
    "updated_ts": 0.0,
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _now() -> float:
    return time.time()


def _iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts or _now()).astimezone().isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("No se pudo escribir %s: %s", path, exc)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("No se pudo leer %s: %s", path, exc)
    return default


def _find_values(obj: Any, key: str, limit: int = 5000) -> Iterable[Any]:
    """Itera todos los valores de una clave en un árbol JSON, sin recursión profunda."""
    stack = [obj]
    found = 0
    while stack and found < limit:
        cur = stack.pop()
        if isinstance(cur, dict):
            if key in cur:
                found += 1
                yield cur[key]
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
        if found >= limit:
            break


def _runs_text(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    if "runs" in obj and isinstance(obj["runs"], list):
        return "".join(str(r.get("text", "")) for r in obj["runs"] if isinstance(r, dict))
    if "simpleText" in obj:
        return str(obj.get("simpleText") or "")
    if "text" in obj and isinstance(obj.get("text"), str):
        return obj["text"]
    return ""


def _duration_to_seconds(text: str) -> int:
    if not text:
        return 0
    parts = text.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return 0


def _fmt_seconds(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "0:00"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _clean_media_title(raw: Any, current: Optional["Track"]) -> str:
    """Normaliza el `media-title` de mpv: yt-dlp expone la URL del stream, no la pista."""
    text = str(raw or "").strip()
    looks_like_url = (
        text.lower().startswith(("http://", "https://"))
        or "googlevideo.com" in text
        or "&sig=" in text
        or "&dur=" in text
    )
    if not text or looks_like_url:
        if current is not None:
            artist = (current.artist or "").strip()
            title = (current.title or "").strip()
            return f"{title} — {artist}" if artist and artist.lower() not in title.lower() else title
        return ""
    return text


def _extract_video_id(value: str) -> Optional[str]:
    """Extrae un videoId de una URL de YouTube/YouTube Music, o valida un ID directo."""
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    try:
        parsed = urllib.parse.urlparse(value)
    except Exception:
        return None
    host = (parsed.netloc or "").lower()
    if "youtube.com" in host or "youtu.be" in host:
        if host.endswith("youtu.be"):
            candidate = parsed.path.strip("/").split("/")[0]
            return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None
        qs = urllib.parse.parse_qs(parsed.query)
        candidate = (qs.get("v") or [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
            return candidate
        m = re.search(r"/(?:embed|shorts|live)/([A-Za-z0-9_-]{11})", parsed.path)
        if m:
            return m.group(1)
    return None


def _is_views(text: str) -> bool:
    low = text.lower()
    return any(
        token in low
        for token in ("reproducciones", "visualizaciones", "views", " de ", "mil ", "millones")
    ) and ":" not in text


# ---------------------------------------------------------------------------
# Modelo de pista
# ---------------------------------------------------------------------------
@dataclass
class Track:
    video_id: str
    title: str
    artist: str = ""
    album: str = ""
    duration: str = ""
    duration_seconds: int = 0
    thumbnail: str = ""
    kind: str = "song"
    scene: str = ""
    source: str = ""
    added_ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Track":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in allowed})


# ---------------------------------------------------------------------------
# Conector YouTube Music (Innertube público)
# ---------------------------------------------------------------------------
class YouTubeMusicClient:
    """Cliente nativo de YouTube Music sin dependencias externas."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._search_cache: Dict[Tuple[str, str, int], Tuple[float, List[Track]]] = {}
        self._related_cache: Dict[str, Tuple[float, List[Track]]] = {}
        self._stream_cache: Dict[str, Tuple[float, str]] = {}
        self._request_count = 0
        self._last_error = ""

    # ------------------------- transporte -------------------------
    def _post(self, endpoint: str, payload: Dict[str, Any], timeout: float = 20.0) -> Dict[str, Any]:
        body = {
            "context": {
                "client": {
                    "clientName": CLIENT_NAME,
                    "clientVersion": CLIENT_VERSION,
                    "hl": "es",
                    "gl": "MX",
                }
            },
            **payload,
        }
        url = f"{YT_BASE}/youtubei/v1/{endpoint}?prettyPrint=false"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "Origin": YT_BASE,
                "Referer": f"{YT_BASE}/",
                "X-YouTube-Client-Name": "67",
                "X-YouTube-Client-Version": CLIENT_VERSION,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        with self._lock:
            self._request_count += 1
        return json.loads(raw.decode("utf-8", errors="replace"))

    # ------------------------- parseo -------------------------
    @staticmethod
    def _best_thumbnail(node: Any) -> str:
        best = ""
        best_area = -1
        for thumb in _find_values(node, "thumbnails", limit=200):
            if not isinstance(thumb, list):
                continue
            for t in thumb:
                if not isinstance(t, dict):
                    continue
                url = str(t.get("url") or "")
                if not url:
                    continue
                area = int(t.get("width") or 0) * int(t.get("height") or 0)
                if area >= best_area:
                    best_area = area
                    best = url
        return best

    @staticmethod
    def _video_meta(node: Dict[str, Any]) -> Tuple[Optional[str], str]:
        for we in _find_values(node, "watchEndpoint", limit=20):
            if not isinstance(we, dict):
                continue
            vid = we.get("videoId")
            if not vid:
                continue
            mvtype = ""
            try:
                mvtype = str(
                    we.get("REDACTED_TOKEN", {})
                    .get("watchEndpointMusicConfig", {})
                    .get("musicVideoType", "")
                )
            except Exception:
                mvtype = ""
            return str(vid), mvtype
        return None, ""

    @staticmethod
    def _browse_id(node: Dict[str, Any]) -> str:
        for be in _find_values(node, "browseEndpoint", limit=30):
            if isinstance(be, dict) and be.get("browseId"):
                return str(be["browseId"])
        return ""

    def _parse_responsive_item(self, item: Dict[str, Any], default_kind: str = "song") -> Optional[Track]:
        if not isinstance(item, dict):
            return None
        cols = item.get("flexColumns") or []
        texts: List[str] = []
        all_texts: List[str] = []
        for col in cols:
            renderer = (col or {}).get("REDACTED_TOKEN") or {}
            text_obj = renderer.get("text") or {}
            texts.append(_runs_text(text_obj).strip())
            for run in text_obj.get("runs", []) or []:
                if isinstance(run, dict) and run.get("text"):
                    all_texts.append(str(run["text"]).strip())

        title = texts[0] if texts else ""
        if not title:
            return None
        subtitle = texts[1] if len(texts) > 1 else ""

        video_id, mvtype = self._video_meta(item)
        browse_id = self._browse_id(item)

        kind = default_kind
        parts = [p.strip() for p in subtitle.split("•") if p.strip()]
        if parts and parts[0].lower() in _TYPE_WORDS:
            kind = _TYPE_WORDS[parts[0].lower()]
            parts = parts[1:]
        elif mvtype:
            kind = "song" if mvtype == "MUSIC_VIDEO_TYPE_ATV" else "video"

        # Duración: preferimos un token m:ss / h:mm:ss en el subtítulo.
        duration = ""
        for p in parts:
            if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", p):
                duration = p
                break
        if not duration:
            for p in all_texts:
                if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", p):
                    duration = p
                    break

        # Artista / álbum / vistas
        clean_parts = [
            p for p in parts
            if p and p != duration and not _is_views(p) and not re.fullmatch(r"\d{4}", p)
        ]
        artist = clean_parts[0] if clean_parts else ""
        album = ""
        if kind == "song" and len(clean_parts) > 1:
            album = clean_parts[1]
        elif kind == "album" and len(clean_parts) > 1:
            album = clean_parts[0]
        elif kind == "playlist" and len(clean_parts) > 1:
            album = ""

        if kind in ("album", "playlist", "artist") and not video_id:
            video_id = None  # type: ignore[assignment]

        return Track(
            video_id=video_id or "",
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            duration_seconds=_duration_to_seconds(duration),
            thumbnail=self._best_thumbnail(item),
            kind=kind,
            source=browse_id if kind in ("album", "playlist") else "",
        )

    def _parse_panel_item(self, item: Dict[str, Any]) -> Optional[Track]:
        if not isinstance(item, dict):
            return None
        vid = str(item.get("videoId") or "")
        if not vid:
            return None
        title = _runs_text(item.get("title") or {})
        byline = _runs_text(item.get("longBylineText") or item.get("shortBylineText") or {})
        length = _runs_text(item.get("lengthText") or {})
        parts = [p.strip() for p in byline.split("•") if p.strip()]
        artist = parts[0] if parts else ""
        album = ""
        if len(parts) > 1 and not re.fullmatch(r"\d{4}", parts[1]):
            album = parts[1]
        return Track(
            video_id=vid,
            title=title,
            artist=artist,
            album=album,
            duration=length,
            duration_seconds=_duration_to_seconds(length),
            thumbnail=self._best_thumbnail(item),
            kind="song",
            source="radio",
        )

    # ------------------------- API pública -------------------------
    def search(self, query: str, limit: int = 20, filter: str = "songs") -> List[Track]:
        query = (query or "").strip()
        if not query:
            return []
        filter = (filter or "songs").lower()
        limit = max(1, min(int(limit or 20), 50))
        if not re.fullmatch(r"[a-z]+", filter):
            filter = "all"

        cache_key = (query.lower(), filter, limit)
        with self._lock:
            cached = self._search_cache.get(cache_key)
            if cached and _now() - cached[0] < 300:
                return [Track.from_dict(t.to_dict()) for t in cached[1]]

        payload: Dict[str, Any] = {"query": query}
        if filter in SEARCH_FILTERS:
            payload["params"] = SEARCH_FILTERS[filter]
        default_kind = {
            "songs": "song",
            "videos": "video",
            "albums": "album",
            "playlists": "playlist",
            "artists": "artist",
        }.get(filter, "song")

        try:
            data = self._post("search", payload)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Búsqueda YouTube Music falló (%s): %s", query, exc)
            return []

        tracks: List[Track] = []
        seen: set = set()
        for item in _find_values(data, "musicResponsiveListItemRenderer", limit=200):
            if not isinstance(item, dict):
                continue
            track = self._parse_responsive_item(item, default_kind=default_kind)
            if not track:
                continue
            if filter in ("songs", "videos") and not track.video_id:
                continue
            if filter in ("songs", "videos") and track.kind != filter.rstrip("s"):
                # "videos" -> "video"; "songs" -> "song"
                if track.kind not in (filter, filter.rstrip("s")):
                    continue
            key = track.video_id or f"{track.kind}:{track.title}:{track.artist}"
            if key in seen:
                continue
            seen.add(key)
            tracks.append(track)
            if len(tracks) >= limit:
                break

        # Fallback: si el filtro estricto no devolvió nada, reintenta sin params.
        if not tracks and filter in SEARCH_FILTERS:
            try:
                data = self._post("search", {"query": query})
                for item in _find_values(data, "musicResponsiveListItemRenderer", limit=200):
                    track = self._parse_responsive_item(item, default_kind=default_kind)
                    if track and (track.video_id or track.kind in ("album", "playlist")):
                        key = track.video_id or f"{track.kind}:{track.title}:{track.artist}"
                        if key in seen:
                            continue
                        seen.add(key)
                        tracks.append(track)
                        if len(tracks) >= limit:
                            break
            except Exception as exc:
                logger.debug("Fallback de búsqueda falló: %s", exc)

        with self._lock:
            self._search_cache[cache_key] = (_now(), tracks)
        return tracks

    def suggest(self, query: str, limit: int = 8) -> List[str]:
        return [t.title for t in self.search(query, limit=limit, filter="all") if t.title]

    def related(self, video_id: str, limit: int = 30) -> List[Track]:
        """Radio infinita de YouTube Music para un videoId."""
        if not video_id:
            return []
        with self._lock:
            cached = self._related_cache.get(video_id)
            if cached and _now() - cached[0] < 600:
                return [Track.from_dict(t.to_dict()) for t in cached[1][:limit]]

        payload = {
            "videoId": video_id,
            "playlistId": f"RDAMVM{video_id}",
            "isAudioOnly": True,
            "enablePersistentPlaylistPanel": True,
        }
        try:
            data = self._post("next", payload)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Radio YouTube Music falló para %s: %s", video_id, exc)
            return []

        tracks: List[Track] = []
        seen = {video_id}
        for item in _find_values(data, "playlistPanelVideoRenderer", limit=200):
            track = self._parse_panel_item(item if isinstance(item, dict) else {})
            if not track or track.video_id in seen:
                continue
            seen.add(track.video_id)
            tracks.append(track)
            if len(tracks) >= limit:
                break

        with self._lock:
            self._related_cache[video_id] = (_now(), tracks)
        return tracks

    def collection_tracks(self, browse_id: str, limit: int = 50) -> List[Track]:
        """Extrae las pistas de un álbum o playlist por browseId."""
        if not browse_id:
            return []
        try:
            data = self._post("browse", {"browseId": browse_id})
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Browse de colección falló (%s): %s", browse_id, exc)
            return []
        tracks: List[Track] = []
        seen: set = set()
        for item in _find_values(data, "musicResponsiveListItemRenderer", limit=300):
            track = self._parse_responsive_item(item if isinstance(item, dict) else {}, default_kind="song")
            if not track or not track.video_id or track.video_id in seen:
                continue
            seen.add(track.video_id)
            tracks.append(track)
            if len(tracks) >= limit:
                break
        return tracks

    def oembed(self, video_id: str) -> Dict[str, Any]:
        try:
            url = (
                "https://www.youtube.com/oembed?format=json&url="
                + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}", safe="")
            )
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            return {}

    def resolve_audio(self, video_id: str, timeout: int = 45) -> Optional[str]:
        """Resuelve la URL de audio con yt-dlp, con caché de 25 minutos."""
        if not video_id:
            return None
        with self._lock:
            cached = self._stream_cache.get(video_id)
            if cached and _now() - cached[0] < 1500:
                return cached[1]

        ytdlp = shutil.which("yt-dlp")
        if not ytdlp:
            self._last_error = "yt-dlp no está instalado"
            return None

        cmd = [
            ytdlp,
            "-q",
            "--no-warnings",
            "--no-playlist",
            "-f",
            "bestaudio[ext=m4a]/bestaudio/best",
            "--get-url",
        ]
        if COOKIES_FILE.exists():
            cmd += ["--cookies", str(COOKIES_FILE)]
        cmd += ["--", f"{YT_BASE}/watch?v={video_id}"]

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                env={**os.environ, "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            )
        except subprocess.TimeoutExpired:
            self._last_error = "yt-dlp agotó el tiempo de resolución"
            return None
        except Exception as exc:
            self._last_error = f"yt-dlp: {exc}"
            return None

        url = ""
        for line in (res.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("http"):
                url = line
                break
        if not url:
            err = (res.stderr or "").strip().splitlines()
            self._last_error = err[-1] if err else f"yt-dlp rc={res.returncode}"
            logger.warning("No se pudo resolver audio %s: %s", video_id, self._last_error)
            return None

        with self._lock:
            self._stream_cache[video_id] = (_now(), url)
        return url

    def status(self) -> Dict[str, Any]:
        ytmusicapi_available = False
        try:
            import ytmusicapi  # type: ignore  # noqa: F401

            ytmusicapi_available = True
        except Exception:
            pass
        return {
            "connector": "YouTube Music · Innertube WEB_REMIX",
            "endpoint": YT_BASE,
            "authenticated": COOKIES_FILE.exists(),
            "cookies_file": str(COOKIES_FILE) if COOKIES_FILE.exists() else "",
            "ytmusicapi_available": ytmusicapi_available,
            "yt_dlp": shutil.which("yt-dlp") or "",
            "mpv": shutil.which("mpv") or "",
            "requests": self._request_count,
            "last_error": self._last_error,
            "cache": {
                "searches": len(self._search_cache),
                "radios": len(self._related_cache),
                "streams": len(self._stream_cache),
            },
        }


# ---------------------------------------------------------------------------
# Motor mpv con IPC
# ---------------------------------------------------------------------------
class MpvController:
    """Control de mpv headless mediante su socket JSON IPC."""

    def __init__(self, socket_path: Path, log_path: Path) -> None:
        self.socket_path = socket_path
        self.log_path = log_path
        self._proc: Optional[subprocess.Popen] = None
        self._log_fh = None
        self._lock = threading.Lock()
        self._request_id = 0
        self.start_time = 0.0
        self.last_error = ""

    def is_alive(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        # Puede existir un mpv soberano de otro proceso (daemon) usando el mismo socket.
        return self.ping(timeout=0.6)

    def ping(self, timeout: float = 1.0) -> bool:
        if not self.socket_path.exists():
            return False
        res = self._command("get_property", "idle-active", timeout=timeout)
        return bool(isinstance(res, dict) and res.get("error") in (None, "success"))

    def _command(self, *args: Any, timeout: float = 4.0) -> Optional[Dict[str, Any]]:
        if not self.socket_path.exists():
            return None
        with self._lock:
            self._request_id += 1
            req_id = self._request_id
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(str(self.socket_path))
                payload = json.dumps({"command": list(args), "request_id": req_id}) + "\n"
                sock.sendall(payload.encode("utf-8"))
                buffer = b""
                deadline = _now() + timeout
                while _now() < deadline and len(buffer) < (1 << 20):
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line.decode("utf-8", errors="replace"))
                        except Exception:
                            continue
                        if isinstance(data, dict) and data.get("request_id") == req_id:
                            return data
                        # Ignorar eventos de mpv de otras suscripciones.
                try:
                    data = json.loads(buffer.decode("utf-8", errors="replace") or "{}")
                    if isinstance(data, dict) and data.get("request_id") == req_id:
                        return data
                except Exception:
                    pass
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        return None

    def get_property(self, name: str, timeout: float = 2.5) -> Any:
        res = self._command("get_property", name, timeout=timeout)
        if isinstance(res, dict) and res.get("error") in (None, "success"):
            return res.get("data")
        return None

    def set_property(self, name: str, value: Any, timeout: float = 2.5) -> bool:
        res = self._command("set_property", name, value, timeout=timeout)
        return bool(isinstance(res, dict) and res.get("error") in (None, "success"))

    def start(self, volume: int = 45, audio_device: Optional[str] = None) -> bool:
        if self.is_alive():
            return True
        mpv = shutil.which("mpv")
        if not mpv:
            self.last_error = "mpv no está instalado"
            return False
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except Exception:
            pass

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._log_fh = open(self.log_path, "ab", buffering=0)
        except Exception:
            self._log_fh = None

        cmd = [
            mpv,
            "--no-config",
            "--idle=yes",
            "--no-video",
            "--audio-display=no",
            "--no-terminal",
            "--really-quiet",
            f"--input-ipc-server={self.socket_path}",
            "--ytdl-format=bestaudio/best",
            "--cache=yes",
            "--cache-pause=no",
            "--network-timeout=25",
            "--audio-client-name=TARDIS Music Maestro",
            f"--volume={max(0, min(int(volume), 130))}",
        ]
        if audio_device:
            cmd.append(f"--audio-device={audio_device}")

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=self._log_fh or subprocess.DEVNULL,
                stderr=self._log_fh or subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:
            self.last_error = f"No se pudo iniciar mpv: {exc}"
            logger.error(self.last_error)
            return False

        self.start_time = _now()
        for _ in range(120):
            if self.socket_path.exists():
                # Verifica que el socket acepte conexiones.
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                        probe.settimeout(0.2)
                        probe.connect(str(self.socket_path))
                    return True
                except Exception:
                    pass
            if self._proc.poll() is not None:
                self.last_error = f"mpv terminó con código {self._proc.returncode}"
                break
            time.sleep(0.05)
        self.last_error = self.last_error or "mpv no abrió el socket IPC"
        logger.error(self.last_error)
        return False

    def load(self, url: str, pause: bool = False) -> bool:
        res = self._command("loadfile", url, "replace", timeout=8)
        ok = bool(isinstance(res, dict) and res.get("error") in (None, "success"))
        if ok and pause:
            self.set_property("pause", True)
        return ok

    def stop(self) -> None:
        self._command("stop")

    def pause(self) -> None:
        self.set_property("pause", True)

    def resume(self) -> None:
        self.set_property("pause", False)

    def quit(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._command("quit", timeout=2)
            except Exception:
                pass
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
        if self._log_fh:
            try:
                self._log_fh.close()
            except Exception:
                pass
            self._log_fh = None

    def status(self) -> Dict[str, Any]:
        if not self.is_alive():
            return {
                "alive": False,
                "idle": True,
                "paused": False,
                "time_pos": 0.0,
                "duration": 0.0,
                "volume": None,
                "media_title": "",
                "path": "",
            }
        return {
            "alive": True,
            "idle": bool(self.get_property("idle-active", timeout=1.5)),
            "paused": bool(self.get_property("pause", timeout=1.5)),
            "time_pos": float(self.get_property("time-pos", timeout=1.5) or 0.0),
            "duration": float(self.get_property("duration", timeout=1.5) or 0.0),
            "volume": self.get_property("volume", timeout=1.5),
            "media_title": str(self.get_property("media-title", timeout=1.5) or ""),
            "path": str(self.get_property("path", timeout=1.5) or ""),
        }


# ---------------------------------------------------------------------------
# Orquestador soberano
# ---------------------------------------------------------------------------
class TardisMusicMaestro:
    """Cerebro musical de TARDIS: búsqueda, cola, soundtrack y API."""

    _instance: Optional["TardisMusicMaestro"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TardisMusicMaestro":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._soundtrack_lock = threading.Lock()
        self.client = YouTubeMusicClient()
        socket_dir = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
        self.socket_path = socket_dir / f"tardis-music-mpv-{os.getuid()}.sock"
        self.mpv = MpvController(self.socket_path, MPV_LOG)
        self.state = self._load_state()
        self.started_ts = _now()
        self._soundtrack_busy = False
        self._soundtrack_status = "idle"
        self._last_error = ""
        self._saw_playback = False
        self._load_ts = 0.0
        self._playing_since = 0.0
        self._suppress_autopilot_until = 0.0
        self._last_autopilot_try = 0.0
        self._dirty = False
        self._duck_until = 0.0
        self._duck_prev_volume: Optional[int] = None
        self.favorites = _read_json(FAVORITES_FILE, {})
        self.daemon_mode = False
        self._monitor_started = False
        logger.info("TARDIS Music Maestro inicializado (cola=%d)", len(self.state.get("queue", [])))

    def start_monitor(self) -> None:
        """Activa el bucle de fondo (solo el daemon soberano lo hace)."""
        if self._monitor_started:
            return
        self._monitor_started = True
        threading.Thread(
            target=self._monitor_loop, name="MusicMaestroMonitor", daemon=True
        ).start()

    # ------------------------- estado -------------------------
    def _load_state(self) -> Dict[str, Any]:
        data = _read_json(STATE_FILE, {})
        state = dict(DEFAULT_STATE)
        if isinstance(data, dict):
            state.update({k: v for k, v in data.items() if k in DEFAULT_STATE})
        queue: List[Dict[str, Any]] = []
        for item in state.get("queue", []):
            if isinstance(item, dict) and item.get("video_id"):
                queue.append(Track.from_dict(item).to_dict())
        state["queue"] = queue
        try:
            state["index"] = max(-1, min(int(state.get("index", -1)), len(queue) - 1))
        except Exception:
            state["index"] = -1
        state["volume"] = max(0, min(int(state.get("volume", 45) or 45), 130))
        state.setdefault("created_ts", _now())
        return state

    def _save_state(self, force: bool = False) -> None:
        with self._lock:
            self.state["updated_ts"] = _now()
            _atomic_json(STATE_FILE, self.state)
            self._dirty = False

    # ------------------------- utilidades internas -------------------------
    def _current_track(self) -> Optional[Track]:
        with self._lock:
            queue = self.state.get("queue", [])
            idx = self.state.get("index", -1)
            if 0 <= idx < len(queue):
                return Track.from_dict(queue[idx])
        return None

    def _next_track(self) -> Optional[Track]:
        with self._lock:
            queue = self.state.get("queue", [])
            idx = self.state.get("index", -1)
            if 0 <= idx + 1 < len(queue):
                return Track.from_dict(queue[idx + 1])
        return None

    def _record_history(self, track: Track, event: str = "play") -> None:
        try:
            entry = {
                "ts": _now(),
                "iso": _iso(),
                "event": event,
                "video_id": track.video_id,
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "scene": track.scene or self.state.get("scene", ""),
                "kind": track.kind,
            }
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(HISTORY_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.debug("No se pudo registrar historial: %s", exc)

    def _set_error(self, message: str) -> None:
        self._last_error = message
        self._soundtrack_status = "error"
        logger.warning("Music Maestro: %s", message)

    # ------------------------- reproducción -------------------------
    def _ensure_mpv(self) -> bool:
        with self._lock:
            volume = int(self.state.get("volume", 45))
        if self.mpv.is_alive():
            return True
        audio_device = (os.environ.get("TARDIS_MUSIC_AUDIO_DEVICE") or "").strip() or None
        ok = self.mpv.start(volume=volume, audio_device=audio_device)
        if not ok:
            self._set_error(self.mpv.last_error or "mpv no disponible")
        return ok

    def play_track(self, track: Track, index: Optional[int] = None) -> Dict[str, Any]:
        if not track or not track.video_id:
            return {"status": "error", "error": "Pista inválida"}
        if not self._ensure_mpv():
            return {"status": "error", "error": self.mpv.last_error or "mpv no disponible"}

        track.scene = track.scene or str(self.state.get("scene", ""))
        url = self.client.resolve_audio(track.video_id)
        if not url:
            # Fallback: mpv resuelve YouTube con su hook yt-dlp.
            url = f"{YT_BASE}/watch?v={track.video_id}"
            logger.info("Usando fallback yt-dlp de mpv para %s (%s)", track.title, track.video_id)

        ok = self.mpv.load(url)
        if not ok:
            self._set_error("mpv no pudo cargar la pista")
            return {"status": "error", "error": self._last_error}

        with self._lock:
            if index is not None:
                self.state["index"] = int(index)
            self.state["user_paused"] = False
            self.state["updated_ts"] = _now()
            self._dirty = True
        self._set_volume(int(self.state.get("volume", 45)), persist=False)
        self._playing_since = _now()
        self._load_ts = _now()
        self._saw_playback = False
        self._record_history(track)
        self._save_state()
        self._soundtrack_status = "playing"
        logger.info("▶ %s — %s (%s)", track.title, track.artist or "?", track.video_id)
        return {
            "status": "ok",
            "playing": track.to_dict(),
            "index": self.state.get("index", -1),
            "resolved": bool(url.startswith("http") and "googlevideo" in url),
        }

    def play_index(self, index: int) -> Dict[str, Any]:
        with self._lock:
            queue = self.state.get("queue", [])
            if not (0 <= index < len(queue)):
                return {"status": "error", "error": "Índice fuera de la cola"}
            self.state["index"] = index
            track = Track.from_dict(queue[index])
        return self.play_track(track, index=index)

    def play_query(self, query: str, filter: str = "songs", limit: int = 12) -> Dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"status": "error", "error": "Consulta vacía"}

        video_id = _extract_video_id(query)
        if video_id:
            meta = self.client.oembed(video_id)
            track = Track(
                video_id=video_id,
                title=str(meta.get("title") or f"YouTube Music · {video_id}"),
                artist=str(meta.get("author_name") or ""),
                thumbnail=str(meta.get("thumbnail_url") or ""),
                kind="song",
                source="url",
            )
            with self._lock:
                self.state["queue"] = [track.to_dict()]
                self.state["index"] = 0
                self.state["scene"] = self.state.get("scene", "focus")
            return self.play_track(track, index=0)

        tracks = self.client.search(query, limit=limit, filter=filter)
        if not tracks:
            tracks = self.client.search(query, limit=limit, filter="all")
            tracks = [t for t in tracks if t.video_id]
        if not tracks:
            return {"status": "error", "error": f"Sin resultados para '{query}'"}

        with self._lock:
            self.state["queue"] = [t.to_dict() for t in tracks]
            self.state["index"] = 0
            self._dirty = True
        result = self.play_track(tracks[0], index=0)
        result["queue_size"] = len(tracks)
        result["query"] = query
        return result

    def pause(self) -> Dict[str, Any]:
        self._ensure_mpv()
        self.mpv.pause()
        with self._lock:
            self.state["user_paused"] = True
        self._soundtrack_status = "paused"
        self._save_state()
        return {"status": "ok", "action": "pause"}

    def resume(self) -> Dict[str, Any]:
        if not self._ensure_mpv():
            return {"status": "error", "error": self.mpv.last_error}
        self.mpv.resume()
        with self._lock:
            self.state["user_paused"] = False
        self._soundtrack_status = "playing"
        self._save_state()
        return {"status": "ok", "action": "resume"}

    def toggle(self) -> Dict[str, Any]:
        st = self.mpv.status()
        if st.get("alive") and not st.get("idle"):
            if st.get("paused"):
                return self.resume()
            return self.pause()
        # Sin pista activa: intenta continuar la cola o el soundtrack.
        if self.state.get("queue"):
            idx = int(self.state.get("index", -1))
            if idx < 0:
                idx = 0
            result = self.play_index(idx)
            if result.get("status") == "ok":
                return result
        return self.start_soundtrack(self.scene_for_context())

    def stop(self) -> Dict[str, Any]:
        if self.mpv.is_alive():
            self.mpv.stop()
        with self._lock:
            self.state["user_paused"] = True
            self._dirty = True
        self._suppress_autopilot_until = _now() + 180
        self._soundtrack_status = "stopped"
        self._playing_since = 0
        self._save_state()
        return {"status": "ok", "action": "stop", "autopilot_suppressed_for": 180}

    def next(self, auto: bool = False) -> Dict[str, Any]:
        with self._lock:
            queue = self.state.get("queue", [])
            idx = int(self.state.get("index", -1))
            repeat = self.state.get("repeat", "off")
            shuffle = bool(self.state.get("shuffle", False))
            autoplay_radio = bool(self.state.get("autoplay_radio", True))
            current = Track.from_dict(queue[idx]) if 0 <= idx < len(queue) else None

        if repeat == "one" and auto and current:
            return self.play_track(current, index=idx)
        if shuffle and len(queue) > 1:
            choices = [i for i in range(len(queue)) if i != idx]
            return self.play_index(random.choice(choices))
        if idx + 1 < len(queue):
            return self.play_index(idx + 1)

        # Fin de cola: extiende con radio si está permitido.
        if autoplay_radio and current:
            radio = self.client.related(current.video_id, limit=25)
            existing = {t.get("video_id") for t in queue}
            new_tracks = [t for t in radio if t.video_id not in existing]
            if new_tracks:
                with self._lock:
                    self.state["queue"].extend(t.to_dict() for t in new_tracks)
                    self.state["index"] = idx + 1
                    self._dirty = True
                return self.play_index(idx + 1)

        if repeat == "all" and queue:
            return self.play_index(0)

        self._soundtrack_status = "idle"
        if auto:
            return self.start_soundtrack(self.scene_for_context())
        return {"status": "ok", "action": "next", "finished": True}

    def previous(self) -> Dict[str, Any]:
        with self._lock:
            idx = int(self.state.get("index", -1))
        return self.play_index(max(0, idx - 1))

    def seek(self, seconds: float) -> Dict[str, Any]:
        self._ensure_mpv()
        res = self.mpv._command("seek", float(seconds), "absolute")
        ok = bool(isinstance(res, dict) and res.get("error") in (None, "success"))
        return {"status": "ok" if ok else "error", "action": "seek", "value": seconds}

    def _set_volume(self, value: int, persist: bool = True) -> int:
        value = max(0, min(int(value), 130))
        if self.mpv.is_alive():
            self.mpv.set_property("volume", value)
        with self._lock:
            self.state["volume"] = value
            self._dirty = True
        if persist:
            self._save_state()
        return value

    def set_volume(self, value: int) -> Dict[str, Any]:
        return {"status": "ok", "volume": self._set_volume(value)}

    def duck(self, seconds: int = 10, volume: int = 12) -> Dict[str, Any]:
        with self._lock:
            prev = int(self.state.get("volume", 45))
            if self._duck_until < _now():
                self._duck_prev_volume = prev
            self._duck_until = _now() + max(1, int(seconds))
        if self.mpv.is_alive():
            self.mpv.set_property("volume", max(0, min(int(volume), 130)))
        return {
            "status": "ok",
            "action": "duck",
            "seconds": seconds,
            "restore_volume": self._duck_prev_volume or prev,
        }

    def unduck(self) -> Dict[str, Any]:
        restore = self._duck_prev_volume
        self._duck_until = 0
        self._duck_prev_volume = None
        if restore is not None:
            self._set_volume(restore)
        return {"status": "ok", "action": "unduck", "volume": restore}

    # ------------------------- cola -------------------------
    def queue_add(self, query: str, filter: str = "songs", limit: int = 1) -> Dict[str, Any]:
        tracks = self.client.search(query, limit=max(1, limit), filter=filter)
        if not tracks:
            return {"status": "error", "error": f"Sin resultados para '{query}'"}
        with self._lock:
            self.state["queue"].extend(t.to_dict() for t in tracks)
            self._dirty = True
        self._save_state()
        return {"status": "ok", "added": [t.to_dict() for t in tracks], "queue_size": len(self.state["queue"])}

    def queue_remove(self, index: int) -> Dict[str, Any]:
        with self._lock:
            queue = self.state.get("queue", [])
            if not (0 <= index < len(queue)):
                return {"status": "error", "error": "Índice fuera de la cola"}
            removed = queue.pop(index)
            if self.state.get("index", -1) >= index:
                self.state["index"] = max(-1, self.state["index"] - 1)
            self._dirty = True
        self._save_state()
        return {"status": "ok", "removed": removed, "queue_size": len(self.state["queue"])}

    def queue_clear(self) -> Dict[str, Any]:
        with self._lock:
            self.state["queue"] = []
            self.state["index"] = -1
            self._dirty = True
        self._save_state()
        return {"status": "ok", "action": "clear"}

    # ------------------------- soundtrack -------------------------
    @staticmethod
    def scene_for_context() -> str:
        env_scene = (os.environ.get("TARDIS_MUSIC_SCENE") or "").strip().lower()
        if env_scene in SCENES:
            return env_scene

        # Estado de continuidad de TARDIS: adapta la escena al contexto real.
        cont = _read_json(BASE_DIR / "data" / "continuity_state.json", {})
        phase_blob = " ".join(str(cont.get(k, "")) for k in ("status", "phase")).lower()
        request_blob = str(cont.get("current_request", "")).lower()
        goal_blob = str(cont.get("architect_goal", "")).lower()
        if any(word in phase_blob for word in ("error", "fallo", "blocked", "bloqueado", "critical")):
            return "calm"
        if any(word in request_blob for word in ("visual", "imagen", "veredicto", "cámara", "camara")):
            return "discovery"
        if any(word in request_blob for word in ("social", "publica", "x.com", "tiktok")):
            return "epic"
        if any(word in request_blob for word in ("música", "musica", "soundtrack", "playlist")):
            return "focus"
        if any(word in request_blob for word in ("regener", "reinicio", "reboot", "renacer")):
            return "doctor"
        if any(word in request_blob for word in ("calma", "descanso", "reparación", "reparacion")):
            return "calm"
        if not request_blob and any(word in goal_blob for word in ("regener", "reinicio")):
            return "doctor"

        hour = datetime.now().hour
        if 5 <= hour < 8:
            return "discovery"
        if 8 <= hour < 12:
            return "focus"
        if 12 <= hour < 15:
            return "creative"
        if 15 <= hour < 19:
            return "epic"
        if 19 <= hour < 22:
            return "night"
        return "calm"

    def scene_info(self) -> List[Dict[str, Any]]:
        out = []
        for key, cfg in SCENES.items():
            out.append(
                {
                    "id": key,
                    "name": cfg["name"],
                    "emoji": cfg["emoji"],
                    "description": cfg["description"],
                    "queries": list(cfg["queries"]),
                }
            )
        return out

    @staticmethod
    def _score_track(track: Track, seed: str) -> float:
        """Puntúa la relevancia de una pista respecto a la semilla de búsqueda."""
        stop = {
            "the", "and", "for", "with", "from", "music", "musica", "música",
            "soundtrack", "banda", "sonora", "original", "motion", "picture",
            "del", "los", "las", "una", "uno", "que", "por", "para",
        }
        tokens = [
            w for w in re.findall(r"[a-z0-9áéíóúñü]+", seed.lower())
            if len(w) > 2 and w not in stop
        ]
        blob = f"{track.title} {track.artist} {track.album}".lower()
        score = 0.0
        for token in tokens:
            if token in blob:
                score += 2.0
            if track.artist and token in track.artist.lower():
                score += 2.5
        for bad in ("karaoke", "8-bit", "chiptune", "cover", "remix", "slowed", "nightcore", "reverb"):
            if bad in blob and bad not in seed.lower():
                score -= 3.0
        if track.duration_seconds and track.duration_seconds < 60:
            score -= 1.5
        return score

    def _build_soundtrack_queue(self, scene: str, size: int = 15) -> List[Track]:
        cfg = SCENES.get(scene) or SCENES["focus"]
        seeds = list(cfg["queries"])
        random.shuffle(seeds)
        candidates: List[Tuple[float, Track]] = []
        seen: set = set()

        for seed in seeds:
            if len(candidates) >= size * 2:
                break
            results = self.client.search(seed, limit=10, filter="songs")
            if not results:
                results = [t for t in self.client.search(seed, limit=10, filter="all") if t.video_id]
            results = sorted(
                results, key=lambda t: self._score_track(t, seed), reverse=True
            )
            taken = 0
            for track in results:
                if track.video_id in seen:
                    continue
                seen.add(track.video_id)
                track.scene = scene
                track.source = track.source or f"scene:{scene}"
                candidates.append((self._score_track(track, seed), track))
                taken += 1
                if taken >= 3:
                    break

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [track for _score, track in candidates[:size]]

    def start_soundtrack(self, scene: Optional[str] = None, auto: bool = False) -> Dict[str, Any]:
        scene = (scene or self.state.get("scene") or self.scene_for_context()).lower()
        if scene not in SCENES:
            return {"status": "error", "error": f"Escena desconocida '{scene}'", "scenes": list(SCENES)}

        if not self._soundtrack_lock.acquire(blocking=False):
            return {
                "status": "building",
                "scene": scene,
                "message": "Ya hay un soundtrack en construcción",
            }
        self._soundtrack_busy = True
        self._soundtrack_status = "building"
        with self._lock:
            self.state["scene"] = scene
            self.state["last_scene"] = scene
            self._dirty = True

        def _worker() -> None:
            try:
                logger.info("Construyendo soundtrack '%s'…", scene)
                tracks = self._build_soundtrack_queue(scene)
                if not tracks:
                    raise RuntimeError("YouTube Music no devolvió pistas para la escena")
                with self._lock:
                    self.state["queue"] = [t.to_dict() for t in tracks]
                    self.state["index"] = 0
                    self.state["user_paused"] = False
                    self.state["autopilot"] = bool(self.state.get("autopilot") or auto)
                    self._dirty = True
                self._save_state()
                result = self.play_track(tracks[0], index=0)
                if result.get("status") != "ok":
                    raise RuntimeError(result.get("error", "No se pudo reproducir"))
                self._soundtrack_status = "playing"
                logger.info("Soundtrack '%s' listo: %d pistas", scene, len(tracks))
            except Exception as exc:
                self._set_error(f"Soundtrack '{scene}': {exc}")
            finally:
                self._soundtrack_busy = False
                try:
                    self._soundtrack_lock.release()
                except RuntimeError:
                    pass

        threading.Thread(target=_worker, name=f"Soundtrack-{scene}", daemon=True).start()
        return {
            "status": "building",
            "scene": scene,
            "scene_name": SCENES[scene]["name"],
            "auto": auto,
            "track_count_target": 15,
        }

    def stop_soundtrack(self) -> Dict[str, Any]:
        with self._lock:
            self.state["autopilot"] = False
            self._dirty = True
        self._save_state()
        return self.stop() | {"autopilot": False}

    # ------------------------- consultas -------------------------
    def search(self, query: str, limit: int = 20, filter: str = "songs") -> Dict[str, Any]:
        tracks = self.client.search(query, limit=limit, filter=filter)
        return {
            "status": "ok",
            "query": query,
            "filter": filter,
            "count": len(tracks),
            "results": [t.to_dict() for t in tracks],
        }

    def history(self, limit: int = 30) -> List[Dict[str, Any]]:
        if not HISTORY_FILE.exists():
            return []
        try:
            lines = HISTORY_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        for line in reversed(lines[-max(1, limit * 3):]):
            try:
                out.append(json.loads(line))
            except Exception:
                continue
            if len(out) >= limit:
                break
        return out

    def toggle_favorite(self, track: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not track:
            cur = self._current_track()
            track = cur.to_dict() if cur else None
        if not track or not track.get("video_id"):
            return {"status": "error", "error": "No hay pista para marcar"}
        vid = str(track["video_id"])
        with self._lock:
            if vid in self.favorites:
                removed = self.favorites.pop(vid)
                action = "removed"
            else:
                self.favorites[vid] = {
                    "video_id": vid,
                    "title": track.get("title", ""),
                    "artist": track.get("artist", ""),
                    "album": track.get("album", ""),
                    "duration": track.get("duration", ""),
                    "thumbnail": track.get("thumbnail", ""),
                    "added_ts": _now(),
                }
                action = "added"
            _atomic_json(FAVORITES_FILE, self.favorites)
        return {"status": "ok", "action": action, "video_id": vid, "total": len(self.favorites)}

    def favorites_list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(self.favorites.values(), key=lambda x: x.get("added_ts", 0), reverse=True)

    def status(self) -> Dict[str, Any]:
        mpv_status = self.mpv.status()
        with self._lock:
            queue = [Track.from_dict(t) for t in self.state.get("queue", [])]
            idx = int(self.state.get("index", -1))
            current = queue[idx] if 0 <= idx < len(queue) else None
            upcoming = queue[idx + 1: idx + 7] if idx >= 0 else queue[:6]
            state = dict(self.state)
            favorites_count = len(self.favorites)

        current_dict = current.to_dict() if current else None
        duration = mpv_status.get("duration") or (current.duration_seconds if current else 0)
        tpos = mpv_status.get("time_pos") or 0
        media_title = _clean_media_title(mpv_status.get("media_title", ""), current)
        return {
            "status": "ok",
            "engine": "TARDIS Music Maestro v1.0",
            "server_time": _iso(),
            "uptime_seconds": round(_now() - self.started_ts, 1),
            "playback": {
                "mpv_alive": mpv_status.get("alive", False),
                "idle": mpv_status.get("idle", True),
                "paused": mpv_status.get("paused", False),
                "playing": bool(mpv_status.get("alive") and not mpv_status.get("idle")),
                "time_pos": tpos,
                "time_pos_text": _fmt_seconds(tpos),
                "duration": duration,
                "duration_text": _fmt_seconds(duration),
                "progress": round((tpos / duration) * 100, 1) if duration else 0.0,
                "volume": state.get("volume", 45),
                "mpv_volume": mpv_status.get("volume"),
                "media_title": media_title,
                "socket": str(self.socket_path),
            },
            "current": current_dict,
            "queue": {
                "length": len(queue),
                "index": idx,
                "upcoming": [t.to_dict() for t in upcoming],
                "repeat": state.get("repeat", "off"),
                "shuffle": bool(state.get("shuffle", False)),
                "autoplay_radio": bool(state.get("autoplay_radio", True)),
                "autopilot": bool(state.get("autopilot", False)),
            },
            "scene": state.get("scene", "focus"),
            "scene_name": SCENES.get(state.get("scene", "focus"), {}).get("name", ""),
            "context_scene": self.scene_for_context(),
            "soundtrack": {
                "busy": self._soundtrack_busy,
                "status": self._soundtrack_status,
                "last_error": self._last_error,
            },
            "connector": self.client.status(),
            "favorites_count": favorites_count,
            "duck": {
                "active": self._duck_until > _now(),
                "until": _iso(self._duck_until) if self._duck_until > _now() else "",
            },
        }

    def doctor(self) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []

        def add(name: str, ok: bool, detail: str = "") -> None:
            checks.append({"check": name, "ok": bool(ok), "detail": detail})

        add("yt-dlp", bool(shutil.which("yt-dlp")), shutil.which("yt-dlp") or "no encontrado")
        add("mpv", bool(shutil.which("mpv")), shutil.which("mpv") or "no encontrado")
        add("data_dir", os.access(DATA_DIR, os.W_OK), str(DATA_DIR))
        add("config_dir", os.access(CONFIG_DIR, os.W_OK), str(CONFIG_DIR))
        add("dashboard", DASHBOARD_FILE.exists(), str(DASHBOARD_FILE))
        add("mpv_socket", True, str(self.socket_path))
        add("mpv_alive", self.mpv.is_alive(), self.mpv.last_error or "ok")
        try:
            req = urllib.request.Request(f"{YT_BASE}/", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                add("youtube_music_http", resp.status == 200, f"HTTP {resp.status}")
        except Exception as exc:
            add("youtube_music_http", False, f"{type(exc).__name__}: {exc}")
        try:
            results = self.client.search("Hans Zimmer Time", limit=1, filter="songs")
            add("youtube_music_search", bool(results), f"{len(results)} resultado(s)")
        except Exception as exc:
            add("youtube_music_search", False, str(exc))
        ok = all(c["ok"] for c in checks if c["check"] not in ("mpv_alive",))
        return {"status": "ok" if ok else "degraded", "checks": checks}

    # ------------------------- bucle de fondo -------------------------
    def _monitor_loop(self) -> None:
        tick = 0
        while True:
            try:
                time.sleep(1.0)
                tick += 1
                self._tick()
                if tick % 30 == 0 and self._dirty:
                    self._save_state()
            except Exception as exc:
                logger.debug("Monitor music loop: %s", exc)

    def _tick(self) -> None:
        # Restauración de volumen tras ducking.
        if self._duck_until and _now() >= self._duck_until:
            if self._duck_prev_volume is not None:
                self._set_volume(self._duck_prev_volume, persist=False)
            self._duck_until = 0
            self._duck_prev_volume = None

        st = self.mpv.status() if self.mpv.is_alive() else {"alive": False, "idle": True}
        alive = bool(st.get("alive"))
        idle = bool(st.get("idle", True))

        if alive and not idle:
            if (st.get("time_pos") or 0) > 0.2:
                self._saw_playback = True
        elif alive and idle and self._saw_playback:
            # Fin de pista detectado.
            self._saw_playback = False
            if not self.state.get("user_paused"):
                logger.info("Pista finalizada; avanzando…")
                self.next(auto=True)
            return

        # Autopilot: soundtrack automático si no hay reproducción.
        with self._lock:
            autopilot = bool(self.state.get("autopilot", False))
            user_paused = bool(self.state.get("user_paused", False))
            scene = str(self.state.get("scene", "focus"))
        if (
            self.daemon_mode
            and autopilot
            and not user_paused
            and not self._soundtrack_busy
            and _now() >= self._suppress_autopilot_until
            and _now() - self._last_autopilot_try > 20
            and (not alive or idle)
        ):
            self._last_autopilot_try = _now()
            target_scene = self.scene_for_context() or scene
            logger.info("Autopilot: iniciando soundtrack '%s'", target_scene)
            self.start_soundtrack(target_scene, auto=True)

    # ------------------------- apagado -------------------------
    def shutdown(self) -> None:
        self._save_state()
        self.mpv.quit()


# ---------------------------------------------------------------------------
# API HTTP + dashboard
# ---------------------------------------------------------------------------
class MusicAPIHandler(BaseHTTPRequestHandler):
    server_version = "TARDIS-Music/1.0"
    engine: TardisMusicMaestro = None  # type: ignore[assignment]

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("API %s - %s", self.address_string(), fmt % args)

    # ------------------------- helpers -------------------------
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-TARDIS-Token")

    def _authorized(self) -> bool:
        token = os.environ.get("TARDIS_MUSIC_TOKEN", "").strip()
        if not token:
            return True
        provided = self.headers.get("X-TARDIS-Token", "")
        if not provided:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            provided = (qs.get("token") or [""])[0]
        return provided == token

    def _send_json(self, payload: Any, code: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, html: str, code: int = 200) -> None:
        raw = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > 2_000_000:
                return {}
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _qs(path: str) -> Dict[str, List[str]]:
        return urllib.parse.parse_qs(urllib.parse.urlparse(path).query)

    # ------------------------- rutas -------------------------
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._send_json({"status": "error", "error": "unauthorized"}, 401)
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = self._qs(self.path)

        try:
            if path in ("/", "/dashboard", "/index.html"):
                if DASHBOARD_FILE.exists():
                    return self._send_html(DASHBOARD_FILE.read_text(encoding="utf-8"))
                return self._send_html(
                    "<h1>TARDIS Music Maestro</h1><p>Dashboard no encontrado.</p>", 200
                )
            if path == "/api/health":
                return self._send_json({"status": "ok", "engine": "TARDIS Music Maestro"})
            if path == "/api/status":
                return self._send_json(self.engine.status())
            if path == "/api/scenes":
                return self._send_json(
                    {
                        "status": "ok",
                        "scenes": self.engine.scene_info(),
                        "context": self.engine.scene_for_context(),
                    }
                )
            if path == "/api/search":
                query = (qs.get("q") or [""])[0]
                limit = int((qs.get("limit") or ["20"])[0])
                filt = (qs.get("filter") or ["songs"])[0]
                return self._send_json(self.engine.search(query, limit=limit, filter=filt))
            if path == "/api/suggest":
                query = (qs.get("q") or [""])[0]
                return self._send_json(
                    {"status": "ok", "suggestions": self.engine.client.suggest(query, limit=8)}
                )
            if path == "/api/queue":
                st = self.engine.status()
                return self._send_json({"status": "ok", **st["queue"], "current": st["current"]})
            if path == "/api/favorites":
                return self._send_json(
                    {"status": "ok", "favorites": self.engine.favorites_list()}
                )
            if path == "/api/history":
                limit = int((qs.get("limit") or ["30"])[0])
                return self._send_json(
                    {"status": "ok", "history": self.engine.history(limit=limit)}
                )
            if path == "/api/doctor":
                return self._send_json(self.engine.doctor())
            if path == "/api/connector":
                return self._send_json({"status": "ok", **self.engine.client.status()})
            return self._send_json({"status": "error", "error": "not found"}, 404)
        except Exception as exc:
            logger.exception("API GET %s", path)
            return self._send_json({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._send_json({"status": "error", "error": "unauthorized"}, 401)
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        body = self._read_body()
        eng = self.engine

        try:
            if path == "/api/play":
                query = str(body.get("query") or body.get("q") or "").strip()
                video_id = str(body.get("video_id") or "").strip()
                if video_id:
                    meta = eng.client.oembed(video_id)
                    track = Track(
                        video_id=video_id,
                        title=str(meta.get("title") or f"YouTube Music · {video_id}"),
                        artist=str(meta.get("author_name") or ""),
                        thumbnail=str(meta.get("thumbnail_url") or ""),
                        source="api",
                    )
                    with eng._lock:
                        eng.state["queue"] = [track.to_dict()]
                        eng.state["index"] = 0
                    return self._send_json(eng.play_track(track, index=0))
                if not query:
                    return self._send_json(
                        {"status": "error", "error": "Falta 'query' o 'video_id'"}, 400
                    )
                filter_ = str(body.get("filter") or "songs")
                return self._send_json(eng.play_query(query, filter=filter_))

            if path == "/api/control":
                action = str(body.get("action") or "").lower()
                value = body.get("value")
                if action in ("play", "resume"):
                    return self._send_json(eng.resume())
                if action == "pause":
                    return self._send_json(eng.pause())
                if action == "toggle":
                    return self._send_json(eng.toggle())
                if action == "next":
                    return self._send_json(eng.next())
                if action == "previous" or action == "prev":
                    return self._send_json(eng.previous())
                if action == "stop":
                    return self._send_json(eng.stop())
                if action == "volume":
                    return self._send_json(eng.set_volume(int(value or 50)))
                if action == "seek":
                    return self._send_json(eng.seek(float(value or 0)))
                if action == "repeat":
                    mode = str(value or "off").lower()
                    if mode not in ("off", "one", "all"):
                        return self._send_json(
                            {"status": "error", "error": "repeat debe ser off|one|all"}, 400
                        )
                    with eng._lock:
                        eng.state["repeat"] = mode
                    eng._save_state()
                    return self._send_json({"status": "ok", "repeat": mode})
                if action == "shuffle":
                    enabled = bool(value) if value is not None else not eng.state.get("shuffle")
                    with eng._lock:
                        eng.state["shuffle"] = enabled
                    eng._save_state()
                    return self._send_json({"status": "ok", "shuffle": enabled})
                if action == "autoplay_radio":
                    enabled = bool(value) if value is not None else not eng.state.get("autoplay_radio")
                    with eng._lock:
                        eng.state["autoplay_radio"] = enabled
                    eng._save_state()
                    return self._send_json({"status": "ok", "autoplay_radio": enabled})
                if action == "duck":
                    return self._send_json(
                        eng.duck(int(body.get("seconds") or 10), int(value or 12))
                    )
                if action == "unduck":
                    return self._send_json(eng.unduck())
                return self._send_json({"status": "error", "error": f"Acción '{action}' no válida"}, 400)

            if path == "/api/soundtrack":
                scene = str(body.get("scene") or "").strip().lower()
                auto = bool(body.get("auto", False))
                if body.get("stop") is True:
                    return self._send_json(eng.stop_soundtrack())
                if scene:
                    with eng._lock:
                        eng.state["scene"] = scene
                if auto:
                    with eng._lock:
                        eng.state["autopilot"] = True
                    eng._save_state()
                return self._send_json(eng.start_soundtrack(scene or None, auto=auto))

            if path == "/api/autopilot":
                enabled = bool(body.get("enabled", True))
                with eng._lock:
                    eng.state["autopilot"] = enabled
                    if not enabled:
                        eng.state["user_paused"] = False
                eng._save_state()
                if enabled:
                    eng._last_autopilot_try = 0
                    eng._suppress_autopilot_until = 0
                return self._send_json({"status": "ok", "autopilot": enabled})

            if path == "/api/queue":
                action = str(body.get("action") or "list").lower()
                if action == "add":
                    query = str(body.get("query") or "").strip()
                    return self._send_json(eng.queue_add(query, limit=int(body.get("limit") or 1)))
                if action == "remove":
                    return self._send_json(eng.queue_remove(int(body.get("index", -1))))
                if action == "clear":
                    return self._send_json(eng.queue_clear())
                if action == "play":
                    return self._send_json(eng.play_index(int(body.get("index", 0))))
                return self._send_json({"status": "error", "error": f"Acción '{action}' no válida"}, 400)

            if path == "/api/favorites":
                action = str(body.get("action") or "toggle").lower()
                track = body.get("track")
                if action in ("toggle", "add", "remove"):
                    if not track:
                        track = eng._current_track()
                        track = track.to_dict() if track else None
                    if track and action == "remove":
                        vid = str(track.get("video_id", ""))
                        with eng._lock:
                            eng.favorites.pop(vid, None)
                            _atomic_json(FAVORITES_FILE, eng.favorites)
                        return self._send_json({"status": "ok", "action": "removed", "video_id": vid})
                    if action == "add" and track and str(track.get("video_id")) not in eng.favorites:
                        return self._send_json(eng.toggle_favorite(track))
                    return self._send_json(eng.toggle_favorite(track))
                return self._send_json({"status": "error", "error": "Acción no válida"}, 400)

            if path == "/api/shutdown":
                threading.Thread(target=lambda: (time.sleep(0.4), os._exit(0)), daemon=True).start()
                return self._send_json({"status": "ok", "action": "shutdown"})

            return self._send_json({"status": "error", "error": "not found"}, 404)
        except Exception as exc:
            logger.exception("API POST %s", path)
            return self._send_json({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, 500)


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT, autopilot: Optional[bool] = None) -> None:
    engine = TardisMusicMaestro.get_instance()
    engine.daemon_mode = True
    engine.start_monitor()
    if autopilot is not None:
        with engine._lock:
            engine.state["autopilot"] = bool(autopilot)
        engine._save_state()
        if autopilot:
            engine._last_autopilot_try = 0
            engine._suppress_autopilot_until = 0
    MusicAPIHandler.engine = engine
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), MusicAPIHandler)
    server.daemon_threads = True

    def _graceful_exit(signum, _frame):
        logger.info("Señal %s recibida; cerrando Music Maestro…", signum)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _graceful_exit)
    signal.signal(signal.SIGINT, _graceful_exit)
    logger.info("TARDIS Music Maestro API en http://%s:%d · dashboard en /", host, port)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logger.info("Deteniendo Music Maestro…")
    finally:
        server.server_close()
        engine.shutdown()


# ---------------------------------------------------------------------------
# Cliente API para CLI / integraciones
# ---------------------------------------------------------------------------
def api_call(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    base: Optional[str] = None,
    timeout: float = 60.0,
) -> Optional[Dict[str, Any]]:
    url = (base or API_BASE).rstrip("/") + path
    data = None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    token = os.environ.get("TARDIS_MUSIC_TOKEN", "").strip()
    if token:
        headers["X-TARDIS-Token"] = token
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def api_available(base: Optional[str] = None) -> bool:
    return bool(api_call("GET", "/api/health", base=base, timeout=1.2))


def music_command(action: str, **kwargs: Any) -> Dict[str, Any]:
    """Despacho unificado: usa el daemon si está vivo y cae al motor local."""
    action = (action or "status").lower().replace("-", "_")

    if action == "status":
        remote = api_call("GET", "/api/status", timeout=3)
        if remote:
            return remote
        return TardisMusicMaestro.get_instance().status()

    if action == "search":
        query = str(kwargs.get("query") or kwargs.get("q") or "")
        limit = int(kwargs.get("limit") or 20)
        filter_ = str(kwargs.get("filter") or "songs")
        if api_available():
            qs = urllib.parse.urlencode({"q": query, "limit": limit, "filter": filter_})
            res = api_call("GET", f"/api/search?{qs}", timeout=60)
            if res:
                return res
        return TardisMusicMaestro.get_instance().search(query, limit=limit, filter=filter_)

    if action in ("play", "play_query"):
        query = str(kwargs.get("query") or kwargs.get("q") or "")
        if api_available():
            res = api_call("POST", "/api/play", {"query": query}, timeout=90)
            if res:
                return res
        return TardisMusicMaestro.get_instance().play_query(query)

    if action in ("pause", "resume", "toggle", "next", "previous", "prev", "stop"):
        mapped = "previous" if action == "prev" else action
        if api_available():
            res = api_call("POST", "/api/control", {"action": mapped}, timeout=60)
            if res:
                return res
        eng = TardisMusicMaestro.get_instance()
        return getattr(eng, mapped)()

    if action == "volume":
        value = int(kwargs.get("value") or kwargs.get("volume") or 50)
        if api_available():
            res = api_call("POST", "/api/control", {"action": "volume", "value": value})
            if res:
                return res
        return TardisMusicMaestro.get_instance().set_volume(value)

    if action == "seek":
        value = float(kwargs.get("value") or kwargs.get("seconds") or 0)
        if api_available():
            res = api_call("POST", "/api/control", {"action": "seek", "value": value})
            if res:
                return res
        return TardisMusicMaestro.get_instance().seek(value)

    if action in ("soundtrack", "scene"):
        scene = kwargs.get("scene")
        auto = bool(kwargs.get("auto", False))
        if api_available():
            res = api_call("POST", "/api/soundtrack", {"scene": scene, "auto": auto}, timeout=90)
            if res:
                return res
        return TardisMusicMaestro.get_instance().start_soundtrack(scene, auto=auto)

    if action == "autopilot" or action == "set_autopilot":
        enabled = bool(kwargs.get("enabled", kwargs.get("value", True)))
        if api_available():
            res = api_call("POST", "/api/autopilot", {"enabled": enabled})
            if res:
                return res
        eng = TardisMusicMaestro.get_instance()
        with eng._lock:
            eng.state["autopilot"] = enabled
        eng._save_state()
        return {"status": "ok", "autopilot": enabled}

    if action in ("repeat", "shuffle", "autoplay_radio"):
        value = kwargs.get("value")
        if api_available():
            res = api_call("POST", "/api/control", {"action": action, "value": value})
            if res:
                return res
        eng = TardisMusicMaestro.get_instance()
        with eng._lock:
            if action == "repeat":
                mode = str(value or "off").lower()
                if mode not in ("off", "one", "all"):
                    return {"status": "error", "error": "repeat debe ser off|one|all"}
                eng.state["repeat"] = mode
            else:
                eng.state[action] = bool(value) if value is not None else not eng.state.get(action)
        eng._save_state()
        return {"status": "ok", action: eng.state.get(action)}

    if action in ("soundtrack_stop", "stop_soundtrack"):
        if api_available():
            res = api_call("POST", "/api/soundtrack", {"stop": True})
            if res:
                return res
        return TardisMusicMaestro.get_instance().stop_soundtrack()

    if action == "scenes":
        if api_available():
            res = api_call("GET", "/api/scenes", timeout=5)
            if res:
                return res
        return {"status": "ok", "scenes": TardisMusicMaestro.get_instance().scene_info()}

    if action in ("queue", "queue_list"):
        if api_available():
            res = api_call("GET", "/api/queue")
            if res:
                return res
        eng = TardisMusicMaestro.get_instance()
        st = eng.status()
        return {"status": "ok", **st["queue"], "current": st["current"]}

    if action == "queue_add":
        query = str(kwargs.get("query") or "")
        if api_available():
            res = api_call("POST", "/api/queue", {"action": "add", "query": query})
            if res:
                return res
        return TardisMusicMaestro.get_instance().queue_add(query)

    if action == "queue_clear":
        if api_available():
            res = api_call("POST", "/api/queue", {"action": "clear"})
            if res:
                return res
        return TardisMusicMaestro.get_instance().queue_clear()

    if action in ("favorites", "favorites_list"):
        if api_available():
            res = api_call("GET", "/api/favorites")
            if res:
                return res
        return {"status": "ok", "favorites": TardisMusicMaestro.get_instance().favorites_list()}

    if action in ("favorite_toggle", "favorite"):
        track = kwargs.get("track")
        if api_available():
            res = api_call("POST", "/api/favorites", {"action": "toggle", "track": track})
            if res:
                return res
        return TardisMusicMaestro.get_instance().toggle_favorite(track)

    if action == "history":
        limit = int(kwargs.get("limit") or 30)
        if api_available():
            res = api_call("GET", f"/api/history?limit={limit}")
            if res:
                return res
        return {"status": "ok", "history": TardisMusicMaestro.get_instance().history(limit)}

    if action == "duck":
        seconds = int(kwargs.get("seconds") or 10)
        if api_available():
            res = api_call("POST", "/api/control", {"action": "duck", "seconds": seconds})
            if res:
                return res
        return TardisMusicMaestro.get_instance().duck(seconds)

    if action == "doctor":
        if api_available():
            res = api_call("GET", "/api/doctor", timeout=60)
            if res:
                return res
        return TardisMusicMaestro.get_instance().doctor()

    return {"status": "error", "error": f"Acción musical '{action}' no reconocida"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _cmd_status(args: argparse.Namespace) -> int:
    data = music_command("status")
    if args.json:
        _print_json(data)
        return 0
    if not isinstance(data, dict):
        print("Sin respuesta del motor musical.")
        return 1
    pb = data.get("playback", {})
    cur = data.get("current") or {}
    q = data.get("queue", {})
    scene = data.get("scene", "")
    scene_name = data.get("scene_name", "")
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  🎼 TARDIS MUSIC MAESTRO · SOUNDTRACK SOBERANO                ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    state = "▶ REPRODUCIENDO" if pb.get("playing") else "⏸ DETENIDO"
    if pb.get("paused"):
        state = "⏸ PAUSADO"
    print(f"  Estado      : {state}")
    if cur:
        print(f"  Pista       : {cur.get('title')} — {cur.get('artist') or '?'}")
        print(f"  Progreso    : {pb.get('time_pos_text')} / {pb.get('duration_text')}")
    print(f"  Escena      : {scene} · {scene_name}")
    print(f"  Cola        : {q.get('index', -1) + 1}/{q.get('length', 0)} · radio={q.get('autoplay_radio')} · autopilot={q.get('autopilot')}")
    print(f"  Volumen     : {pb.get('volume')}%")
    print(f"  Conector    : {data.get('connector', {}).get('connector', '')}")
    if data.get("soundtrack", {}).get("last_error"):
        print(f"  Último error: {data['soundtrack']['last_error']}")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    data = music_command("search", query=args.query, limit=args.limit, filter=args.filter)
    if args.json:
        _print_json(data)
        return 0
    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        print("Sin resultados.")
        return 1
    for i, track in enumerate(results, 1):
        dur = f" [{track.get('duration')}]" if track.get("duration") else ""
        kind = track.get("kind", "")
        print(f"{i:2d}. {track.get('title')} — {track.get('artist') or '?'}{dur}  ({kind})")
        print(f"    id: {track.get('video_id') or track.get('source') or '-'}")
    return 0


def _cmd_play(args: argparse.Namespace) -> int:
    data = music_command("play", query=args.query)
    _print_json(data)
    return 0 if isinstance(data, dict) and data.get("status") in ("ok", "building") else 1


def _cmd_control(args: argparse.Namespace) -> int:
    data = music_command(args.action)
    _print_json(data)
    return 0 if isinstance(data, dict) and data.get("status") in ("ok", "building") else 1


def _cmd_soundtrack(args: argparse.Namespace) -> int:
    if args.stop:
        data = api_call("POST", "/api/soundtrack", {"stop": True}) if api_available() else music_command("stop")
        _print_json(data)
        return 0
    if args.scene not in SCENES:
        print(f"Escena desconocida '{args.scene}'. Disponibles: {', '.join(SCENES)}")
        return 2
    data = music_command("soundtrack", scene=args.scene, auto=args.auto)
    _print_json(data)
    return 0 if isinstance(data, dict) and data.get("status") in ("ok", "building") else 1


def _cmd_scenes(args: argparse.Namespace) -> int:
    data = music_command("scenes")
    if args.json:
        _print_json(data)
        return 0
    for scene in data.get("scenes", []):
        print(f"{scene['emoji']} {scene['id']:<14} {scene['name']}")
        print(f"   {scene['description']}")
    return 0


def _cmd_queue(args: argparse.Namespace) -> int:
    if args.clear:
        data = music_command("queue_clear")
        _print_json(data)
        return 0
    if args.add:
        data = music_command("queue_add", query=args.add)
        _print_json(data)
        return 0
    data = music_command("queue")
    if args.json:
        _print_json(data)
        return 0
    cur = data.get("current") or {}
    if cur:
        print(f"▶ {cur.get('title')} — {cur.get('artist') or '?'}")
    for i, track in enumerate(data.get("upcoming", []), 1):
        print(f"{i:2d}. {track.get('title')} — {track.get('artist') or '?'}")
    return 0


def _cmd_favorites(args: argparse.Namespace) -> int:
    data = music_command("favorites")
    if args.json:
        _print_json(data)
        return 0
    favs = data.get("favorites", [])
    if not favs:
        print("Sin favoritos todavía.")
        return 0
    for i, track in enumerate(favs, 1):
        print(f"{i:2d}. {track.get('title')} — {track.get('artist') or '?'}  ({track.get('video_id')})")
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    data = music_command("history", limit=args.limit)
    if args.json:
        _print_json(data)
        return 0
    for item in data.get("history", []):
        print(f"{item.get('iso', '')}  {item.get('title')} — {item.get('artist') or '?'}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    data = music_command("doctor")
    _print_json(data)
    return 0 if isinstance(data, dict) and data.get("status") == "ok" else 1


def _cmd_serve(args: argparse.Namespace) -> int:
    serve(host=args.host, port=args.port, autopilot=args.autopilot)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tardis-music",
        description="TARDIS Music Maestro · YouTube Music + soundtrack automático",
    )
    parser.add_argument("--api", default=API_BASE, help="Base de la API (default env TARDIS_MUSIC_API)")
    sub = parser.add_subparsers(dest="command")

    p_status = sub.add_parser("status", help="Estado del reproductor y la cola")
    p_status.add_argument("--json", action="store_true")

    p_search = sub.add_parser("search", help="Buscar en YouTube Music")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=15)
    p_search.add_argument(
        "--filter",
        default="songs",
        choices=["songs", "videos", "albums", "playlists", "artists", "all"],
    )
    p_search.add_argument("--json", action="store_true")

    p_play = sub.add_parser("play", help="Reproducir una búsqueda, URL o videoId")
    p_play.add_argument("query")

    for action, help_text in (
        ("pause", "Pausar"),
        ("resume", "Reanudar"),
        ("toggle", "Alternar play/pause"),
        ("next", "Siguiente pista"),
        ("prev", "Pista anterior"),
        ("stop", "Detener"),
    ):
        sub.add_parser(action, help=help_text)

    p_vol = sub.add_parser("volume", help="Ajustar volumen (0-130)")
    p_vol.add_argument("value", type=int)

    p_scene = sub.add_parser("soundtrack", help="Iniciar soundtrack de una escena")
    p_scene.add_argument("scene", nargs="?", default="focus", choices=list(SCENES))
    p_scene.add_argument("--auto", action="store_true", help="Activar autopilot")
    p_scene.add_argument("--stop", action="store_true", help="Detener soundtrack y autopilot")

    p_scenes = sub.add_parser("scenes", help="Listar escenas disponibles")
    p_scenes.add_argument("--json", action="store_true")

    p_queue = sub.add_parser("queue", help="Ver o modificar la cola")
    p_queue.add_argument("--json", action="store_true")
    p_queue.add_argument("--add", metavar="QUERY", help="Añadir pista por búsqueda")
    p_queue.add_argument("--clear", action="store_true", help="Vaciar la cola")

    p_fav = sub.add_parser("favorites", help="Listar favoritos")
    p_fav.add_argument("--json", action="store_true")

    p_hist = sub.add_parser("history", help="Historial de reproducción")
    p_hist.add_argument("--limit", type=int, default=30)
    p_hist.add_argument("--json", action="store_true")

    p_doctor = sub.add_parser("doctor", help="Diagnóstico del subsistema musical")

    p_serve = sub.add_parser("serve", help="Daemon API + soundtrack")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_serve.add_argument("--autopilot", action="store_true", default=None)
    p_serve.add_argument("--no-autopilot", action="store_false", dest="autopilot")

    p_duck = sub.add_parser("duck", help="Bajar volumen temporalmente (voz de TARDIS)")
    p_duck.add_argument("--seconds", type=int, default=10)
    p_duck.add_argument("--volume", type=int, default=12)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.api:
        globals()["API_BASE"] = args.api
    if not args.command:
        build_parser().print_help()
        return 0

    if args.command in ("pause", "resume", "toggle", "next", "prev", "stop"):
        _print_json(music_command(args.command))
        return 0
    if args.command == "volume":
        _print_json(music_command("volume", value=args.value))
        return 0
    if args.command == "duck":
        data = api_call(
            "POST",
            "/api/control",
            {"action": "duck", "seconds": args.seconds, "value": args.volume},
        ) if api_available() else music_command("duck", seconds=args.seconds)
        _print_json(data)
        return 0

    handlers = {
        "status": _cmd_status,
        "search": _cmd_search,
        "play": _cmd_play,
        "soundtrack": _cmd_soundtrack,
        "scenes": _cmd_scenes,
        "queue": _cmd_queue,
        "favorites": _cmd_favorites,
        "history": _cmd_history,
        "doctor": _cmd_doctor,
        "serve": _cmd_serve,
    }
    handler = handlers.get(args.command)
    if not handler:
        print(f"Comando '{args.command}' no implementado.")
        return 2
    return int(handler(args) or 0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
