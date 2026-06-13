from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from adv_search_flights.providers.skyscanner import SkyscannerProvider


def test_skyscanner_schema_is_normalized() -> None:
    payload = {
        "context": {"currency": "USD"},
        "itineraries": {
            "results": [
                {
                    "id": "itinerary-1",
                    "legIds": ["leg-1"],
                    "pricingOptions": [{"price": {"amount": 100}}],
                }
            ]
        },
        "legs": {
            "results": {
                "leg-1": {"id": "leg-1", "segmentIds": ["seg-1", "seg-2"]},
            }
        },
        "segments": {
            "results": {
                "seg-1": {
                    "id": "seg-1",
                    "originPlaceId": "place-pvg",
                    "destinationPlaceId": "place-hkg",
                    "departureDateTime": {"year": 2026, "month": 6, "day": 29, "hour": 8, "minute": 0},
                    "arrivalDateTime": {"year": 2026, "month": 6, "day": 29, "hour": 11, "minute": 0},
                    "marketingCarrierId": "carrier-cx",
                    "flightNumber": "359",
                    "aircraft": "333",
                },
                "seg-2": {
                    "id": "seg-2",
                    "originPlaceId": "place-hkg",
                    "destinationPlaceId": "place-nrt",
                    "departureDateTime": {"year": 2026, "month": 6, "day": 29, "hour": 13, "minute": 0},
                    "arrivalDateTime": {"year": 2026, "month": 6, "day": 29, "hour": 18, "minute": 30},
                    "marketingCarrierId": "carrier-cx",
                    "flightNumber": "500",
                    "aircraft": "333",
                },
            }
        },
        "places": {
            "results": {
                "place-pvg": {"id": "place-pvg", "displayCode": "PVG"},
                "place-hkg": {"id": "place-hkg", "displayCode": "HKG"},
                "place-nrt": {"id": "place-nrt", "displayCode": "NRT"},
            }
        },
        "carriers": {
            "results": {
                "carrier-cx": {"id": "carrier-cx", "alternateId": "CX", "name": "Cathay Pacific"},
            }
        },
    }

    provider = SkyscannerProvider()
    options = provider._normalize(SimpleNamespace(json=payload), "PVG", "NRT", date(2026, 6, 29))

    assert len(options) == 1
    assert options[0].price_cny == 720
    assert options[0].route == "PVG-HKG-NRT"
    assert options[0].segments[0].flight_number == "CX359"
    assert options[0].segments[0].airline_zh == "国泰航空"
    assert options[0].segments[0].aircraft == "333"
    assert options[0].layovers[0].airport == "HKG"
    assert options[0].layovers[0].hours == 2.0
