from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from adv_search_flights.domain.errors import NonRetryableSearchError
from adv_search_flights.diagnostics import log_event

T = TypeVar("T")


class DataCallController:
    def __init__(
        self,
        cooldown_seconds: int = 90,
        retry_delays: tuple[int, ...] = (30, 60, 90),
        event_callback: Callable[[dict], None] | None = None,
    ) -> None:
        self.cooldown_seconds = cooldown_seconds
        self.retry_delays = retry_delays
        self.event_callback = event_callback
        self._lock = asyncio.Lock()
        self._last_call_at = 0.0

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        attempts = len(self.retry_delays) + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                async with self._lock:
                    await self._cooldown()
                    self._last_call_at = time.monotonic()
                return await operation()
            except NonRetryableSearchError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= len(self.retry_delays):
                    log_event("provider.retry_exhausted", level=30, attempt=attempt, error=exc)
                    break
                delay = self.retry_delays[attempt]
                log_event("provider.retry_waiting", level=30, attempt=attempt + 1, wait_seconds=delay, error=exc)
                if self.event_callback:
                    self.event_callback({
                        "type": "provider_retry_waiting",
                        "attempt": attempt + 1,
                        "max_attempts": len(self.retry_delays),
                        "wait_seconds": delay,
                        "message": f"数据源暂时不可用，{delay} 秒后重试（{attempt + 1}/{len(self.retry_delays)}）",
                    })
                await asyncio.sleep(delay)
        if last_error is None:
            raise RuntimeError("数据调用失败")
        raise last_error

    async def _cooldown(self) -> None:
        elapsed = time.monotonic() - self._last_call_at
        wait_seconds = self.cooldown_seconds - elapsed
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
