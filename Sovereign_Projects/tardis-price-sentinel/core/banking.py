"""
TARDIS Bank Promotions & Discount Stacking Calculator
Calculates combined savings using official bank bonus matrices (Banorte, BBVA, Citibanamex, HSBC, Nu, etc.)
and coupon code stacking for Mexican retail and e-commerce.
"""

from typing import List, Dict, Any, Optional
from .models import BankPromo


class BankingEngine:
    PROMOS: List[BankPromo] = [
        BankPromo(
            bank_name="Banorte Digital",
            discount_rate=0.15,
            min_purchase=2000.0,
            description="15% de bonificación directa en compras a un solo pago o MSI con Tarjeta de Crédito Digital.",
            conditions="Válido en Amazon, Mercado Libre, Walmart y comercios participantes.",
            card_type="Crédito Digital"
        ),
        BankPromo(
            bank_name="Citibanamex",
            discount_rate=0.15,
            min_purchase=7000.0,
            description="15% de bonificación en compras a meses sin intereses teniendo nómina Citibanamex (10% sin nómina).",
            conditions="Acumulable durante campañas Hot Sale, Buen Fin o ventas especiales.",
            card_type="Crédito"
        ),
        BankPromo(
            bank_name="HSBC Happy Weekend",
            discount_rate=0.15,
            min_purchase=3000.0,
            description="15% de bonificación en compras a crédito (o 20% si recibes nómina en HSBC).",
            conditions="Aplica el último fin de semana del mes en comercios en línea participantes.",
            card_type="Crédito"
        ),
        BankPromo(
            bank_name="BBVA Bonificación",
            discount_rate=0.12,
            min_purchase=2500.0,
            description="12% de bonificación o Puntos BBVA dobles en compras a meses sin intereses.",
            conditions="Activación requerida en app BBVA previo a la compra.",
            card_type="Crédito"
        ),
        BankPromo(
            bank_name="Santander LikeU",
            discount_rate=0.06,
            min_purchase=500.0,
            description="Cashback directo permanente: 4% en gasolineras, 5% en restaurantes/entretenimiento, 6% en farmacias y ventas especiales.",
            conditions="Directo a tu cuenta sin monto mínimo elevado.",
            card_type="Crédito"
        ),
        BankPromo(
            bank_name="Mercado Pago Tarjeta",
            discount_rate=0.10,
            min_purchase=1000.0,
            description="10% a 15% de descuento extra en Mercado Libre usando la tarjeta de crédito Mercado Pago.",
            conditions="Tope de descuento común de $500 a $1,000 MXN.",
            card_type="Crédito"
        ),
        BankPromo(
            bank_name="Nu México",
            discount_rate=0.05,
            min_purchase=1000.0,
            description="Descuento automático por adelanto de mensualidades en planes a Meses Sin Intereses.",
            conditions="Disponible en la app Nu inmediatamente tras procesar la compra a MSI.",
            card_type="Crédito"
        )
    ]

    @classmethod
    def get_promos(cls) -> List[BankPromo]:
        return [p for p in cls.PROMOS if p.active]

    @classmethod
    def calculate_stacking(
        cls,
        base_price: float,
        coupon_percent: float = 0.0,
        coupon_fixed: float = 0.0,
        bank_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculates effective price after applying store coupons + bank bonus.
        """
        original = base_price
        current = base_price

        # 1. Apply coupon fixed
        if coupon_fixed > 0:
            current = max(0.0, current - coupon_fixed)

        # 2. Apply coupon percentage
        if coupon_percent > 0:
            current = max(0.0, current * (1.0 - (coupon_percent / 100.0)))

        coupon_effective_price = current

        # 3. Apply bank bonus if qualified
        selected_promo = None
        bank_bonus_amount = 0.0

        if bank_name:
            for p in cls.PROMOS:
                if p.bank_name.lower() == bank_name.lower() or bank_name.lower() in p.bank_name.lower():
                    selected_promo = p
                    break

        if not selected_promo:
            # Pick best bank promo eligible for this price
            eligible = [p for p in cls.PROMOS if p.min_purchase <= coupon_effective_price]
            if eligible:
                selected_promo = max(eligible, key=lambda x: x.discount_rate)

        if selected_promo and coupon_effective_price >= selected_promo.min_purchase:
            bank_bonus_amount = coupon_effective_price * selected_promo.discount_rate
            final_effective_price = coupon_effective_price - bank_bonus_amount
        else:
            final_effective_price = coupon_effective_price

        total_savings = original - final_effective_price
        total_savings_pct = (total_savings / original * 100.0) if original > 0 else 0.0

        return {
            "original_price": round(original, 2),
            "coupon_effective_price": round(coupon_effective_price, 2),
            "bank_promo": selected_promo.bank_name if selected_promo else "Ninguna",
            "bank_bonus_amount": round(bank_bonus_amount, 2),
            "final_effective_price": round(final_effective_price, 2),
            "total_savings": round(total_savings, 2),
            "total_savings_pct": round(total_savings_pct, 1),
            "qualified_for_bank": (selected_promo is not None and coupon_effective_price >= selected_promo.min_purchase)
        }
