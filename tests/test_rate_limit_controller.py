from __future__ import annotations

import asyncio

import pytest

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.domain.errors import NonRetryableSearchError


def test_temporary_provider_errors_use_legacy_short_retries() -> None:
    calls = 0
    events: list[dict] = []

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("Google Flights 暂时拒绝了本次查询")
        return "ok"

    controller = DataCallController(
        cooldown_seconds=0,
        retry_delays=(0, 0, 0),
        event_callback=events.append,
    )

    assert asyncio.run(controller.run(operation)) == "ok"
    assert calls == 3
    assert [event["type"] for event in events] == [
        "provider_retry_waiting",
        "provider_retry_waiting",
    ]


def test_non_retryable_errors_are_not_retried() -> None:
    calls = 0

    async def operation() -> None:
        nonlocal calls
        calls += 1
        raise NonRetryableSearchError("invalid request")

    controller = DataCallController(cooldown_seconds=0, retry_delays=(0, 0, 0))

    with pytest.raises(NonRetryableSearchError):
        asyncio.run(controller.run(operation))

    assert calls == 1


def test_legacy_retry_budget_is_bounded() -> None:
    calls = 0

    async def operation() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("temporary failure")

    controller = DataCallController(cooldown_seconds=0, retry_delays=(0, 0, 0))

    with pytest.raises(RuntimeError, match="temporary failure"):
        asyncio.run(controller.run(operation))

    assert calls == 4
