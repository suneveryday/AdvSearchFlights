from __future__ import annotations

import asyncio
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.domain.models import CombinedResult, OneWayOption, OutputFormat, SearchRequest, Segment
from adv_search_flights.output.renderers import render_results
from adv_search_flights.providers.mock import MockProvider
from adv_search_flights.search.engine import FlightSearchEngine


def test_table_output_contains_required_trip_fields() -> None:
    response = asyncio.run(_search(output_format=OutputFormat.table))
    rendered = response.rendered

    assert isinstance(rendered, str)
    assert "总价" in rendered
    assert "去程行程" in rendered
    assert "去程每段航线起降时间" in rendered
    assert "去程中转次数&停留时间" in rendered
    assert "去程价格" in rendered
    assert "回程行程" in rendered
    assert "回程每段航线起降时间" in rendered
    assert "回程中转次数&停留时间" in rendered
    assert "回程价格" in rendered
    assert "SHA(上海虹桥国际机场)" in rendered
    assert "MEL(墨尔本机场)" in rendered
    assert "中国东方航空" in rendered
    assert "机型" not in rendered


def test_text_output_contains_required_segment_details() -> None:
    response = asyncio.run(_search(output_format=OutputFormat.text))
    rendered = response.rendered

    assert isinstance(rendered, str)
    assert "去程行程：" in rendered
    assert "回程行程：" in rendered
    assert "去程每段航线起降时间：" in rendered
    assert "回程每段航线起降时间：" in rendered
    assert "去程中转次数&停留时间：" in rendered
    assert "回程中转次数&停留时间：" in rendered
    assert "MU" in rendered or "SQ" in rendered
    assert "中国东方航空" in rendered or "新加坡航空" in rendered
    assert "789 波音 787-9" in rendered or "359 空客 A350-900" in rendered


def test_json_output_is_sorted_and_has_required_fields() -> None:
    response = asyncio.run(_search(output_format=OutputFormat.json))
    rendered = response.rendered

    assert isinstance(rendered, list)
    prices = [item["total_price_cny"] for item in rendered]
    assert prices == sorted(prices)
    first = rendered[0]
    assert set(first) == {"rank", "total_price_cny", "outbound", "inbound", "purchase_links"}
    assert first["purchase_links"]["outbound"]["type"] == "search"
    assert first["purchase_links"]["outbound"]["url"].startswith("https://www.google.com/travel/flights/search?")
    for leg_name in ("outbound", "inbound"):
        leg = first[leg_name]
        assert "itinerary" in leg
        assert "segments" in leg
        assert "segment_summaries" in leg
        assert "stop_count" in leg
        assert "layovers" in leg
        assert "stop_layover_summary" in leg
        assert "price_cny" in leg
        assert "airlines" in leg
        assert "departure_time" in leg
        assert "arrival_time" in leg
        assert "origin_airport" in leg
        assert "destination_airport" in leg
        assert "layover_hours_total" in leg
        assert "layover_cities" in leg
        segment = leg["segments"][0]
        assert segment["origin_airport"]
        assert segment["origin_airport_name_zh"]
        assert segment["destination_airport"]
        assert segment["destination_airport_name_zh"]
        assert segment["flight_number"]
        assert segment["airline_zh"]
        assert segment["aircraft"]
        assert segment["aircraft_zh"]
        assert segment["departure_time"]
        assert segment["arrival_time"]


def test_booking_link_uses_booking_token_with_generated_tfs() -> None:
    result = _combined_with_raw({"booking_token": "token-only"})
    rendered = render_results([result], OutputFormat.json)

    assert isinstance(rendered, list)
    link = rendered[0]["purchase_links"]["outbound"]
    assert link["type"] == "booking"
    parsed = urlparse(link["url"])
    query = parse_qs(parsed.query)
    assert parsed.path == "/travel/flights/booking"
    assert query["tfs"][0]
    assert query["tfu"][0]
    assert query["curr"][0] == "CNY"


def test_booking_link_uses_complete_tfs_tfu_pair() -> None:
    result = _combined_with_raw({"tfs": "sample-tfs", "tfu": "sample-tfu"})
    rendered = render_results([result], OutputFormat.json)

    assert isinstance(rendered, list)
    link = rendered[0]["purchase_links"]["outbound"]
    assert link["type"] == "booking"
    assert link["url"] == "https://www.google.com/travel/flights/booking?tfs=sample-tfs&tfu=sample-tfu&curr=CNY"


def test_search_link_uses_generated_tfs_when_booking_is_unavailable() -> None:
    result = _combined_with_raw({})
    rendered = render_results([result], OutputFormat.json)

    assert isinstance(rendered, list)
    link = rendered[0]["purchase_links"]["outbound"]
    parsed = urlparse(link["url"])
    query = parse_qs(parsed.query)
    assert link["type"] == "search"
    assert parsed.path == "/travel/flights/search"
    assert query["tfs"][0]
    assert query["curr"][0] == "CNY"


def test_cebu_pacific_pvg_mnl_mel_booking_tfs_matches_google_shape() -> None:
    expected_tfs = "CBwQAhpkEgoyMDI2LTA5LTI5Ih8KA1BWRxIKMjAyNi0wOS0yORoDTU5MKgI1SjIDNjc5Ih4KA01OTBIKMjAyNi0wOS0yORoDTUVMKgI1SjICNDlqDAgDEggvbS8wNndqZnIHCAESA01FTEABSAFwAYIBCwj___________8BmAEC"
    result = _combined_with_raw(
        {"booking_token": "token-only"},
        outbound_segments=[
            _segment("PVG", "MNL", "5J679", "5J", datetime(2026, 9, 29, 1, 35), datetime(2026, 9, 29, 5, 35)),
            _segment("MNL", "MEL", "5J49", "5J", datetime(2026, 9, 29, 12, 55), datetime(2026, 9, 29, 23, 10)),
        ],
    )
    rendered = render_results([result], OutputFormat.json)

    assert isinstance(rendered, list)
    link = rendered[0]["purchase_links"]["outbound"]
    query = parse_qs(urlparse(link["url"]).query)
    assert query["tfs"][0] == expected_tfs


def test_business_cabin_pvg_can_syd_booking_tfs_matches_google_shape() -> None:
    expected_tfs = "CBwQAhpmEgoyMDI2LTA5LTI5IiAKA1BWRxIKMjAyNi0wOS0yORoDQ0FOKgJDWjIEODIxMiIfCgNDQU4SCjIwMjYtMDktMzAaA1NZRCoCQ1oyAzMwMWoMCAMSCC9tLzA2d2pmcgcIARIDU1lEQAFIA3ABggELCP___________wGYAQI"
    expected_tfu = "CnRDalJJYVdVellXRmZTQzFZVjI5QlJrUlVWVUZDUnkwdExTMHRMUzB0TFMxemJXaG5ORUZCUVVGQlIyOHdTRVpWUlU5eVNITkJFZ3hEV2pneU1USjhRMW96TURFYUNnamhlUkFBR2dORFRsazRISERxaVE0PRICCAAiAA"
    result = _combined_with_raw(
        {
            "session_id": "Hie3aa_H-XWoAFDTUABG----------smhg4AAAAAGo0HFUEOrHsA",
            "currency": "CNY",
            "emissions_g": 230634,
            "cabin_class": "BUSINESS",
        },
        outbound_segments=[
            _segment("PVG", "CAN", "CZ8212", "CZ", datetime(2026, 9, 29, 22, 5), datetime(2026, 9, 30, 0, 30)),
            _segment("CAN", "SYD", "CZ301", "CZ", datetime(2026, 9, 30, 8, 0), datetime(2026, 9, 30, 19, 25)),
        ],
    )
    result.outbound.price_cny = 15585
    rendered = render_results([result], OutputFormat.json)

    assert isinstance(rendered, list)
    link = rendered[0]["purchase_links"]["outbound"]
    query = parse_qs(urlparse(link["url"]).query)
    assert query["tfs"][0] == expected_tfs
    assert query["tfu"][0] == expected_tfu


def test_json_selected_flights_token_falls_back_to_search_page() -> None:
    result = _combined_with_raw({"booking_token": '[["PVG", "SYD"]]', "cabin_class": "BUSINESS"})
    rendered = render_results([result], OutputFormat.json)

    assert isinstance(rendered, list)
    link = rendered[0]["purchase_links"]["outbound"]
    assert link["type"] == "search"
    assert urlparse(link["url"]).path == "/travel/flights/search"


async def _search(output_format: OutputFormat):
    engine = FlightSearchEngine(
        MockProvider(),
        DataCallController(cooldown_seconds=0, retry_delays=(0, 0, 0)),
    )
    return await engine.search(
        SearchRequest(
            origin="SHA",
            destinations=["MEL", "SYD"],
            departure="2026-09-29",
            return_date="2026-10-07",
            output_format=output_format,
            limit=3,
        )
    )


def _combined_with_raw(raw: dict, outbound_segments: list[Segment] | None = None) -> CombinedResult:
    outbound = _one_way("PVG", "MEL", raw, outbound_segments)
    inbound = _one_way("MEL", "PVG", {})
    return CombinedResult(
        total_price_cny=7200,
        outbound_destination="MEL",
        inbound_origin="MEL",
        outbound=outbound,
        inbound=inbound,
    )


def _one_way(origin: str, destination: str, raw: dict, segments: list[Segment] | None = None) -> OneWayOption:
    departure = datetime(2026, 9, 29, 10, 0)
    arrival = datetime(2026, 9, 29, 22, 0)
    return OneWayOption(
        source="test",
        origin=origin,
        destination=destination,
        date=date(2026, 9, 29),
        route=f"{origin}-{destination}",
        price_cny=3600,
        raw=raw,
        segments=segments or [_segment(origin, destination, "MU737", "MU", departure, arrival)],
    )


def _segment(origin: str, destination: str, flight_number: str, airline_code: str, departure: datetime, arrival: datetime) -> Segment:
    return Segment(
        flight_number=flight_number,
        airline="Test Airline",
        airline_code=airline_code,
        airline_zh="测试航空",
        aircraft="Boeing 787",
        aircraft_zh="波音 787",
        origin_airport=origin,
        origin_airport_name_zh=origin,
        destination_airport=destination,
        destination_airport_name_zh=destination,
        departure_time=departure,
        arrival_time=arrival,
    )
