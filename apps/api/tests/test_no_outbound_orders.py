"""A6.11 (M10.5): StockViz never places an order at a broker.

This scans every Python file under ``src/`` and fails on:

- a string that names a broker's host (Kite, Alpaca, Dhan, Fyers, Upstox,
  Angel One, Groww, IBKR, Schwab and others) together with an order or
  basket path;
- an import of a broker trading SDK (``kiteconnect``, ``alpaca``,
  ``dhanhq``, ``fyers_apiv3``, ``upstox_client``, ``SmartApi``, ``growwapi``,
  ``ib_insync``, ...);
- a call of a broker SDK's order method (``place_order``, ``submit_order``,
  ``placeOrder``, ``modify_order``, ``place_basket``, ...).

Kite's basket is handed off by the user's browser (a form the web renders),
so ``kite.zerodha.com/connect/basket`` may appear in ``src/`` only as the
URL the API tells the web about, in ``routers/brokers.py``, never in a call.
Docstrings (prose citing a broker's help page) are skipped. The scanner
checks itself on a few planted lines first.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

BROKER_HOSTS = re.compile(
    r"(kite\.trade|kite\.zerodha\.com|zerodha\.com|alpaca\.markets|dhan\.co|dhanhq\.co|"
    r"fyers\.in|upstox\.com|angelbroking\.com|angelone\.in|groww\.in|interactivebrokers|"
    r"ibkr|schwab|tdameritrade|tradier|robinhood|webull|etrade|tastytrade)",
    re.IGNORECASE,
)
ORDER_PATH = re.compile(r"(order|basket|gtt|/trade/place|placeorder)", re.IGNORECASE)
BROKER_SDKS = {
    "kiteconnect",
    "alpaca",
    "alpaca_trade_api",
    "dhanhq",
    "fyers_apiv3",
    "fyers_api",
    "upstox_client",
    "SmartApi",
    "smartapi",
    "growwapi",
    "ib_insync",
    "ibapi",
    "schwab",
    "tda",
    "robin_stocks",
}
ORDER_METHODS = {
    "place_order",
    "placeOrder",
    "placeorder",
    "submit_order",
    "modify_order",
    "modifyOrder",
    "cancel_order",
    "place_basket",
    "place_gtt",
    "place_orders",
    "create_order",
}
ALLOWED = {("routers/brokers.py", "https://kite.zerodha.com/connect/basket")}


def scan(source: str, rel: str) -> list[str]:
    """Every outbound-order finding in one file's source."""
    found: list[str] = []
    tree = ast.parse(source)
    # Docstrings and bare string statements cite pages; they can't send anything.
    prose = {
        id(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose:
            value = node.value
            for url in re.findall(r"[a-z]+://[^\s'\"`<>)]+|[\w.-]+\.\w+/[^\s'\"`<>)]+", value):
                order = BROKER_HOSTS.search(url) and ORDER_PATH.search(url)
                if order and (rel, url.rstrip("`.,")) not in ALLOWED:
                    found.append(f"{rel}:{node.lineno}: broker order URL {url}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BROKER_SDKS:
                    found.append(f"{rel}:{node.lineno}: imports {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in BROKER_SDKS:
                found.append(f"{rel}:{node.lineno}: imports {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in ORDER_METHODS:
                found.append(f"{rel}:{node.lineno}: calls {name}()")
    return found


def test_the_scanner_catches_planted_order_calls() -> None:
    planted = (
        "import kiteconnect\n"
        "from alpaca.trading.client import TradingClient\n"
        "client.submit_order(req)\n"
        "kite.place_order(variety='regular')\n"
        "httpx.post('https://api.kite.trade/orders/regular', data=body)\n"
        "requests.post('https://paper-api.alpaca.markets/v2/orders', json=o)\n"
        "url = 'https://api.dhan.co/v2/orders'\n"
        "url = 'https://api-t1.fyers.in/api/v3/orders/sync'\n"
        "url = 'https://api.upstox.com/v2/order/place'\n"
        "url = 'https://apiconnect.angelbroking.com/rest/secure/angelbroking/order/v1/placeOrder'\n"
        "httpx.post('https://kite.zerodha.com/connect/basket', data=d)\n"
    )
    found = scan(planted, "planted.py")
    assert len(found) == 11, found
    # Market-data URLs are not orders.
    assert scan("u = 'https://data.alpaca.markets/v2/stocks/AAPL/bars'\n", "x.py") == []
    assert scan("u = 'https://api.kite.trade/instruments/historical'\n", "x.py") == []


def test_no_outbound_order_route_anywhere_in_src() -> None:
    findings: list[str] = []
    files = sorted(SRC.rglob("*.py"))
    assert len(files) > 100  # the whole package, not an empty glob
    for path in files:
        rel = path.relative_to(SRC / "stockviz").as_posix()
        findings += scan(path.read_text(encoding="utf-8"), rel)
    assert findings == []
