"""
FastAPI Server & REST API for TARDIS Price Sentinel
Serves the web dashboard, deal search, live arbitrage engine, and alert management.
"""

from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from pathlib import Path

from core.storage import Storage
from contextlib import asynccontextmanager
from core.models import Deal, WatchItem
from core.banking import BankingEngine
from core.notifier import Notifier
from core.cart_resolver import CartResolver
from scrapers.aggregator import DealAggregator
from sentinel.daemon import SentinelDaemon

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
storage = Storage()
notifier = Notifier()
aggregator = DealAggregator(storage=storage, notifier=notifier)
daemon = SentinelDaemon()


from core.validity import ValidityEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Audit existing deals to ensure only active ones are served
    try:
        ValidityEngine.audit_and_purge_expired(storage)
    except Exception:
        pass
    # Auto-start sentinel background monitor
    daemon.start_background()
    yield
    # Gracefully stop daemon on server shutdown
    daemon.stop()


app = FastAPI(
    title="TARDIS Syntropic Price Sentinel & Deal Oracle",
    description="Sovereign Deal Hunter, Price Error Radar & Cross-Store Arbitrage Engine",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class WatchItemRequest(BaseModel):
    keyword: str
    max_price: Optional[float] = None
    min_discount: Optional[float] = None
    category: str = "all"


class StackingRequest(BaseModel):
    price: float
    coupon_percent: float = 0.0
    coupon_fixed: float = 0.0
    bank_name: Optional[str] = None


class OpenCartRequest(BaseModel):
    deal_id: Optional[str] = None
    url: Optional[str] = None
    merchant: Optional[str] = "Desconocido"
    title: Optional[str] = ""


@app.get("/api/cart/resolve")
def resolve_cart(deal_id: Optional[str] = None, url: Optional[str] = None):
    """Resolves any deal to its direct shopping cart / instant buy URL."""
    target_link = url
    merchant = "Desconocido"
    title = ""
    if deal_id:
        deal = storage.get_deal(deal_id)
        if deal:
            target_link = deal.link
            merchant = deal.merchant
            title = deal.title
    if not target_link:
        raise HTTPException(status_code=400, detail="Debe proporcionar deal_id o url")

    resolved = CartResolver.resolve(target_link, merchant, title)
    return resolved


@app.get("/api/cart/jump/{deal_id}")
def jump_to_cart(deal_id: str, background_tasks: BackgroundTasks):
    """
    Direct jump: Opens desktop browser directly on cart/checkout AND
    issues an HTTP 302 redirect so web clicks land directly in the shopping cart.
    """
    deal = storage.get_deal(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")

    resolved = CartResolver.resolve(deal.link, deal.merchant, deal.title)
    cart_url = resolved["cart_url"]

    # Also open in local desktop session
    background_tasks.add_task(CartResolver.open_in_browser, cart_url)

    # 302 Redirect to the merchant's shopping cart or express buy flow
    return RedirectResponse(url=cart_url, status_code=302)


@app.post("/api/cart/open")
def open_cart_desktop(req: OpenCartRequest):
    """
    Triggers local browser opening directly into shopping cart / buy-now screen.
    """
    target_link = req.url
    merchant = req.merchant or "Desconocido"
    title = req.title or ""
    if req.deal_id:
        deal = storage.get_deal(req.deal_id)
        if deal:
            target_link = deal.link
            merchant = deal.merchant
            title = deal.title
    if not target_link:
        raise HTTPException(status_code=400, detail="Debe proporcionar deal_id o url")

    resolved = CartResolver.resolve(target_link, merchant, title)
    cart_url = resolved["cart_url"]
    opened = CartResolver.open_in_browser(cart_url)
    return {
        "status": "opened" if opened else "dispatched",
        "cart_url": cart_url,
        "store_url": resolved.get("store_url"),
        "merchant": resolved.get("merchant"),
        "action_name": resolved.get("action_name"),
        "instructions": resolved.get("instructions")
    }


@app.get("/")
def read_root():
    index_file = STATIC_DIR / "index.html"
    return FileResponse(str(index_file))


@app.get("/api/deals")
def get_deals(
    q: Optional[str] = None,
    merchant: Optional[str] = None,
    category: Optional[str] = None,
    min_discount: float = 0.0,
    is_glitch: Optional[bool] = None,
    is_free: Optional[bool] = None,
    sort_by: str = "syntropy_score",
    limit: int = 50,
    offset: int = 0
):
    deals = storage.list_deals(
        query=q,
        merchant=merchant,
        category=category,
        min_discount=min_discount,
        is_glitch=is_glitch,
        is_free=is_free,
        include_expired=False,
        sort_by=sort_by,
        limit=limit,
        offset=offset
    )
    # Strictly enforce validity
    vigentes = [d for d in deals if ValidityEngine.is_vigente(d) and not d.expired]
    return {"count": len(vigentes), "deals": [d.to_dict() for d in vigentes]}


@app.get("/api/glitches")
def get_glitches(limit: int = 30):
    glitches = storage.list_deals(is_glitch=True, include_expired=False, limit=limit, sort_by="syntropy_score")
    vigentes = [g for g in glitches if ValidityEngine.is_vigente(g) and not g.expired]
    return {"count": len(vigentes), "glitches": [g.to_dict() for g in vigentes]}


@app.get("/api/liquidaciones")
def get_liquidaciones(limit: int = 30):
    deals = storage.list_deals(include_expired=False, limit=100, sort_by="syntropy_score")
    filtered = [
        d for d in deals 
        if (d.liquidation_phase > 0 or "liquidación" in d.title.lower() or "remate" in d.title.lower())
        and ValidityEngine.is_vigente(d) and not d.expired
    ]
    return {"count": len(filtered[:limit]), "liquidaciones": [d.to_dict() for d in filtered[:limit]]}


@app.get("/api/arbitrage")
def get_arbitrage(q: str = Query(..., min_length=2)):
    result = aggregator.search_arbitrage(q)
    return result


@app.get("/api/coupons")
def get_coupons():
    promos = BankingEngine.get_promos()
    # Fetch only active deals with voucher codes from storage
    deals_with_code = storage.list_deals(include_expired=False, limit=60)
    vouchers = [
        {"merchant": d.merchant, "code": d.voucher_code, "deal_title": d.title, "link": d.link}
        for d in deals_with_code if d.voucher_code and ValidityEngine.is_vigente(d) and not d.expired
    ]
    return {
        "bank_promos": [
            {
                "bank": p.bank_name,
                "discount_rate": f"{int(p.discount_rate * 100)}%",
                "min_purchase": p.min_purchase,
                "description": p.description,
                "conditions": p.conditions,
                "card_type": p.card_type
            }
            for p in promos
        ],
        "discovered_coupons": vouchers
    }


@app.post("/api/vigencia/audit")
def audit_vigencia():
    """Runs a full audit across all deals in the database, purging expired deals."""
    res = ValidityEngine.audit_and_purge_expired(storage)
    return {"status": "completed", "result": res}


@app.post("/api/calculator/stacking")
def calculate_stacking(req: StackingRequest):
    res = BankingEngine.calculate_stacking(
        base_price=req.price,
        coupon_percent=req.coupon_percent,
        coupon_fixed=req.coupon_fixed,
        bank_name=req.bank_name
    )
    return res


@app.get("/api/watchlist")
def list_watchlist():
    items = storage.list_watchlist()
    return {"items": [i.to_dict() for i in items]}


@app.post("/api/watchlist")
def add_watchlist(req: WatchItemRequest):
    item = WatchItem(
        keyword=req.keyword.strip(),
        max_price=req.max_price,
        min_discount=req.min_discount,
        category=req.category
    )
    item_id = storage.add_watch_item(item)
    return {"status": "created", "id": item_id}


@app.delete("/api/watchlist/{watch_id}")
def delete_watchlist(watch_id: int):
    ok = storage.delete_watch_item(watch_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Watch item not found")
    return {"status": "deleted"}


@app.post("/api/scan")
def trigger_scan(background_tasks: BackgroundTasks):
    # Perform immediate scan
    res = aggregator.scan_all()
    return {"status": "completed", "result": res}


@app.get("/api/stats")
def get_stats():
    return storage.get_stats()


@app.get("/api/daemon/status")
def get_daemon_status():
    return daemon.get_status()


@app.post("/api/daemon/start")
def start_daemon():
    daemon.start_background()
    return {"status": "started"}


@app.post("/api/daemon/stop")
def stop_daemon():
    daemon.stop()
    return {"status": "stopped"}


@app.post("/api/test-alert")
def trigger_test_alert():
    test_deal = Deal(
        id="test_alert_sample",
        title="[PRUEBA] Consola Nintendo Switch OLED - Edición Especial",
        price=1999.0,
        original_price=6999.0,
        discount_percent=71.4,
        merchant="Amazon México",
        is_glitch=True,
        notes="Prueba de alerta de escritorio TARDIS Sentinel"
    )
    sent = notifier.notify_deal(test_deal, reason="🔔 Alerta de Prueba del Sistema")
    return {"desktop_sent": sent, "message": "Alerta de prueba enviada exitosamente"}
