"""
TARDIS Silicon & Inference Lab — passive profiler (P1 hot-deploy, zero production risk).

Minimal implementation: Loop 1 passive silicon/inference profiler only.
Reads /run/user/1000/tardis_governor.json + AMD iGPU sysfs + Ollama :11435 state
and writes /run/user/1000/tardis_silicon_lab.json atomically. Ultra-lean footprint.
Sandbox hypotheses (Loop 2) and event-bus coordination (Loop 3) are intentionally
left as stubs for the full sovereign promotion during a planned maintenance window.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

GOV_SNAP = Path("/run/user/1000/tardis_governor.json")
OUT_SNAP = Path("/run/user/1000/tardis_silicon_lab.json")
IGPU_BASE = Path("/sys/class/drm/card1/device")


def _read_igpu() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "available": IGPU_BASE.exists(),
        "busy_pct": 0.0,
        "temp_c": 0.0,
        "vram_used_mb": 0.0,
        "gtt_used_mb": 0.0,
        "gtt_total_mb": 0.0,
        "gtt_free_mb": 0.0,
    }
    try:
        if not IGPU_BASE.exists():
            return out
        for name, key, div in (("gpu_busy_percent", "busy_pct", 1.0),
                               ("mem_info_vram_used", "vram_used_mb", 1024 * 1024),
                               ("mem_info_gtt_used", "gtt_used_mb", 1024 * 1024),
                               ("mem_info_gtt_total", "gtt_total_mb", 1024 * 1024)):
            f = IGPU_BASE / name
            if f.exists():
                try:
                    out[key] = round(float(f.read_text().strip()) / div, 1)
                except ValueError:
                    pass
        out["gtt_free_mb"] = round(max(0.0, out["gtt_total_mb"] - out["gtt_used_mb"]), 1)
        hw = IGPU_BASE / "hwmon"
        if hw.exists():
            for d in hw.glob("hwmon*"):
                tf = d / "temp1_input"
                if tf.exists():
                    try:
                        out["temp_c"] = round(float(tf.read_text().strip()) / 1000.0, 1)
                    except ValueError:
                        pass
                    break
    except Exception:
        pass
    return out


def _read_governor() -> Dict[str, Any]:
    try:
        if GOV_SNAP.exists():
            return json.loads(GOV_SNAP.read_text())
    except Exception:
        pass
    return {}


def _query_ollama_11435() -> list:
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:11435/api/ps", timeout=2.0) as r:
            data = json.loads(r.read())
            return data.get("models", []) or []
    except Exception:
        return []


def run_once() -> Dict[str, Any]:
    gov = _read_governor()
    igpu = _read_igpu()
    ollama_11435 = _query_ollama_11435()
    gpu = gov.get("gpu") or {}
    snap = {
        "ok": True,
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "governor_level": gov.get("level", "UNKNOWN"),
        "cpu_psi60": (gov.get("cpu") or {}).get("psi", {}).get("some_avg60", 0.0),
        "mem_available_mb": (gov.get("memory") or {}).get("available_mb", 0.0),
        "swap_used_mb": (gov.get("memory") or {}).get("swap_used_mb", 0.0),
        "rtx3050": {
            "temp_c": gpu.get("temp_c", 0.0),
            "util_pct": gpu.get("util_pct", 0.0),
            "vram_free_mb": gpu.get("vram_free_mb", 0.0),
            "vram_used_mb": gpu.get("vram_used_mb", 0.0),
            "pstate": gpu.get("pstate", ""),
        },
        "igpu": igpu,
        "ollama_11435_models": [m.get("name") for m in ollama_11435 if isinstance(m, dict)],
        "ollama_11435_active": bool(ollama_11435),
        "temporal_brain_sock": bool((gov.get("inference_lanes") or {}).get("temporal_brain_sock", False)),
        "hypotheses_pending": ["H-VULKAN-VLM", "H-KV-QUANT", "H-SPEC-NGRAM", "H-SPEC-R1", "H-BATCH-SAMPLING"],
        "sandbox_active": False,
    }
    # atomic write
    tmp = OUT_SNAP.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(snap, indent=2))
        os.replace(tmp, OUT_SNAP)
    except Exception:
        pass
    return snap


def run_daemon(interval: float = 30.0) -> int:
    import signal
    stop = {"v": False}

    def _h(s, f):
        stop["v"] = True

    signal.signal(signal.SIGTERM, _h)
    signal.signal(signal.SIGINT, _h)
    while not stop["v"]:
        try:
            run_once()
        except Exception:
            pass
        time.sleep(max(5.0, float(interval)))
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="tardis-silicon-lab")
    ap.add_argument("cmd", nargs="?", default="once", choices=("once", "daemon"))
    ap.add_argument("--interval", type=float, default=30.0)
    args = ap.parse_args()
    if args.cmd == "daemon":
        return run_daemon(args.interval)
    print(json.dumps(run_once(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
