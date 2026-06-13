from __future__ import annotations

import os
import shutil
from importlib.util import find_spec
from typing import Any

from adv_search_flights.domain.models import ProviderName
from adv_search_flights.providers.auto import AutoProvider
from adv_search_flights.providers.base import FlightProvider
from adv_search_flights.providers.fli import FliProvider
from adv_search_flights.providers.mock import MockProvider
from adv_search_flights.providers.skyscanner import SkyscannerProvider


def build_provider(provider_name: ProviderName | str | None = None) -> FlightProvider:
    raw_provider = provider_name.value if isinstance(provider_name, ProviderName) else provider_name
    provider = (raw_provider or os.getenv("FLIGHT_PROVIDER", "auto")).strip().lower()
    if provider == "auto":
        return AutoProvider()
    if provider == "fli":
        return FliProvider()
    if provider == "skyscanner":
        return SkyscannerProvider()
    return MockProvider()


def provider_status() -> dict[str, dict[str, Any]]:
    return {
        "auto": {
            "available": True,
            "message": "默认模式：优先 Google Flights，失败或无可用价格时尝试 Skyscanner",
        },
        "mock": {"available": True, "message": "内置演示数据"},
        "fli": {
            "available": shutil.which("fli") is not None,
            "message": "使用 Google Flights 反查数据；默认以 USD 查询并换算为人民币",
            "query_currency": os.getenv("FLI_QUERY_CURRENCY", "USD"),
            "language": os.getenv("FLI_LANGUAGE", "en-US"),
            "country": os.getenv("FLI_COUNTRY", "US"),
            "timeout_seconds": os.getenv("FLI_TIMEOUT_SECONDS", "15"),
            "usd_cny_rate": os.getenv("FLIGHT_USD_CNY_RATE", "7.2"),
        },
        "skyscanner": {
            "available": find_spec("skyscanner") is not None,
            "message": "可选实验源：需要自行安装 irrisolto/skyscanner 及其依赖",
            "locale": os.getenv("SKYSCANNER_LOCALE", "en-US"),
            "market": os.getenv("SKYSCANNER_MARKET", "US"),
            "currency": os.getenv("SKYSCANNER_CURRENCY", "USD"),
        },
    }
