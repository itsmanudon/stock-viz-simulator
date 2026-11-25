"""archive the legacy news tables (A0 hygiene)

Revision ID: ea0040711437
Revises: 89b9ba1b46b5
Create Date: 2026-11-25 21:00:00.000000

The legacy news pipeline (NewsData.io ingest, Anthropic/HTTP sentiment
scoring, the Kafka news workers) is removed in A0: Aegis News owns news, and
``/v1/news`` and the sentiment readers use the ``aegis_*`` copies. The two
tables it wrote are not dropped: ``news_articles`` and ``news_sentiment`` move
to the ``archive`` schema with their rows, primary keys, unique keys, indexes,
sequences and the ``news_sentiment -> news_articles`` key, so nothing is lost.
``news_articles``' keys to ``symbols`` and ``instruments`` and its instrument
trigger are dropped, so the archive never blocks a change to a live table.
The downgrade moves both back and restores them (the keys as NOT VALID, since
archived rows may point at rows deleted since). Dropping the archive is the
owner's call. Same pattern as ``89b9ba1b46b5`` (comments).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ea0040711437"
down_revision: str | None = "89b9ba1b46b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Read from pg_constraint on a database at 89b9ba1b46b5. news_sentiment has no
# key to a live table: its only foreign key is to news_articles, which moves
# with it and stays.
LIVE_KEYS = {
    "news_articles_ticker_fkey": "FOREIGN KEY (ticker) REFERENCES symbols(ticker)",
    "fk_news_articles_instrument_id": "FOREIGN KEY (instrument_id) REFERENCES instruments(id)",
}

# Order does not matter: SET SCHEMA keeps the key between them.
TABLES = ("news_articles", "news_sentiment")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS archive")
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} SET SCHEMA archive")
    op.execute("DROP TRIGGER IF EXISTS trg_news_articles_instrument_id ON archive.news_articles")
    for name in LIVE_KEYS:
        op.execute(f"ALTER TABLE archive.news_articles DROP CONSTRAINT IF EXISTS {name}")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE archive.{table} SET SCHEMA public")
    for name, definition in LIVE_KEYS.items():
        op.execute(f"ALTER TABLE public.news_articles ADD CONSTRAINT {name} {definition} NOT VALID")
    op.execute(
        "CREATE TRIGGER trg_news_articles_instrument_id BEFORE INSERT OR UPDATE OF ticker "
        "ON public.news_articles FOR EACH ROW EXECUTE FUNCTION stockviz_fill_instrument_id()"
    )
