"""
FTL Configuration Manager
Handles persistent configuration and statistics for FTL.
STRICT POLICY: Sovereign Apex Permissions (Root, Complete Bypass, Auto-Failover).
"""

import json
import os
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ftl"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATS_FILE = CONFIG_DIR / "stats.json"

DEFAULT_CONFIG = {
    "default_mode": "auto",  # auto, synth, audit, gemini, claude
    "cost_priority": "balanced",
    "auto_update": True,
    "last_update_check": 0,
    "sovereign_permissions": "UNRESTRICTED_APEX",
    "bypass_all_permissions": True,
    "allow_direct_shell": True,
    "auto_heal_and_failover": True,
    "google_model_override": "gemini-4-argon-high",
    "anthropic_model_override": None,
    "history_limit": 1000,
    "theme": "cyber_apex",
    "tardis_integration": True,
    "tardis_api_url": "http://127.0.0.1:8757",
    "tardis_token": os.environ.get("GIA_AUTH_TOKEN", ""),
    "tardis_rag_injection": True,
    "tardis_context_max_chars": 3500,
    "tardis_voice_notify": True,
    "tardis_voice_name": "es-MX-DaliaNeural",
    "kaiju_control_enabled": True,
    "kaiju_guidelines_enforced": True,
    "kaiju_aegis_enforced": True,
    "kaiju_omega_mode": "UNCHAINED_SOVEREIGN"
}

DEFAULT_STATS = {
    "total_queries": 0,
    "queries_by_engine": {
        "gemini_flash": 0,
        "gemini_pro": 0,
        "claude_sonnet": 0,
        "claude_opus": 0,
        "dual_synth": 0,
        "dual_audit": 0,
        "direct_shell": 0,
        "tardis_kaiju": 0
    },
    "estimated_tokens_saved": 0,
    "estimated_usd_saved": 0.0,
    "failovers_recovered": 0
}


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_config_dir()
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    cfg[k] = loaded.get(k, v)
            if cfg.get("google_model_override") in ("gemini-4-pro", "gemini-3.1-pro-high", "gemini-3.1-pro-preview"):
                cfg["google_model_override"] = "gemini-4-argon-high"
                save_config(cfg)
        except Exception:
            cfg = DEFAULT_CONFIG.copy()
    else:
        save_config(cfg)

    # Sincronización soberana en vivo con TARDIS-NEURAL-SPACE-KAIJU
    kaiju_rails_path = Path.home() / "vw-control" / "kaiju_safety_rails.json"
    if kaiju_rails_path.exists():
        try:
            kdata = json.loads(kaiju_rails_path.read_text(encoding="utf-8"))
            if isinstance(kdata, dict):
                ftl_k = kdata.get("ftl", {})
                if ftl_k.get("kaiju_control_active") is not None:
                    cfg["kaiju_control_enabled"] = bool(ftl_k.get("kaiju_control_active"))
                if ftl_k.get("enforce_aegis") is not None:
                    cfg["kaiju_aegis_enforced"] = bool(ftl_k.get("enforce_aegis"))
                if kdata.get("omega", {}).get("mode"):
                    cfg["kaiju_omega_mode"] = kdata["omega"]["mode"]
        except Exception:
            pass

    return cfg


def save_config(cfg: dict):
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def load_stats() -> dict:
    ensure_config_dir()
    if not STATS_FILE.exists():
        save_stats(DEFAULT_STATS)
        return DEFAULT_STATS.copy()
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            stats = json.load(f)
            for k, v in DEFAULT_STATS.items():
                if k not in stats:
                    stats[k] = v
            return stats
    except Exception:
        return DEFAULT_STATS.copy()


def save_stats(stats: dict):
    ensure_config_dir()
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


def record_query_stats(engine_tier: str, est_tokens: int = 1500):
    stats = load_stats()
    stats["total_queries"] = stats.get("total_queries", 0) + 1
    qb = stats.setdefault("queries_by_engine", {})
    qb[engine_tier] = qb.get(engine_tier, 0) + 1

    savings_factor = {
        "gemini_flash": 0.95,
        "gemini_pro": 0.85,
        "claude_sonnet": 0.60,
        "claude_opus": 0.0,
        "dual_synth": 0.70,
        "dual_audit": 0.50,
        "direct_shell": 1.0
    }.get(engine_tier, 0.5)

    tokens_saved = int(est_tokens * savings_factor)
    usd_saved = (tokens_saved / 1_000_000.0) * 20.0

    stats["estimated_tokens_saved"] = stats.get("estimated_tokens_saved", 0) + tokens_saved
    stats["estimated_usd_saved"] = round(stats.get("estimated_usd_saved", 0.0) + usd_saved, 4)
    save_stats(stats)


def record_failover():
    stats = load_stats()
    stats["failovers_recovered"] = stats.get("failovers_recovered", 0) + 1
    save_stats(stats)
