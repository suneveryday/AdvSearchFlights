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


def test_five_destination_progress_reports_25_directed_patterns() -> None:
    events: list[dict] = []
    response = asyncio.run(FlightSearchEngine(
        MockProvider(),
        DataCallController(cooldown_seconds=0, retry_delays=()),
        event_callback=events.append,
    ).search(SearchRequest(
        origin="SHA",
        destinations=["MEL", "SYD", "SIN", "NRT", "KIX"],
        departure="2026-09-01",
        return_date="2026-09-15",
        limit=50,
    )))

    combining = next(event for event in events if event["type"] == "combining")
    assert response.result_count == 50
    assert combining["destination_count"] == 5
    assert combining["destination_pair_count"] == 25
    assert "25 种往返/开口组合" in combining["message"]


def test_five_multi_airport_cities_keep_sequential_progress_within_total() -> None:
    events: list[dict] = []
    response = asyncio.run(FlightSearchEngine(
        MockProvider(),
        DataCallController(cooldown_seconds=0, retry_delays=()),
        event_callback=events.append,
    ).search(SearchRequest(
        origin="上海",
        destinations=["纽约", "伦敦", "巴黎", "东京", "大阪"],
        departure="2026-09-01",
        return_date="2026-09-15",
        limit=50,
    )))

    progress_events = [event for event in events if "completed" in event and "total" in event]
    assert response.result_count == 50
    assert progress_events
    assert all(event["completed"] <= event["total"] for event in progress_events)


def test_destination_aliases_resolving_to_the_same_airports_are_searched_once() -> None:
    response = asyncio.run(_search(origin="SHA", destinations=["墨尔本", "Melbourne", "MEL"]))

    assert response.destination_airport_options == {"墨尔本": ["MEL"]}
    assert all(item.outbound_destination == item.inbound_origin == "MEL" for item in response.results)


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


def test_failed_destination_is_skipped_when_another_round_trip_is_complete() -> None:
    class SydneyFailureProvider(MockProvider):
        async def search_one_way(self, origin, destination, *args, **kwargs):
            if "SYD" in {origin, destination}:
                raise RuntimeError("SYD test failure")
            return await super().search_one_way(origin, destination, *args, **kwargs)

    response = asyncio.run(FlightSearchEngine(
        SydneyFailureProvider(),
        DataCallController(cooldown_seconds=0, retry_delays=()),
    ).search(SearchRequest(
        origin="SHA",
        destinations=["墨尔本", "悉尼"],
        departure="2026-09-01",
        return_date="2026-09-15",
        limit=50,
    )))

    assert response.result_count > 0
    assert all(item.outbound_destination == item.inbound_origin == "MEL" for item in response.results)
    assert any("SYD test failure" in warning for warning in response.warnings)


def test_unknown_destination_error_names_the_invalid_value() -> None:
    with pytest.raises(ValueError, match="无法识别目的地“火星”"):
        asyncio.run(_search(origin="SHA", destinations=["墨尔本", "火星"]))


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
