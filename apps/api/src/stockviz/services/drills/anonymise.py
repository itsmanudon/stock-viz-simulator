"""Anonymised drill responses (A4.7, M9.3; design note question 5: on by default).

While a drill is anonymised and not revealed, every response about it goes
through ``Mask.apply``:

- **Symbol.** Any string equal to the ticker becomes the drill's label
  ("Stock A"); the ticker and the company name inside free text (an error
  message) are replaced too.
- **Dates.** Every ``datetime`` and ``date`` value, and every ISO date inside
  a string, moves back by ``date_offset_weeks`` whole weeks (a negative
  offset moves it later). Whole weeks keep every weekday the real one, so a
  Monday gap still looks like a Monday; holidays are not re-mapped, so a
  real holiday's gap can fall on an ordinary shown date.
- **Prices, volumes and returns** are unchanged.
- **News.** Headlines, sources and links name the company, so an anonymised
  drill's news markers keep only the count per day ("news: N items").

Indicators, events, forensics and every replay route are reached through the
drill routes only: ``/v1/replay`` answers 404 for an anonymised drill's
session until it is revealed. ``tests/test_drills.py`` greps every response
for the ticker, the company name and each real date in the session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, TypeVar

from pydantic import BaseModel

from stockviz.schemas import NewsEventOut, ReplayEventsOut

M = TypeVar("M", bound=BaseModel)

_ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")

NEWS_NOTE_ANONYMISED = (
    "Headlines are hidden while the drill is anonymised (they would name the company): "
    "each marker shows only how many items were available by that day."
)
NEWS_NOTE_REVEALED = "News whose available_at is at or before the replay date, with headlines."


def label_for(position: int) -> str:
    """Stock A, B, C... by the drill's position in its deck (up to 25)."""
    return f"Stock {chr(ord('A') + position)}"


@dataclass(frozen=True)
class Mask:
    ticker: str
    label: str
    offset_weeks: int
    names: tuple[str, ...] = ()
    """Other identifying strings (the company name) to replace in free text."""

    @property
    def delta(self) -> timedelta:
        return timedelta(weeks=self.offset_weeks)

    def shift_dt(self, value: datetime) -> datetime:
        return value - self.delta

    def unshift_dt(self, value: datetime) -> datetime:
        return value + self.delta

    def shift_date(self, value: date) -> date:
        return value - self.delta

    def unshift_date(self, value: date) -> date:
        return value + self.delta

    def text(self, value: str) -> str:
        if value == self.ticker:
            return self.label
        out = _ISO_DATE.sub(self._shift_match, value)
        for name in self.names:
            if name and len(name) >= 3:
                out = re.sub(re.escape(name), self.label, out, flags=re.IGNORECASE)
        return re.sub(
            rf"(?<![A-Za-z0-9.^]){re.escape(self.ticker)}(?![A-Za-z0-9])", self.label, out
        )

    def _shift_match(self, m: re.Match[str]) -> str:
        try:
            day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return m.group(0)
        return self.shift_date(day).isoformat()

    def walk(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return self.shift_dt(value)
        if isinstance(value, date):
            return self.shift_date(value)
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self.walk(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.walk(v) for v in value]
        return value

    def apply(self, model: M) -> M:
        """The same model with every value masked (validated again)."""
        return type(model).model_validate(self.walk(model.model_dump(mode="python")))

    def events(self, out: ReplayEventsOut) -> ReplayEventsOut:
        """Strip the news markers to their counts, then mask."""
        events: list[Any] = []
        for e in out.events:
            if isinstance(e, NewsEventOut):
                events.append(e.model_copy(update={"sources": [], "headlines": []}))
            else:
                events.append(e)
        stripped = out.model_copy(update={"events": events, "news_rule": NEWS_NOTE_ANONYMISED})
        return self.apply(stripped)


__all__ = ["NEWS_NOTE_ANONYMISED", "NEWS_NOTE_REVEALED", "Mask", "label_for"]
