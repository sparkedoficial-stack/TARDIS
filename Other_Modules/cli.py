"""core/governor/cli.py - CLI soberana `tardis-governor`."""
from __future__ import annotations

import argparse
import json
import logging

def main() -> int:
    ap = argparse.ArgumentParser(prog="tardis-governor", description="TARDIS Sovereign Resource Governor & Inference Arbiter")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Snapshot actual de presión, cgroups y admisión")
    p_adm = sub.add_parser("admit", help="Consulta admisión para una clase de tarea")
    p_adm.add_argument("task_class", nargs="?", default="heavy_learning")
    p_rec = sub.add_parser("reclaim", help="Descarga modelos duplicados, aplica throttling Ring 0 y poda backups")
    p_rec.add_argument("--dry-run", action="store_true")
    p_rec.add_argument("--no-throttle", action="store_true", help="Omitir ajuste cgroup v2 durante reclaim")
    p_th = sub.add_parser("throttle", help="Aplica throttling cgroup v2 en caliente según presión o nivel forzado")
    p_th.add_argument("--level", choices=["ORANGE", "RED"], default=None)
    p_th.add_argument("--dry-run", action="store_true")
    p_rel = sub.add_parser("release", help="Restaura límites cgroup v2 originales tras estabilización")
    p_rel.add_argument("--dry-run", action="store_true")
    p_rel.add_argument("--restore-power-profile", action="store_true", help="Forzar restauración inmediata del perfil energético base")
    p_ge = sub.add_parser("gpu-eco", help="Reconcilia o fija el modo eco P-State GPU (RTX 3050) y Hyprland")
    p_ge.add_argument("--mode", choices=["normal", "eco_idle", "eco_thermal"], default=None)
    p_ge.add_argument("--dry-run", action="store_true")
    p_sb = sub.add_parser("swap-bloat", help="Inspecciona swap-bloat de motores llama-server y recicla de forma segura en reposo")
    p_sb.add_argument("--recycle", action="store_true", help="Ejecuta reconciliación/reciclaje seguro en reposo")
    p_sb.add_argument("--force", action="store_true", help="Omite uptime mínimo y cooldown (sigue verificando reposo/llamada)")
    p_sb.add_argument("--dry-run", action="store_true")
    p_hist = sub.add_parser("history", help="Histórico de telemetría de presión")
    p_hist.add_argument("--limit", type=int, default=20)
    p_d = sub.add_parser("daemon", help="Ejecuta el gobernador en bucle systemd 24/7")
    p_d.add_argument("--interval", type=float, default=20.0)
    p_d.add_argument("--reclaim-interval", type=float, default=300.0)

    args = ap.parse_args()
    from core.tardis_resource_governor import get_resource_governor
    gov = get_resource_governor()

    if args.cmd == "status":
        print(json.dumps(gov.collect_snapshot(persist=True), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "admit":
        res = gov.admit(args.task_class)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("allowed") else 2
    if args.cmd == "reclaim":
        print(
            json.dumps(
                gov.reclaim_resources(dry_run=args.dry_run, apply_throttle=not args.no_throttle),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.cmd == "throttle":
        print(
            json.dumps(
                gov.apply_throttling(dry_run=args.dry_run, force_level=args.level),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.cmd == "release":
        print(
            json.dumps(
                gov.release_throttling(
                    dry_run=args.dry_run,
                    force_restore_power_profile=bool(getattr(args, "restore_power_profile", False)),
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.cmd == "gpu-eco":
        print(
            json.dumps(
                gov.reconcile_gpu_eco(dry_run=args.dry_run, force_mode=args.mode),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.cmd == "swap-bloat":
        if args.recycle:
            out_sb = gov.reconcile_swap_bloat(dry_run=args.dry_run, force=bool(args.force))
        else:
            snap_sb = gov.collect_snapshot(persist=False)
            out_sb = {
                "ok": True,
                "inference_memory": snap_sb.get("inference_memory") or [],
                "memory_bloat_units": snap_sb.get("memory_bloat_units") or [],
                "swap_recycle": gov.get_swap_recycle_status(),
            }
        print(json.dumps(out_sb, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "history":
        print(json.dumps({"ok": True, "history": gov.history(limit=args.limit)}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "daemon":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (tardis-governor) %(message)s")
        return gov.run_daemon(interval=args.interval, reclaim_interval=args.reclaim_interval)
    return 0
