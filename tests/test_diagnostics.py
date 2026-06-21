from __future__ import annotations

import json

from adv_search_flights.diagnostics import configure_logging, log_event, log_path, read_recent_logs


def test_diagnostic_log_rotates_locally_and_redacts_sensitive_fields(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_LOG_DIR", str(tmp_path))
    configure_logging(force=True)

    log_event(
        "test.request",
        route="PVG-MEL",
        booking_token="private-token",
        proxy_url="http://user:pass@example.invalid",
        response_text="x" * 800,
    )

    items = read_recent_logs(10)
    assert log_path() == tmp_path / "app.log"
    assert items[-1]["event"] == "test.request"
    assert items[-1]["route"] == "PVG-MEL"
    assert items[-1]["booking_token"] == "[redacted]"
    assert items[-1]["proxy_url"] == "[redacted]"
    assert len(items[-1]["response_text"]) == 500
    json.dumps(items[-1])
    monkeypatch.delenv("ADV_SEARCH_FLIGHTS_LOG_DIR")
    configure_logging(force=True)
