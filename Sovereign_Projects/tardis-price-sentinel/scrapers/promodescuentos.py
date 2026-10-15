"""
₪ TARDIS Promodescuentos Scraper & Live Deal Oracle
Extracts hot deals, live price errors, coupons, and community ratings
using structured Vue3 JSON embeddings with STRICT ACTIVE / VIGENTE FILTERING.
Guarantees zero expired deals are returned when only_active is requested.
"""

import json
import re
import time
from typing import List, Optional
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from .base import BaseScraper
from core.models import Deal
from core.detector import SyntropicDetector
from core.validity import ValidityEngine


class PromodescuentosScraper(BaseScraper):
    BASE_URL = "https://www.promodescuentos.com"
    RSS_FEEDS = {
        "todas": "https://www.promodescuentos.com/rss",
        "nuevas": "https://www.promodescuentos.com/rss/nuevas",
        "cupones": "https://www.promodescuentos.com/rss/cupones",
        "discusiones": "https://www.promodescuentos.com/rss/discusiones"
    }

    def _parse_thread_dict(self, th: dict, source_tag: str, only_active: bool = True) -> Optional[Deal]:
        """Parses a Vue3 thread payload and strictly verifies validity/expiration."""
        if not th:
            return None

        thread_id = str(th.get("threadId", ""))
        title = th.get("title", "").strip()
        if not title:
            return None

        is_expired = bool(th.get("isExpired", False))
        status = th.get("status", "")
        deleted_at = th.get("deletedAt")
        end_date = th.get("endDate")
        now_ts = int(time.time())

        # If only_active is required, enforce strict rejection of dead/expired deals
        if only_active:
            if is_expired:
                return None
            if status and status != "Activated":
                return None
            if deleted_at is not None:
                return None
            if end_date and int(end_date) < now_ts:
                return None

        price = float(th.get("price", 0.0) or 0.0)
        next_best = float(th.get("nextBestPrice", 0.0) or 0.0)
        temperature = float(th.get("temperature", 0.0) or 0.0)
        voucher = th.get("voucherCode", "") or ""

        merchant_obj = th.get("merchant") or {}
        merchant_name = merchant_obj.get("merchantName") or "Tienda"

        group_obj = th.get("mainGroup") or {}
        category = group_obj.get("threadGroupName") or "General"

        share_link = th.get("shareableLink") or f"{self.BASE_URL}/ofertas/{th.get('titleSlug', '')}-{thread_id}"

        # Image extraction
        img_obj = th.get("mainImage") or {}
        image_url = ""
        if img_obj.get("path") and img_obj.get("name"):
            image_url = f"https://static.promodescuentos.com/{img_obj['path']}/{img_obj['name']}/re/768x768/qt/60/{img_obj['name']}.jpg"

        deal_id = f"pd_{thread_id}" if thread_id else Deal.generate_id(title, merchant_name, price)
        deal = Deal(
            id=deal_id,
            title=title,
            price=price,
            original_price=next_best,
            merchant=merchant_name,
            category=category,
            link=share_link,
            image_url=image_url,
            voucher_code=voucher,
            temperature=temperature,
            expired=is_expired,
            source=source_tag
        )

        deal = SyntropicDetector.analyze_deal(deal)

        # Final check against ValidityEngine (regexes, past dates, expired patterns)
        if only_active and not ValidityEngine.is_vigente(deal):
            return None

        return deal

    def fetch_live_nuevas(self, limit: int = 35) -> List[Deal]:
        """Scrapes live newest deals directly from /nuevas with Vue3 rich data."""
        url = f"{self.BASE_URL}/nuevas"
        resp = self.safe_get(url)
        if not resp:
            return []

        deals: List[Deal] = []
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            for el in soup.find_all(attrs={"data-vue3": True}):
                try:
                    payload = json.loads(el["data-vue3"])
                    th = payload.get("props", {}).get("thread")
                    deal = self._parse_thread_dict(th, source_tag="promodescuentos_nuevas", only_active=True)
                    if deal:
                        deals.append(deal)
                        if len(deals) >= limit:
                            break
                except Exception:
                    continue
        except Exception:
            pass

        return deals

    def fetch_live_hot(self, limit: int = 35) -> List[Deal]:
        """Scrapes live hot deals directly from /hot with Vue3 rich data."""
        url = f"{self.BASE_URL}/hot"
        resp = self.safe_get(url)
        if not resp:
            return []

        deals: List[Deal] = []
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            for el in soup.find_all(attrs={"data-vue3": True}):
                try:
                    payload = json.loads(el["data-vue3"])
                    th = payload.get("props", {}).get("thread")
                    deal = self._parse_thread_dict(th, source_tag="promodescuentos_hot", only_active=True)
                    if deal:
                        deals.append(deal)
                        if len(deals) >= limit:
                            break
                except Exception:
                    continue
        except Exception:
            pass

        return deals

    def fetch_active_coupons(self, limit: int = 35) -> List[Deal]:
        """Searches specifically for active coupons and promotional codes."""
        return self.search_deals("cupon", limit=limit, only_active=True)

    def search_deals(self, query: str, limit: int = 40, only_active: bool = True) -> List[Deal]:
        """
        Queries Promodescuentos search engine and parses rich Vue3 props JSON.
        When only_active=True, passes hide_expired=1 and discards any expired deals.
        """
        url = f"{self.BASE_URL}/search"
        params = {"q": query}
        if only_active:
            params["hide_expired"] = "1"
            params["order"] = "new"

        resp = self.safe_get(url, params=params)
        if not resp:
            return []

        deals: List[Deal] = []
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            elements = soup.find_all(attrs={"data-vue3": True})
            for el in elements:
                try:
                    payload = json.loads(el["data-vue3"])
                    th = payload.get("props", {}).get("thread")
                    deal = self._parse_thread_dict(th, source_tag="promodescuentos_search", only_active=only_active)
                    if deal:
                        deals.append(deal)
                        if len(deals) >= limit:
                            break
                except Exception:
                    continue
        except Exception:
            pass

        return deals

    def fetch_rss_deals(self, feed_name: str = "todas", only_active: bool = True) -> List[Deal]:
        """
        Fetches and parses deals from official Promodescuentos RSS feeds.
        Filters out expired deals and stale items older than 48 hours.
        """
        url = self.RSS_FEEDS.get(feed_name, self.RSS_FEEDS["todas"])
        resp = self.safe_get(url)
        if not resp:
            return []

        deals: List[Deal] = []
        now_dt = datetime.now(timezone.utc)

        try:
            soup = BeautifulSoup(resp.content, "xml")
            items = soup.find_all("item")
            for item in items:
                title = item.title.text.strip() if item.title else ""
                link = item.link.text.strip() if item.link else ""
                category = item.category.text.strip() if item.category else "General"
                pub_date = item.pubDate.text.strip() if item.pubDate else ""
                desc_html = item.description.text if item.description else ""

                if not title:
                    continue

                # Recency check: reject RSS deals older than 48h
                if pub_date:
                    try:
                        dt = parsedate_to_datetime(pub_date)
                        if (now_dt - dt).total_seconds() > (48 * 3600):
                            continue
                    except Exception:
                        pass

                # Extract price and store from desc: e.g. <strong>$350 - Steam</strong>
                price = 0.0
                merchant = "Promodescuentos"
                image_url = ""

                price_match = re.search(r"<strong>\s*\$([\d,]+(?:\.\d{1,2})?)\s*(?:-\s*([^<]+))?</strong>", desc_html)
                if price_match:
                    try:
                        price = float(price_match.group(1).replace(",", ""))
                    except ValueError:
                        price = 0.0
                    if price_match.group(2):
                        merchant = price_match.group(2).strip()

                img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc_html)
                if img_match:
                    image_url = img_match.group(1)

                deal_id = Deal.generate_id(title, merchant, price)
                deal = Deal(
                    id=deal_id,
                    title=title,
                    price=price,
                    merchant=merchant,
                    category=category,
                    link=link,
                    image_url=image_url,
                    source=f"promodescuentos_rss_{feed_name}"
                )
                deal = SyntropicDetector.analyze_deal(deal)

                if only_active and not ValidityEngine.is_vigente(deal):
                    continue

                deals.append(deal)
        except Exception:
            pass

        return deals

    def fetch_glitches_and_errors(self) -> List[Deal]:
        """
        Specific scan strictly for ACTIVE price errors, glitches, and anomalies.
        Excludes any expired or fixed errors.
        """
        queries = ["error de precio", "posible error", "bug de precio", "remate liquidación"]
        all_glitches: List[Deal] = []
        seen_ids = set()

        for q in queries:
            results = self.search_deals(q, limit=20, only_active=True)
            for d in results:
                if d.id not in seen_ids and ValidityEngine.is_vigente(d):
                    seen_ids.add(d.id)
                    all_glitches.append(d)

        all_glitches.sort(key=lambda x: x.syntropy_score, reverse=True)
        return all_glitches
