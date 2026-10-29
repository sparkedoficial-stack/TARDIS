#!/usr/bin/env python3
"""
hardware_autoprovision.py — Auto-provisión de hardware USB para TARDIS
=====================================================================
GODWORKS SYSTEM v26.4 · Arquitecto: El Arquitecto (₪)

Objetivo:
  * Detectar la bocina USB XG2TBK cuando se conecte.
  * Aplicar el perfil de salida de mayor calidad disponible.
  * Fijarla como salida por defecto y restringir el formato a PCM lineal
    (s32le) para evitar resampling con pérdida.
  * Registrar el evento y el estado en JSONL.

No formatea discos ni ejecuta acciones destructivas. Es un provisionador
de audio idempotente y seguro para ejecutarse como servicio de usuario.

Uso:
    python3 core/hardware_autoprovision.py --once
    python3 core/hardware_autoprovision.py --once --dry-run
    python3 core/hardware_autoprovision.py watch
    python3 core/hardware_autoprovision.py --simulate "XG2TBK USB Audio"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "tardis"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = STATE_DIR / "hardware_autoprovision.log"
EVENTS_PATH = STATE_DIR / "hardware_events.jsonl"
TARGET_RE = re.compile(r"xg2|xg-?2tbk", re.IGNORECASE)
DEFAULT_FORMAT = "s32le 2ch 48000Hz"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def log(message: str) -> None:
    # systemd captura stdout hacia hardware_autoprovision.log; no duplicamos
    # escribiendo también desde Python.
    print(f"[{now_iso()}] {message}", flush=True)


def record_event(kind: str, payload: Dict[str, Any]) -> None:
    try:
        with EVENTS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "iso": now_iso(),
                                 "event": kind, **payload}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def run(cmd: List[str], timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return ""
        return proc.stdout
    except Exception:
        return ""


def list_sinks() -> List[Dict[str, str]]:
    """Devuelve sinks de PulseAudio/PipeWire con nombre, formato y estado."""
    out = run(["pactl", "list", "short", "sinks"])
    sinks: List[Dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        sinks.append({
            "index": parts[0],
            "name": parts[1],
            "driver": parts[2],
            "format": parts[3],
            "state": parts[4],
        })
    return sinks


def list_cards() -> List[Dict[str, Any]]:
    """Parsea `pactl list cards` en bloques con perfiles y propiedades."""
    out = run(["pactl", "list", "cards"])
    cards: List[Dict[str, Any]] = []
    for block in out.split("\n\n"):
        if "Name:" not in block:
            continue
        name = ""
        active = ""
        description = ""
        profiles: List[Dict[str, Any]] = []
        in_profiles = False
        for raw in block.splitlines():
            line = raw.strip()
            if line.startswith("Name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                description = line.split(":", 1)[1].strip()
            elif line.startswith("Active Profile:"):
                active = line.split(":", 1)[1].strip()
                in_profiles = False
            elif line.startswith("Profiles:"):
                in_profiles = True
            elif in_profiles and line.startswith(("output:", "input:", "off")):
                profile = line.split(":", 1)[0].strip()
                if line.startswith("off"):
                    profile = "off"
                priority = 0
                m = re.search(r"priority:\s*(\d+)", line)
                if m:
                    priority = int(m.group(1))
                available = "yes" not in line.lower() or "available: yes" in line.lower()
                profiles.append({
                    "profile": profile,
                    "priority": priority,
                    "available": available,
                    "raw": line,
                })
        cards.append({
            "name": name,
            "description": description,
            "active_profile": active,
            "profiles": profiles,
            "blob": block,
        })
    return cards


def _target_match(text: str) -> bool:
    return bool(TARGET_RE.search(text or ""))


def find_target() -> Optional[Dict[str, Any]]:
    """Busca la XG2TBK en sinks y tarjetas de audio."""
    sinks = list_sinks()
    for sink in sinks:
        if _target_match(sink["name"]):
            return {"kind": "sink", "sink": sink, "card": None}

    cards = list_cards()
    for card in cards:
        haystack = "\n".join([card.get("name", ""), card.get("description", ""),
                              card.get("blob", "")])
        if not _target_match(haystack):
            continue
        # Buscar un sink cuyo nombre contenga el sufijo USB de la tarjeta.
        card_fragment = card["name"].replace("alsa_card.", "")
        matched_sink = next(
            (s for s in sinks if card_fragment in s["name"] or "usb" in s["name"].lower()),
            None,
        )
        return {"kind": "card", "sink": matched_sink, "card": card}
    return None


def best_output_profile(card: Dict[str, Any]) -> Optional[str]:
    candidates = [
        p for p in card.get("profiles", [])
        if p["profile"].startswith("output:") and p.get("available", True)
    ]
    if not candidates:
        return None
    # Preferencia: analog-stereo (PCM directo) > iec958 > pro-audio > resto.
    def score(p: Dict[str, Any]) -> tuple:
        name = p["profile"]
        pref = 0
        if "analog-stereo" in name:
            pref = 3
        elif "iec958" in name:
            pref = 2
        elif "pro-audio" in name:
            pref = 1
        return (pref, p.get("priority", 0))
    candidates.sort(key=score, reverse=True)
    return candidates[0]["profile"]


def apply_profile(target: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """Aplica perfil, salida por defecto y formato PCM lineal."""
    card = target.get("card")
    sink = target.get("sink")
    actions: List[str] = []

    if card:
        profile = best_output_profile(card)
        if profile and profile != card.get("active_profile"):
            actions.append(f"set-card-profile {card['name']} {profile}")
            if not dry_run:
                run(["pactl", "set-card-profile", card["name"], profile])
            time.sleep(0.4)
            # Releer sinks tras el cambio de perfil.
            sink = next((s for s in list_sinks() if "usb" in s["name"].lower()),
                        sink)

    if sink:
        actions.append(f"set-default-sink {sink['name']}")
        if not dry_run:
            run(["pactl", "set-default-sink", sink["name"]])
            run(["pactl", "set-sink-mute", sink["name"], "0"])
            run(["pactl", "set-sink-volume", sink["name"], "100%"])
            # PCM lineal sin resampling con pérdida.
            run(["pactl", "set-sink-formats", sink["name"], DEFAULT_FORMAT])
        actions.append(f"set-sink-formats {sink['name']} {DEFAULT_FORMAT}")

    payload = {
        "target": "XG2TBK",
        "actions": actions,
        "dry_run": dry_run,
        "sink": sink,
        "card": card["name"] if card else None,
    }
    record_event("provision", payload)
    return payload


def configure_once(dry_run: bool = False, quiet: bool = False) -> Dict[str, Any]:
    target = find_target()
    if not target:
        if not quiet:
            log("XG2TBK no presente; sin cambios.")
        return {"ok": True, "present": False}
    result = apply_profile(target, dry_run=dry_run)
    log(f"XG2TBK detectada; acciones: {'; '.join(result['actions']) or 'ninguna'}")
    return {"ok": True, "present": True, **result}


def watch() -> None:
    """Escucha eventos de PipeWire/Pulse y reaplica el perfil cuando aparece."""
    if not shutil.which("pactl"):
        log("ERROR: pactl no está disponible; abortando watcher.")
        return
    log("watcher de hardware iniciado; esperando XG2TBK...")
    # Estado inicial
    configure_once(quiet=True)
    proc = subprocess.Popen(
        ["pactl", "subscribe"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1,
    )
    last_check = 0.0
    try:
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            now = time.time()
            if line and ("sink" in line or "card" in line):
                configure_once(quiet=True)
                last_check = now
            elif now - last_check > 30:
                configure_once(quiet=True)
                last_check = now
            if proc.poll() is not None:
                time.sleep(2)
                proc = subprocess.Popen(
                    ["pactl", "subscribe"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1,
                )
    except KeyboardInterrupt:
        pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        log("watcher de hardware detenido.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Auto-provisión USB XG2TBK para TARDIS")
    ap.add_argument("--once", action="store_true", help="una sola comprobación")
    ap.add_argument("--dry-run", action="store_true", help="no aplicar cambios")
    ap.add_argument("--simulate", default="", help="simular una cadena de dispositivo")
    ap.add_argument("command", nargs="?", default="watch", choices=["watch", "status"])
    args = ap.parse_args()

    if args.simulate:
        matched = _target_match(args.simulate)
        print(json.dumps({"simulate": args.simulate, "match": matched}, ensure_ascii=False))
        return 0
    if args.command == "status" or args.once:
        print(json.dumps(configure_once(dry_run=args.dry_run), indent=2, ensure_ascii=False))
        return 0
    watch()
    return 0


if __name__ == "__main__":
    sys.exit(main())
