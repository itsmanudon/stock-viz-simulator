from collections.abc import Generator

from sqlmodel import Session, create_engine

from stockviz.settings import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    echo=_settings.debug,
    pool_pre_ping=True,
)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
