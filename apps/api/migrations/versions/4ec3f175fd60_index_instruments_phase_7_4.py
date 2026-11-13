"""index instruments (Phase 7.4)

Revision ID: 4ec3f175fd60
Revises: 4d4accec26be
Create Date: 2026-11-13 00:57:08.725847

"""

from collections.abc import Sequence

from alembic import op


revision: str = "4ec3f175fd60"
down_revision: str | None = "4d4accec26be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FUNCTION = """
CREATE OR REPLACE FUNCTION stockviz_asset_type(p_ticker text, p_exchange text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN upper(coalesce(p_exchange, '')) = 'COMMODITY' THEN 'commodity'
    WHEN p_ticker ~* '^(NIFTY|BANKNIFTY|MIDCAP|SMALLCAP)' {extra}THEN 'index'
    ELSE 'equity'
  END
$$;
"""


def upgrade() -> None:
    # Phase 7.4: Yahoo index tickers (^GSPC, ^NSEI) are benchmark indices.
    op.execute(_FUNCTION.format(extra="OR left(p_ticker, 1) = '^' "))
    op.execute(
        "UPDATE instruments SET asset_type = 'index' "
        "WHERE left(symbol, 1) = '^' AND asset_type <> 'index'"
    )


def downgrade() -> None:
    op.execute(_FUNCTION.format(extra=""))
