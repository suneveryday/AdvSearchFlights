from __future__ import annotations

import argparse
import asyncio
import json
import sys

from pydantic import ValidationError

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.domain.models import OutputFormat, SearchRequest
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
    search_parser.add_argument("--limit", type=int, default=None, help="最多输出多少条组合")
    search_parser.add_argument("--cooldown-seconds", type=int, default=90, help="限流冷却秒数，默认 90")
    search_parser.add_argument("--retry-waits", default="30,60,90", help="失败重试等待秒数，默认 30,60,90")
    search_parser.add_argument("--no-cooldown", action="store_true", help="本次 CLI 搜索跳过 90 秒冷却，适合本地验证")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
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


def _parse_retry_waits(value: str) -> tuple[int, ...]:
    waits = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not waits:
        raise argparse.ArgumentTypeError("--retry-waits 至少需要一个秒数")
    return waits


def _validation_message(exc: ValidationError) -> str:
    first_error = exc.errors()[0]
    message = str(first_error.get("msg", exc))
    return message.removeprefix("Value error, ").strip()


if __name__ == "__main__":
    main()
