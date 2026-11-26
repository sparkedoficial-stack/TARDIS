"""core/voice/playback_router.py - Reproductor PCM gapless con Barge-In, enrutador LLM multi-carril y rastreador de dictado."""
from __future__ import annotations

from core.voice.common import *
from core.voice.tts_prosody import (
    WordTiming,
    SyncedSpeechSegment,
    pcm_to_wav_bytes,
)

class GaplessAudioPlayer:
    """
    Reproductor de audio de ultra-baja latencia con soporte de:
      - PCM raw directo a PipeWire (`pw-cat`/`pacat`) sin cortes ni archivos temporales.
      - MP3/WAV comprimido con `ffplay`/`mpv`/`pw-play`.
      - Interrupción Barge-In inmediata (<20ms) sin procesos huérfanos.
      - Ventana anti-eco post-locución (240 ms) calibrada para Lentes EVOIR / bocinas.
    """

    def __init__(
        self,
        enabled: bool = True,
        echo_guard_s: float = 0.24,
        on_state: Optional[Callable[[bool], None]] = None,
    ):
        self.enabled = enabled
        self.echo_guard_s = max(0.05, float(echo_guard_s))
        self._on_state = on_state
        self._queue: "queue.Queue[Optional[Tuple[str, Any, int]]]" = queue.Queue()
        self._proc_lock = threading.Lock()
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._playing = False
        self._last_play_end = 0.0
        self._stop_flag = threading.Event()
        self._interrupted = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="TARDIS-AudioPlayer")
        self._thread.start()

    @property
    def is_playing(self) -> bool:
        if self._playing or not self._queue.empty():
            return True
        return (time.monotonic() - self._last_play_end) < self.echo_guard_s

    def _notify(self, playing: bool) -> None:
        if self._on_state is not None:
            try:
                self._on_state(playing)
            except Exception:
                pass

    @staticmethod
    def _raw_pcm_cmd(sample_rate: int) -> Optional[List[str]]:
        if shutil.which("pw-cat"):
            return [
                "pw-cat", "--playback", "--raw",
                "--rate", str(sample_rate),
                "--channels", "1",
                "--format", "s16",
                "-",
            ]
        if shutil.which("pacat"):
            return [
                "pacat", "--playback", "--raw",
                f"--rate={sample_rate}",
                "--channels=1",
                "--format=s16le",
            ]
        if shutil.which("aplay"):
            return [
                "aplay", "-q", "-t", "raw", "-f", "S16_LE",
                "-r", str(sample_rate), "-c", "1", "-",
            ]
        return None

    @staticmethod
    def _file_player_cmd(path: Path) -> Optional[List[str]]:
        if path.suffix.lower() == ".wav" and shutil.which("pw-play"):
            return ["pw-play", str(path)]
        if shutil.which("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
        if shutil.which("mpv"):
            return ["mpv", "--no-video", "--really-quiet", str(path)]
        if shutil.which("pw-play"):
            return ["pw-play", str(path)]
        return None

    def _play_pcm(self, pcm: bytes, sample_rate: int) -> None:
        cmd = self._raw_pcm_cmd(sample_rate)
        if not cmd:
            # Fallback a WAV en archivo temporal
            wav = pcm_to_wav_bytes(pcm, sample_rate=sample_rate)
            self._play_bytes_file(wav, ".wav")
            return
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        with self._proc_lock:
            self._proc = proc
        try:
            if proc.stdin is not None:
                # Escribir en bloques pequeños de ~60ms para responder a Barge-In al instante
                chunk_bytes = max(1024, int(sample_rate * 2 * 0.06))
                for off in range(0, len(pcm), chunk_bytes):
                    if self._interrupted.is_set() or proc.poll() is not None:
                        break
                    try:
                        proc.stdin.write(pcm[off : off + chunk_bytes])
                        proc.stdin.flush()
                    except BrokenPipeError:
                        break
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            proc.wait()
        finally:
            with self._proc_lock:
                self._proc = None

    def _play_bytes_file(self, data: bytes, suffix: str) -> None:
        shm_dir = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())
        tmp = shm_dir / f"tardis_play_{os.getpid()}_{time.time_ns()}{suffix}"
        try:
            tmp.write_bytes(data)
            self._play_path(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def _play_path(self, path: Path) -> None:
        cmd = self._file_player_cmd(path)
        if not cmd:
            return
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        with self._proc_lock:
            self._proc = proc
        try:
            proc.wait()
        finally:
            with self._proc_lock:
                self._proc = None

    def _run_word_sync_clock(
        self,
        segment: SyncedSpeechSegment,
        stop_ev: threading.Event,
        on_start: Optional[Callable[[SyncedSpeechSegment], None]] = None,
        on_word: Optional[Callable[[SyncedSpeechSegment, WordTiming, int], None]] = None,
        on_end: Optional[Callable[[SyncedSpeechSegment, bool], None]] = None,
        pipewire_lead_ms: int = 35,
    ) -> None:
        """
        Reloj de sincronización texto↔sonido: dispara `on_word` en el instante exacto
        en que cada palabra sale por PipeWire, y se detiene al milisegundo ante Barge-In.
        """
        if on_start is not None:
            try:
                on_start(segment)
            except Exception:
                pass
        t0 = time.monotonic() + (max(0, pipewire_lead_ms) / 1000.0)
        timings = segment.word_timings
        interrupted = False
        for idx, wt in enumerate(timings):
            target = t0 + (wt.start_ms / 1000.0)
            while True:
                if stop_ev.is_set() or self._interrupted.is_set():
                    interrupted = True
                    break
                rem = target - time.monotonic()
                if rem <= 0.004:
                    break
                time.sleep(min(0.020, rem))
            if interrupted:
                break
            if on_word is not None:
                try:
                    on_word(segment, wt, idx)
                except Exception:
                    pass
        if on_end is not None:
            try:
                on_end(segment, interrupted)
            except Exception:
                pass

    def _play_synced(self, payload: Dict[str, Any]) -> None:
        segment: SyncedSpeechSegment = payload["segment"]
        on_start = payload.get("on_start")
        on_word = payload.get("on_word")
        on_end = payload.get("on_end")
        stop_ev = threading.Event()
        sync_thread = threading.Thread(
            target=self._run_word_sync_clock,
            args=(segment, stop_ev, on_start, on_word, on_end),
            daemon=True,
            name="TARDIS-WordSync",
        )
        sync_thread.start()
        try:
            if segment.pcm:
                self._play_pcm(segment.pcm, segment.sample_rate)
            elif segment.encoded_bytes:
                ext = ".wav" if "wav" in segment.mime else ".mp3"
                self._play_bytes_file(segment.encoded_bytes, ext)
        finally:
            if self._interrupted.is_set():
                stop_ev.set()
            sync_thread.join(timeout=max(0.4, (segment.duration_ms / 1000.0) + 0.35))
            stop_ev.set()

    def _worker(self) -> None:
        while not self._stop_flag.is_set():
            item = self._queue.get()
            if item is None:
                break
            kind, payload, sr = item
            if not self.enabled or self._interrupted.is_set():
                if kind == "path" and isinstance(payload, Path):
                    payload.unlink(missing_ok=True)
                continue
            try:
                self._playing = True
                self._notify(True)
                if kind == "synced":
                    self._play_synced(payload)
                elif kind == "pcm":
                    self._play_pcm(payload, sr)
                elif kind == "bytes":
                    self._play_bytes_file(payload, ".wav" if sr == -1 else ".mp3")
                elif kind == "path" and isinstance(payload, Path) and payload.exists():
                    self._play_path(payload)
            except Exception as exc:
                logger.debug("Error reproduciendo audio: %s", exc)
            finally:
                self._playing = False
                self._last_play_end = time.monotonic()
                if self._queue.empty():
                    self._notify(False)
                if kind == "path" and isinstance(payload, Path):
                    payload.unlink(missing_ok=True)

    def enqueue_synced(
        self,
        segment: SyncedSpeechSegment,
        *,
        on_start: Optional[Callable[[SyncedSpeechSegment], None]] = None,
        on_word: Optional[Callable[[SyncedSpeechSegment, WordTiming, int], None]] = None,
        on_end: Optional[Callable[[SyncedSpeechSegment, bool], None]] = None,
    ) -> None:
        """Encola un segmento hablado sincronizado palabra por palabra con el audio real."""
        if not self.enabled or segment is None:
            return
        if not segment.pcm and not segment.encoded_bytes:
            return
        self._interrupted.clear()
        self._queue.put((
            "synced",
            {
                "segment": segment,
                "on_start": on_start,
                "on_word": on_word,
                "on_end": on_end,
            },
            segment.sample_rate,
        ))

    def enqueue_pcm(self, pcm: bytes, sample_rate: int = PIPER_SAMPLE_RATE) -> None:
        if not self.enabled or not pcm:
            return
        self._interrupted.clear()
        self._queue.put(("pcm", pcm, int(sample_rate)))

    def enqueue_bytes(self, audio_bytes: bytes, mime: str = "audio/wav") -> None:
        if not self.enabled or not audio_bytes:
            return
        self._interrupted.clear()
        if "wav" in mime and audio_bytes[:4] == b"RIFF":
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    if wf.getnchannels() == 1 and wf.getsampwidth() == 2:
                        pcm = wf.readframes(wf.getnframes())
                        self._queue.put(("pcm", pcm, wf.getframerate()))
                        return
            except Exception:
                pass
        self._queue.put(("bytes", audio_bytes, -1 if "wav" in mime else 0))

    def enqueue_path(self, path: Path) -> None:
        if not self.enabled or not path:
            return
        self._interrupted.clear()
        self._queue.put(("path", path, 0))

    def interrupt(self) -> None:
        self._interrupted.set()
        while True:
            try:
                item = self._queue.get_nowait()
                if item and item[0] == "path" and isinstance(item[1], Path):
                    item[1].unlink(missing_ok=True)
            except queue.Empty:
                break
        with self._proc_lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
                except Exception:
                    try:
                        self._proc.terminate()
                    except Exception:
                        pass
        if self._playing:
            self._playing = False
            self._notify(False)

    def wait_idle(self, cancel_event: Optional[threading.Event] = None, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel_event and cancel_event.is_set():
                return
            if not self._playing and self._queue.empty():
                return
            time.sleep(0.04)

    def shutdown(self) -> None:
        self.interrupt()
        self._stop_flag.set()
        self._queue.put(None)
        self._thread.join(timeout=1.5)


# ==============================================================================
# 8. ENRUTADOR MULTI-CARRIL LLM DE BAJA LATENCIA PARA VOZ LOCAL
# ==============================================================================

class LocalVoiceLLMRouter:
    """
    Enruta cada turno de voz al carril local más rápido y disponible:
      1. Verifica `/slots` de TemporalBrain UDS en <80 ms.
         - Si hay al menos 1 slot libre -> streaming directo en `TARDIS-NEURAL-SPACE-KAIJU` (8B).
      2. Si TemporalBrain está saturado (todos los slots ocupados en tareas largas):
         - Usa el carril GPU dedicado `127.0.0.1:11435` (`qwen3-vl:2b-instruct`,
           siempre con `num_ctx=3072` y `keep_alive=-1` para CERO recargas).
      3. Respaldo a `:8757/api/chat` o Ollama `:11434`.
    """

    @staticmethod
    def _read_token() -> str:
        env = os.environ.get("GIA_AUTH_TOKEN") or os.environ.get("GIA_TOKEN") or ""
        if env:
            return env.strip()
        try:
            if TARDIS_TOKEN_FILE.exists():
                return TARDIS_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        return ""

    @staticmethod
    def inspect_temporal_brain_slots(timeout: float = 0.15) -> Dict[str, Any]:
        if not HAS_HTTPX or httpx is None or not TEMPORAL_BRAIN_SOCK.exists():
            return {"available": False, "free_slots": 0, "total_slots": 0}
        try:
            transport = httpx.HTTPTransport(uds=str(TEMPORAL_BRAIN_SOCK))
            with httpx.Client(transport=transport, base_url="http://localhost", timeout=timeout) as client:
                r = client.get("/slots")
                if r.status_code != 200:
                    return {"available": False, "free_slots": 0, "total_slots": 0}
                slots = r.json()
                total = len(slots) if isinstance(slots, list) else 0
                free = sum(1 for s in slots if isinstance(s, dict) and not s.get("is_processing"))
                return {"available": True, "free_slots": free, "total_slots": total}
        except Exception:
            return {"available": False, "free_slots": 0, "total_slots": 0}

    @staticmethod
    def inspect_voice_ollama_lane(timeout: float = 0.25) -> Dict[str, Any]:
        if not HAS_HTTPX or httpx is None:
            return {"available": False, "model_loaded": False}
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{VOICE_OLLAMA_URL}/api/ps")
                if r.status_code != 200:
                    return {"available": False, "model_loaded": False}
                models = (r.json() or {}).get("models") or []
                loaded = any(VOICE_OLLAMA_MODEL in str(m.get("name", "")) for m in models)
                return {"available": True, "model_loaded": loaded, "models": [m.get("name") for m in models]}
        except Exception:
            return {"available": False, "model_loaded": False}

    def _stream_temporal_brain(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        cancel_event: threading.Event,
    ) -> Iterator[str]:
        if not HAS_HTTPX or httpx is None or not TEMPORAL_BRAIN_SOCK.exists():
            return
        transport = httpx.HTTPTransport(uds=str(TEMPORAL_BRAIN_SOCK))
        with httpx.Client(transport=transport, base_url="http://localhost", timeout=httpx.Timeout(60.0, connect=2.0)) as client:
            payload = {
                "messages": messages,
                "stream": True,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "cache_prompt": True,
            }
            with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
                if resp.status_code != 200:
                    return
                in_think = False
                for line in resp.iter_lines():
                    if cancel_event.is_set():
                        return
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        continue
                    delta = ((obj.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                    if not delta:
                        continue
                    if "<think>" in delta:
                        in_think = True
                        delta = delta.split("<think>", 1)[0]
                    if in_think:
                        if "</think>" in delta:
                            in_think = False
                            delta = delta.split("</think>", 1)[1]
                        else:
                            continue
                    if delta:
                        yield delta

    def _stream_ollama(
        self,
        base_url: str,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        num_ctx: int,
        cancel_event: threading.Event,
        *,
        num_gpu: Optional[int] = None,
    ) -> Iterator[str]:
        if not HAS_HTTPX or httpx is None:
            return
        options: Dict[str, Any] = {
            "num_ctx": num_ctx,
            "num_predict": max_tokens,
            "temperature": temperature,
        }
        if num_gpu is not None and int(num_gpu) >= 0:
            options["num_gpu"] = int(num_gpu)
        with httpx.Client(timeout=httpx.Timeout(45.0, connect=2.5)) as client:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "keep_alive": -1,
                "options": options,
            }
            with client.stream("POST", f"{base_url}/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    return
                in_think = False
                for line in resp.iter_lines():
                    if cancel_event.is_set():
                        return
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    delta = (obj.get("message") or {}).get("content") or ""
                    if not delta:
                        continue
                    if "<think>" in delta:
                        in_think = True
                        delta = delta.split("<think>", 1)[0]
                    if in_think:
                        if "</think>" in delta:
                            in_think = False
                            delta = delta.split("</think>", 1)[1]
                        else:
                            continue
                    if delta:
                        yield delta

    def stream_reply(
        self,
        messages: List[Dict[str, str]],
        *,
        user_text: str,
        client_id: str = "infinite_voice_local",
        max_tokens: int = 240,
        temperature: float = 0.30,
        lane: str = "auto",
        cancel_event: Optional[threading.Event] = None,
    ) -> Tuple[str, Iterator[str]]:
        """
        Elige el carril óptimo y devuelve (lane_name, token_iterator).
        """
        ev = cancel_event or threading.Event()
        tb = self.inspect_temporal_brain_slots()
        vl = self.inspect_voice_ollama_lane()

        # Construir orden dinámico de carriles priorizando latencia conversacional real:
        # En RTX 3050 4 GB con tareas autónomas activas, el carril GPU dedicado :11435
        # (qwen3-vl:2b-instruct con num_gpu=22 y num_ctx=3072 alineado con C310/VLM)
        # ofrece TTFT <1s sin competir con slots de TemporalBrain 8B.
        order: List[str] = []
        if lane == "fast" or lane == "voice_gpu":
            order = ["voice_gpu", "temporal_brain", "api_chat", "ollama_main"]
        elif lane == "temporal_brain":
            order = ["temporal_brain", "voice_gpu", "api_chat", "ollama_main"]
        else:
            if vl["available"]:
                order = ["voice_gpu", "temporal_brain", "api_chat", "ollama_main"]
            elif tb["available"] and tb["free_slots"] > 0:
                order = ["temporal_brain", "api_chat", "ollama_main"]
            elif tb["available"]:
                order = ["temporal_brain", "api_chat", "ollama_main"]
            else:
                order = ["api_chat", "ollama_main"]

        chosen = order[0]

        def _gen() -> Iterator[str]:
            for cand in order:
                if ev.is_set():
                    return
                emitted = False
                try:
                    if cand == "temporal_brain" and tb["available"]:
                        for tok in self._stream_temporal_brain(messages, max_tokens, temperature, ev):
                            emitted = True
                            yield tok
                    elif cand == "voice_gpu" and vl["available"]:
                        for tok in self._stream_ollama(
                            VOICE_OLLAMA_URL, VOICE_OLLAMA_MODEL, messages,
                            max_tokens, temperature, VOICE_OLLAMA_NUM_CTX, ev,
                            num_gpu=VOICE_OLLAMA_NUM_GPU,
                        ):
                            emitted = True
                            yield tok
                    elif cand == "ollama_main":
                        model = os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")
                        for tok in self._stream_ollama(
                            MAIN_OLLAMA_URL, model, messages,
                            max_tokens, temperature, 4096, ev,
                        ):
                            emitted = True
                            yield tok
                    elif cand == "api_chat":
                        tok = self._read_token()
                        payload = json.dumps({"message": user_text, "client_id": client_id}).encode("utf-8")
                        req = urllib.request.Request(
                            f"{TARDIS_CHAT_URL}?key={tok}",
                            data=payload,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=60.0) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                        rep = str(data.get("response") or data.get("reply") or data.get("message") or "").strip()
                        rep = _RE_THINK.sub("", rep).strip()
                        if rep:
                            emitted = True
                            yield rep
                except Exception as exc:
                    logger.warning("Carril LLM '%s' falló: %s", cand, exc)
                if emitted:
                    return
            if not ev.is_set():
                yield "Los motores locales están ocupados en este instante. Inténtalo de nuevo en unos segundos."

        return chosen, _gen()


# ==============================================================================
# 9. SINGLETONS GLOBALES Y TELEMETRÍA CONSOLIDADA
# ==============================================================================

class LiveDictationTracker:
    """
    Registro inmediato en memoria y disco atómico de la voz dictada en curso.
    Permite que CLI, tardis-desktop, mundo-desktop y API consulten en tiempo real
    exactamente qué palabras está capturando el sistema mientras hablas.
    """

    def __init__(self, state_path: Optional[Path] = None):
        data_dir = PROJECT_ROOT / "data"
        self.json_path = state_path or (data_dir / "voice_dictation_live.json")
        self.txt_path = self.json_path.with_suffix(".txt")
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "active": False,
            "partial_text": "",
            "final_text": "",
            "source": "",
            "rms": 0.0,
            "stt_ms": 0,
            "seq": 0,
            "updated_at": 0.0,
            "history": [],
        }

    def _persist_locked(self) -> None:
        try:
            self.json_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_j = self.json_path.with_suffix(".json.tmp")
            tmp_j.write_text(json.dumps(self._state, ensure_ascii=False), encoding="utf-8")
            tmp_j.replace(self.json_path)
            live_line = self._state["partial_text"] if self._state["active"] else self._state["final_text"]
            tmp_t = self.txt_path.with_suffix(".txt.tmp")
            tmp_t.write_text(live_line or "", encoding="utf-8")
            tmp_t.replace(self.txt_path)
        except OSError:
            pass

    def update_partial(self, text: str, *, source: str = "local", rms: float = 0.0, stt_ms: int = 0) -> Dict[str, Any]:
        with self._lock:
            self._state["active"] = True
            self._state["partial_text"] = (text or "").strip()
            self._state["source"] = source
            self._state["rms"] = round(float(rms), 4)
            self._state["stt_ms"] = int(stt_ms)
            self._state["seq"] = int(self._state["seq"]) + 1
            self._state["updated_at"] = round(time.time(), 3)
            self._persist_locked()
            return dict(self._state)

    def commit_final(self, text: str, *, source: str = "local", stt_ms: int = 0) -> Dict[str, Any]:
        clean = (text or "").strip()
        with self._lock:
            self._state["active"] = False
            self._state["partial_text"] = ""
            if clean:
                self._state["final_text"] = clean
                hist = list(self._state.get("history") or [])
                hist.append({"text": clean, "ts": round(time.time(), 3), "source": source, "stt_ms": int(stt_ms)})
                self._state["history"] = hist[-25:]
            self._state["source"] = source
            self._state["stt_ms"] = int(stt_ms)
            self._state["seq"] = int(self._state["seq"]) + 1
            self._state["updated_at"] = round(time.time(), 3)
            self._persist_locked()
            return dict(self._state)

    def clear_active(self) -> None:
        with self._lock:
            if not self._state["active"] and not self._state["partial_text"]:
                return
            self._state["active"] = False
            self._state["partial_text"] = ""
            self._state["updated_at"] = round(time.time(), 3)
            self._persist_locked()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)
