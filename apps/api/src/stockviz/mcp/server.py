"""The StockViz MCP server (A8.6, M11.7): local, stdio, read-only.

Owner, 27 Nov 2026: the official ``mcp`` Python SDK, a local stdio server
only; remote access waits for the pre-release legal review. Run it as the
owner's own process (the CLI's trust): ``python -m stockviz.mcp``.

Every tool calls the API's own routes in process (an ASGI client on
``create_app()``), so an answer is exactly what the page shows, with the same
checks, rate limits and refusals. Each result carries ``source``: the route
that produced it, so a number can be traced. Tools are read-only or simulated
(a backtest books nothing); there is no order tool, and a test keeps it so.

``journal_stats`` reads one user's journal: ``STOCKVIZ_MCP_USER_ID`` names
the user, signed with ``INTERNAL_API_TOKEN`` like the web server. Without it
the tool says it is off.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx
from jose import jwt as jose_jwt
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from stockviz.settings import get_settings

BASE = "http://stockviz.local"
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
TOOL_NAMES = (
    "rule_check",
    "screen",
    "backtest_strategy",
    "symbol_summary",
    "search_documents",
    "macro_overview",
    "journal_stats",
)

ClientFactory = Callable[[], httpx.AsyncClient]


def _default_client() -> httpx.AsyncClient:
    from stockviz.main import create_app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url=BASE)


def _user_headers() -> dict[str, str] | None:
    raw = os.environ.get("STOCKVIZ_MCP_USER_ID", "").strip()
    if not raw.isdigit():
        return None
    token = jose_jwt.encode({"sub": raw}, get_settings().internal_api_token, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def _call(
    factory: ClientFactory,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    async with factory() as client:
        response = await client.request(method, path, params=params, json=json, headers=headers)
    try:
        body: Any = response.json()
    except ValueError:
        body = {"detail": response.text[:500]}
    if response.status_code >= 400:
        detail = body.get("detail") if isinstance(body, dict) else body
        return {"ok": False, "status": response.status_code, "detail": detail, "source": path}
    return {"ok": True, "source": path, "data": body}


def _pick(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: data[k] for k in keys if k in data}


def build_server(factory: ClientFactory = _default_client) -> MCPServer:
    server = MCPServer(
        name="stockviz",
        instructions=(
            "StockViz research tools: rule checks, screens, simulated backtests and stored "
            "research data. Every figure comes from a tool result with its source route; "
            "nothing here places an order."
        ),
    )

    @server.tool(annotations=READ_ONLY)
    async def rule_check(rule: str, timeframe: str = "daily") -> dict[str, Any]:
        """Check a Rule DSL condition: canonical form, hash, warm-up, or the error with its column."""
        return await _call(
            factory, "POST", "/v1/rules/check", json={"rule": rule, "timeframe": timeframe}
        )

    @server.tool(annotations=READ_ONLY)
    async def screen(
        rule: str | None = None,
        market: str | None = None,
        sort: str = "ticker",
        limit: int = 25,
    ) -> dict[str, Any]:
        """Run the screener (optionally with a Rule DSL condition) on the latest stored session."""
        params: dict[str, Any] = {"sort": sort, "limit": max(1, min(limit, 100))}
        if rule:
            params["rule"] = rule
        if market:
            params["market"] = market
        out = await _call(factory, "GET", "/v1/screener", params=params)
        if out["ok"]:
            data = out["data"]
            rows = [
                _pick(r, ("ticker", "name", "last_close", "as_of", "rule_result", "rule_reason"))
                for r in data.get("rows", [])
            ]
            out["data"] = {
                "total": data.get("total"),
                "rows": rows,
                "rule": data.get("rule"),
                "universe": data.get("universe"),
            }
        return out

    @server.tool(annotations=READ_ONLY)
    async def backtest_strategy(
        ticker: str,
        entry_rule: str,
        exit_rule: str | None = None,
        years: int = 5,
        initial_cash: float = 100_000,
        stop_pct: float | None = None,
    ) -> dict[str, Any]:
        """Simulate a Rule DSL strategy on one stored symbol (nothing is booked). Net of costs."""
        end = date.today()
        body: dict[str, Any] = {
            "entry": {"rule": entry_rule},
            "universe": {"ticker": ticker.upper()},
            "from": (end - timedelta(days=int(365.25 * max(1, min(years, 25))))).isoformat(),
            "to": end.isoformat(),
            "initial_cash": initial_cash,
        }
        if exit_rule:
            body["exit"] = {"rule": exit_rule}
        if stop_pct:
            body["stops"] = {"fixed_pct": stop_pct}
        out = await _call(factory, "POST", "/v1/backtest/strategy", json=body)
        if out["ok"]:
            data = out["data"]
            out["data"] = {
                "summary": data.get("summary"),
                "trade_count": len(data.get("trades", [])),
                "trades": data.get("trades", [])[:20],
                "costs": data.get("costs"),
                "window": data.get("window"),
                "strategy_hash": data.get("strategy_hash"),
                "data_fingerprint": data.get("data_fingerprint"),
            }
        return out

    @server.tool(annotations=READ_ONLY)
    async def symbol_summary(ticker: str) -> dict[str, Any]:
        """One stored symbol: name, market, latest close, and its six-dimension checklist."""
        t = ticker.upper()
        detail = await _call(factory, "GET", f"/v1/symbols/{t}")
        if not detail["ok"]:
            return detail
        checklist = await _call(factory, "GET", f"/v1/symbols/{t}/checklist")
        return {
            "ok": True,
            "source": [f"/v1/symbols/{t}", f"/v1/symbols/{t}/checklist"],
            "data": {
                "symbol": detail["data"],
                "checklist": checklist.get("data", {}).get("row") if checklist["ok"] else None,
            },
        }

    @server.tool(annotations=READ_ONLY)
    async def search_documents(query: str, ticker: str | None = None) -> dict[str, Any]:
        """Phrase search over stored filings and transcripts, public by now, with snippets."""
        params: dict[str, Any] = {"q": query}
        if ticker:
            params["ticker"] = ticker.upper()
        return await _call(factory, "GET", "/v1/documents/search", params=params)

    @server.tool(annotations=READ_ONLY)
    async def macro_overview() -> dict[str, Any]:
        """Stored FRED series (latest, 1-month and 1-year change) and the spreads."""
        out = await _call(factory, "GET", "/v1/macro")
        if out["ok"]:
            data = out["data"]
            keep = ("series_id", "label", "units", "latest", "change_month", "change_year", "stale")
            out["data"] = {
                "series": [_pick(s, keep) for s in data.get("series", [])],
                "spreads": [
                    _pick(s, ("key", "label", "latest", "reason")) for s in data.get("spreads", [])
                ],
            }
        return out

    @server.tool(annotations=READ_ONLY)
    async def journal_stats(book: str = "all") -> dict[str, Any]:
        """The configured user's journal: is the edge real? (needs STOCKVIZ_MCP_USER_ID)."""
        headers = _user_headers()
        if headers is None:
            return {
                "ok": False,
                "status": 0,
                "detail": "journal_stats is off: set STOCKVIZ_MCP_USER_ID to your user id.",
                "source": "/v1/journal/stats",
            }
        return await _call(
            factory, "GET", "/v1/journal/stats", params={"book": book}, headers=headers
        )

    return server


def main() -> None:
    build_server().run("stdio")
