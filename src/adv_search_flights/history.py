from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from adv_search_flights.data.reference_data import CITY_AIRPORTS, CITY_TO_IATA
from adv_search_flights.diagnostics import log_event
from adv_search_flights.domain.models import ProviderName, SearchResponse


REAL_PROVIDERS = {ProviderName.auto.value, ProviderName.fli.value, ProviderName.skyscanner.value}
MAX_ROUTE_RECORDS = 10_000
MAX_ENABLED_SCHEDULES = 5
DEFAULT_SCHEDULE_INTERVAL_HOURS = 8
GROUPING_RULE_VERSION = "2"


def history_db_path() -> Path:
    override = os.getenv("ADV_SEARCH_FLIGHTS_HISTORY_DB")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "AdvSearchFlights" / "search_history.sqlite3"


def save_search_response(response: SearchResponse) -> str | None:
    if response.provider.value not in REAL_PROVIDERS or response.result_count <= 0:
        return None
    rendered = response.rendered if isinstance(response.rendered, list) else []
    if not rendered:
        return None

    batch_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    query = response.query.model_dump(mode="json")
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO search_batches (
                id, created_at, provider, origin, destinations_json, departure, return_date,
                cabin_class, result_count, query_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                created_at,
                response.provider.value,
                response.query.origin,
                json.dumps(response.query.destinations, ensure_ascii=False),
                response.query.departure.isoformat(),
                response.query.return_date.isoformat(),
                response.query.cabin_class.value,
                len(rendered),
                json.dumps(query, ensure_ascii=False),
            ),
        )
        seen: set[str] = set()
        rank = 0
        for row in rendered:
            key = _route_key(row)
            if key in seen:
                continue
            seen.add(key)
            rank += 1
            conn.execute(
                """
                INSERT INTO route_records (
                    id, batch_id, rank, total_price_cny, total_layover_hours,
                    layover_cities_json, layover_airports_json, outbound_purchase_url,
                    inbound_purchase_url, rendered_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    batch_id,
                    rank,
                    int(row.get("total_price_cny") or 0),
                    _total_layover_hours(row),
                    json.dumps(_layover_cities(row), ensure_ascii=False),
                    json.dumps(_layover_airports(row), ensure_ascii=False),
                    _purchase_url(row, "outbound"),
                    _purchase_url(row, "inbound"),
                    json.dumps(row, ensure_ascii=False),
                ),
            )
        conn.execute("UPDATE search_batches SET result_count = ? WHERE id = ?", (rank, batch_id))
        _link_batch_to_group(conn, batch_id)
        _enforce_retention(conn, newest_batch_id=batch_id)
    return batch_id


def list_history(limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT id, created_at, provider, origin, destinations_json, departure, return_date,
                   cabin_class, result_count,
                   (SELECT MIN(r.total_price_cny) FROM route_records r WHERE r.batch_id = search_batches.id)
                       AS minimum_price_cny
            FROM search_batches
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_batch_payload(row) for row in rows]


def get_history(batch_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        _ensure_schema(conn)
        batch = conn.execute(
            """
            SELECT id, created_at, provider, origin, destinations_json, departure, return_date,
                   cabin_class, result_count, query_json,
                   (SELECT MIN(r.total_price_cny) FROM route_records r WHERE r.batch_id = search_batches.id)
                       AS minimum_price_cny
            FROM search_batches WHERE id = ?
            """,
            (batch_id,),
        ).fetchone()
        if batch is None:
            return None
        records = conn.execute(
            "SELECT rendered_json FROM route_records WHERE batch_id = ? ORDER BY rank ASC", (batch_id,)
        ).fetchall()
    payload = _batch_payload(batch)
    payload["query"] = json.loads(batch["query_json"])
    payload["rendered"] = [json.loads(row["rendered_json"]) for row in records]
    return payload


def list_history_groups(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT g.*, COUNT(m.batch_id) AS batch_count,
                   COALESCE(SUM(b.result_count), 0) AS result_count,
                   MAX(b.created_at) AS latest_created_at,
                   COALESCE(s.enabled, 0) AS schedule_enabled,
                   s.enabled_at AS schedule_enabled_at,
                   s.next_run_at AS schedule_next_run_at,
                   s.last_run_at AS schedule_last_run_at,
                   s.status AS schedule_status,
                   s.last_error AS schedule_last_error,
                   s.interval_hours AS schedule_interval_hours,
                   s.notification_enabled AS schedule_notification_enabled,
                   s.price_threshold AS schedule_price_threshold,
                   s.desktop_last_notified_price AS schedule_desktop_last_notified_price,
                   s.reminder_last_notified_price AS schedule_reminder_last_notified_price
            FROM history_groups g
            JOIN history_group_batches m ON m.group_id = g.id
            JOIN search_batches b ON b.id = m.batch_id
            LEFT JOIN history_schedules s ON s.group_id = g.id
            GROUP BY g.id
            ORDER BY schedule_enabled DESC,
                     CASE WHEN schedule_enabled = 1 THEN schedule_enabled_at END DESC,
                     latest_created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_group_payload(row) for row in rows]


def get_history_group(group_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        _ensure_schema(conn)
        group = conn.execute("SELECT * FROM history_groups WHERE id = ?", (group_id,)).fetchone()
        if group is None:
            return None
        batches = conn.execute(
            """
            SELECT b.id, b.created_at, b.provider, b.origin, b.destinations_json, b.departure,
                   b.return_date, b.cabin_class, b.result_count,
                   (SELECT MIN(r.total_price_cny) FROM route_records r WHERE r.batch_id = b.id)
                       AS minimum_price_cny
            FROM search_batches b
            JOIN history_group_batches m ON m.batch_id = b.id
            WHERE m.group_id = ? ORDER BY b.created_at DESC
            """,
            (group_id,),
        ).fetchall()
    payload = _group_payload(group)
    payload["batches"] = [_batch_payload(row) for row in batches]
    return payload


def get_history_group_results(
    group_id: str,
    *,
    batch_id: str | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    active_filters = _normalize_filters(filters or {})
    with _connect() as conn:
        _ensure_schema(conn)
        group = conn.execute("SELECT * FROM history_groups WHERE id = ?", (group_id,)).fetchone()
        if group is None:
            return None
        batches = conn.execute(
            """
            SELECT b.id, b.created_at, b.provider, b.origin, b.destinations_json, b.departure,
                   b.return_date, b.cabin_class, b.result_count,
                   (SELECT MIN(r.total_price_cny) FROM route_records r WHERE r.batch_id = b.id)
                       AS minimum_price_cny
            FROM search_batches b
            JOIN history_group_batches m ON m.batch_id = b.id
            WHERE m.group_id = ? ORDER BY b.created_at ASC
            """,
            (group_id,),
        ).fetchall()
        if not batches:
            return None
        batch_ids = {row["id"] for row in batches}
        selected_id = batch_id if batch_id in batch_ids else batches[-1]["id"]
        rows_by_batch: dict[str, list[dict[str, Any]]] = {}
        option_rows: list[dict[str, Any]] = []
        for batch in batches:
            records = conn.execute(
                "SELECT rendered_json FROM route_records WHERE batch_id = ? ORDER BY rank ASC", (batch["id"],)
            ).fetchall()
            rendered = [json.loads(row["rendered_json"]) for row in records]
            rows_by_batch[batch["id"]] = rendered
            option_rows.extend(rendered)

    filtered_by_batch = {
        item_id: [row for row in rows if _matches_filters(row, active_filters)]
        for item_id, rows in rows_by_batch.items()
    }
    trend = [
        {
            "batch_id": batch["id"],
            "created_at": batch["created_at"],
            "label": _local_timestamp(batch["created_at"]),
            "minimum_price_cny": min((int(row.get("total_price_cny") or 0) for row in filtered_by_batch[batch["id"]]), default=None),
            "match_count": len(filtered_by_batch[batch["id"]]),
        }
        for batch in batches
    ]
    selected_batch = next(row for row in batches if row["id"] == selected_id)
    return {
        "group": _group_payload(group),
        "batches": [_batch_payload(row) for row in reversed(batches)],
        "selected_batch": _batch_payload(selected_batch),
        "filters": active_filters,
        "filter_options": _filter_options(option_rows),
        "trend": trend,
        "rendered": filtered_by_batch[selected_id],
        "result_count": len(filtered_by_batch[selected_id]),
    }


def delete_history_group(group_id: str) -> bool:
    with _connect() as conn:
        _ensure_schema(conn)
        batch_ids = [
            row["batch_id"]
            for row in conn.execute("SELECT batch_id FROM history_group_batches WHERE group_id = ?", (group_id,)).fetchall()
        ]
        if not batch_ids:
            return False
        _delete_batches(conn, batch_ids)
        conn.execute("DELETE FROM history_groups WHERE id = ?", (group_id,))
    return True


def canonical_location(value: str) -> dict[str, str]:
    cleaned = value.strip()
    upper = cleaned.upper()
    if len(upper) == 3 and upper.isascii() and upper.isalpha():
        return {"key": f"AIRPORT:{upper}", "display": upper}

    airports = CITY_AIRPORTS.get(cleaned)
    if airports:
        normalized = sorted({item.upper() for item in airports})
        if len(normalized) == 1:
            return {"key": f"AIRPORT:{normalized[0]}", "display": cleaned}
        return {"key": f"CITY:{','.join(normalized)}", "display": cleaned}

    airport = CITY_TO_IATA.get(cleaned)
    if airport:
        code = airport.upper()
        aliases = CITY_AIRPORTS.get(cleaned) or CITY_AIRPORTS.get(code)
        if aliases and len(set(aliases)) > 1:
            normalized = sorted({item.upper() for item in aliases})
            return {"key": f"CITY:{','.join(normalized)}", "display": cleaned}
        return {"key": f"AIRPORT:{code}", "display": cleaned}
    return {"key": f"TEXT:{upper}", "display": cleaned}


def _connect() -> sqlite3.Connection:
    path = history_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_batches (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, provider TEXT NOT NULL,
            origin TEXT NOT NULL, destinations_json TEXT NOT NULL, departure TEXT NOT NULL,
            return_date TEXT NOT NULL, cabin_class TEXT NOT NULL, result_count INTEGER NOT NULL,
            query_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS route_records (
            id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, rank INTEGER NOT NULL,
            total_price_cny INTEGER NOT NULL, total_layover_hours REAL NOT NULL,
            layover_cities_json TEXT NOT NULL, layover_airports_json TEXT NOT NULL,
            outbound_purchase_url TEXT, inbound_purchase_url TEXT, rendered_json TEXT NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES search_batches(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history_groups (
            id TEXT PRIMARY KEY, group_key TEXT NOT NULL UNIQUE,
            origin_key TEXT NOT NULL, origin_display TEXT NOT NULL,
            destination_keys_json TEXT NOT NULL, destination_displays_json TEXT NOT NULL,
            departure TEXT NOT NULL, return_date TEXT NOT NULL, cabin_class TEXT NOT NULL,
            adults INTEGER NOT NULL, max_stops INTEGER NOT NULL, max_layover_hours REAL NOT NULL,
            provider TEXT NOT NULL, currency TEXT NOT NULL, result_limit INTEGER,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history_group_batches (
            group_id TEXT NOT NULL, batch_id TEXT NOT NULL UNIQUE,
            PRIMARY KEY(group_id, batch_id),
            FOREIGN KEY(group_id) REFERENCES history_groups(id) ON DELETE CASCADE,
            FOREIGN KEY(batch_id) REFERENCES search_batches(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history_schedules (
            group_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
            enabled_at TEXT, next_run_at TEXT, last_run_at TEXT,
            status TEXT NOT NULL DEFAULT 'disabled', last_error TEXT, updated_at TEXT NOT NULL,
            interval_hours INTEGER NOT NULL DEFAULT 8,
            notification_enabled INTEGER NOT NULL DEFAULT 0, price_threshold INTEGER,
            desktop_last_notified_price INTEGER, desktop_last_notified_at TEXT,
            reminder_last_notified_price INTEGER, reminder_last_notified_at TEXT,
            FOREIGN KEY(group_id) REFERENCES history_groups(id) ON DELETE CASCADE
        )
        """
    )
    _ensure_column(conn, "history_schedules", "interval_hours", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "history_schedules", "notification_enabled", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "history_schedules", "price_threshold", "INTEGER")
    _ensure_column(conn, "history_schedules", "desktop_last_notified_price", "INTEGER")
    _ensure_column(conn, "history_schedules", "desktop_last_notified_at", "TEXT")
    _ensure_column(conn, "history_schedules", "reminder_last_notified_price", "INTEGER")
    _ensure_column(conn, "history_schedules", "reminder_last_notified_at", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES ('rate_limit_retry_minutes', '5')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES ('analytics_consent', 'unset')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES ('analytics_install_id', ?)",
        (str(uuid.uuid4()),),
    )
    conn.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('http_proxy', '')")
    conn.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('all_proxy', '')")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_search_batches_created_at ON search_batches(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_route_records_batch_rank ON route_records(batch_id, rank)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_group_batches_group ON history_group_batches(group_id)")
    version = conn.execute(
        "SELECT value FROM history_metadata WHERE key = 'grouping_rule_version'"
    ).fetchone()
    if version is None or version["value"] != GROUPING_RULE_VERSION:
        conn.execute("DELETE FROM history_group_batches")
        conn.execute("DELETE FROM history_groups")
        _backfill_group_mappings(conn)
        conn.execute(
            "INSERT OR REPLACE INTO history_metadata (key, value) VALUES ('grouping_rule_version', ?)",
            (GROUPING_RULE_VERSION,),
        )
    else:
        _backfill_group_mappings(conn)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    newest = conn.execute("SELECT id FROM search_batches ORDER BY created_at DESC LIMIT 1").fetchone()
    if newest is not None:
        _enforce_retention(conn, newest_batch_id=newest["id"])


def _backfill_group_mappings(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT b.id FROM search_batches b
        LEFT JOIN history_group_batches m ON m.batch_id = b.id
        WHERE m.batch_id IS NULL ORDER BY b.created_at ASC
        """
    ).fetchall()
    for row in rows:
        _link_batch_to_group(conn, row["id"])


def _link_batch_to_group(conn: sqlite3.Connection, batch_id: str) -> None:
    batch = conn.execute("SELECT * FROM search_batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        return
    query = json.loads(batch["query_json"])
    origin = canonical_location(batch["origin"])
    destination_values = json.loads(batch["destinations_json"])
    destinations = [canonical_location(value) for value in destination_values]
    destinations.sort(key=lambda item: item["key"])
    dimensions = {
        "origin": origin["key"],
        "destinations": [item["key"] for item in destinations],
        "departure": batch["departure"],
        "return_date": batch["return_date"],
        "cabin_class": batch["cabin_class"],
        "adults": int(query.get("adults") or 1),
        "max_stops": int(query.get("max_stops") if query.get("max_stops") is not None else 1),
        "max_layover_hours": float(query.get("max_layover_hours") if query.get("max_layover_hours") is not None else 10),
        "provider": batch["provider"],
        "currency": str(query.get("currency") or "CNY").upper(),
    }
    raw_key = json.dumps(dimensions, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    group_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    now = batch["created_at"]
    existing = conn.execute("SELECT id FROM history_groups WHERE group_key = ?", (group_key,)).fetchone()
    group_id = existing["id"] if existing else str(uuid.uuid4())
    if existing is None:
        conn.execute(
            """
            INSERT INTO history_groups (
                id, group_key, origin_key, origin_display, destination_keys_json,
                destination_displays_json, departure, return_date, cabin_class, adults,
                max_stops, max_layover_hours, provider, currency, result_limit, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group_id, group_key, origin["key"], origin["display"],
                json.dumps([item["key"] for item in destinations], ensure_ascii=False),
                json.dumps([item["display"] for item in destinations], ensure_ascii=False),
                batch["departure"], batch["return_date"], batch["cabin_class"], dimensions["adults"],
                dimensions["max_stops"], dimensions["max_layover_hours"], batch["provider"],
                dimensions["currency"], None, now, now,
            ),
        )
    else:
        conn.execute("UPDATE history_groups SET updated_at = MAX(updated_at, ?) WHERE id = ?", (now, group_id))
    conn.execute(
        "INSERT OR IGNORE INTO history_group_batches (group_id, batch_id) VALUES (?, ?)", (group_id, batch_id)
    )


def _group_payload(row: sqlite3.Row) -> dict[str, Any]:
    destinations = json.loads(row["destination_displays_json"])
    payload = {
        "id": row["id"],
        "origin": row["origin_display"],
        "destinations": destinations,
        "departure": row["departure"],
        "return_date": row["return_date"],
        "cabin_class": row["cabin_class"],
        "adults": row["adults"],
        "max_stops": row["max_stops"],
        "max_layover_hours": row["max_layover_hours"],
        "provider": row["provider"],
        "currency": row["currency"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    for field in (
        "batch_count", "result_count", "latest_created_at", "schedule_enabled",
        "schedule_enabled_at", "schedule_next_run_at", "schedule_last_run_at",
        "schedule_status", "schedule_last_error",
        "schedule_interval_hours", "schedule_notification_enabled", "schedule_price_threshold",
        "schedule_desktop_last_notified_price", "schedule_reminder_last_notified_price",
    ):
        if field in row.keys():
            payload[field] = row[field]
    payload["title"] = f"{payload['origin']} → {' / '.join(destinations)}"
    payload["date_label"] = f"{payload['departure']} 至 {payload['return_date']}"
    return payload


def _schedule_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "group_id": row["group_id"],
        "enabled": bool(row["enabled"]),
        "enabled_at": row["enabled_at"],
        "next_run_at": row["next_run_at"],
        "last_run_at": row["last_run_at"],
        "status": row["status"],
        "last_error": row["last_error"],
        "interval_hours": int(row["interval_hours"]),
        "notification_enabled": bool(row["notification_enabled"]),
        "price_threshold": row["price_threshold"],
        "desktop_last_notified_price": row["desktop_last_notified_price"],
        "desktop_last_notified_at": row["desktop_last_notified_at"],
        "reminder_last_notified_price": row["reminder_last_notified_price"],
        "reminder_last_notified_at": row["reminder_last_notified_at"],
        "origin": row["origin_display"],
        "destinations": json.loads(row["destination_displays_json"]),
        "departure": row["departure"],
        "return_date": row["return_date"],
    }


def _pause_expired_schedules(conn: sqlite3.Connection, now: datetime) -> None:
    conn.execute(
        """
        UPDATE history_schedules SET status = 'paused_expired', next_run_at = NULL, updated_at = ?
        WHERE enabled = 1 AND group_id IN (
            SELECT id FROM history_groups WHERE departure < ?
        )
        """,
        (now.isoformat(), now.date().isoformat()),
    )


def _next_future_run(enabled_at: str, interval_hours: int, now: datetime) -> datetime:
    anchor = _as_utc(datetime.fromisoformat(enabled_at.replace("Z", "+00:00")))
    elapsed = max(0.0, (now - anchor).total_seconds())
    interval_seconds = interval_hours * 60 * 60
    periods = int(elapsed // interval_seconds) + 1
    return anchor + timedelta(seconds=periods * interval_seconds)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_filters(filters: dict[str, Any]) -> dict[str, Any]:
    def strings(name: str) -> list[str]:
        value = filters.get(name) or []
        return [str(item) for item in value if str(item).strip()]

    return {
        "max_total_price": _optional_float(filters.get("max_total_price")),
        "include_airlines": strings("include_airlines"),
        "exclude_airlines": strings("exclude_airlines"),
        "airport_routes": strings("airport_routes"),
        "max_stops_per_leg": _optional_int(filters.get("max_stops_per_leg")),
        "max_single_layover_hours": _optional_float(filters.get("max_single_layover_hours")),
        "exclude_layover_airports": strings("exclude_layover_airports"),
        "departure_time_range": _normalize_time_range(filters.get("departure_time_range")),
        "arrival_time_range": _normalize_time_range(filters.get("arrival_time_range")),
    }


def _matches_filters(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    price = int(row.get("total_price_cny") or 0)
    if filters["max_total_price"] is not None and price > filters["max_total_price"]:
        return False
    airlines = _row_airlines(row)
    if filters["include_airlines"] and not set(filters["include_airlines"]).intersection(airlines):
        return False
    if set(filters["exclude_airlines"]).intersection(airlines):
        return False
    if filters["airport_routes"] and _airport_route(row) not in filters["airport_routes"]:
        return False
    if filters["max_stops_per_leg"] is not None and any(
        max(0, len((row.get(direction) or {}).get("segments") or []) - 1) > filters["max_stops_per_leg"]
        for direction in ("outbound", "inbound")
    ):
        return False
    if filters["max_single_layover_hours"] is not None and any(
        float(item.get("duration_hours") if item.get("duration_hours") is not None else item.get("hours") or 0)
        > filters["max_single_layover_hours"]
        for direction in ("outbound", "inbound")
        for item in ((row.get(direction) or {}).get("layovers") or [])
    ):
        return False
    if set(filters["exclude_layover_airports"]).intersection(_row_layover_airports(row)):
        return False
    if not _time_in_range((row.get("outbound") or {}).get("departure_time"), filters["departure_time_range"]):
        return False
    if not _time_in_range((row.get("inbound") or {}).get("arrival_time"), filters["arrival_time_range"]):
        return False
    return True


def _filter_options(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "airlines": sorted({value for row in rows for value in _row_airlines(row)}),
        "airport_routes": sorted({_airport_route(row) for row in rows}),
        "layover_airports": sorted({value for row in rows for value in _row_layover_airports(row)}),
    }


def _row_airlines(row: dict[str, Any]) -> set[str]:
    return {
        str(value)
        for direction in ("outbound", "inbound")
        for value in ((row.get(direction) or {}).get("airlines") or [])
        if value
    }


def _row_layover_airports(row: dict[str, Any]) -> set[str]:
    return {
        str(item.get("airport"))
        for direction in ("outbound", "inbound")
        for item in ((row.get(direction) or {}).get("layovers") or [])
        if item.get("airport")
    }


def _airport_route(row: dict[str, Any]) -> str:
    outbound = row.get("outbound") or {}
    inbound = row.get("inbound") or {}
    return f"{outbound.get('origin_airport', '')}→{outbound.get('destination_airport', '')} / {inbound.get('origin_airport', '')}→{inbound.get('destination_airport', '')}"


def _enforce_retention(conn: sqlite3.Connection, *, newest_batch_id: str) -> None:
    count = conn.execute("SELECT COUNT(*) AS value FROM route_records").fetchone()["value"]
    while count > MAX_ROUTE_RECORDS:
        oldest = conn.execute(
            "SELECT id FROM search_batches WHERE id != ? ORDER BY created_at ASC LIMIT 1", (newest_batch_id,)
        ).fetchone()
        if oldest is None:
            break
        _delete_batches(conn, [oldest["id"]])
        count = conn.execute("SELECT COUNT(*) AS value FROM route_records").fetchone()["value"]


def _delete_batches(conn: sqlite3.Connection, batch_ids: list[str]) -> None:
    for batch_id in batch_ids:
        conn.execute("DELETE FROM route_records WHERE batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM history_group_batches WHERE batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM search_batches WHERE id = ?", (batch_id,))
    conn.execute("DELETE FROM history_groups WHERE id NOT IN (SELECT DISTINCT group_id FROM history_group_batches)")


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    number = _optional_float(value)
    return int(number) if number is not None else None


def _normalize_time_range(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    start = str(value.get("start") or "").strip()[:5]
    end = str(value.get("end") or "").strip()[:5]
    if not start and not end:
        return None
    return {"start": start, "end": end}


def _time_in_range(value: Any, time_range: dict[str, str] | None) -> bool:
    if not time_range:
        return True
    text = str(value or "")
    clock = text[11:16] if "T" in text else text[-5:]
    start = time_range.get("start") or "00:00"
    end = time_range.get("end") or "23:59"
    if start <= end:
        return start <= clock <= end
    return clock >= start or clock <= end


def get_app_settings() -> dict[str, Any]:
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT key, value FROM app_settings WHERE key IN "
            "('rate_limit_retry_minutes', 'analytics_consent', 'analytics_install_id', 'http_proxy', 'all_proxy')"
        ).fetchall()
    values = {row["key"]: row["value"] for row in rows}
    return {
        "rate_limit_retry_minutes": int(values.get("rate_limit_retry_minutes", "5")),
        "analytics_consent": values.get("analytics_consent", "unset"),
        "analytics_install_id": values["analytics_install_id"],
        "http_proxy": values.get("http_proxy", ""),
        "all_proxy": values.get("all_proxy", ""),
    }


def update_app_settings(
    *,
    rate_limit_retry_minutes: int | None = None,
    analytics_consent: str | None = None,
    http_proxy: str | None = None,
    all_proxy: str | None = None,
) -> dict[str, Any]:
    if rate_limit_retry_minutes is None and analytics_consent is None and http_proxy is None and all_proxy is None:
        raise ValueError("至少需要更新一个设置项")
    if rate_limit_retry_minutes is not None:
        minutes = int(rate_limit_retry_minutes)
        if not 5 <= minutes <= 20:
            raise ValueError("限频重试等待需设置为 5 到 20 分钟")
    if analytics_consent is not None and analytics_consent not in {"unset", "granted", "denied"}:
        raise ValueError("匿名统计授权状态无效")
    http_proxy = _validated_proxy(http_proxy, {"http", "https"}, "HTTP / HTTPS 代理")
    all_proxy = _validated_proxy(all_proxy, {"http", "https", "socks5", "socks5h"}, "ALL_PROXY")
    with _connect() as conn:
        _ensure_schema(conn)
        if rate_limit_retry_minutes is not None:
            conn.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('rate_limit_retry_minutes', ?)",
                (str(rate_limit_retry_minutes),),
            )
        if analytics_consent is not None:
            conn.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('analytics_consent', ?)",
                (analytics_consent,),
            )
        if http_proxy is not None:
            conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('http_proxy', ?)", (http_proxy,))
        if all_proxy is not None:
            conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('all_proxy', ?)", (all_proxy,))
    return get_app_settings()


def _validated_proxy(value: str | None, schemes: set[str], label: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme.lower() not in schemes or not parsed.hostname or parsed.port is None:
        raise ValueError(f"{label}格式无效")
    return normalized


def list_history_schedules() -> list[dict[str, Any]]:
    with _connect() as conn:
        _ensure_schema(conn)
        _pause_expired_schedules(conn, datetime.now(timezone.utc))
        rows = conn.execute(
            """
            SELECT s.*, g.origin_display, g.destination_displays_json, g.departure, g.return_date
            FROM history_schedules s
            JOIN history_groups g ON g.id = s.group_id
            WHERE s.enabled = 1
            ORDER BY s.enabled_at DESC
            """
        ).fetchall()
    return [_schedule_payload(row) for row in rows]


def toggle_history_schedule(
    group_id: str,
    enabled: bool,
    *,
    interval_hours: int = DEFAULT_SCHEDULE_INTERVAL_HOURS,
    notification_enabled: bool = False,
    price_threshold: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 1 <= int(interval_hours) <= 48:
        raise ValueError("定时搜索间隔必须为 1 到 48 小时")
    if notification_enabled and (price_threshold is None or int(price_threshold) <= 0):
        raise ValueError("开启价格提醒时必须设置大于 0 的价格阈值")
    current = _as_utc(now or datetime.now(timezone.utc))
    with _connect() as conn:
        _ensure_schema(conn)
        group = conn.execute("SELECT * FROM history_groups WHERE id = ?", (group_id,)).fetchone()
        if group is None:
            raise ValueError("没有找到这条搜索历史")
        existing = conn.execute("SELECT * FROM history_schedules WHERE group_id = ?", (group_id,)).fetchone()
        if enabled:
            active_count = conn.execute(
                "SELECT COUNT(*) FROM history_schedules WHERE enabled = 1 AND group_id != ?",
                (group_id,),
            ).fetchone()[0]
            if active_count >= MAX_ENABLED_SCHEDULES:
                raise ValueError(f"最多只能启用 {MAX_ENABLED_SCHEDULES} 组定时自动搜索")
            expired = date.fromisoformat(group["departure"]) < current.date()
            status = "paused_expired" if expired else "scheduled"
            next_run_at = None if expired else (current + timedelta(hours=int(interval_hours))).isoformat()
            conn.execute(
                """
                INSERT INTO history_schedules (
                    group_id, enabled, enabled_at, next_run_at, last_run_at, status, last_error, updated_at,
                    interval_hours, notification_enabled, price_threshold,
                    desktop_last_notified_price, desktop_last_notified_at,
                    reminder_last_notified_price, reminder_last_notified_at
                ) VALUES (?, 1, ?, ?, NULL, ?, NULL, ?, ?, ?, ?, NULL, NULL, NULL, NULL)
                ON CONFLICT(group_id) DO UPDATE SET
                    enabled = 1, enabled_at = excluded.enabled_at, next_run_at = excluded.next_run_at,
                    status = excluded.status, last_error = NULL, updated_at = excluded.updated_at,
                    interval_hours = excluded.interval_hours,
                    notification_enabled = excluded.notification_enabled,
                    price_threshold = excluded.price_threshold
                """,
                (
                    group_id, current.isoformat(), next_run_at, status, current.isoformat(),
                    int(interval_hours), int(notification_enabled), int(price_threshold) if price_threshold is not None else None,
                ),
            )
            log_event(
                "schedule.configured",
                group_id=group_id,
                interval_hours=int(interval_hours),
                notification_enabled=notification_enabled,
                price_threshold=price_threshold,
            )
        elif existing is not None:
            conn.execute(
                "UPDATE history_schedules SET enabled = 0, enabled_at = NULL, next_run_at = NULL, status = 'disabled', updated_at = ? WHERE group_id = ?",
                (current.isoformat(), group_id),
            )
        row = conn.execute(
            """
            SELECT s.*, g.origin_display, g.destination_displays_json, g.departure, g.return_date
            FROM history_schedules s JOIN history_groups g ON g.id = s.group_id
            WHERE s.group_id = ?
            """,
            (group_id,),
        ).fetchone()
        batch = None
        if enabled:
            batch = conn.execute(
                """
                SELECT b.query_json FROM search_batches b
                JOIN history_group_batches m ON m.batch_id = b.id
                WHERE m.group_id = ? ORDER BY b.created_at DESC LIMIT 1
                """,
                (group_id,),
            ).fetchone()
    if row is None:
        return {"group_id": group_id, "enabled": False, "status": "disabled"}
    payload = _schedule_payload(row)
    if batch is not None:
        payload["query"] = json.loads(batch["query_json"])
    return payload


def claim_due_history_schedule(*, now: datetime | None = None) -> dict[str, Any] | None:
    current = _as_utc(now or datetime.now(timezone.utc))
    with _connect() as conn:
        _ensure_schema(conn)
        _pause_expired_schedules(conn, current)
        row = conn.execute(
            """
            SELECT s.*, g.origin_display, g.destination_displays_json, g.departure, g.return_date
            FROM history_schedules s JOIN history_groups g ON g.id = s.group_id
            WHERE s.enabled = 1 AND s.status IN ('scheduled', 'succeeded', 'failed')
              AND s.next_run_at IS NOT NULL AND s.next_run_at <= ?
            ORDER BY s.next_run_at ASC, s.enabled_at DESC LIMIT 1
            """,
            (current.isoformat(),),
        ).fetchone()
        if row is None:
            return None
        batch = conn.execute(
            """
            SELECT b.query_json FROM search_batches b
            JOIN history_group_batches m ON m.batch_id = b.id
            WHERE m.group_id = ? ORDER BY b.created_at DESC LIMIT 1
            """,
            (row["group_id"],),
        ).fetchone()
        if batch is None:
            return None
        conn.execute(
            "UPDATE history_schedules SET status = 'queued', updated_at = ? WHERE group_id = ?",
            (current.isoformat(), row["group_id"]),
        )
        payload = _schedule_payload(row)
        payload["status"] = "queued"
        payload["query"] = json.loads(batch["query_json"])
        return payload


def update_history_schedule_status(
    group_id: str,
    status: str,
    *,
    error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    allowed = {"scheduled", "queued", "running", "rate_limited_wait", "succeeded", "failed", "paused_expired"}
    if status not in allowed:
        raise ValueError(f"未知定时任务状态：{status}")
    current = _as_utc(now or datetime.now(timezone.utc))
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM history_schedules WHERE group_id = ? AND enabled = 1", (group_id,)).fetchone()
        if row is None:
            raise ValueError("定时自动搜索未启用")
        next_run_at = row["next_run_at"]
        last_run_at = row["last_run_at"]
        if status in {"succeeded", "failed"}:
            last_run_at = current.isoformat()
            next_run_at = _next_future_run(row["enabled_at"], int(row["interval_hours"]), current).isoformat()
        conn.execute(
            """
            UPDATE history_schedules
            SET status = ?, last_error = ?, last_run_at = ?, next_run_at = ?, updated_at = ?
            WHERE group_id = ?
            """,
            (status, error, last_run_at, next_run_at, current.isoformat(), group_id),
        )
        result = conn.execute(
            """
            SELECT s.*, g.origin_display, g.destination_displays_json, g.departure, g.return_date
            FROM history_schedules s JOIN history_groups g ON g.id = s.group_id
            WHERE s.group_id = ?
            """,
            (group_id,),
        ).fetchone()
    return _schedule_payload(result)


def reset_schedule_runtime_states(*, now: datetime | None = None) -> None:
    current = _as_utc(now or datetime.now(timezone.utc))
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT group_id, enabled_at, interval_hours FROM history_schedules WHERE enabled = 1 AND status IN ('queued', 'running', 'rate_limited_wait')"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE history_schedules SET status = 'scheduled', next_run_at = ?, updated_at = ? WHERE group_id = ?",
                (_next_future_run(row["enabled_at"], int(row["interval_hours"]), current).isoformat(), current.isoformat(), row["group_id"]),
            )
        overdue = conn.execute(
            """
            SELECT group_id, enabled_at, interval_hours FROM history_schedules
            WHERE enabled = 1 AND status IN ('scheduled', 'succeeded', 'failed')
              AND next_run_at IS NOT NULL AND next_run_at <= ?
            """,
            (current.isoformat(),),
        ).fetchall()
        for row in overdue:
            conn.execute(
                "UPDATE history_schedules SET status = 'scheduled', next_run_at = ?, updated_at = ? WHERE group_id = ?",
                (_next_future_run(row["enabled_at"], int(row["interval_hours"]), current).isoformat(), current.isoformat(), row["group_id"]),
            )
        _pause_expired_schedules(conn, current)


def evaluate_schedule_alert(group_id: str, batch_id: str) -> dict[str, Any]:
    with _connect() as conn:
        _ensure_schema(conn)
        schedule = conn.execute(
            """
            SELECT s.*, g.origin_display, g.destination_displays_json, g.currency
            FROM history_schedules s JOIN history_groups g ON g.id = s.group_id
            WHERE s.group_id = ? AND s.enabled = 1
            """,
            (group_id,),
        ).fetchone()
        if schedule is None or not bool(schedule["notification_enabled"]):
            return {"should_notify": False, "reason": "notification_disabled", "channels": {"desktop": False, "reminders": False}}
        belongs = conn.execute(
            "SELECT 1 FROM history_group_batches WHERE group_id = ? AND batch_id = ?",
            (group_id, batch_id),
        ).fetchone()
        if belongs is None:
            return {"should_notify": False, "reason": "batch_not_in_group", "channels": {"desktop": False, "reminders": False}}
        route = conn.execute(
            """
            SELECT total_price_cny, outbound_purchase_url, inbound_purchase_url, rendered_json
            FROM route_records WHERE batch_id = ? ORDER BY total_price_cny ASC, rank ASC LIMIT 1
            """,
            (batch_id,),
        ).fetchone()
        if route is None:
            return {"should_notify": False, "reason": "no_results", "channels": {"desktop": False, "reminders": False}}
        price = int(route["total_price_cny"])
        threshold = int(schedule["price_threshold"] or 0)
        if threshold <= 0 or price >= threshold:
            result = {
                "should_notify": False, "reason": "threshold_not_met", "price": price,
                "threshold": threshold, "channels": {"desktop": False, "reminders": False},
            }
            log_event("alert.evaluated", group_id=group_id, batch_id=batch_id, **result)
            return result
        desktop_last = schedule["desktop_last_notified_price"]
        reminder_last = schedule["reminder_last_notified_price"]
        channels = {
            "desktop": desktop_last is None or price < int(desktop_last),
            "reminders": reminder_last is None or price < int(reminder_last),
        }
        rendered = json.loads(route["rendered_json"])
        result = {
            "should_notify": any(channels.values()),
            "reason": "new_low" if any(channels.values()) else "already_notified",
            "group_id": group_id,
            "batch_id": batch_id,
            "title": f"{schedule['origin_display']} → {' / '.join(json.loads(schedule['destination_displays_json']))}",
            "currency": schedule["currency"],
            "price": price,
            "threshold": threshold,
            "channels": channels,
            "purchase_links": rendered.get("purchase_links") or {
                "outbound": {"url": route["outbound_purchase_url"]},
                "inbound": {"url": route["inbound_purchase_url"]},
            },
        }
        log_event("alert.evaluated", group_id=group_id, batch_id=batch_id, price=price, threshold=threshold, channels=channels)
        return result


def record_schedule_alert_delivery(
    group_id: str,
    channel: str,
    price: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if channel not in {"desktop", "reminders"}:
        raise ValueError("未知提醒渠道")
    value = int(price)
    if value <= 0:
        raise ValueError("提醒价格必须大于 0")
    current = _as_utc(now or datetime.now(timezone.utc)).isoformat()
    price_column = "desktop_last_notified_price" if channel == "desktop" else "reminder_last_notified_price"
    time_column = "desktop_last_notified_at" if channel == "desktop" else "reminder_last_notified_at"
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM history_schedules WHERE group_id = ? AND enabled = 1", (group_id,)).fetchone()
        if row is None:
            raise ValueError("定时自动搜索未启用")
        previous = row[price_column]
        if previous is None or value < int(previous):
            conn.execute(
                f"UPDATE history_schedules SET {price_column} = ?, {time_column} = ?, updated_at = ? WHERE group_id = ?",
                (value, current, current, group_id),
            )
        updated = conn.execute("SELECT * FROM history_schedules WHERE group_id = ?", (group_id,)).fetchone()
    log_event("alert.delivery_recorded", group_id=group_id, channel=channel, price=value)
    return {"group_id": group_id, "channel": channel, "price": updated[price_column], "sent_at": updated[time_column]}


def _batch_payload(row: sqlite3.Row) -> dict[str, Any]:
    destinations = json.loads(row["destinations_json"])
    return {
        "id": row["id"], "created_at": row["created_at"], "provider": row["provider"],
        "origin": row["origin"], "destinations": destinations, "departure": row["departure"],
        "return_date": row["return_date"], "cabin_class": row["cabin_class"],
        "result_count": row["result_count"],
        "minimum_price_cny": row["minimum_price_cny"] if "minimum_price_cny" in row.keys() else None,
        "label": _batch_label(row["created_at"], row["origin"], destinations, row["result_count"], row["cabin_class"]),
    }


def _batch_label(created_at: str, origin: str, destinations: list[str], result_count: int, cabin_class: str) -> str:
    timestamp = _local_timestamp(created_at)
    cabin_label = {"ECONOMY": "经济舱", "PREMIUM_ECONOMY": "超级经济舱", "BUSINESS": "商务舱", "FIRST": "头等舱"}.get(cabin_class, cabin_class)
    return f"{timestamp} · {origin} -> {'/'.join(destinations)} · {result_count} 条 · {cabin_label}"


def _local_timestamp(created_at: str, local_timezone: tzinfo | None = None) -> str:
    value = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(local_timezone).strftime("%Y-%m-%d %H:%M")


def _route_key(row: dict[str, Any]) -> str:
    return json.dumps({"total": row.get("total_price_cny"), "outbound": _segment_key(row.get("outbound")), "inbound": _segment_key(row.get("inbound"))}, ensure_ascii=False, sort_keys=True)


def _segment_key(leg: Any) -> list[tuple[Any, ...]]:
    if not isinstance(leg, dict):
        return []
    return [(segment.get("flight_number"), segment.get("origin_airport"), segment.get("destination_airport"), segment.get("departure_time")) for segment in leg.get("segments", []) if isinstance(segment, dict)]


def _total_layover_hours(row: dict[str, Any]) -> float:
    return float((row.get("outbound") or {}).get("layover_hours_total") or 0) + float((row.get("inbound") or {}).get("layover_hours_total") or 0)


def _layover_cities(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for direction in ("outbound", "inbound"):
        values.extend((row.get(direction) or {}).get("layover_cities") or [])
    return list(dict.fromkeys(values))


def _layover_airports(row: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for direction in ("outbound", "inbound"):
        values.extend((row.get(direction) or {}).get("layovers") or [])
    return values


def _purchase_url(row: dict[str, Any], direction: str) -> str | None:
    return ((row.get("purchase_links") or {}).get(direction) or {}).get("url")
