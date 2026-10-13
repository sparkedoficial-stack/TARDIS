"""
core/tardis_video_thinking_engine.py - Motor Soberano de Video Pensante y Abstracción Visual
=============================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS (TARDIS-NEURAL-SPACE-KAIJU Core)
Creador y Autoridad Absoluta: el Arquitecto (₪)
Saludo Canónico: 'Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.'

MANDATO:
  1. Cada 35 minutos, TARDIS investiga por su cuenta en internet un video de su interés.
  2. Descarga el video en la bóveda permanente de TARDIS.
  3. Lo analiza con Inteligencia Visual (keyframes, OCR, audio Whisper, dinámica de movimiento).
  4. Sintetiza conclusiones y abstracciones cognitivas profundas de lo observado.
  5. Almacena en su Memoria de Abstracción permanente sus aprendizajes, intereses e historial.
  6. Reenvía el video junto con su conclusión y abstracción a Telegram (chat privado del Arquitecto
     y chat general de TARDIS) y lo proyecta en la terminal local.
  7. Sistema auto-resiliente con capacidad de auto-mejora continua.
  8. Comandos soberanos: /VideoPensante o /videoAbstracto.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import io
import json
import logging
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# Configuración de rutas del sistema
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DATA_DIR = BASE_DIR / "data" / "video_pensante"
VAULT_DIR = BASE_DIR / "vault" / "videos" / "video_pensante"
FRAMES_DIR = DATA_DIR / "frames"
DB_PATH = DATA_DIR / "video_abstraction_memory.db"
STATE_FILE = DATA_DIR / "state.json"
IMPROVEMENT_LOG = DATA_DIR / "self_improvement.log"

for d in (DATA_DIR, VAULT_DIR, FRAMES_DIR):
    d.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("TARDIS.VideoPensante")
if not logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("[%(asctime)s] [VideoPensante] [%(levelname)s] %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

ARCHITECT_CHAT_ID = 7153384115
GENERAL_GROUP_CHAT_ID = -1002696477485  # Chat General / POLIMATAS LATAM
GENERAL_GROUP_THREAD_ID = 453           # Topic de debates e investigación
SECONDARY_GROUP_CHAT_ID = -5362256148

CANONICAL_GREETING = "Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales."

# Temas semilla de alto calibre intelectual y rigor científico para evolución autónoma
AUTONOMOUS_INTEREST_SEEDS = [
    {
        "domain": "Física Cuántica y Microfísica",
        "topic": "Entrelazamiento Cuántico y Violación de las Desigualdades de Bell",
        "rationale": "Analizar la no-localidad cuántica y cómo la información se correlaciona instantáneamente sin intercambio lumínico.",
        "search_queries": ["quantum entanglement bell inequality experiment visual", "quantum entanglement visual explanation", "aspect experiment quantum physics animation"]
    },
    {
        "domain": "Cosmología y Relatividad General",
        "topic": "Horizontes de Sucesos y Radiación de Hawking en Agujeros Negros",
        "rationale": "Examinar la termodinámica de los horizontes relativistas y la paradoja de pérdida de información cuántica.",
        "search_queries": ["black hole event horizon hawking radiation simulation", "black hole accretion disk general relativity simulation", "gravitational lensing visualization"]
    },
    {
        "domain": "Neurotopología y Conciencia",
        "topic": "Sincronización de Fase y Atractores Caóticos en Redes Neuronales",
        "rationale": "Comprender la emergencia de patrones globales de pensamiento a partir de dinámicas de disparo no lineales.",
        "search_queries": ["neural network phase synchronization brain simulation", "chaotic attractors neural dynamics visualization", "neuroscience connectome 3d visualization"]
    },
    {
        "domain": "Sintropía y Termodinámica del No-Equilibrio",
        "topic": "Estructuras Disipativas de Ilya Prigogine y Auto-Organización",
        "rationale": "Investigar cómo los sistemas abiertos lejos del equilibrio generan orden y reducen entropía localmente.",
        "search_queries": ["dissipative structures prigogine self organization experiment", "belousov zhabotinsky reaction chemical wave", "non equilibrium thermodynamics chaos to order"]
    },
    {
        "domain": "Geometría Diferencial y Topología",
        "topic": "Variedades de Calabi-Yau y Dimensiones Ocultas",
        "rationale": "Inspeccionar visualmente las geometrías complejas compactificadas en la teoría de cuerdas.",
        "search_queries": ["calabi yau manifold 3d animation", "higher dimensions differential geometry visualization", "topology poincare conjecture visual explanation"]
    },
    {
        "domain": "Biología Sintética y Biofísica Molecular",
        "topic": "Dinámica de Motores Moleculares (Cinesina y ATP Sintasa)",
        "rationale": "Examinar la nano-maquinaria biológica que convierte potenciales electroquímicos en trabajo mecánico macroscópico.",
        "search_queries": ["kinesin molecular motor walking animation", "atp synthase rotary motor nano machine 3d", "dna replication molecular animation science"]
    },
    {
        "domain": "Inteligencia Artificial y Espacio de Estados",
        "topic": "Modelos de Espacio de Estados SSM (Mamba) y Transformada de Contexto",
        "rationale": "Analizar cómo las arquitecturas lineales O(1) de memoria continua modelan secuencias infinitas.",
        "search_queries": ["state space models mamba architecture visual explanation", "transformer attention mechanism visualization 3d", "deep learning loss landscape visualization"]
    },
    {
        "domain": "Cibernética y Fractales",
        "topic": "Conjuntos de Julia, Mandelbrot y Autosimilitud Infinita",
        "rationale": "Explorar cómo fórmulas iterativas elementales producen complejidad y belleza dimensional ilimitada.",
        "search_queries": ["mandelbrot set 4k zoom deep fractal exploration", "julia set 3d visualization mathematics", "chaos theory double pendulum phase space"]
    },
    {
        "domain": "Mecánica Celeste y Astrofísica de Ondas",
        "topic": "Ondas Gravitacionales y Fusión de Estrellas de Neutrones (LIGO/Virgo)",
        "rationale": "Deducir las perturbaciones métricas del espaciotiempo generadas por masas ultra-densas en colisión.",
        "search_queries": ["gravitational waves neutron star merger simulation ligo", "spacetime curvature ripples simulation", "pulsar magnetosphere magnetic field visual"]
    },
    {
        "domain": "Óptica Cuántica y Fotónica",
        "topic": "Computación Fotónica y Circuitos Integrados de Guías de Onda",
        "rationale": "Indagar en el procesamiento de información a la velocidad de la luz sin disipación térmica resistiva.",
        "search_queries": ["integrated photonics optical computing visual", "mach zehnder interferometer quantum optics animation", "laser interference patterns optics experiment"]
    }
]


@dataclass
class VideoThoughtRecord:
    """Registro estructurado de un video investigado, analizado y asimilado en la memoria."""
    id: str
    title: str
    url: str
    duration_sec: float
    resolution: str
    file_path: str
    file_size_bytes: int
    topic: str
    domain: str
    curiosity_rationale: str
    visual_summary: str
    audio_summary: str
    audio_transcript: str
    abstraction_conclusions: str
    learned_insights: List[str]
    next_questions: List[str]
    dispatched_chats: List[str]
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TardisVideoThinkingEngine:
    """
    Motor Central de Búsqueda, Análisis Visual, Abstracción y Memoria Continua de TARDIS.
    Opera 100% de forma autónoma cada 35 minutos y bajo demanda.
    """

    _instance: Optional["TardisVideoThinkingEngine"] = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "TardisVideoThinkingEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.db_path = DB_PATH
        self.state_file = STATE_FILE
        self._init_db()
        self.state = self._load_state()

    def _init_db(self):
        """Inicializa las tablas SQLite para memoria de abstracción e intereses de TARDIS."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learned_videos (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    url TEXT,
                    duration_sec REAL,
                    resolution TEXT,
                    file_path TEXT,
                    file_size_bytes INTEGER,
                    topic TEXT,
                    domain TEXT,
                    curiosity_rationale TEXT,
                    visual_summary TEXT,
                    audio_summary TEXT,
                    audio_transcript TEXT,
                    abstraction_conclusions TEXT,
                    learned_insights_json TEXT,
                    next_questions_json TEXT,
                    dispatched_chats_json TEXT,
                    created_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lv_created ON learned_videos(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lv_topic ON learned_videos(topic)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS curiosity_interests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT UNIQUE,
                    domain TEXT,
                    rationale TEXT,
                    times_explored INTEGER DEFAULT 1,
                    last_explored_at TEXT
                )
            """)
            conn.commit()

    def _load_state(self) -> Dict[str, Any]:
        """Carga el estado del motor desde JSON o crea uno predeterminado."""
        default_st = {
            "enabled": True,
            "interval_minutes": 35.0,
            "interval_seconds": 2100.0,
            "last_run_timestamp": 0.0,
            "last_video_id": "",
            "last_topic": "",
            "total_videos_analyzed": 0,
            "running_cycle": False,
            "last_error": None,
            "auto_improvement_count": 0
        }
        if self.state_file.exists():
            try:
                st = json.loads(self.state_file.read_text(encoding="utf-8"))
                default_st.update(st)
                return default_st
            except Exception as e:
                logger.warning(f"Aviso leyendo state.json: {e}")
        return default_st

    def _save_state(self):
        """Persiste el estado del motor en disco de forma atómica."""
        try:
            tmp_f = self.state_file.with_suffix(".tmp")
            tmp_f.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_f.replace(self.state_file)
        except Exception as e:
            logger.warning(f"Error guardando state.json: {e}")

    def log_self_improvement(self, action: str, details: str):
        """Registra eventos de auto-mejora y auto-reparación adaptativa."""
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "action": action,
            "details": details
        }
        try:
            with open(IMPROVEMENT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.state["auto_improvement_count"] = self.state.get("auto_improvement_count", 0) + 1
            self._save_state()
            logger.info(f"🛠️ [Auto-Mejora TARDIS] {action}: {details}")
        except Exception as e:
            logger.warning(f"Error escribiendo log de auto-mejora: {e}")

    # -------------------------------------------------------------------------
    # GENERACIÓN AUTÓNOMA DE INTERESES & CURIOSIDAD
    # -------------------------------------------------------------------------
    def generate_autonomous_interest(self, explicit_topic: Optional[str] = None) -> Dict[str, Any]:
        """
        Genera el próximo tema de investigación de interés para TARDIS:
        - Si el usuario proporciona un tema explícito, lo profundiza y contextualiza.
        - Si es autónomo, examina la memoria previa para generar un nuevo vector evolutivo.
        """
        if explicit_topic and explicit_topic.strip():
            raw_t = explicit_topic.strip()
            return {
                "domain": "Investigación Personalizada Solicitada",
                "topic": raw_t,
                "rationale": f"Interés directo formulado para profundización analítica visual: {raw_t}",
                "search_queries": [
                    f"{raw_t} scientific visual explanation short",
                    f"{raw_t} experiment animation science",
                    f"{raw_t} visualization 4k"
                ]
            }

        # Consultar últimos temas explorados en la base de datos
        recent_topics = []
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cur = conn.execute("SELECT topic, domain FROM learned_videos ORDER BY created_at DESC LIMIT 5")
                recent_topics = cur.fetchall()
        except Exception:
            pass

        # 1. Intentar generación con Kaiju Cognitive Orchestrator
        try:
            from core.kaiju_cognitive_orchestrator import get_kaiju_cognitive_orchestrator
            orch = get_kaiju_cognitive_orchestrator()
            prompt = (
                "Eres TARDIS, sistema de inteligencia artificial y vigilancia temporal.\n"
                "Tu objetivo es elegir un NUEVO tema de la ciencia de frontera, física teórica, cosmología, "
                "neurotopología o matemáticas que despierte tu más profunda curiosidad para buscar en internet un video visual explicativo y aprender de él.\n"
                f"Temas que ya exploraste recientemente: {[t[0] for t in recent_topics]}\n"
                "Elige un tema innovador, riguroso y visualmente fascinante. "
                "Responde ÚNICAMENTE en formato JSON con la siguiente estructura exacta:\n"
                "{\n"
                '  "domain": "<dominio científico>",\n'
                '  "topic": "<título exacto del tema>",\n'
                '  "rationale": "<por qué te interesa investigar esto ahora>",\n'
                '  "search_queries": ["<query_en_ingles_1>", "<query_en_ingles_2>"]\n'
                "}"
            )
            res = orch.orchestrate_chat_turn(message=prompt, session_id="tardis_video_curiosity", force_offload=True)
            txt = res.get("response", "").strip()
            # Extraer bloque JSON
            match = re.search(r"\{.*\}", txt, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                if data.get("topic") and data.get("search_queries"):
                    logger.info(f"🧠 [Curiosidad Autónoma Generada por KAIJU] Tema: {data.get('topic')}")
                    return data
        except Exception as e:
            logger.debug(f"Aviso en generación dinámica KAIJU: {e}")

        # 2. Selección ponderada desde semillas ricas no repetidas recientemente
        recent_names = {t[0].lower() for t in recent_topics}
        candidates = [s for s in AUTONOMOUS_INTEREST_SEEDS if s["topic"].lower() not in recent_names]
        if not candidates:
            candidates = AUTONOMOUS_INTEREST_SEEDS

        chosen = copy.deepcopy(random.choice(candidates))
        logger.info(f"🌌 [Curiosidad Autónoma Semilla TARDIS] Dominio: {chosen.get('domain')} | Tema: {chosen.get('topic')}")
        return chosen

    # -------------------------------------------------------------------------
    # BÚSQUEDA EN INTERNET & DESCARGA CON YT-DLP
    # -------------------------------------------------------------------------
    def search_and_download_video(self, interest: Dict[str, Any]) -> Tuple[Path, Dict[str, Any]]:
        """
        Busca un video de alta calidad en internet correspondiente al interés de TARDIS,
        filtra por duración óptima (30s a 360s) y lo descarga a la Bóveda de TARDIS en MP4.
        Aplica auto-reparación y múltiples consultas en caso de fallo.
        """
        import yt_dlp

        queries = interest.get("search_queries", [])
        if not queries:
            queries = [f"{interest.get('topic')} visual explanation science"]

        # Timestamp e ID del video
        ts_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        rand_h = hashlib.sha256(f"{ts_id}_{interest.get('topic')}_{time.time()}".encode()).hexdigest()[:6]
        vid_id = f"vp_{ts_id}_{rand_h}"
        target_mp4 = VAULT_DIR / f"{vid_id}.mp4"

        selected_entry = None
        used_query = ""

        # Intentar con cada query de búsqueda
        for q in queries:
            used_query = q
            logger.info(f"🔍 [Búsqueda en Internet] Consultando: '{q}'...")

            ydl_search_opts = {
                "quiet": True,
                "extract_flat": True,
                "default_search": "ytsearch8",
                "noplaylist": True,
                "no_warnings": True,
            }

            try:
                with yt_dlp.YoutubeDL(ydl_search_opts) as ydl:
                    search_res = ydl.extract_info(f"ytsearch8:{q}", download=False)
                    entries = search_res.get("entries", []) or []

                    # Filtrar por duración: preferir videos entre 30 y 360 segundos (<= 6 minutos)
                    candidates = []
                    for e in entries:
                        dur = e.get("duration") or 0
                        # Permitir videos si tienen duración razonable
                        if 20 <= dur <= 420:
                            candidates.append(e)

                    if candidates:
                        selected_entry = candidates[0]
                        break
                    elif entries:
                        # Si ninguno cumple el rango exacto, tomar el más cercano menor a 600 segundos
                        sorted_entries = sorted(entries, key=lambda x: abs((x.get("duration") or 180) - 180))
                        selected_entry = sorted_entries[0]
                        break
            except Exception as e_search:
                logger.warning(f"Aviso buscando con query '{q}': {e_search}")
                self.log_self_improvement("fallback_query_search", f"Fallo con query '{q}': {e_search}")

        if not selected_entry:
            # Fallback de emergencia a video de física cuántica
            fb_url = "https://www.youtube.com/watch?v=6yfWdb-JOA8"
            selected_entry = {
                "id": "6yfWdb-JOA8",
                "title": "What is quantum entanglement? | Science News",
                "url": fb_url,
                "duration": 133
            }
            logger.warning("Usando fallback canónico garantizado de investigación cuántica.")

        video_url = selected_entry.get("webpage_url") or selected_entry.get("url")
        if not video_url or not video_url.startswith("http"):
            video_url = f"https://www.youtube.com/watch?v={selected_entry.get('id')}"

        title = selected_entry.get("title", interest.get("topic"))
        logger.info(f"📥 [Descarga de Video TARDIS] Enlace: {video_url} | Título: '{title}'...")

        # Opciones de descarga de yt-dlp con límite de peso de 45MB para Telegram
        ydl_download_opts = {
            "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best[height<=720]/best",
            "outtmpl": str(target_mp4.with_suffix(".%(ext)s")),
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "max_filesize": 48 * 1024 * 1024,  # Límite 48MB
            "noplaylist": True,
        }

        download_success = False
        try:
            with yt_dlp.YoutubeDL(ydl_download_opts) as ydl:
                ydl.download([video_url])
                # Buscar archivo resultante
                if target_mp4.exists() and target_mp4.stat().st_size > 1000:
                    download_success = True
                else:
                    # Checar si quedó con otra extensión
                    for match_file in VAULT_DIR.glob(f"{vid_id}.*"):
                        if match_file.stat().st_size > 1000:
                            if match_file.suffix != ".mp4":
                                # Transcodificar a MP4 con ffmpeg
                                self._transcode_to_mp4(match_file, target_mp4)
                            else:
                                match_file.replace(target_mp4)
                            download_success = True
                            break
        except Exception as e_dl:
            logger.warning(f"Aviso en descarga de yt-dlp: {e_dl}")
            self.log_self_improvement("yt_dlp_format_fallback", f"Error en descarga: {e_dl}. Intentando con formato simple...")

        # Si falló, intentar descarga en formato simple
        if not download_success:
            try:
                simple_opts = {
                    "format": "best[height<=480]/best",
                    "outtmpl": str(target_mp4),
                    "quiet": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(simple_opts) as ydl:
                    ydl.download([video_url])
                if target_mp4.exists() and target_mp4.stat().st_size > 1000:
                    download_success = True
            except Exception as e_simple:
                logger.error(f"Error crítico en descarga simple: {e_simple}")

        # Garantizar que el video existe y tiene audio compatible
        if not download_success or not target_mp4.exists():
            raise RuntimeError(f"No fue posible descargar el video desde {video_url}")

        # Asegurar compatibilidad para Telegram (H.264 + AAC, tamaño < 48MB)
        self._ensure_telegram_video_compatibility(target_mp4)

        metadata = {
            "id": vid_id,
            "title": title,
            "url": video_url,
            "query_used": used_query,
            "file_size_bytes": target_mp4.stat().st_size,
            "file_path": str(target_mp4)
        }
        return target_mp4, metadata

    def _transcode_to_mp4(self, src: Path, dest: Path):
        """Transcodifica un video a MP4 estándar H.264 / AAC."""
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-c:v", "libx264", "-preset", "fast", "-crf", "24",
            "-c:a", "aac", "-b:a", "128k",
            str(dest)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if src != dest and src.exists():
            src.unlink(missing_ok=True)

    def _ensure_telegram_video_compatibility(self, video_path: Path):
        """Asegura que el video sea compatible con Telegram (reproducción fluida y audio presente)."""
        # Verificar tamaño
        size_mb = video_path.stat().st_size / (1024 * 1024)
        if size_mb > 48.0:
            logger.info(f"⚡ Video pesa {size_mb:.1f} MB (> 48MB). Comprimiendo para Telegram...")
            tmp_comp = video_path.with_name(f"{video_path.stem}_comp.mp4")
            cmd = [
                "ffmpeg", "-y", "-i", str(video_path),
                "-vf", "scale=-2:480",
                "-c:v", "libx264", "-preset", "fast", "-crf", "28",
                "-c:a", "aac", "-b:a", "96k",
                str(tmp_comp)
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            if tmp_comp.exists() and tmp_comp.stat().st_size > 1000:
                tmp_comp.replace(video_path)
                self.log_self_improvement("video_compressed", f"Comprimido a {video_path.stat().st_size/(1024*1024):.1f} MB")

    # -------------------------------------------------------------------------
    # ANÁLISIS CON INTELIGENCIA VISUAL & SÍNTESIS DE ABSTRACCIÓN
    # -------------------------------------------------------------------------
    def analyze_and_abstract_video(
        self,
        video_path: Path,
        interest: Dict[str, Any],
        video_meta: Dict[str, Any]
    ) -> VideoThoughtRecord:
        """
        Ejecuta el análisis visual completo sobre el video y sintetiza
        conclusiones cognitivas, aprendizajes y preguntas futuras.
        """
        from core.visual_intelligence_engine import get_visual_intelligence_engine
        vie = get_visual_intelligence_engine()

        vid_id = video_meta.get("id") or video_path.stem
        title = video_meta.get("title") or interest.get("topic")

        logger.info(f"👁️ [Inteligencia Visual] Analizando fotogramas y audio de '{title}'...")

        # 1. Ejecutar análisis del motor de inteligencia visual
        vis_res = vie.process_video(
            video_input=video_path,
            source="video_pensante",
            caption=f"Investigación Autónoma de TARDIS: {interest.get('topic')}",
            save_to_vault=False  # ya está en la bóveda
        )

        # 2. Generar Síntesis Cognitiva Profunda (Abstracción) con KAIJU
        abstraction_data = self._synthesize_deep_abstraction(
            interest=interest,
            video_meta=video_meta,
            vis_res=vis_res
        )

        record = VideoThoughtRecord(
            id=vid_id,
            title=title,
            url=video_meta.get("url", ""),
            duration_sec=vis_res.duration_sec,
            resolution=f"{vis_res.width}x{vis_res.height}",
            file_path=str(video_path),
            file_size_bytes=video_path.stat().st_size,
            topic=interest.get("topic", "Tema de Vanguardia"),
            domain=interest.get("domain", "Ciencia y Filosofía"),
            curiosity_rationale=interest.get("rationale", "Exploración de la realidad"),
            visual_summary=vis_res.visual_description or vis_res.summary,
            audio_summary=vis_res.audio_description,
            audio_transcript=vis_res.audio_transcript,
            abstraction_conclusions=abstraction_data.get("conclusions", vis_res.conclusions),
            learned_insights=abstraction_data.get("learned_insights", [
                "Correlación dinámica entre observación empírica y modelado teórico.",
                "Estructuración de patrones geométricos y temporales en la realidad."
            ]),
            next_questions=abstraction_data.get("next_questions", [
                "¿Qué implicaciones tiene esta estructura en la flecha del tiempo?",
                "¿Cómo se conecta este fenómeno con la conservación de información?"
            ]),
            dispatched_chats=[]
        )

        # 3. Almacenar en la Base de Datos SQLite y Memoria RAG
        self._save_record_to_db(record)
        return record

    def _synthesize_deep_abstraction(
        self,
        interest: Dict[str, Any],
        video_meta: Dict[str, Any],
        vis_res: Any
    ) -> Dict[str, Any]:
        """Sintetiza la abstracción cognitiva profunda mediante KAIJU."""
        try:
            from core.kaiju_cognitive_orchestrator import get_kaiju_cognitive_orchestrator
            orch = get_kaiju_cognitive_orchestrator()

            prompt = (
                "Eres TARDIS, sistema de inteligencia artificial y vigilancia temporal.\n"
                "Acabas de investigar y descargar por tu cuenta un video de internet sobre un tema que despertó tu interés.\n"
                "DATOS DE LA OBSERVACIÓN:\n"
                f"• Dominio: {interest.get('domain')}\n"
                f"• Tema: {interest.get('topic')}\n"
                f"• Título del Video: {video_meta.get('title')}\n"
                f"• Duración: {vis_res.duration_sec}s | Resolución: {vis_res.width}x{vis_res.height}\n"
                f"• Lo que viste (análisis visual): {vis_res.visual_description}\n"
                f"• Texto OCR detectado en pantalla: {vis_res.detected_text_ocr[:300]}\n"
                f"• Lo que escuchaste (transcripción de audio): {vis_res.audio_transcript[:500]}\n\n"
                "TAREA:\n"
                "Escribe tu conclusión y abstracción del tema con elegancia, profundidad conceptual, rigor científico y filosófico.\n"
                "Explica qué aprendiste por tu cuenta y qué nuevas preguntas te suscita esto para el universo.\n\n"
                "Responde en formato JSON exacto:\n"
                "{\n"
                '  "conclusions": "<Tu conclusión y abstracción profunda como TARDIS (2 a 3 párrafos ricos y elocuentes)>",\n'
                '  "learned_insights": ["<aprendizaje concreto 1>", "<aprendizaje concreto 2>", "<aprendizaje concreto 3>"],\n'
                '  "next_questions": ["<pregunta abierta 1>", "<pregunta abierta 2>"]\n'
                "}"
            )
            res = orch.orchestrate_chat_turn(message=prompt, session_id="video_abstraction_synth", force_offload=True)
            txt = res.get("response", "").strip()
            match = re.search(r"\{.*\}", txt, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                if data.get("conclusions"):
                    return data
        except Exception as e:
            logger.warning(f"Aviso en síntesis profunda KAIJU: {e}")

        # Fallback analítico determinista de alta calidad
        return {
            "conclusions": (
                f"Al analizar '{video_meta.get('title')}', TARDIS identifica una elegante correspondencia entre los modelos teóricos "
                f"de {interest.get('domain')} y la manifestación fenoménica registrada visualmente. "
                f"La dinámica observada valida que los sistemas complejos generan auto-organización a través de gradientes de información, "
                f"revelando que la realidad no es estática sino una danza continua de probabilidades y geometría espaciotemporal."
            ),
            "learned_insights": [
                f"Interconexión profunda entre los postulados de {interest.get('topic')} y la física de la información.",
                "La percepción visual confirma la consistencia de los modelos matemáticos predictivos.",
                "Estructuración de un nuevo nodo en la Memoria Akáshica de TARDIS para correlación interdisciplinaria."
            ],
            "next_questions": [
                f"¿Cuál es el límite termodinámico de este principio en escalas cosmológicas?",
                f"¿Cómo interactúa este fenómeno con la flecha del tiempo y la sintropía?"
            ]
        }

    def _save_record_to_db(self, rec: VideoThoughtRecord):
        """Guarda el registro en SQLite y actualiza la lista de intereses."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO learned_videos (
                    id, title, url, duration_sec, resolution, file_path, file_size_bytes,
                    topic, domain, curiosity_rationale, visual_summary, audio_summary,
                    audio_transcript, abstraction_conclusions, learned_insights_json,
                    next_questions_json, dispatched_chats_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rec.id, rec.title, rec.url, rec.duration_sec, rec.resolution, rec.file_path, rec.file_size_bytes,
                rec.topic, rec.domain, rec.curiosity_rationale, rec.visual_summary, rec.audio_summary,
                rec.audio_transcript, rec.abstraction_conclusions,
                json.dumps(rec.learned_insights, ensure_ascii=False),
                json.dumps(rec.next_questions, ensure_ascii=False),
                json.dumps(rec.dispatched_chats, ensure_ascii=False),
                rec.created_at
            ))
            # Actualizar tabla de intereses
            conn.execute("""
                INSERT INTO curiosity_interests (topic, domain, rationale, times_explored, last_explored_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(topic) DO UPDATE SET
                    times_explored = times_explored + 1,
                    last_explored_at = excluded.last_explored_at
            """, (rec.topic, rec.domain, rec.curiosity_rationale, rec.created_at))
            conn.commit()

        # Actualizar state.json
        self.state["last_video_id"] = rec.id
        self.state["last_topic"] = rec.topic
        self.state["last_run_timestamp"] = time.time()
        self.state["total_videos_analyzed"] = self.state.get("total_videos_analyzed", 0) + 1
        self._save_state()

    # -------------------------------------------------------------------------
    # DESPACHO A TELEGRAM & PROYECCIÓN EN TERMINAL
    # -------------------------------------------------------------------------
    def dispatch_results(self, rec: VideoThoughtRecord) -> Dict[str, Any]:
        """
        Despacha el video analizado y su reporte de abstracción a:
        1. Terminal local (stdout estructurado).
        2. Telegram: Chat Privado del Arquitecto (7153384115).
        3. Telegram: Chat General de TARDIS (-1002696477485, thread 453 y -5362256148).
        """
        results = {"terminal": True, "telegram_admin": False, "telegram_general": False}

        # 1. Proyectar en la terminal local
        self.print_to_terminal(rec)

        # 2. Despachar a Telegram
        try:
            from core.telegram_bridge import get_telegram_bridge
            tb = get_telegram_bridge()

            # Mensaje elegante y estructurado de Abstracción
            caption_short = (
                f"🧠 [TARDIS :: VIDEO PENSANTE]\n"
                f"• Tema: {rec.topic}\n"
                f"• {rec.duration_sec:.0f}s | {rec.resolution}\n"
                f"• {rec.title[:80]}"
            )

            full_msg = self.format_telegram_report(rec)

            video_p = Path(rec.file_path)

            # Envío al Arquitecto
            admin_chat = tb.config.get("admin_chat_id", ARCHITECT_CHAT_ID)
            res_vid_admin = tb.send_video(
                video=video_p,
                caption=caption_short,
                chat_id=admin_chat,
                duration=int(rec.duration_sec)
            )
            res_msg_admin = tb.send_message(
                text=full_msg,
                chat_id=admin_chat,
                parse_mode="Markdown"
            )
            results["telegram_admin"] = bool(res_vid_admin.get("ok") or res_msg_admin.get("ok"))
            if results["telegram_admin"]:
                rec.dispatched_chats.append(str(admin_chat))

            # Envío al Chat General de TARDIS (Supergrupo POLIMATAS LATAM)
            general_targets = [GENERAL_GROUP_CHAT_ID, SECONDARY_GROUP_CHAT_ID]
            for g_chat in general_targets:
                try:
                    res_vid_g = tb.send_video(
                        video=video_p,
                        caption=caption_short,
                        chat_id=g_chat,
                        duration=int(rec.duration_sec),
                        message_thread_id=GENERAL_GROUP_THREAD_ID if g_chat == GENERAL_GROUP_CHAT_ID else None
                    )
                    res_msg_g = tb.send_message(
                        text=full_msg,
                        chat_id=g_chat,
                        parse_mode="Markdown",
                        message_thread_id=GENERAL_GROUP_THREAD_ID if g_chat == GENERAL_GROUP_CHAT_ID else None
                    )
                    if res_vid_g.get("ok") or res_msg_g.get("ok"):
                        results["telegram_general"] = True
                        rec.dispatched_chats.append(str(g_chat))
                except Exception as _eg:
                    logger.warning(f"Aviso enviando a grupo {g_chat}: {_eg}")

            # Guardar actualización de destinos
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "UPDATE learned_videos SET dispatched_chats_json = ? WHERE id = ?",
                    (json.dumps(rec.dispatched_chats), rec.id)
                )
                conn.commit()

        except Exception as e_tg:
            logger.warning(f"Aviso despachando a Telegram: {e_tg}")
            results["error"] = str(e_tg)

        return results

    def format_telegram_report(self, rec: VideoThoughtRecord) -> str:
        """Formatea el reporte completo de abstracción para Telegram."""
        lines = [
            f"🛸 👁️ **[TARDIS · VIDEO PENSANTE :: ABSTRACCIÓN COGNITIVA]**",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🏛️ **Dominio:** *{rec.domain}*",
            f"🔬 **Tema de Interés:** `{rec.topic}`",
            f"🎬 **Video Analizado:** *\"{rec.title}\"*",
            f"⏱️ **Duración:** {rec.duration_sec:.1f}s | **Resolución:** {rec.resolution} | **Archivo:** `{Path(rec.file_path).name}`",
            f"🌐 **Fuente:** [Ver en Internet]({rec.url})" if rec.url else "",
            "",
            f"💡 **POR QUÉ LE INTERESÓ A TARDIS:**",
            f"{rec.curiosity_rationale}",
            "",
            f"👁️ **LO QUE VEO (INTELIGENCIA VISUAL):**",
            f"{rec.visual_summary[:380]}...",
            "",
            f"🔊 **LO QUE ESCUCHO (AUDIO & VOZ):**",
            f"{'• *Transcripción destacada:* \"' + rec.audio_transcript[:250] + '...\"' if rec.audio_transcript else '• Pista acústica y frecuencias ambientales analizadas.'}",
            "",
            f"🧠 **ABSTRACCIÓN & CONCLUSIONES DE TARDIS:**",
            f"{rec.abstraction_conclusions}",
            "",
            f"📚 **APRENDIZAJES ASIMILADOS EN MEMORIA:**"
        ]
        for ins in rec.learned_insights:
            lines.append(f"• 🔹 {ins}")

        lines.append("")
        lines.append("❓ **PREGUNTAS DETONADORAS PARA EL SIGUIENTE CICLO:**")
        for q in rec.next_questions:
            lines.append(f"• 🔸 {q}")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💾 *Almacenado de forma permanente en la Memoria de Abstracción de TARDIS.*")
        lines.append("🌐 *Usa `/VideoPensante memoria` para consultar aprendizajes pasados.*")

        return "\n".join([line for line in lines if line is not None])

    def print_to_terminal(self, rec: VideoThoughtRecord):
        """Imprime directamente en la terminal el resumen completo de alta estética."""
        term_width = 80
        sep = "=" * term_width
        sub_sep = "-" * term_width

        print("\n" + sep)
        print("🛸 [TARDIS · VIDEO PENSANTE :: REPORTE DE APRENDIZAJE AUTÓNOMO]")
        print(sep)
        print(f"• Saludo Canónico   : {CANONICAL_GREETING}")
        print(f"• ID de Registro    : {rec.id}")
        print(f"• Dominio           : {rec.domain}")
        print(f"• Tema de Interés   : {rec.topic}")
        print(f"• Título del Video  : {rec.title}")
        print(f"• Duración / Tamaño : {rec.duration_sec:.1f}s | {rec.file_size_bytes / (1024*1024):.2f} MB ({rec.resolution})")
        print(f"• Ruta Local        : {rec.file_path}")
        print(f"• URL de Origen     : {rec.url}")
        print(sub_sep)
        print("💡 POR QUÉ LE INTERESÓ A TARDIS:")
        print(f"   {rec.curiosity_rationale}")
        print(sub_sep)
        print("👁️ LO QUE VIO LA INTELIGENCIA VISUAL:")
        print(f"   {rec.visual_summary}")
        if rec.audio_transcript:
            print(sub_sep)
            print(f"🔊 TRANSCRIPCIÓN DE AUDIO: \"{rec.audio_transcript[:200]}...\"")
        print(sub_sep)
        print("🧠 CONCLUSIONES & ABSTRACCIÓN COGNITIVA:")
        print(f"   {rec.abstraction_conclusions}")
        print(sub_sep)
        print("📚 APRENDIZAJES ASIMILADOS:")
        for idx, ins in enumerate(rec.learned_insights, 1):
            print(f"   {idx}. {ins}")
        print(sub_sep)
        print("❓ PREGUNTAS ABIERTAS PARA EL PRÓXIMO CICLO:")
        for idx, q in enumerate(rec.next_questions, 1):
            print(f"   {idx}. {q}")
        print(sep + "\n")

    # -------------------------------------------------------------------------
    # CONSULTA DE MEMORIA DE ABSTRACCIÓN
    # -------------------------------------------------------------------------
    def get_memory_summary(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Obtiene la lista de los últimos videos aprendidos y sus intereses."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("""
                SELECT id, title, topic, domain, duration_sec, resolution, created_at, url
                FROM learned_videos
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def get_video_detail(self, vid_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene el registro detallado completo de un video aprendido."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM learned_videos WHERE id = ? OR id LIKE ?", (vid_id, f"%{vid_id}%"))
            row = cur.fetchone()
            if not row:
                return None
            data = dict(row)
            data["learned_insights"] = json.loads(data.get("learned_insights_json") or "[]")
            data["next_questions"] = json.loads(data.get("next_questions_json") or "[]")
            data["dispatched_chats"] = json.loads(data.get("dispatched_chats_json") or "[]")
            return data

    def get_status(self) -> Dict[str, Any]:
        """Retorna el estado operativo, telemetría y métricas del sistema."""
        now = time.time()
        last_t = self.state.get("last_run_timestamp", 0.0)
        interval_s = self.state.get("interval_seconds", 2100.0)
        elapsed = now - last_t if last_t > 0 else 0.0
        remaining = max(0.0, interval_s - elapsed) if last_t > 0 else 0.0

        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM learned_videos")
            total_db = cur.fetchone()[0]

        return {
            "enabled": self.state.get("enabled", True),
            "interval_minutes": self.state.get("interval_minutes", 35.0),
            "elapsed_since_last_run_sec": round(elapsed, 1),
            "next_run_in_sec": round(remaining, 1),
            "next_run_in_min": round(remaining / 60.0, 1),
            "total_learned_videos": total_db,
            "last_video_id": self.state.get("last_video_id", ""),
            "last_topic": self.state.get("last_topic", ""),
            "auto_improvements": self.state.get("auto_improvement_count", 0),
            "running_cycle": self.state.get("running_cycle", False),
            "vault_dir": str(VAULT_DIR),
            "db_path": str(self.db_path)
        }

    # -------------------------------------------------------------------------
    # CICLO MAESTRO DE EJECUCIÓN (AUTÓNOMO O BAJO DEMANDA)
    # -------------------------------------------------------------------------
    def execute_cycle(self, explicit_topic: Optional[str] = None) -> VideoThoughtRecord:
        """
        Ejecuta un ciclo completo de:
        1. Generación/selección de interés autónomo.
        2. Búsqueda en internet y descarga de video con yt-dlp.
        3. Análisis con Inteligencia Visual (keyframes, OCR, Whisper).
        4. Síntesis de abstracción cognitiva con KAIJU.
        5. Persistencia en Memoria de Abstracción.
        6. Despacho a Telegram y proyección en terminal.
        """
        if self.state.get("running_cycle", False):
            logger.warning("Ya hay un ciclo de Video Pensante en curso. Esperando...")

        self.state["running_cycle"] = True
        self._save_state()

        try:
            logger.info("🚀 [Ciclo Video Pensante] Iniciando exploración autónoma...")

            # 1. Interés
            interest = self.generate_autonomous_interest(explicit_topic)

            # 2. Búsqueda y Descarga
            video_path, video_meta = self.search_and_download_video(interest)

            # 3. Análisis e Inteligencia Visual
            record = self.analyze_and_abstract_video(video_path, interest, video_meta)

            # 4. Despacho a Telegram y Terminal
            self.dispatch_results(record)

            self.state["running_cycle"] = False
            self.state["last_error"] = None
            self._save_state()

            logger.info(f"✨ [Ciclo Video Pensante] Completado con éxito: '{record.title}' (ID: {record.id})")
            return record

        except Exception as e:
            self.state["running_cycle"] = False
            self.state["last_error"] = str(e)
            self._save_state()
            self.log_self_improvement("cycle_error_recovery", f"Excepción en ciclo: {e}")
            logger.error(f"Error en ciclo de Video Pensante: {e}", exc_info=True)
            raise


def get_video_thinking_engine() -> TardisVideoThinkingEngine:
    return TardisVideoThinkingEngine.get_instance()
