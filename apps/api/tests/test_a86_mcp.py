"""A8.6 (M11.7): the local MCP server. The A8 done-when: an agent runs a screen
and a backtest through MCP. Tools are driven through ``call_tool`` as an MCP
client would; the routes run in process on the test database.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.mcp import server as mcp_server
from stockviz.models import PriceBar
from tests.symbols import seed_symbols


def _seed(session: Session) -> None:
    seed_symbols(session, "WAVE")
    start = date.today() - timedelta(days=900)
    for i in range(620):
        day = start + timedelta(days=i)
        if day.weekday() >= 5:
            continue
        price = Decimal(str(round(100 + 10 * math.sin(i / 15) + i * 0.05, 4)))
        session.add(PriceBar(ticker="WAVE", interval="1d", ts=datetime.combine(day, datetime.min.time()),
                             open=price, high=price, low=price, close=price, volume=1000))  # fmt: skip
    session.commit()


@pytest.fixture
def server(client: TestClient):
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url=mcp_server.BASE
        )

    return mcp_server.build_server(factory)


async def _call(server: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await server.call_tool(name, args)
    assert not result.is_error, result.content
    return result.structured_content.get("result", result.structured_content)


async def test_tools_are_read_only_and_none_places_an_order(server) -> None:
    tools = await server.list_tools()
    assert tuple(t.name for t in tools) == mcp_server.TOOL_NAMES
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)
    banned = re.compile(r"order|trade|buy|sell|place|basket|transfer", re.I)
    assert not [t.name for t in tools if banned.search(t.name)]


async def test_rule_check_through_mcp(server) -> None:
    ok = await _call(server, "rule_check", {"rule": "close > sma(close, 20)"})
    assert ok["ok"] and ok["data"]["valid"] and ok["source"] == "/v1/rules/check"
    bad = await _call(server, "rule_check", {"rule": "close >>> 1"})
    assert bad["ok"] and bad["data"]["valid"] is False


async def test_an_agent_runs_a_screen_and_a_backtest(server, session: Session) -> None:
    _seed(session)
    screen = await _call(server, "screen", {"rule": "close > sma(close, 20)"})
    assert screen["ok"] and screen["source"] == "/v1/screener"
    assert "rows" in screen["data"] and screen["data"]["rule"] is not None
    run = await _call(
        server,
        "backtest_strategy",
        {
            "ticker": "wave",
            "entry_rule": "close crosses_above sma(close, 20)",
            "exit_rule": "close crosses_below sma(close, 20)",
            "years": 2,
        },
    )
    assert run["ok"] and run["source"] == "/v1/backtest/strategy"
    assert run["data"]["trade_count"] > 0 and run["data"]["summary"] is not None
    assert run["data"]["strategy_hash"] and run["data"]["data_fingerprint"]


async def test_refusals_come_back_as_results_with_their_source(server) -> None:
    out = await _call(server, "symbol_summary", {"ticker": "NOPE"})
    assert out["ok"] is False and out["status"] == 404
    off = await _call(server, "journal_stats", {})
    assert off["ok"] is False and "STOCKVIZ_MCP_USER_ID" in off["detail"]


async def test_journal_stats_signs_as_the_configured_user(server, monkeypatch) -> None:
    monkeypatch.setenv("STOCKVIZ_MCP_USER_ID", "1")
    out = await _call(server, "journal_stats", {})
    # User 1 may not exist in the test database; the point is the call is signed.
    assert out["source"] == "/v1/journal/stats" and out.get("status") != 401
