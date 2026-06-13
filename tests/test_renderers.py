from __future__ import annotations

import asyncio

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.domain.models import OutputFormat, SearchRequest
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
    assert set(first) == {"rank", "total_price_cny", "outbound", "inbound"}
    for leg_name in ("outbound", "inbound"):
        leg = first[leg_name]
        assert "itinerary" in leg
        assert "segments" in leg
        assert "segment_summaries" in leg
        assert "stop_count" in leg
        assert "layovers" in leg
        assert "stop_layover_summary" in leg
        assert "price_cny" in leg
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
