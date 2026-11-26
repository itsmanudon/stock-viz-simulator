"""Feed and broker providers by name (A6.3)."""

from __future__ import annotations

from typing import Any

from stockviz.services.feeds.alpaca import AlpacaFeed
from stockviz.services.feeds.base import BrokerProvider, StubBroker
from stockviz.services.feeds.finnhub import FinnhubFeed
from stockviz.services.feeds.massive import MassiveFeed
from stockviz.services.feeds.provider import HttpFeed
from stockviz.services.feeds.tiingo import TiingoFeed
from stockviz.settings import Settings

FEED_CLASSES: dict[str, type[HttpFeed]] = {
    "alpaca": AlpacaFeed,
    "tiingo": TiingoFeed,
    "massive": MassiveFeed,
    "finnhub": FinnhubFeed,
}
FEED_NAMES = tuple(FEED_CLASSES)
BACKFILL_PROVIDERS = ("alpaca", "tiingo", "massive")
"""Providers with minute history on their free plan."""

KEY_ENV_VARS: dict[str, tuple[str, ...]] = {
    "alpaca": ("ALPACA_KEY_ID", "ALPACA_SECRET_KEY"),
    "tiingo": ("TIINGO_API_KEY",),
    "massive": ("MASSIVE_API_KEY",),
    "finnhub": ("FINNHUB_API_KEY",),
}


def feed_keys(name: str, settings: Settings) -> dict[str, str]:
    if name == "alpaca":
        return {
            "key": settings.alpaca_key_id,
            "secret": settings.alpaca_secret_key.get_secret_value(),
        }
    if name == "tiingo":
        return {"key": settings.tiingo_api_key.get_secret_value()}
    if name == "massive":
        return {"key": settings.massive_api_key}
    if name == "finnhub":
        return {"key": settings.finnhub_api_key.get_secret_value()}
    raise KeyError(name)


def build_feed(name: str, settings: Settings, **options: Any) -> HttpFeed:
    """The named provider with its keys from settings (blank = not configured)."""
    cls = FEED_CLASSES[name]
    return cls(**feed_keys(name, settings), **options)


BROKERS: dict[str, BrokerProvider] = {
    "zerodha": StubBroker(
        name="zerodha",
        label="Zerodha",
        reason=(
            "tradebook CSV import is /v1/books/{id}/imports (A5.3); the login, "
            "fills hook and basket export come with A6.11 and the paid Kite app"
        ),
    ),
}
