"""
TARDIS Syntropic Deal & Glitch Analyzer
Evaluates price anomalies, discount percentages, retail clearance phases (.01/.02/.03),
and assigns the Syntropic Deal Gravity Score (0-1000).
"""

import re
from typing import Tuple, Optional
from .models import Deal


class SyntropicDetector:
    GLITCH_KEYWORDS = [
        r"error\s+de\s+precio",
        r"posible\s+error",
        r"glitch",
        r"bug\s+de\s+precio",
        r"precio\s+equivocado",
        r"inversi[oó]n\s+de\s+precio",
        r"se\s+equivocaron",
        r"liquidaci[oó]n\s+total",
        r"remate\s+final",
        r"regalado",
    ]

    DISCOUNT_PATTERNS = [
        r"[-–—]?\s*(\d{1,2})\s*%\s*(?:de\s+descuento|off|dcto)",
        r"con\s+(?:un\s+)?(\d{1,2})\s*%",
        r"hasta\s+(?:un\s+)?[-–—]?\s*(\d{1,2})\s*%",
    ]

    ORIGINAL_PRICE_PATTERNS = [
        r"(?:antes|era|costaba|precio\s+original)\s*[:\$]?\s*([\d,]+(?:\.\d{1,2})?)",
        r"baja\s+de\s*[:\$]?\s*([\d,]+(?:\.\d{1,2})?)",
    ]

    VOUCHER_PATTERNS = [
        r"(?:cup[oó]n|c[oó]digo|code)\s*[:=\s]\s*([A-Z0-9_\-]{3,20})",
        r"aplica\s+(?:el\s+)?c[oó]digo\s+([A-Z0-9_\-]{3,20})",
        r"usa\s+(?:el\s+)?cup[oó]n\s+([A-Z0-9_\-]{3,20})",
    ]

    @classmethod
    def analyze_deal(cls, deal: Deal) -> Deal:
        """Enriches and evaluates a deal in place."""
        title_lower = deal.title.lower()

        # 1. Price sanitization
        try:
            deal.price = float(deal.price)
        except (ValueError, TypeError):
            deal.price = 0.0

        try:
            deal.original_price = float(deal.original_price)
        except (ValueError, TypeError):
            deal.original_price = 0.0

        # Freebie detection
        if deal.price <= 0.0 or "gratis" in title_lower or "100% de descuento" in title_lower:
            deal.is_free = True
            deal.discount_percent = 100.0

        # 2. Extract original price from title if not set
        if deal.original_price <= 0.0 and deal.price > 0.0:
            for pat in cls.ORIGINAL_PRICE_PATTERNS:
                m = re.search(pat, deal.title, re.IGNORECASE)
                if m:
                    try:
                        extracted = float(m.group(1).replace(",", ""))
                        if extracted > deal.price:
                            deal.original_price = extracted
                            break
                    except ValueError:
                        pass

        # 3. Calculate discount percentage
        if deal.original_price > deal.price > 0.0:
            deal.discount_percent = round((1.0 - (deal.price / deal.original_price)) * 100.0, 1)
        elif not deal.is_free:
            # Check title for explicit discount percentage
            for pat in cls.DISCOUNT_PATTERNS:
                m = re.search(pat, deal.title, re.IGNORECASE)
                if m:
                    try:
                        disc = float(m.group(1))
                        if 0 < disc <= 100:
                            deal.discount_percent = disc
                            if deal.price > 0.0 and deal.original_price == 0.0 and disc < 100:
                                deal.original_price = round(deal.price / (1.0 - (disc / 100.0)), 2)
                            break
                    except ValueError:
                        pass

        # 4. Voucher extraction
        if not deal.voucher_code:
            for pat in cls.VOUCHER_PATTERNS:
                m = re.search(pat, deal.title, re.IGNORECASE)
                if m:
                    deal.voucher_code = m.group(1).upper()
                    break

        # 5. Clearance phase detection (.01, .02, .03)
        cents = round((deal.price - int(deal.price)) * 100)
        if cents == 1:
            deal.liquidation_phase = 3  # Phase 3: Final blowout clearance
        elif cents == 2:
            deal.liquidation_phase = 2  # Phase 2: Medium clearance
        elif cents == 3:
            deal.liquidation_phase = 1  # Phase 1: First markdown

        # 6. Glitch & Price Error Detection
        is_glitch = False
        glitch_notes = []

        # Check explicit keywords
        for kw in cls.GLITCH_KEYWORDS:
            m = re.search(kw, title_lower)
            if m:
                is_glitch = True
                glitch_notes.append(f"Palabra clave de error detectada: '{m.group(0)}'")
                break

        # Check discount anomaly
        if deal.discount_percent >= 75.0 and not deal.is_free:
            is_glitch = True
            glitch_notes.append(f"Descuento anómalo ultra-alto ({deal.discount_percent}%)")

        # Check suspicious low price for expensive hardware categories
        high_val_keywords = ["laptop", "rtx", "geforce", "playstation", "ps5", "xbox", "iphone", "ipad", "oled"]
        if any(h in title_lower for h in high_val_keywords) and 0 < deal.price < 1500.0:
            is_glitch = True
            glitch_notes.append(f"Precio sospechosamente bajo para hardware (${deal.price:,.2f})")

        if deal.liquidation_phase == 3:
            glitch_notes.append("Liquidación Fase 3 (.01) detectada")

        deal.is_glitch = is_glitch
        if glitch_notes:
            deal.notes = " | ".join(glitch_notes)

        # 7. Validity & Expiration check
        from .validity import ValidityEngine
        if not ValidityEngine.is_vigente(deal):
            deal.expired = True

        # 8. Calculate Syntropy Score (0 - 1000)
        deal.syntropy_score = cls.calculate_syntropy_score(deal)

        return deal

    @classmethod
    def calculate_syntropy_score(cls, deal: Deal) -> float:
        """
        Calculates deal gravity score (0 to 1000).
        Higher score = higher priority and urgency.
        """
        score = 0.0

        # Discount contribution (0 - 400 pts)
        score += min(400.0, deal.discount_percent * 4.0)

        # Community Temperature contribution (0 - 300 pts)
        if deal.temperature > 0:
            score += min(300.0, (deal.temperature / 10.0))

        # Glitch / Error bonus (200 pts)
        if deal.is_glitch:
            score += 200.0

        # Free item bonus (250 pts)
        if deal.is_free:
            score += 250.0

        # Liquidation phase bonus
        if deal.liquidation_phase == 3:
            score += 150.0
        elif deal.liquidation_phase == 2:
            score += 80.0
        elif deal.liquidation_phase == 1:
            score += 40.0

        # Coupon available bonus
        if deal.voucher_code:
            score += 50.0

        return round(min(1000.0, score), 1)
