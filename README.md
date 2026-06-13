# AdvSearchFlights

AdvSearchFlights 是一个纯 Python 后端命令行工具，用于复杂航班搜索、开口航线组合和价格排序。它以 Google Flights / `fli` 为主数据源，并支持可选的 Skyscanner 实验备用源。

## 核心功能

- 出发地支持中文城市名或 IATA 机场代码，单选输入。
- 目的地支持 1 到 5 个候选城市或机场。
- 城市会自动展开为多个机场，例如 `上海 -> PVG/SHA`、`北京 -> PEK/PKX`。
- 选择 1 个目的地时，生成同一城市到达和返回的往返航班。
- 选择 2 个或更多候选目的地时，从候选城市中组合往返和不走回头路的开口航线。
- 每段单程默认过滤：中转次数 `<= 1`，单次中转停留 `<= 10` 小时。
- 自动排除无价格航班。
- 结果按人民币总价从低到高排序。
- 输出机场三字码、机场中文名、航空公司中文名称、航班号、执飞机型、起降时间、中转机场、中转停留小时数和单程价格。
- 支持 `table`、`text`、`json` 三种输出格式。
- 真实数据调用默认 90 秒冷却，失败后按 30/60/90 秒递增等待重试。
<img width="3990" height="3946" alt="image" src="https://github.com/user-attachments/assets/fb446f58-4ac7-4f6e-86ad-2914d51be5f0" />


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

Skyscanner 是可选实验备用源。它依赖第三方仓库 `irrisolto/skyscanner`，不是本项目的默认安装依赖。使用前需要自行安装该仓库及其依赖，并确保 Python 可以导入 `skyscanner`：

```powershell
$env:SKYSCANNER_LOCALE="en-US"
$env:SKYSCANNER_MARKET="US"
$env:SKYSCANNER_CURRENCY="USD"
$env:SKYSCANNER_RETRY_DELAY="2"
$env:SKYSCANNER_MAX_RETRIES="6"
```

## 引用源

本项目的数据源适配参考以下开源项目：

- Google Flights / `fli`: https://github.com/punitarani/fli
- Skyscanner experimental fallback: https://github.com/irrisolto/skyscanner

AdvSearchFlights 使用 MIT License 发布。可选第三方数据源库可能使用各自的许可证；安装或使用这些库时，请自行阅读并遵守对应许可证条款。

## 测试

```powershell
python -m pytest
```

---

# AdvSearchFlights

AdvSearchFlights is a pure Python backend CLI tool for complex flight search, open-jaw route combination, and price sorting. It uses Google Flights / `fli` as the primary data source and supports an optional experimental Skyscanner fallback.

## Features

- Single origin input, accepting Chinese city names or IATA airport codes.
- One to five candidate destinations.
- City input expands to all known airports, for example `Shanghai -> PVG/SHA` and `Beijing -> PEK/PKX`.
- One destination creates a same-city round trip.
- Two or more candidate destinations can create both round trips and open-jaw routes that avoid returning from the same destination.
- Default filters per one-way option: stops `<= 1`, layover duration `<= 10` hours.
- Flights without price are excluded automatically.
- Results are sorted by total CNY price from low to high.
- Result details include IATA codes, Chinese airport names, Chinese airline names, flight numbers, aircraft type, departure/arrival times, layover airports, layover hours, and one-way prices.
- Output formats: `table`, `text`, `json`.
- Real data calls default to a 90-second cooldown and retry waits of 30/60/90 seconds.

## Installation

```powershell
cd AdvSearchFlights
python -m pip install -e ".[dev]"
```

Runtime dependencies only:

```powershell
python -m pip install -r requirements.txt
```

## CLI

```powershell
adv-search-flights search --origin Beijing --dest Shanghai --departure 2026-06-20 --return-date 2026-06-26 --provider auto --format table
```

Full example:

```powershell
adv-search-flights search `
  --origin Shanghai `
  --dest Tokyo Shizuoka `
  --departure 2026-06-29 `
  --return-date 2026-07-07 `
  --provider auto `
  --format table `
  --max-stops 1 `
  --max-layover-hours 10 `
  --adults 1 `
  --currency CNY `
  --limit 20 `
  --cooldown-seconds 90 `
  --retry-waits 30,60,90
```

## Parameters

| CLI option | Required | Default | Description |
|---|---:|---|---|
| `--origin` | Yes | - | Origin city or airport. Accepts Chinese names or IATA codes. City input expands to all known airports. |
| `--dest` | Yes | - | One to five candidate destination cities or airports. One destination creates a round trip; two or more candidates can create open-jaw routes. |
| `--departure` | Yes | - | Outbound date in `YYYY-MM-DD` format. |
| `--return-date` | Yes | - | Return date in `YYYY-MM-DD` format. |
| `--provider` | No | `auto` | Data source: `auto`, `fli`, `skyscanner`, `mock`. |
| `--format` | No | `table` | Output format: `table`, `text`, `json`. |
| `--max-stops` | No | `1` | Maximum stops allowed for each one-way option. |
| `--max-layover-hours` | No | `10` | Maximum layover duration per connection, in hours. |
| `--adults` | No | `1` | Number of adult passengers. |
| `--currency` | No | `CNY` | Output and sorting currency. Total price is displayed in CNY. |
| `--limit` | No | unlimited | Maximum number of combined results; applied after filtering and sorting. |
| `--cooldown-seconds` | No | `90` | Cooldown between real data calls. |
| `--retry-waits` | No | `30,60,90` | Retry waits in seconds, comma-separated. |
| `--no-cooldown` | No | off | Skip cooldown for this CLI run. Useful for local validation. |

## Output Contract

All output formats are sorted by total price from low to high and include:

- total price
- outbound itinerary
- outbound segment departure/arrival times
- outbound stop count and layover duration
- outbound price
- inbound itinerary
- inbound segment departure/arrival times
- inbound stop count and layover duration
- inbound price

Every segment includes:

- IATA airport code
- Chinese airport name
- Chinese airline name
- flight number
- aircraft type
- departure time
- arrival time

## Python Usage

```python
import asyncio

from adv_search_flights.control.rate_limit import DataCallController
from adv_search_flights.domain.models import SearchRequest
from adv_search_flights.providers import build_provider
from adv_search_flights.search.engine import FlightSearchEngine


async def main():
    request = SearchRequest(
        origin="Shanghai",
        destinations=["Tokyo", "Shizuoka"],
        departure="2026-06-29",
        return_date="2026-07-07",
        provider="auto",
        output_format="json",
        max_stops=1,
        max_layover_hours=10,
        adults=1,
        currency="CNY",
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

## Provider Configuration

Google Flights / `fli` uses a 15-second timeout by default:

```powershell
$env:FLI_QUERY_CURRENCY="USD"
$env:FLI_LANGUAGE="en-US"
$env:FLI_COUNTRY="US"
$env:FLI_TIMEOUT_SECONDS="15"
$env:FLIGHT_USD_CNY_RATE="7.2"
```

Skyscanner is an optional experimental fallback source. It depends on the third-party `irrisolto/skyscanner` repository and is not installed by default. Before using it, install that repository and its dependencies yourself, then make sure Python can import `skyscanner`:

```powershell
$env:SKYSCANNER_LOCALE="en-US"
$env:SKYSCANNER_MARKET="US"
$env:SKYSCANNER_CURRENCY="USD"
$env:SKYSCANNER_RETRY_DELAY="2"
$env:SKYSCANNER_MAX_RETRIES="6"
```

## Source Credits

This project references the following open-source projects for data-source adapters:

- Google Flights / `fli`: https://github.com/punitarani/fli
- Skyscanner experimental fallback: https://github.com/irrisolto/skyscanner

AdvSearchFlights is released under the MIT License. Optional third-party data-source libraries may use their own licenses; please review and comply with their license terms when installing or using them.

## Tests

```powershell
python -m pytest
```
