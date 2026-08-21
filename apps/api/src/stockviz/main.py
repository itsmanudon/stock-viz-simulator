from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from stockviz import __version__
from stockviz.limiter import limiter
from stockviz.observability import init_sentry
from stockviz.routers import (
    alerts,
    backtest,
    bars,
    comments,
    health,
    indicators,
    leaderboard,
    markets,
    news,
    options,
    orders,
    quotes,
    recommendations,
    screener,
    stream,
    symbols,
    trading,
    watchlist,
)
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
    init_sentry(settings)

    app = FastAPI(
        title="StockViz API",
        version=__version__,
        description="Market data, news, and paper-trading backend for StockViz.",
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    # Register screener before symbols so /v1/symbols/screen wins over the
    # /v1/symbols/{ticker} catch-all in symbols.router.
    app.include_router(screener.router)
    app.include_router(symbols.router)
    app.include_router(bars.router)
    app.include_router(markets.router)
    app.include_router(news.router)
    app.include_router(quotes.router)
    app.include_router(indicators.router)
    app.include_router(recommendations.router)
    app.include_router(trading.router)
    app.include_router(alerts.router)
    app.include_router(watchlist.router)
    app.include_router(leaderboard.router)
    app.include_router(orders.router)
    app.include_router(stream.router)
    app.include_router(comments.router)
    app.include_router(options.router)
    app.include_router(backtest.router)

    return app


app = create_app()
