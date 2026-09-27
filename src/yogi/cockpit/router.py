"""Cockpit HTTP Router — Pure transport controllers delegating to Core and Application Services.

Strictly preserves:
1. Zero business logic, math, filtering, or ranking in router handlers.
2. Canonical screening pipeline: QUALIFY -> ORDER -> SHOW -> LIMIT -> RESULTS.
3. Decoupling of presentation columns via ColumnProjectingAssembler without polluting ScreeningQuery.
"""

from datetime import datetime, timezone
import logging
import re
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

logger = logging.getLogger(__name__)

from yogi.cockpit.schemas import (
    BandAuditItemOut,
    BandBackupItemOut,
    BandBackupsResponseOut,
    BandGlobalLogResponseOut,
    BandLogResponseOut,
    BandRestoreResponseOut,
    BandUpdateIn,
    BandUpdateOut,
    BandsResponseOut,
    CandleSeriesOut,
    ExportRequestIn,
    FilterGroupIn,
    MetadataResponseOut,
    MetadataUpdateIn,
    MetadataUpdateOut,
    QueryResultOut,
    RaceResponseOut,
    RankCutoffIn,
    RefreshRequestIn,
    ScreenRequestIn,
    StockDetailPanelOut,
    StrategyDetailOut,
    StrategyRunIn,
    StrategySummaryOut,
    SystemStatusOut,
    UserPresetIn,
    UserPresetOut,
    to_screening_query,
)
from yogi.cockpit.state import AppState, ColumnProjectingAssembler
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.ranking import RankingOrder
from yogi.core.contracts.results import ExportFormat
from yogi.data.providers.exceptions import (
    DataProviderAuthenticationError,
    DataProviderError,
)

try:
    from yogi.data.providers.exceptions import RateLimitExceededError  # type: ignore
except ImportError:
    class RateLimitExceededError(DataProviderError):
        """Raised when market data provider rate limits are exceeded."""
        pass


def get_app_state(request: Request) -> AppState:
    """Dependency provider resolving AppState from the FastAPI application container."""
    state = getattr(request.app.state, "yogi_state", None)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Application state not initialized.",
        )
    return state


router = APIRouter(prefix="/api", tags=["Cockpit API"])


@router.get("/status", response_model=SystemStatusOut)
def get_system_status(app_state: AppState = Depends(get_app_state)) -> SystemStatusOut:
    """Return health status, universe size, and materialized dataset timestamp."""
    return SystemStatusOut(
        status="READY",
        universe_count=len(app_state.dataset),
        last_built_at=app_state.last_built_at.isoformat() if app_state.last_built_at else None,
        exchange=app_state.config.exchange,
        provider=app_state.config.provider,
        is_demo=app_state.is_demo,
    )


@router.post("/dataset/refresh", response_model=SystemStatusOut)
async def refresh_dataset(
    req: Optional[RefreshRequestIn] = None,
    app_state: AppState = Depends(get_app_state),
) -> SystemStatusOut:
    """Rebuild in-memory feature dataset asynchronously and replace reference atomically."""
    symbols = req.symbols if req else None
    symbol_limit = req.symbol_limit if req else None
    provider = req.provider if req else None
    try:
        await app_state.refresh(symbols=symbols, symbol_limit=symbol_limit, provider=provider)
    except Exception as exc:
        logger.exception("Failed to refresh dataset: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh dataset: {exc}",
        )
    return SystemStatusOut(
        status="READY",
        universe_count=len(app_state.dataset),
        last_built_at=app_state.last_built_at.isoformat() if app_state.last_built_at else None,
        exchange=app_state.config.exchange,
        provider=app_state.config.provider,
        is_demo=app_state.is_demo,
    )


@router.get("/table", response_model=QueryResultOut)
def get_table(
    columns: Optional[str] = Query(default=None, description="Comma-separated column keys"),
    app_state: AppState = Depends(get_app_state),
) -> QueryResultOut:
    """Assemble presentation table of current dataset with default or requested columns."""
    col_list = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
    rows = list(app_state.dataset.values())
    payload = app_state.assembler.assemble(records=rows, columns=col_list)
    return QueryResultOut.from_core(payload)


@router.post("/screen", response_model=QueryResultOut)
def run_screen(
    req: ScreenRequestIn,
    app_state: AppState = Depends(get_app_state),
) -> QueryResultOut:
    """Execute dynamic screening intent adhering strictly to QUALIFY -> ORDER -> SHOW -> LIMIT -> RESULTS."""
    # 1. Translate screening fields into frozen ScreeningQuery (NO columns)
    query = to_screening_query(
        filter_group=req.filter_group,
        ranking_metric=req.ranking_metric,
        ranking_order=req.ranking_order,
        selection_cutoffs=req.selection_cutoffs,
        limit=req.limit,
    )

    # 2. Bind presentation columns at the Cockpit boundary if provided
    assembler = (
        ColumnProjectingAssembler(delegate=app_state.assembler, columns=req.columns)
        if req.columns
        else app_state.assembler
    )

    # 3. Execute canonical pipeline
    payload = app_state.orchestrator.execute_screen(
        query=query,
        records=app_state.dataset,
        result_assembler=assembler,
    )

    return QueryResultOut.from_core(payload)


@router.get("/strategies", response_model=list[StrategySummaryOut])
def list_strategies(
    include_user: bool = False,
    app_state: AppState = Depends(get_app_state),
) -> list[StrategySummaryOut]:
    """List all registered strategy recipes and verified mentor presets."""
    summaries: list[StrategySummaryOut] = []
    for name in app_state.catalog.list_names():
        spec = app_state.catalog.get(name)
        summaries.append(
            StrategySummaryOut(
                name=spec.name,
                description=spec.description or "",
                is_mentor_preset=spec.is_mentor_preset,
                target_ranking_metric=spec.target_ranking_metric,
            )
        )
    if include_user:
        for p in app_state.list_user_presets():
            summaries.append(
                StrategySummaryOut(
                    name=p["name"],
                    description=p.get("description") or "Custom user preset",
                    is_mentor_preset=False,
                    target_ranking_metric=p.get("ranking_metric"),
                )
            )
    return summaries


@router.get("/strategies/{name}", response_model=StrategyDetailOut)
def get_strategy(
    name: str,
    app_state: AppState = Depends(get_app_state),
) -> StrategyDetailOut:
    """Retrieve complete specification for a mentor preset or registered strategy."""
    detail = app_state.get_strategy_detail(name)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy '{name}' not found in catalog or user presets.",
        )
    return detail


@router.get("/user-presets", response_model=list[UserPresetOut])
def list_user_presets(app_state: AppState = Depends(get_app_state)) -> list[UserPresetOut]:
    """List all user-defined screening presets."""
    presets = app_state.list_user_presets()
    return [UserPresetOut(**p) for p in presets]


@router.post("/user-presets", response_model=UserPresetOut)
def save_user_preset(
    preset_in: UserPresetIn,
    app_state: AppState = Depends(get_app_state),
) -> UserPresetOut:
    """Save or update a user-defined screening preset."""
    payload = preset_in.model_dump()
    payload["created_at"] = datetime.now(timezone.utc).isoformat()
    saved = app_state.save_user_preset(payload)
    return UserPresetOut(**saved)


@router.delete("/user-presets/{name}")
def delete_user_preset(
    name: str,
    app_state: AppState = Depends(get_app_state),
) -> dict[str, Any]:
    """Delete a user-defined screening preset by name."""
    success = app_state.delete_user_preset(name)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User preset '{name}' not found.",
        )
    return {"success": True, "name": name}


@router.get("/panel/{symbol}", response_model=StockDetailPanelOut)
def get_stock_panel(
    symbol: str,
    app_state: AppState = Depends(get_app_state),
) -> StockDetailPanelOut:
    """Extract multi-timeframe analytical panel data for the stock drawer."""
    try:
        panel = app_state.get_stock_panel(symbol)
    except DataProviderAuthenticationError as exc:
        logger.warning("Provider authentication failed for symbol '%s': %s", symbol, exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Market data provider authentication failed: {exc}",
        )
    except RateLimitExceededError as exc:
        logger.warning("Provider rate limit reached for symbol '%s': %s", symbol, exc)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Data provider rate limit reached. Please wait a minute: {exc}",
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise

        exc_type_name = type(exc).__name__
        msg = str(exc)
        lower_msg = msg.lower()

        # Check for rate limit indicators
        if (
            exc_type_name == "RateLimitExceededError"
            or "rate limit" in lower_msg
            or "credit limit" in lower_msg
            or "minute limit" in lower_msg
            or "too many requests" in lower_msg
        ):
            logger.warning("Provider rate limit detected for symbol '%s': %s", symbol, exc)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Data provider rate limit reached. Please wait a minute: {msg}",
            )

        # Check for authentication indicators
        if (
            exc_type_name == "DataProviderAuthenticationError"
            or "api key is required" in lower_msg
            or "invalid api key" in lower_msg
            or "unauthorized" in lower_msg
            or "authentication failed" in lower_msg
        ):
            logger.warning("Provider auth failure detected for symbol '%s': %s", symbol, exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Market data provider authentication failed: {msg}",
            )

        # Check for provider connection / outage / network failure
        if (
            isinstance(exc, (DataProviderError, ConnectionError, TimeoutError, OSError))
            or "offline" in lower_msg
            or "connection" in lower_msg
            or "timeout" in lower_msg
            or "temporarily unavailable" in lower_msg
            or "failed to establish a new connection" in lower_msg
        ):
            logger.warning("Provider outage/network failure for symbol '%s': %s", symbol, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Market data provider offline or unavailable: {msg}",
            )

        # Other unexpected provider/orchestrator errors
        logger.error("Unexpected error retrieving stock panel for '%s': %s", symbol, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Market data provider error: {msg}",
        )

    if panel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stock '{symbol}' not found in current materialized dataset or active provider.",
        )
    return panel


@router.post("/strategy/run", response_model=QueryResultOut)
def run_strategy(
    req: StrategyRunIn,
    app_state: AppState = Depends(get_app_state),
) -> QueryResultOut:
    """Execute a registered strategy recipe or mentor preset through the canonical pipeline."""
    if app_state.catalog.has(req.strategy_name):
        query = app_state.catalog.to_query(req.strategy_name)
    elif app_state.get_user_preset(req.strategy_name) is not None:
        u = app_state.get_user_preset(req.strategy_name)
        fg = FilterGroupIn(**u["filter_group"]) if u.get("filter_group") else None
        cutoffs = [RankCutoffIn(**c) for c in u.get("selection_cutoffs", [])]
        query = to_screening_query(
            filter_group=fg,
            ranking_metric=u.get("ranking_metric"),
            ranking_order=u.get("ranking_order", RankingOrder.DESCENDING),
            selection_cutoffs=cutoffs,
            limit=u.get("limit"),
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy '{req.strategy_name}' not found in catalog or user presets.",
        )

    # 1. Apply optional limit override if specified in request
    if req.limit is not None:
        query = ScreeningQuery(
            filter_group=query.filter_group,
            ranking_metric=query.ranking_metric,
            ranking_order=query.ranking_order,
            selection_cutoffs=query.selection_cutoffs,
            limit=req.limit,
        )

    # 2. Bind presentation columns at the Cockpit boundary if provided
    assembler = (
        ColumnProjectingAssembler(delegate=app_state.assembler, columns=req.columns)
        if req.columns
        else app_state.assembler
    )

    # 3. Execute canonical pipeline
    payload = app_state.orchestrator.execute_screen(
        query=query,
        records=app_state.dataset,
        result_assembler=assembler,
    )

    return QueryResultOut.from_core(payload)


@router.get("/bands/{symbol}", response_model=BandsResponseOut)
def get_bands(
    symbol: str,
    app_state: AppState = Depends(get_app_state),
) -> BandsResponseOut:
    """Retrieve all discretionary band widths for a symbol across standard timeframes."""
    if app_state.bands_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bands repository not configured.",
        )

    sym = symbol.strip().upper()
    bands_map = app_state.bands_repo.get_all_bands(sym)
    return BandsResponseOut(symbol=sym, bands=dict(bands_map))


@router.put("/bands/{symbol}", response_model=BandUpdateOut)
def update_band(
    symbol: str,
    req: BandUpdateIn,
    app_state: AppState = Depends(get_app_state),
) -> BandUpdateOut:
    """Update a discretionary band width for a symbol and timeframe."""
    if app_state.bands_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bands repository not configured.",
        )

    sym = symbol.strip().upper()
    val = app_state.bands_repo.set_band(
        symbol=sym,
        timeframe=req.timeframe,
        value=req.value,
        who="cockpit",
        source="api",
    )
    app_state.clear_panel_cache()
    return BandUpdateOut(symbol=sym, timeframe=req.timeframe, value=val, success=True)


@router.get("/bands/log/{symbol}", response_model=BandLogResponseOut)
def get_band_log_symbol(
    symbol: str,
    limit: int = Query(default=60, ge=1, le=500),
    app_state: AppState = Depends(get_app_state),
) -> BandLogResponseOut:
    """Retrieve reverse-chronological band change history for a single symbol."""
    if app_state.bands_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bands repository not configured.",
        )
    sym = symbol.strip().upper()
    resolved_limit = limit if isinstance(limit, int) else getattr(limit, "default", 60)
    if hasattr(app_state.bands_repo, "get_history"):
        history = app_state.bands_repo.get_history(symbol=sym, limit=resolved_limit)
        items = [
            BandAuditItemOut(
                when=e.when,
                symbol=e.symbol,
                timeframe=e.timeframe,
                old_pct=e.old_pct,
                new_pct=e.new_pct,
                changed_by=e.changed_by,
                source=e.source,
            )
            for e in history
        ]
    else:
        items = []
    return BandLogResponseOut(symbol=sym, changes=items)


@router.get("/bands/log", response_model=BandGlobalLogResponseOut)
def get_band_log_all(
    limit: int = Query(default=300, ge=1, le=1000),
    app_state: AppState = Depends(get_app_state),
) -> BandGlobalLogResponseOut:
    """Retrieve global reverse-chronological band change history across all symbols."""
    if app_state.bands_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bands repository not configured.",
        )
    resolved_limit = limit if isinstance(limit, int) else getattr(limit, "default", 300)
    if hasattr(app_state.bands_repo, "get_history"):
        history = app_state.bands_repo.get_history(symbol=None, limit=resolved_limit)
        items = [
            BandAuditItemOut(
                when=e.when,
                symbol=e.symbol,
                timeframe=e.timeframe,
                old_pct=e.old_pct,
                new_pct=e.new_pct,
                changed_by=e.changed_by,
                source=e.source,
            )
            for e in history
        ]
    else:
        items = []
    return BandGlobalLogResponseOut(changes=items)


@router.get("/bands/backups", response_model=BandBackupsResponseOut)
def get_band_backups(
    app_state: AppState = Depends(get_app_state),
) -> BandBackupsResponseOut:
    """Retrieve available dated daily band backups."""
    if app_state.bands_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bands repository not configured.",
        )
    # Prototype triggers daily snapshot before listing
    if hasattr(app_state.bands_repo, "create_snapshot"):
        try:
            app_state.bands_repo.create_snapshot(reason="auto")
        except Exception as exc:
            logger.warning("Could not create automatic daily snapshot: %s", exc)

    if hasattr(app_state.bands_repo, "list_backups"):
        backups = app_state.bands_repo.list_backups()
        items = [
            BandBackupItemOut(
                file=b.filename,
                date=b.date_str,
                stocks=b.symbol_count,
                size_kb=b.size_kb,
            )
            for b in backups
        ]
    else:
        items = []
    return BandBackupsResponseOut(backups=items)


@router.post("/bands/restore/{filename}", response_model=BandRestoreResponseOut)
@router.get("/bands/restore/{filename}", response_model=BandRestoreResponseOut)
def restore_band_backup(
    filename: str,
    app_state: AppState = Depends(get_app_state),
) -> BandRestoreResponseOut:
    """Restore all band width configurations from a dated backup snapshot."""
    if app_state.bands_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bands repository not configured.",
        )
    if app_state.is_demo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Band restore operation is disabled in demo mode.",
        )

    # Strict path traversal and regex protection
    if not re.match(r"^bands_\d{4}-\d{2}-\d{2}\.csv$", filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid backup filename '{filename}'. Format must match 'bands_YYYY-MM-DD.csv'.",
        )

    if not hasattr(app_state.bands_repo, "restore_backup"):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Active bands repository does not support restoration.",
        )

    try:
        app_state.bands_repo.restore_backup(filename)
    except FileNotFoundError as fnf_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(fnf_err),
        ) from fnf_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(val_err),
        ) from val_err
    except PermissionError as perm_err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(perm_err),
        ) from perm_err
    except Exception as exc:
        logger.error("Unexpected error during restore of %s: %s", filename, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Restore failed: {exc}",
        ) from exc

    # Invalidate panel cache to purge stale calculated envelopes
    app_state.clear_panel_cache()

    # Determine restored stock count for response
    all_bands = getattr(app_state.bands_repo, "_bands", {})
    count = len(all_bands)
    return BandRestoreResponseOut(
        ok=True,
        msg=f"restored {filename} ({count} stocks).",
        filename=filename,
        stocks=count,
    )


# -----------------------------------------------------------------------------
# Security Metadata Endpoints (Two-way metadata overlay)
# -----------------------------------------------------------------------------

@router.get("/meta/{symbol}", response_model=MetadataResponseOut)
def get_metadata(
    symbol: str,
    exchange: str = Query(default="NSE"),
    app_state: AppState = Depends(get_app_state),
) -> MetadataResponseOut:
    """Retrieve canonical security metadata for a symbol."""
    sym_u = symbol.strip().upper()
    ex_u = exchange.strip().upper()

    repo = app_state.metadata_repository
    sec = repo.get_metadata(sym_u, exchange=ex_u) if repo else None

    if sec is None:
        rec = app_state.dataset.get(sym_u)
        if rec is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Security metadata not found for symbol '{sym_u}'.",
            )
        is_fno = str(rec.get("fno", "N")).upper() == "Y"
        return MetadataResponseOut(
            symbol=sym_u,
            exchange=ex_u,
            name=rec.get("name"),
            sector=rec.get("sector"),
            grade=rec.get("grade"),
            is_fno=is_fno,
            fno="Y" if is_fno else "N",
            mcap=rec.get("mcap"),
            instrument_type=str(rec.get("instr", "EQ")),
            listing_status="ACTIVE",
            series_or_group=str(rec.get("grp", "")) or None,
        )

    return MetadataResponseOut(
        symbol=sec.symbol,
        exchange=sec.exchange,
        name=sec.name,
        isin=sec.isin,
        sector=sec.sector,
        grade=sec.grade,
        is_fno=sec.is_fno,
        fno="Y" if sec.is_fno else "N",
        mcap=sec.mcap,
        instrument_type=sec.instrument_type.value,
        listing_status=sec.listing_status.value,
        series_or_group=sec.series_or_group,
        notes=sec.notes,
    )


@router.post("/meta/{symbol}", response_model=MetadataUpdateOut)
def update_metadata(
    symbol: str,
    body: MetadataUpdateIn,
    exchange: str = Query(default="NSE"),
    app_state: AppState = Depends(get_app_state),
) -> MetadataUpdateOut:
    """Update a security metadata field (two-way edit)."""
    sym_u = symbol.strip().upper()
    ex_u = exchange.strip().upper()

    if app_state.is_demo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Metadata update operation is disabled in demo mode.",
        )

    repo = app_state.metadata_repository
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Metadata repository is not configured.",
        )

    try:
        updated = repo.update_metadata(
            symbol=sym_u,
            field=body.field,
            value=body.value,
            exchange=ex_u,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Symbol '{sym_u}' not found for metadata update.",
            )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(val_err),
        ) from val_err
    except Exception as exc:
        logger.error("Failed to update metadata for %s: %s", sym_u, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Metadata update failed: {exc}",
        ) from exc

    return MetadataUpdateOut(
        symbol=sym_u,
        field=body.field,
        value=body.value,
        success=True,
    )



@router.get("/candles/{symbol}", response_model=CandleSeriesOut)
def get_candles(
    symbol: str,
    tf: str = Query(default="D", pattern="^(D|W|M|Q|H|Y)$"),
    band_tf: Optional[str] = Query(default=None, pattern="^(D|W|M|Q|H|Y|NONE|none|OFF|off|)$"),
    exchange: str = Query(default="NSE"),
    years: int = Query(default=2, gt=0, le=20),
    app_state: AppState = Depends(get_app_state),
) -> CandleSeriesOut:
    """Retrieve synthesized candlestick bars and rolling band envelope curves."""
    if app_state.chart_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart service is not available (no market data provider registered).",
        )
    # Resolve parameters if called directly in Python tests where defaults are Query/FieldInfo objects
    resolved_tf = tf if isinstance(tf, str) else getattr(tf, "default", "D")
    resolved_band_tf = band_tf if (isinstance(band_tf, str) or band_tf is None) else getattr(band_tf, "default", None)
    resolved_exchange = exchange if isinstance(exchange, str) else getattr(exchange, "default", "NSE")
    resolved_years = years if isinstance(years, int) else getattr(years, "default", 2)

    try:
        return app_state.chart_service.get_candles(
            symbol=symbol,
            timeframe=resolved_tf,
            band_timeframe=resolved_band_tf,
            exchange=resolved_exchange,
            years=resolved_years,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/race", response_model=RaceResponseOut)
async def get_race(
    symbols: Optional[str] = Query(default=None, description="Comma-separated symbols, or empty for leaders"),
    anchor: str = Query(default="2021-01-01", description="Fixed anchor date YYYY-MM-DD"),
    top: int = Query(default=15, ge=1, le=50, description="Maximum number of leader lines"),
    metric: str = Query(default="SPA_A21", description="Ranking metric for auto-leader selection"),
    exchange: Optional[str] = Query(default=None, description="Exchange code (defaults to engine configuration)"),
    app_state: AppState = Depends(get_app_state),
) -> RaceResponseOut:
    """Return sprint race time-series curves week-by-week from fixed anchor date."""
    race_svc = app_state.race_service
    if race_svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Race service is not available (no market data provider registered).",
        )
    target_exchange = exchange or app_state.config.exchange
    try:
        return await race_svc.get_race(
            symbols=symbols,
            anchor=anchor,
            top=top,
            metric=metric,
            exchange=target_exchange,
        )
    except DataProviderError as exc:
        logger.error("Provider error during race curve generation: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream provider failure: {exc}",
        )
    except Exception as exc:
        logger.error("Unexpected error during race curve generation: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Race calculation failed: {exc}",
        )


@router.post("/export")
def export_screen(
    req: ExportRequestIn,
    app_state: AppState = Depends(get_app_state),
) -> Response:
    """Execute screen and export results to XLSX, CSV, or JSON binary/text bytes."""
    # 1. Resolve ScreeningQuery
    if req.strategy_name:
        if not app_state.catalog.has(req.strategy_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Strategy '{req.strategy_name}' not found in catalog.",
            )
        query = app_state.catalog.to_query(req.strategy_name)
        if req.limit is not None:
            query = ScreeningQuery(
                filter_group=query.filter_group,
                ranking_metric=query.ranking_metric,
                ranking_order=query.ranking_order,
                selection_cutoffs=query.selection_cutoffs,
                limit=req.limit,
            )
    else:
        query = to_screening_query(
            filter_group=req.filter_group,
            ranking_metric=req.ranking_metric,
            ranking_order=req.ranking_order,
            selection_cutoffs=req.selection_cutoffs,
            limit=req.limit,
        )

    # 2. Bind presentation columns at the Cockpit boundary if provided
    assembler = (
        ColumnProjectingAssembler(delegate=app_state.assembler, columns=req.columns)
        if req.columns
        else app_state.assembler
    )

    # 3. Execute canonical pipeline
    payload = app_state.orchestrator.execute_screen(
        query=query,
        records=app_state.dataset,
        result_assembler=assembler,
    )

    # 4. Serialize to requested export format
    fmt = req.format
    export_bytes = app_state.formatter.format(payload, export_format=fmt)

    media_types = {
        ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ExportFormat.CSV: "text/csv; charset=utf-8",
        ExportFormat.JSON: "application/json",
    }
    media_type = media_types.get(fmt, "application/octet-stream")
    ext = fmt.value if hasattr(fmt, "value") else str(fmt)

    return Response(
        content=export_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="yogi_export.{ext}"'},
    )
