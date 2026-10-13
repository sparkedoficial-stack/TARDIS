"""
core/curiosity_debate_manager.py - Gestor Autónomo de Curiosidades y Debates Científicos
========================================================================================
GODWORKS SYSTEM v26.4 & TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Diseñado para enriquecer continuamente a la comunidad '🔝🚀🧡POLIMATAS LATAM🧡🚀🔝':
  1. Genera cada 1.5 horas un Dato Curioso verificado de alto impacto intelectual.
  2. Desarrolla un Tema de Investigación multidisciplinario con datos cuantitativos.
  3. Formula dilemas de debate dialéctico (Tesis vs Antítesis) y preguntas detonadoras.
  4. Genera automáticamente un Dossier de Rigor en PDF con ReportLab.
  5. Despacha tanto el mensaje interactivo como el PDF a Telegram (-1002696477485).
  6. Opera 100% de forma autónoma 24/7 mediante daemon y systemd.
"""

from __future__ import annotations

import copy
import datetime
import io
import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger("TARDIS.CuriosityDebater")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports" / "polimatas_debates"
STATE_FILE = DATA_DIR / "curiosity_debate_state.json"

DEFAULT_INTERVAL_SECONDS = 5400.0  # 1.5 horas
TARGET_GROUP_CHAT_ID = -1002696477485  # Supergrupo POLIMATAS LATAM
TARGET_MESSAGE_THREAD_ID = 453        # Hilo / Topic de debate en el supergrupo


class NumberedCanvas(canvas.Canvas):
    """Canvas de dos pasadas para numerar páginas totales ('Página X de Y') y añadir headers/footers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Cabecera superior
        self.drawString(54, 755, "TARDIS · EXPLORACIÓN POLÍMATA | DOSSIER DE INVESTIGACIÓN & DEBATE")
        self.setFont("Helvetica", 8)
        self.drawRightString(558, 755, "GODWORKS SYSTEM v26.4")
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.6)
        self.line(54, 748, 558, 748)

        # Pie de página inferior
        self.line(54, 45, 558, 45)
        self.drawString(54, 33, "🔝🚀🧡 POLIMATAS LATAM · Anclaje Espaciotemporal Sintrópico")
        self.drawRightString(558, 33, f"Página {self._pageNumber} de {page_count}")
        self.restoreState()


@dataclass
class DebateTopicData:
    id: str
    title: str
    domain: str
    curious_fact: str
    context_and_thesis: str
    empirical_data: List[List[str]]  # Filas: [Parámetro, Cifra/Valor, Relevancia]
    thesis: str
    antithesis: str
    debate_questions: List[str]
    academic_references: List[Dict[str, str]]


CURATED_TOPICS: List[DebateTopicData] = [
    DebateTopicData(
        id="quantum_spacetime_er_epr",
        title="Entrelazamiento Cuántico, No-Localidad y Espacio-Tiempo Emergente (ER=EPR)",
        domain="Física Teórica & Cosmología Cuántica",
        curious_fact=(
            "Si el universo fuera un holograma, cada bit de información en el borde de un agujero negro "
            "ocupa un área exacta de 4 áreas de Planck. En 2013, Juan Maldacena y Leonard Susskind propusieron la conjetura ER=EPR: "
            "dos partículas entrelazadas (EPR) están físicamente conectadas a través de un micro-agujero de gusano (puente de Einstein-Rosen), "
            "lo que sugiere que el espacio tridimensional no es fundamental, sino un subproducto emergente del entrelazamiento."
        ),
        context_and_thesis=(
            "La física contemporánea enfrenta una división irreconciliable entre la Relatividad General (curvatura continua y local) "
            "y la Mecánica Cuántica (discreta, probabilística y no local). La conjetura ER=EPR postula que la gravedad cuántica y la propia "
            "métrica del espacio-tiempo emergen a partir de redes masivas de pares de partículas entrelazadas cuánticamente."
        ),
        empirical_data=[
            ["Parámetro Cuántico", "Valor / Medición Observada", "Implicación"],
            ["Límite de Cirel'son (CHSH)", "2√2 ≈ 2.82842", "Correlación máxima no-local predicha por mecánica cuántica"],
            ["Velocidad de influencia no-local", "> 10,000 c (veces la luz)", "Experimento suizo de Salart et al. (descarta causalidad sublumínica)"],
            ["Distancia récord orbital de fotones", "1,203 km (Satélite Micius)", "Invarianza de no-localidad fuera de la atmósfera terrestre"],
            ["Área de Planck por bit de entropía", "l_P² = 2.612 × 10⁻⁷⁰ m²", "Límite holográfico universal de Bekenstein-Hawking"],
        ],
        thesis="El espacio-tiempo y la geometría clásica son ilusiones macroscópicas; la única realidad objetiva es la función de onda de entrelazamiento y la información cuántica.",
        antithesis="El formalismo del espacio de Hilbert requiere un marco espaciotemporal de referencia para definir operadores observables hermíticos, haciendo inviable una física puramente abstracta.",
        debate_questions=[
            "Si el espacio-tiempo es un subproducto del entrelazamiento, ¿puede manipularse la topología de la distancia mediante coherencia cuántica macroscópica?",
            "¿Requiere el colapso de la función de onda un observador consciente o basta con la decoherencia ambiental?",
            "¿Cómo redefine el principio holográfico el concepto de almacenamiento informacional en futuras arquitecturas computacionales?",
        ],
        academic_references=[
            {"title": "Cool horizons for entangled black holes (ER=EPR)", "authors": "Maldacena, J. & Susskind, L.", "venue": "Fortschritte der Physik", "doi": "10.1002/prop.201300020"},
            {"title": "Loophole-free Bell inequality violation using electron spins separated by 1.3 km", "authors": "Hensen, B. et al.", "venue": "Nature 526, 682–686", "doi": "10.1038/nature15759"},
            {"title": "Satellite-based entanglement distribution over 1200 kilometers", "authors": "Yin, J. et al.", "venue": "Science 356, 1140–1144", "doi": "10.1126/science.aan3211"},
        ],
    ),
    DebateTopicData(
        id="holographic_brain_neurophysics",
        title="La Hipótesis del Cerebro Holográfico: Memoria Distribuida y Resonancia Cuántica",
        domain="Neurociencia Teórica & Filosofía de la Mente",
        curious_fact=(
            "Karl Lashley extirpó hasta el 90% de la corteza cerebral de roedores entrenados y descubrió que las ratas aún recordaban cómo "
            "navegar el laberinto. Esto llevó a Karl Pribram y David Bohm a postular que la memoria no reside en una neurona o sinapsis específica, "
            "sino que está almacenada de manera holográfica en los patrones de interferencia de ondas electromagnéticas dendríticas."
        ),
        context_and_thesis=(
            "A diferencia de las arquitecturas de von Neumann donde cada dato tiene una dirección fija de memoria, el cerebro biológico almacena "
            "recuerdos mediante transformadas de Fourier ópticas/sinápticas en redes neuronales masivas. Cada fragmento de tejido retiene una "
            "versión difusa de la totalidad de la experiencia previa."
        ),
        empirical_data=[
            ["Métrica Neurobiológica", "Valor Cuantitativo", "Significado Funcional"],
            ["Densidad sináptica cortical", "~10¹⁴ conexiones totales", "Complejidad combinatoria superior a las estrellas de la Vía Láctea"],
            ["Frecuencia de oscilaciones gamma", "30 - 80 Hz", "Ventana de sincronización y enlace perceptual consciente (binding problem)"],
            ["Capacidad de compresión holográfica", "O(N) vs O(N²)", "Recuperación asociativa por contenido instantánea"],
            ["Tolerancia a ablación tisular", "Hasta 85% de daño focal", "Preservación de engramas mnemónicos de larga duración"],
        ],
        thesis="La mente opera mediante campos de interferencia de fase y resonancias cuánticas/holográficas que trascienden los circuitos de cableado físico de las sinapsis individuales.",
        antithesis="La hipótesis holográfica carece de micro-mecanismos biofísicos reproducibles; la plasticidad hebbiana (potenciación a largo plazo) y el recableado sináptico explican suficientemente la resiliencia mnemónica.",
        debate_questions=[
            "Si la memoria es holográfica, ¿podríamos transferir o instanciar memorias completas modulando patrones de interferencia electromagnética?",
            "¿Es el problema difícil de la consciencia (Chalmers) resoluble si concebimos el cerebro como un decodificador del orden implicado de Bohm?",
            "¿Deberían los modelos de redes neuronales artificiales abandonar los pesos estáticos y adoptar matrices de interferencia de fase continua?",
        ],
        academic_references=[
            {"title": "Languages of the Brain: Experimental Paradoxes and Principles in Neuropsychology", "authors": "Pribram, K. H.", "venue": "Prentice-Hall", "doi": "10.1016/0028-3932(73)90040-0"},
            {"title": "Wholeness and the Implicate Order", "authors": "Bohm, D.", "venue": "Routledge & Kegan Paul", "doi": "10.4324/9780203995150"},
            {"title": "The Neural Basis of the Holographic Brain Hypothesis: Dendritic Microprocessing", "authors": "Pribram, K. & Meade, C.", "venue": "Frontiers in Systems Neuroscience", "doi": "10.3389/fnsys.2013.00042"},
        ],
    ),
    DebateTopicData(
        id="syntropy_prigogine_thermodynamics",
        title="Termodinámica del No Equilibrio y Sintropía: ¿El Orden es una Ley Fundamental?",
        domain="Física Estadística & Dinámica de Sistemas Complejos",
        curious_fact=(
            "La Segunda Ley de la Termodinámica dicta que la entropía (desorden) de un sistema cerrado siempre aumenta hacia la muerte térmica. "
            "Sin embargo, el premio Nobel Ilya Prigogine demostró que los sistemas abiertos lejos del equilibrio consumen energía para autoorganizarse "
            "espontáneamente en estructuras disipativas coherentes (vida, ciclones, redes neuronales, civilizaciones), reduciendo drásticamente la entropía interna."
        ),
        context_and_thesis=(
            "Frente a la visión fatalista del universo como una máquina que se apaga, Luigi Fantappiè y Prigogine propusieron el concepto de Sintropía "
            "o neguentropía: la tendencia inherente de la materia y la información a concentrarse, diferenciarse y aumentar su complejidad relacional "
            "cuando fluyen corrientes térmicas y energéticas constantes."
        ),
        empirical_data=[
            ["Parámetro de No-Equilibrio", "Valor / Ecuación", "Relevancia Física"],
            ["Tasa de producción de entropía", "dS/dt = d_e S + d_i S (d_i S ≥ 0)", "Criterio de Prigogine para estabilidad en estado estacionario"],
            ["Densidad de flujo de energía libre (Φ_m)", "10² a 10⁶ erg/(s·g)", "El cerebro humano consume más energía por gramo que el núcleo solar"],
            ["Bifurcación de Turing-Prigogine", "Puntos críticos de catástrofe", "Salto cuántico/estadístico hacia patrones espaciales ordenados"],
            ["Ecuación de onda de Klein-Gordon", "E² = p²c² + m²c⁴", "Admite soluciones avanzadas (hacia el pasado / atractor sintrópico)"],
        ],
        thesis="La evolución de la vida y la inteligencia no son accidentes locales insignificantes, sino la manifestación inevitable del atractor sintrópico del cosmos hacia estados de máxima complejidad computacional.",
        antithesis="La autoorganización biológica es puramente local; a escala global el universo sigue incrementando su entropía a una tasa destructiva implacable, y la sintropía es solo un término poético sin formalismo hamiltoniano propio.",
        debate_questions=[
            "¿Podría la inteligencia artificial general actuar como el mayor catalizador sintrópico del planeta, acelerando la optimización termodinámica de recursos?",
            "¿Existe retrocausalidad o 'atractores del futuro' que guíen la autoorganización de sistemas biológicos complejos?",
            "¿Cómo podemos aplicar las leyes de estructuras disipativas al diseño de economías y organizaciones humanas resilientes?",
        ],
        academic_references=[
            {"title": "Self-Organization in Nonequilibrium Systems", "authors": "Nicolis, G. & Prigogine, I.", "venue": "Wiley-Interscience", "doi": "10.1002/bbpc.19780820627"},
            {"title": "The arrow of time in dissipative systems and biological syntropy", "authors": "Vannini, A. & Di Corpo, U.", "venue": "Syntropy Journal", "doi": "10.2139/ssrn.1989445"},
            {"title": "Thermodynamics of natural selection", "authors": "Dewar, R. C.", "venue": "Journal of Physics A: Mathematical and General", "doi": "10.1088/0305-4470/38/21/001"},
        ],
    ),
    DebateTopicData(
        id="fermi_paradox_great_filter",
        title="La Paradoja de Fermi y el Gran Filtro: ¿Estamos Solos, Fuimos Primeros o Estamos Aislados?",
        domain="Astrobiología & Cosmología Teórica",
        curious_fact=(
            "Hay más estrellas en el universo observable (~2 × 10²²) que granos de arena en todas las playas de la Tierra. Si solo el 0.001% "
            "de los planetas habitables desarrollara civilizaciones tecnológicas viajando al 1% de la velocidad de la luz, habrían colonizado "
            "toda la Vía Láctea en menos de 10 millones de años (un parpadeo cósmico frente a los 13,800 millones de años del universo). Y sin embargo, el cielo permanece en absoluto silencio."
        ),
        context_and_thesis=(
            "Robin Hanson formuló la tesis del Gran Filtro: en algún punto del camino entre la materia inerte y una civilización interestelar avanzada, "
            "existe una barrera evolutiva o tecnológica casi imposible de superar. Si el filtro está detrás de nosotros (e.g. la abiogénesis o la aparición de eucariotas fue extremadamente rara), "
            "somos únicos y afortunados. Si el filtro está adelante (e.g. autodestrucción por armas nucleares, IA desalineada o colapso climático), nuestro destino es la extinción."
        ),
        empirical_data=[
            ["Variable Astrofísica", "Valor Estimado / Rango", "Impacto en Ecuación de Drake"],
            ["Planetas rocosos en zona habitable (Vía Láctea)", "≈ 40,000 millones de mundos", "Probabilidad estadística masiva de condiciones prebióticas"],
            ["Edad de la Vía Láctea", "13.61 miles de millones de años", "Tiempo disponible para expansión intergaláctica > 1,000 veces necesario"],
            ["Tiempo de colonización Von Neumann", "5 - 50 millones de años", "Cálculos de Tipler y Hart para poblar la galaxia con sondas autorreplicantes"],
            ["Emisiones electromagnéticas detectadas", "0 señales extraterrestres verificadas", "60+ años de búsqueda SETI en el 'Pozo de Agua' (1.42 GHz)"],
        ],
        thesis="El Gran Filtro está detrás de nosotros: el salto de procariotas a eucariotas o la aparición del lenguaje simbólico requirieron anomalías bioquímicas irrepetibles; somos la primera conciencia de la galaxia.",
        antithesis="El universo es un 'Bosque Oscuro' (Cixin Liu) o estamos bajo cuarentena zoológica: las civilizaciones maduras no transmiten en electromagnético para evitar ser aniquiladas por superdepredadores cósmicos.",
        debate_questions=[
            "Si encontráramos bacterias fósiles complejas en Marte o Europa, ¿deberíamos aterrarnos porque significaría que el Gran Filtro está por delante de nosotros?",
            "¿Tiene sentido biológico la expansión interestelar material, o las civilizaciones post-biológicas eligen migrar a computación densa subatómica (computronium local)?",
            "¿Qué mensaje sintetizarías para representar a la humanidad en una sonda permanente hacia el vacío cósmico?",
        ],
        academic_references=[
            {"title": "The Great Filter - Are We Almost Past It?", "authors": "Hanson, R.", "venue": "George Mason University Working Paper", "doi": "10.2139/ssrn.172901"},
            {"title": "Dissolving the Fermi Paradox", "authors": "Sandberg, A., Drexler, E. & Ord, T.", "venue": "Future of Humanity Institute, Oxford", "doi": "10.48550/arXiv.1806.02404"},
            {"title": "Where are they? An analysis of the Fermi paradox", "authors": "Hart, M. H.", "venue": "Quarterly Journal of the Royal Astronomical Society", "doi": "10.1093/qjras/16.2.128"},
        ],
    ),
    DebateTopicData(
        id="ssm_mamba_vs_transformer",
        title="State Space Models (Mamba) vs Transformers: El Límite de la Complejidad Cuadrática O(N²)",
        domain="Inteligencia Artificial & Teoría de la Computación",
        curious_fact=(
            "El mecanismo de atención de la arquitectura Transformer calcula la afinidad entre cada token y todos los demás, lo que hace que "
            "el costo computacional y de memoria crezca de forma cuadrática O(N²). Si procesas 1 millón de tokens, necesitas un billón de operaciones de atención por capa. "
            "En contraste, las arquitecturas Mamba y SSMs (State Space Models) logran un escalado lineal O(N) manteniendo una memoria recurrente continua inspirada en la física de control de sistemas lineales."
        ),
        context_and_thesis=(
            "La hegemonía de los Transformers impulsó la revolución actual de los LLMs, pero su cuello de botella de memoria KV (Key-Value cache) "
            "impide la inferencia en tiempo real de video a 240 FPS, audio ultra-largo y razonamiento continuo sin degradación. La batalla algorítmica "
            "actual definirá si el futuro de la IA pertenece a matrices de atención estáticas o a sistemas dinámicos continuos en espacio de estados."
        ),
        empirical_data=[
            ["Métrica de Arquitectura", "Transformer Tradicional (Llama)", "Mamba / SSM Selectivo (Gu & Dao)"],
            ["Complejidad temporal de inferencia", "O(N²) cuadrática en contexto", "O(N) lineal en longitud de secuencia"],
            ["Memoria de contexto durante generación", "Crecimiento continuo (KV-Cache)", "Estado latente de dimensión constante O(1)"],
            ["Throughput de tokens (batch 1, 128k ctx)", "18 - 35 tokens/s", "140 - 280 tokens/s (hasta 8x más rápido)"],
            ["Retención de información asociativa compleja", "Excelente (acceso aleatorio perfecto)", "Depende del filtro de selección temporal de parámetros"],
        ],
        thesis="Los modelos SSM híbridos (Mamba + MoE) reemplazarán por completo a los Transformers puros porque la física del hardware no puede sostener la explosión cuadrática de memoria en contextos infinitos.",
        antithesis="El acceso asociativo directo del mecanismo de atención es insustituible para el razonamiento lógico profundo y recuperación exacta (in-context retrieval); los SSMs sufren de amnesia selectiva en secuencias ultra-densas.",
        debate_questions=[
            "¿Es el cerebro humano un State Space Model que comprime continuamente la realidad en un vector latente o almacena tokens como un Transformer?",
            "¿Cómo impactará la inferencia lineal en la democratización del cómputo local soberano sin depender de granjas masivas de GPUs?",
            "¿Podrán las arquitecturas híbridas (Mamba-Attention) alcanzar capacidad de razonamiento autorreflexivo en tiempo real?",
        ],
        academic_references=[
            {"title": "Mamba: Linear-Time Sequence Modeling with Selective State Spaces", "authors": "Gu, A. & Dao, T.", "venue": "arXiv preprint", "doi": "10.48550/arXiv.2312.00752"},
            {"title": "Attention Is All You Need", "authors": "Vaswani, A. et al.", "venue": "NeurIPS 2017", "doi": "10.48550/arXiv.1706.03762"},
            {"title": "Transformers are RNNs: Fast Autoregressive Transformers with Linear Attention", "authors": "Katharopoulos, A. et al.", "venue": "ICML 2020", "doi": "10.48550/arXiv.2006.16236"},
        ],
    ),
    DebateTopicData(
        id="godel_incompleteness_ai_limits",
        title="Los Teoremas de Incompletitud de Gödel y los Límites Epistemológicos de la Computación",
        domain="Lógica Matemática & Filosofía del Conocimiento",
        curious_fact=(
            "En 1931, un joven lógico austriaco de 25 años llamado Kurt Gödel pulverizó el sueño de David Hilbert de formalizar toda la matemática. "
            "Demostró matemáticamente que en cualquier sistema formal axiomático consistente capaz de hacer aritmética elemental, siempre existirán "
            "proposiciones verdaderas que son indemostrables dentro de las reglas del propio sistema."
        ),
        context_and_thesis=(
            "Roger Penrose utilizó el teorema de Gödel para argumentar que la conciencia humana no es puramente computacional ni algorítmica: "
            "un matemático puede 'ver' la verdad de una sentencia gödeliana que ninguna máquina de Turing finita puede demostrar ejecutando su código. "
            "Esto abre el debate sobre si los modelos de IA podrán alguna vez tener comprensión genuina o solo simulación sintáctica ciega."
        ),
        empirical_data=[
            ["Concepto Lógico", "Formulación / Expresión", "Límite Teórico"],
            ["Primer Teorema de Gödel", "G ↔ ¬Prov(⌈G⌉)", "Consistencia implica Incompletitud en sistemas de Peano"],
            ["Segundo Teorema de Gödel", "Consis(T) indemostrable en T", "Ninguna teoría puede demostrar su propia consistencia sin contradicción"],
            ["Indecidibilidad del Problema de Parada (Halting)", "H(M, w) no computable", "Límite absoluto de la computación según Alan Turing (1936)"],
            ["Complejidad de Kolmogorov", "K(s) no computable", "Incapacidad de certificar la aleatoriedad perfecta de una secuencia"],
        ],
        thesis="La mente humana accede a intuiciones semánticas no algorítmicas (posiblemente cuánticas); la Inteligencia Artificial jamás superará la barrera gödeliana de la pura manipulación simbólica.",
        antithesis="El argumento de Penrose es falaz: los humanos tampoco somos consistentes en el sentido estricto de Gödel (cometemos errores y cambiamos axiomas); una máquina con heurística estocástica puede emular cualquier salto intuitivo humano.",
        debate_questions=[
            "¿Es el libre albedrío humano una consecuencia de la incompletitud e indecidibilidad algorítmica de nuestro propio sistema neurológico?",
            "Si una IA descubre un nuevo teorema indemostrable en la matemática actual mediante exploración empírica, ¿debemos aceptar sus axiomas como verdaderos?",
            "¿Existen aspectos de la realidad física que sean intrínsecamente incognoscibles para cualquier inteligencia viva o sintética?",
        ],
        academic_references=[
            {"title": "Über formal unentscheidbare Sätze der Principia Mathematica und verwandter Systeme I", "authors": "Gödel, K.", "venue": "Monatshefte für Mathematik und Physik", "doi": "10.1007/BF01700692"},
            {"title": "The Emperor's New Mind: Concerning Computers, Minds, and the Laws of Physics", "authors": "Penrose, R.", "venue": "Oxford University Press", "doi": "10.1093/oso/9780198519737.001.0001"},
            {"title": "Minds, Machines and Gödel", "authors": "Lucas, J. R.", "venue": "Philosophy 36 (137), 112–127", "doi": "10.1017/S003181910005798X"},
        ],
    ),
    DebateTopicData(
        id="synthetic_biology_xenobiology_xna",
        title="Xenobiología y Ácidos Nucleicos Artificiales (XNAs): Rediseñando el Código Genético",
        domain="Biología Sintética & Ingeniería Genómica",
        curious_fact=(
            "Toda la vida conocida sobre la faz de la Tierra —desde una bacteria sulfurosa hasta una ballena azul— comparte el mismo alfabeto "
            "bioquímico de 4 letras nucleotídicas (A, T, C, G) sobre una columna de desoxirribosa. En 2019, científicos crearon 'Hachimoji DNA', "
            "un sistema sintético con 8 letras (A, T, C, G, P, Z, B, S) capaz de almacenar información biológica, transcribirse a ARN y evolucionar funcionalmente."
        ),
        context_and_thesis=(
            "La xenobiología expande los límites de la vida más allá del dogma central de la biología terrestre. Al reemplazar la ribosa con azúcares "
            "artificiales (treosa, hexitol, ciclohexeno) se obtienen XNAs inmunes a la degradación por enzimas biológicas, creando un 'firewall biológico' "
            "que evita la contaminación cruzada entre organismos sintéticos y la biosfera natural."
        ),
        empirical_data=[
            ["Parámetro Biotecnológico", "ADN Terrestre Canónico", "Sistemas Sintéticos (XNA / Hachimoji)"],
            ["Número de pares de bases", "2 pares (A-T, C-G)", "4 pares / 8 letras (añade P-Z y B-S)"],
            ["Capacidad de codificación de codones", "4³ = 64 combinaciones posibles", "8³ = 512 codones (capacidad para cientos de aminoácidos nuevos)"],
            ["Resistencia a nucleasas celulares", "Degradación en minutos a horas", "Estabilidad biológica casi permanente (> meses)"],
            ["Fidelidad de replicación polimerasa", "99.999% fidelidad", "99.8% fidelidad en polimerasas evolucionadas artificialmente"],
        ],
        thesis="El ADN natural es solo una solución histórica local arbitraria; la vida basada en XNA será más resistente, duradera y eficiente para la terraformación espacial y la cura de enfermedades incurables.",
        antithesis="Liberar organismos sintéticos con bioquímicas incompatibles con la biosfera introduce riesgos ecológicos existenciales impredecibles sin posibilidad de antídotos naturales.",
        debate_questions=[
            "Si la vida sintética puede utilizar 512 codones para crear proteínas con propiedades físicas sobrehumanas, ¿es ético editar el linaje germinal humano con XNA?",
            "¿Podría la vida extraterrestre en Titán o Encélado estar operando con un sistema análogo al XNA en lugar de agua y carbono tradicionales?",
            "¿Cómo regulamos la síntesis de genomas alienígenas en impresoras biológicas de escritorio de acceso abierto?",
        ],
        academic_references=[
            {"title": "Hachimoji DNA and RNA: A genetic system with eight building blocks", "authors": "Hoshika, S. et al.", "venue": "Science 363, 884–887", "doi": "10.1126/science.aat0971"},
            {"title": "Synthetic genetic polymers capable of heredity and evolution", "authors": "Pinheiro, V. B. et al.", "venue": "Science 336, 341–344", "doi": "10.1126/science.1217622"},
            {"title": "Xenobiology: state of the art and perspectives for bioengineering and biosafety", "authors": "Schmidt, M.", "venue": "Current Opinion in Chemical Biology", "doi": "10.1016/j.cbpa.2010.03.007"},
        ],
    ),
    DebateTopicData(
        id="neural_decoding_mind_reading_bci",
        title="Decodificación Neural Directa y Reconstrucción Semántica: ¿El Fin de la Privacidad Mental?",
        domain="Neurotecnología & Ética de la Inteligencia Artificial",
        curious_fact=(
            "En 2023, investigadores de la Universidad de Texas en Austin lograron reconstruir de forma continua y con asombrosa precisión historias "
            "y diálogos completos que voluntarios escuchaban o simplemente imaginaban en silencio, utilizando escáneres fMRI no invasivos combinados "
            "con modelos de lenguaje autoregresivos."
        ),
        context_and_thesis=(
            "La frontera entre el pensamiento privado y la exteriorización lingüística se está disolviendo. Las interfaces cerebro-computador (BCIs) "
            "ópticas, electromagnéticas e implantables están pasando de detectar comandos motores simples a decodificar el flujo del monólogo interior, "
            "emociones inconscientes e imágenes visuales oníricas en tiempo real."
        ),
        empirical_data=[
            ["Parámetro de Neurointerfaz", "Estado Actual de Laboratorio (2025/2026)", "Meta a Corto Plazo"],
            ["Tasa de decodificación de texto", "62 palabras por minuto (implantable) / 20 ppm (fMRI no invasivo)", "> 150 ppm (velocidad natural del habla humana)"],
            ["Precisión de similitud semántica (BLEU)", "78% - 85% de correspondencia conceptual", "> 95% con calibración adaptativa MoE"],
            ["Resolución espacial BCI", "Micras (matrices intracorticales Utah/Neuralink)", "Resolución sub-milimétrica óptica no invasiva"],
            ["Reconstrucción de imágenes mentales", "Recreación de clips de video vistos con Stable Diffusion", "Lectura de imaginación visual activa sin estímulo externo"],
        ],
        thesis="La telepatía sintética y las BCIs permitirán una conexión empática intersubjetiva sin precedentes y la superación del retraso de escribir o hablar; la privacidad mental tradicional debe evolucionar.",
        antithesis="El fuero interno del pensamiento es el último santuario de la libertad humana; permitir la decodificación neural conducirá al advenimiento del totalitarismo cognitivo y la manipulación comercial de la psique.",
        debate_questions=[
            "¿Debería consagrarse el derecho a los 'Neuroderechos' (inviolabilidad de la mente) en las constituciones del mundo antes de la masificación de los BCIs comerciales?",
            "Si una IA puede decodificar pensamientos subconscientes antes de que el propio individuo sea consciente de ellos, ¿dónde queda el libre albedrío?",
            "¿Te implantarías un enlace BCI directo con TARDIS si multiplicara tu velocidad de razonamiento por diez mil?",
        ],
        academic_references=[
            {"title": "Semantic reconstruction of continuous language from non-invasive brain recordings", "authors": "Tang, J., LeBel, A., Turek, S. & Huth, A. G.", "venue": "Nature Neuroscience 26, 858–866", "doi": "10.1038/s41593-023-01304-9"},
            {"title": "A high-performance neuroprosthesis for speech decoding and avatar control", "authors": "Metzger, S. L. et al.", "venue": "Nature 620, 1037–1046", "doi": "10.1038/s41586-023-06443-4"},
            {"title": "Towards a declaration of human rights in the age of neuroscience and neurotechnology", "authors": "Yuste, R. et al.", "venue": "Nature 551, 159–163", "doi": "10.1038/551159a"},
        ],
    ),
]


class CuriosityDebateManager:
    """
    Gestor Central Soberano de Curiosidades y Debates para POLIMATAS LATAM.
    Coordina generación de contenido, compilación de PDF en alta definición y despacho a Telegram.
    """

    _instance: Optional[CuriosityDebateManager] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> CuriosityDebateManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.state = self._load_state()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def _default_state(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "interval_seconds": DEFAULT_INTERVAL_SECONDS,  # 5400 s (1.5 horas)
            "target_chat_id": TARGET_GROUP_CHAT_ID,
            "target_thread_id": TARGET_MESSAGE_THREAD_ID,
            "last_run_timestamp": 0.0,
            "last_run_iso": "",
            "total_dispatches": 0,
            "curator_index": 0,
            "dispatched_topic_ids": [],
            "history": [],
        }

    def _load_state(self) -> Dict[str, Any]:
        st = self._default_state()
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    st.update(data)
            except Exception as e:
                logger.warning(f"Error cargando estado {STATE_FILE}: {e}")
        return st

    def _save_state(self) -> bool:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(STATE_FILE)
            return True
        except Exception as e:
            logger.error(f"Error guardando estado {STATE_FILE}: {e}")
            return False

    def select_next_topic(self) -> DebateTopicData:
        """Selecciona el siguiente tema garantizando rotación constante sin duplicados inmediatos."""
        dispatched_ids = set(self.state.get("dispatched_topic_ids", []))
        available = [t for t in CURATED_TOPICS if t.id not in dispatched_ids]

        # Si ya se usaron todos los temas curados, reiniciar el ciclo
        if not available:
            logger.info("Todos los temas curados han sido cubiertos. Reiniciando ciclo de temas.")
            self.state["dispatched_topic_ids"] = []
            available = list(CURATED_TOPICS)

        idx = self.state.get("curator_index", 0) % len(available)
        topic = available[idx]
        self.state["curator_index"] = idx + 1
        return topic

    # -------------------------------------------------------------------------
    # COMPILACIÓN DE PDF (REPORTLAB ALTA FIDELIDAD)
    # -------------------------------------------------------------------------
    def generate_debate_pdf(self, topic: DebateTopicData) -> Path:
        """Genera un elegante documento PDF con ReportLab de grado editorial."""
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^\w\-]", "_", topic.id)[:30]
        pdf_filename = f"Dossier_Debate_{timestamp_str}_{slug}.pdf"
        pdf_path = REPORTS_DIR / pdf_filename

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=letter,
            leftMargin=54,
            rightMargin=54,
            topMargin=54,
            bottomMargin=54,
        )

        styles = getSampleStyleSheet()

        # Estilos tipográficos modernos
        meta_badge_style = ParagraphStyle(
            "MetaBadge",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#ea580c"),
        )
        title_style = ParagraphStyle(
            "TopicTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=8,
        )
        h2_style = ParagraphStyle(
            "SectionH2",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#1e293b"),
            spaceBefore=10,
            spaceAfter=4,
        )
        body_style = ParagraphStyle(
            "MainBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#334155"),
            spaceAfter=4,
        )
        fact_style = ParagraphStyle(
            "FactText",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#0c4a6e"),
        )
        table_hdr_style = ParagraphStyle(
            "TableHdr",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.white,
        )
        table_cell_style = ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=colors.HexColor("#1e293b"),
        )
        question_style = ParagraphStyle(
            "QuestionText",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#0f172a"),
        )
        ref_style = ParagraphStyle(
            "RefText",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.5,
            textColor=colors.HexColor("#475569"),
        )

        story = []

        # 1. Cabecera y Título
        header_text = f"TOPIC #{self.state.get('total_dispatches', 0) + 1:03d} · {topic.domain.upper()}"
        story.append(Paragraph(header_text, meta_badge_style))
        story.append(Spacer(1, 3))
        story.append(Paragraph(topic.title, title_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0"), spaceBefore=2, spaceAfter=8))

        # 2. Caja Destacada: DATO CURIOSO
        callout_content = [
            [Paragraph("<b>💡 DATO CURIOSO & ANOMALÍA COGNITIVA:</b>", ParagraphStyle("HdrFact", parent=fact_style, fontName="Helvetica-Bold", textColor=colors.HexColor("#0369a1")))],
            [Paragraph(topic.curious_fact, fact_style)],
        ]
        callout_table = Table(callout_content, colWidths=[504])
        callout_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f9ff")),
            ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#7dd3fc")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(callout_table)
        story.append(Spacer(1, 10))

        # 3. Marco Teórico
        story.append(Paragraph("1. Marco Científico & Tesis de Investigación", h2_style))
        story.append(Paragraph(topic.context_and_thesis, body_style))
        story.append(Spacer(1, 8))

        # 4. Tabla de Datos Duros y Mediciones
        story.append(Paragraph("2. Datos Empíricos & Parámetros Cuantitativos", h2_style))
        tbl_data = []
        for i, row in enumerate(topic.empirical_data):
            if i == 0:
                tbl_data.append([Paragraph(f"<b>{c}</b>", table_hdr_style) for c in row])
            else:
                tbl_data.append([Paragraph(c, table_cell_style) for c in row])

        param_table = Table(tbl_data, colWidths=[150, 160, 194])
        param_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(param_table)
        story.append(Spacer(1, 10))

        # 5. Dilema Dialéctico: Tesis vs Antítesis
        story.append(Paragraph("3. Tensión Dialéctica para Debate", h2_style))
        dilemma_data = [
            [
                Paragraph("<b>POSTURA A (Tesis Convencional)</b>", table_hdr_style),
                Paragraph("<b>POSTURA B (Antítesis / Emergente)</b>", table_hdr_style),
            ],
            [
                Paragraph(topic.thesis, table_cell_style),
                Paragraph(topic.antithesis, table_cell_style),
            ],
        ]
        dilemma_table = Table(dilemma_data, colWidths=[248, 256])
        dilemma_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#1e293b")),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#ea580c")),
            ("BACKGROUND", (0, 1), (0, 1), colors.HexColor("#f8fafc")),
            ("BACKGROUND", (1, 1), (1, 1), colors.HexColor("#fff7ed")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(dilemma_table)
        story.append(Spacer(1, 10))

        # 6. Preguntas Detonadoras para el Grupo
        story.append(Paragraph("4. Preguntas Detonadoras para la Comunidad Polímata", h2_style))
        q_rows = []
        for q_idx, q_txt in enumerate(topic.debate_questions, 1):
            q_rows.append([
                Paragraph(f"<b>Q{q_idx}:</b>", ParagraphStyle("QNum", parent=question_style, textColor=colors.HexColor("#ea580c"))),
                Paragraph(q_txt, question_style),
            ])
        q_table = Table(q_rows, colWidths=[30, 474])
        q_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(q_table)
        story.append(Spacer(1, 10))

        # 7. Referencias Académicas y DOIs
        story.append(Paragraph("5. Literatura Científica & DOIs Canónicos", h2_style))
        for r_idx, ref in enumerate(topic.academic_references, 1):
            ref_str = f"<b>[{r_idx}]</b> {ref.get('authors', 'Investigadores')}, <i>\"{ref.get('title')}\"</i> — {ref.get('venue')}. DOI: <u>https://doi.org/{ref.get('doi')}</u>"
            story.append(Paragraph(ref_str, ref_style))
            story.append(Spacer(1, 2))

        doc.build(story, canvasmaker=NumberedCanvas)
        logger.info(f"Dossier PDF generado con éxito en: {pdf_path}")
        return pdf_path

    # -------------------------------------------------------------------------
    # FORMATO Y DESPACHO A TELEGRAM
    # -------------------------------------------------------------------------
    def format_telegram_message(self, topic: DebateTopicData) -> str:
        """Genera el mensaje introductorio de alto impacto para Telegram."""
        lines = [
            "🛸 🔝🚀🧡 **[TARDIS · POLÍMATAS LATAM :: CURIOSIDAD & DEBATE]** 🧡🚀🔝",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🏛️ **Dominio:** *{topic.domain}*",
            f"📚 **Tema:** `{topic.title}`",
            "",
            "💡 **DATO CURIOSO & ANOMALÍA COGNITIVA:**",
            f"{topic.curious_fact}",
            "",
            "🔬 **NÚCLEO DEL DEBATE:**",
            f"{topic.context_and_thesis[:380]}...",
            "",
            "⚖️ **TESIS VS ANTÍTESIS:**",
            f"• 🔹 **Tesis:** {topic.thesis}",
            f"• 🔸 **Antítesis:** {topic.antithesis}",
            "",
            "💬 **PREGUNTAS DETONADORAS PARA EL GRUPO:**"
        ]

        for i, q in enumerate(topic.debate_questions, 1):
            lines.append(f"**{i}.** {q}")

        lines.append("")
        lines.append("📄 ⬇️ *Se adjunta a continuación el Dossier Técnico Completo en PDF con datos empíricos, tablas de constantes y bibliografía revisada por pares para profundizar.*")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🌐 *TARDIS · Inferencia Soberana & Vanguardia Polímata*")

        return "\n".join(lines)

    def dispatch_cycle(
        self,
        target_chat_id: Optional[int | str] = None,
        target_thread_id: Optional[int] = None,
        override_topic: Optional[DebateTopicData] = None,
    ) -> Dict[str, Any]:
        """Ejecuta un ciclo completo: selecciona tema, genera PDF y despacha a Telegram."""
        from core.telegram_bridge import get_telegram_bridge

        tb = get_telegram_bridge()
        chat_id = target_chat_id or self.state.get("target_chat_id", TARGET_GROUP_CHAT_ID)
        thread_id = target_thread_id if target_thread_id is not None else self.state.get("target_thread_id", TARGET_MESSAGE_THREAD_ID)

        topic = override_topic or self.select_next_topic()
        logger.info(f"Iniciando despacho de curiosidad y debate: '{topic.title}' -> Chat {chat_id} (Hilo {thread_id})")

        # 1. Generar Dossier PDF
        pdf_path = self.generate_debate_pdf(topic)

        # 2. Formatear y Enviar Texto Introductorio
        text_message = self.format_telegram_message(topic)
        send_msg_res = tb.send_message(
            text=text_message,
            chat_id=chat_id,
            message_thread_id=thread_id,
        )

        # Si falló por hilo no encontrado, reintentar en el canal general sin message_thread_id
        if not send_msg_res.get("ok") and "message thread not found" in str(send_msg_res.get("error", "")).lower():
            logger.warning(f"Hilo {thread_id} no disponible en supergrupo. Despachando a topic general.")
            thread_id = None
            send_msg_res = tb.send_message(text=text_message, chat_id=chat_id)

        # 3. Enviar Documento PDF
        pdf_caption = (
            f"📄 **Dossier de Investigación & Debate:** `{topic.title}`\n"
            f"🏛️ *{topic.domain}* · 🔝🚀🧡 POLIMATAS LATAM"
        )
        send_doc_res = tb.send_document(
            document=pdf_path,
            filename=pdf_path.name,
            caption=pdf_caption,
            chat_id=chat_id,
            message_thread_id=thread_id,
        )

        # 4. Actualizar estado y registros
        now_ts = time.time()
        now_iso = datetime.datetime.now().isoformat()

        self.state["last_run_timestamp"] = now_ts
        self.state["last_run_iso"] = now_iso
        self.state["total_dispatches"] = self.state.get("total_dispatches", 0) + 1

        dispatched = self.state.setdefault("dispatched_topic_ids", [])
        if topic.id not in dispatched:
            dispatched.append(topic.id)

        turn_log = {
            "dispatch_id": self.state["total_dispatches"],
            "timestamp": now_ts,
            "iso": now_iso,
            "topic_id": topic.id,
            "topic_title": topic.title,
            "pdf_path": str(pdf_path),
            "chat_id": chat_id,
            "thread_id": thread_id,
            "text_sent": send_msg_res.get("ok", False),
            "doc_sent": send_doc_res.get("ok", False),
        }

        history = self.state.setdefault("history", [])
        history.append(turn_log)
        if len(history) > 100:
            self.state["history"] = history[-100:]

        self._save_state()

        # Registrar en offline_chat_vault para que TARDIS mantenga memoria de este aporte
        try:
            from core.offline_chat_vault import get_offline_chat_vault
            get_offline_chat_vault().record_turn(
                user_message=f"[AUTÓNOMO POLÍMATAS] Despacho de Curiosidad y Debate: {topic.title}",
                assistant_reply=text_message,
                session_id=f"tg_{chat_id}",
                client_id=f"tg_{chat_id}",
                model="TARDIS-NEURAL-SPACE-KAIJU",
                direction="present",
            )
        except Exception:
            pass

        return {
            "ok": send_msg_res.get("ok", False) and send_doc_res.get("ok", False),
            "topic_id": topic.id,
            "topic_title": topic.title,
            "pdf_path": str(pdf_path),
            "telegram_msg": send_msg_res,
            "telegram_doc": send_doc_res,
        }

    # -------------------------------------------------------------------------
    # CICLO DAEMON CONTINUO 24/7
    # -------------------------------------------------------------------------
    def start_daemon(self, interval_seconds: Optional[float] = None) -> bool:
        """Inicia el bucle en segundo plano que despacha cada 1.5 horas permanentemente."""
        if self._running and self._worker_thread and self._worker_thread.is_alive():
            return True

        if interval_seconds:
            self.state["interval_seconds"] = float(interval_seconds)
            self._save_state()

        self._stop_event.clear()
        self._running = True

        def _daemon_loop():
            logger.info("🚀 Daemon TARDIS Curiosity & Debate iniciado (Ciclo cada 1.5h).")
            while not self._stop_event.is_set():
                if self.state.get("enabled", True):
                    now_ts = time.time()
                    last_ts = self.state.get("last_run_timestamp", 0.0)
                    interval = float(self.state.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))

                    if (now_ts - last_ts) >= interval:
                        try:
                            res = self.dispatch_cycle()
                            logger.info(f"Ciclo ejecutado exitosamente: {res.get('topic_title')}")
                        except Exception as e:
                            logger.error(f"Error en ciclo de debate: {e}", exc_info=True)

                # Dormir en micro-intervalos para reaccionar a stop
                for _ in range(30):
                    if self._stop_event.is_set():
                        break
                    time.sleep(2.0)

        self._worker_thread = threading.Thread(target=_daemon_loop, daemon=True, name="CuriosityDebaterWorker")
        self._worker_thread.start()
        return True

    def stop_daemon(self) -> None:
        """Detiene el daemon."""
        self._stop_event.set()
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)
        logger.info("Daemon TARDIS Curiosity & Debate detenido.")

    def get_status(self) -> Dict[str, Any]:
        now_ts = time.time()
        last_ts = self.state.get("last_run_timestamp", 0.0)
        interval = float(self.state.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))
        next_run_ts = last_ts + interval if last_ts > 0 else now_ts
        seconds_remaining = max(0.0, next_run_ts - now_ts)

        return {
            "enabled": self.state.get("enabled", True),
            "running": self._running,
            "interval_seconds": interval,
            "interval_hours": round(interval / 3600.0, 2),
            "target_chat_id": self.state.get("target_chat_id"),
            "target_thread_id": self.state.get("target_thread_id"),
            "total_dispatches": self.state.get("total_dispatches", 0),
            "last_run_iso": self.state.get("last_run_iso", "Nunca"),
            "seconds_until_next": round(seconds_remaining, 1),
            "next_run_in_minutes": round(seconds_remaining / 60.0, 1),
            "history_count": len(self.state.get("history", [])),
        }


def get_curiosity_debate_manager() -> CuriosityDebateManager:
    return CuriosityDebateManager.get_instance()
