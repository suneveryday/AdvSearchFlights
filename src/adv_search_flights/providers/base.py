from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from adv_search_flights.domain.models import OneWayOption


class FlightProvider(ABC):
    name: str
    rate_limited: bool = True

    @abstractmethod
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
        """Return normalized one-way flight options."""

