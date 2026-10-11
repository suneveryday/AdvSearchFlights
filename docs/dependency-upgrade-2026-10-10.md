# 依赖升级记录（2026-10-10）

本次依据 `CONTRIBUTING.md` 检查 PyPI、npm、crates.io 与航班源上游发布，升级现有主版本范围内的稳定依赖。版本对比以升级前的锁文件为准。Farello 应用版本仍为 0.10.5。

## 前端和桌面 CLI

| 依赖 | 升级前 | 升级后 |
| --- | --- | --- |
| @tauri-apps/api | 2.11.0 | 2.12.2 |
| @tauri-apps/cli | 2.11.2 | 2.12.1 |
| react / react-dom | 19.2.7 | 19.3.0 |
| @types/react | 19.2.17 | 19.3.0 |
| @types/react-dom | 19.2.3 | 19.3.0 |
| lucide-react | 1.21.0 | 1.54.0 |
| posthog-js | 1.391.2 | 1.438.5 |
| vite | 7.3.5 | 7.3.7 |
| vitest | 4.1.9 | 4.1.11 |

`desktop/package.json` 的最低版本与已验证版本对齐；`package-lock.json` 同时刷新传递依赖。`@vitejs/plugin-react` 仍为 5.2.0，TypeScript 仍为 5.9.3。

检查时存在跨主版本更新：Vite 8.3.4、React 插件 6.1.2、Vitest 5.0.3、TypeScript 7.0.2。本次保留现有工具链主版本；这些更新需要独立迁移和构建行为验证。官方迁移说明：[Vite](https://vite.dev/guide/migration)、[Vitest](https://vitest.dev/guide/migration/)。

## Rust

| 依赖 | 升级前 | 升级后 |
| --- | --- | --- |
| tauri | 2.11.2 | 2.12.2 |
| tauri-build | 2.6.2 | 2.7.1 |
| tauri-plugin-notification | 2.3.3 | 2.5.1 |
| serde | 1.0.228 | 1.0.229 |
| serde_json | 1.0.150 | 1.0.151 |
| libc | 0.2.186 | 0.2.190 |

通过 `cargo update` 更新 `Cargo.lock` 中符合现有约束的依赖；保留 `Cargo.toml` 的版本策略。Tauri JavaScript API 和 Rust 核心均为 2.12.2。

## Python 和航班数据源

`uv pip list --python .venv/bin/python --outdated --format json` 返回空列表。当前运行时依赖为 httpx 0.28.1、pydantic 2.14.0、flights 0.9.0、socksio 1.0.0；开发依赖 pytest 9.1.1、PyInstaller 6.22.3，均未更改。

[flights 的 PyPI 发布](https://pypi.org/project/flights/)和 [fli 上游发布](https://github.com/punitarani/fli/releases)确认 Python 发布版仍为 0.9.0。上游的 `fli-js-v0.0.4` 属于另一个 JavaScript 实现，不适用于现有 Python sidecar。实验性 [Skyscanner 客户端](https://github.com/irrisolto/skyscanner)没有项目中可升级的安装依赖，继续保留可选适配器。

## 验证

- Python：78 项测试通过，`uv pip check` 通过；贡献规范的 mock 搜索命令通过，日期使用未来的 2026-11-15 / 2026-11-22。
- 前端：39 项测试通过（包括 analytics consent 和事件过滤测试），TypeScript 检查与 Vite production build 通过。
- Rust：`cargo test --locked`，6 项测试通过。
- 完整 macOS arm64 `Farello.app` 构建通过，包含重新打包的 Python sidecar；`codesign --verify --deep --strict` 通过。沿用 ad-hoc 签名，未公证。
- 应用内的 `Contents/MacOS/farello-backend` 使用临时数据库运行 mock 搜索，成功输出 2 条 JSON 结果。运行时需要系统 semaphore，验证在允许该操作的执行环境完成。
- `npm audit --json`：已知漏洞从 10 项（4 high、5 moderate、1 low）降到 0 项；这是 npm 依赖审计结果，不代表全项目安全评估。
- 构建有两个非阻断提示：PostHog 发布包 sourcemap 缺少源文件，以及前端 JavaScript chunk 超过 500 kB。

本次未修改 provider、搜索规则或遥测业务逻辑，保留升级前已有的未提交改动。没有提交或推送代码。真实航班查询、桌面通知与 PostHog Live Events 的端到端行为需单独验收，单元测试和 mock 搜索不证明这些路径成功。

## 复现与回退

在项目根目录执行 Python 测试，在 `desktop` 执行 `npm ci`、`npm test` 和 `npm run build`；在 `desktop/src-tauri` 执行 `cargo test --locked`。完整应用构建在 `desktop` 执行：

```bash
npm run tauri build -- --bundles app -- --locked
```

若需回退本次依赖更新，只恢复升级前的 `desktop/package.json`、`desktop/package-lock.json` 和 `desktop/src-tauri/Cargo.lock`，然后执行 `npm ci` 并重新构建应用。不要重置整个工作区，以免覆盖原有未提交修改。
