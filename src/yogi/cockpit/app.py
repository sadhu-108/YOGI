"""Cockpit Application Factory — FastAPI ASGI application instantiation, lifespan, and asset mounting."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from yogi.cockpit.router import router
from yogi.cockpit.state import AppState

logger = logging.getLogger(__name__)


def create_app(
    app_state: Optional[AppState] = None,
    static_dir: Optional[Path] = None,
    auto_refresh: bool = False,
    autoload_cache: Optional[bool] = None,
    auto_background: Optional[bool] = None,
) -> FastAPI:
    """Instantiate and configure the YOGI Cockpit FastAPI application."""
    is_testing = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    should_autoload = autoload_cache if autoload_cache is not None else not is_testing
    should_autobackground = auto_background if auto_background is not None else not is_testing

    state = app_state if app_state is not None else AppState(autoload_cache=should_autoload)
    if should_autoload and not state.dataset:
        state.load_persisted_cache()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        if auto_refresh and not state.dataset:
            try:
                await state.refresh()
            except Exception as exc:
                # Startup resilience: allow server boot even if live provider is offline
                logger.warning(
                    "Optional startup dataset pre-warming failed; continuing startup without cached data: %s",
                    exc,
                    exc_info=True,
                )
        elif should_autobackground and not state.dataset and not state.is_demo:
            # Fast startup: If no dataset is active and live provider is configured, trigger initial background rebuild
            logger.info("Lifespan: No active dataset found. Triggering initial background rebuild...")
            state.start_background_rebuild()
        yield


    app = FastAPI(
        title="YOGI Investing Cockpit",
        description="Interactive screening, strategy execution, and multi-timeframe financial analysis.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Attach AppState to FastAPI application container
    app.state.yogi_state = state

    # Configure CORS for local browser access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routes
    app.include_router(router)

    # Resolve static assets directory
    assets_path = static_dir if static_dir is not None else Path(__file__).parent / "static"
    if assets_path.exists():
        app.mount("/static", StaticFiles(directory=str(assets_path)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(str(assets_path / "index.html"))

    return app
