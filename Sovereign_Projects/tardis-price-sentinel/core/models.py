"""
TARDIS Syntropic Price Sentinel - Data Models
Defines structured classes for Deals, Anomalies, Watchlist and Promotions.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any
from datetime import datetime
import hashlib
import json


@dataclass
class Deal:
    id: str
    title: str
    price: float
    original_price: float = 0.0
    discount_percent: float = 0.0
    merchant: str = "Desconocido"
    category: str = "General"
    link: str = ""
    direct_link: str = ""
    cart_url: str = ""
    image_url: str = ""
    voucher_code: str = ""
    temperature: float = 0.0
    is_glitch: bool = False
    is_free: bool = False
    liquidation_phase: int = 0  # 1 (.03), 2 (.02), 3 (.01)
    source: str = "generic"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expired: bool = False
    syntropy_score: float = 0.0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if not data.get("cart_url"):
            data["cart_jump_url"] = f"/api/cart/jump/{self.id}"
        else:
            data["cart_jump_url"] = data["cart_url"]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Deal":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @staticmethod
    def generate_id(title: str, merchant: str, price: float) -> str:
        raw = f"{title.strip().lower()}|{merchant.strip().lower()}|{price:.2f}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class WatchItem:
    id: Optional[int] = None
    keyword: str = ""
    max_price: Optional[float] = None
    min_discount: Optional[float] = None
    category: str = "all"
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_matched_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BankPromo:
    bank_name: str
    discount_rate: float  # e.g. 0.15 for 15%
    min_purchase: float
    description: str
    active: bool = True
    conditions: str = ""
    card_type: str = "Crédito"  # Crédito / Débito / Digital
