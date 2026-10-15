"""
Scrapers package
"""

from .base import BaseScraper
from .promodescuentos import PromodescuentosScraper
from .mercadolibre import MercadoLibreScraper
from .liquidaciones import LiquidacionesScraper
from .aggregator import DealAggregator

__all__ = [
    "BaseScraper",
    "PromodescuentosScraper",
    "MercadoLibreScraper",
    "LiquidacionesScraper",
    "DealAggregator",
]
