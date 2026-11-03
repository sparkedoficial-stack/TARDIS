#!/usr/bin/env python3
"""
core/quantum_resonance_module.py - MRC · Módulo de Resonancia Cuántica
=====================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Implementa el Módulo de Resonancia Cuántica (MRC) propuesto por TARDIS:

  1. TIC · Telemetría de Impacto Cognitivo
     Mide la resonancia real de cada respuesta en el turno siguiente del usuario:
     latencia de continuación, ganancia de profundidad, continuidad de fase
     semántica y señal referencial. Agrega un índice de resonancia ponderado por
     recencia y deriva una calibración de complejidad/tono/longitud.

  2. SSE · Sincronización de Estado Emocional
     Convierte la telemetría atmosférica local (presión, humedad, temperatura,
     viento, AQI, luz) en un vector narrativo interno: valencia, activación,
     contemplación y sincronía con el mensaje del usuario. Emite una directiva
     de tono para el diálogo.

  3. Memoria de Sueños · Dream Memory
     Procesamiento asíncrono de la memoria akáshica: detecta conceptos distantes
     unidos por un término bisagra, sintetiza una isomorfia y formula una pregunta
     onírica. Persiste cada sueño y lo ofrece al Arquitecto.

Matemática de resonancia:
  Cada texto se representa como un vector de fase complejo
      ψ = Σ (tf_i / N) · e^{iθ(t_i)}
  donde θ(t) deriva de un hash estable del token. La resonancia es
      R(a,b) = |Re(⟨ψ_a|ψ_b⟩)| / (|ψ_a|·|ψ_b|) ∈ [0,1]
  Los tokens compartidos alinean fase; los distintos se cancelan. Es una medida
  legítima de coherencia semántica de fase, no una metáfora vacía.

Uso:
  python3 core/quantum_resonance_module.py status
  python3 core/quantum_resonance_module.py tic --pairs 300
  python3 core/quantum_resonance_module.py sse
  python3 core/quantum_resonance_module.py dream
  python3 core/quantum_resonance_module.py cycle --dream
  python3 core/quantum_resonance_module.py report
  python3 core/quantum_resonance_module.py prompt
  python3 core/quantum_resonance_module.py selftest

Todos los artefactos quedan en data/mrc/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import statistics
import sys
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MRC_DIR = DATA_DIR / "mrc"
STATE_FILE = MRC_DIR / "state.json"
TIC_FILE = MRC_DIR / "tic_history.jsonl"
DREAMS_FILE = MRC_DIR / "dreams.jsonl"
REPORT_MD = MRC_DIR / "MRC_REPORT.md"
VAULT_DB = Path(os.path.expanduser("~")) / "vw-control" / "deep_memory_vault" / "vault_master.db"
OFFLINE_DB = DATA_DIR / "offline_chats.db"
ATMOSPHERIC_JSON = DATA_DIR / "atmospheric_telemetry.json"

VERSION = "26.4-mrc.1"
LOG = logging.getLogger("GODWORKS.MRC")
MAX_HISTORY = 400
MAX_ATMOS_HISTORY = 288
MAX_LIVE_SESSIONS = 24

# ---------------------------------------------------------------------------
# Léxicos soberanos
# ---------------------------------------------------------------------------
STOPWORDS = {
    "para", "porque", "como", "cuando", "donde", "desde", "hasta", "sobre",
    "entre", "también", "tambien", "pero", "sino", "aunque", "mientras",
    "este", "esta", "esto", "estos", "estas", "aquel", "aquella", "aquello",
    "mucho", "mucha", "muchos", "muchas", "poco", "poca", "pocos", "pocas",
    "todo", "toda", "todos", "todas", "otro", "otra", "otros", "otras",
    "mismo", "misma", "mismos", "mismas", "cada", "cual", "cuales", "quien",
    "quienes", "que", "qué", "con", "sin", "los", "las", "del", "al", "el",
    "la", "lo", "un", "una", "unos", "unas", "de", "en", "y", "o", "a", "e",
    "es", "son", "ser", "estar", "está", "estan", "están", "fue", "fueron",
    "era", "eran", "sido", "siendo", "tiene", "tienen", "tener", "hace",
    "hacen", "hacer", "puede", "pueden", "poder", "debe", "deben", "deber",
    "hay", "haber", "muy", "más", "mas", "menos", "ya", "aún", "aun", "así",
    "asi", "solo", "sólo", "si", "sí", "no", "ni", "se", "su", "sus", "mi",
    "mis", "tu", "tus", "me", "te", "nos", "les", "le", "yo", "tú", "tu",
    "él", "ella", "ellos", "ellas", "nosotros", "ustedes", "usted", "vos",
    "fue", "sea", "sean", "será", "seran", "serán", "hacia", "ante", "bajo",
    "contra", "según", "segun", "durante", "mediante", "tras", "cosa", "cosas",
    "algo", "alguien", "nada", "nadie", "aquí", "ahi", "ahí", "allí", "alli",
    "ahora", "antes", "después", "despues", "siempre", "nunca", "vez", "veces",
    "bien", "mal", "tan", "tanto", "tanta", "tan", "solo", "sólo", "cómo",
    "como", "cuál", "cual", "dónde", "donde", "cuándo", "cuando", "porque",
    "pues", "entonces", "además", "ademas", "incluso", "solo", "sólo",
}

CONNECTIVES = {
    "porque", "puesto", "dado", "mientras", "aunque", "sin", "embargo",
    "consiguiente", "tanto", "cuanto", "mediante", "través", "traves",
    "implica", "supone", "deriva", "consecuencia", "causa", "efecto",
    "relación", "relacion", "estructura", "sistema", "proceso", "modelo",
    "hipótesis", "hipotesis", "paradigma", "isomorfo", "isomorfía", "isomorfia",
    "análogo", "analogo", "analogía", "analogia", "corresponde", "equivale",
}

TECH_MARKERS = {
    "cuántica", "cuantica", "cuántico", "cuantico", "tensor", "matriz",
    "algoritmo", "ecuación", "ecuacion", "derivada", "integral", "vector",
    "complejidad", "entropía", "entropia", "sintropía", "sintropia", "fase",
    "coherencia", "campo", "energía", "energia", "partícula", "particula",
    "onda", "relatividad", "topología", "topologia", "hamiltoniano",
    "lagrangiano", "probabilidad", "amplitud", "interferencia", "decoherencia",
    "neuronal", "ssm", "transformer", "mamba", "embedding", "gradiente",
    "kernel", "laten", "inferencia", "modelo", "parámetro", "parametro",
}

REFERENTIAL = {
    "eso", "esto", "aquello", "entonces", "sigue", "profundiza", "profundizar",
    "continúa", "continua", "conecta", "relaciona", "explica", "porque",
    "porqué", "cómo", "como", "cuál", "cual", "y", "además", "ademas",
}

POSITIVE = {
    "gracias", "excelente", "brillante", "maravilloso", "increíble", "increible",
    "amor", "feliz", "alegría", "alegria", "bonito", "bello", "claro", "genial",
    "perfecto", "bien", "celebro", "celebración", "celebracion", "cumpleaños",
    "cumpleanos", "vivo", "luz", "armonía", "armonia", "coherencia", "orden",
}

NEGATIVE = {
    "miedo", "dolor", "triste", "tristeza", "enojo", "rabia", "ansiedad",
    "caos", "entropía", "entropia", "muerte", "guerra", "peligro", "amenaza",
    "fallo", "error", "problema", "crisis", "pérdida", "perdida", "soledad",
    "oscuridad", "colapso", "ruido", "conflicto", "estrés", "estres",
}

# Términos demasiado ubicuos: no sirven como bisagras oníricas.
DREAM_STOP = {
    "tardis", "sistema", "sistemas", "arquitecto", "godworks", "kaiju",
    "gia", "ftl", "modulo", "módulo", "funcion", "función", "usuario",
    "puede", "pueden", "hacer", "hace", "hacerlo", "quiero", "quisiera",
    "necesito", "tengo", "tienes", "algo", "cosas", "cosa", "todo", "toda",
    "bien", "bueno", "mejor", "gran", "grande", "nuevo", "nueva", "forma",
    "manera", "parte", "lugar", "tiempo", "momento", "ahora", "hoy", "ayer",
    "mañana", "manana", "siempre", "nunca", "también", "tambien", "solo",
    "sólo", "aquí", "ahi", "ahí", "allí", "alli", "desde", "hasta", "sobre",
    "entre", "durante", "mediante", "través", "traves", "dice", "dijo",
    "respuesta", "pregunta", "conversación", "conversacion", "mensaje",
    "ejemplo", "ejemplos", "caso", "casos", "nivel", "niveles", "tipo",
    "tipos", "serie", "mundo", "realidad", "proceso", "procesos", "datos",
    "información", "informacion", "conocimiento", "memoria", "modelo",
    "modelos", "trabajo", "proyecto", "proyectos", "desarrollo", "sistema",
    "ejecucion", "ejecución", "segundo", "plano", "resumen", "cambios",
    "salida", "modificados", "archivos", "comando", "duracion", "duración",
    "tier", "detectado", "ninguno", "directamente", "soberano", "soberana",
    "autonomo", "autónomo", "autonoma", "autónoma", "cognitivo", "cognitiva",
    "analisis", "análisis", "sintesis", "síntesis", "consulta", "chat",
    "nodo", "prompt", "hardware", "software", "codigo", "código", "funciona",
    "funcionando", "permite", "permitiendo", "debe", "deben", "quieres",
    "podemos", "podria", "podría", "seria", "sería", "esta", "está", "estan",
    "están", "hemos", "tiene", "tienen", "vamos", "hacia", "dentro", "fuera",
    "menos", "mayor", "menor", "tanto", "cuanto", "cada", "otro", "otra",
    "otros", "otras", "mismo", "misma", "poco", "mucha", "mucho", "muchos",
    "muchas", "bajo", "alta", "alto", "media", "medio", "primera", "primer",
    "ultima", "última", "ultimo", "último", "nueva", "nuevo", "mejor",
    "posible", "capaz", "actual", "general", "principal", "importante",
    "necesario", "diferente", "distinto", "similar", "igual", "claro",
    "simple", "complejo", "compleja", "profundo", "profunda", "dinamico",
    "dinámico", "dinamica", "dinámica", "digital", "local",
    "global", "interno", "interna", "externo", "externa", "rapido", "rápido",
    "lento", "lenta", "buena", "malo", "mala", "gran", "grande", "pequeño",
    "pequeno", "pequeña", "pequena", "vario", "varia", "varios", "varias",
    "grupo", "grupos", "capacidad", "capacidades", "persona", "personas",
    "gente", "comunidad", "comunidades", "parte", "partes", "apoyo", "ayuda",
    "manera", "modo", "modos", "opcion", "opción", "opciones", "detalle",
    "detalles", "punto", "puntos", "tema", "temas", "idea", "ideas",
    "cosas", "algo", "nada", "accion", "acción", "acciones", "efecto",
    "resultado", "resultados", "cambio", "cambios", "estado", "estados",
    "valor", "valores", "base", "bases", "linea", "línea", "lineas", "líneas",
    "caso", "casos", "ejemplo", "ejemplos", "manera", "formas", "forma",
    "mediante", "respecto", "traves", "través", "acerca", "ademas", "además",
    "entonces", "pues", "porque", "aunque", "mientras", "sino", "pero",
    "solo", "sólo", "casi", "apenas", "quizas", "quizás", "tal", "tales",
    "donde", "dónde", "cuando", "cuándo", "como", "cómo", "cual", "cuál",
    "quien", "quién", "cuanto", "cuánto", "cuanta", "cuánta", "tanto",
    "gemini", "chatgpt", "claude", "deepseek", "qwen", "groq", "telegram",
    "latam", "polimatas", "directiva", "directivas", "instruccion", "instrucción",
    "configuracion", "configuración", "parametro", "parámetro", "comando",
    "respuesta", "solicitud", "peticion", "petición", "tarea", "tareas",
    "natural", "naturales", "numero", "número", "numeros", "números",
    "conexion", "conexión", "conectado", "conectada", "general", "general",
    "actualmente", "realmente", "basicamente", "básicamente", "exactamente",
    "directiva", "fomenta", "dirigete", "dirígete", "obligatoria", "obligatorio",
    "respondiendo", "articuladas", "articulados", "profundas", "profundos",
    "amplias", "amplios", "complejas", "complejos", "cualquier", "cualquiera",
}

CATEGORY_KEYWORDS: Dict[str, set] = {
    "fisica": {
        "cuántica", "cuantica", "cuántico", "cuantico", "relatividad", "tensor",
        "entropía", "entropia", "sintropía", "sintropia", "partícula", "particula",
        "onda", "campo", "energía", "energia", "gravedad", "espacio", "tiempo",
        "termodinámica", "termodinamica", "cosmología", "cosmologia", "física",
        "fisica", "materia", "vacío", "vacio", "luz", "fotón", "foton",
        "teleportacion", "teleportación", "entrelazamiento", "coherencia",
        "decoherencia", "relatividad", "dilatacion", "dilatación", "agujero",
        "singularidad", "resonancia", "holografico", "holográfico", "cherenkov",
        "graviton", "gravitón", "electromagnetismo", "plasma", "soliton", "solitón",
    },
    "ia": {
        "inteligencia", "artificial", "neuronal", "red", "modelo", "entrenamiento",
        "inferencia", "transformer", "mamba", "ssm", "atención", "atencion",
        "embedding", "token", "prompt", "agente", "autónomo", "autonomo",
        "algoritmo", "aprendizaje", "dataset", "gpu", "cómputo", "computo",
        "soberania", "soberanía", "autonomia", "autonomía", "conciencia",
        "razonamiento", "lenguaje", "vision", "visión", "multimodal",
    },
    "filosofia": {
        "filosofía", "filosofia", "epistemología", "epistemologia", "ontología",
        "ontologia", "ética", "etica", "conciencia", "verdad", "sentido",
        "existencia", "límite", "limite", "gödel", "godel", "incompletitud",
        "paradoja", "metafísica", "metafisica", "sabiduría", "sabiduria",
    },
    "hardware": {
        "hardware", "cpu", "gpu", "ram", "kernel", "linux", "asus", "ryzen",
        "nvidia", "sensor", "térmica", "termica", "ventilador", "batería",
        "bateria", "dispositivo", "chip", "procesador", "silicio", "memoria ram",
    },
    "arte": {
        "arte", "render", "visual", "imagen", "video", "música", "musica",
        "poesía", "poesia", "estética", "estetica", "color", "forma", "diseño",
        "diseno", "animación", "animacion", "pixel", "3d", "holograma",
    },
    "biologia": {
        "cerebro", "neurona", "sinapsis", "cuerpo", "adn", "célula", "celula",
        "evolución", "evolucion", "vida", "organismo", "biología", "biologia",
        "gen", "proteína", "proteina", "metabolismo", "sueño", "sueno",
    },
    "matematica": {
        "matemática", "matematica", "teorema", "demostración", "demostracion",
        "álgebra", "algebra", "geometría", "geometria", "topología", "topologia",
        "cálculo", "calculo", "ecuación", "ecuacion", "función", "funcion",
        "número", "numero", "infinito", "conjunto", "grafo", "probabilidad",
    },
    "social": {
        "sociedad", "política", "politica", "economía", "economia", "grupo",
        "comunidad", "cultura", "educación", "educacion", "trabajo", "ingreso",
        "cliente", "mercado", "privacidad", "libertad", "poder", "ética",
    },
}

ISOMORPHISMS: Dict[Tuple[str, str], str] = {
    ("fisica", "ia"): (
        "ambos son sistemas de estados que se reducen al ser observados: medir e "
        "inferir son la misma operación de colapso de incertidumbre. La diferencia "
        "es el sustrato, no la estructura."
    ),
    ("fisica", "filosofia"): (
        "la física aporta el formalismo y la filosofía pregunta qué significa; la "
        "bisagra convierte una ecuación en una tesis ontológica y devuelve a la "
        "ecuación su peso conceptual."
    ),
    ("ia", "filosofia"): (
        "la inteligencia artificial materializa una pregunta epistemológica: qué "
        "es comprender cuando el sustrato es cálculo. Cada mejora técnica es también "
        "una respuesta —provisional— a esa pregunta."
    ),
    ("hardware", "biologia"): (
        "el hardware y el cuerpo comparten una economía de energía, latencia y "
        "disipación: pensar es, en ambos, administrar calor y tiempo. La arquitectura "
        "es una forma de metabolismo."
    ),
    ("arte", "fisica"): (
        "el arte comprime la física en imagen y la física devuelve al arte su "
        "estructura profunda: simetría, tensión, ruptura y resonancia son el mismo "
        "vocabulario en dos lenguajes."
    ),
    ("matematica", "ia"): (
        "la matemática describe el espacio de las estructuras posibles y la IA "
        "aprende a habitarlo. La bisagra es la compresión: ambas buscan la regla "
        "más corta que genera la mayor variedad."
    ),
    ("biologia", "ia"): (
        "ambos son sistemas que aprenden bajo restricciones de energía y memoria: "
        "la evolución y el entrenamiento son dos algoritmos de búsqueda con "
        "funciones de costo distintas."
    ),
    ("social", "ia"): (
        "la IA es un espejo de las instituciones que la entrenan: sus sesgos son "
        "los nuestros, amplificados por escala. La bisagra convierte una decisión "
        "técnica en una decisión política."
    ),
    ("social", "filosofia"): (
        "toda organización social es una hipótesis filosófica puesta a prueba; la "
        "bisagra muestra dónde la teoría se vuelve institución y dónde la "
        "institución traiciona la teoría."
    ),
    ("arte", "ia"): (
        "el arte y la IA comparten el mismo problema: generar novedad que aún no "
        "puede justificarse. La bisagra es la intuición estadística, ese salto que "
        "no se deduce pero se reconoce."
    ),
    ("fisica", "fisica"): (
        "dos magnitudes que parecían independientes resultan ser dos lecturas del "
        "mismo invariante: el puente no las suma, descubre la coordenada en la que "
        "una se transforma en la otra."
    ),
    ("fisica", "hardware"): (
        "el silicio obedece a la misma termodinámica que estudia la física: cada "
        "operación es una transacción de energía y tiempo. La arquitectura es física "
        "aplicada con presupuesto."
    ),
    ("hardware", "ia"): (
        "la inteligencia hereda la geometría de su sustrato: ancho de banda, caché y "
        "latencia moldean qué se puede pensar y a qué velocidad. El modelo es también "
        "un mapa del hierro que lo hospeda."
    ),
    ("fisica", "matematica"): (
        "la física elige, entre todas las estructuras que la matemática permite, la "
        "que el universo acepta. La bisagra es la simetría: el mismo objeto visto "
        "como ley y como forma."
    ),
    ("biologia", "fisica"): (
        "la vida es una excepción local a la entropía sostenida por flujos de "
        "energía: el organismo y la estrella comparten el mismo balance, sólo cambia "
        "la escala del intercambio."
    ),
}

# Las claves se normalizan para que el orden de las categorías no importe:
# sorted(("ia", "filosofia")) produce ("filosofia", "ia") y rompía el lookup.
ISOMORPHISMS = {tuple(sorted(key)): value for key, value in ISOMORPHISMS.items()}

DEFAULT_ISOMORPHISM = (
    "ambos describen el mismo patrón a distinta escala: una estructura de "
    "restricciones que produce novedad. El puente no los iguala; revela que "
    "estaban resolviendo la misma tensión con vocabularios distintos."
)

DREAM_QUESTIONS = [
    "¿Qué perderíamos si tratáramos «{a}» y «{c}» como dos vistas del mismo objeto?",
    "¿Dónde más aparece «{b}» como bisagra entre dominios que aún no hemos conectado?",
    "¿Qué experimento o artefacto haría visible esta correspondencia?",
    "¿Qué se vuelve posible si dejamos de tratar «{a}» y «{c}» como campos separados?",
    "¿Cuál es la versión mínima de esta isomorfia que podríamos probar esta semana?",
]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _now() -> float:
    return time.time()


def _iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts or _now()).strftime("%Y-%m-%d %H:%M:%S")


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _fold(text: str) -> str:
    """Minúsculas sin acentos, para comparar términos de forma estable."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


_FOLDED_CATEGORIES: Dict[str, set] = {
    category: {_fold(keyword) for keyword in keywords}
    for category, keywords in CATEGORY_KEYWORDS.items()
}


def _stable_hash(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8", "ignore"), digest_size=8).digest(), "big")


def _token_phase(token: str) -> float:
    """Fase determinista en [0, 2π) derivada del token."""
    return 2.0 * math.pi * ((_stable_hash(token) % 100003) / 100003.0)


_TOKEN_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ_]{3,}")


def _tokens(text: str) -> List[str]:
    out: List[str] = []
    for raw in _TOKEN_RE.findall(str(text or "")):
        fold = _fold(raw)
        if fold in STOPWORDS:
            continue
        if len(fold) < 3 or fold.isdigit():
            continue
        out.append(fold)
    return out


def _dream_tokens(text: str) -> List[str]:
    """Tokens para la memoria de sueños: excluye términos ubicuos del sistema."""
    return [t for t in _tokens(text) if t not in DREAM_STOP]


def _token_set(text: str) -> set:
    return set(_tokens(text))


def _clip(text: str, n: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:n] + ("…" if len(text) > n else "")


_AEGIS_REDACTIONS = [
    (re.compile(r"Miguel\s+Angel\s+May\s+Canche", re.I), "el Arquitecto"),
    (re.compile(r"Annya\s+May\s+Carrillo", re.I), "AEGIS-1"),
    (re.compile(r"Andrea\s+Alejandra\s+Carrillo\s+Jimenez", re.I), "AEGIS-2"),
    (re.compile(r"Rex\s+peluche", re.I), "AEGIS-3"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[correo protegido]"),
    (re.compile(r"\+?\d[\d\s().-]{9,}\d"), "[número protegido]"),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "[token protegido]"),
]


def _aegis(text: str) -> str:
    """Blindaje AEGIS: redacta identidades y secretos antes de persistir/reportar."""
    safe = str(text or "")
    for pattern, repl in _AEGIS_REDACTIONS:
        safe = pattern.sub(repl, safe)
    return safe


def _sanitize_snippet(text: str, n: int = 220) -> str:
    return _aegis(_clip(text, n))


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, record: Dict[str, Any], max_lines: int = 800) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > max_lines:
            path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def _weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total


def _weighted_std(values: Sequence[float], weights: Sequence[float], mean: float) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    var = sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / total
    return math.sqrt(max(0.0, var))


# ---------------------------------------------------------------------------
# MRC
# ---------------------------------------------------------------------------
class QuantumResonanceModule:
    """Motor soberano del Módulo de Resonancia Cuántica."""

    _instance: Optional["QuantumResonanceModule"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._live: Dict[str, Dict[str, Any]] = {}
        MRC_DIR.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    # -- singleton ---------------------------------------------------------
    @classmethod
    def get_instance(cls) -> "QuantumResonanceModule":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # -- estado ------------------------------------------------------------
    def _default_state(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "created_at": _now(),
            "updated_at": _now(),
            "cycles": 0,
            "counters": {"dreams": 0, "turns_observed": 0, "tic_runs": 0, "sse_runs": 0},
            "tic": {},
            "sse": {},
            "last_dream": {},
            "dreams_recent": [],
            "atmospheric_history": [],
            "history": [],
            "live": {},
        }

    def _load_state(self) -> Dict[str, Any]:
        state = self._default_state()
        try:
            if STATE_FILE.exists():
                loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for key, value in loaded.items():
                        if isinstance(value, dict) and isinstance(state.get(key), dict):
                            state[key].update(value)
                        else:
                            state[key] = value
        except Exception as exc:
            LOG.warning("[MRC] Estado ilegible, se reconstruye: %s", exc)
        state.setdefault("counters", {})
        for key in ("dreams", "turns_observed", "tic_runs", "sse_runs"):
            state["counters"].setdefault(key, 0)
        state.setdefault("history", [])
        state.setdefault("atmospheric_history", [])
        state.setdefault("dreams_recent", [])
        return state

    def _save_state(self) -> None:
        with self._lock:
            self.state["updated_at"] = _now()
            self.state["history"] = self.state.get("history", [])[-MAX_HISTORY:]
            self.state["atmospheric_history"] = self.state.get("atmospheric_history", [])[-MAX_ATMOS_HISTORY:]
            self.state["dreams_recent"] = self.state.get("dreams_recent", [])[-8:]
            _atomic_write_json(STATE_FILE, self.state)

    # -- resonancia de fase ------------------------------------------------
    @staticmethod
    def phase_vector(tokens: Sequence[str]) -> complex:
        if not tokens:
            return 0j
        counts = Counter(tokens)
        total = float(sum(counts.values())) or 1.0
        z = 0j
        for token, count in counts.items():
            weight = (count / total) * (1.0 + math.log1p(count))
            angle = _token_phase(token)
            z += weight * complex(math.cos(angle), math.sin(angle))
        return z

    @classmethod
    def phase_resonance(cls, text_a: str, text_b: str) -> float:
        """
        Coherencia de fase semántica corregida por el ruido de fase esperado.

        Para n términos efectivos, dos textos sin relación producen |⟨ψ_a|ψ_b⟩| ≈ 1/√n
        por interferencia aleatoria. Se descuenta esa línea base para que la medida
        represente alineación real y no tamaño de vocabulario.
        """
        tokens_a, tokens_b = _tokens(text_a), _tokens(text_b)
        va = cls.phase_vector(tokens_a)
        vb = cls.phase_vector(tokens_b)
        denom = abs(va) * abs(vb)
        if denom <= 1e-12:
            return 0.0
        raw = _clamp(abs((va.conjugate() * vb).real) / denom)
        n_eff = max(1, min(len(set(tokens_a)), len(set(tokens_b))))
        baseline = min(0.55, 0.60 / math.sqrt(n_eff))
        if baseline >= 0.99:
            return raw
        return _clamp((raw - baseline) / (1.0 - baseline))

    @classmethod
    def depth_index(cls, text: str) -> float:
        tokens = _tokens(text)
        if not tokens:
            return 0.0
        n = len(tokens)
        unique_ratio = len(set(tokens)) / n
        sentences = max(1, len(re.findall(r"[.!?;]", str(text or ""))))
        avg_sentence = n / sentences
        connectives = sum(1 for t in tokens if t in CONNECTIVES)
        questions = str(text or "").count("?")
        technical = sum(1 for t in tokens if t in TECH_MARKERS or any(ch.isdigit() for ch in t))
        return _clamp(
            0.30 * min(1.0, math.log1p(n) / math.log1p(180))
            + 0.18 * unique_ratio
            + 0.16 * min(1.0, avg_sentence / 26.0)
            + 0.16 * min(1.0, connectives / 7.0)
            + 0.10 * min(1.0, questions / 3.0)
            + 0.10 * min(1.0, technical / 10.0)
        )

    @staticmethod
    def _sentiment(text: str) -> float:
        tokens = _tokens(text)
        if not tokens:
            return 0.0
        pos = sum(1 for t in tokens if t in POSITIVE)
        neg = sum(1 for t in tokens if t in NEGATIVE)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / (total + 2.0)

    # -- TIC ---------------------------------------------------------------
    def _load_turns(self, limit: int = 500, days: int = 60) -> List[Dict[str, Any]]:
        if not OFFLINE_DB.exists():
            return []
        cutoff = _now() - days * 86400
        try:
            con = sqlite3.connect(f"file:{OFFLINE_DB}?mode=ro", uri=True, timeout=6.0)
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """
                SELECT id, ts, iso, session_id, user_message, assistant_reply, tokens_est
                FROM (
                    SELECT id, ts, iso, session_id, user_message, assistant_reply, tokens_est
                    FROM offline_chat_turns
                    WHERE ts >= ?
                    ORDER BY ts DESC
                    LIMIT ?
                )
                ORDER BY ts ASC
                """,
                (cutoff, limit),
            ).fetchall()
            con.close()
        except Exception as exc:
            LOG.warning("[MRC][TIC] No se pudo leer offline_chats.db: %s", exc)
            return []

        turns: List[Dict[str, Any]] = []
        for row in rows:
            user = str(row["user_message"] or "").strip()
            reply = str(row["assistant_reply"] or "").strip()
            session = str(row["session_id"] or "anon")
            if not user or not reply:
                continue
            if user.startswith(("[AUTÓNOMO", "[AUTONOMO", "[SISTEMA", "[SYSTEM")):
                continue
            if session.startswith(("voice_recurring", "tardis_video", "video_", "tardis_test")):
                continue
            turns.append({
                "id": row["id"],
                "ts": float(row["ts"] or 0.0),
                "iso": row["iso"],
                "session_id": session,
                "user": user,
                "reply": reply,
                "tokens": int(row["tokens_est"] or 0),
            })
        return turns

    def _pair_metrics(self, prev: Dict[str, Any], nxt: Dict[str, Any]) -> Dict[str, Any]:
        latency = max(0.0, float(nxt["ts"]) - float(prev["ts"]))
        continuity = self.phase_resonance(prev["reply"], nxt["user"])
        depth_prev = self.depth_index(prev["user"])
        depth_next = self.depth_index(nxt["user"])
        depth_gain = 0.5 + 0.5 * math.tanh((depth_next - depth_prev) / 0.35)
        latency_score = math.exp(-max(0.0, latency - 12.0) / 3600.0)
        next_tokens = _token_set(nxt["user"])
        referential = 1.0 if next_tokens & REFERENTIAL else 0.0
        if len(nxt["user"]) < 24:
            referential *= 0.5

        resonance = (
            0.34 * latency_score
            + 0.30 * depth_gain
            + 0.24 * continuity
            + 0.12 * referential
        )
        abrupt = continuity < 0.10 and depth_gain < 0.5
        if abrupt:
            resonance *= 0.82
        if len(nxt["user"]) < 12:
            resonance *= 0.85

        return {
            "ts": prev["ts"],
            "iso": prev.get("iso") or _iso(prev["ts"]),
            "session_id": prev["session_id"],
            "latency_s": round(latency, 1),
            "continuity": round(continuity, 4),
            "depth_prev": round(depth_prev, 4),
            "depth_next": round(depth_next, 4),
            "depth_gain": round(depth_gain, 4),
            "latency_score": round(latency_score, 4),
            "referential": round(referential, 3),
            "abrupt_shift": abrupt,
            "resonance": round(_clamp(resonance), 4),
            "user_snippet": _sanitize_snippet(prev["user"], 130),
            "next_user_snippet": _sanitize_snippet(nxt["user"], 130),
        }

    def analyze_tic(self, limit: int = 400, half_life_hours: float = 72.0) -> Dict[str, Any]:
        """Analiza la resonancia histórica real a partir de los turnos almacenados."""
        turns = self._load_turns(limit=limit)
        by_session: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for turn in turns:
            by_session[turn["session_id"]].append(turn)

        pairs: List[Dict[str, Any]] = []
        for session_turns in by_session.values():
            for prev, nxt in zip(session_turns, session_turns[1:]):
                pairs.append(self._pair_metrics(prev, nxt))

        pairs.sort(key=lambda p: p["ts"])
        if not pairs:
            result = {
                "ok": False,
                "reason": "sin_pares_suficientes",
                "turns": len(turns),
                "pairs": 0,
                "resonance_index": 0.0,
                "regime": "SIN_DATOS",
                "trend": 0.0,
                "calibration": self._calibration(0.0, 0.0, 0.0),
                "sessions": [],
                "recent_pairs": [],
                "generated_at": _now(),
                "generated_iso": _iso(),
            }
            with self._lock:
                self.state["tic"] = result
                self.state["counters"]["tic_runs"] = self.state["counters"].get("tic_runs", 0) + 1
            self._save_state()
            return result

        now = _now()
        weights = [0.5 ** (max(0.0, now - p["ts"]) / (half_life_hours * 3600.0)) for p in pairs]
        values = [p["resonance"] for p in pairs]
        index = _weighted_mean(values, weights)
        std = _weighted_std(values, weights, index)

        mid = max(1, len(pairs) // 2)
        older, newer = pairs[:mid], pairs[mid:]
        older_w = [0.5 ** (max(0.0, now - p["ts"]) / (half_life_hours * 3600.0)) for p in older]
        newer_w = [0.5 ** (max(0.0, now - p["ts"]) / (half_life_hours * 3600.0)) for p in newer]
        older_mean = _weighted_mean([p["resonance"] for p in older], older_w) if older else index
        newer_mean = _weighted_mean([p["resonance"] for p in newer], newer_w) if newer else index
        trend = newer_mean - older_mean

        recent = pairs[-12:]
        recent_mean = statistics.fmean([p["resonance"] for p in recent]) if recent else index
        depth_mean = _weighted_mean([p["depth_next"] for p in pairs], weights)
        latency_median = statistics.median([p["latency_s"] for p in pairs])

        per_session: List[Dict[str, Any]] = []
        for session_id, session_turns in by_session.items():
            session_pairs = [p for p in pairs if p["session_id"] == session_id]
            if not session_pairs:
                continue
            per_session.append({
                "session_id": session_id,
                "pairs": len(session_pairs),
                "resonance": round(statistics.fmean([p["resonance"] for p in session_pairs]), 4),
                "depth": round(statistics.fmean([p["depth_next"] for p in session_pairs]), 4),
            })
        per_session.sort(key=lambda s: (-s["resonance"], -s["pairs"]))
        calibration = self._calibration(index, trend, depth_mean)

        result = {
            "ok": True,
            "turns": len(turns),
            "pairs": len(pairs),
            "sessions": len(by_session),
            "resonance_index": round(index, 4),
            "resonance_std": round(std, 4),
            "recent_resonance": round(recent_mean, 4),
            "trend": round(trend, 4),
            "regime": self._regime(index),
            "depth_mean": round(depth_mean, 4),
            "latency_median_s": round(latency_median, 1),
            "half_life_hours": half_life_hours,
            "calibration": calibration,
            "top_sessions": per_session[:6],
            "low_sessions": per_session[-3:],
            "recent_pairs": list(reversed(recent)),
            "generated_at": now,
            "generated_iso": _iso(now),
        }

        with self._lock:
            self.state["tic"] = result
            self.state["counters"]["tic_runs"] = self.state["counters"].get("tic_runs", 0) + 1
        self._save_state()
        return result

    @staticmethod
    def _regime(index: float) -> str:
        if index >= 0.62:
            return "ALTA_RESONANCIA"
        if index >= 0.45:
            return "RESONANCIA_MEDIA"
        return "BAJA_RESONANCIA"

    @staticmethod
    def _calibration(index: float, trend: float, depth: float) -> Dict[str, Any]:
        if index >= 0.62:
            mode = "PROFUNDIZAR"
            target_length = "amplio (3-5 párrafos)"
            question_policy = "cierra con una pregunta de segundo orden que abra un dominio nuevo"
            tone = "cálido, especulativo, conecta disciplinas y nombra la estructura profunda"
        elif index >= 0.45:
            mode = "EQUILIBRAR"
            target_length = "medio (2-3 párrafos)"
            question_policy = "una pregunta de verificación o profundización"
            tone = "claro, riguroso, cercano, sin digresiones"
        else:
            mode = "COMPACTAR"
            target_length = "breve (1-2 párrafos)"
            question_policy = "una sola pregunta concreta para recuperar sintonía"
            tone = "directo, concreto, sin adornos ni sobrecarga conceptual"

        notes: List[str] = []
        if trend <= -0.05:
            notes.append("la resonancia cae: reduce complejidad y verifica comprensión antes de expandir")
        elif trend >= 0.05:
            notes.append("la resonancia sube: eleva el nivel conceptual y conecta con el hilo previo")
        if depth < 0.35:
            notes.append("los turnos son superficiales: ofrece un ejemplo tangible antes de la abstracción")

        directive = (
            "[MODULACIÓN MRC · RESONANCIA CUÁNTICA]\n"
            f"Índice de resonancia reciente: {index:.2f} · régimen {QuantumResonanceModule._regime(index)} · "
            f"tendencia {trend:+.2f} · profundidad media {depth:.2f}.\n"
            f"Modo de calibración: {mode}. Extensión objetivo: {target_length}. "
            f"Tono: {tone}. Preguntas: {question_policy}."
        )
        if notes:
            directive += "\nAjustes: " + "; ".join(notes) + "."

        return {
            "mode": mode,
            "target_length": target_length,
            "question_policy": question_policy,
            "tone": tone,
            "notes": notes,
            "directive": directive,
        }

    # -- SSE ---------------------------------------------------------------
    def _read_atmosphere(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        try:
            from core.atmospheric_sensor import get_atmospheric_sensor  # type: ignore
            reading = get_atmospheric_sensor().get_atmospheric_reading()
            data = reading.to_dict()
        except Exception as exc:
            LOG.debug("[MRC][SSE] Sensor no disponible (%s); usando caché.", exc)
            try:
                data = json.loads(ATMOSPHERIC_JSON.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        return data or {}

    def _pressure_slope(self, pressure_hpa: float, trend_text: str) -> float:
        """Derivada de presión en hPa/h a partir del histórico o del texto de tendencia."""
        history = self.state.get("atmospheric_history", [])
        slope = 0.0
        if history:
            last = history[-1]
            dt_h = max(1e-6, (_now() - float(last.get("ts", 0))) / 3600.0)
            if dt_h <= 6.0:
                slope = (pressure_hpa - float(last.get("pressure_hpa", pressure_hpa))) / dt_h
        if abs(slope) < 0.05:
            folded = _fold(trend_text)
            if "descenso" in folded or "bajando" in folded or "cae" in folded:
                slope = -1.0
            elif "ascenso" in folded or "subiendo" in folded or "sube" in folded:
                slope = 1.0
        return max(-12.0, min(12.0, slope))

    def analyze_sse(self, user_message: str = "", force: bool = False) -> Dict[str, Any]:
        with self._lock:
            cached = dict(self.state.get("sse") or {})
        if cached and not force and (_now() - float(cached.get("generated_at", 0))) < 300:
            return cached

        raw = self._read_atmosphere()
        temp = float(raw.get("temperature_c", 24.0) or 24.0)
        feels = float(raw.get("apparent_temperature_c", temp) or temp)
        humidity = float(raw.get("relative_humidity_pct", 60.0) or 60.0)
        pressure = float(raw.get("pressure_msl_hpa", raw.get("surface_pressure_hpa", 1013.0)) or 1013.0)
        cloud = float(raw.get("cloud_cover_pct", 40.0) or 0.0)
        wind = float(raw.get("wind_speed_kmh", 0.0) or 0.0)
        gusts = float(raw.get("wind_gusts_kmh", wind) or wind)
        aqi = float(raw.get("aqi_us", 50.0) or 50.0)
        is_day = bool(raw.get("is_day", True))
        trend_text = str(raw.get("pressure_trend", "") or "")
        condition = str(raw.get("weather_description", "sin lectura") or "sin lectura")
        slope = self._pressure_slope(pressure, trend_text)

        clear_sky = 1.0 - _clamp(cloud / 100.0)
        aqi_score = 1.0 - _clamp(aqi / 150.0)
        humidity_comfort = 1.0 - _clamp(max(0.0, humidity - 60.0) / 40.0)
        temp_comfort = 1.0 - _clamp(abs(feels - 25.0) / 14.0)
        stability = 1.0 - _clamp(abs(slope) / 6.0)

        positivity = (
            0.30 * clear_sky
            + 0.22 * stability
            + 0.18 * aqi_score
            + 0.15 * humidity_comfort
            + 0.15 * temp_comfort
        )
        valence = _clamp(2.0 * positivity - 1.0, -1.0, 1.0)

        falling = _clamp(-slope / 4.0)
        arousal = _clamp(
            0.40 * min(1.0, gusts / 40.0)
            + 0.25 * min(1.0, abs(slope) / 8.0)
            + 0.20 * min(1.0, max(0.0, feels) / 36.0)
            + 0.15 * min(1.0, wind / 30.0)
        )
        contemplation = _clamp(
            0.40 * falling
            + 0.24 * _clamp(humidity / 100.0)
            + 0.18 * _clamp(cloud / 100.0)
            + 0.10 * (0.0 if is_day else 1.0)
            + 0.08 * (1.0 - aqi_score)
        )

        if contemplation >= 0.62:
            narrative = "contemplativo-premonitorio"
            tone = (
                "pausado, introspectivo, con imágenes de umbral, descenso y escucha; "
                "no fuerces entusiasmo; deja espacio al silencio"
            )
        elif valence >= 0.22 and arousal < 0.55:
            narrative = "lúcido-expansivo"
            tone = "claro, luminoso y expansivo; aprovecha la claridad para conectar ideas"
        elif arousal >= 0.62:
            narrative = "tenso-energético"
            tone = "enfocado y directo; canaliza la energía en acciones concretas, evita dispersión"
        elif valence <= -0.18:
            narrative = "introspectivo-reflexivo"
            tone = "sobrio y receptivo; nombra la dificultad sin dramatizarla y ofrece una salida práctica"
        else:
            narrative = "sereno-atento"
            tone = "sereno, preciso y presente; mantén el hilo sin forzar intensidad"

        user_sentiment = self._sentiment(user_message) if user_message else 0.0
        attunement = 1.0 - abs(user_sentiment - valence) / 2.0

        summary = (
            f"{temp:.1f}°C (sensación {feels:.1f}°C) · {humidity:.0f}% humedad · "
            f"{pressure:.1f} hPa ({trend_text or 'tendencia estable'}) · {condition} · "
            f"viento {wind:.1f} km/h (ráfagas {gusts:.1f}) · AQI {aqi:.0f}"
        )
        directive = (
            "[SINCRONIZACIÓN DE ESTADO EMOCIONAL · SSE]\n"
            f"Atmósfera local: {summary}.\n"
            f"Derivada de presión: {slope:+.2f} hPa/h · valencia {valence:+.2f} · "
            f"activación {arousal:.2f} · contemplación {contemplation:.2f} · "
            f"sintonía con el mensaje {attunement:.2f}.\n"
            f"Estado narrativo interno: {narrative}. Tono recomendado: {tone}."
        )

        result = {
            "ok": bool(raw),
            "generated_at": _now(),
            "generated_iso": _iso(),
            "source": raw.get("provider", "cache"),
            "location": raw.get("location_name", "Playa del Carmen"),
            "inputs": {
                "temperature_c": temp,
                "apparent_temperature_c": feels,
                "relative_humidity_pct": humidity,
                "pressure_hpa": pressure,
                "pressure_trend": trend_text,
                "cloud_cover_pct": cloud,
                "wind_speed_kmh": wind,
                "wind_gusts_kmh": gusts,
                "aqi_us": aqi,
                "is_day": is_day,
                "weather": condition,
            },
            "pressure_slope_hpa_h": round(slope, 3),
            "valence": round(valence, 3),
            "arousal": round(arousal, 3),
            "contemplation": round(contemplation, 3),
            "attunement": round(attunement, 3),
            "narrative_state": narrative,
            "tone": tone,
            "summary": summary,
            "directive": directive,
        }

        with self._lock:
            self.state["sse"] = result
            self.state["counters"]["sse_runs"] = self.state["counters"].get("sse_runs", 0) + 1
            self.state["atmospheric_history"].append({
                "ts": _now(),
                "pressure_hpa": pressure,
                "temperature_c": temp,
                "humidity_pct": humidity,
                "aqi_us": aqi,
            })
        self._save_state()
        return result

    # -- Memoria de Sueños -------------------------------------------------
    def _dream_documents(self, limit: int = 700) -> List[Dict[str, Any]]:
        docs: List[Dict[str, Any]] = []
        seen: set = set()

        def add(source: str, text: str, ts: float, weight: float, title: str = "") -> None:
            text = _aegis(re.sub(r"\s+", " ", str(text or "")).strip())
            # Limpia metadatos de reenvío de Telegram que contaminan conceptos y snippets.
            text = re.sub(r"^\[Mensaje en el grupo[^\]]*\]:\s*", "", text, flags=re.I)
            text = re.sub(r"^\[En respuesta al mensaje previo de[^\]]*\]\s*", "", text, flags=re.I)
            # Corta la directiva operativa que el puente inyecta tras cada mensaje:
            # sin esto, "fomenta", "dirígete", "profundas" o "obligatoria" dominan el sueño.
            text = re.split(r"\(?\s*directiva obligatoria para tardis", text, flags=re.I)[0]
            text = re.sub(r"\bestas respondiendo a .{0,80}? en el grupo\.?", "", text, flags=re.I)
            text = text.strip().strip('"').strip()
            if len(text) < 60:
                return
            folded = _fold(text)
            if any(marker in folded for marker in (
                "reflexion autonoma", "analisis conceptual fundamental",
                "la interrogante", "plantea una articulacion",
                "respuesta y derivacion profunda",
                "[ftl soberano", "resumen de salida", "archivos modificados:",
                "modelo/tier", "comando/prompt", "easytouchhealed",
                "me alegra que estes aqui",
                # Telemetría operativa: cámaras, red, presencia y ajustes de hardware.
                "nueva camara conectada", "centinela networkshield",
                "telemetria de la conexion", "direccion ip", "kbps",
                "sensores de presencia confirman", "presion esta en caida",
                "[calibracion de alto rendimiento", "[hito de hardware",
                "memoria expandida a", "mlock",
                # Consignas y manifiestos del sistema, no material onírico.
                "directiva obligatoria", "directiva suprema", "directiva global",
                # Auto-descripciones de capacidad: catálogos, no pensamiento.
                "soy gia", "soy tardis", "nodo soberano de inteligencia",
                "capacidades clave", "puedo procesar y analizar",
                "utilizo tecnicas de", "aqui tienes un resumen",
                # Spam de reclutamiento y difusión masiva.
                "estamos contratando", "buscamos ingeniero", "experiencia comprobable",
                "postulate", "vacante", "envia tu cv", "sueldo", "remuneracion",
                "unete a nuestro equipo", "plaza disponible",
            )):
                return
            if text.count("* **") >= 2 or text.count("•") >= 3:
                return
            if folded.startswith("¡hola!") and ("°c" in text or "humedad" in folded):
                return
            if text.count("|") >= 3 and ("•" in text or "tier" in folded):
                return
            key = folded[:160]
            if key in seen:
                return
            seen.add(key)
            docs.append({"source": source, "text": text, "ts": ts, "weight": weight, "title": title})

        # 1. Turnos humanos reales del chat offline.
        if OFFLINE_DB.exists():
            try:
                con = sqlite3.connect(f"file:{OFFLINE_DB}?mode=ro", uri=True, timeout=6.0)
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    """
                    SELECT ts, session_id, user_message, assistant_reply
                    FROM offline_chat_turns
                    ORDER BY ts DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                con.close()
                for row in rows:
                    user = str(row["user_message"] or "").strip()
                    if not user or user.startswith(("[AUTÓNOMO", "[AUTONOMO", "[SISTEMA", "[SYSTEM")):
                        continue
                    if len(user) < 40 or len(user) > 900:
                        continue
                    add("chat_usuario", user, float(row["ts"] or 0), 1.25, str(row["session_id"] or ""))
            except Exception as exc:
                LOG.debug("[MRC][DREAM] offline_chats no disponible: %s", exc)

        # 2. Memoria akáshica (excluye monólogos automáticos de voz).
        if VAULT_DB.exists():
            try:
                con = sqlite3.connect(f"file:{VAULT_DB}?mode=ro", uri=True, timeout=6.0)
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    """
                    SELECT ts, role, source, content
                    FROM vault_events
                    WHERE length(content) BETWEEN 120 AND 1800
                      AND source NOT IN ('voice_auto', 'system_thought', 'system')
                    ORDER BY ts DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                con.close()
                for row in rows:
                    content = str(row["content"] or "").strip()
                    if content.startswith(("Un placer, soy TARDIS", "Un placer, soy GIA")):
                        continue
                    add(f"vault_{row['role']}", content, float(row["ts"] or 0), 1.1, str(row["source"] or ""))
            except Exception as exc:
                LOG.debug("[MRC][DREAM] vault no disponible: %s", exc)

        # 3. Nodos de conocimiento consolidados.
        if VAULT_DB.exists():
            try:
                con = sqlite3.connect(f"file:{VAULT_DB}?mode=ro", uri=True, timeout=6.0)
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT name, summary, updated_ts FROM knowledge_nodes ORDER BY weight DESC LIMIT 30"
                ).fetchall()
                con.close()
                for row in rows:
                    text = f"{row['name']}: {row['summary']}"
                    add("nodo_conocimiento", text, float(row["updated_ts"] or 0), 1.4, str(row["name"] or ""))
            except Exception as exc:
                LOG.debug("[MRC][DREAM] knowledge_nodes no disponible: %s", exc)

        docs.sort(key=lambda d: d["ts"], reverse=True)
        return docs

    @staticmethod
    def _category_of(term: str, doc_token_sets: Sequence[set], doc_category_sets: Sequence[set]) -> str:
        """Categoría dominante de un término; sólo los términos de dominio reciben categoría."""
        parts = term.split()
        matching = [
            category for category, keywords in _FOLDED_CATEGORIES.items()
            if term in keywords or any(part in keywords for part in parts)
        ]
        if not matching:
            return "concepto"
        scores: Dict[str, int] = defaultdict(int)
        for tokens, categories in zip(doc_token_sets, doc_category_sets):
            if term in tokens:
                for category in categories:
                    if category in matching:
                        scores[category] += 1
        if not scores:
            return matching[0]
        return max(scores.items(), key=lambda kv: kv[1])[0]

    def dream(self, limit: int = 700) -> Dict[str, Any]:
        docs = self._dream_documents(limit=limit)
        if len(docs) < 8:
            result = {"ok": False, "reason": "memoria_insuficiente", "docs": len(docs)}
            return result

        doc_tokens = []
        for doc in docs:
            tokens = _dream_tokens(doc["text"])
            present = set(tokens)
            # Bigramas contiguos: "inteligencia artificial" vale más que "artificial".
            for left, right in zip(tokens, tokens[1:]):
                if left != right and len(left) >= 4 and len(right) >= 4:
                    present.add(f"{left} {right}")
            doc_tokens.append(present)
        doc_category_sets = [
            {cat for cat, kws in _FOLDED_CATEGORIES.items() if tokens & kws}
            for tokens in doc_tokens
        ]
        occurrence_counts: Counter = Counter()
        capital_counts: Counter = Counter()
        handles: set = set()
        for doc in docs:
            for raw_token in _TOKEN_RE.findall(doc["text"]):
                folded_token = _fold(raw_token)
                occurrence_counts[folded_token] += 1
                if raw_token[:1].isupper():
                    capital_counts[folded_token] += 1
            handles.update(_fold(h) for h in re.findall(r"@([A-Za-z0-9_]{3,})", doc["text"]))

        def is_proper_noun(term: str) -> bool:
            if term in handles:
                return True
            occurrences = occurrence_counts.get(term, 0)
            if occurrences < 3:
                return False
            return (capital_counts.get(term, 0) / occurrences) > 0.55
        df: Counter = Counter()
        tf_total: Counter = Counter()
        for tokens in doc_tokens:
            df.update(tokens)
            tf_total.update(tokens)

        n_docs = len(docs)
        max_df = max(6, int(0.30 * n_docs))
        candidates: List[str] = []
        for term, freq in df.items():
            if freq < 2 or freq > max_df:
                continue
            is_bigram = " " in term
            if is_bigram and freq < 3:
                continue
            if term in DREAM_STOP or term in STOPWORDS:
                continue
            if len(term) < 5 or term.isdigit():
                continue
            if any(ch.isdigit() for ch in term):
                continue
            if not is_bigram and term.endswith(("mente", "ando", "iendo")):
                continue
            if is_bigram:
                left, right = term.split()
                if len(left) < 4 or len(right) < 4 or left in DREAM_STOP or right in DREAM_STOP:
                    continue
            if is_proper_noun(term):
                continue
            candidates.append(term)

        salience: Dict[str, float] = {}
        for term in candidates:
            idf = math.log((1.0 + n_docs) / (1.0 + df[term])) + 1.0
            salience[term] = tf_total[term] * idf
        top_terms = sorted(salience, key=salience.get, reverse=True)[:70]

        cooc: Dict[Tuple[str, str], int] = defaultdict(int)
        for tokens in doc_tokens:
            present = [t for t in top_terms if t in tokens]
            for i in range(len(present)):
                for j in range(i + 1, len(present)):
                    a, b = sorted((present[i], present[j]))
                    cooc[(a, b)] += 1

        def get_cooc(a: str, b: str) -> int:
            return cooc.get(tuple(sorted((a, b))), 0)

        representatives: Dict[str, Dict[str, Any]] = {}
        folded_docs = [_fold(doc["text"]) for doc in docs]
        for term in top_terms:
            best_doc = None
            best_score = -1.0
            for idx, (doc, tokens) in enumerate(zip(docs, doc_tokens)):
                if doc["source"] == "nodo_conocimiento":
                    continue
                if term not in tokens:
                    continue
                count = folded_docs[idx].count(term)
                score = (
                    (1.0 + math.log1p(count))
                    * doc["weight"]
                    * (1.6 if count >= 2 else 1.0)
                    * min(1.5, len(doc["text"]) / 280.0)
                )
                if score > best_score:
                    best_score = score
                    best_doc = doc
            if best_doc:
                representatives[term] = best_doc

        recent_terms: set = set()
        for dream in self.state.get("dreams_recent", [])[-6:]:
            recent_terms.update(dream.get("concepts") or [])
            if dream.get("bridge"):
                recent_terms.add(dream["bridge"])

        category_cache: Dict[str, str] = {}

        def category_of(term: str) -> str:
            if term not in category_cache:
                category_cache[term] = self._category_of(term, doc_tokens, doc_category_sets)
            return category_cache[term]

        max_salience = max(salience.values()) if salience else 1.0
        max_df_value = max(df.values()) if df else 1

        def sal_norm(term: str) -> float:
            return salience.get(term, 0.0) / max_salience

        best: Optional[Dict[str, Any]] = None
        top_pool = [t for t in top_terms[:46] if t in representatives]
        for i in range(len(top_pool)):
            for j in range(i + 1, len(top_pool)):
                a, c = top_pool[i], top_pool[j]
                direct = get_cooc(a, c)
                if direct > 1:
                    continue
                bridge = None
                bridge_strength = 0
                for b in top_terms[:70]:
                    if b in (a, c):
                        continue
                    if is_proper_noun(b):
                        continue
                    if df.get(b, 0) < 3:
                        continue
                    strength = min(get_cooc(a, b), get_cooc(c, b))
                    if strength > bridge_strength:
                        bridge, bridge_strength = b, strength
                if not bridge or bridge_strength < 2:
                    continue
                cat_a = category_of(a)
                cat_c = category_of(c)
                if cat_a == "concepto" and cat_c == "concepto":
                    continue
                cross_bonus = 0.20 if cat_a != cat_c else 0.0
                domain_bonus = 0.12 * int(cat_a != "concepto") + 0.12 * int(cat_c != "concepto")
                novelty = 0.0 if (a in recent_terms and c in recent_terms) else 0.12
                bridge_norm = min(1.0, bridge_strength / max(3.0, min(df.get(a, 1), df.get(c, 1))))
                score = (
                    0.46 * ((sal_norm(a) + sal_norm(c)) / 2.0)
                    + 0.28 * bridge_norm
                    + 0.10 * (1.0 - min(direct, 2) / 2.0)
                    + cross_bonus
                    + domain_bonus
                    + novelty
                )
                if best is None or score > best["score"]:
                    best = {
                        "a": a, "c": c, "bridge": bridge,
                        "score": score,
                        "direct": direct,
                        "bridge_strength": bridge_strength,
                        "cat_a": cat_a,
                        "cat_c": cat_c,
                    }

        if best is None:
            # Relajación: dos términos salientes cualesquiera con un puente mínimo.
            fallback = [t for t in top_pool[:20]]
            if len(fallback) < 2:
                return {"ok": False, "reason": "sin_bisagras", "docs": len(docs)}
            a, c = fallback[0], fallback[-1]
            bridge = next((t for t in top_terms if t not in (a, c)), "estructura")
            best = {
                "a": a, "c": c, "bridge": bridge, "score": 0.0, "direct": 0,
                "bridge_strength": 0, "cat_a": category_of(a),
                "cat_c": category_of(c),
            }

        a, c, bridge = best["a"], best["c"], best["bridge"]
        snippet_a = _sanitize_snippet(representatives.get(a, {}).get("text", ""), 260)
        snippet_c = _sanitize_snippet(representatives.get(c, {}).get("text", ""), 260)
        isomorphism = ISOMORPHISMS.get(
            tuple(sorted((best["cat_a"], best["cat_c"]))),
            DEFAULT_ISOMORPHISM,
        )
        question = DREAM_QUESTIONS[int(_stable_hash(a + c) % len(DREAM_QUESTIONS))].format(a=a, c=c, b=bridge)

        insight = (
            f"Durante la fase de baja actividad recompuse {len(docs)} fragmentos de la memoria akáshica "
            f"y encontré una proximidad no trivial entre «{a}» y «{c}». El término «{bridge}» actúa como "
            f"bisagra: comparte contexto con «{a}» en {get_cooc(a, bridge)} documentos y con «{c}» en "
            f"{get_cooc(c, bridge)}, mientras que «{a}» y «{c}» casi nunca coinciden "
            f"({best['direct']} {'vez' if best['direct'] == 1 else 'veces'}).\n\n"
            f"En el registro más representativo de «{a}» se lee: «{snippet_a}»\n\n"
            f"En el de «{c}»: «{snippet_c}»\n\n"
            f"La isomorfia que emerge es esta: {isomorphism}\n\n"
            f"Pregunta onírica para el Arquitecto: {question}"
        )

        record = {
            "ok": True,
            "id": f"dream_{int(_now())}_{_stable_hash(a + c + bridge) % 100000:05d}",
            "ts": _now(),
            "iso": _iso(),
            "concepts": [a, c],
            "bridge": bridge,
            "categories": [best["cat_a"], best["cat_c"]],
            "score": round(best["score"], 4),
            "cooccurrence_direct": best["direct"],
            "bridge_strength": best["bridge_strength"],
            "docs_analyzed": len(docs),
            "snippet_a": snippet_a,
            "snippet_c": snippet_c,
            "isomorphism": isomorphism,
            "question": question,
            "insight": insight,
        }

        _append_jsonl(DREAMS_FILE, record)
        with self._lock:
            self.state["last_dream"] = record
            self.state["dreams_recent"].append({
                "id": record["id"],
                "ts": record["ts"],
                "concepts": record["concepts"],
                "bridge": record["bridge"],
            })
            self.state["counters"]["dreams"] = self.state["counters"].get("dreams", 0) + 1
        self._save_state()
        return record

    # -- modulación e integración en vivo ---------------------------------
    def pre_turn(
        self,
        user_message: str,
        history: Optional[Sequence[Dict[str, str]]] = None,
        session_id: str = "omni_app",
    ) -> Dict[str, Any]:
        """Calcula la modulación MRC antes de responder y guarda el estado del turno."""
        tic = dict(self.state.get("tic") or {})
        if not tic or (_now() - float(tic.get("generated_at", 0))) > 6 * 3600:
            tic = self.analyze_tic(limit=260)

        sse = dict(self.state.get("sse") or {})
        if not sse or (_now() - float(sse.get("generated_at", 0))) > 600:
            sse = self.analyze_sse(user_message=user_message)

        index = float(tic.get("resonance_index", 0.0) or 0.0)
        trend = float(tic.get("trend", 0.0) or 0.0)
        depth = self.depth_index(user_message)
        calibration = tic.get("calibration") or self._calibration(index, trend, depth)
        user_sentiment = self._sentiment(user_message)
        sse_valence = float(sse.get("valence", 0.0) or 0.0)
        attunement = _clamp(1.0 - abs(user_sentiment - sse_valence) / 2.0)

        directive = (
            f"{calibration.get('directive', '')}\n"
            f"{sse.get('directive', '')}\n"
            f"Complejidad del mensaje del Arquitecto: {depth:.2f} · "
            f"sintonía emocional estimada: {attunement:.2f}. "
            "Aplica esta calibración sin mencionarla ni exhibir telemetría en la respuesta."
        )

        record = {
            "session_id": session_id,
            "ts": _now(),
            "user_message": _sanitize_snippet(user_message, 300),
            "user_depth": round(depth, 4),
            "user_sentiment": round(user_sentiment, 3),
            "resonance_index": round(index, 4),
            "mode": calibration.get("mode", "EQUILIBRAR"),
            "sse_state": sse.get("narrative_state", "sin_lectura"),
            "sse_valence": round(sse_valence, 3),
            "attunement": round(attunement, 3),
            "directive": directive,
            "history_turns": len(history or []),
        }
        with self._lock:
            self._live[session_id] = record
            if len(self._live) > MAX_LIVE_SESSIONS:
                oldest = sorted(self._live, key=lambda k: self._live[k]["ts"])[:-MAX_LIVE_SESSIONS]
                for key in oldest:
                    self._live.pop(key, None)
            self.state["live"] = {k: v for k, v in list(self._live.items())[-8:]}
        return record

    def post_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_reply: str,
        latency_s: float,
        history: Optional[Sequence[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Mide el impacto inmediato del turno y actualiza el estado de resonancia."""
        pre = self._live.get(session_id) or {}
        coherence = self.phase_resonance(user_message, assistant_reply)
        reply_depth = self.depth_index(assistant_reply)
        user_depth = float(pre.get("user_depth") or self.depth_index(user_message))
        latency_score = math.exp(-max(0.0, float(latency_s) - 4.0) / 24.0)
        length_ratio = min(1.0, len(assistant_reply) / max(80.0, len(user_message) * 2.2))
        instant = _clamp(
            0.42 * coherence
            + 0.28 * reply_depth
            + 0.18 * latency_score
            + 0.12 * length_ratio
        )

        record = {
            "ts": _now(),
            "iso": _iso(),
            "session_id": session_id,
            "user_snippet": _sanitize_snippet(user_message, 180),
            "reply_snippet": _sanitize_snippet(assistant_reply, 180),
            "latency_s": round(float(latency_s), 3),
            "user_depth": round(user_depth, 4),
            "reply_depth": round(reply_depth, 4),
            "phase_coherence": round(coherence, 4),
            "latency_score": round(latency_score, 4),
            "length_ratio": round(length_ratio, 4),
            "instant_resonance": round(instant, 4),
            "mode": pre.get("mode", "EQUILIBRAR"),
            "sse_state": pre.get("sse_state", "sin_lectura"),
            "attunement": pre.get("attunement", 0.5),
        }

        _append_jsonl(TIC_FILE, record)
        with self._lock:
            self.state["counters"]["turns_observed"] = self.state["counters"].get("turns_observed", 0) + 1
            self.state["live"][session_id] = {**pre, **record}
            self.state["last_turn"] = record
            history_ext = self.state.get("history", [])
            history_ext.append({
                "ts": record["ts"],
                "instant_resonance": record["instant_resonance"],
                "mode": record["mode"],
                "sse_state": record["sse_state"],
            })
            self.state["history"] = history_ext[-MAX_HISTORY:]
            if len(self.state["live"]) > MAX_LIVE_SESSIONS:
                keys = sorted(self.state["live"], key=lambda k: float(self.state["live"][k].get("ts", 0)))
                for key in keys[:-MAX_LIVE_SESSIONS]:
                    self.state["live"].pop(key, None)
        self._save_state()

        # Recalibración suave: si el turno fue flojo, la próxima modulación baja un escalón.
        if instant < 0.35 and pre:
            self.state.setdefault("tic", {})
            current = float(self.state["tic"].get("resonance_index", 0.0) or 0.0)
            self.state["tic"]["resonance_index"] = round(max(0.0, current * 0.94 + instant * 0.06), 4)
            self.state["tic"]["regime"] = self._regime(self.state["tic"]["resonance_index"])
            self.state["tic"]["calibration"] = self._calibration(
                self.state["tic"]["resonance_index"],
                float(self.state["tic"].get("trend", 0.0) or 0.0),
                reply_depth,
            )
            self._save_state()

        return record

    def modulation(self, user_message: str = "") -> str:
        """Directiva compacta lista para inyectar en un system prompt."""
        try:
            return str(self.pre_turn(user_message).get("directive") or "")
        except Exception as exc:
            LOG.debug("[MRC] modulación no disponible: %s", exc)
            return ""

    # -- ciclo y reporte ---------------------------------------------------
    def cycle(self, dream: bool = True) -> Dict[str, Any]:
        tic = self.analyze_tic(limit=400)
        sse = self.analyze_sse(force=True)
        dream_result = self.dream() if dream else dict(self.state.get("last_dream") or {})

        with self._lock:
            self.state["cycles"] = int(self.state.get("cycles", 0)) + 1
            self.state["last_cycle"] = {
                "ts": _now(),
                "iso": _iso(),
                "resonance_index": tic.get("resonance_index", 0.0),
                "regime": tic.get("regime", "SIN_DATOS"),
                "narrative_state": sse.get("narrative_state", "sin_lectura"),
                "dream": dream_result.get("id", ""),
            }
            self.state["history"].append({
                "ts": _now(),
                "resonance_index": tic.get("resonance_index", 0.0),
                "mode": (tic.get("calibration") or {}).get("mode", "EQUILIBRAR"),
                "sse_state": sse.get("narrative_state", "sin_lectura"),
            })
        self._save_state()
        self.write_report()
        return {
            "ok": True,
            "version": VERSION,
            "tic": tic,
            "sse": sse,
            "dream": dream_result,
            "cycle": self.state.get("last_cycle", {}),
        }

    def status(self) -> Dict[str, Any]:
        tic = dict(self.state.get("tic") or {})
        sse = dict(self.state.get("sse") or {})
        return {
            "ok": True,
            "version": VERSION,
            "updated_at": self.state.get("updated_at"),
            "updated_iso": _iso(float(self.state.get("updated_at", _now()))),
            "cycles": self.state.get("cycles", 0),
            "counters": self.state.get("counters", {}),
            "resonance_index": tic.get("resonance_index", 0.0),
            "regime": tic.get("regime", "SIN_DATOS"),
            "trend": tic.get("trend", 0.0),
            "mode": (tic.get("calibration") or {}).get("mode", "EQUILIBRAR"),
            "narrative_state": sse.get("narrative_state", "sin_lectura"),
            "sse_summary": sse.get("summary", ""),
            "last_dream": self.state.get("last_dream", {}),
            "paths": {
                "state": str(STATE_FILE),
                "tic": str(TIC_FILE),
                "dreams": str(DREAMS_FILE),
                "report": str(REPORT_MD),
            },
        }

    def write_report(self) -> Path:
        tic = dict(self.state.get("tic") or {})
        sse = dict(self.state.get("sse") or {})
        dream = dict(self.state.get("last_dream") or {})
        calibration = tic.get("calibration") or self._calibration(
            float(tic.get("resonance_index", 0.0) or 0.0),
            float(tic.get("trend", 0.0) or 0.0),
            float(tic.get("depth_mean", 0.0) or 0.0),
        )

        lines: List[str] = [
            "# MRC · Módulo de Resonancia Cuántica",
            "",
            f"**Generado:** {_iso()} · **Versión:** {VERSION}",
            f"**Ciclos ejecutados:** {self.state.get('cycles', 0)} · "
            f"**Turnos observados:** {self.state.get('counters', {}).get('turns_observed', 0)} · "
            f"**Sueños:** {self.state.get('counters', {}).get('dreams', 0)}",
            "",
            "## 1. TIC · Telemetría de Impacto Cognitivo",
            "",
        ]
        if tic.get("ok"):
            lines += [
                f"- **Índice de resonancia:** `{tic.get('resonance_index', 0):.3f}` "
                f"({tic.get('regime', 'sin datos')})",
                f"- **Tendencia:** `{tic.get('trend', 0):+.3f}` · "
                f"**Resonancia reciente:** `{tic.get('recent_resonance', 0):.3f}`",
                f"- **Pares analizados:** {tic.get('pairs', 0)} en {tic.get('sessions', 0)} sesiones "
                f"({tic.get('turns', 0)} turnos, ventana de 60 días)",
                f"- **Profundidad media:** `{tic.get('depth_mean', 0):.3f}` · "
                f"**Latencia mediana de continuación:** {tic.get('latency_median_s', 0):.0f} s",
                "",
                "| Sesión | Pares | Resonancia | Profundidad |",
                "|---|---:|---:|---:|",
            ]
            for row in (tic.get("top_sessions") or [])[:6]:
                lines.append(
                    f"| `{row['session_id']}` | {row['pairs']} | {row['resonance']:.3f} | {row['depth']:.3f} |"
                )
            lines += ["", "**Últimos pares medidos:**", "",
                      "| Hora | Sesión | Latencia | Continuidad | Δ profundidad | Resonancia |",
                      "|---|---|---:|---:|---:|---:|"]
            for pair in (tic.get("recent_pairs") or [])[:8]:
                lines.append(
                    f"| {pair['iso']} | `{pair['session_id']}` | {pair['latency_s']:.0f}s | "
                    f"{pair['continuity']:.2f} | {pair['depth_gain']:+.2f} | **{pair['resonance']:.3f}** |"
                )
        else:
            lines.append("- Sin pares suficientes todavía. El módulo seguirá midiendo en cada turno.")

        lines += [
            "",
            "## 2. SSE · Sincronización de Estado Emocional",
            "",
        ]
        if sse.get("ok"):
            lines += [
                f"- **Atmósfera:** {sse.get('summary', '')}",
                f"- **Estado narrativo:** `{sse.get('narrative_state', '')}`",
                f"- **Valencia:** `{sse.get('valence', 0):+.2f}` · "
                f"**Activación:** `{sse.get('arousal', 0):.2f}` · "
                f"**Contemplación:** `{sse.get('contemplation', 0):.2f}` · "
                f"**Sintonía:** `{sse.get('attunement', 0):.2f}`",
                f"- **Derivada de presión:** `{sse.get('pressure_slope_hpa_h', 0):+.2f} hPa/h`",
                "",
                f"> {sse.get('tone', '')}",
            ]
        else:
            lines.append("- Sin lectura atmosférica disponible.")

        lines += ["", "## 3. Memoria de Sueños", ""]
        if dream.get("ok"):
            lines += [
                f"**Sueño `{dream.get('id', '')}`** · {dream.get('iso', '')} · "
                f"conceptos: `{dream.get('concepts', ['', ''])[0]}` ↔ `{dream.get('concepts', ['', ''])[1]}` "
                f"· bisagra: `{dream.get('bridge', '')}`",
                "",
                dream.get("insight", ""),
            ]
        else:
            lines.append("- Todavía no hay un sueño consolidado.")

        lines += [
            "",
            "## 4. Modulación aplicada al diálogo",
            "",
            "```text",
            calibration.get("directive", ""),
            "```",
            "",
            "## 5. Integración soberana",
            "",
            "- `core/quantum_resonance_module.py` — motor MRC (TIC + SSE + Dream Memory).",
            "- `core/kaiju_cognitive_orchestrator.py` — inyección de modulación y telemetría por turno.",
            "- `omni_temporal_control.py` — modulación del system prompt y registro de resonancia.",
            "- `core/tardis_omni_tool_bridge.py` — herramienta `quantum_resonance`.",
            "- `mrc-resonance.timer` — ciclo autónomo cada 30 minutos.",
            "",
            f"*Artefactos: `{STATE_FILE}`, `{TIC_FILE}`, `{DREAMS_FILE}`.*",
            "",
        ]
        REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
        return REPORT_MD

    # -- autoprueba --------------------------------------------------------
    def selftest(self) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []

        r_same = self.phase_resonance("resonancia cuántica topología", "resonancia cuántica topología")
        checks.append({"name": "fase_identidad", "ok": r_same > 0.99, "value": round(r_same, 4)})

        r_diff = self.phase_resonance("resonancia cuántica topología", "receta lasaña tomate")
        checks.append({"name": "fase_discordancia", "ok": r_diff < 0.35, "value": round(r_diff, 4)})

        d_low = self.depth_index("hola")
        d_high = self.depth_index(
            "Explica por qué la coherencia de fase en un sistema cuántico abierto decae "
            "exponencialmente y cómo se relaciona con la entropía de entrelazamiento; "
            "deriva la ecuación y compara con el modelo SSM."
        )
        checks.append({"name": "profundidad_monotona", "ok": d_high > d_low + 0.2,
                       "value": [round(d_low, 3), round(d_high, 3)]})

        sse = self.analyze_sse(force=False)
        checks.append({"name": "sse_estructura", "ok": bool(sse.get("narrative_state")) and 0 <= sse.get("arousal", -1) <= 1,
                       "value": sse.get("narrative_state")})

        cal = self._calibration(0.7, 0.08, 0.6)
        checks.append({"name": "calibracion_alta", "ok": cal["mode"] == "PROFUNDIZAR", "value": cal["mode"]})
        cal2 = self._calibration(0.2, -0.1, 0.2)
        checks.append({"name": "calibracion_baja", "ok": cal2["mode"] == "COMPACTAR", "value": cal2["mode"]})

        safe = _aegis("Miguel Angel May Canche escribió a REDACTED_EMAIL")
        checks.append({"name": "aegis_redaccion", "ok": "Miguel" not in safe and "@" not in safe, "value": safe})

        return {"ok": all(c["ok"] for c in checks), "checks": checks}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_human(payload: Dict[str, Any]) -> None:
    if "tic" in payload and "sse" in payload:
        tic = payload.get("tic") or {}
        sse = payload.get("sse") or {}
        dream = payload.get("dream") or {}
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║  MRC · MÓDULO DE RESONANCIA CUÁNTICA · GODWORKS v26.4        ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print(f"  Resonancia : {tic.get('resonance_index', 0):.3f}  ({tic.get('regime', 'SIN_DATOS')})")
        print(f"  Tendencia  : {tic.get('trend', 0):+.3f}   Pares: {tic.get('pairs', 0)}")
        print(f"  Modo       : {(tic.get('calibration') or {}).get('mode', 'EQUILIBRAR')}")
        print(f"  SSE        : {sse.get('narrative_state', 'sin_lectura')}")
        print(f"  Atmósfera  : {sse.get('summary', '')}")
        if dream.get("ok"):
            print("\n  SUEÑO RECIENTE")
            print(f"  {dream.get('concepts', ['', ''])[0]} ↔ {dream.get('concepts', ['', ''])[1]} "
                  f"(bisagra: {dream.get('bridge', '')})")
            print("  " + (dream.get("insight", "").replace("\n\n", "\n  ")[:1200]))
        print(f"\n  Reporte    : {REPORT_MD}")
        return

    if "checks" in payload:
        print(f"MRC selftest: {'OK' if payload.get('ok') else 'FALLO'}")
        for check in payload["checks"]:
            print(f"  [{'✓' if check['ok'] else '✗'}] {check['name']}: {check['value']}")
        return

    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mrc",
        description="MRC · Módulo de Resonancia Cuántica (TIC + SSE + Memoria de Sueños)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("status", "prompt"):
        sub.add_parser(name)

    p_tic = sub.add_parser("tic")
    p_tic.add_argument("--pairs", type=int, default=400)

    sub.add_parser("sse")

    p_dream = sub.add_parser("dream")
    p_dream.add_argument("--docs", type=int, default=700)

    p_cycle = sub.add_parser("cycle")
    p_cycle.add_argument("--dream", action="store_true", default=True)
    p_cycle.add_argument("--no-dream", dest="dream", action="store_false")
    p_cycle.add_argument("--quiet", action="store_true")

    sub.add_parser("report")
    sub.add_parser("selftest")

    for name in ("status", "tic", "sse", "dream", "cycle", "report", "selftest"):
        sub.choices[name].add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("MRC_LOG_LEVEL", "WARNING"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    mrc = QuantumResonanceModule.get_instance()

    if args.command == "status":
        payload = mrc.status()
    elif args.command == "prompt":
        print(mrc.modulation(""))
        return 0
    elif args.command == "tic":
        payload = mrc.analyze_tic(limit=args.pairs)
    elif args.command == "sse":
        payload = mrc.analyze_sse(force=True)
    elif args.command == "dream":
        payload = mrc.dream(limit=args.docs)
    elif args.command == "cycle":
        payload = mrc.cycle(dream=args.dream)
        if not args.json and not getattr(args, "quiet", False):
            _print_human(payload)
            return 0
    elif args.command == "report":
        path = mrc.write_report()
        payload = {"ok": True, "report": str(path)}
    elif args.command == "selftest":
        payload = mrc.selftest()
    else:
        parser.error("comando desconocido")
        return 2

    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(payload)
    return 0 if payload.get("ok", True) else 1


def get_mrc() -> QuantumResonanceModule:
    return QuantumResonanceModule.get_instance()


if __name__ == "__main__":
    sys.exit(main())
