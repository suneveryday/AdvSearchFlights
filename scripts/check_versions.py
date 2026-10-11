"""Fail when the Python, desktop, Rust, or lockfile versions differ."""
from pathlib import Path
import json
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    expected = project["project"]["version"]
    package = json.loads((ROOT / "desktop/package.json").read_text())
    package_lock = json.loads((ROOT / "desktop/package-lock.json").read_text())
    tauri = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())
    cargo = tomllib.loads((ROOT / "desktop/src-tauri/Cargo.toml").read_text())
    cargo_lock = tomllib.loads((ROOT / "desktop/src-tauri/Cargo.lock").read_text())
    backend = re.search(
        r'^__version__ = "([^"]+)"',
        (ROOT / "src/adv_search_flights/__init__.py").read_text(encoding="utf-8-sig"),
        re.MULTILINE,
    )
    versions = {
        "Python package": backend.group(1) if backend else None,
        "desktop/package.json": package["version"],
        "desktop/package-lock.json": package_lock["version"],
        "npm lock root package": package_lock["packages"][""]["version"],
        "Tauri config": tauri["version"],
        "Cargo.toml": cargo["package"]["version"],
        "Cargo.lock": next(p["version"] for p in cargo_lock["package"] if p["name"] == "farello-desktop"),
    }
    mismatches = {name: value for name, value in versions.items() if value != expected}
    if mismatches:
        raise SystemExit(f"Expected {expected}; mismatched versions: {mismatches}")
    print(f"All application and lockfile versions match: {expected}")


if __name__ == "__main__":
    main()
