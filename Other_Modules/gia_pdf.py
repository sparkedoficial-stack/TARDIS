"""
GIA · Modulo de procesamiento PDF para generacion de modelos 3D
================================================================
Capacidades:
  - Extraccion de texto, imagenes y metadatos de PDF
  - Renderizado de paginas como imagenes para analisis visual
  - Analisis multimodal con modelo de vision local (llava, qwen2.5-vl)
  - Generacion de prompts arquitectonicos para qwen3-coder:30b
  - Pipeline completo PDF -> analisis -> codigo VectorScript

Arquitecto · Sistema GIA · v1.0-PDF-CRYSTAL
"""
from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

import httpx

# ===== DEPENDENCIAS PDF =====
# Estrategia robusta: probar PyMuPDF (mas rapido y completo), fallback a pypdf
try:
    import fitz  # PyMuPDF
    PDF_BACKEND = "pymupdf"
except ImportError:
    try:
        import pypdf
        PDF_BACKEND = "pypdf"
    except ImportError:
        PDF_BACKEND = None


# =====================================================================
#  ESTRUCTURAS DE DATOS
# =====================================================================

@dataclass
class PageContent:
    """Contenido extraido de una pagina."""
    page_number: int
    text: str
    image_count: int
    width: float
    height: float
    rendered_image_b64: str = ""  # PNG base64 para vision
    extracted_dimensions: list[str] = field(default_factory=list)
    detected_keywords: list[str] = field(default_factory=list)


@dataclass
class PDFAnalysis:
    """Resultado completo del analisis."""
    source_path: str
    page_count: int
    pages: list[PageContent] = field(default_factory=list)
    document_type: str = "desconocido"  # plano, render, especificacion, mixto
    detected_scale: str | None = None
    detected_units: str = "mm"
    raw_text_full: str = ""
    summary: str = ""
    suggested_prompts: list[str] = field(default_factory=list)
    extraction_backend: str = PDF_BACKEND or "none"


# =====================================================================
#  EXTRACTOR DE PDF
# =====================================================================

class PDFExtractor:
    """Extrae texto, imagenes y renderiza paginas."""

    UNIT_PATTERNS = {
        "mm": [r"\bmm\b", r"\bmilimetros?\b", r"\bmilimetres?\b"],
        "cm": [r"\bcm\b", r"\bcentimetros?\b"],
        "m":  [r"\bmts?\b", r"\bmetros?\b", r"\bm²\b", r"\bm2\b"],
        "ft": [r"\bft\b", r"\bfeet\b", r"\bpies\b"],
        "in": [r"\bin\b", r"\binch(es)?\b", r"\bpulgadas?\b"],
    }

    DIMENSION_PATTERN = re.compile(
        r"(\d+(?:[.,]\d+)?)\s*(?:x|X|\*|por)\s*(\d+(?:[.,]\d+)?)"
        r"(?:\s*(?:x|X|\*|por)\s*(\d+(?:[.,]\d+)?))?\s*"
        r"(mm|cm|m|ft|in|pies|metros?|centimetros?)?",
        re.IGNORECASE
    )

    SCALE_PATTERN = re.compile(r"(?:escala|scale|esc\.?)\s*[:\-]?\s*1\s*[:/]\s*(\d+)", re.IGNORECASE)

    KEYWORD_DICT = {
        "plano":      ["plano", "planta", "planimetria", "floor plan"],
        "fachada":    ["fachada", "elevation", "frontal", "lateral"],
        "corte":      ["corte", "seccion", "section"],
        "muro":       ["muro", "pared", "wall"],
        "puerta":     ["puerta", "door"],
        "ventana":    ["ventana", "window"],
        "techo":      ["techo", "cubierta", "roof"],
        "estructura": ["columna", "viga", "losa", "column", "beam", "slab"],
        "mobiliario": ["mesa", "silla", "cama", "sofa", "table", "chair", "bed"],
    }

    def __init__(self):
        if PDF_BACKEND is None:
            raise RuntimeError(
                "Sin backend PDF disponible. Instala con: pip install pymupdf"
            )

    def extract(self, pdf_path: str | Path, render_dpi: int = 100,
                max_pages: int = 20, render_for_vision: bool = True) -> PDFAnalysis:
        """Extrae contenido completo del PDF."""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF no encontrado: {pdf_path}")

        if PDF_BACKEND == "pymupdf":
            return self._extract_pymupdf(pdf_path, render_dpi, max_pages, render_for_vision)
        elif PDF_BACKEND == "pypdf":
            return self._extract_pypdf(pdf_path, max_pages)
        else:
            raise RuntimeError("backend no disponible")

    def _extract_pymupdf(self, pdf_path: Path, dpi: int, max_pages: int,
                         render: bool) -> PDFAnalysis:
        doc = fitz.open(str(pdf_path))
        analysis = PDFAnalysis(
            source_path=str(pdf_path),
            page_count=len(doc),
            extraction_backend="pymupdf"
        )
        full_text_parts = []

        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            text = page.get_text()
            full_text_parts.append(text)

            pc = PageContent(
                page_number=i + 1,
                text=text,
                image_count=len(page.get_images()),
                width=page.rect.width,
                height=page.rect.height,
            )
            pc.extracted_dimensions = self._extract_dimensions(text)
            pc.detected_keywords = self._detect_keywords(text)

            if render:
                # Render a PNG base64 para analisis visual
                mat = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_bytes = pix.tobytes("png")
                pc.rendered_image_b64 = base64.b64encode(img_bytes).decode("ascii")

            analysis.pages.append(pc)

        doc.close()
        analysis.raw_text_full = "\n\n".join(full_text_parts)
        analysis.detected_units = self._detect_units(analysis.raw_text_full)
        analysis.detected_scale = self._detect_scale(analysis.raw_text_full)
        analysis.document_type = self._classify_document(analysis)
        return analysis

    def _extract_pypdf(self, pdf_path: Path, max_pages: int) -> PDFAnalysis:
        """Fallback sin renderizado de imagenes."""
        reader = pypdf.PdfReader(str(pdf_path))
        analysis = PDFAnalysis(
            source_path=str(pdf_path),
            page_count=len(reader.pages),
            extraction_backend="pypdf"
        )
        full_text_parts = []
        for i, page in enumerate(reader.pages):
            if i >= max_pages:
                break
            text = page.extract_text() or ""
            full_text_parts.append(text)
            pc = PageContent(
                page_number=i + 1,
                text=text,
                image_count=0,
                width=float(page.mediabox.width),
                height=float(page.mediabox.height),
            )
            pc.extracted_dimensions = self._extract_dimensions(text)
            pc.detected_keywords = self._detect_keywords(text)
            analysis.pages.append(pc)
        analysis.raw_text_full = "\n\n".join(full_text_parts)
        analysis.detected_units = self._detect_units(analysis.raw_text_full)
        analysis.detected_scale = self._detect_scale(analysis.raw_text_full)
        analysis.document_type = self._classify_document(analysis)
        return analysis

    def _extract_dimensions(self, text: str) -> list[str]:
        """Encuentra patrones tipo '5x3 m', '1200x800x600 mm', etc."""
        matches = self.DIMENSION_PATTERN.findall(text)
        results = []
        for m in matches:
            w, h, d, unit = m
            unit = unit or ""
            if d:
                results.append(f"{w}x{h}x{d} {unit}".strip())
            else:
                results.append(f"{w}x{h} {unit}".strip())
        return list(set(results))[:30]  # dedupe + cap

    def _detect_units(self, text: str) -> str:
        """Detecta unidad predominante."""
        counts = {}
        for unit, patterns in self.UNIT_PATTERNS.items():
            counts[unit] = sum(len(re.findall(p, text, re.IGNORECASE)) for p in patterns)
        if not any(counts.values()):
            return "mm"
        return max(counts, key=counts.get)

    def _detect_scale(self, text: str) -> str | None:
        m = self.SCALE_PATTERN.search(text)
        return f"1:{m.group(1)}" if m else None

    def _detect_keywords(self, text: str) -> list[str]:
        text_lower = text.lower()
        found = []
        for category, words in self.KEYWORD_DICT.items():
            if any(w in text_lower for w in words):
                found.append(category)
        return found

    def _classify_document(self, analysis: PDFAnalysis) -> str:
        all_keywords = set()
        for p in analysis.pages:
            all_keywords.update(p.detected_keywords)
        if {"plano", "muro", "puerta"} & all_keywords:
            return "plano arquitectonico"
        if "fachada" in all_keywords:
            return "fachada / elevacion"
        if "corte" in all_keywords:
            return "corte / seccion"
        if "estructura" in all_keywords:
            return "plano estructural"
        if "mobiliario" in all_keywords:
            return "mobiliario / interiorismo"
        return "documento generico"


# =====================================================================
#  ANALIZADOR MULTIMODAL (visión local)
# =====================================================================

class VisionAnalyzer:
    """Usa modelo de vision local (llava, qwen2.5-vl, llama3.2-vision) via Ollama."""

    SYSTEM_VISION = """Analiza esta imagen de un documento arquitectonico.
Identifica con precision:
1. Tipo de dibujo (plano de planta, fachada, corte, perspectiva, render)
2. Elementos visibles (muros, puertas, ventanas, mobiliario, escaleras)
3. Dimensiones aproximadas si son legibles
4. Proporciones generales del espacio
5. Caracteristicas geometricas relevantes

Responde de forma estructurada y concisa en espanol."""

    def __init__(self, ollama_url: str = "http://REDACTED_IP:11434"):
        self.url = ollama_url.rstrip("/")

    def list_vision_models(self) -> list[str]:
        """Detecta modelos con capacidad de vision instalados."""
        try:
            with httpx.Client(timeout=5.0) as c:
                r = c.get(f"{self.url}/api/tags")
                models = r.json().get("models", [])
            vision_keywords = ["llava", "vision", "vl", "bakllava", "moondream", "minicpm"]
            return [m["name"] for m in models
                    if any(k in m["name"].lower() for k in vision_keywords)]
        except Exception:
            return []

    def analyze_page(self, page: PageContent, model: str,
                     custom_prompt: str | None = None,
                     timeout: float = 120.0) -> str:
        """Envia la imagen renderizada al modelo de vision."""
        if not page.rendered_image_b64:
            return "(sin imagen renderizada)"
        prompt = custom_prompt or self.SYSTEM_VISION
        try:
            with httpx.Client(timeout=timeout) as c:
                r = c.post(f"{self.url}/api/chat", json={
                    "model": model,
                    "messages": [{
                        "role": "user",
                        "content": prompt,
                        "images": [page.rendered_image_b64]
                    }],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 600}
                })
                if r.status_code != 200:
                    return f"[error vision {r.status_code}]"
                return r.json().get("message", {}).get("content", "(vacio)")
        except Exception as e:
            return f"[excepcion vision: {e}]"


# =====================================================================
#  GENERADOR DE PROMPTS GEOMETRICOS
# =====================================================================

class GeometryPromptBuilder:
    """Convierte un PDFAnalysis + analisis visual en prompts para qwen3-coder."""

    def build_prompts(self, analysis: PDFAnalysis,
                      vision_descriptions: dict[int, str] | None = None) -> list[str]:
        """Genera lista de prompts arquitectonicos accionables."""
        prompts = []
        vision = vision_descriptions or {}

        # Prompt maestro: vista general del documento
        master = self._build_master_prompt(analysis, vision)
        prompts.append(master)

        # Prompts especificos por pagina con contenido relevante
        for page in analysis.pages:
            if page.detected_keywords or page.extracted_dimensions:
                pp = self._build_page_prompt(page, analysis, vision.get(page.page_number))
                if pp:
                    prompts.append(pp)

        return prompts

    def _build_master_prompt(self, analysis: PDFAnalysis,
                             vision: dict[int, str]) -> str:
        parts = []
        parts.append(f"# CONTEXTO DEL DOCUMENTO PDF")
        parts.append(f"Tipo detectado: {analysis.document_type}")
        parts.append(f"Paginas: {analysis.page_count}")
        parts.append(f"Unidades: {analysis.detected_units}")
        if analysis.detected_scale:
            parts.append(f"Escala: {analysis.detected_scale}")

        all_dims = []
        for p in analysis.pages:
            all_dims.extend(p.extracted_dimensions)
        if all_dims:
            parts.append(f"\nDimensiones extraidas:\n" + "\n".join(f"  - {d}" for d in all_dims[:15]))

        all_kw = set()
        for p in analysis.pages:
            all_kw.update(p.detected_keywords)
        if all_kw:
            parts.append(f"\nElementos detectados: {', '.join(sorted(all_kw))}")

        if vision:
            parts.append("\n# ANALISIS VISUAL POR PAGINA")
            for pn, desc in sorted(vision.items()):
                parts.append(f"\nPagina {pn}:\n{desc}")

        parts.append("\n# TAREA")
        parts.append(
            "Manifiesta en Vectorworks la geometria 3D que mejor represente "
            "este documento. Usa execute_vectorscript con codigo Python valido. "
            f"Trabaja en unidades {analysis.detected_units}. "
            "Si es un plano, extruye los muros a altura estandar 2700 mm. "
            "Si es una fachada, modela los elementos como volumenes. "
            "Crea capas y clases coherentes con la estructura del documento."
        )
        return "\n".join(parts)

    def _build_page_prompt(self, page: PageContent, analysis: PDFAnalysis,
                           vision_text: str | None) -> str | None:
        if not (page.detected_keywords or page.extracted_dimensions):
            return None
        parts = [f"# PAGINA {page.page_number}"]
        if page.detected_keywords:
            parts.append(f"Contenido: {', '.join(page.detected_keywords)}")
        if page.extracted_dimensions:
            parts.append(f"Dimensiones: {', '.join(page.extracted_dimensions[:10])}")
        if vision_text:
            parts.append(f"Vision IA:\n{vision_text[:400]}")
        parts.append(
            f"\nManifiesta esta pagina como geometria 3D en Vectorworks "
            f"con unidades {analysis.detected_units}. Asigna a una capa "
            f"llamada 'Pagina_{page.page_number}'."
        )
        return "\n".join(parts)


# =====================================================================
#  PIPELINE COMPLETO
# =====================================================================

class PDFToGeometryPipeline:
    """Orquesta extraccion + vision + generacion de prompts."""

    def __init__(self, ollama_url: str = "http://REDACTED_IP:11434"):
        self.extractor = PDFExtractor()
        self.vision = VisionAnalyzer(ollama_url)
        self.prompt_builder = GeometryPromptBuilder()

    def process(self, pdf_path: str | Path,
                use_vision: bool = True,
                vision_model: str | None = None,
                max_pages: int = 10,
                progress_callback: Callable[[str], None] | None = None) -> dict:
        """Pipeline completo. Retorna dict con analysis y prompts."""
        def log(msg):
            if progress_callback:
                progress_callback(msg)

        log(f"Extrayendo PDF: {pdf_path}")
        analysis = self.extractor.extract(pdf_path, max_pages=max_pages,
                                          render_for_vision=use_vision)
        log(f"Extraidas {len(analysis.pages)} paginas - tipo: {analysis.document_type}")

        vision_results = {}
        if use_vision:
            vision_models = self.vision.list_vision_models()
            if not vision_models:
                log("Sin modelos de vision instalados - omitiendo analisis visual")
                log("Instala con: ollama pull llava:13b  o  ollama pull qwen2.5vl:7b")
            else:
                model = vision_model or vision_models[0]
                log(f"Analizando paginas con vision: {model}")
                for page in analysis.pages:
                    if page.rendered_image_b64:
                        log(f"  Analizando pagina {page.page_number}...")
                        desc = self.vision.analyze_page(page, model)
                        vision_results[page.page_number] = desc

        log("Generando prompts arquitectonicos...")
        prompts = self.prompt_builder.build_prompts(analysis, vision_results)
        analysis.suggested_prompts = prompts

        log(f"Pipeline completo: {len(prompts)} prompts generados")
        return {
            "analysis": analysis,
            "vision_results": vision_results,
            "prompts": prompts,
        }


# =====================================================================
#  TEST AUTONOMO
# =====================================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python gia_pdf.py <archivo.pdf> [--no-vision]")
        sys.exit(1)
    pdf = sys.argv[1]
    use_vision = "--no-vision" not in sys.argv

    print(f"Backend PDF: {PDF_BACKEND}")
    if PDF_BACKEND is None:
        print("ERROR: instala con 'pip install pymupdf'")
        sys.exit(1)

    pipeline = PDFToGeometryPipeline()
    result = pipeline.process(pdf, use_vision=use_vision,
                              progress_callback=lambda m: print(f"  > {m}"))

    print("\n" + "=" * 60)
    print("ANALISIS")
    print("=" * 60)
    a = result["analysis"]
    print(f"Tipo: {a.document_type}")
    print(f"Paginas: {a.page_count}")
    print(f"Unidades: {a.detected_units}")
    print(f"Escala: {a.detected_scale}")

    print("\n" + "=" * 60)
    print(f"PROMPTS GENERADOS ({len(result['prompts'])})")
    print("=" * 60)
    for i, p in enumerate(result["prompts"], 1):
        print(f"\n--- PROMPT {i} ---")
        print(p[:500] + ("..." if len(p) > 500 else ""))
