from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAURI_DIR = ROOT / "desktop" / "src-tauri"
BINARIES_DIR = TAURI_DIR / "binaries"
BUILD_DIR = ROOT / "build" / "sidecar"
ENTRYPOINT = ROOT / "scripts" / "sidecar_entry.py"


def target_triple() -> str:
    result = subprocess.run(
        ["rustc", "--print", "host-tuple"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if not value.endswith("-apple-darwin"):
        raise RuntimeError(f"当前仅支持 macOS sidecar 构建，检测到：{value}")
    return value


def main() -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("Farello macOS sidecar 必须在 macOS 上构建")

    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "缺少 PyInstaller。请先在项目虚拟环境执行：python -m pip install -e '.[dev]'"
        ) from exc

    triple = target_triple()
    output_name = f"farello-backend-{triple}"
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    output_path = BINARIES_DIR / output_name
    if output_path.exists():
        output_path.unlink()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            output_name,
            "--distpath",
            str(BINARIES_DIR),
            "--workpath",
            str(BUILD_DIR / "work"),
            "--specpath",
            str(BUILD_DIR),
            "--paths",
            str(ROOT / "src"),
            "--collect-all",
            "fli",
            "--copy-metadata",
            "flights",
            str(ENTRYPOINT),
        ],
        cwd=ROOT,
        check=True,
    )

    if not output_path.exists():
        raise RuntimeError(f"sidecar 构建未生成预期文件：{output_path}")
    output_path.chmod(0o755)
    print(f"Built Farello sidecar: {output_path}")


if __name__ == "__main__":
    main()
