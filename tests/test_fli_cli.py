"""Keep the optional CLI path usable with current transitive dependencies."""
import subprocess
import sys


def test_fli_cli_starts_without_network() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "from fli.cli import cli; cli()", "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "flights" in result.stdout
