"""core/voice/tts_prosody.py - Sanitización prosódica es-MX, alineación por palabra y Piper ONNX / Edge TTS."""
from __future__ import annotations

from core.voice.common import *
from core.voice.vad_segmentation import strip_accents, normalize_key

# ==============================================================================
# 7. SANITIZACIÓN PROSÓDICA + PIPER ONNX TTS LOCAL + HÍBRIDO EDGE-TTS
# ==============================================================================

_RE_THINK = re.compile(r"<think>[\s\S]*?(?:</think>|\Z)", re.IGNORECASE)
_RE_HW_DIRECTIVE = re.compile(r"\[\[HW_ACTION:[\s\S]*?\]\]", re.IGNORECASE)
_RE_MD_CODE = re.compile(r"```[\s\S]*?(?:```|\Z)")
_RE_MD_INLINE_CODE = re.compile(r"`([^`]+)`")
_RE_MD_TABLE = re.compile(r"^\s*\|.*$", re.MULTILINE)
_RE_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_RE_URL = re.compile(r"https?://\S+")
_RE_HTML = re.compile(r"</?[a-zA-Z][^>]*>")
_RE_MD_CHARS = re.compile(r"[*_#>|~•●▪►₪]+")
_RE_NON_LATIN = re.compile(r"[^\x20-\x7E\u00A0-\u00FF\u0100-\u017F\u2010-\u2027\u2030-\u205E\n]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…:;])\s+|\n+")


# Mapa de dicción fonética para espeak-ng / Piper es-MX:
# Corrige anglicismos, acrónimos técnicos y nombres del ecosistema para una
# pronunciación cálida, fluida y natural en español de México.
_ES_MX_PHONETIC_DICTION: List[Tuple[re.Pattern, str]] = [
    # Nombres de herramientas / subsistemas que espeak es-MX lee literal mal
    (re.compile(r"\bBluetooth\b", re.IGNORECASE), "blutuz"),
    (re.compile(r"\bPipeWire\b", re.IGNORECASE), "paip guayer"),
    (re.compile(r"\bWhisper\b", re.IGNORECASE), "güísper"),
    (re.compile(r"\bfaster[\s-]?whisper\b", re.IGNORECASE), "fáster güísper"),
    (re.compile(r"\bOllama\b", re.IGNORECASE), "olama"),
    (re.compile(r"\bHyprland\b", re.IGNORECASE), "jáiperland"),
    (re.compile(r"\bWayland\b", re.IGNORECASE), "güéiland"),
    (re.compile(r"\bWi[\s-]?Fi\b", re.IGNORECASE), "guái fai"),
    (re.compile(r"\bPython\b", re.IGNORECASE), "páiton"),
    (re.compile(r"\bGitHub\b", re.IGNORECASE), "guítjab"),
    (re.compile(r"\bWebSocket\b", re.IGNORECASE), "güebsóquet"),
    (re.compile(r"\bFastAPI\b", re.IGNORECASE), "fast api"),
    (re.compile(r"\bONNX\b", re.IGNORECASE), "ónix"),
    (re.compile(r"\bNVIDIA\b", re.IGNORECASE), "envidia"),
    (re.compile(r"\bRyzen\b", re.IGNORECASE), "ráisen"),
    (re.compile(r"\bPiper\b", re.IGNORECASE), "páiper"),
    (re.compile(r"\bSilero\b", re.IGNORECASE), "siléro"),
    (re.compile(r"\bAntigravity\b", re.IGNORECASE), "antigráviti"),
    (re.compile(r"\bGODWORKS\b", re.IGNORECASE), "god güorks"),
    (re.compile(r"\bTemporalBrain\b", re.IGNORECASE), "temporal brein"),
    (re.compile(r"\bKAIJU\b", re.IGNORECASE), "kaiyu"),
    (re.compile(r"\bEVOIR\b", re.IGNORECASE), "evuár"),
    (re.compile(r"\bBarge[\s-]?In\b", re.IGNORECASE), "barch in"),
    (re.compile(r"\bsystemd\b", re.IGNORECASE), "sístem de"),
    (re.compile(r"\bkernel\b", re.IGNORECASE), "quérnel"),
    (re.compile(r"\bJSON\b"), "yéison"),
    (re.compile(r"\bLinux\b", re.IGNORECASE), "línux"),
    (re.compile(r"\bVRAM\b"), "ve ram"),
    (re.compile(r"\bCPU\b"), "ce pe u"),
    (re.compile(r"\bGPU\b"), "ge pe u"),
    (re.compile(r"\bSTT\b"), "ese te te"),
    (re.compile(r"\bTTS\b"), "te te ese"),
    (re.compile(r"\bVAD\b"), "ve a de"),
    (re.compile(r"\bLLM\b"), "ele ele eme"),
    (re.compile(r"\bCLI\b"), "ce ele i"),
    (re.compile(r"\bAPI\b"), "api"),
    (re.compile(r"\bUSB\b"), "u ese be"),
    (re.compile(r"\bSSD\b"), "ese ese de"),
    (re.compile(r"\bHFP\b"), "hache efe pe"),
    (re.compile(r"\bA2DP\b"), "a dos de pe"),
    (re.compile(r"\bPCM\b"), "pe ce eme"),
    (re.compile(r"\bWAV\b"), "guav"),
    (re.compile(r"\bMP3\b", re.IGNORECASE), "eme pe tres"),
    # Abreviaturas frecuentes del español hablado
    (re.compile(r"\bp\.\s*ej\.", re.IGNORECASE), "por ejemplo"),
    (re.compile(r"\bej\.", re.IGNORECASE), "por ejemplo"),
    (re.compile(r"\betc\.", re.IGNORECASE), "etcétera"),
    (re.compile(r"\bvs\.?\b", re.IGNORECASE), "versus"),
    (re.compile(r"\baprox\.", re.IGNORECASE), "aproximadamente"),
    (re.compile(r"\bmáx\.", re.IGNORECASE), "máximo"),
    (re.compile(r"\bmín\.", re.IGNORECASE), "mínimo"),
    (re.compile(r"\bseg\.", re.IGNORECASE), "segundos"),
]


def prepare_text_for_speech(text: str, *, phonetic_diction: bool = True) -> str:
    """
    Convierte texto técnico/Markdown en prosa hablada natural en español mexicano
    para Piper ONNX y Edge TTS (expande unidades, limpia código/URLs/pensamiento
    y optimiza la dicción fonética de términos técnicos y anglicismos).
    """
    if not text:
        return ""
    body = _RE_THINK.sub(" ", text)
    body = _RE_HW_DIRECTIVE.sub(" ", body)
    body = _RE_MD_CODE.sub(" ", body)
    body = _RE_MD_TABLE.sub(" ", body)
    body = _RE_MD_LINK.sub(r"\1", body)
    body = _RE_URL.sub(" ", body)
    body = _RE_HTML.sub(" ", body)
    body = _RE_MD_INLINE_CODE.sub(r"\1", body)
    # Preservar ritmo en saltos de línea convirtiéndolos en pausas naturales si falta puntuación
    body = re.sub(r"([A-Za-zÁÉÍÓÚáéíóúÑñ0-9])\s*\n+\s*", r"\1. ", body)
    body = _RE_MD_CHARS.sub(" ", body)

    # Versiones técnicas tipo v26.4 -> versión 26 punto 4
    body = re.sub(r"\bv(\d+)\.(\d+)(?:\.(\d+))?\b", lambda m: (
        f"versión {m.group(1)} punto {m.group(2)}" + (f" punto {m.group(3)}" if m.group(3) else "")
    ), body, flags=re.IGNORECASE)
    # Fracciones tipo 22/29 -> 22 de 29
    body = re.sub(r"\b(\d{1,3})/(\d{1,3})\b", r"\1 de \2", body)

    # Expansiones prosódicas naturales para unidades técnicas
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*°\s*C\b", r"\1 grados Celsius", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*°\s*F\b", r"\1 grados Fahrenheit", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", r"\1 por ciento", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*GHz\b", r"\1 gigahercios", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*MHz\b", r"\1 megahercios", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*kHz\b", r"\1 kilohercios", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*Hz\b", r"\1 hercios", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*(?:GiB|GB)\b", r"\1 gigabytes", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*(?:MiB|MB)\b", r"\1 megabytes", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*(?:KiB|KB)\b", r"\1 kilobytes", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*ms\b", r"\1 milisegundos", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*RPM\b", r"\1 revoluciones por minuto", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*dBFS\b", r"\1 decibelios", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*dB\b", r"\1 decibelios", body)
    body = re.sub(r"\bkm/h\b", "kilómetros por hora", body, flags=re.IGNORECASE)
    body = re.sub(r"\btok/s\b", "tokens por segundo", body, flags=re.IGNORECASE)

    if phonetic_diction:
        for pat, rep in _ES_MX_PHONETIC_DICTION:
            body = pat.sub(rep, body)

    # Mejorar pausas expresivas alrededor de guiones largos y paréntesis
    body = re.sub(r"\s*[—–]\s*", ", ", body)
    body = re.sub(r"\(([^()]{1,90})\)", r", \1, ", body)
    body = body.replace("...", "… ")

    body = _RE_NON_LATIN.sub(" ", body)
    body = re.sub(r"\s+([.,;:!?…])", r"\1", body)
    body = re.sub(r",\s*,+", ", ", body)
    body = re.sub(r"\.{2,}", ".", body)
    body = re.sub(r"\s+", " ", body).strip()
    return body


@dataclass
class ExpressiveProsody:
    """Parámetros expresivos dinámicos para Piper ONNX por oración/cláusula."""
    style: str = "warm"
    length_scale: float = 0.96
    noise_scale: float = 0.64
    noise_w_scale: float = 0.80
    trailing_pause_ms: int = 210


def analyze_expressive_prosody(
    text: str,
    *,
    base_rate: Any = "+6%",
    style_hint: str = "",
) -> ExpressiveProsody:
    """
    Calcula la prosodia expresiva óptima para la dicción de TARDIS según
    puntuación, tono discursivo e intención (pregunta, exclamación, técnico, cálido).
    """
    base_ls = _rate_to_length_scale(base_rate)
    s = (text or "").strip()
    low = normalize_key(s)
    hint = (style_hint or "").strip().lower()

    # Determinar pausa natural de respiración al cierre de la cláusula
    if s.endswith(("?", "!", "…")):
        pause_ms = 240
    elif s.endswith("."):
        pause_ms = 210
    elif s.endswith((":", ";")):
        pause_ms = 175
    elif s.endswith(","):
        pause_ms = 120
    else:
        pause_ms = 160

    if "?" in s or "¿" in s:
        return ExpressiveProsody(
            style="inquisitive",
            length_scale=round(max(0.74, min(1.22, base_ls * 0.98)), 3),
            noise_scale=0.69,
            noise_w_scale=0.85,
            trailing_pause_ms=pause_ms,
        )
    if "!" in s or "¡" in s or any(g in low for g in ("un placer", "arquitecto", "excelente", "listo", "perfecto")):
        return ExpressiveProsody(
            style="expressive",
            length_scale=round(max(0.74, min(1.22, base_ls * 0.96)), 3),
            noise_scale=0.70,
            noise_w_scale=0.86,
            trailing_pause_ms=pause_ms,
        )
    if hint in ("detailed", "step_by_step", "technical", "dictation") or any(
        k in low for k in ("primero", "segundo", "paso", "temperatura", "frecuencia", "megahercios", "gigabytes", "milisegundos")
    ):
        return ExpressiveProsody(
            style="articulate",
            length_scale=round(max(0.80, min(1.25, base_ls * 1.04)), 3),
            noise_scale=0.56,
            noise_w_scale=0.72,
            trailing_pause_ms=max(pause_ms, 220),
        )
    if hint in ("calm", "concise") or len(s) <= 32:
        return ExpressiveProsody(
            style="calm",
            length_scale=round(max(0.76, min(1.22, base_ls * 1.00)), 3),
            noise_scale=0.60,
            noise_w_scale=0.76,
            trailing_pause_ms=pause_ms,
        )
    return ExpressiveProsody(
        style="warm",
        length_scale=round(max(0.76, min(1.22, base_ls * 0.99)), 3),
        noise_scale=0.64,
        noise_w_scale=0.80,
        trailing_pause_ms=pause_ms,
    )


def polish_tts_pcm(
    pcm_bytes: bytes,
    sample_rate: int = PIPER_SAMPLE_RATE,
    *,
    trailing_pause_ms: int = 190,
) -> bytes:
    """
    Pulido acústico de calidad estudio para el PCM generado por Piper ONNX:
      - Recorta silencio muerto excesivo al inicio/fin conservando ataque natural.
      - Normaliza sonoridad suavemente hacia -18 dBFS con limitador tanh anti-clipping.
      - Aplica rampa fade-in (12 ms) y fade-out (18 ms) para eliminar clics en Bluetooth EVOIR.
      - Añade pausa prosódica natural entre cláusulas/oraciones.
    """
    if not pcm_bytes or len(pcm_bytes) < 64:
        return pcm_bytes
    usable = len(pcm_bytes) - (len(pcm_bytes) % 2)
    samples = np.frombuffer(pcm_bytes[:usable], dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size < 64:
        return pcm_bytes

    # 1. Recorte suave de silencio muerto inicial/final
    abs_s = np.abs(samples)
    active = np.where(abs_s > 0.0045)[0]
    if active.size > 0:
        lead_pad = int(sample_rate * 0.025)
        tail_pad = int(sample_rate * 0.055)
        s_idx = max(0, int(active[0]) - lead_pad)
        e_idx = min(samples.size, int(active[-1]) + tail_pad)
        if e_idx > s_idx + 32:
            samples = samples[s_idx:e_idx]

    # 2. Nivelación RMS suave hacia -18 dBFS (0.126) evitando picos bruscos
    rms = float(np.sqrt(np.mean(samples * samples)))
    if 0.008 < rms:
        target_rms = 0.135
        gain = min(2.2, max(0.65, target_rms / rms))
        samples = samples * gain
        peak = float(np.max(np.abs(samples)))
        if peak > 0.90:
            samples = np.tanh(samples * 1.08) * 0.92

    # 3. Fade-in 12 ms / Fade-out 18 ms anti-pop
    fi = min(int(sample_rate * 0.012), samples.size // 4)
    fo = min(int(sample_rate * 0.018), samples.size // 4)
    if fi > 2:
        samples[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)
    if fo > 2:
        samples[-fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)

    # 4. Pausa prosódica controlada al cierre
    pause_samples = max(0, int(sample_rate * max(0, min(600, int(trailing_pause_ms))) / 1000.0))
    if pause_samples > 0:
        samples = np.concatenate([samples, np.zeros(pause_samples, dtype=np.float32)])

    pcm_i16 = np.clip(samples * 32767.0, -32768.0, 32767.0).astype(np.int16)
    return pcm_i16.tobytes()


@dataclass
class WordTiming:
    """Marca temporal exacta de una palabra sincronizada con el audio PCM."""
    word: str
    start_ms: int
    end_ms: int
    char_start: int
    char_end: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


@dataclass
class SyncedSpeechSegment:
    """Segmento hablado con audio PCM, prosodia y mapa palabra-a-milisegundo."""
    display_text: str
    spoken_text: str
    pcm: bytes
    sample_rate: int
    duration_ms: int
    prosody: ExpressiveProsody
    word_timings: List[WordTiming] = field(default_factory=list)
    mime: str = "audio/wav"
    encoded_bytes: Optional[bytes] = None
    char_offset: int = 0  # desplazamiento respecto al texto completo de la respuesta

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "display_text": self.display_text,
            "spoken_text": self.spoken_text,
            "sample_rate": self.sample_rate,
            "duration_ms": self.duration_ms,
            "prosody": self.prosody.style,
            "char_offset": self.char_offset,
            "word_timings": [w.to_dict() for w in self.word_timings],
        }


_VOWEL_GROUPS_RE = re.compile(r"[aeiouáéíóúü]+", re.IGNORECASE)
_WORD_SPAN_RE = re.compile(r"\S+")


def compute_word_timings(
    display_text: str,
    duration_ms: int,
    *,
    start_offset_ms: int = 0,
    trailing_pause_ms: int = 180,
) -> List[WordTiming]:
    """
    Calcula marcas temporales palabra por palabra sincronizadas a la duración real
    del PCM generado, ponderando sílabas en español y pausas de puntuación.
    Conserva los índices exactos `char_start`/`char_end` dentro de `display_text`.
    """
    if not display_text or duration_ms <= 0:
        return []
    matches = list(_WORD_SPAN_RE.finditer(display_text))
    if not matches:
        return []

    # Reservar la pausa prosódica final para que la última palabra termine justo antes del silencio
    active_ms = max(int(duration_ms * 0.55), duration_ms - max(0, min(trailing_pause_ms, duration_ms // 3)))
    lead_ms = min(25, active_ms // 10)
    usable_ms = max(40, active_ms - lead_ms)

    weights: List[float] = []
    for m in matches:
        tok = m.group(0)
        core = re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]", "", tok)
        syllables = max(1, len(_VOWEL_GROUPS_RE.findall(core))) if core else 1
        # Peso acústico = sílabas + longitud consonántica + pausa por puntuación
        w = 0.85 * syllables + 0.18 * max(1, len(core))
        if any(ch.isdigit() for ch in tok):
            w += 1.4  # los números en español toman más sílabas al leerse
        if tok.endswith((",", ";", "—", "–")):
            w += 1.35
        elif tok.endswith((":", ".", "!", "?", "…")):
            w += 2.15
        weights.append(max(0.6, w))

    total_w = sum(weights) or 1.0
    timings: List[WordTiming] = []
    cursor = float(start_offset_ms + lead_ms)
    for m, w in zip(matches, weights):
        span_ms = (w / total_w) * usable_ms
        t_start = int(round(cursor))
        cursor += span_ms
        t_end = max(t_start + 15, int(round(cursor)))
        timings.append(
            WordTiming(
                word=m.group(0),
                start_ms=t_start,
                end_ms=t_end,
                char_start=m.start(),
                char_end=m.end(),
            )
        )
    if timings:
        timings[-1].end_ms = max(timings[-1].start_ms + 20, start_offset_ms + active_ms)
    return timings


def extract_streaming_sentence(buffer: str, is_first: bool = False) -> Tuple[Optional[str], str]:
    """
    Extrae la siguiente oración lista para TTS minimizando el tiempo al primer audio (TTFA).
    Primera oración: umbral agresivo (14 chars) para empezar a sonar casi al instante.
    """
    min_len = 14 if is_first else 34
    if len(buffer) < min_len:
        return None, buffer

    match = _SENTENCE_SPLIT_RE.search(buffer)
    if match and match.start() >= min_len:
        sentence = buffer[: match.start() + 1].strip()
        rest = buffer[match.end() :]
        return sentence, rest

    if len(buffer) >= (64 if is_first else 96):
        comma_idx = buffer.find(", ", 28 if is_first else 48)
        if comma_idx != -1:
            sentence = buffer[: comma_idx + 1].strip()
            rest = buffer[comma_idx + 2 :]
            return sentence, rest

    return None, buffer


def resolve_voice_spec(voice: Optional[str], mode: str = DEFAULT_TTS_MODE) -> Tuple[str, str]:
    """
    Resuelve (engine, voice_id) a partir de un nombre/alias y el modo ('local'|'hybrid'|'edge').
    """
    raw = (voice or "").strip()
    low = raw.lower()
    m = (mode or "local").strip().lower()

    if low in VOICE_ALIASES:
        resolved = VOICE_ALIASES[low]
    elif raw in LOCAL_PIPER_VOICES:
        resolved = raw
    elif re.match(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z0-9]+Neural$", raw):
        resolved = raw
    else:
        resolved = DEFAULT_LOCAL_VOICE if m == "local" else DEFAULT_EDGE_VOICE

    if resolved in LOCAL_PIPER_VOICES:
        return "piper", resolved
    if m == "local":
        # En modo 100% local, mapear voces masculinas Edge a ald-medium y femeninas a claude-high
        if any(k in resolved.lower() for k in ("jorge", "alvaro", "álvaro")):
            return "piper", "es_MX-ald-medium"
        return "piper", "es_MX-claude-high"
    return "edge-tts", resolved


def _rate_to_length_scale(rate: Any) -> float:
    """Convierte velocidad tipo '+8%', '-10%' o 1.15 en length_scale de Piper (<1 = más rápido)."""
    if rate is None or rate == "":
        return 0.94  # ligeramente ágil y natural
    factor = 1.0
    if isinstance(rate, (int, float)):
        factor = float(rate)
    elif isinstance(rate, str):
        s = rate.strip()
        m = re.match(r"^([+-]?\d+(?:\.\d+)?)%$", s)
        if m:
            factor = 1.0 + float(m.group(1)) / 100.0
        else:
            try:
                factor = float(s)
            except ValueError:
                factor = 1.0
    factor = max(0.65, min(1.55, factor))
    return round(1.0 / factor, 3)


def _normalize_edge_rate(rate: Any) -> str:
    if rate is None or rate == "":
        return "+8%"
    if isinstance(rate, str) and re.match(r"^[+-]\d{1,2}%$", rate.strip()):
        return rate.strip()
    try:
        pct = int(round((max(0.65, min(1.55, float(rate))) - 1.0) * 100))
        return f"+{pct}%" if pct >= 0 else f"{pct}%"
    except Exception:
        return "+8%"


def pcm_to_wav_bytes(pcm: bytes, sample_rate: int = PIPER_SAMPLE_RATE, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class SovereignLocalTTS:
    """
    Sintetizador TTS residente de ultra-baja latencia:
      - Piper ONNX residente en memoria (100% offline, ~80-250ms, sin subprocesos).
      - Caché LRU en RAM para frases frecuentes (0ms).
      - Soporte híbrido con `edge-tts` async en memoria y failover inmediato a Piper.
    """

    def __init__(
        self,
        mode: str = DEFAULT_TTS_MODE,
        default_voice: Optional[str] = None,
        onnx_threads: int = 4,
        cache_max_items: int = 64,
    ):
        self.mode = (mode or "local").strip().lower()
        self.default_voice = default_voice or (
            DEFAULT_LOCAL_VOICE if self.mode == "local" else DEFAULT_EDGE_VOICE
        )
        self.onnx_threads = max(1, min(8, int(onnx_threads)))
        self._piper_voices: Dict[str, Any] = {}
        self._piper_lock = threading.Lock()
        self._synth_lock = threading.Lock()
        self._cache: "OrderedDict[Tuple[str, str, str], Tuple[bytes, str, int]]" = OrderedDict()
        self._cache_max = cache_max_items
        self._stats = {"local_count": 0, "edge_count": 0, "cache_hits": 0, "last_ms": 0.0}

    def available_piper_voices(self) -> List[Dict[str, Any]]:
        out = []
        for vid, info in LOCAL_PIPER_VOICES.items():
            p = PIPER_MODELS_DIR / info["file"]
            if p.is_file():
                out.append({**info, "path": str(p), "installed": True})
        return out

    def is_piper_available(self) -> bool:
        return bool(self.available_piper_voices())

    def list_all_voices(self) -> List[Dict[str, Any]]:
        return self.available_piper_voices() + list(EDGE_VOICES)

    def _load_piper_voice(self, voice_id: str):
        with self._piper_lock:
            if voice_id in self._piper_voices:
                return self._piper_voices[voice_id]
            info = LOCAL_PIPER_VOICES.get(voice_id) or LOCAL_PIPER_VOICES[DEFAULT_LOCAL_VOICE]
            model_path = PIPER_MODELS_DIR / info["file"]
            if not model_path.is_file():
                # Buscar cualquier .onnx instalado
                installed = self.available_piper_voices()
                if not installed:
                    raise FileNotFoundError(f"No hay modelos Piper en {PIPER_MODELS_DIR}")
                model_path = Path(installed[0]["path"])
                voice_id = installed[0]["id"]
                if voice_id in self._piper_voices:
                    return self._piper_voices[voice_id]

            if VOICE_LIB.exists() and str(VOICE_LIB) not in sys.path:
                sys.path.insert(0, str(VOICE_LIB))
            import onnxruntime as ort
            from piper.config import PiperConfig
            from piper.voice import PiperVoice

            cfg_path = Path(str(model_path) + ".json")
            with cfg_path.open("r", encoding="utf-8") as fh:
                config_dict = json.load(fh)

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = self.onnx_threads
            opts.inter_op_num_threads = 1
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            opts.log_severity_level = 3

            session = ort.InferenceSession(
                str(model_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            voice_obj = PiperVoice(session=session, config=PiperConfig.from_dict(config_dict))
            self._piper_voices[voice_id] = voice_obj
            logger.info("🔊 Piper ONNX local cargado: %s (%d threads)", voice_id, self.onnx_threads)
            return voice_obj

    def warmup(self, voice: Optional[str] = None) -> float:
        t0 = time.perf_counter()
        eng, vid = resolve_voice_spec(voice or self.default_voice, mode="local")
        if self.is_piper_available():
            self._load_piper_voice(vid)
        return time.perf_counter() - t0

    def synthesize_piper_pcm(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        rate: Any = "+6%",
        style_hint: str = "",
        prosody: Optional[ExpressiveProsody] = None,
    ) -> Tuple[bytes, int]:
        """
        Sintetiza texto limpio a PCM16 mono raw usando Piper ONNX local en memoria,
        aplicando prosodia expresiva dinámica y pulido acústico anti-clic.
        """
        clean = prepare_text_for_speech(text)
        if not clean:
            return b"", PIPER_SAMPLE_RATE

        _, vid = resolve_voice_spec(voice or self.default_voice, mode="local")
        eff_prosody = prosody or analyze_expressive_prosody(text, base_rate=rate, style_hint=style_hint)
        cache_key = (
            "piper_pcm_v2",
            vid,
            f"{eff_prosody.style}:{eff_prosody.length_scale}:{eff_prosody.trailing_pause_ms}:{clean}",
        )
        if len(clean) <= 180 and cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            self._stats["cache_hits"] += 1
            data, _, sr = self._cache[cache_key]
            return data, sr

        from piper.config import SynthesisConfig

        voice_obj = self._load_piper_voice(vid)
        syn_cfg = SynthesisConfig(
            length_scale=eff_prosody.length_scale,
            noise_scale=eff_prosody.noise_scale,
            noise_w_scale=eff_prosody.noise_w_scale,
            normalize_audio=True,
            volume=1.0,
        )
        t0 = time.perf_counter()
        with self._synth_lock:
            chunks = list(voice_obj.synthesize(clean, syn_config=syn_cfg))
        raw_pcm = b"".join(c.audio_int16_bytes for c in chunks)
        sr = chunks[0].sample_rate if chunks else voice_obj.config.sample_rate
        pcm = polish_tts_pcm(raw_pcm, sample_rate=sr, trailing_pause_ms=eff_prosody.trailing_pause_ms) if raw_pcm else b""
        dt_ms = (time.perf_counter() - t0) * 1000.0
        self._stats["local_count"] += 1
        self._stats["last_ms"] = round(dt_ms, 1)

        if pcm and len(clean) <= 180:
            self._cache[cache_key] = (pcm, "audio/pcm", sr)
            if len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)
        return pcm, sr

    def synthesize_synced_segment(
        self,
        display_text: str,
        *,
        voice: Optional[str] = None,
        rate: Any = "+6%",
        mode: Optional[str] = None,
        style_hint: str = "",
        char_offset: int = 0,
    ) -> Optional[SyncedSpeechSegment]:
        """
        Sintetiza un segmento hablado con prosodia expresiva y calcula los timestamps
        exactos palabra por palabra sincronizados a la duración real del audio generado.
        """
        disp = (display_text or "").strip()
        if not disp:
            return None
        spoken = prepare_text_for_speech(disp)
        if not spoken:
            return None

        eff_mode = (mode or self.mode or "local").strip().lower()
        prosody = analyze_expressive_prosody(disp, base_rate=rate, style_hint=style_hint)
        engine, vid = resolve_voice_spec(voice or self.default_voice, mode=eff_mode)

        if engine == "piper" and self.is_piper_available():
            pcm, sr = self.synthesize_piper_pcm(
                disp, voice=vid, rate=rate, style_hint=style_hint, prosody=prosody
            )
            if pcm:
                dur_ms = max(80, int(round(len(pcm) / float(max(1, sr) * 2) * 1000.0)))
                timings = compute_word_timings(
                    disp, dur_ms, trailing_pause_ms=prosody.trailing_pause_ms
                )
                return SyncedSpeechSegment(
                    display_text=disp,
                    spoken_text=spoken,
                    pcm=pcm,
                    sample_rate=sr,
                    duration_ms=dur_ms,
                    prosody=prosody,
                    word_timings=timings,
                    mime="audio/wav",
                    encoded_bytes=pcm_to_wav_bytes(pcm, sample_rate=sr),
                    char_offset=char_offset,
                )

        # Ruta híbrida / edge-tts (con estimación acústica fiel o decodificación WAV exacta)
        audio_bytes, mime, sr = self.synthesize_bytes(
            disp, voice=voice, rate=rate, mode=eff_mode
        )
        if not audio_bytes:
            return None
        pcm = b""
        dur_ms = 0
        if "wav" in mime and audio_bytes[:4] == b"RIFF":
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    sr = wf.getframerate()
                    pcm = wf.readframes(wf.getnframes())
                    dur_ms = max(80, int(round(wf.getnframes() / float(max(1, sr)) * 1000.0)))
            except Exception:
                dur_ms = 0
        if dur_ms <= 0:
            # Estimación precisa para MP3 24kbps-48kbps según ritmo de sílabas (~62 ms/carácter en español)
            words = max(1, len(disp.split()))
            dur_ms = max(320, int(words * 365 * prosody.length_scale))
        timings = compute_word_timings(disp, dur_ms, trailing_pause_ms=prosody.trailing_pause_ms)
        return SyncedSpeechSegment(
            display_text=disp,
            spoken_text=spoken,
            pcm=pcm,
            sample_rate=sr,
            duration_ms=dur_ms,
            prosody=prosody,
            word_timings=timings,
            mime=mime,
            encoded_bytes=audio_bytes,
            char_offset=char_offset,
        )

    async def synthesize_bytes_async(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        rate: Any = "+8%",
        pitch: str = "+0Hz",
        mode: Optional[str] = None,
        edge_timeout_s: float = 2.6,
    ) -> Tuple[Optional[bytes], str, int]:
        """
        Sintetiza texto limpio a bytes reproducibles:
          - Modo 'local' o voz Piper -> WAV PCM16 22050 Hz (100% offline).
          - Modo 'hybrid' / 'edge' con voz Edge -> MP3 async con failover inmediato a Piper.
        Retorna (audio_bytes, mime, sample_rate).
        """
        clean = prepare_text_for_speech(text)
        if not clean:
            return None, "audio/wav", PIPER_SAMPLE_RATE

        eff_mode = (mode or self.mode or "local").strip().lower()
        engine, vid = resolve_voice_spec(voice or self.default_voice, mode=eff_mode)

        if engine == "piper" and self.is_piper_available():
            loop = asyncio.get_running_loop()
            pcm, sr = await loop.run_in_executor(
                None, lambda: self.synthesize_piper_pcm(clean, voice=vid, rate=rate)
            )
            if pcm:
                return pcm_to_wav_bytes(pcm, sample_rate=sr), "audio/wav", sr

        # Intento Edge TTS en memoria (async, sin subprocesos CLI)
        if HAS_EDGE_TTS and edge_tts is not None and engine == "edge-tts":
            rate_str = _normalize_edge_rate(rate)
            cache_key = ("edge_mp3", vid, f"{rate_str}:{pitch}:{clean}")
            if len(clean) <= 180 and cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                self._stats["cache_hits"] += 1
                data, mime, sr = self._cache[cache_key]
                return data, mime, sr
            try:
                t0 = time.perf_counter()

                async def _stream_edge() -> bytes:
                    comm = edge_tts.Communicate(clean, vid, rate=rate_str, pitch=pitch)
                    buf = io.BytesIO()
                    async for chunk in comm.stream():
                        if chunk.get("type") == "audio":
                            buf.write(chunk["data"])
                    return buf.getvalue()

                timeout_val = edge_timeout_s if eff_mode == "hybrid" else 18.0
                data = await asyncio.wait_for(_stream_edge(), timeout=timeout_val)
                if data:
                    self._stats["edge_count"] += 1
                    self._stats["last_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
                    if len(clean) <= 180:
                        self._cache[cache_key] = (data, "audio/mpeg", 24000)
                        if len(self._cache) > self._cache_max:
                            self._cache.popitem(last=False)
                    return data, "audio/mpeg", 24000
            except Exception as exc:
                logger.debug("edge-tts async falló o excedió timeout (%s); failover a Piper local", exc)

        # Failover soberano 100% local a Piper ONNX
        if self.is_piper_available():
            try:
                loop = asyncio.get_running_loop()
                pcm, sr = await loop.run_in_executor(
                    None, lambda: self.synthesize_piper_pcm(clean, voice=voice, rate=rate)
                )
                if pcm:
                    return pcm_to_wav_bytes(pcm, sample_rate=sr), "audio/wav", sr
            except Exception as exc:
                logger.warning("Fallback Piper local falló: %s", exc)

        return None, "audio/wav", PIPER_SAMPLE_RATE

    def synthesize_bytes(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        rate: Any = "+8%",
        pitch: str = "+0Hz",
        mode: Optional[str] = None,
    ) -> Tuple[Optional[bytes], str, int]:
        """Versión síncrona segura desde cualquier hilo."""
        clean = prepare_text_for_speech(text)
        if not clean:
            return None, "audio/wav", PIPER_SAMPLE_RATE

        eff_mode = (mode or self.mode or "local").strip().lower()
        engine, vid = resolve_voice_spec(voice or self.default_voice, mode=eff_mode)
        if engine == "piper" and self.is_piper_available():
            pcm, sr = self.synthesize_piper_pcm(clean, voice=vid, rate=rate)
            if pcm:
                return pcm_to_wav_bytes(pcm, sample_rate=sr), "audio/wav", sr

        try:
            asyncio.get_running_loop()
            box: Dict[str, Any] = {}

            def _run() -> None:
                box["res"] = asyncio.run(
                    self.synthesize_bytes_async(clean, voice=voice, rate=rate, pitch=pitch, mode=eff_mode)
                )

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=35.0)
            return box.get("res", (None, "audio/wav", PIPER_SAMPLE_RATE))
        except RuntimeError:
            return asyncio.run(
                self.synthesize_bytes_async(clean, voice=voice, rate=rate, pitch=pitch, mode=eff_mode)
            )

    def get_status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "default_voice": self.default_voice,
            "piper_available": self.is_piper_available(),
            "piper_loaded_voices": list(self._piper_voices.keys()),
            "edge_tts_available": HAS_EDGE_TTS,
            "voices": self.list_all_voices(),
            "stats": dict(self._stats),
        }
