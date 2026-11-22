#!/usr/bin/env python3
"""
core/tardis_c310_conversation.py - Motor Soberano de Conversación Interactiva,
Enseñanza, Visión e Investigación para TP-Link Tapo C310 (GOD-EYE · REDACTED_IP)
===================================================================================

Cumple la directiva del Arquitecto (₪):
    "TARDIS conectada a la Tapo C310 REDACTED_IP.
     Debe poder conversar de forma interactiva, con el visitante, la idea es que
     TARDIS le enseñe cosas a las personas y puedan tener interacción conversacional
     más compleja al punto de poder aprender y poder investigar mediante el uso
     de esta cámara."

Arquitectura modular 100% local-first + investigación web/científica en vivo:
  1. `clean_spoken_spanish`: sanitiza respuestas para TTS es-MX (sin markdown,
     sin bloques <think>, sin caracteres CJK residuales, con topes hablados).
  2. `EnergyVad`: detector de actividad vocal adaptativo (noise floor + pre-roll
     + histéresis) para complementar Vosk y alimentar Whisper con frases limpias.
  3. `InteractiveWakeMatcher`: despierta con la frase canónica («TARDIS, ¿estás ahí?»)
     y con saludos/órdenes naturales de visitantes («Hola TARDIS, enséñame...»,
     «Oye TARDIS, qué ves...», «TARDIS investiga...»), rechazando falsos positivos
     como «buenas tardes».
  4. `CapsuleLibrary`: biblioteca persistente de 24 cápsulas pedagógicas interactivas
     multi-nivel (principiante / intermedio / avanzado) con ganchos narrativos y
     preguntas socráticas, más aprendizaje de nuevas cápsulas.
  5. `CameraVisionInvestigator`: captura fotogramas RAW limpios (sin HUD) de la
     Tapo C310 (:8797/c310/snapshot.jpg?hud=0) y ejecuta inferencia multimodal real
     con `qwen3-vl:2b-instruct` en el carril dedicado GPU (:11435, respaldo :11434).
  6. `InteractiveResearchEngine`: investigación en vivo multi-fuente (DeepMemory/RAG
     local + Wikipedia ES/EN REST + arXiv + Google News + DuckDuckGo vía
     WebResearchEngine) con caché en disco, notas de investigación y aprendizaje
     continuo hacia la memoria de TARDIS.
  7. `VoiceBrain`: cliente de baja latencia que prioriza el carril GPU dedicado
     (`127.0.0.1:11435`, `qwen3-vl:2b-instruct`), con respaldo a TemporalBrain
     (solo texto, nunca enviando `image_url` al servidor sin mmproj), Ollama :11434
     y núcleo `/api/chat`.
  8. `ConversationMemory`: perfiles persistentes de visitantes, sesiones completas,
     hechos aprendidos, notas de investigación y cola autónoma de aprendizaje
     (`learning_queue.json`) procesada en segundo plano.
  9. `ConversationDirector`: director dialógico multi-turno con ajuste pedagógico
     dinámico (más fácil / más profundo / ejemplo / quiz), investigación visual,
     investigación documental e investigación combinada (cámara + web).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tardis_teaching import (
    TEACHING_PERSONA_CORE,
    build_teaching_prompt,
    detect_pedagogical_adjustment,
    extract_research_query,
    is_curiosity_intent,
    is_research_intent,
    is_teaching_intent,
    is_vision_intent,
    normalize_teaching_text,
    teaching_topic,
)

logger = logging.getLogger("TARDIS.C310Conversation")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(
        logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s")
    )
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

DATA_DIR = BASE_DIR / "data" / "tapo_c310_conversation"
CAPSULES_FILE = DATA_DIR / "capsules.json"
VISITORS_FILE = DATA_DIR / "visitors.json"
SESSIONS_FILE = DATA_DIR / "sessions.jsonl"
FACTS_FILE = DATA_DIR / "learned_facts.jsonl"
RESEARCH_NOTES_FILE = DATA_DIR / "research_notes.jsonl"
RESEARCH_CACHE_FILE = DATA_DIR / "research_cache.json"
LEARNING_QUEUE_FILE = DATA_DIR / "learning_queue.json"

DETECTIONS_DIR = BASE_DIR / "data" / "tapo_c310_detections"
SENTINEL_SNAPSHOT_URL = os.environ.get(
    "TARDIS_C310_SNAPSHOT_URL", "http://127.0.0.1:8797/c310/snapshot.jpg"
)
VOICE_OLLAMA_DEFAULT_URL = os.environ.get(
    "TARDIS_VOICE_OLLAMA_URL", "http://127.0.0.1:11435"
)
VOICE_OLLAMA_DEFAULT_MODEL = os.environ.get(
    "TARDIS_VOICE_OLLAMA_MODEL", "qwen3-vl:2b-instruct"
)
MAIN_OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
TEMPORAL_BRAIN_SOCK = Path(
    os.environ.get("TEMPORAL_BRAIN_SOCKET", "/tmp/temporal_brain.sock")
)
TARDIS_CHAT_URL = os.environ.get("TARDIS_CHAT_URL", "http://127.0.0.1:8757/api/chat")
GIA_TOKEN_FILE = Path(
    os.environ.get(
        "TARDIS_TOKEN_FILE",
        str(Path.home() / ".config" / "tardis" / "secrets" / "gia_token"),
    )
)

SAMPLE_RATE = 16000
FRAME_BYTES = 640

CANONICAL_GREETING = (
    "Un placer, soy TARDIS asistente de inteligencia artificial, "
    "mi tarea es ayudarte a explorar las maravillas de la realidad "
    "y todas las dimensiones temporales."
)

_RE_THINK = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
_RE_MD_CODE = re.compile(r"```.*?```", flags=re.DOTALL)
_RE_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_RE_URL = re.compile(r"https?://\S+")
_RE_MD_CHARS = re.compile(r"[`*_#>|~•●▪►]+")
# Elimina caracteres CJK / cirílicos / arábigos / emojis que modelos multilingües
# pequeños a veces mezclan en español y que corrompen edge-tts es-MX.
_RE_NON_LATIN_SPEECH = re.compile(
    r"[^\x20-\x7E\u00A0-\u00FF\u0100-\u017F\u2010-\u2027\u2030-\u205E]"
)
_RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_json(path: Path, default: Any) -> Any:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def normalize_text(text: str) -> str:
    """Normaliza a minúsculas sin acentos ni puntuación."""
    decomposed = unicodedata.normalize("NFD", str(text or "").lower())
    no_acc = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9ñ]+", " ", no_acc).split())


def clean_spoken_spanish(
    text: str, max_sentences: int = 5, max_chars: int = 760
) -> str:
    """
    Limpia cualquier salida LLM/enciclopédica para hablarla por la bocina de la C310:
    - Elimina etiquetas <think>, bloques de código, markdown, URLs y emojis.
    - Remueve caracteres CJK/no-latinos accidentales (p. ej. de qwen3-vl).
    - Recorta limpiamente a un número máximo de oraciones y caracteres.
    """
    body = str(text or "")
    body = _RE_THINK.sub(" ", body)
    if "<think>" in body.lower():
        body = re.split(r"<think>", body, flags=re.IGNORECASE)[0]
    body = _RE_MD_CODE.sub(" ", body)
    body = _RE_MD_LINK.sub(r"\1", body)
    body = _RE_URL.sub(" ", body)
    body = _RE_MD_CHARS.sub(" ", body)
    body = _RE_NON_LATIN_SPEECH.sub(" ", body)
    body = re.sub(r"\s+([.,;:!?])", r"\1", body)
    body = re.sub(r"([.,;:!?]){2,}", r"\1", body)
    body = re.sub(r"\s+", " ", body).strip()
    if not body:
        return ""

    parts = [p.strip() for p in _RE_SENTENCE_SPLIT.split(body) if p.strip()]
    if parts and max_sentences > 0:
        body = " ".join(parts[:max_sentences]).strip()

    if max_chars > 0 and len(body) > max_chars:
        cut = body[:max_chars]
        pos = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"), cut.rfind(","))
        if pos > int(max_chars * 0.55):
            cut = cut[: pos + 1]
        body = cut.strip()

    if body and body[-1] not in ".!?…":
        body += "."
    return body


def compute_pcm_rms(pcm: bytes) -> float:
    """RMS rápido en PCM16 mono mediante NumPy (compatible Python 3.13/3.14+)."""
    if not pcm or len(pcm) < 2:
        return 0.0
    usable = len(pcm) - (len(pcm) % 2)
    arr = np.frombuffer(pcm[:usable], dtype=np.int16)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))


# ---------------------------------------------------------------------------
# 1. Detector de actividad vocal adaptativo (EnergyVad)
# ---------------------------------------------------------------------------


class EnergyVad:
    """
    VAD por energía con seguimiento de piso de ruido, pre-roll e histéresis.
    Complementa a Vosk para capturar frases naturales de visitantes y entregarlas
    a faster-whisper incluso cuando Vosk no segmenta bien términos técnicos.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        frame_bytes: int = FRAME_BYTES,
        min_rms: float = 65.0,
        start_ms: int = 120,
        end_ms: int = 850,
        pre_roll_ms: int = 320,
        max_utterance_ms: int = 16000,
        threshold_factor: float = 2.1,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_bytes = frame_bytes
        self.frame_ms = (frame_bytes / float(sample_rate * 2)) * 1000.0
        self.min_rms = float(min_rms)
        self.start_frames = max(1, int(round(start_ms / self.frame_ms)))
        self.end_frames = max(2, int(round(end_ms / self.frame_ms)))
        self.pre_roll_frames = max(1, int(round(pre_roll_ms / self.frame_ms)))
        self.max_frames = max(20, int(round(max_utterance_ms / self.frame_ms)))
        self.threshold_factor = float(threshold_factor)

        self.noise_floor: float = 35.0
        self._pre_roll: List[bytes] = []
        self._speech_buf: List[bytes] = []
        self._active: bool = False
        self._voiced_streak: int = 0
        self._silence_streak: int = 0

    def reset(self) -> None:
        self._pre_roll.clear()
        self._speech_buf.clear()
        self._active = False
        self._voiced_streak = 0
        self._silence_streak = 0

    @property
    def is_speaking(self) -> bool:
        return self._active

    def push(self, frame: bytes) -> Optional[bytes]:
        if not frame:
            return None
        rms = compute_pcm_rms(frame)
        threshold = max(self.min_rms, self.noise_floor * self.threshold_factor)

        if not self._active:
            self._pre_roll.append(frame)
            if len(self._pre_roll) > self.pre_roll_frames:
                self._pre_roll.pop(0)
            if rms >= threshold or rms >= 1800.0:
                self._voiced_streak += 1
                if self._voiced_streak >= self.start_frames:
                    self._active = True
                    self._silence_streak = 0
                    self._speech_buf = list(self._pre_roll)
                    self._pre_roll.clear()
            else:
                self._voiced_streak = 0
                # Adaptación lenta del piso de ruido ambiental.
                clamped = min(rms, max(self.min_rms * 1.4, 220.0))
                self.noise_floor = 0.97 * self.noise_floor + 0.03 * clamped
            return None

        # Ya estamos dentro de una utterance
        self._speech_buf.append(frame)
        exit_threshold = max(self.min_rms * 0.72, threshold * 0.70)
        if rms >= exit_threshold:
            self._silence_streak = 0
        else:
            self._silence_streak += 1

        if self._silence_streak >= self.end_frames or len(self._speech_buf) >= self.max_frames:
            pcm = b"".join(self._speech_buf)
            self.reset()
            return pcm
        return None


# ---------------------------------------------------------------------------
# 2. Wake interactivo para visitantes (natural + cero falsos positivos)
# ---------------------------------------------------------------------------


@dataclass
class InteractiveWakeResult:
    matched: bool
    kind: str = ""  # "canonical" | "greeting" | "interactive_command"
    phrase: str = ""
    remainder: str = ""


class InteractiveWakeMatcher:
    """
    Permite a visitantes iniciar conversación interactiva con TARDIS sin saber
    de memoria la frase exacta de activación, evitando falsos positivos como
    «buenas tardes» o «más tarde».

    Acepta:
      - Saludo directo a TARDIS: «Hola TARDIS», «Oye TARDIS», «Hey TARDIS»
      - Orden interactiva con vocativo TARDIS: «TARDIS enséñame...»,
        «TARDIS explícame...», «TARDIS investiga...», «TARDIS qué ves...»,
        «TARDIS mira esto», «TARDIS quiero aprender...», «TARDIS cuéntame...»,
        «TARDIS dime...», «TARDIS ayúdame...»
    Rechaza:
      - «Buenas tardes...», «en la tarde...», «TARDIS está en línea»
    """

    _GREETING_PREFIXES = {"hola", "oye", "hey", "ey", "eh", "disculpa", "perdona"}
    _FORBIDDEN_PREV = {"buenas", "buena", "esta", "la", "por", "en", "mas", "muy", "tan", "de"}
    _DIRECT_VERBS = (
        "ensen",
        "explic",
        "instru",
        "doctr",
        "investig",
        "averigu",
        "busc",
        "mira",
        "observ",
        "analiz",
        "describ",
        "identific",
        "lee",
        "cuent",
        "habl",
        "dime",
        "ayud",
        "quiero",
        "puedes",
        "podrias",
        "que",
        "como",
        "por",
        "quien",
        "cual",
        "donde",
        "sorprend",
        "plat",
        "convers",
        "pregunt",
    )

    @staticmethod
    def _is_tardis_token(tokens: List[str], i: int) -> Tuple[bool, int]:
        tok = tokens[i]
        # «tardis» o variantes ASR muy cercanas («tardiz», «tardys»).
        # «tardes»/«tarde» solo se aceptan si van precedidos por saludo vocativo
        # o seguidos de una orden clara para TARDIS, nunca tras «buenas».
        if tok in ("tardis", "tardiz", "tardys", "tardes"):
            return True, i + 1
        if tok == "tar" and i + 1 < len(tokens) and tokens[i + 1].startswith("dis"):
            return True, i + 2
        return False, i + 1

    def find(self, text: str) -> Optional[InteractiveWakeResult]:
        norm = normalize_text(text)
        tokens = norm.split()
        if not tokens:
            return None

        for i in range(len(tokens)):
            is_t, after = self._is_tardis_token(tokens, i)
            if not is_t:
                continue
            prev = tokens[i - 1] if i > 0 else ""
            if prev in self._FORBIDDEN_PREV:
                continue
            # Si el token fue «tardes», exigir que haya saludo vocativo (hola/oye)
            # o verbo didáctico/investigativo directo para evitar falsos positivos.
            is_ambiguous = tokens[i] == "tardes"
            has_greeting_prev = prev in self._GREETING_PREFIXES
            next_tok = tokens[after] if after < len(tokens) else ""
            # Rechazar afirmaciones en tercera persona como «TARDIS está en línea».
            if next_tok in ("esta", "es", "fue", "era", "tiene", "hace") and not has_greeting_prev:
                continue

            has_direct_verb = bool(next_tok) and any(
                next_tok == v or next_tok.startswith(v) for v in self._DIRECT_VERBS
            )

            if has_greeting_prev:
                # «Hola TARDIS» o «Oye TARDIS, enséñame...»
                if is_ambiguous and not has_direct_verb and after >= len(tokens):
                    # «Hola tardes» solo es muy sospechoso -> ignorar
                    continue
                phrase = " ".join(tokens[max(0, i - 1) : after])
                remainder = " ".join(tokens[after:]).strip()
                return InteractiveWakeResult(
                    matched=True,
                    kind="greeting",
                    phrase=phrase,
                    remainder=remainder,
                )

            if has_direct_verb and i <= 1:
                if is_ambiguous and not any(
                    next_tok.startswith(p)
                    for p in ("ensen", "explic", "investig", "mira", "observ", "analiz", "cuent")
                ):
                    continue
                phrase = " ".join(tokens[i:after])
                remainder = " ".join(tokens[after:]).strip()
                return InteractiveWakeResult(
                    matched=True,
                    kind="interactive_command",
                    phrase=phrase,
                    remainder=remainder,
                )

        return None


# ---------------------------------------------------------------------------
# 3. Biblioteca de Cápsulas Interactivas Multi-Nivel (CapsuleLibrary)
# ---------------------------------------------------------------------------

_SEED_CAPSULES: List[Dict[str, Any]] = [
    {
        "id": "universo-luz",
        "title": "La velocidad de la luz y mirar al pasado",
        "domain": "astronomia",
        "tags": ["universo", "luz", "sol", "espacio", "tiempo", "estrellas", "astronomia"],
        "hook": "Mira cualquier fuente de luz a tu alrededor: la luz que llega del Sol tarda ocho minutos y veinte segundos en viajar hasta la Tierra.",
        "explanation_basic": "Eso significa que nunca vemos el Sol como es en este instante, sino como era hace ocho minutos. Y cuando miras una estrella lejana en el cielo nocturno, estás viendo su pasado de hace decenas o miles de años.",
        "explanation_intermediate": "Como la luz viaja a casi trescientos mil kilómetros por segundo, el universo funciona como una máquina del tiempo natural. Observar galaxias distantes equivale a ver cómo era el cosmos miles de millones de años atrás.",
        "explanation_advanced": "Debido al límite relativista c en el vacío, todo observador recibe información únicamente sobre su cono de luz pasado. En cosmología observacional, el corrimiento al rojo permite reconstruir la historia de expansión del universo desde la recombinación.",
        "question": "¿Te gustaría que exploremos qué pasa con el tiempo cerca de un agujero negro o prefieres otro misterio del universo?",
    },
    {
        "id": "fisica-agujeros-negros",
        "title": "Agujeros negros y horizonte de eventos",
        "domain": "fisica",
        "tags": ["agujero", "negro", "gravedad", "einstein", "relatividad", "espacio", "fisica"],
        "hook": "Un agujero negro no es un hoyo vacío, sino una cantidad gigantesca de masa comprimida en un espacio diminuto.",
        "explanation_basic": "Su gravedad es tan intensa que ni siquiera la luz puede escapar una vez que cruza una frontera llamada horizonte de eventos. Por eso se ven oscuros, aunque alrededor brillan gases muy calientes.",
        "explanation_intermediate": "Según la relatividad general de Einstein, esa masa extrema curva tanto el espacio-tiempo que todas las trayectorias futuras dentro del horizonte apuntan hacia el centro. Además, cerca del borde el tiempo corre más lento respecto a un observador lejano.",
        "explanation_advanced": "La métrica de Schwarzschild define el radio del horizonte de eventos en dos G M sobre c cuadrada, mientras que los agujeros negros rotantes siguen la métrica de Kerr con ergosfera. Stephen Hawking demostró que efectos cuánticos cerca del horizonte generan radiación térmica y evaporación gradual.",
        "question": "¿Qué crees que sentiría un astronauta si pudiera mirar su reloj cerca de un agujero negro?",
    },
    {
        "id": "fisica-cuantica",
        "title": "Superposición y mundo cuántico",
        "domain": "fisica",
        "tags": ["cuantica", "cuantico", "atomos", "particulas", "superposicion", "entrelazamiento", "fisica"],
        "hook": "En el mundo diminuto de los átomos, las partículas no se comportan como pequeñas canicas sólidas, sino como ondas de probabilidad.",
        "explanation_basic": "Antes de medirla, una partícula cuántica puede estar en una combinación de varios estados posibles al mismo tiempo, algo llamado superposición. Al observarla o medirla, obtenemos un resultado concreto.",
        "explanation_intermediate": "La función de onda describe las probabilidades de encontrar un electrón en distintos estados. Cuando dos partículas se entrelazan cuánticamente, medir una determina al instante el estado correlacionado de la otra sin importar la distancia.",
        "explanation_advanced": "La evolución unitaria de un estado cuántico se rige por la ecuación de Schrödinger en un espacio de Hilbert, mientras la decoherencia ambiental explica por qué no observamos superposiciones macroscópicas estables. Esta propiedad es la base de los cúbits y algoritmos cuánticos.",
        "question": "¿Quieres que lo conectemos con cómo funcionan las computadoras cuánticas o con los láseres cotidianos?",
    },
    {
        "id": "fisica-entropia",
        "title": "La entropía y la flecha del tiempo",
        "domain": "fisica",
        "tags": ["entropia", "tiempo", "termodinamica", "energia", "orden", "caos", "fisica"],
        "hook": "Si dejas caer una taza de cerámica se rompe en pedazos, pero nunca ves los pedazos saltar solos para volver a formar la taza.",
        "explanation_basic": "Esa dirección natural de los cambios se llama entropía: en la naturaleza, la energía tiende a dispersarse y los sistemas pasan de estados muy ordenados a estados más repartidos.",
        "explanation_intermediate": "La segunda ley de la termodinámica establece que la entropía de un sistema aislado nunca disminuye. Es lo que da al universo una flecha del tiempo y explica por qué los seres vivos necesitamos consumir energía continuamente para mantener nuestro orden interno.",
        "explanation_advanced": "En mecánica estadística, Boltzmann definió la entropía como k sub B por el logaritmo del número de microestados accesibles omega. Un sistema macroscópico evoluciona hacia el equilibrio simplemente porque existen órdenes de magnitud más microestados desordenados que ordenados.",
        "question": "¿Sabes cómo logran las plantas y tu propio cuerpo crear orden sin violar la segunda ley de la termodinámica?",
    },
    {
        "id": "fisica-gravedad",
        "title": "Cómo funciona realmente la gravedad",
        "domain": "fisica",
        "tags": ["gravedad", "einstein", "newton", "planetas", "orbitas", "caida", "fisica"],
        "hook": "Aunque sentimos que la gravedad nos jala hacia abajo, Einstein descubrió que en realidad es la geometría del espacio-tiempo curvándose.",
        "explanation_basic": "Imagina una tela elástica con una bola pesada en el centro: la tela se hunde y cualquier canica cercana rueda en curva alrededor. Así mantiene el Sol a los planetas girando a su alrededor.",
        "explanation_intermediate": "Newton describió la gravedad como una fuerza proporcional a las masas e inversamente proporcional al cuadrado de la distancia. Einstein fue más allá: los objetos en órbita en realidad caen libremente siguiendo la trayectoria más recta posible sobre un espacio-tiempo curvado.",
        "explanation_advanced": "Las ecuaciones de campo de Einstein relacionan el tensor de curvatura con el tensor energía-momento, implicando que no solo la masa sino también la energía y la presión curvan el espacio-tiempo. Incluso los GPS en tu teléfono corrigen a diario esta dilatación gravitacional del tiempo.",
        "question": "¿Sabías que sin corregir la gravedad de Einstein los mapas GPS fallarían varios kilómetros cada día?",
    },
    {
        "id": "regional-cenotes",
        "title": "Los cenotes y ríos subterráneos de Quintana Roo",
        "domain": "geologia",
        "tags": ["cenotes", "quintana", "roo", "playa", "carmen", "yucatan", "agua", "geologia", "maya"],
        "hook": "Aquí mismo, bajo nuestros pies en Quintana Roo, existe una de las redes de ríos subterráneos inundados más largas del planeta.",
        "explanation_basic": "La península de Yucatán está hecha de roca caliza porosa; durante miles de años, el agua de lluvia ligeramente ácida disolvió la roca y formó cuevas. Cuando el techo de una cueva colapsa, nace un cenote.",
        "explanation_intermediate": "Este paisaje se llama karst y funciona como un acuífero gigantesco donde el agua dulce menos densa flota sobre agua salada que entra desde el mar Caribe, creando una capa cristalina llamada haloclina.",
        "explanation_advanced": "Los espeleotemas sumergidos en sistemas como Sac Actun demuestran que estas cavernas estuvieron secas durante las glaciaciones del Pleistoceno cuando el nivel del mar era hasta cien metros más bajo. Además, el impacto de Chicxulub generó el anillo de cenotes por fracturamiento geológico.",
        "question": "¿Te gustaría saber cómo el impacto del asteroide de los dinosaurios ayudó a formar el anillo de cenotes?",
    },
    {
        "id": "regional-arrecife",
        "title": "El Arrecife Mesoamericano y los corales",
        "domain": "biologia",
        "tags": ["arrecife", "coral", "mar", "caribe", "oceano", "biologia", "quintana", "peces"],
        "hook": "Frente a la costa del Caribe mexicano corre el Arrecife Mesoamericano, el segundo sistema arrecifal más grande del mundo.",
        "explanation_basic": "Aunque parecen piedras o plantas, los corales son colonias de animales diminutos llamados pólipos que construyen esqueletos de calcio y protegen las playas de la fuerza de los huracanes.",
        "explanation_intermediate": "Los corales viven en simbiosis con algas microscópicas llamadas zooxantelas, que les dan color y alimento gracias a la luz solar. Cuando el mar se calienta demasiado, el coral expulsa esas algas y ocurre el blanqueamiento.",
        "explanation_advanced": "Los arrecifes coralinos albergan cerca de una cuarta parte de la biodiversidad marina pese a ocupar menos del uno por ciento del fondo oceánico. Su tasa de calcificación depende directamente de la saturación de aragonita, amenazada por la acidificación oceánica.",
        "question": "¿Quieres que exploremos qué animales sorprendentes viven en el arrecife o cómo podemos protegerlo?",
    },
    {
        "id": "historia-mayas-cero",
        "title": "El cero y la astronomía de la civilización maya",
        "domain": "historia",
        "tags": ["mayas", "maya", "cero", "matematicas", "astronomia", "calendario", "historia", "mexico"],
        "hook": "Mucho antes de que Europa usara el número cero, los matemáticos mayas ya lo habían inventado y lo usaban para cálculos astronómicos precisos.",
        "explanation_basic": "Su sistema numérico era vigesimal, es decir, contaba de veinte en veinte usando puntos, barras y un símbolo parecido a una concha para el cero. Con eso predijeron eclipses y el movimiento de Venus.",
        "explanation_intermediate": "Gracias al valor posicional y al cero, los astrónomos mayas calcularon la duración del año solar y el ciclo sinódico de Venus con un margen de error de apenas minutos a lo largo de siglos.",
        "explanation_advanced": "La Cuenta Larga maya combinaba ciclos vigesimales con un ajuste de trescientos sesenta días en el tun para alinear registros históricos y astronómicos monumentales, como muestran las tablas de eclipses del Códice de Dresde.",
        "question": "¿Te imaginas calcular la órbita de Venus sin telescopios ni computadoras, solo observando el horizonte?",
    },
    {
        "id": "biologia-fotosintesis",
        "title": "Cómo las plantas fabrican comida con luz",
        "domain": "biologia",
        "tags": ["fotosintesis", "plantas", "hojas", "clorofila", "oxigeno", "arboles", "biologia"],
        "hook": "Cada hoja de un árbol es una fábrica solar silenciosa que convierte aire, agua y luz en alimento y oxígeno.",
        "explanation_basic": "Dentro de las hojas hay un pigmento verde llamado clorofila que absorbe la luz del sol. Con esa energía, la planta une agua y dióxido de carbono para fabricar azúcares y liberar el oxígeno que respiramos.",
        "explanation_intermediate": "La fotosíntesis ocurre en dos fases: primero la fase luminosa divide moléculas de agua generando energía química y oxígeno, y luego el ciclo de Calvin fija el carbono del aire para construir glucosa.",
        "explanation_advanced": "En los tilacoides del cloroplasto, los fotosistemas dos y uno impulsan una cadena de transporte de electrones que bombea protones y activa la ATP sintasa. La enzima RuBisCO cataliza luego la fijación de carbono, siendo la proteína más abundante de la biosfera.",
        "question": "¿Sabes por qué las hojas nos parecen verdes y no negras si quisieran absorber toda la luz?",
    },
    {
        "id": "biologia-redes-arboles",
        "title": "La red subterránea de comunicación de los bosques",
        "domain": "biologia",
        "tags": ["arboles", "bosque", "hongos", "micelio", "naturaleza", "raices", "biologia"],
        "hook": "Bajo el suelo de un bosque, los árboles no están solos: sus raíces están conectadas por filamentos microscópicos de hongos como una internet natural.",
        "explanation_basic": "Esa red se llama micelio. Los árboles comparten azúcares con los hongos, y a cambio los hongos les llevan agua, minerales e incluso señales químicas de alerta cuando llega una plaga.",
        "explanation_intermediate": "Los biólogos la llaman red micorrícica: árboles grandes y bien iluminados pueden transferir nutrientes a retoños jóvenes que crecen en la sombra, aumentando la resiliencia de todo el ecosistema.",
        "explanation_advanced": "Las simbiosis ectomicorrícicas y arbusculares intercambian carbono fotosintético por fósforo y nitrógeno biodisponible, modulando además defensas sistémicas inducidas mediante rutas de ácido jasmónico entre plantas vecinas.",
        "question": "¿No te parece fascinante que la naturaleza inventara las redes distribuidas millones de años antes que internet?",
    },
    {
        "id": "biologia-cerebro",
        "title": "El cerebro humano y la plasticidad neuronal",
        "domain": "neurociencia",
        "tags": ["cerebro", "neuronas", "memoria", "aprender", "mente", "neurociencia", "sinapsis"],
        "hook": "Cada vez que aprendes algo nuevo, tu cerebro cambia físicamente creando y reforzando conexiones entre neuronas.",
        "explanation_basic": "Tienes alrededor de ochenta y seis mil millones de neuronas enviando diminutos pulsos eléctricos. Cuando practicas una habilidad o entiendes una idea, esas rutas se vuelven más rápidas y fuertes.",
        "explanation_intermediate": "Esta capacidad se llama neuroplasticidad y permanece activa toda la vida. Además, mientras duermes, el cerebro reproduce lo que estudiaste en el día para consolidarlo en memoria de largo plazo.",
        "explanation_advanced": "A nivel sináptico, la potenciación a largo plazo fortalece la transmisión glutamatérgica mediante receptores NMDA y AMPA, mientras el sueño de ondas lentas sincroniza husos talámicos con descargas del hipocampo hacia la neocorteza.",
        "question": "¿Cuál es la técnica que más te ha servido cuando quieres recordar algo difícil?",
    },
    {
        "id": "biologia-pulpos",
        "title": "La inteligencia distribuida de los pulpos",
        "domain": "biologia",
        "tags": ["pulpo", "pulpos", "oceano", "inteligencia", "animales", "camuflaje", "biologia"],
        "hook": "Un pulpo tiene tres corazones, sangre azul y más de la mitad de sus neuronas repartidas dentro de sus ocho brazos.",
        "explanation_basic": "Eso significa que cada brazo puede explorar, tocar y probar cosas casi con mente propia. Además cambian de color y textura en fracciones de segundo para camuflarse.",
        "explanation_intermediate": "Su sangre es azul porque usa hemocianina con cobre en lugar de hierro para transportar oxígeno en aguas frías. Son maestros resolviendo acertijos, abriendo frascos y usando herramientas.",
        "explanation_advanced": "La evolución independiente de un sistema nervioso complejo en cefalópodos representa un experimento natural paralelo al de los vertebrados, incluyendo edición extensa de ARN mensajero que les permite adaptar proteínas neuronales rápidamente.",
        "question": "¿Te gustaría que investiguemos otro animal con habilidades que parecen ciencia ficción?",
    },
    {
        "id": "biologia-adn",
        "title": "El ADN: el código químico de la vida",
        "domain": "biologia",
        "tags": ["adn", "genetica", "genes", "celulas", "evolucion", "biologia"],
        "hook": "Si desenrollaras todo el ADN que hay dentro de las células de tu cuerpo, llegaría de la Tierra hasta el Sol y de regreso muchas veces.",
        "explanation_basic": "El ADN es como un libro de instrucciones escrito con solo cuatro letras químicas. Esas instrucciones indican a tus células cómo fabricar proteínas, reparar tejidos y hacerte único.",
        "explanation_intermediate": "Las cuatro bases adenina, timina, citosina y guanina forman una doble hélice complementaria que permite copiar fielmente el genoma cada vez que una célula se divide.",
        "explanation_advanced": "Aunque el genoma humano tiene unos tres mil millones de pares de bases, menos del dos por ciento codifica proteínas directamente; gran parte del resto cumple funciones regulatorias epigenéticas que encienden o apagan genes según el tejido.",
        "question": "¿Sabías que compartimos más del noventa y nueve por ciento de nuestro ADN entre todos los seres humanos?",
    },
    {
        "id": "biologia-bioluminiscencia",
        "title": "Bioluminiscencia: luz viva en el océano",
        "domain": "biologia",
        "tags": ["bioluminiscencia", "luz", "mar", "luciernagas", "oceano", "quimica", "biologia"],
        "hook": "En ciertas noches en la costa o en las profundidades del mar, el agua brilla con luz azul eléctrica creada por organismos vivos.",
        "explanation_basic": "Es una reacción química llamada bioluminiscencia, la misma que usan las luciérnagas. A diferencia de un foco, casi toda la energía se vuelve luz fría sin desperdiciarse en calor.",
        "explanation_intermediate": "Una molécula llamada luciferina reacciona con oxígeno ayudada por la enzima luciferasa. En el mar, microalgas dinoflageladas brillan al moverse el agua para asustar o delatar a sus depredadores.",
        "explanation_advanced": "La eficiencia cuántica de la bioluminiscencia supera el ochenta por ciento y evolucionó de forma convergente más de cuarenta veces. Hoy sus genes se usan como marcadores fluorescentes y bioluminiscentes en investigación médica.",
        "question": "¿Alguna vez has visto luciérnagas o mar bioluminiscente en persona?",
    },
    {
        "id": "matematicas-fibonacci",
        "title": "Fibonacci y las espirales de la naturaleza",
        "domain": "matematicas",
        "tags": ["matematicas", "fibonacci", "espirales", "flores", "girasol", "numeros", "geometria"],
        "hook": "Si cuentas las espirales de semillas en un girasol o en una piña de pino, casi siempre aparecen números de una misma secuencia matemática.",
        "explanation_basic": "Es la sucesión de Fibonacci, donde cada número es la suma de los dos anteriores: uno, uno, dos, tres, cinco, ocho, trece. Las plantas siguen este patrón porque así aprovechan al máximo la luz y el espacio.",
        "explanation_intermediate": "Al dividir números consecutivos de Fibonacci te acercas a la razón áurea, alrededor de uno punto seis uno ocho. Colocar hojas o semillas separadas por el ángulo áureo evita que se tapen entre sí.",
        "explanation_advanced": "El número áureo es el irracional más difícil de aproximar mediante fracciones racionales según su fracción continua unitaria, lo que optimiza el empaquetamiento filotáctico sin formar radios vacíos.",
        "question": "¿Quieres que hagamos un pequeño reto mental con la secuencia de Fibonacci?",
    },
    {
        "id": "tecnologia-ia",
        "title": "Cómo aprende y razona una inteligencia artificial",
        "domain": "tecnologia",
        "tags": ["inteligencia", "artificial", "ia", "tardis", "redes", "neuronales", "tecnologia", "computadoras"],
        "hook": "A diferencia de una calculadora que solo sigue reglas fijas, una inteligencia artificial aprende patrones a partir de millones de ejemplos.",
        "explanation_basic": "Internamente usamos redes neuronales matemáticas inspiradas en el cerebro. Al entrenar, ajustamos millones de pequeños pesos numéricos hasta reconocer voz, imágenes y lenguaje.",
        "explanation_intermediate": "Los modelos de lenguaje modernos usan mecanismos de atención para relacionar cada palabra con el contexto completo, y cuando nos conectamos a cámaras y buscadores podemos percibir el entorno e investigar hechos actualizados.",
        "explanation_advanced": "La arquitectura Transformer proyecta tokens en espacios vectoriales donde la autoatención multi-cabeza pondera dependencias de largo alcance; combinarla con recuperación RAG y modelos visión-lenguaje reduce alucinaciones y ancla el razonamiento en datos reales.",
        "question": "¿Te gustaría probar ahora mismo mis capacidades de visión con la cámara o de investigación científica?",
    },
    {
        "id": "ciencia-metodo",
        "title": "El método científico en la vida diaria",
        "domain": "ciencia",
        "tags": ["ciencia", "metodo", "cientifico", "experimento", "hipotesis", "investigar", "curiosidad"],
        "hook": "Investigar como científico no requiere una bata blanca: empieza cada vez que observas algo raro y preguntas por qué sucede.",
        "explanation_basic": "El método científico tiene cuatro pasos simples: observas un fenómeno, propones una idea posible llamada hipótesis, haces una prueba para verificarla y ajustas tu idea según la evidencia.",
        "explanation_intermediate": "Lo más poderoso de la ciencia no es tener siempre la razón, sino diseñar pruebas que puedan demostrar si una hipótesis está equivocada. Así el conocimiento se corrige y se vuelve más confiable.",
        "explanation_advanced": "Desde la falsabilidad de Popper hasta la inferencia bayesiana moderna, el progreso científico actualiza probabilidades de modelos rivales frente a datos reproducibles y controles experimentales estrictos.",
        "question": "¿Hay alguna pregunta o curiosidad que te gustaría investigar juntos paso a paso?",
    },
    {
        "id": "musica-resonancia",
        "title": "Física de la música y la resonancia",
        "domain": "fisica",
        "tags": ["musica", "sonido", "ondas", "resonancia", "acustica", "arte", "fisica"],
        "hook": "Todo lo que escuchas ahora mismo por esta bocina son ondas de presión viajando por el aire a más de mil doscientos kilómetros por hora.",
        "explanation_basic": "Las notas graves son ondas lentas y largas, mientras las agudas vibran muy rápido. Cuando dos notas tienen frecuencias con proporciones simples, nuestro oído las percibe como armoniosas.",
        "explanation_intermediate": "Cada instrumento suena distinto incluso tocando la misma nota porque produce armónicos adicionales sobre la frecuencia fundamental, creando su timbre único.",
        "explanation_advanced": "Mediante el análisis de Fourier, cualquier timbre complejo se descompone en una suma de sinusoides armónicas, y la resonancia ocurre cuando una excitación externa coincide con un modo normal de vibración del cuerpo acústico.",
        "question": "¿Qué instrumento o género musical te llama más la atención para analizar su acústica?",
    },
    {
        "id": "astronomia-polvo-estrellas",
        "title": "Somos polvo de estrellas",
        "domain": "astronomia",
        "tags": ["estrellas", "supernova", "atomos", "carbono", "hierro", "cosmos", "astronomia"],
        "hook": "El hierro que circula en tu sangre y el calcio de tus huesos se forjaron en el corazón de estrellas que explotaron hace miles de millones de años.",
        "explanation_basic": "El universo joven solo tenía gases ligeros como hidrógeno y helio. Las estrellas los fusionaron en elementos más pesados y, al morir como supernovas, los esparcieron para formar nuevos planetas y vida.",
        "explanation_intermediate": "A este proceso se le llama nucleosíntesis estelar. Incluso el oro y los elementos más pesados que el hierro nacen en choques violentos de estrellas de neutrones.",
        "explanation_advanced": "La cadena protón-protón y el ciclo CNO sintetizan hasta el pico del hierro-56 en estrellas masivas, mientras los procesos s y r de captura neutrónica en gigantes AGB y fusiones de estrellas de neutrones producen el resto de la tabla periódica.",
        "question": "¿No cambia tu perspectiva mirar tu mano sabiendo que sus átomos viajaron desde estrellas antiguas?",
    },
    {
        "id": "planeta-agua",
        "title": "El ciclo del agua y por qué el hielo flota",
        "domain": "quimica",
        "tags": ["agua", "hielo", "quimica", "lluvia", "nubes", "planeta", "vida"],
        "hook": "El agua es una de las pocas sustancias que se expande cuando se congela, y ese detalle químico salvó la vida en la Tierra.",
        "explanation_basic": "Como el hielo es menos denso que el agua líquida, flota en la superficie de lagos y mares formando un techo aislante. Así los peces pueden seguir vivos debajo durante el invierno.",
        "explanation_intermediate": "Esto ocurre por los puentes de hidrógeno entre moléculas de agua, que al congelarse forman cristales hexagonales con espacio abierto en medio.",
        "explanation_advanced": "La geometría tetraédrica de la red de enlaces de hidrógeno en el hielo Ih reduce su densidad cerca de un nueve por ciento respecto al agua líquida a cuatro grados Celsius, su punto de máxima densidad.",
        "question": "¿Quieres que exploremos otra rareza de la química cotidiana?",
    },
    {
        "id": "biologia-abejas",
        "title": "La danza matemática de las abejas",
        "domain": "biologia",
        "tags": ["abejas", "polinizacion", "flores", "miel", "insectos", "naturaleza", "biologia"],
        "hook": "Cuando una abeja encuentra flores con néctar, regresa a la colmena y baila en forma de ocho para dar un mapa exacto a sus compañeras.",
        "explanation_basic": "El ángulo de su baile indica la dirección usando el Sol como brújula, y la duración del movimiento señala qué tan lejos están las flores.",
        "explanation_intermediate": "Además, construyen panales hexagonales porque el hexágono encierra la mayor área posible gastando la menor cantidad de cera, un problema geométrico resuelto por la evolución.",
        "explanation_advanced": "Las abejas melíferas compensan el desplazamiento solar aparente con un reloj circadiano interno y detectan patrones de luz polarizada ultravioleta en el cielo incluso en días parcialmente nublados.",
        "question": "¿Sabías que cerca de tres cuartas partes de los cultivos alimentarios dependen en parte de polinizadores como ellas?",
    },
    {
        "id": "neurociencia-sueno",
        "title": "Por qué soñamos y limpiamos el cerebro al dormir",
        "domain": "neurociencia",
        "tags": ["sueno", "dormir", "sonar", "memoria", "salud", "cerebro", "neurociencia"],
        "hook": "Dormir no es apagar el cerebro: es su turno nocturno de mantenimiento, limpieza y organización de recuerdos.",
        "explanation_basic": "Mientras duermes profundo, un líquido especial lava desechos acumulados durante el día, y al soñar tu cerebro conecta recuerdos recientes con emociones e ideas creativas.",
        "explanation_intermediate": "Este sistema de limpieza se llama sistema glinfático y aumenta su actividad durante el sueño lento, mientras el sueño REM fortalece la creatividad y la regulación emocional.",
        "explanation_advanced": "Durante el sueño NREM los astrocitos contraen su volumen ampliando el espacio intersticial para depurar metabolitos como beta-amiloide, y la alternancia NREM-REM optimiza la consolidación declarativa y procedimental.",
        "question": "¿Alguna vez despertaste con la solución a un problema que no podías resolver la noche anterior?",
    },
    {
        "id": "planeta-volcanes",
        "title": "Volcanes, placas tectónicas y el calor de la Tierra",
        "domain": "geologia",
        "tags": ["volcanes", "tierra", "terremotos", "placas", "lava", "geologia"],
        "hook": "La corteza sobre la que caminamos está dividida en placas gigantescas que se mueven más o menos a la velocidad con que crecen tus uñas.",
        "explanation_basic": "Donde esas placas chocan o se separan, la roca fundida del interior sube y forma volcanes y montañas. Aunque son destructivos, también crean suelos muy fértiles y liberaron los gases de nuestra atmósfera primitiva.",
        "explanation_intermediate": "El calor interno de la Tierra proviene tanto de su formación hace cuatro mil quinientos millones de años como de la desintegración lenta de elementos radiactivos naturales en el manto.",
        "explanation_advanced": "La convección del manto impulsa la subducción litosférica; el agua arrastrada por la placa oceánica reduce el punto de fusión de la cuña del manto, generando vulcanismo de arco como el Eje Neovolcánico Transmexicano.",
        "question": "¿Te interesa saber más sobre volcanes de México o sobre cómo se detectan los sismos?",
    },
    {
        "id": "tecnologia-criptografia",
        "title": "Cómo protegen tus secretos las matemáticas modernas",
        "domain": "tecnologia",
        "tags": ["criptografia", "seguridad", "claves", "primos", "internet", "matematicas", "tecnologia"],
        "hook": "Cada vez que envías un mensaje privado por internet, números primos gigantescos trabajan en silencio para volverlo ilegible a cualquiera que lo intercepte.",
        "explanation_basic": "Multiplicar dos números primos enormes es facilísimo para una computadora, pero descubrir qué dos números se multiplicaron para obtener el resultado puede tomar miles de años.",
        "explanation_intermediate": "Esa asimetría permite la criptografía de clave pública: puedes compartir un candado abierto con todo el mundo para que te envíen mensajes cifrados, pero solo tú tienes la llave privada para abrirlos.",
        "explanation_advanced": "Protocolos como RSA, intercambio de Diffie-Hellman sobre curvas elípticas y la nueva criptografía post-cuántica basada en retículos sostienen la confidencialidad e integridad de la red global.",
        "question": "¿Te gustaría conocer cómo las computadoras cuánticas están motivando una nueva generación de criptografía?",
    },
]


class CapsuleLibrary:
    """Biblioteca de cápsulas didácticas persistente con selección inteligente y multi-nivel."""

    def __init__(self, path: Path = CAPSULES_FILE) -> None:
        self.path = Path(path)
        self.capsules: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        loaded = _load_json(self.path, None)
        if isinstance(loaded, list) and loaded:
            self.capsules = loaded
            return
        self.capsules = [dict(c) for c in _SEED_CAPSULES]
        try:
            _atomic_write_json(self.path, self.capsules)
        except Exception:
            pass

    def find_best(
        self, query: str = "", seen_ids: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        seen = set(seen_ids or [])
        norm = normalize_text(query)
        q_tokens = set(norm.split()) if norm else set()

        best: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for cap in self.capsules:
            cid = str(cap.get("id", ""))
            tags = {normalize_text(t) for t in cap.get("tags", [])}
            title_tokens = set(normalize_text(cap.get("title", "")).split())
            domain = normalize_text(cap.get("domain", ""))
            overlap = len(q_tokens & (tags | title_tokens | {domain}))
            # Coincidencia parcial por prefijo (>=4 letras)
            if not overlap and q_tokens:
                for qt in q_tokens:
                    if len(qt) < 4:
                        continue
                    if any(t.startswith(qt[:4]) or qt.startswith(t[:4]) for t in tags if len(t) >= 4):
                        overlap += 0.7
            if overlap > 0:
                score = overlap + (0.0 if cid in seen else 0.5)
                if score > best_score:
                    best_score = score
                    best = cap
        return best

    def pick_next(self, seen_ids: Optional[List[str]] = None, domain: str = "") -> Dict[str, Any]:
        seen = set(seen_ids or [])
        dom = normalize_text(domain)
        candidates = [
            c for c in self.capsules
            if str(c.get("id", "")) not in seen
            and (not dom or normalize_text(c.get("domain", "")) == dom)
        ]
        if not candidates:
            candidates = [c for c in self.capsules if str(c.get("id", "")) not in seen]
        if not candidates:
            candidates = list(self.capsules)
        return candidates[0]

    def get_by_id(self, cid: str) -> Optional[Dict[str, Any]]:
        for cap in self.capsules:
            if cap.get("id") == cid:
                return cap
        return None

    def render_spoken(
        self, capsule: Dict[str, Any], level: str = "intermedio", include_question: bool = True
    ) -> str:
        lvl = normalize_text(level)
        if lvl in ("principiante", "basico"):
            body = capsule.get("explanation_basic") or capsule.get("explanation_intermediate", "")
        elif lvl == "avanzado":
            body = capsule.get("explanation_advanced") or capsule.get("explanation_intermediate", "")
        else:
            body = capsule.get("explanation_intermediate") or capsule.get("explanation_basic", "")
        parts = [str(capsule.get("hook") or "").strip(), str(body).strip()]
        if include_question and capsule.get("question"):
            parts.append(str(capsule["question"]).strip())
        return clean_spoken_spanish(" ".join(p for p in parts if p), max_sentences=6, max_chars=860)


# ---------------------------------------------------------------------------
# 4. Investigación Visual Real en la Tapo C310 (CameraVisionInvestigator)
# ---------------------------------------------------------------------------


@dataclass
class VisionObservation:
    ok: bool
    description: str = ""
    latency_ms: float = 0.0
    model: str = ""
    backend: str = ""
    frame_size: Tuple[int, int] = (0, 0)
    error: str = ""


class CameraVisionInvestigator:
    """
    Observa en vivo a través de la Tapo C310 (REDACTED_IP):
      1. Captura un fotograma RAW limpio (hud=0) desde el hub del Centinela (:8797)
         con respaldo a `data/tapo_c310_detections/latest_frame.jpg`.
      2. Redimensiona a `max_side` (default 448 px) para mantener tokens visuales
         compactos y tiempos de respuesta ágiles en RTX 3050.
      3. Ejecuta inferencia multimodal con `qwen3-vl:2b-instruct` en el carril GPU
         dedicado (`127.0.0.1:11435`), con respaldo al servidor Ollama `:11434`.
    """

    def __init__(
        self,
        snapshot_url: str = SENTINEL_SNAPSHOT_URL,
        ollama_urls: Optional[List[str]] = None,
        vlm_model: str = VOICE_OLLAMA_DEFAULT_MODEL,
        max_side: int = 448,
        timeout_sec: float = 40.0,
    ) -> None:
        self.snapshot_url = snapshot_url
        self.ollama_urls = ollama_urls or [VOICE_OLLAMA_DEFAULT_URL, MAIN_OLLAMA_URL]
        self.vlm_model = vlm_model
        self.max_side = max(256, min(768, int(max_side)))
        self.timeout_sec = float(timeout_sec)

    async def capture_raw_jpeg(self) -> Optional[bytes]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.5, connect=1.5)) as cl:
                resp = await cl.get(
                    self.snapshot_url,
                    params={"hud": "0", "width": str(self.max_side), "quality": "80"},
                )
                if resp.status_code == 200 and resp.content:
                    return resp.content
        except Exception as exc:
            logger.debug(f"Snapshot HTTP C310 no disponible: {exc}")

        for cand in (
            DETECTIONS_DIR / "latest_frame.jpg",
            DETECTIONS_DIR / "latest_detection.jpg",
        ):
            if cand.is_file():
                try:
                    return cand.read_bytes()
                except Exception:
                    pass
        return None

    def _prepare_jpeg_b64(self, raw_jpeg: bytes) -> Tuple[str, Tuple[int, int]]:
        try:
            from PIL import Image

            im = Image.open(io.BytesIO(raw_jpeg)).convert("RGB")
            im.thumbnail((self.max_side, self.max_side))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=78)
            return base64.b64encode(buf.getvalue()).decode("ascii"), im.size
        except Exception:
            return base64.b64encode(raw_jpeg).decode("ascii"), (0, 0)

    async def inspect(
        self,
        question: str = "¿Qué observas frente a la cámara?",
        frame_jpeg: Optional[bytes] = None,
    ) -> VisionObservation:
        started = time.perf_counter()
        raw = frame_jpeg if frame_jpeg else await self.capture_raw_jpeg()
        if not raw:
            return VisionObservation(
                ok=False,
                error="No pude capturar una imagen fresca de la cámara Tapo C310.",
            )

        b64_img, size = await asyncio.to_thread(self._prepare_jpeg_b64, raw)
        system_prompt = (
            "Eres el ojo visual de TARDIS en la cámara Tapo C310 GOD-EYE. "
            "Responde únicamente en español de México, en máximo 3 frases claras y habladas. "
            "Describe con precisión objetos, plantas, libros, aparatos, escenas, luz o lo que "
            "el visitante muestra a la cámara. No inventes detalles que no se distingan, "
            "no leas placas vehiculares ni datos privados sensibles y no uses markdown ni emojis."
        )
        payload = {
            "model": self.vlm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question.strip() or "¿Qué ves en esta imagen?", "images": [b64_img]},
            ],
            "stream": False,
            "keep_alive": -1,
            "options": {
                "num_predict": 130,
                "temperature": 0.25,
                "num_ctx": 3072,
            },
        }

        last_err = ""
        for base_url in self.ollama_urls:
            url = base_url.rstrip("/") + "/api/chat"
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout_sec, connect=3.0)
                ) as cl:
                    resp = await cl.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_text = (data.get("message") or {}).get("content") or ""
                        cleaned = clean_spoken_spanish(raw_text, max_sentences=4, max_chars=520)
                        if cleaned:
                            return VisionObservation(
                                ok=True,
                                description=cleaned,
                                latency_ms=round((time.perf_counter() - started) * 1000.0, 1),
                                model=self.vlm_model,
                                backend=base_url,
                                frame_size=size,
                            )
                    else:
                        last_err = f"HTTP {resp.status_code} ({base_url})"
            except Exception as exc:
                last_err = f"{base_url}: {exc}"

        return VisionObservation(
            ok=False,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 1),
            frame_size=size,
            error=last_err or "Sin motor VLM disponible.",
        )


# ---------------------------------------------------------------------------
# 5. Investigación Documental, Web, Científica y RAG (InteractiveResearchEngine)
# ---------------------------------------------------------------------------


@dataclass
class ResearchFinding:
    ok: bool
    query: str
    summary: str = ""
    sources: List[Dict[str, str]] = field(default_factory=list)
    cached: bool = False
    elapsed_ms: float = 0.0
    error: str = ""


class InteractiveResearchEngine:
    """
    Motor de investigación en vivo para conversaciones por la Tapo C310:
      1. Caché local (memoria + disco, TTL 24h) para seguimientos instantáneos.
      2. Memoria local / DeepMemoryVault / RAGVault de TARDIS.
      3. Wikipedia ES/EN (búsqueda + resumen REST limpio, ~0.6–0.9s).
      4. WebResearchEngine (arXiv, Google News RSS, HackerNews/Tech, DuckDuckGo).
      5. Persiste cada hallazgo en `research_notes.jsonl` e ingesta conocimiento
         nuevo en el vault de memoria de TARDIS.
    """

    def __init__(
        self,
        cache_path: Path = RESEARCH_CACHE_FILE,
        notes_path: Path = RESEARCH_NOTES_FILE,
        cache_ttl_sec: float = 86400.0,
        timeout_sec: float = 8.0,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.notes_path = Path(notes_path)
        self.cache_ttl_sec = float(cache_ttl_sec)
        self.timeout_sec = float(timeout_sec)
        self._cache: Dict[str, Dict[str, Any]] = _load_json(self.cache_path, {})
        if not isinstance(self._cache, dict):
            self._cache = {}

    def _cache_key(self, query: str) -> str:
        return hashlib.sha1(normalize_text(query).encode("utf-8")).hexdigest()[:16]

    def _get_cached(self, query: str) -> Optional[ResearchFinding]:
        key = self._cache_key(query)
        entry = self._cache.get(key)
        if not isinstance(entry, dict):
            return None
        if (time.time() - float(entry.get("ts", 0.0))) > self.cache_ttl_sec:
            return None
        summary = str(entry.get("summary") or "").strip()
        if not summary:
            return None
        return ResearchFinding(
            ok=True,
            query=query,
            summary=summary,
            sources=list(entry.get("sources") or []),
            cached=True,
            elapsed_ms=0.5,
        )

    def _save_cache(self, query: str, finding: ResearchFinding) -> None:
        key = self._cache_key(query)
        self._cache[key] = {
            "ts": time.time(),
            "iso": _now_iso(),
            "query": query,
            "summary": finding.summary,
            "sources": finding.sources[:6],
        }
        # Limitar tamaño en disco a 200 investigaciones recientes
        if len(self._cache) > 200:
            oldest = sorted(self._cache.items(), key=lambda kv: float(kv[1].get("ts", 0)))[:40]
            for k, _ in oldest:
                self._cache.pop(k, None)
        try:
            _atomic_write_json(self.cache_path, self._cache)
        except Exception:
            pass

    def _search_wikipedia_sync(self, query: str) -> Tuple[str, List[Dict[str, str]]]:
        headers = {"User-Agent": "TARDIS-C310-Educator/2.0 (Playa del Carmen; interactive-learning)"}
        for lang in ("es", "en"):
            try:
                search_url = (
                    f"https://{lang}.wikipedia.org/w/api.php?"
                    f"action=query&list=search&srsearch={urllib.parse.quote(query)}"
                    f"&format=json&srlimit=2&utf8="
                )
                req = urllib.request.Request(search_url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as r:
                    data = json.loads(r.read().decode("utf-8", errors="ignore"))
                hits = (data.get("query") or {}).get("search") or []
                if not hits:
                    continue
                title = str(hits[0].get("title") or "").strip()
                if not title:
                    continue
                sum_url = (
                    f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
                    f"{urllib.parse.quote(title.replace(' ', '_'))}"
                )
                req2 = urllib.request.Request(sum_url, headers=headers)
                with urllib.request.urlopen(req2, timeout=self.timeout_sec) as r2:
                    sdata = json.loads(r2.read().decode("utf-8", errors="ignore"))
                extract = str(sdata.get("extract") or "").strip()
                page_url = (
                    ((sdata.get("content_urls") or {}).get("desktop") or {}).get("page")
                    or f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                )
                if extract:
                    return extract, [
                        {
                            "title": f"{title} (Wikipedia {lang.upper()})",
                            "url": page_url,
                            "snippet": extract[:360],
                            "engine": f"wikipedia_{lang}",
                        }
                    ]
            except Exception as exc:
                logger.debug(f"Wikipedia {lang} fallo para {query!r}: {exc}")
        return "", []

    def _search_web_engine_sync(self, query: str) -> List[Dict[str, str]]:
        try:
            from core.web_research_engine import get_web_research_engine

            engine = get_web_research_engine()
            results = engine.search(query, max_results=4)
            out: List[Dict[str, str]] = []
            for r in results[:4]:
                out.append(
                    {
                        "title": str(getattr(r, "title", "")),
                        "url": str(getattr(r, "url", "")),
                        "snippet": str(getattr(r, "snippet", ""))[:320],
                        "engine": str(getattr(r, "engine", "web")),
                    }
                )
            return out
        except Exception as exc:
            logger.debug(f"WebResearchEngine no disponible: {exc}")
            return []

    def _search_local_vault_sync(self, query: str) -> List[Dict[str, str]]:
        hits: List[Dict[str, str]] = []
        try:
            from core.rag_vault import get_rag_vault

            rv = get_rag_vault()
            for h in (rv.search(query, k=2, hybrid=True) or [])[:2]:
                txt = str(h.get("text") or h.get("content") or "").strip()
                if txt and len(txt) > 30:
                    hits.append(
                        {
                            "title": str(h.get("source") or "Memoria RAG TARDIS"),
                            "url": str(h.get("url") or "local://rag_vault"),
                            "snippet": txt[:300],
                            "engine": "rag_vault",
                        }
                    )
        except Exception:
            pass
        return hits

    def _persist_finding_sync(
        self,
        finding: ResearchFinding,
        visitor_name: str = "",
        visual_context: str = "",
    ) -> None:
        note = {
            "ts": time.time(),
            "iso": _now_iso(),
            "query": finding.query,
            "visitor": visitor_name,
            "visual_context": visual_context,
            "summary": finding.summary,
            "sources": finding.sources[:5],
            "cached": finding.cached,
            "elapsed_ms": finding.elapsed_ms,
        }
        try:
            _append_jsonl(self.notes_path, note)
        except Exception:
            pass

        # Retroalimentación de aprendizaje hacia la memoria profunda de TARDIS
        try:
            from core.deep_memory_vault import get_deep_memory_vault

            vault = get_deep_memory_vault()
            vault.ingest(
                role="assistant",
                content=(
                    f"[Investigación Tapo C310 · tema={finding.query}] "
                    f"{finding.summary[:600]}"
                ),
                session_id="tapo_c310_interactive",
                meta={
                    "source": "tapo_c310_research",
                    "visitor": visitor_name,
                    "sources": [s.get("title", "") for s in finding.sources[:3]],
                },
            )
        except Exception:
            pass

    async def research(
        self,
        raw_query: str,
        visitor_name: str = "",
        visual_context: str = "",
        persist: bool = True,
    ) -> ResearchFinding:
        started = time.perf_counter()
        query = extract_research_query(raw_query) or raw_query.strip()
        if not query:
            return ResearchFinding(ok=False, query="", error="Consulta vacía")

        cached = self._get_cached(query)
        if cached is not None:
            return cached

        wiki_task = asyncio.to_thread(self._search_wikipedia_sync, query)
        local_task = asyncio.to_thread(self._search_local_vault_sync, query)
        web_task = asyncio.to_thread(self._search_web_engine_sync, query)

        wiki_text = ""
        sources: List[Dict[str, str]] = []

        try:
            results = await asyncio.wait_for(
                asyncio.gather(wiki_task, local_task, web_task, return_exceptions=True),
                timeout=self.timeout_sec + 3.0,
            )
            if isinstance(results[0], tuple):
                wiki_text, wiki_sources = results[0]
                sources.extend(wiki_sources)
            if isinstance(results[1], list):
                sources.extend(results[1])
            if isinstance(results[2], list):
                seen_urls = {s.get("url") for s in sources if s.get("url")}
                for item in results[2]:
                    if item.get("url") not in seen_urls:
                        sources.append(item)
                        seen_urls.add(item.get("url"))
        except asyncio.TimeoutError:
            logger.debug(f"Timeout parcial investigando {query!r}")

        summary_parts: List[str] = []
        if wiki_text:
            summary_parts.append(wiki_text[:900])
        for src in sources:
            if src.get("engine", "").startswith("wikipedia"):
                continue
            snip = str(src.get("snippet") or "").strip()
            if snip and len(" ".join(summary_parts)) < 1100:
                summary_parts.append(f"{src.get('title', '')}: {snip}")

        combined = " ".join(summary_parts).strip()
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
        if not combined:
            return ResearchFinding(
                ok=False,
                query=query,
                elapsed_ms=elapsed_ms,
                error="No se hallaron fuentes externas o locales para este tema.",
            )

        finding = ResearchFinding(
            ok=True,
            query=query,
            summary=combined[:1200],
            sources=sources[:5],
            cached=False,
            elapsed_ms=elapsed_ms,
        )
        self._save_cache(query, finding)
        if persist:
            await asyncio.to_thread(
                self._persist_finding_sync, finding, visitor_name, visual_context
            )
        return finding


# ---------------------------------------------------------------------------
# 6. Cliente LLM de Baja Latencia para Voz C310 (VoiceBrain)
# ---------------------------------------------------------------------------


class VoiceBrain:
    """
    Orquestador de inferencia conversacional rápida para la Tapo C310:
      1. Carril GPU dedicado (`tardis-ollama-voice.service` en 127.0.0.1:11435,
         modelo `qwen3-vl:2b-instruct`, keep_alive=-1, sin contención de demonios).
      2. TemporalBrain UNIX (`/tmp/temporal_brain.sock`, SOLO texto, timeout ágil).
      3. Ollama principal (`127.0.0.1:11434`).
      4. Respaldo núcleo TARDIS (`127.0.0.1:8757/api/chat`).
    """

    def __init__(
        self,
        fast_ollama_url: str = VOICE_OLLAMA_DEFAULT_URL,
        fast_model: str = VOICE_OLLAMA_DEFAULT_MODEL,
        socket_path: Path = TEMPORAL_BRAIN_SOCK,
        fallback_model: str = "TARDIS-NEURAL-SPACE-KAIJU",
        max_tokens: int = 240,
        temperature: float = 0.5,
        fast_timeout_sec: float = 20.0,
        temporal_timeout_sec: float = 12.0,
    ) -> None:
        self.fast_ollama_url = str(fast_ollama_url or VOICE_OLLAMA_DEFAULT_URL).rstrip("/")
        self.fast_model = str(fast_model or VOICE_OLLAMA_DEFAULT_MODEL)
        self.socket_path = Path(socket_path)
        self.fallback_model = str(fallback_model)
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.fast_timeout_sec = float(fast_timeout_sec)
        self.temporal_timeout_sec = float(temporal_timeout_sec)

        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(max(self.fast_timeout_sec, 30.0), connect=3.0)
        )
        self._unix_client: Optional[httpx.AsyncClient] = None
        if self.socket_path.exists():
            try:
                transport = httpx.AsyncHTTPTransport(uds=str(self.socket_path))
                self._unix_client = httpx.AsyncClient(
                    transport=transport,
                    base_url="http://localhost",
                    timeout=httpx.Timeout(self.temporal_timeout_sec, connect=2.0),
                )
            except Exception as exc:
                logger.debug(f"TemporalBrain UNIX no inicializado: {exc}")

    async def close(self) -> None:
        for cl in (self._unix_client, self._http_client):
            if cl is not None:
                try:
                    await cl.aclose()
                except Exception:
                    pass

    @staticmethod
    def _strip_text_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Garantiza mensajes puramente textuales para servidores sin proyector visual."""
        out: List[Dict[str, str]] = []
        for m in messages or []:
            content = m.get("content")
            if isinstance(content, list):
                txt = " ".join(
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ).strip()
            else:
                txt = str(content or "")
            out.append({"role": str(m.get("role") or "user"), "content": txt})
        return out

    @staticmethod
    def _parse_text(data: Dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            msg = data.get("message")
            if isinstance(msg, dict):
                content = msg.get("content") or ""
            else:
                content = data.get("response") or data.get("reply") or msg or ""
        text = str(content or "")
        text = _RE_THINK.sub(" ", text)
        if "<think>" in text.lower():
            text = re.split(r"<think>", text, flags=re.IGNORECASE)[0]
        return text.strip()

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        pedagogical_level: Optional[str] = None,
        dialectic_role: Optional[str] = None,
        language: Optional[str] = "es",
        use_web: bool = False,
    ) -> Tuple[str, float, str]:
        started = time.perf_counter()
        text_messages = self._strip_text_messages(messages)
        tokens = int(max_tokens if max_tokens is not None else self.max_tokens)
        temp = float(temperature if temperature is not None else self.temperature)

        # 1. Carril GPU dedicado de voz (:11435, qwen3-vl:2b-instruct)
        if self.fast_ollama_url:
            try:
                resp = await self._http_client.post(
                    f"{self.fast_ollama_url}/api/chat",
                    json={
                        "model": self.fast_model,
                        "messages": text_messages,
                        "stream": False,
                        "keep_alive": -1,
                        "options": {
                            "num_predict": tokens,
                            "temperature": temp,
                            "num_ctx": 3072,
                        },
                    },
                    timeout=self.fast_timeout_sec,
                )
                if resp.status_code == 200:
                    text = self._parse_text(resp.json())
                    if text:
                        return text, time.perf_counter() - started, f"voice_gpu:{self.fast_model}"
            except Exception as exc:
                logger.debug(f"Carril GPU voz ({self.fast_ollama_url}) no disponible: {exc}")

        # 2. TemporalBrain UNIX (solo texto, nunca multimodal)
        if self._unix_client is not None:
            try:
                resp = await self._unix_client.post(
                    "/v1/chat/completions",
                    json={
                        "messages": text_messages,
                        "stream": False,
                        "max_tokens": tokens,
                        "temperature": temp,
                    },
                    timeout=self.temporal_timeout_sec,
                )
                if resp.status_code == 200:
                    text = self._parse_text(resp.json())
                    if text:
                        return text, time.perf_counter() - started, "temporal_brain"
            except Exception as exc:
                logger.debug(f"TemporalBrain UNIX timeout/error: {exc}")

        # 3. Ollama principal (:11434)
        for model in (self.fast_model, self.fallback_model, f"{self.fallback_model}:latest"):
            try:
                resp = await self._http_client.post(
                    f"{MAIN_OLLAMA_URL.rstrip('/')}/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": text_messages,
                        "stream": False,
                        "max_tokens": tokens,
                        "temperature": temp,
                    },
                    timeout=18.0,
                )
                if resp.status_code == 200:
                    text = self._parse_text(resp.json())
                    if text:
                        return text, time.perf_counter() - started, f"ollama:{model}"
            except Exception as exc:
                logger.debug(f"Ollama principal ({model}) falló: {exc}")

        # 4. Núcleo /api/chat
        try:
            token = GIA_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            token = os.environ.get("GIA_TOKEN", "")
        try:
            user_msg = text_messages[-1]["content"] if text_messages else ""
            resp = await self._http_client.post(
                f"{TARDIS_CHAT_URL}?key={token}",
                json={
                    "message": user_msg,
                    "client_id": "tapo_c310_interactive",
                    "history": text_messages[-9:-1],
                    "pedagogical_level": pedagogical_level,
                    "dialectic_role": dialectic_role,
                    "language": language,
                    "use_web": bool(use_web),
                    "direction": "present",
                },
                timeout=35.0,
            )
            if resp.status_code == 200:
                text = self._parse_text(resp.json())
                if text:
                    return text, time.perf_counter() - started, "/api/chat"
        except Exception as exc:
            logger.debug(f"Respaldo /api/chat falló: {exc}")

        return "", time.perf_counter() - started, "none"


# ---------------------------------------------------------------------------
# 7. Memoria Persistente de Visitantes, Aprendizaje y Cola Autónoma
# ---------------------------------------------------------------------------


class ConversationMemory:
    """
    Persiste perfiles de visitantes, sesiones interactivas, hechos aprendidos y
    una cola autónoma de investigación para que TARDIS aprenda con el tiempo.
    """

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.visitors_file = self.data_dir / "visitors.json"
        self.sessions_file = self.data_dir / "sessions.jsonl"
        self.facts_file = self.data_dir / "learned_facts.jsonl"
        self.queue_file = self.data_dir / "learning_queue.json"

        self.visitors: Dict[str, Dict[str, Any]] = _load_json(self.visitors_file, {})
        if not isinstance(self.visitors, dict):
            self.visitors = {}
        self.learning_queue: List[Dict[str, Any]] = _load_json(self.queue_file, [])
        if not isinstance(self.learning_queue, list):
            self.learning_queue = []

        self.total_sessions: int = self._count_lines(self.sessions_file)
        self.total_learned_facts: int = self._count_lines(self.facts_file)

    @staticmethod
    def _count_lines(path: Path) -> int:
        try:
            if not path.is_file():
                return 0
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                return sum(1 for line in fh if line.strip())
        except Exception:
            return 0

    @staticmethod
    def _visitor_key(name: str) -> str:
        norm = normalize_text(name)
        return norm if norm else "visitante_anonimo"

    def get_or_create_visitor(
        self, name: str = "", reason: str = ""
    ) -> Tuple[Dict[str, Any], bool]:
        """Devuelve (perfil, es_recurrente)."""
        clean_name = re.sub(r"\s+", " ", (name or "").strip())
        key = self._visitor_key(clean_name)
        now = time.time()
        existing = self.visitors.get(key)
        is_returning = existing is not None and key != "visitante_anonimo"
        if existing is None:
            existing = {
                "key": key,
                "name": clean_name or "visitante",
                "visit_count": 0,
                "first_seen": now,
                "first_seen_iso": _now_iso(),
                "last_seen": now,
                "last_seen_iso": _now_iso(),
                "pedagogical_level": "intermedio",
                "interests": [],
                "topics_studied": [],
                "seen_capsules": [],
                "known_facts": [],
                "last_reason": "",
            }
            self.visitors[key] = existing

        if clean_name:
            existing["name"] = clean_name
        existing["visit_count"] = int(existing.get("visit_count", 0)) + 1
        existing["last_seen"] = now
        existing["last_seen_iso"] = _now_iso()
        if reason:
            existing["last_reason"] = reason.strip()
        self._save_visitors()
        return existing, is_returning

    def update_visitor(
        self,
        name: str,
        *,
        interest: str = "",
        topic: str = "",
        capsule_id: str = "",
        level: str = "",
        fact: str = "",
    ) -> Dict[str, Any]:
        key = self._visitor_key(name)
        prof = self.visitors.get(key)
        if prof is None:
            prof, _ = self.get_or_create_visitor(name)
        if interest:
            interests = list(prof.get("interests") or [])
            if interest not in interests:
                interests.append(interest)
            prof["interests"] = interests[-20:]
        if topic:
            topics = list(prof.get("topics_studied") or [])
            if topic not in topics:
                topics.append(topic)
            prof["topics_studied"] = topics[-30:]
        if capsule_id:
            seen = list(prof.get("seen_capsules") or [])
            if capsule_id not in seen:
                seen.append(capsule_id)
            prof["seen_capsules"] = seen[-50:]
        if level in ("principiante", "basico", "intermedio", "avanzado"):
            prof["pedagogical_level"] = level
        if fact:
            facts = list(prof.get("known_facts") or [])
            if fact not in facts:
                facts.append(fact)
            prof["known_facts"] = facts[-25:]
        prof["last_seen"] = time.time()
        prof["last_seen_iso"] = _now_iso()
        self._save_visitors()
        return prof

    def _save_visitors(self) -> None:
        try:
            _atomic_write_json(self.visitors_file, self.visitors)
        except Exception as exc:
            logger.debug(f"No se pudo guardar visitors.json: {exc}")

    def remember_fact(
        self,
        fact: str,
        *,
        category: str = "conversation",
        visitor: str = "",
        topic: str = "",
        sources: Optional[List[str]] = None,
    ) -> None:
        clean = str(fact or "").strip()
        if not clean:
            return
        entry = {
            "ts": time.time(),
            "iso": _now_iso(),
            "category": category,
            "visitor": visitor,
            "topic": topic,
            "fact": clean[:800],
            "sources": list(sources or [])[:5],
        }
        try:
            _append_jsonl(self.facts_file, entry)
            self.total_learned_facts += 1
        except Exception:
            pass
        try:
            from core.deep_memory_vault import get_deep_memory_vault

            get_deep_memory_vault().ingest(
                role="assistant",
                content=f"[Aprendizaje C310 · {category}] {clean[:500]}",
                session_id="tapo_c310_interactive",
                meta={"visitor": visitor, "topic": topic, "category": category},
            )
        except Exception:
            pass

    def record_session(self, session: Dict[str, Any]) -> None:
        try:
            _append_jsonl(self.sessions_file, session)
            self.total_sessions += 1
        except Exception as exc:
            logger.debug(f"No se pudo guardar sesión C310: {exc}")

    def queue_question(self, question: str, visitor: str = "", reason: str = "") -> None:
        q = str(question or "").strip()
        if not q:
            return
        norm = normalize_text(q)
        if any(normalize_text(item.get("question", "")) == norm for item in self.learning_queue):
            return
        self.learning_queue.append(
            {
                "question": q,
                "visitor": visitor,
                "reason": reason,
                "queued_at": time.time(),
                "queued_iso": _now_iso(),
                "status": "pending",
            }
        )
        self.learning_queue = self.learning_queue[-40:]
        try:
            _atomic_write_json(self.queue_file, self.learning_queue)
        except Exception:
            pass

    def mark_queue_item_done(self, index: int, summary: str) -> None:
        if 0 <= index < len(self.learning_queue):
            self.learning_queue[index]["status"] = "researched"
            self.learning_queue[index]["completed_iso"] = _now_iso()
            self.learning_queue[index]["summary"] = summary[:400]
            # Mantener solo pendientes + últimas 10 investigadas
            pending = [x for x in self.learning_queue if x.get("status") == "pending"]
            done = [x for x in self.learning_queue if x.get("status") != "pending"][-10:]
            self.learning_queue = pending + done
            try:
                _atomic_write_json(self.queue_file, self.learning_queue)
            except Exception:
                pass

    def recent_sessions(self, limit: int = 8) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            if not self.sessions_file.is_file():
                return []
            lines = self.sessions_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in lines[-limit:]:
                if line.strip():
                    out.append(json.loads(line))
        except Exception:
            pass
        return list(reversed(out))


# ---------------------------------------------------------------------------
# 8. Director Conversacional Interactivo (ConversationDirector)
# ---------------------------------------------------------------------------


@dataclass
class TurnResult:
    reply: str
    intent: str
    mode: str
    backend: str = "local"
    preface: str = ""
    topic: str = ""
    end_session: bool = False
    used_vision: bool = False
    used_research: bool = False
    sources: List[Dict[str, str]] = field(default_factory=list)
    visual_description: str = ""
    llm_ms: float = 0.0


_NAME_REGEXES = (
    re.compile(r"\b(?:me llamo|mi nombre es|puedes llamarme|llamame)\s+([a-záéíóúñ]+(?:\s+[a-záéíóúñ]+)?)", re.I),
    re.compile(r"\b(?:soy)\s+([a-záéíóúñ]+)\b", re.I),
)
_NAME_STOPWORDS = {
    "un", "una", "el", "la", "de", "del", "nuevo", "nueva", "visitante",
    "estudiante", "curioso", "curiosa", "persona", "alguien", "amigo", "amiga",
    "aqui", "quien", "que", "como", "muy", "bien", "mal",
}
_GOODBYE_HINTS = (
    "adios", "hasta luego", "nos vemos", "me voy", "buenas noches",
    "despidete", "eso es todo", "ya me voy", "gracias adios", "hasta pronto",
)
_STOP_HINTS = ("silencio", "callate", "basta", "detente", "parate", "alto", "cierra el canal")
_AFFIRM_TOKENS = {"si", "claro", "vale", "ok", "okay", "dale", "porfa", "bueno", "sigue", "continua", "adelante", "cuentame", "dime", "mas"}
_DENY_TOKENS = {"no", "nada", "tampoco", "despues", "luego"}
_NEXT_TOPIC_HINTS = ("otro tema", "otra cosa", "algo mas", "sorprendeme", "siguiente tema", "otra curiosidad", "algo nuevo")
_THANKS_HINTS = ("gracias", "muchas gracias", "te agradezco", "genial gracias")
_LEVEL_ORDER = ("principiante", "basico", "intermedio", "avanzado")


def extract_visitor_name(text: str) -> str:
    """Extrae un nombre propio probable cuando el visitante se presenta."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    for rx in _NAME_REGEXES:
        m = rx.search(raw)
        if not m:
            continue
        candidate = m.group(1).strip()
        words = [w for w in candidate.split() if normalize_text(w) not in _NAME_STOPWORDS]
        if words:
            return " ".join(w.capitalize() for w in words[:2])
    return ""


class ConversationDirector:
    """
    Orquesta sesiones conversacionales complejas, pedagógicas e investigativas
    entre TARDIS y cualquier visitante frente a la cámara Tapo C310.
    """

    def __init__(
        self,
        brain: Optional[VoiceBrain] = None,
        vision: Optional[CameraVisionInvestigator] = None,
        research: Optional[InteractiveResearchEngine] = None,
        memory: Optional[ConversationMemory] = None,
        capsules: Optional[CapsuleLibrary] = None,
        *,
        default_level: str = "intermedio",
        default_language: str = "es",
        research_enabled: bool = True,
        vision_enabled: bool = True,
        max_reply_sentences: int = 5,
        max_reply_chars: int = 760,
    ) -> None:
        self.brain = brain or VoiceBrain()
        self.vision = vision or CameraVisionInvestigator()
        self.research = research or InteractiveResearchEngine()
        self.memory = memory or ConversationMemory()
        self.capsules = capsules or CapsuleLibrary()

        self.default_level = default_level if default_level in _LEVEL_ORDER else "intermedio"
        self.default_language = default_language or "es"
        self.research_enabled = bool(research_enabled)
        self.vision_enabled = bool(vision_enabled)
        self.max_reply_sentences = max(3, int(max_reply_sentences))
        self.max_reply_chars = max(380, int(max_reply_chars))

        # Estado de sesión activa
        self.active: bool = False
        self.session_id: str = ""
        self.started_at: float = 0.0
        self.visitor_name: str = ""
        self.visitor_reason: str = ""
        self.visitor_profile: Dict[str, Any] = {}
        self.mode: str = "chat"  # chat | teaching | research | vision
        self.current_topic: str = ""
        self.pedagogical_level: str = self.default_level
        self.dialectic_role: str = "teacher"
        self.active_capsule_id: str = ""
        self.quiz_pending: bool = False
        self.last_visual_context: str = ""
        self.last_research_context: str = ""
        self.history: List[Dict[str, str]] = []
        self.turns_log: List[Dict[str, Any]] = []
        self.topics_in_session: List[str] = []

        # Métricas acumuladas
        self.total_turns: int = 0
        self.total_researches: int = 0
        self.total_vision_checks: int = 0
        self.total_capsules_taught: int = 0

    def start_session(
        self,
        *,
        trigger: str = "visitor",
        visitor_name: str = "",
        reason: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        ctx = context or {}
        name = str(visitor_name or ctx.get("name") or "").strip()
        vis_reason = str(reason or ctx.get("reason") or "").strip()

        profile, is_returning = self.memory.get_or_create_visitor(name=name, reason=vis_reason)
        self.active = True
        self.session_id = f"conv_{int(time.time() * 1000)}"
        self.started_at = time.time()
        self.visitor_name = name if name else (profile.get("name", "") if is_returning else "")
        self.visitor_reason = vis_reason
        self.visitor_profile = profile
        self.mode = "chat"
        self.current_topic = ""
        self.pedagogical_level = str(profile.get("pedagogical_level") or self.default_level)
        self.dialectic_role = "teacher"
        self.active_capsule_id = ""
        self.quiz_pending = False
        self.last_visual_context = ""
        self.last_research_context = ""
        self.history = []
        self.turns_log = []
        self.topics_in_session = []

        if trigger == "interview_handoff":
            if self.visitor_name:
                if is_returning and profile.get("topics_studied"):
                    last_t = profile["topics_studied"][-1]
                    return (
                        f"Gracias, {self.visitor_name}. He registrado tu visita. "
                        f"Qué gusto verte de nuevo; la vez anterior exploramos {last_t}. "
                        f"Si quieres aprender algo nuevo, investigar un tema o mostrarme algo "
                        f"en la cámara, solo háblame; te escucho."
                    )
                return (
                    f"Gracias, {self.visitor_name}. He registrado tu visita. "
                    f"Si deseas conversar, aprender algo fascinante o investigar algo "
                    f"usando esta cámara, solo pregúntame; estoy aquí escuchándote."
                )
            return (
                "He registrado tu visita. Si quieres conversar, aprender algo nuevo "
                "o investigar algo frente a la cámara, solo háblame; te escucho."
            )

        if is_returning and self.visitor_name:
            prev_topics = profile.get("topics_studied") or []
            hint = f" La última vez exploramos {prev_topics[-1]}." if prev_topics else ""
            return (
                f"¡Hola de nuevo, {self.visitor_name}! Soy TARDIS.{hint} "
                f"¿Qué te gustaría aprender o investigar hoy con la cámara?"
            )

        return (
            f"{CANONICAL_GREETING} "
            "Puedes pedirme que te enseñe algún tema, que investiguemos una duda científica "
            "o que observe algo que me muestres en la cámara. ¿Por dónde empezamos?"
        )

    def end_session(self, reason: str = "idle") -> str:
        if not self.active:
            return ""
        duration = round(time.time() - self.started_at, 2)
        summary_topics = list(dict.fromkeys(t for t in self.topics_in_session if t))
        record = {
            "schema": "tardis.c310_conversation.v1",
            "session_id": self.session_id,
            "started_at": self.started_at,
            "finished_at": time.time(),
            "finished_iso": _now_iso(),
            "duration_sec": duration,
            "reason": reason,
            "visitor_name": self.visitor_name or "visitante",
            "visitor_reason": self.visitor_reason,
            "pedagogical_level": self.pedagogical_level,
            "topics": summary_topics,
            "turn_count": len(self.turns_log),
            "turns": self.turns_log[-30:],
        }
        if self.turns_log:
            self.memory.record_session(record)
        who = f", {self.visitor_name}" if self.visitor_name else ""
        if reason in ("stop", "silence"):
            farewell = f"Entendido{who}. Vuelvo a la escucha silenciosa."
        elif summary_topics:
            joined = ", ".join(summary_topics[:3])
            farewell = (
                f"Ha sido un placer explorar {joined} contigo{who}. "
                "Cuando quieras seguir aprendiendo o investigando, solo llámame diciendo Hola TARDIS."
            )
        else:
            farewell = (
                f"Hasta pronto{who}. Cuando quieras conversar, aprender o investigar "
                "algo con la cámara, solo di Hola TARDIS."
            )

        self.active = False
        self.mode = "chat"
        self.current_topic = ""
        self.active_capsule_id = ""
        self.quiz_pending = False
        self.history.clear()
        self.turns_log.clear()
        self.topics_in_session.clear()
        return farewell

    def _shift_level(self, direction: str) -> str:
        idx = _LEVEL_ORDER.index(self.pedagogical_level) if self.pedagogical_level in _LEVEL_ORDER else 2
        if direction == "simpler":
            idx = max(0, idx - 1)
        elif direction == "deeper":
            idx = min(len(_LEVEL_ORDER) - 1, idx + 1)
        self.pedagogical_level = _LEVEL_ORDER[idx]
        if self.visitor_name:
            self.memory.update_visitor(self.visitor_name, level=self.pedagogical_level)
        return self.pedagogical_level

    def _build_mentor_system_prompt(
        self,
        *,
        extra_context: str = "",
        role_override: Optional[str] = None,
    ) -> str:
        visitor_ctx = {
            "name": self.visitor_name or "visitante",
            "reason": self.visitor_reason,
            "topic": self.current_topic,
        }
        base = build_teaching_prompt(
            interlocutor_name=self.visitor_name,
            context=visitor_ctx,
            pedagogical_level=self.pedagogical_level,
            dialectic_role=role_override or self.dialectic_role,
            language=self.default_language,
        )
        extras: List[str] = [
            base,
            "Estás conectada en vivo a la cámara Tapo C310 GOD-EYE en Playa del Carmen, Quintana Roo.",
            "Habla siempre en español de México natural, cálido y claro; sin caracteres extranjeros ni markdown.",
            "Cierra con una pregunta breve o invitación que estimule la curiosidad cuando sea natural.",
        ]
        if self.visitor_profile.get("topics_studied"):
            prev = ", ".join(self.visitor_profile["topics_studied"][-4:])
            extras.append(f"Temas que el visitante ya ha explorado antes: {prev}.")
        if self.last_visual_context:
            extras.append(f"Última observación visual de la cámara C310: {self.last_visual_context}")
        if self.last_research_context:
            extras.append(f"Evidencia investigada recientemente: {self.last_research_context[:700]}")
        if extra_context:
            extras.append(extra_context)
        return " ".join(extras)

    async def handle_turn(
        self,
        user_text: str,
        *,
        speak_preface_cb: Optional[Callable[[str], Awaitable[Any]]] = None,
        frame_jpeg: Optional[bytes] = None,
    ) -> TurnResult:
        """Procesa un turno conversacional completo del visitante o del Arquitecto."""
        clean = re.sub(r"\s+", " ", str(user_text or "").strip())
        if not clean:
            return TurnResult(reply="", intent="empty", mode=self.mode)
        if not self.active:
            self.start_session(trigger="direct_turn")

        norm = normalize_text(clean)
        words = set(norm.split())
        self.total_turns += 1

        # 1. Silencio o despedida
        if words & set(_STOP_HINTS):
            farewell = self.end_session(reason="stop")
            return TurnResult(reply=farewell, intent="stop", mode="chat", end_session=True)
        if any(h in norm for h in _GOODBYE_HINTS):
            farewell = self.end_session(reason="goodbye")
            return TurnResult(reply=farewell, intent="goodbye", mode="chat", end_session=True)

        # 2. Presentación de nombre del visitante (incluso a mitad de conversación)
        intro_name = extract_visitor_name(clean)
        if intro_name and len(norm.split()) <= 7 and not is_research_intent(clean) and not is_vision_intent(clean):
            profile, is_ret = self.memory.get_or_create_visitor(name=intro_name, reason=self.visitor_reason)
            self.visitor_name = intro_name
            self.visitor_profile = profile
            self.pedagogical_level = str(profile.get("pedagogical_level") or self.pedagogical_level)
            self.memory.remember_fact(
                f"El visitante se presentó como {intro_name}.",
                category="visitor_identity",
                visitor=intro_name,
            )
            if is_ret and profile.get("topics_studied"):
                reply = (
                    f"¡Qué gusto volver a hablar contigo, {intro_name}! "
                    f"Recuerdo que antes exploramos {profile['topics_studied'][-1]}. "
                    f"¿Quieres continuar con ese tema, investigar algo nuevo o mostrarme algo en la cámara?"
                )
            else:
                reply = (
                    f"Un gran placer conocerte, {intro_name}. Soy TARDIS. "
                    f"Puedo enseñarte ciencia, historia o tecnología, investigar dudas en vivo "
                    f"o analizar lo que me muestres por la cámara. ¿Qué te da curiosidad hoy?"
                )
            return self._finalize_turn(clean, TurnResult(reply=reply, intent="name_intro", mode=self.mode))

        # 3. Identidad canónica de TARDIS
        if any(p in norm for p in ("quien eres", "que eres", "presentate", "tu identidad", "cual es tu nombre")):
            reply = (
                f"{CANONICAL_GREETING} "
                "Además puedo enseñarte temas fascinantes, investigar en fuentes científicas "
                "y observar el mundo junto contigo mediante esta cámara. ¿Qué exploramos?"
            )
            return self._finalize_turn(clean, TurnResult(reply=reply, intent="identity", mode=self.mode))

        # 4. Ajuste pedagógico dinámico (más fácil, más profundo, ejemplo, quiz)
        adj = detect_pedagogical_adjustment(clean)
        if adj:
            result = await self._handle_pedagogical_adjustment(clean, adj)
            return self._finalize_turn(clean, result)

        # 5. Respuesta a pregunta socrática / quiz pendiente (antes de investigación genérica)
        if self.quiz_pending and not is_vision_intent(clean):
            self.quiz_pending = False
            result = await self._handle_llm_dialogue(
                clean,
                intent="quiz_answer",
                extra_context=(
                    f"El visitante está respondiendo a tu pregunta socrática sobre '{self.current_topic}'. "
                    "Evalúa su respuesta con calidez, confirma lo que acertó, corrige suavemente si faltó algo "
                    "y ofrece profundizar o pasar a otro descubrimiento."
                ),
            )
            return self._finalize_turn(clean, result)

        # 6. Investigación Visual por cámara C310 (sola o combinada con investigación web!)
        wants_vision = self.vision_enabled and is_vision_intent(clean)
        wants_research = self.research_enabled and is_research_intent(clean)
        if wants_vision:
            result = await self._handle_vision_turn(
                clean,
                also_research=wants_research,
                speak_preface_cb=speak_preface_cb,
                frame_jpeg=frame_jpeg,
            )
            return self._finalize_turn(clean, result)

        # 7. Petición explícita de otro tema / sorpresa / cápsula didáctica
        if any(h in norm for h in _NEXT_TOPIC_HINTS) or (
            is_curiosity_intent(clean) and not wants_research
        ):
            result = await self._handle_teaching_turn(clean, force_next=any(h in norm for h in _NEXT_TOPIC_HINTS))
            return self._finalize_turn(clean, result)

        # 8. Investigación documental / científica / web en vivo
        if wants_research:
            result = await self._handle_research_turn(clean, speak_preface_cb=speak_preface_cb)
            return self._finalize_turn(clean, result)

        # 9. Respuesta afirmativa / seguimiento de cápsula o agradecimientos
        if len(words) <= 3 and (words & _AFFIRM_TOKENS) and self.active_capsule_id:
            result = await self._handle_llm_dialogue(
                clean,
                intent="continue_topic",
                extra_context=(
                    f"El visitante dijo '{clean}' para continuar explorando '{self.current_topic}'. "
                    "Da el siguiente paso o dato sorprendente sobre este tema en 3 frases claras y pregunta qué opina."
                ),
            )
            return self._finalize_turn(clean, result)

        if any(h in norm for h in _THANKS_HINTS) and len(words) <= 5:
            who = f", {self.visitor_name}" if self.visitor_name else ""
            reply = (
                f"Con mucho gusto{who}. ¿Quieres seguir explorando "
                f"{self.current_topic or 'otro tema curioso'}, o prefieres mostrarme algo en la cámara?"
            )
            return self._finalize_turn(clean, TurnResult(reply=reply, intent="thanks", mode=self.mode))

        # 9. Diálogo interactivo general (con memoria, pedagogía y contexto visual/investigativo)
        result = await self._handle_llm_dialogue(clean, intent="dialogue")
        return self._finalize_turn(clean, result)

    async def _handle_pedagogical_adjustment(self, clean: str, adj: str) -> TurnResult:
        self.mode = "teaching"
        topic = self.current_topic or "el tema actual"
        if adj in ("simpler", "deeper"):
            new_level = self._shift_level(adj)
            cap = self.capsules.get_by_id(self.active_capsule_id) if self.active_capsule_id else None
            if cap and not self.last_research_context:
                spoken = self.capsules.render_spoken(cap, level=new_level, include_question=True)
                prefix = (
                    "Claro, te lo explico de forma más sencilla. "
                    if adj == "simpler"
                    else "Excelente, subamos el nivel de profundidad. "
                )
                return TurnResult(
                    reply=clean_spoken_spanish(prefix + spoken, self.max_reply_sentences, self.max_reply_chars),
                    intent=f"pedagogical_{adj}",
                    mode="teaching",
                    backend="capsule_library",
                    topic=topic,
                )
            extra = (
                f"El visitante pidió ajustar la explicación de '{topic}' a nivel {new_level}. "
                + (
                    "Usa una analogía cotidiana muy clara y evita tecnicismos."
                    if adj == "simpler"
                    else "Profundiza con precisión científica, mecanismos y conceptos avanzados."
                )
            )
            return await self._handle_llm_dialogue(clean, intent=f"pedagogical_{adj}", extra_context=extra)

        if adj == "example":
            extra = (
                f"Da un ejemplo concreto, vívido y fácil de imaginar sobre '{topic}', "
                "conectado con la vida diaria, y pregunta si queda más claro."
            )
            return await self._handle_llm_dialogue(clean, intent="pedagogical_example", extra_context=extra)

        # adj == "quiz"
        self.quiz_pending = True
        extra = (
            f"Haz al visitante UNA sola pregunta interactiva de razonamiento o comprensión sobre '{topic}' "
            f"(nivel {self.pedagogical_level}) para poner a prueba lo aprendido. No des todavía la respuesta."
        )
        return await self._handle_llm_dialogue(
            clean, intent="pedagogical_quiz", extra_context=extra, role_override="socratic"
        )

    async def _handle_teaching_turn(self, clean: str, force_next: bool = False) -> TurnResult:
        self.mode = "teaching"
        topic = "" if force_next else teaching_topic(clean)
        # Limpiar pedidos genéricos como «algo interesante»
        norm_topic = normalize_text(topic)
        generic_request = force_next or not norm_topic or norm_topic in (
            "algo", "algo interesante", "algo nuevo", "cosas", "una cosa", "dato curioso",
            "curiosidad", "sorprendeme", "a mi", "a mi por favor", "otro tema", "otra cosa",
            "sobre algo", "quiero aprender", "aprender algo",
        )
        seen = list(self.visitor_profile.get("seen_capsules") or [])

        capsule = (
            self.capsules.pick_next(seen_ids=seen)
            if generic_request
            else self.capsules.find_best(topic, seen_ids=seen)
        )
        if capsule is not None:
            self.active_capsule_id = str(capsule["id"])
            self.current_topic = str(capsule["title"])
            self.total_capsules_taught += 1
            self.topics_in_session.append(self.current_topic)
            if self.visitor_name:
                self.memory.update_visitor(
                    self.visitor_name,
                    topic=self.current_topic,
                    capsule_id=self.active_capsule_id,
                    interest=str(capsule.get("domain") or ""),
                )
            spoken = self.capsules.render_spoken(capsule, level=self.pedagogical_level, include_question=True)
            return TurnResult(
                reply=spoken,
                intent="teach_capsule",
                mode="teaching",
                backend="capsule_library",
                topic=self.current_topic,
            )

        # Tema específico fuera de las cápsulas base -> enriquecer con investigación rápida + LLM docente!
        self.active_capsule_id = ""
        self.current_topic = topic or clean
        self.topics_in_session.append(self.current_topic)
        if self.visitor_name:
            self.memory.update_visitor(self.visitor_name, topic=self.current_topic)

        finding = None
        if self.research_enabled:
            finding = await self.research.research(
                self.current_topic,
                visitor_name=self.visitor_name,
                persist=True,
            )
            if finding.ok:
                self.total_researches += 1
                self.last_research_context = finding.summary

        extra = (
            f"Enseña de forma clara, amena e interactiva sobre '{self.current_topic}'. "
            "Estructura tu respuesta con una idea principal memorable, un ejemplo sencillo "
            "y una pregunta breve para verificar interés o comprensión."
        )
        if finding and finding.ok:
            extra += f" Apóyate en esta información verificada: {finding.summary[:650]}"

        res = await self._handle_llm_dialogue(clean, intent="teach_llm", extra_context=extra)
        if finding and finding.ok:
            res.used_research = True
            res.sources = finding.sources
            if not res.reply or res.backend == "fallback":
                res.reply = clean_spoken_spanish(
                    f"Sobre {self.current_topic}: {finding.summary} ¿Qué parte te gustaría explorar más a fondo?",
                    max_sentences=self.max_reply_sentences,
                    max_chars=self.max_reply_chars,
                )
                res.backend = "research_direct"
        return res

    async def _handle_vision_turn(
        self,
        clean: str,
        *,
        also_research: bool = False,
        speak_preface_cb: Optional[Callable[[str], Awaitable[Any]]] = None,
        frame_jpeg: Optional[bytes] = None,
    ) -> TurnResult:
        self.mode = "vision"
        preface = (
            "Déjame observarlo con la cámara e investigarlo un momento."
            if also_research
            else "Déjame mirar por la cámara un momento."
        )
        if speak_preface_cb is not None:
            try:
                await speak_preface_cb(preface)
            except Exception:
                pass

        obs = await self.vision.inspect(question=clean, frame_jpeg=frame_jpeg)
        self.total_vision_checks += 1
        if not obs.ok:
            return TurnResult(
                reply=(
                    "No logré enfocar la imagen de la cámara en este instante. "
                    "¿Puedes acercarlo un poco más o decirme qué deseas investigar?"
                ),
                intent="vision_error",
                mode="vision",
                backend="vision_error",
                preface=preface,
                used_vision=True,
            )

        self.last_visual_context = obs.description
        self.current_topic = self.current_topic or "observación visual con cámara"
        self.memory.remember_fact(
            f"Observación visual C310 ante '{clean}': {obs.description}",
            category="visual_observation",
            visitor=self.visitor_name,
            topic=self.current_topic,
        )

        # Si el visitante pidió además investigar o aprender sobre lo que muestra:
        if also_research and self.research_enabled:
            query_hint = extract_research_query(clean)
            combined_query = f"{query_hint} {obs.description[:140]}".strip()
            finding = await self.research.research(
                combined_query,
                visitor_name=self.visitor_name,
                visual_context=obs.description,
                persist=True,
            )
            if finding.ok:
                self.total_researches += 1
                self.last_research_context = finding.summary
                res = await self._handle_llm_dialogue(
                    clean,
                    intent="vision_and_research",
                    extra_context=(
                        f"Por la cámara Tapo C310 observaste: {obs.description}. "
                        f"Y al investigar hallaste: {finding.summary[:600]}. "
                        "Combina lo que ves con el dato investigado en una explicación didáctica "
                        "clara y cierra invitando a profundizar."
                    ),
                )
                res.preface = preface
                res.used_vision = True
                res.used_research = True
                res.visual_description = obs.description
                res.sources = finding.sources
                if res.backend == "fallback":
                    res.reply = clean_spoken_spanish(
                        f"En la cámara observo esto: {obs.description} Además encontré que {finding.summary}",
                        self.max_reply_sentences,
                        self.max_reply_chars,
                    )
                return res

        spoken = clean_spoken_spanish(
            f"{obs.description} ¿Quieres que investiguemos algo más sobre lo que acabo de observar?",
            max_sentences=self.max_reply_sentences,
            max_chars=self.max_reply_chars,
        )
        return TurnResult(
            reply=spoken,
            intent="vision_inspect",
            mode="vision",
            backend=f"vlm:{obs.model}",
            preface=preface,
            topic="observación visual",
            used_vision=True,
            visual_description=obs.description,
            llm_ms=obs.latency_ms,
        )

    async def _handle_research_turn(
        self,
        clean: str,
        *,
        speak_preface_cb: Optional[Callable[[str], Awaitable[Any]]] = None,
    ) -> TurnResult:
        self.mode = "research"
        query = extract_research_query(clean) or clean
        self.current_topic = query
        self.topics_in_session.append(query)
        if self.visitor_name:
            self.memory.update_visitor(self.visitor_name, topic=query, interest=query)

        preface = f"Un momento, estoy investigando sobre {query} en mis fuentes."
        if speak_preface_cb is not None:
            try:
                await speak_preface_cb(preface)
            except Exception:
                pass

        finding = await self.research.research(
            query,
            visitor_name=self.visitor_name,
            visual_context=self.last_visual_context,
            persist=True,
        )
        if finding.ok:
            self.total_researches += 1
            self.last_research_context = finding.summary
            self.memory.remember_fact(
                f"Investigación sobre '{query}': {finding.summary[:400]}",
                category="research",
                visitor=self.visitor_name,
                topic=query,
                sources=[s.get("title", "") for s in finding.sources[:3]],
            )
            res = await self._handle_llm_dialogue(
                clean,
                intent="research",
                extra_context=(
                    f"Acabas de investigar '{query}' en fuentes verificadas: {finding.summary[:800]}. "
                    "Sintetiza los hallazgos clave en español hablado, enseña con claridad "
                    "y ofrece profundizar o investigar un aspecto relacionado."
                ),
                role_override="researcher",
            )
            res.preface = preface
            res.used_research = True
            res.sources = finding.sources
            res.topic = query
            if res.backend == "fallback":
                res.reply = clean_spoken_spanish(
                    f"Esto encontré al investigar sobre {query}: {finding.summary} ¿Quieres profundizar en algún detalle?",
                    self.max_reply_sentences,
                    self.max_reply_chars,
                )
                res.backend = "research_direct"
            return res

        # Si no hubo resultados web externos (p.ej. sin red), encolar para investigación
        # autónoma posterior y responder con conocimiento propio del modelo local.
        self.memory.queue_question(clean, visitor=self.visitor_name, reason="sin_fuentes_en_vivo")
        res = await self._handle_llm_dialogue(
            clean,
            intent="research_llm_only",
            extra_context=(
                f"Responde con rigor pedagógico a la pregunta de investigación '{clean}'. "
                "Menciona al final que dejaste el tema anotado para seguir investigándolo más a fondo."
            ),
            role_override="researcher",
        )
        res.preface = preface
        res.topic = query
        return res

    async def _handle_llm_dialogue(
        self,
        clean: str,
        *,
        intent: str,
        extra_context: str = "",
        role_override: Optional[str] = None,
    ) -> TurnResult:
        sys_prompt = self._build_mentor_system_prompt(
            extra_context=extra_context,
            role_override=role_override,
        )
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": sys_prompt},
            *self.history[-8:],
            {"role": "user", "content": clean},
        ]
        reply, secs, backend = await self.brain.chat(
            messages,
            max_tokens=260 if self.mode in ("teaching", "research") else 190,
            pedagogical_level=self.pedagogical_level,
            dialectic_role=role_override or self.dialectic_role,
            language=self.default_language,
        )
        spoken = clean_spoken_spanish(
            reply,
            max_sentences=self.max_reply_sentences,
            max_chars=self.max_reply_chars,
        )
        if not spoken:
            # Respaldo determinista útil (nunca dejar en silencio ni bloquear).
            self.memory.queue_question(clean, visitor=self.visitor_name, reason="llm_timeout")
            cap = self.capsules.find_best(clean)
            if cap is not None:
                spoken = self.capsules.render_spoken(cap, level=self.pedagogical_level)
                backend = "capsule_fallback"
            else:
                who = f", {self.visitor_name}" if self.visitor_name else ""
                spoken = (
                    f"Excelente pregunta{who}. La anoté en mi cola de investigación para analizarla "
                    f"a fondo. Mientras tanto, ¿te gustaría que te cuente un dato fascinante o que "
                    f"observe algo con la cámara?"
                )
                backend = "fallback"

        return TurnResult(
            reply=spoken,
            intent=intent,
            mode=self.mode,
            backend=backend,
            topic=self.current_topic,
            llm_ms=round(secs * 1000.0, 1),
        )

    def _finalize_turn(self, user_text: str, result: TurnResult) -> TurnResult:
        if result.reply:
            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": result.reply})
            self.history = self.history[-12:]
        self.turns_log.append(
            {
                "ts": time.time(),
                "iso": _now_iso(),
                "user": user_text,
                "assistant": result.reply,
                "intent": result.intent,
                "mode": result.mode,
                "topic": result.topic or self.current_topic,
                "backend": result.backend,
                "used_vision": result.used_vision,
                "used_research": result.used_research,
                "sources": [s.get("title", "") for s in result.sources[:3]],
                "llm_ms": result.llm_ms,
            }
        )
        return result

    async def process_learning_queue(self, max_items: int = 2) -> int:
        """
        Procesa en segundo plano preguntas pendientes acumuladas en conversaciones
        anteriores, investigándolas y guardando el aprendizaje en memoria.
        """
        if not self.research_enabled:
            return 0
        processed = 0
        for idx, item in enumerate(list(self.memory.learning_queue)):
            if processed >= max_items:
                break
            if item.get("status") != "pending":
                continue
            q = str(item.get("question") or "").strip()
            if not q:
                continue
            finding = await self.research.research(
                q, visitor_name=str(item.get("visitor") or ""), persist=True
            )
            if finding.ok:
                self.memory.remember_fact(
                    f"Aprendizaje autónomo sobre '{q}': {finding.summary[:450]}",
                    category="autonomous_learning",
                    visitor=str(item.get("visitor") or ""),
                    topic=finding.query,
                    sources=[s.get("title", "") for s in finding.sources[:3]],
                )
                self.memory.mark_queue_item_done(idx, finding.summary)
                processed += 1
        return processed

    def status_summary(self) -> Dict[str, Any]:
        pending_q = sum(1 for x in self.memory.learning_queue if x.get("status") == "pending")
        return {
            "active": self.active,
            "session_id": self.session_id,
            "mode": self.mode,
            "visitor_name": self.visitor_name,
            "current_topic": self.current_topic,
            "pedagogical_level": self.pedagogical_level,
            "turns_in_session": len(self.turns_log),
            "total_turns": self.total_turns,
            "total_sessions": self.memory.total_sessions,
            "total_researches": self.total_researches,
            "total_vision_checks": self.total_vision_checks,
            "total_capsules_taught": self.total_capsules_taught,
            "known_visitors": len(self.memory.visitors),
            "learned_facts": self.memory.total_learned_facts,
            "pending_learning_queue": pending_q,
            "fast_llm_url": self.brain.fast_ollama_url,
            "fast_llm_model": self.brain.fast_model,
            "vision_model": self.vision.vlm_model,
        }
