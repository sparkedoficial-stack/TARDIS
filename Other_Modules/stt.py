"""core/voice/stt.py - STT Soberano Local (faster-whisper CUDA int8 / CPU fallback + DSP + anti-alucinación)."""
from __future__ import annotations

from core.voice.common import *
from core.voice.vad_segmentation import (
    preprocess_pcm_for_stt,
    is_whisper_hallucination,
    DictationNormalizer,
    strip_accents,
    normalize_key,
)

# ==============================================================================
# 6. STT SOBERANO LOCAL (CUDA int8 AUTOMÁTICO + CPU FALLBACK + DSP + PROMPT)
# ==============================================================================

@dataclass
class TranscriptionResult:
    text: str
    raw_text: str
    elapsed_s: float
    device: str
    model: str
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    audio_metrics: Dict[str, float] = field(default_factory=dict)
    corrections: List[str] = field(default_factory=list)


class SovereignLocalSTT:
    """
    Motor STT singleton de alta precisión con faster-whisper:
      - Selección inteligente de dispositivo (`cuda` int8 si hay >=480 MiB VRAM libre
        para `small` o >=280 MiB para `base`; failover limpio a `cpu` int8).
      - Preprocesamiento DSP (pasa-altos 85 Hz + AGC suave).
      - Prompt de dominio dinámico + hotwords + beam_size=2.
      - Normalización de dictado y filtro anti-alucinación por confianza.
    """

    def __init__(
        self,
        model_size: str = DEFAULT_STT_MODEL,
        device: str = DEFAULT_STT_DEVICE,
        cpu_threads: int = int(os.environ.get("TARDIS_VOICE_WHISPER_THREADS", "6")),
    ):
        self.requested_model = model_size or "auto"
        self.requested_device = device or "auto"
        self.cpu_threads = max(2, int(cpu_threads))
        self.model_size: str = "base"
        self.active_device: str = "cpu"
        self.compute_type: str = "int8"
        self._model = None
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._normalizer = DictationNormalizer()
        self._last_error: Optional[str] = None
        self._stats = {"count": 0, "total_ms": 0.0, "last_ms": 0.0}

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _choose_backend(self) -> Tuple[str, str, str]:
        """Decide (model_size, device, compute_type) óptimo según hardware y VRAM libre."""
        req_m = self.requested_model.strip().lower()
        req_d = self.requested_device.strip().lower()

        can_cuda = False
        free_vram = 0
        if req_d in ("auto", "cuda", "gpu"):
            preload_cuda_libraries()
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    _, free_vram = query_gpu_vram_mb(cache_ttl=1.0)
                    # Margen conservador en RTX 3050 4 GB
                    can_cuda = free_vram >= 320 or req_d == "cuda"
            except Exception:
                can_cuda = False

        if req_d == "cpu":
            can_cuda = False

        if can_cuda:
            if req_m == "auto":
                # small usa ~288 MiB VRAM y da mucha mayor precisión en español dictado
                chosen_model = "small" if free_vram >= 520 else "base"
            else:
                chosen_model = req_m
            return chosen_model, "cuda", "int8"

        # CPU fallback: si CPU está en powersave (<1.2 GHz), priorizar base para fluidez;
        # si CPU tiene buen reloj y el usuario pidió small, usar small.
        if req_m == "auto":
            freq = query_cpu_freq_mhz()
            chosen_model = "small" if (freq == 0.0 or freq >= 1800.0) else "base"
        else:
            chosen_model = req_m
        return chosen_model, "cpu", "int8"

    def _load(self):
        with self._load_lock:
            if self._model is not None:
                return self._model
            if VOICE_LIB.exists() and str(VOICE_LIB) not in sys.path:
                sys.path.insert(0, str(VOICE_LIB))
            from faster_whisper import WhisperModel

            MODEL_CACHE.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

            model_name, dev, ctype = self._choose_backend()
            try:
                self._model = WhisperModel(
                    model_name,
                    device=dev,
                    compute_type=ctype,
                    cpu_threads=self.cpu_threads,
                    download_root=str(MODEL_CACHE),
                )
                self.model_size = model_name
                self.active_device = dev
                self.compute_type = ctype
                self._last_error = None
                logger.info(
                    "⚡ STT Whisper cargado: model=%s device=%s compute=%s",
                    self.model_size, self.active_device, self.compute_type,
                )
                return self._model
            except Exception as exc:
                logger.warning("Fallo cargando Whisper (%s/%s): %s; usando CPU base int8", model_name, dev, exc)
                self._last_error = str(exc)
                fallback_model = "base"
                self._model = WhisperModel(
                    fallback_model,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=self.cpu_threads,
                    download_root=str(MODEL_CACHE),
                )
                self.model_size = fallback_model
                self.active_device = "cpu"
                self.compute_type = "int8"
                return self._model

    def warmup(self) -> float:
        t0 = time.perf_counter()
        self._load()
        return time.perf_counter() - t0

    def decode_to_pcm16k(self, audio_bytes: bytes, suffix: str = ".wav") -> bytes:
        """Decodifica cualquier formato de audio a PCM 16-bit mono 16 kHz (ruta zero-spawn para WAV 16k)."""
        if audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    if (
                        wf.getnchannels() == 1
                        and wf.getsampwidth() == 2
                        and wf.getframerate() == SAMPLE_RATE
                    ):
                        return wf.readframes(wf.getnframes())
            except Exception:
                pass

        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg no disponible para decodificar audio")

        shm_dir = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())
        tmp_path = shm_dir / f"tardis_stt_{os.getpid()}_{time.time_ns()}{suffix or '.wav'}"
        try:
            tmp_path.write_bytes(audio_bytes)
            proc = subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-loglevel", "error",
                    "-i", str(tmp_path),
                    "-ar", str(SAMPLE_RATE),
                    "-ac", "1",
                    "-f", "s16le",
                    "-",
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=25,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg falló: {proc.stderr.decode(errors='ignore')[:200]}")
            return proc.stdout
        finally:
            tmp_path.unlink(missing_ok=True)

    def transcribe_pcm_detailed(
        self,
        pcm_bytes: bytes,
        *,
        language: str = DEFAULT_LANGUAGE,
        min_duration_s: float = 0.20,
        context_hint: str = "",
        dictation_mode: bool = False,
        beam_size: Optional[int] = None,
    ) -> TranscriptionResult:
        if not pcm_bytes:
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size)

        audio_f32, metrics = preprocess_pcm_for_stt(pcm_bytes, sample_rate=SAMPLE_RATE)
        if audio_f32.size < int(SAMPLE_RATE * min_duration_s):
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size, audio_metrics=metrics)

        if metrics["rms_out"] < 0.0022:
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size, audio_metrics=metrics)

        model = self._load()
        lang_arg = None if (not language or language.lower() == "auto") else language.split("-")[0].lower()

        # En CUDA podemos usar beam_size=2 (o 3 en dictado) con latencia mínima;
        # en CPU int8, beam_size=2 para frases cortas/medias y 1 si hay estrangulamiento.
        if beam_size is None:
            if self.active_device == "cuda":
                eff_beam = 3 if dictation_mode else 2
            else:
                freq = query_cpu_freq_mhz()
                eff_beam = 2 if (freq == 0.0 or freq >= 1600.0) else 1
        else:
            eff_beam = max(1, int(beam_size))

        prompt = SOVEREIGN_DOMAIN_PROMPT
        if context_hint:
            prompt = f"{SOVEREIGN_DOMAIN_PROMPT} {context_hint.strip()}"[:440]

        t0 = time.perf_counter()
        with self._infer_lock:
            kwargs: Dict[str, Any] = {
                "language": lang_arg,
                "beam_size": eff_beam,
                "best_of": eff_beam,
                "temperature": [0.0, 0.2],
                "vad_filter": True,
                "vad_parameters": {
                    "threshold": 0.38,
                    "min_silence_duration_ms": 280,
                    "speech_pad_ms": 180,
                },
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.62,
                "compression_ratio_threshold": 2.25,
                "log_prob_threshold": -1.15,
                "initial_prompt": prompt,
                "hotwords": SOVEREIGN_HOTWORDS,
            }
            try:
                segments_iter, _info = model.transcribe(audio_f32, **kwargs)
                segments = list(segments_iter)
            except TypeError:
                # Compatibilidad con versiones antiguas sin `hotwords`
                kwargs.pop("hotwords", None)
                segments_iter, _info = model.transcribe(audio_f32, **kwargs)
                segments = list(segments_iter)

        elapsed = time.perf_counter() - t0
        kept_texts: List[str] = []
        logprobs: List[float] = []
        no_speech_probs: List[float] = []
        for seg in segments:
            seg_txt = (seg.text or "").strip()
            if not seg_txt:
                continue
            nsp = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
            alp = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
            # Descartar segmentos que el propio modelo considera ruido/no-habla con baja confianza
            if nsp > 0.78 and alp < -1.0:
                continue
            if is_whisper_hallucination(seg_txt):
                continue
            kept_texts.append(seg_txt)
            logprobs.append(alp)
            no_speech_probs.append(nsp)

        raw_text = " ".join(kept_texts).strip()
        avg_lp = float(np.mean(logprobs)) if logprobs else 0.0
        avg_nsp = float(np.mean(no_speech_probs)) if no_speech_probs else 0.0

        if not raw_text or is_whisper_hallucination(raw_text):
            return TranscriptionResult(
                "", raw_text, elapsed, self.active_device, self.model_size,
                avg_logprob=avg_lp, no_speech_prob=avg_nsp, audio_metrics=metrics,
            )

        norm_text, corrections = self._normalizer.normalize(raw_text, dictation_mode=dictation_mode)
        self._stats["count"] += 1
        self._stats["last_ms"] = round(elapsed * 1000.0, 1)
        self._stats["total_ms"] += elapsed * 1000.0

        return TranscriptionResult(
            text=norm_text,
            raw_text=raw_text,
            elapsed_s=elapsed,
            device=self.active_device,
            model=self.model_size,
            avg_logprob=round(avg_lp, 3),
            no_speech_prob=round(avg_nsp, 3),
            audio_metrics=metrics,
            corrections=corrections,
        )

    def transcribe_pcm_partial(
        self,
        pcm_bytes: bytes,
        *,
        language: str = DEFAULT_LANGUAGE,
        context_hint: str = "",
        dictation_mode: bool = False,
        max_window_s: float = 10.0,
    ) -> TranscriptionResult:
        """
        Transcripción parcial ultrarrápida (<250 ms en CUDA) para mostrar al instante
        la voz convertida a texto mientras el usuario sigue dictando.
        """
        if not pcm_bytes:
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size)

        max_bytes = int(max(2.0, float(max_window_s)) * SAMPLE_RATE * 2)
        if len(pcm_bytes) > max_bytes:
            pcm_bytes = pcm_bytes[-max_bytes:]

        audio_f32, metrics = preprocess_pcm_for_stt(pcm_bytes, sample_rate=SAMPLE_RATE)
        if audio_f32.size < int(SAMPLE_RATE * 0.28) or metrics["rms_out"] < 0.0028:
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size, audio_metrics=metrics)

        model = self._load()
        lang_arg = None if (not language or language.lower() == "auto") else language.split("-")[0].lower()
        prompt = SOVEREIGN_DOMAIN_PROMPT
        if context_hint:
            prompt = f"{SOVEREIGN_DOMAIN_PROMPT} {context_hint.strip()}"[:360]

        t0 = time.perf_counter()
        # Si hay una transcripción final ocupando el lock, no bloquear el hilo de vista previa
        if not self._infer_lock.acquire(timeout=0.08):
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size, audio_metrics=metrics)
        try:
            kwargs: Dict[str, Any] = {
                "language": lang_arg,
                "beam_size": 1,
                "best_of": 1,
                "temperature": 0.0,
                "vad_filter": False,
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.68,
                "compression_ratio_threshold": 2.35,
                "log_prob_threshold": -1.25,
                "initial_prompt": prompt,
                "hotwords": SOVEREIGN_HOTWORDS,
            }
            try:
                segments_iter, _info = model.transcribe(audio_f32, **kwargs)
                segments = list(segments_iter)
            except TypeError:
                kwargs.pop("hotwords", None)
                segments_iter, _info = model.transcribe(audio_f32, **kwargs)
                segments = list(segments_iter)
        finally:
            self._infer_lock.release()

        elapsed = time.perf_counter() - t0
        kept: List[str] = []
        for seg in segments:
            seg_txt = (seg.text or "").strip()
            if not seg_txt or is_whisper_hallucination(seg_txt):
                continue
            nsp = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
            alp = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
            if nsp > 0.80 and alp < -1.05:
                continue
            kept.append(seg_txt)

        raw_text = " ".join(kept).strip()
        if not raw_text or is_whisper_hallucination(raw_text):
            return TranscriptionResult("", raw_text, elapsed, self.active_device, self.model_size, audio_metrics=metrics)

        norm_text, corrections = self._normalizer.normalize(raw_text, dictation_mode=dictation_mode)
        return TranscriptionResult(
            text=norm_text,
            raw_text=raw_text,
            elapsed_s=elapsed,
            device=self.active_device,
            model=self.model_size,
            audio_metrics=metrics,
            corrections=corrections,
        )

    def transcribe_pcm(
        self,
        pcm_bytes: bytes,
        language: str = DEFAULT_LANGUAGE,
        min_duration_s: float = 0.20,
        context_hint: str = "",
        dictation_mode: bool = False,
    ) -> Tuple[str, float]:
        res = self.transcribe_pcm_detailed(
            pcm_bytes,
            language=language,
            min_duration_s=min_duration_s,
            context_hint=context_hint,
            dictation_mode=dictation_mode,
        )
        return res.text, res.elapsed_s

    def transcribe_audio_bytes(
        self,
        audio_bytes: bytes,
        *,
        audio_format: str = "wav",
        language: str = DEFAULT_LANGUAGE,
        context_hint: str = "",
        dictation_mode: bool = False,
    ) -> Tuple[str, float]:
        if not audio_bytes:
            return "", 0.0
        fmt = (audio_format or "wav").strip().lower().lstrip(".")
        if fmt in ("pcm", "pcm16", "s16le", "raw"):
            return self.transcribe_pcm(
                audio_bytes, language=language, context_hint=context_hint, dictation_mode=dictation_mode
            )
        pcm_bytes = self.decode_to_pcm16k(audio_bytes, suffix=f".{fmt}")
        return self.transcribe_pcm(
            pcm_bytes, language=language, context_hint=context_hint, dictation_mode=dictation_mode
        )

    def transcribe_file(
        self,
        audio_path: str | Path,
        *,
        language: str = DEFAULT_LANGUAGE,
        context_hint: str = "",
        dictation_mode: bool = False,
    ) -> TranscriptionResult:
        p = Path(audio_path)
        raw = p.read_bytes()
        pcm = self.decode_to_pcm16k(raw, suffix=p.suffix or ".wav")
        return self.transcribe_pcm_detailed(
            pcm, language=language, context_hint=context_hint, dictation_mode=dictation_mode
        )

    def get_status(self) -> Dict[str, Any]:
        avg_ms = (self._stats["total_ms"] / self._stats["count"]) if self._stats["count"] else 0.0
        used_vram, free_vram = query_gpu_vram_mb()
        return {
            "engine": "faster-whisper",
            "loaded": self.is_loaded,
            "model": self.model_size if self.is_loaded else self.requested_model,
            "device": self.active_device,
            "compute_type": self.compute_type,
            "sample_rate": SAMPLE_RATE,
            "transcriptions": self._stats["count"],
            "last_ms": self._stats["last_ms"],
            "avg_ms": round(avg_ms, 1),
            "vram_used_mb": used_vram,
            "vram_free_mb": free_vram,
            "last_error": self._last_error,
        }
