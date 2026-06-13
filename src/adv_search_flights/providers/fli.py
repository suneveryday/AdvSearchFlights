from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import date, datetime
from typing import Any

from adv_search_flights.data.reference_data import aircraft_name_zh, airline_name_zh, airport_name_zh, layover_hours
from adv_search_flights.domain.models import Layover, OneWayOption, Segment
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
    ) -> list[OneWayOption]:
        if shutil.which("fli") is None:
            raise RuntimeError("未找到 fli CLI，请先安装 flights 包")

        query_currency = os.getenv("FLI_QUERY_CURRENCY") or ("USD" if currency.upper() == "CNY" else currency)
        proc = await asyncio.create_subprocess_exec(
            "fli",
            "flights",
            origin,
            destination,
            departure_date.isoformat(),
            "--currency",
            query_currency,
            "--language",
            os.getenv("FLI_LANGUAGE", "en-US"),
            "--country",
            os.getenv("FLI_COUNTRY", "US"),
            "--format",
            "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timeout_seconds = int(os.getenv("FLI_TIMEOUT_SECONDS", "15"))
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
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
        return self._normalize(payload, origin, destination, departure_date)

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

