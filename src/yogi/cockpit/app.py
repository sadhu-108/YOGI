"""Cockpit Application Factory — FastAPI ASGI application instantiation, lifespan, and asset mounting."""

import logging
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
) -> FastAPI:
    """Instantiate and configure the YOGI Cockpit FastAPI application."""
    state = app_state if app_state is not None else AppState()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Pre-warm dataset at startup if requested and currently empty
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
