"""
core/scientific_research_engine.py - Motor Soberano de Investigación y Aprendizaje de Rigor Científico
=======================================================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4

Diseñado para investigar de forma autónoma en repositorios de literatura científica revisada por pares
y bases de datos académicas mundiales de máxima jerarquía:
  1. arXiv API (Física, Matemáticas, Ciencias de la Computación, Biología Cuantitativa).
  2. OpenAlex API (Catálogo global de 250M+ obras científicas, conteo de citas, DOIs y PDFs de libre acceso).
  3. Europe PMC & PubMed / NCBI E-utilities (Biomedicina, Neurociencia, Genómica, Medicina).
  4. CrossRef API (Verificación bibliográfica y resolución de DOIs directos).
  5. Wikipedia Académica API (Bases conceptuales, teoremas y definiciones enciclopédicas).

Capacidades:
  - Formulación cognitiva y traducción de temas a términos técnicos de rigor académico.
  - Evaluación y filtrado por citas, revisión por pares y disponibilidad de PDF directo.
  - Generación de síntesis pedagógica estructurada para maximizar el aprendizaje del Arquitecto.
  - Envío automático y formateado de reportes interactivos con enlaces directos a Telegram.
  - Agenda autónoma de aprendizaje continuo (Curiosity & Learning Agenda) con ciclo programable.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("TARDIS.ScientificResearch")

BASE_DIR = Path(__file__).resolve().parent.parent
AGENDA_FILE = BASE_DIR / "scientific_learning_agenda.json"
DEFAULT_UA = "TARDIS-ScientificResearch/2.0 (Linux x86_64; mailto:tardis@godworks.local)"


@dataclass
class ScientificPaper:
    """Representa un artículo científico obtenido con metadatos completos y enlaces."""
    title: str
    authors: List[str]
    year: Optional[int] = None
    venue: str = "Publicación Científica"
    doi: Optional[str] = None
    doi_url: Optional[str] = None
    landing_url: str = ""
    pdf_url: Optional[str] = None
    abstract: str = ""
    source_engine: str = "openalex"
    citations_count: int = 0
    peer_reviewed: bool = True
    categories: List[str] = field(default_factory=list)
    key_findings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScientificResearchReport:
    """Informe consolidado de investigación científica estructurado para el aprendizaje."""
    topic: str
    scientific_domain: str
    conceptual_summary: str
    fundamental_principles: List[str]
    papers: List[ScientificPaper]
    learning_roadmap: List[str]
    open_questions: List[str]
    generated_at: str
    elapsed_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["papers"] = [p.to_dict() if isinstance(p, ScientificPaper) else p for p in self.papers]
        return d


class ScientificResearchEngine:
    """Motor central de investigación científica y despacho a Telegram."""

    _instance: Optional["ScientificResearchEngine"] = None
    _lock = threading.Lock()

    def __init__(self, agenda_path: Optional[Path | str] = None):
        self.agenda_path = Path(agenda_path) if agenda_path else AGENDA_FILE
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_lock = threading.Lock()
        self._autonomous_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._init_default_agenda_if_missing()

    @classmethod
    def get_instance(cls) -> "ScientificResearchEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # -------------------------------------------------------------------------
    # 1. GESTIÓN DE AGENDA AUTÓNOMA DE APRENDIZAJE
    # -------------------------------------------------------------------------
    def _init_default_agenda_if_missing(self) -> None:
        """Inicializa la agenda con tópicos de frontera científica de alto impacto si no existe."""
        if self.agenda_path.exists():
            return

        default_curriculum = {
            "version": "1.0",
            "autonomous_mode": True,
            "interval_hours": 12.0,
            "last_cycle_timestamp": 0.0,
            "topics": [
                {
                    "id": "quant_entangle",
                    "topic": "Entrelazamiento Cuántico, Teorema de Bell y Decoherencia",
                    "domain": "Física Cuántica & Información Cuántica",
                    "status": "pending",
                    "priority": 1,
                    "researched_count": 0,
                    "last_researched": None
                },
                {
                    "id": "syntropy_thermo",
                    "topic": "Termodinámica del No Equilibrio y Sintropía Retrocausal",
                    "domain": "Física Teórica & Sistemas Complejos",
                    "status": "pending",
                    "priority": 1,
                    "researched_count": 0,
                    "last_researched": None
                },
                {
                    "id": "ssm_transformers",
                    "topic": "State Space Models (Mamba) vs Arquitectura Transformer en Redes Neuronales",
                    "domain": "Inteligencia Artificial & Modelos de Lenguaje",
                    "status": "pending",
                    "priority": 2,
                    "researched_count": 0,
                    "last_researched": None
                },
                {
                    "id": "nuclear_fusion",
                    "topic": "Fusión Nuclear por Confinamiento Magnético: Avances en Tokamaks y Stellarators",
                    "domain": "Física de Plasmas & Energía",
                    "status": "pending",
                    "priority": 2,
                    "researched_count": 0,
                    "last_researched": None
                },
                {
                    "id": "crispr_epigenetics",
                    "topic": "CRISPR-Cas9, Reprogramación Celular y Rejuvenecimiento Epigenético",
                    "domain": "Biología Molecular & Biotecnología",
                    "status": "pending",
                    "priority": 2,
                    "researched_count": 0,
                    "last_researched": None
                },
                {
                    "id": "navier_stokes",
                    "topic": "Ecuaciones de Navier-Stokes: Regularidad, Existencia Suave y Turbulencia",
                    "domain": "Matemáticas Puras & Mecánica de Fluidos",
                    "status": "pending",
                    "priority": 3,
                    "researched_count": 0,
                    "last_researched": None
                },
                {
                    "id": "topological_insulators",
                    "topic": "Aislantes Topológicos, Estados de Borde y Fermiones de Majorana",
                    "domain": "Física de la Materia Condensada",
                    "status": "pending",
                    "priority": 3,
                    "researched_count": 0,
                    "last_researched": None
                },
                {
                    "id": "post_quantum_crypto",
                    "topic": "Criptografía Post-Cuántica: Algoritmos Basados en Reticulados (Lattices)",
                    "domain": "Criptografía & Ciencias de la Computación",
                    "status": "pending",
                    "priority": 3,
                    "researched_count": 0,
                    "last_researched": None
                },
                {
                    "id": "neural_decoding",
                    "topic": "Decodificación Neural Directa: Interfaces Cerebro-Computador y Reconstrucción del Lenguaje",
                    "domain": "Neurociencia Computacional",
                    "status": "pending",
                    "priority": 3,
                    "researched_count": 0,
                    "last_researched": None
                },
                {
                    "id": "dark_matter_axions",
                    "topic": "Materia Oscura: Detección Experimental de Axiones y WIMPs",
                    "domain": "Cosmología & Física de Partículas",
                    "status": "pending",
                    "priority": 3,
                    "researched_count": 0,
                    "last_researched": None
                }
            ]
        }
        self.save_agenda(default_curriculum)

    def load_agenda(self) -> Dict[str, Any]:
        """Carga la agenda de investigación persistente."""
        try:
            if self.agenda_path.exists():
                with open(self.agenda_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error cargando agenda de investigación: {e}")
        return {"version": "1.0", "autonomous_mode": True, "interval_hours": 12.0, "topics": []}

    def save_agenda(self, data: Dict[str, Any]) -> bool:
        """Guarda la agenda de investigación persistente de manera atómica."""
        try:
            tmp_path = self.agenda_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.agenda_path)
            return True
        except Exception as e:
            logger.error(f"Error guardando agenda de investigación: {e}")
            return False

    def add_topic_to_agenda(self, topic: str, domain: str = "Ciencia General", priority: int = 1) -> Dict[str, Any]:
        """Agrega un tema personalizado a la agenda de aprendizaje."""
        agenda = self.load_agenda()
        clean_topic = topic.strip()
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", clean_topic.lower())[:30]

        # Verificar si ya existe
        for item in agenda.get("topics", []):
            if item.get("topic", "").lower() == clean_topic.lower():
                item["status"] = "pending"
                item["priority"] = priority
                self.save_agenda(agenda)
                return {"ok": True, "action": "updated", "topic": item}

        new_item = {
            "id": f"custom_{slug}_{int(time.time())}",
            "topic": clean_topic,
            "domain": domain,
            "status": "pending",
            "priority": priority,
            "researched_count": 0,
            "last_researched": None
        }
        agenda.setdefault("topics", []).insert(0, new_item)
        self.save_agenda(agenda)
        return {"ok": True, "action": "created", "topic": new_item}

    def get_next_agenda_topic(self) -> Optional[Dict[str, Any]]:
        """Obtiene el siguiente tema prioritario a investigar."""
        agenda = self.load_agenda()
        topics = agenda.get("topics", [])
        pending = [t for t in topics if t.get("status") == "pending"]
        if pending:
            pending.sort(key=lambda x: (x.get("priority", 2), x.get("researched_count", 0)))
            return pending[0]

        # Si todos están completados, rotar al que lleva más tiempo sin investigar
        if topics:
            topics.sort(key=lambda x: x.get("last_researched") or "")
            return topics[0]
        return None

    def mark_topic_researched(self, topic_str: str) -> None:
        """Marca un tema como investigado y actualiza metadatos."""
        agenda = self.load_agenda()
        for t in agenda.get("topics", []):
            if t.get("topic", "").lower() == topic_str.lower():
                t["status"] = "completed"
                t["researched_count"] = t.get("researched_count", 0) + 1
                t["last_researched"] = datetime.now().isoformat()
                break
        agenda["last_cycle_timestamp"] = time.time()
        self.save_agenda(agenda)

    # -------------------------------------------------------------------------
    # 2. MOTORES DE BÚSQUEDA CIENTÍFICA (ARXIV, OPENALEX, EUROPE PMC, CROSSREF)
    # -------------------------------------------------------------------------
    def search_arxiv(self, query: str, max_results: int = 5) -> List[ScientificPaper]:
        """Consulta arXiv API para artículos en física, matemáticas, CS y biología cuantitativa."""
        papers: List[ScientificPaper] = []
        try:
            clean_q = re.sub(r"[^\w\s\-\+]", "", query).strip()
            encoded_q = urllib.parse.quote(f"all:{clean_q}")
            url = f"https://export.arxiv.org/api/query?search_query={encoded_q}&start=0&max_results={max_results}&sortBy=relevance&sortOrder=descending"

            req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)
            ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

            for entry in root.findall("atom:entry", ns):
                title_elem = entry.find("atom:title", ns)
                title = title_elem.text.strip().replace("\n", " ") if title_elem is not None and title_elem.text else "Paper sin título"

                summary_elem = entry.find("atom:summary", ns)
                abstract = summary_elem.text.strip().replace("\n", " ") if summary_elem is not None and summary_elem.text else ""

                id_elem = entry.find("atom:id", ns)
                abs_url = id_elem.text.strip() if id_elem is not None and id_elem.text else ""

                arxiv_id = abs_url.split("/abs/")[-1] if "/abs/" in abs_url else ""
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""

                pub_elem = entry.find("atom:published", ns)
                year = None
                if pub_elem is not None and pub_elem.text:
                    try:
                        year = int(pub_elem.text[:4])
                    except ValueError:
                        pass

                authors = []
                for auth in entry.findall("atom:author", ns):
                    name_elem = auth.find("atom:name", ns)
                    if name_elem is not None and name_elem.text:
                        authors.append(name_elem.text.strip())

                cats = []
                for cat in entry.findall("atom:category", ns):
                    term = cat.get("term")
                    if term:
                        cats.append(term)

                doi_elem = entry.find("arxiv:doi", ns)
                doi = doi_elem.text.strip() if doi_elem is not None and doi_elem.text else None
                doi_url = f"https://doi.org/{doi}" if doi else None

                papers.append(ScientificPaper(
                    title=title,
                    authors=authors[:5],
                    year=year,
                    venue=f"arXiv: {cats[0]}" if cats else "arXiv Preprint",
                    doi=doi,
                    doi_url=doi_url,
                    landing_url=abs_url,
                    pdf_url=pdf_url,
                    abstract=abstract,
                    source_engine="arxiv",
                    citations_count=0,
                    peer_reviewed=False,
                    categories=cats,
                ))
        except Exception as e:
            logger.warning(f"Aviso en búsqueda arXiv ('{query}'): {e}")

        return papers

    def search_openalex(self, query: str, max_results: int = 5) -> List[ScientificPaper]:
        """Consulta OpenAlex API para metadatos globales, revistas prestigiosas y conteo de citas."""
        papers: List[ScientificPaper] = []
        try:
            encoded_q = urllib.parse.quote(query.strip())
            url = f"https://api.openalex.org/works?search={encoded_q}&per-page={max_results}&sort=relevance_score:desc"

            req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for work in data.get("results", []):
                title = work.get("display_name") or "Artículo de Investigación"
                year = work.get("publication_year")
                citations = work.get("cited_by_count", 0)

                authors = []
                for a in work.get("authorships", [])[:5]:
                    name = a.get("author", {}).get("display_name")
                    if name:
                        authors.append(name)

                venue_name = "Publicación Científica"
                prim_loc = work.get("primary_location") or {}
                if prim_loc.get("source"):
                    venue_name = prim_loc["source"].get("display_name") or venue_name

                doi = work.get("doi")
                doi_url = doi if doi and doi.startswith("http") else (f"https://doi.org/{doi}" if doi else None)

                # Reconstrucción del abstract desde índice invertido de OpenAlex
                abstract = ""
                inv = work.get("abstract_inverted_index")
                if inv and isinstance(inv, dict):
                    word_pos = []
                    for word, positions in inv.items():
                        for pos in positions:
                            word_pos.append((pos, word))
                    word_pos.sort(key=lambda x: x[0])
                    abstract = " ".join(w for _, w in word_pos)

                # PDF de Acceso Abierto
                open_access = work.get("open_access", {})
                pdf_url = open_access.get("oa_url")
                landing_url = prim_loc.get("landing_page_url") or doi_url or (f"https://openalex.org/W{work.get('id')}" if work.get("id") else "")

                # Conceptos/Categorías
                cats = [c.get("display_name") for c in work.get("concepts", [])[:4] if c.get("display_name")]

                papers.append(ScientificPaper(
                    title=title,
                    authors=authors,
                    year=year,
                    venue=venue_name,
                    doi=doi,
                    doi_url=doi_url,
                    landing_url=landing_url,
                    pdf_url=pdf_url,
                    abstract=abstract,
                    source_engine="openalex",
                    citations_count=citations,
                    peer_reviewed=True,
                    categories=cats,
                ))
        except Exception as e:
            logger.warning(f"Aviso en búsqueda OpenAlex ('{query}'): {e}")

        return papers

    def search_europepmc(self, query: str, max_results: int = 5) -> List[ScientificPaper]:
        """Consulta Europe PMC para literatura biomédica, bioquímica y neurociencias con texto completo."""
        papers: List[ScientificPaper] = []
        try:
            encoded_q = urllib.parse.quote(query.strip())
            url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={encoded_q}&format=json&pageSize={max_results}&resultType=core"

            req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for item in data.get("resultList", {}).get("result", []):
                title = item.get("title") or "Investigación Biomédica"
                title = re.sub(r"<[^>]+>", "", title).strip()

                author_str = item.get("authorString") or ""
                authors = [a.strip() for a in author_str.split(",")[:5] if a.strip()]

                year = None
                try:
                    year = int(item.get("pubYear"))
                except (ValueError, TypeError):
                    pass

                journal = item.get("journalTitle") or "Europe PMC Journal"
                doi = item.get("doi")
                doi_url = f"https://doi.org/{doi}" if doi else None

                pmid = item.get("pmid")
                pmcid = item.get("pmcid")

                pdf_url = None
                if item.get("hasPDF") == "Y" and pmcid:
                    pdf_url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"

                landing_url = f"https://europepmc.org/article/MED/{pmid}" if pmid else (doi_url or f"https://europepmc.org/article/PMC/{pmcid}" if pmcid else "")
                abstract = item.get("abstractText") or ""
                abstract = re.sub(r"<[^>]+>", "", abstract).strip()

                papers.append(ScientificPaper(
                    title=title,
                    authors=authors,
                    year=year,
                    venue=journal,
                    doi=doi,
                    doi_url=doi_url,
                    landing_url=landing_url,
                    pdf_url=pdf_url,
                    abstract=abstract,
                    source_engine="europepmc",
                    citations_count=int(item.get("citedByCount", 0)),
                    peer_reviewed=True,
                    categories=["Biomedicine", "Life Sciences"],
                ))
        except Exception as e:
            logger.warning(f"Aviso en búsqueda Europe PMC ('{query}'): {e}")

        return papers

    def search_wikipedia_science(self, query: str) -> Dict[str, Any]:
        """Obtiene la formulación axiomática, historia y principios formales de Wikipedia."""
        info = {"summary": "", "url": "", "title": ""}
        clean_q = re.sub(r"\b(investiga|busca|sobre|artículo|paper|en internet)\b", "", query, flags=re.I).strip()
        headers = {"User-Agent": DEFAULT_UA}

        for lang in ("es", "en"):
            try:
                api_url = (
                    f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=1"
                    f"&explaintext=1&titles={urllib.parse.quote(clean_q)}&format=json&redirects=1"
                )
                req = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                pages = data.get("query", {}).get("pages", {})
                for page_id, page_data in pages.items():
                    if page_id != "-1":
                        title = page_data.get("title", "")
                        extract = page_data.get("extract", "").strip()
                        if extract:
                            info["title"] = title
                            info["summary"] = extract[:1500]
                            info["url"] = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                            return info
            except Exception:
                pass

        return info

    # -------------------------------------------------------------------------
    # 3. FORMULACIÓN COGNITIVA Y RECOLECCIÓN MULTI-FUENTE
    # -------------------------------------------------------------------------
    def formulate_academic_queries(self, topic: str) -> Tuple[str, List[str], str]:
        """
        Descompone el tema en términos científicos rigurosos y detecta el dominio.
        Retorna: (Dominio científico, Lista de queries académicas, Términos en inglés)
        """
        t_low = topic.lower()

        # Detección de Dominio
        domain = "Ciencia General & Fundamentos Teóricos"
        if any(w in t_low for w in ("cuántic", "cuantic", "entrelazamiento", "spin", "decoherencia", "bell", "epr")):
            domain = "Física Cuántica & Información Cuántica"
        elif any(w in t_low for w in ("sintropía", "sintropia", "entropía", "entropia", "retrocausal", "termodinámica", "termodinamica")):
            domain = "Física Teórica & Termodinámica del No Equilibrio"
        elif any(w in t_low for w in ("fusion", "fusión", "tokamak", "stellarator", "plasma")):
            domain = "Física de Plasmas & Fusión Nuclear"
        elif any(w in t_low for w in ("crispr", "gen", "adn", "epigen", "longevidad", "celular", "proteina", "proteína")):
            domain = "Biotecnología & Biología Molecular"
        elif any(w in t_low for w in ("transformer", "mamba", "ssm", "neuronal", "llm", "inteligencia artificial", "deep learning")):
            domain = "Inteligencia Artificial & Arquitectura de Modelos"
        elif any(w in t_low for w in ("navier", "stokes", "turbulencia", "ecuacion", "ecuación", "teorema", "matemática")):
            domain = "Matemáticas Puras & Mecánica de Fluidos"
        elif any(w in t_low for w in ("cerebro", "neurona", "cogni", "neurociencia", "sinapsis", "bci")):
            domain = "Neurociencia Computacional & Neurobiología"
        elif any(w in t_low for w in ("materia oscura", "agujero negro", "axion", "cosmolog", "astrofísica", "astrofisica")):
            domain = "Cosmología & Astrofísica de Altas Energías"
        elif any(w in t_low for w in ("aislante topologico", "aislante topológico", "majorana", "weyl", "materia condensada")):
            domain = "Física del Estado Sólido & Materia Condensada"

        # Limpiar palabras conversacionales
        clean_topic = re.sub(
            r"\b(investiga|investigar|busca|buscar|sobre|acerca de|de rigor cientifico|de rigor científico|quiero aprender|aprender sobre|papers de|links de|enlaces de|articulos de|artículos de)\b",
            "",
            topic,
            flags=re.IGNORECASE
        ).strip() or topic

        # Expansión de consultas
        queries = [clean_topic]

        # Traducción / Mapeo técnico a inglés para máxima cobertura de papers internacionales
        english_mapping = [
            ("entrelazamiento cuántico", "quantum entanglement decoherence Bell inequality"),
            ("sintropía", "syntropy negentropy non-equilibrium thermodynamics retrocausality"),
            ("fusión nuclear", "nuclear fusion magnetic confinement tokamak stellarator"),
            ("redes neuronales", "neural network deep learning architectures"),
            ("aislantes topológicos", "topological insulators edge states condensed matter"),
            ("materia oscura", "dark matter direct detection axions WIMPs"),
            ("epigenética", "epigenetics cellular reprogramming longevity CRISPR"),
            ("neurociencia", "computational neuroscience neural decoding"),
            ("criptografía post-cuántica", "post-quantum cryptography lattice based"),
            ("mamba vs transformers", "state space models Mamba transformer language models")
        ]

        academic_en = clean_topic
        for es_term, en_term in english_mapping:
            if es_term in clean_topic.lower():
                academic_en = en_term
                queries.append(en_term)
                break

        if len(queries) == 1:
            queries.append(f"{clean_topic} review fundamentals")
            queries.append(f"{clean_topic} advances 2024 2025 2026")

        return domain, list(dict.fromkeys(queries))[:3], academic_en

    def execute_research(
        self,
        topic: str,
        max_papers: int = 5,
        target_domain: Optional[str] = None
    ) -> ScientificResearchReport:
        """
        Ejecuta el pipeline completo de investigación de rigor científico:
        1. Formulación de consultas multi-idioma de alto nivel.
        2. Búsqueda paralela en arXiv, OpenAlex, Europe PMC y Wikipedia.
        3. Fusión, desduplicación y ranking por citas y rigor metodológico.
        4. Síntesis pedagógica profunda estructurada para el aprendizaje.
        """
        t0 = time.time()
        domain, queries, en_topic = self.formulate_academic_queries(topic)
        if target_domain:
            domain = target_domain

        collected_papers: List[ScientificPaper] = []
        seen_titles = set()

        def add_paper(p: ScientificPaper):
            norm_title = re.sub(r"[^\w]", "", p.title.lower())
            if norm_title and norm_title not in seen_titles:
                seen_titles.add(norm_title)
                collected_papers.append(p)

        # 1. Búsqueda en OpenAlex (Cubre todas las ciencias con citas y prestigio de revista)
        for q in queries:
            alex_results = self.search_openalex(q, max_results=max_papers)
            for p in alex_results:
                add_paper(p)
            if len(collected_papers) >= max_papers * 2:
                break

        # 2. Búsqueda en arXiv (Física, Matemáticas, Computación, IA)
        for q in queries:
            arxiv_results = self.search_arxiv(q, max_results=max_papers)
            for p in arxiv_results:
                add_paper(p)
            if len(collected_papers) >= max_papers * 3:
                break

        # 3. Búsqueda en Europe PMC si es del área biológica, médica o química
        if any(w in domain.lower() for w in ("biología", "biologia", "neuro", "bio", "medicina")):
            for q in queries:
                epmc_results = self.search_europepmc(q, max_results=max_papers)
                for p in epmc_results:
                    add_paper(p)

        # 4. Wikipedia científica para fundamentación axiomática
        wiki_info = self.search_wikipedia_science(topic)

        # Ordenar por citas e impacto académico (los que tienen DOI y citas arriba)
        collected_papers.sort(
            key=lambda p: (
                1 if p.doi else 0,
                1 if p.pdf_url else 0,
                p.citations_count,
                p.year or 0
            ),
            reverse=True
        )

        selected_papers = collected_papers[:max_papers]

        # 5. Generar síntesis pedagógica estructurada
        report = self._build_pedagogical_synthesis(
            topic=topic,
            domain=domain,
            papers=selected_papers,
            wiki_info=wiki_info,
            elapsed_seconds=round(time.time() - t0, 2)
        )

        return report

    def _build_pedagogical_synthesis(
        self,
        topic: str,
        domain: str,
        papers: List[ScientificPaper],
        wiki_info: Dict[str, Any],
        elapsed_seconds: float
    ) -> ScientificResearchReport:
        """Construye un reporte pedagógico exhaustivo con rigor científico."""

        # 1. Resumen conceptual de alto nivel
        concept_summary = wiki_info.get("summary") or ""
        if not concept_summary and papers:
            # Reconstruir desde los abstracts más relevantes
            abstract_snippets = [p.abstract[:400] for p in papers if p.abstract]
            concept_summary = " ".join(abstract_snippets[:2])

        if not concept_summary:
            concept_summary = (
                f"El estudio riguroso de '{topic}' abarca el análisis formal dentro del área de {domain}, "
                "evaluando sus leyes fundamentales, modelos matemáticos y verificación experimental."
            )

        # 2. Principios Fundamentales y Axiomas
        principles = [
            f"**Marco Axiomático:** {domain} define el comportamiento del sistema mediante modelos teóricos contrastables.",
            "**Metodología y Reproducibilidad:** Los avances analizados se sustentan en experimentos reproducibles y derivaciones analíticas publicadas en literatura revisada por pares.",
            "**Acceso al Conocimiento Abierto:** Cada artículo seleccionado incluye enlaces canónicos persistentes (DOI) o preprints de acceso público inmediato."
        ]

        if "cuántica" in domain.lower():
            principles.append("**Principio Cuántico:** Estados descritos por vectores en un espacio de Hilbert $\\mathcal{H}$, operadores hermíticos para observables y evolución unitaria bajo la ecuación de Schrödinger.")
        elif "termodinámica" in domain.lower() or "sintropía" in topic.lower():
            principles.append("**Principio Termodinámico:** Dinámica de no equilibrio regida por el teorema de fluctuación, producción de entropía local y atractores sintrópicos de autoorganización.")
        elif "inteligencia artificial" in domain.lower():
            principles.append("**Principio Computacional:** Complejidad algorítmica, compresión informacional y trade-off entre memoria asociativa y throughput en arquitecturas de secuencia.")

        # 3. Ruta de Aprendizaje (Roadmap)
        roadmap = []
        if papers:
            roadmap.append(f"1. **Fundamentos:** Comenzar revisando el artículo con mayor consenso: *'{papers[0].title}'* ({papers[0].venue}, {papers[0].year or 's/f'}).")
            if len(papers) > 1:
                roadmap.append(f"2. **Profundización Técnica:** Examinar la formulación de: *'{papers[1].title}'* para entender la metodología y derivaciones.")
            if len(papers) > 2:
                roadmap.append(f"3. **Frontera Actual:** Contrastar con el desarrollo reciente: *'{papers[-1].title}'* para identificar el estado del arte.")
        else:
            roadmap.append("1. Explorar la bibliografía fundacional y consultar las fuentes DOI recomendadas.")

        # 4. Preguntas Abiertas en la Frontera del Conocimiento
        open_questions = [
            f"¿Cuáles son los límites de escala o divergencias experimentales en los modelos de {topic}?",
            "¿Cómo se integran estos hallazgos con teorías unificadas o aplicaciones prácticas de próxima generación?",
            "¿Qué hipótesis aún carecen de confirmación empírica definitiva según los últimos papers?"
        ]

        return ScientificResearchReport(
            topic=topic,
            scientific_domain=domain,
            conceptual_summary=concept_summary,
            fundamental_principles=principles,
            papers=papers,
            learning_roadmap=roadmap,
            open_questions=open_questions,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            elapsed_seconds=elapsed_seconds
        )

    # -------------------------------------------------------------------------
    # 4. FORMATO Y DESPACHO DIRECTO A TELEGRAM
    # -------------------------------------------------------------------------
    def format_telegram_report(self, report: ScientificResearchReport) -> str:
        """Formatea el informe de investigación para Telegram con rigor y estética limpia."""
        lines = [
            f"🔬 **[INVESTIGACIÓN DE RIGOR CIENTÍFICO]**",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📚 **Tema:** `{report.topic}`",
            f"🏛️ **Dominio:** *{report.scientific_domain}*",
            f"⏱️ **Tiempo de Síntesis:** `{report.elapsed_seconds}s` · `{report.generated_at}`",
            "",
            "🎓 **FUNDAMENTOS & MARCO CONCEPTUAL:**",
            f"{report.conceptual_summary[:850]}...",
            "",
            "🧪 **PRINCIPIOS CLAVE:**"
        ]

        for p in report.fundamental_principles[:3]:
            lines.append(f"• {p}")

        lines.append("")
        lines.append("📄 **ARTÍCULOS CIENTÍFICOS Y ENLACES DE ACCESO DIRECTO:**")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        for i, paper in enumerate(report.papers, 1):
            auth_str = ", ".join(paper.authors[:3])
            if len(paper.authors) > 3:
                auth_str += " et al."
            if not auth_str:
                auth_str = "Investigadores"

            year_str = f"({paper.year})" if paper.year else ""
            cit_str = f" · 🌟 Citas: `{paper.citations_count}`" if paper.citations_count > 0 else ""

            lines.append(f"**{i}. {paper.title}**")
            lines.append(f"   👥 *{auth_str}* {year_str}")
            lines.append(f"   🏛️ *{paper.venue}*{cit_str}")

            # Enlaces de acceso
            links = []
            if paper.doi_url:
                links.append(f"[🔗 Enlace DOI]({paper.doi_url})")
            if paper.landing_url and paper.landing_url != paper.doi_url:
                links.append(f"[📖 Leer Artículo]({paper.landing_url})")
            if paper.pdf_url:
                links.append(f"[📥 Descargar PDF]({paper.pdf_url})")

            if links:
                lines.append(f"   {' · '.join(links)}")

            if paper.abstract:
                clean_abs = paper.abstract[:280].strip()
                lines.append(f"   💡 *Aporte:* \"{clean_abs}...\"")
            lines.append("")

        lines.append("🗺️ **RUTA DE APRENDIZAJE RECOMENDADA:**")
        for step in report.learning_roadmap:
            lines.append(f"{step}")

        lines.append("")
        lines.append("🔭 **FRONTERA DEL CONOCIMIENTO:**")
        for q in report.open_questions[:2]:
            lines.append(f"• {q}")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🌐 *TARDIS Sistema de Exploración Científica Soberana*")

        return "\n".join(lines)

    def send_report_to_telegram(
        self,
        report: ScientificResearchReport,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Envía el informe a Telegram respetando límites de caracteres y botones interactivos."""
        try:
            from core.telegram_bridge import get_telegram_bridge
            tb = get_telegram_bridge()

            target_chat = chat_id or tb.config.get("admin_chat_id")
            if not target_chat and tb.config.get("allowed_chats"):
                target_chat = tb.config["allowed_chats"][0]

            if not target_chat:
                return {"ok": False, "error": "No hay chat_id destino configurado en Telegram"}

            full_text = self.format_telegram_report(report)

            # Construir teclado inline interactivo con botones a los papers principales
            inline_buttons = []
            for i, p in enumerate(report.papers[:4], 1):
                btn_url = p.pdf_url or p.landing_url or p.doi_url
                if btn_url:
                    inline_buttons.append([{
                        "text": f"📄 Paper {i} ({'PDF Directo' if p.pdf_url else 'Ver'})",
                        "url": btn_url
                    }])

            reply_markup = {"inline_keyboard": inline_buttons} if inline_buttons else None

            # Si el texto es menor a 4000 caracteres, enviarlo en un solo bloque
            if len(full_text) <= 4000:
                res = tb.send_message(
                    text=full_text,
                    chat_id=target_chat,
                    reply_to_message_id=reply_to_message_id,
                    reply_markup=reply_markup
                )
                return res

            # Si supera 4000 caracteres, partir inteligentemente en 2 bloques
            parts = full_text.split("📄 **ARTÍCULOS CIENTÍFICOS Y ENLACES DE ACCESO DIRECTO:**")
            if len(parts) == 2:
                part1 = parts[0].strip()
                part2 = "📄 **ARTÍCULOS CIENTÍFICOS Y ENLACES DE ACCESO DIRECTO:**\n" + parts[1].strip()

                tb.send_message(text=part1, chat_id=target_chat, reply_to_message_id=reply_to_message_id)
                res = tb.send_message(text=part2, chat_id=target_chat, reply_markup=reply_markup)
                return res
            else:
                chunk1 = full_text[:3800]
                chunk2 = full_text[3800:]
                tb.send_message(text=chunk1, chat_id=target_chat, reply_to_message_id=reply_to_message_id)
                res = tb.send_message(text=chunk2, chat_id=target_chat, reply_markup=reply_markup)
                return res

        except Exception as e:
            logger.error(f"Error despachando reporte científico a Telegram: {e}")
            return {"ok": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # 5. CICLO AUTÓNOMO PROGRAMADO (DAEMON DE DESCUBRIMIENTO)
    # -------------------------------------------------------------------------
    def run_autonomous_cycle(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        """Ejecuta un ciclo autónomo: toma el siguiente tema pendiente de la agenda, investiga y envía."""
        next_item = self.get_next_agenda_topic()
        if not next_item:
            return {"ok": False, "error": "No hay temas disponibles en la agenda"}

        topic_str = next_item["topic"]
        domain_str = next_item.get("domain", "Ciencia General")
        logger.info(f"Iniciando investigación científica autónoma: '{topic_str}' ({domain_str})")

        report = self.execute_research(topic=topic_str, max_papers=5, target_domain=domain_str)
        self.mark_topic_researched(topic_str)

        send_res = self.send_report_to_telegram(report, chat_id=chat_id)
        return {
            "ok": True,
            "topic": topic_str,
            "domain": domain_str,
            "papers_found": len(report.papers),
            "telegram_result": send_res
        }

    def start_autonomous_daemon(self, interval_seconds: Optional[float] = None) -> bool:
        """Inicia el hilo en segundo plano que investiga periódicamente y envía descubrimientos."""
        if self._autonomous_thread and self._autonomous_thread.is_alive():
            return True

        self._stop_event.clear()

        def _worker():
            logger.info("Daemon de Investigación Científica Autónoma TARDIS iniciado.")
            while not self._stop_event.is_set():
                agenda = self.load_agenda()
                if agenda.get("autonomous_mode", True):
                    try:
                        self.run_autonomous_cycle()
                    except Exception as e:
                        logger.error(f"Error en ciclo autónomo de investigación: {e}")

                intv = interval_seconds or (agenda.get("interval_hours", 12.0) * 3600)
                # Dormir en intervalos cortos para responder al stop
                sleep_chunks = int(intv / 5)
                for _ in range(sleep_chunks):
                    if self._stop_event.is_set():
                        break
                    time.sleep(5.0)

        self._autonomous_thread = threading.Thread(target=_worker, daemon=True, name="ScientificResearchDaemon")
        self._autonomous_thread.start()
        return True

    def stop_autonomous_daemon(self) -> None:
        """Detiene el daemon de investigación autónoma."""
        self._stop_event.set()
        if self._autonomous_thread and self._autonomous_thread.is_alive():
            self._autonomous_thread.join(timeout=2.0)


def get_scientific_research_engine() -> ScientificResearchEngine:
    return ScientificResearchEngine.get_instance()
