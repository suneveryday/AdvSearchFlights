from __future__ import annotations

from adv_search_flights.data.generated_airports import GENERATED_AIRPORT_NAME_ZH, GENERATED_CITY_AIRPORTS
from adv_search_flights.data.reference_data import AIRPORT_NAME_ZH
from adv_search_flights.data.airports import resolve_airports


def test_generated_airports_include_markdown_rows() -> None:
    assert GENERATED_AIRPORT_NAME_ZH["CAN"] == "广州白云国际机场"
    assert "CAN" in GENERATED_CITY_AIRPORTS["广州"]


def test_handcrafted_airport_name_takes_precedence() -> None:
    assert AIRPORT_NAME_ZH["MNL"] == "马尼拉尼诺伊·阿基诺国际机场"


def test_generated_city_airports_are_resolvable() -> None:
    assert resolve_airports("广州") == ["CAN"]
    assert resolve_airports("香港") == ["HKG"]
