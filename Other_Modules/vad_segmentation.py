"""core/voice/vad_segmentation.py - DSP acústico, Silero VAD v6, segmentador adaptativo y normalizador de dictado."""
from __future__ import annotations

from core.voice.common import *
from core.voice.common import _CUDA_LOCK, _VRAM_CACHE

# ==============================================================================
# 2. PREPROCESAMIENTO ACÚSTICO DSP PARA STT DE ALTA PRECISIÓN
# ==============================================================================

_HPF_SOS = None
if HAS_SCIPY and scipy_signal is not None:
    try:
        # Filtro pasa-altos Butterworth 2do orden @ 85 Hz para 16 kHz
        _HPF_SOS = scipy_signal.butter(2, 85.0 / (SAMPLE_RATE * 0.5), btype="highpass", output="sos")
    except Exception:
        _HPF_SOS = None


def preprocess_pcm_for_stt(
    pcm_bytes: bytes,
    sample_rate: int = SAMPLE_RATE,
    apply_hpf: bool = True,
    apply_agc: bool = True,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """
    Acondiciona audio PCM16 mono 16 kHz antes de Whisper:
      1. Conversión int16 -> float32 [-1, 1] y remoción de DC offset.
      2. Filtro pasa-altos 85 Hz (suprime ventilador, retumbo y artefactos HFP).
      3. Estimación de ruido y ganancia adaptativa (AGC suave) sobre señal activa
         con limitación suave tanh para no recortar picos.
    """
    if not pcm_bytes:
        return np.zeros(0, dtype=np.float32), {"rms_in": 0.0, "rms_out": 0.0, "peak": 0.0, "duration_s": 0.0, "gain": 1.0}

    usable = len(pcm_bytes) - (len(pcm_bytes) % 2)
    audio = np.frombuffer(pcm_bytes[:usable], dtype=np.int16).astype(np.float32) / 32768.0
    if audio.size == 0:
        return audio, {"rms_in": 0.0, "rms_out": 0.0, "peak": 0.0, "duration_s": 0.0, "gain": 1.0}

    # 1. Quitar offset DC
    audio = audio - float(np.mean(audio))
    rms_in = float(np.sqrt(np.mean(audio * audio)))

    # 2. Pasa-altos Butterworth 85 Hz
    if apply_hpf and audio.size >= 64:
        if _HPF_SOS is not None and sample_rate == SAMPLE_RATE and scipy_signal is not None:
            try:
                audio = scipy_signal.sosfilt(_HPF_SOS, audio).astype(np.float32)
            except Exception:
                pass
        else:
            # Filtro pasa-altos de primer orden ligero en NumPy puro si no hay scipy
            alpha = 0.965
            out = np.empty_like(audio)
            out[0] = audio[0]
            out[1:] = audio[1:] - alpha * audio[:-1]
            audio = out

    # 3. AGC suave basado en energía de tramas activas (top 30% RMS)
    gain = 1.0
    snr_est_db = 0.0
    if apply_agc and audio.size >= 320:
        frame_len = 320  # 20ms @ 16kHz
        n_frames = audio.size // frame_len
        if n_frames >= 3:
            framed = audio[: n_frames * frame_len].reshape(n_frames, frame_len)
            frame_rms = np.sqrt(np.mean(framed * framed, axis=1))
            noise_est = float(np.percentile(frame_rms, 15))
            speech_est = float(np.percentile(frame_rms, 85))
            if noise_est > 1e-6:
                snr_est_db = float(20.0 * np.log10(max(speech_est, 1e-6) / noise_est))
            # Solo amplificar si hay señal vocal real por encima del piso de ruido
            if speech_est > 0.0045:
                target_rms = 0.095
                desired_gain = target_rms / max(speech_est, 1e-4)
                # Limitar ganancia a [0.65, 6.0] (+15.5 dB max) para no disparar ruido
                gain = float(np.clip(desired_gain, 0.65, 6.0))
                if abs(gain - 1.0) > 0.08:
                    audio = audio * gain
                    # Limitador suave para evitar clipping duro en picos
                    peak_after = float(np.max(np.abs(audio)))
                    if peak_after > 0.92:
                        audio = (0.95 * np.tanh(audio / 0.95)).astype(np.float32)

    rms_out = float(np.sqrt(np.mean(audio * audio)))
    peak = float(np.max(np.abs(audio)))
    metrics = {
        "rms_in": round(rms_in, 5),
        "rms_out": round(rms_out, 5),
        "peak": round(peak, 4),
        "duration_s": round(audio.size / float(sample_rate), 3),
        "gain": round(gain, 2),
        "snr_est_db": round(snr_est_db, 1),
    }
    return audio.astype(np.float32, copy=False), metrics


# ==============================================================================
# 3. SILERO VAD v6 NEURAL STREAMING + SEGMENTADOR ADAPTATIVO CON BARGE-IN
# ==============================================================================

class SileroVadStream:
    """
    Detector de actividad vocal neural Silero VAD v6 (ONNX Runtime CPU, 1 hilo).
    Consume tramas PCM16 de cualquier tamaño (30 ms, 20 ms, 32 ms) y actualiza
    el estado LSTM (h, c) en bloques exactos de 512 muestras + 64 de contexto.
    """

    WINDOW_SAMPLES = 512
    CONTEXT_SAMPLES = 64

    def __init__(self, onnx_path: Optional[Path] = None):
        self._session = None
        self._onnx_path = onnx_path or self._find_model_path()
        self._ctx = np.zeros((1, self.CONTEXT_SAMPLES), dtype=np.float32)
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self._last_prob = 0.0
        self._lock = threading.Lock()
        self._init_session()

    @staticmethod
    def _find_model_path() -> Optional[Path]:
        candidates = [
            VOICE_LIB / "faster_whisper" / "assets" / "silero_vad_v6.onnx",
            VOICE_RUNTIME / "models" / "silero_vad_v6.onnx",
        ]
        for c in candidates:
            if c.is_file():
                return c
        try:
            import faster_whisper
            p = Path(faster_whisper.__file__).resolve().parent / "assets" / "silero_vad_v6.onnx"
            if p.is_file():
                return p
        except Exception:
            pass
        return None

    def _init_session(self) -> None:
        if not self._onnx_path or not self._onnx_path.is_file():
            return
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.log_severity_level = 3
            self._session = ort.InferenceSession(
                str(self._onnx_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:
            logger.debug("Silero VAD v6 no pudo cargarse (%s); usando respaldo", exc)
            self._session = None

    @property
    def available(self) -> bool:
        return self._session is not None

    def reset(self) -> None:
        with self._lock:
            self._ctx.fill(0.0)
            self._h.fill(0.0)
            self._c.fill(0.0)
            self._pending = np.zeros(0, dtype=np.float32)
            self._last_prob = 0.0

    def speech_probability(self, pcm_bytes: bytes) -> float:
        """Devuelve probabilidad vocal [0.0, 1.0] para la trama PCM16 mono 16kHz."""
        if self._session is None or not pcm_bytes:
            return 0.0
        usable = len(pcm_bytes) - (len(pcm_bytes) % 2)
        if usable <= 0:
            return self._last_prob
        samples = np.frombuffer(pcm_bytes[:usable], dtype=np.int16).astype(np.float32) / 32768.0
        with self._lock:
            buf = np.concatenate([self._pending, samples]) if self._pending.size else samples
            max_prob = 0.0
            ran = False
            offset = 0
            while (buf.size - offset) >= self.WINDOW_SAMPLES:
                chunk = buf[offset : offset + self.WINDOW_SAMPLES].reshape(1, self.WINDOW_SAMPLES)
                inp = np.concatenate([self._ctx, chunk], axis=1)
                probs, hn, cn = self._session.run(
                    None,
                    {"input": inp, "h": self._h, "c": self._c},
                )
                self._h = hn
                self._c = cn
                self._ctx = chunk[:, -self.CONTEXT_SAMPLES :]
                p = float(probs.reshape(-1)[0])
                if p > max_prob:
                    max_prob = p
                ran = True
                offset += self.WINDOW_SAMPLES
            self._pending = buf[offset:]
            if ran:
                self._last_prob = max_prob
            return self._last_prob


@dataclass
class SegmenterConfig:
    sample_rate: int = SAMPLE_RATE
    frame_ms: int = 30
    vad_aggressiveness: int = 2
    silence_hold_ms: int = 740
    long_speech_hold_ms: int = 1080
    dictation_hold_ms: int = 1350
    min_speech_ms: int = 240
    max_utterance_ms: int = 30000
    pre_roll_ms: int = 360
    barge_in: bool = True
    barge_in_rms: float = 0.068
    barge_in_frames: int = 8
    silero_start_prob: float = 0.46
    silero_cont_prob: float = 0.28
    silero_barge_prob: float = 0.72
    use_silero: bool = True
    dictation_mode: bool = False


class AdaptiveSpeechSegmenter:
    """
    Segmentador híbrido neural (Silero VAD v6 + WebRTC VAD + RMS adaptativo) con:
      - Pre-roll 360 ms para no truncar consonantes iniciales.
      - Paciencia adaptativa: cierre ágil (~740ms) en frases cortas y paciencia
        extendida (~1.08s-1.35s) en dictados largos para no cortar pausas naturales.
      - Barge-In anti-eco calibrado para bocinas y Lentes EVOIR Bluetooth.
    """

    def __init__(self, cfg: Optional[SegmenterConfig] = None, silero: Optional[SileroVadStream] = None):
        self.cfg = cfg or SegmenterConfig()
        self.silero = silero if silero is not None else (SileroVadStream() if self.cfg.use_silero else None)
        if self.silero is not None and not self.silero.available:
            self.silero = None
        self.vad = webrtcvad.Vad(self.cfg.vad_aggressiveness) if HAS_WEBRTCVAD else None
        self.noise_floor = 0.008
        self.in_speech = False
        self.speech_frames: List[bytes] = []
        self.voiced_frame_count = 0
        self.pre_roll: Deque[bytes] = deque(maxlen=max(1, self.cfg.pre_roll_ms // self.cfg.frame_ms))
        self.silence_frames = 0
        self.barge_streak = 0
        self._update_frame_budgets()

    def _update_frame_budgets(self) -> None:
        fm = max(10, self.cfg.frame_ms)
        self._base_hold_frames = max(1, self.cfg.silence_hold_ms // fm)
        self._long_hold_frames = max(self._base_hold_frames, self.cfg.long_speech_hold_ms // fm)
        self._dictation_hold_frames = max(self._long_hold_frames, self.cfg.dictation_hold_ms // fm)
        self._min_frames = max(1, self.cfg.min_speech_ms // fm)
        self._max_frames = max(10, self.cfg.max_utterance_ms // fm)

    def set_silence_hold_ms(self, ms: int) -> None:
        self.cfg.silence_hold_ms = max(350, min(3000, int(ms)))
        self.cfg.long_speech_hold_ms = max(self.cfg.silence_hold_ms, int(self.cfg.silence_hold_ms * 1.42))
        self._update_frame_budgets()

    def set_dictation_mode(self, enabled: bool) -> None:
        self.cfg.dictation_mode = bool(enabled)

    def reset_utterance(self) -> None:
        self.in_speech = False
        self.speech_frames.clear()
        self.voiced_frame_count = 0
        self.silence_frames = 0
        self.barge_streak = 0
        if self.silero is not None:
            self.silero.reset()

    def get_current_speech_pcm(self, max_seconds: float = 12.0) -> Tuple[bytes, float]:
        """Devuelve una instantánea segura del audio hablado en curso para vista previa en vivo."""
        if not self.in_speech or not self.speech_frames:
            return b"", 0.0
        frames = list(self.speech_frames)
        max_frames = max(1, int((max_seconds * 1000.0) / max(10, self.cfg.frame_ms)))
        if len(frames) > max_frames:
            frames = frames[-max_frames:]
        pcm = b"".join(frames)
        dur_s = len(pcm) / float(max(1, self.cfg.sample_rate) * 2)
        return pcm, dur_s

    @staticmethod
    def frame_rms(frame: bytes) -> float:
        if not frame or len(frame) < 2:
            return 0.0
        usable = len(frame) - (len(frame) % 2)
        pcm = np.frombuffer(frame[:usable], dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(pcm * pcm)))

    def _detect_voice(self, frame: bytes, rms: float, threshold: float, continuing: bool) -> Tuple[bool, float]:
        prob = 0.0
        if self.silero is not None:
            prob = self.silero.speech_probability(frame)
            p_thresh = self.cfg.silero_cont_prob if continuing else self.cfg.silero_start_prob
            # Exige probabilidad neural Silero + un piso energético mínimo para ignorar ruido eléctrico
            min_e = threshold * (0.45 if continuing else 0.62)
            return (prob >= p_thresh and rms >= max(0.0055, min_e)), prob

        energy_ok = rms > threshold
        if self.vad is None:
            return energy_ok, (1.0 if energy_ok else 0.0)
        try:
            vad_ok = self.vad.is_speech(frame, self.cfg.sample_rate)
        except Exception:
            vad_ok = energy_ok
        ok = vad_ok and rms > (threshold * (0.62 if continuing else 0.72))
        return ok, (0.85 if ok else 0.05)

    def _effective_hold_frames(self) -> int:
        if self.cfg.dictation_mode:
            return self._dictation_hold_frames
        # Tras >2.4s de locución continua, ampliar paciencia para pausas reflexivas
        speech_ms = len(self.speech_frames) * self.cfg.frame_ms
        if speech_ms >= 2400:
            return self._long_hold_frames
        return self._base_hold_frames

    def process_frame(self, frame: bytes, ai_speaking: bool = False) -> Dict[str, Any]:
        rms = self.frame_rms(frame)
        threshold = max(0.010, self.noise_floor * 2.35)

        if ai_speaking:
            if self.cfg.barge_in:
                barge_thresh = max(self.cfg.barge_in_rms, self.noise_floor * 4.6)
                prob = 0.0
                if self.silero is not None:
                    prob = self.silero.speech_probability(frame)
                    voice_hit = (prob >= self.cfg.silero_barge_prob) and (rms >= barge_thresh)
                else:
                    vad_hit = True
                    if self.vad is not None:
                        try:
                            vad_hit = self.vad.is_speech(frame, self.cfg.sample_rate)
                        except Exception:
                            vad_hit = True
                    voice_hit = vad_hit and (rms >= barge_thresh)

                if voice_hit:
                    self.barge_streak += 1
                    self.pre_roll.append(frame)
                    if self.barge_streak >= self.cfg.barge_in_frames:
                        self.in_speech = True
                        self.speech_frames = list(self.pre_roll)
                        self.voiced_frame_count = self.barge_streak
                        self.silence_frames = 0
                        self.barge_streak = 0
                        return {
                            "utterance": None,
                            "barge_in": True,
                            "rms": rms,
                            "vad_prob": prob,
                            "in_speech": True,
                        }
                else:
                    self.barge_streak = max(0, self.barge_streak - 1)
                    self.pre_roll.append(frame)
            else:
                self.pre_roll.append(frame)
            return {
                "utterance": None,
                "barge_in": False,
                "rms": rms,
                "vad_prob": 0.0,
                "in_speech": False,
            }

        self.barge_streak = 0
        is_voice, prob = self._detect_voice(frame, rms, threshold, continuing=self.in_speech)

        if not self.in_speech:
            self.noise_floor = 0.98 * self.noise_floor + 0.02 * min(rms, 0.032)
            self.pre_roll.append(frame)
            if is_voice:
                self.in_speech = True
                self.speech_frames = list(self.pre_roll)
                self.voiced_frame_count = 1
                self.silence_frames = 0
            return {
                "utterance": None,
                "barge_in": False,
                "rms": rms,
                "vad_prob": prob,
                "in_speech": self.in_speech,
            }

        self.speech_frames.append(frame)
        if is_voice:
            self.voiced_frame_count += 1
            self.silence_frames = 0
        else:
            self.silence_frames += 1

        hold_limit = self._effective_hold_frames()
        if self.silence_frames >= hold_limit or len(self.speech_frames) >= self._max_frames:
            frames = list(self.speech_frames)
            voiced = self.voiced_frame_count
            self.reset_utterance()
            # Descartar micro-ruidos sin suficientes tramas vocales reales
            min_voiced = max(2, self._min_frames // 2)
            if len(frames) >= self._min_frames and voiced >= min_voiced:
                return {
                    "utterance": b"".join(frames),
                    "barge_in": False,
                    "rms": rms,
                    "vad_prob": prob,
                    "in_speech": False,
                }
        return {
            "utterance": None,
            "barge_in": False,
            "rms": rms,
            "vad_prob": prob,
            "in_speech": self.in_speech,
        }


# ==============================================================================
# 4. NORMALIZACIÓN DE DICTADO Y FILTRO ANTI-ALUCINACIONES
# ==============================================================================

def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_key(text: str) -> str:
    s = strip_accents(text).lower()
    s = re.sub(r"[^a-z0-9ñ]+", " ", s)
    return " ".join(s.split())


def is_whisper_hallucination(text: str) -> bool:
    """Detecta alucinaciones clásicas de Whisper y bucles repetitivos degenerados."""
    raw = (text or "").strip()
    if not raw:
        return True
    norm = re.sub(r"\s+", " ", raw.lower()).strip()
    norm_clean = re.sub(r"^[.,!?;:¡¿\-–—\s\"'()]+|[.,!?;:¡¿\-–—\s\"'()]+$", "", norm)
    if not norm_clean or len(norm_clean) < 2:
        return True
    if norm in EXTENDED_WHISPER_HALLUCINATIONS or norm_clean in EXTENDED_WHISPER_HALLUCINATIONS:
        return True
    if strip_accents(norm_clean) in EXTENDED_WHISPER_HALLUCINATIONS:
        return True

    # Detección de bucles repetitivos (ej. "gracias gracias gracias gracias")
    words = re.findall(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ0-9]+", norm_clean)
    if len(words) >= 5:
        unique_ratio = len(set(words)) / float(len(words))
        if unique_ratio <= 0.25:
            return True
    # Repetición exacta de la misma palabra 4+ veces seguidas
    if re.search(r"\b(\w{2,})(?:\s+\1){3,}\b", norm_clean):
        return True
    return False


class DictationNormalizer:
    """
    Normaliza transcripciones de dictado por voz en español mexicano/técnico:
      - Correcciones fonéticas conscientes del contexto (sin tocar 'buenas tardes').
      - Limpieza de muletillas vacilantes y duplicaciones por tartamudeo.
      - Comandos hablados de puntuación/formato en modo dictado.
      - Detección de enunciados incompletos para coalescencia fluida.
    """

    # Correcciones seguras aplicables siempre (términos inequívocos mal transcritos)
    _DOMAIN_SUBS: Tuple[Tuple[re.Pattern[str], str], ...] = (
        # Vocativos y usos de "TARDIS" mal transcritos como "tardes" / "tardiz" / "tar dis"
        (re.compile(r"(?i)\b(?:hola|oye|hey|ey|oiga|escucha)\s+tardes\b"), lambda m: m.group(0).split()[0] + " TARDIS"),  # type: ignore[arg-type]
        (re.compile(r"(?i)^tardes(?=\s*[,:?¿!¡]|\s+(?:est[aá]s|dime|explica|expl[ií]came|analiza|busca|investiga|programa|ay[uú]dame|abre|cierra|pausa|despierta|silencio|cu[eé]ntame|resume|haz|crea|ejecuta|activa|desactiva))"), "TARDIS"),
        (re.compile(r"(?i)\b(?:tardiz|tard[ií]s|tar\s+dis)\b"), "TARDIS"),
        # Ecosistema GODWORKS / FTL / KAIJU / GIA / Linux / Hardware
        (re.compile(r"(?i)\b(?:efe\s+te\s+ele|f\s+t\s+l|fetel|efetel)\b"), "FTL"),
        (re.compile(r"(?i)\b(?:kaiyu|cay[uú]|caillou|kayu|kaichu|kai\s+ju)\b"), "KAIJU"),
        (re.compile(r"(?i)\b(?:o\s+llama|holama|olama|o-llama)\b"), "Ollama"),
        (re.compile(r"(?i)\b(?:paip\s*guayer|pipe\s+wire|paip\s+wire|paipewire)\b"), "PipeWire"),
        (re.compile(r"(?i)\b(?:g[uü]isper|wisper|guisper|whis\s+per)\b"), "Whisper"),
        (re.compile(r"(?i)\b(?:paiper\s+t\s*t\s*s|piper\s+t\s*t\s*s)\b"), "Piper TTS"),
        (re.compile(r"(?i)\b(?:hiperland|hyper\s+land|haiperland)\b"), "Hyprland"),
        (re.compile(r"(?i)\b(?:antigraviti|anti\s+gravity|antigravity\s+cli)\b"), "Antigravity"),
        (re.compile(r"(?i)\b(?:god\s+works|godworx|god\s+worx)\b"), "GODWORKS"),
        (re.compile(r"(?i)\b(?:ge\s+i\s+a|g\s+i\s+a)\b"), "GIA"),
        (re.compile(r"(?i)\b(?:c\s+trescientos\s+diez|ce\s+310|c\s+310)\b"), "C310"),
        (re.compile(r"(?i)\b(?:r\s*t\s*x\s+tres\s+mil\s+cincuenta|r\s+t\s+x\s+3050)\b"), "RTX 3050"),
        (re.compile(r"(?i)\b(?:lentes\s+(?:e\s*voir|ebor|evo\s*ir|evoyr))\b"), "lentes EVOIR"),
        (re.compile(r"(?i)\b(?:system\s+d|sisten\s+d)\b"), "systemd"),
        (re.compile(r"(?i)\b(?:ge\s+pe\s+u|g\s+p\s+u)\b"), "GPU"),
        (re.compile(r"(?i)\b(?:ce\s+pe\s+u|c\s+p\s+u)\b"), "CPU"),
        (re.compile(r"(?i)\b(?:u\s+ve\s+ram|v\s+ram|uve\s+ram)\b"), "VRAM"),
        (re.compile(r"(?i)\b(?:te\s+te\s+ese|t\s+t\s+s)\b"), "TTS"),
        (re.compile(r"(?i)\b(?:ese\s+te\s+te|s\s+t\s+t)\b"), "STT"),
        (re.compile(r"(?i)\b(?:ve\s+a\s+de|v\s+a\s+d)\b"), "VAD"),
    )

    # Muletillas iniciales comunes al comenzar a hablar
    _LEADING_FILLERS = re.compile(
        r"^(?:(?:eh+|emm+|mmm+|amm+|ahh+|umm+|este+|bueno\s+este)\s*[,….\s]+)+",
        re.IGNORECASE,
    )
    # Palabras cortas repetidas accidentalmente por vacilación ("quiero quiero" -> "quiero")
    _STUTTER_RE = re.compile(
        r"(?i)\b(el|la|los|las|un|una|de|que|en|y|o|pero|para|por|con|a|me|te|se|lo|mi|tu|es|quiero|puedes|como|cómo)\s+\1\b"
    )

    # Comandos de puntuación hablados (aplicados en modo dictado)
    _DICTATION_PUNCT: Tuple[Tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"(?i)\s*\b(?:punto\s+y\s+aparte|nueva\s+l[ií]nea|salto\s+de\s+l[ií]nea)\b\s*"), ".\n"),
        (re.compile(r"(?i)\s*\b(?:punto\s+y\s+seguido|punto\s+final)\b\s*"), ". "),
        (re.compile(r"(?i)\s*\b(?:dos\s+puntos)\b\s*"), ": "),
        (re.compile(r"(?i)\s*\b(?:punto\s+y\s+coma)\b\s*"), "; "),
        (re.compile(r"(?i)\s*\b(?:abre\s+par[eé]ntesis|abrir\s+par[eé]ntesis)\b\s*"), " ("),
        (re.compile(r"(?i)\s*\b(?:cierra\s+par[eé]ntesis|cerrar\s+par[eé]ntesis)\b\s*"), ") "),
        (re.compile(r"(?i)\s*\b(?:signo\s+de\s+interrogaci[oó]n)\b\s*"), "? "),
        (re.compile(r"(?i)\s*\b(?:signo\s+de\s+exclamaci[oó]n)\b\s*"), "! "),
        (re.compile(r"(?i)\s*,\s*\bcoma\b\s*|\s+\bcoma\b(?=\s|$)"), ", "),
    )

    # Conectores abiertos que indican que el usuario probablemente va a continuar la frase
    _TRAILING_CONNECTORS = frozenset({
        "y", "e", "o", "u", "pero", "sino", "porque", "aunque", "que",
        "para", "por", "con", "sin", "sobre", "entre", "hacia", "desde",
        "de", "del", "al", "el", "la", "los", "las", "un", "una", "unos", "unas",
        "como", "cuando", "donde", "si", "entonces", "ademas", "tambien",
        "mientras", "cuyo", "cuya", "mi", "tu", "su",
    })

    _ALONE_STARTERS = frozenset({
        "oye", "mira", "espera", "escucha", "este", "bueno", "entonces", "pues",
    })

    def normalize(self, text: str, dictation_mode: bool = False) -> Tuple[str, List[str]]:
        """Aplica corrección de dictado y devuelve (texto_normalizado, correcciones_aplicadas)."""
        raw = re.sub(r"\s+", " ", (text or "").strip())
        if not raw:
            return "", []

        corrections: List[str] = []
        out = raw

        # 1. Limpiar muletillas al inicio
        cleaned_fillers = self._LEADING_FILLERS.sub("", out).strip()
        if cleaned_fillers and cleaned_fillers != out:
            corrections.append("fillers_trimmed")
            out = cleaned_fillers

        # 2. Correcciones fonéticas de dominio TARDIS/técnico
        for pattern, repl in self._DOMAIN_SUBS:
            new_out = pattern.sub(repl, out)
            if new_out != out:
                corrections.append(f"domain:{repl if isinstance(repl, str) else 'vocative_TARDIS'}")
                out = new_out

        # 3. Quitar duplicaciones por tartamudeo de dictado
        dedup = self._STUTTER_RE.sub(r"\1", out)
        if dedup != out:
            corrections.append("stutter_collapsed")
            out = dedup

        # 4. Puntuación dictada explícita (solo en modo dictado o frases con comandos claros)
        if dictation_mode:
            for pattern, repl in self._DICTATION_PUNCT:
                new_out = pattern.sub(repl, out)
                if new_out != out:
                    corrections.append("dictation_punct")
                    out = new_out

        # 5. Limpieza tipográfica y capitalización
        out = re.sub(r"[ \t]+([.,;:!?])", r"\1", out)
        out = re.sub(r"\.{2,}", ".", out)
        out = re.sub(r"[ \t]{2,}", " ", out).strip()
        if out and out[0].islower():
            out = out[0].upper() + out[1:]

        return out, corrections

    def is_incomplete_utterance(self, text: str) -> bool:
        """
        Determina si el texto dictado parece una frase a medio decir (para esperar
        brevemente la continuación y fusionarla en vez de cortar la conversación).
        """
        s = (text or "").strip()
        if not s:
            return False
        # Si cierra con signo de interrogación o exclamación, es un turno completo
        if s.endswith(("?", "!")):
            return False
        tokens = normalize_key(s).split()
        if not tokens:
            return False
        # Un saludo o comando corto válido NO es incompleto
        if len(tokens) == 1 and tokens[0] in ("hola", "tardis", "gracias", "ok", "si", "no", "para", "pausa", "silencio", "repite", "salir"):
            return False
        if len(tokens) == 1 and tokens[0] in self._ALONE_STARTERS:
            return True
        if len(tokens) <= 2 and tokens[0] in ("oye", "hola", "hey") and tokens[-1] == "tardis":
            # "Oye TARDIS" -> puede continuar inmediatamente con la pregunta, salvo pausa
            return True
        if tokens[-1] in self._TRAILING_CONNECTORS and len(tokens) >= 2:
            return True
        return False


class UtteranceCoalescer:
    """
    Fusiona fragmentos consecutivos de dictado entrecortado dentro de una ventana corta
    (ej. 'Oye TARDIS, explícame sobre...' + [pausa 1s] + '...los agujeros negros').
    """

    def __init__(self, normalizer: Optional[DictationNormalizer] = None, max_wait_s: float = 2.0):
        self.normalizer = normalizer or DictationNormalizer()
        self.max_wait_s = max_wait_s
        self._buffer: List[str] = []
        self._last_ts: float = 0.0
        self._lock = threading.Lock()

    def push(self, fragment: str) -> Tuple[Optional[str], bool]:
        """
        Agrega un fragmento transcrito.
        Retorna (texto_listo_o_None, esperando_continuacion).
        """
        frag = (fragment or "").strip()
        if not frag:
            return None, False
        now = time.monotonic()
        with self._lock:
            if self._buffer and (now - self._last_ts) > (self.max_wait_s + 1.5):
                # Expiró el fragmento viejo
                self._buffer.clear()
            self._buffer.append(frag)
            self._last_ts = now
            merged = " ".join(self._buffer).strip()
            # No retener más de 2 fragmentos acumulados o enunciados ya largos
            if len(self._buffer) < 2 and len(merged) < 110 and self.normalizer.is_incomplete_utterance(merged):
                return None, True
            self._buffer.clear()
            return merged, False

    def flush_if_expired(self) -> Optional[str]:
        now = time.monotonic()
        with self._lock:
            if not self._buffer:
                return None
            if (now - self._last_ts) >= self.max_wait_s:
                merged = " ".join(self._buffer).strip()
                self._buffer.clear()
                return merged
            return None

    def flush_now(self) -> Optional[str]:
        with self._lock:
            if not self._buffer:
                return None
            merged = " ".join(self._buffer).strip()
            self._buffer.clear()
            return merged
