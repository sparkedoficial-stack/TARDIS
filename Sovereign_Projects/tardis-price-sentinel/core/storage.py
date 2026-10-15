"""
TARDIS SQLite Storage & Historical Price Registry
Handles database persistence, deduplication, price tracking, and watchlist management.
"""

import sqlite3
import json
from typing import List, Optional, Dict, Any
from pathlib import Path
from datetime import datetime
from .models import Deal, WatchItem


class Storage:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            db_path = str(base_dir / "deals.db")
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # Deals table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deals (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    price REAL NOT NULL,
                    original_price REAL DEFAULT 0.0,
                    discount_percent REAL DEFAULT 0.0,
                    merchant TEXT,
                    category TEXT,
                    link TEXT,
                    direct_link TEXT,
                    cart_url TEXT,
                    image_url TEXT,
                    voucher_code TEXT,
                    temperature REAL DEFAULT 0.0,
                    is_glitch INTEGER DEFAULT 0,
                    is_free INTEGER DEFAULT 0,
                    liquidation_phase INTEGER DEFAULT 0,
                    source TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    expired INTEGER DEFAULT 0,
                    syntropy_score REAL DEFAULT 0.0,
                    notes TEXT
                )
            """)

            # Migration for existing tables
            try:
                cursor.execute("ALTER TABLE deals ADD COLUMN direct_link TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE deals ADD COLUMN cart_url TEXT")
            except sqlite3.OperationalError:
                pass

            # Price History table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_id TEXT NOT NULL,
                    price REAL NOT NULL,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY(deal_id) REFERENCES deals(id)
                )
            """)

            # Watchlist table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    max_price REAL,
                    min_discount REAL,
                    category TEXT DEFAULT 'all',
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT,
                    last_matched_at TEXT
                )
            """)

            # Alerts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_id TEXT,
                    watch_id INTEGER,
                    alert_type TEXT,
                    message TEXT,
                    triggered_at TEXT,
                    sent_desktop INTEGER DEFAULT 0
                )
            """)

            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_deals_price ON deals(price)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_deals_score ON deals(syntropy_score)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_deals_glitch ON deals(is_glitch)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_deals_merchant ON deals(merchant)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_deal ON price_history(deal_id)")
            conn.commit()

    def save_deal(self, deal: Deal) -> bool:
        """
        Inserts or updates a deal.
        Records price history when price changes.
        Returns True if newly inserted or updated.
        """
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT price FROM deals WHERE id = ?", (deal.id,))
            row = cursor.fetchone()

            if row is None:
                # Insert new deal
                cursor.execute("""
                    INSERT INTO deals (
                        id, title, price, original_price, discount_percent, merchant,
                        category, link, direct_link, cart_url, image_url, voucher_code, temperature,
                        is_glitch, is_free, liquidation_phase, source, created_at,
                        updated_at, expired, syntropy_score, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    deal.id, deal.title, deal.price, deal.original_price, deal.discount_percent,
                    deal.merchant, deal.category, deal.link, deal.direct_link, deal.cart_url, deal.image_url, deal.voucher_code,
                    deal.temperature, 1 if deal.is_glitch else 0, 1 if deal.is_free else 0,
                    deal.liquidation_phase, deal.source, deal.created_at, now,
                    1 if deal.expired else 0, deal.syntropy_score, deal.notes
                ))
                # Insert initial price history
                cursor.execute("""
                    INSERT INTO price_history (deal_id, price, recorded_at) VALUES (?, ?, ?)
                """, (deal.id, deal.price, now))
                conn.commit()
                return True
            else:
                old_price = row["price"]
                # Update existing deal
                cursor.execute("""
                    UPDATE deals SET
                        title = ?, price = ?, original_price = ?, discount_percent = ?,
                        merchant = ?, category = ?, link = ?, direct_link = ?, cart_url = ?,
                        image_url = ?, voucher_code = ?, temperature = ?, is_glitch = ?,
                        is_free = ?, liquidation_phase = ?, updated_at = ?, expired = ?,
                        syntropy_score = ?, notes = ?
                    WHERE id = ?
                """, (
                    deal.title, deal.price, deal.original_price, deal.discount_percent,
                    deal.merchant, deal.category, deal.link, deal.direct_link, deal.cart_url,
                    deal.image_url, deal.voucher_code, deal.temperature, 1 if deal.is_glitch else 0,
                    1 if deal.is_free else 0,
                    deal.liquidation_phase, now, 1 if deal.expired else 0,
                    deal.syntropy_score, deal.notes, deal.id
                ))
                # If price changed, record history
                if abs(old_price - deal.price) > 0.01:
                    cursor.execute("""
                        INSERT INTO price_history (deal_id, price, recorded_at) VALUES (?, ?, ?)
                    """, (deal.id, deal.price, now))
                conn.commit()
                return False

    def get_deal(self, deal_id: str) -> Optional[Deal]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM deals WHERE id = ?", (deal_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d["is_glitch"] = bool(d["is_glitch"])
                d["is_free"] = bool(d["is_free"])
                d["expired"] = bool(d["expired"])
                return Deal.from_dict(d)
        return None

    def list_deals(
        self,
        query: Optional[str] = None,
        merchant: Optional[str] = None,
        category: Optional[str] = None,
        min_discount: float = 0.0,
        is_glitch: Optional[bool] = None,
        is_free: Optional[bool] = None,
        include_expired: bool = False,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "syntropy_score"  # syntropy_score, discount_percent, price_asc, created_at
    ) -> List[Deal]:
        conditions = []
        params = []

        if query:
            conditions.append("(title LIKE ? OR notes LIKE ? OR voucher_code LIKE ?)")
            q = f"%{query}%"
            params.extend([q, q, q])

        if merchant and merchant.lower() != "todos":
            conditions.append("LOWER(merchant) LIKE ?")
            params.append(f"%{merchant.lower()}%")

        if category and category.lower() != "todos":
            conditions.append("LOWER(category) LIKE ?")
            params.append(f"%{category.lower()}%")

        if min_discount > 0:
            conditions.append("discount_percent >= ?")
            params.append(min_discount)

        if is_glitch is not None:
            conditions.append("is_glitch = ?")
            params.append(1 if is_glitch else 0)

        if is_free is not None:
            conditions.append("is_free = ?")
            params.append(1 if is_free else 0)

        if not include_expired:
            conditions.append("expired = 0")

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        order_map = {
            "syntropy_score": "syntropy_score DESC",
            "discount_percent": "discount_percent DESC",
            "price_asc": "price ASC",
            "price_desc": "price DESC",
            "created_at": "updated_at DESC"
        }
        order_clause = order_map.get(sort_by, "syntropy_score DESC")

        sql = f"SELECT * FROM deals {where_clause} ORDER BY {order_clause} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            deals = []
            for row in cursor.fetchall():
                d = dict(row)
                d["is_glitch"] = bool(d["is_glitch"])
                d["is_free"] = bool(d["is_free"])
                d["expired"] = bool(d["expired"])
                deals.append(Deal.from_dict(d))
            return deals

    def get_price_history(self, deal_id: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT price, recorded_at FROM price_history WHERE deal_id = ? ORDER BY recorded_at ASC",
                (deal_id,)
            )
            return [dict(r) for r in cursor.fetchall()]

    # Watchlist Management
    def add_watch_item(self, item: WatchItem) -> int:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO watchlist (keyword, max_price, min_discount, category, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                item.keyword, item.max_price, item.min_discount, item.category,
                1 if item.enabled else 0, item.created_at
            ))
            conn.commit()
            return cursor.lastrowid

    def list_watchlist(self) -> List[WatchItem]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watchlist ORDER BY id DESC")
            items = []
            for r in cursor.fetchall():
                items.append(WatchItem(
                    id=r["id"],
                    keyword=r["keyword"],
                    max_price=r["max_price"],
                    min_discount=r["min_discount"],
                    category=r["category"],
                    enabled=bool(r["enabled"]),
                    created_at=r["created_at"],
                    last_matched_at=r["last_matched_at"]
                ))
            return items

    def delete_watch_item(self, watch_id: int) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM watchlist WHERE id = ?", (watch_id,))
            conn.commit()
            return cursor.rowcount > 0

    def update_watch_matched(self, watch_id: int):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE watchlist SET last_matched_at = ? WHERE id = ?",
                (datetime.now().isoformat(), watch_id)
            )
            conn.commit()

    # Alerts
    def record_alert(self, deal_id: str, message: str, alert_type: str = "glitch", watch_id: Optional[int] = None, sent_desktop: bool = False):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alerts (deal_id, watch_id, alert_type, message, triggered_at, sent_desktop)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (deal_id, watch_id, alert_type, message, datetime.now().isoformat(), 1 if sent_desktop else 0))
            conn.commit()

    def mark_deal_expired(self, deal_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE deals SET expired = 1, updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), deal_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def purge_expired_deals(self) -> int:
        """Removes expired deals older than 7 days from the database."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM deals WHERE expired = 1")
            conn.commit()
            return cursor.rowcount

    def get_stats(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM deals WHERE expired = 0")
            active_deals = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM deals")
            total_history = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM deals WHERE is_glitch = 1 AND expired = 0")
            active_glitches = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM deals WHERE is_free = 1 AND expired = 0")
            active_free = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT merchant) FROM deals WHERE expired = 0")
            merchants_count = cursor.fetchone()[0]

            cursor.execute("SELECT MAX(discount_percent) FROM deals WHERE expired = 0")
            max_discount = cursor.fetchone()[0] or 0.0

            cursor.execute("SELECT COUNT(*) FROM watchlist WHERE enabled = 1")
            active_watches = cursor.fetchone()[0]

            return {
                "total_deals": active_deals,
                "all_time_history": total_history,
                "active_glitches": active_glitches,
                "active_free": active_free,
                "merchants_count": merchants_count,
                "max_discount": max_discount,
                "active_watches": active_watches
            }
