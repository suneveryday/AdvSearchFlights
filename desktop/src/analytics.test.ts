import { describe, expect, it, vi } from "vitest";
import { captureAnalytics, configureAnalytics, durationBucket, normalizedErrorCategory, resultCountBucket, sanitizeCaptureResult, setAnalyticsClientForTests } from "./analytics";

const settings = { rate_limit_retry_minutes: 5, analytics_consent: "granted" as const, analytics_install_id: "test-install-id", http_proxy: "", all_proxy: "" };

describe("anonymous analytics safeguards", () => {
  it("keeps only the explicit event property allowlist", () => {
    const sanitized = sanitizeCaptureResult({
      uuid: "event-id",
      event: "farello_search_finished",
      properties: {
        token: "public-project-token",
        distinct_id: "install-id",
        source: "manual",
        outcome: "results",
        result_count_bucket: "11-50",
        duration_bucket: "30-120s",
        route: "PVG-MEL",
        price: 7492,
        $current_url: "tauri://localhost/search?origin=PVG",
        $referrer: "private",
      },
    });

    expect(sanitized?.properties).toEqual({
      token: "public-project-token",
      distinct_id: "install-id",
      source: "manual",
      outcome: "results",
      result_count_bucket: "11-50",
      duration_bucket: "30-120s",
    });
  });

  it("drops unknown events entirely", () => {
    expect(sanitizeCaptureResult({ uuid: "id", event: "$pageview", properties: { distinct_id: "id" } })).toBeNull();
  });

  it("uses stable result, duration, and error categories", () => {
    expect([resultCountBucket(0), resultCountBucket(8), resultCountBucket(40), resultCountBucket(80)]).toEqual(["0", "1-10", "11-50", "51+"]);
    expect([durationBucket(1000), durationBucket(6000), durationBucket(40000), durationBucket(180000)]).toEqual(["<5s", "5-30s", "30-120s", ">=120s"]);
    expect(normalizedErrorCategory("Google Flights 返回 ErrorResponse")).toBe("provider");
    expect(normalizedErrorCategory("连接超时")).toBe("timeout");
  });

  it("sends nothing while consent is disabled", () => {
    const capture = vi.fn();
    const optOut = vi.fn();
    setAnalyticsClientForTests({ init: vi.fn(), capture, opt_in_capturing: vi.fn(), opt_out_capturing: optOut }, true);
    configureAnalytics({ ...settings, analytics_consent: "denied" });
    captureAnalytics("farello_workspace_viewed", { workspace: "search" });
    expect(capture).not.toHaveBeenCalled();
  });

  it("sends only typed product events after consent", () => {
    const capture = vi.fn();
    const init = vi.fn();
    setAnalyticsClientForTests({ init, capture, opt_in_capturing: vi.fn(), opt_out_capturing: vi.fn() }, true);
    configureAnalytics(settings);
    captureAnalytics("farello_workspace_viewed", { workspace: "history" });
    expect(init).toHaveBeenCalledOnce();
    expect(capture).toHaveBeenCalledWith("farello_workspace_viewed", { workspace: "history" });
  });

  it("degrades safely when analytics configuration is unavailable", () => {
    const capture = vi.fn();
    setAnalyticsClientForTests({ init: vi.fn(), capture, opt_in_capturing: vi.fn(), opt_out_capturing: vi.fn() }, false);
    configureAnalytics(settings);
    captureAnalytics("farello_app_opened", { app_version: "0.10.0", platform: "macos" });
    expect(capture).not.toHaveBeenCalled();
  });
});
