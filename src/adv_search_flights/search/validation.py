from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from adv_search_flights.domain.models import OneWayOption


class SourceComparison(BaseModel):
    route: str
    providers: list[str]
    lowest_price_cny: int | None
    highest_price_cny: int | None
    price_spread_cny: int | None


def compare_provider_results(options: list[OneWayOption]) -> list[SourceComparison]:
    grouped: dict[str, list[OneWayOption]] = defaultdict(list)
    for option in options:
        grouped[f"{option.origin}->{option.destination}:{option.date.isoformat()}"].append(option)

    comparisons: list[SourceComparison] = []
    for route, items in grouped.items():
        prices = [item.price_cny for item in items if item.price_cny is not None]
        comparisons.append(
            SourceComparison(
                route=route,
                providers=sorted({item.source for item in items}),
                lowest_price_cny=min(prices) if prices else None,
                highest_price_cny=max(prices) if prices else None,
                price_spread_cny=(max(prices) - min(prices)) if prices else None,
            )
        )
    return comparisons

