from __future__ import annotations

import asyncio
import json

from adv_search_flights.cli import run_gui_search_payload, run_gui_search_stream


def test_gui_search_payload_returns_envelope_for_mock_provider() -> None:
    envelope = asyncio.run(
        run_gui_search_payload(
            {
                "origin": "SHA",
                "destinations": ["MEL"],
                "departure": "2026-09-01",
                "return_date": "2026-09-15",
                "provider": "mock",
                "format": "json",
                "limit": 2,
                "no_cooldown": True,
                "retry_waits": [0, 0, 0],
            },
            check_network=False,
        )
    )

    assert envelope["ok"] is True
    assert envelope["error"] is None
    assert envelope["response"]["result_count"] == 2
    assert envelope["response"]["rendered"][0]["rank"] == 1
    assert envelope["network_status"]["status"] == "unknown"
    assert envelope["provider_status"]["status"] == "ok"


def test_gui_search_payload_reports_validation_error() -> None:
    envelope = asyncio.run(run_gui_search_payload(json.dumps({"origin": "SHA"}), check_network=False))

    assert envelope["ok"] is False
    assert envelope["response"] is None
    assert envelope["error"]["type"] == "validation_error"
    assert envelope["provider_status"]["status"] == "no_results"


def test_gui_search_payload_ignores_retired_rate_limit_wait_setting() -> None:
    envelope = asyncio.run(run_gui_search_payload({
        "origin": "SHA", "destinations": ["MEL"], "departure": "2026-09-01", "return_date": "2026-09-15",
        "provider": "mock", "format": "json", "rate_limit_retry_minutes": 4,
    }, check_network=False))

    assert envelope["ok"] is True
    assert envelope["response"]["result_count"] > 0


def test_gui_search_limit_zero_returns_all_results() -> None:
    envelope = asyncio.run(run_gui_search_payload({
        "origin": "SHA", "destinations": ["MEL"], "departure": "2026-09-01", "return_date": "2026-09-15",
        "provider": "mock", "format": "json", "limit": 0, "no_cooldown": True,
    }, check_network=False))

    assert envelope["ok"] is True
    assert envelope["response"]["query"]["limit"] is None
    assert envelope["response"]["result_count"] == 4


def test_gui_search_stream_emits_progress_and_final_envelope() -> None:
    events = []
    envelope = asyncio.run(
        run_gui_search_stream(
            {
                "origin": "SHA",
                "destinations": ["MEL"],
                "departure": "2026-09-01",
                "return_date": "2026-09-15",
                "provider": "mock",
                "format": "json",
                "limit": 1,
                "no_cooldown": True,
                "retry_waits": [0, 0, 0],
            },
            check_network=False,
            emit=events.append,
        )
    )

    assert envelope["ok"] is True
    assert [event["type"] for event in events if event["type"] in {"started", "combining", "completed"}] == [
        "started",
        "combining",
        "completed",
    ]
    assert events[-1]["envelope"]["response"]["result_count"] == 1
