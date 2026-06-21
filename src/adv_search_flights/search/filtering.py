from __future__ import annotations

from adv_search_flights.domain.models import CombinedResult, OneWayOption, SearchRequest


def filter_one_way_options(options: list[OneWayOption], request: SearchRequest) -> list[OneWayOption]:
    return [
        option
        for option in options
        if option.price_cny is not None
        and option.stops <= request.max_stops
        and option.max_layover_minutes <= request.max_layover_minutes
    ]


def sort_and_limit_results(results: list[CombinedResult], limit: int | None = None) -> list[CombinedResult]:
    sorted_results = sorted(results, key=lambda item: item.total_price_cny)
    if limit is not None:
        return sorted_results[:limit]
    return sorted_results
