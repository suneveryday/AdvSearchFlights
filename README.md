# Farello

新版本给这个小工具起了一个名字：Farello
Farello 是一个航班复杂搜索工具，用于多目的地候选、开口航线组合和价格排序。同时具备设置自动定时搜索并通过Apple reminds提醒。

当前数据源以 Google Flights 为主，航班请求都是由用户本机网络发起。

## 核心功能

- 出发地支持中文城市名或 IATA 机场代码，单选输入。
- 目的地支持 1 到 4 个候选城市或机场。
- 城市会自动展开为多个机场，例如 `上海 -> PVG/SHA`、`北京 -> PEK/PKX`。
- 选择 1 个目的地时，生成同一城市到达和返回的往返航班。
- 选择 2 个或更多候选目的地时，从候选城市中组合往返和不走回头路的开口航线。
- 每段单程默认过滤：中转次数 `<= 1`，单次中转停留 `<= 10` 小时。
- 输出机场三字码、机场中文名、航空公司中文名称、航班号、执飞机型、起降时间、中转机场、中转停留小时数和单程价格。
- 支持舱位选择：经济舱、超级经济舱、商务舱、头等舱。
- 历史组可开启 1–48 小时定时搜索，默认 8 小时，最多同时启用 5 组；确认设置后立即搜索一次，后续仅在 App 运行期间执行。
- 定时搜索可设置价格阈值；最低往返总价严格低于阈值时，通过 macOS 桌面通知和 Apple Reminders 提醒，之后仅在出现更低价格时再次提醒。

### 匿名使用统计
Farello 仅在首次启动得到明确授权后初始化 PostHog。用户可以在“设置 → 隐私与统计”中随时关闭。统计只包含应用版本、系统平台、工作区、搜索是否成功、结果数量区间、耗时区间、标准化错误类别、定时搜索配置和提醒渠道是否成功。
以下内容永不上传：航线、日期、机场、价格、搜索输入和结果、历史组或批次 ID、购买链接、提醒阈值、原始错误、姓名、邮箱、账号或硬件标识。应用使用本地 SQLite 中随机生成的匿名安装 ID，不启用自动点击采集、页面浏览、Session Replay 或用户画像。

历史组的闹钟按钮用于配置定时搜索。提醒功能需要检查以下系统权限：
- `系统设置 → 通知 → Farello`
- `系统设置 → 隐私与安全性 → 自动化 → Reminders`


## 安装

```powershell
cd AdvSearchFlights
python -m pip install -e ".[dev]"
```

仅安装运行依赖：

```powershell
python -m pip install -r requirements.txt
```

## CLI 命令

```powershell
adv-search-flights search --origin 北京 --dest 上海 --departure 2026-06-20 --return-date 2026-06-26 --provider auto --format table
```

GUI JSON 协议示例：

```bash
printf '%s' '{
  "origin": "上海",
  "destinations": ["墨尔本", "悉尼"],
  "departure": "2026-09-29",
  "return_date": "2026-10-07",
  "provider": "mock",
  "format": "json",
  "cabin_class": "ECONOMY",
  "limit": 50,
  "no_cooldown": true,
  "retry_waits": [0, 0, 0]
}' | adv-search-flights gui-search --skip-network-check
```

`gui-search` 输出固定 JSON envelope：

- `ok`：本次调用是否完成。
- `response`：完整 `SearchResponse` JSON，包含 `result_count`、`results`、`rendered`、`warnings`。
- `network_status`：代理、`fli` CLI、Google Flights 连通性检查结果。
- `provider_status`：数据源运行状态、warning 分类、结果数量。
- `error`：参数错误、搜索错误或 JSON 解析错误。
- `history_batch_id`：真实搜索结果成功保存后的本地历史批次 ID；mock 搜索固定为空。

完整示例：

```powershell
adv-search-flights search `
  --origin 上海 `
  --dest 东京 静冈 `
  --departure 2026-06-29 `
  --return-date 2026-07-07 `
  --provider auto `
  --format table `
  --max-stops 1 `
  --max-layover-hours 10 `
  --adults 1 `
  --currency CNY `
  --cabin-class ECONOMY `
  --limit 20 `
  --cooldown-seconds 90 `
  --retry-waits 30,60,90
```

## 参数说明

| CLI 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `--origin` | 是 | - | 出发城市或机场，支持中文名或 IATA 代码；城市会展开为全部已知机场。 |
| `--dest` | 是 | - | 候选目的地列表，支持 1 到 5 个中文城市名或 IATA 代码；1 个目的地生成往返，2 个或更多候选目的地可生成开口航线。 |
| `--departure` | 是 | - | 去程日期，格式 `YYYY-MM-DD`。 |
| `--return-date` | 是 | - | 回程日期，格式 `YYYY-MM-DD`。 |
| `--provider` | 否 | `auto` | 数据源：`auto`、`fli`、`skyscanner`、`mock`。 |
| `--format` | 否 | `table` | 输出格式：`table`、`text`、`json`。 |
| `--max-stops` | 否 | `1` | 每段单程允许的最大中转次数。 |
| `--max-layover-hours` | 否 | `10` | 每次中转允许的最长停留小时数。 |
| `--adults` | 否 | `1` | 成人乘客数。 |
| `--currency` | 否 | `CNY` | 输出和排序币种。当前总价以人民币展示。 |
| `--cabin-class` | 否 | `ECONOMY` | 舱位：`ECONOMY`、`PREMIUM_ECONOMY`、`BUSINESS`、`FIRST`。 |
| `--limit` | 否 | 无限制 | 最多返回多少条组合结果；筛选排序完成后再截取。 |
| `--cooldown-seconds` | 否 | `90` | 每次真实数据调用之间的冷却秒数。 |
| `--retry-waits` | 否 | `30,60,90` | 失败重试等待秒数，逗号分隔。 |
| `--no-cooldown` | 否 | 关闭 | 本次 CLI 搜索跳过冷却，适合本地验证。 |

## 输出字段

所有输出格式都会按总价从低到高排序，并包含以下字段：

- 总价
- 去程行程
- 去程每段航线起降时间
- 去程中转次数和停留时间
- 去程价格
- 回程行程
- 回程每段航线起降时间
- 回程中转次数和停留时间
- 回程价格

每段航线都会展示：

- 机场三字码
- 机场中文名
- 航空公司中文名称
- 航班号
- 执飞机型
- 起飞时间
- 到达时间

历史 CLI：

```bash
adv-search-flights history-list --format json
adv-search-flights history-get <batch_id> --format json
adv-search-flights history-group-list --format json
adv-search-flights history-group-get <group_id> --format json
adv-search-flights history-group-results <group_id> --filters '{"max_total_price": 10000}' --format json
adv-search-flights history-group-delete <group_id> --format json
```

GUI 的独立历史工作区支持价格上限、包含/排除航司、起降机场、中转次数、单次停留和排除中转机场筛选。某批次无匹配结果时，趋势图保留时间点并显示断点。

## Python 调用

```python
import asyncio

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.domain.models import SearchRequest
from adv_search_flights.providers import build_provider
from adv_search_flights.search.engine import FlightSearchEngine


async def main():
    request = SearchRequest(
        origin="上海",
        destinations=["东京", "静冈"],
        departure="2026-06-29",
        return_date="2026-07-07",
        provider="auto",
        output_format="json",
        max_stops=1,
        max_layover_hours=10,
        adults=1,
        currency="CNY",
        cabin_class="ECONOMY",
        limit=20,
    )
    engine = FlightSearchEngine(
        provider=build_provider(request.provider),
        controller=DataCallController(cooldown_seconds=90),
    )
    response = await engine.search(request)
    print(response.rendered)


asyncio.run(main())
```

## 数据源配置

Google Flights / `fli` 默认 15 秒超时：

```powershell
$env:FLI_QUERY_CURRENCY="USD"
$env:FLI_LANGUAGE="en-US"
$env:FLI_COUNTRY="US"
$env:FLI_TIMEOUT_SECONDS="15"
$env:FLIGHT_USD_CNY_RATE="7.2"
```

## 引用源

本项目的数据源适配参考以下开源项目：

- Google Flights / `fli`: https://github.com/punitarani/fli
- Skyscanner experimental fallback: https://github.com/irrisolto/skyscanner

Farello 使用 MIT License 发布。可选第三方数据源库可能使用各自的许可证；安装或使用这些库时，请自行阅读并遵守对应许可证条款。

## 测试

```powershell
python -m pytest
```

---

下面是英文版：

Farello

The new version of this small utility has been given a name: Farello.

Farello is an advanced flight search tool designed for multi-destination candidates, open-jaw route combinations, and price ranking. It also supports automatic scheduled searches and reminders through Apple Reminders.

The current primary data source is Google Flights, and all flight requests are initiated through the user’s local network.

Core Features

* The origin supports either a Chinese city name or an IATA airport code, with single-selection input.
* Destinations support 1 to 5 candidate cities or airports.
* Cities are automatically expanded into multiple airports, for example: Shanghai -> PVG/SHA, Beijing -> PEK/PKX.
* When 1 destination is selected, Farello generates round-trip flights arriving at and returning from the same city.
* When 2 or more candidate destinations are selected, Farello generates round-trip and non-backtracking open-jaw route combinations from the candidate cities.
* Each one-way segment is filtered by default with: number of stops <= 1, and each layover duration <= 10 hours.
* Output includes airport three-letter codes, Chinese airport names, Chinese airline names, flight numbers, aircraft type, departure and arrival times, layover airports, layover duration in hours, and one-way prices.
* Cabin class selection is supported: Economy, Premium Economy, Business, and First Class.
* Historical groups can enable scheduled searches from 1 to 48 hours, with a default interval of 8 hours. Up to 5 groups can be enabled at the same time. After confirmation, Farello runs one search immediately; subsequent scheduled searches only run while the app is open.
* Scheduled searches can include a price threshold. When the lowest round-trip total price is strictly lower than the threshold, Farello sends a macOS desktop notification and an Apple Reminders reminder. After that, it only reminds again when an even lower price appears.

Anonymous Usage Analytics

Farello only initializes PostHog after explicit authorization on first launch. Users can disable it at any time in Settings → Privacy & Analytics.

Analytics only include the app version, system platform, workspace, whether the search succeeded, result count range, duration range, standardized error category, scheduled search configuration, and whether reminder channels succeeded.

The following content is never uploaded: routes, dates, airports, prices, search inputs and results, historical group or batch IDs, purchase links, reminder thresholds, raw errors, names, email addresses, accounts, or hardware identifiers.

The app uses a randomly generated anonymous installation ID stored in the local SQLite database. It does not enable automatic click tracking, page view tracking, Session Replay, or user profiles.

The alarm button in a historical group is used to configure scheduled searches. The reminder feature requires checking the following system permissions:

* System Settings → Notifications → Farello
* System Settings → Privacy & Security → Automation → Reminders

Installation

cd AdvSearchFlights
python -m pip install -e ".[dev]"

Install runtime dependencies only:

python -m pip install -r requirements.txt

CLI Commands

adv-search-flights search --origin 北京 --dest 上海 --departure 2026-06-20 --return-date 2026-06-26 --provider auto --format table

GUI JSON protocol example:

printf '%s' '{
  "origin": "上海",
  "destinations": ["墨尔本", "悉尼"],
  "departure": "2026-09-29",
  "return_date": "2026-10-07",
  "provider": "mock",
  "format": "json",
  "cabin_class": "ECONOMY",
  "limit": 50,
  "no_cooldown": true,
  "retry_waits": [0, 0, 0]
}' | adv-search-flights gui-search --skip-network-check

gui-search outputs a fixed JSON envelope:

* ok: Whether this invocation completed.
* response: The full SearchResponse JSON, including result_count, results, rendered, and warnings.
* network_status: Proxy, fli CLI, and Google Flights connectivity check results.
* provider_status: Data source runtime status, warning categories, and result count.
* error: Parameter errors, search errors, or JSON parsing errors.
* history_batch_id: Local historical batch ID after real search results are successfully saved; always empty for mock searches.

Full example:

adv-search-flights search `
  --origin 上海 `
  --dest 东京 静冈 `
  --departure 2026-06-29 `
  --return-date 2026-07-07 `
  --provider auto `
  --format table `
  --max-stops 1 `
  --max-layover-hours 10 `
  --adults 1 `
  --currency CNY `
  --cabin-class ECONOMY `
  --limit 20 `
  --cooldown-seconds 90 `
  --retry-waits 30,60,90

Parameters

CLI Parameter	Required	Default	Description
--origin	Yes	-	Origin city or airport. Supports Chinese names or IATA codes. Cities are expanded into all known airports.
--dest	Yes	-	Candidate destination list. Supports 1 to 5 Chinese city names or IATA codes. 1 destination generates a round trip; 2 or more candidate destinations can generate open-jaw routes.
--departure	Yes	-	Departure date in YYYY-MM-DD format.
--return-date	Yes	-	Return date in YYYY-MM-DD format.
--provider	No	auto	Data source: auto, fli, skyscanner, or mock.
--format	No	table	Output format: table, text, or json.
--max-stops	No	1	Maximum number of stops allowed for each one-way segment.
--max-layover-hours	No	10	Maximum allowed duration for each layover, in hours.
--adults	No	1	Number of adult passengers.
--currency	No	CNY	Currency used for output and sorting. Current total prices are displayed in Chinese yuan.
--cabin-class	No	ECONOMY	Cabin class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, or FIRST.
--limit	No	Unlimited	Maximum number of combined results to return. Results are truncated after filtering and sorting.
--cooldown-seconds	No	90	Cooldown seconds between real data calls.
--retry-waits	No	30,60,90	Retry wait durations after failures, separated by commas.
--no-cooldown	No	Disabled	Skip cooldown for this CLI search. Suitable for local validation.

Output Fields

All output formats are sorted by total price from low to high and include the following fields:

* Total price
* Outbound itinerary
* Departure and arrival times for each outbound segment
* Number of outbound stops and layover duration
* Outbound price
* Return itinerary
* Departure and arrival times for each return segment
* Number of return stops and layover duration
* Return price

Each flight segment displays:

* Airport three-letter code
* Chinese airport name
* Chinese airline name
* Flight number
* Aircraft type
* Departure time
* Arrival time

Historical CLI:

adv-search-flights history-list --format json
adv-search-flights history-get <batch_id> --format json
adv-search-flights history-group-list --format json
adv-search-flights history-group-get <group_id> --format json
adv-search-flights history-group-results <group_id> --filters '{"max_total_price": 10000}' --format json
adv-search-flights history-group-delete <group_id> --format json

The GUI’s standalone history workspace supports filtering by maximum price, included or excluded airlines, departure and arrival airports, number of stops, individual layover duration, and excluded layover airports.

When a batch has no matching results, the trend chart keeps the time point and displays it as a gap.

Python Usage

import asyncio
from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.domain.models import SearchRequest
from adv_search_flights.providers import build_provider
from adv_search_flights.search.engine import FlightSearchEngine
async def main():
    request = SearchRequest(
        origin="上海",
        destinations=["东京", "静冈"],
        departure="2026-06-29",
        return_date="2026-07-07",
        provider="auto",
        output_format="json",
        max_stops=1,
        max_layover_hours=10,
        adults=1,
        currency="CNY",
        cabin_class="ECONOMY",
        limit=20,
    )
    engine = FlightSearchEngine(
        provider=build_provider(request.provider),
        controller=DataCallController(cooldown_seconds=90),
    )
    response = await engine.search(request)
    print(response.rendered)
asyncio.run(main())

Data Source Configuration

Google Flights / fli uses a default timeout of 15 seconds:

$env:FLI_QUERY_CURRENCY="USD"
$env:FLI_LANGUAGE="en-US"
$env:FLI_COUNTRY="US"
$env:FLI_TIMEOUT_SECONDS="15"
$env:FLIGHT_USD_CNY_RATE="7.2"

References

This project’s data source adapters refer to the following open-source projects:

* Google Flights / fli: https://github.com/punitarani/fli
* Skyscanner experimental fallback: https://github.com/irrisolto/skyscanner

Farello is released under the MIT License. Optional third-party data source libraries may use their own licenses. Please read and comply with the corresponding license terms when installing or using those libraries.

Tests

python -m pytest
