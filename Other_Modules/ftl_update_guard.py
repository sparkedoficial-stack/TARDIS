#!/usr/bin/env python3
"""
GODWORKS · FTL Update Guard · Compuerta de mantenimiento
=======================================================
Impide que las actualizaciones, reinicios y auto-mejoras del sistema
interrumpan una petición que el Arquitecto está redactando o transmitiendo.

Uso
---
  ftl_update_guard.py --check                 # 0 = libre, 75 = diferir
  ftl_update_guard.py --wait --timeout 600    # espera a que la bóveda se cierre
  ftl_update_guard.py --status                # informe JSON legible
  ftl_update_guard.py --explain               # motivo en texto plano

Códigos de salida
-----------------
  0   vía libre (sin bóvedas activas)
  75  EX_TEMPFAIL · hay una petición en curso; reintentar más tarde

Integración
-----------
* `ExecStartPre=` en `ftl-web-portal.service` (drop-in): los reinicios esperan.
* `auto_update_tardis.sh`: el ciclo de git sync se salta si hay bóveda viva.
* `tardis_system_repair.py` / `savemode_manager.py`: esperan antes de reiniciar.
* `savage-update`: consulta la compuerta antes de tocar servicios FTL.

Un flag manual ``~/.config/ftl/maintenance.flag`` (con un epoch opcional)
también activa la compuerta para ventanas de mantenimiento deliberadas.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

FTL_DIR = Path(__file__).resolve().parent
if str(FTL_DIR) not in sys.path:
    sys.path.insert(0, str(FTL_DIR))

import chat_vault as vault  # noqa: E402

MAINTENANCE_FLAG = Path.home() / ".config" / "ftl" / "maintenance.flag"
EX_TEMPFAIL = 75
POLL_SECONDS = 1.5


def manual_maintenance() -> dict:
    if not MAINTENANCE_FLAG.is_file():
        return {"active": False}
    try:
        raw = MAINTENANCE_FLAG.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        raw = ""
    until = None
    for token in raw.replace(",", " ").split():
        try:
            value = float(token)
        except ValueError:
            continue
        until = value / 1000.0 if value > 1e11 else value
        break
    if until and until <= time.time():
        try:
            MAINTENANCE_FLAG.unlink(missing_ok=True)
        except Exception:
            pass
        return {"active": False, "expired": True}
    return {"active": True, "until": until, "note": raw[:200]}


def snapshot() -> dict:
    vault.purge_expired()
    gate = vault.gate_status()
    manual = manual_maintenance()
    busy = bool(gate.get("defer_updates")) or bool(manual.get("active"))
    return {
        "busy": busy,
        "defer_updates": busy,
        "vault": gate,
        "maintenance": manual,
        "checked_at": vault.iso(),
    }


def wait_until_clear(timeout: float, *, quiet: bool = False) -> dict:
    started = time.time()
    deadline = started + max(0.0, timeout)
    current = snapshot()
    if not current["busy"]:
        return {**current, "waited_s": 0.0, "timed_out": False}
    if not quiet:
        print(
            f"[ftl-guard] Petición en curso ({current['vault']['active']} bóveda(s)). "
            f"Esperando hasta {int(timeout)}s antes de continuar…",
            file=sys.stderr,
        )
    while current["busy"] and time.time() < deadline:
        time.sleep(POLL_SECONDS)
        current = snapshot()
    current["waited_s"] = round(time.time() - started, 1)
    current["timed_out"] = bool(current["busy"])
    if not quiet:
        if current["busy"]:
            print(
                "[ftl-guard] Tiempo de espera agotado; se pospone el mantenimiento.",
                file=sys.stderr,
            )
        else:
            print(
                f"[ftl-guard] Bóveda cerrada tras {current['waited_s']}s. Vía libre.",
                file=sys.stderr,
            )
    return current


def explain(snap: dict) -> str:
    if not snap["busy"]:
        return "VÍA LIBRE · ninguna petición blindada en curso."
    lines = ["PETICIÓN EN CURSO · mantenimiento diferido:"]
    for draft in snap["vault"].get("drafts", []):
        lines.append(
            f"  • {draft['draft_id']} · sesión {draft['session_id']} · "
            f"{draft['state']} · {draft['chars']} caracteres · expira en {draft['expires_in']}s"
        )
    if snap["maintenance"].get("active"):
        lines.append(f"  • mantenimiento manual activo · {snap['maintenance'].get('note', '')}")
    return "\n".join(lines)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="FTL Update Guard · compuerta de mantenimiento")
    parser.add_argument("--check", action="store_true", help="0 libre · 75 diferir")
    parser.add_argument("--wait", action="store_true", help="Espera a que la bóveda se cierre")
    parser.add_argument("--timeout", type=float, default=600.0, help="Segundos máximos de espera (default 600)")
    parser.add_argument("--status", action="store_true", help="Informe JSON")
    parser.add_argument("--explain", action="store_true", help="Motivo legible")
    parser.add_argument("--quiet", action="store_true", help="Sin mensajes por stderr")
    parser.add_argument("--flag-maintenance", nargs="?", const="", default=None, metavar="EPOCH_O_MINUTOS",
                        help="Activa el flag manual (epoch o minutos desde ahora)")
    parser.add_argument("--clear-maintenance", action="store_true", help="Desactiva el flag manual")
    args = parser.parse_args()

    if args.flag_maintenance is not None:
        raw = (args.flag_maintenance or "").strip()
        until = time.time() + 60.0
        if raw:
            try:
                value = float(raw)
                until = value / 1000.0 if value > 1e11 else (time.time() + value * 60 if value < 10000 else value)
            except ValueError:
                pass
        MAINTENANCE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        MAINTENANCE_FLAG.write_text(f"{until} · ventana de mantenimiento manual\n", encoding="utf-8")
        print(json.dumps({"ok": True, "maintenance_until": vault.iso(until)}, ensure_ascii=False))
        return 0
    if args.clear_maintenance:
        MAINTENANCE_FLAG.unlink(missing_ok=True)
        print(json.dumps({"ok": True, "maintenance": False}, ensure_ascii=False))
        return 0

    if args.wait:
        snap = wait_until_clear(args.timeout, quiet=args.quiet)
        if args.status:
            print(json.dumps(snap, indent=2, ensure_ascii=False))
        elif args.explain and not args.quiet:
            print(explain(snap))
        return EX_TEMPFAIL if snap["busy"] else 0

    snap = snapshot()
    if args.status:
        print(json.dumps(snap, indent=2, ensure_ascii=False))
    elif args.explain:
        print(explain(snap))
    else:
        print("DEFER" if snap["busy"] else "CLEAR")
    if args.check or not (args.status or args.explain):
        return EX_TEMPFAIL if snap["busy"] else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
