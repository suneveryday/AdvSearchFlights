from __future__ import annotations

from datetime import date

from adv_search_flights.providers.fli import FliProvider


def test_fli_real_schema_is_normalized() -> None:
    payload = {
        "success": True,
        "currency": "USD",
        "flights": [
            {
                "duration": 632,
                "stops": 1,
                "price": 347.0,
                "currency": "USD",
                "legs": [
                    {
                        "departure_airport": {"code": "JFK", "name": "John F Kennedy International Airport"},
                        "arrival_airport": {"code": "CLT", "name": "Charlotte/Douglas International Airport"},
                        "departure_time": "2026-06-20T06:30:00",
                        "arrival_time": "2026-06-20T08:34:00",
                        "airline": {"code": "AA", "name": "American Airlines"},
                        "flight_number": "2643",
                        "aircraft": "Boeing 737MAX 8 Passenger",
                    },
                    {
                        "departure_airport": {"code": "CLT", "name": "Charlotte/Douglas International Airport"},
                        "arrival_airport": {"code": "LAX", "name": "Los Angeles International Airport"},
                        "departure_time": "2026-06-20T11:56:00",
                        "arrival_time": "2026-06-20T14:02:00",
                        "airline": {"code": "AA", "name": "American Airlines"},
                        "flight_number": "1213",
                        "aircraft": "Airbus A321neo",
                    },
                ],
                "layovers": [
                    {"airport": {"code": "CLT", "name": "Charlotte/Douglas International Airport"}, "duration": 202}
                ],
            }
        ],
    }

    rows = FliProvider()._normalize(payload, "JFK", "LAX", date(2026, 6, 20))

    assert len(rows) == 1
    assert rows[0].price_cny == 2498
    assert rows[0].segments[0].flight_number == "AA2643"
    assert rows[0].segments[0].airline_zh == "美国航空"
    assert rows[0].segments[0].aircraft_zh == "波音 737MAX 8 客机"
    assert rows[0].layovers[0].airport == "CLT"
    assert rows[0].layovers[0].hours == 3.4
