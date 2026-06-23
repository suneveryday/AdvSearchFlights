from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field


GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights"
GITHUB_RELEASES_URL = "https://api.github.com/repos/suneveryday/AdvSearchFlights/releases/latest"
PROXY_ENV_KEYS = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY")


class NetworkCheck(BaseModel):
    name: str
    status: str
    ok: bool | None
    message: str
    latency_ms: int | None = None
    details: dict[str, Any] | None = None


class ProxySummary(BaseModel):
    has_proxy: bool
    http_proxy: str | None = None
    https_proxy: str | None = None
    all_proxy: str | None = None
    no_proxy: str | None = None


class ProxyCandidate(BaseModel):
    source: str
    http_proxy: str | None = None
    all_proxy: str | None = None
    status: str = "unchecked"
    message: str | None = None
    latency_ms: int | None = None


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


def diagnose_network(provider: str, *, timeout_seconds: float = 8.0, check_google: bool = True) -> NetworkDiagnostics:
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


def diagnose_network_modules(provider: str = "fli", *, timeout_seconds: float = 8.0, mode: str = "manual") -> dict[str, Any]:
    if mode in {"startup", "first_run"}:
        return diagnose_startup_network_modules(provider, timeout_seconds=timeout_seconds)
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
    return {
        "status": status,
        "modules": modules,
        "proxy": proxy.model_dump(mode="json"),
        "direct_google_flights": None,
        "proxy_candidates": [],
        "selected_proxy": None,
        "auto_configured": False,
        "manual_required": False,
        "guide_status": "direct_ok" if status == "ok" else "error",
        "user_message": "网络检测通过" if status == "ok" else "网络检测未通过，请检查当前网络或代理设置",
    }


def diagnose_startup_network_modules(provider: str = "fli", *, timeout_seconds: float = 8.0) -> dict[str, Any]:
    provider_name = provider.lower()
    direct = _check_google_flights_with_proxy_env(None, timeout_seconds, clear_proxy=True)
    if provider_name not in {"auto", "fli"} or direct.ok:
        current_proxy = summarize_proxy_env()
        modules = [
            {
                "name": "proxy",
                "label": "代理配置",
                "status": "skipped",
                "ok": None,
                "message": "当前网络可访问 Google Flights，无需手动配置代理",
            },
            _module("google_flights", "Google Flights 页面", direct),
        ]
        return {
            "status": "ok" if direct.ok else "warning",
            "modules": modules,
            "proxy": current_proxy.model_dump(mode="json"),
            "direct_google_flights": _module("google_flights", "Google Flights 页面", direct),
            "proxy_candidates": [],
            "selected_proxy": None,
            "auto_configured": False,
            "manual_required": False,
            "guide_status": "direct_ok" if direct.ok else "error",
            "user_message": "当前网络可直接访问 Google Flights" if direct.ok else "当前网络暂时无法访问 Google Flights",
        }

    candidates = _proxy_candidates(include_environment=False)
    selected: ProxyCandidate | None = None
    selected_check: NetworkCheck | None = None
    checked_candidates: list[ProxyCandidate] = []
    for candidate in candidates:
        env = _candidate_env(candidate)
        check = _check_google_flights_with_proxy_env(env, timeout_seconds, clear_proxy=True)
        candidate.status = "ok" if check.ok else check.status
        candidate.message = check.message
        candidate.latency_ms = check.latency_ms
        checked_candidates.append(candidate)
        if check.ok and selected is None:
            selected = candidate
            selected_check = check
            break

    if selected is not None:
        _activate_proxy_candidate(selected)
        _persist_proxy_candidate(selected)
        proxy_summary = summarize_proxy_env(_candidate_env(selected))
        modules = [
            {
                "name": "proxy",
                "label": "代理配置",
                "status": "ok",
                "ok": True,
                "message": f"已自动发现可用代理：{selected.source}",
                "details": proxy_summary.model_dump(mode="json"),
            },
            _module("google_flights", "Google Flights 页面", selected_check or direct),
        ]
        return {
            "status": "ok",
            "modules": modules,
            "proxy": proxy_summary.model_dump(mode="json"),
            "direct_google_flights": _module("google_flights", "Google Flights 页面", direct),
            "proxy_candidates": [_candidate_payload(item) for item in checked_candidates],
            "selected_proxy": _candidate_payload(selected),
            "auto_configured": True,
            "manual_required": False,
            "guide_status": "proxy_auto_configured",
            "user_message": "已自动发现并保存可用代理，Google Flights 连接正常",
        }

    modules = [
        {
            "name": "proxy",
            "label": "代理配置",
            "status": "warning",
            "ok": False,
            "message": "当前网络无法访问 Google Flights；可在设置中手动填写代理作为排障选项",
        },
        _module("google_flights", "Google Flights 页面", direct),
    ]
    return {
        "status": "error",
        "modules": modules,
        "proxy": summarize_proxy_env({}).model_dump(mode="json"),
        "direct_google_flights": _module("google_flights", "Google Flights 页面", direct),
        "proxy_candidates": [_candidate_payload(item) for item in checked_candidates],
        "selected_proxy": None,
        "auto_configured": False,
        "manual_required": True,
        "guide_status": "needs_manual_proxy",
        "user_message": "无法连接 Google Flights，请检查网络或手动填写代理",
    }


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
    return _check_google_flights_with_proxy_env(None, timeout_seconds, clear_proxy=False)


def _check_google_flights_with_proxy_env(env: dict[str, str] | None, timeout_seconds: float, *, clear_proxy: bool) -> NetworkCheck:
    start = time.monotonic()
    request_env = os.environ.copy()
    if clear_proxy:
        for key in PROXY_ENV_KEYS:
            request_env.pop(key, None)
    if env:
        request_env.update({key: value for key, value in env.items() if value})
    curl = shutil.which("curl") or "/usr/bin/curl"
    try:
        completed = subprocess.run(
            [
                curl,
                "-I",
                "-L",
                "--max-time",
                str(max(1, int(round(timeout_seconds)))),
                "-sS",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                GOOGLE_FLIGHTS_URL,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 1,
            check=False,
            env=request_env,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        status_text = (completed.stdout or "").strip()
        status_code = int(status_text[-3:]) if status_text[-3:].isdigit() else 0
        if completed.returncode == 0 and 0 < status_code < 500:
            return NetworkCheck(
                name="google_flights",
                status="ok",
                ok=True,
                message=f"Google Flights 可访问，HTTP {status_code}",
                latency_ms=latency_ms,
            )
        if completed.returncode != 0:
            raw_message = (completed.stderr or completed.stdout or f"curl exit {completed.returncode}").strip()
            return NetworkCheck(
                name="google_flights",
                status="error",
                ok=False,
                message=_friendly_google_error(raw_message),
                latency_ms=latency_ms,
                details={"raw_message": raw_message, "curl_exit_code": completed.returncode},
            )
        return NetworkCheck(
            name="google_flights",
            status="warning",
            ok=False,
            message=f"Google Flights 返回 HTTP {status_code}",
            latency_ms=latency_ms,
        )
    except subprocess.TimeoutExpired:
        latency_ms = int((time.monotonic() - start) * 1000)
        return NetworkCheck(
            name="google_flights",
            status="error",
            ok=False,
            message="Google Flights 连接超时，当前网络可能不可达或代理未生效",
            latency_ms=latency_ms,
            details={"raw_message": "subprocess timeout"},
        )
    except httpx.HTTPError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return NetworkCheck(name="google_flights", status="error", ok=False, message=f"Google Flights 不可达：{exc}", latency_ms=latency_ms)
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return NetworkCheck(name="google_flights", status="error", ok=False, message=f"Google Flights 检查失败：{exc}", latency_ms=latency_ms)


def _friendly_google_error(raw_message: str) -> str:
    normalized = raw_message.lower()
    if "timed out" in normalized or "timeout" in normalized or "operation timed out" in normalized:
        return "Google Flights 连接超时，当前网络可能不可达或代理未生效"
    if "could not resolve" in normalized or "name or service not known" in normalized:
        return "Google Flights 域名解析失败，请检查当前网络或 DNS 设置"
    if "failed to connect" in normalized or "connection refused" in normalized:
        return "Google Flights 连接失败，请检查当前网络或代理是否可用"
    return "Google Flights 暂时不可达，请检查当前网络或代理设置"


def _proxy_candidates(*, include_environment: bool = True) -> list[ProxyCandidate]:
    candidates: list[ProxyCandidate] = []
    candidates.extend(_saved_proxy_candidates())
    candidates.extend(_macos_proxy_candidates())
    candidates.extend(_common_local_proxy_candidates())
    if include_environment:
        candidates.extend(_environment_proxy_candidates())
    result: list[ProxyCandidate] = []
    seen: set[tuple[str | None, str | None]] = set()
    for candidate in candidates:
        key = (candidate.http_proxy, candidate.all_proxy)
        if key == (None, None) or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _saved_proxy_candidates() -> list[ProxyCandidate]:
    try:
        from adv_search_flights.history import get_app_settings

        settings = get_app_settings()
    except Exception:
        return []
    return [
        ProxyCandidate(
            source="saved_settings",
            http_proxy=settings.get("http_proxy") or None,
            all_proxy=settings.get("all_proxy") or None,
        )
    ]


def _environment_proxy_candidates() -> list[ProxyCandidate]:
    http_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    all_proxy = os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
    return [ProxyCandidate(source="environment", http_proxy=http_proxy, all_proxy=all_proxy)]


def _macos_proxy_candidates() -> list[ProxyCandidate]:
    if sys.platform != "darwin":
        return []
    try:
        output = subprocess.run(["scutil", "--proxy"], capture_output=True, text=True, timeout=2, check=False).stdout
    except Exception:
        return []
    values: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    candidates: list[ProxyCandidate] = []
    if values.get("HTTPEnable") == "1" and values.get("HTTPProxy") and values.get("HTTPPort"):
        candidates.append(ProxyCandidate(source="macos_http_proxy", http_proxy=f"http://{values['HTTPProxy']}:{values['HTTPPort']}"))
    if values.get("HTTPSEnable") == "1" and values.get("HTTPSProxy") and values.get("HTTPSPort"):
        candidates.append(ProxyCandidate(source="macos_https_proxy", http_proxy=f"http://{values['HTTPSProxy']}:{values['HTTPSPort']}"))
    if values.get("SOCKSEnable") == "1" and values.get("SOCKSProxy") and values.get("SOCKSPort"):
        candidates.append(ProxyCandidate(source="macos_socks_proxy", all_proxy=f"socks5://{values['SOCKSProxy']}:{values['SOCKSPort']}"))
    return candidates


def _common_local_proxy_candidates() -> list[ProxyCandidate]:
    candidates: list[ProxyCandidate] = []
    for port in (7893, 7890, 8080, 1087, 1080):
        if _local_port_open(port):
            candidates.append(ProxyCandidate(source=f"local_http_{port}", http_proxy=f"http://127.0.0.1:{port}"))
    for port in (7894, 7891, 1086, 1080):
        if _local_port_open(port):
            candidates.append(ProxyCandidate(source=f"local_socks_{port}", all_proxy=f"socks5://127.0.0.1:{port}"))
    return candidates


def _local_port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _candidate_env(candidate: ProxyCandidate) -> dict[str, str]:
    env: dict[str, str] = {}
    if candidate.http_proxy:
        env.update({
            "http_proxy": candidate.http_proxy,
            "https_proxy": candidate.http_proxy,
            "HTTP_PROXY": candidate.http_proxy,
            "HTTPS_PROXY": candidate.http_proxy,
        })
    if candidate.all_proxy:
        env.update({"all_proxy": candidate.all_proxy, "ALL_PROXY": candidate.all_proxy})
    return env


def _persist_proxy_candidate(candidate: ProxyCandidate) -> None:
    try:
        from adv_search_flights.history import update_app_settings

        update_app_settings(http_proxy=candidate.http_proxy or "", all_proxy=candidate.all_proxy or "")
    except Exception:
        pass


def _activate_proxy_candidate(candidate: ProxyCandidate) -> None:
    for key in PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.update(_candidate_env(candidate))


def _candidate_payload(candidate: ProxyCandidate) -> dict[str, Any]:
    return {
        "source": candidate.source,
        "http_proxy": _redact_proxy(candidate.http_proxy),
        "all_proxy": _redact_proxy(candidate.all_proxy),
        "status": candidate.status,
        "message": candidate.message,
        "latency_ms": candidate.latency_ms,
    }


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
