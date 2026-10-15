"""
Unit tests for CartResolver and cart endpoints
"""

import pytest
from core.cart_resolver import CartResolver
from core.models import Deal
from core.storage import Storage
from fastapi.testclient import TestClient
from web.app import app


def test_amazon_cart_resolution():
    url = "https://www.amazon.com.mx/dp/B07D9SNPYT?tag=test-20"
    res = CartResolver.resolve(url, merchant="Amazon México")
    assert res["is_direct_cart"] is True
    assert "ASIN.1=B07D9SNPYT" in res["cart_url"]
    assert "add.html" in res["cart_url"]
    assert res["item_id"] == "B07D9SNPYT"


def test_mercadolibre_cart_resolution():
    url = "https://articulo.mercadolibre.com.mx/MLM-REDACTED_PHONE-producto-test-_JM"
    res = CartResolver.resolve(url, merchant="Mercado Libre")
    assert res["is_direct_cart"] is True
    assert "checkout/buy?item_id=MLM2077544317" in res["cart_url"]
    assert res["item_id"] == "MLM2077544317"


def test_walmart_cart_resolution():
    url = "https://www.walmart.com.mx/ip/pantalla-4k/12345"
    res = CartResolver.resolve(url, merchant="Walmart México")
    assert res["is_direct_cart"] is True
    assert "walmart.com.mx/cart" in res["cart_url"]


def test_fastapi_cart_endpoints():
    client = TestClient(app)

    # 1. Resolve direct URL
    resp = client.get("/api/cart/resolve?url=https://www.amazon.com.mx/dp/B08N5WRWNW")
    assert resp.status_code == 200
    data = resp.json()
    assert "ASIN.1=B08N5WRWNW" in data["cart_url"]

    # 2. Insert temporary deal in storage to test jump
    storage = Storage()
    test_deal = Deal(
        id="test_deal_cart_unit",
        title="Laptop Gamer RTX 4060",
        price=18999.0,
        merchant="Mercado Libre",
        link="https://articulo.mercadolibre.com.mx/MLM-REDACTED_PHONE-laptop-gamer"
    )
    storage.save_deal(test_deal)

    # 3. Test resolve by deal_id
    resp = client.get("/api/cart/resolve?deal_id=test_deal_cart_unit")
    assert resp.status_code == 200
    data = resp.json()
    assert "item_id=MLM9988776655" in data["cart_url"]

    # 4. Test jump redirect
    resp = client.get("/api/cart/jump/test_deal_cart_unit", follow_redirects=False)
    assert resp.status_code == 302
    assert "checkout/buy?item_id=MLM9988776655" in resp.headers["Location"]
