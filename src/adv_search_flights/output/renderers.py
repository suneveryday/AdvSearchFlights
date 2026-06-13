from __future__ import annotations

from typing import Any

from adv_search_flights.data.reference_data import airport_label
from adv_search_flights.domain.models import CombinedResult, OneWayOption, OutputFormat, Segment


def render_results(results: list[CombinedResult], output_format: OutputFormat) -> str | list[dict[str, Any]]:
    sorted_results = sorted(results, key=lambda item: item.total_price_cny)
    rows = [_result_payload(index, item) for index, item in enumerate(sorted_results, 1)]
    if output_format == OutputFormat.json:
        return rows
    if output_format == OutputFormat.text:
        return "\n\n".join(_render_text_item(row) for row in rows)
    return _render_table(rows)


def _render_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| # | 总价 | 去程行程 | 去程每段航线起降时间 | 去程中转次数&停留时间 | 去程价格 | 回程行程 | 回程每段航线起降时间 | 回程中转次数&停留时间 | 回程价格 |",
        "|---:|---:|---|---|---|---:|---|---|---|---:|",
    ]
    for row in rows:
        outbound = row["outbound"]
        inbound = row["inbound"]
        lines.append(
            "| {rank} | ¥{total} | {out_itinerary} | {out_segments} | {out_stops} | ¥{out_price} | "
            "{in_itinerary} | {in_segments} | {in_stops} | ¥{in_price} |".format(
                rank=row["rank"],
                total=row["total_price_cny"],
                out_itinerary=_escape_table(outbound["itinerary"]),
                out_segments=_escape_table("<br>".join(outbound["segment_summaries"])),
                out_stops=_escape_table(outbound["stop_layover_summary"]),
                out_price=outbound["price_cny"],
                in_itinerary=_escape_table(inbound["itinerary"]),
                in_segments=_escape_table("<br>".join(inbound["segment_summaries"])),
                in_stops=_escape_table(inbound["stop_layover_summary"]),
                in_price=inbound["price_cny"],
            )
        )
    return "\n".join(lines)


def _render_text_item(row: dict[str, Any]) -> str:
    outbound = row["outbound"]
    inbound = row["inbound"]
    return "\n".join(
        [
            f"{row['rank']}. 总价：¥{row['total_price_cny']}",
            f"去程行程：{outbound['itinerary']}",
            "去程每段航线起降时间：",
            *_indent(outbound["segment_summaries"]),
            f"去程中转次数&停留时间：{outbound['stop_layover_summary']}",
            f"去程价格：¥{outbound['price_cny']}",
            f"回程行程：{inbound['itinerary']}",
            "回程每段航线起降时间：",
            *_indent(inbound["segment_summaries"]),
            f"回程中转次数&停留时间：{inbound['stop_layover_summary']}",
            f"回程价格：¥{inbound['price_cny']}",
        ]
    )


def _result_payload(index: int, item: CombinedResult) -> dict[str, Any]:
    return {
        "rank": index,
        "total_price_cny": item.total_price_cny,
        "outbound": _one_way_payload(item.outbound),
        "inbound": _one_way_payload(item.inbound),
    }


def _one_way_payload(option: OneWayOption) -> dict[str, Any]:
    layovers = [_layover_payload(item) for item in option.layovers]
    return {
        "itinerary": _one_way_itinerary(option),
        "segments": [_segment_payload(segment) for segment in option.segments],
        "segment_summaries": [_segment_summary(segment) for segment in option.segments],
        "stop_count": option.stops,
        "layovers": layovers,
        "stop_layover_summary": _stop_layover_summary(option),
        "price_cny": option.price_cny,
    }


def _segment_payload(segment: Segment) -> dict[str, Any]:
    return {
        "route": f"{_airport_display(segment.origin_airport, segment.origin_airport_name_zh)} -> {_airport_display(segment.destination_airport, segment.destination_airport_name_zh)}",
        "flight_number": segment.flight_number,
        "airline": segment.airline,
        "airline_zh": segment.airline_zh,
        "aircraft": segment.aircraft,
        "aircraft_zh": segment.aircraft_zh,
        "origin_airport": segment.origin_airport,
        "origin_airport_name_zh": segment.origin_airport_name_zh,
        "departure_time": segment.departure_time.isoformat(),
        "destination_airport": segment.destination_airport,
        "destination_airport_name_zh": segment.destination_airport_name_zh,
        "arrival_time": segment.arrival_time.isoformat(),
    }


def _segment_summary(segment: Segment) -> str:
    aircraft = _aircraft_display(segment)
    airline = _airline_display(segment)
    return (
        f"{segment.flight_number} / {airline} / {aircraft} / "
        f"{_airport_display(segment.origin_airport, segment.origin_airport_name_zh)} "
        f"{segment.departure_time:%Y-%m-%d %H:%M} -> "
        f"{_airport_display(segment.destination_airport, segment.destination_airport_name_zh)} "
        f"{segment.arrival_time:%Y-%m-%d %H:%M}"
    )


def _layover_payload(layover) -> dict[str, Any]:
    return {
        "airport": layover.airport,
        "airport_name_zh": layover.airport_name_zh,
        "duration_hours": layover.hours,
    }


def _stop_layover_summary(option: OneWayOption) -> str:
    if not option.layovers:
        return f"{option.stops} 次中转；无中转停留"
    layovers = "；".join(
        f"{_airport_display(item.airport, item.airport_name_zh)} 停留 {item.hours:g} 小时" for item in option.layovers
    )
    return f"{option.stops} 次中转；{layovers}"


def _one_way_itinerary(option: OneWayOption) -> str:
    labels = [_airport_display(segment.origin_airport, segment.origin_airport_name_zh) for segment in option.segments]
    if option.segments:
        labels.append(_airport_display(option.segments[-1].destination_airport, option.segments[-1].destination_airport_name_zh))
    return " -> ".join(labels) if labels else option.route


def _airport_display(code: str, name_zh: str | None) -> str:
    return airport_label(code, name_zh)


def _aircraft_display(segment: Segment) -> str:
    if segment.aircraft and segment.aircraft_zh:
        return f"{segment.aircraft} {segment.aircraft_zh}"
    return segment.aircraft_zh or segment.aircraft or "未知机型"


def _airline_display(segment: Segment) -> str:
    return segment.airline_zh or segment.airline or "未知航空公司"


def _indent(lines: list[str]) -> list[str]:
    return [f"  - {line}" for line in lines]


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")
