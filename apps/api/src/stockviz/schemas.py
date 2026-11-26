"""HTTP response schemas.

Kept separate from the SQLModel tables so we can evolve the wire format
without churning the DB schema (or vice versa).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SymbolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str
    sector: str | None = None
    exchange: str | None = None
    currency: str = "USD"
    is_active: bool


class BarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    # The stored bar's provenance (A1.4a); a resampled bar says "mixed" when
    # its daily bars disagree.
    source: str | None = None
    adjustment_semantics: str | None = None
    # Resampled intervals only (``1wk``, ``1mo``; A1.4a): the daily bars in
    # the period, and whether the period is not over at the venue. A partial
    # bar is "so far", never a closed bar. Null on ``1d``.
    sessions: int | None = None
    partial: bool | None = None
    # Intraday intervals only (A6.2: ``1m``-``60m``): ``ts`` is the bar's open
    # instant (naive UTC) and ``closed_at`` its close, clipped at the session
    # close; ``session_date`` is the venue's date of its session; ``feed`` and
    # ``badge`` name where it came from ("File (local)", "IEX only", "SIP");
    # ``minutes`` counts the stored 1-minute bars in it. Null on 1d/1wk/1mo.
    closed_at: datetime | None = None
    session_date: date | None = None
    feed: str | None = None
    badge: str | None = None
    minutes: int | None = None


class QuoteOut(BaseModel):
    ticker: str
    ts: datetime
    close: Decimal


class NewsArticleOut(BaseModel):
    """One Aegis News document linked to StockViz symbols (Phase 2).

    Read from the copied ``aegis_*`` tables, never from Aegis live. No article
    text, summary or image: the feed never sends them. ``available_at`` is
    when Aegis made the document available, the time every point-in-time read
    uses; ``published_at`` is the publisher's claim and is often empty (audit
    AG-12). ``sentiment`` is the raw Aegis label, ``mixed`` included (AG-4),
    and ``sentiment_model`` names the model and version behind it.
    """

    id: str
    tickers: list[str]
    title: str
    url: str | None = None
    source: str
    published_at: datetime | None = None
    available_at: datetime
    sentiment: Literal["positive", "neutral", "negative", "mixed"] | None = None
    sentiment_model: str | None = None
    topic: str | None = None


class NewsReactionOut(BaseModel):
    """A linked stock's move on the session after a headline (news redesign).

    The session is the first stored daily bar whose session closed after the
    headline's ``available_at`` (``event_study``'s rule). ``change_pct`` is its
    close against the previous stored close (null for the first bar held).
    ``closes`` holds up to five closes either side, ``reaction_index`` marks
    the session in it. Association, not cause.
    """

    ticker: str
    session_date: date
    change_pct: float | None = None
    closes: list[float]
    reaction_index: int


class NewsFeedItemOut(NewsArticleOut):
    reactions: list[NewsReactionOut] = []


class NewsFeedOut(BaseModel):
    """``/v1/news/feed``: one page of the archive, newest-available first."""

    items: list[NewsFeedItemOut]
    next_cursor: str | None = None
    total: int
    note: str = (
        "Headlines, sources, dates and links only: Aegis News stores no article text. "
        "Price moves are the session after each headline, an association, not a cause."
    )


class NewsDayOut(BaseModel):
    """Documents that became available on one UTC day, by sentiment."""

    date: date
    positive: int
    neutral: int
    negative: int
    mixed: int
    unscored: int


class NewsFacetOut(BaseModel):
    value: str
    count: int


class NewsHeatCellOut(BaseModel):
    date: date
    count: int
    net: float | None = None
    """(positive - negative) / count, null on a day without coverage."""


class NewsHeatRowOut(BaseModel):
    ticker: str
    total: int
    cells: list[NewsHeatCellOut]


class NewsOverviewOut(BaseModel):
    """``/v1/news/overview``: the timeline, filter options and coverage heatmap.

    ``days`` and the heatmap ignore the date filters (they show the whole
    archive); ``total``, ``sentiments``, ``topics`` and ``sources`` honour them.
    """

    total: int
    first_date: date | None = None
    last_date: date | None = None
    days: list[NewsDayOut]
    sentiments: dict[str, int]
    topics: list[NewsFacetOut]
    sources: list[NewsFacetOut]
    heatmap_days: list[date]
    heatmap: list[NewsHeatRowOut]


class SymbolDetailOut(BaseModel):
    """Symbol metadata + most recent close, used on the ticker detail page."""

    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str
    sector: str | None = None
    exchange: str | None = None
    currency: str = "USD"
    is_active: bool
    latest: QuoteOut | None = None
    # A3.1: whether raw exchange prices (``eod_raw``) are stored, so the chart
    # can offer ``/bars?adjustment=raw``. False means adjusted prices only.
    has_raw: bool = False
    # A3.5: the symbol's market (``US`` or ``IN``) and venue index, when its
    # venue has one; ``is_indian`` mounts the delivery pane.
    market: Literal["US", "IN"] | None = None
    benchmark: str | None = None
    benchmark_name: str | None = None
    is_indian: bool = False
    # A6.2: the intraday bars stored for the symbol (default feed), or null.
    intraday: IntradayInfoOut | None = None
    # A6.7: an index's stored volume is 0, not real, so it has no volume profile.
    is_index: bool = False


class IntradayCoverageOut(BaseModel):
    feed: str
    interval: Literal["1m", "60m"]
    first: datetime
    last: datetime


class IntradayInfoOut(BaseModel):
    """A6.2: which intraday intervals a symbol has, from its best stored feed.

    ``intervals`` is every interval the bars route can build (all five with
    1-minute bars; ``60m`` alone with only hourly bars). ``first``/``last`` are
    bar opens (naive UTC) over that feed's stored bars; ``coverage`` lists
    each stored feed and interval; ``badge`` is the chart's source badge.
    """

    feed: str
    badge: str
    intervals: list[Literal["1m", "5m", "15m", "30m", "60m"]]
    first: datetime
    last: datetime
    venue: str
    time_zone: str
    feeds: list[str]
    coverage: list[IntradayCoverageOut]


class EarningsEventOut(BaseModel):
    """One provider-backed earnings date for the calendar."""

    id: int
    ticker: str
    name: str
    event_date: date
    report_time: str | None = None
    fiscal_period: str | None = None
    eps_estimate: Decimal | None = None
    eps_actual: Decimal | None = None
    surprise_pct: Decimal | None = None
    result: Literal["beat", "miss", "in_line", "unknown"] = "unknown"
    source: str
    fetched_at: datetime


class IndicatorPointOut(BaseModel):
    ts: datetime
    value: float


class MACDPointOut(BaseModel):
    ts: datetime
    macd: float
    signal: float
    histogram: float


class IndicatorMetaOut(BaseModel):
    label: str
    pane: Literal["price", "separate"]
    outputs: list[str]
    params: dict[str, float]
    lookback: int
    group: str
    # "start": a cumulative series (OBV, A/D) whose level starts at 0 on the
    # first bar loaded; read its shape, not the number.
    anchored: Literal["none", "start"] = "none"


class IndicatorParamOut(BaseModel):
    """One study parameter and its bounds (A3.4). Whole numbers from ``min``
    to ``max``; decimals above ``min`` (``min_exclusive``) up to ``max``.
    ``choices`` names the values 1..n when the parameter picks an option."""

    name: str
    label: str
    type: Literal["int", "float"]
    default: float
    min: float
    max: float
    min_exclusive: bool
    step: float
    choices: list[str] = Field(default_factory=list)


class IndicatorSignalOut(BaseModel):
    """A study's canonical signal as a Rule DSL rule, on its default
    parameters, with the latest evidence grade (A3.4) or null before the
    ``indicator-evidence`` job has run."""

    rule: str  # canonical text
    hash: str
    description: str
    source: str = ""
    evidence: ChecklistEvidenceOut | None = None


class IndicatorCatalogItemOut(BaseModel):
    key: str
    label: str
    params: list[str]
    defaults: list[float]
    outputs: list[str]
    pane: Literal["price", "separate"]
    group: str
    # A3.4: parameter schemas, the all-defaults key, and the evidence badge.
    parameters: list[IndicatorParamOut] = Field(default_factory=list)
    default_key: str = ""
    anchored: Literal["none", "start"] = "none"
    description: str = ""
    source: str = ""
    # Null: no canonical signal, so "No grade" (never a made-up one).
    signal: IndicatorSignalOut | None = None


class IndicatorsOut(BaseModel):
    """Indicator bundle keyed by indicator name.

    Scalar indicators (SMA/EMA/RSI) come back under ``series``; MACD has
    three aligned series so it gets its own field. The web app picks what
    to draw based on the names list it asked for.
    """

    ticker: str
    # A single-output indicator is keyed by its name ("rsi_14"); one with
    # several outputs by name and output ("bb_20_2.upper") (Phase 6.1).
    series: dict[str, list[IndicatorPointOut]] = {}
    macd: list[MACDPointOut] | None = None
    # Per requested name: label, pane, outputs, lookback (Phase 6.1).
    meta: dict[str, IndicatorMetaOut] = {}
    # Bars loaded before the window so the first value shown does not depend
    # on where the data starts (audit RS-1); no value before this is returned.
    warmup_bars: int = 0
    window_start: datetime | None = None
    # A1.4a: the bar interval the indicators ran on. On ``1wk``/``1mo`` a
    # partial newest bar (its week or month not over) is left out of the
    # inputs, so no value is computed on it; this is its timestamp.
    interval: str = "1d"
    partial_bar_excluded: datetime | None = None
    # A6.2: on intraday intervals, the feed the bars came from (null otherwise).
    feed: str | None = None


# ---------------------------------------------------------------------------
# Dividends
# ---------------------------------------------------------------------------


class DividendCreditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    ex_date: date
    amount_credited: Decimal
    # The currency ``amount_credited`` is in; ``base_value`` is the same credit
    # in the portfolio's base currency (Phase 4.5c). ``ytd_income`` sums those.
    currency: str
    base_value: Decimal
    credited_at: datetime


class ProjectedDividendOut(BaseModel):
    ticker: str
    projected_ex_date: date | None
    projected_amount: Decimal


class DividendSummaryOut(BaseModel):
    ytd_income: Decimal
    history: list[DividendCreditOut]
    projected: list[ProjectedDividendOut]


# ---------------------------------------------------------------------------
# Paper trading
# ---------------------------------------------------------------------------


class PositionOut(BaseModel):
    ticker: str
    name: str
    quantity: Decimal
    # ISO-4217 currency the symbol trades in.
    currency: str = "USD"
    # avg_cost is in the position's native currency.
    avg_cost: Decimal
    last_close: Decimal | None
    # Native-currency aggregates (unchanged regardless of display preference).
    market_value_native: Decimal = Decimal(0)
    unrealized_pl_native: Decimal = Decimal(0)
    # Same aggregates converted to the portfolio's display currency.
    market_value: Decimal
    unrealized_pl: Decimal
    reserved_quantity: Decimal = Decimal(0)
    available_quantity: Decimal = Decimal(0)


class PortfolioOptionOut(BaseModel):
    """An open option contract marked to its current theoretical value."""

    option_id: int
    ticker: str
    option_type: Literal["call", "put"]
    strike: Decimal
    expiry: date
    quantity: int
    currency: str = "USD"
    premium_paid: Decimal
    market_value_native: Decimal
    market_value: Decimal
    unrealized_pl: Decimal
    greeks: OptionGreeksOut | None = None
    """Per-share Greeks at today's price (Phase 9.1, UX-5); null when unpriceable.
    Signed for the position: a short leg's are negated (Phase 9.2)."""
    side: Literal["long", "short"] = "long"
    """A short leg's ``premium_paid`` is the premium it received, and its
    ``market_value`` is negative: what buying it back would cost."""
    strategy: str | None = None
    """The strategy this leg was opened in, in words (Phase 9.3)."""


class ValuationWarningOut(BaseModel):
    """A figure the valuation could not price (audit LG-13).

    ``code``: ``no_close`` and ``no_option_price`` (valued at 0) or
    ``no_fx_rate`` (added unconverted; in All books, dates without a rate are
    left out of the combined history). ``stale_fx_rate`` (A5.2, All books
    only): a rate older than the session before the date it values was used.
    ``subject`` is a ticker or currency.
    """

    code: Literal["no_close", "no_option_price", "no_fx_rate", "stale_fx_rate"]
    subject: str
    message: str


class CurrencyCashOut(BaseModel):
    """Cash held in one currency: ``amount`` native, ``value`` in display currency."""

    currency: str
    amount: Decimal
    value: Decimal


class PortfolioOut(BaseModel):
    """Snapshot of the user's default portfolio used by /portfolio.

    All top-level aggregates (cash_balance, market_value, totals) are in
    ``display_currency``. Per-position fields carry both native and converted
    amounts so the UI can show either.

    ``market_value`` counts equities only; ``options_market_value`` is the
    mark-to-model value of open contracts. ``total_value`` is the sum of both
    plus cash — an options book that is not counted here would make NAV
    understate the account by the premium at risk.
    """

    portfolio_id: int
    display_currency: str = "USD"
    cash_balance: Decimal
    reserved_cash: Decimal = Decimal(0)
    available_cash: Decimal = Decimal(0)
    market_value: Decimal
    options_market_value: Decimal = Decimal(0)
    total_value: Decimal
    total_cost_basis: Decimal
    # #68 (Phase 8.1): equities plus open options, with each part.
    unrealized_pl: Decimal
    unrealized_pl_equity: Decimal = Decimal(0)
    unrealized_pl_options: Decimal = Decimal(0)
    # Lifetime realized P&L; closes without a stored realization are counted
    # in ``realized_pl_unavailable`` and left out, never estimated.
    realized_pl: Decimal = Decimal(0)
    realized_pl_unavailable: int = 0
    # A4.2, net first: fees paid on equity fills (display currency) and
    # realized P&L after them.
    fees_paid: Decimal = Decimal(0)
    realized_pl_net: Decimal = Decimal(0)
    positions: list[PositionOut]
    option_positions: list[PortfolioOptionOut] = []
    # Empty when the total is complete; otherwise what it leaves out (LG-13).
    valuation_warnings: list[ValuationWarningOut] = []
    # Phase 4.5b: cash per currency, base first. ``cash_balance`` is their
    # total in display currency; ``available_cash`` is the base's buying power.
    cash_by_currency: list[CurrencyCashOut] = []
    # Phase 4.8: the account's base currency (USD or INR), and whether it is
    # fixed (true once the account has any trade, order or option).
    base_currency: str = "USD"
    base_currency_locked: bool = True
    # A5.2: set only for ``?book=all``: the books summed, each in the display
    # currency. ``portfolio_id`` is 0 then and ``base_currency`` is the
    # display currency.
    combined: CombinedOut | None = None


class CombinedBookOut(BaseModel):
    """One book's share of the All books figure (A5.2)."""

    id: int
    name: str
    kind: Literal["paper", "imported"]
    base_currency: str
    archived: bool
    is_default: bool
    total_value: Decimal
    """In the display currency at the latest rate."""


class CombinedOut(BaseModel):
    """What ``?book=all`` summed and how (A5.2, M10.1)."""

    books: list[CombinedBookOut]
    fx_rule: str
    per_book_only: list[str]
    """Figures that are per book and absent from All books (risk, stress, ...)."""


ClientOrderId = Annotated[
    str | None,
    Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
]
"""A client-generated key (a UUID, say) that makes a submission safe to repeat:
the same key returns the first order instead of placing a second (#67, LG-10)."""


# ---------------------------------------------------------------------------
# Trade plans (A5.4, M10.3)
# ---------------------------------------------------------------------------

PlanPrice = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]
PlanSize = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=6)]
PlanTag = Annotated[str, Field(min_length=1, max_length=32)]


def _check_plan_prices(
    side: str, entry: Decimal | None, stop: Decimal | None, target: Decimal | None
) -> None:
    if entry is None:
        return
    if side == "long":
        if stop is not None and stop >= entry:
            raise ValueError("a long plan's stop must be below its entry")
        if target is not None and target <= entry:
            raise ValueError("a long plan's target must be above its entry")
    else:
        if stop is not None and stop <= entry:
            raise ValueError("a short plan's stop must be above its entry")
        if target is not None and target >= entry:
            raise ValueError("a short plan's target must be below its entry")


class TradePlanDraft(BaseModel):
    """The plan fields a trader writes (A5.4). Entry, stop and size are required."""

    model_config = ConfigDict(extra="forbid")

    side: Literal["long", "short"] = "long"
    planned_entry: PlanPrice
    planned_stop: PlanPrice
    planned_target: PlanPrice | None = None
    planned_size: PlanSize
    setup_version_id: int | None = Field(default=None, ge=1)
    thesis_id: int | None = Field(default=None, ge=1)
    thesis_text: str | None = Field(default=None, max_length=4000)
    why: str | None = Field(default=None, max_length=2000)
    invalidation: str | None = Field(default=None, max_length=4000)
    horizon_bars: int | None = Field(default=None, ge=1, le=10000)
    confidence: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=8000)
    tags: list[PlanTag] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _prices(self) -> TradePlanDraft:
        _check_plan_prices(self.side, self.planned_entry, self.planned_stop, self.planned_target)
        return self


class TradePlanIn(TradePlanDraft):
    """``POST /v1/plans``: a plan for ``ticker`` in the ``?book=`` book.

    ``link_open_position`` links the book's open position in the ticker to the
    plan: its entry fills were made before the plan, so the plan is labelled
    "written after entry" and never locked.
    """

    ticker: str = Field(min_length=1, max_length=16)
    link_open_position: bool = False


class TradePlanPatch(BaseModel):
    """``PATCH /v1/plans/{id}``. Plan fields only before the first fill (else
    409); ``notes`` and ``tags`` always. ``status`` closes or cancels."""

    model_config = ConfigDict(extra="forbid")

    planned_entry: PlanPrice | None = None
    planned_stop: PlanPrice | None = None
    planned_target: PlanPrice | None = None
    planned_size: PlanSize | None = None
    setup_version_id: int | None = Field(default=None, ge=1)
    thesis_id: int | None = Field(default=None, ge=1)
    thesis_text: str | None = Field(default=None, max_length=4000)
    why: str | None = Field(default=None, max_length=2000)
    invalidation: str | None = Field(default=None, max_length=4000)
    horizon_bars: int | None = Field(default=None, ge=1, le=10000)
    confidence: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=8000)
    tags: list[PlanTag] | None = Field(default=None, max_length=12)
    status: Literal["closed", "cancelled"] | None = None


class TradePlanOut(BaseModel):
    id: int
    source: Literal["paper", "replay", "drill", "imported"]
    book_id: int | None
    replay_session_id: int | None
    ticker: str | None
    currency: str
    side: Literal["long", "short"]
    planned_entry: Decimal | None
    planned_stop: Decimal | None
    planned_target: Decimal | None
    planned_size: Decimal | None
    risk_per_share: Decimal | None
    """|entry - stop|."""
    planned_risk: Decimal | None
    """|entry - stop| x size, in ``currency``."""
    reward_per_share: Decimal | None
    """|target - entry| (null without a target)."""
    reward_risk: Decimal | None
    """reward / risk per share, 2 decimals (null without a target)."""
    setup_version_id: int | None
    setup_label: str | None
    thesis_id: int | None
    thesis_title: str | None
    thesis_text: str | None
    why: str | None
    invalidation: str | None
    horizon_bars: int | None
    confidence: int | None
    notes: str | None
    tags: list[str]
    status: Literal["open", "active", "closed", "cancelled"]
    locked: bool
    locked_at: datetime | None
    first_fill_at: datetime | None
    written_after_entry: bool
    frozen: bool
    """True once a fill is linked: only notes and tags can change."""
    fills: int
    """Paper fills linked to the plan (replay and drill plans: 0)."""
    created_at: datetime
    updated_at: datetime


class TradePlansOut(BaseModel):
    plans: list[TradePlanOut]
    limit: int


class TradeIn(BaseModel):
    """Request body for POST /v1/trades."""

    ticker: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    client_order_id: ClientOrderId = None
    # A5.4: link the fill to a plan (one of the two; buys only).
    trade_plan_id: int | None = Field(default=None, ge=1)
    plan: TradePlanDraft | None = None
    """A new plan written on the ticket, created with the order."""

    @field_validator("quantity")
    @classmethod
    def _bounded_quantity(cls, value: Decimal) -> Decimal:
        # LG-9: "NaN" used to pass here and fail later with a 500.
        from stockviz.services.trading.bounds import MAX_QUANTITY, check_amount

        return check_amount(value, name="quantity", maximum=MAX_QUANTITY)


class TradeOut(BaseModel):
    """One executed trade — used by both POST response and /trades history.

    ``price`` is the per-share fill price in the symbol's native currency.
    ``currency`` is that native currency; ``fx_rate`` is USD-per-unit at fill
    time (1 for USD symbols). ``total_native`` and ``total_usd`` are pre-
    computed so clients don't have to re-multiply.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    ts: datetime
    currency: str = "USD"
    fx_rate: Decimal = Decimal(1)
    total_native: Decimal = Decimal(0)
    total_usd: Decimal = Decimal(0)
    # Phase 4.8: the amount in the account's base currency (USD or INR);
    # ``fx_rate`` converts into it. ``realized_pnl`` is in it too.
    base_currency: str = "USD"
    total_base: Decimal = Decimal(0)
    # USD gain/loss against the position's weighted-average cost basis.
    # Set on sells; None on buys and on rows written before this was tracked.
    # Gross of fees (the price gain); ``realized_pnl_net`` takes this sell's
    # fees off.
    realized_pnl: Decimal | None = None
    # A4.2: fees on this fill in the native currency (null: a fill made
    # before A4.2, never recalculated), the schedule and each component.
    fees: Decimal | None = None
    fee_schedule: str | None = None
    fee_lines: list[TradeFeeLineOut] = []
    # Native cash effect net of fees: a buy's value + fees, a sell's value - fees.
    net_native: Decimal | None = None
    realized_pnl_net: Decimal | None = None
    # A5.2: the trade's book (always set; the All books list mixes them).
    book_id: int | None = None
    # A5.4: the plan the fill is linked to.
    trade_plan_id: int | None = None
    # A5.3: the broker fill an imported book's trade posts (null: paper). Its
    # fees are estimated from the dated schedule (the tradebook has none).
    broker_fill_id: int | None = None
    fees_estimated: bool = False


class TradeFeeLineOut(BaseModel):
    key: str
    label: str
    amount: Decimal
    rate: str = ""
    effective_from: date | None = None
    source_url: str | None = None


class ReplaySessionCreateIn(BaseModel):
    """Open an isolated replay book over a frozen stored-1d range.

    ``start_at`` snaps to the first 1d bar at-or-after the request.
    ``end_at`` snaps to the last 1d bar at-or-before the request (or the latest
    stored bar at creation if omitted). Profile is server-pinned.

    A4.6: ``starting_cash`` is in the symbol's currency; omitted, it is the
    currency's default ($100,000; ₹10,00,000; else 100,000 units).
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str
    start_at: datetime
    end_at: datetime | None = None
    starting_cash: Decimal | None = None
    # A6.9: the bars (1d, or 1m/5m/15m/60m from stored minutes; an intraday
    # session needs end_at) and the replay profile (intrabar_ohlc, the default,
    # or legacy_close).
    interval: Literal["1d", "1m", "5m", "15m", "60m"] = "1d"
    profile: Literal["legacy_close", "intrabar_ohlc"] | None = None


class ReplayOrderIn(BaseModel):
    """Intent only. A market order fills at the session's current stored
    close; a limit / stop-loss / take-profit order (A4.6) rests, priced by
    ``limit_price`` (the limit or the trigger), and is judged from the next
    bar on.

    A6.9: ``bracket`` is a long entry (``entry_type`` market, or limit at
    ``limit_price``) with a sell ``stop_price`` below it and a sell
    ``target_price`` above it, one cancels the other. ``side`` must be buy.
    Owner, 27 Nov 2026: ``direction: short`` (US-listed only) makes it a short
    sale with a buy stop above and a buy target below; ``side`` is then sell."""

    model_config = ConfigDict(extra="forbid")

    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop_loss", "take_profit", "bracket"] = "market"
    quantity: Decimal
    limit_price: Decimal | None = None
    entry_type: Literal["market", "limit"] = "market"
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    direction: Literal["long", "short"] = "long"


class ReplayPositionOut(BaseModel):
    ticker: str
    quantity: Decimal
    avg_cost: Decimal


class ReplayFillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    ticker: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    realized_pnl: Decimal | None = None
    profile_name: str
    model_version: str
    reference_price: Decimal | None
    reason: str
    assumptions: list[str]
    market_interval: str
    order_type: str
    evaluated_at: datetime
    created_at: datetime
    # A4.6: fees in the session currency (0 before A4.6 and on USD symbols).
    fees: Decimal = Decimal(0)
    fee_lines: list[TradeFeeLineOut] = []
    order_id: int | None = None


class ReplayOrderOut(BaseModel):
    """A4.6: a resting order. ``status`` open | filled | cancelled |
    rejected | expired; ``reason`` says why it left ``open``.

    A6.9: a bracket's entry is ``bracket`` (``limit_price`` its limit, or
    its market fill price) and its stop and target carry ``parent_id``;
    all three share ``oco_group``. ``pending`` is a child waiting for its
    entry. ``order_inside_bar_unknown``: the fill was a stop chosen first
    because the stop and the target were both inside one bar with nothing
    finer to say which came first."""

    id: int
    session_id: int
    ticker: str
    side: Literal["buy", "sell"]
    order_type: Literal["limit", "stop_loss", "take_profit", "bracket"]
    quantity: Decimal
    limit_price: Decimal
    status: Literal["pending", "open", "filled", "cancelled", "rejected", "expired"]
    placed_at: datetime
    resolved_at: datetime | None = None
    reason: str | None = None
    parent_id: int | None = None
    oco_group: int | None = None
    order_inside_bar_unknown: bool = False


class ReplaySessionListOut(BaseModel):
    """Lightweight list row. Positions and next-bar lookups are detail-only."""

    id: int
    ticker: str
    start_at: datetime
    current_at: datetime
    end_at: datetime
    status: str
    starting_cash: Decimal
    cash_balance: Decimal
    has_next: bool
    created_at: datetime
    currency: str = "USD"
    interval: str = "1d"
    profile_name: str = "legacy_close"


class ReplaySessionOut(BaseModel):
    id: int
    ticker: str
    profile_name: str
    model_version: str
    start_at: datetime
    current_at: datetime
    end_at: datetime
    starting_cash: Decimal
    cash_balance: Decimal
    status: str
    has_next: bool = False
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    positions: list[ReplayPositionOut] = []
    # A4.6: the book's currency, the fee schedule its fills pay, whether the
    # owner's override let it end inside the lag, and whether it can trade
    # (an index session is watch-only).
    currency: str = "USD"
    fee_schedule: str = "none"
    lag_override: bool = False
    tradable: bool = True
    open_orders: int = 0
    # A6.9: the session's bars (and minute feed, intraday) and the profile's
    # assumptions from the registry, so the page names its fill model.
    interval: str = "1d"
    feed: str | None = None
    profile_assumptions: list[str] = []


class ReplayAvailabilityOut(BaseModel):
    ticker: str
    currency: str
    first_bar: datetime
    last_bar: datetime
    bars_count: int
    # A4.6: the lag (days; 0 = none), the last end date it allows (null: no
    # lag, or waived for the caller), the default starting cash in the
    # currency, the fee schedule fills pay, and whether it can be traded.
    lag_days: int = 0
    max_end: date | None = None
    lag_waived: bool = False
    default_starting_cash: Decimal = Decimal("100000.00")
    fee_schedule: str = "none"
    tradable: bool = True
    # A6.9: the intervals a session can run on (1d, plus the intraday ones
    # when minutes are stored), the minute feed and its stored range.
    intervals: list[str] = ["1d"]
    minute_feed: str | None = None
    minute_first: datetime | None = None
    minute_last: datetime | None = None


class ReplaySummaryOut(BaseModel):
    """Mark-to-market at the current observable replay bar only."""

    ticker: str
    status: str
    current_at: datetime
    current_close: Decimal
    cash: Decimal
    starting_cash: Decimal
    positions_market_value: Decimal
    equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    return_pct: Decimal
    fills_count: int
    has_next: bool
    visible_high: Decimal
    visible_low: Decimal
    # A4.6: amounts above are in ``currency``; ``fees_paid`` is already out of cash.
    currency: str = "USD"
    fees_paid: Decimal = Decimal(0)


class ReplayBarOut(BaseModel):
    ticker: str
    ts: datetime
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class ReplayMarketOut(BaseModel):
    ticker: str
    current_at: datetime
    start_at: datetime
    end_at: datetime
    has_next: bool
    status: str
    bar: ReplayBarOut


class ReplayDecisionOut(BaseModel):
    status: str
    fill_quantity: Decimal
    fill_price: Decimal | None
    remaining_quantity: Decimal
    reason: str
    profile_name: str
    model_version: str
    reference_price: Decimal | None
    assumptions: list[str]


class ReplaySubmitOut(BaseModel):
    """A market order carries the kernel's ``decision`` (and ``fill``); a
    resting order (A4.6) carries ``order`` and no decision yet."""

    session: ReplaySessionOut
    decision: ReplayDecisionOut | None = None
    fill: ReplayFillOut | None = None
    order: ReplayOrderOut | None = None
    # A6.9: a bracket's stop and target (``order`` is its entry).
    children: list[ReplayOrderOut] = []


class ReplayEpisodeFillOut(BaseModel):
    """ReplayFill facts plus post-fill concentration for forensic detail."""

    id: int
    ticker: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    realized_pnl: Decimal | None = None
    profile_name: str
    model_version: str
    reference_price: Decimal | None
    reason: str
    assumptions: list[str]
    market_interval: str
    order_type: str
    evaluated_at: datetime
    created_at: datetime
    equity_after: Decimal | None = None
    concentration_pct: Decimal | None = None
    fees: Decimal = Decimal(0)


class ReplayEpisodeForensicsOut(BaseModel):
    """One reconstructed exposure episode, long or (27 Nov 2026) short."""

    index: int
    ticker: str
    opened_at: datetime
    closed_at: datetime | None = None
    status: Literal["open", "closed"]
    entry_price: Decimal
    exit_price: Decimal | None = None
    entry_quantity: Decimal
    peak_quantity: Decimal
    weighted_entry_price: Decimal
    weighted_exit_price: Decimal | None = None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None = None
    return_pct: Decimal | None = None
    holding_bars: int
    holding_calendar_days: int
    mae_amount: Decimal | None = None
    mae_pct: Decimal | None = None
    mfe_amount: Decimal | None = None
    mfe_pct: Decimal | None = None
    benchmark_return_pct: Decimal | None = None
    excess_return_pct: Decimal | None = None
    max_position_pct: Decimal | None = None
    entry_equity: Decimal | None = None
    peak_exposure: Decimal
    fills: list[ReplayEpisodeFillOut] = []
    # A4.6: the episode's fees; ``realized_pnl`` is net of them.
    fees: Decimal = Decimal(0)
    # 27 Nov 2026: ``short`` when a short sale opened it (US replay sessions).
    side: Literal["long", "short"] = "long"


class ReplayForensicsOut(BaseModel):
    """Session-level forensic scorecard. Derived; not persisted."""

    ticker: str
    status: str
    analysis_scope: Literal["so_far", "final", "cancelled"]
    analysis_at: datetime
    starting_cash: Decimal
    equity: Decimal
    replay_return_pct: Decimal
    buy_hold_return_pct: Decimal | None = None
    excess_return_pct: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    max_concentration_pct: Decimal | None = None
    fills_count: int
    episodes_count: int
    closed_episodes_count: int
    open_episodes_count: int
    episodes: list[ReplayEpisodeForensicsOut] = []
    currency: str = "USD"


class ReplayJournalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thesis: str | None = Field(default=None, max_length=4000)
    invalidation: str | None = Field(default=None, max_length=4000)
    expected_holding_bars: int | None = Field(default=None, ge=1, le=10000)
    confidence: int | None = Field(default=None, ge=1, le=5)
    reflection: str | None = Field(default=None, max_length=8000)


class ReplayJournalOut(BaseModel):
    session_id: int
    thesis: str | None = None
    invalidation: str | None = None
    expected_holding_bars: int | None = None
    confidence: int | None = None
    reflection: str | None = None
    locked: bool
    """The thesis fields are frozen: locked at the first fill, or (A5.4)
    written after it."""
    locked_at: datetime | None = None
    # A5.4: the journal (a trade plan) was started after the first fill.
    written_after_entry: bool = False
    created_at: datetime
    updated_at: datetime


class ExecutionProvenanceOut(BaseModel):
    """Durable kernel provenance for one live equity paper fill (SIM-04).

    Absent for trades written before provenance existed. ``evaluated_at`` is
    the adapter evaluation instant (UTC); ``created_at`` is when the row was
    persisted.
    """

    model_config = ConfigDict(from_attributes=True)

    trade_id: int
    profile_name: str
    model_version: str
    reference_price: Decimal | None
    fill_price: Decimal
    reason: str
    assumptions: list[str]
    market_interval: str
    order_type: str
    evaluated_at: datetime
    created_at: datetime


class PortfolioHistoryPointOut(BaseModel):
    """One row of the equity-curve series returned by /v1/portfolio/history."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    nav: Decimal
    # A5.2, ``?book=all`` only: outside money that day in the display
    # currency (a new book's opening value, an imported book's buys less
    # sells), so a change over a range can leave it out. Null per book.
    flow: Decimal | None = None


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


class ProfileOut(BaseModel):
    """The caller's display settings (`/v1/profile`)."""

    user_id: int
    display_currency: str = "USD"


class ProfilePatchIn(BaseModel):
    """Fields are optional: a patch sends only what changes."""

    display_currency: str | None = None


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class AlertIn(BaseModel):
    """Request body for POST /v1/alerts (Phase 7.1: rules of several kinds).

    A price-level alert keeps the original shape: ``ticker``, ``direction``,
    ``target_price``. Other rules name a ``kind`` and its ``params`` (see
    ``services/alerts/rules.py``).
    """

    ticker: str | None = None
    kind: Literal["price", "technical", "news", "portfolio", "rule"] = "price"
    direction: Literal["above", "below"] | None = None
    target_price: Decimal | None = None
    params: dict[str, Any] | None = None
    # A2.3: required for kind "rule" (your setup's version or a preset's).
    setup_version_id: int | None = Field(default=None, ge=1)
    repeat: Literal["once", "every_cross"] = "once"
    cooldown_sessions: int = Field(default=1, ge=1, le=250)
    # A5.1: the book a portfolio rule watches (yours, else 404); null = the
    # default book. Portfolio rules only.
    book_id: int | None = Field(default=None, ge=1)


class AlertPatch(BaseModel):
    """``PATCH /v1/alerts/{id}``: pause or resume a rule; point a rule alert at
    another setup version (A2.3: it re-arms from now)."""

    paused: bool | None = None
    setup_version_id: int | None = Field(default=None, ge=1)


class AlertOut(BaseModel):
    """One alert rule in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str | None
    kind: str = "price"
    direction: Literal["above", "below"] | None
    target_price: Decimal | None
    params: dict[str, Any] | None = None
    setup_version_id: int | None = None
    # A5.1: a portfolio rule's book; null = the default book.
    book_id: int | None = Field(default=None, validation_alias="portfolio_id")
    repeat: str = "once"
    cooldown_sessions: int = 1
    paused: bool = False
    created_at: datetime
    armed_at: datetime | None = None
    triggered_at: datetime | None
    dismissed_at: datetime | None
    # Evaluation state: the condition at the last judged bar (RS-8).
    last_state: bool | None = None
    last_bar_date: date | None = None
    last_fired_bar_date: date | None = None
    # The rule in words, for lists and notifications.
    description: str = ""
    # The symbol's trading currency, so the target formats without a second
    # lookup. The target is in this currency, like every stored price.
    currency: str = "USD"


class AlertEventOut(BaseModel):
    """One firing of a rule: what was seen, against what, on which bar."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_id: int
    kind: str
    ticker: str | None
    session_date: date
    bar_date: date | None
    observed: Decimal | None
    threshold: Decimal | None
    message: str
    source: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


class WatchlistItemOut(BaseModel):
    """One ticker on the authenticated user's default watchlist."""

    ticker: str
    name: str
    sector: str | None
    added_at: datetime
    last_close: Decimal | None
    # Timestamp of the stored bar behind last_close (audit RS-13), so the page
    # can date the price. None when the symbol has no stored bars.
    last_close_at: datetime | None = None
    currency: str = "USD"
    # The last 30 daily closes, oldest first, for the row's sparkline (RS-12:
    # the page used to fetch bars once per item).
    closes: list[Decimal] = []


# A2.5 (M4.6): many lists, notes, tags, column sets. These literals equal
# models/watchlist.WATCHLIST_COLOURS and services/watchlists.COLUMN_KEYS
# (tests/test_watchlists_router.py checks).
WatchlistColour = Literal["aqua", "blue", "violet", "pink", "amber", "lime", "slate"]
ColumnKey = Literal[
    "close",
    "change_pct",
    "rsi_14",
    "pct_from_52w_high",
    "sma_50_gap_pct",
    "sma_200_gap_pct",
    "atr_pct_14",
    "hv_20",
    "volume_ratio",
    "avg_volume_20",
    "pe",
    "pb",
    "market_cap_usd",
    "dividend_yield",
    "roe",
    "sentiment_7d",
    "delivery_pct",
    "checklist_met",
    "sector",
]


class WatchlistOut(BaseModel):
    id: int
    name: str
    colour: WatchlistColour
    position: int
    is_default: bool
    column_set_id: int | None
    item_count: int
    # Only with ?contains=TICKER: whether that ticker is on the list.
    contains: bool | None = None
    created_at: datetime


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    colour: WatchlistColour = "aqua"


class WatchlistPatch(BaseModel):
    """Only the fields sent change. ``column_set_id: null`` clears it;
    ``is_default`` takes ``true`` only (make another list the default)."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    colour: WatchlistColour | None = None
    is_default: bool | None = None
    column_set_id: int | None = None


class WatchlistOrderIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)


class WatchlistRowOut(WatchlistItemOut):
    note: str | None = None
    tags: list[str] = []
    # The requested columns' values; null when there is no data. With
    # checklist_met, checklist_evaluated rides along.
    values: dict[str, float | int | str | None] = {}


class WatchlistItemsOut(BaseModel):
    watchlist: WatchlistOut
    columns: list[ColumnKey]
    column_set_id: int | None
    items: list[WatchlistRowOut]


class WatchlistBulkIn(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=100)


class WatchlistBulkOut(BaseModel):
    added: list[str]
    already_listed: list[str]
    unknown: list[str]
    item_count: int


class WatchlistItemPatch(BaseModel):
    """``note: null`` or blank clears it; ``tags`` replaces the tags."""

    note: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)


class ColumnSetIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    columns: list[ColumnKey] = Field(min_length=1, max_length=19)


class ColumnSetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    columns: list[ColumnKey] | None = Field(default=None, min_length=1, max_length=19)


class ColumnSetOut(BaseModel):
    id: int
    name: str
    columns: list[ColumnKey]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Pending orders (advanced order types)
# ---------------------------------------------------------------------------


class PendingOrderIn(BaseModel):
    ticker: str
    side: str
    order_type: str
    quantity: str
    limit_price: str
    client_order_id: ClientOrderId = None
    # A5.4: the plan the order's fill is linked to (buy limits only).
    trade_plan_id: int | None = Field(default=None, ge=1)
    plan: TradePlanDraft | None = None


class PendingOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    side: str
    order_type: str
    quantity: Decimal
    limit_price: Decimal
    status: str
    created_at: datetime
    filled_at: datetime | None
    fill_price: Decimal | None
    # Populated when a triggered order could not be filled.
    cancel_reason: str | None = None
    # A5.2: the order's book (the All books list mixes them).
    portfolio_id: int | None = None
    # A5.4: the plan its fill will be linked to.
    trade_plan_id: int | None = None


# ---------------------------------------------------------------------------
# Screener
# ---------------------------------------------------------------------------


class ScreenerResultOut(BaseModel):
    """One symbol that passed every active filter on /v1/symbols/screen."""

    ticker: str
    name: str
    sector: str | None = None
    exchange: str | None = None
    currency: str = "USD"
    last_close: Decimal
    # Date of the bar the metrics (and last_close) come from (web UI audit T1).
    as_of: date | None = None
    rsi_14: float | None = None
    momentum_pct: float | None = None
    momentum_days: int | None = None
    high_52w: Decimal
    low_52w: Decimal
    # Rolling 7-day mean Aegis news sentiment in [-1, 1]. None when the symbol
    # has no scored Aegis documents in the week.
    sentiment_7d: float | None = None


class FundamentalRowOut(BaseModel):
    concept: str
    label: str
    unit: str  # a currency, "shares" or "<currency>/share"
    values: list[Decimal | None]  # aligned with FundamentalsOut.periods


class FundamentalsOut(BaseModel):
    """Statement figures as known on ``as_of`` (Phase 6.3).

    ``point_in_time`` is false when any figure came from a source without
    filing dates (yfinance), whose values are dated by when they were fetched.
    """

    ticker: str
    period: Literal["annual", "quarter"]
    as_of: date
    currency: str | None = None
    periods: list[date]
    rows: list[FundamentalRowOut]
    sources: list[str]
    point_in_time: bool
    latest_available_at: date | None = None


class ValuationMetricOut(BaseModel):
    key: str
    label: str
    value: float | None
    unit: str  # "x", "%", or a currency
    reason: str | None = None  # why value is null


class ValuationOut(BaseModel):
    """Valuation and metrics as known on ``as_of`` (Phase 6.4).

    ``fx_rate`` converts the trading currency's price into the reporting
    currency (INFY.NS trades in INR and reports in USD). ``basis`` is
    ``ttm`` (four quarters) or ``annual`` (the latest year).
    """

    ticker: str
    as_of: date
    price: Decimal | None = None
    price_date: date | None = None
    trading_currency: str
    reporting_currency: str | None = None
    fx_rate: Decimal | None = None
    basis: Literal["ttm", "annual"] | None = None
    point_in_time: bool
    sources: list[str]
    metrics: list[ValuationMetricOut]


class ValuationPointOut(BaseModel):
    date: date
    value: float


class ValuationHistoryOut(BaseModel):
    ticker: str
    metric: str
    points: list[ValuationPointOut]
    # Share of the history at or below the latest value, 0-100.
    percentile: float | None = None
    # A7.4: the history's 10th/25th/50th/75th/90th percentile levels (nearest rank).
    bands: dict[str, float] | None = None


class ScreenerRowOut(BaseModel):
    """One row of /v1/screener (Phase 6.2). Unknown values are null, never 0."""

    ticker: str
    name: str
    sector: str | None = None
    exchange: str | None = None
    market: str | None = None  # ISO country of the listing (US, IN, GB, ...)
    mic: str | None = None  # the venue, e.g. XNAS, XNSE
    currency: str = "USD"
    last_close: Decimal | None = None
    as_of: date | None = None
    rsi_14: float | None = None
    momentum_pct: float | None = None
    momentum_days: int | None = None
    high_52w: Decimal | None = None
    low_52w: Decimal | None = None
    pct_from_52w_high: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    sma_50_gap_pct: float | None = None
    sma_200_gap_pct: float | None = None
    atr_pct_14: float | None = None
    hv_20: float | None = None
    avg_volume_20: float | None = None
    sentiment_7d: float | None = None
    # Phase 6.5 fundamentals, as known on the snapshot date (percents are
    # percents; market cap in USD to compare across markets).
    pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    ev_ebitda: float | None = None
    dividend_yield: float | None = None
    market_cap_usd: float | None = None
    net_margin: float | None = None
    roe: float | None = None
    debt_to_equity: float | None = None
    revenue_growth: float | None = None
    # A2.2: the rule's result on this row, when the screen ran one. A row is
    # "unknown" when data the rule needs is missing; ``rule_reason`` says what.
    rule_result: Literal["met", "not_met", "unknown"] | None = None
    rule_reason: str | None = None
    rule_bar_date: date | None = None  # the bar the rule was judged on


class ScreenerRuleCountsOut(BaseModel):
    met: int
    not_met: int
    unknown: int


class ScreenerRuleOut(BaseModel):
    """The rule a screen ran (A2.2), and how it went over every candidate."""

    text: str
    canonical: str
    hash: str
    setup_version_id: int | None = None
    mode: Literal["met_only", "all"]
    as_of: date | None = None  # the date asked for; null = latest completed session
    # Venue (MIC) -> the session the rule was judged on there: the newest
    # stored bar on or before the target, so every symbol of a venue is judged
    # on one date. A symbol with no bar that day is unknown.
    sessions: dict[str, date]
    counts: ScreenerRuleCountsOut  # over every candidate the filters let through
    evaluated: int
    # A3.3: judged on the signed-in caller's drawings (never cached).
    user_scoped: bool = False
    cached: bool = False  # true when every result came from the in-process cache


class ScreenerPageOut(BaseModel):
    rows: list[ScreenerRowOut]
    total: int  # every match, before paging (audit RS-5)
    offset: int
    limit: int
    # A2.2: the screened universe and its survivorship flag, on every page.
    universe: UniverseOut | None = None
    rule: ScreenerRuleOut | None = None


class SavedScreenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    # The screener URL's query string, e.g. "market=IN&rsi_max=30&sort=rsi_14".
    query: str = Field(max_length=2000)
    # A2.2: the setup version the screen runs (yours or a preset's).
    setup_version_id: int | None = None
    # A2.3: notify when the rule's members change. Null keeps the saved value.
    notify_on_change: bool | None = None


class SavedScreenPatch(BaseModel):
    """``PATCH /v1/screens/{id}`` (A2.3)."""

    notify_on_change: bool


class SavedScreenOut(BaseModel):
    id: int
    name: str
    query: str
    setup_version_id: int | None = None
    notify_on_change: bool = False
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Rules, setups and theses (A2.2)
# ---------------------------------------------------------------------------

RULE_MAX_LENGTH = 4000


class RuleErrorOut(BaseModel):
    kind: Literal["syntax", "type"]
    message: str
    line: int | None = None  # from 1
    column: int | None = None  # from 1


RuleTimeframe = Literal["daily", "1m", "5m", "15m", "30m", "60m"]
"""A6.4: the bars a rule is judged on."""
SetupFeed = Literal["auto", "iex", "sip", "kite", "file"]


class RuleCheckIn(BaseModel):
    rule: str = Field(min_length=1, max_length=RULE_MAX_LENGTH)
    # A4.4: ``number`` checks a numeric expression (a rotation's ranking)
    # instead of a condition.
    expect: Literal["condition", "number"] = "condition"
    # A6.4: the bars the rule is judged on (``daily`` or an intraday interval).
    timeframe: RuleTimeframe = "daily"


class RuleCheckOut(BaseModel):
    """``POST /v1/rules/check``: the canonical form of a valid rule, or where it
    went wrong. Always 200, so an editor can show either."""

    valid: bool
    canonical: str | None = None
    hash: str | None = None
    type: str | None = None  # e.g. "boolean series"
    # Daily bars a rule needs before its first judged bar; null with
    # ``warmup_whole_history`` when it reads the whole history.
    warmup_bars: int | None = None
    warmup_whole_history: bool = False
    # What it reads besides bars: "benchmark", "fundamentals", "news",
    # "delivery", "drawings" (A3.3).
    uses: list[str] = Field(default_factory=list)
    # A3.3: it reads the owner's drawings (drawing(), avwap()), so only its
    # owner can run it; it cannot be a preset or forked by another user.
    user_scoped: bool = False
    error: RuleErrorOut | None = None
    # A6.4: the timeframe it was checked for; warm-up counts its bars.
    timeframe: str | None = None


SetupKind = Literal["screen", "alert", "strategy", "checklist"]


class SetupVersionOut(BaseModel):
    id: int
    setup_id: int
    version: int
    rule_text: str
    canonical_text: str
    rule_hash: str
    timeframe: str
    # A6.4: the stored intraday feed it reads (``auto`` = the best stored).
    feed: str = "auto"
    notes: str | None = None
    created_at: datetime
    # A3.3: the rule reads its owner's drawings (only the owner can run it).
    user_scoped: bool = False


class SetupOut(BaseModel):
    id: int
    name: str
    kind: SetupKind
    description: str | None = None
    is_preset: bool
    # True when the caller owns it (false for presets).
    owned: bool
    forked_from_version_id: int | None = None
    created_at: datetime
    archived_at: datetime | None = None
    latest_version: SetupVersionOut
    version_count: int


class SetupDetailOut(SetupOut):
    versions: list[SetupVersionOut]  # newest first


class SetupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: SetupKind = "screen"
    description: str | None = Field(default=None, max_length=2000)
    rule: str = Field(min_length=1, max_length=RULE_MAX_LENGTH)
    notes: str | None = Field(default=None, max_length=2000)
    timeframe: RuleTimeframe = "daily"
    feed: SetupFeed = "auto"


class SetupVersionIn(BaseModel):
    rule: str = Field(min_length=1, max_length=RULE_MAX_LENGTH)
    notes: str | None = Field(default=None, max_length=2000)
    timeframe: RuleTimeframe = "daily"
    feed: SetupFeed = "auto"


class SetupForkIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    # The version to copy; default the source's newest.
    version_id: int | None = None


class ThesisIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=10000)
    kill_rule: str | None = Field(default=None, min_length=1, max_length=RULE_MAX_LENGTH)


class ThesisPatch(BaseModel):
    """Only the fields sent change; ``kill_rule: null`` removes the kill rule."""

    title: str | None = Field(default=None, min_length=1, max_length=160)
    body: str | None = Field(default=None, min_length=1, max_length=10000)
    kill_rule: str | None = Field(default=None, min_length=1, max_length=RULE_MAX_LENGTH)


class ThesisCloseIn(BaseModel):
    status: Literal["closed", "invalidated"] = "closed"


class ThesisOut(BaseModel):
    id: int
    ticker: str | None
    title: str
    body: str
    kill_rule_text: str | None = None
    kill_rule_hash: str | None = None
    status: Literal["open", "invalidated", "closed"]
    created_at: datetime
    updated_at: datetime
    # A7.5 (M5.6): the kill switch, a rule alert judged nightly (A2.3's engine).
    kill_alert_id: int | None = None
    kill_state: Literal["none", "armed", "paused", "fired"] = "none"
    kill_fired_at: datetime | None = None
    kill_fired_on: date | None = None


# ---------------------------------------------------------------------------
# Portfolio analytics
# ---------------------------------------------------------------------------


class SectorAllocationOut(BaseModel):
    sector: str
    market_value: Decimal
    pct: float


class TopMoverOut(BaseModel):
    ticker: str
    name: str
    sector: str | None
    unrealized_pl: Decimal
    return_pct: float


class PeriodReturnOut(BaseModel):
    """One period's time-weighted return (Phase 8.1). Percentages, or null with a reason."""

    period: str
    start_date: date | None
    end_date: date
    return_pct: float | None
    annualised_pct: float | None
    reason: str | None = None


class XirrOut(BaseModel):
    """A money-weighted (XIRR) annual return; null with a reason when it means nothing."""

    rate_pct: float | None
    first_flow: date | None
    flows: int
    reason: str | None = None


class HoldingReturnOut(BaseModel):
    ticker: str
    kind: str
    xirr: XirrOut


class PortfolioReturnsOut(BaseModel):
    """Phase 8.1 returns. Each block names its method and basis (UX-9)."""

    currency: str
    twr_method: str
    twr_basis: str
    periods: list[PeriodReturnOut]
    xirr_method: str
    xirr_basis: str
    account_xirr: XirrOut
    holdings: list[HoldingReturnOut]


class ExposureBucketOut(BaseModel):
    key: str
    equity_value: Decimal
    cash_value: Decimal
    options_delta: Decimal
    weight_pct: float
    options_delta_pct: float


class ExposureOut(BaseModel):
    dimension: str
    buckets: list[ExposureBucketOut]


class PortfolioExposureOut(BaseModel):
    """Phase 8.2: weights of NAV in the display currency; method named (UX-9)."""

    currency: str
    method: str
    basis: str
    dimensions: list[ExposureOut]


class HoldingAttributionOut(BaseModel):
    ticker: str
    currency: str
    entry_rate: Decimal | None
    rate_now: Decimal | None
    cost_base: Decimal | None
    value_base: Decimal | None
    price_effect: Decimal | None
    currency_effect: Decimal | None
    cross_effect: Decimal | None
    income: Decimal
    reason: str | None = None


class PortfolioAttributionOut(BaseModel):
    """Phase 8.2: each holding's gain split into price, currency and cross, in base."""

    currency: str
    method: str
    basis: str
    holdings: list[HoldingAttributionOut]


class VarOut(BaseModel):
    """One VaR/CVaR figure; losses are positive amounts in ``currency``."""

    confidence: float
    horizon_days: int
    scenarios: int
    tail_count: int
    var: float
    var_pct: float
    cvar: float
    cvar_pct: float


class MonteCarloOut(BaseModel):
    method: str
    paths: int
    horizon_days: int
    mean_block: int
    seed: int
    percentiles: dict[str, float]
    prob_loss_10: float
    prob_loss_20: float
    # Phase 8.6 goals: a target value in a year, and the share of resampled
    # paths that reach it ("about 1 in 4 on past behaviour").
    goal: float | None = None
    prob_goal: float | None = None


class RiskWindowOut(BaseModel):
    start: date | None
    end: date | None
    sessions: int


class RiskNoteOut(BaseModel):
    ticker: str
    reason: str


class RiskProxyOut(BaseModel):
    ticker: str
    proxy: str
    days: int


class PortfolioRiskOut(BaseModel):
    """Phase 8.3 risk, in the base currency. Method, window and proxies named (UX-9)."""

    currency: str
    nav: float
    method: str
    var_rule: str
    window: RiskWindowOut
    holdings_included: int
    excluded: list[RiskNoteOut]
    proxied: list[RiskProxyOut]
    var: list[VarOut]
    monte_carlo: MonteCarloOut | None
    reason: str | None = None


class StressDriverOut(BaseModel):
    ticker: str
    change: float


class StressScenarioOut(BaseModel):
    key: str
    name: str
    kind: str
    start: date | None
    end: date | None
    nav_before: float
    nav_after: float
    change: float
    change_pct: float
    drivers: list[StressDriverOut]
    proxied: list[str]
    missing: list[str]


class PortfolioStressOut(BaseModel):
    """Phase 8.4 stress tests, in the base currency, applied instantly (UX-9)."""

    currency: str
    method: str
    basis: str
    scenarios: list[StressScenarioOut]


class RiskLimitsIn(BaseModel):
    """Phase 8.5: each cap is a percentage of NAV, (0, 100], or null for none."""

    max_position_pct: Decimal | None = Field(default=None, gt=0, le=100)
    max_order_pct: Decimal | None = Field(default=None, gt=0, le=100)
    max_sector_pct: Decimal | None = Field(default=None, gt=0, le=100)
    max_currency_pct: Decimal | None = Field(default=None, gt=0, le=100)
    max_var_pct: Decimal | None = Field(default=None, gt=0, le=100)


class RiskLimitsOut(RiskLimitsIn):
    updated_at: datetime | None = None


class LimitCheckOut(BaseModel):
    limit: str
    label: str
    cap: float
    value_after: float | None
    breached: bool
    note: str | None = None


class LimitPreviewOut(BaseModel):
    """What a buy would do to each limit that is set; empty when none are."""

    ticker: str
    quantity: Decimal
    checks: list[LimitCheckOut]
    breached: bool


class PortfolioAnalyticsOut(BaseModel):
    """Aggregated analytics for /v1/portfolio/analytics.

    Time-series metrics are ``None`` until at least two NAV snapshots have
    been recorded. ``history_days`` is the actual span observed (not the
    requested window) so the UI can label charts honestly.
    """

    display_currency: str = "USD"
    history_days: int
    total_return_pct: float | None
    annualised_return_pct: float | None
    sharpe_ratio: float | None
    max_drawdown_pct: float | None
    risk_free_rate: float
    sector_allocation: list[SectorAllocationOut]
    top_gainers: list[TopMoverOut]
    top_losers: list[TopMoverOut]
    returns: PortfolioReturnsOut | None = None
    exposure: PortfolioExposureOut | None = None
    attribution: PortfolioAttributionOut | None = None


class PortfolioOverviewOut(BaseModel):
    """Summary and analytics from the same request-local portfolio valuation."""

    portfolio: PortfolioOut
    analytics: PortfolioAnalyticsOut


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


class OptionTradeIn(BaseModel):
    """Request body for POST /v1/options/trade.

    ``action="open"`` buys a contract — ``ticker``, ``option_type``,
    ``strike``, ``expiry`` and ``quantity`` are required — or, with
    ``side="short"`` (Phase 9.2), writes a covered one: a call covered by
    held shares, a put secured by cash. ``action="close"`` sells a long
    position back or buys a short one back — only ``option_id`` is required.
    """

    action: Literal["open", "close"]
    side: Literal["long", "short"] = "long"
    ticker: str | None = None
    option_type: Literal["call", "put"] | None = None
    strike: Decimal | None = None
    expiry: date | None = None
    quantity: int | None = Field(default=None, ge=1, le=1_000)
    option_id: int | None = None
    # Opens only: a repeat with the same key returns the first contract (LG-10).
    client_order_id: ClientOrderId = None

    @field_validator("strike")
    @classmethod
    def _bounded_strike(cls, value: Decimal | None) -> Decimal | None:
        from stockviz.services.trading.bounds import MAX_PRICE, check_amount

        return None if value is None else check_amount(value, name="strike", maximum=MAX_PRICE)

    @field_validator("expiry")
    @classmethod
    def _bounded_expiry(cls, value: date | None) -> date | None:
        from stockviz._time import utcnow
        from stockviz.services.trading.bounds import MAX_OPTION_YEARS

        horizon = utcnow().date().replace(year=utcnow().year + MAX_OPTION_YEARS)
        if value is not None and value > horizon:
            raise ValueError(f"expiry must be within {MAX_OPTION_YEARS} years")
        return value


class OptionGreeksOut(BaseModel):
    """Per-share Black-Scholes greeks, shown on the ticket and each position.

    ``theta`` is per calendar day; ``vega`` and ``rho`` are per 1.00 (100
    percentage points) of volatility and rate.
    """

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


class OptionRiskOut(BaseModel):
    """What a position can lose and must hold back (Phase 9.2), in USD.

    ``collateral`` is cash reserved (a cash-secured put's strike value); ``shares_reserved`` the shares a
    covered call holds back. ``max_gain`` is null when unbounded.
    """

    collateral: Decimal
    shares_reserved: Decimal
    max_loss: Decimal
    max_gain: Decimal | None
    breakeven: Decimal
    basis: str


class OptionQuoteOut(BaseModel):
    """GET /v1/options/quote: what an open would cost now (audit LG-7).

    Priced by the same function the open charges with. ``spot`` is the latest
    stored close (``spot_at``), ``volatility`` the 30-day historical volatility
    used as the IV proxy, ``per_share`` the Black-Scholes value and
    ``premium`` the charge for ``quantity`` contracts of ``contract_size``.
    """

    ticker: str
    option_type: Literal["call", "put"]
    strike: Decimal
    expiry: date
    quantity: int
    spot: Decimal
    spot_at: datetime
    volatility: float
    risk_free_rate: float
    per_share: Decimal
    premium: Decimal
    contract_size: int
    greeks: OptionGreeksOut
    volatility_method: str
    """How ``volatility`` was estimated, in words."""
    side: Literal["long", "short"] = "long"
    risk: OptionRiskOut
    volatility_closes: int
    premium_floor_applied: bool
    """True when the model price was under the 0.01-a-share minimum (LG-14)."""


class OptionImpliedVolOut(BaseModel):
    """GET /v1/options/implied-volatility: the volatility a price implies.

    ``implied_volatility`` is annualised (0.25 = 25%), or ``null`` with a
    ``reason``. ``historical_volatility`` is what StockViz prices with, for
    comparison.
    """

    ticker: str
    option_type: Literal["call", "put"]
    strike: Decimal
    expiry: date
    per_share_price: Decimal
    spot: Decimal
    spot_at: datetime
    risk_free_rate: float
    implied_volatility: float | None
    reason: str | None
    historical_volatility: float


class OptionPositionOut(BaseModel):
    """One options position with its current Black-Scholes valuation.

    ``premium_paid`` and ``current_value`` are whole-position totals (per-share
    price * 100 * contracts); ``greeks`` are per-share. For a short leg
    (Phase 9.2) ``current_value`` and ``greeks`` are negated: it is a liability.
    """

    id: int
    ticker: str
    option_type: Literal["call", "put"]
    strike: Decimal
    expiry: date
    quantity: int
    premium_paid: Decimal
    status: Literal["open", "closed", "exercised", "expired"]
    opened_at: datetime
    current_value: Decimal
    greeks: OptionGreeksOut
    side: Literal["long", "short"] = "long"
    """``premium_paid`` is the premium received for a short leg (Phase 9.2)."""
    cover: Literal["shares", "cash", "leg"] | None = None
    collateral: Decimal = Decimal(0)
    """USD a cash-secured put holds back while open; 0 otherwise."""
    shares_reserved: Decimal = Decimal(0)
    """Shares a covered call holds back while open; 0 otherwise."""
    strategy_id: int | None = None
    """The strategy this leg was opened in (Phase 9.3)."""
    covering_leg_id: int | None = None


class OptionStrategyIn(BaseModel):
    """A strategy from a template (Phase 9.3). Strikes go low to high:

    - one strike: covered_call, cash_secured_put, protective_put, straddle,
      calendar (with ``far_expiry`` and ``option_type``);
    - two: bull_call, bear_put, bull_put, bear_call, strangle;
    - four: iron_condor (long put, short put, short call, long call).
    """

    kind: Literal[
        "covered_call", "cash_secured_put", "protective_put", "bull_call", "bear_put",
        "bull_put", "bear_call", "iron_condor", "straddle", "strangle", "calendar",
    ]  # fmt: skip
    ticker: str = Field(min_length=1, max_length=16)
    strikes: list[Decimal] = Field(min_length=1, max_length=4)
    expiry: date
    far_expiry: date | None = None
    option_type: Literal["call", "put"] | None = None
    quantity: int = Field(ge=1, le=1_000)
    client_order_id: ClientOrderId = None

    @field_validator("strikes")
    @classmethod
    def _bounded_strikes(cls, value: list[Decimal]) -> list[Decimal]:
        from stockviz.services.trading.bounds import MAX_PRICE, check_amount

        return [check_amount(v, name="strike", maximum=MAX_PRICE) for v in value]


class OptionStrategyLegOut(BaseModel):
    """One leg of a strategy quote: priced per share and for the whole leg (USD)."""

    side: Literal["long", "short"]
    option_type: Literal["call", "put"]
    strike: Decimal
    expiry: date
    per_share: Decimal
    premium: Decimal


class OptionStrategyRiskOut(BaseModel):
    """The strategy's figures at open, in USD. ``net_premium`` is positive when
    credited; ``collateral`` is cash held back while it is open (a covered
    call's ``shares_reserved`` instead); ``max_gain`` null when unbounded or,
    for a calendar, not stated; ``breakevens`` underlying prices at expiry."""

    net_premium: Decimal
    collateral: Decimal
    shares_reserved: Decimal
    max_loss: Decimal
    max_gain: Decimal | None
    breakevens: list[Decimal]
    basis: str


class OptionStrategyQuoteOut(BaseModel):
    kind: str
    label: str
    ticker: str
    quantity: int
    spot: Decimal
    spot_at: datetime
    legs: list[OptionStrategyLegOut]
    risk: OptionStrategyRiskOut


class OptionStrategyOut(BaseModel):
    """An opened strategy and its legs. ``status`` is ``open``, ``closed`` (by
    the user) or ``settled`` (at expiry)."""

    id: int
    kind: str
    label: str
    status: str
    net_premium: Decimal
    collateral: Decimal
    max_loss: Decimal | None
    max_gain: Decimal | None
    opened_at: datetime
    legs: list[OptionPositionOut]


class OptionStrategyTradeOut(BaseModel):
    strategy: OptionStrategyOut
    cash_delta: Decimal


class PayoffPointOut(BaseModel):
    spot: float
    at_expiry: float
    today: float


class OptionStrategyPayoffOut(BaseModel):
    """POST /v1/options/strategies/payoff (Phase 9.5): the quote plus two P&L
    curves after premiums, at the first expiry and today, and the model chance
    of profit (null without volatility or time). ``method`` states the model."""

    quote: OptionStrategyQuoteOut
    horizon: date
    points: list[PayoffPointOut]
    prob_profit: float | None
    volatility: float
    method: str


class UnderlyingGreeksOut(BaseModel):
    ticker: str
    spot: Decimal
    delta_shares: float
    dollar_delta: float
    gamma_shares: float
    theta_per_day: float
    vega_per_point: float
    rho_per_point: float


class ExpiryItemOut(BaseModel):
    label: str
    legs: list[str]
    at_risk: Decimal | None
    outcome: str
    net_cash: Decimal | None
    strategy_id: int | None


class ExpiryGroupOut(BaseModel):
    expiry: date
    items: list[ExpiryItemOut]


class OptionsBookOut(BaseModel):
    """GET /v1/options/book (Phase 9.5): the book's Greeks in money (per
    underlying, and dollar figures summed) and open legs by expiry with what
    today's close would do. ``unpriced`` lists legs with no stored close."""

    underlyings: list[UnderlyingGreeksOut]
    dollar_delta: float
    theta_per_day: float
    vega_per_point: float
    rho_per_point: float
    expirations: list[ExpiryGroupOut]
    unpriced: list[str]
    method: str


class SurfacePointOut(BaseModel):
    strike: Decimal
    call_iv: float | None
    put_iv: float | None


class SurfaceExpiryOut(BaseModel):
    expiry: date
    points: list[SurfacePointOut]


class OptionSurfaceOut(BaseModel):
    """GET /v1/options/surface (Phase 9.6): implied volatility by expiry and
    strike from the latest stored option-chain snapshot, or ``snapshot_date``
    null when none is stored. Annualised (0.25 = 25%)."""

    ticker: str
    snapshot_date: date | None
    spot: Decimal | None
    expiries: list[SurfaceExpiryOut]
    source: str


class OptionTradeOut(BaseModel):
    """Result of an options trade: the affected position plus the cash move
    (negative when premium was paid, positive when proceeds were received)."""

    position: OptionPositionOut
    cash_delta: Decimal


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------


class RsiThresholdStrategy(BaseModel):
    """Buy when RSI(14) drops below ``buy_below``, sell when it rises above ``sell_above``."""

    type: Literal["rsi_threshold"]
    buy_below: float = Field(ge=0, le=100)
    sell_above: float = Field(ge=0, le=100)


class SmaCrossoverStrategy(BaseModel):
    """Buy when the short SMA crosses above the long SMA, sell on the reverse."""

    type: Literal["sma_crossover"]
    short_window: int = Field(ge=1, le=500)
    long_window: int = Field(ge=2, le=500)


StrategySpec = Annotated[
    RsiThresholdStrategy | SmaCrossoverStrategy,
    Field(discriminator="type"),
]


FeeScheduleName = Literal[
    "auto",
    "none",
    "us_equity",
    "us_equity_2026",
    "in_equity_delivery_nse",
    "in_delivery_nse_2026",
    "in_equity_delivery_bse",
    "in_delivery_bse_2026",
]
"""A4.2: backtests trade cash equity on daily bars, so the intraday and F&O
schedules are listed (GET /v1/fees/schedules) but not offered here."""
BrokerageName = Literal["zerodha", "zero"]


HoldoutMode = Literal["last_20pct", "none"]
"""A4.3: ``last_20pct`` (the default) holds out the last 20% of the requested
range: the run, sweeps and walk-forwards see only the first 80% until the
family's holdout is unlocked. ``none`` is an explicit choice, stamped on the
result."""


class BacktestIn(BaseModel):
    """Request body for POST /v1/backtest.

    ``commission_bps`` and ``slippage_bps`` are charged on both legs of every
    round trip. They default to zero (a frictionless run); set them to model
    realistic costs, which is usually what separates a strategy that looks
    profitable from one that is.
    """

    ticker: str
    from_: date = Field(alias="from")
    to: date
    initial_cash: Decimal = Field(gt=0)
    strategy: StrategySpec
    commission_bps: float = Field(default=0.0, ge=0, le=1000)
    slippage_bps: float = Field(default=0.0, ge=0, le=1000)
    # Phase 5.2 (audit SR-7): "price" (default) ignores dividends and says so;
    # "total" credits each dividend to shares held into its ex-date.
    return_mode: Literal["price", "total"] = "price"
    # Phase 5.3 cost models. Owner decision (12 Nov 2026): backtests fill at
    # the next bar's open by default; "next_close" keeps the old rule.
    fill_rule: Literal["next_open", "next_close"] = "next_open"
    # Moves the fill price against the trader (half the spread, plus slippage).
    spread_bps: float = Field(default=0.0, ge=0, le=1000)
    # Regulatory fees per fill; commission_bps is charged on top.
    # Phase 5.6 adds Indian delivery (NSE, BSE); a schedule must match the
    # symbol's currency. A4.2: date-versioned, and "auto" (the default) picks
    # the symbol's market: NSE/BSE delivery for Indian listings, none for the
    # rest (see services/fee_view.py::resolve_fee_schedule).
    fee_schedule: FeeScheduleName = "auto"
    # A4.2: the broker model for Indian brokerage ("zerodha" delivery is free).
    brokerage: BrokerageName = "zerodha"
    # A4.2: at most this % of the 20-day average traded value per buy; null
    # turns the cap off (runs saved before A4.2 rerun without it).
    adv_cap_pct: float | None = Field(default=10.0, gt=0, le=100)
    # A4.3: the last 20% of the range is held out unless "none" is chosen.
    holdout: HoldoutMode = "last_20pct"

    model_config = ConfigDict(populate_by_name=True)


# --- A4.3: the report card and overfitting checks ------------------------


class RunWindowOut(BaseModel):
    """The range a run actually used (A4.3). With the default holdout the
    in-sample range ends the day before ``holdout_from``."""

    requested_from: date
    requested_to: date
    from_date: date
    to_date: date
    holdout: HoldoutMode
    holdout_pct: float | None = None
    holdout_from: date | None = None
    holdout_to: date | None = None
    note: str


class ReportMetricOut(BaseModel):
    key: str
    label: str
    value: float | None = None
    unit: Literal["pct", "ratio", "money", "r", "days", "count"]
    formula: str
    note: str | None = None
    """Why ``value`` is null."""


class SharpeStatsOut(BaseModel):
    """Bailey and López de Prado's inputs: per-day Sharpe of the net excess
    returns, their skewness and kurtosis (not excess), and the PSR."""

    observations: int
    sharpe: float
    """Per day: mean / sample standard deviation of daily excess returns."""
    sharpe_annual: float
    skewness: float | None = None
    kurtosis: float | None = None
    risk_free_rate: float
    psr: float | None = None
    """PSR(0): the probability the true Sharpe is above 0."""
    benchmark_sharpe: float = 0.0
    formula: str


class FanPointOut(BaseModel):
    date: date
    p5: float
    p50: float
    p95: float


class PercentilesOut(BaseModel):
    p5: float
    p50: float
    p95: float


class MonteCarloFanOut(BaseModel):
    """A4.3: the Phase 8 stationary block bootstrap of the run's daily net
    returns, as many sessions as the run had. Seeded: the same run gives the
    same fan."""

    method: str
    paths: int
    mean_block: int
    seed: int
    horizon_days: int
    max_drawdown: PercentilesOut
    final_nav: PercentilesOut
    prob_loss: float
    fan: list[FanPointOut]
    actual_max_drawdown: float


class RegimeRowOut(BaseModel):
    state: str | None = None
    """``Calm trend``, ``Choppy``, ``High-vol down``; null: not enough data."""
    sessions: int
    share: float
    total_return: float
    sharpe: float | None = None
    exposure: float
    trades_entered: int


class RegimeSplitOut(BaseModel):
    market: str | None = None
    index: str | None = None
    rows: list[RegimeRowOut] = []
    index_sessions: int = 0
    breadth_sessions: int = 0
    method: str
    reason: str | None = None


class ReportCardOut(BaseModel):
    """A4.3 (M7.4): everything here is net of costs and depends only on the
    run (it is stored with a saved run and compared on rerun)."""

    metrics: list[ReportMetricOut]
    sharpe: SharpeStatsOut
    monte_carlo: MonteCarloFanOut | None = None
    monte_carlo_reason: str | None = None
    regimes: RegimeSplitOut


class TrialsOut(BaseModel):
    family_key: str
    family_label: str
    definition: str
    scope: Literal["user", "anonymous"]
    n: int
    """Distinct variants (strategy hashes) of the family in the ledger."""
    runs: int
    sharpe_variance: float | None = None
    """Variance of the variants' per-day Sharpes (null under 2 variants)."""
    sharpe_annual_values: list[float] = []


class DsrOut(BaseModel):
    n: int
    sharpe: float
    sharpe_annual: float
    observations: int
    skewness: float | None = None
    kurtosis: float | None = None
    variance: float | None = None
    expected_max_sharpe: float
    expected_max_sharpe_annual: float
    value: float | None = None
    formula: str
    note: str
    meaning: str


class HoldoutResultOut(BaseModel):
    from_date: date
    to_date: date
    total_return: float
    sharpe: float
    max_drawdown: float
    psr: float | None = None
    trades: int


class HoldoutStatusOut(BaseModel):
    mode: HoldoutMode
    status: Literal["locked", "seen", "none"]
    holdout_from: date | None = None
    holdout_to: date | None = None
    unlocked_at: datetime | None = None
    can_unlock: bool = False
    result: HoldoutResultOut | None = None
    note: str


class OverfittingChecksOut(BaseModel):
    """A4.3: what the trial ledger says about this run. Read at response time
    from the ledger and holdout unlocks, so it is never stored with a saved
    run and never part of a rerun's comparison."""

    trials: TrialsOut
    dsr: DsrOut
    holdout: HoldoutStatusOut


class BacktestFeeOut(BaseModel):
    name: str
    amount: Decimal


class FeeSourceOut(BaseModel):
    url: str
    title: str
    date: str
    """The document's own date (ISO), or ``undated page``."""
    read_on: date


class FeeComponentOut(BaseModel):
    key: str
    label: str
    kind: Literal["value", "per_share", "flat", "gst"]
    rate: Decimal
    rate_text: str
    side: Literal["buy", "sell", "both"]
    cap: Decimal | None = None
    gst_on: list[str] = []
    per_scrip_day: bool = False
    note: str = ""
    source: FeeSourceOut


class FeeVersionOut(BaseModel):
    effective_from: date
    effective_to: date | None = None
    start_confirmed: bool = True
    components: list[FeeComponentOut]
    notes: list[str] = []
    fills: int | None = None
    """In a run's ``costs``: the fills priced under this version."""


class BrokerageOut(BaseModel):
    key: str
    label: str
    rate_text: str
    source: FeeSourceOut | None = None


class FeeScheduleOut(BaseModel):
    name: str
    aliases: list[str] = []
    label: str
    currency: str | None = None
    market: str = ""
    segment: str = ""
    venue: str | None = None
    coverage_from: date | None = None
    brokerage: list[BrokerageOut] = []
    versions: list[FeeVersionOut] = []
    notes: list[str] = []
    default_for: list[str] = []
    """Venues (MIC) whose symbols get this schedule by default."""


class FeeSchedulesOut(BaseModel):
    """GET /v1/fees/schedules (A4.2)."""

    schedules: list[FeeScheduleOut]
    defaults: dict[str, str]
    """Venue (MIC) -> the schedule live fills, replay and backtests use by default."""
    default_other: str = "none"
    brokerage_models: list[str]
    notes: list[str] = []


class CostsOut(BaseModel):
    """A4.2: the costs a run applied, each component with its rate and source."""

    schedule: str
    """The resolved family name."""
    requested: str
    label: str
    currency: str | None = None
    segment: str = ""
    brokerage: BrokerageOut | None = None
    commission_bps: float = 0.0
    coverage_from: date | None = None
    fills_before_coverage: int = 0
    versions: list[FeeVersionOut] = []
    notes: list[str] = []
    price_bands_checked: bool = False
    price_bands_note: str | None = None


class LiquidityOut(BaseModel):
    """A4.2: the ADV participation cap."""

    adv_cap_pct: float | None = None
    adv_bars: int = 20
    partial_entries: int = 0
    skipped_entries: int = 0
    not_capped: int = 0
    """Entries with fewer than 20 earlier bars: not capped."""
    note: str


class FeeEstimateLineOut(BaseModel):
    key: str
    label: str
    amount: Decimal
    rate_text: str
    source: FeeSourceOut | None = None


class FeeEstimateOut(BaseModel):
    """GET /v1/fees/estimate (A4.2): the order review's costs."""

    ticker: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    currency: str
    schedule: str
    label: str
    on: date
    effective_from: date | None = None
    before_coverage: bool = False
    brokerage: BrokerageOut | None = None
    notional: Decimal
    total: Decimal
    net_amount: Decimal
    """Buy: value + fees (what is paid). Sell: value - fees (what is received)."""
    lines: list[FeeEstimateLineOut]
    dp_note: str | None = None


class BacktestTradeOut(BaseModel):
    date: date
    side: Literal["buy", "sell"]
    price: Decimal
    shares: Decimal
    # Phase 5.3: the price before spread and slippage, and each fee charged.
    reference_price: Decimal | None = None
    fees: list[BacktestFeeOut] = []
    # A4.2: the shares asked for when the ADV cap bought fewer (null: not capped).
    requested_shares: Decimal | None = None


class EquityPointOut(BaseModel):
    date: date
    nav: Decimal
    # A6.4: an intraday run's point is a bar: its open instant (naive UTC);
    # ``date`` is then its session date.
    at: datetime | None = None


class BacktestSummaryOut(BaseModel):
    """Strategy result, alongside buy-and-hold over the same window.

    ``excess_return`` is the strategy's return minus the benchmark's, in
    percentage points — the number that answers "was this worth doing?".
    """

    total_return: float
    sharpe: float
    max_drawdown: float
    final_nav: Decimal
    benchmark_return: float = 0.0
    benchmark_final_nav: Decimal = Decimal(0)
    excess_return: float = 0.0
    total_costs: Decimal = Decimal(0)
    # A4.2, net first: everything above is after costs; gross adds back the
    # fees and the spread/slippage price cost.
    gross_return: float = 0.0
    gross_final_nav: Decimal = Decimal(0)
    total_fees: Decimal = Decimal(0)
    price_costs: Decimal = Decimal(0)


class UniverseOut(BaseModel):
    """The universe a backtest ran on and whether it is point in time (A1.4a,
    M1.5). ``survivorship_biased`` is true when names that were delisted are
    missing from it, so results look better than an investor could have done.
    Set in one place: ``services/backtest/universe.py``."""

    name: str
    point_in_time: bool
    survivorship_biased: bool
    note: str


class BacktestOut(BaseModel):
    ticker: str
    # Phase 5.2: every amount is in the symbol's currency (audit SR-11).
    currency: str = "USD"
    # The stored bars' basis ("split_adjusted", ...), or "mixed" (audit SR-7).
    price_basis: str | None = None
    return_mode: Literal["price", "total"] = "price"
    # Bars before ``from`` the strategy saw but did not trade on (audit SR-3).
    warmup_bars: int = 0
    # Phase 5.3: the kernel profile (name/version) and fee schedule used.
    execution_profile: str = "legacy_close/v1"
    fee_schedule: str = "none"
    trades: list[BacktestTradeOut]
    equity_curve: list[EquityPointOut]
    summary: BacktestSummaryOut
    # A1.4a: which universe the symbol came from and its survivorship flag.
    universe: UniverseOut
    # A4.2: each cost component with its rate and source, and the ADV cap.
    costs: CostsOut | None = None
    liquidity: LiquidityOut | None = None
    # A4.3: the window used (holdout), the report card, and the ledger's
    # checks (response time only, never stored).
    window: RunWindowOut | None = None
    report: ReportCardOut | None = None
    checks: OverfittingChecksOut | None = None


# --- A4.1: backtests on the Rule DSL -------------------------------------


class StrategyRuleIn(BaseModel):
    """A rule: a setup version (yours or a preset's) or inline Rule DSL text.
    Inline text is saved as a setup version owned by the user when the run is
    saved, so a saved run always points at a version."""

    setup_version_id: int | None = None
    rule: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def _one(self) -> StrategyRuleIn:
        if (self.setup_version_id is None) == (self.rule is None):
            raise ValueError("give exactly one of setup_version_id or rule")
        return self


class AtrStopIn(BaseModel):
    """Entry price minus ``multiple`` x ATR(``period``) at the signal bar
    (plus, for a short). Fixed for the trade."""

    multiple: float = Field(gt=0, le=20)
    period: int = Field(default=14, ge=1, le=250)


class TrailingStopIn(BaseModel):
    """Ratchets with the highest high since entry (lowest low for a short):
    ``pct`` below it, or ``value`` x ATR(``period``) below it. Updated after
    each bar's close, used from the next bar."""

    kind: Literal["atr", "pct"]
    value: float = Field(gt=0, le=50)
    period: int = Field(default=14, ge=1, le=250)


class StrategyStopsIn(BaseModel):
    """Any combination; the first hit wins (see ``StrategyBacktestOut.stop_priority``)."""

    fixed_pct: float | None = Field(default=None, gt=0, le=90)
    atr: AtrStopIn | None = None
    trailing: TrailingStopIn | None = None
    time_bars: int | None = Field(default=None, ge=1, le=2000)


class StrategySizingIn(BaseModel):
    """``all_in``: all free cash (a basket splits it over the free slots);
    ``fixed_fraction``: ``fraction`` of equity per entry; ``fixed_risk``:
    ``risk_pct`` % of equity lost if the initial stop is hit (stop distance
    x quantity), which needs a fixed, ATR or trailing stop. Whole shares;
    never more than the free cash."""

    kind: Literal["all_in", "fixed_fraction", "fixed_risk"] = "all_in"
    fraction: float | None = Field(default=None, gt=0, le=1)
    risk_pct: float | None = Field(default=None, gt=0, le=10)
    max_positions: int | None = Field(default=None, ge=1, le=50)

    @model_validator(mode="after")
    def _params(self) -> StrategySizingIn:
        if self.kind == "fixed_fraction" and self.fraction is None:
            raise ValueError("fixed_fraction sizing needs fraction")
        if self.kind == "fixed_risk" and self.risk_pct is None:
            raise ValueError("fixed_risk sizing needs risk_pct")
        return self


class StrategyUniverseIn(BaseModel):
    """One ticker, one of your watchlists, or up to 50 tickers."""

    ticker: str | None = Field(default=None, min_length=1, max_length=16)
    watchlist_id: int | None = None
    tickers: list[str] | None = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="after")
    def _one(self) -> StrategyUniverseIn:
        given = [v is not None for v in (self.ticker, self.watchlist_id, self.tickers)]
        if sum(given) != 1:
            raise ValueError("give exactly one of ticker, watchlist_id or tickers")
        return self


class StrategyBacktestIn(BaseModel):
    """POST /v1/backtest/strategy (A4.1): a Rule DSL strategy.

    Signals come from the rule's vector mode on each completed bar; orders
    fill on the next bar under ``fill_rule`` through the execution kernel and
    ``SimLedger``. Long only unless ``direction`` is ``short``, which needs
    every symbol listed in ``shortable`` and US-listed (Indian shorts wait for
    the F&O-eligible list)."""

    entry: StrategyRuleIn
    exit: StrategyRuleIn | None = None
    stops: StrategyStopsIn = Field(default_factory=StrategyStopsIn)
    sizing: StrategySizingIn = Field(default_factory=StrategySizingIn)
    universe: StrategyUniverseIn
    from_: date = Field(alias="from")
    to: date
    initial_cash: Decimal = Field(gt=0)
    fill_rule: Literal["next_open", "next_close"] = "next_open"
    fee_schedule: FeeScheduleName = "auto"
    brokerage: BrokerageName = "zerodha"
    adv_cap_pct: float | None = Field(default=10.0, gt=0, le=100)
    commission_bps: float = Field(default=0.0, ge=0, le=1000)
    slippage_bps: float = Field(default=0.0, ge=0, le=1000)
    spread_bps: float = Field(default=0.0, ge=0, le=1000)
    direction: Literal["long", "short"] = "long"
    shortable: list[str] = Field(default_factory=list, max_length=50)
    holdout: HoldoutMode = "last_20pct"
    # A6.4: the bars signals and fills use. ``from``/``to`` stay session
    # dates. An intraday run reads one stored feed (``auto``: the best
    # stored); ``flatten_at_close`` sells a position still open at each
    # session's last bar, at its close.
    timeframe: RuleTimeframe = "daily"
    feed: SetupFeed = "auto"
    flatten_at_close: bool = False

    model_config = ConfigDict(populate_by_name=True)


class StrategyRuleOut(BaseModel):
    role: Literal["entry", "exit"]
    text: str
    canonical: str
    hash: str
    setup_version_id: int | None = None
    warmup_bars: int | None = None
    """Daily bars the rule needs before its first value; null: whole history."""


class StrategyTradeOut(BaseModel):
    """One round trip. ``pnl`` is net of both legs' fees; ``r_multiple`` is
    ``pnl`` over the initial risk (quantity x distance from the entry fill to
    the initial stop), null without a price stop. ``open``: still held at the
    end, marked at the last close (``reason`` ``end_of_data``, no exit fees)."""

    ticker: str
    direction: Literal["long", "short"]
    entry_date: date
    entry_price: Decimal
    entry_reference_price: Decimal
    exit_date: date
    exit_price: Decimal
    exit_reference_price: Decimal
    quantity: Decimal
    entry_fees: Decimal
    exit_fees: Decimal
    pnl: Decimal
    return_pct: float
    reason: Literal[
        "exit_rule", "stop_fixed", "stop_atr", "trail", "time", "end_of_data", "session_close"
    ]
    gap: bool = False
    """The bar opened through the stop, so it filled at the open, not the stop."""
    open: bool = False
    bars_held: int
    initial_stop: Decimal | None = None
    initial_risk: Decimal | None = None
    r_multiple: float | None = None
    requested_quantity: Decimal | None = None
    """A4.2: shares the sizing asked for when the ADV cap filled fewer."""
    exit_adv_pct: float | None = None
    """A4.2: the exit's value as % of the 20-day ADV, when above the cap
    (exits are not capped)."""
    entry_at: datetime | None = None
    """A6.4: an intraday trade's entry and exit bars (open instants, naive
    UTC); ``entry_date``/``exit_date`` are their session dates."""
    exit_at: datetime | None = None
    same_day: bool | None = None
    """A6.4: priced on the same-day (intraday) schedule; null on daily runs."""


class StrategySummaryOut(BacktestSummaryOut):
    """Net first (every figure above is after costs), gross second: the same
    trades with the fees and the spread/slippage price cost added back."""

    gross_return: float = 0.0
    gross_final_nav: Decimal = Decimal(0)
    total_fees: Decimal = Decimal(0)
    price_costs: Decimal = Decimal(0)
    trade_count: int = 0


class StrategySymbolOut(BaseModel):
    ticker: str
    bars: int
    warmup_bars: int
    unknown_entry_bars: int
    unknown_exit_bars: int
    trades: int


class StrategyBenchmarkOut(BaseModel):
    """Buy and hold over the window: the symbol, or an equal-weight basket."""

    kind: Literal["buy_and_hold", "equal_weight_buy_and_hold"]
    tickers: list[str]
    total_return: float
    final_nav: Decimal


class StrategyUniverseSourceOut(BaseModel):
    kind: Literal["ticker", "watchlist", "list"]
    watchlist_id: int | None = None
    name: str | None = None
    tickers: list[str]


class StrategyBacktestOut(BaseModel):
    mode: Literal["strategy"] = "strategy"
    tickers: list[str]
    currency: str
    price_basis: str | None = None
    execution_profile: str
    fee_schedule: str
    direction: Literal["long", "short"] = "long"
    rules: list[StrategyRuleOut]
    stops: StrategyStopsIn
    sizing: StrategySizingIn
    stop_priority: str
    trades: list[StrategyTradeOut]
    equity_curve: list[EquityPointOut]
    summary: StrategySummaryOut
    benchmark: StrategyBenchmarkOut
    source: StrategyUniverseSourceOut
    universe: UniverseOut
    warmup_bars: int = 0
    unknown_entry_bars: int = 0
    """Window bars (all symbols) whose entry signal was unknown: no action."""
    unknown_exit_bars: int = 0
    """Bars in a position whose exit signal was unknown: no action."""
    ignored_entry_signals: int = 0
    """Entry signals while already in that symbol (no pyramiding)."""
    skipped_entries: int = 0
    """Entry signals not taken: no free slot, no cash for one share, or the
    ATR a stop needs unknown at the signal bar."""
    skip_reasons: dict[str, int] = {}
    symbols: list[StrategySymbolOut]
    strategy_hash: str
    data_fingerprint: str
    notes: list[str] = []
    costs: CostsOut | None = None
    liquidity: LiquidityOut | None = None
    window: RunWindowOut | None = None
    report: ReportCardOut | None = None
    checks: OverfittingChecksOut | None = None
    # A6.4: intraday runs (null on daily ones).
    timeframe: str | None = None
    feed: str | None = None
    feed_badge: str | None = None
    flatten_at_close: bool | None = None
    periods_per_year: float | None = None
    """Bars a year the Sharpe and Sortino are annualised by."""


# --- A4.4: cross-sectional rotation ---------------------------------------


class FactorIn(BaseModel):
    """A7.7 (M7.5): one factor of a multi-factor model."""

    name: str | None = Field(default=None, max_length=40)
    expression: str = Field(min_length=1, max_length=2000)
    """A numeric Rule DSL expression per symbol (e.g. ``pct_change(close, 252)``)."""
    weight: float = Field(gt=0, le=10)
    higher_is_better: bool = True


class RotationBacktestIn(BaseModel):
    """POST /v1/backtest/rotation (A4.4): hold the top ``top_n`` symbols of a
    universe by a numeric Rule DSL expression, rebalanced weekly or monthly
    on the venue calendar. ``cash_filter`` is an optional condition judged on
    the market index (``^GSPC`` / ``^NSEI``) at each rebalance close: met
    means hold cash. Long only.

    A7.7 (M7.5): ``factors`` instead of ``ranking`` makes it a multi-factor
    model: each factor is z-scored across the universe on each session
    (symbols with every factor known), signed by ``higher_is_better``, and
    weighted; the weighted sum ranks. Exactly one of the two."""

    ranking: str | None = Field(default=None, min_length=1, max_length=4000)
    """A numeric expression; higher ranks first (e.g. ``pct_change(close, 126)``)."""
    factors: list[FactorIn] | None = Field(default=None, min_length=1, max_length=8)
    top_n: int = Field(default=5, ge=1, le=50)
    schedule: Literal["weekly", "monthly"] = "monthly"
    weighting: Literal["equal", "inverse_volatility"] = "equal"
    buffer: int = Field(default=0, ge=0, le=50)
    """Hysteresis: a holding is kept while its rank is at most top_n + buffer."""
    cash_filter: StrategyRuleIn | None = None
    universe: StrategyUniverseIn
    from_: date = Field(alias="from")
    to: date
    initial_cash: Decimal = Field(gt=0)
    fill_rule: Literal["next_open", "next_close"] = "next_open"
    fee_schedule: FeeScheduleName = "auto"
    brokerage: BrokerageName = "zerodha"
    adv_cap_pct: float | None = Field(default=10.0, gt=0, le=100)
    commission_bps: float = Field(default=0.0, ge=0, le=1000)
    slippage_bps: float = Field(default=0.0, ge=0, le=1000)
    spread_bps: float = Field(default=0.0, ge=0, le=1000)
    holdout: HoldoutMode = "last_20pct"

    @model_validator(mode="after")
    def _one_ranking(self) -> RotationBacktestIn:
        if (self.ranking is None) == (self.factors is None):
            raise ValueError("give exactly one of ranking or factors")
        return self

    model_config = ConfigDict(populate_by_name=True)


class RotationRankOut(BaseModel):
    ticker: str
    value: float
    rank: int


class RotationUnrankedOut(BaseModel):
    ticker: str
    reason: Literal["no_bar", "unknown", "volatility_unknown"]


class RotationRebalanceOut(BaseModel):
    """One rebalance: ranked on ``signal_date``'s close, traded on each
    symbol's next bar (``trade_dates``)."""

    signal_date: date
    trade_dates: list[date] = []
    equity: Decimal
    cash_filter: bool | None = None
    """The cash filter at this close (null: no filter, or unknown)."""
    skipped: str | None = None
    ranked: list[RotationRankOut] = []
    unranked: list[RotationUnrankedOut] = []
    held_before: list[str] = []
    held_after: list[str] = []
    entered: list[str] = []
    exited: list[str] = []
    weights: dict[str, float] = {}
    """Target weight of every name held after (fraction of the equity)."""
    bought: Decimal = Decimal(0)
    sold: Decimal = Decimal(0)
    turnover: float = 0.0
    replaced_orders: int = 0
    not_filled: dict[str, int] = {}


class RotationTradeOut(BaseModel):
    ticker: str
    entry_date: date
    entry_price: Decimal
    entry_reference_price: Decimal
    exit_date: date
    exit_price: Decimal
    exit_reference_price: Decimal
    quantity: Decimal
    entry_fees: Decimal
    exit_fees: Decimal
    pnl: Decimal
    return_pct: float
    reason: Literal["rebalance", "resize", "cash_filter", "end_of_data"]
    """``resize``: shares trimmed back to the target weight (entry at the
    holding's average price)."""
    open: bool = False
    bars_held: int
    requested_quantity: Decimal | None = None
    exit_adv_pct: float | None = None


class RotationRuleOut(BaseModel):
    role: Literal["ranking", "cash_filter", "factor"]
    text: str
    canonical: str
    hash: str
    setup_version_id: int | None = None
    warmup_bars: int | None = None


class RotationTurnoverOut(BaseModel):
    """One-way turnover: (bought + sold) / 2 / equity at the rebalance close."""

    rebalances: int
    mean_per_rebalance: float
    total: float
    annualised: float
    definition: str


class RotationBacktestOut(BaseModel):
    mode: Literal["rotation"] = "rotation"
    tickers: list[str]
    currency: str
    price_basis: str | None = None
    execution_profile: str
    fee_schedule: str
    rules: list[RotationRuleOut]
    top_n: int
    schedule: Literal["weekly", "monthly"]
    weighting: Literal["equal", "inverse_volatility"]
    buffer: int = 0
    venue: str
    cash_filter_index: str | None = None
    timing: str
    rebalances: list[RotationRebalanceOut]
    trades: list[RotationTradeOut]
    equity_curve: list[EquityPointOut]
    summary: StrategySummaryOut
    benchmark: StrategyBenchmarkOut
    turnover: RotationTurnoverOut
    source: StrategyUniverseSourceOut
    universe: UniverseOut
    warmup_bars: int = 0
    cash_filter_unknown: int = 0
    unfilled_at_end: int = 0
    skip_reasons: dict[str, int] = {}
    strategy_hash: str
    data_fingerprint: str
    notes: list[str] = []
    costs: CostsOut | None = None
    liquidity: LiquidityOut | None = None
    window: RunWindowOut | None = None
    report: ReportCardOut | None = None
    checks: OverfittingChecksOut | None = None


# --- A4.5: scan event study ------------------------------------------------


class ScanUniverseIn(BaseModel):
    """Up to 50 tickers, one of your watchlists, or a whole market
    (``US`` or ``IN``: its active non-index symbols)."""

    tickers: list[str] | None = Field(default=None, min_length=1, max_length=50)
    watchlist_id: int | None = None
    market: Literal["US", "IN"] | None = None

    @model_validator(mode="after")
    def _one(self) -> ScanUniverseIn:
        given = [v is not None for v in (self.tickers, self.watchlist_id, self.market)]
        if sum(given) != 1:
            raise ValueError("give exactly one of tickers, watchlist_id or market")
        return self


class ScanEventStudyIn(BaseModel):
    """POST /v1/research/scan-event-study (A4.5): what happened after a Rule
    DSL condition turned true. ``trigger`` is a setup version or inline text
    (news and delivery triggers are rules too: ``news.count(1) >= 1``,
    ``delivery_pct > 60``)."""

    trigger: StrategyRuleIn
    universe: ScanUniverseIn
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    horizons: list[int] = Field(default_factory=lambda: [5, 20, 60], min_length=1, max_length=5)
    cooldown: int = Field(default=0, ge=0, le=250)
    """Sessions after an event during which a new event on the symbol is skipped."""

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _horizons(self) -> ScanEventStudyIn:
        if any(h < 1 or h > 250 for h in self.horizons):
            raise ValueError("each horizon must be between 1 and 250 sessions")
        self.horizons = sorted(set(self.horizons))
        return self


class ScanTriggerOut(BaseModel):
    text: str
    canonical: str
    hash: str
    setup_version_id: int | None = None
    uses: list[str] = []
    warmup_bars: int | None = None


class ScanUniverseSourceOut(BaseModel):
    kind: Literal["list", "watchlist", "market"]
    name: str | None = None
    watchlist_id: int | None = None
    market: str | None = None
    tickers: int


class ScanPercentilesOut(BaseModel):
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


class HistogramOut(BaseModel):
    """Counts of net returns in equal bins from the 1st to the 99th
    percentile; values beyond fall in the end bins."""

    edges: list[float]
    counts: list[int]


class ScanHorizonOut(BaseModel):
    """One forward horizon. Returns are fractions (0.01 = 1%). Under
    ``min_events`` only the counts are given."""

    horizon: int
    n: int
    symbols: int
    incomplete: int
    overlapping: int
    enough: bool
    base_rate: float | None = None
    mean_net: float | None = None
    median_net: float | None = None
    mean_excess: float | None = None
    median_excess: float | None = None
    hit_rate: float | None = None
    """Share of events with a net return above zero."""
    hit_rate_excess: float | None = None
    """Share of events whose net return beat the base rate."""
    t_stat: float | None = None
    t_stat_clustered: float | None = None
    clusters: int = 0
    net_percentiles: ScanPercentilesOut | None = None
    excess_percentiles: ScanPercentilesOut | None = None
    histogram: HistogramOut | None = None
    fee_schedules: dict[str, int] = {}


class ScanEventOut(BaseModel):
    ticker: str
    date: date
    net: dict[str, float | None]
    """Net forward return per horizon (key: sessions), null if incomplete."""
    excess: dict[str, float | None]


class ScanEventStudyOut(BaseModel):
    trigger: ScanTriggerOut
    source: ScanUniverseSourceOut
    from_: date = Field(serialization_alias="from")
    to: date
    cooldown: int
    horizons: list[ScanHorizonOut]
    min_events: int
    events_found: int
    events_skipped_cooldown: int
    events: list[ScanEventOut]
    events_shown: int
    method: dict[str, str]
    universe: UniverseOut
    disclaimer: str

    model_config = ConfigDict(populate_by_name=True)


class ExperimentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    hypothesis: str | None = Field(default=None, max_length=4000)


class ExperimentOut(BaseModel):
    id: int
    name: str
    hypothesis: str | None
    created_at: datetime
    run_count: int = 0


class ExperimentRunIn(BaseModel):
    """Save a backtest (Phase 5.4): the same body as POST /v1/backtest, or
    (A4.1) a Rule DSL strategy, the body of POST /v1/backtest/strategy."""

    backtest: BacktestIn | None = None
    strategy: StrategyBacktestIn | None = None
    rotation: RotationBacktestIn | None = None
    """A4.4: a rotation, the body of POST /v1/backtest/rotation."""
    experiment_id: int | None = None

    @model_validator(mode="after")
    def _one(self) -> ExperimentRunIn:
        given = [v is not None for v in (self.backtest, self.strategy, self.rotation)]
        if sum(given) != 1:
            raise ValueError("give exactly one of backtest, strategy or rotation")
        return self


class WalkForwardIn(BaseModel):
    """Phase 5.5. ``backtest`` sets the symbol, range, cash, costs and fees;
    its strategy type picks the default grid when ``grid`` is empty."""

    backtest: BacktestIn
    grid: list[StrategySpec] | None = Field(default=None, max_length=50)
    in_sample_years: int = Field(default=3, ge=1, le=20)
    out_of_sample_years: int = Field(default=1, ge=1, le=10)
    step_years: int = Field(default=1, ge=1, le=10)
    score: Literal["sharpe", "total_return"] = "sharpe"
    experiment_id: int | None = None


class SweepIn(BaseModel):
    backtest: BacktestIn
    grid: list[StrategySpec] | None = Field(default=None, max_length=50)
    score: Literal["sharpe", "total_return"] = "sharpe"
    experiment_id: int | None = None


class ExperimentRunOut(BaseModel):
    id: int
    experiment_id: int | None
    parent_run_id: int | None = None
    kind: str
    ticker: str
    request: dict
    execution_profile: str
    fee_schedule: str
    code_version: str
    dataset_fingerprint: str
    bar_count: int
    first_bar_at: datetime | None
    last_bar_at: datetime | None
    created_at: datetime
    summary: BacktestSummaryOut
    # A1.4a: the stored result's universe stamp; runs saved before it existed
    # get the stamp that held for them (the pinned list, survivorship-biased).
    universe: UniverseOut
    # Full stored result; omitted from list responses. A BacktestOut for
    # ``single`` runs; for ``walk_forward`` and ``sweep`` runs, the shape their
    # ``result_kind`` names (windows + stitched curve, or ranked settings).
    result: dict[str, Any] | None = None
    # A4.3: the ledger's checks for this run, read now (full reads only).
    checks: OverfittingChecksOut | None = None


class ExperimentRerunOut(BaseModel):
    """``identical``: same data, same result. ``data_changed``: the bars or
    dividends the run read are not the same any more, so nothing is compared.
    ``different``: same data, different result (the code changed)."""

    status: Literal["identical", "different", "data_changed"]
    stored_fingerprint: str
    current_fingerprint: str
    differences: list[str] = []


# ---------------------------------------------------------------------------
# Markets summary
# ---------------------------------------------------------------------------


class MarketSummaryRowOut(BaseModel):
    """One row of the /markets table, with its sparkline series inlined."""

    ticker: str
    name: str
    sector: str | None = None
    exchange: str | None = None
    currency: str = "USD"
    last_close: Decimal | None = None
    # Timestamp of the stored bar behind last_close, so the page can date the
    # price (web UI audit T1). None when the symbol has no stored bars.
    last_close_at: datetime | None = None
    prev_close: Decimal | None = None
    change_pct: float | None = None
    # Oldest-first closes for the inline sparkline.
    closes: list[Decimal] = []


class MarketsSummaryOut(BaseModel):
    """Everything the markets page renders, in one response.

    ``sectors`` lists every sector in the active universe (not just the
    filtered slice) so the filter control needs no second request.
    """

    rows: list[MarketSummaryRowOut]
    sectors: list[str]


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------


class SentimentPointOut(BaseModel):
    """Mean sentiment for one day, over the articles scored that day."""

    date: str
    mean_score: float
    article_count: int


class SentimentSeriesOut(BaseModel):
    """Daily sentiment for one symbol, plus the rolling figure the screener uses.

    Days with no scored articles are omitted rather than emitted as zero: a gap
    and a genuinely neutral day are different readings.
    """

    ticker: str
    points: list[SentimentPointOut]
    rolling_7d: float | None = None
    rolling_7d_article_count: int = 0


# ---------------------------------------------------------------------------
# Trading Journal
# ---------------------------------------------------------------------------


class JournalStatsOut(BaseModel):
    """Realized-P&L roll-up for a day, a week, or a month.

    ``trade_count`` counts every closing execution, so scratches (exactly zero
    realized P&L) are included there but in neither ``winning_trades`` nor
    ``losing_trades``. ``win_rate`` is ``None`` when nothing was decided, and
    ``profit_factor`` is ``None`` when nothing was lost — a made-up number
    would be worse than a hidden metric.

    Money is USD, serialized as a decimal string (see docs/TRADING_JOURNAL.md
    for why the Journal does not convert into the display currency).
    """

    realized_pnl: Decimal
    trade_count: int
    winning_trades: int
    losing_trades: int
    gross_profit: Decimal
    gross_loss: Decimal
    win_rate: float | None = None
    profit_factor: float | None = None


class JournalDaySummaryOut(BaseModel):
    date: str
    stats: JournalStatsOut


class JournalWeekSummaryOut(BaseModel):
    """One Monday-anchored week, clipped to the month being viewed."""

    start: str
    end: str
    stats: JournalStatsOut


class JournalPeriodOut(BaseModel):
    year: int
    month: int
    first_day: str
    last_day: str


class JournalMonthOut(BaseModel):
    """A month of realized trading. Carries no trade list by design.

    ``days`` holds only the sessions that had a closing execution, so the
    payload stays O(days) however many trades the account has. Per-trade
    detail is fetched lazily from the day endpoint.

    ``return_pct`` is realized P&L as a percentage of NAV at the start of the
    month, and is ``None`` when no snapshot predates it. It is not a
    time-weighted return.
    """

    period: JournalPeriodOut
    currency: str = "USD"
    summary: JournalStatsOut
    return_pct: float | None = None
    start_nav: Decimal | None = None
    days: list[JournalDaySummaryOut]
    weeks: list[JournalWeekSummaryOut]
    unavailable_count: int = 0


class JournalSignalOut(BaseModel):
    """The rule-based score that stood when the trade was placed.

    Reserved for persisted opening-decision provenance. Currently null: closing
    fills do not identify their opening decisions in the average-cost book.
    """

    score: int
    max_score: int
    computed_at: datetime


class JournalExecutionOut(BaseModel):
    """One closing execution — the Journal's definition of a "trade".

    Equity legs carry ``side``/``quantity``/``price``/``avg_cost``; option legs
    carry the contract terms plus ``premium_paid``/``proceeds``. ``avg_cost``
    is the native weighted-average basis captured before the sell. It is
    ``None`` for legacy fills; rounded realized P&L cannot recover it exactly.
    """

    kind: str
    reference_id: int
    ticker: str
    session_date: str
    executed_at: datetime
    realized_pnl: Decimal
    currency: str = "USD"

    side: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    avg_cost: Decimal | None = None

    option_type: str | None = None
    strike: Decimal | None = None
    expiry: str | None = None
    contracts: int | None = None
    premium_paid: Decimal | None = None
    proceeds: Decimal | None = None
    option_status: str | None = None

    signal_at_entry: JournalSignalOut | None = None


class JournalDayOut(BaseModel):
    date: str
    currency: str = "USD"
    stats: JournalStatsOut
    executions: list[JournalExecutionOut]
    offset: int = 0
    has_more: bool = False
    unavailable_count: int = 0


class JournalWeekOut(BaseModel):
    start: str
    end: str
    currency: str = "USD"
    stats: JournalStatsOut
    best_trade: JournalExecutionOut | None = None
    worst_trade: JournalExecutionOut | None = None
    unavailable_count: int = 0


class BaseCurrencyIn(BaseModel):
    """``PUT /v1/portfolio/base-currency``: restart a fresh account in USD or INR."""

    base_currency: str = Field(min_length=3, max_length=3)


# ---------------------------------------------------------------------------
# Books (A5.1)
# ---------------------------------------------------------------------------


class BookOut(BaseModel):
    """One book: a paper book trades here; an imported one holds a broker's fills."""

    id: int
    name: str
    kind: Literal["paper", "imported"]
    is_default: bool
    # False for an imported book: holdings only, cash stays 0.
    cash_tracked: bool
    broker: str | None = None
    holder_kind: Literal["self", "family", "huf"]
    holder_label: str | None = None
    base_currency: str
    archived_at: datetime | None = None
    created_at: datetime
    # Paper and not archived: trades, orders and options may land in it.
    writable: bool
    # What the book has done (trades, orders, ...); empty = fresh, so its
    # base currency can still change and it can be deleted outright.
    activity: list[str] = Field(default_factory=list)


class BooksOut(BaseModel):
    books: list[BookOut]
    limit: int


class BookIn(BaseModel):
    """``POST /v1/books``."""

    name: str = Field(min_length=1, max_length=60)
    kind: Literal["paper", "imported"] = "paper"
    base_currency: Literal["USD", "INR"] = "USD"
    holder_kind: Literal["self", "family", "huf"] = "self"
    # Free text ("Mum", "Jariwala HUF"). Never a PAN: a PAN-shaped label is 422.
    holder_label: str | None = Field(default=None, max_length=60)
    # Imported books only; default zerodha.
    broker: Literal["zerodha", "dhan", "fyers", "upstox", "angelone", "groww", "other"] | None = (
        None
    )


class BookPatch(BaseModel):
    """``PATCH /v1/books/{id}``. Absent fields stay; ``holder_label: null`` clears it."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    holder_kind: Literal["self", "family", "huf"] | None = None
    holder_label: str | None = Field(default=None, max_length=60)
    archived: bool | None = None
    # Only true: the default moves to this book.
    is_default: Literal[True] | None = None


# ---------------------------------------------------------------------------
# Notifications (Phase 7.2)
# ---------------------------------------------------------------------------


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    title: str
    body: str
    link: str | None
    created_at: datetime
    read_at: datetime | None
    # A2.3: structured detail, e.g. a screen's {"entries": [...], "exits": [...]}.
    data: dict[str, Any] | None = None


class UnreadCountOut(BaseModel):
    unread: int


ChannelName = Literal["webhook", "email", "telegram"]


class NotificationChannelOut(BaseModel):
    """One delivery channel (A2.3). The webhook secret is never returned."""

    channel: ChannelName
    enabled: bool = False
    # False when the server lacks the channel's config (SMTP_*, TELEGRAM_BOT_TOKEN).
    available: bool
    # The user's part is filled in (webhook URL and secret, Telegram chat id).
    configured: bool = False
    url: str | None = None  # webhook
    secret_set: bool = False  # webhook
    address: str | None = None  # email; null = the account email
    chat_id: str | None = None  # telegram
    muted_categories: list[str] = []
    updated_at: datetime | None = None


class NotificationChannelsOut(BaseModel):
    channels: list[NotificationChannelOut]
    # Categories a channel can mute.
    categories: list[str]


class NotificationChannelIn(BaseModel):
    """A change to one channel. Fields left null are unchanged."""

    channel: ChannelName
    enabled: bool | None = None
    url: str | None = Field(default=None, max_length=500)
    # Write-only. An empty string removes it.
    secret: str | None = Field(default=None, max_length=256)
    address: str | None = Field(default=None, max_length=320)
    chat_id: str | None = Field(default=None, max_length=64)
    muted_categories: list[str] | None = None


class NotificationChannelsIn(BaseModel):
    channels: list[NotificationChannelIn] = Field(min_length=1, max_length=3)


class NotificationChannelTestOut(BaseModel):
    channel: ChannelName
    ok: bool
    detail: str


# ---------------------------------------------------------------------------
# News event studies (Phase 7.4)
# ---------------------------------------------------------------------------


class EventStudyWindowOut(BaseModel):
    start: int
    end: int
    mean_car_pct: float | None
    std_error_pct: float | None
    t_stat: float | None


class EventStudyPointOut(BaseModel):
    offset: int
    mean_car_pct: float | None
    std_error_pct: float | None


class EventStudyEventOut(BaseModel):
    ticker: str
    document_id: str
    title: str
    available_at: datetime
    event_date: date
    car_pct: float


class EventStudyOut(BaseModel):
    """Abnormal returns around news of a kind. Association, not cause."""

    tickers: list[str]
    sentiment: str | None
    event_type: str | None
    pre: int
    post: int
    model: str = "market-adjusted: stock log return minus its market index's"
    benchmarks: dict[str, str]
    no_benchmark: list[str]
    min_events: int
    enough: bool
    events_found: int
    events_used: int
    events_incomplete: int
    overlapping: int
    windows: list[EventStudyWindowOut]
    path: list[EventStudyPointOut]
    events: list[EventStudyEventOut]


# ---------------------------------------------------------------------------
# Checklist (A2.4, M4.4)
# ---------------------------------------------------------------------------

ChecklistStatus = Literal["met", "not_met", "unknown"]
ChecklistGrade = Literal["A", "B", "C", "D", "insufficient"]


class ChecklistEvidenceOut(BaseModel):
    """The latest evidence study of one dimension setup version: the forward
    20-session return after the rule turned true, net of fees, against the
    base rate (``services/checklist/evidence.py``). Association, not advice."""

    grade: ChecklistGrade
    n_events: int
    symbols: int
    horizon: int
    window_start: date
    window_end: date
    mean_excess: float | None = None
    t_stat: float | None = None
    hit_rate: float | None = None
    mean_net_return: float | None = None
    base_rate: float | None = None
    overlapping_skipped: int = 0
    fee_schedules: dict[str, int] = Field(default_factory=dict)
    universe: UniverseOut
    computed_at: datetime


class ChecklistConditionDefOut(BaseModel):
    label: str
    rule: str  # canonical text


class ChecklistVariantOut(BaseModel):
    """One setup of a dimension: ``all`` listings, or ``india`` / ``other``."""

    scope: Literal["all", "india", "other"]
    setup_id: int
    setup_version_id: int
    version: int
    canonical: str
    hash: str
    conditions: list[ChecklistConditionDefOut]
    evidence: ChecklistEvidenceOut | None = None


class ChecklistDimensionOut(BaseModel):
    key: str
    name: str
    summary: str
    source: str
    variants: list[ChecklistVariantOut]


class ChecklistConditionOut(BaseModel):
    label: str
    rule: str
    status: ChecklistStatus
    reason: str | None = None


class ChecklistResultOut(BaseModel):
    key: str
    scope: Literal["all", "india", "other"]
    setup_version_id: int | None = None
    status: ChecklistStatus
    reason: str | None = None
    conditions: list[ChecklistConditionOut] = Field(default_factory=list)


class ChecklistRowOut(BaseModel):
    """One symbol's checklist on its venue session. ``met`` of ``total`` (6)
    dimensions met; ``evaluated`` judged met or not met (the rest unknown).
    Neutral wording only: a count of conditions, never a call to buy or sell."""

    ticker: str
    name: str
    sector: str | None = None
    currency: str | None = None
    session_date: date
    met: int
    evaluated: int
    total: int
    results: list[ChecklistResultOut]
    computed_at: datetime
    # The session trails the newest checklist session of the same venue by
    # more than five days (a stalled symbol).
    stale: bool = False


class ChecklistOut(BaseModel):
    dimensions: list[ChecklistDimensionOut]
    rows: list[ChecklistRowOut]
    total: int
    universe: UniverseOut
    disclaimer: str


class SymbolChecklistOut(BaseModel):
    ticker: str
    dimensions: list[ChecklistDimensionOut]
    row: ChecklistRowOut | None = None
    universe: UniverseOut
    disclaimer: str


# ---------------------------------------------------------------------------
# Chart drawings (A3.2, M2.4)
# ---------------------------------------------------------------------------

DrawingKind = Literal[
    "trendline",
    "ray",
    "hline",
    "rectangle",
    "channel",
    "fib_retracement",
    "fib_extension",
    "ruler",
    "text",
    "position_long",
    "position_short",
    "avwap",
    "volume_profile",
]
DrawingColour = Literal["aqua", "blue", "violet", "pink", "amber", "lime", "slate", "foreground"]


class DrawingPoint(BaseModel):
    """An anchor: a daily bar's venue date and a price. ``ts`` is null only
    where the kind takes a price alone (an hline, a position's stop and
    target). ``price`` is null only for an anchored VWAP (A3.3), whose one
    point is its anchor date."""

    ts: date | None = None
    price: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)


class DrawingStyle(BaseModel):
    colour: DrawingColour = "aqua"
    width: int = Field(default=1, ge=1, le=4)
    dash: Literal["solid", "dashed", "dotted"] = "solid"
    fill_opacity: float = Field(default=0.12, ge=0, le=0.5)
    # A3.3: an anchored VWAP's bands (0 none, 1 = +-1, 2 = +-1 and +-2
    # standard deviations); other kinds ignore it.
    bands: int = Field(default=0, ge=0, le=2)


class DrawingIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    kind: DrawingKind
    points: list[DrawingPoint] = Field(min_length=1, max_length=3)
    style: DrawingStyle = Field(default_factory=DrawingStyle)
    label: str | None = Field(default=None, max_length=80)
    locked: bool = False


class DrawingPatch(BaseModel):
    """Only the fields sent change; ``label: null`` clears it. A locked
    drawing takes only ``locked`` (409 otherwise)."""

    points: list[DrawingPoint] | None = Field(default=None, min_length=1, max_length=3)
    style: DrawingStyle | None = None
    label: str | None = Field(default=None, max_length=80)
    locked: bool | None = None


class PositionMetricsOut(BaseModel):
    """The position tool's figures, per share, in the symbol's currency."""

    side: Literal["long", "short"]
    entry: Decimal
    stop: Decimal
    target: Decimal
    risk_per_share: Decimal
    reward_per_share: Decimal
    # reward / risk: the target is this many R from the entry.
    reward_risk: Decimal
    stop_pct: Decimal
    target_pct: Decimal


class DrawingOut(BaseModel):
    id: int
    ticker: str
    kind: DrawingKind
    points: list[DrawingPoint]
    style: DrawingStyle
    label: str | None
    locked: bool
    position: PositionMetricsOut | None = None
    created_at: datetime
    updated_at: datetime


class DrawingsOut(BaseModel):
    ticker: str
    drawings: list[DrawingOut]
    limit: int
    # The stored daily bar range anchors must fall in (null: no bars).
    first_bar: date | None
    last_bar: date | None


# ---------------------------------------------------------------------------
# Anchored VWAP (A3.3, M2.5)
# ---------------------------------------------------------------------------


class AvwapPointOut(BaseModel):
    """One bar's anchored VWAP. ``ts`` is the bar's time as the bars route
    gives it (on weekly/monthly the period's last stored session). Bands are
    null unless asked for."""

    ts: datetime
    vwap: float
    upper1: float | None = None
    lower1: float | None = None
    upper2: float | None = None
    lower2: float | None = None


class AvwapOut(BaseModel):
    ticker: str
    anchor: date
    # The first stored daily bar on or after ``anchor``: where the sums start.
    anchor_bar: date
    interval: Literal["1d", "1wk", "1mo", "1m", "5m", "15m", "30m", "60m"]
    bands: int
    # "daily": weekly/monthly values are the daily AVWAP sampled at each
    # period's last stored session. A6.2, intraday: "1m" (computed from minute
    # bars and sampled at each bar's last minute, keyed by the bar's open) or
    # "60m" (on the 60-minute chart's own bars).
    computed_from: Literal["daily", "1m", "60m"] = "daily"
    # A6.2, intraday: the instant asked for and the open of the first bar the
    # sums start at (naive UTC); null on daily intervals.
    anchor_at: datetime | None = None
    anchor_bar_at: datetime | None = None
    feed: str | None = None
    decimals: int
    points: list[AvwapPointOut]


class VolumeProfileBinOut(BaseModel):
    low: Decimal
    high: Decimal
    # The volume spread into this price slice (a share of each bar's volume).
    volume: float


class VolumeProfileOut(BaseModel):
    """A6.7 (M2.9): ``GET /v1/symbols/{ticker}/volume-profile``.

    ``bins`` run from the lowest price up. ``poc`` is the middle of the bin with
    the most volume; ``vah``/``val`` bound the value area (``value_area`` of the
    volume, 0.7 by default). ``source`` is ``minutes`` (stored 1-minute bars on
    ``feed``) or ``daily`` (an EOD approximation). ``from``/``to`` are the range
    read, naive UTC.
    """

    model_config = ConfigDict(populate_by_name=True)

    ticker: str
    source: Literal["minutes", "daily"]
    feed: str | None = None
    from_: datetime = Field(alias="from")
    to: datetime
    bars: int
    bins: list[VolumeProfileBinOut]
    poc: Decimal
    poc_index: int
    vah: Decimal
    val: Decimal
    value_area: float
    total_volume: float
    value_volume: float
    badges: list[str]
    note: str


# ---------------------------------------------------------------------------
# A3.5: relative strength, delivery, chart events, market regime
# ---------------------------------------------------------------------------


class RelativeStrengthPeriodOut(BaseModel):
    period: Literal["1m", "3m", "6m", "12m"]
    sessions: int
    return_pct: float | None = None
    percentile: float | None = None


class RelativeStrengthUniverseOut(BaseModel):
    market: Literal["US", "IN"] | None = None
    size: int
    as_of: date | None = None
    point_in_time: bool = False
    survivorship_biased: bool = True
    note: str


class RelativeStrengthOut(BaseModel):
    ticker: str
    market: Literal["US", "IN"] | None = None
    benchmark: str | None = None
    benchmark_name: str | None = None
    as_of: date | None = None
    periods: list[RelativeStrengthPeriodOut]
    method: str
    universe: RelativeStrengthUniverseOut
    high_52w: float | None = None
    last_close: float | None = None
    distance_from_high_52w_pct: float | None = None
    reason: str | None = None


class DeliveryPointOut(BaseModel):
    ts: date
    delivery_pct: float
    avg_20: float | None = None


class DeliveryOut(BaseModel):
    ticker: str
    interval: Literal["1d", "1wk", "1mo"]
    applicable: bool
    has_data: bool
    avg_sessions: int
    points: list[DeliveryPointOut]
    note: str | None = None


class NewsHeadlineOut(BaseModel):
    id: str
    title: str
    source: str | None = None
    url: str | None = None
    available_at: datetime
    published_at: datetime | None = None


class NewsEventOut(BaseModel):
    type: Literal["news"] = "news"
    date: date
    count: int
    sources: list[str]
    headlines: list[NewsHeadlineOut]


class EarningsMarkerOut(BaseModel):
    type: Literal["earnings"] = "earnings"
    date: date
    report_time: str | None = None
    fiscal_period: str | None = None
    eps_estimate: Decimal | None = None
    eps_actual: Decimal | None = None
    surprise_pct: Decimal | None = None


class DividendEventOut(BaseModel):
    type: Literal["dividend"] = "dividend"
    date: date
    amount: Decimal
    currency: str


class SplitEventOut(BaseModel):
    type: Literal["split"] = "split"
    date: date
    ratio_from: Decimal
    ratio_to: Decimal


class FillEventOut(BaseModel):
    type: Literal["fill"] = "fill"
    date: date
    ts: datetime
    side: str
    quantity: Decimal
    price: Decimal
    # A5.5: the R of the journal entry this fill closes (null on opening and
    # partial fills, and without a plan stop).
    r_multiple: float | None = None
    # A5.1: the book the fill landed in.
    book_id: int | None = None
    # A5.5: the journal entry the fill belongs to (once the journal was read).
    journal_entry_id: int | None = None
    closes_entry: bool = False


SymbolEventOut = Annotated[
    NewsEventOut | EarningsMarkerOut | DividendEventOut | SplitEventOut | FillEventOut,
    Field(discriminator="type"),
]


class SymbolEventsOut(BaseModel):
    ticker: str
    from_date: date = Field(serialization_alias="from")
    to_date: date = Field(serialization_alias="to")
    types: list[Literal["news", "earnings", "dividend", "split", "fill"]]
    fills_included: bool
    news_rule: str
    events: list[SymbolEventOut]


class RegimeInputOut(BaseModel):
    name: str
    value: float | None = None
    description: str


class RegimeRuleOut(BaseModel):
    state: Literal["Calm trend", "Choppy", "High-vol down"]
    rule: str
    description: str
    met: bool | None = None


class MarketRegimeOut(BaseModel):
    market: Literal["US", "IN"]
    name: str
    index: str
    index_name: str
    as_of: date | None = None
    state: Literal["Calm trend", "Choppy", "High-vol down"] | None = None
    reason: str | None = None
    inputs: list[RegimeInputOut]
    rules: list[RegimeRuleOut]
    breadth_count: int
    breadth_universe: int
    breadth_as_of: date | None = None
    vol_window_sessions: int
    hv_20: float | None = None


class RegimeOut(BaseModel):
    markets: list[MarketRegimeOut]
    method: str
    disclaimer: str


class HoldoutUnlockIn(BaseModel):
    """A4.3: unlock a strategy family's holdout, once: the request of the run on screen."""

    backtest: BacktestIn | None = None
    strategy: StrategyBacktestIn | None = None
    rotation: RotationBacktestIn | None = None

    @model_validator(mode="after")
    def _one(self) -> HoldoutUnlockIn:
        given = [v is not None for v in (self.backtest, self.strategy, self.rotation)]
        if sum(given) != 1:
            raise ValueError("give exactly one of backtest, strategy or rotation")
        return self


# ---------------------------------------------------------------------------
# Replay chart context (A4.6)
# ---------------------------------------------------------------------------


class ReplayEventsOut(BaseModel):
    """A4.6: the replay chart's markers, cut at the session clock: news whose
    ``available_at`` is at or before ``current_at`` and the session's fills."""

    session_id: int
    ticker: str
    current_at: datetime
    news_rule: str
    events: list[Annotated[NewsEventOut | FillEventOut, Field(discriminator="type")]]


class ReplayDrawingIn(BaseModel):
    """A4.6: a session drawing (A3.2's shape, no ticker: the session's)."""

    kind: DrawingKind
    points: list[DrawingPoint] = Field(min_length=1, max_length=3)
    style: DrawingStyle = Field(default_factory=DrawingStyle)
    label: str | None = Field(default=None, max_length=80)
    locked: bool = False


# ---------------------------------------------------------------------------
# Drills and decks (A4.7, M9.3)
# ---------------------------------------------------------------------------


class DrillDeckIn(BaseModel):
    """POST /v1/drills/decks: K drills from a rule's real false-to-true
    triggers. ``rule`` is a setup version or inline text (saved as a version
    of your "Rules from drills" setup)."""

    name: str | None = Field(default=None, max_length=120)
    rule: StrategyRuleIn
    universe: ScanUniverseIn
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    k: int = Field(default=10, ge=1, le=25)
    """Drills in the deck (sampled at random from the eligible triggers)."""
    lead_bars: int = Field(default=60, ge=5, le=250)
    """N: bars of lead-in shown before the trigger bar."""
    follow_bars: int = Field(default=40, ge=5, le=250)
    """M: the session ends this many bars after the trigger (clamped to data)."""
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    anonymised: bool = True

    model_config = ConfigDict(populate_by_name=True)


class DrillRuleOut(BaseModel):
    text: str
    canonical: str
    hash: str
    setup_version_id: int


class DrillCheckOut(BaseModel):
    key: Literal["entry", "stop", "size"]
    label: str
    status: Literal["passed", "failed", "not_applicable"]
    detail: str


class DrillScoreOut(BaseModel):
    """Process, not profit: did the trade follow the plan."""

    checks: list[DrillCheckOut]
    passed: int
    applicable: int
    followed_plan: bool | None
    """True when every applicable check passed; null with no trade."""
    traded: bool
    r_achieved: float | None
    """Total P&L over the planned risk. Shown beside the score; it is not the score."""
    r_note: str
    total_pnl: Decimal
    rules: dict[str, str]


class DrillPlanIn(BaseModel):
    planned_entry: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    planned_stop: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    planned_size: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _long(self) -> DrillPlanIn:
        if self.planned_stop >= self.planned_entry:
            raise ValueError("a long plan's stop must be below its entry")
        return self


class DrillPlanOut(BaseModel):
    side: Literal["long"] = "long"
    planned_entry: Decimal
    planned_stop: Decimal
    planned_size: Decimal
    planned_risk: Decimal
    """(entry - stop) x size, in the session's currency."""
    note: str | None
    locked: bool
    locked_at: datetime | None


class DrillRevealHorizonOut(BaseModel):
    bars: int
    date: date | None
    close: Decimal | None
    return_pct: float | None
    """From the trigger bar's close; null when the data ends first."""


class DrillRevealOut(BaseModel):
    ticker: str
    name: str | None
    sector: str | None
    currency: str
    trigger_date: date
    session_start: date
    session_end: date
    shown_trigger_date: date
    date_offset_weeks: int
    after: list[DrillRevealHorizonOut]
    next_bars: list[ReplayBarOut]
    """Stored daily bars after the session's last one (up to 60)."""


class DrillRowOut(BaseModel):
    id: int
    position: int
    label: str
    status: Literal["not_started", "in_progress", "revealed"]
    ticker: str | None
    """Null while the drill is anonymised and not revealed."""
    trigger_date: date | None
    score: DrillScoreOut | None


class DrillDeckSummaryOut(BaseModel):
    drills: int
    not_started: int
    in_progress: int
    revealed: int
    traded: int
    followed_plan: int
    checks_passed: int
    checks_applicable: int


class DrillDeckOut(BaseModel):
    id: int
    name: str
    rule: DrillRuleOut
    universe: dict[str, Any]
    from_: date = Field(alias="from")
    to: date
    k: int
    lead_bars: int
    follow_bars: int
    seed: int
    anonymised: bool
    triggers_found: int
    triggers_eligible: int
    lag_skipped: int
    created_at: datetime
    drills: list[DrillRowOut]
    summary: DrillDeckSummaryOut
    method: dict[str, str]

    model_config = ConfigDict(populate_by_name=True)


class DrillOut(BaseModel):
    """One drill. While ``anonymised`` the symbol is ``label`` everywhere and
    every date is shifted by whole weeks; nothing names the real ticker,
    company or dates (``reveal`` is null)."""

    id: int
    deck_id: int
    deck_name: str
    position: int
    label: str
    status: Literal["not_started", "in_progress", "revealed"]
    anonymised: bool
    date_note: str | None
    news_note: str
    trigger_at: datetime
    session: ReplaySessionOut
    summary: ReplaySummaryOut
    bar: ReplayBarOut
    history: list[ReplayBarOut]
    orders: list[ReplayOrderOut]
    fills: list[ReplayFillOut]
    plan: DrillPlanOut | None
    needs_plan: bool
    score: DrillScoreOut | None
    reveal: DrillRevealOut | None


# --- A5.3: broker tradebook imports -----------------------------------------------


class ImportColumnOut(BaseModel):
    """Which header a canonical field was read from (``header`` null: absent)."""

    field: str
    label: str
    required: bool
    header: str | None


class ImportTradeOut(BaseModel):
    """A parsed trade: only the parsed fields, never the raw row."""

    row: int
    ticker: str
    symbol: str
    exchange: str
    isin: str | None = None
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    executed_at: datetime
    time_known: bool = True
    # Restated for later splits (the as-traded numbers stay on the fill).
    restated_quantity: Decimal
    restated_price: Decimal
    product: Literal["delivery", "intraday", "mixed"] | None = None
    fees: Decimal
    fees_estimated: bool = True
    status: Literal["posted", "needs_opening_lot"]
    basis_uncertain: bool = False
    intraday_short: bool = False
    """An intraday short sale, or a buy covering one the same day."""


class ImportProblemOut(BaseModel):
    """One row the import leaves out or flags. Row numbers count the header as
    row 1. ``reason`` is fixed text: no cell value is ever echoed."""

    row: int
    kind: Literal[
        "rejected",
        "segment",
        "unmatched",
        "duplicate_in_file",
        "already_imported",
        "needs_opening_lot",
        "basis_uncertain",
        "not_executed",
    ]
    reason: str
    field: str | None = None
    # Parsed fields only, where they help (the symbol of an unmatched row).
    symbol: str | None = None
    exchange: str | None = None


class ImportCountsOut(BaseModel):
    rows: int = 0
    new: int = 0
    posted: int = 0
    needs_opening_lot: int = 0
    duplicate: int = 0
    unmatched: int = 0
    skipped_segment: int = 0
    rejected: int = 0
    not_executed: int = 0
    """Orders in the file that did not execute (an order-status column, A6.11)."""
    basis_uncertain: int = 0
    intraday_inferred: int = 0
    intraday_short: int = 0
    """Sells posted as intraday shorts (covered by buys the same day)."""


class ImportPreviewOut(BaseModel):
    """``POST /v1/books/{id}/imports/preview``: nothing is stored."""

    format: str
    """The column map the file was read with (``dhan_tradebook_v1``, ``custom_3``)."""
    format_label: str = ""
    format_status: Literal["unconfirmed", "confirmed", "custom"]
    format_note: str
    format_source: str = ""
    broker: str = "zerodha"
    detected: Literal["header", "chosen", "saved", "fallback"] = "header"
    """header: the header row fits this map; chosen: the caller named it; saved:
    the caller's own map; fallback: no map fits (``missing_required`` names
    the closest map's missing columns)."""
    alternatives: list[str] = []
    """Other built-in maps the header row also fits."""
    market: Literal["in", "us"] = "in"
    headers: list[str] = []
    """The file's header row (names only, never a cell), for "Map columns yourself"."""
    file_sha256: str
    can_commit: bool
    message: str | None = None
    date_order: str
    columns: list[ImportColumnOut]
    unmatched_headers: list[str]
    missing_required: list[str]
    counts: ImportCountsOut
    sample: list[ImportTradeOut]
    problems: list[ImportProblemOut]
    problems_total: int
    fees_note: str


class ImportBatchOut(BaseModel):
    id: int
    created_at: datetime
    column_map: str
    format_status: Literal["unconfirmed", "confirmed", "custom"]
    broker: str = "zerodha"
    rows_total: int
    rows_added: int
    rows_duplicate: int
    rows_unmatched: int
    rows_skipped_segment: int
    rows_rejected: int
    # Of this batch's fills now in the book.
    fills: int
    posted: int
    needs_opening_lot: int
    first_trade_at: datetime | None = None
    last_trade_at: datetime | None = None


class ImportCommitOut(BaseModel):
    """``POST .../imports/commit``. ``batch`` is null when nothing was new."""

    batch: ImportBatchOut | None
    added: int
    counts: ImportCountsOut


class OpeningLotIn(BaseModel):
    """An opening lot: shares held before the file's window."""

    ticker: str = Field(min_length=1, max_length=16)
    on: date
    quantity: Decimal = Field(gt=0, le=Decimal("1e10"))
    avg_price: Decimal = Field(gt=0, le=Decimal("1e9"))


class OpeningLotOut(BaseModel):
    id: int
    ticker: str
    on: date
    quantity: Decimal
    avg_price: Decimal
    created_at: datetime


class NeedsOpeningLotOut(BaseModel):
    """Sells that wait for an opening lot, per symbol."""

    ticker: str
    fills: int
    first_sell_at: datetime
    # Shares the earliest waiting sell is short by, restated for splits.
    short_by: Decimal


class ImportMapColumnOut(BaseModel):
    field: str
    label: str
    required: bool


class ImportMapOut(BaseModel):
    """A built-in tradebook column map (A6.11). Every broker map is unconfirmed."""

    name: str
    broker: str
    label: str
    status: Literal["unconfirmed", "confirmed", "custom"]
    market: Literal["in", "us"] | None
    note: str
    source: str
    """What the map is built from, with the date it was read."""
    how_to: str
    columns: list[ImportMapColumnOut]


ImportMapField = Literal[
    "trade_date",
    "executed_at",
    "symbol",
    "exchange",
    "side",
    "quantity",
    "price",
    "trade_id",
    "order_id",
    "isin",
]


class SavedImportMapIn(BaseModel):
    """``POST /v1/import-maps``: "Map columns yourself". Header names only."""

    name: str = Field(min_length=1, max_length=60)
    mapping: dict[ImportMapField, str]
    default_exchange: Literal["NSE", "BSE"] | None = None
    date_order: Literal["auto", "day_first", "month_first"] = "auto"


class SavedImportMapOut(BaseModel):
    id: int
    name: str
    mapping: dict[str, str]
    default_exchange: Literal["NSE", "BSE"] | None = None
    date_order: Literal["auto", "day_first", "month_first"] = "auto"
    created_at: datetime
    updated_at: datetime


class ImportsOut(BaseModel):
    """``GET /v1/books/{id}/imports``."""

    book_id: int
    broker: str | None
    market: Literal["in", "us"] = "in"
    currency: str = "INR"
    format: str
    """The book's broker's map (Zerodha for an ``other`` book)."""
    format_status: Literal["unconfirmed", "confirmed", "custom"]
    format_note: str
    max_bytes: int
    maps: list[ImportMapOut] = []
    saved_maps: list[SavedImportMapOut] = []
    custom_fields: list[ImportMapColumnOut] = []
    batches: list[ImportBatchOut]
    opening_lots: list[OpeningLotOut]
    needs_opening_lot: list[NeedsOpeningLotOut]
    basis_uncertain: int
    fills: int
    posted: int


# --- A5.5: journal entries (round trips) ------------------------------------------


class JournalExcursionOut(BaseModel):
    """One excursion: the worst (MAE) or best (MFE) bar while shares were held."""

    per_share: Decimal
    """Daily low (MAE) or high (MFE) minus the ledger's average cost; for a short
    entry, the average short price minus the daily high (MAE) or low (MFE)."""
    pct: Decimal
    """Per share as a percent of the average cost."""
    amount: Decimal
    """Per share x the shares held that day."""
    shares: Decimal
    date: date
    price: Decimal
    """The low or high itself (where the chart marks it)."""
    r: float | None = None
    """Amount over the initial risk; null without a plan stop."""


class JournalExcursionsOut(BaseModel):
    basis: Literal["exact_close", "approximate_daily", "exact_minutes"]
    note: str
    mae: JournalExcursionOut | None = None
    mfe: JournalExcursionOut | None = None
    reason: str | None = None
    """Why MAE and MFE are null (a missing bar, no bars)."""
    missing_sessions: list[date] = []
    sessions: int = 0


class JournalEntryPlanOut(BaseModel):
    id: int
    status: str
    label: Literal["locked", "written_after_entry"]
    locked_at: datetime | None = None
    first_fill_at: datetime | None = None
    planned_entry: Decimal | None = None
    planned_stop: Decimal | None = None
    planned_target: Decimal | None = None
    planned_size: Decimal | None = None
    setup_version_id: int | None = None
    setup_label: str | None = None
    counts_for_adherence: bool
    """Only a plan locked before the entry counts in plan-adherence stats."""


class JournalEntryFillOut(BaseModel):
    trade_id: int | None = None
    replay_fill_id: int | None = None
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    fees: Decimal
    fees_estimated: bool
    at: datetime
    venue_date: date
    time_known: bool
    """False for an imported fill whose file gave a date only (dated at the IST day start)."""


class JournalNewsHeadlineOut(BaseModel):
    id: str
    title: str
    source: str | None = None
    url: str | None = None
    available_at: datetime
    date: date
    """The venue date of ``available_at``."""


class JournalNewsWindowOut(BaseModel):
    from_date: date
    to_date: date
    coverage: Literal["covered", "before_news_copy"]
    """``before_news_copy``: the window ends before the first Aegis document held."""
    note: str
    headlines: list[JournalNewsHeadlineOut] = []


class JournalEntrySummaryOut(BaseModel):
    id: int
    source: Literal["paper", "imported", "replay"]
    book_id: int | None = None
    replay_session_id: int | None = None
    ticker: str | None = None
    currency: str
    venue: str
    side: Literal["long", "short"]
    """``short``: an imported intraday short (sells opened it, buys closed it)."""
    status: Literal["open", "closed"]
    opened_at: datetime
    closed_at: datetime | None = None
    entry_date: date
    exit_date: date | None = None
    as_of_date: date | None = None
    """The last close an open entry is marked at."""
    mark_close: Decimal | None = None
    avg_entry: Decimal
    avg_exit: Decimal | None = None
    quantity: Decimal
    """Most shares held."""
    held: Decimal
    """Shares still held (open entries)."""
    net_pnl: Decimal
    """Realized minus every fee, plus the open shares marked at the last close."""
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None = None
    fees: Decimal
    fees_estimated: bool
    return_pct: Decimal | None = None
    holding_days: int
    holding_sessions: int
    fills_count: int
    r_multiple: float | None = None
    r_reason: str | None = None
    initial_risk: Decimal | None = None
    excursions: JournalExcursionsOut
    plan: JournalEntryPlanOut | None = None
    setup_tags: list[str] = []
    mistake_tags: list[str] = []
    has_notes: bool = False


class TradeReplayBarOut(BaseModel):
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class TradeReplayFillOut(BaseModel):
    at: datetime
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    time_known: bool


class TradeReplayHesitationOut(BaseModel):
    """A6.10: from the plan's entry level being touched to the fill, and
    whether a stop the price went through was honoured (closed on that bar)."""

    entry_touched_at: datetime | None = None
    fill_at: datetime
    wait_bars: int | None = None
    stop_breached_at: datetime | None = None
    stop_honoured: bool | None = None
    exit_at: datetime | None = None
    exit_price: Decimal | None = None
    note: str


class TradeReplayOut(BaseModel):
    """A6.10 (M9.5): a read-only playback of a paper or imported entry. No orders."""

    entry_id: int
    ticker: str | None
    currency: str
    side: Literal["long", "short"]
    status: Literal["open", "closed"]
    interval: Literal["1m", "1d"]
    bars_note: str
    bars: list[TradeReplayBarOut]
    fills: list[TradeReplayFillOut]
    planned_entry: Decimal | None = None
    planned_stop: Decimal | None = None
    planned_target: Decimal | None = None
    excursions: JournalExcursionsOut
    hesitation: TradeReplayHesitationOut | None = None


class JournalEntryOut(JournalEntrySummaryOut):
    fills: list[JournalEntryFillOut]
    adherence: DrillScoreOut | None = None
    """The drill's process score against a plan locked before entry."""
    adherence_note: str | None = None
    news_at_entry: JournalNewsWindowOut | None = None
    news_at_exit: JournalNewsWindowOut | None = None
    review_notes: str | None = None
    mistakes: str | None = None
    lessons: str | None = None
    updated_at: datetime


class JournalEntriesOut(BaseModel):
    entries: list[JournalEntrySummaryOut]
    total: int
    limit: int
    offset: int
    note: str


class JournalEntryPatch(BaseModel):
    """The user's text. Null leaves a field; ``""`` clears it."""

    model_config = ConfigDict(extra="forbid")

    review_notes: str | None = Field(default=None, max_length=4000)
    mistakes: str | None = Field(default=None, max_length=4000)
    lessons: str | None = Field(default=None, max_length=4000)
    setup_tags: list[str] | None = Field(default=None, max_length=12)
    mistake_tags: list[str] | None = Field(default=None, max_length=12)


# --- A5.6: "Is my edge real?" (services/journal/edge.py) ---------------------------------


class EdgeIntervalOut(BaseModel):
    """A seeded bootstrap interval of the mean (``level`` 0.9: 5th to 95th percentile)."""

    low: float
    high: float
    level: float


class EdgeGroupOut(BaseModel):
    """One group's figures over its closed journal entries.

    ``counts_only`` under ``min_closed`` (A2.4's 30): only ``n``, ``wins``,
    ``losses`` and ``breakeven``, with ``counts_only_reason``; every other
    figure is null. Money figures are null when the group mixes currencies
    (``money_note``); R figures need 30 entries with R (``r_note``)."""

    key: str
    label: str
    kind: Literal["overall", "setup", "setup_tag", "mistake_tag", "source"]
    setup_version_id: int | None = None
    n: int
    wins: int
    losses: int
    breakeven: int
    counts_only: bool
    counts_only_reason: str | None = None
    includes_imported: bool = False
    currencies: list[str] = []
    currency: str | None = None
    win_rate: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None
    payoff: float | None = None
    profit_factor: float | None = None
    expectancy: float | None = None
    """Mean net P&L per trade, fees included (estimated for imports)."""
    expectancy_interval: EdgeIntervalOut | None = None
    n_r: int = 0
    expectancy_r: float | None = None
    expectancy_r_interval: EdgeIntervalOut | None = None
    r_note: str | None = None
    adherence_rate: float | None = None
    """Share of scored plans (locked before entry) that were followed."""
    adherence_n: int = 0
    avg_holding_days: float | None = None
    total_net_pnl: float | None = None
    money_note: str | None = None


class EdgeBacktestOut(BaseModel):
    """The newest saved A4.1 strategy run whose entry is the setup version."""

    run_id: int
    created_at: datetime
    ticker: str
    closed_trades: int
    n_r: int
    expectancy_r: float | None = None
    win_rate: float | None = None
    avg_holding_days: float | None = None
    report_expectancy_r: float | None = None
    holdout: str
    sample: Literal["in_sample", "holdout_seen"]
    sample_note: str
    unlocked_at: datetime | None = None


EdgeDriftStatus = Literal[
    "consistent",
    "outside_interval",
    "too_few_live_trades",
    "too_few_backtest_trades",
    "no_backtest",
    "backtest_no_r",
]


class EdgeDriftOut(BaseModel):
    """Live (journal) against backtest, per trade, for one setup version."""

    setup_version_id: int
    label: str
    status: EdgeDriftStatus
    text: str
    live_n: int
    live_n_r: int
    live_expectancy_r: float | None = None
    live_interval: EdgeIntervalOut | None = None
    live_win_rate: float | None = None
    live_avg_holding_days: float | None = None
    backtest: EdgeBacktestOut | None = None
    diff_expectancy_r: float | None = None
    """Live minus backtest; only when the two can be compared."""
    diff_win_rate: float | None = None
    diff_avg_holding_days: float | None = None


class EdgeStatsOut(BaseModel):
    book_id: int | None = None
    source: Literal["paper", "imported", "replay", "all"] | None = None
    sources_included: list[str]
    setup_version_id: int | None = None
    tag: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    min_closed: int
    seed: int
    resamples: int
    mean_block: int
    interval_level: float
    method: str
    open_excluded: int
    """Open entries under these filters: counted here, never in the figures."""
    overall: EdgeGroupOut
    by_setup: list[EdgeGroupOut]
    by_setup_tag: list[EdgeGroupOut]
    by_mistake_tag: list[EdgeGroupOut]
    by_source: list[EdgeGroupOut]
    drift: list[EdgeDriftOut]
    imported_fees_estimated: bool
    honesty: list[str]


# ---------------------------------------------------------------------------
# Chart templates and layouts (A6.8, M2.10)
# ---------------------------------------------------------------------------

ChartTypeKey = Literal["candles", "hollow", "bars", "line", "area", "heikin-ashi"]
ChartScaleKey = Literal["linear", "log", "percent"]
ChartIntervalKey = Literal["1d", "1wk", "1mo", "1m", "5m", "15m", "30m", "60m"]
ChartGridKey = Literal["1", "2v", "2h", "4"]
LinkColourKey = Literal["aqua", "blue", "violet", "pink", "amber", "lime", "slate"]


class ChartTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    chart_type: ChartTypeKey = "candles"
    scale: ChartScaleKey = "linear"
    indicators: list[str] = Field(default_factory=list, max_length=16)
    """Indicator registry keys with their parameters (``sma_50``, ``bb_20_2``)."""
    pane_heights: dict[str, int] = Field(default_factory=dict)
    """Pixels by pane kind (``price``, ``volume``, ``rsi``...), 48 to 1200."""


class ChartTemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    chart_type: ChartTypeKey | None = None
    scale: ChartScaleKey | None = None
    indicators: list[str] | None = Field(default=None, max_length=16)
    pane_heights: dict[str, int] | None = None


class ChartTemplateOut(BaseModel):
    id: int
    name: str
    chart_type: ChartTypeKey
    scale: ChartScaleKey
    indicators: list[str]
    pane_heights: dict[str, int]
    created_at: datetime
    updated_at: datetime


class ChartPaneIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    interval: ChartIntervalKey = "1d"
    template_id: int | None = None
    link: LinkColourKey | None = None
    """The link colour; null is unlinked."""


class ChartPaneOut(BaseModel):
    symbol: str
    interval: ChartIntervalKey
    template_id: int | None
    """Null when the pane has the default look or its template was deleted."""
    link: LinkColourKey | None


class ChartLayoutIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    grid: ChartGridKey = "1"
    panes: list[ChartPaneIn] = Field(min_length=1, max_length=4)
    """One per grid cell in reading order: 1, 2 (``2v``, ``2h``) or 4."""


class ChartLayoutPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    grid: ChartGridKey | None = None
    panes: list[ChartPaneIn] | None = Field(default=None, min_length=1, max_length=4)


class ChartLayoutOut(BaseModel):
    id: int
    name: str
    grid: ChartGridKey
    panes: list[ChartPaneOut]
    created_at: datetime
    updated_at: datetime


class BreadthPointOut(BaseModel):
    """A7.1 (M3.3): one session's breadth over the market's stored members."""

    date: date
    advancers: int
    decliners: int
    unchanged: int
    members: int
    new_highs: int
    new_lows: int
    highs_minus_lows: int
    ad_line: int
    ad_ratio_20: float | None = None
    ad_ratio_40: float | None = None
    mcclellan: float | None = None
    summation: float | None = None
    thrust_ema10: float | None = None
    thrust: bool = False
    pct_above_20: float | None = None
    pct_above_50: float | None = None
    pct_above_100: float | None = None
    pct_above_200: float | None = None
    pct_rsi_50: float | None = None


class BreadthOut(BaseModel):
    market: Literal["US", "IN"]
    start: date
    end: date
    members: int
    universe_note: str
    method: dict[str, str]
    points: list[BreadthPointOut]


class RotationPointOut(BaseModel):
    """A7.2 (M3.2): one week of a sector's trail."""

    week: date
    rs_trend: float
    rs_momentum: float
    quadrant: Literal["leading", "weakening", "lagging", "improving"]


class RotationSectorOut(BaseModel):
    sector: str
    members: int
    points: list[RotationPointOut]


class RotationOut(BaseModel):
    market: Literal["US", "IN"]
    benchmark: str
    benchmark_name: str
    as_of: date | None = None
    note: str
    method: dict[str, str]
    sectors: list[RotationSectorOut]


class ForensicTestOut(BaseModel):
    key: str
    label: str
    result: Literal["pass", "fail", "unknown"]
    detail: str


class ForensicScoreOut(BaseModel):
    value: float | None = None
    zone: str | None = None
    missing: list[str] = []
    parts: dict[str, float] = {}


class ForensicsOut(BaseModel):
    """A7.3 (M5.1, M5.2): the forensic scorecard on annual facts as known on ``as_of``."""

    ticker: str
    as_of: date
    sector: str | None = None
    financial: bool
    financial_note: str | None = None
    fiscal_year_end: date | None = None
    previous_year_end: date | None = None
    currency: str | None = None
    piotroski_score: int | None = None
    piotroski_known: int | None = None
    piotroski: list[ForensicTestOut] = []
    altman_z: ForensicScoreOut | None = None
    beneish_m: ForensicScoreOut | None = None
    cfo_to_pat: ForensicScoreOut | None = None
    reason: str | None = None
    method: dict[str, str]


class ReverseDcfRowOut(BaseModel):
    wacc: float
    terminal_growth: float
    implied_growth: float | None = None


class ReverseDcfStepOut(BaseModel):
    step: str
    value: float | None = None


class ReverseDcfOut(BaseModel):
    """A7.4 (M5.3): the free-cash-flow growth today's enterprise value implies."""

    ticker: str
    as_of: date
    currency: str | None = None
    implied_growth: float | None = None
    reason: str | None = None
    base_fcf: float | None = None
    base_fcf_source: str
    wacc: float
    terminal_growth: float
    years: int
    enterprise_value: float | None = None
    sensitivity: list[ReverseDcfRowOut]
    reconciliation: list[ReverseDcfStepOut]
    method: str


class BehaviourCellOut(BaseModel):
    key: str
    entries: int
    net_pnl: float
    win_rate: float | None = None


class BehaviourOut(BaseModel):
    """A7.6 (M10.4): behaviour diagnostics over closed journal entries."""

    entries: int
    counts_only: bool
    reason: str | None = None
    discipline_scored: int
    discipline_followed: int
    discipline_rate: float | None = None
    winners: int
    losers: int
    avg_hold_winners: float | None = None
    avg_hold_losers: float | None = None
    disposition_index: float | None = None
    tilt_entries: list[int]
    tilt_rate: float | None = None
    by_weekday: list[BehaviourCellOut]
    by_hour: list[BehaviourCellOut]
    fees_total: float
    fees_per_entry: float | None = None
    fees_share_of_gross: float | None = None
    fees_estimated: bool
    currencies: list[str]
    method: dict[str, str]
