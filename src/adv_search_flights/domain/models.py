from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class OutputFormat(str, Enum):
    table = "table"
    text = "text"
    json = "json"


class ProviderName(str, Enum):
    auto = "auto"
    mock = "mock"
    fli = "fli"
    skyscanner = "skyscanner"


class SearchRequest(BaseModel):
    origin: str = Field(
        min_length=2,
        description="Departure city or airport. Accepts Chinese city names or IATA airport/city codes, for example 上海, SHA, PVG.",
    )
    destinations: list[str] = Field(
        min_length=1,
        description="One to five candidate destination cities or airports. One candidate creates a round trip; two different candidates create open-jaw routes.",
    )
    departure: date = Field(description="Outbound departure date in YYYY-MM-DD format.")
    return_date: date = Field(description="Inbound return date in YYYY-MM-DD format.")
    output_format: OutputFormat = Field(default=OutputFormat.table, description="Output renderer: table, text, or json.")
    provider: ProviderName = Field(default=ProviderName.auto, description="Data source: auto, fli, skyscanner, or mock.")
    max_stops: int = Field(default=1, ge=0, le=3, description="Maximum stops allowed for each one-way option.")
    max_layover_hours: float = Field(default=10.0, ge=0, description="Maximum layover duration per connection, in hours.")
    adults: int = Field(default=1, ge=1, le=9, description="Number of adult passengers.")
    currency: str = Field(default="CNY", min_length=3, max_length=3, description="Output currency. CNY is used for sorting and display.")
    limit: int | None = Field(default=None, ge=1, description="Maximum number of combined open-jaw results to return.")

    @property
    def max_layover_minutes(self) -> int:
        return int(round(self.max_layover_hours * 60))

    @field_validator("origin")
    @classmethod
    def normalize_origin(cls, value: str) -> str:
        return value.strip()

    @field_validator("destinations")
    @classmethod
    def unique_destinations(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in value:
            key = item.strip().upper()
            if key and key not in seen:
                seen.add(key)
                result.append(item.strip())
        if len(result) < 1:
            raise ValueError("destinations 至少需要 1 个候选目的地")
        if len(result) > 5:
            raise ValueError("destinations 最多支持 5 个不同的候选目的地")
        return result

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


class Segment(BaseModel):
    flight_number: str
    airline: str
    airline_code: str | None = None
    airline_zh: str | None = None
    aircraft: str | None = None
    aircraft_zh: str | None = None
    origin_airport: str
    origin_airport_name_zh: str | None = None
    destination_airport: str
    destination_airport_name_zh: str | None = None
    departure_time: datetime
    arrival_time: datetime


class Layover(BaseModel):
    airport: str
    airport_name_zh: str | None = None
    minutes: int
    hours: float


class OneWayOption(BaseModel):
    source: str
    origin: str
    destination: str
    date: date
    route: str
    segments: list[Segment]
    layovers: list[Layover] = Field(default_factory=list)
    price_cny: int | None
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def stops(self) -> int:
        return max(0, len(self.segments) - 1)

    @property
    def max_layover_minutes(self) -> int:
        if not self.layovers:
            return 0
        return max(item.minutes for item in self.layovers)


class CombinedResult(BaseModel):
    total_price_cny: int
    outbound_destination: str
    inbound_origin: str
    outbound: OneWayOption
    inbound: OneWayOption


class SearchResponse(BaseModel):
    query: SearchRequest
    provider: ProviderName
    origin_iata: str
    origin_iatas: list[str] = Field(default_factory=list)
    origin_name_zh: str | None = None
    origin_names_zh: dict[str, str | None] = Field(default_factory=dict)
    destination_iatas: list[str]
    destination_airport_options: dict[str, list[str]] = Field(default_factory=dict)
    destination_names_zh: dict[str, str | None] = Field(default_factory=dict)
    result_count: int
    results: list[CombinedResult]
    rendered: str | list[dict[str, Any]] | None = None
    warnings: list[str] = Field(default_factory=list)
