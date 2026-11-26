"""Chart templates and layouts (A6.8, M2.10).

A **template** is a saved look for one chart: the chart type, the price
scale, the indicators (registry keys with their parameters, ``rsi_14``,
``bb_20_2``) and the pane heights by pane kind (``price``, ``volume``,
``rsi``...). The stock page saves its current chart as one; the chart
workspace applies one to a pane.

A **layout** is a saved chart workspace: a grid (``1``, ``2v`` side by side,
``2h`` stacked or ``4``) and its panes, one per grid cell, each with a
symbol, an interval (daily, weekly, monthly or intraday), a template id or
null (the default look) and a link colour or null (unlinked). Panes of one
colour always share a symbol: a pane in a colour follows the last symbol
chosen in it. The colours are the watchlist colour tags.

``panes`` is JSON: ``[{symbol, interval, template_id, link}]``. A template
id is not a foreign key, so deleting a template clears it from every layout
in the service (``services/chart_templates.delete_template``), and a read
drops one that no longer exists. Symbols are public tickers, checked when
the layout is saved; a symbol removed later reads as missing in the web.
Both tables are per user: another user's row is 404.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.watchlist import WATCHLIST_COLOURS

_JSON = JSON().with_variant(JSONB(), "postgresql")

MAX_TEMPLATES_PER_USER = 50
MAX_LAYOUTS_PER_USER = 50
MAX_TEMPLATE_INDICATORS = 16
MAX_PANE_KINDS = 16
MIN_PANE_HEIGHT = 48
"""The web's ``MIN_PANE_HEIGHT`` (``lib/chart-panes.ts``)."""
MAX_PANE_HEIGHT = 1200

CHART_TYPES = ("candles", "hollow", "bars", "line", "area", "heikin-ashi")
"""The web's ``CHART_TYPES`` (``lib/chart-view.ts``)."""
CHART_SCALES = ("linear", "log", "percent")
CHART_INTERVALS = ("1d", "1wk", "1mo", "1m", "5m", "15m", "30m", "60m")
"""The bars route's intervals (``routers/bars.py``)."""
CHART_GRIDS = ("1", "2v", "2h", "4")
GRID_PANES: dict[str, int] = {"1": 1, "2v": 2, "2h": 2, "4": 4}
LINK_COLOURS = WATCHLIST_COLOURS
"""Seven link colours, the watchlist tags (``--list-<name>`` in the web)."""


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ChartTemplate(SQLModel, table=True):
    __tablename__ = "chart_templates"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_chart_templates_user_name"),
        CheckConstraint(_in("chart_type", CHART_TYPES), name="ck_chart_templates_chart_type"),
        CheckConstraint(_in("scale", CHART_SCALES), name="ck_chart_templates_scale"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=64)
    chart_type: str = Field(max_length=16)
    scale: str = Field(max_length=16)
    indicators: list[str] = Field(default_factory=list, sa_column=Column(_JSON, nullable=False))
    """Indicator registry keys, each with its parameters (``sma_50``, ``macd``)."""
    pane_heights: dict[str, int] = Field(
        default_factory=dict, sa_column=Column(_JSON, nullable=False)
    )
    """Pixels by pane kind; a kind not listed keeps the chart's default."""
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class ChartLayout(SQLModel, table=True):
    __tablename__ = "chart_layouts"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_chart_layouts_user_name"),
        CheckConstraint(_in("grid", CHART_GRIDS), name="ck_chart_layouts_grid"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=64)
    grid: str = Field(max_length=4)
    panes: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(_JSON, nullable=False)
    )
    """One per grid cell, in reading order: ``{symbol, interval, template_id, link}``."""
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


__all__ = [
    "CHART_GRIDS",
    "CHART_INTERVALS",
    "CHART_SCALES",
    "CHART_TYPES",
    "GRID_PANES",
    "LINK_COLOURS",
    "MAX_LAYOUTS_PER_USER",
    "MAX_TEMPLATES_PER_USER",
    "ChartLayout",
    "ChartTemplate",
]
