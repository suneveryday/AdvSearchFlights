from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date, datetime
from typing import Any

from adv_search_flights.data.reference_data import aircraft_name_zh, airline_name_zh, airport_name_zh, layover_hours
from adv_search_flights.diagnostics import log_event
from adv_search_flights.domain.models import Layover, OneWayOption, Segment
from adv_search_flights.network import resolve_fli_cli_executable
from adv_search_flights.providers.base import FlightProvider


class FliProvider(FlightProvider):
    name = "fli"

    async def search_one_way(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        adults: int,
        currency: str,
        max_stops: int,
        max_layover_minutes: int,
        cabin_class: str = "ECONOMY",
    ) -> list[OneWayOption]:
        query_currency = os.getenv("FLI_QUERY_CURRENCY") or currency.upper()
        language = os.getenv("FLI_LANGUAGE", "zh-CN")
        country = os.getenv("FLI_COUNTRY", "SG")
        if not os.getenv("ADV_SEARCH_FLIGHTS_USE_FLI_CLI"):
            try:
                log_event(
                    "fli.direct.started",
                    origin=origin,
                    destination=destination,
                    date=departure_date.isoformat(),
                    currency=query_currency,
                    language=language,
                    country=country,
                    cabin_class=cabin_class,
                    http_tunnel_configured=bool(os.getenv("https_proxy") or os.getenv("HTTPS_PROXY")),
                    socks_tunnel_configured=bool(os.getenv("all_proxy") or os.getenv("ALL_PROXY")),
                )
                return await asyncio.to_thread(
                    _search_with_fli_api,
                    origin,
                    destination,
                    departure_date,
                    adults,
                    query_currency,
                    language,
                    country,
                    cabin_class,
                )
            except Exception as exc:
                log_event("fli.direct.failed", level=40, origin=origin, destination=destination, date=departure_date.isoformat(), error=exc)
                if not os.getenv("ADV_SEARCH_FLIGHTS_FALLBACK_TO_CLI_ON_DIRECT_ERROR"):
                    raise RuntimeError(str(exc) or "Google Flights 查询失败") from exc

        fli_executable = resolve_fli_cli_executable()
        if fli_executable is None:
            raise RuntimeError("未找到 fli CLI，且直接查询不可用")

        proc = await asyncio.create_subprocess_exec(
            fli_executable,
            "flights",
            origin,
            destination,
            departure_date.isoformat(),
            "--currency",
            query_currency,
            "--language",
            language,
            "--country",
            country,
            "--format",
            "json",
            "--class",
            cabin_class,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timeout_seconds = int(os.getenv("FLI_TIMEOUT_SECONDS", "15"))
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.CancelledError:
            proc.kill()
            await proc.communicate()
            raise
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"Google Flights 查询超过 {timeout_seconds} 秒，已自动中止") from exc

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(_error_message(stdout_text, stderr_text))
        payload = json.loads(stdout_text)
        if isinstance(payload, dict) and payload.get("success") is False:
            raise RuntimeError(_error_message(stdout_text, stderr_text))
        normalized = self._normalize(payload, origin, destination, departure_date)
        if normalized or not _should_use_direct_fli_fallback(payload):
            return normalized
        return await asyncio.to_thread(
            _search_with_fli_api,
            origin,
            destination,
            departure_date,
            adults,
            query_currency,
            language,
            country,
            cabin_class,
        )

    def _normalize(self, payload: Any, origin: str, destination: str, departure_date: date) -> list[OneWayOption]:
        items = payload.get("flights") or payload.get("results") or payload
        if not isinstance(items, list):
            return []
        normalized: list[OneWayOption] = []
        for item in items:
            price_cny = _parse_price(item.get("price") or item.get("price_cny") or item.get("total_price"), item.get("currency") or payload.get("currency"))
            segments = [_segment_from_mapping(row) for row in item.get("segments") or item.get("flights") or item.get("legs") or []]
            segments = [segment for segment in segments if segment is not None]
            layovers = [_layover_from_mapping(row) for row in item.get("layovers", []) if isinstance(row, dict)]
            if price_cny is None or not segments:
                continue
            normalized.append(
                OneWayOption(
                    source=self.name,
                    origin=origin,
                    destination=destination,
                    date=departure_date,
                    route="-".join([segment.origin_airport for segment in segments] + [segments[-1].destination_airport]),
                    segments=segments,
                    layovers=layovers,
                    price_cny=price_cny,
                    raw=item,
                )
            )
        return normalized


def _parse_price(value: Any, currency: Any = "CNY") -> int | None:
    if value is None:
        return None
    amount = float(value) if isinstance(value, int | float) else float("".join(char for char in str(value) if char.isdigit() or char == "."))
    if str(currency or "CNY").upper() == "CNY":
        return int(round(amount))
    return int(round(amount * _currency_to_cny_rate(str(currency))))


def _should_use_direct_fli_fallback(payload: Any) -> bool:
    if os.getenv("ADV_SEARCH_FLIGHTS_DISABLE_FLI_DIRECT_FALLBACK"):
        return False
    return isinstance(payload, dict) and payload.get("success") is True and int(payload.get("count") or 0) == 0


def _search_with_fli_api(
    origin: str,
    destination: str,
    departure_date: date,
    adults: int,
    currency: str,
    language: str,
    country: str,
    cabin_class: str = "ECONOMY",
) -> list[OneWayOption]:
    from fli.core import build_flight_segments, parse_cabin_class, parse_max_stops, parse_sort_by, resolve_airport
    from fli.models import FlightSearchFilters, PassengerInfo
    from fli.search import SearchFlights
    from fli.search._decoders import parse_flight_row
    from fli.search._urls import with_locale_params
    from fli.search._wire import parse_first_wrb_payload

    origin_airport = resolve_airport(origin)
    destination_airport = resolve_airport(destination)
    segments, trip_type = build_flight_segments(
        origin=origin_airport,
        destination=destination_airport,
        departure_date=departure_date.isoformat(),
        return_date=None,
        time_restrictions=None,
    )
    filters = FlightSearchFilters(
        trip_type=trip_type,
        passenger_info=PassengerInfo(adults=adults),
        flight_segments=segments,
        stops=parse_max_stops("ANY"),
        seat_type=parse_cabin_class(cabin_class),
        sort_by=parse_sort_by("CHEAPEST"),
        show_all_results=True,
    )
    client = SearchFlights()
    url = with_locale_params(client.BASE_URL, currency, language, country)
    response = client.client.post(
        url=url,
        data=f"f.req={filters.encode()}",
        impersonate="chrome",
        allow_redirects=True,
        timeout=int(os.getenv("FLI_TIMEOUT_SECONDS", "15")),
    )
    log_event(
        "fli.http.completed",
        origin=origin,
        destination=destination,
        date=departure_date.isoformat(),
        status_code=response.status_code,
        response_bytes=len(response.text),
        has_error_response="ErrorResponse" in response.text,
        error_response_code=_diagnostic_error_response_code(response.text),
    )
    response.raise_for_status()
    inner = parse_first_wrb_payload(response.text)
    if not isinstance(inner, list):
        if "ErrorResponse" in response.text:
            raise RuntimeError("Google Flights 暂时拒绝了本次查询，请稍后重试或降低查询频率")
        return []

    try:
        client._capture_session_id(inner)
    except AttributeError:
        pass
    session_id = getattr(client, "_last_session_id", None)

    options: list[OneWayOption] = []
    seen: set[tuple[Any, ...]] = set()
    raw_rows = _iter_flight_rows(inner)
    parse_failures = 0
    for raw_row in raw_rows:
        try:
            flight = parse_flight_row(raw_row)
            option = _option_from_fli_flight(
                flight,
                origin,
                destination,
                departure_date,
                raw_row,
                session_id=session_id,
                cabin_class=cabin_class,
            )
        except Exception:
            parse_failures += 1
            continue
        if option.price_cny is None or not option.segments:
            continue
        key = (
            option.price_cny,
            tuple((segment.flight_number, segment.origin_airport, segment.destination_airport, segment.departure_time.isoformat()) for segment in option.segments),
        )
        if key in seen:
            continue
        seen.add(key)
        options.append(option)
    log_event("fli.parse.completed", origin=origin, destination=destination, date=departure_date.isoformat(), raw_row_count=len(raw_rows), parse_failure_count=parse_failures, option_count=len(options))
    return options


def _iter_flight_rows(inner: list[Any]) -> list[Any]:
    rows: list[Any] = []
    for value in inner:
        if not isinstance(value, list) or not value:
            continue
        first = value[0]
        if not isinstance(first, list):
            continue
        for item in first:
            if isinstance(item, list):
                rows.append(item)
    return rows


def _diagnostic_error_response_code(response_text: str) -> int | None:
    match = re.search(
        r'\[(\d+),null,\[\["type\.googleapis\.com/travel\.frontend\.flights\.ErrorResponse"',
        response_text,
    )
    return int(match.group(1)) if match else None


def _option_from_fli_flight(
    flight: Any,
    origin: str,
    destination: str,
    departure_date: date,
    raw_row: Any,
    *,
    session_id: str | None = None,
    cabin_class: str = "ECONOMY",
) -> OneWayOption:
    segments = [_segment_from_fli_leg(leg) for leg in getattr(flight, "legs", [])]
    segments = [segment for segment in segments if segment is not None]
    layovers = [_layover_from_fli_layover(row) for row in getattr(flight, "layovers", []) or []]
    price_cny = _parse_price(getattr(flight, "price", None), getattr(flight, "currency", None) or "CNY")
    return OneWayOption(
        source=FliProvider.name,
        origin=origin,
        destination=destination,
        date=departure_date,
        route="-".join([segment.origin_airport for segment in segments] + [segments[-1].destination_airport]) if segments else f"{origin}-{destination}",
        segments=segments,
        layovers=layovers,
        price_cny=price_cny,
        raw={
            "provider": "fli_direct",
            "booking_token": getattr(flight, "booking_token", None),
            "currency": getattr(flight, "currency", None),
            "session_id": session_id,
            "emissions_g": getattr(flight, "co2_emissions_g", None),
            "cabin_class": cabin_class,
            "raw_row": raw_row,
        },
    )


def _segment_from_fli_leg(leg: Any) -> Segment | None:
    try:
        airline = getattr(leg, "airline", None)
        airline_code = _enum_code(airline)
        airline_name = _enum_value(airline) or airline_code or ""
        flight_number = str(getattr(leg, "flight_number", "") or "")
        if airline_code and flight_number and not flight_number.upper().startswith(airline_code.upper()):
            flight_number = f"{airline_code}{flight_number}"
        origin_airport = _enum_code(getattr(leg, "departure_airport", None))
        destination_airport = _enum_code(getattr(leg, "arrival_airport", None))
        return Segment(
            flight_number=flight_number,
            airline=airline_name,
            airline_code=airline_code,
            airline_zh=airline_name_zh(airline_code or airline_name),
            aircraft=str(getattr(leg, "aircraft", "") or ""),
            aircraft_zh=aircraft_name_zh(str(getattr(leg, "aircraft", "") or "")),
            origin_airport=origin_airport,
            origin_airport_name_zh=airport_name_zh(origin_airport),
            destination_airport=destination_airport,
            destination_airport_name_zh=airport_name_zh(destination_airport),
            departure_time=getattr(leg, "departure_datetime"),
            arrival_time=getattr(leg, "arrival_datetime"),
        )
    except Exception:
        return None


def _layover_from_fli_layover(row: Any) -> Layover:
    airport = _enum_code(getattr(row, "airport", None))
    minutes = int(getattr(row, "duration", 0) or 0)
    return Layover(airport=airport, airport_name_zh=airport_name_zh(airport), minutes=minutes, hours=layover_hours(minutes))


def _enum_code(value: Any) -> str:
    return str(getattr(value, "name", "") or "").removeprefix("_")


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", "") or "")


def _currency_to_cny_rate(currency: str) -> float:
    env_key = f"FLIGHT_{currency.upper()}_CNY_RATE"
    if os.getenv(env_key):
        return float(os.environ[env_key])
    return {"USD": 7.2, "EUR": 7.8, "GBP": 9.1, "JPY": 0.05}.get(currency.upper(), 1.0)


def _segment_from_mapping(row: dict[str, Any]) -> Segment | None:
    try:
        airline = row.get("airline")
        airline_code = _nested_text(airline, "code") or _first_text(row, "airline_code", "carrier_code", "carrier")
        airline_name = _nested_text(airline, "name") or str(row.get("airline") or row.get("carrier") or "")
        aircraft_code = _first_text(row, "aircraft", "aircraft_code", "equipment", "aircraft_type")
        origin_airport = _airport_code(row.get("origin_airport") or row.get("departure_airport") or row.get("origin") or row.get("from"))
        destination_airport = _airport_code(row.get("destination_airport") or row.get("arrival_airport") or row.get("destination") or row.get("to"))
        flight_number = str(row.get("flight_number") or row.get("flight") or row.get("number") or "")
        if airline_code and flight_number and not flight_number.upper().startswith(airline_code.upper()):
            flight_number = f"{airline_code}{flight_number}"
        return Segment(
            flight_number=flight_number,
            airline=airline_name,
            airline_code=airline_code,
            airline_zh=airline_name_zh(airline_code or airline_name),
            aircraft=aircraft_code,
            aircraft_zh=aircraft_name_zh(aircraft_code),
            origin_airport=origin_airport,
            origin_airport_name_zh=airport_name_zh(origin_airport),
            destination_airport=destination_airport,
            destination_airport_name_zh=airport_name_zh(destination_airport),
            departure_time=_parse_datetime(row.get("departure_time") or row.get("departure")),
            arrival_time=_parse_datetime(row.get("arrival_time") or row.get("arrival")),
        )
    except Exception:
        return None


def _layover_from_mapping(row: dict[str, Any]) -> Layover:
    airport = _airport_code(row.get("airport") or row.get("airport_code") or row.get("iata"))
    minutes = int(row.get("minutes") or row.get("duration_minutes") or row.get("duration") or 0)
    return Layover(airport=airport, airport_name_zh=airport_name_zh(airport), minutes=minutes, hours=layover_hours(minutes))


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if row.get(key):
            return str(row[key])
    return ""


def _nested_text(value: Any, key: str) -> str:
    return str(value[key]) if isinstance(value, dict) and value.get(key) else ""


def _airport_code(value: Any) -> str:
    return str(value.get("code") or value.get("iata") or "") if isinstance(value, dict) else str(value or "")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _error_message(stdout_text: str, stderr_text: str) -> str:
    for text in (stdout_text, stderr_text):
        if not text.strip():
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text.strip()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or error)
        return str(payload)
    return "fli 查询失败，但没有返回错误详情"
