"""Deterministic post-trade forensics for a ReplaySession (SIM-07).

Computed from stored ``ReplayFill`` rows and replay-visible 1d bars only.
Never inspects bars after the analysis horizon:

* active / cancelled → ``current_at``
* completed → ``end_at`` (frozen; equals ``current_at`` at completion)
* a closed episode never uses bars after its exit fill

MAE / MFE use stored daily high/low as *retrospective range* after the bar
is observable. That is not an execution timestamp. Live/replay fills still
use ``legacy_close`` at the stored close and do not touch same-day OHLC.

Definitions (long-only, one ticker):

* **Episode** — opening exposure through adds/reductions until quantity
  returns to zero. Partial sells do not split an episode.
* **Weighted entry** — running buy-notional / buy-quantity (same as ledger).
* **MAE_pct** — worst ``(bar.low - active_weighted_entry) / active_weighted_entry``
  while quantity is still open after that bar's fills. Reported as a percent.
* **MFE_pct** — analogous using ``bar.high``.
* **Holding bars** — count of stored 1d bars in ``[opened_at, closed_or_as_of]``.
  Not labelled "trading days"; CSV data may include calendar days.
* **Holding calendar days** — ``(end_date - open_date).days``.
* **Episode return** — realized (plus unrealized if still open) / total buy
  notional of the episode.
* **Episode benchmark** — ``(exit_or_as_of close - entry-bar close) / entry-bar
  close``. Same-symbol buy-and-hold over the episode's observable bars.
  Percentage only; no assumed full-capital dollar P&L.
* **Session benchmark** — start-bar close → analysis-bar close, versus replay
  equity return on starting cash.
* **Concentration** — ``position_notional / replay_equity`` at each fill.
  One-ticker replay concentration, not portfolio diversification.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from sqlmodel import Session

from stockviz.models import ReplaySession, ReplaySessionStatus
from stockviz.services.replay.ledger import MICROS
from stockviz.services.replay.market import get_visible_replay_history
from stockviz.services.replay.session import list_replay_fills
from stockviz.services.replay.summary import compute_replay_summary

ZERO = Decimal("0")
HUNDRED = Decimal("100")
PCT = Decimal("0.0001")


class _FillLike(Protocol):
    id: int | None
    ticker: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    realized_pnl: Decimal | None
    evaluated_at: datetime
    profile_name: str
    model_version: str
    reference_price: Decimal | None
    reason: str
    assumptions: list[str]
    market_interval: str
    order_type: str
    created_at: datetime
    session_id: int


class _BarLike(Protocol):
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True, slots=True)
class FillSnapshot:
    """Immutable fill facts used by episode reconstruction."""

    id: int
    session_id: int
    ticker: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    realized_pnl: Decimal | None
    evaluated_at: datetime
    created_at: datetime
    profile_name: str
    model_version: str
    reference_price: Decimal | None
    reason: str
    assumptions: tuple[str, ...]
    market_interval: str
    order_type: str
    equity_after: Decimal | None
    concentration_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class ReplayEpisode:
    index: int
    ticker: str
    opened_at: datetime
    closed_at: datetime | None
    status: str
    entry_price: Decimal
    exit_price: Decimal | None
    entry_quantity: Decimal
    peak_quantity: Decimal
    weighted_entry_price: Decimal
    weighted_exit_price: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    return_pct: Decimal | None
    holding_bars: int
    holding_calendar_days: int
    mae_amount: Decimal | None
    mae_pct: Decimal | None
    mfe_amount: Decimal | None
    mfe_pct: Decimal | None
    benchmark_return_pct: Decimal | None
    excess_return_pct: Decimal | None
    max_position_pct: Decimal | None
    entry_equity: Decimal | None
    peak_exposure: Decimal
    fills: tuple[FillSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ReplayForensics:
    ticker: str
    status: str
    analysis_scope: Literal["so_far", "final", "cancelled"]
    analysis_at: datetime
    starting_cash: Decimal
    equity: Decimal
    replay_return_pct: Decimal
    buy_hold_return_pct: Decimal | None
    excess_return_pct: Decimal | None
    max_drawdown_pct: Decimal | None
    max_concentration_pct: Decimal | None
    fills_count: int
    episodes_count: int
    closed_episodes_count: int
    open_episodes_count: int
    episodes: tuple[ReplayEpisode, ...]


def _q_pct(value: Decimal) -> Decimal:
    return value.quantize(PCT)


def _q_money(value: Decimal) -> Decimal:
    return value.quantize(MICROS)


def _pct_change(start: Decimal, end: Decimal) -> Decimal | None:
    if start <= 0:
        return None
    return _q_pct((end - start) / start * HUNDRED)


def _as_fill(fill: FillSnapshot | _FillLike) -> FillSnapshot:
    if isinstance(fill, FillSnapshot):
        return fill
    assumptions = fill.assumptions if isinstance(fill.assumptions, list) else list(fill.assumptions)
    return FillSnapshot(
        id=int(fill.id or 0),
        session_id=fill.session_id,
        ticker=fill.ticker,
        side=fill.side.lower(),
        quantity=fill.quantity,
        fill_price=fill.fill_price,
        realized_pnl=fill.realized_pnl,
        evaluated_at=fill.evaluated_at,
        created_at=fill.created_at,
        profile_name=fill.profile_name,
        model_version=fill.model_version,
        reference_price=fill.reference_price,
        reason=fill.reason,
        assumptions=tuple(assumptions),
        market_interval=fill.market_interval,
        order_type=fill.order_type,
        equity_after=None,
        concentration_pct=None,
    )


def sort_fills(fills: Sequence[FillSnapshot]) -> list[FillSnapshot]:
    """Deterministic chronology: ``evaluated_at`` then stable fill id."""

    snapshots = list(fills)
    snapshots.sort(key=lambda row: (row.evaluated_at, row.id))
    return snapshots


def annotate_fill_economics(
    fills: Sequence[FillSnapshot], *, starting_cash: Decimal
) -> list[FillSnapshot]:
    """Walk fills once, attaching post-fill equity and concentration."""

    cash = starting_cash
    qty = ZERO
    out: list[FillSnapshot] = []
    for fill in fills:
        notional = _q_money(fill.quantity * fill.fill_price)
        if fill.side == "buy":
            cash = _q_money(cash - notional)
            qty = qty + fill.quantity
        else:
            cash = _q_money(cash + notional)
            qty = qty - fill.quantity
        position_notional = _q_money(qty * fill.fill_price)
        equity = _q_money(cash + position_notional)
        concentration: Decimal | None = None
        if equity > 0 and qty > 0:
            concentration = _q_pct(position_notional / equity * HUNDRED)
        elif equity > 0:
            concentration = ZERO
        out.append(
            FillSnapshot(
                id=fill.id,
                session_id=fill.session_id,
                ticker=fill.ticker,
                side=fill.side,
                quantity=fill.quantity,
                fill_price=fill.fill_price,
                realized_pnl=fill.realized_pnl,
                evaluated_at=fill.evaluated_at,
                created_at=fill.created_at,
                profile_name=fill.profile_name,
                model_version=fill.model_version,
                reference_price=fill.reference_price,
                reason=fill.reason,
                assumptions=fill.assumptions,
                market_interval=fill.market_interval,
                order_type=fill.order_type,
                equity_after=equity,
                concentration_pct=concentration,
            )
        )
    return out


@dataclass
class _OpenEpisode:
    ticker: str
    opened_at: datetime
    fills: list[FillSnapshot]
    qty: Decimal = ZERO
    peak_qty: Decimal = ZERO
    buy_qty: Decimal = ZERO
    buy_notional: Decimal = ZERO
    sell_qty: Decimal = ZERO
    sell_notional: Decimal = ZERO
    realized: Decimal = ZERO
    peak_exposure: Decimal = ZERO
    entry_equity: Decimal | None = None


def reconstruct_episodes(fills: Sequence[FillSnapshot]) -> list[_OpenEpisode]:
    """Group fills into long-only episodes. Does not mutate ledger state."""

    episodes: list[_OpenEpisode] = []
    current: _OpenEpisode | None = None
    for fill in fills:
        if current is None:
            if fill.side != "buy":
                continue
            current = _OpenEpisode(ticker=fill.ticker, opened_at=fill.evaluated_at, fills=[])
        current.fills.append(fill)
        if fill.side == "buy":
            current.qty += fill.quantity
            current.buy_qty += fill.quantity
            current.buy_notional += _q_money(fill.quantity * fill.fill_price)
            if current.qty > current.peak_qty:
                current.peak_qty = current.qty
            exposure = _q_money(current.qty * fill.fill_price)
            if exposure > current.peak_exposure:
                current.peak_exposure = exposure
            if current.entry_equity is None:
                current.entry_equity = fill.equity_after
        else:
            current.qty -= fill.quantity
            current.sell_qty += fill.quantity
            current.sell_notional += _q_money(fill.quantity * fill.fill_price)
            if fill.realized_pnl is not None:
                current.realized += fill.realized_pnl
            if current.qty <= 0:
                current.qty = ZERO
                episodes.append(current)
                current = None
    if current is not None:
        episodes.append(current)
    return episodes


def _bars_in(bars: Sequence[_BarLike], start: datetime, end: datetime) -> list[_BarLike]:
    return [bar for bar in bars if start <= bar.ts <= end]


def _calendar_days(start: datetime, end: datetime) -> int:
    return max(0, (end.date() - start.date()).days)


def _close_at(bars: Sequence[_BarLike], ts: datetime) -> Decimal | None:
    for bar in bars:
        if bar.ts == ts:
            return bar.close
    return None


def _mae_mfe(
    *,
    episode_fills: Sequence[FillSnapshot],
    bars: Sequence[_BarLike],
    opened_at: datetime,
    holding_end: datetime,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    """Price-based MAE/MFE vs the active weighted entry after each bar's fills.

    Bars after a full exit on that timestamp are skipped (qty is already 0),
    so a dedicated exit bar does not contribute same-day high/low unless the
    episode also opened on that bar and remained open after its fills.
    """

    fills_by_ts: dict[datetime, list[FillSnapshot]] = {}
    for fill in episode_fills:
        fills_by_ts.setdefault(fill.evaluated_at, []).append(fill)

    qty = ZERO
    buy_qty = ZERO
    buy_notional = ZERO
    mae_amount: Decimal | None = None
    mae_pct: Decimal | None = None
    mfe_amount: Decimal | None = None
    mfe_pct: Decimal | None = None

    for bar in bars:
        if bar.ts < opened_at or bar.ts > holding_end:
            continue
        for fill in fills_by_ts.get(bar.ts, []):
            if fill.side == "buy":
                qty += fill.quantity
                buy_qty += fill.quantity
                buy_notional += _q_money(fill.quantity * fill.fill_price)
            else:
                qty -= fill.quantity
        if qty <= 0 or buy_qty <= 0:
            continue
        cost = buy_notional / buy_qty
        adverse = bar.low - cost
        favorable = bar.high - cost
        adverse_pct = adverse / cost * HUNDRED
        favorable_pct = favorable / cost * HUNDRED
        if mae_amount is None or adverse < mae_amount:
            mae_amount = _q_money(adverse)
            mae_pct = _q_pct(adverse_pct)
        if mfe_amount is None or favorable > mfe_amount:
            mfe_amount = _q_money(favorable)
            mfe_pct = _q_pct(favorable_pct)
    return mae_amount, mae_pct, mfe_amount, mfe_pct


def _equity_curve(
    *,
    fills: Sequence[FillSnapshot],
    bars: Sequence[_BarLike],
    starting_cash: Decimal,
) -> list[Decimal]:
    """Mark-to-market equity at each visible bar close using actual fill prices."""

    remaining = list(fills)
    cash = starting_cash
    qty = ZERO
    navs: list[Decimal] = []
    for bar in bars:
        while remaining and remaining[0].evaluated_at <= bar.ts:
            fill = remaining.pop(0)
            notional = _q_money(fill.quantity * fill.fill_price)
            if fill.side == "buy":
                cash = _q_money(cash - notional)
                qty += fill.quantity
            else:
                cash = _q_money(cash + notional)
                qty -= fill.quantity
        navs.append(_q_money(cash + qty * bar.close))
    return navs


def compute_max_drawdown_pct(navs: Sequence[Decimal]) -> Decimal | None:
    """Worst peak-to-trough decline as a negative percent. ``None`` if <2 points."""

    if len(navs) < 2:
        return None
    peak = navs[0]
    worst = ZERO
    for nav in navs[1:]:
        if nav > peak:
            peak = nav
            continue
        if peak <= 0:
            continue
        dd = (nav - peak) / peak
        if dd < worst:
            worst = dd
    return _q_pct(worst * HUNDRED)


def finish_episodes(
    raw: Sequence[_OpenEpisode],
    *,
    bars: Sequence[_BarLike],
    analysis_at: datetime,
    mark_close: Decimal,
) -> list[ReplayEpisode]:
    finished: list[ReplayEpisode] = []
    for index, episode in enumerate(raw, start=1):
        closed = episode.qty <= 0
        closed_at = episode.fills[-1].evaluated_at if closed else None
        holding_end = closed_at if closed_at is not None else analysis_at
        weighted_entry = episode.buy_notional / episode.buy_qty if episode.buy_qty > 0 else ZERO
        weighted_exit = episode.sell_notional / episode.sell_qty if episode.sell_qty > 0 else None
        holding = _bars_in(bars, episode.opened_at, holding_end)
        holding_bars = len(holding)
        remaining_qty = episode.qty
        unrealized: Decimal | None = None
        if not closed:
            unrealized = _q_money((mark_close - weighted_entry) * remaining_qty)
        total_result = episode.realized + (unrealized or ZERO)
        return_pct = (
            _q_pct(total_result / episode.buy_notional * HUNDRED)
            if episode.buy_notional > 0
            else None
        )
        mae_amount, mae_pct, mfe_amount, mfe_pct = _mae_mfe(
            episode_fills=episode.fills,
            bars=bars,
            opened_at=episode.opened_at,
            holding_end=holding_end,
        )
        entry_close = _close_at(bars, episode.opened_at) or episode.fills[0].fill_price
        exit_close = _close_at(bars, holding_end) or (
            episode.fills[-1].fill_price if closed else mark_close
        )
        benchmark = _pct_change(entry_close, exit_close)
        excess = None
        if return_pct is not None and benchmark is not None:
            excess = _q_pct(return_pct - benchmark)
        conc_values = [
            fill.concentration_pct for fill in episode.fills if fill.concentration_pct is not None
        ]
        max_position_pct = max(conc_values) if conc_values else None
        finished.append(
            ReplayEpisode(
                index=index,
                ticker=episode.ticker,
                opened_at=episode.opened_at,
                closed_at=closed_at,
                status="closed" if closed else "open",
                entry_price=_q_money(episode.fills[0].fill_price),
                exit_price=_q_money(episode.fills[-1].fill_price) if closed else None,
                entry_quantity=_q_money(episode.fills[0].quantity),
                peak_quantity=_q_money(episode.peak_qty),
                weighted_entry_price=_q_money(weighted_entry),
                weighted_exit_price=_q_money(weighted_exit) if weighted_exit is not None else None,
                realized_pnl=_q_money(episode.realized),
                unrealized_pnl=unrealized,
                return_pct=return_pct,
                holding_bars=holding_bars,
                holding_calendar_days=_calendar_days(episode.opened_at, holding_end),
                mae_amount=mae_amount,
                mae_pct=mae_pct,
                mfe_amount=mfe_amount,
                mfe_pct=mfe_pct,
                benchmark_return_pct=benchmark,
                excess_return_pct=excess,
                max_position_pct=max_position_pct,
                entry_equity=episode.entry_equity,
                peak_exposure=_q_money(episode.peak_exposure),
                fills=tuple(episode.fills),
            )
        )
    return finished


def analysis_scope_for(status: str) -> Literal["so_far", "final", "cancelled"]:
    if status == ReplaySessionStatus.COMPLETED.value:
        return "final"
    if status == ReplaySessionStatus.CANCELLED.value:
        return "cancelled"
    return "so_far"


def compute_replay_forensics_from_rows(
    *,
    ticker: str,
    status: str,
    start_at: datetime,
    analysis_at: datetime,
    starting_cash: Decimal,
    equity: Decimal,
    replay_return_pct: Decimal,
    fills: Sequence[FillSnapshot] | Sequence[_FillLike],
    bars: Sequence[_BarLike],
    mark_close: Decimal,
) -> ReplayForensics:
    """Pure forensics. ``bars`` must already be clipped to the analysis horizon."""

    annotated = annotate_fill_economics(
        sort_fills([_as_fill(fill) for fill in fills]), starting_cash=starting_cash
    )
    episodes = finish_episodes(
        reconstruct_episodes(annotated),
        bars=bars,
        analysis_at=analysis_at,
        mark_close=mark_close,
    )
    start_close = _close_at(bars, start_at)
    analysis_close = _close_at(bars, analysis_at) or mark_close
    buy_hold = _pct_change(start_close, analysis_close) if start_close is not None else None
    excess = None
    if buy_hold is not None:
        excess = _q_pct(replay_return_pct - buy_hold)
    conc_values = [
        fill.concentration_pct for fill in annotated if fill.concentration_pct is not None
    ]
    max_conc = max(conc_values) if conc_values else ZERO
    navs = _equity_curve(fills=annotated, bars=bars, starting_cash=starting_cash)
    return ReplayForensics(
        ticker=ticker,
        status=status,
        analysis_scope=analysis_scope_for(status),
        analysis_at=analysis_at,
        starting_cash=starting_cash,
        equity=equity,
        replay_return_pct=replay_return_pct,
        buy_hold_return_pct=buy_hold,
        excess_return_pct=excess,
        max_drawdown_pct=compute_max_drawdown_pct(navs),
        max_concentration_pct=max_conc,
        fills_count=len(annotated),
        episodes_count=len(episodes),
        closed_episodes_count=sum(1 for item in episodes if item.status == "closed"),
        open_episodes_count=sum(1 for item in episodes if item.status == "open"),
        episodes=tuple(episodes),
    )


def compute_replay_forensics(session: Session, replay: ReplaySession) -> ReplayForensics:
    """Load clipped session facts once, then reconstruct episodes in memory."""

    summary = compute_replay_summary(session, replay)
    bars = get_visible_replay_history(session, replay)
    fills = list_replay_fills(session, replay=replay)
    return compute_replay_forensics_from_rows(
        ticker=replay.ticker,
        status=replay.status,
        start_at=replay.start_at,
        analysis_at=replay.current_at,
        starting_cash=replay.starting_cash,
        equity=summary.equity,
        replay_return_pct=summary.return_pct,
        fills=fills,
        bars=bars,
        mark_close=summary.current_close,
    )
