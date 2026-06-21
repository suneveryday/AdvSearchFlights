from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from datetime import date
from datetime import datetime

from adv_search_flights.providers.fli import FliProvider, _diagnostic_error_response_code, _option_from_fli_flight


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
                "booking_token": "token+with/slash",
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
    assert rows[0].raw["booking_token"] == "token+with/slash"


def test_fli_provider_uses_resolved_executable(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            payload = {
                "success": True,
                "currency": "USD",
                "flights": [
                    {
                        "price": 100,
                        "currency": "USD",
                        "legs": [
                            {
                                "departure_airport": {"code": "PVG"},
                                "arrival_airport": {"code": "MEL"},
                                "departure_time": "2026-09-29T10:00:00",
                                "arrival_time": "2026-09-29T22:00:00",
                                "airline": {"code": "MU", "name": "China Eastern"},
                                "flight_number": "737",
                            }
                        ],
                    }
                ],
            }
            return json.dumps(payload).encode(), b""

    async def fake_create_subprocess_exec(executable, *args, **kwargs):
        captured["executable"] = executable
        captured["args"] = list(args)
        return FakeProcess()

    monkeypatch.setattr("adv_search_flights.providers.fli.resolve_fli_cli_executable", lambda: "/tmp/project/.venv/bin/fli")
    monkeypatch.setattr("adv_search_flights.providers.fli.asyncio.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_USE_FLI_CLI", "1")

    rows = asyncio.run(FliProvider().search_one_way("PVG", "MEL", date(2026, 9, 29), 1, "CNY", 1, 600, cabin_class="BUSINESS"))

    assert captured["executable"] == "/tmp/project/.venv/bin/fli"
    assert "--class" in captured["args"]
    assert captured["args"][captured["args"].index("--class") + 1] == "BUSINESS"
    assert len(rows) == 1


def test_direct_fli_does_not_require_a_separate_cli(monkeypatch) -> None:
    called = False

    def fake_direct_search(*args, **kwargs):
        nonlocal called
        called = True
        return []

    def fail_if_cli_is_resolved():
        raise AssertionError("direct fli path must not resolve the external CLI")

    monkeypatch.delenv("ADV_SEARCH_FLIGHTS_USE_FLI_CLI", raising=False)
    monkeypatch.setattr("adv_search_flights.providers.fli._search_with_fli_api", fake_direct_search)
    monkeypatch.setattr("adv_search_flights.providers.fli.resolve_fli_cli_executable", fail_if_cli_is_resolved)

    rows = asyncio.run(
        FliProvider().search_one_way(
            "PVG",
            "MEL",
            date(2026, 9, 29),
            1,
            "CNY",
            1,
            600,
        )
    )

    assert called is True
    assert rows == []


def test_error_response_code_is_diagnostic_only() -> None:
    payload = '["wrb.fr",null,null,null,null,[13,null,[["type.googleapis.com/travel.frontend.flights.ErrorResponse",[]]]]]'
    assert _diagnostic_error_response_code(payload) == 13
    assert _diagnostic_error_response_code("ErrorResponse") is None


def test_direct_fli_result_is_converted_to_one_way_option() -> None:
    flight = SimpleNamespace(
        price=3620.0,
        currency="CNY",
        booking_token="booking-token",
        co2_emissions_g=53570,
        legs=[
            SimpleNamespace(
                airline=SimpleNamespace(name="_5J", value="Cebu Pacific"),
                flight_number="679",
                departure_airport=SimpleNamespace(name="PVG"),
                arrival_airport=SimpleNamespace(name="MNL"),
                departure_datetime=datetime(2026, 9, 29, 1, 35),
                arrival_datetime=datetime(2026, 9, 29, 5, 35),
                aircraft="Airbus A320neo",
            ),
            SimpleNamespace(
                airline=SimpleNamespace(name="_5J", value="Cebu Pacific"),
                flight_number="49",
                departure_airport=SimpleNamespace(name="MNL"),
                arrival_airport=SimpleNamespace(name="MEL"),
                departure_datetime=datetime(2026, 9, 29, 12, 55),
                arrival_datetime=datetime(2026, 9, 29, 23, 10),
                aircraft="Airbus A330-900neo",
            ),
        ],
        layovers=[SimpleNamespace(airport=SimpleNamespace(name="MNL"), duration=440)],
    )

    option = _option_from_fli_flight(
        flight,
        "PVG",
        "MEL",
        date(2026, 9, 29),
        raw_row=["raw"],
        session_id="session-id",
        cabin_class="BUSINESS",
    )

    assert option.price_cny == 3620
    assert option.route == "PVG-MNL-MEL"
    assert [segment.flight_number for segment in option.segments] == ["5J679", "5J49"]
    assert option.layovers[0].airport == "MNL"
    assert option.raw["booking_token"] == "booking-token"
    assert option.raw["session_id"] == "session-id"
    assert option.raw["emissions_g"] == 53570
    assert option.raw["cabin_class"] == "BUSINESS"
