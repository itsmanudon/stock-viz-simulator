"""Local browser-test fixture: make historical fills through real accounting.

Only run against an explicitly named disposable journal verification database.
The production application never imports this module.
"""

import os
import sys
from datetime import datetime
from decimal import Decimal

from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine, select
from stockviz.models import PriceBar, Symbol, TradeSide, User
from stockviz.services.trading.execute import apply_fill, ensure_default_portfolio

url = os.environ["JOURNAL_TEST_DATABASE_URL"]
if not (make_url(url).database or "").startswith("stockviz_journal_verify_"):
    raise RuntimeError("Journal fixtures require an isolated verification database")
with Session(create_engine(url)) as session:
    user = session.exec(select(User).where(User.email == sys.argv[1])).one()
    portfolio = ensure_default_portfolio(session, user.id)
    if session.get(Symbol, "AAPL") is None:
        session.add(Symbol(ticker="AAPL", name="Apple Inc.", currency="USD"))
        session.flush()
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=datetime(2026, 8, 28),
                interval="1d",
                open=Decimal(120),
                high=Decimal(120),
                low=Decimal(120),
                close=Decimal(120),
                volume=1000000,
                source="test",
            )
        )
        session.commit()
    for month, day, pnl in [
        (7, 7, 100),
        (7, 9, 240),
        (7, 15, 40),
        (7, 23, 500),
        (8, 3, 100),
        (8, 5, -80),
        (8, 12, 50),
        (8, 19, 272),
        (8, 20, -120),
        (8, 21, 0),
        (8, 26, 400),
    ]:
        for side, price in [
            (TradeSide.BUY, Decimal(100)),
            (TradeSide.SELL, Decimal(100) + Decimal(pnl) / 10),
        ]:
            result = apply_fill(
                session,
                portfolio=portfolio,
                ticker="AAPL",
                side=side,
                quantity=Decimal(10),
                price=price,
                currency="USD",
                fx_rate=Decimal(1),
            )
            result.trade.ts = datetime(
                2026, month, day, 17 if side == TradeSide.BUY else 18
            )
            session.add(result.trade)
            session.commit()
print("Seeded browser-test fills through apply_fill")
