"""Stale-close market fills and repeated submissions (#67, audit LG-10).

A market order is refused (409) when the symbol's newest close trails the
newest close of active symbols in its currency. A ``client_order_id`` makes a
trade or pending order safe to repeat: the same key returns the first one, and
the same key with a different order is a 409.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import PriceBar, Symbol, Trade, User
from stockviz.models.order import PendingOrder
from stockviz.services.trading import ensure_default_portfolio
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
THURSDAY = datetime(2026, 11, 5)
FRIDAY = datetime(2026, 11, 6)


def _headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _bar(ticker: str, ts: datetime, close: str = "100") -> PriceBar:
    value = Decimal(close)
    return PriceBar(
        ticker=ticker,
        ts=ts,
        interval="1d",
        open=value,
        high=value,
        low=value,
        close=value,
        volume=1_000,
        source="test",
    )


def _seed(session: Session, *, aapl_day: datetime, msft_day: datetime = FRIDAY) -> int:
    session.add_all(
        [
            Symbol(ticker="AAPL", name="Apple"),
            Symbol(ticker="MSFT", name="Microsoft"),
            Symbol(ticker="SAP.DE", name="SAP", currency="EUR"),
        ]
    )
    user = User(email="keys@stockviz.dev", name="Keys")
    session.add(user)
    session.commit()
    session.add_all(
        [
            _bar("AAPL", aapl_day),
            _bar("MSFT", msft_day),
            # A later close in another currency never makes a USD symbol stale.
            _bar("SAP.DE", datetime(2026, 11, 9)),
        ]
    )
    session.commit()
    assert user.id is not None
    return user.id


def _buy(client: TestClient, user_id: int, **extra: object):
    body = {"ticker": "AAPL", "side": "buy", "quantity": "2", **extra}
    return client.post("/v1/trades", json=body, headers=_headers(user_id))


def _cash(session: Session, user_id: int) -> Decimal:
    portfolio = ensure_default_portfolio(session, user_id)
    session.refresh(portfolio)
    return portfolio.cash_balance


def test_market_order_refused_when_close_trails_its_market(
    session: Session, client: TestClient
) -> None:
    user_id = _seed(session, aapl_day=THURSDAY)

    response = _buy(client, user_id)

    assert response.status_code == 409
    assert "2026-11-05" in response.json()["detail"]
    assert "2026-11-06" in response.json()["detail"]
    assert session.exec(select(Trade)).all() == []


def test_market_order_fills_when_the_whole_market_shares_the_close(
    session: Session, client: TestClient
) -> None:
    # A weekend or a market holiday: every USD symbol stops at Friday.
    user_id = _seed(session, aapl_day=FRIDAY)

    response = _buy(client, user_id)

    assert response.status_code == 201
    assert Decimal(response.json()["price"]) == Decimal(100)


def test_inactive_symbols_do_not_set_the_market_close(session: Session, client: TestClient) -> None:
    user_id = _seed(session, aapl_day=THURSDAY, msft_day=FRIDAY)
    msft = session.get(Symbol, "MSFT")
    assert msft is not None
    msft.is_active = False
    session.add(msft)
    session.commit()

    assert _buy(client, user_id).status_code == 201


def test_repeated_client_order_id_fills_once(session: Session, client: TestClient) -> None:
    user_id = _seed(session, aapl_day=FRIDAY)

    first = _buy(client, user_id, client_order_id="ticket-1")
    second = _buy(client, user_id, client_order_id="ticket-1")

    assert first.status_code == 201
    assert second.status_code == 201
    replay, original = second.json(), first.json()
    # The stored rate reads back as "1.00000000"; the value is the same.
    assert Decimal(replay.pop("fx_rate")) == Decimal(original.pop("fx_rate"))
    assert replay == original
    assert len(session.exec(select(Trade)).all()) == 1
    assert _cash(session, user_id) == Decimal("100000") - Decimal("200")


def test_client_order_id_naming_a_different_order_is_a_conflict(
    session: Session, client: TestClient
) -> None:
    user_id = _seed(session, aapl_day=FRIDAY)
    assert _buy(client, user_id, client_order_id="ticket-1").status_code == 201

    response = _buy(client, user_id, client_order_id="ticket-1", quantity="3")

    assert response.status_code == 409
    assert "buy 2" in response.json()["detail"]
    assert len(session.exec(select(Trade)).all()) == 1


def test_orders_without_a_key_still_fill_each_time(session: Session, client: TestClient) -> None:
    user_id = _seed(session, aapl_day=FRIDAY)

    assert _buy(client, user_id).status_code == 201
    assert _buy(client, user_id).status_code == 201

    assert len(session.exec(select(Trade)).all()) == 2


def test_client_order_ids_are_per_portfolio(session: Session, client: TestClient) -> None:
    user_id = _seed(session, aapl_day=FRIDAY)
    other = User(email="other@stockviz.dev", name="Other")
    session.add(other)
    session.commit()
    assert other.id is not None

    assert _buy(client, user_id, client_order_id="shared").status_code == 201
    assert _buy(client, other.id, client_order_id="shared").status_code == 201

    assert len(session.exec(select(Trade)).all()) == 2


def test_client_order_id_shape_is_checked(session: Session, client: TestClient) -> None:
    user_id = _seed(session, aapl_day=FRIDAY)

    assert _buy(client, user_id, client_order_id="has spaces").status_code == 422
    assert _buy(client, user_id, client_order_id="x" * 65).status_code == 422
    assert _buy(client, user_id, client_order_id="").status_code == 422


def _limit(client: TestClient, user_id: int, **extra: object):
    body = {
        "ticker": "AAPL",
        "side": "buy",
        "order_type": "limit",
        "quantity": "2",
        "limit_price": "90",
        **extra,
    }
    return client.post("/v1/orders", json=body, headers=_headers(user_id))


def test_repeated_pending_order_is_placed_once(session: Session, client: TestClient) -> None:
    user_id = _seed(session, aapl_day=FRIDAY)

    first = _limit(client, user_id, client_order_id="limit-1")
    second = _limit(client, user_id, client_order_id="limit-1")

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert len(session.exec(select(PendingOrder)).all()) == 1


def test_pending_order_key_naming_a_different_order_is_a_conflict(
    session: Session, client: TestClient
) -> None:
    user_id = _seed(session, aapl_day=FRIDAY)
    assert _limit(client, user_id, client_order_id="limit-1").status_code == 201

    response = _limit(client, user_id, client_order_id="limit-1", limit_price="95")

    assert response.status_code == 409
    assert len(session.exec(select(PendingOrder)).all()) == 1


def _priced_aapl(session: Session) -> None:
    from datetime import timedelta

    for day in range(40):
        session.add(_bar("AAPL", datetime(2026, 9, 1) + timedelta(days=day), str(100 + day % 5)))
    session.commit()


def _open(client: TestClient, user_id: int, **extra: object):
    from datetime import timedelta

    from stockviz._time import utcnow

    body = {
        "action": "open",
        "ticker": "AAPL",
        "option_type": "call",
        "strike": "100",
        "expiry": (utcnow().date() + timedelta(days=60)).isoformat(),
        "quantity": 1,
        **extra,
    }
    return client.post("/v1/options/trade", json=body, headers=_headers(user_id))


def test_repeated_option_open_charges_once(session: Session, client: TestClient) -> None:
    from stockviz.models.option import OptionsPosition

    user_id = _seed(session, aapl_day=FRIDAY)
    _priced_aapl(session)

    first = _open(client, user_id, client_order_id="option-1")
    second = _open(client, user_id, client_order_id="option-1")

    assert first.status_code == 201, first.text
    assert second.status_code == 201
    assert second.json()["position"]["id"] == first.json()["position"]["id"]
    assert len(session.exec(select(OptionsPosition)).all()) == 1
    premium = Decimal(first.json()["position"]["premium_paid"])
    assert _cash(session, user_id) == Decimal("100000") - premium


def test_option_key_naming_a_different_contract_is_a_conflict(
    session: Session, client: TestClient
) -> None:
    user_id = _seed(session, aapl_day=FRIDAY)
    _priced_aapl(session)
    assert _open(client, user_id, client_order_id="option-1").status_code == 201

    assert _open(client, user_id, client_order_id="option-1", strike="105").status_code == 409
