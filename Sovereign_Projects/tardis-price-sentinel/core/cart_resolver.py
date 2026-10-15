"""
TARDIS Smart Cart & Express Checkout Resolver
Transforms deal links from any platform (Amazon, Mercado Libre, Walmart, Steam, etc.)
into direct shopping cart / instant express buy links, and provides one-click
browser opening for desktop users.
"""

import re
import os
import urllib.parse
import subprocess
import webbrowser
import logging
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger("tardis.cart_resolver")

# Memory cache for resolved deal URLs
_RESOLVE_CACHE: Dict[str, Dict[str, Any]] = {}


class CartResolver:
    """
    Intelligent cart and checkout resolver for multi-merchant deals.
    Detects merchant patterns, extracts product identifiers (ASIN, MLM-ID, etc.),
    and constructs direct add-to-cart or express checkout URLs.
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/REDACTED_IP Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-MX,es;q=0.9,en;q=0.8"
    }

    @classmethod
    def resolve(cls, link: str, merchant: str = "Desconocido", title: str = "") -> Dict[str, Any]:
        """
        Resolves any deal link to its direct shopping cart / buy-now link.
        Returns a rich metadata dictionary.
        """
        if not link:
            return cls._fallback_response(link, merchant, "Enlace no proporcionado")

        cache_key = f"{link}|{merchant}"
        if cache_key in _RESOLVE_CACHE:
            return _RESOLVE_CACHE[cache_key]

        target_url = link.strip()
        detected_merchant = merchant

        # Step 1: If it's a Promodescuentos link, follow the outbound redirect to the store
        if "promodescuentos.com" in target_url:
            resolved_store_url, found_merchant = cls._resolve_promodescuentos_redirect(target_url)
            if resolved_store_url:
                target_url = resolved_store_url
                if found_merchant and (detected_merchant in ["Desconocido", "Promodescuentos", ""]):
                    detected_merchant = found_merchant

        # Step 2: Clean tracking parameters while preserving product identity
        clean_url = cls._clean_url(target_url)

        # Step 3: Merchant-specific cart synthesis
        result = cls._synthesize_cart_url(clean_url, detected_merchant, title)

        _RESOLVE_CACHE[cache_key] = result
        return result

    @classmethod
    def _resolve_promodescuentos_redirect(cls, url: str) -> tuple[Optional[str], Optional[str]]:
        """
        Follows Promodescuentos visit redirects to find the direct e-commerce destination.
        """
        thread_id = None
        # Extract thread ID from /ofertas/...-1193765 or /cupones/...-1193592 or /share-deal/1193765
        match = re.search(r'promodescuentos\.com/(?:ofertas|cupones)/.*?-(\d+)(?:[/?#]|$)', url)
        if match:
            thread_id = match.group(1)
        else:
            match = re.search(r'promodescuentos\.com/share-deal/(\d+)', url)
            if match:
                thread_id = match.group(1)

        if not thread_id:
            return None, None

        visit_url = f"https://www.promodescuentos.com/visit/thread/{thread_id}"
        try:
            resp = requests.get(visit_url, headers=cls.HEADERS, allow_redirects=False, timeout=4)
            location = resp.headers.get("Location")
            if location:
                # Often points to path.promodescuentos.com/pepper-mx/redirect?url=...
                if "url=" in location:
                    parsed = urllib.parse.urlparse(location)
                    query_params = urllib.parse.parse_qs(parsed.query)
                    if "url" in query_params:
                        real_dest = urllib.parse.unquote(query_params["url"][0])
                        return real_dest, cls._guess_merchant_from_domain(real_dest)
                
                # If it's a direct store redirect
                if "promodescuentos.com" not in location:
                    return location, cls._guess_merchant_from_domain(location)

                # Follow one more hop if needed
                resp2 = requests.get(location, headers=cls.HEADERS, allow_redirects=True, timeout=4)
                if resp2 and "promodescuentos.com" not in resp2.url:
                    return resp2.url, cls._guess_merchant_from_domain(resp2.url)
        except Exception as e:
            logger.debug(f"Promodescuentos redirect resolution error: {e}")

        return None, None

    @classmethod
    def _clean_url(cls, url: str) -> str:
        """Removes fragment and non-essential affiliate query params if appropriate."""
        if "#" in url:
            url = url.split("#")[0]
        return url

    @classmethod
    def _guess_merchant_from_domain(cls, url: str) -> str:
        domain = urllib.parse.urlparse(url).netloc.lower()
        if "amazon" in domain:
            return "Amazon"
        elif "mercadolibre" in domain or "mercadopago" in domain:
            return "Mercado Libre"
        elif "walmart" in domain:
            return "Walmart"
        elif "bodegaaurrera" in domain:
            return "Bodega Aurrera"
        elif "chedraui" in domain:
            return "Chedraui"
        elif "liverpool" in domain:
            return "Liverpool"
        elif "steampowered" in domain or "steamcommunity" in domain:
            return "Steam"
        elif "aliexpress" in domain:
            return "AliExpress"
        elif "nintendo" in domain:
            return "Nintendo"
        elif "playstation" in domain or "sony" in domain:
            return "PlayStation"
        return "Tienda Externa"

    @classmethod
    def _synthesize_cart_url(cls, url: str, merchant: str, title: str) -> Dict[str, Any]:
        """
        Generates direct cart / express checkout URL according to merchant rules.
        """
        merchant_lower = merchant.lower()
        url_lower = url.lower()

        # ==========================================
        # 1. AMAZON (amazon.com.mx, amazon.com)
        # ==========================================
        if "amazon" in merchant_lower or "amazon" in url_lower or "amzn" in url_lower:
            asin = cls._extract_amazon_asin(url)
            domain = "amazon.com.mx" if "amazon.com.mx" in url or ".mx" in url else "amazon.com.mx"

            if asin:
                # Direct Add-to-Cart URL: automatically inserts item and lands in shopping cart
                cart_url = f"https://www.{domain}/gp/aws/cart/add.html?ASIN.1={asin}&Quantity.1=1"
                direct_product = f"https://www.{domain}/dp/{asin}"
                return {
                    "cart_url": cart_url,
                    "store_url": direct_product,
                    "merchant": "Amazon México",
                    "item_id": asin,
                    "action_name": "Añadir a Carrito Amazon 🛒",
                    "is_direct_cart": True,
                    "instructions": f"Se abrirá Amazon agregando el artículo ASIN {asin} a tu carrito."
                }
            else:
                cart_url = f"https://www.{domain}/gp/cart/view.html"
                return {
                    "cart_url": cart_url,
                    "store_url": url,
                    "merchant": "Amazon México",
                    "item_id": "",
                    "action_name": "Abrir Carrito Amazon 🛒",
                    "is_direct_cart": True,
                    "instructions": "Abriendo tu carrito de Amazon México."
                }

        # ==========================================
        # 2. MERCADO LIBRE (mercadolibre.com.mx)
        # ==========================================
        if "mercado" in merchant_lower or "mercadolibre" in url_lower:
            item_id = cls._extract_mercadolibre_item(url)
            if item_id:
                # Direct Express Buy / Checkout flow
                cart_url = f"https://www.mercadolibre.com.mx/gz/checkout/buy?item_id={item_id}&quantity=1"
                clean_product = f"https://articulo.mercadolibre.com.mx/{item_id}"
                return {
                    "cart_url": cart_url,
                    "store_url": clean_product,
                    "merchant": "Mercado Libre",
                    "item_id": item_id,
                    "action_name": "Comprar / Carrito Mercado Libre ⚡",
                    "is_direct_cart": True,
                    "instructions": f"Se abrirá la pasarela de compra directa de Mercado Libre para {item_id}."
                }
            else:
                return {
                    "cart_url": "https://www.mercadolibre.com.mx/gz/cart",
                    "store_url": url,
                    "merchant": "Mercado Libre",
                    "item_id": "",
                    "action_name": "Abrir Carrito Mercado Libre 🛒",
                    "is_direct_cart": True,
                    "instructions": "Abriendo tu carrito de compras en Mercado Libre."
                }

        # ==========================================
        # 3. WALMART MÉXICO / BODEGA AURRERA
        # ==========================================
        if "walmart" in merchant_lower or "walmart" in url_lower:
            return {
                "cart_url": "https://www.walmart.com.mx/cart",
                "store_url": url,
                "merchant": "Walmart México",
                "item_id": "",
                "action_name": "Ir al Carrito Walmart 🛒",
                "is_direct_cart": True,
                "instructions": "Abriendo carrito de Walmart México."
            }

        if "bodega" in merchant_lower or "aurrera" in merchant_lower or "bodegaaurrera" in url_lower:
            return {
                "cart_url": "https://despensa.bodegaaurrera.com.mx/cart",
                "store_url": url,
                "merchant": "Bodega Aurrera",
                "item_id": "",
                "action_name": "Ir al Carrito Aurrera 🛒",
                "is_direct_cart": True,
                "instructions": "Abriendo carrito de Bodega Aurrera."
            }

        # ==========================================
        # 4. CHEDRAUI
        # ==========================================
        if "chedraui" in merchant_lower or "chedraui" in url_lower:
            return {
                "cart_url": "https://www.chedraui.com.mx/cart",
                "store_url": url,
                "merchant": "Chedraui",
                "item_id": "",
                "action_name": "Ir al Carrito Chedraui 🛒",
                "is_direct_cart": True,
                "instructions": "Abriendo carrito de compras de Chedraui."
            }

        # ==========================================
        # 5. STEAM
        # ==========================================
        if "steam" in merchant_lower or "steampowered" in url_lower:
            return {
                "cart_url": "https://store.steampowered.com/cart/",
                "store_url": url,
                "merchant": "Steam",
                "item_id": "",
                "action_name": "Ir al Carrito de Steam 🎮",
                "is_direct_cart": True,
                "instructions": "Abriendo carrito de compras de Steam."
            }

        # ==========================================
        # 6. ALIEXPRESS
        # ==========================================
        if "aliexpress" in merchant_lower or "aliexpress" in url_lower:
            return {
                "cart_url": "https://shoppingcart.aliexpress.com/shopcart/shopcartDetail.htm",
                "store_url": url,
                "merchant": "AliExpress",
                "item_id": "",
                "action_name": "Ir al Carrito AliExpress 📦",
                "is_direct_cart": True,
                "instructions": "Abriendo carrito de compras de AliExpress."
            }

        # ==========================================
        # 7. LIVERPOOL
        # ==========================================
        if "liverpool" in merchant_lower or "liverpool" in url_lower:
            return {
                "cart_url": "https://www.liverpool.com.mx/tienda/cart",
                "store_url": url,
                "merchant": "Liverpool",
                "item_id": "",
                "action_name": "Ir al Carrito Liverpool 🛍️",
                "is_direct_cart": True,
                "instructions": "Abriendo carrito de compras de Liverpool."
            }

        # ==========================================
        # 8. DEFAULT FALLBACK
        # ==========================================
        return {
            "cart_url": url,
            "store_url": url,
            "merchant": merchant or "Tienda",
            "item_id": "",
            "action_name": f"Ir a Oferta en {merchant} ↗",
            "is_direct_cart": False,
            "instructions": f"Abriendo la publicación directa en {merchant}."
        }

    @staticmethod
    def _extract_amazon_asin(url: str) -> Optional[str]:
        """Extracts 10-char Amazon ASIN."""
        # /dp/B0... or /gp/product/B0...
        m = re.search(r'/(?:dp|gp/product|d)/([A-Z0-9]{10})', url)
        if m:
            return m.group(1)
        # ?asin=B0...
        m = re.search(r'[?&]asin=([A-Z0-9]{10})', url, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        # General /B0... pattern
        m = re.search(r'/([B0][A-Z0-9]{9})(?:[/?&#]|$)', url)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _extract_mercadolibre_item(url: str) -> Optional[str]:
        """Extracts Mercado Libre Item ID (e.g. MLM2077544317)."""
        # MLM-REDACTED_PHONE or MLM2077544317
        m = re.search(r'MLM-?(\d+)', url)
        if m:
            return f"MLM{m.group(1)}"
        # /p/MLM...
        m = re.search(r'/p/(MLM\d+)', url)
        if m:
            return m.group(1)
        # item_id=MLM...
        m = re.search(r'item_id=(MLM\d+)', url)
        if m:
            return m.group(1)
        return None

    @classmethod
    def open_in_browser(cls, target_url: str) -> bool:
        """
        Spawns the user's default desktop browser directly to target_url.
        Uses xdg-open or python webbrowser with DISPLAY/WAYLAND support.
        """
        if not target_url:
            return False

        # Ensure DISPLAY environment variable is passed for GUI browsers
        env = dict(os.environ)
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"
        if "WAYLAND_DISPLAY" not in env and os.path.exists("/run/user/1000/wayland-0"):
            env["WAYLAND_DISPLAY"] = "wayland-0"

        try:
            # Try xdg-open directly first for desktop integration
            proc = subprocess.Popen(
                ["xdg-open", target_url],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            return True
        except Exception:
            try:
                return webbrowser.open_new_tab(target_url)
            except Exception as e:
                logger.error(f"Failed to open browser: {e}")
                return False

    @staticmethod
    def _fallback_response(link: str, merchant: str, reason: str) -> Dict[str, Any]:
        return {
            "cart_url": link or "#",
            "store_url": link or "#",
            "merchant": merchant,
            "item_id": "",
            "action_name": "Abrir Enlace",
            "is_direct_cart": False,
            "instructions": reason
        }
