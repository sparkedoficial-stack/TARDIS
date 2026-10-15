"""
₪ TARDIS Mercado Libre México Deals Scraper
Extracts live discounts, lightning deals, and clearance promotions from Mercado Libre México.
Enforces strict filtering of active/vigente deals only.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper
from core.models import Deal
from core.detector import SyntropicDetector
from core.validity import ValidityEngine


class MercadoLibreScraper(BaseScraper):
    OFERTAS_URL = "https://www.mercadolibre.com.mx/ofertas"

    def fetch_deals(self, limit: int = 50) -> List[Deal]:
        """Scrapes Mercado Libre México daily offers and lightning discounts, ensuring only active deals."""
        resp = self.safe_get(self.OFERTAS_URL)
        if not resp:
            return []

        deals: List[Deal] = []
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select(".promotions_wrapper .promotion-item, .poly-card, .andes-card, .ui-search-layout__item")
            for card in cards:
                # Check for expired/ended status markers
                card_text_lower = card.text.lower()
                if any(x in card_text_lower for x in ["finalizada", "agotado", "pausada", "sin stock", "publicación finalizada"]):
                    continue

                status_el = card.select_one(".promotion-item__status, .poly-component__status, [class*='ended'], [class*='expired'], [class*='out-of-stock'], [class*='paused']")
                if status_el:
                    s_text = status_el.text.lower()
                    if any(x in s_text for x in ["finalizada", "agotado", "pausada", "sin stock"]):
                        continue

                title_el = card.select_one(".promotion-item__title, .poly-component__title, .poly-card__title, a[title], .ui-search-item__title")
                price_el = card.select_one(".andes-money-amount__fraction")
                disc_el = card.select_one(".promotion-item__discount, .andes-money-amount__discount, [class*='discount']")
                link_el = card.select_one("a[href]")
                img_el = card.select_one("img[src], img[data-src]")

                if not title_el or not price_el:
                    continue

                title = title_el.text.strip()
                if not title:
                    title = title_el.get("title", "").strip()

                if not title or len(title) < 5:
                    continue

                # Price parsing
                raw_price = price_el.text.strip().replace(",", "")
                try:
                    price = float(raw_price)
                except ValueError:
                    continue

                # Original price parsing if present
                original_price = 0.0
                prev_price_el = card.select_one(".andes-money-amount--previous .andes-money-amount__fraction")
                if prev_price_el:
                    try:
                        original_price = float(prev_price_el.text.strip().replace(",", ""))
                    except ValueError:
                        pass

                # Discount percentage parsing
                discount_percent = 0.0
                if disc_el:
                    disc_match = re.search(r"(\d{1,2})%", disc_el.text)
                    if disc_match:
                        discount_percent = float(disc_match.group(1))

                # Image URL
                image_url = ""
                if img_el:
                    image_url = img_el.get("src") or img_el.get("data-src", "")

                # Link URL
                link = link_el["href"] if link_el else ""
                if "#" in link:
                    link = link.split("#")[0]

                deal_id = Deal.generate_id(title, "Mercado Libre", price)
                deal = Deal(
                    id=deal_id,
                    title=title,
                    price=price,
                    original_price=original_price,
                    discount_percent=discount_percent,
                    merchant="Mercado Libre",
                    category="General",
                    link=link,
                    image_url=image_url,
                    source="mercadolibre_ofertas"
                )
                deal = SyntropicDetector.analyze_deal(deal)

                # Strict validity check
                if not ValidityEngine.is_vigente(deal):
                    continue

                deals.append(deal)
                if len(deals) >= limit:
                    break
        except Exception:
            pass

        return deals
