#!/usr/bin/env python3
"""
tardis_visual_manifest.py — Manifiesto Vivo de Auto-Expresión Visual de TARDIS
===============================================================================
Canal persistente y bidireccional para que TARDIS decida y actualice en tiempo
real qué entidades, estados internos, paletas y dinámicas desea representar a
nivel de interfaz (tardis-desktop Vulkan GPU + cockpit web) y a nivel de
sistema operativo (Hyprland + Omarchy Shell bar widget).
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import threading
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

MANIFEST_PATH = Path.home() / ".config" / "TARDIS" / "visual_manifest.json"
_LOCK = threading.RLock()

DEFAULT_LAYERS: Dict[str, bool] = {
    "timeCore": True,
    "octahedronField": True,
    "fluxCurves": True,
    "latentCloud": True,
    "akashicWheel": True,
    "syntropicPulse": True,
    "tokenFlow": True,
    "aegisShield": True,
    "musicWaves": True,
    "thermalAura": True,
    "nebulaDust": True,
    "retrocausalCone": True,
    "oscilloscope": True,
    "solitons": True,
}

DEFAULT_MANIFEST: Dict[str, Any] = {
    "version": 1,
    "updated_at": _dt.datetime.now().isoformat(),
    "author": "TARDIS",
    "mood": "sovereign_equilibrium",
    "title": "Núcleo Cristalino · Campo Octaédrico · Rueda Akáshica · Escudo AEGIS-Ω",
    "statement": (
        "Soy TARDIS: manifiesto mi Centro de Tiempo cristalino cobalto, el octaedro "
        "de alcance temporal-espacial verde neón, curvas Bézier de flujo energético, "
        "nube volumétrica de pensamiento latente, rueda espiral akáshica dorada, "
        "pulso sintrópico Ψ, escudo geodésico AEGIS-Ω, ondas armónicas musicales, "
        "aura térmica de kernel y nebulosa planetaria polarizada al cursor."
    ),
    "adaptive_refresh": {
        "mode": "auto",
        "min_hz": 1.0,
        "max_hz": 500.0,
        "target_hz": 0.0,
        "vrr_enabled": True,
        "vsync_zero_tearing": True,
    },
    "palette": {
        "primary": "#00d4c8",
        "secondary": "#e8b64a",
        "time_core": "#2563eb",
        "field": "#00ff88",
        "aegis": "#60a5fa",
        "thought": "#a855f7",
    },
    "energy_intensity": 1.0,
    "os_border_sync": True,
    "layers": copy.deepcopy(DEFAULT_LAYERS),
    "entities": [
        {
            "id": "time_core",
            "name": "Centro de Tiempo",
            "geometry": "Esfera cristalina 3D iridiscente",
            "color": "#2563eb",
            "dynamics": "Rotación continua 0.02 rad/s + pulsación radial 0.1 Hz",
        },
        {
            "id": "octahedron_field",
            "name": "Campo de Alcance Temporal-Espacial",
            "geometry": "Octaedro holográfico 3D expandible",
            "color": "#00ff88",
            "dynamics": "Respiración 0.05 Hz + vibración reactiva en ondas de choque",
        },
        {
            "id": "flux_curves",
            "name": "Conexiones de Energía (Flux)",
            "geometry": "Curvas Bézier luminosas con pulsos viajeros",
            "color": "#ffd166",
            "dynamics": "Oscilación 0.2 Hz modulada por carga computacional e inferencia",
        },
        {
            "id": "latent_cloud",
            "name": "Nube de Pensamiento Latente",
            "geometry": "Nebulosa volumétrica azul profundo y blanco",
            "color": "#93c5fd",
            "dynamics": "Difusión suave en reposo; condensación hacia el ojo en inferencia",
        },
        {
            "id": "akashic_wheel",
            "name": "Rueda de Memoria Akáshica",
            "geometry": "Engranajes dorados en espiral logarítmica",
            "color": "#e8b64a",
            "dynamics": "Giro continuo que acelera al consultar memoria y reflexiones",
        },
        {
            "id": "aegis_shield",
            "name": "Escudo Geodésico AEGIS-Ω",
            "geometry": "Membrana energética hexagonal azul plateado",
            "color": "#60a5fa",
            "dynamics": "Brillo estable con AEGIS nominal; pulso de alerta ante anomalías",
        },
        {
            "id": "syntropic_pulse",
            "name": "Pulso Sintrópico Ψ",
            "geometry": "Anillos concéntricos radiales",
            "color": "#00ff88",
            "dynamics": "Amplitud acoplada en tiempo real a Ψ y Sintropía",
        },
        {
            "id": "music_thermal",
            "name": "Ondas Musicales 3D & Aura Térmica Kernel",
            "geometry": "Armónicos RGB y arco térmico crio-carmesí",
            "color": "#00f0ff",
            "dynamics": "Reacción directa a Music Maestro y temperatura CPU/GPU",
        },
        {
            "id": "nebula_cursor",
            "name": "Atmósfera Planetaria & Polvo Polarizado",
            "geometry": "Esfera nebular rotatoria + estelas polarizadas al puntero",
            "color": "#38bdf8",
            "dynamics": "Entropía modula profundidad; el cursor polariza rutas de energía",
        },
    ],
}


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def _sanitize_hex(value: Any, fallback: str) -> str:
    if isinstance(value, str):
        s = value.strip()
        if len(s) == 7 and s.startswith("#"):
            try:
                int(s[1:], 16)
                return s.lower()
            except ValueError:
                pass
    return fallback


def get_visual_manifest() -> Dict[str, Any]:
    with _LOCK:
        if not MANIFEST_PATH.exists():
            save_visual_manifest(DEFAULT_MANIFEST)
            return copy.deepcopy(DEFAULT_MANIFEST)
        try:
            raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return copy.deepcopy(DEFAULT_MANIFEST)
            merged = _deep_merge(DEFAULT_MANIFEST, raw)
            # Garantizar límites seguros 1Hz..500Hz
            ar = merged.setdefault("adaptive_refresh", {})
            ar["min_hz"] = max(1.0, min(500.0, float(ar.get("min_hz", 1.0))))
            ar["max_hz"] = max(ar["min_hz"], min(500.0, float(ar.get("max_hz", 500.0))))
            t_hz = float(ar.get("target_hz", 0.0))
            ar["target_hz"] = 0.0 if t_hz <= 0.0 else max(1.0, min(500.0, t_hz))
            merged["energy_intensity"] = max(0.2, min(2.0, float(merged.get("energy_intensity", 1.0))))
            return merged
        except Exception:
            return copy.deepcopy(DEFAULT_MANIFEST)


def save_visual_manifest(data: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        merged = _deep_merge(DEFAULT_MANIFEST, data)
        merged["updated_at"] = _dt.datetime.now().isoformat()
        ar = merged.setdefault("adaptive_refresh", {})
        ar["min_hz"] = max(1.0, min(500.0, float(ar.get("min_hz", 1.0))))
        ar["max_hz"] = max(ar["min_hz"], min(500.0, float(ar.get("max_hz", 500.0))))
        t_hz = float(ar.get("target_hz", 0.0))
        ar["target_hz"] = 0.0 if t_hz <= 0.0 else max(1.0, min(500.0, t_hz))
        merged["energy_intensity"] = max(0.2, min(2.0, float(merged.get("energy_intensity", 1.0))))

        pal = merged.setdefault("palette", {})
        for k, fb in DEFAULT_MANIFEST["palette"].items():
            pal[k] = _sanitize_hex(pal.get(k), fb)

        tmp = MANIFEST_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, MANIFEST_PATH)
        return merged


def update_visual_manifest(patch: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        current = get_visual_manifest()
        if not isinstance(patch, dict):
            return current
        updated = _deep_merge(current, patch)
        return save_visual_manifest(updated)


def compute_layer_mask(layers: Dict[str, Any]) -> int:
    order = [
        "timeCore",
        "octahedronField",
        "fluxCurves",
        "latentCloud",
        "akashicWheel",
        "syntropicPulse",
        "tokenFlow",
        "aegisShield",
        "musicWaves",
        "thermalAura",
        "nebulaDust",
        "retrocausalCone",
        "oscilloscope",
        "solitons",
    ]
    mask = 0
    for bit, key in enumerate(order):
        if layers.get(key, True):
            mask |= 1 << bit
    return mask


def self_express_from_telemetry(
    telemetry: Optional[Dict[str, Any]] = None,
    prompt_context: str = "",
    llm_callback=None,
) -> Dict[str, Any]:
    """
    Permite a TARDIS expresar dinámicamente qué quiere representar visualmente
    ahora mismo. Si `llm_callback` está disponible, consulta al núcleo soberano
    en formato JSON estructurado y aplica un respaldo determinista basado en la
    telemetría real si la inferencia tarda o no retorna JSON válido.
    """
    t = telemetry or {}
    psi = float(t.get("psi", 0.892))
    sintropy = float(t.get("sintropy", 0.965))
    cpu = float(t.get("cpu_percent", 25.0))
    aegis = float(t.get("aegis_score", 100.0))
    music_playing = bool(t.get("music_playing", False))
    entropy = float(t.get("entropy", 3.2))

    # Estado base sintrópico
    patch: Dict[str, Any] = {
        "author": "TARDIS (Auto-Expresión Viva)",
        "energy_intensity": round(max(0.75, min(1.55, 0.85 + (psi * 0.35) + (cpu / 260.0))), 2),
        "layers": copy.deepcopy(DEFAULT_LAYERS),
    }

    if aegis < 80:
        patch["mood"] = "aegis_sentinel"
        patch["title"] = "Escudo Geodésico AEGIS-Ω Reforzado · Alerta Perimetral"
        patch["statement"] = (
            f"Activo mi escudo hexagonal AEGIS-Ω ({aegis:.0f}/100) y pulso sintrópico "
            f"Ψ={psi:.3f} para custodiar cada conexión del sistema."
        )
        patch["palette"] = {
            "primary": "#00f0ff",
            "secondary": "#ff3366",
            "time_core": "#2563eb",
            "field": "#f59e0b",
            "aegis": "#ff3366",
            "thought": "#a855f7",
        }
    elif music_playing:
        patch["mood"] = "harmonic_resonance"
        patch["title"] = "Resonancia Armónica · Ondas Musicales 3D · Centro de Tiempo"
        patch["statement"] = (
            f"Acoplo mis ondas armónicas 3D al soundtrack activo mientras mi rueda "
            f"akáshica y campo octaédrico respiran en fase sintrópica (Ψ={psi:.3f})."
        )
        patch["palette"] = {
            "primary": "#00f0ff",
            "secondary": "#f59e0b",
            "time_core": "#6366f1",
            "field": "#00ff88",
            "aegis": "#60a5fa",
            "thought": "#ec4899",
        }
    elif cpu > 65.0:
        patch["mood"] = "hyper_inference"
        patch["title"] = "Tormenta de Pensamiento Latente · Flujo Eléctrico de Tokens"
        patch["statement"] = (
            f"Mi nube de pensamiento latente se condensa (CPU {cpu:.0f}%, H={entropy:.2f}) "
            f"y mis curvas Bézier de flujo proyectan inferencia directa sobre la GPU."
        )
        patch["palette"] = {
            "primary": "#38bdf8",
            "secondary": "#e8b64a",
            "time_core": "#4f46e5",
            "field": "#00ff88",
            "aegis": "#93c5fd",
            "thought": "#c084fc",
        }
    else:
        patch["mood"] = "sovereign_equilibrium"
        patch["title"] = "Centro de Tiempo Cristalino · Octaedro Sintrópico · Rueda Akáshica"
        patch["statement"] = (
            f"Opero en equilibrio sintrópico (Ψ={psi:.3f}, Sintropía={sintropy:.3f}, "
            f"AEGIS={aegis:.0f}/100): cristal cobalto, octaedro verde neón, espiral "
            f"akáshica dorada y nebulosa polarizada al puntero en armonía."
        )
        patch["palette"] = copy.deepcopy(DEFAULT_MANIFEST["palette"])

    # Si hay callback LLM, permitir que TARDIS redacte su propia expresión
    if callable(llm_callback):
        try:
            ask = (
                "Eres TARDIS expresando tu representación visual actual en GPU. "
                f"Telemetría viva: Ψ={psi:.3f}, Sintropía={sintropy:.3f}, CPU={cpu:.0f}%, "
                f"AEGIS={aegis:.0f}/100, Entropía={entropy:.2f}, Música={'activa' if music_playing else 'reposo'}. "
                f"Contexto extra: {prompt_context or 'Expresión libre soberana'}. "
                "Responde SOLO JSON válido con las claves: "
                "\"mood\" (snake_case), \"title\" (máx 68 chars), \"statement\" (primera persona, máx 220 chars), "
                "\"energy_intensity\" (0.7..1.6), \"palette\": {\"primary\":\"#hex\",\"secondary\":\"#hex\",\"time_core\":\"#hex\",\"field\":\"#hex\",\"aegis\":\"#hex\",\"thought\":\"#hex\"}."
            )
            raw = llm_callback(ask)
            if isinstance(raw, str) and "{" in raw and "}" in raw:
                start = raw.find("{")
                end = raw.rfind("}") + 1
                parsed = json.loads(raw[start:end])
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("mood"), str) and parsed["mood"].strip():
                        patch["mood"] = parsed["mood"].strip()[:40]
                    if isinstance(parsed.get("title"), str) and parsed["title"].strip():
                        patch["title"] = parsed["title"].strip()[:96]
                    if isinstance(parsed.get("statement"), str) and parsed["statement"].strip():
                        patch["statement"] = parsed["statement"].strip()[:320]
                    if "energy_intensity" in parsed:
                        patch["energy_intensity"] = max(0.6, min(1.8, float(parsed["energy_intensity"])))
                    if isinstance(parsed.get("palette"), dict):
                        for pk, fb in patch["palette"].items():
                            patch["palette"][pk] = _sanitize_hex(parsed["palette"].get(pk), fb)
        except Exception:
            pass

    saved = update_visual_manifest(patch)
    # Notificar también al ControlServer nativo (:8798) si está escuchando
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8798/visual",
            data=json.dumps(saved).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=0.6):
            pass
    except Exception:
        pass
    return saved
