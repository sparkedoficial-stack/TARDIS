"""
GIA Control Center - Modulo de procesamiento PDF
==================================================
Extrae texto, tablas, dibujos y prestaciones arquitectonicas de PDFs
para construir contexto que el LLM usa al generar geometria.

API expuesta (consumida por gia_control.py):
    PDFProcessor          - .process(path, progress_cb) -> PDFDocument
    PDFContextStore       - .add/.get/.remove/.list_ids/.context_for_prompt
    PDFDocument           - dataclass serializable (.to_dict)
    PageContent           - una pagina (.page_number, .text, .tables, .drawing_count, .has_drawings)
    check_dependencies()  - {ready, pymupdf, pdfplumber}
    extract_architectural_features(doc) - dict con dimensiones/habitaciones/areas/escalas

Estrategia:
    - PyMuPDF (fitz) para texto rapido y conteo de drawings
    - pdfplumber (opcional) para extraccion de tablas
    - Si no hay PyMuPDF, fallback a pypdf para texto basico
    - Heuristicas regex para detectar prestaciones arquitectonicas

Arquitecto - Sistema GIA - v1.0-PROCESSOR
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

# ===== BACKEND PDF (lazy y robusto) =====
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    fitz = None

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    pdfplumber = None

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False
    pypdf = None


def check_dependencies() -> dict:
    """Devuelve estado de dependencias y readiness."""
    return {
        "pymupdf":    HAS_PYMUPDF,
        "pdfplumber": HAS_PDFPLUMBER,
        "pypdf":      HAS_PYPDF,
        "ready":      HAS_PYMUPDF or HAS_PYPDF,
    }


# =====================================================================
#  ESTRUCTURAS
# =====================================================================

@dataclass
class PageContent:
    """Una pagina del PDF tras extraccion."""
    page_number: int
    text: str
    tables: list = field(default_factory=list)   # cada tabla = lista de filas
    drawing_count: int = 0
    width_pt: float = 0.0
    height_pt: float = 0.0

    @property
    def has_drawings(self) -> bool:
        return self.drawing_count > 5

    def char_count(self) -> int:
        return len(self.text)


@dataclass
class PDFDocument:
    """Resultado completo del procesamiento de un PDF.

    v6.4 OPTIMIZACION: incluye caches internos para evitar re-computos
    costosos (total_text, lowered text, features, AV inventory, keyword
    index). Los caches se invalidan automaticamente si la lista de pages
    cambia (via len(pages)).
    """
    filename: str
    full_path: str
    page_count: int
    pages: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    processing_time_s: float = 0.0
    has_arquitectural_plans: bool = False
    backend_used: str = ""

    # ----- caches internos (v6.4) -----
    # Estos campos NO se serializan a dict ni a JSON. Son lazy.
    _cache_total_text: str = field(default="", repr=False, compare=False)
    _cache_total_text_lower: str = field(default="", repr=False, compare=False)
    _cache_features: dict = field(default_factory=dict, repr=False, compare=False)
    _cache_av_inventory: dict = field(default_factory=dict, repr=False, compare=False)
    _cache_summary: dict = field(default_factory=dict, repr=False, compare=False)
    _cache_keyword_index: dict = field(default_factory=dict, repr=False, compare=False)
    _cache_invalidation_key: int = field(default=0, repr=False, compare=False)

    def _check_cache_valid(self) -> bool:
        """Cache valido si la cantidad de paginas no cambio."""
        return self._cache_invalidation_key == len(self.pages)

    def _mark_cache_built(self):
        self._cache_invalidation_key = len(self.pages)

    def invalidate_caches(self):
        """Fuerza re-calculo de caches en la proxima invocacion."""
        self._cache_total_text = ""
        self._cache_total_text_lower = ""
        self._cache_features.clear()
        self._cache_av_inventory.clear()
        self._cache_summary.clear()
        self._cache_keyword_index.clear()
        self._cache_invalidation_key = -1

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "full_path": self.full_path,
            "page_count": self.page_count,
            "metadata": self.metadata,
            "processing_time_s": round(self.processing_time_s, 2),
            "has_arquitectural_plans": self.has_arquitectural_plans,
            "backend_used": self.backend_used,
            "pages_summary": [
                {
                    "page": p.page_number,
                    "char_count": p.char_count(),
                    "drawing_count": p.drawing_count,
                    "tables": len(p.tables),
                    "has_drawings": p.has_drawings,
                }
                for p in self.pages
            ],
        }

    def total_text(self) -> str:
        """Concatena texto de todas las paginas. CACHEADO (v6.4)."""
        if self._cache_total_text and self._check_cache_valid():
            return self._cache_total_text
        # Build con list comprehension + join (mas rapido que +=)
        parts = [f"=== Pagina {p.page_number} ===\n{p.text}" for p in self.pages]
        self._cache_total_text = "\n\n".join(parts)
        self._mark_cache_built()
        return self._cache_total_text

    def total_text_lower(self) -> str:
        """Version lowercased de total_text para regex/keyword search. CACHEADO."""
        if self._cache_total_text_lower and self._check_cache_valid():
            return self._cache_total_text_lower
        self._cache_total_text_lower = self.total_text().lower()
        return self._cache_total_text_lower

    def keyword_index(self) -> dict:
        """Indice invertido: keyword -> [page_numbers].

        Pre-computa al primer acceso. Permite buscar 'K2' o 'BMFL' en O(1)
        en vez de O(N pages * M keywords). Solo indexa keywords del
        vocabulario AV (~150 terms) - no full inverted index.
        """
        if self._cache_keyword_index and self._check_cache_valid():
            return self._cache_keyword_index
        index: dict = {}
        # Importar lazy para evitar circular
        keywords_to_index = set()
        try:
            for terms in _AV_KEYWORDS.values():
                for t in terms:
                    t_clean = t.strip().lower()
                    if t_clean:
                        keywords_to_index.add(t_clean)
        except NameError:
            # _AV_KEYWORDS aun no esta definido (carga inicial); usar set vacio
            pass
        for p in self.pages:
            page_text_lower = p.text.lower()
            for kw in keywords_to_index:
                if kw in page_text_lower:
                    index.setdefault(kw, []).append(p.page_number)
        self._cache_keyword_index = index
        self._mark_cache_built()
        return self._cache_keyword_index


# =====================================================================
#  PROCESADOR
# =====================================================================

class PDFProcessor:
    """Convierte un archivo PDF a PDFDocument con extraccion adaptativa."""

    def __init__(self, max_pages: int = 200):
        self.max_pages = max_pages

    def process(self,
                pdf_path: str | Path,
                progress_cb: Optional[Callable[[int, int, str], None]] = None,
                extract_tables: bool = False,
                build_summary: bool = True) -> PDFDocument:
        """
        Procesa el PDF.

        v6.4 OPTIMIZACIONES:
          - extract_tables=False por defecto (pdfplumber es ~10x mas lento
            que pymupdf; activar SOLO si se necesitan tablas, ej. cotizaciones)
          - build_summary=True: pre-computa summary/features/keyword_index
            tras la extraccion para que las tools LLM sean instantaneas
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF no encontrado: {path}")
        if not check_dependencies()["ready"]:
            raise RuntimeError(
                "Sin backend PDF. Instala: pip install pymupdf pdfplumber"
            )

        t0 = time.time()
        doc = PDFDocument(
            filename=path.name,
            full_path=str(path),
            page_count=0,
        )

        if HAS_PYMUPDF:
            self._extract_with_pymupdf(path, doc, progress_cb)
            doc.backend_used = "pymupdf"
        else:
            self._extract_with_pypdf(path, doc, progress_cb)
            doc.backend_used = "pypdf"

        # Tablas con pdfplumber - solo si se pidio explicitamente (v6.4)
        if extract_tables and HAS_PDFPLUMBER and doc.pages:
            try:
                self._extract_tables_pdfplumber(path, doc, progress_cb)
            except Exception:
                pass

        doc.has_arquitectural_plans = self._detect_architectural(doc)

        # Pre-construir caches para que el LLM tenga respuestas instantaneas (v6.4)
        if build_summary:
            try:
                if progress_cb:
                    progress_cb(doc.page_count, doc.page_count, "indexando")
                # Estos calls construyen los caches dentro de doc
                _ = doc.total_text_lower()
                _ = doc.keyword_index()
                _ = extract_architectural_features(doc)
                _ = extract_av_equipment(doc)
                _ = build_compact_summary(doc)
            except Exception:
                pass

        doc.processing_time_s = time.time() - t0
        return doc

    # ---------- backends ----------

    def _extract_with_pymupdf(self, path: Path, doc: PDFDocument, cb):
        with fitz.open(str(path)) as pdf:
            doc.metadata = pdf.metadata or {}
            doc.page_count = min(len(pdf), self.max_pages)
            for i in range(doc.page_count):
                if cb:
                    cb(i + 1, doc.page_count, "extrayendo")
                page = pdf[i]
                text = page.get_text("text") or ""
                drawings = 0
                try:
                    drawings = len(page.get_drawings())
                except Exception:
                    pass
                rect = page.rect
                doc.pages.append(PageContent(
                    page_number=i + 1,
                    text=text,
                    drawing_count=drawings,
                    width_pt=rect.width,
                    height_pt=rect.height,
                ))

    def _extract_with_pypdf(self, path: Path, doc: PDFDocument, cb):
        reader = pypdf.PdfReader(str(path))
        doc.metadata = dict(reader.metadata) if reader.metadata else {}
        doc.page_count = min(len(reader.pages), self.max_pages)
        for i in range(doc.page_count):
            if cb:
                cb(i + 1, doc.page_count, "extrayendo")
            page = reader.pages[i]
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            doc.pages.append(PageContent(
                page_number=i + 1,
                text=text,
                drawing_count=0,
            ))

    def _extract_tables_pdfplumber(self, path: Path, doc: PDFDocument, cb):
        with pdfplumber.open(str(path)) as pdf:
            for i, p in enumerate(pdf.pages[: doc.page_count]):
                if cb:
                    cb(i + 1, doc.page_count, "tablas")
                try:
                    tbls = p.extract_tables() or []
                    if tbls and i < len(doc.pages):
                        doc.pages[i].tables = [
                            [[(c or "").strip() for c in row] for row in tbl]
                            for tbl in tbls
                        ]
                except Exception:
                    continue

    # ---------- heuristicas ----------

    def _detect_architectural(self, doc: PDFDocument) -> bool:
        """Detecta si el PDF parece arquitectonico (planos + vocabulario)."""
        text_lower = " ".join(p.text for p in doc.pages).lower()
        keywords = (
            "planta", "alzado", "seccion", "fachada", "escala",
            "muro", "pared", "habitacion", "dormitorio", "sala",
            "cocina", "bano", "comedor", "balcon", "terraza",
            "metros", "m2", "m²", "mm", "cm",
            "estructur", "arquitec", "vivienda",
        )
        kw_hits = sum(1 for k in keywords if k in text_lower)
        drawing_pages = sum(1 for p in doc.pages if p.has_drawings)
        return kw_hits >= 3 or drawing_pages >= 1


# =====================================================================
#  STORE DE CONTEXTO
# =====================================================================

class PDFContextStore:
    """Mantiene los PDFs cargados y construye el bloque de contexto inyectado al system prompt.

    v6.4 OPTIMIZACION: el contexto inyectado al system prompt ahora es un
    RESUMEN compacto (~500 tokens) en vez de un dump de 8000 chars (~2000
    tokens). Esto reduce ~75% los tokens del system prompt cuando hay
    PDFs cargados, dejando mas contexto al modelo para razonar.

    Si el LLM necesita el texto completo, usa la tool get_pdf_page_text
    bajo demanda (por pagina especifica).
    """

    # Cap de chars de FALLBACK por PDF cuando no hay resumen (raro)
    MAX_TEXT_PER_PDF = 1500

    def __init__(self):
        self._docs: dict[str, PDFDocument] = {}

    def add(self, doc: PDFDocument):
        self._docs[doc.filename] = doc

    def remove(self, doc_id: str) -> bool:
        return self._docs.pop(doc_id, None) is not None

    def get(self, doc_id: str) -> Optional[PDFDocument]:
        return self._docs.get(doc_id)

    def list_ids(self) -> list[str]:
        return list(self._docs.keys())

    def __len__(self):
        return len(self._docs)

    def context_for_prompt(self, max_chars: int = 2000) -> str:
        """Resumen compacto inyectado al system prompt.

        v6.4: formato denso optimizado para LLMs. Solo metadata + counts +
        highlights. Si el modelo necesita el texto completo de una pagina,
        llamara get_pdf_page_text bajo demanda.
        """
        if not self._docs:
            return ""

        parts = ["=== PDFs CARGADOS (resumen) ==="]
        total_chars = 0

        for fname, doc in self._docs.items():
            summary = build_compact_summary(doc)
            line = self._format_summary_line(fname, summary, doc)
            if total_chars + len(line) > max_chars:
                parts.append(f"\n[+{len(self._docs) - len(parts) + 1} PDFs mas, "
                             "usa list_loaded_pdfs+get_pdf_features para detalle]")
                break
            parts.append(line)
            total_chars += len(line)

        parts.append("Para detalle: get_pdf_features(pdf_id), "
                     "get_pdf_av_equipment(pdf_id), "
                     "get_pdf_page_text(pdf_id, page_number)")
        parts.append("=== FIN ===")
        return "\n".join(parts)

    def _format_summary_line(self, fname: str, summary: dict, doc: PDFDocument) -> str:
        """Una linea por PDF, formato denso."""
        bits = [
            f"\n[{fname}] {doc.page_count}p",
            f"backend={doc.backend_used}",
        ]
        if doc.has_arquitectural_plans:
            bits.append("ARQ")
        if summary.get("is_av_event"):
            bits.append("AV-EVENT")
        if summary.get("dim_count"):
            bits.append(f"dims={summary['dim_count']}")
        if summary.get("area_count"):
            bits.append(f"areas={summary['area_count']}")
        if summary.get("scale"):
            bits.append(f"escala={summary['scale']}")
        line = " ".join(bits)

        if summary.get("top_av_categories"):
            cats = summary["top_av_categories"]
            cat_str = ", ".join(f"{k}={v}" for k, v in cats[:6])
            line += "\n  AV: " + cat_str
        if summary.get("quantified_highlights"):
            qh = summary["quantified_highlights"][:5]
            qh_str = ", ".join(f"{q['qty']}x {q['term']}" for q in qh)
            line += "\n  QTY: " + qh_str
        if summary.get("rooms"):
            line += "\n  Espacios: " + ", ".join(summary["rooms"][:8])
        if summary.get("dimensions"):
            line += "\n  Dims: " + " | ".join(summary["dimensions"][:5])
        return line


# ---------------------------------------------------------------------
# v6.4: RESUMEN COMPACTO PRE-COMPUTADO
# ---------------------------------------------------------------------

def build_compact_summary(doc: PDFDocument) -> dict:
    """Resumen estructurado pequeno (~500 chars JSON) que el LLM puede
    consumir como tool result en vez del dump completo.

    Cacheado en doc._cache_summary.
    """
    if doc._cache_summary and doc._check_cache_valid():
        return doc._cache_summary

    features = extract_architectural_features(doc)
    av = extract_av_equipment(doc)

    # Top categorias AV por count
    counts = av.get("counts", {}) or {}
    top_cats = sorted(counts.items(), key=lambda x: -x[1])

    summary = {
        "filename": doc.filename,
        "pages": doc.page_count,
        "backend": doc.backend_used,
        "is_architectural": doc.has_arquitectural_plans,
        "is_av_event": av.get("is_av_event", False),
        "total_av_mentions": av.get("total_av_mentions", 0),
        "top_av_categories": top_cats[:8],
        "quantified_highlights": av.get("quantified_items", [])[:10],
        "suggested_helpers": av.get("suggested_helpers", [])[:8],
        "dim_count": len(features.get("dimensions", [])),
        "area_count": len(features.get("areas", [])),
        "rooms": features.get("rooms", [])[:8],
        "scale": features.get("scale"),
        "dimensions": features.get("dimensions", [])[:6],
        "areas": features.get("areas", [])[:5],
    }
    doc._cache_summary = summary
    return summary


def search_pdf_keyword(doc: PDFDocument, keyword: str, limit: int = 20) -> dict:
    """Busca un keyword en el PDF usando el indice invertido pre-computado.

    Devuelve: {"keyword": kw, "found_in_pages": [int, ...], "snippets": [...]}
    O(1) si el keyword esta en el vocabulario AV, O(N) si no (escanea pages).
    """
    kw = keyword.strip().lower()
    if not kw:
        return {"keyword": keyword, "found_in_pages": [], "snippets": []}

    index = doc.keyword_index()
    pages = index.get(kw, [])

    # Si no esta en el indice, hacer fallback scan
    if not pages:
        for p in doc.pages:
            if kw in p.text.lower():
                pages.append(p.page_number)

    # Extraer snippets de las primeras N paginas con match
    snippets = []
    for pnum in pages[:limit]:
        for p in doc.pages:
            if p.page_number == pnum:
                idx = p.text.lower().find(kw)
                if idx >= 0:
                    start = max(0, idx - 60)
                    end = min(len(p.text), idx + len(kw) + 60)
                    snippet = p.text[start:end].replace("\n", " ").strip()
                    snippets.append({"page": pnum, "snippet": "..." + snippet + "..."})
                break

    return {
        "keyword": keyword,
        "found_in_pages": pages,
        "match_count": len(pages),
        "snippets": snippets[:limit],
    }


# =====================================================================
#  EXTRACCION DE PRESTACIONES ARQUITECTONICAS
# =====================================================================

# Patrones regex
_DIM_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:x|×|\*)\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|m\b|metros?|ft|in|pulg)",
    re.IGNORECASE,
)
_AREA_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²|metros\s*cuadrados|sq\.?\s*m|sqm)",
    re.IGNORECASE,
)
_SCALE_PATTERN = re.compile(
    r"\bescala\s*[:=]?\s*1\s*[:/]\s*(\d+)|\b1\s*[:/]\s*(\d+)\b",
    re.IGNORECASE,
)
_ROOM_KEYWORDS = (
    "sala", "comedor", "cocina", "dormitorio", "habitacion", "habitación",
    "bano", "baño", "estudio", "oficina", "balcon", "balcón",
    "terraza", "garaje", "lavanderia", "lavandería", "vestibulo",
    "vestíbulo", "patio", "jardin", "jardín", "recibidor",
    "despacho", "biblioteca", "sala de estar", "living", "master",
    "principal", "secundario", "huesped", "huésped",
)

# Vocabulario de equipo audiovisual mapeado a categorias de gia.* helpers
_AV_KEYWORDS = {
    # AUDIO
    "speaker": (
        "altavoz", "altavoces", "bocina", "bocinas", "monitor de piso",
        "wedge", "side fill", "sidefill", "main pa", "fill",
        "kara", "k1 ", "k2 ", "k3 ",
        "vtx a12", "vtx-a12", "leopard", "lina", "ulysses",
    ),
    "subwoofer": (
        "subwoofer", "subgrave", "sub-grave", "ks28", "ks21",
        "vtx b28", "vtx-b28", "1100-lfc", "1100lfc",
    ),
    "speaker_array": (
        "line array", "linea de audio", "linea de bocinas", "j-array", "j array",
        "arreglo lineal", "main hangs", "left/right", "l/r",
    ),
    "microphone": (
        "microfono", "micrófono", "microphone", " mic ", "wireless mic",
        "shure", "sennheiser", "sm58", "sm57", "beta 58", "beta 57",
        "ksm", "rode", "akg", "dpa",
    ),
    "console": (
        "consola", "console", "mixer", "mezcladora", "midas", "digico",
        "yamaha cl", "yamaha ql", "avid", "ds100", "soundcraft", "allen heath",
        "behringer x32", "x32",
    ),
    # VIDEO
    "screen": (
        "pantalla", "screen", "led wall", "led-wall", "videowall", "video wall",
        "monitor", "display", "lcd", "p2.6", "p2.9", "p3.9", "p4.8",
        "absen", "roe", "infiled", "unilumin",
    ),
    "projector": (
        "proyector", "projector", "barco", "panasonic ptz", "christie",
        "epson", "10000 lumens", "20000 lumens", "throw", "lente proyector",
    ),
    "camera": (
        "camara", "cámara", "camera", "ptz", "blackmagic",
        "sony hdc", "sony pmw", "ross", "panasonic ux180",
    ),
    # ILUMINACION
    "lighting": (
        "luminaria", "fixture", "par 64", "par64", "par led", "par-led",
        "fresnel", "blinder", "strobe", "estrobo",
        "atomic 3000", "atomic3000", "sunstrip",
    ),
    "moving_head": (
        "moving head", "cabezal movil", "cabezal móvil", "cabeza movil",
        "spot ", "wash ", "beam ",
        "robe ", "martin ", "claypaky", "clay paky", "ayrton",
        "mac viper", "mac aura", "viper profile", "robin pointe",
        "spiider", "elation",
    ),
    "follow_spot": (
        "follow spot", "followspot", "seguidor", "trackspot", "lycian",
    ),
    "lighting_console": (
        "consola de luces", "consola de iluminacion", "consola de iluminación",
        "lighting console", "ma3", "ma2", "grandma", "grand ma",
        "hog4", "hog 4", "avolites", "chamsys",
    ),
    "haze_smoke": (
        "haze", "humo", "maquina de humo", "máquina de humo", "neblina",
        "smoke machine", "fog machine", "le maitre", "look solutions",
    ),
    # RIGGING
    "truss": (
        "truss", "estructura de aluminio", "rigging", "armatron",
        "global truss", "prolyte", "milos", "totem", "ground support",
        "f34", "f44", "h30v", "h40v", "tower lift", "vertical truss",
    ),
    "motor": (
        "motor", "polipasto", "chain hoist", "verlinde", "cm lodestar",
        "lodestar classic", "yale", "stagemaker",
    ),
    # ESCENARIO
    "stage": (
        "escenario", "stage", "tarima", "platform", "rosco", "stagedeck",
        "stage deck", "litedeck", "litec", "doughty",
    ),
    "dj_booth": (
        "cabina dj", "dj booth", "pioneer", "cdj-3000", "cdj 3000",
        "djm-900", "djm 900", "rane", "denon prime",
    ),
    "barricade": (
        "valla", "barricade", "mojo barrier", "mojobarrier", "barricada",
    ),
    "riser": (
        "riser", "tarima de bateria", "drum riser", "tarima movil",
    ),
}

# Mapping de tipo AV detectado -> funcion gia.* sugerida
_AV_TO_GIA = {
    "speaker": "speaker",
    "subwoofer": "subwoofer",
    "speaker_array": "speaker_array",
    "microphone": "microphone",
    "screen": "screen",
    "projector": "projector",
    "camera": "camera",
    "lighting": "lighting",
    "moving_head": "moving_head",
    "follow_spot": "lighting",
    "haze_smoke": "box",
    "truss": "truss_av",
    "stage": "stage",
    "dj_booth": "dj_booth",
    "console": "box",          # console no tiene helper especifico, usar caja generica
    "lighting_console": "box",
    "motor": "box",
    "barricade": "box",
    "riser": "stage",
}


def extract_architectural_features(doc: PDFDocument) -> dict:
    """
    Extrae prestaciones del PDF: dimensiones, areas, escalas, habitaciones.
    v6.4: CACHEADO - llamadas repetidas devuelven el mismo dict instantaneamente.
    """
    if doc._cache_features and doc._check_cache_valid():
        return doc._cache_features
    result = _compute_architectural_features(doc)
    doc._cache_features = result
    return result


def _compute_architectural_features(doc: PDFDocument) -> dict:
    text = doc.total_text()
    text_lower = text.lower()

    # Dimensiones (5x4 m, 1500x800 mm, etc.)
    dims = []
    seen = set()
    for m in _DIM_PATTERN.finditer(text):
        a, b, unit = m.group(1), m.group(2), m.group(3)
        key = (a, b, unit.lower())
        if key in seen:
            continue
        seen.add(key)
        dims.append(f"{a}x{b} {unit}")
        if len(dims) >= 30:
            break

    # Areas
    areas = []
    seen_a = set()
    for m in _AREA_PATTERN.finditer(text):
        v = m.group(1)
        if v in seen_a:
            continue
        seen_a.add(v)
        areas.append(f"{v} m2")
        if len(areas) >= 20:
            break

    # Escala
    scale = None
    for m in _SCALE_PATTERN.finditer(text):
        n = m.group(1) or m.group(2)
        if n:
            scale = f"1:{n}"
            break

    # Habitaciones
    rooms_set = set()
    for kw in _ROOM_KEYWORDS:
        if kw in text_lower:
            rooms_set.add(kw)

    return {
        "filename": doc.filename,
        "page_count": doc.page_count,
        "is_architectural": doc.has_arquitectural_plans,
        "dimensions": dims,
        "areas": areas,
        "scale": scale,
        "rooms": sorted(rooms_set),
        "drawing_pages": [p.page_number for p in doc.pages if p.has_drawings],
        "has_tables": any(p.tables for p in doc.pages),
        "table_count": sum(len(p.tables) for p in doc.pages),
    }


# =====================================================================
#  EXTRACCION DE EQUIPO AUDIOVISUAL
# =====================================================================

# Patrones de cuantificacion: "8 bocinas", "4x speaker", "(2) microfonos", "qty 6"
_QTY_PATTERN = re.compile(
    r"(?:^|\s|\()(\d{1,3})(?:x|\s+x|\s*\)\s*|\s+)([a-zA-Záéíóúñ\s\-_/]{3,40})",
    re.IGNORECASE | re.MULTILINE,
)


def extract_av_equipment(doc: PDFDocument) -> dict:
    """
    Detecta equipo AV mencionado en el PDF y produce un inventario.

    v6.4 OPTIMIZACION: usa cache interno de doc + keyword_index para evitar
    re-escanear el texto en cada llamada. Reduce ~80% del tiempo en
    invocaciones repetidas (el LLM tiende a llamar esta tool 2-3 veces).

    Devuelve:
      {
        "is_av_event": bool, "total_av_mentions": int,
        "counts": {"speaker": 12, ...}, "found_terms": {...},
        "quantified_items": [...], "suggested_helpers": [...],
      }
    """
    # ---- CACHE HIT ----
    if doc._cache_av_inventory and doc._check_cache_valid():
        return doc._cache_av_inventory

    # ---- CACHE MISS - compute con keyword_index ----
    text_lower = doc.total_text_lower()
    kw_index = doc.keyword_index()  # construye al primer acceso

    counts = {}
    found_terms = {}

    for category, terms in _AV_KEYWORDS.items():
        cat_total = 0
        cat_terms = []
        for term in terms:
            t_clean = term.strip().lower()
            if not t_clean:
                continue
            # FAST PATH: si el keyword no esta en el indice, saltar
            if t_clean not in kw_index:
                continue
            n = text_lower.count(t_clean)
            if n > 0:
                cat_total += n
                cat_terms.append(f"{t_clean}({n})")
        if cat_total > 0:
            counts[category] = cat_total
            found_terms[category] = cat_terms

    # Items cuantificados
    quantified = []
    # Precomputar lista de keywords por longitud descendente (greedy match)
    if not hasattr(extract_av_equipment, "_kw_by_len_cache"):
        kw_list = []
        for category, kw_tuple in _AV_KEYWORDS.items():
            for kw in kw_tuple:
                kw_clean = kw.strip().lower()
                if kw_clean:
                    kw_list.append((kw_clean, category, len(kw_clean)))
        kw_list.sort(key=lambda x: -x[2])  # mas largos primero
        extract_av_equipment._kw_by_len_cache = kw_list
    kw_sorted = extract_av_equipment._kw_by_len_cache

    for m in _QTY_PATTERN.finditer(text_lower):
        try:
            qty = int(m.group(1))
        except ValueError:
            continue
        if qty < 1 or qty > 999:
            continue
        term = m.group(2).strip()[:40]
        term_padded = " " + term + " "
        # Buscar el primer match (que sera el mas largo por orden)
        cat = None
        for kw_clean, category, _ in kw_sorted:
            if (" " + kw_clean + " ") in term_padded:
                cat = category
                break
        if cat:
            quantified.append({"qty": qty, "term": term, "category": cat})

    suggested = sorted({f"gia.{_AV_TO_GIA[c]}" for c in counts if c in _AV_TO_GIA})

    result = {
        "is_av_event": sum(counts.values()) >= 5,
        "total_av_mentions": sum(counts.values()),
        "counts": counts,
        "found_terms": found_terms,
        "quantified_items": quantified,
        "suggested_helpers": suggested,
    }
    doc._cache_av_inventory = result
    return result


# =====================================================================
#  ANALISIS DE COTIZACIONES (v5.7) - AV vs Misceláneo + tipos de cable
# =====================================================================

# Categorias para clasificar items de una cotizacion
# v6.1: granularidad alta para Smart AV Inserter (cada subcategoria
# mapea a un tipo distinto de objeto renderizable).
_QUOTATION_CATEGORIES = {
    # ---- AUDIO ----
    "av_audio_main": (
        r"\b(line\s*array|k1\b|k2\b|kara\b|leopard|panther|jbl\s*vtx\s*a|"
        r"d&b\s*v|d&b\s*y|main\s*pa|fr.line)",
    ),
    "av_audio_sub": (
        r"\b(subwoofer|sub\s*woofer|sub\s*bass|ks28|ks21|vtx\s*b|"
        r"meyer\s*1100|d&b\s*j[\-\s]sub|sb\s*\d+)",
    ),
    "av_audio_monitor": (
        r"\b(monitor\s*de\s*piso|wedge|stage\s*monitor|floor\s*monitor|"
        r"sidefill|side\s*fill|drum\s*fill|m4\b|m2\b)",
    ),
    "av_audio_iem": (
        r"\b(in[\-\s]?ear|iem\b|psm\s*\d+|sennheiser\s*ew|shure\s*psm|"
        r"belt[\-\s]?pack|body[\-\s]?pack|transmisor\s*iem)",
    ),
    "av_audio_amp": (
        r"\b(amplificador|amplifier|powersoft|lab\.?gruppen|crown\s*x|"
        r"d80\b|d40\b|powered\s*rack)",
    ),
    "av_audio_processor": (
        r"\b(procesador|drive\s*rack|dsp|crossover|ecualizador|equalizer|"
        r"compresor|compressor|gate|effects|reverb|delay\s*rack)",
    ),
    "av_audio_di": (
        r"\b(di\s*box|direct\s*box|caja\s*directa|countryman|radial\s*di|"
        r"j48|jdi\b|active\s*di|passive\s*di)",
    ),
    "av_audio_console": (
        r"\b(consola\s*audio|console\s*audio|mixer\s*audio|mezcladora\s*audio|"
        r"midas\s*pro|digico\s*sd|yamaha\s*cl|yamaha\s*ql|yamaha\s*rivage|"
        r"avid\s*s\d|avid\s*venue|allen\s*heath\s*dlive|behringer\s*x32|"
        r"soundcraft\s*vi|m32\b)",
    ),
    "av_audio_stagebox": (
        r"\b(stage\s*box|stagebox|stage\s*rack|io\s*rack|dl\d+|"
        r"sd[\-\s]?rack|rio\s*\d+|sb\s*168|dn\d+)",
    ),
    "av_audio_speaker_aux": (  # bocinas no-line-array (delay, fills, point source)
        r"\b(altavoz|altavoces|bocina|loudspeaker|point\s*source|"
        r"fill\s*speaker|delay\s*speaker|d&b\s*e|q1\b|qsc|ev\s*\w+|"
        r"front[\-\s]?fill|out[\-\s]?fill)",
    ),
    "av_microphone_wireless": (
        r"\b(microfono\s*inalambrico|microphone\s*wireless|wireless\s*mic|"
        r"shure\s*ulx|shure\s*qlx|shure\s*axient|sennheiser\s*ew|"
        r"ew\s*ii?\s*\d|axient\s*digital|handheld\s*wireless)",
    ),
    "av_microphone_vocal": (
        r"\b(sm58|beta\s*58|beta\s*87|ksm9|sm87|vocal\s*mic|microfono\s*vocal)",
    ),
    "av_microphone_instrument": (
        r"\b(sm57|beta\s*57|beta\s*52|e604|e602|e609|e914|atm[\-\s]?23|"
        r"instrument\s*mic|microfono\s*instrumental|drum\s*mic|kick\s*mic|"
        r"snare\s*mic)",
    ),
    "av_microphone_condenser": (
        r"\b(condensador|condenser|c414|c451|km184|ksm32|ksm44|akg\s*c\d|"
        r"neumann|tlm|u87|overhead\s*mic|choir\s*mic)",
    ),
    "av_microphone_lavalier": (
        r"\b(lavalier|lapel|solapa|countryman\s*\w|dpa\s*4\d|sennheiser\s*me|"
        r"omni\s*lavalier|tie[\-\s]?clip)",
    ),

    # ---- VIDEO ----
    "av_video_led": (
        r"\b(led\s*wall|videowall|video\s*wall|pantalla\s*led|panel\s*led|"
        r"absen|roe\s*visual|infiled|unilumin|leyard|p[1-9]\.\d{1,3}\b)",
    ),
    "av_video_projector": (
        r"\b(proyector|projector|laser\s*projector|barco|christie\s*\w|"
        r"epson\s*\w|panasonic\s*pt|sony\s*vpl|wuxga|4k\s*projector|"
        r"\d{4,5}\s*l[uú]menes|lumens)",
    ),
    "av_video_screen": (
        r"\b(pantalla\s*frontal|pantalla\s*posterior|fast[\-\s]?fold|"
        r"da[\-\s]?lite|stewart\s*screen|cyc\s*screen|retroproy|"
        r"front\s*projection|rear\s*projection)",
    ),
    "av_video_camera": (
        r"\b(camara|cámara|camera|ptz|broadcast\s*cam|sony\s*hdc|"
        r"panasonic\s*ag|blackmagic\s*ursa|hd\s*camera|robocam|"
        r"camara\s*lipstick|lipstick\s*cam)",
    ),
    "av_video_switcher": (
        r"\b(switcher|atem|trycaster|tricaster|barco\s*e2|barco\s*s3|"
        r"e2\s*generation|encore|video\s*switcher|mezclador\s*video)",
    ),
    "av_video_distribution": (
        r"\b(distribuidor\s*video|video\s*distribution|scaler|matrix|"
        r"da[\-\s]?\d|extron|crestron\s*dm|kramer\s*\w|aja\s*\w|"
        r"video\s*server|playback|pixera|hippotizer|disguise|d3\b|notch)",
    ),
    "av_video_monitor": (
        r"\b(monitor\s*de\s*retorno|return\s*monitor|confidence\s*monitor|"
        r"reference\s*monitor|onstage\s*monitor|video\s*monitor)",
    ),

    # ---- LIGHTING ----
    "av_lighting_par": (
        r"\b(par\s*64|par\s*led|par\s*\d+|chauvet\s*par|elation\s*sixpar)",
    ),
    "av_lighting_mover_spot": (
        r"\b(robe\s*bmfl|mac\s*viper|megapointe|spot\s*moving|moving\s*spot|"
        r"esprite|robe\s*tetra)",
    ),
    "av_lighting_mover_wash": (
        r"\b(mac\s*aura|robe\s*tarrantula|wash\s*moving|moving\s*wash|"
        r"mac\s*encore\s*wash|robe\s*megapointe\s*wash|elation\s*proteus\s*hybrid)",
    ),
    "av_lighting_mover_beam": (
        r"\b(beam\s*moving|moving\s*beam|sharpy|beam\s*7r|beam\s*15r|"
        r"clay\s*paky\s*sharpy)",
    ),
    "av_lighting_source4": (
        r"\b(source\s*4|source4|s4\s*lustre|etc\s*s4|leko)",
    ),
    "av_lighting_strobe": (
        r"\b(strobe|estrobo|atomic\s*\d+|martin\s*atomic|sgm\s*q[\-\s]?7)",
    ),
    "av_lighting_blinder": (
        r"\b(blinder|molefey|mole[\-\s]?fey|dwe\s*blinder|audience\s*blinder)",
    ),
    "av_lighting_followspot": (
        r"\b(follow\s*spot|seguidor|robert\s*juliat|rj\s*korrigan|"
        r"lycian\s*\w+)",
    ),
    "av_lighting_console": (
        r"\b(grandma|hog\s*4|chamsys|magicq|onyx\s*ma|console\s*luc|"
        r"consola\s*luc|avo\s*sapphire)",
    ),
    "av_lighting_dimmer": (
        r"\b(dimmer|sensor3|etc\s*sensor|chilipro|rack\s*de\s*dimmer)",
    ),
    # Misceláneo - rigging, cables, accesorios, transporte, mano de obra
    "misc_rigging": (
        r"\b(truss|estructura\s*aluminio|rigging|prolyte|milos|tomcat|"
        r"global\s*truss|f34|f44|h30v|polipasto|chain\s*hoist|motor\s*\d*t|"
        r"verlinde|cm\s*lodestar|stagemaker|grillete|shackle|sling|bridle)",
    ),
    "misc_cables_video": (
        r"\b(cable\s*hdmi|cable\s*sdi|cable\s*video|fibra\s*video|fiber\s*video|"
        r"hdmi\s*\d+|sdi\s*\d+|displayport|dp\s*cable|vga\s*cable)",
    ),
    "misc_cables_audio": (
        r"\b(cable\s*xlr|cable\s*audio|cable\s*spk|speakon|multipair|snake|"
        r"manguera|xlr\s*\d+|trs\s*cable|jack\s*cable|stereo\s*cable)",
    ),
    "misc_cables_data": (
        r"\b(cable\s*ethernet|cable\s*red|cat\s*5|cat\s*6|cat\s*7|cat5e|"
        r"cable\s*dmx|dmx\s*cable|art-?net|cable\s*datos|data\s*cable|"
        r"cable\s*usb|usb\s*\d+)",
    ),
    "misc_power": (
        r"\b(distro|distribu(idor|ción)\s*eléctrica|powerlock|cam-?lok|"
        r"transformador|generador|breaker|tablero\s*eléctrico|cable\s*"
        r"eléctrico|cable\s*power|extension|extensión)",
    ),
    "misc_scenery": (
        r"\b(tarima|stage|riser|tension\s*fabric|spirals|drape|cortina|backdrop|"
        r"cyc|panel|valla|barrera|barricade|podium)",
    ),
    "misc_transport": (
        r"\b(transporte|flete|envio|envío|carga|trailer|trailler|montacargas|"
        r"forklift|grua|grúa)",
    ),
    "misc_labor": (
        r"\b(montaje|mano\s*de\s*obra|operador|personal|tecnico|técnico|"
        r"ingeniero|asistente|stagehand|labor|crew)",
    ),
    "misc_other": (
        r"\b(seguro|insurance|permiso|permit|licencia|impuesto|iva|tax)",
    ),
}

# Patron para detectar lineas tipo: "12 x Robe Robin BMFL @ $250 = $3000"
_QUOTE_LINE_PATTERN = re.compile(
    r"^\s*"
    r"(\d{1,4})\s*[xX×]?\s+"           # cantidad
    r"([A-Za-z][^\$\n]{3,80}?)"        # descripcion
    r"(?:[\$\€\£\s]+(\d[\d,\.]*))?"   # precio unitario opcional
    r"(?:[\$\€\£\s]+(\d[\d,\.]*))?"   # precio total opcional
    r"\s*$",
    re.MULTILINE,
)


def _classify_quotation_line(text):
    """Clasifica una linea de cotizacion en una categoria conocida."""
    text_lower = text.lower()
    for category, patterns in _QUOTATION_CATEGORIES.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return category
    return "misc_other"


def extract_quotation_items(doc):
    """
    Analiza un PDF como cotizacion: detecta items, los clasifica en
    AV-equipo (renderizable) vs Miscelaneo (no renderizable normalmente).

    Devuelve:
      {
        "is_quotation": bool,
        "total_items_detected": int,
        "av_renderable": [{"qty", "description", "category", "unit_price", "total"}, ...],
        "miscellaneous": [{"qty", "description", "category", "unit_price", "total"}, ...],
        "by_category": {cat_name: [items...]},
        "totals": {"av_count": N, "misc_count": N, "estimated_total_value": float},
        "cable_inventory": {"video": [...], "audio": [...], "data": [...]},
      }
    """
    text = doc.total_text() if hasattr(doc, 'total_text') else ""
    if not text:
        return {"is_quotation": False, "total_items_detected": 0,
                "av_renderable": [], "miscellaneous": [], "by_category": {},
                "totals": {}, "cable_inventory": {}}

    av_items = []
    misc_items = []
    by_category = {}
    cable_inventory = {"video": [], "audio": [], "data": []}
    total_value = 0.0

    for match in _QUOTE_LINE_PATTERN.finditer(text):
        try:
            qty_str = match.group(1)
            desc = (match.group(2) or "").strip()
            unit_str = match.group(3)
            total_str = match.group(4)

            qty = int(qty_str)
            if qty < 1 or qty > 9999:
                continue
            if len(desc) < 3:
                continue

            unit_price = None
            if unit_str:
                try: unit_price = float(unit_str.replace(",", ""))
                except ValueError: pass
            line_total = None
            if total_str:
                try:
                    line_total = float(total_str.replace(",", ""))
                    total_value += line_total
                except ValueError: pass

            category = _classify_quotation_line(desc)
            item = {
                "qty": qty,
                "description": desc[:120],
                "category": category,
                "unit_price": unit_price,
                "total": line_total,
            }

            by_category.setdefault(category, []).append(item)

            if category.startswith("av_"):
                av_items.append(item)
            else:
                misc_items.append(item)

            # Detectar cables especificos
            if category == "misc_cables_video":
                cable_inventory["video"].append({"qty": qty, "desc": desc[:80]})
            elif category == "misc_cables_audio":
                cable_inventory["audio"].append({"qty": qty, "desc": desc[:80]})
            elif category == "misc_cables_data":
                cable_inventory["data"].append({"qty": qty, "desc": desc[:80]})
        except Exception:
            continue

    is_quotation = len(av_items) + len(misc_items) >= 3

    return {
        "is_quotation": is_quotation,
        "total_items_detected": len(av_items) + len(misc_items),
        "av_renderable": av_items,
        "miscellaneous": misc_items,
        "by_category": by_category,
        "cable_inventory": cable_inventory,
        "totals": {
            "av_count": len(av_items),
            "misc_count": len(misc_items),
            "estimated_total_value": round(total_value, 2),
            "av_qty_sum": sum(i["qty"] for i in av_items),
            "misc_qty_sum": sum(i["qty"] for i in misc_items),
        },
    }


def quotation_to_av_spec(quotation_data):
    """
    Convierte el resultado de extract_quotation_items en una spec rica
    que el Smart AV Inserter consume.

    Devuelve estructura granular con:
      audio: main / sub / monitor / iem / amp / processor / di / console /
             stagebox / speaker_aux / mics (wireless/vocal/instrument/condenser/lavalier)
      video: led_wall (m2 estimados) / projectors / screens / cameras /
             switcher / distribution / monitor
      lighting: par / mover_spot / mover_wash / mover_beam / source4 / strobe /
                blinder / followspot / console / dimmer
      cabling: video / audio / data / power
      misc: rigging / scenery / labor / transport
      counts: total objetos renderizables sumados

    Cada subkey lleva qty y modelos detectados ([{model: str, qty: N}]) para
    que el Smart AV Inserter manifieste con el simbolo correcto cuando exista.
    """
    def _empty():
        return {"qty": 0, "models": []}

    spec = {
        "audio": {
            "main":          _empty(),
            "sub":           _empty(),
            "monitor":       _empty(),
            "iem":           _empty(),
            "amp":           _empty(),
            "processor":     _empty(),
            "di":            _empty(),
            "console":       _empty(),
            "stagebox":      _empty(),
            "speaker_aux":   _empty(),
            "mic_wireless":   _empty(),
            "mic_vocal":      _empty(),
            "mic_instrument": _empty(),
            "mic_condenser":  _empty(),
            "mic_lavalier":   _empty(),
        },
        "video": {
            "led_wall":     _empty(),
            "projector":    _empty(),
            "screen":       _empty(),
            "camera":       _empty(),
            "switcher":     _empty(),
            "distribution": _empty(),
            "monitor":      _empty(),
        },
        "lighting": {
            "par":         _empty(),
            "mover_spot":  _empty(),
            "mover_wash":  _empty(),
            "mover_beam":  _empty(),
            "source4":     _empty(),
            "strobe":      _empty(),
            "blinder":     _empty(),
            "followspot":  _empty(),
            "console":     _empty(),
            "dimmer":      _empty(),
        },
        "cabling": {
            "video": [], "audio": [], "data": [], "power": [],
        },
        "misc": {
            "rigging": [], "scenery": [], "labor": [], "transport": [],
        },
        "stage": {},
        "options": {"signal_flow": True, "use_pio": True,
                    "auto_layout": True},
        "totals": {"renderable_objects": 0, "total_qty": 0,
                   "estimated_value": 0.0},
    }

    # Mapeo categoria -> (familia, subkey)
    cat_to_path = {
        "av_audio_main":         ("audio", "main"),
        "av_audio_sub":          ("audio", "sub"),
        "av_audio_monitor":      ("audio", "monitor"),
        "av_audio_iem":          ("audio", "iem"),
        "av_audio_amp":          ("audio", "amp"),
        "av_audio_processor":    ("audio", "processor"),
        "av_audio_di":           ("audio", "di"),
        "av_audio_console":      ("audio", "console"),
        "av_audio_stagebox":     ("audio", "stagebox"),
        "av_audio_speaker_aux":  ("audio", "speaker_aux"),
        "av_microphone_wireless":  ("audio", "mic_wireless"),
        "av_microphone_vocal":     ("audio", "mic_vocal"),
        "av_microphone_instrument":("audio", "mic_instrument"),
        "av_microphone_condenser": ("audio", "mic_condenser"),
        "av_microphone_lavalier":  ("audio", "mic_lavalier"),

        "av_video_led":          ("video", "led_wall"),
        "av_video_projector":    ("video", "projector"),
        "av_video_screen":       ("video", "screen"),
        "av_video_camera":       ("video", "camera"),
        "av_video_switcher":     ("video", "switcher"),
        "av_video_distribution": ("video", "distribution"),
        "av_video_monitor":      ("video", "monitor"),

        "av_lighting_par":         ("lighting", "par"),
        "av_lighting_mover_spot":  ("lighting", "mover_spot"),
        "av_lighting_mover_wash":  ("lighting", "mover_wash"),
        "av_lighting_mover_beam":  ("lighting", "mover_beam"),
        "av_lighting_source4":     ("lighting", "source4"),
        "av_lighting_strobe":      ("lighting", "strobe"),
        "av_lighting_blinder":     ("lighting", "blinder"),
        "av_lighting_followspot":  ("lighting", "followspot"),
        "av_lighting_console":     ("lighting", "console"),
        "av_lighting_dimmer":      ("lighting", "dimmer"),
    }

    misc_map = {
        "misc_rigging":   "rigging",
        "misc_scenery":   "scenery",
        "misc_labor":     "labor",
        "misc_transport": "transport",
    }
    cable_map = {
        "misc_cables_video": "video",
        "misc_cables_audio": "audio",
        "misc_cables_data":  "data",
        "misc_power":        "power",
    }

    av = quotation_data.get("av_renderable", [])
    misc = quotation_data.get("miscellaneous", [])

    for item in av:
        cat = item.get("category", "")
        qty = int(item.get("qty", 1) or 1)
        desc = item.get("description", "")
        path = cat_to_path.get(cat)
        if not path:
            continue
        family, sub = path
        spec[family][sub]["qty"] += qty
        spec[family][sub]["models"].append({"model": desc[:80], "qty": qty})
        spec["totals"]["renderable_objects"] += 1
        spec["totals"]["total_qty"] += qty

    for item in misc:
        cat = item.get("category", "")
        qty = int(item.get("qty", 1) or 1)
        desc = item.get("description", "")
        if cat in cable_map:
            spec["cabling"][cable_map[cat]].append({
                "qty": qty, "desc": desc[:80]})
        elif cat in misc_map:
            spec["misc"][misc_map[cat]].append({
                "qty": qty, "desc": desc[:80]})

    spec["totals"]["estimated_value"] = float(
        quotation_data.get("totals", {}).get("estimated_total_value", 0.0))

    # ---- Spec compatible con tools legacy (quick_audio_setup, etc.) ----
    # Para que el Smart AV Inserter pueda seguir invocando los quick_*
    # sin perder informacion, sintetizamos counts agregados.
    a = spec["audio"]
    spec["legacy_quick_audio"] = {
        "speaker_count": a["main"]["qty"] + a["speaker_aux"]["qty"],
        "sub_count":     a["sub"]["qty"],
        "mic_count":     (a["mic_wireless"]["qty"] + a["mic_vocal"]["qty"] +
                          a["mic_instrument"]["qty"] + a["mic_condenser"]["qty"] +
                          a["mic_lavalier"]["qty"]),
        "monitor_count": a["monitor"]["qty"],
        "iem_count":     a["iem"]["qty"],
        "has_mixer":     a["console"]["qty"] > 0,
        "has_stagebox":  a["stagebox"]["qty"] > 0,
    }
    L = spec["lighting"]
    spec["legacy_quick_lighting"] = {
        "par_count":     L["par"]["qty"],
        "mover_count":   (L["mover_spot"]["qty"] + L["mover_wash"]["qty"] +
                          L["mover_beam"]["qty"]),
        "source4_count": L["source4"]["qty"],
        "strobe_count":  L["strobe"]["qty"],
        "blinder_count": L["blinder"]["qty"],
    }
    V = spec["video"]
    spec["legacy_quick_video"] = {
        "led_wall":         V["led_wall"]["qty"] > 0,
        "led_panel_count":  V["led_wall"]["qty"],
        "projector_count":  V["projector"]["qty"],
        "screen_count":     V["screen"]["qty"],
        "camera_count":     V["camera"]["qty"],
        "switcher_count":   V["switcher"]["qty"],
    }
    return spec


# =====================================================================
#  SINTESIS DE PROMPT GEOMETRICO
# =====================================================================

def synthesize_geometric_prompt(doc: PDFDocument, intent: str = "manifestar") -> str:
    """
    Toma un PDF analizado y emite un prompt ULTRA-PRECISO que el modelo
    usa directamente para generar VectorScript.

    Intents:
      manifestar  - planta arquitectonica en VW
      analizar    - solo reporte textual
      programa    - tabla de espacios y areas
      audiovisual - escenario/evento AV con equipo (pantallas, bocinas, luces, truss)
    """
    feats = extract_architectural_features(doc)
    av = extract_av_equipment(doc)
    lines = []

    lines.append(f"# PROMPT SINTETIZADO desde '{doc.filename}'")
    lines.append(f"# Backend: {doc.backend_used} | Paginas: {doc.page_count}")
    tipo = "ARQUITECTONICO" if feats["is_architectural"] else "TEXTO/DATOS"
    if av["is_av_event"]:
        tipo += " + AV-EVENT"
    lines.append(f"# Tipo: {tipo}")
    lines.append("")

    # Resumen arquitectonico
    if feats["scale"]:
        lines.append(f"Escala detectada: {feats['scale']}")
    if feats["dimensions"]:
        lines.append(f"Dimensiones encontradas ({len(feats['dimensions'])}): " +
                     ", ".join(feats["dimensions"][:10]))
    if feats["areas"]:
        lines.append(f"Areas encontradas: " + ", ".join(feats["areas"][:8]))
    if feats["rooms"]:
        lines.append(f"Espacios identificados: " + ", ".join(feats["rooms"]))

    # Resumen AV
    if av["counts"]:
        lines.append("")
        lines.append("EQUIPO AV DETECTADO:")
        for cat, n in sorted(av["counts"].items(), key=lambda x: -x[1]):
            terms = av["found_terms"].get(cat, [])
            term_str = ", ".join(terms[:3])
            lines.append(f"  - {cat}: {n} menciones [{term_str}]")
        if av["quantified_items"]:
            lines.append("")
            lines.append("ITEMS CUANTIFICADOS (heuristica):")
            for item in av["quantified_items"][:10]:
                lines.append(f"  - {item['qty']} x {item['term']} -> {item['category']}")
        if av["suggested_helpers"]:
            lines.append("Helpers gia.* sugeridos: " + ", ".join(av["suggested_helpers"]))

    if feats["table_count"]:
        lines.append("")
        lines.append(f"Tablas extraidas: {feats['table_count']}")
    lines.append("")

    # Instruccion concreta segun intent
    if intent == "manifestar":
        lines.append("INSTRUCCION:")
        lines.append("Usando los datos arriba, manifiesta en Vectorworks 2026 la planta descrita "
                     "en el PDF. Sigue esta secuencia:")
        lines.append("")
        lines.append("1. Crea una capa nueva 'Planta-PDF' y activala (set_active_layer).")
        lines.append("2. Para cada espacio identificado, manifiesta un rectangulo del tamano "
                     "correspondiente (en mm: si el PDF da metros, MULTIPLICA POR 1000).")
        lines.append("3. Distribuye los rectangulos en grilla con separacion de 500 mm para que "
                     "no se solapen.")
        lines.append("4. Para cada rectangulo, anade etiqueta de texto con el nombre del espacio "
                     "y su area en m2.")
        lines.append("5. Si hay dimensiones de muros perimetrales claras, manifestar muros "
                     "(create_wall) de 200 mm de espesor y 2700 mm de altura por defecto.")
        lines.append("6. Reporta al final: cuantos espacios manifestados, area total construida.")

    elif intent == "analizar":
        lines.append("INSTRUCCION:")
        lines.append("Sintetiza un reporte estructurado del PDF: programa arquitectonico, "
                     "areas, prestaciones tecnicas, equipo AV, ambiguedades a resolver. "
                     "NO manifiestes geometria, solo analisis textual.")

    elif intent == "programa":
        lines.append("INSTRUCCION:")
        lines.append("Construye una tabla del programa arquitectonico: nombre del espacio, "
                     "area, observaciones. Si hay dimensiones x by y, usa esas; si solo hay "
                     "area, asume proporcion 4:3 al dimensionar.")

    elif intent == "audiovisual":
        lines.append("INSTRUCCION:")
        lines.append("Manifiesta en Vectorworks 2026 el escenario AV descrito en el PDF "
                     "usando los HELPERS gia.* (capa de abstraccion). Sigue esta secuencia:")
        lines.append("")
        lines.append("1. Crea capa 'AV-Event' y activala.")
        lines.append("2. Manifiesta la INFRAESTRUCTURA primero:")
        lines.append("   - gia.stage(...)        si hay tarima/escenario")
        lines.append("   - gia.truss_grid(...)   o gia.truss_box(...) para rigging frontal")
        lines.append("   - gia.truss(...)        para colgantes individuales")
        lines.append("3. Manifiesta AUDIO:")
        lines.append("   - gia.speaker_array(...) en L/R sobre el truss")
        lines.append("   - gia.subwoofer(...)    pegados al piso bajo el line array")
        lines.append("   - gia.speaker(model='Kara') para fills, monitores")
        lines.append("4. Manifiesta VIDEO:")
        lines.append("   - gia.screen(...)      para pantallas LED (dim tipico 6000x3375 mm)")
        lines.append("   - gia.projector(...)   si hay proyector con throw point")
        lines.append("   - gia.camera(...)      camaras con look-at al centro del escenario")
        lines.append("5. Manifiesta ILUMINACION:")
        lines.append("   - gia.moving_head(..., target_x=, target_y=, target_z=)  con apuntes")
        lines.append("   - gia.lighting(..., type='par64'|'led_par'|'blinder')")
        lines.append("6. ELEMENTOS ESCENICOS adicionales:")
        lines.append("   - gia.dj_booth(...) para cabina")
        lines.append("   - gia.microphone(...) en posiciones de tarima")
        lines.append("")
        lines.append("USA gia.scene([{...}, {...}]) para manifestar TODO en una sola llamada.")
        lines.append("")
        lines.append("CONVENCIONES de coordenadas para escenarios:")
        lines.append("- Origen (0,0,0) = downstage center, piso")
        lines.append("- Eje X positivo = stage right (mirando hacia el publico)")
        lines.append("- Eje Y positivo = upstage (alejandose del publico)")
        lines.append("- Eje Z positivo = arriba")
        lines.append("- Escenario tipico: 12000 x 8000 x 1000 mm; truss a z=7000")
        lines.append("- Line array K2 colgado a z=6500, 8 cajas x lado")

    else:
        lines.append(f"INSTRUCCION: {intent}")

    lines.append("")
    lines.append("REGLAS CRITICAS:")
    lines.append("- Vectorworks usa unidades del documento. Asume mm. Si el PDF dice metros, x1000.")
    lines.append("- PREFERIR helpers gia.* sobre vs.* directo cuando exista equivalente.")
    lines.append("- Para geometria custom: vs.Rect(...) ; src=vs.LNewObj() ; vs.SetSelect(src) ; "
                 "vs.BeginXtrd(0, h) ; vs.Add3DObj(src) ; vs.EndXtrd() ; result=vs.LNewObj()")
    lines.append("- NO existe vs.Extrude. Usar el patron BeginXtrd/Add3DObj/EndXtrd.")
    lines.append("- Asignar SIEMPRE a 'result' el resultado (handle, lista de ids, o str).")

    return "\n".join(lines)


# =====================================================================
#  AUTOTEST CLI
# =====================================================================
if __name__ == "__main__":
    import sys
    deps = check_dependencies()
    print("=== GIA pdf_processor ===")
    print("Dependencias:", deps)
    if not deps["ready"]:
        print("Instala: pip install pymupdf pdfplumber")
        sys.exit(1)
    if len(sys.argv) > 1:
        path = sys.argv[1]
        print(f"\nProcesando {path}...")
        proc = PDFProcessor()
        doc = proc.process(path, progress_cb=lambda c, t, p: print(f"  [{c}/{t}] {p}"))
        print(f"\nResultado: {doc.to_dict()}")
        print("\nFeatures:", extract_architectural_features(doc))
        print("\n--- Prompt sintetizado ---")
        print(synthesize_geometric_prompt(doc))
    else:
        print("Uso: python pdf_processor.py <archivo.pdf>")
