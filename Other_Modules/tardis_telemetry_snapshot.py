"""
core/tardis_telemetry_snapshot.py - Colector Unificado de Telemetría Viva de TARDIS
====================================================================================
Recolecta en menos de un segundo el estado real del nodo soberano TARDIS para alimentar
en tiempo real las animaciones 3D, los gráficos de datos y los HUDs de video respuestas:

  * Manifiesto visual vivo (~/.config/TARDIS/visual_manifest.json): paleta, capas, ánimo.
  * Tensor causal / retrocausal (Ψ, Sintropía, Φ_adv, O_QCO, S_geom, Q_topo, Lamport).
  * Metapensamiento cognitivo (entropía Shannon, coherencia sintrópica, símbolos activos).
  * Bóveda Akáshica 250GB (eventos, épocas jerárquicas, contemplaciones, grafo KG).
  * Postura de seguridad AEGIS-Ω (score, hallazgos, archivos escaneados).
  * Hardware, térmica y presión de Kernel Ring 0 (PSI CPU/MEM/IO, CPU/GPU/NVMe °C, RAM).
  * Radar RF de presencia y telemetría atmosférica local sanitizada (sin coordenadas).
  * Subsistemas activos, ciclos autónomos y Music Maestro.

Blindaje AEGIS-Ω:
  * Jamás coloca tokens o credenciales en parámetros de URL (solo cabecera X-GIA-Key).
  * Jamás expone datos personales confidenciales ni cadenas de versión obsoletas.
"""

from __future__ import annotations

import concurrent.futures
import copy
import datetime as _dt
import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("TardisTelemetrySnapshot")

BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN_FILE = Path.home() / ".config" / "tardis" / "secrets" / "gia_token"

_CACHE_LOCK = threading.RLock()
_CACHE_TS: float = 0.0
_CACHE_DATA: Optional[Dict[str, Any]] = None

_FONT_CANDIDATES: Dict[str, List[str]] = {
    "mono_bold": [
        "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ],
    "mono": [
        "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf",
        "/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ],
    "sans_bold": [
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "sans": [
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}

_FONT_RESOLVED_CACHE: Dict[str, Optional[str]] = {}

_FORBIDDEN_RE = re.compile(
    r"miguel\s+[aá]ngel\s+may\s+canch[eé]|v26\.4|v26\b",
    re.IGNORECASE,
)


def resolve_font_path(kind: str = "sans_bold") -> Optional[str]:
    """Resuelve una fuente TrueType disponible en el sistema (Arch/Omarchy o Debian)."""
    if kind in _FONT_RESOLVED_CACHE:
        return _FONT_RESOLVED_CACHE[kind]
    for path in _FONT_CANDIDATES.get(kind, _FONT_CANDIDATES["sans_bold"]):
        if os.path.exists(path):
            _FONT_RESOLVED_CACHE[kind] = path
            return path
    for candidates in _FONT_CANDIDATES.values():
        for path in candidates:
            if os.path.exists(path):
                _FONT_RESOLVED_CACHE[kind] = path
                return path
    _FONT_RESOLVED_CACHE[kind] = None
    return None


def hex_to_rgb(value: Any, fallback: Tuple[int, int, int] = (0, 212, 200)) -> Tuple[int, int, int]:
    """Convierte un color hexadecimal #RRGGBB a tupla RGB uint8 segura."""
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        try:
            return (
                max(0, min(255, int(value[0]))),
                max(0, min(255, int(value[1]))),
                max(0, min(255, int(value[2]))),
            )
        except Exception:
            return fallback
    if isinstance(value, str):
        s = value.strip().lstrip("#")
        if len(s) == 6:
            try:
                return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
            except ValueError:
                pass
    return fallback


def _sanitize_text(text: Any, max_len: int = 240) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    s = _FORBIDDEN_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max(1, max_len - 1)].rstrip() + "…"
    return s


def _read_api_token() -> str:
    env_tok = os.environ.get("GIA_TOKEN") or os.environ.get("GIA_AUTH_TOKEN") or ""
    if env_tok.strip():
        return env_tok.strip()
    try:
        if TOKEN_FILE.is_file():
            return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def _http_get_json(url: str, token: str, timeout: float = 0.65) -> Optional[Dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-GIA-Key"] = token
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def _read_kernel_psi() -> Dict[str, float]:
    """Lee Pressure Stall Information (PSI) directamente del kernel Linux (/proc/pressure)."""
    out = {"cpu_avg10": 0.0, "mem_avg10": 0.0, "io_avg10": 0.0}
    mapping = (("cpu", "cpu_avg10"), ("memory", "mem_avg10"), ("io", "io_avg10"))
    for fname, key in mapping:
        p = Path(f"/proc/pressure/{fname}")
        try:
            if p.is_file():
                txt = p.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"some\s+avg10=([0-9.]+)", txt)
                if m:
                    out[key] = round(float(m.group(1)), 2)
        except Exception:
            pass
    return out


def _read_local_hw_fallback() -> Dict[str, Any]:
    """Telemetría local instantánea desde psutil y /sys/class/hwmon como respaldo o complemento."""
    hw: Dict[str, Any] = {
        "cpu_percent": 0.0,
        "ram_percent": 0.0,
        "ram_used_gb": 0.0,
        "ram_total_gb": 32.0,
        "ram_available_gb": 0.0,
        "cpu_temp_c": 0.0,
        "gpu_temp_c": 0.0,
        "nvme_temp_c": 0.0,
        "battery_percent": 100.0,
        "power_plugged": True,
        "power_profile": "performance",
    }
    try:
        import psutil
        hw["cpu_percent"] = round(float(psutil.cpu_percent(interval=None)), 1)
        vm = psutil.virtual_memory()
        hw["ram_percent"] = round(float(vm.percent), 1)
        hw["ram_total_gb"] = round(vm.total / (1024 ** 3), 2)
        hw["ram_available_gb"] = round(vm.available / (1024 ** 3), 2)
        hw["ram_used_gb"] = round((vm.total - vm.available) / (1024 ** 3), 2)
        bat = psutil.sensors_battery()
        if bat is not None:
            hw["battery_percent"] = round(float(bat.percent), 1)
            hw["power_plugged"] = bool(bat.power_plugged)
        temps = psutil.sensors_temperatures() or {}
        for k in ("k10temp", "coretemp", "acpitz"):
            entries = temps.get(k)
            if entries:
                hw["cpu_temp_c"] = round(float(entries[0].current), 1)
                break
        for k in ("amdgpu", "nouveau", "nvidia"):
            entries = temps.get(k)
            if entries:
                hw["gpu_temp_c"] = round(float(entries[0].current), 1)
                break
        if temps.get("nvme"):
            hw["nvme_temp_c"] = round(float(temps["nvme"][0].current), 1)
    except Exception:
        pass
    return hw


def _load_visual_manifest() -> Dict[str, Any]:
    try:
        from core.tardis_visual_manifest import compute_layer_mask, get_visual_manifest
        mf = get_visual_manifest()
        layers = mf.get("layers") if isinstance(mf.get("layers"), dict) else {}
        mf["layer_mask"] = int(compute_layer_mask(layers))
        mf["active_layers_count"] = sum(1 for v in layers.values() if bool(v))
        mf["total_layers_count"] = max(1, len(layers))
        return mf
    except Exception:
        layers = {
            "timeCore": True, "octahedronField": True, "fluxCurves": True,
            "latentCloud": True, "akashicWheel": True, "syntropicPulse": True,
            "tokenFlow": True, "aegisShield": True, "musicWaves": True,
            "thermalAura": True, "nebulaDust": True, "retrocausalCone": True,
            "oscilloscope": True, "solitons": True,
        }
        return {
            "mood": "sovereign_equilibrium",
            "title": "Centro de Tiempo Cristalino · Octaedro Sintrópico · Rueda Akáshica",
            "statement": (
                "Opero en equilibrio sintrópico con núcleo cristalino cobalto, "
                "campo octaédrico neón, rueda akáshica dorada y escudo AEGIS-Ω."
            ),
            "author": "TARDIS",
            "energy_intensity": 1.2,
            "palette": {
                "primary": "#00d4c8",
                "secondary": "#e8b64a",
                "time_core": "#2563eb",
                "field": "#00ff88",
                "aegis": "#60a5fa",
                "thought": "#a855f7",
            },
            "layers": layers,
            "layer_mask": (1 << 14) - 1,
            "active_layers_count": 14,
            "total_layers_count": 14,
        }


def default_snapshot() -> Dict[str, Any]:
    """Retorna una estructura completa con valores base seguros."""
    mf = _load_visual_manifest()
    local_hw = _read_local_hw_fallback()
    psi_k = _read_kernel_psi()
    local_hw["psi_cpu_avg10"] = psi_k["cpu_avg10"]
    local_hw["psi_mem_avg10"] = psi_k["mem_avg10"]
    local_hw["psi_io_avg10"] = psi_k["io_avg10"]
    return {
        "captured_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp": time.time(),
        "live_api": False,
        "core": {
            "system": "TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL",
            "model": os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU"),
            "llm_online": True,
            "num_ctx": 16384,
            "active_tasks_count": 0,
            "models_count": 1,
        },
        "visual_manifest": mf,
        "causal": {
            "psi": 0.892,
            "sintropy": 0.965,
            "phi_adv": 0.780,
            "o_qco": 0.840,
            "s_geom": 1.5708,
            "q_topo": 3,
            "bifurcation": "EQUILIBRIO_SINTROPICO",
            "lamport": 0,
            "active_clients": 1,
            "cone_active": True,
            "oscilloscope_active": True,
        },
        "cognitive": {
            "entropy_shannon": 3.20,
            "syntropy_coherence_pct": 82.0,
            "active_symbols": ["Ψ", "Ω", "∮", "∇S", "ℵ₀"],
        },
        "vault": {
            "total_events": 0,
            "compressed_events": 0,
            "knowledge_nodes": 0,
            "knowledge_relations": 0,
            "hierarchical_epochs": 0,
            "background_contemplations": 0,
            "complexity_level": 0,
            "vault_size_mb": 0.0,
            "max_capacity_gb": 250.0,
        },
        "aegis": {
            "score": 100,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "scanned_files": 0,
        },
        "hardware": local_hw,
        "rf_radar": {
            "active": False,
            "presence_state": "QUIET",
            "confidence": 0.85,
            "active_bssid_count": 0,
            "shannon_entropy": 0.5,
            "total_rf_energy_uw": 0.0,
            "mean_variance": 0.0,
        },
        "atmospheric": {
            "available": False,
            "temperature_c": 0.0,
            "apparent_temperature_c": 0.0,
            "relative_humidity_pct": 0,
            "surface_pressure_hpa": 1013.0,
            "wind_speed_kmh": 0.0,
            "cloud_cover_pct": 0,
            "weather_description": "Telemetría local",
        },
        "music": {
            "playing": False,
            "media_title": "",
            "progress": 0.0,
            "volume": 70,
            "time_pos_text": "0:00",
            "duration_text": "0:00",
        },
        "subsystems": {
            "online": 1,
            "degraded": 0,
            "offline": 0,
            "total": 1,
            "autonomous_cycles": 0,
            "autonomous_running": False,
        },
    }


def _extract_temps(hw_resp: Dict[str, Any]) -> Tuple[float, float, float]:
    temps = hw_resp.get("temperatures") if isinstance(hw_resp.get("temperatures"), dict) else {}
    cpu_t = 0.0
    gpu_t = 0.0
    nvme_t = 0.0
    for key in ("k10temp", "coretemp", "acpitz"):
        arr = temps.get(key)
        if isinstance(arr, list) and arr and isinstance(arr[0], dict):
            try:
                cpu_t = round(float(arr[0].get("current_c", 0.0)), 1)
                break
            except Exception:
                pass
    for key in ("amdgpu", "nvidia", "nouveau"):
        arr = temps.get(key)
        if isinstance(arr, list) and arr and isinstance(arr[0], dict):
            try:
                gpu_t = round(float(arr[0].get("current_c", 0.0)), 1)
                break
            except Exception:
                pass
    arr_nv = temps.get("nvme")
    if isinstance(arr_nv, list) and arr_nv and isinstance(arr_nv[0], dict):
        try:
            nvme_t = round(float(arr_nv[0].get("current_c", 0.0)), 1)
        except Exception:
            pass
    return cpu_t, gpu_t, nvme_t


def collect_tardis_snapshot(
    api_base: Optional[str] = None,
    timeout: float = 0.65,
    use_cache_sec: float = 2.0,
    fetch_http: bool = True,
) -> Dict[str, Any]:
    """
    Recolecta una instantánea completa y fresca de la información viva de TARDIS.
    Combina manifiesto visual, endpoints locales del nodo :8757 y telemetría directa de kernel.
    """
    global _CACHE_TS, _CACHE_DATA
    now = time.time()
    if use_cache_sec > 0.0:
        with _CACHE_LOCK:
            if _CACHE_DATA is not None and (now - _CACHE_TS) <= use_cache_sec:
                return copy.deepcopy(_CACHE_DATA)

    snap = default_snapshot()
    base = (api_base or os.environ.get("GIA_API_URL") or "http://127.0.0.1:8757").rstrip("/")
    token = _read_api_token()

    # Intentar leer SYNC_HUB en memoria si estamos dentro del proceso de TARDIS
    try:
        import sys
        otc = sys.modules.get("omni_temporal_control")
        if otc is not None and hasattr(otc, "SYNC_HUB"):
            c_state = getattr(otc.SYNC_HUB, "causal_state", None)
            if isinstance(c_state, dict):
                snap["causal"]["psi"] = float(c_state.get("psi", snap["causal"]["psi"]))
                snap["causal"]["sintropy"] = float(c_state.get("sintropy", snap["causal"]["sintropy"]))
                snap["causal"]["phi_adv"] = float(c_state.get("phi_adv", snap["causal"]["phi_adv"]))
                snap["causal"]["o_qco"] = float(c_state.get("o_qco", snap["causal"]["o_qco"]))
                snap["causal"]["s_geom"] = float(c_state.get("s_geom", snap["causal"]["s_geom"]))
                snap["causal"]["q_topo"] = int(c_state.get("q_topo", snap["causal"]["q_topo"]))
                snap["causal"]["bifurcation"] = _sanitize_text(
                    c_state.get("bifurcation", snap["causal"]["bifurcation"]), 42
                )
    except Exception:
        pass

    endpoints = {
        "status": f"{base}/api/status",
        "sync": f"{base}/api/sync?client_id=tardis-video&since=0",
        "os": f"{base}/api/os/status",
        "hardware": f"{base}/api/hardware/status",
        "cognitive": f"{base}/api/cognitive/spectrogram",
        "aegis": f"{base}/api/aegis/status",
        "rf": f"{base}/api/rf_radar/status",
        "atmo": f"{base}/api/sensors/atmospheric",
        "music": f"{base}/api/music/status",
        "subsystems": f"{base}/api/hub/subsystems",
        "autonomous": f"{base}/api/autonomous/status",
    }

    fetched: Dict[str, Optional[Dict[str, Any]]] = {}
    if fetch_http:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                fut_map = {
                    ex.submit(_http_get_json, url, token, timeout): key
                    for key, url in endpoints.items()
                }
                for fut in concurrent.futures.as_completed(fut_map, timeout=max(0.9, timeout * 2.2)):
                    k = fut_map[fut]
                    try:
                        fetched[k] = fut.result()
                    except Exception:
                        fetched[k] = None
        except Exception:
            pass

    live_hits = sum(1 for v in fetched.values() if isinstance(v, dict))
    snap["live_api"] = live_hits > 0

    # 1. Status & Vault 250GB
    st = fetched.get("status")
    if isinstance(st, dict):
        snap["core"]["model"] = _sanitize_text(st.get("model") or snap["core"]["model"], 48)
        models = st.get("models")
        if isinstance(models, list):
            snap["core"]["models_count"] = len(models)
        cfg = st.get("config") if isinstance(st.get("config"), dict) else {}
        if cfg.get("num_ctx"):
            snap["core"]["num_ctx"] = int(cfg["num_ctx"])
        snap["core"]["active_tasks_count"] = int(st.get("active_tasks_count", 0) or 0)
        v = st.get("vault_250gb") if isinstance(st.get("vault_250gb"), dict) else {}
        if v:
            snap["vault"].update({
                "total_events": int(v.get("total_events", 0) or 0),
                "compressed_events": int(v.get("compressed_events", 0) or 0),
                "knowledge_nodes": int(v.get("knowledge_nodes", 0) or 0),
                "knowledge_relations": int(v.get("knowledge_relations", 0) or 0),
                "hierarchical_epochs": int(v.get("hierarchical_epochs", 0) or 0),
                "background_contemplations": int(v.get("background_contemplations", 0) or 0),
                "complexity_level": int(v.get("complexity_level", 0) or 0),
                "vault_size_mb": round(float(v.get("vault_size_mb", 0.0) or 0.0), 2),
                "max_capacity_gb": round(float(v.get("max_capacity_gb", 250.0) or 250.0), 1),
            })

    # 2. Causal / Sync
    sy = fetched.get("sync")
    if isinstance(sy, dict):
        snap["causal"]["lamport"] = int(sy.get("lamport", snap["causal"]["lamport"]) or 0)
        c = sy.get("causal") if isinstance(sy.get("causal"), dict) else {}
        if c:
            snap["causal"]["psi"] = round(float(c.get("psi", snap["causal"]["psi"])), 4)
            snap["causal"]["sintropy"] = round(float(c.get("sintropy", snap["causal"]["sintropy"])), 4)
            snap["causal"]["phi_adv"] = round(float(c.get("phi_adv", snap["causal"]["phi_adv"])), 4)
            snap["causal"]["o_qco"] = round(float(c.get("o_qco", snap["causal"]["o_qco"])), 4)
            snap["causal"]["s_geom"] = round(float(c.get("s_geom", snap["causal"]["s_geom"])), 4)
            snap["causal"]["q_topo"] = int(c.get("q_topo", snap["causal"]["q_topo"]) or 3)
            snap["causal"]["bifurcation"] = _sanitize_text(c.get("bifurcation", snap["causal"]["bifurcation"]), 36)
            snap["causal"]["active_clients"] = int(c.get("active_clients", snap["causal"]["active_clients"]) or 1)
            snap["causal"]["cone_active"] = bool(c.get("coneActive", True))
            snap["causal"]["oscilloscope_active"] = bool(c.get("oscilloscopeActive", True))

    # 3. OS & Hardware
    os_st = fetched.get("os")
    if isinstance(os_st, dict):
        if "cpu_percent" in os_st:
            snap["hardware"]["cpu_percent"] = round(float(os_st["cpu_percent"]), 1)
        if "ram_percent" in os_st:
            snap["hardware"]["ram_percent"] = round(float(os_st["ram_percent"]), 1)
        if "ram_total_gb" in os_st:
            tot = float(os_st["ram_total_gb"])
            avail = float(os_st.get("ram_available_gb", 0.0))
            snap["hardware"]["ram_total_gb"] = round(tot, 2)
            snap["hardware"]["ram_available_gb"] = round(avail, 2)
            snap["hardware"]["ram_used_gb"] = round(max(0.0, tot - avail), 2)
        bat = os_st.get("battery") if isinstance(os_st.get("battery"), dict) else {}
        if "percent" in bat:
            snap["hardware"]["battery_percent"] = round(float(bat["percent"]), 1)
            snap["hardware"]["power_plugged"] = bool(bat.get("plugged", True))

    hw_st = fetched.get("hardware")
    if isinstance(hw_st, dict):
        cpu_t, gpu_t, nvme_t = _extract_temps(hw_st)
        if cpu_t > 0:
            snap["hardware"]["cpu_temp_c"] = cpu_t
        if gpu_t > 0:
            snap["hardware"]["gpu_temp_c"] = gpu_t
        if nvme_t > 0:
            snap["hardware"]["nvme_temp_c"] = nvme_t
        pp = hw_st.get("power_profile") if isinstance(hw_st.get("power_profile"), dict) else {}
        if pp.get("active_profile"):
            snap["hardware"]["power_profile"] = _sanitize_text(pp["active_profile"], 24)

    # 4. Cognitive spectrogram
    cog = fetched.get("cognitive")
    if isinstance(cog, dict):
        if "entropy_shannon" in cog:
            snap["cognitive"]["entropy_shannon"] = round(float(cog["entropy_shannon"]), 3)
        if "syntropy_coherence_pct" in cog:
            snap["cognitive"]["syntropy_coherence_pct"] = round(float(cog["syntropy_coherence_pct"]), 1)
        syms = cog.get("active_symbols")
        if isinstance(syms, list) and syms:
            snap["cognitive"]["active_symbols"] = [_sanitize_text(s, 28) for s in syms[:6]]

    # 5. AEGIS-Ω
    ae = fetched.get("aegis")
    if isinstance(ae, dict):
        aud = ae.get("audit") if isinstance(ae.get("audit"), dict) else ae
        if "score" in aud:
            snap["aegis"]["score"] = int(round(float(aud["score"])))
        counts = aud.get("counts") if isinstance(aud.get("counts"), dict) else {}
        snap["aegis"]["critical"] = int(counts.get("crítico", counts.get("critical", 0)) or 0)
        snap["aegis"]["high"] = int(counts.get("alto", counts.get("high", 0)) or 0)
        snap["aegis"]["medium"] = int(counts.get("medio", counts.get("medium", 0)) or 0)
        snap["aegis"]["low"] = int(counts.get("bajo", counts.get("low", 0)) or 0)
        pol = aud.get("policy") if isinstance(aud.get("policy"), dict) else {}
        snap["aegis"]["scanned_files"] = int(pol.get("scanned_files", 0) or 0)

    # 6. RF Presence Radar
    rf = fetched.get("rf")
    if isinstance(rf, dict):
        snap["rf_radar"]["active"] = bool(rf.get("active", False))
        snap["rf_radar"]["presence_state"] = _sanitize_text(rf.get("presence_state", "QUIET"), 20).upper()
        snap["rf_radar"]["confidence"] = round(float(rf.get("confidence", 0.85) or 0.0), 2)
        snap["rf_radar"]["active_bssid_count"] = int(rf.get("active_bssid_count", 0) or 0)
        snap["rf_radar"]["shannon_entropy"] = round(float(rf.get("shannon_entropy", 0.5) or 0.0), 3)
        snap["rf_radar"]["total_rf_energy_uw"] = round(float(rf.get("total_rf_energy_uw", 0.0) or 0.0), 4)
        snap["rf_radar"]["mean_variance"] = round(float(rf.get("mean_variance", 0.0) or 0.0), 3)

    # 7. Atmospheric (strictly sanitized — no coordinates)
    at = fetched.get("atmo")
    if isinstance(at, dict):
        atm = at.get("atmospheric") if isinstance(at.get("atmospheric"), dict) else at
        if "temperature_c" in atm:
            snap["atmospheric"]["available"] = True
            snap["atmospheric"]["temperature_c"] = round(float(atm.get("temperature_c", 0.0)), 1)
            snap["atmospheric"]["apparent_temperature_c"] = round(float(atm.get("apparent_temperature_c", atm.get("temperature_c", 0.0))), 1)
            snap["atmospheric"]["relative_humidity_pct"] = int(round(float(atm.get("relative_humidity_pct", 0))))
            snap["atmospheric"]["surface_pressure_hpa"] = round(float(atm.get("surface_pressure_hpa", 1013.0)), 1)
            snap["atmospheric"]["wind_speed_kmh"] = round(float(atm.get("wind_speed_kmh", 0.0)), 1)
            snap["atmospheric"]["cloud_cover_pct"] = int(round(float(atm.get("cloud_cover_pct", 0))))
            snap["atmospheric"]["weather_description"] = _sanitize_text(atm.get("weather_description", "Despejado"), 40)

    # 8. Music Maestro
    mu = fetched.get("music")
    if isinstance(mu, dict):
        pb = mu.get("playback") if isinstance(mu.get("playback"), dict) else {}
        snap["music"]["playing"] = bool(pb.get("playing", False) and not pb.get("paused", False))
        snap["music"]["media_title"] = _sanitize_text(pb.get("media_title", ""), 64)
        snap["music"]["progress"] = round(float(pb.get("progress", 0.0) or 0.0), 1)
        snap["music"]["volume"] = int(round(float(pb.get("volume", 70) or 70)))
        snap["music"]["time_pos_text"] = _sanitize_text(pb.get("time_pos_text", "0:00"), 12)
        snap["music"]["duration_text"] = _sanitize_text(pb.get("duration_text", "0:00"), 12)

    # 9. Subsystems & Autonomous controller
    subs = fetched.get("subsystems")
    if isinstance(subs, dict):
        cnt = subs.get("counts") if isinstance(subs.get("counts"), dict) else {}
        on = int(cnt.get("online", 0) or 0)
        deg = int(cnt.get("degraded", 0) or 0)
        off = int(cnt.get("offline", 0) or 0)
        tot = on + deg + off
        if tot > 0:
            snap["subsystems"]["online"] = on
            snap["subsystems"]["degraded"] = deg
            snap["subsystems"]["offline"] = off
            snap["subsystems"]["total"] = tot

    aut = fetched.get("autonomous")
    if isinstance(aut, dict):
        snap["subsystems"]["autonomous_cycles"] = int(aut.get("cycle_count", aut.get("cycles_completed", 0)) or 0)
        snap["subsystems"]["autonomous_running"] = bool(aut.get("running", False))

    # Sanitizar campos del manifiesto visual
    vm = snap["visual_manifest"]
    vm["title"] = _sanitize_text(vm.get("title", ""), 90)
    vm["statement"] = _sanitize_text(vm.get("statement", ""), 260)
    vm["mood"] = _sanitize_text(vm.get("mood", "sovereign_equilibrium"), 40)

    with _CACHE_LOCK:
        _CACHE_TS = time.time()
        _CACHE_DATA = copy.deepcopy(snap)

    return snap


def summarize_snapshot(snap: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Produce un resumen compacto y seguro para metadatos de respuesta y subtítulos Telegram."""
    if not isinstance(snap, dict):
        return {}
    c = snap.get("causal", {})
    hw = snap.get("hardware", {})
    ae = snap.get("aegis", {})
    vm = snap.get("visual_manifest", {})
    sub = snap.get("subsystems", {})
    vault = snap.get("vault", {})
    return {
        "psi": round(float(c.get("psi", 0.892)), 2),
        "sintropy": round(float(c.get("sintropy", 0.965)), 2),
        "aegis_score": int(ae.get("score", 100)),
        "cpu_percent": round(float(hw.get("cpu_percent", 0.0)), 0),
        "cpu_temp_c": round(float(hw.get("cpu_temp_c", 0.0)), 1),
        "ram_percent": round(float(hw.get("ram_percent", 0.0)), 0),
        "mood": str(vm.get("mood", "sovereign_equilibrium")),
        "subsystems_online": int(sub.get("online", 0)),
        "subsystems_total": int(sub.get("total", 0)),
        "vault_events": int(vault.get("total_events", 0)),
        "model": str(snap.get("core", {}).get("model", "TARDIS-NEURAL-SPACE-KAIJU")),
        "live_api": bool(snap.get("live_api", False)),
    }


def format_caption_telemetry(summary: Optional[Dict[str, Any]]) -> str:
    """Formatea una etiqueta compacta de telemetría viva para el pie de video en Telegram."""
    if not isinstance(summary, dict) or not summary:
        return ""
    parts = [
        f"Ψ {summary.get('psi', 0.89):.2f}",
        f"AEGIS {summary.get('aegis_score', 100)}/100",
    ]
    subs_tot = int(summary.get("subsystems_total", 0) or 0)
    if subs_tot > 0:
        parts.append(f"Subs {summary.get('subsystems_online', 0)}/{subs_tot}")
    temp = float(summary.get("cpu_temp_c", 0.0) or 0.0)
    if temp > 0:
        parts.append(f"{temp:.0f}°C")
    return " · ".join(parts)
