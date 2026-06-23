from __future__ import annotations

import os
import subprocess

import httpx

from adv_search_flights.network.diagnostics import (
    NetworkCheck,
    ProxyCandidate,
    classify_provider_message,
    diagnose_network,
    diagnose_network_modules,
    summarize_proxy_env,
)


def test_proxy_summary_redacts_credentials() -> None:
    summary = summarize_proxy_env(
        {
            "HTTPS_PROXY": "http://user:secret@127.0.0.1:7893",
            "ALL_PROXY": "socks5://127.0.0.1:7894",
            "NO_PROXY": "localhost",
        }
    )

    assert summary.has_proxy is True
    assert summary.https_proxy == "http://127.0.0.1:7893"
    assert summary.all_proxy == "socks5://127.0.0.1:7894"
    assert summary.no_proxy == "localhost"


def test_provider_error_classification() -> None:
    assert classify_provider_message("Google Flights 查询超过 15 秒，已自动中止") == "timeout"
    assert classify_provider_message("Could not reach Google Flights (www.google.com)") == "connection_failed"
    assert classify_provider_message("429 Too Many Requests") == "rate_limited"
    assert classify_provider_message("Google Flights 返回 ErrorResponse") == "provider_error"
    assert classify_provider_message("Google Flights 返回了 ErrorResponse，但没有明确限频信号") == "provider_error"
    assert classify_provider_message("Google Flights 返回 HTTP 403") == "provider_error"
    assert classify_provider_message("未找到 fli CLI，请先安装 flights 包") == "missing_dependency"


def test_diagnose_network_reports_missing_fli(monkeypatch) -> None:
    monkeypatch.setattr("adv_search_flights.network.diagnostics.shutil.which", lambda _: None)
    monkeypatch.setattr("adv_search_flights.network.diagnostics.Path.exists", lambda _: False)
    monkeypatch.setattr("adv_search_flights.network.diagnostics._fli_runtime_available", lambda: False)
    diagnostics = diagnose_network("fli", check_google=False)

    assert diagnostics.status == "error"
    assert diagnostics.checks[0].name == "fli_cli"
    assert diagnostics.checks[0].status == "error"


def test_diagnose_network_accepts_bundled_fli_runtime(monkeypatch) -> None:
    monkeypatch.setattr("adv_search_flights.network.diagnostics.shutil.which", lambda _: None)
    monkeypatch.setattr("adv_search_flights.network.diagnostics.Path.exists", lambda _: False)
    monkeypatch.setattr("adv_search_flights.network.diagnostics._fli_runtime_available", lambda: True)

    diagnostics = diagnose_network("fli", check_google=False)

    assert diagnostics.checks[0].status == "ok"
    assert diagnostics.checks[0].message == "内置 fli 运行时可用"


def test_diagnose_network_classifies_google_timeout(monkeypatch) -> None:
    monkeypatch.setattr("adv_search_flights.network.diagnostics.shutil.which", lambda _: "/tmp/fli")

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="curl", timeout=0.01)

    monkeypatch.setattr("adv_search_flights.network.diagnostics.subprocess.run", raise_timeout)
    diagnostics = diagnose_network("fli", timeout_seconds=0.01, check_google=True)

    assert diagnostics.status == "error"
    assert diagnostics.checks[0].status == "ok"
    assert diagnostics.checks[1].name == "google_flights"
    assert diagnostics.checks[1].status == "error"


def test_diagnose_network_modules_returns_named_modules(monkeypatch) -> None:
    monkeypatch.setattr("adv_search_flights.network.diagnostics.shutil.which", lambda _: "/tmp/fli")
    monkeypatch.setattr(
        "adv_search_flights.network.diagnostics._check_google_flights",
        lambda timeout_seconds: type("Check", (), {"status": "ok", "ok": True, "message": "ok", "latency_ms": 1})(),
    )
    monkeypatch.setattr(
        "adv_search_flights.network.diagnostics._check_url",
        lambda name, url, timeout_seconds: type("Check", (), {"name": name, "status": "ok", "ok": True, "message": "ok", "latency_ms": 1})(),
    )

    result = diagnose_network_modules("fli")

    assert result["status"] in {"ok", "warning"}
    assert {item["name"] for item in result["modules"]} >= {"proxy", "fli_cli", "google_flights", "github_releases"}


def test_startup_network_current_network_ok_skips_proxy_detection(monkeypatch) -> None:
    monkeypatch.setattr(
        "adv_search_flights.network.diagnostics._check_google_flights_with_proxy_env",
        lambda env, timeout_seconds, clear_proxy: NetworkCheck(name="google_flights", status="ok", ok=True, message="current network ok"),
    )
    monkeypatch.setattr("adv_search_flights.network.diagnostics._proxy_candidates", lambda **kwargs: (_ for _ in ()).throw(AssertionError("proxy candidates should not be checked")))

    result = diagnose_network_modules("fli", mode="startup")

    assert result["status"] == "ok"
    assert result["guide_status"] == "direct_ok"
    assert result["auto_configured"] is False
    assert result["manual_required"] is False
    assert result["modules"][0]["message"] == "当前网络可访问 Google Flights，无需手动配置代理"
    assert result["user_message"] == "当前网络可直接访问 Google Flights"


def test_first_run_network_uses_startup_detection(monkeypatch) -> None:
    monkeypatch.setattr(
        "adv_search_flights.network.diagnostics._check_google_flights_with_proxy_env",
        lambda env, timeout_seconds, clear_proxy: NetworkCheck(name="google_flights", status="ok", ok=True, message="current network ok"),
    )
    monkeypatch.setattr("adv_search_flights.network.diagnostics._proxy_candidates", lambda **kwargs: (_ for _ in ()).throw(AssertionError("proxy candidates should not be checked")))

    result = diagnose_network_modules("fli", mode="first_run")

    assert result["status"] == "ok"
    assert result["guide_status"] == "direct_ok"
    assert result["auto_configured"] is False
    assert result["manual_required"] is False


def test_startup_network_auto_configures_first_working_proxy(monkeypatch) -> None:
    checks: list[dict[str, str]] = []
    persisted: list[ProxyCandidate] = []
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(
        "adv_search_flights.network.diagnostics._check_google_flights",
        lambda timeout_seconds: NetworkCheck(name="google_flights", status="error", ok=False, message="current network failed"),
    )

    def fake_check(env, timeout_seconds, clear_proxy):
        checks.append(env)
        if env is None:
            return NetworkCheck(name="google_flights", status="error", ok=False, message="current network failed")
        return NetworkCheck(name="google_flights", status="ok", ok=True, message="proxy ok", latency_ms=12)

    monkeypatch.setattr("adv_search_flights.network.diagnostics._check_google_flights_with_proxy_env", fake_check)
    monkeypatch.setattr(
        "adv_search_flights.network.diagnostics._proxy_candidates",
        lambda **kwargs: [ProxyCandidate(source="local_http_7893", http_proxy="http://127.0.0.1:7893")],
    )
    monkeypatch.setattr("adv_search_flights.network.diagnostics._persist_proxy_candidate", lambda candidate: persisted.append(candidate))

    result = diagnose_network_modules("fli", mode="startup")

    assert result["status"] == "ok"
    assert result["guide_status"] == "proxy_auto_configured"
    assert result["auto_configured"] is True
    assert result["manual_required"] is False
    assert result["selected_proxy"]["source"] == "local_http_7893"
    assert persisted[0].http_proxy == "http://127.0.0.1:7893"
    assert checks[0] is None
    assert checks[1]["https_proxy"] == "http://127.0.0.1:7893"
    assert os.environ["https_proxy"] == "http://127.0.0.1:7893"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7893"
    assert "all_proxy" not in os.environ
    assert "ALL_PROXY" not in os.environ


def test_startup_network_ignores_process_proxy_environment(monkeypatch) -> None:
    checks: list[tuple[dict[str, str] | None, bool]] = []
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:33210")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:33210")

    def fake_check(env, timeout_seconds, clear_proxy):
        checks.append((env, clear_proxy))
        if env and env.get("https_proxy") == "http://127.0.0.1:7893":
            return NetworkCheck(name="google_flights", status="ok", ok=True, message="proxy ok", latency_ms=12)
        return NetworkCheck(name="google_flights", status="error", ok=False, message="failed")

    monkeypatch.setattr("adv_search_flights.network.diagnostics._check_google_flights_with_proxy_env", fake_check)
    monkeypatch.setattr(
        "adv_search_flights.network.diagnostics._proxy_candidates",
        lambda include_environment=True: [ProxyCandidate(source="saved_settings", http_proxy="http://127.0.0.1:7893")],
    )
    monkeypatch.setattr("adv_search_flights.network.diagnostics._persist_proxy_candidate", lambda candidate: None)

    result = diagnose_network_modules("fli", mode="startup")

    assert result["status"] == "ok"
    assert checks[0] == (None, True)
    assert result["selected_proxy"]["source"] == "saved_settings"
    assert "33210" not in str(result["proxy"])


def test_startup_network_requires_manual_proxy_when_all_candidates_fail(monkeypatch) -> None:
    def fake_check(env, timeout_seconds, clear_proxy):
        return NetworkCheck(name="google_flights", status="error", ok=False, message="failed")

    monkeypatch.setattr(
        "adv_search_flights.network.diagnostics._check_google_flights",
        lambda timeout_seconds: NetworkCheck(name="google_flights", status="error", ok=False, message="current network failed"),
    )
    monkeypatch.setattr("adv_search_flights.network.diagnostics._check_google_flights_with_proxy_env", fake_check)
    monkeypatch.setattr(
        "adv_search_flights.network.diagnostics._proxy_candidates",
        lambda **kwargs: [ProxyCandidate(source="local_http_7893", http_proxy="http://127.0.0.1:7893")],
    )

    result = diagnose_network_modules("fli", mode="startup")

    assert result["status"] == "error"
    assert result["guide_status"] == "needs_manual_proxy"
    assert result["auto_configured"] is False
    assert result["manual_required"] is True
    assert result["modules"][0]["message"] == "当前网络无法访问 Google Flights；可在设置中手动填写代理作为排障选项"
    assert result["user_message"] == "无法连接 Google Flights，请检查网络或手动填写代理"


def test_google_flights_curl_timeout_uses_friendly_message(monkeypatch) -> None:
    monkeypatch.setattr("adv_search_flights.network.diagnostics.shutil.which", lambda _: "/usr/bin/curl")

    class Completed:
        returncode = 28
        stdout = "000"
        stderr = "curl: (28) Connection timed out after 3002 milliseconds"

    monkeypatch.setattr("adv_search_flights.network.diagnostics.subprocess.run", lambda *args, **kwargs: Completed())

    diagnostics = diagnose_network("fli", check_google=True)

    google = diagnostics.checks[1]
    assert google.status == "error"
    assert google.message == "Google Flights 连接超时，当前网络可能不可达或代理未生效"
    assert google.details
    assert "curl: (28)" in google.details["raw_message"]
