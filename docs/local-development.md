# 本机共享开发环境

配置日期：2026-10-10。主仓库是克隆下来的 `Farello-GitHub` 目录。

## 工具链管理

解释器、编译器与版本管理器安装在当前用户或标准 Homebrew 目录中，供所有项目共享。

| 工具 | 管理方式 | 本次安装或复用的版本 |
| --- | --- | --- |
| Homebrew | `/opt/homebrew` | 7.0.9 |
| Python | uv，`~/.local/share/uv/python` | 全局默认 3.14.8；Farello 3.12.15 |
| uv | `~/.local/bin`，官方安装器 | 0.12.24 |
| Node.js / npm | fnm，`~/.local/share/fnm` | Node 24.21.0 LTS / npm 11.19.0 |
| fnm | `~/.local/bin`，官方安装器 | 1.39.0 |
| Rust / Cargo | rustup，`~/.rustup` 与 `~/.cargo` | stable 1.99.0，含 rustfmt 与 Clippy |
| Apple 编译工具 | 已有 Command Line Tools | Clang 21；无需完整 Xcode 即可构建本项目 |

共享 zsh 配置为 `~/.config/dev-toolchains/env.zsh`，由 `~/.zprofile` 和 `~/.zshrc` 加载。原配置备份位于 `~/.config/dev-toolchains/`。新终端自动生效；已打开的终端可执行 `exec zsh -l`。

交互式终端中的 fnm 会沿父目录查找 `.node-version` / `.nvmrc` 并切换版本。非交互式登录 shell 默认使用 fnm 的 default 版本；需要不同版本的构建脚本可显式执行 `eval "$(fnm env --shell zsh)"` 和 `fnm use`。

macOS 自带 `/usr/bin/python3` 保持原样。`python` 与 `python3` 的用户默认入口由 uv 管理；`python3.12` 可直接访问共享的兼容版本。

## Farello 依赖恢复与开发

项目根目录的 `.python-version` 声明 Python 3.12，`.node-version` 声明 Node 24。

```bash
cd Farello-GitHub
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m pytest

cd desktop
npm ci
npm test
npm run build
npm run build:sidecar
npm run tauri dev
```

完整应用构建：在 `desktop` 执行 `npm run tauri build -- --bundles app`。Rust 测试：在 `desktop/src-tauri` 执行 `cargo test --locked`。

Python 的 `.venv` 和前端的 `node_modules` 隔离每个项目的库依赖；它们复用共享解释器与工具链。创建其他项目时无需重新安装 Python、Node 或 Rust，只需安装该项目自身依赖。

## 日常升级

```bash
brew update
brew upgrade
uv self update
uv python upgrade 3.12 3.14
fnm install --lts
fnm default lts-latest
rustup update stable
```

uv 与 fnm 使用官方独立安装器，因此 `brew upgrade` 不负责升级这两个管理器。fnm 更新可重新执行其官方安装器，保留 `--install-dir "$HOME/.local/bin" --skip-shell --force-no-brew`，避免重复写入 shell 配置。升级解释器后，旧虚拟环境可能仍使用旧版本，需要按项目重新创建。

Homebrew 匿名统计已关闭。没有修改系统代理、安装实验性 Skyscanner fallback、配置 PostHog token，或恢复旧电脑的用户历史数据库。

## 验证记录

- Python：78 项通过。修正一个测试对 2026 年 6 月固定日期和真实系统时钟的混用；业务代码未变更。
- 前端：39 项通过，TypeScript / Vite production build 成功。
- Rust：6 项通过，锁文件未更新。
- Python sidecar：PyInstaller 重建成功，独立执行 mock 搜索成功；这项检查仅验证打包与运行环境，不证明真实航班数据可查询。
- 完整 macOS arm64 应用构建成功，产物位于 `desktop/src-tauri/target/release/bundle/macos/Farello.app`，版本 0.10.5，使用现有配置的 ad-hoc 签名，未公证。
- Cargo 首次下载遇到连接故障；单次设置 `CARGO_HTTP_MULTIPLEXING=false` 后成功，没有持久修改网络设置。
- 首次恢复时 npm 依赖审计有 10 项已知漏洞；2026-10-10 的依赖升级后降为 0 项，详见 [依赖升级记录](dependency-upgrade-2026-10-10.md)。

官方说明：[Homebrew](https://docs.brew.sh/Installation)、[uv](https://docs.astral.sh/uv/)、[fnm](https://github.com/Schniz/fnm)、[Rust](https://rust-lang.org/tools/install/)。
