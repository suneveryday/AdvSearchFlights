from __future__ import annotations

from datetime import date

import adv_search_flights.search.combiner as combiner
from adv_search_flights.domain.models import CombinedResult, OneWayOption


def test_limited_results_match_exhaustive_global_price_order() -> None:
    outbound = {
        "A": [_option("SHA", "A", price) for price in (100, 230, 410)],
        "B": [_option("SHA", "B", price) for price in (80, 350)],
    }
    inbound = {
        "A": [_option("A", "SHA", price) for price in (120, 280)],
        "B": [_option("B", "SHA", price) for price in (90, 260, 500)],
    }

    limited = combiner.combine_open_jaw_results(outbound, inbound, limit=7)
    expected = sorted(
        [
            (
            outbound_option.price_cny + inbound_option.price_cny,
            outbound_option.destination,
            inbound_option.origin,
            outbound_option.price_cny,
            inbound_option.price_cny,
            )
            for outbound_options in outbound.values()
            for inbound_options in inbound.values()
            for outbound_option in outbound_options
            for inbound_option in inbound_options
            if outbound_option.price_cny is not None and inbound_option.price_cny is not None
        ],
        key=lambda item: item[0],
    )

    assert [_identity(item) for item in limited] == expected[:7]
    assert [item.total_price_cny for item in limited] == sorted(item.total_price_cny for item in limited)


def test_two_destinations_include_round_trips_and_both_open_jaw_directions() -> None:
    outbound = {
        "MEL": [_option("PVG", "MEL", 100)],
        "SYD": [_option("PVG", "SYD", 200)],
    }
    inbound = {
        "MEL": [_option("MEL", "PVG", 300)],
        "SYD": [_option("SYD", "PVG", 400)],
    }

    results = combiner.combine_open_jaw_results(outbound, inbound)

    assert {(item.outbound.destination, item.inbound.origin) for item in results} == {
        ("MEL", "MEL"),
        ("MEL", "SYD"),
        ("SYD", "MEL"),
        ("SYD", "SYD"),
    }


def test_five_destinations_cover_all_25_directed_patterns_without_limit() -> None:
    destinations = ["MEL", "SYD", "SIN", "NRT", "KIX"]
    outbound = {destination: [_option("SHA", destination, 100 + index)] for index, destination in enumerate(destinations)}
    inbound = {destination: [_option(destination, "SHA", 200 + index)] for index, destination in enumerate(destinations)}

    results = combiner.combine_open_jaw_results(outbound, inbound)

    assert len(results) == 25
    assert len({(item.outbound.destination, item.inbound.origin) for item in results}) == 25


def test_top_50_materializes_only_requested_results(monkeypatch) -> None:
    destinations = ["MEL", "SYD", "SIN", "NRT", "KIX"]
    outbound = {
        destination: [_option("SHA", destination, 1000 + index * 100 + price) for price in range(100)]
        for index, destination in enumerate(destinations)
    }
    inbound = {
        destination: [_option(destination, "SHA", 1500 + index * 100 + price) for price in range(100)]
        for index, destination in enumerate(destinations)
    }
    constructed = 0
    result_model = CombinedResult

    def counting_result(**kwargs):
        nonlocal constructed
        constructed += 1
        return result_model(**kwargs)

    monkeypatch.setattr(combiner, "CombinedResult", counting_result)
    results = combiner.combine_open_jaw_results(outbound, inbound, limit=50)

    assert combiner.combination_candidate_count(outbound, inbound) == 250_000
    assert len(results) == 50
    assert constructed == 50
    assert [item.total_price_cny for item in results] == sorted(item.total_price_cny for item in results)


def _option(origin: str, destination: str, price: int) -> OneWayOption:
    return OneWayOption(
        source="test",
        origin=origin,
        destination=destination,
        date=date(2026, 9, 1),
        route=f"{origin}-{destination}",
        segments=[],
        price_cny=price,
    )


def _identity(item: CombinedResult) -> tuple[int, str, str, int, int]:
    assert item.outbound.price_cny is not None
    assert item.inbound.price_cny is not None
    return (
        item.total_price_cny,
        item.outbound.destination,
        item.inbound.origin,
        item.outbound.price_cny,
        item.inbound.price_cny,
    )
