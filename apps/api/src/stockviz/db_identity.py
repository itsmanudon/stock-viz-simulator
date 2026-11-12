"""Identity triggers for schemas built from the models (Phase 4.4a).

Production gets the instrument triggers from migration ``686dcf74171b``. A
schema built with ``SQLModel.metadata.create_all`` (the SQLite test engine,
the scratch Postgres engines) had none, so ``instrument_id`` stayed NULL there
and nothing could read through it. ``install`` runs after ``create_all``:

- PostgreSQL: the same functions and triggers as the migration (copied: a
  migration must not change when this module does, and this module is
  today's schema);
- SQLite (tests only): equivalent triggers in SQLite's dialect, with the
  same venue rules, written as AFTER triggers that update the new row.

``tests/test_instrument_identity_parity.py`` checks the SQLite rules give the
same instrument as the Postgres function for the same symbols.
"""

from __future__ import annotations

from sqlalchemy import Table, event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper
from sqlmodel import SQLModel

from stockviz.services.instruments import TICKER_TABLES

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


PG_FUNCTIONS = rf"""
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


_EXCHANGE = "upper(coalesce(NEW.exchange, ''))"

_SQLITE_MIC = f"""CASE
    WHEN {_EXCHANGE} IN ('NMS', 'NGM', 'NCM', 'NAS', 'NASDAQ') THEN 'XNAS'
    WHEN {_EXCHANGE} IN ('NYQ', 'NYSE') THEN 'XNYS'
    WHEN {_EXCHANGE} IN ('ASE', 'AMEX') THEN 'XASE'
    WHEN {_EXCHANGE} IN ('PCX', 'ARCA') THEN 'ARCX'
    WHEN {_EXCHANGE} IN ('LSE', 'LON') THEN 'XLON'
    WHEN {_EXCHANGE} IN ('GER', 'ETR', 'XETRA') THEN 'XETR'
    WHEN {_EXCHANGE} IN ('TOR', 'TSX') THEN 'XTSE'
    WHEN {_EXCHANGE} IN ('JPX', 'TYO') THEN 'XTKS'
    WHEN {_EXCHANGE} IN ('NSE', 'NSI') THEN 'XNSE'
    WHEN {_EXCHANGE} IN ('BSE', 'BOM') THEN 'XBOM'
    WHEN {_EXCHANGE} = 'COMMODITY' THEN NULL
    WHEN NEW.ticker LIKE '%.NS' THEN 'XNSE'
    WHEN NEW.ticker LIKE '%.BO' THEN 'XBOM'
    WHEN NEW.ticker LIKE '%.L' THEN 'XLON'
    WHEN NEW.ticker LIKE '%.DE' THEN 'XETR'
    WHEN NEW.ticker LIKE '%.TO' THEN 'XTSE'
    WHEN NEW.ticker LIKE '%.T' THEN 'XTKS'
    WHEN NEW.ticker IN ({_sql_list(_US_XNAS)}) THEN 'XNAS'
    WHEN NEW.ticker IN ({_sql_list(_US_XNYS)}) THEN 'XNYS'
    ELSE NULL
  END"""

_SQLITE_SYMBOL = """CASE
    WHEN NEW.ticker LIKE '%.NS' OR NEW.ticker LIKE '%.BO' OR NEW.ticker LIKE '%.DE'
      OR NEW.ticker LIKE '%.TO' THEN substr(NEW.ticker, 1, length(NEW.ticker) - 3)
    WHEN NEW.ticker LIKE '%.L' OR NEW.ticker LIKE '%.T'
      THEN substr(NEW.ticker, 1, length(NEW.ticker) - 2)
    ELSE NEW.ticker
  END"""

_SQLITE_COUNTRY_OF_MIC = """CASE {mic}
    WHEN 'XNAS' THEN 'US' WHEN 'XNYS' THEN 'US' WHEN 'XASE' THEN 'US' WHEN 'ARCX' THEN 'US'
    WHEN 'XLON' THEN 'GB' WHEN 'XETR' THEN 'DE' WHEN 'XTSE' THEN 'CA' WHEN 'XTKS' THEN 'JP'
    WHEN 'XNSE' THEN 'IN' WHEN 'XBOM' THEN 'IN' ELSE NULL END"""

_SQLITE_ASSET_TYPE = f"""CASE
    WHEN {_EXCHANGE} = 'COMMODITY' THEN 'commodity'
    WHEN upper(NEW.ticker) LIKE 'NIFTY%' OR upper(NEW.ticker) LIKE 'BANKNIFTY%'
      OR upper(NEW.ticker) LIKE 'MIDCAP%' OR upper(NEW.ticker) LIKE 'SMALLCAP%' THEN 'index'
    ELSE 'equity'
  END"""

_YAHOO_ID = (
    "(SELECT instrument_id FROM instrument_identifiers WHERE scheme = 'yahoo' "
    "AND value = NEW.ticker AND valid_to IS NULL ORDER BY valid_from DESC LIMIT 1)"
)


def _sqlite_backfill() -> str:
    """SQLite does not enforce foreign keys, and without an ORM relationship a
    flush may insert a symbol's bars before the symbol; fill those once the
    instrument exists. (Postgres rejects that order, so it needs no such step.)"""
    return "\n".join(
        f"  UPDATE {table} SET instrument_id = {_YAHOO_ID} "
        "WHERE ticker = NEW.ticker AND instrument_id IS NULL;"
        for table in TICKER_TABLES
    )


def _sqlite_statements() -> list[str]:
    mic = f"({_SQLITE_MIC})"
    statements = [
        f"""CREATE TRIGGER trg_symbols_instrument AFTER INSERT ON symbols
WHEN {_YAHOO_ID} IS NULL
BEGIN
  INSERT INTO instruments (symbol, mic, country, currency, quote_unit, asset_type, status, created_at)
  VALUES (
    {_SQLITE_SYMBOL}, {mic}, {_SQLITE_COUNTRY_OF_MIC.format(mic=mic)}, NEW.currency,
    CASE WHEN {mic} = 'XLON' AND NEW.currency = 'GBP' THEN 'GBX' ELSE NEW.currency END,
    {_SQLITE_ASSET_TYPE}, CASE WHEN NEW.is_active THEN 'active' ELSE 'inactive' END,
    CURRENT_TIMESTAMP
  );
  INSERT INTO instrument_identifiers (instrument_id, scheme, value, valid_from)
  VALUES ((SELECT max(id) FROM instruments), 'yahoo', NEW.ticker, date('now')),
         ((SELECT max(id) FROM instruments), 'aegis', 'stockviz:' || NEW.ticker, date('now'));
{_sqlite_backfill()}
END""",
        f"""CREATE TRIGGER trg_symbols_instrument_update AFTER UPDATE OF exchange, is_active ON symbols
WHEN {_YAHOO_ID} IS NOT NULL
BEGIN
  UPDATE instruments SET
    mic = coalesce(mic, {mic}),
    country = coalesce(country, {_SQLITE_COUNTRY_OF_MIC.format(mic=mic)}),
    status = CASE WHEN NEW.is_active THEN 'active' ELSE 'inactive' END
  WHERE id = {_YAHOO_ID};
END""",
    ]
    for table in TICKER_TABLES:
        for when, name in (("INSERT", "ins"), ("UPDATE OF ticker", "upd")):
            statements.append(
                f"""CREATE TRIGGER trg_{table}_instrument_id_{name} AFTER {when} ON {table}
BEGIN
  UPDATE {table} SET instrument_id = {_YAHOO_ID} WHERE rowid = NEW.rowid;
END"""
            )
    return statements


def _postgres_statements() -> list[str]:
    statements = [PG_FUNCTIONS]
    for table in TICKER_TABLES:
        statements.append(
            f"CREATE TRIGGER trg_{table}_instrument_id BEFORE INSERT OR UPDATE OF ticker "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION stockviz_fill_instrument_id()"
        )
    statements.append(
        "CREATE TRIGGER trg_symbols_instrument AFTER INSERT OR UPDATE OF exchange, is_active "
        "ON symbols FOR EACH ROW EXECUTE FUNCTION stockviz_symbol_instrument()"
    )
    return statements


def install(connection: Connection) -> None:
    """Create the identity triggers on a schema ``create_all`` just built."""
    dialect = connection.dialect.name
    if dialect == "postgresql":
        statements = _postgres_statements()
    elif dialect == "sqlite":
        statements = _sqlite_statements()
    else:
        return
    for statement in statements:
        # exec_driver_sql: function bodies hold ``::`` casts and ``stockviz:``.
        connection.exec_driver_sql(statement)


@event.listens_for(SQLModel.metadata, "after_create")
def _after_create(_target, connection: Connection, **_kw) -> None:
    install(connection)


_CURRENT_YAHOO_ID = text(
    "SELECT instrument_id FROM instrument_identifiers WHERE scheme = 'yahoo' "
    "AND value = :ticker AND valid_to IS NULL ORDER BY valid_from DESC LIMIT 1"
)


def instrument_id_for(connection: Connection, ticker: str) -> int | None:
    """The instrument a ticker names today, read on the writer's connection."""
    return connection.execute(_CURRENT_YAHOO_ID, {"ticker": ticker}).scalar()


def _set_instrument_id(_mapper, connection: Connection, target) -> None:
    """Writers set ``instrument_id`` themselves (Phase 4.6b).

    Every ORM insert into a ticker table resolves the ticker to its current
    instrument here, before the INSERT, so the ORM knows the value (and the
    primary key where ``instrument_id`` is part of it). Bulk upserts that skip
    the ORM resolve it with ``services.instruments.instrument_ids``. The
    database triggers stay as a backstop and write the same value.

    A symbol added in the same flush must be inserted first, so its trigger
    has made the instrument: ``_order_after_symbols`` sees to that.
    """
    if _mapper.local_table.name not in _TICKER_TABLE_SET:
        return
    ticker = getattr(target, "ticker", None)
    if ticker is None:
        target.instrument_id = None
        return
    history = inspect(target).attrs.ticker.history
    if target.instrument_id is None or history.has_changes():
        target.instrument_id = instrument_id_for(connection, ticker)


_TICKER_TABLE_SET = frozenset(TICKER_TABLES)


def _order_after_symbols() -> None:
    """Make the unit of work insert ``symbols`` rows before ticker-table rows.

    A foreign key alone does not order a flush; a relationship does. Each
    ticker model gets a private, never-loaded relationship to ``Symbol``
    (``lazy="noload"``, ``passive_deletes="all"``: deleting a symbol never
    touches its rows), so ``session.add(Symbol(...)); session.add(PriceBar(...))``
    inserts the symbol, then its bars.
    """
    from sqlalchemy.orm import relationship

    from stockviz.models.market import Symbol

    registry = SQLModel._sa_registry  # pyright: ignore[reportAttributeAccessIssue]
    for mapper in registry.mappers:
        table = mapper.local_table
        assert isinstance(table, Table)
        if table.name not in _TICKER_TABLE_SET or mapper.has_property("_symbol_order"):
            continue
        mapper.add_property(
            "_symbol_order",
            relationship(
                Symbol,
                primaryjoin=table.c.ticker == Symbol.__table__.c.ticker,  # pyright: ignore[reportAttributeAccessIssue]
                foreign_keys=[table.c.ticker],
                lazy="noload",
                passive_deletes="all",
            ),
        )


_order_after_symbols()
# On every mapper: a listener on the SQLModel base does not reach classes
# mapped before this module is imported.
event.listen(Mapper, "before_insert", _set_instrument_id)
event.listen(Mapper, "before_update", _set_instrument_id)
