"""
₪ TARDIS :: Syntropic Deal Validity & Expiry Engine
Ensures the system searches, ingests, and displays STRICTLY ACTIVE (VIGENTES) offers.
Detects expired deals via API flags, community markings, title regexes, temporal windows,
and live thread status inspection.
"""

import re
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

from .models import Deal


class ValidityEngine:
    # Regex patterns indicating expired, finished, or out-of-stock deals
    EXPIRED_KEYWORDS = [
        r"\b(?:agotad[oa]s?|expirad[oa]s?|finalizad[oa]s?|terminad[oa]s?|termin[oó]|vencid[oa]s?)\b",
        r"\b(?:sin\s+stock|out\s+of\s+stock|sold\s+out|ya\s+no\s+hay|no\s+disponible)\b",
        r"\b(?:pausad[oa]s?|cancelad[oa]s?|cerrad[oa]s?|venci[oó])\b",
        r"\[\s*(?:agotad[oa]|expirad[oa]|finalizad[oa]|terminad[oa]|termin[oó]|cerrad[oa]|vencid[oa])\s*\]",
        r"\(\s*(?:agotad[oa]|expirad[oa]|finalizad[oa]|terminad[oa]|termin[oó]|cerrad[oa]|vencid[oa])\s*\)",
    ]

    # Specific date patterns in title referring to days before today (Sept 25, 2026)
    # E.g. "Cupones 20 Septiembre", "Válido 19 de Septiembre"
    EXPIRED_DATE_PATTERNS = [
        r"(?:cupon(?:es)?|válido|valido|oferta)\s+(?:del?\s+)?(?:[0-1]?[0-9]|2[0-4])\s+de?\s+septiembre",
        r"(?:[0-1]?[0-9]|2[0-4])\s+septiembre\s*(?:[-–:]|\b)",
    ]

    @classmethod
    def is_vigente(cls, deal: Deal) -> bool:
        """
        Determines if a deal is strictly active (vigente).
        Returns True if the deal is active, False if expired.
        """
        # 1. Direct model flag
        if deal.expired:
            return False

        # 2. Check title against expired patterns
        title_lower = deal.title.lower()
        for pat in cls.EXPIRED_KEYWORDS:
            if re.search(pat, title_lower):
                return False

        # 3. Check for specific past date references in title
        for pat in cls.EXPIRED_DATE_PATTERNS:
            if re.search(pat, title_lower):
                return False

        # 4. Check notes for expired indicators
        if deal.notes:
            notes_lower = deal.notes.lower()
            for pat in cls.EXPIRED_KEYWORDS:
                if re.search(pat, notes_lower):
                    return False

        # 5. Price error / glitch freshness check
        # Price errors and glitches usually last minutes to hours.
        # If a glitch deal was created more than 48 hours ago without updates, consider expired.
        if deal.is_glitch and deal.created_at:
            try:
                created_dt = datetime.fromisoformat(deal.created_at)
                age_hours = (datetime.now() - created_dt).total_seconds() / 3600.0
                if age_hours > 72.0:
                    return False
            except Exception:
                pass

        return True

    @classmethod
    def check_live_thread(cls, url: str, timeout: int = 4) -> Optional[bool]:
        """
        Queries Promodescuentos or merchant URL live to verify isExpired status.
        Returns: True (vigente), False (expired), or None (inconclusive / network error).
        """
        if not url or not url.startswith("http"):
            return None

        if "promodescuentos.com" in url:
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                resp = requests.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 404:
                    return False
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Check Vue3 thread prop
                    for el in soup.find_all(attrs={"data-vue3": True}):
                        try:
                            import json
                            data = json.loads(el["data-vue3"])
                            th = data.get("props", {}).get("thread", {})
                            if th:
                                is_expired = bool(th.get("isExpired", False))
                                status = th.get("status", "")
                                if is_expired or (status and status != "Activated"):
                                    return False
                                return True
                        except Exception:
                            pass
                    # Check for generic expired banners
                    if "Esta oferta ha finalizado" in resp.text or "Oferta expirada" in resp.text:
                        return False
                    return True
            except Exception:
                return None

        return None

    @classmethod
    def audit_and_purge_expired(cls, storage, verify_live: bool = False) -> Dict[str, int]:
        """
        Scans all deals in the database.
        Marks any expired or stale deal with expired = 1.
        Returns a summary dictionary of audited deals.
        """
        all_deals = storage.list_deals(limit=1000, include_expired=True)
        marked_expired = 0
        active_count = 0

        for deal in all_deals:
            was_expired = deal.expired
            is_active = cls.is_vigente(deal)

            if not is_active and not was_expired:
                deal.expired = True
                storage.save_deal(deal)
                marked_expired += 1
            elif is_active:
                if verify_live and deal.link and "promodescuentos.com" in deal.link:
                    live_status = cls.check_live_thread(deal.link)
                    if live_status is False:
                        deal.expired = True
                        storage.save_deal(deal)
                        marked_expired += 1
                        continue
                active_count += 1

        return {
            "total_audited": len(all_deals),
            "marked_expired": marked_expired,
            "active_vigentes": active_count
        }
