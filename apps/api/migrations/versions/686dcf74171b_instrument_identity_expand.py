"""instrument identity expand

Revision ID: 686dcf74171b
Revises: 99489c8896a9
Create Date: 2026-11-12

Phase 4.3, the additive step of the identity migration (workspace
``docs/phase-4-design-note.md`` section 2). Nothing here is destructive and
nothing reads the new columns yet.

1. ``instruments`` and ``instrument_identifiers``.
2. SQL functions that derive an instrument from a ``symbols`` row
   (``stockviz_ensure_instrument``): venue from ``symbols.exchange`` (yfinance
   codes such as NMS, NYQ, LSE, GER, NSI), else the Yahoo suffix, else the
   Aegis venue list for the 25 US seed symbols; ``GBX`` as the quote unit for
   London (audit MD-2: yfinance quotes ``GBp``); Nifty tickers typed
   ``index`` and ``COMMODITY`` rows ``commodity``.
3. One instrument per existing symbol, with ``yahoo`` (the ticker) and
   ``aegis`` (``stockviz:<ticker>``) identifiers.
4. A nullable ``instrument_id`` (FK, indexed) beside each of the 17 ``ticker``
   columns, backfilled.
5. Dual write: a trigger on every one of those tables fills ``instrument_id``
   from ``ticker`` on insert and on a ticker change (this covers the bulk
   ``price_bars`` upsert, which bypasses the ORM), and a trigger on
   ``symbols`` creates the instrument for a new symbol and fills its venue
   once ``metadata`` records the exchange.

Downgrade removes all of it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "686dcf74171b"
down_revision: str | None = "99489c8896a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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

# Aegis' verified venues for the US seed symbols
# (aegis-news/data/instruments/stockviz.json), used when symbols.exchange is
# empty (a database where `metadata` has not run).
_US_XNAS = (
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "NVDA",
    "WMT",
    "INTC",
    "CSCO",
    "ADBE",
    "NFLX",
)
_US_XNYS = ("JPM", "JNJ", "V", "PG", "MA", "UNH", "HD", "BAC", "XOM", "PFE", "DIS", "CRM", "KO")


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


FUNCTIONS = rf"""
CREATE OR REPLACE FUNCTION stockviz_mic(p_ticker text, p_exchange text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN upper(coalesce(p_exchange, '')) IN ('NMS', 'NGM', 'NCM', 'NAS', 'NASDAQ') THEN 'XNAS'
    WHEN upper(coalesce(p_exchange, '')) IN ('NYQ', 'NYSE') THEN 'XNYS'
    WHEN upper(coalesce(p_exchange, '')) IN ('ASE', 'AMEX') THEN 'XASE'
    WHEN upper(coalesce(p_exchange, '')) IN ('PCX', 'ARCA') THEN 'ARCX'
    WHEN upper(coalesce(p_exchange, '')) IN ('LSE', 'LON') THEN 'XLON'
    WHEN upper(coalesce(p_exchange, '')) IN ('GER', 'ETR', 'XETRA') THEN 'XETR'
    WHEN upper(coalesce(p_exchange, '')) IN ('TOR', 'TSX') THEN 'XTSE'
    WHEN upper(coalesce(p_exchange, '')) IN ('JPX', 'TYO') THEN 'XTKS'
    WHEN upper(coalesce(p_exchange, '')) IN ('NSE', 'NSI') THEN 'XNSE'
    WHEN upper(coalesce(p_exchange, '')) IN ('BSE', 'BOM') THEN 'XBOM'
    WHEN upper(coalesce(p_exchange, '')) = 'COMMODITY' THEN NULL
    WHEN p_ticker ~* '\.NS$' THEN 'XNSE'
    WHEN p_ticker ~* '\.BO$' THEN 'XBOM'
    WHEN p_ticker ~* '\.L$' THEN 'XLON'
    WHEN p_ticker ~* '\.DE$' THEN 'XETR'
    WHEN p_ticker ~* '\.TO$' THEN 'XTSE'
    WHEN p_ticker ~* '\.T$' THEN 'XTKS'
    WHEN p_ticker IN ({_sql_list(_US_XNAS)}) THEN 'XNAS'
    WHEN p_ticker IN ({_sql_list(_US_XNYS)}) THEN 'XNYS'
    ELSE NULL
  END
$$;

CREATE OR REPLACE FUNCTION stockviz_country(p_mic text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE p_mic
    WHEN 'XNAS' THEN 'US' WHEN 'XNYS' THEN 'US' WHEN 'XASE' THEN 'US' WHEN 'ARCX' THEN 'US'
    WHEN 'XLON' THEN 'GB' WHEN 'XETR' THEN 'DE' WHEN 'XTSE' THEN 'CA' WHEN 'XTKS' THEN 'JP'
    WHEN 'XNSE' THEN 'IN' WHEN 'XBOM' THEN 'IN'
    ELSE NULL
  END
$$;

CREATE OR REPLACE FUNCTION stockviz_asset_type(p_ticker text, p_exchange text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN upper(coalesce(p_exchange, '')) = 'COMMODITY' THEN 'commodity'
    WHEN p_ticker ~* '^(NIFTY|BANKNIFTY|MIDCAP|SMALLCAP)' THEN 'index'
    ELSE 'equity'
  END
$$;

CREATE OR REPLACE FUNCTION stockviz_ensure_instrument(p_ticker text) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
  v_id bigint;
  s record;
  v_mic text;
  v_unit text;
  v_since date;
BEGIN
  SELECT instrument_id INTO v_id FROM instrument_identifiers
   WHERE scheme = 'yahoo' AND value = p_ticker AND valid_to IS NULL
   ORDER BY valid_from DESC LIMIT 1;
  IF v_id IS NOT NULL THEN
    RETURN v_id;
  END IF;
  SELECT * INTO s FROM symbols WHERE ticker = p_ticker;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  v_mic := stockviz_mic(s.ticker, s.exchange);
  v_unit := CASE WHEN v_mic = 'XLON' AND s.currency = 'GBP' THEN 'GBX' ELSE s.currency END;
  v_since := coalesce(s.created_at::date, current_date);
  BEGIN
    INSERT INTO instruments (symbol, mic, country, currency, quote_unit, asset_type, status, created_at)
    VALUES (
      regexp_replace(s.ticker, '\.(NS|BO|L|DE|TO|T)$', '', 'i'), v_mic, stockviz_country(v_mic),
      s.currency, v_unit, stockviz_asset_type(s.ticker, s.exchange),
      CASE WHEN s.is_active THEN 'active' ELSE 'inactive' END, now() AT TIME ZONE 'utc'
    )
    RETURNING id INTO v_id;
  EXCEPTION WHEN unique_violation THEN
    -- Two tickers that share a venue symbol: keep the full ticker as the symbol.
    INSERT INTO instruments (symbol, mic, country, currency, quote_unit, asset_type, status, created_at)
    VALUES (
      s.ticker, v_mic, stockviz_country(v_mic), s.currency, v_unit,
      stockviz_asset_type(s.ticker, s.exchange),
      CASE WHEN s.is_active THEN 'active' ELSE 'inactive' END, now() AT TIME ZONE 'utc'
    )
    RETURNING id INTO v_id;
  END;
  INSERT INTO instrument_identifiers (instrument_id, scheme, value, valid_from)
  VALUES (v_id, 'yahoo', s.ticker, v_since), (v_id, 'aegis', 'stockviz:' || s.ticker, v_since);
  RETURN v_id;
END
$$;

CREATE OR REPLACE FUNCTION stockviz_fill_instrument_id() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.ticker IS NULL THEN
    NEW.instrument_id := NULL;
  ELSE
    NEW.instrument_id := stockviz_ensure_instrument(NEW.ticker);
  END IF;
  RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION stockviz_symbol_instrument() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_id bigint;
  v_mic text;
BEGIN
  v_id := stockviz_ensure_instrument(NEW.ticker);
  IF TG_OP = 'UPDATE' AND v_id IS NOT NULL THEN
    v_mic := stockviz_mic(NEW.ticker, NEW.exchange);
    UPDATE instruments SET
      mic = coalesce(mic, v_mic),
      country = coalesce(country, stockviz_country(coalesce(mic, v_mic))),
      status = CASE WHEN NEW.is_active THEN 'active' ELSE 'inactive' END
    WHERE id = v_id;
  END IF;
  RETURN NULL;
END
$$;
"""

DROP_FUNCTIONS = """
DROP FUNCTION IF EXISTS stockviz_symbol_instrument();
DROP FUNCTION IF EXISTS stockviz_fill_instrument_id();
DROP FUNCTION IF EXISTS stockviz_ensure_instrument(text);
DROP FUNCTION IF EXISTS stockviz_asset_type(text, text);
DROP FUNCTION IF EXISTS stockviz_country(text);
DROP FUNCTION IF EXISTS stockviz_mic(text, text);
"""


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("mic", sa.String(length=4), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("quote_unit", sa.String(length=3), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("listed_on", sa.Date(), nullable=True),
        sa.Column("delisted_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "mic", name="uq_instruments_symbol_mic"),
    )
    op.create_table(
        "instrument_identifiers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("scheme", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scheme", "value", "valid_from", name="uq_instrument_identifiers_scheme_value_from"
        ),
    )
    op.create_index(
        "ix_instrument_identifiers_instrument_id", "instrument_identifiers", ["instrument_id"]
    )

    op.execute(FUNCTIONS)
    op.execute("SELECT stockviz_ensure_instrument(ticker) FROM symbols ORDER BY ticker")

    for table in TICKER_TABLES:
        op.add_column(table, sa.Column("instrument_id", sa.BigInteger(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_instrument_id", table, "instruments", ["instrument_id"], ["id"]
        )
        op.execute(
            f"UPDATE {table} AS t SET instrument_id = i.instrument_id "
            "FROM instrument_identifiers AS i "
            "WHERE i.scheme = 'yahoo' AND i.value = t.ticker AND i.valid_to IS NULL"
        )
        op.create_index(f"ix_{table}_instrument_id", table, ["instrument_id"])
        op.execute(
            f"CREATE TRIGGER trg_{table}_instrument_id BEFORE INSERT OR UPDATE OF ticker "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION stockviz_fill_instrument_id()"
        )

    op.execute(
        "CREATE TRIGGER trg_symbols_instrument AFTER INSERT OR UPDATE OF exchange, is_active "
        "ON symbols FOR EACH ROW EXECUTE FUNCTION stockviz_symbol_instrument()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_symbols_instrument ON symbols")
    for table in reversed(TICKER_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_instrument_id ON {table}")
        op.drop_index(f"ix_{table}_instrument_id", table_name=table)
        op.drop_constraint(f"fk_{table}_instrument_id", table, type_="foreignkey")
        op.drop_column(table, "instrument_id")
    op.execute(DROP_FUNCTIONS)
    op.drop_index("ix_instrument_identifiers_instrument_id", table_name="instrument_identifiers")
    op.drop_table("instrument_identifiers")
    op.drop_table("instruments")
