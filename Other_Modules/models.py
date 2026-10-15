"""
FTL Model Registry & Dynamic Discovery Engine
STRICT POLICY: ONLY accepts Frontier Models at Maximum Reasoning Power.
All base, low-tier, and reduced-effort models are strictly filtered out.
"""

import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from config import CONFIG_DIR, load_config

MODELS_CACHE_FILE = CONFIG_DIR / "models_cache.json"
CACHE_TTL_SECONDS = 86400  # 24 hours


@dataclass
class ModelProfile:
    model_id: str
    display_name: str
    provider: str  # "google" or "anthropic"
    tier: str  # "flash-high", "pro-high", "sonnet-thinking", "opus-thinking"
    effort_level: str  # "high", "max"
    context_window: int  # tokens
    cost_factor: float  # Relative cost scale
    abstraction_score: float  # 1.0 - 10.0
    speed_score: float  # 1.0 - 10.0
    is_flagship: bool = False
    is_latest: bool = False


class ModelRegistry:
    def __init__(self):
        self.models: Dict[str, ModelProfile] = {}
        self.flagships: Dict[str, str] = {
            "google_flash_high": "gemini-3.8-flash-high",
            "google_pro_high": "gemini-4-pro",
            "anthropic_sonnet": "sonnet",
            "anthropic_opus": "opus",
            "tardis_kaiju": "TARDIS-NEURAL-SPACE-KAIJU",
            "external_cloud": "groq_deepseek",
            "tardis_infinite": "TARDIS-QUAD-INFINITE-CODE"
        }
        self.load_or_discover()

    def is_frontier_max_power(self, model_id: str, display_name: str) -> bool:
        """
        Enforces strict boundary: ONLY accept frontier models at maximum capability.
        Rejects base models, low/medium effort variants, and legacy/weak models.
        """
        mid = model_id.lower()
        dname = display_name.lower()

        # Sovereign TARDIS and Infinite Code models are always recognized
        if "kaiju" in mid or "tardis" in mid or "infinite" in mid or "deepseek" in mid or "groq" in mid:
            return True

        # Reject any low or medium effort versions
        if "-low" in mid or "-medium" in mid or "low" in dname or "medium" in dname:
            return False

        # Reject Haiku or OSS models
        if "haiku" in mid or "oss" in mid or "gpt-oss" in mid:
            return False

        # Reject base models with no high/thinking capacity
        if "base" in mid or "lite" in mid or "flash-8b" in mid:
            return False

        # Allow Google high-tier frontier models (Gemini 4 Pro, Gemini Pro, Flash High)
        if "gemini" in mid:
            if "high" in mid or "high" in dname or "pro" in mid or "4" in mid:
                return True
            return False

        # Allow Claude frontier thinking models
        if "claude" in mid or mid in ("sonnet", "opus"):
            if "opus" in mid or "sonnet" in mid:
                return True
            return False

        return False

    def discover_from_agy(self) -> List[ModelProfile]:
        """Runs 'agy models' and filters STRICTLY for maximum power frontier models."""
        discovered = []
        try:
            res = subprocess.run(["agy", "models"], capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                for raw_line in res.stdout.splitlines():
                    line = re.sub(r'[\u2800-\u28ff]', '', raw_line).strip()
                    if not line or "Fetching available" in line:
                        continue
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        model_id, display_name = parts[0], parts[1]
                    elif len(parts) == 1:
                        model_id, display_name = parts[0], parts[0]
                    else:
                        continue

                    # STRICT FILTER: Discard any base or sub-maximal models
                    if not self.is_frontier_max_power(model_id, display_name):
                        continue

                    profile = self._classify_frontier_model(model_id, display_name)
                    if profile:
                        discovered.append(profile)
        except Exception:
            pass
        return discovered

    def discover_from_claude(self) -> List[ModelProfile]:
        """Frontier maximum power models for Anthropic Claude."""
        return [
            ModelProfile(
                model_id="opus",
                display_name="Claude Opus 4.6 (Thinking - Max Power)",
                provider="anthropic",
                tier="opus-thinking",
                effort_level="max",
                context_window=200_000,
                cost_factor=10.0,
                abstraction_score=9.9,
                speed_score=6.0,
                is_flagship=True,
                is_latest=True
            ),
            ModelProfile(
                model_id="sonnet",
                display_name="Claude Sonnet 4.6 (Thinking - High Power)",
                provider="anthropic",
                tier="sonnet-thinking",
                effort_level="max",
                context_window=200_000,
                cost_factor=2.5,
                abstraction_score=9.5,
                speed_score=7.8,
                is_flagship=True,
                is_latest=True
            ),
            ModelProfile(
                model_id="claude-opus-4-6-thinking",
                display_name="Claude Opus 4.6 Thinking",
                provider="anthropic",
                tier="opus-thinking",
                effort_level="max",
                context_window=200_000,
                cost_factor=10.0,
                abstraction_score=9.9,
                speed_score=6.0,
                is_flagship=False,
                is_latest=True
            ),
            ModelProfile(
                model_id="claude-sonnet-4-6",
                display_name="Claude Sonnet 4.6 Thinking",
                provider="anthropic",
                tier="sonnet-thinking",
                effort_level="max",
                context_window=200_000,
                cost_factor=2.5,
                abstraction_score=9.5,
                speed_score=7.8,
                is_flagship=False,
                is_latest=True
            )
        ]

    def _classify_frontier_model(self, model_id: str, display_name: str) -> Optional[ModelProfile]:
        mid = model_id.lower()
        if "gemini" in mid:
            match = re.search(r'gemini-(\d+(?:\.\d+)?)', mid)
            version_val = float(match.group(1)) if match else 3.0

            if "flash" in mid and ("high" in mid or version_val >= 3.8):
                tier = "flash-high"
                ctx = 1_000_000
                cost = 0.15
                abs_score = min(7.5 + (version_val - 3.0) * 1.5, 9.5)
                speed = 9.5
            elif "pro" in mid or version_val >= 4.0:
                tier = "pro-high"
                ctx = 2_000_000
                cost = 1.2 if version_val >= 4.0 else 1.0
                abs_score = 10.0 if version_val >= 4.0 else min(8.8 + (version_val - 3.0) * 1.5, 9.7)
                speed = 8.5 if version_val >= 4.0 else 7.5
            else:
                return None

            return ModelProfile(
                model_id=model_id,
                display_name=f"{display_name} [MAX EFFORT]",
                provider="google",
                tier=tier,
                effort_level="high",
                context_window=ctx,
                cost_factor=cost,
                abstraction_score=round(abs_score, 1),
                speed_score=round(speed, 1)
            )
        elif "claude" in mid:
            if "opus" in mid:
                return ModelProfile(
                    model_id=model_id,
                    display_name=f"{display_name} [MAX EFFORT]",
                    provider="anthropic",
                    tier="opus-thinking",
                    effort_level="max",
                    context_window=200_000,
                    cost_factor=10.0,
                    abstraction_score=9.9,
                    speed_score=6.0
                )
            elif "sonnet" in mid:
                return ModelProfile(
                    model_id=model_id,
                    display_name=f"{display_name} [MAX EFFORT]",
                    provider="anthropic",
                    tier="sonnet-thinking",
                    effort_level="max",
                    context_window=200_000,
                    cost_factor=2.5,
                    abstraction_score=9.5,
                    speed_score=7.8
                )
        return None

    def discover_from_tardis(self) -> List[ModelProfile]:
        """Sovereign local quantum neural engine TARDIS-NEURAL-SPACE-KAIJU."""
        return [
            ModelProfile(
                model_id="TARDIS-NEURAL-SPACE-KAIJU",
                display_name="TARDIS-NEURAL-SPACE-KAIJU (MLA + SSM + MoE) [NÚCLEO SOBERANO]",
                provider="tardis",
                tier="kaiju-sovereign",
                effort_level="max",
                context_window=32768,
                cost_factor=0.0,
                abstraction_score=10.0,
                speed_score=10.0,
                is_flagship=True,
                is_latest=True
            )
        ]

    def discover_from_infinite(self) -> List[ModelProfile]:
        """TARDIS Infinite Code (Quad-Model Synthesis + Chinese Cloud Accelerator)."""
        return [
            ModelProfile(
                model_id="TARDIS-QUAD-INFINITE-CODE",
                display_name="TARDIS Infinite Code (Fusión Cuádruple: Flash High + Pro High + Sonnet Thinking + Opus)",
                provider="tardis_infinite",
                tier="quad-infinite-apex",
                effort_level="max",
                context_window=1_000_000,
                cost_factor=1.5,
                abstraction_score=10.0,
                speed_score=9.8,
                is_flagship=True,
                is_latest=True
            ),
            ModelProfile(
                model_id="groq_deepseek",
                display_name="Chinese Cloud API / Groq DeepSeek (300+ tok/s External Token Gateway)",
                provider="external_cloud",
                tier="fast-accelerator",
                effort_level="high",
                context_window=128_000,
                cost_factor=0.05,
                abstraction_score=9.2,
                speed_score=10.0,
                is_flagship=True,
                is_latest=True
            )
        ]

    def discover_from_frontier(self) -> List[ModelProfile]:
        """Sovereign Apex Frontier Models: Gemini 4 Pro & Emerging Checkpoints."""
        return [
            ModelProfile(
                model_id="gemini-4-pro",
                display_name="Gemini 4 Pro (Apex Frontier / Ultra Deep Reasoning) [MAX EFFORT]",
                provider="google",
                tier="pro-high",
                effort_level="high",
                context_window=2_000_000,
                cost_factor=1.2,
                abstraction_score=10.0,
                speed_score=8.5,
                is_flagship=True,
                is_latest=True
            )
        ]

    def refresh(self):
        """Forces rediscovery of ONLY frontier max power models."""
        discovered_agy = self.discover_from_agy()
        discovered_claude = self.discover_from_claude()
        discovered_tardis = self.discover_from_tardis()
        discovered_infinite = self.discover_from_infinite()
        discovered_frontier = self.discover_from_frontier()

        all_models: Dict[str, ModelProfile] = {}
        for m in discovered_agy + discovered_claude + discovered_tardis + discovered_infinite + discovered_frontier:
            all_models[m.model_id] = m

        # Select highest version Google Flash High
        flashes = [m for m in all_models.values() if m.provider == "google" and m.tier == "flash-high"]
        if flashes:
            flashes.sort(key=lambda m: float(re.search(r'(\d+(?:\.\d+)?)', m.model_id).group(1)) if re.search(r'(\d+(?:\.\d+)?)', m.model_id) else 0.0, reverse=True)
            self.flagships["google_flash_high"] = flashes[0].model_id
            flashes[0].is_flagship = True
            flashes[0].is_latest = True

        # Select highest version Google Pro High
        pros = [m for m in all_models.values() if m.provider == "google" and m.tier == "pro-high"]
        if pros:
            pros.sort(key=lambda m: float(re.search(r'(\d+(?:\.\d+)?)', m.model_id).group(1)) if re.search(r'(\d+(?:\.\d+)?)', m.model_id) else 0.0, reverse=True)
            self.flagships["google_pro_high"] = pros[0].model_id
            pros[0].is_flagship = True
            pros[0].is_latest = True

        # Flagships for Anthropic (Frontier Thinking)
        self.flagships["anthropic_sonnet"] = "sonnet"
        self.flagships["anthropic_opus"] = "opus"
        self.flagships["tardis_kaiju"] = "TARDIS-NEURAL-SPACE-KAIJU"
        self.flagships["external_cloud"] = "groq_deepseek"
        self.flagships["tardis_infinite"] = "TARDIS-QUAD-INFINITE-CODE"

        self.models = all_models
        self.save_cache()

    def save_cache(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "timestamp": time.time(),
            "flagships": self.flagships,
            "models": {mid: asdict(p) for mid, p in self.models.items()}
        }
        with open(MODELS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_or_discover(self):
        if MODELS_CACHE_FILE.exists():
            try:
                with open(MODELS_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if time.time() - data.get("timestamp", 0) < CACHE_TTL_SECONDS:
                        self.flagships = data.get("flagships", self.flagships)
                        raw_models = data.get("models", {})
                        # Validate that cached models follow the strict frontier max power rule
                        valid_models = {}
                        for mid, p in raw_models.items():
                            if self.is_frontier_max_power(mid, p.get("display_name", "")):
                                valid_models[mid] = ModelProfile(**p)
                        if valid_models:
                            self.models = valid_models
                            return
            except Exception:
                pass
        self.refresh()

    def validate_model_override(self, model_id: str, provider: str) -> bool:
        """Ensures user override does NOT select a weak or base model."""
        if not self.is_frontier_max_power(model_id, model_id):
            raise ValueError(
                f"RECHAZADO: El modelo '{model_id}' no cumple la Directiva Soberana de Máxima Potencia.\n"
                f"FTL solo acepta modelos de frontera con máximo razonamiento (High / Thinking / Opus / Sonnet)."
            )
        return True

    def get_google_model(self, tier: str = "flash") -> str:
        cfg = load_config()
        override = cfg.get("google_model_override")
        if override:
            self.validate_model_override(override, "google")
            return override
        if tier == "pro":
            return self.flagships.get("google_pro_high", "gemini-4-pro")
        return self.flagships.get("google_flash_high", "gemini-3.8-flash-high")

    def get_anthropic_model(self, tier: str = "sonnet") -> str:
        cfg = load_config()
        override = cfg.get("anthropic_model_override")
        if override:
            self.validate_model_override(override, "anthropic")
            return override
        if tier == "opus":
            return self.flagships.get("anthropic_opus", "opus")
        return self.flagships.get("anthropic_sonnet", "sonnet")

    def get_tardis_model(self) -> str:
        return self.flagships.get("tardis_kaiju", "TARDIS-NEURAL-SPACE-KAIJU")


# Global Registry Instance
registry = ModelRegistry()

