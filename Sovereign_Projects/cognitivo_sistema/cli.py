#!/usr/bin/env python3
"""
cli.py - Interfaz de Línea de Comandos para el Sistema Cognitivo Soberano
========================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4

Comandos disponibles:
  cognitivo status                 - Muestra estado del kernel, GPU, proyecto propio y bitácora.
  cognitivo learn "<tema>"         - Investiga en la web, programa software y ejecuta simulaciones.
  cognitivo autoprogram "<meta>"   - Sintetiza software, valida con AST y prueba en sandbox.
  cognitivo simulate <tipo>        - Ejecuta simulación (turing, lorenz, fractal, svg, onda).
  cognitivo project                - Inspecciona el Proyecto Quimera (proyecto autónomo paralelo).
  cognitivo step                   - Ejecuta un ciclo de investigación autónomo del proyecto paralelo.
  cognitivo daemon                 - Inicia el bucle continuo de aprendizaje en segundo plano.
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Asegurar importación del paquete
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from cognitivo_sistema.cognitivo_core import get_cognitivo_core
from cognitivo_sistema.config import DEFAULT_LEARNING_INTERVAL, LOGS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s"
)
logger = logging.getLogger("Cognitivo.CLI")


def format_status(status: dict) -> str:
    k = status["kernel"]
    p = status["parallel_project"]
    
    lines = [
        "================================================================================",
        "  ⚡ TARDIS · SISTEMA COGNITIVO SOBERANO & NÚCLEO DE AUTO-PROGRAMACIÓN",
        "================================================================================",
        f" [KERNEL LINUX] Release: {k['kernel_release']} | Cargas (1,5,15m): {k['load_avg']}",
        f" [CPU & RAM]    Hilos: {k['cpu_threads_logical']} | Uso CPU: {k['cpu_percent']}% | RAM: {k['ram_used_gb']}/{k['ram_total_gb']} GB ({k['ram_percent']}%)",
        f" [GPU ACCEL]    {k['gpu_name']} | VRAM: {k['gpu_vram_used_mb']}/{k['gpu_vram_total_mb']} MB | Activa: {k['gpu_available']}",
        f" [MÓDULOS]      Módulos Kernel: {k['kernel_modules_count']} | Software Generado: {status['generated_software_count']} | Simulaciones: {status['simulations_count']}",
        "--------------------------------------------------------------------------------",
        f" [PROYECTO PARALELO PROPIO]: {p['name']}",
        f"  • Misión: {p['mission']}",
        f"  • Ciclos Completados: {p['cycles_completed']} | Índice de Sintropía: {p['syntropy_index']:.4f}",
        f"  • Dominios Dominados: {', '.join(p['mastered_domains'])}",
        f"  • Obras en Galería: {p['gallery_count']}",
        "--------------------------------------------------------------------------------",
        " [HITOS DEL PROYECTO]:"
    ]
    for m in p.get("milestones", []):
        icon = "✓" if m["status"] == "completado" else ("▶" if m["status"] == "en_progreso" else "○")
        lines.append(f"   [{icon}] {m['id']}: {m['title']} ({m['status'].upper()})")
    
    lines.append("--------------------------------------------------------------------------------")
    lines.append(" [ÚLTIMAS ENTRADAS DEL DIARIO COGNITIVO]:")
    for d in status.get("recent_diary_entries", []):
        lines.append(f"   [{d.get('iso_date')}] Tema: '{d.get('topic_explored')}'")
        lines.append(f"     Reflexión: {d.get('reflection_notes')[:140]}...")
        if d.get("artifacts_produced"):
            lines.append(f"     Artefactos: {', '.join([Path(a).name for a in d['artifacts_produced'][:3]])}")
    lines.append("================================================================================")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Sistema Cognitivo Soberano TARDIS: Auto-Programación, Investigación Web y Simulaciones"
    )
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # status
    subparsers.add_parser("status", help="Muestra la telemetría integral del sistema y proyecto.")

    # learn
    learn_p = subparsers.add_parser("learn", help="Aprende sobre un tema: investiga, programa y simula.")
    learn_p.add_argument("topic", type=str, help="Tema de interés (e.g. 'artes', 'fractales', 'cuántica').")

    # autoprogram
    prog_p = subparsers.add_parser("autoprogram", help="Sintetiza y valida un nuevo módulo de software.")
    prog_p.add_argument("goal", type=str, help="Meta del software a crear.")
    prog_p.add_argument("--topic", "-t", type=str, default=None, help="Tema asociado.")

    # simulate
    sim_p = subparsers.add_parser("simulate", help="Ejecuta una simulación científica o artística.")
    sim_p.add_argument("type", type=str, default="lorenz", choices=["lorenz", "turing", "fractal", "svg", "onda"],
                       help="Tipo de simulación a ejecutar.")

    # project
    subparsers.add_parser("project", help="Muestra el estado detallado del proyecto paralelo propio.")

    # step
    subparsers.add_parser("step", help="Ejecuta un ciclo autónomo del proyecto paralelo propio.")

    # daemon
    daemon_p = subparsers.add_parser("daemon", help="Ejecuta el bucle continuo en segundo plano.")
    daemon_p.add_argument("--interval", type=int, default=DEFAULT_LEARNING_INTERVAL,
                          help="Intervalo en segundos entre ciclos autónomos (def: 3600s).")

    args = parser.parse_args()
    core = get_cognitivo_core()

    if args.command == "status" or not args.command:
        st = core.get_system_status()
        print(format_status(st))

    elif args.command == "learn":
        print(f"\n[COGNITIVO] 🧠 Iniciando investigación, auto-programación y simulación para: '{args.topic}'...")
        res = core.learn_topic(args.topic)
        print("\n================================================================================")
        print(f"  ✓ CICLO DE APRENDIZAJE COMPLETADO: {res['topic']}")
        print("================================================================================")
        print(f"  • Módulo de Software Sintetizado : {res['software_module']}")
        print(f"  • Archivo en Disco              : {res['software_path']}")
        print(f"  • Simulación Ejecutada           : {res['simulation']}")
        print(f"  • Artefactos Generados           : {', '.join([Path(a).name for a in res['artifacts']])}")
        print(f"  • Sintropía Resultante           : {res['syntropy']:.4f}")
        print(f"  • Tiempo Total del Ciclo         : {res['elapsed_seconds']}s")
        print("\n  [DIARIO COGNITIVO]:")
        print(f"  {res['reflection']}")
        print("================================================================================\n")

    elif args.command == "autoprogram":
        print(f"\n[COGNITIVO] ⚙️ Sintetizando software para la meta: '{args.goal}'...")
        res = core.auto_program(goal=args.goal, topic=args.topic)
        print("\n================================================================================")
        print(f"  ✓ SOFTWARE AUTO-PROGRAMADO CON ÉXITO: {res['module_name']}")
        print("================================================================================")
        print(f"  • Archivo Creado       : {res['file_path']}")
        print(f"  • Validación AST       : {'PASS' if res['ast_valid'] else 'FAIL'}")
        print(f"  • Ejecución en Sandbox : {'SUCCESS' if res['execution_success'] else 'FAIL'}")
        print(f"  • Ciclos de Reparación : {res['repair_cycles']}")
        if res.get("output_files"):
            print(f"  • Artefactos Creados   : {', '.join([Path(p).name for p in res['output_files']])}")
        print("================================================================================\n")

    elif args.command == "simulate":
        print(f"\n[COGNITIVO] 🔬 Ejecutando simulación de tipo '{args.type}' con aceleración de hardware...")
        res = core.simulate(args.type)
        print("\n================================================================================")
        print(f"  ✓ SIMULACIÓN COMPLETADA: {res['title']}")
        print("================================================================================")
        print(f"  • Tipo           : {res['simulation_type']}")
        print(f"  • Hardware Usado : {res['hardware_used']}")
        print(f"  • Tiempo         : {res['elapsed_seconds']}s")
        print(f"  • Artefactos     : {', '.join([Path(p).name for p in res['output_files']])}")
        print("================================================================================\n")

    elif args.command == "project":
        p = core.project_manager.get_project_state()
        print(json.dumps(p, indent=2, ensure_ascii=False))

    elif args.command == "step":
        print("\n[COGNITIVO] 🔄 Ejecutando paso autónomo del Proyecto Quimera...")
        res = core.run_parallel_cycle()
        print(f"✓ Paso completado sobre '{res['topic']}'. Software: {res['software_module']}. Sintropía: {res['syntropy']:.4f}")

    elif args.command == "daemon":
        # Ejecución en bucle desacoplada
        interval = args.interval
        log_file = LOGS_DIR / "daemon_cognitivo.log"
        logger.info(f"[DAEMON] Iniciando demonio cognitivo continuo (intervalo: {interval}s). Log: {log_file}")
        
        while True:
            try:
                logger.info("[DAEMON] Iniciando ciclo programado...")
                res = core.run_parallel_cycle()
                logger.info(f"[DAEMON] Ciclo finalizado: {res['topic']} (Sintropía: {res['syntropy']:.4f})")
            except Exception as e:
                logger.error(f"[DAEMON] Error en ciclo: {e}", exc_info=True)
            
            time.sleep(interval)


if __name__ == "__main__":
    main()
