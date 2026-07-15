<p align="right">
  <a href="./README.en.md">English</a> · <strong>简体中文</strong>
</p>

<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="Farello 组合多目的地与开口航线搜索，按价格排序，并在 macOS 上定时监控价格。">
</p>

<p align="center">
  <a href="https://github.com/suneveryday/AdvSearchFlights/releases"><img alt="最新版本" src="https://img.shields.io/github/v/release/suneveryday/AdvSearchFlights?style=flat-square&color=0878d1"></a>
  <img alt="macOS" src="https://img.shields.io/badge/macOS-桌面应用-111827?style=flat-square&logo=apple&logoColor=white">
  <img alt="Python 3.11 及以上" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <a href="./LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-238636?style=flat-square"></a>
</p>

Farello 是一款本地优先的复杂航班搜索与价格监控工具，适合普通往返搜索难以覆盖的行程。输入一个出发地和最多五个候选目的地，它会展开城市机场、组合往返与开口航线、过滤不合适的航段，并按总价排序。

- **一次探索更多组合** — 同时比较单目的地往返与多城市开口航线。
- **保留真正有用的细节** — 查看机场、航司、航班号、机型、起降时间、中转、停留时长与分段价格。
- **在本机持续看价** — 定时重复搜索；总价低于阈值时，通过 macOS 通知和 Apple Reminders 提醒。

> Farello 当前主要通过 [`fli`](https://github.com/punitarani/fli) 使用 Google Flights 数据。搜索请求从你的电脑发出，结果保存在本地 SQLite 数据库中。

## 从候选目的地到值得预订的路线

| 你的输入 | Farello 生成的路线 |
| --- | --- |
| `上海 → 墨尔本` | 常规往返：上海 → 墨尔本 → 上海 |
| `上海 → 墨尔本、悉尼` | 往返加开口航线，例如：上海 → 墨尔本 · 悉尼 → 上海 |

每段单程默认最多中转一次、每次中转不超过十小时。Farello 会先过滤航段，再组合完整行程，并按人民币总价从低到高排序。

<p align="center">
  <img src="./assets/readme/workflow.svg" width="100%" alt="Farello 展开城市机场、搜索各航段、组合并排序行程，随后可选地定时监控价格并发送提醒。">
</p>

## 你可以做什么

- 输入中文城市名或 IATA 机场代码；城市会展开为已知机场，例如 `上海 → PVG/SHA`。
- 从 1–5 个候选目的地中搜索经济舱、超级经济舱、商务舱或头等舱。
- 生成同城往返与不走回头路的开口航线组合。
- 先按中转次数与停留时长过滤，再按总价排序。
- 在桌面端查看搜索历史、价格趋势和保存的路线组。
- 按价格、航司、起降机场、中转次数、停留时长和排除中转机场筛选历史。
- 为最多五个历史组设置 1–48 小时的定时搜索。
- 只在低于价格阈值时提醒；之后仅在出现更低价时再次提醒。
- 通过 macOS 桌面应用、CLI、稳定 JSON 子进程协议或 Python 包使用。

## 快速开始

### 不联网体验 CLI

Farello 需要 Python 3.11 或更高版本。

```bash
git clone https://github.com/suneveryday/AdvSearchFlights.git
cd AdvSearchFlights
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

adv-search-flights search \
  --origin SHA \
  --dest MEL SYD \
  --departure 2026-09-29 \
  --return-date 2026-10-07 \
  --provider mock \
  --format table \
  --limit 2 \
  --no-cooldown
```

准备从本机网络查询真实数据时，把 `--provider mock` 改为 `--provider auto`。

### 从源码运行 macOS 应用

桌面端由 React、Tauri 2 与内嵌 Python sidecar 组成。除 Python 外，还需安装 Node.js 与 Rust 工具链。

```bash
# 在仓库根目录并激活 Python 环境后执行
cd desktop
npm install
npm run build:sidecar
npm run tauri dev
```

首次网络检查会先尝试当前网络；直连失败时，可以发现本机可用代理。Farello 不会上传代理凭证。

## CLI 用法

```bash
adv-search-flights search \
  --origin 上海 \
  --dest 东京 静冈 \
  --departure 2026-09-29 \
  --return-date 2026-10-07 \
  --provider auto \
  --cabin-class ECONOMY \
  --max-stops 1 \
  --max-layover-hours 10 \
  --format table \
  --limit 20
```

执行 `adv-search-flights search --help` 查看完整参数。

<details>
<summary><strong>核心搜索参数</strong></summary>

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `--origin` | 必填 | 中文城市名或 IATA 机场代码 |
| `--dest` | 必填 | 1–5 个候选城市或机场 |
| `--departure` | 必填 | `YYYY-MM-DD` 格式的去程日期 |
| `--return-date` | 必填 | `YYYY-MM-DD` 格式的回程日期 |
| `--provider` | `auto` | `auto`、`fli`、`skyscanner` 或 `mock` |
| `--format` | `table` | `table`、`text` 或 `json` |
| `--max-stops` | `1` | 每段单程的最大中转次数 |
| `--max-layover-hours` | `10` | 每次中转的最长停留小时数 |
| `--cabin-class` | `ECONOMY` | `ECONOMY`、`PREMIUM_ECONOMY`、`BUSINESS` 或 `FIRST` |
| `--limit` | 不限制 | 筛选与排序后截取结果 |
| `--cooldown-seconds` | `90` | 真实数据调用之间的间隔 |
| `--retry-waits` | `30,60,90` | 逗号分隔的重试等待时间 |

</details>

<details>
<summary><strong>历史与 GUI 协议命令</strong></summary>

```bash
adv-search-flights history-list --format json
adv-search-flights history-group-list --format json
adv-search-flights history-group-get <group_id> --format json
adv-search-flights history-group-results <group_id> \
  --filters '{"max_total_price": 10000}' \
  --format json
adv-search-flights history-group-delete <group_id> --format json
```

`gui-search` 从 stdin 接收一个 JSON 请求，返回包含 `ok`、`response`、`network_status`、`provider_status`、`error` 与 `history_batch_id` 的稳定 envelope。桌面端与 Python 的完整调用流程见[架构说明](./docs/architecture.md)。

</details>

## 工作原理

1. 把出发城市与候选目的地解析为已知机场。
2. 查询相关机场组合的去程与回程航班。
3. 移除不符合价格、中转或停留时长限制的航段。
4. 把可用航段组合为往返和开口航线。
5. 按总价排序，并输出表格、文本或 JSON。
6. 把成功的真实搜索保存在本地，供桌面历史与定时监控复用。

桌面端通过本地子进程调用 Python 引擎，不会启动本地 Web 服务器。数据源、组合规则、网络诊断和 UI 相互隔离，便于独立测试。完整模块图见[架构说明](./docs/architecture.md)。

## 定时搜索与提醒

在历史组中点击闹钟按钮，可以配置搜索间隔与可选价格阈值。确认后 Farello 会立即搜索一次，后续任务仅在应用保持运行时执行。

提醒需要以下 macOS 权限：

- `系统设置 → 通知 → Farello`
- `系统设置 → 隐私与安全性 → 自动化 → Reminders`

权限失败不会中断定时搜索本身。

## 隐私

首次启动时只有在你明确同意后才会启用匿名统计，也可以随时在**设置 → 隐私与统计**中关闭。启用后，Farello 只发送应用版本、系统平台、工作区、搜索是否成功、结果数量与耗时区间、标准化错误分类、定时搜索配置和提醒渠道是否成功等粗粒度运行事件。

航线、日期、机场、价格、搜索输入与结果、历史 ID、购买链接、提醒阈值、原始错误、身份、账号信息与硬件标识永不上传。Farello 使用本地随机安装 ID，并关闭自动点击采集、页面浏览、Session Replay 与用户画像。

## 当前边界

- 桌面应用当前面向 macOS；Python CLI 可独立开发和测试。
- 定时搜索仅在 Farello 运行期间执行。
- 真实结果依赖第三方数据源与用户网络；数据源可能变化、限流或不返回有效价格。
- `auto` 优先通过 `fli` 使用 Google Flights；可选 Skyscanner 适配器仍为实验性功能。
- Farello 用于比较行程，最终预订在外部数据源链接中完成。

## 开发

```bash
python -m pytest

cd desktop
npm test
npm run build
```

欢迎贡献。请先阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)，保持数据源解析逻辑相互隔离，并为行为变更补充针对性测试。安全问题请遵循 [SECURITY.md](./SECURITY.md)。

## 致谢

- Google Flights 适配：[`punitarani/fli`](https://github.com/punitarani/fli)
- 实验性 Skyscanner fallback：[`irrisolto/skyscanner`](https://github.com/irrisolto/skyscanner)

Farello 采用 [MIT License](./LICENSE) 发布。可选第三方数据源可能使用各自的许可证。
