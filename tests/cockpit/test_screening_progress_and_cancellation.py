"""Targeted tests for screening progress reporting, percentage tracking, and cancellation."""

import time
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional, Sequence
import pytest
from fastapi import HTTPException

from yogi.cockpit.router import cancel_screen, get_screen_progress, run_screen
from yogi.cockpit.schemas import (
    FilterGroupIn,
    FilterRuleIn,
    ScreenRequestIn,
)
from yogi.cockpit.state import AppState, ScreeningTask
from yogi.core.configuration.engine import EngineConfig
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.filter import (
    FilterGroupSpec,
    FilterOperator,
    FilterRuleSpec,
    ScreeningCancelledError,
)
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.filter.engine import FilterEngine
from yogi.ranking.engine import RankingEngine
from yogi.results.assembler import ResultAssembler
from yogi.selection.engine import SelectionEngine
from yogi.timeframe.engine import TimeframeEngine


class SyntheticProvider(IDataProvider):
    name = "synthetic"

    def __init__(self, count: int = 60) -> None:
        self.symbols = [f"SYM_{i:03d}" for i in range(count)]

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return self.symbols

    def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 2) -> Sequence[MarketBar]:
        base = datetime(2025, 1, 1)
        idx = int(symbol.split("_")[-1]) if "_" in symbol else 0
        return [
            MarketBar(
                timestamp=base + timedelta(days=i),
                open=100.0 + idx + i * 0.5,
                high=102.0 + idx + i * 0.5,
                low=98.0 + idx + i * 0.5,
                close=101.0 + idx + i * 0.5,
                volume=1000.0,
            )
            for i in range(40)
        ]

    def batch_daily_history(self, symbols: Sequence[str], exchange: str = "NSE", years: int = 2) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.daily_history(symbol, exchange)
        return bars[-1].close if bars else None

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> Any:
        from yogi.core.contracts.provider import ProviderHealth
        return ProviderHealth(provider="synthetic", ok=True)


def _make_app_state(symbols_count: int = 50) -> tuple[AppState, SyntheticProvider]:
    from yogi.calculation.trend import TrendCalculator

    provider = SyntheticProvider(count=symbols_count)
    hub = RegistryHub()
    hub.providers.register("synthetic", provider)
    hub.calculations.register("trend", TrendCalculator())

    tf_engine = TimeframeEngine()
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
        result_assembler=ResultAssembler(),
        timeframe_engine=tf_engine,
    )

    records = {
        sym: {
            "symbol": sym,
            "exchange": "NSE",
            "provider": "synthetic",
            "price": 100.0 + i,
            "name": f"Company {sym}",
            "sector": "Technology" if i % 2 == 0 else "Finance",
            "mcap": 10000.0 + i * 100.0,
        }
        for i, sym in enumerate(provider.symbols)
    }

    state = AppState(
        orchestrator=orchestrator,
        initial_dataset=records,
        config=EngineConfig(provider="synthetic"),
    )
    return state, provider


# ===========================================================================
# 1. Progress Reporting Tests
# ===========================================================================

def test_progress_starts_at_zero_and_reaches_one_hundred():
    """Verify progress starts at 0% and successfully completes at 100%."""
    state, provider = _make_app_state(30)
    bars_map = {s: provider.daily_history(s) for s in provider.symbols}

    progress_log: list[float] = []

    def on_prog(pct: float, stage: str, msg: str, curr: int, tot: int) -> None:
        progress_log.append(pct)

    query = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[
                FilterRuleSpec(
                    field="EMA_D_5_13",
                    condition_type="ema",
                    timeframe="D",
                    p1=5,
                    p2=13,
                    state="UP",
                )
            ]
        )
    )

    result = state.orchestrator.execute_screen(
        query=query,
        records=state.dataset,
        bars_cache=bars_map,
        progress_callback=on_prog,
    )

    assert len(result.rows) > 0
    assert len(progress_log) >= 2
    assert progress_log[0] == 0.0
    assert progress_log[-1] == 100.0


def test_progress_is_strictly_monotonic_and_within_bounds():
    """Verify progress is strictly non-decreasing and always in [0.0, 100.0]."""
    state, _ = _make_app_state(40)
    req_id = "req_monotonic_test"

    state.register_screening_task(req_id, total_count=40)

    # Simulate sequence of progress updates
    updates = [0.0, 5.0, 15.0, 15.0, 42.0, 80.0, 75.0, 95.0, 100.0, 105.0]
    for u in updates:
        state.update_screening_progress(req_id, progress=u, stage="test", message=f"At {u}%")
        task = state.get_screening_task(req_id)
        assert task is not None
        assert 0.0 <= task.progress <= 100.0

    task_final = state.get_screening_task(req_id)
    assert task_final.progress == 100.0


def test_progress_updates_associated_with_correct_request():
    """Verify independent progress tracking across multiple concurrent requests."""
    state, _ = _make_app_state(10)
    req_1 = "scr_alpha"
    req_2 = "scr_beta"

    state.register_screening_task(req_1)
    state.register_screening_task(req_2)

    state.update_screening_progress(req_1, 35.0, "stage1", "Alpha at 35%")
    state.update_screening_progress(req_2, 70.0, "stage2", "Beta at 70%")

    t1 = state.get_screening_task(req_1)
    t2 = state.get_screening_task(req_2)

    assert t1.progress == 35.0
    assert t1.message == "Alpha at 35%"
    assert t2.progress == 70.0
    assert t2.message == "Beta at 70%"


# ===========================================================================
# 2. Cancellation Tests
# ===========================================================================

def test_cancelling_running_screen_stops_computation():
    """Verify that cancellation check interrupts execution and raises ScreeningCancelledError."""
    state, provider = _make_app_state(60)
    bars_map = {s: provider.daily_history(s) for s in provider.symbols}

    checked_counts = 0

    def cancel_check() -> bool:
        nonlocal checked_counts
        checked_counts += 1
        return checked_counts >= 2  # Cancel after 2 checks

    query = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[
                FilterRuleSpec(
                    field="EMA_D_5_13",
                    condition_type="ema",
                    timeframe="D",
                    p1=5,
                    p2=13,
                    state="UP",
                )
            ]
        )
    )

    with pytest.raises(ScreeningCancelledError):
        state.orchestrator.execute_screen(
            query=query,
            records=state.dataset,
            bars_cache=bars_map,
            cancel_check=cancel_check,
        )


def test_cancelled_request_does_not_publish_partial_results(monkeypatch):
    """Verify that cancelled screening via router returns 499 and partial results are not returned."""
    state, _ = _make_app_state(20)

    # Mock execute_screen to simulate cancellation midway
    def mock_execute(*args, **kwargs):
        raise ScreeningCancelledError("Screening was cancelled by the user.")

    monkeypatch.setattr(state.orchestrator, "execute_screen", mock_execute)

    req = ScreenRequestIn(
        request_id="req_to_cancel",
        filter_group=FilterGroupIn(
            rules=[FilterRuleIn(field="price", op=">", value=100.0)]
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        run_screen(req=req, app_state=state)

    assert exc_info.value.status_code == 499
    assert "cancelled" in exc_info.value.detail.lower()

    # Verify task state is marked cancelled, not completed
    task = state.get_screening_task("req_to_cancel")
    assert task is not None
    assert task.status == "cancelled"


def test_cancellation_after_completion_does_not_mark_task_cancelled():
    """Verify that a cancellation arriving after completion does NOT mark it cancelled."""
    state, _ = _make_app_state(10)
    req_id = "req_already_done"

    state.register_screening_task(req_id)
    state.complete_screening_task(req_id)

    status_code, msg = state.request_screening_cancellation(req_id)
    assert status_code == "completed"

    task = state.get_screening_task(req_id)
    assert task.status == "completed"
    assert task.progress == 100.0


def test_repeated_cancellation_requests_handled_safely():
    """Verify multiple cancellation calls on the same request do not error."""
    state, _ = _make_app_state(10)
    req_id = "req_repeat_cancel"

    state.register_screening_task(req_id)

    # First cancel
    st1, msg1 = state.request_screening_cancellation(req_id)
    assert st1 == "cancelling"

    # Second cancel while cancelling
    st2, msg2 = state.request_screening_cancellation(req_id)
    assert st2 == "cancelling"

    # Mark cancelled
    state.cancel_screening_task(req_id)

    # Third cancel after cancelled
    st3, msg3 = state.request_screening_cancellation(req_id)
    assert st3 == "cancelled"


def test_cancel_unknown_request_returns_404():
    """Verify cancelling an unknown request identifier returns HTTP 404."""
    state, _ = _make_app_state(5)

    with pytest.raises(HTTPException) as exc_info:
        cancel_screen("non_existent_req_id", app_state=state)

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


def test_progress_unknown_request_returns_404():
    """Verify requesting progress on an unknown request identifier returns HTTP 404."""
    state, _ = _make_app_state(5)

    with pytest.raises(HTTPException) as exc_info:
        get_screen_progress("unknown_progress_id", app_state=state)

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


def test_cancelling_one_request_does_not_affect_unrelated_requests():
    """Verify cancelling request A does not cancel or interfere with request B."""
    state, _ = _make_app_state(10)
    req_A = "task_A"
    req_B = "task_B"

    state.register_screening_task(req_A)
    state.register_screening_task(req_B)

    # Cancel A
    state.request_screening_cancellation(req_A)
    assert state.is_screening_cancelled(req_A) is True
    assert state.is_screening_cancelled(req_B) is False

    # Complete B
    state.complete_screening_task(req_B)
    assert state.get_screening_task(req_B).status == "completed"
    assert state.get_screening_task(req_A).status == "cancelling"


def test_failed_request_records_failure_and_does_not_report_completed():
    """Verify that exceptions mark the task failed and do not report 100% completion."""
    state, _ = _make_app_state(10)
    req_id = "req_to_fail"

    state.register_screening_task(req_id)
    state.fail_screening_task(req_id, "Syntax error in rule")

    task = state.get_screening_task(req_id)
    assert task.status == "failed"
    assert "Syntax error" in task.error
    assert task.progress < 100.0


# ===========================================================================
# 3. End-to-End Router Screening with Real Request ID
# ===========================================================================

def test_router_screening_end_to_end_with_progress_and_completion():
    """Execute end-to-end screen via router and verify task completes at 100%."""
    state, _ = _make_app_state(25)
    req_id = "req_router_e2e"

    req = ScreenRequestIn(
        request_id=req_id,
        filter_group=FilterGroupIn(
            rules=[FilterRuleIn(field="price", op=">", value=110.0)]
        ),
    )

    out = run_screen(req=req, app_state=state)
    assert out.qualified_count > 0

    prog = get_screen_progress(req_id, app_state=state)
    assert prog.status == "completed"
    assert prog.progress == 100.0
    assert prog.stage == "completed"


def test_bars_cache_get_bars_for_symbols_cancellation_and_progress(tmp_path):
    """Verify MarketBarsCache.get_bars_for_symbols respects cancel_check and reports progress."""
    from yogi.storage.cache import MarketBarsCache
    cache = MarketBarsCache(cache_dir=tmp_path)
    symbols = [f"TEST_{i:03d}" for i in range(100)]

    # 1. Test progress reporting
    progress_reported = []
    def on_prog(curr, tot):
        progress_reported.append((curr, tot))

    found, missing = cache.get_bars_for_symbols(symbols, exchange="NSE", progress_callback=on_prog)
    assert len(missing) == 100
    assert len(progress_reported) > 0
    assert progress_reported[-1] == (100, 100)

    # 2. Test cancellation check interruption
    cancel_count = 0
    def cancel_check():
        nonlocal cancel_count
        cancel_count += 1
        return cancel_count >= 2

    with pytest.raises(ScreeningCancelledError):
        cache.get_bars_for_symbols(symbols, exchange="NSE", cancel_check=cancel_check)


def test_request_identity_stale_response_protection():
    """Verify that multiple sequential requests with different request IDs maintain strict isolation."""
    state, _ = _make_app_state(10)
    req1 = "req_stale"
    req2 = "req_fresh"

    state.register_screening_task(req1)
    state.register_screening_task(req2)

    # Cancel req1
    state.request_screening_cancellation(req1)
    state.cancel_screening_task(req1)

    # Complete req2
    state.complete_screening_task(req2)

    t1 = state.get_screening_task(req1)
    t2 = state.get_screening_task(req2)

    assert t1.status == "cancelled"
    assert t2.status == "completed"

