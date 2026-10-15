"""
₪ TARDIS Mexican Retail Liquidation & Clearance Scraper
Tracks store clearance (.01, .02, .03) across Walmart, Bodega Aurrera,
Chedraui, Soriana, Liverpool, and Sears in Mexico.
Enforces strict filtering: only active and vigente liquidaciones are gathered.
"""

from typing import List
from core.models import Deal
from core.validity import ValidityEngine
from .promodescuentos import PromodescuentosScraper


class LiquidacionesScraper:
    def __init__(self):
        self.pd_scraper = PromodescuentosScraper()

    def fetch_liquidaciones(self, limit: int = 40) -> List[Deal]:
        """
        Gathers clearance and closeout deals with special attention to .01/.02/.03 prices.
        Strictly returns only active and unexpired deals.
        """
        queries = [
            "liquidación walmart",
            "liquidación aurrera",
            "liquidación bodega",
            "liquidación chedraui",
            "liquidación liverpool",
            "remate",
            ".01"
        ]

        seen_ids = set()
        liquidaciones: List[Deal] = []

        for q in queries:
            results = self.pd_scraper.search_deals(q, limit=15, only_active=True)
            for d in results:
                if d.id not in seen_ids and ValidityEngine.is_vigente(d):
                    seen_ids.add(d.id)
                    # Boost syntropy score for physical or retail liquidation
                    if d.liquidation_phase > 0:
                        d.syntropy_score += 100.0
                    liquidaciones.append(d)
                if len(liquidaciones) >= limit:
                    break
            if len(liquidaciones) >= limit:
                break

        # Sort by phase and syntropy score
        liquidaciones.sort(key=lambda x: (x.liquidation_phase, x.syntropy_score), reverse=True)
        return liquidaciones
