"""News and portfolio alert rules, and the notification centre (Phase 7.2).

Phase 7's acceptance: "An alert fires from a price, a technical and a news
condition, with history and deduplication."
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import (
    AegisEvent,
    Alert,
    AlertDirection,
    AlertEvent,
    AlertKind,
    AlertRepeat,
    Notification,
    OrderType,
    PortfolioSnapshot,
    PriceBar,
    TradeSide,
    User,
)
from stockviz.services.alerts import evaluate_pending_alerts
from stockviz.services.trading import ensure_default_portfolio
from stockviz.services.trading.orders import create_pending_order, settle_pending_orders
from stockviz.settings import get_settings
from tests.test_aegis_news import _document, _symbols

DAY0 = datetime(2025, 1, 6)


def _user(session: Session, email: str = "n@stockviz.dev") -> int:
    user = User(email=email, name="N")
    session.add(user)
    session.commit()
    assert user.id is not None
    return user.id


def _bars(session: Session, closes: list[float] | list[int], ticker: str = "AAPL") -> None:
    for day, close in enumerate(closes):
        c = Decimal(str(close))
        session.add(
            PriceBar(
                ticker=ticker, ts=DAY0 + timedelta(days=day), interval="1d",
                open=c, high=c, low=c, close=c, volume=1000, source="test",
            )
        )  # fmt: skip
    session.commit()


def _alert_notices(session: Session) -> list[Notification]:
    return list(session.exec(select(Notification).where(Notification.category == "alert")).all())


def test_price_technical_and_news_rules_fire_once_each(session: Session) -> None:
    """Phase 7 acceptance: three conditions, history, deduplication."""
    _symbols(session)  # AAPL, MSFT, TSLA and their Aegis mappings
    user = _user(session)
    # 40 rising closes then a fall: last close 98, RSI 14 well under 30.
    closes = [100 + i for i in range(40)] + [140 - 6 * i for i in range(1, 8)]
    _bars(session, closes)
    armed = utcnow() - timedelta(days=3)
    session.add_all(
        [
            Alert(user_id=user, ticker="AAPL", direction=AlertDirection.BELOW,
                  target_price=Decimal(100), armed_at=armed),
            Alert(user_id=user, ticker="AAPL", kind=AlertKind.TECHNICAL, armed_at=armed,
                  params={"indicator": "rsi_14", "op": "below", "value": 30.0}),
            Alert(user_id=user, ticker="AAPL", kind=AlertKind.NEWS, armed_at=armed,
                  params={"sentiment": "negative", "event_type": None}),
        ]
    )  # fmt: skip
    session.commit()
    _document(session, "doc_neg", tickers=["AAPL"], available_at=utcnow() - timedelta(days=1),
              sentiment=("negative", -0.7))  # fmt: skip
    _document(session, "doc_pos", tickers=["AAPL"], available_at=utcnow() - timedelta(days=1),
              sentiment=("positive", 0.6))  # fmt: skip
    _document(session, "doc_early", tickers=["AAPL"], available_at=armed - timedelta(days=1),
              sentiment=("negative", -0.9))  # fmt: skip

    assert evaluate_pending_alerts(session) == 3
    assert evaluate_pending_alerts(session) == 0  # the second night writes nothing

    events = session.exec(select(AlertEvent)).all()
    assert sorted(e.kind for e in events) == ["news", "price", "technical"]
    news = next(e for e in events if e.kind == "news")
    assert news.source == "document:doc_neg" and "Headline doc_neg (negative)" in news.message
    notices = _alert_notices(session)
    assert len(notices) == 3
    assert {n.link for n in notices} == {f"/alerts?rule={e.alert_id}" for e in events}


def test_a_news_rule_can_require_an_event_type(session: Session) -> None:
    _symbols(session)
    user = _user(session)
    armed = utcnow() - timedelta(days=3)
    session.add(
        Alert(user_id=user, ticker="AAPL", kind=AlertKind.NEWS, armed_at=armed,
              params={"sentiment": None, "event_type": "earnings"},
              repeat=AlertRepeat.EVERY_CROSS)
    )  # fmt: skip
    session.commit()
    when = utcnow() - timedelta(hours=5)
    _document(session, "doc_a", tickers=["AAPL"], available_at=when)
    _document(session, "doc_b", tickers=["AAPL"], available_at=when)
    session.add(
        AegisEvent(event_id="ev_1", revision=1, document_id="doc_b", event_type="Earnings",
                   available_at=when, evidence_kind="text")
    )  # fmt: skip
    session.commit()
    assert evaluate_pending_alerts(session) == 1
    (event,) = session.exec(select(AlertEvent)).all()
    assert event.source == "document:doc_b"


def test_a_drawdown_rule_fires_when_the_account_falls_past_it(session: Session) -> None:
    user = _user(session)
    portfolio = ensure_default_portfolio(session, user)  # $100,000 cash
    session.add(
        Alert(user_id=user, kind=AlertKind.PORTFOLIO,
              params={"metric": "drawdown_pct", "threshold": 10.0})
    )  # fmt: skip
    session.commit()
    day1 = datetime(2026, 11, 10, 23)
    assert evaluate_pending_alerts(session, now=day1) == 0  # records state only
    # A peak of $120,000 on a stored snapshot; the live value is $100,000.
    session.add(
        PortfolioSnapshot(user_id=user, date=datetime(2026, 11, 9).date(), nav=Decimal(120000))
    )
    session.commit()
    assert evaluate_pending_alerts(session, now=day1) == 0  # same session: judged
    assert evaluate_pending_alerts(session, now=day1 + timedelta(days=1)) == 1
    (event,) = session.exec(select(AlertEvent)).all()
    assert event.observed is not None and round(event.observed, 2) == Decimal("16.67")
    assert "below its peak of 120,000.00" in event.message and "(USD)" in event.message
    assert portfolio.id is not None


def test_settlement_tells_the_owner(session: Session) -> None:
    _symbols(session)
    user = _user(session)
    ensure_default_portfolio(session, user)
    _bars(session, [100, 90])
    filled = create_pending_order(
        session, user_id=user, ticker="AAPL", side=TradeSide.BUY,
        order_type=OrderType.LIMIT, quantity=Decimal(2), limit_price=Decimal(95),
    )  # fmt: skip
    settle_pending_orders(session)
    refused = create_pending_order(
        session, user_id=user, ticker="AAPL", side=TradeSide.BUY,
        order_type=OrderType.LIMIT, quantity=Decimal(1000), limit_price=Decimal(99),
    )  # fmt: skip
    # Spend the cash the second order reserved, so it fails at settlement.
    from stockviz.models import Portfolio

    portfolio = session.exec(select(Portfolio).where(Portfolio.user_id == user)).one()
    portfolio.cash_balance = Decimal(500)
    session.add(portfolio)
    session.commit()
    settle_pending_orders(session)
    settle_pending_orders(session)  # a rerun adds nothing

    rows = {n.source_key: n for n in session.exec(select(Notification)).all()}
    assert rows[f"order:{filled.id}:filled"].body.startswith("Filled at 90.00 USD")
    assert rows[f"order:{filled.id}:filled"].link == "/orders?status=filled"
    assert rows[f"order:{refused.id}:cancelled"].title == "Limit buy 1000 AAPL cancelled"
    assert len(rows) == 2


def _headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, get_settings().internal_api_token, "HS256")
    return {"Authorization": f"Bearer {token}"}


def test_the_notification_centre_api(session: Session, client: TestClient) -> None:
    from stockviz.models import NotificationCategory
    from stockviz.services.notifications import notify

    me, other = _user(session), _user(session, "other@stockviz.dev")
    for i in range(3):
        notify(session, user_id=me, category=NotificationCategory.SYSTEM, title=f"t{i}",
               body="b", source_key=f"k{i}")  # fmt: skip
    notify(session, user_id=me, category=NotificationCategory.SYSTEM, title="dup", body="b",
           source_key="k0")  # fmt: skip
    notify(session, user_id=other, category=NotificationCategory.ORDER, title="theirs",
           body="b", source_key="k9")  # fmt: skip
    session.commit()
    h = _headers(me)

    rows = client.get("/v1/notifications", headers=h).json()
    assert [r["title"] for r in rows] == ["t2", "t1", "t0"]
    assert client.get("/v1/notifications/unread-count", headers=h).json() == {"unread": 3}
    page = client.get(f"/v1/notifications?before_id={rows[0]['id']}&limit=1", headers=h).json()
    assert [r["title"] for r in page] == ["t1"]

    assert client.post(f"/v1/notifications/{rows[0]['id']}/read", headers=h).json()["read_at"]
    assert client.get("/v1/notifications?unread=true", headers=h).json()[0]["title"] == "t1"
    theirs = session.exec(select(Notification).where(Notification.user_id == other)).one()
    assert client.post(f"/v1/notifications/{theirs.id}/read", headers=h).status_code == 404
    assert client.post("/v1/notifications/read-all", headers=h).json() == {"unread": 0}
    assert client.get("/v1/notifications/unread-count", headers=h).json() == {"unread": 0}
    assert client.get("/v1/notifications?category=order", headers=h).json() == []
