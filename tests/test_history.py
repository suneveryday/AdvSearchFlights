from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.domain.models import SearchRequest
import adv_search_flights.history as history_module
from adv_search_flights.cli import main
from adv_search_flights.history import (
    _local_timestamp,
    canonical_location,
    claim_due_history_schedule,
    delete_history_group,
    evaluate_schedule_alert,
    get_app_settings,
    get_history,
    get_history_group,
    get_history_group_results,
    list_history,
    list_history_groups,
    list_history_schedules,
    reset_schedule_runtime_states,
    record_schedule_alert_delivery,
    save_search_response,
    toggle_history_schedule,
    update_app_settings,
    update_history_schedule_status,
)
from adv_search_flights.providers.mock import MockProvider
from adv_search_flights.search.engine import FlightSearchEngine


def test_history_saves_real_provider_response_and_lists_batches(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    response = asyncio.run(_mock_search(provider="fli", origin="广州", destinations=["新加坡"]))

    batch_id = save_search_response(response)

    assert batch_id is not None
    items = list_history()
    assert len(items) == 1
    assert items[0]["id"] == batch_id
    assert items[0]["origin"] == "广州"
    assert items[0]["destinations"] == ["新加坡"]
    assert items[0]["cabin_class"] == "ECONOMY"

    history = get_history(batch_id)
    assert history is not None
    assert history["rendered"][0]["purchase_links"]["outbound"]["url"]
    assert history["rendered"][0]["outbound"]["segments"][0]["origin_airport"] == "CAN"


def test_history_does_not_save_mock_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    response = asyncio.run(_mock_search(provider="mock", origin="香港", destinations=["曼谷"]))

    assert save_search_response(response) is None
    assert list_history() == []


def test_history_timestamp_is_displayed_in_local_timezone() -> None:
    china_standard_time = timezone(timedelta(hours=8))

    assert _local_timestamp("2026-06-18T16:30:00+00:00", china_standard_time) == "2026-06-19 00:30"
    assert _local_timestamp("2026-06-18T16:30:00", china_standard_time) == "2026-06-19 00:30"


def test_location_normalization_obeys_city_and_airport_grouping_rules() -> None:
    assert canonical_location("上海")["key"] == canonical_location("Shanghai")["key"]
    assert canonical_location("上海")["key"] != canonical_location("PVG")["key"]
    assert canonical_location("新加坡")["key"] == canonical_location("Singapore")["key"]
    assert canonical_location("新加坡")["key"] == canonical_location("SIN")["key"]
    assert canonical_location("东京")["key"] == canonical_location("Tokyo")["key"]
    assert canonical_location("东京")["key"] != canonical_location("HND")["key"]


def test_history_groups_ignore_destination_order_but_include_all_search_dimensions(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    first = asyncio.run(_mock_search(provider="fli", origin="上海", destinations=["墨尔本", "悉尼"]))
    second = asyncio.run(_mock_search(provider="fli", origin="Shanghai", destinations=["悉尼", "墨尔本"]))

    save_search_response(first)
    save_search_response(second)

    groups = list_history_groups()
    assert len(groups) == 1
    assert groups[0]["batch_count"] == 2

    changed = second.model_copy(deep=True)
    changed.query.adults = 2
    save_search_response(changed)
    changed = second.model_copy(deep=True)
    changed.query.currency = "SGD"
    save_search_response(changed)
    changed = second.model_copy(deep=True)
    changed.query.limit = 8
    save_search_response(changed)
    changed = second.model_copy(deep=True)
    changed.query.max_stops = 2
    save_search_response(changed)

    groups = list_history_groups()
    assert len(groups) == 4
    assert max(group["batch_count"] for group in groups) == 3


def test_backfill_is_idempotent_and_does_not_modify_original_history(tmp_path, monkeypatch) -> None:
    path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(path))
    response = asyncio.run(_mock_search(provider="fli", origin="北京", destinations=["东京"]))
    save_search_response(response)
    with sqlite3.connect(path) as conn:
        batches_before = conn.execute("SELECT * FROM search_batches").fetchall()
        routes_before = conn.execute("SELECT * FROM route_records").fetchall()

    assert len(list_history_groups()) == 1
    assert len(list_history_groups()) == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM search_batches").fetchall() == batches_before
        assert conn.execute("SELECT * FROM route_records").fetchall() == routes_before
        assert conn.execute("SELECT COUNT(*) FROM history_group_batches").fetchone()[0] == 1


def test_grouping_v2_rebuilds_only_aggregate_tables_and_merges_legacy_limit_groups(tmp_path, monkeypatch) -> None:
    path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(path))
    first = asyncio.run(_mock_search(provider="fli", origin="上海", destinations=["墨尔本", "悉尼"]))
    second = first.model_copy(deep=True)
    second.query.limit = 8
    first_id = save_search_response(first)
    second_id = save_search_response(second)

    with sqlite3.connect(path) as conn:
        group_id = conn.execute("SELECT id FROM history_groups").fetchone()[0]
        conn.execute(
            """
            INSERT INTO history_groups
            SELECT 'legacy-split', 'legacy-limit-key', origin_key, origin_display,
                   destination_keys_json, destination_displays_json, departure, return_date,
                   cabin_class, adults, max_stops, max_layover_hours, provider, currency, 8,
                   created_at, updated_at
            FROM history_groups WHERE id = ?
            """,
            (group_id,),
        )
        conn.execute("UPDATE history_group_batches SET group_id = 'legacy-split' WHERE batch_id = ?", (second_id,))
        conn.execute("UPDATE history_metadata SET value = '1' WHERE key = 'grouping_rule_version'")
        batches_before = conn.execute("SELECT * FROM search_batches ORDER BY id").fetchall()
        routes_before = conn.execute("SELECT * FROM route_records ORDER BY id").fetchall()

    groups = list_history_groups()

    assert len(groups) == 1
    assert groups[0]["batch_count"] == 2
    assert {item["id"] for item in get_history_group(groups[0]["id"])["batches"]} == {first_id, second_id}
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM search_batches ORDER BY id").fetchall() == batches_before
        assert conn.execute("SELECT * FROM route_records ORDER BY id").fetchall() == routes_before
        assert conn.execute("SELECT value FROM history_metadata WHERE key = 'grouping_rule_version'").fetchone()[0] == "2"


def test_group_filters_drive_results_and_trend_with_null_gap(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    first = asyncio.run(_mock_search(provider="fli", origin="广州", destinations=["新加坡"]))
    first.rendered[0]["total_price_cny"] = 3000
    first.rendered[0]["outbound"]["airlines"] = ["测试航空 A"]
    first.rendered[0]["outbound"]["layovers"] = [{"airport": "BKK", "duration_hours": 3}]
    first.rendered[0]["outbound"]["departure_time"] = "2026-09-01T03:00:00"
    first_id = save_search_response(first)

    second = asyncio.run(_mock_search(provider="fli", origin="广州", destinations=["新加坡"]))
    second.rendered[0]["total_price_cny"] = 5000
    second.rendered[0]["outbound"]["airlines"] = ["测试航空 B"]
    second.rendered[0]["outbound"]["departure_time"] = "2026-09-01T12:00:00"
    second_minimum = min(row["total_price_cny"] for row in second.rendered)
    second_id = save_search_response(second)
    group_id = list_history_groups()[0]["id"]

    payload = get_history_group_results(group_id, batch_id=second_id, filters={"include_airlines": ["测试航空 A"]})

    assert payload is not None
    assert payload["selected_batch"]["id"] == second_id
    assert payload["rendered"] == []
    points = {point["batch_id"]: point for point in payload["trend"]}
    assert points[first_id]["minimum_price_cny"] == 3000
    assert points[second_id]["minimum_price_cny"] is None
    batches = {batch["id"]: batch for batch in payload["batches"]}
    assert batches[first_id]["minimum_price_cny"] == 3000
    assert batches[second_id]["minimum_price_cny"] == second_minimum
    assert "测试航空 A" in payload["filter_options"]["airlines"]
    assert "BKK" in payload["filter_options"]["layover_airports"]

    limited = get_history_group_results(group_id, filters={"max_single_layover_hours": 2})
    assert limited is not None
    assert all(row["total_price_cny"] != 3000 for row in limited["rendered"])

    morning = get_history_group_results(
        group_id,
        filters={"departure_time_range": {"start": "00:00", "end": "06:00"}},
    )
    assert morning is not None
    morning_points = {point["batch_id"]: point for point in morning["trend"]}
    assert morning_points[first_id]["minimum_price_cny"] == 3000
    assert morning_points[second_id]["minimum_price_cny"] is None
    morning_batches = {batch["id"]: batch for batch in morning["batches"]}
    assert morning_batches[first_id]["minimum_price_cny"] == 3000
    assert morning_batches[second_id]["minimum_price_cny"] == second_minimum


def test_delete_group_removes_complete_batches_and_orphans(tmp_path, monkeypatch) -> None:
    path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(path))
    response = asyncio.run(_mock_search(provider="fli", origin="香港", destinations=["曼谷"]))
    batch_id = save_search_response(response)
    group_id = list_history_groups()[0]["id"]

    assert get_history_group(group_id) is not None
    assert delete_history_group(group_id) is True
    assert get_history(batch_id) is None
    assert list_history_groups() == []
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM route_records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM history_group_batches").fetchone()[0] == 0


def test_retention_deletes_oldest_whole_batch_and_keeps_newest_complete(tmp_path, monkeypatch) -> None:
    path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(path))
    monkeypatch.setattr(history_module, "MAX_ROUTE_RECORDS", 3)
    first = asyncio.run(_mock_search(provider="fli", origin="北京", destinations=["东京"]))
    first_id = save_search_response(first)
    second = asyncio.run(_mock_search(provider="fli", origin="香港", destinations=["曼谷"]))
    second_id = save_search_response(second)

    assert get_history(first_id) is None
    latest = get_history(second_id)
    assert latest is not None
    assert len(latest["rendered"]) == 2
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM route_records WHERE batch_id = ?", (first_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM route_records WHERE batch_id = ?", (second_id,)).fetchone()[0] == 2


def test_history_group_cli_contracts(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    response = asyncio.run(_mock_search(provider="fli", origin="广州", destinations=["新加坡"]))
    save_search_response(response)
    group_id = list_history_groups()[0]["id"]

    monkeypatch.setattr(sys, "argv", ["adv-search-flights", "history-group-list", "--format", "json"])
    main()
    assert group_id in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        ["adv-search-flights", "history-group-results", group_id, "--filters", '{"max_total_price": 1}', "--format", "json"],
    )
    main()
    assert '"minimum_price_cny": null' in capsys.readouterr().out


def test_schedule_uses_latest_query_and_defaults_to_eight_hours(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    first = asyncio.run(_mock_search(provider="fli", origin="广州", destinations=["新加坡"]))
    first.query.limit = 10
    save_search_response(first)
    latest = asyncio.run(_mock_search(provider="fli", origin="广州", destinations=["新加坡"]))
    latest.query.limit = 50
    save_search_response(latest)
    group_id = list_history_groups()[0]["id"]
    now = datetime(2026, 6, 19, 2, 30, tzinfo=timezone.utc)

    schedule = toggle_history_schedule(group_id, True, now=now)

    assert schedule["enabled"] is True
    assert schedule["status"] == "scheduled"
    assert schedule["interval_hours"] == 8
    assert schedule["notification_enabled"] is False
    assert schedule["next_run_at"] == (now + timedelta(hours=8)).isoformat()
    assert schedule["query"]["limit"] == 50
    assert claim_due_history_schedule(now=now + timedelta(hours=7, minutes=59)) is None
    claimed = claim_due_history_schedule(now=now + timedelta(hours=8, minutes=1))
    assert claimed is not None
    assert claimed["group_id"] == group_id
    assert claimed["query"]["limit"] == 50
    assert claim_due_history_schedule(now=now + timedelta(hours=8, minutes=2)) is None


def test_schedule_validates_interval_and_notification_threshold(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    save_search_response(asyncio.run(_mock_search(provider="fli", origin="广州", destinations=["新加坡"])))
    group_id = list_history_groups()[0]["id"]
    now = datetime(2026, 6, 19, tzinfo=timezone.utc)

    one_hour = toggle_history_schedule(group_id, True, interval_hours=1, notification_enabled=True, price_threshold=5000, now=now)
    assert one_hour["next_run_at"] == (now + timedelta(hours=1)).isoformat()
    assert one_hour["price_threshold"] == 5000
    assert one_hour["notification_enabled"] is True
    forty_eight = toggle_history_schedule(group_id, True, interval_hours=48, now=now)
    assert forty_eight["next_run_at"] == (now + timedelta(hours=48)).isoformat()
    with pytest.raises(ValueError, match="1 到 48"):
        toggle_history_schedule(group_id, True, interval_hours=0, now=now)
    with pytest.raises(ValueError, match="价格阈值"):
        toggle_history_schedule(group_id, True, notification_enabled=True, price_threshold=0, now=now)


def test_old_schedule_schema_migrates_with_one_hour_interval(tmp_path, monkeypatch) -> None:
    path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(path))
    save_search_response(asyncio.run(_mock_search(provider="fli", origin="北京", destinations=["东京"])))
    group_id = list_history_groups()[0]["id"]
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE history_schedules")
        conn.execute(
            """CREATE TABLE history_schedules (
                group_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
                enabled_at TEXT, next_run_at TEXT, last_run_at TEXT,
                status TEXT NOT NULL DEFAULT 'disabled', last_error TEXT, updated_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO history_schedules VALUES (?, 1, ?, ?, NULL, 'scheduled', NULL, ?)",
            (group_id, "2026-06-19T00:00:00+00:00", "2026-06-19T01:00:00+00:00", "2026-06-19T00:00:00+00:00"),
        )

    migrated = list_history_schedules()[0]
    assert migrated["interval_hours"] == 1
    assert migrated["notification_enabled"] is False


def test_alerts_trigger_on_first_threshold_hit_and_new_lower_price(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    response = asyncio.run(_mock_search(provider="fli", origin="广州", destinations=["新加坡"]))
    first_batch = save_search_response(response)
    group_id = list_history_groups()[0]["id"]
    first_price = min(row["total_price_cny"] for row in response.rendered)
    toggle_history_schedule(group_id, True, interval_hours=8, notification_enabled=True, price_threshold=first_price + 1)

    first = evaluate_schedule_alert(group_id, first_batch)
    assert first["should_notify"] is True
    assert first["channels"] == {"desktop": True, "reminders": True}
    assert first["purchase_links"]["outbound"]["url"]
    record_schedule_alert_delivery(group_id, "desktop", first_price)
    desktop_sent = evaluate_schedule_alert(group_id, first_batch)
    assert desktop_sent["channels"] == {"desktop": False, "reminders": True}
    record_schedule_alert_delivery(group_id, "reminders", first_price)
    assert evaluate_schedule_alert(group_id, first_batch)["should_notify"] is False

    toggle_history_schedule(group_id, True, interval_hours=12, notification_enabled=True, price_threshold=first_price + 200)
    assert evaluate_schedule_alert(group_id, first_batch)["should_notify"] is False

    cheaper = asyncio.run(_mock_search(provider="fli", origin="广州", destinations=["新加坡"]))
    for row in cheaper.rendered:
        row["total_price_cny"] -= 100
    cheaper_batch = save_search_response(cheaper)
    next_alert = evaluate_schedule_alert(group_id, cheaper_batch)
    assert next_alert["price"] == first_price - 100
    assert next_alert["channels"] == {"desktop": True, "reminders": True}


def test_alert_threshold_is_strictly_lower(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    response = asyncio.run(_mock_search(provider="fli", origin="香港", destinations=["曼谷"]))
    batch_id = save_search_response(response)
    group_id = list_history_groups()[0]["id"]
    price = min(row["total_price_cny"] for row in response.rendered)
    toggle_history_schedule(group_id, True, notification_enabled=True, price_threshold=price)
    alert = evaluate_schedule_alert(group_id, batch_id)
    assert alert["should_notify"] is False
    assert alert["reason"] == "threshold_not_met"


def test_schedule_limit_expiry_reset_and_delete_cascade(tmp_path, monkeypatch) -> None:
    path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(path))
    monkeypatch.setattr(history_module, "MAX_ENABLED_SCHEDULES", 1)
    first = asyncio.run(_mock_search(provider="fli", origin="北京", destinations=["东京"]))
    second = asyncio.run(_mock_search(provider="fli", origin="香港", destinations=["曼谷"]))
    save_search_response(first)
    save_search_response(second)
    groups = list_history_groups()
    now = datetime(2026, 6, 19, tzinfo=timezone.utc)
    toggle_history_schedule(groups[0]["id"], True, now=now)

    with pytest.raises(ValueError, match="最多只能启用"):
        toggle_history_schedule(groups[1]["id"], True, now=now)

    reset_schedule_runtime_states(now=now + timedelta(hours=1, minutes=10))
    skipped_item = list_history_schedules()[0]
    assert datetime.fromisoformat(skipped_item["next_run_at"]) > now + timedelta(hours=1, minutes=10)

    update_history_schedule_status(groups[0]["id"], "running", now=now + timedelta(hours=1))
    reset_schedule_runtime_states(now=now + timedelta(hours=2, minutes=10))
    reset_item = list_history_schedules()[0]
    assert reset_item["status"] == "scheduled"
    assert datetime.fromisoformat(reset_item["next_run_at"]) > now + timedelta(hours=2, minutes=10)

    delete_history_group(groups[0]["id"])
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM history_schedules WHERE group_id = ?", (groups[0]["id"],)).fetchone()[0] == 0


def test_disabling_schedule_clears_pin_and_restores_latest_search_order(tmp_path, monkeypatch) -> None:
    path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(path))
    save_search_response(asyncio.run(_mock_search(provider="fli", origin="北京", destinations=["东京"])))
    save_search_response(asyncio.run(_mock_search(provider="fli", origin="香港", destinations=["曼谷"])))
    groups = list_history_groups()
    older_group = groups[-1]
    toggle_history_schedule(older_group["id"], True, now=datetime(2026, 6, 19, tzinfo=timezone.utc))
    assert list_history_groups()[0]["id"] == older_group["id"]

    disabled = toggle_history_schedule(older_group["id"], False, now=datetime(2026, 6, 19, 1, tzinfo=timezone.utc))

    assert disabled["enabled"] is False
    assert disabled["enabled_at"] is None
    assert list_history_groups()[0]["id"] == groups[0]["id"]


def test_expired_schedule_is_paused_and_settings_are_validated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    response = asyncio.run(_mock_search(provider="fli", origin="广州", destinations=["新加坡"]))
    save_search_response(response)
    group_id = list_history_groups()[0]["id"]

    schedule = toggle_history_schedule(group_id, True, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert schedule["enabled"] is True
    assert schedule["status"] == "paused_expired"
    assert schedule["next_run_at"] is None

    assert get_app_settings()["rate_limit_retry_minutes"] == 5
    assert update_app_settings(rate_limit_retry_minutes=20)["rate_limit_retry_minutes"] == 20
    with pytest.raises(ValueError):
        update_app_settings(rate_limit_retry_minutes=4)
    with pytest.raises(ValueError):
        update_app_settings(rate_limit_retry_minutes=21)


def test_app_settings_persist_anonymous_analytics_consent_and_install_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))

    initial = get_app_settings()
    assert initial["analytics_consent"] == "unset"
    assert uuid.UUID(initial["analytics_install_id"])

    updated = update_app_settings(analytics_consent="granted")
    assert updated["analytics_consent"] == "granted"
    assert updated["analytics_install_id"] == initial["analytics_install_id"]
    assert updated["rate_limit_retry_minutes"] == 5

    retry_updated = update_app_settings(rate_limit_retry_minutes=12)
    assert retry_updated["analytics_consent"] == "granted"
    assert retry_updated["analytics_install_id"] == initial["analytics_install_id"]

    with pytest.raises(ValueError):
        update_app_settings(analytics_consent="invalid")


def test_app_settings_persist_and_validate_proxy_urls(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))

    initial = get_app_settings()
    assert initial["http_proxy"] == ""
    assert initial["all_proxy"] == ""

    updated = update_app_settings(
        http_proxy=" http://127.0.0.1:7893 ",
        all_proxy="socks5://127.0.0.1:7894",
    )
    assert updated["http_proxy"] == "http://127.0.0.1:7893"
    assert updated["all_proxy"] == "socks5://127.0.0.1:7894"
    assert get_app_settings()["http_proxy"] == "http://127.0.0.1:7893"

    cleared = update_app_settings(http_proxy="", all_proxy="")
    assert cleared["http_proxy"] == ""
    assert cleared["all_proxy"] == ""
    with pytest.raises(ValueError, match="HTTP / HTTPS 代理格式无效"):
        update_app_settings(http_proxy="127.0.0.1:7893")
    with pytest.raises(ValueError, match="ALL_PROXY格式无效"):
        update_app_settings(all_proxy="ftp://127.0.0.1:7894")


def test_app_settings_cli_supports_partial_analytics_updates(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["adv-search-flights", "app-settings-update", "--analytics-consent", "denied", "--format", "json"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["item"]["analytics_consent"] == "denied"
    assert payload["item"]["rate_limit_retry_minutes"] == 5


def test_app_settings_cli_persists_proxy_values(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ADV_SEARCH_FLIGHTS_HISTORY_DB", str(tmp_path / "history.sqlite3"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "adv-search-flights", "app-settings-update",
            "--http-proxy", "http://127.0.0.1:7893",
            "--all-proxy", "socks5://127.0.0.1:7894",
            "--format", "json",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["item"]["http_proxy"] == "http://127.0.0.1:7893"
    assert payload["item"]["all_proxy"] == "socks5://127.0.0.1:7894"


async def _mock_search(provider: str, origin: str, destinations: list[str]):
    engine = FlightSearchEngine(
        MockProvider(),
        DataCallController(cooldown_seconds=0, retry_delays=(0, 0, 0)),
    )
    return await engine.search(
        SearchRequest(
            origin=origin,
            destinations=destinations,
            departure="2026-09-01",
            return_date="2026-09-15",
            provider=provider,
            output_format="json",
            cabin_class="ECONOMY",
            limit=2,
        )
    )
