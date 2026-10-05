"""
gia_sales_presentation.py - Compositor de PDF de presentacion de ventas.
=========================================================================

Toma N renders PNG (front/side/iso/top) + tabla de equipo + metadata y
produce un PDF profesional listo para enviar al cliente.

Layout del PDF:
    Pagina 1: portada con titulo, cliente, fecha, hero render iso
    Pagina 2: 2x2 grid de renders (front, side, iso, top)
    Pagina 3: tabla de equipo (Audio | Lighting | Video | Structure)
    Pagina 4: metricas (potencia, rigging, audiencia, costo opcional)

Usa pymupdf (fitz) que ya esta instalado en el venv.

API:
    build_sales_pdf(
        output_path: str,
        title: str,
        client_name: str = "",
        renders: dict[str, str] = None,   # {view_name: png_path}
        equipment: dict[str, int] = None, # {class_name: count}
        metrics: dict = None,             # power, rigging, audience, cost
        brand_color: tuple = (0.0, 0.65, 0.85),  # teal por defecto
    ) -> dict
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

try:
    import fitz  # pymupdf
    _HAS_PYMUPDF = True
except ImportError:
    _HAS_PYMUPDF = False


# ---------------------------------------------------------------------
# Constantes de layout (puntos PDF, 1pt = 1/72 inch)
# ---------------------------------------------------------------------

PAGE_W = 595  # A4 width
PAGE_H = 842  # A4 height
MARGIN = 36


# ---------------------------------------------------------------------
# Helpers de dibujo
# ---------------------------------------------------------------------

def _hex_to_rgb(hex_str: str) -> tuple:
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def _draw_header(page, title: str, brand: tuple, subtitle: str = ""):
    """Banda superior de marca con titulo."""
    page.draw_rect(
        fitz.Rect(0, 0, PAGE_W, 80),
        color=brand, fill=brand, overlay=False,
    )
    page.insert_text(
        (MARGIN, 35),
        title.upper(),
        fontsize=18, color=(1, 1, 1), fontname="helv",
    )
    if subtitle:
        page.insert_text(
            (MARGIN, 60),
            subtitle, fontsize=10, color=(1, 1, 1), fontname="helv",
        )


def _draw_footer(page, page_num: int, total: int, brand: tuple):
    """Pie de pagina con paginacion y branding."""
    line_y = PAGE_H - 30
    page.draw_line(
        (MARGIN, line_y),
        (PAGE_W - MARGIN, line_y),
        color=brand, width=0.5,
    )
    page.insert_text(
        (MARGIN, PAGE_H - 18),
        "GIA Sales Presentation - Generado " + datetime.now().strftime("%Y-%m-%d %H:%M"),
        fontsize=7, color=(0.5, 0.5, 0.5),
    )
    page.insert_text(
        (PAGE_W - MARGIN - 30, PAGE_H - 18),
        f"{page_num} / {total}",
        fontsize=7, color=(0.5, 0.5, 0.5),
    )


def _insert_image_safe(page, rect: "fitz.Rect", path: str, fallback_text: str = ""):
    """Inserta una imagen si existe; si no, dibuja un placeholder."""
    if path and os.path.isfile(path):
        try:
            page.insert_image(rect, filename=path, keep_proportion=True)
            return True
        except Exception as e:  # noqa: BLE001
            fallback_text = f"Error: {e}"
    # Placeholder
    page.draw_rect(rect, color=(0.85, 0.85, 0.85), fill=(0.95, 0.95, 0.95))
    cx = (rect.x0 + rect.x1) / 2 - 60
    cy = (rect.y0 + rect.y1) / 2
    page.insert_text(
        (cx, cy), fallback_text or "[render no disponible]",
        fontsize=10, color=(0.6, 0.6, 0.6),
    )
    return False


def _draw_equipment_table(page, equipment: dict, y_start: float, brand: tuple) -> float:
    """Dibuja tabla de equipo agrupada por familia. Retorna y_end."""
    if not equipment:
        page.insert_text(
            (MARGIN, y_start + 20), "Sin inventario disponible",
            fontsize=10, color=(0.5, 0.5, 0.5),
        )
        return y_start + 40

    # Agrupar por prefijo (Audio-, Lighting-, Video-, Structure-, etc.)
    groups: dict[str, list[tuple]] = {}
    for cls, count in equipment.items():
        if cls.startswith("_"):
            continue
        prefix = cls.split("-")[0] if "-" in cls else "Other"
        groups.setdefault(prefix, []).append((cls, count))

    y = y_start
    row_h = 16
    col_class_x = MARGIN
    col_count_x = PAGE_W - MARGIN - 80

    # Header de tabla
    page.draw_rect(
        fitz.Rect(MARGIN, y, PAGE_W - MARGIN, y + row_h),
        color=brand, fill=brand,
    )
    page.insert_text((col_class_x + 6, y + 12), "EQUIPO / CLASE",
                     fontsize=10, color=(1, 1, 1), fontname="hebo")
    page.insert_text((col_count_x, y + 12), "CANTIDAD",
                     fontsize=10, color=(1, 1, 1), fontname="hebo")
    y += row_h + 4

    # Filas por grupo
    for group_name in sorted(groups.keys()):
        items = sorted(groups[group_name], key=lambda x: -x[1])
        # Header de grupo
        page.draw_rect(
            fitz.Rect(MARGIN, y, PAGE_W - MARGIN, y + row_h),
            color=(0.92, 0.92, 0.92), fill=(0.92, 0.92, 0.92),
        )
        page.insert_text((col_class_x + 6, y + 12), group_name.upper(),
                         fontsize=9, color=(0.2, 0.2, 0.2), fontname="hebo")
        group_total = sum(c for _, c in items)
        page.insert_text((col_count_x, y + 12), str(group_total),
                         fontsize=9, color=(0.2, 0.2, 0.2), fontname="hebo")
        y += row_h
        # Items del grupo
        for cls, count in items:
            label = cls.split("-", 1)[1] if "-" in cls else cls
            page.insert_text((col_class_x + 20, y + 12), label,
                             fontsize=9, color=(0.3, 0.3, 0.3))
            page.insert_text((col_count_x + 8, y + 12), str(count),
                             fontsize=9, color=(0.3, 0.3, 0.3))
            y += row_h
            # Avoid overflow: break si y > footer area
            if y > PAGE_H - 60:
                break
        y += 4
        if y > PAGE_H - 60:
            break

    return y


def _draw_metrics_panel(page, metrics: dict, y_start: float, brand: tuple) -> float:
    """KPIs en cards laterales."""
    if not metrics:
        return y_start

    cards = []
    if "total_kw" in metrics:
        cards.append(("CARGA ELECTRICA", f"{metrics['total_kw']:.1f} kW",
                      f"@ {metrics.get('voltage', 208)}V {metrics.get('phases', 3)}f"))
    if "audience" in metrics:
        cards.append(("CAPACIDAD", f"{metrics['audience']}", "personas"))
    if "rigging_max_pct" in metrics:
        cards.append(("RIGGING", f"{metrics['rigging_max_pct']:.0f}%",
                      "max motor load"))
    if "estimated_cost" in metrics:
        cards.append(("COSTO EST.", f"${metrics['estimated_cost']:,.0f}",
                      metrics.get("currency", "USD")))

    if not cards:
        return y_start

    n = len(cards)
    card_w = (PAGE_W - 2 * MARGIN - (n - 1) * 8) / n
    card_h = 70
    y = y_start

    for i, (label, value, sub) in enumerate(cards):
        x = MARGIN + i * (card_w + 8)
        rect = fitz.Rect(x, y, x + card_w, y + card_h)
        page.draw_rect(rect, color=brand, fill=brand, width=0)
        page.insert_text((x + 8, y + 16), label,
                         fontsize=8, color=(1, 1, 1), fontname="hebo")
        page.insert_text((x + 8, y + 42), value,
                         fontsize=20, color=(1, 1, 1), fontname="hebo")
        page.insert_text((x + 8, y + 58), sub,
                         fontsize=8, color=(0.9, 0.9, 0.9))

    return y + card_h + 16


# ---------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------

def build_sales_pdf(
    output_path: str,
    title: str = "Evento Corporativo",
    client_name: str = "",
    renders: dict | None = None,
    equipment: dict | None = None,
    metrics: dict | None = None,
    brand_color: tuple | str = "#00A6BC",
    notes: str = "",
) -> dict:
    """
    Construye PDF de presentacion de ventas.

    Returns:
        {"ok": bool, "path": str, "pages": int, "error": str|None}
    """
    if not _HAS_PYMUPDF:
        return {
            "ok": False, "path": "", "pages": 0,
            "error": "pymupdf no instalado en el entorno actual",
        }

    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if isinstance(brand_color, str):
        brand = _hex_to_rgb(brand_color)
    else:
        brand = brand_color

    renders = renders or {}
    equipment = equipment or {}
    metrics = metrics or {}

    doc = fitz.open()

    # =================================================================
    # PAGINA 1 - PORTADA
    # =================================================================
    p1 = doc.new_page(width=PAGE_W, height=PAGE_H)
    # Banda de marca grande (toda la mitad superior)
    p1.draw_rect(
        fitz.Rect(0, 0, PAGE_W, 320),
        color=brand, fill=brand,
    )
    p1.insert_text((MARGIN, 80), "GIA",
                   fontsize=14, color=(1, 1, 1), fontname="hebo")
    p1.insert_text((MARGIN, 105), "EVENT PRODUCTION SYSTEM",
                   fontsize=9, color=(1, 1, 1, 0.8) if False else (1, 1, 1),
                   fontname="helv")

    # Auto-fit del titulo: reduce font Y wrap si sigue siendo largo
    title_text = title.upper()
    font_size = 32
    max_w = PAGE_W - 2 * MARGIN
    # Helvetica bold mayusculas: ~0.65 * font_size por caracter
    while font_size > 18 and len(title_text) * font_size * 0.65 > max_w:
        font_size -= 2
    # Si todavia no cabe, wrap en 2 lineas
    lines = [title_text]
    if len(title_text) * font_size * 0.65 > max_w:
        words = title_text.split()
        mid = len(words) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    y_title = 200 if len(lines) == 1 else 185
    for i, line in enumerate(lines):
        p1.insert_text((MARGIN, y_title + i * (font_size + 4)),
                       line, fontsize=font_size, color=(1, 1, 1), fontname="hebo")
    if client_name:
        p1.insert_text((MARGIN, 235), f"Cliente: {client_name}",
                       fontsize=14, color=(1, 1, 1), fontname="helv")
    p1.insert_text((MARGIN, 290),
                   datetime.now().strftime("%d de %B, %Y"),
                   fontsize=11, color=(1, 1, 1, 0.85) if False else (1, 1, 1))

    # Hero render (iso)
    hero_path = renders.get("hero") or renders.get("iso") or renders.get("iso_right")
    hero_rect = fitz.Rect(MARGIN, 360, PAGE_W - MARGIN, 780)
    _insert_image_safe(p1, hero_rect, hero_path or "",
                       "[render iso pendiente]")
    _draw_footer(p1, 1, 4, brand)

    # =================================================================
    # PAGINA 2 - GRID 2x2 DE VISTAS
    # =================================================================
    p2 = doc.new_page(width=PAGE_W, height=PAGE_H)
    _draw_header(p2, "Vistas del Diseno", brand,
                 "Frente, Lateral, Isometrica y Planta")

    view_layout = [
        ("front", "FRENTE", 0, 0),
        ("right", "LATERAL DER.", 1, 0),
        ("iso_right", "ISOMETRICA", 0, 1),
        ("top", "PLANTA", 1, 1),
    ]

    cell_w = (PAGE_W - 2 * MARGIN - 8) / 2
    cell_h = 320
    y_grid_start = 110

    for view_key, label, col, row in view_layout:
        x = MARGIN + col * (cell_w + 8)
        y = y_grid_start + row * (cell_h + 16)
        # Caption arriba
        p2.insert_text((x, y + 12), label,
                       fontsize=9, color=brand, fontname="hebo")
        # Imagen
        rect = fitz.Rect(x, y + 18, x + cell_w, y + cell_h)
        _insert_image_safe(p2, rect, renders.get(view_key, ""),
                           f"[{label} pendiente]")
    _draw_footer(p2, 2, 4, brand)

    # =================================================================
    # PAGINA 3 - INVENTARIO DE EQUIPO
    # =================================================================
    p3 = doc.new_page(width=PAGE_W, height=PAGE_H)
    _draw_header(p3, "Inventario de Equipo", brand,
                 "Conteo por clase AV manifestada en el documento")
    _draw_equipment_table(p3, equipment, 110, brand)
    _draw_footer(p3, 3, 4, brand)

    # =================================================================
    # PAGINA 4 - METRICAS Y NOTAS
    # =================================================================
    p4 = doc.new_page(width=PAGE_W, height=PAGE_H)
    _draw_header(p4, "Metricas y Especificaciones", brand,
                 "Carga electrica, rigging y capacidad de audiencia")
    y_next = _draw_metrics_panel(p4, metrics, 110, brand)

    if notes:
        p4.insert_text((MARGIN, y_next + 20), "NOTAS:",
                       fontsize=10, color=brand, fontname="hebo")
        # Wrap notes
        for i, line in enumerate(_wrap_text(notes, 80)):
            p4.insert_text((MARGIN, y_next + 40 + i * 14), line,
                           fontsize=9, color=(0.3, 0.3, 0.3))

    # Hero render duplicado al final (full width)
    if hero_path and os.path.isfile(hero_path):
        bottom_rect = fitz.Rect(MARGIN, PAGE_H - 350, PAGE_W - MARGIN, PAGE_H - 50)
        _insert_image_safe(p4, bottom_rect, hero_path, "")
    _draw_footer(p4, 4, 4, brand)

    # =================================================================
    # GUARDAR
    # =================================================================
    try:
        doc.save(output_path)
        pages = len(doc)
        doc.close()
        return {
            "ok": True,
            "path": output_path,
            "pages": pages,
            "size_bytes": os.path.getsize(output_path),
            "error": None,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False, "path": output_path, "pages": 0,
            "error": f"{type(e).__name__}: {e}",
        }


def _wrap_text(text: str, width: int) -> list:
    """Simple word-wrap por max chars."""
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip() if cur else w
    if cur:
        lines.append(cur)
    return lines[:20]  # max 20 lineas


# ---------------------------------------------------------------------
# CLI de test
# ---------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json
    p = argparse.ArgumentParser(description="Build sales PDF")
    p.add_argument("--output", required=True, help="output PDF path")
    p.add_argument("--title", default="Evento Corporativo")
    p.add_argument("--client", default="")
    p.add_argument("--renders", default="{}", help='JSON: {"front":"path",...}')
    p.add_argument("--equipment", default="{}", help='JSON: {"Audio-Speaker":4,...}')
    p.add_argument("--metrics", default="{}", help='JSON: {"total_kw":12.5,...}')
    p.add_argument("--brand", default="#00A6BC")
    p.add_argument("--notes", default="")
    args = p.parse_args()

    r = build_sales_pdf(
        output_path=args.output,
        title=args.title,
        client_name=args.client,
        renders=json.loads(args.renders),
        equipment=json.loads(args.equipment),
        metrics=json.loads(args.metrics),
        brand_color=args.brand,
        notes=args.notes,
    )
    print(json.dumps(r, indent=2, ensure_ascii=False))
