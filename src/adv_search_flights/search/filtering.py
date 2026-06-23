from __future__ import annotations

from adv_search_flights.domain.models import OneWayOption, SearchRequest


def filter_one_way_options(options: list[OneWayOption], request: SearchRequest) -> list[OneWayOption]:
    return [
        option
        for option in options
        if option.price_cny is not None
        and option.stops <= request.max_stops
        and option.max_layover_minutes <= request.max_layover_minutes
    ]
