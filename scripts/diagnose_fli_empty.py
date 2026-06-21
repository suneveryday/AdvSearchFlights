from __future__ import annotations

from fli.core import (
    build_flight_segments,
    parse_cabin_class,
    parse_max_stops,
    parse_sort_by,
    resolve_airport,
)
from fli.models import FlightSearchFilters, PassengerInfo
from fli.search import SearchFlights
from fli.search._decoders import parse_flight_row
from fli.search._urls import with_locale_params
from fli.search._wire import parse_first_wrb_payload


def main() -> None:
    origin = resolve_airport("PVG")
    destination = resolve_airport("MEL")
    segments, trip_type = build_flight_segments(
        origin=origin,
        destination=destination,
        departure_date="2026-09-29",
        return_date=None,
        time_restrictions=None,
    )
    filters = FlightSearchFilters(
        trip_type=trip_type,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=segments,
        stops=parse_max_stops("ANY"),
        seat_type=parse_cabin_class("ECONOMY"),
        sort_by=parse_sort_by("CHEAPEST"),
        show_all_results=True,
    )
    client = SearchFlights()
    url = with_locale_params(client.BASE_URL, "CNY", "zh-CN", "SG")
    response = client.client.post(
        url=url,
        data=f"f.req={filters.encode()}",
        impersonate="chrome",
        allow_redirects=True,
    )
    inner = parse_first_wrb_payload(response.text)
    print("status", response.status_code)
    print("response_len", len(response.text))
    print("response_prefix", repr(response.text[:300]))
    print("inner_len", len(inner) if isinstance(inner, list) else None)

    raw_rows = []
    if isinstance(inner, list):
        for idx in (2, 3):
            value = inner[idx] if len(inner) > idx else None
            if isinstance(value, list) and value and isinstance(value[0], list):
                raw_rows.extend(value[0])
            print(
                "idx",
                idx,
                "type",
                type(value).__name__,
                "first_type",
                type(value[0]).__name__ if isinstance(value, list) and value else None,
                "count",
                len(value[0]) if isinstance(value, list) and value and isinstance(value[0], list) else None,
            )
    print("raw_count", len(raw_rows))

    parsed = []
    for row_index, row in enumerate(raw_rows[:10]):
        try:
            flight = parse_flight_row(row)
        except Exception as exc:  # noqa: BLE001 - diagnostic script
            print("parse_error", row_index, type(exc).__name__, str(exc))
            continue
        parsed.append(flight)
        legs = [
            (
                leg.airline.name.removeprefix("_") if leg.airline else None,
                leg.flight_number,
                leg.departure_airport.name,
                leg.arrival_airport.name,
            )
            for leg in flight.legs
        ]
        print("parsed", row_index, "price", flight.price, "currency", flight.currency, "legs", legs)
    print("parsed_count_first_10", len(parsed))


if __name__ == "__main__":
    main()
