"""`stockviz.cli doctor`: a read-only check of a self-hosted instance (A10.1).

One line per check: ``ok``, ``warn``, ``off`` or ``fail``. Only a ``fail``
(a required item) makes the command exit 1. Never prints a secret: keys are
named, never shown.

Checks: the database answers; migrations are at head; the web bridge secret
is set, not the committed default and at least 32 characters; how many
symbols and daily bars are stored and the newest bar (none is ``warn``: the
release ships no market data); the scheduler; each optional provider key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import text
from sqlmodel import Session

from stockviz.settings import _DEV_SECRET_DEFAULTS, Settings

MIN_SECRET_LENGTH = 32

OPTIONAL_KEYS: tuple[tuple[str, str], ...] = (
    ("ALPHA_VANTAGE_KEY", "alpha_vantage_key"),
    ("SEC_USER_AGENT", "sec_user_agent"),
    ("ALPACA_KEY_ID", "alpaca_key_id"),
    ("TIINGO_API_KEY", "tiingo_api_key"),
    ("FINNHUB_API_KEY", "finnhub_api_key"),
    ("MASSIVE_API_KEY", "massive_api_key"),
    ("KITE_API_KEY", "kite_api_key"),
    ("AEGIS_BASE_URL", "aegis_base_url"),
    ("SMTP_HOST", "smtp_host"),
    ("TELEGRAM_BOT_TOKEN", "telegram_bot_token"),
)


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # ok | warn | off | fail
    detail: str


def _value(settings: Settings, attr: str) -> str:
    raw = getattr(settings, attr, "")
    if isinstance(raw, SecretStr):
        raw = raw.get_secret_value()
    return str(raw or "").strip()


def secret_checks(settings: Settings) -> list[Check]:
    token = _value(settings, "internal_api_token")
    if not token:
        return [Check("INTERNAL_API_TOKEN", "fail", "not set")]
    if token == _DEV_SECRET_DEFAULTS["internal_api_token"]:
        return [Check("INTERNAL_API_TOKEN", "fail", "still the committed dev default")]
    if len(token) < MIN_SECRET_LENGTH:
        return [Check("INTERNAL_API_TOKEN", "fail", f"shorter than {MIN_SECRET_LENGTH} characters")]
    return [Check("INTERNAL_API_TOKEN", "ok", "set (must equal the web's)")]


def key_checks(settings: Settings) -> list[Check]:
    out = []
    for env, attr in OPTIONAL_KEYS:
        on = bool(_value(settings, attr))
        out.append(Check(env, "ok" if on else "off", "set" if on else "blank: that feature is off"))
    return out


def scheduler_check(settings: Settings) -> Check:
    if settings.enable_scheduler:
        return Check("ENABLE_SCHEDULER", "ok", "nightly jobs run in this process")
    return Check(
        "ENABLE_SCHEDULER", "warn", "off: run the stockviz.cli jobs yourself or set it to true"
    )


def database_checks(session: Session) -> list[Check]:
    try:
        session.connection().execute(text("SELECT 1"))
    except Exception:
        return [Check("database", "fail", "does not answer")]
    out = [Check("database", "ok", "answers")]
    out.append(migration_check(session))
    symbols = session.connection().execute(text("SELECT count(*) FROM symbols")).one()[0]
    bars, newest = (
        session.connection()
        .execute(text("SELECT count(*), max(ts) FROM price_bars WHERE interval = '1d'"))
        .one()
    )
    out.append(
        Check(
            "symbols",
            "ok" if symbols else "warn",
            f"{symbols} stored" if symbols else "none: run `stockviz.cli seed`",
        )
    )
    out.append(
        Check(
            "daily bars",
            "ok" if bars else "warn",
            f"{bars} stored, newest {str(newest)[:10]}"
            if bars
            else "none (no market data ships): run `stockviz.cli ingest <tickers>`",
        )
    )
    return out


def migration_check(session: Session) -> Check:
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[3]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    heads = set(ScriptDirectory.from_config(cfg).get_heads())
    current = set(MigrationContext.configure(session.connection()).get_current_heads())
    if current == heads:
        return Check("migrations", "ok", "at head")
    if not current:
        return Check("migrations", "fail", "none applied: run `alembic upgrade head`")
    return Check("migrations", "fail", "behind head: run `alembic upgrade head`")


def run(session: Session, settings: Settings) -> list[Check]:
    return [
        *database_checks(session),
        *secret_checks(settings),
        scheduler_check(settings),
        *key_checks(settings),
    ]


def render(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    return "\n".join(f"{c.status:<4}  {c.name:<{width}}  {c.detail}" for c in checks)
