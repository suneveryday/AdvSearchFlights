from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.domain.errors import RateLimitedSearchError
from adv_search_flights.domain.models import SearchRequest
from adv_search_flights.providers.mock import MockProvider
from adv_search_flights.search.engine import FlightSearchEngine


def test_multiple_destinations_include_round_trip_and_open_jaw_results() -> None:
    response = asyncio.run(_search(origin="上海", destinations=["墨尔本", "悉尼"]))
    assert response.result_count > 0
    assert response.origin_iatas == ["PVG", "SHA"]
    assert any(item.outbound_destination == item.inbound_origin for item in response.results)
    assert any(item.outbound_destination != item.inbound_origin for item in response.results)
    assert response.results == sorted(response.results, key=lambda item: item.total_price_cny)


def test_single_destination_returns_round_trip_results() -> None:
    response = asyncio.run(_search(origin="SHA", destinations=["MEL"]))

    assert response.result_count > 0
    assert all(item.outbound_destination == item.inbound_origin for item in response.results)


def test_up_to_five_candidate_destinations_are_cross_combined() -> None:
    response = asyncio.run(_search(origin="SHA", destinations=["MEL", "SYD", "SIN", "NRT", "KIX"]))

    airport_pairs = {(item.outbound.destination, item.inbound.origin) for item in response.results}
    assert len(response.query.destinations) == 5
    assert len(airport_pairs) == 25
    assert any(outbound == inbound for outbound, inbound in airport_pairs)
    assert any(outbound != inbound for outbound, inbound in airport_pairs)


def test_more_than_five_candidate_destinations_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(
            origin="SHA",
            destinations=["MEL", "SYD", "SIN", "NRT", "KIX", "BKK"],
            departure="2026-09-01",
            return_date="2026-09-15",
        )


def test_non_shanghai_city_airport_resolution_cases() -> None:
    cases = [
        ("北京", ["东京"], ["PEK", "PKX"], {"HND", "NRT"}),
        ("广州", ["新加坡"], ["CAN"], {"SIN"}),
        ("香港", ["曼谷"], ["HKG"], {"BKK", "DMK"}),
    ]
    for origin, destinations, expected_origins, expected_destinations in cases:
        response = asyncio.run(_search(origin=origin, destinations=destinations))
        assert response.origin_iatas == expected_origins
        assert set(response.destination_iatas) == expected_destinations
        assert response.result_count > 0


def test_search_request_accepts_cabin_class() -> None:
    request = SearchRequest(
        origin="广州",
        destinations=["新加坡"],
        departure="2026-09-01",
        return_date="2026-09-15",
        cabin_class="BUSINESS",
    )

    assert request.cabin_class.value == "BUSINESS"


def test_rate_limited_leg_is_skipped_while_other_airport_pair_returns_results() -> None:
    class PartiallyRateLimitedProvider(MockProvider):
        rate_limited = True

        async def search_one_way(self, origin, destination, *args, **kwargs):
            if "PVG" in {origin, destination}:
                raise RateLimitedSearchError("HTTP 429 Too Many Requests")
            return await super().search_one_way(origin, destination, *args, **kwargs)

    events: list[dict] = []
    engine = FlightSearchEngine(
        PartiallyRateLimitedProvider(),
        DataCallController(
            cooldown_seconds=0,
            retry_delays=(0, 0, 0),
            event_callback=events.append,
        ),
        event_callback=events.append,
    )
    response = asyncio.run(engine.search(SearchRequest(
        origin="上海",
        destinations=["墨尔本"],
        departure="2026-09-01",
        return_date="2026-09-15",
    )))

    assert response.result_count > 0
    assert any("429" in warning for warning in response.warnings)
    assert sum(event["type"] == "provider_retry_waiting" for event in events) == 6


async def _search(origin: str, destinations: list[str]):
    engine = FlightSearchEngine(
        MockProvider(),
        DataCallController(cooldown_seconds=0, retry_delays=(0, 0, 0)),
    )
    return await engine.search(
        SearchRequest(
            origin=origin,
            destinations=destinations,
            departure="2026-09-01",
            return_date="2026-09-15",
        )
    )
