from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, time
from importlib import import_module
from typing import Any

from adv_search_flights.data.reference_data import aircraft_name_zh, airline_name_zh, airport_name_zh, layover_hours
from adv_search_flights.domain.errors import NonRetryableSearchError
from adv_search_flights.domain.models import Layover, OneWayOption, Segment
from adv_search_flights.providers.base import FlightProvider


class SkyscannerProvider(FlightProvider):
    name = "skyscanner"

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
        return await asyncio.to_thread(
            self._search_sync,
            origin,
            destination,
            departure_date,
            adults,
            currency,
            max_stops,
            max_layover_minutes,
        )

    def _search_sync(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        adults: int,
        currency: str,
        max_stops: int,
        max_layover_minutes: int,
    ) -> list[OneWayOption]:
        scanner_cls, cabin_class = _load_skyscanner()
        scanner = scanner_cls(
            locale=os.getenv("SKYSCANNER_LOCALE", "en-US"),
            currency=os.getenv("SKYSCANNER_CURRENCY", "USD" if currency.upper() == "CNY" else currency),
            market=os.getenv("SKYSCANNER_MARKET", "US"),
            retry_delay=int(os.getenv("SKYSCANNER_RETRY_DELAY", "2")),
            max_retries=int(os.getenv("SKYSCANNER_MAX_RETRIES", "6")),
            proxy=os.getenv("SKYSCANNER_PROXY", ""),
            px_authorization=os.getenv("SKYSCANNER_PX_AUTHORIZATION") or None,
            verify=os.getenv("SKYSCANNER_VERIFY", "true").lower() != "false",
        )
        origin_airport = scanner.get_airport_by_code(origin)
        destination_airport = scanner.get_airport_by_code(destination)
        response = scanner.get_flight_prices(
            origin=origin_airport,
            destination=destination_airport,
            depart_date=datetime.combine(departure_date, time.min),
            cabinClass=cabin_class.ECONOMY,
            adults=adults,
        )
        options = self._normalize(response, origin, destination, departure_date)
        return [
            option
            for option in options
            if option.stops <= max_stops
            and option.max_layover_minutes <= max_layover_minutes
            and option.price_cny is not None
        ]

    def _normalize(self, response: Any, origin: str, destination: str, departure_date: date) -> list[OneWayOption]:
        payload = getattr(response, "json", response)
        if not isinstance(payload, dict):
            return []
        indexes = _build_indexes(payload)
        normalized: list[OneWayOption] = []
        for itinerary in _itineraries(payload):
            price = _price_cny(itinerary, payload)
            if price is None:
                continue
            segments = _segments_for_itinerary(itinerary, indexes)
            if not segments:
                continue
            layovers = _layovers_from_segments(segments)
            normalized.append(
                OneWayOption(
                    source=self.name,
                    origin=origin,
                    destination=destination,
                    date=departure_date,
                    route="-".join([segment.origin_airport for segment in segments] + [segments[-1].destination_airport]),
                    segments=segments,
                    layovers=layovers,
                    price_cny=price,
                    raw=itinerary,
                )
            )
        return normalized


def _load_skyscanner() -> tuple[Any, Any]:
    try:
        scanner_cls = import_module("skyscanner").SkyScanner
    except (AttributeError, ModuleNotFoundError):
        try:
            scanner_cls = import_module("skyscanner.skyscanner").SkyScanner
        except ModuleNotFoundError as exc:
            raise NonRetryableSearchError(
                "未安装 irrisolto/skyscanner。请先克隆该仓库并安装其依赖，或把仓库路径加入 PYTHONPATH。"
            ) from exc
    try:
        cabin_class = import_module("skyscanner.types").CabinClass
    except ModuleNotFoundError as exc:
        raise NonRetryableSearchError("已找到 skyscanner，但缺少 skyscanner.types.CabinClass") from exc
    return scanner_cls, cabin_class


def _build_indexes(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexes = {"legs": {}, "segments": {}, "places": {}, "carriers": {}}
    for key, target in (("legs", "legs"), ("segments", "segments"), ("places", "places"), ("carriers", "carriers")):
        for row in _items_from_container(_find_first_key(payload, key)):
            row_id = _first_text(row, "id", "entityId", "entity_id", "placeId", "carrierId")
            if row_id:
                indexes[target][row_id] = row
    return indexes


def _itineraries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _items_from_container(_find_first_key(payload, "itineraries"))


def _find_first_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find_first_key(child, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_first_key(child, key)
            if found is not None:
                return found
    return None


def _items_from_container(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        results = value.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        if isinstance(results, dict):
            return [item for item in results.values() if isinstance(item, dict)]
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _price_cny(itinerary: dict[str, Any], payload: dict[str, Any]) -> int | None:
    price = _first_number(itinerary, "amount", "price", "totalPrice", "rawPrice")
    if price is None:
        for option in itinerary.get("pricingOptions", []) or []:
            if isinstance(option, dict):
                price = _first_number(option, "amount", "price", "totalPrice", "rawPrice")
                if price is None and isinstance(option.get("price"), dict):
                    price = _first_number(option["price"], "amount", "value")
                if price is not None:
                    break
    if price is None:
        return None
    currency = _first_text(itinerary, "currency") or _first_text(payload.get("context", {}) if isinstance(payload.get("context"), dict) else {}, "currency")
    return int(round(price * _currency_to_cny_rate(currency or os.getenv("SKYSCANNER_CURRENCY", "USD"))))


def _segments_for_itinerary(itinerary: dict[str, Any], indexes: dict[str, dict[str, Any]]) -> list[Segment]:
    segments: list[Segment] = []
    leg_refs = itinerary.get("legIds") or itinerary.get("legs") or itinerary.get("leg_ids") or []
    if isinstance(leg_refs, str | dict):
        leg_refs = [leg_refs]
    for leg_ref in leg_refs:
        leg = leg_ref if isinstance(leg_ref, dict) else indexes["legs"].get(str(leg_ref), {})
        segment_refs = leg.get("segmentIds") or leg.get("segments") or []
        if isinstance(segment_refs, str | dict):
            segment_refs = [segment_refs]
        for segment_ref in segment_refs:
            row = segment_ref if isinstance(segment_ref, dict) else indexes["segments"].get(str(segment_ref), {})
            segment = _segment_from_row(row, indexes)
            if segment:
                segments.append(segment)
        if not segment_refs:
            segment = _segment_from_row(leg, indexes)
            if segment:
                segments.append(segment)
    return segments


def _segment_from_row(row: dict[str, Any], indexes: dict[str, dict[str, Any]]) -> Segment | None:
    origin_code = _place_code(row.get("origin") or row.get("originPlace") or row.get("originPlaceId"), indexes)
    destination_code = _place_code(row.get("destination") or row.get("destinationPlace") or row.get("destinationPlaceId"), indexes)
    departure_time = _parse_datetime(row.get("departure") or row.get("departureDateTime") or row.get("departure_time"))
    arrival_time = _parse_datetime(row.get("arrival") or row.get("arrivalDateTime") or row.get("arrival_time"))
    if not origin_code or not destination_code or not departure_time or not arrival_time:
        return None
    carrier_ref = row.get("marketingCarrier") or row.get("marketingCarrierId") or row.get("operatingCarrier") or row.get("operatingCarrierId")
    carrier = carrier_ref if isinstance(carrier_ref, dict) else indexes["carriers"].get(str(carrier_ref), {})
    airline_code = _first_text(carrier, "alternateId", "iata", "code", "displayCode")
    airline_name = _first_text(carrier, "name", "displayName") or airline_code
    flight_number = _first_text(row, "flightNumber", "flight_number", "number")
    if airline_code and flight_number and not flight_number.upper().startswith(airline_code.upper()):
        flight_number = f"{airline_code}{flight_number}"
    aircraft_code = _first_text(row, "aircraft", "aircraftCode", "equipment")
    return Segment(
        flight_number=flight_number,
        airline=airline_name,
        airline_code=airline_code or None,
        airline_zh=airline_name_zh(airline_code or airline_name),
        aircraft=aircraft_code or None,
        aircraft_zh=aircraft_name_zh(aircraft_code),
        origin_airport=origin_code,
        origin_airport_name_zh=airport_name_zh(origin_code),
        destination_airport=destination_code,
        destination_airport_name_zh=airport_name_zh(destination_code),
        departure_time=departure_time,
        arrival_time=arrival_time,
    )


def _place_code(value: Any, indexes: dict[str, dict[str, Any]]) -> str:
    if isinstance(value, dict):
        return _first_text(value, "iata", "skyId", "displayCode", "code", "entityId")
    place = indexes["places"].get(str(value), {})
    return _first_text(place, "iata", "skyId", "displayCode", "code", "entityId")


def _layovers_from_segments(segments: list[Segment]) -> list[Layover]:
    layovers = []
    for prev_segment, next_segment in zip(segments, segments[1:]):
        minutes = max(int((next_segment.departure_time - prev_segment.arrival_time).total_seconds() / 60), 0)
        layovers.append(
            Layover(
                airport=prev_segment.destination_airport,
                airport_name_zh=prev_segment.destination_airport_name_zh,
                minutes=minutes,
                hours=layover_hours(minutes),
            )
        )
    return layovers


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, dict):
        if all(key in value for key in ("year", "month", "day", "hour", "minute")):
            return datetime(int(value["year"]), int(value["month"]), int(value["day"]), int(value["hour"]), int(value["minute"]))
        value = value.get("iso") or value.get("dateTime") or value.get("local")
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if row.get(key):
            return str(row[key])
    return ""


def _first_number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None or isinstance(value, dict | list):
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return None


def _currency_to_cny_rate(currency: str) -> float:
    currency = currency.upper()
    env_key = f"FLIGHT_{currency}_CNY_RATE"
    if os.getenv(env_key):
        return float(os.environ[env_key])
    return {"CNY": 1.0, "USD": 7.2, "EUR": 7.8, "GBP": 9.1, "JPY": 0.05}.get(currency, 1.0)
