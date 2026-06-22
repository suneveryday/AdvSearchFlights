from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any
from datetime import date

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.data.airports import resolve_airports
from adv_search_flights.data.reference_data import airport_name_zh
from adv_search_flights.diagnostics import log_event
from adv_search_flights.domain.models import OneWayOption, SearchRequest, SearchResponse
from adv_search_flights.output.renderers import render_results
from adv_search_flights.providers.base import FlightProvider
from adv_search_flights.search.combiner import combination_candidate_count, combine_open_jaw_results
from adv_search_flights.search.filtering import filter_one_way_options


class FlightSearchEngine:
    def __init__(
        self,
        provider: FlightProvider,
        controller: DataCallController | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
        max_concurrency: int = 1,
    ) -> None:
        self.provider = provider
        self.controller = controller or DataCallController()
        self.progress_callback = progress_callback
        self.event_callback = event_callback
        self.max_concurrency = max(1, max_concurrency)
        self._leg_cache: dict[tuple[str, str, date], list[OneWayOption]] = {}

    async def search(self, request: SearchRequest) -> SearchResponse:
        origin_airports = resolve_airports(request.origin)
        destination_groups = _resolve_destination_groups(request.destinations)
        warnings: list[str] = []
        outbound_by_dest: dict[str, list[OneWayOption]] = {}
        inbound_by_dest: dict[str, list[OneWayOption]] = {}
        total_legs = _count_legs(origin_airports, destination_groups)
        started_at = time.monotonic()
        log_event(
            "search.started",
            provider=request.provider.value,
            origin_airports=origin_airports,
            destination_airports=destination_groups,
            departure=request.departure.isoformat(),
            return_date=request.return_date.isoformat(),
            cabin_class=request.cabin_class.value,
            total_legs=total_legs,
        )
        completed_legs = 0
        self._event("started", completed=completed_legs, total=total_legs, message=f"准备搜索 {total_legs} 个单程组合")
        self._progress(completed_legs, total_legs, f"准备搜索 {total_legs} 个单程组合")

        if self.max_concurrency > 1:
            await self._search_legs_concurrently(
                origin_airports=origin_airports,
                destination_groups=destination_groups,
                request=request,
                warnings=warnings,
                outbound_by_dest=outbound_by_dest,
                inbound_by_dest=inbound_by_dest,
                total_legs=total_legs,
            )
        else:
            for destination_key, destination_airports in destination_groups.items():
                outbound_by_dest[destination_key] = []
                inbound_by_dest[destination_key] = []
                for origin_airport in origin_airports:
                    for destination_airport in destination_airports:
                        if origin_airport == destination_airport:
                            continue
                        self._event("leg_started", completed=completed_legs, total=total_legs, origin=origin_airport, destination=destination_airport, date=request.departure.isoformat(), direction="outbound", message=f"正在查询 {origin_airport}->{destination_airport}")
                        self._progress(completed_legs, total_legs, f"正在查询 {origin_airport}->{destination_airport}")
                        outbound_by_dest[destination_key].extend(
                            await self._search_one_leg(origin_airport, destination_airport, request.departure, request, warnings)
                        )
                        completed_legs += 1
                        self._event("leg_finished", completed=completed_legs, total=total_legs, origin=origin_airport, destination=destination_airport, date=request.departure.isoformat(), direction="outbound", message=f"已完成 {completed_legs}/{total_legs}：{origin_airport}->{destination_airport}")
                        self._progress(completed_legs, total_legs, f"已完成 {completed_legs}/{total_legs}：{origin_airport}->{destination_airport}")

                        self._event("leg_started", completed=completed_legs, total=total_legs, origin=destination_airport, destination=origin_airport, date=request.return_date.isoformat(), direction="inbound", message=f"正在查询 {destination_airport}->{origin_airport}")
                        self._progress(completed_legs, total_legs, f"正在查询 {destination_airport}->{origin_airport}")
                        inbound_by_dest[destination_key].extend(
                            await self._search_one_leg(destination_airport, origin_airport, request.return_date, request, warnings)
                        )
                        completed_legs += 1
                        self._event("leg_finished", completed=completed_legs, total=total_legs, origin=destination_airport, destination=origin_airport, date=request.return_date.isoformat(), direction="inbound", message=f"已完成 {completed_legs}/{total_legs}：{destination_airport}->{origin_airport}")
                        self._progress(completed_legs, total_legs, f"已完成 {completed_legs}/{total_legs}：{destination_airport}->{origin_airport}")

        destination_pair_count = len(destination_groups) ** 2
        candidate_count = combination_candidate_count(outbound_by_dest, inbound_by_dest)
        combination_started_at = time.monotonic()
        self._event(
            "combining",
            completed=total_legs,
            total=total_legs,
            destination_count=len(destination_groups),
            destination_pair_count=destination_pair_count,
            message=f"正在比较 {len(destination_groups)} 个候选目的地的 {destination_pair_count} 种往返/开口组合",
        )
        log_event(
            "combining.started",
            destination_count=len(destination_groups),
            destination_pair_count=destination_pair_count,
            outbound_option_count=sum(map(len, outbound_by_dest.values())),
            inbound_option_count=sum(map(len, inbound_by_dest.values())),
            candidate_count=candidate_count,
            limit=request.limit,
        )
        results = combine_open_jaw_results(outbound_by_dest, inbound_by_dest, request.limit)
        log_event(
            "combining.completed",
            destination_pair_count=destination_pair_count,
            candidate_count=candidate_count,
            materialized_count=len(results),
            duration_ms=round((time.monotonic() - combination_started_at) * 1000),
        )
        destination_iatas = _unique(airport for airports in destination_groups.values() for airport in airports)
        response = SearchResponse(
            query=request,
            provider=request.provider,
            origin_iata="/".join(origin_airports),
            origin_iatas=origin_airports,
            origin_name_zh=" / ".join(filter(None, (airport_name_zh(code) for code in origin_airports))) or None,
            origin_names_zh={code: airport_name_zh(code) for code in origin_airports},
            destination_iatas=destination_iatas,
            destination_airport_options=destination_groups,
            destination_names_zh={destination: airport_name_zh(destination) for destination in destination_iatas},
            result_count=len(results),
            results=results,
            warnings=warnings,
        )
        response.rendered = render_results(results, request.output_format)
        log_event(
            "search.completed",
            provider=request.provider.value,
            result_count=len(results),
            warning_count=len(warnings),
            duration_ms=round((time.monotonic() - started_at) * 1000),
        )
        return response

    async def _search_legs_concurrently(
        self,
        *,
        origin_airports: list[str],
        destination_groups: dict[str, list[str]],
        request: SearchRequest,
        warnings: list[str],
        outbound_by_dest: dict[str, list[OneWayOption]],
        inbound_by_dest: dict[str, list[OneWayOption]],
        total_legs: int,
    ) -> None:
        semaphore = asyncio.Semaphore(self.max_concurrency)
        progress_lock = asyncio.Lock()
        completed_legs = 0

        for destination_key in destination_groups:
            outbound_by_dest[destination_key] = []
            inbound_by_dest[destination_key] = []

        async def run_leg(
            destination_key: str,
            bucket: dict[str, list[OneWayOption]],
            origin: str,
            destination: str,
            departure_date: date,
        ) -> None:
            nonlocal completed_legs
            async with semaphore:
                self._event("leg_started", completed=completed_legs, total=total_legs, origin=origin, destination=destination, date=departure_date.isoformat(), message=f"正在查询 {origin}->{destination}")
                self._progress(completed_legs, total_legs, f"正在查询 {origin}->{destination}")
                options = await self._search_one_leg(origin, destination, departure_date, request, warnings)
                bucket[destination_key].extend(options)
                async with progress_lock:
                    completed_legs += 1
                    self._event("leg_finished", completed=completed_legs, total=total_legs, origin=origin, destination=destination, date=departure_date.isoformat(), message=f"已完成 {completed_legs}/{total_legs}：{origin}->{destination}")
                    self._progress(completed_legs, total_legs, f"已完成 {completed_legs}/{total_legs}：{origin}->{destination}")

        tasks = []
        for destination_key, destination_airports in destination_groups.items():
            for origin_airport in origin_airports:
                for destination_airport in destination_airports:
                    if origin_airport == destination_airport:
                        continue
                    tasks.append(run_leg(destination_key, outbound_by_dest, origin_airport, destination_airport, request.departure))
                    tasks.append(run_leg(destination_key, inbound_by_dest, destination_airport, origin_airport, request.return_date))
        await asyncio.gather(*tasks)

    async def _search_one_leg(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        request: SearchRequest,
        warnings: list[str],
    ) -> list[OneWayOption]:
        cache_key = (origin, destination, departure_date)
        if cache_key in self._leg_cache:
            log_event("leg.cache_hit", origin=origin, destination=destination, date=departure_date.isoformat())
            return self._leg_cache[cache_key]
        started_at = time.monotonic()
        log_event("leg.started", origin=origin, destination=destination, date=departure_date.isoformat())
        try:
            operation = lambda: self.provider.search_one_way(
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                adults=request.adults,
                currency=request.currency,
                max_stops=request.max_stops,
                max_layover_minutes=request.max_layover_minutes,
                cabin_class=request.cabin_class.value,
            )
            options = await self.controller.run(operation) if self.provider.rate_limited else await operation()
        except Exception as exc:  # noqa: BLE001
            log_event(
                "leg.failed",
                level=40,
                origin=origin,
                destination=destination,
                date=departure_date.isoformat(),
                duration_ms=round((time.monotonic() - started_at) * 1000),
                error=exc,
            )
            warnings.append(f"{origin}->{destination} 搜索失败：{exc}")
            self._event("leg_failed", origin=origin, destination=destination, date=departure_date.isoformat(), message=f"{origin}->{destination} 搜索失败：{exc}")
            self._leg_cache[cache_key] = []
            return []
        for option in options:
            option.raw.setdefault("cabin_class", request.cabin_class.value)
        filtered = filter_one_way_options(options, request)
        log_event(
            "leg.completed",
            origin=origin,
            destination=destination,
            date=departure_date.isoformat(),
            raw_count=len(options),
            filtered_count=len(filtered),
            duration_ms=round((time.monotonic() - started_at) * 1000),
        )
        self._leg_cache[cache_key] = filtered
        return filtered

    def _progress(self, completed: int, total: int, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(completed, total, message)

    def _event(self, event_type: str, **payload) -> None:
        if self.event_callback:
            self.event_callback({"type": event_type, **payload})


def estimate_leg_count(request: SearchRequest) -> int:
    origin_airports = resolve_airports(request.origin)
    destination_groups = _resolve_destination_groups(request.destinations)
    return _count_legs(origin_airports, destination_groups)


def _resolve_destination_groups(destinations: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    seen_airport_sets: set[tuple[str, ...]] = set()
    for destination in destinations:
        try:
            airports = resolve_airports(destination)
        except ValueError as exc:
            raise ValueError(f"无法识别目的地“{destination}”：{exc}") from exc
        semantic_key = tuple(sorted(airports))
        if semantic_key in seen_airport_sets:
            continue
        seen_airport_sets.add(semantic_key)
        groups[destination] = airports
    return groups


def _count_legs(origin_airports: list[str], destination_groups: dict[str, list[str]]) -> int:
    total = 0
    for destination_airports in destination_groups.values():
        for origin_airport in origin_airports:
            for destination_airport in destination_airports:
                if origin_airport != destination_airport:
                    total += 2
    return total


def _unique(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
