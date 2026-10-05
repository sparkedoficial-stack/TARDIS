#!/usr/bin/env python3
"""
tardis_curiosity_debater.py - CLI y Centinela de Curiosidades & Debates para POLIMATAS LATAM
=============================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU

Despacha cada 1.5 horas un dato curioso fascinante y un tema de investigación de frontera con
datos cuantitativos en PDF a Telegram para generar debate y conversaciones multidisciplinarias.

Uso:
  python3 tardis_curiosity_debater.py --run-now
  python3 tardis_curiosity_debater.py --status
  python3 tardis_curiosity_debater.py --daemon
  python3 tardis_curiosity_debater.py --interval-hours 1.5
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.curiosity_debate_manager import get_curiosity_debate_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s"
)
logger = logging.getLogger("TARDIS.DebaterCLI")


def main():
    parser = argparse.ArgumentParser(
        description="Sistema Soberano de Curiosidades, Investigación y Debates TARDIS para POLIMATAS LATAM"
    )
    parser.add_argument(
        "--run-now", "-r",
        action="store_true",
        help="Ejecutar un despacho inmediato de dato curioso + tema de investigación con PDF a Telegram."
    )
    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Mostrar estado actual, métricas, siguiente ciclo y configuración."
    )
    parser.add_argument(
        "--daemon", "-d",
        action="store_true",
        help="Ejecutar en modo daemon continuo en primer plano."
    )
    parser.add_argument(
        "--interval-hours", "-i",
        type=float,
        default=None,
        help="Intervalo de despacho en horas (por defecto: 1.5 horas)."
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        default=None,
        help="Chat ID de Telegram de destino (por defecto: -1002696477485)."
    )
    parser.add_argument(
        "--thread-id",
        type=int,
        default=None,
        help="Message Thread ID (Topic) en el supergrupo (por defecto: 453)."
    )

    args = parser.parse_args()
    mgr = get_curiosity_debate_manager()

    if args.interval_hours is not None:
        secs = args.interval_hours * 3600.0
        mgr.state["interval_seconds"] = secs
        mgr._save_state()
        print(f"⏱️ Intervalo actualizado a {args.interval_hours} horas ({secs:.0f} segundos).")

    if args.chat_id is not None:
        mgr.state["target_chat_id"] = int(args.chat_id) if args.chat_id.lstrip("-").isdigit() else args.chat_id
        mgr._save_state()
        print(f"🎯 Chat ID objetivo actualizado a {mgr.state['target_chat_id']}.")

    if args.thread_id is not None:
        mgr.state["target_thread_id"] = args.thread_id
        mgr._save_state()
        print(f"🧵 Thread ID objetivo actualizado a {args.thread_id}.")

    if args.status:
        st = mgr.get_status()
        print("\n" + "=" * 70)
        print("🛸 TARDIS · ESTADO DEL SISTEMA DE CURIOSIDADES & DEBATES")
        print("=" * 70)
        print(f"• Estado Operativo    : {'🟢 ACTIVO' if st.get('enabled') else '🔴 PAUSADO'}")
        print(f"• Intervalo Configurado: Cada {st.get('interval_hours')} horas ({st.get('interval_seconds'):.0f} s)")
        print(f"• Chat Objetivo        : {st.get('target_chat_id')} (POLIMATAS LATAM)")
        print(f"• Hilo / Topic         : {st.get('target_thread_id')}")
        print(f"• Despachos Totales    : {st.get('total_dispatches')}")
        print(f"• Último Despacho      : {st.get('last_run_iso')}")
        print(f"• Próximo Despacho en  : {st.get('next_run_in_minutes')} minutos ({st.get('seconds_until_next')} s)")
        print("=" * 70 + "\n")
        return 0

    if args.run_now:
        print("\n🚀 [DESPACHO INMEDIATO]: Generando dato curioso, investigación y PDF...")
        target_chat = int(args.chat_id) if args.chat_id and args.chat_id.lstrip("-").isdigit() else (args.chat_id or None)
        res = mgr.dispatch_cycle(target_chat_id=target_chat, target_thread_id=args.thread_id)
        if res.get("ok"):
            print(f"✅ Éxito absoluto:")
            print(f"   • Tema        : {res.get('topic_title')}")
            print(f"   • Dossier PDF : {res.get('pdf_path')}")
            print(f"   • Telegram Msg: {'OK' if res.get('telegram_msg', {}).get('ok') else res.get('telegram_msg')}")
            print(f"   • Telegram PDF: {'OK' if res.get('telegram_doc', {}).get('ok') else res.get('telegram_doc')}")
        else:
            print(f"⚠️ Aviso en el despacho:")
            print(f"   • Telegram Msg: {res.get('telegram_msg')}")
            print(f"   • Telegram Doc: {res.get('telegram_doc')}")
        return 0

    if args.daemon:
        print(f"🚀 Iniciando Daemon de Curiosidades & Debates (Intervalo: {mgr.state.get('interval_seconds', 5400)/3600:.1f}h)...")
        mgr.start_daemon()
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n🛑 Deteniendo daemon...")
            mgr.stop_daemon()
            return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
