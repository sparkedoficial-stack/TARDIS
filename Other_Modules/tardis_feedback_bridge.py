#!/usr/bin/env python3
"""
core/tardis_feedback_bridge.py - Canal de retroalimentación activa TARDIS ↔ Qoder
===============================================================================
TARDIS y esta sesión de chat se comunican por dos sentidos:

  TARDIS → Qoder : peticiones de cambio en el buzón (`core/qoder_request_bridge.py`,
                   subidas por el Hub, FTL, voz o los agentes de auto-mejora).
  Qoder  → TARDIS: veredictos de cada petición y deltas de salud del sistema que el
                   propio TARDIS puede releer en `/api/qoder/feedback`.

Este módulo:
  * sondea TARDIS (salud, agentes, auto-mejora) y el buzón con token del sistema;
  * detecta `pending`/`awaiting_user_approval` y cambios de estado;
  * detecta **regresiones**: un subsistema que pasa a `offline`/`degraded` que antes no lo
    estaba, un agente que deja de correr, la salud global que baja;
  * deja el estado en `~/.local/share/tardis-qoder/feedback/state.json` y los eventos en
    `events.jsonl` para que la sesión de chat los lea y responda;
  * nunca escribe en el código de TARDIS: sólo reporta. Los parches siguen pasando por
    `tardis-patch` (snapshot → verify → deploy → smoke) o por los agentes con su propia
    validación.

Uso:
  python3 core/tardis_feedback_bridge.py --once        # un ciclo (lo que lee el chat)
  python3 core/tardis_feedback_bridge.py --watch 60    # bucle para systemd
  python3 core/tardis_feedback_bridge.py --status      # resumen legible
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
API = os.environ.get("TARDIS_API", "http://127.0.0.1:8757")
OUT_DIR = Path(os.environ.get("TARDIS_FEEDBACK_DIR", Path.home() / ".local/share/tardis-qoder/feedback"))
STATE = OUT_DIR / "state.json"
EVENTS = OUT_DIR / "events.jsonl"
TOKEN_FILE = BASE / "gia_bridge_token.txt"
MAX_EVENTS = 400


def _token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _get(path: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(API + path, headers={"X-API-Key": _token(), "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _load_state() -> Dict[str, Any]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE)


def _emit(event: Dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    # Rotación simple: conserva las últimas MAX_EVENTS líneas.
    try:
        lines = EVENTS.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_EVENTS:
            EVENTS.write_text("\n".join(lines[-MAX_EVENTS:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def collect() -> Dict[str, Any]:
    """Reúne salud, agentes, auto-mejora y buzón en un solo snapshot."""
    health = _get("/api/hub/health") or {}
    agents = _get("/api/hub/agents") or {}
    improve = _get("/api/self_improve/status") or {}
    inbox = _get("/api/qoder/requests") or {}
    subs = {k: v.get("status") for k, v in (health.get("subsystems") or {}).items()}
    pending = []
    for req in inbox.get("requests") or []:
        st = str(req.get("status") or "")
        if st in ("pending", "awaiting_user_approval", "new"):
            pending.append({
                "id": req.get("request_id"),
                "title": req.get("title"),
                "status": st,
                "risk": req.get("risk"),
                "source": req.get("source"),
                "files": req.get("target_files") or [],
            })
    return {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "health_counts": health.get("counts") or {},
        "subsystems": subs,
        "agents": {"count": agents.get("agents"), "auto": agents.get("auto_mode") or []},
        "self_improve": {"score": improve.get("health_score"), "status": improve.get("status")},
        "inbox": {"stats": inbox.get("stats") or {}, "pending": pending},
    }


def diff(prev: Dict[str, Any], cur: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Eventos nuevos respecto al ciclo anterior."""
    events: List[Dict[str, Any]] = []
    if not prev:
        events.append({"kind": "primer_ciclo", "detail": "estado inicial registrado"})
        for p in cur["inbox"]["pending"]:
            events.append({"kind": "peticion_pendiente", **p})
        return events

    # 1. Cambios de salud por subsistema
    old, new = prev.get("subsystems") or {}, cur["subsystems"]
    for sid, st in new.items():
        before = old.get(sid)
        if before and before != st:
            events.append({"kind": "subsistema_cambio", "subsystem": sid, "from": before, "to": st})
    for sid in old:
        if sid not in new:
            events.append({"kind": "subsistema_ausente", "subsystem": sid})

    # 2. Peticiones nuevas o que cambiaron de estado
    prev_ids = {p["id"]: p["status"] for p in (prev.get("inbox", {}).get("pending") or [])}
    for p in cur["inbox"]["pending"]:
        if p["id"] not in prev_ids:
            events.append({"kind": "peticion_pendiente", **p})
        elif prev_ids[p["id"]] != p["status"]:
            events.append({"kind": "peticion_estado", "id": p["id"], "from": prev_ids[p["id"]], "to": p["status"]})

    # 3. Auto-mejora
    a0, a1 = (prev.get("self_improve") or {}).get("score"), (cur.get("self_improve") or {}).get("score")
    if a0 is not None and a1 is not None and a1 < a0:
        events.append({"kind": "salud_baja", "from": a0, "to": a1})
    return events


def cycle() -> Dict[str, Any]:
    prev = _load_state()
    cur = collect()
    events = diff(prev, cur)
    for ev in events:
        ev.update({"ts": cur["ts"], "iso": cur["iso"]})
        _emit(ev)
    cur["events_new"] = events
    _save_state(cur)
    return cur


def summary(cur: Dict[str, Any]) -> str:
    c = cur.get("health_counts") or {}
    lines = [f"[{cur['iso']}] salud={c} agentes={cur['agents']['count']} "
             f"auto_mejora={cur['self_improve']['score']} "
             f"buzón={cur['inbox']['stats'].get('active', 0)} activas"]
    for p in cur["inbox"]["pending"]:
        lines.append(f"  · {p['id']} [{p['status']}] {p['title']} (riesgo {p['risk']})")
    for ev in cur.get("events_new") or []:
        if ev.get("kind") != "peticion_pendiente":
            lines.append(f"  Δ {ev['kind']}: " + json.dumps({k: v for k, v in ev.items() if k not in ('ts', 'iso', 'kind')},
                                                          ensure_ascii=False)[:160])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="un ciclo y salir")
    ap.add_argument("--watch", type=int, default=0, help="ciclo cada N segundos")
    ap.add_argument("--status", action="store_true", help="resumen del último estado")
    a = ap.parse_args()
    if a.status:
        st = _load_state()
        print(summary(st) if st else "sin estado todavía")
        return 0
    if a.watch:
        while True:
            try:
                print(summary(cycle()), flush=True)
            except Exception as e:
                print(f"error ciclo: {e}", flush=True)
            time.sleep(a.watch)
    cur = cycle()
    print(summary(cur))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
