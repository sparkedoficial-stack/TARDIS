"""
Tests for TARDIS ValidityEngine & Strict Active Deal Verification
"""

import pytest
from core.models import Deal
from core.validity import ValidityEngine
from core.detector import SyntropicDetector


def test_validity_engine_active_deal():
    deal = Deal(
        id="test_active",
        title="Laptop Lenovo Legion 5 Pro RTX 4070",
        price=22999.0,
        original_price=31999.0,
        discount_percent=28.1,
        merchant="Amazon México"
    )
    assert ValidityEngine.is_vigente(deal) is True
    assert deal.expired is False


def test_validity_engine_expired_flag():
    deal = Deal(
        id="test_expired_flag",
        title="Audífonos Sony WH-1000XM5",
        price=4500.0,
        expired=True
    )
    assert ValidityEngine.is_vigente(deal) is False


def test_validity_engine_expired_keywords_in_title():
    # Keywords: agotado, expirado, finalizado, sin stock, terminado
    samples = [
        "Consola Nintendo Switch OLED [Agotado]",
        "Sams Club: Cupones de descuento (Expirado)",
        "Amazon: Tenis Adidas Samba [Finalizado]",
        "Rappi: $100 off en hamburguesas - ya no hay",
        "Walmart: Pantalla TCL 55 pulgadas sin stock",
        "Mercado Libre: Cupones 20 Septiembre"  # Past date
    ]
    for title in samples:
        deal = Deal(id="sample", title=title, price=999.0)
        analyzed = SyntropicDetector.analyze_deal(deal)
        assert ValidityEngine.is_vigente(deal) is False, f"Expected '{title}' to be detected as not vigente"
        assert analyzed.expired is True


def test_detector_marks_expired():
    deal = Deal(
        id="sample_expired_detector",
        title="[Agotado] Monitor Gamer Asus TUF 165Hz",
        price=2999.0,
        original_price=4999.0
    )
    analyzed = SyntropicDetector.analyze_deal(deal)
    assert analyzed.expired is True


def test_audit_and_purge_expired(tmp_path):
    from core.storage import Storage

    test_db = str(tmp_path / "test_deals.db")
    storage = Storage(db_path=test_db)

    # Insert 1 active deal and 2 expired deals
    deal_active = Deal(id="d_act", title="Consola Xbox Series X Activa", price=8999.0)
    deal_expired_title = Deal(id="d_exp1", title="Consola PS5 [Agotado]", price=7999.0)
    deal_past_date = Deal(id="d_exp2", title="Mercado Libre: Cupones 22 Septiembre", price=0.0)

    storage.save_deal(deal_active)
    storage.save_deal(deal_expired_title)
    storage.save_deal(deal_past_date)

    # Run audit
    res = ValidityEngine.audit_and_purge_expired(storage)
    assert res["total_audited"] == 3
    assert res["marked_expired"] == 2
    assert res["active_vigentes"] == 1

    # list_deals without expired should only return 1 deal
    active_deals = storage.list_deals(include_expired=False)
    assert len(active_deals) == 1
    assert active_deals[0].id == "d_act"
