"""core/voice/abstraction.py - Motor de abstracción semántica local (<15 ms, 0 llamadas LLM)."""
from __future__ import annotations

from core.voice.common import *
from core.voice.vad_segmentation import (
    DictationNormalizer,
    strip_accents,
    normalize_key,
)

# ==============================================================================
# 5. MOTOR DE ABSTRACCIÓN SEMÁNTICA EN TIEMPO REAL (<15 ms, 100% LOCAL)
# ==============================================================================

@dataclass
class VoiceAbstraction:
    raw_text: str
    normalized_text: str
    intent: str
    sub_intent: str = ""
    entities: List[str] = field(default_factory=list)
    active_topic: str = ""
    resolved_query: str = ""
    needs_web: bool = False
    web_query: str = ""
    response_style: str = "balanced"  # concise | balanced | detailed | step_by_step
    max_tokens: int = 240
    max_sentences: int = 4
    instant_reply: Optional[str] = None
    action: Optional[Dict[str, Any]] = None
    system_guidance: str = ""
    corrections: List[str] = field(default_factory=list)
    is_incomplete: bool = False
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "intent": self.intent,
            "sub_intent": self.sub_intent,
            "entities": self.entities,
            "active_topic": self.active_topic,
            "resolved_query": self.resolved_query,
            "needs_web": self.needs_web,
            "web_query": self.web_query,
            "response_style": self.response_style,
            "max_tokens": self.max_tokens,
            "max_sentences": self.max_sentences,
            "has_instant_reply": self.instant_reply is not None,
            "action": self.action,
            "corrections": self.corrections,
            "is_incomplete": self.is_incomplete,
            "latency_ms": round(self.latency_ms, 2),
        }


class VoiceAbstractionEngine:
    """
    Motor de abstracción cognitiva de ultra-baja latencia (<15ms) para conversación
    y dictado por voz:
      - Normaliza dictado (DictationNormalizer).
      - Clasifica intención y sub-intención con alta precisión en español.
      - Extrae entidades y mantiene memoria de tópico activo multi-turno.
      - Resuelve referencias anafóricas ("eso", "explícalo más simple", "dame un ejemplo",
        "profundiza", "hazlo más corto", "repite").
      - Resuelve instantáneamente comandos deterministas locales (hora, telemetría,
        volumen, motor de voz, modo dictado) sin esperar inferencia LLM.
      - Ajusta dinámicamente estilo y presupuesto de tokens para máxima fluidez hablada.
    """

    _STOPWORDS = frozenset({
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a",
        "en", "con", "sin", "por", "para", "sobre", "entre", "hacia", "desde", "que",
        "cual", "cuales", "quien", "quienes", "como", "cuando", "donde", "porque",
        "pero", "mas", "muy", "poco", "mucho", "todo", "toda", "todos", "todas",
        "esto", "esta", "estos", "estas", "eso", "esa", "esos", "esas", "algo",
        "hola", "oye", "hey", "tardis", "por", "favor", "dime", "puedes", "podrias",
        "quiero", "necesito", "explicame", "explica", "cuentame", "hablame", "me",
        "te", "se", "nos", "le", "les", "mi", "tu", "su", "es", "son", "esta", "estan",
        "fue", "ser", "estar", "hacer", "tener", "hay", "ver", "saber", "aqui", "ahi",
    })

    _ANAPHORA_MARKERS = (
        "eso", "esto", "lo anterior", "el anterior", "la anterior", "ese tema",
        "esa idea", "lo mismo", "de nuevo", "otra vez", "mas sobre", "más sobre",
        "y su ", "y sus ", "al respecto",
    )

    _WEB_KEYWORDS = (
        "hoy", "actual", "actualmente", "ultima hora", "última hora", "noticias",
        "precio de", "cuanto cuesta", "cuánto cuesta", "cotizacion", "cotización",
        "clima en", "tiempo en", "temperatura en", "pronostico", "pronóstico",
        "resultado del partido", "quien gano", "quién ganó", "version actual",
        "versión actual", "busca en internet", "investiga en la web", "googlea",
    )

    def __init__(self, normalizer: Optional[DictationNormalizer] = None):
        self.normalizer = normalizer or DictationNormalizer()
        self.active_topic: str = ""
        self.recent_entities: Deque[str] = deque(maxlen=12)
        self.recent_topics: Deque[str] = deque(maxlen=6)
        self.last_user_text: str = ""
        self.last_assistant_reply: str = ""
        self.dictation_mode: bool = False
        self.dictation_buffer: List[str] = []

    def record_assistant_reply(self, reply: str) -> None:
        if reply and reply.strip():
            self.last_assistant_reply = reply.strip()

    def get_stt_context_hint(self) -> str:
        """Construye una pista léxica compacta para el prompt de Whisper sin causar bucles."""
        parts: List[str] = []
        if self.active_topic:
            parts.append(f"Tema actual: {self.active_topic}.")
        if self.recent_entities:
            ents = ", ".join(list(dict.fromkeys(self.recent_entities))[-8:])
            parts.append(f"Palabras clave recientes: {ents}.")
        if self.last_user_text:
            tail = " ".join(self.last_user_text.split()[-14:])
            parts.append(tail)
        return " ".join(parts).strip()[:220]

    def _extract_entities(self, text: str) -> List[str]:
        entities: List[str] = []
        # Acrónimos, términos técnicos con dígitos o CamelCase/Mayúsculas
        for m in re.finditer(r"\b(?:[A-Z]{2,}[0-9]*|[A-Z][a-z]+[A-Z][A-Za-z0-9]*|[A-Za-z]+[0-9]{2,})\b", text):
            tok = m.group(0)
            if tok.lower() not in self._STOPWORDS and tok not in entities:
                entities.append(tok)
        # Sustantivos significativos (>=4 letras no stopword)
        for tok in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9\-]{4,}", text):
            low = strip_accents(tok).lower()
            if low not in self._STOPWORDS and tok not in entities:
                entities.append(tok)
            if len(entities) >= 8:
                break
        return entities

    def _extract_topic(self, normalized_text: str, entities: List[str]) -> str:
        # Intenta capturar complemento después de "sobre", "acerca de", "qué es", "cómo funciona"
        m = re.search(
            r"(?i)(?:sobre|acerca\s+de|qu[eé]\s+es|c[oó]mo\s+funciona|expl[ií]came|h[aá]blame\s+de|investiga)\s+([^?.!]{3,70})",
            normalized_text,
        )
        if m:
            cand = m.group(1).strip(" ,.;:¡¿")
            if len(cand.split()) >= 1 and normalize_key(cand) not in ("eso", "esto", "lo anterior"):
                return cand[:70]
        if entities:
            return ", ".join(entities[:3])
        return self.active_topic

    @staticmethod
    def _instant_time_date(only_time: bool = False, only_date: bool = False) -> str:
        now = datetime.datetime.now()
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        meses = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        ]
        hora = now.strftime("%I:%M %p").lstrip("0")
        fecha = f"{dias[now.weekday()]} {now.day} de {meses[now.month - 1]} de {now.year}"
        if only_time:
            return f"Son las {hora}."
        if only_date:
            return f"Hoy es {fecha}."
        return f"Son las {hora} del {fecha}."

    @staticmethod
    def _instant_telemetry() -> str:
        cpu_pct = psutil.cpu_percent(interval=0.05) if HAS_PSUTIL and psutil else 0.0
        mem = psutil.virtual_memory() if HAS_PSUTIL and psutil else None
        ram_str = (
            f"{mem.used / (1024**3):.1f} de {mem.total / (1024**3):.0f} gigabytes de memoria RAM"
            if mem else "memoria operativa"
        )
        freq = query_cpu_freq_mhz()
        freq_str = f" a {freq:.0f} megahercios" if freq > 0 else ""

        cpu_temp = ""
        try:
            for h in Path("/sys/class/hwmon").glob("hwmon*"):
                if (h / "name").read_text(encoding="utf-8").strip() == "k10temp":
                    t = int((h / "temp1_input").read_text(encoding="utf-8").strip()) // 1000
                    cpu_temp = f", CPU en {t} grados"
                    break
        except Exception:
            pass

        gpu_str = ""
        if shutil.which("nvidia-smi"):
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                    stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=2.0,
                ).strip().splitlines()[0]
                gt, gu, gtot = [x.strip() for x in out.split(",")]
                gpu_str = f" y GPU RTX 3050 en {gt} grados usando {gu} de {gtot} megabytes de VRAM"
            except Exception:
                pass

        return (
            f"El sistema TARDIS está operativo. Procesador al {cpu_pct:.0f} por ciento{freq_str}{cpu_temp}, "
            f"{ram_str}{gpu_str}."
        )

    @staticmethod
    def _adjust_volume(op: str) -> str:
        if not shutil.which("pactl"):
            return "No encontré pactl para controlar el volumen."
        try:
            if op == "up":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+12%"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)
                return "Volumen subido."
            if op == "down":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-12%"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)
                return "Volumen bajado."
            if op == "mute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)
                return "Audio silenciado."
            if op == "unmute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)
                return "Audio restaurado."
        except Exception as exc:
            return f"No pude ajustar el volumen: {exc}"
        return "Listo."

    @staticmethod
    def _copy_to_clipboard(text: str) -> bool:
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(
                        cmd, input=text.encode("utf-8"),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=3, check=True,
                    )
                    return True
                except Exception:
                    continue
        return False

    def abstract(self, raw_text: str, allow_system_actions: bool = True) -> VoiceAbstraction:
        """Normaliza y abstrae la consulta por voz en <15 ms."""
        t0 = time.perf_counter()
        normalized, corrections = self.normalizer.normalize(raw_text, dictation_mode=self.dictation_mode)
        low = normalize_key(normalized)
        is_inc = self.normalizer.is_incomplete_utterance(normalized)
        entities = self._extract_entities(normalized)

        # 0. Control de modo dictado
        if any(k in low for k in ("activa modo dictado", "activar modo dictado", "modo dictado", "inicia dictado", "iniciar dictado")):
            self.dictation_mode = True
            self.dictation_buffer.clear()
            return VoiceAbstraction(
                raw_text=raw_text, normalized_text=normalized,
                intent="dictation_mode", sub_intent="start",
                active_topic=self.active_topic,
                instant_reply="Modo dictado continuo activado. Dicta con libertad y di termina dictado cuando finalices.",
                action={"type": "dictation_mode", "enabled": True},
                corrections=corrections,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        if self.dictation_mode:
            if any(k in low for k in ("termina dictado", "terminar dictado", "fin de dictado", "salir de dictado", "modo conversacion", "deten dictado")):
                self.dictation_mode = False
                full_doc = "\n".join(self.dictation_buffer).strip()
                copied = self._copy_to_clipboard(full_doc) if full_doc else False
                word_cnt = len(full_doc.split()) if full_doc else 0
                note = " y lo copié al portapapeles" if copied else ""
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="dictation_mode", sub_intent="stop",
                    active_topic=self.active_topic,
                    instant_reply=f"Dictado finalizado con {word_cnt} palabras{note}. Volvemos a conversación normal.",
                    action={"type": "dictation_mode", "enabled": False, "text": full_doc, "copied": copied},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("borra lo ultimo", "borra la ultima frase", "deshaz lo ultimo")):
                if self.dictation_buffer:
                    self.dictation_buffer.pop()
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="dictation_mode", sub_intent="undo",
                    instant_reply="Último fragmento borrado. Continúa dictando.",
                    action={"type": "dictation_undo"},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("lee el dictado", "leer dictado", "que llevo dictado")):
                doc = " ".join(self.dictation_buffer).strip()
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="dictation_mode", sub_intent="read",
                    instant_reply=doc or "Aún no has dictado texto.",
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            # Captura pura de dictado sin molestar al LLM
            self.dictation_buffer.append(normalized)
            return VoiceAbstraction(
                raw_text=raw_text, normalized_text=normalized,
                intent="dictation_capture", sub_intent="append",
                instant_reply="",  # Silencioso para fluidez del dictado
                action={"type": "dictation_append", "text": normalized, "buffer_size": len(self.dictation_buffer)},
                corrections=corrections,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # 1. Comandos instantáneos de control de voz/TTS (exigen frase corta imperativa para cero falsos positivos)
        n_words = len(low.split())
        if n_words <= 7:
            if any(k in low for k in ("usa voz local", "activa voz local", "cambia a voz local", "usa piper", "activa piper", "cambia a piper", "modo voz local", "modo offline")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="voice_control", sub_intent="tts_local",
                    instant_reply="Voz neuronal local Piper activada. Operando cien por ciento local y sin latencia de red.",
                    action={"type": "set_tts_mode", "mode": "local"},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("usa voz cortana", "activa voz cortana", "cambia a cortana", "usa cortana", "usa voz edge", "activa modo hibrido", "cambia a modo hibrido")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="voice_control", sub_intent="tts_hybrid",
                    instant_reply="Modo híbrido con voz Cortana activado y respaldo local Piper listo.",
                    action={"type": "set_tts_mode", "mode": "hybrid"},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("habla mas rapido", "acelera la voz", "sube velocidad de voz")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="voice_control", sub_intent="rate_up",
                    instant_reply="Perfecto, aumento un poco la velocidad al hablar.",
                    action={"type": "adjust_rate", "delta": 0.10},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("habla mas lento", "habla mas despacio", "baja la velocidad de voz")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="voice_control", sub_intent="rate_down",
                    instant_reply="Entendido, hablaré con un ritmo más pausado.",
                    action={"type": "adjust_rate", "delta": -0.10},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
        if low in ("repite", "repitelo", "repite eso", "repite lo ultimo", "que dijiste", "no te escuche"):
            rep = self.last_assistant_reply or "Aún no he dicho nada en esta sesión."
            return VoiceAbstraction(
                raw_text=raw_text, normalized_text=normalized,
                intent="voice_control", sub_intent="repeat",
                instant_reply=rep,
                corrections=corrections,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # 2. Comandos instantáneos de sistema/hardware (solo si permitidos y frase corta directa)
        if allow_system_actions and len(low.split()) <= 10:
            if any(k in low for k in ("que hora es", "dime la hora", "hora actual")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="system_command", sub_intent="time",
                    instant_reply=self._instant_time_date(only_time=True),
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("que dia es", "que fecha es", "fecha de hoy")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="system_command", sub_intent="date",
                    instant_reply=self._instant_time_date(only_date=True),
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("sube el volumen", "subir volumen", "mas volumen")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="system_command", sub_intent="volume_up",
                    instant_reply=self._adjust_volume("up"),
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("baja el volumen", "bajar volumen", "menos volumen")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="system_command", sub_intent="volume_down",
                    instant_reply=self._adjust_volume("down"),
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("estado del sistema", "telemetria del sistema", "temperatura de la gpu", "temperatura del cpu", "como esta el sistema")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="hardware_telemetry", sub_intent="status",
                    instant_reply=self._instant_telemetry(),
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )

        # 3. Clasificación de refinamiento / seguimiento anafórico
        sub_intent = ""
        response_style = "balanced"
        max_tokens = 240
        max_sentences = 4
        guidance_parts: List[str] = []

        if any(k in low for k in ("mas simple", "mas sencillo", "facil", "para principiantes", "sin tecnicismos")):
            intent = "followup_refinement"
            sub_intent = "simplify"
            response_style = "concise"
            max_tokens = 180
            max_sentences = 3
            guidance_parts.append("Explica el mismo tema con lenguaje muy simple, cotidiano y una analogía clara.")
        elif any(k in low for k in ("mas corto", "resumelo", "en resumen", "breve", "en una frase")):
            intent = "followup_refinement"
            sub_intent = "shorter"
            response_style = "concise"
            max_tokens = 110
            max_sentences = 2
            guidance_parts.append("Responde en máximo 1 o 2 frases ultra concisas.")
        elif any(k in low for k in ("dame un ejemplo", "pon un ejemplo", "ejemplo practico", "como se aplica")):
            intent = "followup_refinement"
            sub_intent = "example"
            response_style = "balanced"
            max_tokens = 220
            max_sentences = 4
            guidance_parts.append("Da un ejemplo concreto, práctico y fácil de imaginar en voz alta.")
        elif any(k in low for k in ("profundiza", "mas detalle", "explica mejor", "a fondo", "tecnicamente")):
            intent = "followup_refinement"
            sub_intent = "deepen"
            response_style = "detailed"
            max_tokens = 380
            max_sentences = 6
            guidance_parts.append("Profundiza con rigor técnico claro y bien articulado para escucharse por voz.")
        elif any(k in low for k in ("paso a paso", "como hago para", "como puedo", "guia")):
            intent = "technical_explanation"
            sub_intent = "step_by_step"
            response_style = "step_by_step"
            max_tokens = 300
            max_sentences = 5
            guidance_parts.append("Explica en pasos breves y secuenciales hablados (primero, luego, finalmente).")
        elif low in ("hola", "hola tardis", "buenos dias", "buenas tardes", "buenas noches", "oye tardis", "estas ahi", "tardis estas ahi"):
            intent = "greeting"
            response_style = "concise"
            max_tokens = 90
            max_sentences = 2
            guidance_parts.append("Saluda con calidez y brevedad en 1 o 2 frases directas.")
        elif any(k in low for k in ("explica", "como funciona", "que es", "por que", "diferencia entre", "analiza")):
            intent = "technical_explanation"
            response_style = "balanced"
            max_tokens = 280
            max_sentences = 4
        elif "?" in normalized or any(low.startswith(p) for p in ("que ", "como ", "cuando ", "donde ", "quien ", "cuanto ", "cual ")):
            intent = "factual_question"
            response_style = "concise"
            max_tokens = 190
            max_sentences = 3
        else:
            intent = "conversation"
            response_style = "balanced"
            max_tokens = 220
            max_sentences = 4

        # 4. Resolución de anáforas y memoria de tópico
        has_anaphora = (
            intent == "followup_refinement"
            or any(m in f" {low} " for m in self._ANAPHORA_MARKERS)
        )
        new_topic = self._extract_topic(normalized, entities)
        if not has_anaphora and new_topic:
            self.active_topic = new_topic
            if new_topic not in self.recent_topics:
                self.recent_topics.append(new_topic)
        for ent in entities:
            self.recent_entities.append(ent)

        resolved_query = normalized
        if has_anaphora and self.active_topic and normalize_key(self.active_topic) not in low:
            resolved_query = f"{normalized} (referido al tema activo: {self.active_topic})"
            guidance_parts.append(
                f"El usuario hace referencia al tema en curso: «{self.active_topic}». Mantén continuidad exacta."
            )

        # 5. Detección ligera de necesidad de internet
        needs_web = any(k in low for k in self._WEB_KEYWORDS)
        web_query = f"{normalized} {self.active_topic}".strip() if (needs_web and has_anaphora) else normalized

        self.last_user_text = normalized

        if self.active_topic:
            guidance_parts.append(f"Tópico activo: {self.active_topic}.")
        guidance_parts.append(
            f"Estilo hablado: {response_style} (idealmente <= {max_sentences} oraciones naturales sin Markdown ni tablas)."
        )

        return VoiceAbstraction(
            raw_text=raw_text,
            normalized_text=normalized,
            intent=intent,
            sub_intent=sub_intent,
            entities=entities,
            active_topic=self.active_topic,
            resolved_query=resolved_query,
            needs_web=needs_web,
            web_query=web_query if needs_web else "",
            response_style=response_style,
            max_tokens=max_tokens,
            max_sentences=max_sentences,
            instant_reply=None,
            action=None,
            system_guidance=" ".join(guidance_parts),
            corrections=corrections,
            is_incomplete=is_inc,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
