from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from stockviz import __version__
from stockviz.routers import bars, health, indicators, news, quotes, symbols
from stockviz.scheduler import build_scheduler
from stockviz.settings import get_settings

if TYPE_CHECKING:
    from apscheduler.schedulers.background import BackgroundScheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the APScheduler if enabled, shut it down on app exit.

    Disabled by default so unit tests / one-shot CLI invocations don't spin
    up a background thread. Toggle via ``ENABLE_SCHEDULER=true`` in env.
    """
    scheduler: BackgroundScheduler | None = None
    settings = get_settings()
    if settings.enable_scheduler:
        scheduler = build_scheduler()
        scheduler.start()
        app.state.scheduler = scheduler

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="StockViz API",
        version=__version__,
        description="Market data, news, and paper-trading backend for StockViz.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(symbols.router)
    app.include_router(bars.router)
    app.include_router(news.router)
    app.include_router(quotes.router)
    app.include_router(indicators.router)

    return app


app = create_app()
