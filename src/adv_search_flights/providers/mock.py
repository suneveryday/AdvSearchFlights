from __future__ import annotations

from datetime import date, datetime, timedelta

from adv_search_flights.data.reference_data import aircraft_name_zh, airline_name_zh, airport_name_zh, layover_hours
from adv_search_flights.domain.models import Layover, OneWayOption, Segment
from adv_search_flights.providers.base import FlightProvider


class MockProvider(FlightProvider):
    name = "mock"
    rate_limited = False

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
        base = datetime.combine(departure_date, datetime.min.time()).replace(hour=9)
        options = [
            OneWayOption(
                source=self.name,
                origin=origin,
                destination=destination,
                date=departure_date,
                route=f"{origin}-{destination}",
                segments=[
                    Segment(
                        flight_number=f"MU{abs(hash(origin + destination)) % 700 + 100}",
                        airline="China Eastern Airlines",
                        airline_code="MU",
                        airline_zh=airline_name_zh("MU"),
                        aircraft="789",
                        aircraft_zh=aircraft_name_zh("789"),
                        origin_airport=origin,
                        origin_airport_name_zh=airport_name_zh(origin),
                        destination_airport=destination,
                        destination_airport_name_zh=airport_name_zh(destination),
                        departure_time=base,
                        arrival_time=base + timedelta(hours=10, minutes=20),
                    )
                ],
                price_cny=self._price(origin, destination, 0),
            ),
            OneWayOption(
                source=self.name,
                origin=origin,
                destination=destination,
                date=departure_date,
                route=f"{origin}-SIN-{destination}",
                segments=[
                    Segment(
                        flight_number=f"SQ{abs(hash(origin)) % 800 + 100}",
                        airline="Singapore Airlines",
                        airline_code="SQ",
                        airline_zh=airline_name_zh("SQ"),
                        aircraft="359",
                        aircraft_zh=aircraft_name_zh("359"),
                        origin_airport=origin,
                        origin_airport_name_zh=airport_name_zh(origin),
                        destination_airport="SIN",
                        destination_airport_name_zh=airport_name_zh("SIN"),
                        departure_time=base.replace(hour=12),
                        arrival_time=base.replace(hour=18),
                    ),
                    Segment(
                        flight_number=f"SQ{abs(hash(destination)) % 800 + 100}",
                        airline="Singapore Airlines",
                        airline_code="SQ",
                        airline_zh=airline_name_zh("SQ"),
                        aircraft="359",
                        aircraft_zh=aircraft_name_zh("359"),
                        origin_airport="SIN",
                        origin_airport_name_zh=airport_name_zh("SIN"),
                        destination_airport=destination,
                        destination_airport_name_zh=airport_name_zh(destination),
                        departure_time=base.replace(hour=22),
                        arrival_time=base.replace(hour=7) + timedelta(days=1),
                    ),
                ],
                layovers=[Layover(airport="SIN", airport_name_zh=airport_name_zh("SIN"), minutes=240, hours=layover_hours(240))],
                price_cny=self._price(origin, destination, 1),
            ),
        ]
        return [
            option
            for option in options
            if option.stops <= max_stops
            and option.max_layover_minutes <= max_layover_minutes
            and option.price_cny is not None
        ]

    def _price(self, origin: str, destination: str, stops: int) -> int:
        seed = sum(ord(char) for char in origin + destination)
        return 1800 + (seed % 2400) + stops * 450

