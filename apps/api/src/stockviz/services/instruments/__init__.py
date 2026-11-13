"""Instrument identity (Phase 4.3). See ``models/instrument.py``."""

TICKER_TABLES = (
    "alerts",
    "comments",
    "corporate_actions",
    "dividends",
    "earnings_events",
    "news_articles",
    "options_positions",
    "pending_orders",
    "portfolio_dividends",
    "positions",
    "price_bar_quarantine",
    "price_bars",
    "recommendations",
    "replay_sessions",
    "symbol_metrics",
    "trades",
    "watchlist_items",
)
"""Every table with a ``ticker`` foreign key, and so an ``instrument_id``.
The 4.3 migration keeps its own copy, as migrations must not import app code."""


def instrument_of(ticker):
    """SQL scalar: the instrument a public ticker names today (Phase 4.4).

    ``ticker`` is a string or a ticker column (correlated, e.g.
    ``Position.ticker``). Reads filter ``X.instrument_id == instrument_of(t)``
    instead of ``X.ticker == t``: the ``yahoo`` identifier is the resolver, so
    a renamed listing keeps its history once 4.6 drops the ticker keys.
    """
    from sqlmodel import col, select

    from stockviz.models.instrument import SCHEME_YAHOO, InstrumentIdentifier

    return (
        select(InstrumentIdentifier.instrument_id)
        .where(
            col(InstrumentIdentifier.scheme) == SCHEME_YAHOO,
            col(InstrumentIdentifier.value) == ticker,
            col(InstrumentIdentifier.valid_to).is_(None),
        )
        .order_by(col(InstrumentIdentifier.valid_from).desc())
        .limit(1)
        # Correlate a ticker column to whichever enclosing query holds it, even
        # through a LATERAL (recent_bars): implicit correlation only looks one
        # level up and would otherwise add that table to this FROM.
        .correlate_except(InstrumentIdentifier)
        .scalar_subquery()
    )


def instruments_of(tickers):
    """SQL subquery: the instruments a collection of public tickers name."""
    from sqlmodel import col, select

    from stockviz.models.instrument import SCHEME_YAHOO, InstrumentIdentifier

    return select(InstrumentIdentifier.instrument_id).where(
        col(InstrumentIdentifier.scheme) == SCHEME_YAHOO,
        col(InstrumentIdentifier.value).in_(list(tickers)),
        col(InstrumentIdentifier.valid_to).is_(None),
    )


def resolve_symbol(session, symbol: str):
    """The ``Instrument`` behind a public symbol (today's ticker), or None.

    Routers keep their URLs (``/stocks/AAPL``); this is the one place a public
    symbol becomes an instrument.
    """
    from sqlmodel import col, select

    from stockviz.models.instrument import SCHEME_YAHOO, Instrument, InstrumentIdentifier

    return session.exec(
        select(Instrument)
        .join(InstrumentIdentifier, col(InstrumentIdentifier.instrument_id) == col(Instrument.id))
        .where(
            col(InstrumentIdentifier.scheme) == SCHEME_YAHOO,
            col(InstrumentIdentifier.value) == symbol.upper(),
            col(InstrumentIdentifier.valid_to).is_(None),
        )
        .order_by(col(InstrumentIdentifier.valid_from).desc())
    ).first()


def instrument_ids(session, tickers) -> dict[str, int]:
    """Ticker -> current instrument id, for bulk writes that skip the ORM (Phase 4.6b).

    A ticker with no instrument (no symbol) is absent from the result; the
    write then fails on the NOT NULL ``instrument_id``, as it should.
    """
    from sqlmodel import col, select

    from stockviz.models.instrument import SCHEME_YAHOO, InstrumentIdentifier

    wanted = sorted(set(tickers))
    if not wanted:
        return {}
    rows = session.exec(
        select(InstrumentIdentifier.value, InstrumentIdentifier.instrument_id)
        .where(
            col(InstrumentIdentifier.scheme) == SCHEME_YAHOO,
            col(InstrumentIdentifier.value).in_(wanted),
            col(InstrumentIdentifier.valid_to).is_(None),
        )
        .order_by(col(InstrumentIdentifier.valid_from))
    ).all()
    return dict(rows)


def is_index_ticker(ticker: str) -> bool:
    """Benchmarks (Phase 7.4): Yahoo index tickers start with ``^``.

    Indices are instruments of asset type ``index``: bars are stored and
    studied, but they are never traded and stay out of the screener, the
    markets table and the signals.
    """
    return ticker.startswith("^")
