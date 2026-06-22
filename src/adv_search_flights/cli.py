from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from pydantic import ValidationError

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.domain.models import OutputFormat, SearchRequest
from adv_search_flights.diagnostics import configure_logging, log_event, log_path, read_recent_logs
from adv_search_flights.history import (
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
from adv_search_flights.network import diagnose_network, diagnose_network_modules, provider_status
from adv_search_flights.providers import build_provider
from adv_search_flights.search.engine import FlightSearchEngine


def main() -> None:
    parser = argparse.ArgumentParser(prog="adv-search-flights", description="AdvSearchFlights")
    subparsers = parser.add_subparsers(dest="command")

    search_parser = subparsers.add_parser("search", help="执行一次复杂航班搜索")
    search_parser.add_argument("--origin", required=True, help="出发城市，中文名或 IATA 代码")
    search_parser.add_argument("--dest", nargs="+", required=True, help="候选目的地城市，1 到 5 个；1 个生成往返，2 个不同目的地生成开口航线")
    search_parser.add_argument("--departure", required=True, help="去程日期 YYYY-MM-DD")
    search_parser.add_argument("--return-date", required=True, help="回程日期 YYYY-MM-DD")
    search_parser.add_argument("--format", choices=[item.value for item in OutputFormat], default="table", help="输出格式：table、text、json")
    search_parser.add_argument("--provider", choices=["auto", "mock", "fli", "skyscanner"], default="auto", help="数据源：auto 优先 fli，失败后尝试 Skyscanner")
    search_parser.add_argument("--max-stops", type=int, default=1, help="每段单程最多中转次数，默认 1")
    search_parser.add_argument("--max-layover-hours", type=float, default=10.0, help="每次中转最长停留小时数，默认 10")
    search_parser.add_argument("--adults", type=int, default=1, help="成人乘客数，默认 1")
    search_parser.add_argument("--currency", default="CNY", help="输出币种，默认 CNY")
    search_parser.add_argument("--cabin-class", choices=["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"], default="ECONOMY", help="舱位，默认 ECONOMY")
    search_parser.add_argument("--limit", type=int, default=None, help="最多输出多少条组合")
    search_parser.add_argument("--cooldown-seconds", type=int, default=90, help="相邻请求冷却秒数，默认 90")
    search_parser.add_argument("--retry-waits", default="30,60,90", help="普通失败重试等待秒数，默认 30,60,90")
    search_parser.add_argument("--no-cooldown", action="store_true", help="本次 CLI 搜索跳过请求冷却，适合本地验证")

    gui_parser = subparsers.add_parser("gui-search", help="从 stdin 读取 JSON，输出适合桌面 GUI 使用的 JSON envelope")
    gui_parser.add_argument("--skip-network-check", action="store_true", help="跳过 Google Flights 连通性预检，适合测试或离线 UI 调试")
    gui_parser.add_argument("--stream", action="store_true", help="以 NDJSON 输出搜索进度事件，最后输出 completed/failed 事件")

    network_parser = subparsers.add_parser("network-check", help="输出桌面 GUI 使用的模块化网络检测结果")
    network_parser.add_argument("--provider", choices=["auto", "mock", "fli", "skyscanner"], default="fli")
    network_parser.add_argument("--mode", choices=["startup", "manual"], default="manual")
    network_parser.add_argument("--format", choices=["json"], default="json")

    history_list_parser = subparsers.add_parser("history-list", help="列出本地历史搜索批次")
    history_list_parser.add_argument("--format", choices=["json"], default="json")
    history_list_parser.add_argument("--limit", type=int, default=50)

    history_get_parser = subparsers.add_parser("history-get", help="读取一个本地历史搜索批次")
    history_get_parser.add_argument("batch_id")
    history_get_parser.add_argument("--format", choices=["json"], default="json")

    history_group_list_parser = subparsers.add_parser("history-group-list", help="列出聚合后的本地搜索历史")
    history_group_list_parser.add_argument("--format", choices=["json"], default="json")
    history_group_list_parser.add_argument("--limit", type=int, default=100)

    history_group_get_parser = subparsers.add_parser("history-group-get", help="读取聚合历史组及其搜索批次")
    history_group_get_parser.add_argument("group_id")
    history_group_get_parser.add_argument("--format", choices=["json"], default="json")

    history_group_results_parser = subparsers.add_parser("history-group-results", help="筛选聚合历史组并计算价格趋势")
    history_group_results_parser.add_argument("group_id")
    history_group_results_parser.add_argument("--batch-id", default=None)
    history_group_results_parser.add_argument("--filters", default="{}", help="结构化筛选 JSON")
    history_group_results_parser.add_argument("--format", choices=["json"], default="json")

    history_group_delete_parser = subparsers.add_parser("history-group-delete", help="删除聚合历史组及其完整搜索批次")
    history_group_delete_parser.add_argument("group_id")
    history_group_delete_parser.add_argument("--format", choices=["json"], default="json")

    history_schedule_list_parser = subparsers.add_parser("history-schedule-list", help="列出启用的定时自动搜索")
    history_schedule_list_parser.add_argument("--format", choices=["json"], default="json")

    history_schedule_toggle_parser = subparsers.add_parser("history-schedule-toggle", help="启用或关闭历史组定时搜索")
    history_schedule_toggle_parser.add_argument("group_id")
    history_schedule_toggle_parser.add_argument("--enabled", choices=["true", "false"], required=True)
    history_schedule_toggle_parser.add_argument("--interval-hours", type=int, default=8)
    history_schedule_toggle_parser.add_argument("--notification-enabled", choices=["true", "false"], default="false")
    history_schedule_toggle_parser.add_argument("--price-threshold", type=int, default=None)
    history_schedule_toggle_parser.add_argument("--format", choices=["json"], default="json")

    history_schedule_claim_parser = subparsers.add_parser("history-schedule-claim-due", help="领取一个到期定时任务")
    history_schedule_claim_parser.add_argument("--format", choices=["json"], default="json")

    history_schedule_update_parser = subparsers.add_parser("history-schedule-update", help="更新定时任务运行状态")
    history_schedule_update_parser.add_argument("group_id")
    history_schedule_update_parser.add_argument("--status", required=True)
    history_schedule_update_parser.add_argument("--error", default=None)
    history_schedule_update_parser.add_argument("--format", choices=["json"], default="json")

    history_schedule_reset_parser = subparsers.add_parser("history-schedule-reset-runtime", help=argparse.SUPPRESS)
    history_schedule_reset_parser.add_argument("--format", choices=["json"], default="json")

    history_schedule_alert_parser = subparsers.add_parser("history-schedule-evaluate-alert", help=argparse.SUPPRESS)
    history_schedule_alert_parser.add_argument("group_id")
    history_schedule_alert_parser.add_argument("batch_id")
    history_schedule_alert_parser.add_argument("--format", choices=["json"], default="json")

    history_schedule_record_parser = subparsers.add_parser("history-schedule-record-alert", help=argparse.SUPPRESS)
    history_schedule_record_parser.add_argument("group_id")
    history_schedule_record_parser.add_argument("--channel", choices=["desktop", "reminders"], required=True)
    history_schedule_record_parser.add_argument("--price", type=int, required=True)
    history_schedule_record_parser.add_argument("--format", choices=["json"], default="json")

    app_settings_get_parser = subparsers.add_parser("app-settings-get", help="读取桌面应用设置")
    app_settings_get_parser.add_argument("--format", choices=["json"], default="json")

    app_settings_update_parser = subparsers.add_parser("app-settings-update", help="更新桌面应用设置")
    app_settings_update_parser.add_argument("--rate-limit-retry-minutes", type=int)
    app_settings_update_parser.add_argument("--analytics-consent", choices=["unset", "granted", "denied"])
    app_settings_update_parser.add_argument("--http-proxy")
    app_settings_update_parser.add_argument("--all-proxy")
    app_settings_update_parser.add_argument("--format", choices=["json"], default="json")

    diagnostics_parser = subparsers.add_parser("diagnostics-log", help="查看本地诊断日志")
    diagnostics_parser.add_argument("--tail", type=int, default=200)
    diagnostics_parser.add_argument("--format", choices=["json"], default="json")

    diagnostics_event_parser = subparsers.add_parser("diagnostics-event", help=argparse.SUPPRESS)
    diagnostics_event_parser.add_argument("event")
    diagnostics_event_parser.add_argument("--fields", default="{}")

    args = parser.parse_args()
    configure_logging()
    if args.command is None:
        parser.print_help()
        return
    if args.command == "gui-search":
        asyncio.run(_run_gui_search_command(args))
        return
    if args.command == "network-check":
        print(json.dumps(diagnose_network_modules(args.provider, mode=args.mode), ensure_ascii=False, indent=2))
        return
    if args.command == "history-list":
        print(json.dumps({"items": list_history(args.limit)}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-get":
        item = get_history(args.batch_id)
        print(json.dumps({"item": item}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-group-list":
        print(json.dumps({"items": list_history_groups(args.limit)}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-group-get":
        print(json.dumps({"item": get_history_group(args.group_id)}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-group-results":
        try:
            filters = json.loads(args.filters)
        except json.JSONDecodeError as exc:
            parser.error(f"--filters 不是有效 JSON：{exc}")
        item = get_history_group_results(args.group_id, batch_id=args.batch_id, filters=filters)
        print(json.dumps({"item": item}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-group-delete":
        print(json.dumps({"deleted": delete_history_group(args.group_id)}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-schedule-list":
        print(json.dumps({"items": list_history_schedules()}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-schedule-toggle":
        try:
            item = toggle_history_schedule(
                args.group_id,
                args.enabled == "true",
                interval_hours=args.interval_hours,
                notification_enabled=args.notification_enabled == "true",
                price_threshold=args.price_threshold,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps({"item": item}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-schedule-claim-due":
        print(json.dumps({"item": claim_due_history_schedule()}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-schedule-update":
        try:
            item = update_history_schedule_status(args.group_id, args.status, error=args.error)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps({"item": item}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-schedule-reset-runtime":
        reset_schedule_runtime_states()
        print(json.dumps({"ok": True}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-schedule-evaluate-alert":
        print(json.dumps({"item": evaluate_schedule_alert(args.group_id, args.batch_id)}, ensure_ascii=False, indent=2))
        return
    if args.command == "history-schedule-record-alert":
        try:
            item = record_schedule_alert_delivery(args.group_id, args.channel, args.price)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps({"item": item}, ensure_ascii=False, indent=2))
        return
    if args.command == "app-settings-get":
        print(json.dumps({"item": get_app_settings()}, ensure_ascii=False, indent=2))
        return
    if args.command == "app-settings-update":
        try:
            item = update_app_settings(
                rate_limit_retry_minutes=args.rate_limit_retry_minutes,
                analytics_consent=args.analytics_consent,
                http_proxy=args.http_proxy,
                all_proxy=args.all_proxy,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps({"item": item}, ensure_ascii=False, indent=2))
        return
    if args.command == "diagnostics-log":
        print(json.dumps({"path": str(log_path()), "items": read_recent_logs(args.tail)}, ensure_ascii=False, indent=2))
        return
    if args.command == "diagnostics-event":
        try:
            fields = json.loads(args.fields)
        except json.JSONDecodeError as exc:
            parser.error(f"--fields 不是有效 JSON：{exc}")
        log_event(args.event, **fields)
        print(json.dumps({"ok": True}))
        return
    asyncio.run(_run_search(args))


async def _run_search(args: argparse.Namespace) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        request = SearchRequest(
            origin=args.origin,
            destinations=args.dest,
            departure=args.departure,
            return_date=args.return_date,
            output_format=args.format,
            provider=args.provider,
            max_stops=args.max_stops,
            max_layover_hours=args.max_layover_hours,
            adults=args.adults,
            currency=args.currency,
            cabin_class=args.cabin_class,
            limit=args.limit,
        )
    except ValidationError as exc:
        print(f"参数错误：{_validation_message(exc)}", file=sys.stderr)
        raise SystemExit(2) from exc
    controller = DataCallController(
        cooldown_seconds=0 if args.no_cooldown else args.cooldown_seconds,
        retry_delays=_parse_retry_waits(args.retry_waits),
    )
    response = await FlightSearchEngine(build_provider(request.provider), controller=controller).search(request)
    if request.output_format == OutputFormat.json:
        print(json.dumps(response.rendered, ensure_ascii=False, indent=2))
        return
    print(response.rendered)


async def _run_gui_search_command(args: argparse.Namespace) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raw_input = sys.stdin.read()
    if args.stream:
        await run_gui_search_stream(raw_input, check_network=not args.skip_network_check)
        return
    envelope = await run_gui_search_payload(raw_input, check_network=not args.skip_network_check)
    print(json.dumps(envelope, ensure_ascii=False, indent=2))


async def run_gui_search_stream(raw_input: str | dict, *, check_network: bool = True, emit=None) -> dict:
    def emit_event(event: dict) -> None:
        if emit:
            emit(event)
        else:
            print(json.dumps(event, ensure_ascii=False), flush=True)

    envelope = await run_gui_search_payload(raw_input, check_network=check_network, event_callback=emit_event)
    final_type = "completed" if envelope.get("ok") else "failed"
    emit_event({"type": final_type, "envelope": envelope})
    return envelope


async def run_gui_search_payload(raw_input: str | dict, *, check_network: bool = True, event_callback=None) -> dict:
    try:
        payload = json.loads(raw_input) if isinstance(raw_input, str) else dict(raw_input)
    except json.JSONDecodeError as exc:
        envelope = _gui_error("invalid_json", f"无法解析 JSON：{exc}", provider="unknown", network_status=None)
        if event_callback:
            event_callback({"type": "failed", "message": envelope["error"]["message"]})
        return envelope

    request_payload = _normalize_gui_payload(payload)
    provider_name = str(request_payload.get("provider") or "auto")
    try:
        request = SearchRequest(**request_payload)
    except ValidationError as exc:
        envelope = _gui_error("validation_error", _validation_message(exc), provider=provider_name, network_status=None)
        if event_callback:
            event_callback({"type": "failed", "message": envelope["error"]["message"]})
        return envelope

    network_status = diagnose_network(request.provider.value, check_google=check_network).payload()
    if event_callback:
        event_callback({"type": "network_check", "network_status": network_status, "message": f"网络预检：{network_status['status']}"})
    controller = DataCallController(
        cooldown_seconds=0 if bool(payload.get("no_cooldown")) else int(payload.get("cooldown_seconds", 90)),
        retry_delays=_parse_gui_retry_waits(payload.get("retry_waits", "30,60,90")),
        event_callback=event_callback,
    )

    timeout_seconds = _parse_gui_timeout(payload.get("gui_timeout_seconds"))
    fli_timeout_seconds = _parse_optional_positive_int(payload.get("fli_timeout_seconds"))
    previous_fli_timeout = os.environ.get("FLI_TIMEOUT_SECONDS")
    if fli_timeout_seconds:
        os.environ["FLI_TIMEOUT_SECONDS"] = str(fli_timeout_seconds)

    try:
        search_operation = FlightSearchEngine(
            build_provider(request.provider),
            controller=controller,
            event_callback=event_callback,
            max_concurrency=_parse_max_concurrency(payload.get("max_concurrent_searches")),
        ).search(request)
        response = await asyncio.wait_for(search_operation, timeout=timeout_seconds) if timeout_seconds else await search_operation
    except asyncio.TimeoutError:
        destination_count = len(request.destinations)
        timeout_hint = (
            "候选目的地较多，单程查询数量会明显增加。可以提高总超时、减少城市数量，或先用较少目的地验证网络后重试。"
            if destination_count >= 5
            else "可以减少目的地、提高单段或总超时后重试。"
        )
        envelope = _gui_error(
            "search_timeout",
            f"搜索超过 {timeout_seconds} 秒，已自动中止。{timeout_hint}",
            provider=request.provider.value,
            network_status=network_status,
            warnings=[],
        )
        if event_callback:
            event_callback({"type": "failed", "message": envelope["error"]["message"]})
        return envelope
    except Exception as exc:  # noqa: BLE001
        envelope = _gui_error(
            "search_error",
            str(exc),
            provider=request.provider.value,
            network_status=network_status,
            warnings=[],
        )
        if event_callback:
            event_callback({"type": "failed", "message": envelope["error"]["message"]})
        return envelope
    finally:
        if fli_timeout_seconds:
            if previous_fli_timeout is None:
                os.environ.pop("FLI_TIMEOUT_SECONDS", None)
            else:
                os.environ["FLI_TIMEOUT_SECONDS"] = previous_fli_timeout

    history_batch_id = _save_history(response)
    status = provider_status(request.provider.value, response.result_count, response.warnings)
    return {
        "ok": True,
        "response": response.model_dump(mode="json"),
        "network_status": network_status,
        "provider_status": status.model_dump(mode="json"),
        "history_batch_id": history_batch_id,
        "error": None,
    }


def _parse_retry_waits(value: str) -> tuple[int, ...]:
    waits = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not waits:
        raise argparse.ArgumentTypeError("--retry-waits 至少需要一个秒数")
    return waits


def _parse_rate_limit_retry_minutes(value) -> int:
    minutes = int(value)
    if not 5 <= minutes <= 20:
        raise argparse.ArgumentTypeError("限频重试等待需设置为 5 到 20 分钟")
    return minutes


def _parse_gui_retry_waits(value) -> tuple[int, ...]:
    if isinstance(value, list | tuple):
        waits = tuple(int(item) for item in value)
        return waits or (30, 60, 90)
    return _parse_retry_waits(str(value))


def _parse_gui_timeout(value) -> int | None:
    timeout = _parse_optional_positive_int(value)
    if timeout is None:
        return 240
    return timeout


def _parse_optional_positive_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_max_concurrency(value) -> int:
    parsed = _parse_optional_positive_int(value)
    if parsed is None:
        return 1
    return min(parsed, 6)


def _normalize_gui_payload(payload: dict) -> dict:
    normalized = dict(payload)
    if "format" in normalized and "output_format" not in normalized:
        normalized["output_format"] = normalized.pop("format")
    normalized.setdefault("output_format", "json")
    if normalized.get("limit") == 0:
        normalized["limit"] = None
    return {
        key: value
        for key, value in normalized.items()
        if key
        in {
            "origin",
            "destinations",
            "departure",
            "return_date",
            "output_format",
            "provider",
            "max_stops",
            "max_layover_hours",
            "adults",
            "currency",
            "cabin_class",
            "limit",
        }
    }


def _save_history(response) -> str | None:
    try:
        return save_search_response(response)
    except Exception as exc:  # noqa: BLE001
        response.warnings.append(f"历史记录保存失败：{exc}")
        return None


def _gui_error(
    error_type: str,
    message: str,
    *,
    provider: str,
    network_status: dict | None,
    warnings: list[str] | None = None,
) -> dict:
    warnings = warnings or []
    return {
        "ok": False,
        "response": None,
        "network_status": network_status,
        "provider_status": provider_status(provider, 0, warnings).model_dump(mode="json"),
        "error": {"type": error_type, "message": message},
    }


def _validation_message(exc: ValidationError) -> str:
    first_error = exc.errors()[0]
    message = str(first_error.get("msg", exc))
    return message.removeprefix("Value error, ").strip()


if __name__ == "__main__":
    main()
