#!/usr/bin/env python3
"""
tardis_scientific_researcher.py - Herramienta CLI de Investigación Científica Autónoma
=====================================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4

Permite realizar investigaciones de alto rigor científico, consultar bases de datos
académicas mundiales (arXiv, OpenAlex, Europe PMC, PubMed) y enviar resúmenes con
enlaces directos y PDFs a Telegram.

Uso:
  python3 tardis_scientific_researcher.py --topic "computación cuántica" --send-telegram
  python3 tardis_scientific_researcher.py --next-agenda --send-telegram
  python3 tardis_scientific_researcher.py --list-agenda
  python3 tardis_scientific_researcher.py --add-topic "Fusión Nuclear Tokamaks"
  python3 tardis_scientific_researcher.py --daemon
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Asegurar importación de core
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.scientific_research_engine import (
    ScientificResearchEngine,
    get_scientific_research_engine,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s"
)
logger = logging.getLogger("TARDIS.ResearcherCLI")


def main():
    parser = argparse.ArgumentParser(
        description="Sistema Soberano de Investigación y Aprendizaje de Rigor Científico TARDIS"
    )
    parser.add_argument(
        "--topic", "-t",
        type=str,
        help="Tema o pregunta de rigor científico a investigar."
    )
    parser.add_argument(
        "--max-papers", "-n",
        type=int,
        default=4,
        help="Número máximo de artículos científicos a compilar (def: 4)."
    )
    parser.add_argument(
        "--send-telegram", "-tg",
        action="store_true",
        help="Enviar el reporte completo estructurado con enlaces y PDFs a Telegram."
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        default=None,
        help="Chat ID de Telegram de destino (si se omite, usa admin_chat_id configurado)."
    )
    parser.add_argument(
        "--next-agenda",
        action="store_true",
        help="Investigar el siguiente tema prioritario de la agenda de aprendizaje continuo."
    )
    parser.add_argument(
        "--add-topic",
        type=str,
        help="Añadir un tema a la agenda de aprendizaje científico."
    )
    parser.add_argument(
        "--domain",
        type=str,
        default="Ciencia General",
        help="Dominio o disciplina científica del tema al agregarlo."
    )
    parser.add_argument(
        "--list-agenda",
        action="store_true",
        help="Mostrar todos los temas en la agenda de aprendizaje."
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Ejecutar en modo daemon continuo, investigando temas periódicamente."
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=12.0,
        help="Intervalo en horas para el modo daemon (def: 12.0)."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Salida estructurada en JSON puro en la terminal."
    )

    args = parser.parse_args()
    engine = get_scientific_research_engine()

    # 1. Listar agenda
    if args.list_agenda:
        agenda = engine.load_agenda()
        topics = agenda.get("topics", [])
        print("\n" + "=" * 70)
        print("📖 AGENDA DE APRENDIZAJE & RIGOR CIENTÍFICO TARDIS")
        print("=" * 70)
        print(f"Modo Autónomo: {'🟢 ACTIVO' if agenda.get('autonomous_mode', True) else '🔴 PAUSADO'}")
        print(f"Intervalo: Cada {agenda.get('interval_hours', 12)} horas")
        print(f"Total de temas: {len(topics)}\n")

        for i, t in enumerate(topics, 1):
            st_icon = "✅" if t.get("status") == "completed" else "⏳"
            print(f"{st_icon} {i:2d}. {t.get('topic')}")
            print(f"     Dominio: {t.get('domain', 'General')} | Investigado: {t.get('researched_count', 0)} veces")
        print("=" * 70 + "\n")
        return 0

    # 2. Añadir tema a la agenda
    if args.add_topic:
        res = engine.add_topic_to_agenda(args.add_topic, domain=args.domain)
        print(f"✅ Tema '{args.add_topic}' registrado con éxito en la agenda ({res.get('action')}).")
        return 0

    # 3. Investigar siguiente tema de la agenda
    if args.next_agenda:
        next_t = engine.get_next_agenda_topic()
        if not next_t:
            print("❌ No hay temas en la agenda de aprendizaje.")
            return 1
        args.topic = next_t["topic"]
        args.domain = next_t.get("domain", "Ciencia General")
        print(f"⏳ Investigando siguiente tema de la agenda: '{args.topic}' ({args.domain})...")

    # 4. Modo Daemon
    if args.daemon:
        print(f"🚀 Iniciando Daemon de Investigación Científica Autónoma (Intervalo: {args.interval_hours}h)...")
        engine.start_autonomous_daemon(interval_seconds=args.interval_hours * 3600)
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n🛑 Deteniendo daemon de investigación...")
            engine.stop_autonomous_daemon()
            return 0

    # 5. Investigar tema específico
    if not args.topic:
        parser.print_help()
        return 1

    print(f"\n🔬 Investigando tema con rigor científico: '{args.topic}'...")
    report = engine.execute_research(args.topic, max_papers=args.max_papers)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        text_report = engine.format_telegram_report(report)
        print("\n" + text_report + "\n")

    # Si se solicitó enviar a Telegram
    if args.send_telegram:
        print("📤 Enviando reporte científico estructurado a Telegram...")
        res_tg = engine.send_report_to_telegram(report, chat_id=args.chat_id)
        if res_tg.get("ok"):
            print("✅ Reporte y enlaces de acceso despachados con éxito a Telegram.")
        else:
            print(f"⚠️ Aviso al despachar a Telegram: {res_tg.get('error')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
