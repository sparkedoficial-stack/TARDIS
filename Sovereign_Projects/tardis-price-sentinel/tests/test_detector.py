"""
Unit tests for SyntropicDetector
"""

import pytest
from core.models import Deal
from core.detector import SyntropicDetector


def test_freebie_detection():
    d = Deal(id="test_free", title="Juego Gratis para Steam", price=0.0)
    d = SyntropicDetector.analyze_deal(d)
    assert d.is_free is True
    assert d.discount_percent == 100.0
    assert d.syntropy_score >= 250.0


def test_glitch_keyword_detection():
    d = Deal(id="test_glitch", title="Amazon: [Error de precio] Tenis Skechers", price=862.0, original_price=2399.0)
    d = SyntropicDetector.analyze_deal(d)
    assert d.is_glitch is True
    assert "error de precio" in d.notes.lower()


def test_discount_anomaly_detection():
    d = Deal(id="test_high_disc", title="Smart TV 65 pulgadas", price=1500.0, original_price=12000.0)
    d = SyntropicDetector.analyze_deal(d)
    assert d.discount_percent == 87.5
    assert d.is_glitch is True


def test_liquidation_phases():
    d1 = Deal(id="liq1", title="Walmart Playera", price=19.01)
    d1 = SyntropicDetector.analyze_deal(d1)
    assert d1.liquidation_phase == 3  # .01 = Phase 3

    d2 = Deal(id="liq2", title="Walmart Juguete", price=99.02)
    d2 = SyntropicDetector.analyze_deal(d2)
    assert d2.liquidation_phase == 2  # .02 = Phase 2

    d3 = Deal(id="liq3", title="Walmart Toalla", price=45.03)
    d3 = SyntropicDetector.analyze_deal(d3)
    assert d3.liquidation_phase == 1  # .03 = Phase 1


def test_voucher_code_extraction():
    d = Deal(id="voucher_test", title="Descuento en compras usando cupón: SUPERGAMER2026", price=500.0)
    d = SyntropicDetector.analyze_deal(d)
    assert d.voucher_code == "SUPERGAMER2026"
