"""Phase 6.6, audit RS-12: the watchlist reads bars once, not once per item."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy import event
from sqlmodel import Session

from stockviz.models import PriceBar, User
from stockviz.settings import get_settings
from tests.symbols import seed_symbols


def test_one_bars_query_for_the_whole_list(session: Session, client: TestClient) -> None:
    tickers = ["AAPL", "MSFT", "INFY.NS"]
    for t in tickers:
        seed_symbols(session, t)
        for i in range(40):
            c = Decimal(100 + i)
            session.add(
                PriceBar(
                    ticker=t, ts=datetime(2026, 9, 1) + timedelta(days=i), interval="1d",
                    open=c, high=c, low=c, close=c, volume=1, source="test",
                )
            )  # fmt: skip
    user = User(email="wl@stockviz.dev", name="W")
    session.add(user)
    session.commit()
    assert user.id is not None
    token = jose_jwt.encode({"sub": str(user.id)}, get_settings().internal_api_token, "HS256")
    headers = {"Authorization": f"Bearer {token}"}
    for t in tickers:
        assert client.post(f"/v1/watchlist/{t}", headers=headers).status_code == 201

    statements: list[str] = []
    bind = session.get_bind()

    def count(_conn, _cursor, statement, *_args):
        if "price_bars" in statement:
            statements.append(statement)

    event.listen(bind, "before_cursor_execute", count)
    try:
        rows = client.get("/v1/watchlist", headers=headers).json()
    finally:
        event.remove(bind, "before_cursor_execute", count)

    assert len(statements) == 1  # was one per item
    assert {r["ticker"] for r in rows} == set(tickers)
    row = rows[0]
    assert len(row["closes"]) == 30 and Decimal(row["closes"][-1]) == Decimal(row["last_close"])
