"""
FTL Self-Improver & Dynamic Evolution Engine
Keeps underlying CLI engines up to date and auto-discovers latest frontier models.
"""

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Tuple

from config import load_config, save_config
from models import registry


class SelfImprover:
    def __init__(self):
        self.registry = registry

    def update_cli_binaries(self) -> Dict[str, str]:
        """Runs native update commands for Claude and AGY."""
        results = {}

        # 1. Update AGY
        try:
            res_agy = subprocess.run(["agy", "update"], capture_output=True, text=True, timeout=30)
            results["agy"] = res_agy.stdout.strip() or res_agy.stderr.strip()
        except Exception as e:
            results["agy"] = f"Failed to check agy update: {str(e)}"

        # 2. Update Claude
        try:
            res_claude = subprocess.run(["claude", "update"], capture_output=True, text=True, timeout=30)
            results["claude"] = res_claude.stdout.strip() or res_claude.stderr.strip()
        except Exception as e:
            results["claude"] = f"Failed to check claude update: {str(e)}"

        return results

    def refresh_frontier_models(self) -> Tuple[bool, List[str]]:
        """
        Re-scans available models and promotes newly released versions
        to the active flagship positions.
        """
        old_flagships = dict(self.registry.flagships)
        self.registry.refresh()
        new_flagships = self.registry.flagships

        changes = []
        for tier, model_id in new_flagships.items():
            if old_flagships.get(tier) != model_id:
                changes.append(f"Promoted {tier} from {old_flagships.get(tier)} -> {model_id}")

        has_changes = len(changes) > 0
        return has_changes, changes

    def perform_full_evolution_cycle(self) -> Dict[str, any]:
        """
        Complete self-improvement cycle:
        1. Updates CLI engines
        2. Discovers and promotes latest Google and Anthropic models
        3. Updates routing calibration and timestamps
        """
        cli_results = self.update_cli_binaries()
        has_new_models, model_promotions = self.refresh_frontier_models()

        cfg = load_config()
        cfg["last_update_check"] = time.time()
        save_config(cfg)

        return {
            "cli_updates": cli_results,
            "new_models_found": has_new_models,
            "promotions": model_promotions,
            "current_flagships": self.registry.flagships
        }

    def check_background_auto_update(self):
        """Runs a background check if 24 hours have elapsed since last check."""
        cfg = load_config()
        if not cfg.get("auto_update", True):
            return

        last_check = cfg.get("last_update_check", 0)
        # Check every 24 hours
        if time.time() - last_check > 86400:
            try:
                self.perform_full_evolution_cycle()
            except Exception:
                pass


# Global self-improver instance
improver = SelfImprover()
