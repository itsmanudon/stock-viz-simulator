"""The local-only rule for the owner's intraday files (A6.1).

Owner decision, 26 Nov 2026: the owner's intraday files never go to
production, demos included. So the loader writes only to a database on this
machine: PostgreSQL whose host is ``localhost``, ``127.0.0.1`` or ``::1``
(or SQLite, a local file by construction, for tests). There is no flag,
setting or environment variable that overrides it.

The check reads the URL the writer is bound to (never only the
``DATABASE_URL`` setting, which a caller could bypass). It refuses a URL
with no host (a socket path or ``PGHOST`` could point anywhere), and one
whose query names ``host``, ``hostaddr`` or ``service`` (libpq would connect
there instead of the URL's host).
"""

from __future__ import annotations

from sqlalchemy.engine import URL, make_url

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_OVERRIDING_QUERY_KEYS = frozenset({"host", "hostaddr", "service"})


class RemoteDatabaseRefused(RuntimeError):
    """The database is not on this machine: the owner's files never leave it."""


def local_database_problem(url: str | URL) -> str | None:
    """Why ``url`` is not an allowed target, or None when it is local."""
    parsed = make_url(url) if isinstance(url, str) else url
    backend = parsed.get_backend_name()
    if backend == "sqlite":
        return None
    if backend != "postgresql":
        return f"database backend {backend!r} is not PostgreSQL on this machine"
    host = (parsed.host or "").strip().strip("[]").lower()
    if not host:
        return "the database URL names no host (a socket or PGHOST could be anywhere)"
    if host not in LOCAL_HOSTS:
        return f"the database host {host!r} is not localhost, 127.0.0.1 or ::1"
    overriding = sorted(_OVERRIDING_QUERY_KEYS & {k.lower() for k in parsed.query})
    if overriding:
        return f"the database URL's query sets {', '.join(overriding)}, which overrides the host"
    return None


def require_local_database(url: str | URL) -> None:
    """Raise :class:`RemoteDatabaseRefused` unless ``url`` is a local database."""
    problem = local_database_problem(url)
    if problem is not None:
        raise RemoteDatabaseRefused(
            f"refusing to load the owner's intraday files: {problem}. These files never "
            "go to production or any hosted database (owner decision, 26 Nov 2026); "
            "point DATABASE_URL at a local PostgreSQL. There is no override."
        )
