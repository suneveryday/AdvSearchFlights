from __future__ import annotations

from adv_search_flights.data.reference_data import AIRPORT_NAME_ZH, CITY_AIRPORTS, CITY_TO_IATA


def resolve_airports(value: str) -> list[str]:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("城市不能为空")
    if cleaned in CITY_AIRPORTS:
        return CITY_AIRPORTS[cleaned]
    if len(cleaned) == 3 and cleaned.isascii():
        code = cleaned.upper()
        if code in CITY_AIRPORTS and code not in AIRPORT_NAME_ZH:
            return CITY_AIRPORTS[code]
        return [code]
    if cleaned in CITY_TO_IATA:
        code = CITY_TO_IATA[cleaned]
        return CITY_AIRPORTS.get(cleaned) or CITY_AIRPORTS.get(code) or [code]
    raise ValueError(f"未知城市或 IATA 代码：{value}")


def normalize_city(value: str) -> str:
    return resolve_airports(value)[0]

