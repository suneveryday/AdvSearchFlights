from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field


GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights"
GITHUB_RELEASES_URL = "https://api.github.com/repos/suneveryday/AdvSearchFlights/releases/latest"


class NetworkCheck(BaseModel):
    name: str
    status: str
    ok: bool | None
    message: str
    latency_ms: int | None = None


class ProxySummary(BaseModel):
    has_proxy: bool
    http_proxy: str | None = None
    https_proxy: str | None = None
    all_proxy: str | None = None
    no_proxy: str | None = None


class NetworkDiagnostics(BaseModel):
    proxy: ProxySummary
    checks: list[NetworkCheck] = Field(default_factory=list)

    @property
    def status(self) -> str:
        if any(check.status == "error" for check in self.checks):
            return "error"
        if any(check.status == "warning" for check in self.checks):
            return "warning"
        if all(check.ok is None for check in self.checks):
            return "unknown"
        return "ok"

    def payload(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["status"] = self.status
        return data


class ProviderRunStatus(BaseModel):
    provider: str
    status: str
    result_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    message: str | None = None


def diagnose_network(provider: str, *, timeout_seconds: float = 3.0, check_google: bool = True) -> NetworkDiagnostics:
    checks: list[NetworkCheck] = []
    provider_name = provider.lower()
    if provider_name in {"auto", "fli"}:
        checks.append(_check_fli_cli())
    else:
        checks.append(NetworkCheck(name="fli_cli", status="skipped", ok=None, message=f"provider={provider} 不需要 fli CLI 预检"))

    if check_google and provider_name in {"auto", "fli"}:
        checks.append(_check_google_flights(timeout_seconds))
    else:
        checks.append(NetworkCheck(name="google_flights", status="skipped", ok=None, message="本次未执行 Google Flights 连通性检查"))

    return NetworkDiagnostics(proxy=summarize_proxy_env(), checks=checks)


def diagnose_network_modules(provider: str = "fli", *, timeout_seconds: float = 3.0) -> dict[str, Any]:
    proxy = summarize_proxy_env()
    modules = [
        {
            "name": "proxy",
            "label": "代理配置",
            "status": "ok" if proxy.has_proxy else "warning",
            "ok": proxy.has_proxy,
            "message": "已检测到代理环境" if proxy.has_proxy else "未检测到代理，真实搜索可能受网络环境影响",
            "details": proxy.model_dump(mode="json"),
        }
    ]
    provider_name = provider.lower()
    modules.append(_module("fli_cli", "fli CLI", _check_fli_cli()))
    if provider_name in {"auto", "fli"}:
        modules.append(_module("google_flights", "Google Flights 页面", _check_google_flights(timeout_seconds)))
        modules.append(_module("google_flights_query", "Google Flights/fli 查询", _check_google_flights(timeout_seconds)))
    else:
        modules.append(
            {
                "name": "google_flights",
                "label": "Google Flights 页面",
                "status": "skipped",
                "ok": None,
                "message": f"provider={provider} 暂不需要 Google Flights 检查",
            }
        )
    modules.append(_module("github_releases", "GitHub Releases", _check_url("github_releases", GITHUB_RELEASES_URL, timeout_seconds)))
    status = "ok"
    if any(item["status"] == "error" for item in modules):
        status = "error"
    elif any(item["status"] == "warning" for item in modules):
        status = "warning"
    return {"status": status, "modules": modules, "proxy": proxy.model_dump(mode="json")}


def summarize_proxy_env(env: dict[str, str] | None = None) -> ProxySummary:
    values = env or os.environ
    http_proxy = values.get("HTTPS_PROXY") or values.get("https_proxy") or values.get("HTTP_PROXY") or values.get("http_proxy")
    https_proxy = values.get("HTTPS_PROXY") or values.get("https_proxy")
    all_proxy = values.get("ALL_PROXY") or values.get("all_proxy")
    no_proxy = values.get("NO_PROXY") or values.get("no_proxy")
    return ProxySummary(
        has_proxy=any([http_proxy, https_proxy, all_proxy]),
        http_proxy=_redact_proxy(http_proxy),
        https_proxy=_redact_proxy(https_proxy),
        all_proxy=_redact_proxy(all_proxy),
        no_proxy=no_proxy,
    )


def _module(name: str, label: str, check: NetworkCheck) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "status": check.status,
        "ok": check.ok,
        "message": check.message,
        "latency_ms": check.latency_ms,
    }


def classify_provider_messages(messages: list[str]) -> list[str]:
    categories: list[str] = []
    for message in messages:
        category = classify_provider_message(message)
        if category not in categories:
            categories.append(category)
    return categories


def classify_provider_message(message: str) -> str:
    text = message.lower()
    if "未找到 fli" in message or "no module named" in text or "not found" in text:
        return "missing_dependency"
    if "timed out" in text or "timeout" in text or "超过" in message or "超时" in message:
        return "timeout"
    if "could not reach" in text or "failed to connect" in text or "connection refused" in text or "dns" in text:
        return "connection_failed"
    if "没有明确限频信号" in message or "not explicitly rate limited" in text:
        return "provider_error"
    if "429" in text or "rate limit" in text or "too many requests" in text or "rate_limited" in text or "限频" in message:
        return "rate_limited"
    if "no result" in text or "无结果" in message:
        return "no_results"
    return "provider_error"


def provider_status(provider: str, result_count: int, warnings: list[str]) -> ProviderRunStatus:
    categories = classify_provider_messages(warnings)
    if result_count > 0:
        status = "ok_with_warnings" if warnings else "ok"
        message = None if not warnings else "搜索成功，但部分单程查询失败"
    elif warnings:
        status = "error"
        message = "所有可组合航段都未返回可用结果，详见 warnings"
    else:
        status = "no_results"
        message = "搜索完成，但没有符合当前筛选条件的结果"
        categories = ["no_results"]
    return ProviderRunStatus(
        provider=provider,
        status=status,
        result_count=result_count,
        warnings=warnings,
        categories=categories,
        message=message,
    )


def resolve_fli_cli_executable() -> str | None:
    executable = shutil.which("fli")
    if not executable:
        sibling = Path(sys.executable).with_name("fli")
        if sibling.exists():
            executable = str(sibling)
    return executable


def _check_fli_cli() -> NetworkCheck:
    executable = resolve_fli_cli_executable()
    if executable:
        return NetworkCheck(name="fli_cli", status="ok", ok=True, message=f"找到 fli CLI：{executable}")
    if _fli_runtime_available():
        return NetworkCheck(name="fli_cli", status="ok", ok=True, message="内置 fli 运行时可用")
    return NetworkCheck(name="fli_cli", status="error", ok=False, message="未找到 fli CLI，请先安装 flights 包或确认 PATH")


def _fli_runtime_available() -> bool:
    try:
        from fli.search import SearchFlights  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def _check_google_flights(timeout_seconds: float) -> NetworkCheck:
    start = time.monotonic()
    try:
        response = httpx.head(GOOGLE_FLIGHTS_URL, follow_redirects=True, timeout=timeout_seconds)
        latency_ms = int((time.monotonic() - start) * 1000)
        if response.status_code < 500:
            return NetworkCheck(
                name="google_flights",
                status="ok",
                ok=True,
                message=f"Google Flights 可访问，HTTP {response.status_code}",
                latency_ms=latency_ms,
            )
        return NetworkCheck(
            name="google_flights",
            status="warning",
            ok=False,
            message=f"Google Flights 返回 HTTP {response.status_code}",
            latency_ms=latency_ms,
        )
    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - start) * 1000)
        return NetworkCheck(name="google_flights", status="error", ok=False, message="Google Flights 连通性检查超时", latency_ms=latency_ms)
    except httpx.HTTPError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return NetworkCheck(name="google_flights", status="error", ok=False, message=f"Google Flights 不可达：{exc}", latency_ms=latency_ms)
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return NetworkCheck(name="google_flights", status="error", ok=False, message=f"Google Flights 检查失败：{exc}", latency_ms=latency_ms)


def _check_url(name: str, url: str, timeout_seconds: float) -> NetworkCheck:
    start = time.monotonic()
    try:
        response = httpx.head(url, follow_redirects=True, timeout=timeout_seconds)
        latency_ms = int((time.monotonic() - start) * 1000)
        if response.status_code < 500:
            return NetworkCheck(name=name, status="ok", ok=True, message=f"可访问，HTTP {response.status_code}", latency_ms=latency_ms)
        return NetworkCheck(name=name, status="warning", ok=False, message=f"返回 HTTP {response.status_code}", latency_ms=latency_ms)
    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - start) * 1000)
        return NetworkCheck(name=name, status="error", ok=False, message="连通性检查超时", latency_ms=latency_ms)
    except httpx.HTTPError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return NetworkCheck(name=name, status="error", ok=False, message=f"不可达：{exc}", latency_ms=latency_ms)


def _redact_proxy(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if not parsed.username and not parsed.password:
        return value
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
