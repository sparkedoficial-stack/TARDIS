"""
Base Scraper Module
Provides shared HTTP session, headers rotation, and robust error handling.
"""

import requests
import random
import time
from typing import Optional, Dict


class BaseScraper:
    USER_AGENTS = [
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/REDACTED_IP Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/REDACTED_IP Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    ]

    def __init__(self, timeout: int = 12):
        self.timeout = timeout
        self.session = requests.Session()

    def get_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if extra:
            headers.update(extra)
        return headers

    def safe_get(self, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> Optional[requests.Response]:
        req_headers = self.get_headers(headers)
        try:
            resp = self.session.get(url, params=params, headers=req_headers, timeout=self.timeout)
            if resp.status_code == 200:
                return resp
        except Exception:
            pass
        return None
