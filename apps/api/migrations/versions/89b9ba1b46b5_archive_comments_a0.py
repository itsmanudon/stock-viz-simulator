"""archive the comments table (A0 hygiene)

Revision ID: 89b9ba1b46b5
Revises: a7d9c1e3f246
Create Date: 2026-11-25 19:00:00.000000

Comments are removed from the app (A0, workspace
``docs/stockviz-handover-2026-11-25.md``). The table is not dropped: it moves
to the ``archive`` schema with its rows, primary key, indexes and the
reply-to-parent key, so nothing is lost. Its keys to ``users``, ``symbols`` and
``instruments`` and its instrument trigger are dropped, so the archive never
blocks a change to a live table (such as deleting a user). The downgrade
moves it back and restores them (the keys as NOT VALID, since archived rows
may point at rows deleted since). Dropping the archive is the owner's call.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "89b9ba1b46b5"
down_revision: str | None = "a7d9c1e3f246"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LIVE_KEYS = {
    "comments_user_id_fkey": "FOREIGN KEY (user_id) REFERENCES users(id)",
    "comments_ticker_fkey": "FOREIGN KEY (ticker) REFERENCES symbols(ticker)",
    "fk_comments_instrument_id": "FOREIGN KEY (instrument_id) REFERENCES instruments(id)",
}


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS archive")
    op.execute("ALTER TABLE public.comments SET SCHEMA archive")
    op.execute("DROP TRIGGER IF EXISTS trg_comments_instrument_id ON archive.comments")
    for name in LIVE_KEYS:
        op.execute(f"ALTER TABLE archive.comments DROP CONSTRAINT IF EXISTS {name}")


def downgrade() -> None:
    op.execute("ALTER TABLE archive.comments SET SCHEMA public")
    for name, definition in LIVE_KEYS.items():
        op.execute(f"ALTER TABLE public.comments ADD CONSTRAINT {name} {definition} NOT VALID")
    op.execute(
        "CREATE TRIGGER trg_comments_instrument_id BEFORE INSERT OR UPDATE OF ticker "
        "ON public.comments FOR EACH ROW EXECUTE FUNCTION stockviz_fill_instrument_id()"
    )
