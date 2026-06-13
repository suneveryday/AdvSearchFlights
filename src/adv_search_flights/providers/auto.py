from __future__ import annotations

from datetime import date

from adv_search_flights.domain.models import OneWayOption
from adv_search_flights.providers.base import FlightProvider
from adv_search_flights.providers.fli import FliProvider
from adv_search_flights.providers.skyscanner import SkyscannerProvider


class AutoProvider(FlightProvider):
    name = "auto"

    def __init__(self) -> None:
        self.primary = FliProvider()
        self.fallback = SkyscannerProvider()

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
        primary_error: Exception | None = None
        try:
            primary_results = await self.primary.search_one_way(
                origin,
                destination,
                departure_date,
                adults,
                currency,
                max_stops,
                max_layover_minutes,
            )
            if primary_results:
                return primary_results
        except Exception as exc:  # noqa: BLE001
            primary_error = exc

        try:
            return await self.fallback.search_one_way(
                origin,
                destination,
                departure_date,
                adults,
                currency,
                max_stops,
                max_layover_minutes,
            )
        except Exception as fallback_error:  # noqa: BLE001
            if primary_error is not None:
                raise RuntimeError(f"Google Flights 失败：{primary_error}；Skyscanner 备用失败：{fallback_error}") from fallback_error
            return []
