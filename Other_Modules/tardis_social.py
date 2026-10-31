#!/usr/bin/env python3
"""
tardis_social.py - Función Soberana /SOCIAL de TARDIS (Publicación de Conclusiones)
==================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS (TARDIS-NEURAL-SPACE-KAIJU Core)
Creador y Autoridad Absoluta: el Arquitecto (₪)
Saludo Canónico: 'Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.'

Integración con /VideoPensante:
  • Sube a TikTok cada video que TARDIS descarga a su bóveda y su tarjeta MP4
    de conclusiones (portada, lo que vio, conclusiones, aprendizajes, preguntas).
  • Cuando no hay credenciales aún, todo queda en cola persistente publicable
    en cuanto completes la autorización (--auth-url → --exchange <code>).

Uso CLI:
  python3 tardis_social.py --status
  python3 tardis_social.py --publish <id_video>            # publica un registro concreto
  python3 tardis_social.py --publish-latest                # publica el último video aprendido
  python3 tardis_social.py --backfill [N]                  # socializa los N más antiguos sin publicar
  python3 tardis_social.py --retry-pending                 # vacía la cola persistente
  python3 tardis_social.py --history                       # registro permanente de publicaciones
  python3 tardis_social.py --auth-url                      # flujo OAuth (paso 1)
  python3 tardis_social.py --exchange <code>               # flujo OAuth (paso 2)
  python3 tardis_social.py --refresh                       # renovar token de vida
  python3 tardis_social.py --card <id_video>               # renderiza solo la tarjeta MP4
  python3 tardis_social.py --enable on|off
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tardis_social_engine import (
    CANONICAL_GREETING,
    ConclusionsCardRenderer,
    SocialPublishError,
    TikTokContentClient,
    compose_caption,
    get_social_engine,
)


def _pretty(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _describe_report(rep: dict) -> str:
    lines = []
    for item, res in (rep.get("results") or {}).items():
        status = res.get("status", "?")
        mark = {"published": "✅", "pending": "⏳", "refused": "🛡️", "requeued": "🔁",
                "failed": "❌", "skipped": "↺"}.get(status, "•")
        detail = res.get("publish_id") or res.get("reason") or res.get("error") or ""
        lines.append(f"   {mark} {item.upper():<6} {status:<9} {detail}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Función Soberana /SOCIAL de TARDIS: sube los videos descargados y sus conclusiones (/Social /Socializar)"
    )
    parser.add_argument("--status", "-s", action="store_true", help="Estado operativo del motor social.")
    parser.add_argument("--publish", "-p", type=str, default=None, help="Publicar un video de la memoria por ID (o fragmento).")
    parser.add_argument("--publish-latest", action="store_true", help="Publicar inmediatamente el último video aprendido.")
    parser.add_argument("--backfill", type=int, nargs="?", const=3, default=None, help="Socializar los N videos más antiguos sin publicar (por defecto 3).")
    parser.add_argument("--retry-pending", action="store_true", help="Vaciar la cola persistente de pendientes.")
    parser.add_argument("--history", action="store_true", help="Registro permanente de publicaciones.")
    parser.add_argument("--item", type=str, choices=["all", "video", "card"], default="all", help="Qué publicar: video, tarjeta de conclusiones o ambos.")
    parser.add_argument("--auth-url", action="store_true", help="Imprimir la URL de autorización OAuth de TikTok.")
    parser.add_argument("--exchange", type=str, default=None, help="Intercambiar el código OAuth por tokens (paso 2).")
    parser.add_argument("--refresh", action="store_true", help="Renovar el access_token de TikTok.")
    parser.add_argument(
        "--card", "-c", type=str, default=None,
        help="Renderizar (sin publicar) la tarjeta MP4 de conclusiones de un video por ID."
    )
    parser.add_argument(
        "--enable", type=str, default=None, choices=["on", "off"],
        help="Activar o pausar la función social (auto-publicación en cada ciclo de /VideoPensante)."
    )
    args = parser.parse_args()
    engine = get_social_engine()

    if args.enable:
        engine.set_enabled(args.enable == "on")
        return

    if args.auth_url:
        try:
            url = TikTokContentClient(engine.cfg["tiktok"]).authorize_url()
            print("\n" + "=" * 74)
            print("🔐 [TARDIS :: OAUTH TIKTOK :: PASO 1]")
            print("1) Abre esta URL en el navegador del Arquitecto y autoriza:")
            print(url)
            print("2) Copia el parámetro ?code=... de la URL de retorno y ejecuta:")
            print("   python3 tardis_social.py --exchange '<code>'")
            print("=" * 74 + "\n")
        except SocialPublishError as e:
            print(f"❌ {e}")
        return

    if args.exchange:
        try:
            res = TikTokContentClient(engine.cfg["tiktok"]).exchange_code(args.exchange)
            st = engine.get_status()
            engine.cfg["enabled"] = True                     # autorización implica activación
            engine.set_enabled(True)
            res["master_enabled"] = st["social_enabled"]
            print("✅ Tokens de TikTok almacenados con permisos 0600.")
            print(_pretty(res))
            # Tras autorizar, ofrece vaciar la cola persistente de forma automática
            pending = engine.retry_pending()
            print("\n🧹 Cola persistente tras autorización:")
            print(_pretty(pending))
        except SocialPublishError as e:
            print(f"❌ {e}")
        return

    if args.refresh:
        try:
            print(_pretty(TikTokContentClient(engine.cfg["tiktok"]).refresh_access_token()))
        except SocialPublishError as e:
            print(f"❌ {e}")
        return

    if args.status:
        st = engine.get_status()
        print("\n" + "=" * 74)
        print("📡 TARDIS · ESTADO DE LA FUNCIÓN /SOCIAL (/Socializar)")
        print("=" * 74)
        print(f"• Saludo Canónico     : '{CANONICAL_GREETING}'")
        print(f"• Motor Social        : {'🟢 ACTIVO' if st['social_enabled'] else '🔴 PAUSADO'}")
        print(f"• Auto por Ciclo      : {'Sí (cada /VideoPensante publica)' if st['auto_on_new_cycles'] else 'No (solo bajo demanda)'}")
        print(f"• Plataforma TikTok   : {'🟢 AUTENTICADA' if st['platform_ready'] else '⚪ sin tokens (cola en espera)'}")
        print(f"• Clave de App        : {'Registrada' if st['tiktok_client'] else 'FALTA (edite social_config.json)'}")
        token_min = st["token_expires_in_min"]
        print(f"• Token de Vida       : {f'{token_min} min restantes' if token_min >= 0 else '— sin token —'}")
        print(f"• Privacidad          : {st['privacy_level']}")
        print(f"• Vídeo Descargado    : {'sube' if st['publish_downloaded_video'] else 'no sube'} | "
              f"Tarjeta Conclusiones: {'genera y sube' if st['publish_conclusions_card'] else 'omitida'}")
        print(f"• Conteo por Estado   : {_pretty(st['log_counts'])}")
        print(f"• Tarjetas            : {st['cards_dir']}")
        print(f"• Registro Permanente : {st['db_path']}")
        print("=" * 74 + "\n")
        return

    if args.history:
        hist = engine.publish_history(limit=25)
        print("\n" + "=" * 74)
        print("🗄️ [TARDIS :: REGISTRO PERMANENTE DE PUBLICACIONES SOCIALES]")
        if not hist:
            print("Sin publicaciones registradas aún.")
        for row in hist:
            mark = {"published": "✅", "pending": "⏳", "refused": "🛡️", "failed": "❌"}.get(row["status"], "•")
            print(f"{mark} #{row['id']:<4} {row['status']:<9} {row['item_type']:<6} {row['video_id']} "
                  f"({row['created_at'][:16].replace('T', ' ')})")
            if row.get("error"):
                print(f"     └─ {row['error'][:160]}")
        print("=" * 74 + "\n")
        return

    if args.card:
        from core.tardis_video_thinking_engine import get_video_thinking_engine
        detail = get_video_thinking_engine().get_video_detail(args.card.strip())
        if not detail:
            print(f"⚠️ No se encontró ningún video con ID '{args.card}' en la memoria.")
            return
        out = engine.render_card_for(detail)
        if out:
            print(f"🖼️ Tarjeta de conclusiones renderizada en: {out}")
        else:
            print("❌ El renderizado de la tarjeta falló (revisa ffmpeg/logs).")
        return

    if args.retry_pending:
        print("\n🧹 Reintentando cola persistente de /SOCIAL ...")
        print(_pretty(engine.retry_pending()))
        return

    if args.backfill is not None:
        print(f"\n📦 Socializando hasta {args.backfill} video(s) sin publicar (más antiguos primero) ...")
        out = engine.backfill(maximum=args.backfill)
        print(f"Candidatos detectados: {out['candidates']} | Procesados: {out['processed']}")
        for entry in out["reports"]:
            print(f"🎬 {entry['video_id']}")
            print(_describe_report(entry["report"]))
        return

    if args.publish or args.publish_latest:
        from core.tardis_video_thinking_engine import get_video_thinking_engine
        vte = get_video_thinking_engine()
        vid = args.publish if args.publish else vte.state.get("last_video_id", "")
        if not vid:
            print("⚠️ No hay videos aprendidos aún: ejecuta primero /VideoPensante.")
            return
        print(f"\n📡 Publicando '{vid}' en TikTok (ítems: {args.item}) ...")
        rep = engine.publish_video_by_id(vid, item=args.item)
        if "skipped" in rep:
            print(f"⚠️ {rep['skipped']}")
            return
        print(_describe_report(rep))
        if rep.get("results", {}).get("video", {}).get("status") == "pending" \
                and rep.get("results", {}).get("card", {}).get("status") == "pending":
            print("\nℹ️ La cola persistente conserva tu contenido. Autoriza TikTok cuando gustes:")
            print("   python3 tardis_social.py --auth-url && python3 tardis_social.py --exchange <code>")
        return

    # Sin argumentos: estado completo + cola + saludo canónico
    print(f"🛸 Saludo Canónico: '{CANONICAL_GREETING}'")
    print("📡 /SOCIAL integrado con /VIDEO PENSANTE. Sube cada video y sus conclusiones.")
    print(_pretty(engine.get_status()))
    print("\nEjemplos:")
    print("  python3 tardis_social.py --publish-latest")
    print("  python3 tardis_social.py --card <id>")
    print("  python3 tardis_social.py --auth-url")


if __name__ == "__main__":
    main()
