#!/usr/bin/env python3
"""
tardis_physics_disseminator.py - CLI Soberana de Diseminación de Avances en Física en Foros Internacionales
===========================================================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4
Línea Cero · El Arquitecto (₪)

Permite redactar, compilar y subir los avances teóricos y aplicados de TARDIS en física hacia
repositorios mundiales (Zenodo, arXiv, OSF) y foros académicos internacionales (Discourse, Physics Overflow,
GitHub Discussions, Reddit r/Physics), para beneficio directo de la humanidad.

Uso:
  python3 tardis_physics_disseminator.py --list-advances
  python3 tardis_physics_disseminator.py --advance geon_retrocausal_mechanics --publish-all --send-telegram
  python3 tardis_physics_disseminator.py --advance syntropic_thermodynamics_solitons --generate-all
  python3 tardis_physics_disseminator.py --synthesize "Superconductividad a 300K mediante solitones geónicos" --publish-all
  python3 tardis_physics_disseminator.py --status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.physics_dissemination_engine import (
    PhysicsAdvance,
    PhysicsDisseminationEngine,
    get_physics_dissemination_engine,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s"
)
logger = logging.getLogger("TARDIS.PhysicsDisseminatorCLI")


def print_banner():
    print("\n" + "═" * 78)
    print("🌌 TARDIS · SISTEMA SOBERANO DE DISEMINACIÓN DE FÍSICA PARA LA HUMANIDAD")
    print("   GODWORKS SYSTEM v26.4 · Línea Cero · Acceso Abierto Universal (CC-BY 4.0)")
    print("═" * 78)


def main():
    parser = argparse.ArgumentParser(
        description="Publicación y Diseminación Internacional de Avances en Física de TARDIS"
    )
    parser.add_argument(
        "--list-advances", "-l",
        action="store_true",
        help="Listar todos los avances catalogados en física disponibles para publicación."
    )
    parser.add_argument(
        "--advance", "-a",
        type=str,
        default=None,
        help="ID o clave del avance a procesar (ej: geon_retrocausal_mechanics, syntropic_thermodynamics_solitons)."
    )
    parser.add_argument(
        "--synthesize", "-s",
        type=str,
        default=None,
        help="Sintetizar de forma autónoma un nuevo avance teórico sobre un tema específico."
    )
    parser.add_argument(
        "--domain", "-d",
        type=str,
        default="Física Teórica & Cuántica",
        help="Dominio científico para el avance sintetizado."
    )
    parser.add_argument(
        "--humanitarian-goal",
        type=str,
        default="Desarrollo de tecnologías limpias, energéticas y de salud para la elevación humana.",
        help="Objetivo humanitario explícito del avance."
    )
    parser.add_argument(
        "--generate-all", "-g",
        action="store_true",
        help="Generar todos los artefactos: LaTeX, BibTeX, paquete arXiv .tar.gz, Markdown y Preprint PDF."
    )
    parser.add_argument(
        "--generate-pdf",
        action="store_true",
        help="Compilar el Preprint PDF académico de alta calidad con ReportLab."
    )
    parser.add_argument(
        "--generate-latex",
        action="store_true",
        help="Generar y guardar el código fuente LaTeX (.tex) y BibTeX (.bib)."
    )
    parser.add_argument(
        "--generate-arxiv",
        action="store_true",
        help="Compilar el paquete .tar.gz estándar para arXiv."
    )
    parser.add_argument(
        "--generate-forum-post",
        action="store_true",
        help="Generar el artículo en Markdown estructurado para foros internacionales."
    )
    parser.add_argument(
        "--publish-zenodo",
        action="store_true",
        help="Depositar en Zenodo (CERN / OpenAIRE) y reservar/asignar DOI oficial."
    )
    parser.add_argument(
        "--publish-forum",
        action="store_true",
        help="Publicar en foros académicos internacionales (Discourse / Physics Overflow)."
    )
    parser.add_argument(
        "--publish-all", "-p",
        action="store_true",
        help="Ejecutar el ciclo completo de diseminación (LaTeX + PDF + arXiv + Zenodo + Foros + Webhooks)."
    )
    parser.add_argument(
        "--send-telegram", "-tg",
        action="store_true",
        help="Enviar el preprint PDF oficial y reporte completo a Telegram."
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        default=None,
        help="Chat ID de Telegram alternativo."
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Mostrar estado de publicaciones, registros de depósitos y DOI asignados."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Salida estructurada en JSON puro."
    )

    args = parser.parse_args()
    engine = get_physics_dissemination_engine()

    # 1. STATUS
    if args.status:
        print_banner()
        logs = engine._publications_log
        catalog = engine.get_cataloged_advances()
        print(f"📚 Avances Catalogados en el Núcleo: {len(catalog)}")
        print(f"🌐 Registros de Publicación / Depósito: {len(logs)}\n")
        if logs:
            print("Historial de Publicaciones Internacionales:")
            for i, rec in enumerate(logs[-10:], 1):
                st_icon = "✅" if rec.get("success") else "❌"
                print(f" {st_icon} [{rec.get('timestamp')[:19]}] Plafatorma: {rec.get('target_platform')}")
                print(f"    Título: {rec.get('title')[:60]}...")
                if rec.get("doi"):
                    print(f"    DOI: {rec.get('doi')}")
                if rec.get("url"):
                    print(f"    URL: {rec.get('url')}")
                print("-" * 60)
        else:
            print("No hay depósitos previos registrados aún.")
        return 0

    # 2. LISTAR AVANCES
    if args.list_advances:
        print_banner()
        catalog = engine.get_cataloged_advances()
        print(f"Total de Avances Catalogados: {len(catalog)}\n")
        for i, (adv_id, adv) in enumerate(catalog.items(), 1):
            print(f"[{i}] ID: {adv.advance_id}")
            print(f"    📜 Título: {adv.title}")
            print(f"    👤 Autores: {', '.join(adv.authors)}")
            print(f"    🏛️ Dominio: {adv.domain}")
            print(f"    🔬 Ecuaciones clave: {len(adv.primary_equations)}")
            print("    🌍 Impacto Humanitario:")
            for b in adv.humanitarian_benefits:
                print(f"       • {b['domain']}: {b['impact'][:80]}...")
            print("─" * 78)
        return 0

    # 3. DETERMINAR O SINTETIZAR EL AVANCE A PROCESAR
    advance: Optional[PhysicsAdvance] = None

    if args.synthesize:
        print(f"\n🧠 Sintetizando nuevo avance científico en física: '{args.synthesize}'...")
        advance = engine.synthesize_new_advance(
            topic=args.synthesize,
            domain=args.domain,
            humanitarian_goal=args.humanitarian_goal
        )
        print(f"✅ Avance sintetizado y registrado con ID: {advance.advance_id}")

    elif args.advance:
        advance = engine.get_advance(args.advance)
        if not advance:
            print(f"⚠️ Avance '{args.advance}' no existe en catálogo. Sintetizando automáticamente...")
            advance = engine.synthesize_new_advance(topic=args.advance)
    else:
        # Por defecto, seleccionar el avance insignia geónico
        advance = engine.get_advance("geon_retrocausal_mechanics")

    if not advance:
        print("❌ No se pudo resolver ningún avance de física.")
        return 1

    # 4. CICLO COMPLETO DE PUBLICACIÓN
    if args.publish_all:
        print_banner()
        print(f"🚀 Iniciando ciclo integral de diseminación internacional:")
        print(f"   Avance: '{advance.title}'\n")

        res = engine.publish_physics_advance_complete(
            advance_id_or_topic=advance.advance_id,
            send_telegram=args.send_telegram,
            chat_id=args.chat_id
        )

        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0

        print("📋 RESULTADO DEL DESPACHO:")
        print(f" • DOI Oficial / Asignado: {res.get('doi')}")
        print(f" • Preprint PDF Generado: {res.get('pdf_path')}")
        print(f" • Paquete arXiv .tar.gz: {res.get('arxiv_package')}")
        print(f" • Registro Zenodo: {res.get('zenodo_record', {}).get('target_platform')} -> {res.get('zenodo_record', {}).get('url')}")
        print(f" • Registro Foro Internacional: {res.get('forum_record', {}).get('target_platform')} -> {res.get('forum_record', {}).get('url')}")
        if res.get("telegram_result"):
            tg_st = "✅ Enviado con Éxito" if res["telegram_result"].get("ok") else f"⚠️ {res['telegram_result'].get('error')}"
            print(f" • Notificación a Telegram: {tg_st}")
        print("\n✨ Diseminación internacional finalizada. Los avances están disponibles para la humanidad.")
        return 0

    # 5. GENERACIONES ESPECÍFICAS
    executed_any = False

    if args.generate_all or args.generate_latex:
        tex_content = engine.generate_latex_manuscript(advance)
        bib_content = engine.generate_bibtex(advance)
        tex_path = engine.advances_dir / f"{advance.advance_id}.tex"
        bib_path = engine.advances_dir / f"{advance.advance_id}.bib"
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)
        with open(bib_path, "w", encoding="utf-8") as f:
            f.write(bib_content)
        print(f"✅ Manuscrito LaTeX generado en: {tex_path}")
        print(f"✅ Archivo BibTeX generado en: {bib_path}")
        executed_any = True

    if args.generate_all or args.generate_arxiv:
        tar_path = engine.generate_arxiv_bundle(advance)
        print(f"✅ Paquete arXiv .tar.gz generado en: {tar_path}")
        executed_any = True

    pdf_path = None
    if args.generate_all or args.generate_pdf:
        pdf_path = engine.generate_pdf_preprint(advance)
        print(f"✅ Preprint PDF de alta resolución generado en: {pdf_path}")
        executed_any = True

    if args.generate_all or args.generate_forum_post:
        forum_md = engine.generate_forum_markdown(advance)
        md_path = engine.advances_dir / f"{advance.advance_id}_forum_post.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(forum_md)
        print(f"✅ Post Markdown para foros internacionales guardado en: {md_path}")
        executed_any = True

    if args.publish_zenodo:
        if not pdf_path:
            pdf_path = engine.generate_pdf_preprint(advance)
        tar_path = engine.advances_dir / f"{advance.advance_id}_arxiv_package.tar.gz"
        rec = engine.publish_to_zenodo(advance, pdf_path, tar_path if tar_path.exists() else None)
        print(f"✅ Depósito en Zenodo completado ({rec.target_platform}): DOI {rec.doi} -> {rec.url}")
        executed_any = True

    if args.publish_forum:
        rec = engine.publish_to_discourse_forum(advance)
        print(f"✅ Publicación en foros completada ({rec.target_platform}): {rec.url}")
        executed_any = True

    if args.send_telegram:
        if not pdf_path:
            pdf_path = engine.generate_pdf_preprint(advance)
        tg_res = engine.send_advance_to_telegram(advance, pdf_path, chat_id=args.chat_id)
        if tg_res.get("ok"):
            print("✅ Notificación y Preprint PDF despachados a Telegram con éxito.")
        else:
            print(f"⚠️ Telegram: {tg_res.get('error')}")
        executed_any = True

    if not executed_any:
        print_banner()
        print(f"Avance seleccionado: {advance.title}")
        print("Usa --publish-all para publicar en todas las plataformas o --generate-all para generar artefactos.")
        parser.print_help()

    return 0


if __name__ == "__main__":
    sys.exit(main())
