"""
Unit tests for Storage and BankingEngine
"""

import tempfile
import os
from pathlib import Path
from core.models import Deal, WatchItem
from core.storage import Storage
from core.banking import BankingEngine


def test_storage_crud_and_price_history():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db = f.name

    try:
        storage = Storage(db_path=temp_db)

        # 1. Insert deal
        deal1 = Deal(
            id="d1",
            title="Consola Xbox Series S",
            price=4500.0,
            original_price=6000.0,
            discount_percent=25.0,
            merchant="Amazon"
        )
        is_new = storage.save_deal(deal1)
        assert is_new is True

        retrieved = storage.get_deal("d1")
        assert retrieved is not None
        assert retrieved.price == 4500.0

        # 2. Update price and check price history
        deal1.price = 3999.0
        is_new2 = storage.save_deal(deal1)
        assert is_new2 is False

        history = storage.get_price_history("d1")
        assert len(history) == 2
        assert history[0]["price"] == 4500.0
        assert history[1]["price"] == 3999.0

        # 3. Watchlist
        w = WatchItem(keyword="xbox", max_price=5000.0)
        w_id = storage.add_watch_item(w)
        items = storage.list_watchlist()
        assert len(items) == 1
        assert items[0].id == w_id

        del_ok = storage.delete_watch_item(w_id)
        assert del_ok is True
        assert len(storage.list_watchlist()) == 0

    finally:
        if os.path.exists(temp_db):
            os.remove(temp_db)


def test_banking_stacking_calculation():
    # Test base price $10,000, 10% coupon, Banorte Digital promo (15%)
    res = BankingEngine.calculate_stacking(
        base_price=10000.0,
        coupon_percent=10.0,
        bank_name="Banorte Digital"
    )

    assert res["original_price"] == 10000.0
    assert res["coupon_effective_price"] == 9000.0
    assert res["bank_bonus_amount"] == 1350.0  # 15% of 9000
    assert res["final_effective_price"] == 7650.0
    assert res["total_savings"] == 2350.0
    assert res["total_savings_pct"] == 23.5
    assert res["qualified_for_bank"] is True
