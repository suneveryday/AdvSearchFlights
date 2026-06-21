from __future__ import annotations

import httpx

from adv_search_flights.network.diagnostics import (
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
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr("adv_search_flights.network.diagnostics.httpx.head", raise_timeout)
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
