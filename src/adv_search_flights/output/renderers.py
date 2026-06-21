from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlencode

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
        "purchase_links": {
            "outbound": _purchase_link(item.outbound),
            "inbound": _purchase_link(item.inbound),
        },
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
        "airlines": _unique_text(segment.airline_zh or segment.airline for segment in option.segments),
        "departure_time": option.segments[0].departure_time.isoformat() if option.segments else None,
        "arrival_time": option.segments[-1].arrival_time.isoformat() if option.segments else None,
        "origin_airport": option.segments[0].origin_airport if option.segments else option.origin,
        "destination_airport": option.segments[-1].destination_airport if option.segments else option.destination,
        "layover_hours_total": round(sum(item.hours for item in option.layovers), 1),
        "layover_cities": _unique_text(_airport_display(item.airport, item.airport_name_zh) for item in option.layovers),
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


def _purchase_link(option: OneWayOption) -> dict[str, str | None]:
    tfs = _tfs_from_raw(option.raw) or _build_tfs(option, include_selected_flights=True)
    booking_url = _booking_url_from_raw(option, tfs)
    if booking_url:
        return {
            "type": "booking",
            "label": "购买页",
            "url": booking_url,
        }

    search_url = _search_url(option, tfs)
    return {
        "type": "search",
        "label": "搜索页链接",
        "url": search_url,
    }


def _booking_url_from_raw(option: OneWayOption, tfs: str | None) -> str | None:
    raw = option.raw
    for key in ("booking_url", "google_flights_booking_url", "booking_page_url", "url"):
        value = str(raw.get(key) or "").strip()
        if _is_google_flights_booking_url(value):
            return value

    tfu = str(raw.get("tfu") or raw.get("tfu_token") or "").strip()
    if tfs and tfu:
        return f"https://www.google.com/travel/flights/booking?{urlencode({'tfs': tfs, 'tfu': tfu, 'curr': 'CNY'})}"

    booking_token = _booking_token_from_option(option) or str(raw.get("booking_token") or "").strip()
    if booking_token.startswith("[") or booking_token.startswith("{"):
        return None
    if tfs and booking_token:
        return f"https://www.google.com/travel/flights/booking?{urlencode({'tfs': tfs, 'tfu': _tfu_from_booking_token(booking_token), 'curr': 'CNY'})}"
    return None


def _is_google_flights_booking_url(value: str) -> bool:
    return value.startswith("https://www.google.com/travel/flights/booking?") and "tfs=" in value and "tfu=" in value


def _search_url(option: OneWayOption, tfs: str | None) -> str:
    search_tfs = tfs or _build_tfs(option, include_selected_flights=False)
    if search_tfs:
        return f"https://www.google.com/travel/flights/search?{urlencode({'tfs': search_tfs, 'curr': 'CNY'})}"
    params = {"q": f"Flights from {option.origin} to {option.destination} on {option.date.isoformat()}", "curr": "CNY"}
    return f"https://www.google.com/travel/flights?{urlencode(params)}"


def _tfs_from_raw(raw: dict[str, Any]) -> str | None:
    return str(raw.get("tfs") or raw.get("tfs_token") or "").strip() or None


def _build_tfs(option: OneWayOption, *, include_selected_flights: bool) -> str | None:
    if not option.segments:
        return None
    origin = option.segments[0].origin_airport or option.origin
    destination = option.segments[-1].destination_airport or option.destination
    inner = _proto_len(2, option.date.isoformat().encode())
    if include_selected_flights:
        for segment in option.segments:
            flight = _selected_flight_message(segment)
            if flight:
                inner += _proto_len(4, flight)
    inner += _airport_token(13, origin)
    inner += _airport_token(14, destination)
    cabin_code = {
        "ECONOMY": 1,
        "PREMIUM_ECONOMY": 2,
        "BUSINESS": 3,
        "FIRST": 4,
    }.get(str(option.raw.get("cabin_class") or "ECONOMY").upper(), 1)
    root = (
        _proto_varint(1, 28)
        + _proto_varint(2, 2)
        + _proto_len(3, inner)
        + _proto_varint(8, 1)
        + _proto_varint(9, cabin_code)
        + _proto_varint(14, 1)
        + _proto_len(16, _proto_varint(1, 18446744073709551615))
        + _proto_varint(19, 2)
    )
    return _b64_url(root)


def _selected_flight_message(segment: Segment) -> bytes | None:
    airline_code = (segment.airline_code or segment.flight_number[:2]).strip().upper()
    flight_number = _flight_number_without_airline_code(segment.flight_number, airline_code)
    if not segment.origin_airport or not segment.destination_airport or not airline_code or not flight_number:
        return None
    return (
        _proto_len(1, segment.origin_airport.encode())
        + _proto_len(2, segment.departure_time.date().isoformat().encode())
        + _proto_len(3, segment.destination_airport.encode())
        + _proto_len(5, airline_code.encode())
        + _proto_len(6, flight_number.encode())
    )


def _flight_number_without_airline_code(value: str, airline_code: str) -> str:
    normalized = "".join(char for char in value.strip().upper() if char.isalnum())
    code = "".join(char for char in airline_code.strip().upper() if char.isalnum())
    if code and normalized.startswith(code):
        normalized = normalized[len(code):]
    return normalized


GOOGLE_PLACE_IDS = {
    "SHA": "/m/06wjf",
    "PVG": "/m/06wjf",
    "SIN": "/m/06t2t",
}


def _airport_token(field: int, code: str) -> bytes:
    normalized = code.strip().upper()
    place_id = GOOGLE_PLACE_IDS.get(normalized)
    token_type = 3 if place_id else 1
    token = place_id or normalized
    return _proto_len(field, _proto_varint(1, token_type) + _proto_len(2, token.encode()))


def _tfu_from_booking_token(token: str) -> str:
    normalized = token + "=" * ((4 - len(token) % 4) % 4)
    payload = _proto_len(1, normalized.encode()) + _proto_len(2, _proto_varint(1, 0)) + _proto_len(4, b"")
    return _b64_url(payload)


def _booking_token_from_option(option: OneWayOption) -> str | None:
    session_id = str(option.raw.get("session_id") or "").strip()
    flight_numbers = [segment.flight_number.strip().upper() for segment in option.segments if segment.flight_number.strip()]
    if not session_id or not flight_numbers or option.price_cny is None:
        return None
    currency = str(option.raw.get("currency") or "CNY").upper()
    price = int(option.price_cny)
    price_message = _proto_varint(1, price) + _proto_varint(2, 0) + _proto_len(3, currency.encode())
    payload = (
        _proto_len(1, session_id.encode())
        + _proto_len(2, "|".join(flight_numbers).encode())
        + _proto_len(3, price_message)
        + _proto_varint(7, 28)
    )
    emissions = int(option.raw.get("emissions_g") or 0)
    if emissions > 0:
        payload += _proto_varint(14, emissions)
    return base64.b64encode(payload).decode("ascii").rstrip("=")


def _proto_varint(field: int, value: int) -> bytes:
    return _proto_tag(field, 0) + _varint(value)


def _proto_len(field: int, payload: bytes) -> bytes:
    return _proto_tag(field, 2) + _varint(len(payload)) + payload


def _proto_tag(field: int, wire_type: int) -> bytes:
    return _varint((field << 3) | wire_type)


def _varint(value: int) -> bytes:
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(output)


def _b64_url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _airport_display(code: str, name_zh: str | None) -> str:
    return airport_label(code, name_zh)


def _unique_text(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


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
