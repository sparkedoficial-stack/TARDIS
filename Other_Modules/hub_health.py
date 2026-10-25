#!/usr/bin/env python3
"""
core/hub_health.py - Comprobación real del estado de los subsistemas del Master Hub
===================================================================================
El catálogo del Hub declaraba `status: online` para los 32 subsistemas sin comprobar
nada: había unidades systemd inactivas y un módulo marcado con una GPU que no produce
vídeo. Este módulo sustituye la etiqueta por un sondeo en paralelo con caché corta.

Estados:
  online    - responde con 2xx en < umbral
  degraded  - responde 2xx pero lento, o 4xx inesperado
  offline   - no responde (timeout / conexión rechazada) o la unidad exigida está caída
  unknown   - sin sonda definida

No abre conexiones de red exteriores: sólo loopback y unidades systemd de usuario.
"""
from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

API = "http://127.0.0.1:8757"
TIMEOUT = 3.0
SLOW_MS = 2500
CACHE_TTL = 10.0

# id del catálogo -> (path HTTP opcional, unidad systemd opcional).
# Las unidades son unidades --user; None = no aplica.
PROBES: Dict[str, Dict[str, Optional[str]]] = {
    "chat": {"http": "/health", "unit": "tardis"},
    "users": {"http": "/api/admin/users", "unit": None},
    "client": {"http": "/client", "unit": "client-gateway"},
    "boveda": {"http": "/api/vault/status", "unit": None},
    "price_sentinel": {"http": "http://127.0.0.1:8787/", "unit": "tardis-price-sentinel"},
    "terminal_pty": {"http": "http://127.0.0.1:7681/", "unit": "ftl-web-terminal"},
    "ftl_portal": {"http": "http://127.0.0.1:8765/", "unit": "ftl-web-portal"},
    "sensors": {"http": "/api/sensors/presence_status", "unit": None},
    "holodeck": {"http": "/holodeck", "unit": None},
    "shield": {"http": "/api/cyberdefense/status", "unit": None},
    "benchmark": {"http": "/benchmark", "unit": None},
    "safety": {"http": "/api/kaiju_safety/status", "unit": None},
    "gods_eye": {"http": "/api/gods_eye/status", "unit": None},
    "curiosity_debater": {"http": "/api/autonomous/status", "unit": "tardis-curiosity-debater"},
    "video_v_engine": {"http": "/video_engine", "unit": None},
    "video_vp_engine": {"http": "/video_pixelart", "unit": None},
    "agent_colony": {"http": "/api/colony", "unit": "tardis"},
    "scientific_researcher": {"http": "/scientific_researcher", "unit": None},
    "blender_3d": {"http": "/blender_animator", "unit": None},
    "airplay_monitor": {"http": "127.0.0.1:7000", "unit": "uxplay-airplay"},
    "vw_vault": {"http": "/api/vw/telemetry", "unit": None},
    "idle_daemon": {"http": "/api/idle/status", "unit": None},
    "adaptation_sys": {"http": "/api/adaptation/modules", "unit": None},
    "quantum_explorer": {"http": "/api/autonomous/status", "unit": None},
    "advanced_telemetry": {"http": "/api/telemetry", "unit": None},
    "embeddings_srv": {"http": "/embeddings", "unit": "tardis-embeddings"},
    "supervisor_thermal": {"http": "/supervisor", "unit": "tardis-supervisor"},
    "system_optimizer": {"http": "/api/system/capabilities", "unit": None},
    "background_subsystem": {"http": "/api/autonomous/status", "unit": None},
    "quantum_bridge": {"http": "/api/bridge/status", "unit": "tardis-ipad-bridge"},
    "companion_overlay": {"http": "/companion", "unit": None},
    "hybrid_synergy": {"http": "/api/synergy/status", "unit": None},
}

_cache: Dict[str, Any] = {"ts": 0.0, "data": None}


def _unit_active(unit: str) -> bool:
    try:
        res = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True, text=True, timeout=2.0,
        )
        return res.stdout.strip() == "active"
    except Exception:
        return False


def _probe_one(sid: str, spec: Dict[str, Optional[str]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"id": sid, "status": "unknown", "latency_ms": None, "detail": ""}
    unit = spec.get("unit")
    if unit:
        out["unit"] = unit
        out["unit_active"] = _unit_active(unit)
    path = spec.get("http")
    if not path:
        # Sin endpoint HTTP: el estado lo decide su unidad systemd.
        if unit:
            out["status"] = "online" if out.get("unit_active") else "offline"
        return out
    if "://" not in path and ":" in path:
        # Puerto directo (p. ej. AirPlay RAOP): se comprueba que acepte conexión.
        host, port = path.split(":", 1)
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, int(port)), timeout=1.5):
                out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                out["status"] = "online"
        except Exception as e:
            out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            out["status"] = "offline" if unit is None else ("online" if out.get("unit_active") else "offline")
            out["detail"] = type(e).__name__
        return out
    url = path if path.startswith("http") else API + path
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            ms = round((time.perf_counter() - t0) * 1000, 1)
            out["latency_ms"] = ms
            out["http"] = resp.status
            if 200 <= resp.status < 300:
                out["status"] = "degraded" if ms > SLOW_MS else "online"
            else:
                out["status"] = "degraded"
                out["detail"] = f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        out.update({"latency_ms": ms, "http": e.code})
        # 404/405 en la ruta declarada significa que el subsistema no expone nada ahí.
        out["status"] = "degraded" if e.code < 500 else "offline"
        out["detail"] = f"HTTP {e.code}"
    except Exception as e:
        out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out["status"] = "offline"
        out["detail"] = type(e).__name__
    if out.get("unit_active") is False and out["status"] == "online":
        # Responde por la API pero su unidad está caída: puede ser un path servido por el
        # propio API. Lo marcamos degradado para que el operador lo vea.
        out["status"] = "degraded"
        out["detail"] = (out.get("detail") or "") + f" unidad {unit} inactiva"
    return out


def hub_health(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    if not force and _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda kv: _probe_one(*kv), PROBES.items()))
    by_id = {r["id"]: r for r in results}
    counts: Dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    data = {
        "ok": True,
        "timestamp": now,
        "counts": counts,
        "subsystems": by_id,
    }
    _cache.update({"ts": now, "data": data})
    return data


__all__ = ["hub_health", "PROBES"]
