# Farello

Farello 是一个航班复杂搜索工具，用于多目的地候选、开口航线组合和价格排序。v0.10.0 默认展示价格最低的 50 个组合，并增加需要用户明确授权的 PostHog 匿名产品统计。

当前数据源以 Google Flights / `fli` 为主，并支持可选的 Skyscanner 实验备用源。应用不自建服务器，真实航班请求仍由用户本机网络发起。

## 核心功能

- 出发地支持中文城市名或 IATA 机场代码，单选输入。
- 目的地支持 1 到 5 个候选城市或机场。
- 城市会自动展开为多个机场，例如 `上海 -> PVG/SHA`、`北京 -> PEK/PKX`。
- 选择 1 个目的地时，生成同一城市到达和返回的往返航班。
- 选择 2 个或更多候选目的地时，从候选城市中组合往返和不走回头路的开口航线。
- 每段单程默认过滤：中转次数 `<= 1`，单次中转停留 `<= 10` 小时。
- 自动排除无价格航班。
- 结果按人民币总价从低到高排序。
- GUI 默认返回 50 条组合结果；把结果数量改为 `0` 时仍可返回全部组合。
- 输出机场三字码、机场中文名、航空公司中文名称、航班号、执飞机型、起降时间、中转机场、中转停留小时数和单程价格。
- 支持 `table`、`text`、`json` 三种输出格式。
- 支持舱位选择：经济舱、超级经济舱、商务舱、头等舱。
- GUI 真实搜索成功后会保存本地历史批次，方便减少重复请求和限频风险。
- 独立历史工作区按完整查询条件聚合批次，支持最低价格趋势和稳定语义筛选。
- GUI 相邻单程请求保持 2 秒固定间隔；普通供应商失败按 3、8、15 秒短重试，不再启用限频专用长等待或 RPC 分类策略。
- 本地滚动诊断日志记录搜索阶段、航段耗时、HTTP 状态、响应大小、解析数量和异常类型，并自动隐藏代理、cookie 与购买 token。
- 历史组可开启 1–48 小时定时搜索，默认 8 小时，最多同时启用 5 组；确认设置后立即搜索一次，后续仅在 App 运行期间执行。
- 定时搜索可设置价格阈值；最低往返总价严格低于阈值时，通过 macOS 桌面通知和 Apple Reminders 提醒，之后仅在出现更低价格时再次提醒。
- `gui-search` JSON 协议供桌面 GUI 通过子进程调用，并支持流式进度事件。
- 独立网络诊断模块可检测代理摘要、`fli` CLI、Google Flights 连通性，并把常见错误转成可读状态。

## macOS 桌面 GUI（v0.10.0）

桌面端位于 `desktop/`，技术栈为 Tauri + React + TypeScript + Vite。

v0.10.0 使用紧凑的 macOS 桌面工具布局：侧栏负责工作区与搜索条件，顶部工具栏承载主题、网络和设置入口，内容区统一展示搜索状态、结果表格与历史详情。支持浅色/深色模式、`⌘K` 快速操作、`⌘,` 打开设置和 `⌘F` 回到搜索输入。搜索进展默认折叠，结果数量默认 `50`，填 `0` 表示返回全部组合；历史批次固定展示日期、时间和价格，趋势图默认显示最新搜索区间。

### 匿名使用统计

Farello 仅在首次启动得到明确授权后初始化 PostHog。用户可以在“设置 → 隐私与统计”中随时关闭。统计只包含应用版本、系统平台、工作区、搜索是否成功、结果数量区间、耗时区间、标准化错误类别、定时搜索配置和提醒渠道是否成功。

以下内容永不上传：航线、日期、机场、价格、搜索输入和结果、历史组或批次 ID、购买链接、提醒阈值、原始错误、姓名、邮箱、账号或硬件标识。应用使用本地 SQLite 中随机生成的匿名安装 ID，不启用自动点击采集、页面浏览、Session Replay 或用户画像。

开发预览和自动测试不会发送真实统计。生产打包前，在 `desktop/.env.local` 或构建环境中配置：

```bash
VITE_POSTHOG_PROJECT_TOKEN=phc_your_project_token
VITE_POSTHOG_HOST=https://us.i.posthog.com
```

`.env.local` 已被 Git 忽略，仓库只提交 `desktop/.env.example`。发布前还必须在 PostHog 项目设置中关闭 IP 数据采集。

历史组的闹钟按钮用于配置定时搜索。提醒功能需要检查以下系统权限：

- `系统设置 → 通知 → Farello`
- `系统设置 → 隐私与安全性 → 自动化 → Reminders`

应用会创建或复用 Apple Reminders 中的 `Farello` 列表；已有 `AdvSearchFlights` 列表会自动改名并继续复用。同一历史组始终更新一条未完成提醒事项。任一提醒渠道权限失败都不会中断定时搜索，失败原因会写入诊断日志。

为兼容旧版本，诊断日志继续保存在 `~/Library/Logs/AdvSearchFlights/app.log`。单文件上限 5 MB，保留两个轮换文件。可查看最近日志：

```bash
adv-search-flights diagnostics-log --tail 200 --format json
```

开发预览：

```bash
cd desktop
npm install
npm run dev
```

前端测试和构建：

```bash
cd desktop
npm run test
npm run build
```

Tauri/macOS 打包需要 Rust/Cargo 工具链：

```bash
cd desktop
npm run tauri build -- --bundles app,dmg
```

桌面端在 Tauri 环境中调用本地 `adv-search-flights gui-search` 子进程；在普通浏览器开发环境中会回退到 mock 数据，方便调 UI。mock 数据不会写入历史库。

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

## 本地历史库

为保证升级后仍能读取既有记录，本地 SQLite 历史库继续沿用旧版兼容路径：

```bash
~/Library/Application Support/AdvSearchFlights/search_history.sqlite3
```

保存规则：

- 只保存真实数据源成功结果：`fli`、`auto`、`skyscanner` 且 `result_count > 0`。
- `mock` 搜索永不写入历史库，避免污染真实搜索记录。
- 每次搜索保存为一个批次，批次内按航段和价格去重，不覆盖旧批次。
- 每条记录对应一个组合往返/开口航线，保存总价、总时长、中转城市/机场、去程和回程分段、购买页链接和完整 rendered JSON。
- 原始批次和航线记录是事实数据；聚合历史只新增映射，不改写旧记录。
- 聚合规则带版本标记；规则升级只重建聚合映射，`10/50` 条等不同结果上限会归入同组。
- 全局约保留 10,000 条航线结果，超过后按最老搜索批次整批清理，最新批次不会被截断。

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

### 网络与代理排障

如果 GUI 或 CLI 提示 Google Flights 不可达，优先检查：

- 命令行环境是否继承了正确代理变量：`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`。
- 本机是否能访问 `https://www.google.com/travel/flights`。
- `fli` CLI 是否在当前 `PATH` 中可用。
- 是否触发 Google Flights 超时或疑似限频，必要时稍后重试或减少目的地数量。
- 检查诊断日志中的 `status_code`、`has_error_response`、`error_response_code`、航段耗时和重试次数，区分网络不可达、Google ErrorResponse 与解析问题。
- 真实搜索、购买链接和筛选器改动后，优先用纯后端 `gui-search` 验证结果，再看 GUI 展示，避免把解析异常误判为无结果。

`gui-search` 会把这些信息放进 `network_status` 和 `provider_status`，供 GUI 展示更友好的提示。

## 稳定回退点

本次修改前的稳定回退基线为 `v0.6.3 / checkpoint-v0.6-m4`。如果真实搜索或购买链接再次异常，可继续使用搜索链路稳定基线 `v0.3.9 / checkpoint-v0.3-m10` 对照验证。

## 隐私说明

v0.9 不上传匿名统计，不保存 API key 或个人信息。真实搜索结果、定时配置、提醒阈值和重试设置仅保存在当前 Mac 的本地 SQLite 文件中，不会上传 Notion 或云端。

未来如果加入匿名统计，会采用 opt-in，并且不会上传航线、日期、价格、机场或搜索关键词。

## 后续规划

- 搜索历史导出和更长周期价格分析。
- 排除航司、排除中转城市，支持代码和名称输入。
- 更完整的 macOS 打包交付和版本检查。
- 后续版本：搜索历史导出、价格趋势分析、更多数据源和 Windows 打包。

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

Farello 使用 MIT License 发布。可选第三方数据源库可能使用各自的许可证；安装或使用这些库时，请自行阅读并遵守对应许可证条款。

## 测试

```powershell
python -m pytest
```

---

# Farello

Farello is a macOS flight-search application with a reusable Python backend CLI for complex flight search, open-jaw route combination, and price sorting. It uses Google Flights / `fli` as the primary data source and supports an optional experimental Skyscanner fallback.

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

Farello is released under the MIT License. Optional third-party data-source libraries may use their own licenses; please review and comply with their license terms when installing or using them.

## Tests

```powershell
python -m pytest
```
