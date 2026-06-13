from __future__ import annotations

from collections.abc import Callable
from datetime import date

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.data.airports import resolve_airports
from adv_search_flights.data.reference_data import airport_name_zh
from adv_search_flights.domain.models import OneWayOption, SearchRequest, SearchResponse
from adv_search_flights.output.renderers import render_results
from adv_search_flights.providers.base import FlightProvider
from adv_search_flights.search.combiner import combine_open_jaw_results
from adv_search_flights.search.filtering import filter_one_way_options, sort_and_limit_results


class FlightSearchEngine:
    def __init__(
        self,
        provider: FlightProvider,
        controller: DataCallController | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> None:
        self.provider = provider
        self.controller = controller or DataCallController()
        self.progress_callback = progress_callback
        self._leg_cache: dict[tuple[str, str, date], list[OneWayOption]] = {}

    async def search(self, request: SearchRequest) -> SearchResponse:
        origin_airports = resolve_airports(request.origin)
        destination_groups = {destination: resolve_airports(destination) for destination in request.destinations}
        warnings: list[str] = []
        outbound_by_dest: dict[str, list[OneWayOption]] = {}
        inbound_by_dest: dict[str, list[OneWayOption]] = {}
        total_legs = _count_legs(origin_airports, destination_groups)
        completed_legs = 0
        self._progress(completed_legs, total_legs, f"准备搜索 {total_legs} 个单程组合")

        for destination_key, destination_airports in destination_groups.items():
            outbound_by_dest[destination_key] = []
            inbound_by_dest[destination_key] = []
            for origin_airport in origin_airports:
                for destination_airport in destination_airports:
                    if origin_airport == destination_airport:
                        continue
                    self._progress(completed_legs, total_legs, f"正在查询 {origin_airport}->{destination_airport}")
                    outbound_by_dest[destination_key].extend(
                        await self._search_one_leg(origin_airport, destination_airport, request.departure, request, warnings)
                    )
                    completed_legs += 1
                    self._progress(completed_legs, total_legs, f"已完成 {completed_legs}/{total_legs}：{origin_airport}->{destination_airport}")

                    self._progress(completed_legs, total_legs, f"正在查询 {destination_airport}->{origin_airport}")
                    inbound_by_dest[destination_key].extend(
                        await self._search_one_leg(destination_airport, origin_airport, request.return_date, request, warnings)
                    )
                    completed_legs += 1
                    self._progress(completed_legs, total_legs, f"已完成 {completed_legs}/{total_legs}：{destination_airport}->{origin_airport}")

        combined = combine_open_jaw_results(outbound_by_dest, inbound_by_dest)
        results = sort_and_limit_results(combined, request.limit)
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
        return response

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
            return self._leg_cache[cache_key]
        try:
            operation = lambda: self.provider.search_one_way(
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                adults=request.adults,
                currency=request.currency,
                max_stops=request.max_stops,
                max_layover_minutes=request.max_layover_minutes,
            )
            options = await self.controller.run(operation) if self.provider.rate_limited else await operation()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{origin}->{destination} 搜索失败：{exc}")
            self._leg_cache[cache_key] = []
            return []
        filtered = filter_one_way_options(options, request)
        self._leg_cache[cache_key] = filtered
        return filtered

    def _progress(self, completed: int, total: int, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(completed, total, message)


def estimate_leg_count(request: SearchRequest) -> int:
    origin_airports = resolve_airports(request.origin)
    destination_groups = {destination: resolve_airports(destination) for destination in request.destinations}
    return _count_legs(origin_airports, destination_groups)


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
