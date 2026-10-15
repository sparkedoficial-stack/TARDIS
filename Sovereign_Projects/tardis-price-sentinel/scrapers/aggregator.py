"""
₪ TARDIS Master Multi-Source Aggregator & Price Arbitrage Engine
Orchestrates concurrent scraping across all platforms, enforces 100% active (vigente)
guarantees, and performs cross-merchant price arbitrage analysis.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from core.models import Deal, WatchItem
from core.storage import Storage
from core.notifier import Notifier
from core.validity import ValidityEngine
from .promodescuentos import PromodescuentosScraper
from .mercadolibre import MercadoLibreScraper
from .liquidaciones import LiquidacionesScraper


class DealAggregator:
    def __init__(self, storage: Optional[Storage] = None, notifier: Optional[Notifier] = None):
        self.storage = storage or Storage()
        self.notifier = notifier or Notifier()
        self.pd_scraper = PromodescuentosScraper()
        self.ml_scraper = MercadoLibreScraper()
        self.liq_scraper = LiquidacionesScraper()

    def scan_all(self, verify_live: bool = False) -> Dict[str, Any]:
        """
        Executes a concurrent sweep across all scrapers for STRICTLY ACTIVE (VIGENTES) deals,
        saves them to database, cleans expired entries, and triggers notifications for glitches.
        """
        all_deals: List[Deal] = []
        new_count = 0
        glitch_count = 0

        tasks = {
            "pd_live_hot": lambda: self.pd_scraper.fetch_live_hot(limit=35),
            "pd_live_nuevas": lambda: self.pd_scraper.fetch_live_nuevas(limit=35),
            "pd_cupones_vigentes": lambda: self.pd_scraper.fetch_active_coupons(limit=35),
            "pd_glitches_vigentes": lambda: self.pd_scraper.fetch_glitches_and_errors(),
            "ml_ofertas_vigentes": lambda: self.ml_scraper.fetch_deals(limit=50),
            "liquidaciones_vigentes": lambda: self.liq_scraper.fetch_liquidaciones(limit=40),
        }

        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_name = {executor.submit(func): name for name, func in tasks.items()}
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    deals = future.result()
                    # Filter only active deals
                    active_deals = [d for d in deals if ValidityEngine.is_vigente(d) and not d.expired]
                    all_deals.extend(active_deals)
                except Exception:
                    pass

        # Deduplicate deals by ID, keeping highest syntropy score
        unique_deals: Dict[str, Deal] = {}
        for d in all_deals:
            if d.id not in unique_deals or d.syntropy_score > unique_deals[d.id].syntropy_score:
                unique_deals[d.id] = d

        # Save to database and evaluate alerts
        watchlist = self.storage.list_watchlist()
        for deal in unique_deals.values():
            # Guarantee deal is marked vigente
            deal.expired = False
            is_new = self.storage.save_deal(deal)
            if is_new:
                new_count += 1

            if deal.is_glitch:
                glitch_count += 1
                if is_new:
                    self.notifier.notify_deal(deal, reason="🚨 Error de Precio Vigente Detectado")
                    self.storage.record_alert(
                        deal_id=deal.id,
                        message=f"Glitch vigente en {deal.merchant}: {deal.title} por ${deal.price:,.2f}",
                        alert_type="glitch",
                        sent_desktop=True
                    )

            # Check watchlist
            self._check_watchlist_match(deal, watchlist, is_new)

        # Audit and mark any existing stale deals in database as expired
        audit_res = ValidityEngine.audit_and_purge_expired(self.storage, verify_live=verify_live)

        return {
            "total_collected": len(unique_deals),
            "new_deals": new_count,
            "glitches_detected": glitch_count,
            "purged_expired": audit_res.get("marked_expired", 0),
            "active_vigentes_in_db": audit_res.get("active_vigentes", 0),
            "status": "success"
        }

    def _check_watchlist_match(self, deal: Deal, watchlist: List[WatchItem], is_new: bool):
        title_lower = deal.title.lower()
        for item in watchlist:
            if not item.enabled:
                continue

            # Check keyword match
            if item.keyword.lower() in title_lower:
                # Check max price constraint
                if item.max_price is not None and deal.price > item.max_price:
                    continue
                # Check min discount constraint
                if item.min_discount is not None and deal.discount_percent < item.min_discount:
                    continue

                self.storage.update_watch_matched(item.id)
                if is_new and not deal.expired and ValidityEngine.is_vigente(deal):
                    self.notifier.notify_deal(
                        deal,
                        reason=f"🎯 Coincidencia en Watchlist: '{item.keyword}'"
                    )
                    self.storage.record_alert(
                        deal_id=deal.id,
                        watch_id=item.id,
                        message=f"Watchlist '{item.keyword}' coincide con {deal.title} (${deal.price:,.2f})",
                        alert_type="watchlist",
                        sent_desktop=True
                    )

    def search_arbitrage(self, query: str) -> Dict[str, Any]:
        """
        Cross-platform price comparison & arbitrage analysis for a given product.
        Only returns STRICTLY ACTIVE (VIGENTES) offers across Amazon, Mercado Libre, Walmart, etc.
        """
        # Search via aggregator (only active)
        deals = self.pd_scraper.search_deals(query, limit=35, only_active=True)

        # Also search in local database (only active)
        local_matches = self.storage.list_deals(query=query, limit=20, include_expired=False)
        combined: Dict[str, Deal] = {d.id: d for d in deals if ValidityEngine.is_vigente(d)}
        for lm in local_matches:
            if lm.id not in combined and ValidityEngine.is_vigente(lm):
                combined[lm.id] = lm

        all_matches = [d for d in combined.values() if d.price > 0 and not d.expired]
        if not all_matches:
            return {
                "query": query,
                "found": 0,
                "lowest_price": 0.0,
                "highest_price": 0.0,
                "max_savings": 0.0,
                "savings_pct": 0.0,
                "best_store": "N/A",
                "best_deal": None,
                "offers": []
            }

        # Sort by price ascending
        all_matches.sort(key=lambda x: x.price)
        lowest = all_matches[0]
        highest = max(all_matches, key=lambda x: x.price)

        max_savings = highest.price - lowest.price
        savings_pct = (max_savings / highest.price * 100.0) if highest.price > 0 else 0.0

        return {
            "query": query,
            "found": len(all_matches),
            "lowest_price": lowest.price,
            "highest_price": highest.price,
            "max_savings": round(max_savings, 2),
            "savings_pct": round(savings_pct, 1),
            "best_store": lowest.merchant,
            "best_deal": lowest.to_dict(),
            "offers": [d.to_dict() for d in all_matches]
        }
