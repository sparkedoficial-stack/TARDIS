#!/usr/bin/env python3
"""
tardis_video_pensante.py - Sistema Soberano de Video Pensante y Abstracción Visual
===================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS (TARDIS-NEURAL-SPACE-KAIJU Core)
Creador y Autoridad Absoluta: el Arquitecto (₪)
Saludo Canónico: 'Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.'

Comandos Soportados:
  /VideoPensante  o  /videoAbstracto

Uso CLI:
  python3 tardis_video_pensante.py --run-now
  python3 tardis_video_pensante.py --topic "física cuántica y entrelazamiento"
  python3 tardis_video_pensante.py --daemon
  python3 tardis_video_pensante.py --interval-minutes 35
  python3 tardis_video_pensante.py --memory
  python3 tardis_video_pensante.py --ver <id_o_fragmento>
  python3 tardis_video_pensante.py --status
"""

from __future__ import annotations

import argparse
import datetime
import os
import signal
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tardis_video_thinking_engine import (
    CANONICAL_GREETING,
    TardisVideoThinkingEngine,
    get_video_thinking_engine,
)


def run_daemon_loop(engine: TardisVideoThinkingEngine):
    """Bucle autónomo continuo que ejecuta un ciclo de investigación cada 35 minutos."""
    print("🛸 [TARDIS :: DEMONIO AUTÓNOMO DE VIDEO PENSANTE]")
    print(f"• Saludo Canónico : '{CANONICAL_GREETING}'")
    interval_sec = engine.state.get("interval_seconds", 2100.0)
    print(f"• Frecuencia      : Cada {interval_sec/60:.1f} minutos ({interval_sec:.0f}s)")
    print("• Modo            : 100% Autónomo, local y desencadenado")
    print("• Destinos        : Telegram (Admin + Chat General) y Consola Local")
    print("--------------------------------------------------------------------------------")

    stop_event = False

    def handle_signal(sig, frame):
        nonlocal stop_event
        print("\n🛑 Señal recibida. Deteniendo Demonio de Video Pensante de forma segura...")
        stop_event = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Si nunca ha corrido o han pasado más de 35 minutos, ejecutar de inmediato
    last_t = engine.state.get("last_run_timestamp", 0.0)
    elapsed = time.time() - last_t
    if last_t == 0.0 or elapsed >= interval_sec:
        print("⚡ [Inicio] Ejecutando ciclo inaugural inmediato...")
        try:
            engine.execute_cycle()
        except Exception as e:
            print(f"⚠️ Aviso en ciclo inicial: {e}")

    while not stop_event:
        interval_sec = engine.state.get("interval_seconds", 2100.0)
        last_t = engine.state.get("last_run_timestamp", 0.0)
        elapsed = time.time() - last_t
        remaining = max(0.0, interval_sec - elapsed)

        if remaining > 0:
            # Esperar en pasos de 5 segundos para responder ágilmente a señales
            sleep_step = min(5.0, remaining)
            time.sleep(sleep_step)
        else:
            print(f"\n⏰ [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Cumplido intervalo de 35 minutos. Iniciando investigación autónoma...")
            try:
                engine.execute_cycle()
            except Exception as e:
                print(f"⚠️ Error en ciclo autónomo: {e}")
                time.sleep(10.0)


def main():
    parser = argparse.ArgumentParser(
        description="Sistema Soberano TARDIS de Video Pensante / Video Abstracto (/VideoPensante /videoAbstracto)"
    )
    parser.add_argument(
        "--run-now", "-r",
        action="store_true",
        help="Ejecutar de inmediato un ciclo de búsqueda autónoma, descarga, análisis visual y despacho."
    )
    parser.add_argument(
        "--topic", "-t",
        type=str,
        default=None,
        help="Investigar y analizar un tema específico dictado por el usuario."
    )
    parser.add_argument(
        "--daemon", "-d",
        action="store_true",
        help="Iniciar el demonio continuo en primer plano (ejecución autónoma cada 35 minutos)."
    )
    parser.add_argument(
        "--interval-minutes", "-i",
        type=float,
        default=None,
        help="Ajustar el intervalo en minutos para las ejecuciones automáticas (por defecto: 35.0 minutos)."
    )
    parser.add_argument(
        "--memory", "-m", "--list", "-l",
        action="store_true",
        help="Mostrar los videos analizados y la memoria de abstracción e intereses de TARDIS."
    )
    parser.add_argument(
        "--ver", "-v",
        type=str,
        default=None,
        help="Consultar el detalle completo, conclusiones y abstracción de un video específico por ID."
    )
    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Mostrar el estado operativo, telemetría y métricas del sistema."
    )

    args = parser.parse_args()
    engine = get_video_thinking_engine()

    if args.interval_minutes is not None:
        mins = max(1.0, args.interval_minutes)
        engine.state["interval_minutes"] = mins
        engine.state["interval_seconds"] = mins * 60.0
        engine._save_state()
        print(f"⏱️ Intervalo de ejecución actualizado a {mins:.1f} minutos ({mins * 60.0:.0f}s).")

    if args.status:
        st = engine.get_status()
        print("\n" + "=" * 75)
        print("🛸 TARDIS · ESTADO DEL SISTEMA /VideoPensante /videoAbstracto")
        print("=" * 75)
        print(f"• Saludo Canónico        : '{CANONICAL_GREETING}'")
        print(f"• Estado Operativo       : {'🟢 ACTIVO (24/7)' if st.get('enabled') else '🔴 PAUSADO'}")
        print(f"• Intervalo Autónomo     : Cada {st.get('interval_minutes')} minutos (35 min nominal)")
        print(f"• Transcurrido desde último: {st.get('elapsed_since_last_run_sec')/60:.1f} min ({st.get('elapsed_since_last_run_sec')}s)")
        print(f"• Próxima Búsqueda en   : {st.get('next_run_in_min')} min ({st.get('next_run_in_sec')}s)")
        print(f"• Total Videos Aprendidos: {st.get('total_learned_videos')}")
        print(f"• Último Video Analizado : {st.get('last_video_id') or '(Ninguno aún)'}")
        print(f"• Último Tema de Interés : {st.get('last_topic') or '(Ninguno aún)'}")
        print(f"• Eventos de Auto-Mejora : {st.get('auto_improvements')}")
        print(f"• Base de Datos Memoria  : {st.get('db_path')}")
        print(f"• Bóveda de Almacenamiento: {st.get('vault_dir')}")
        print("=" * 75 + "\n")
        return

    if args.memory:
        mem = engine.get_memory_summary(limit=15)
        print("\n" + "=" * 75)
        print("📚 [TARDIS :: MEMORIA DE ABSTRACCIÓN E INTERESES DE VIDEO PENSANTE]")
        print("=" * 75)
        if not mem:
            print("No hay videos registrados aún. Ejecuta: python3 tardis_video_pensante.py --run-now")
        else:
            for v in mem:
                print(f"🎬 ID: {v['id']}")
                print(f"   • Tema        : {v.get('topic')}")
                print(f"   • Dominio     : {v.get('domain')}")
                print(f"   • Título      : {v.get('title')}")
                print(f"   • Duración    : {v.get('duration_sec', 0):.1f}s | {v.get('resolution')}")
                print(f"   • Registrado  : {v.get('created_at', '')[:19].replace('T', ' ')}")
                print(f"   • URL         : {v.get('url')}")
                print("   " + "-" * 70)
            print("Para ver el análisis y abstracción completa usa: python3 tardis_video_pensante.py --ver <ID>")
        print("=" * 75 + "\n")
        return

    if args.ver:
        det = engine.get_video_detail(args.ver.strip())
        if not det:
            print(f"⚠️ No se encontró ningún video con ID '{args.ver}'.")
            return
        print("\n" + "=" * 75)
        print(f"👁️ [DETALLE DE ABSTRACCIÓN :: {det.get('id')}]")
        print("=" * 75)
        print(f"• Título       : {det.get('title')}")
        print(f"• Tema         : {det.get('topic')} ({det.get('domain')})")
        print(f"• Duración     : {det.get('duration_sec', 0):.1f}s | {det.get('resolution')}")
        print(f"• Archivo      : {det.get('file_path')}")
        print(f"• Fuente Web   : {det.get('url')}")
        print("\n💡 POR QUÉ LE INTERESÓ A TARDIS:")
        print(det.get("curiosity_rationale"))
        print("\n👁️ LO QUE VIO LA INTELIGENCIA VISUAL:")
        print(det.get("visual_summary"))
        print("\n🔊 LO QUE ESCUCHÓ:")
        print(det.get("audio_summary") or det.get("audio_transcript") or "(Audio ambiental)")
        print("\n🧠 CONCLUSIONES & ABSTRACCIÓN:")
        print(det.get("abstraction_conclusions"))
        print("\n📚 APRENDIZAJES ASIMILADOS:")
        for ins in det.get("learned_insights", []):
            print(f"• {ins}")
        print("\n❓ PREGUNTAS ABIERTAS:")
        for q in det.get("next_questions", []):
            print(f"• {q}")
        print("=" * 75 + "\n")
        return

    if args.daemon:
        run_daemon_loop(engine)
        return

    # Si no se pasó ningún argumento o se especificó --run-now o --topic
    print(f"🛸 Saludo Canónico: '{CANONICAL_GREETING}'")
    print("🚀 Iniciando investigación y abstracción de video...")
    try:
        engine.execute_cycle(explicit_topic=args.topic)
    except Exception as e:
        print(f"❌ Error ejecutando ciclo: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
