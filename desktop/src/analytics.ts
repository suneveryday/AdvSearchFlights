import posthog from "posthog-js/dist/module.no-external";
import type { CaptureResult, PostHog } from "posthog-js/dist/module.no-external";
import packageInfo from "../package.json";
import type { AppSettings, NetworkCheckResult } from "./types";

export type AnalyticsEventProperties = {
  farello_app_opened: { app_version: string; platform: "macos" | "other" };
  farello_workspace_viewed: { workspace: "search" | "history" };
  farello_search_started: { source: "manual" | "scheduled" };
  farello_search_finished: { source: "manual" | "scheduled"; outcome: "results" | "empty"; result_count_bucket: ResultCountBucket; duration_bucket: DurationBucket };
  farello_search_failed: { source: "manual" | "scheduled"; error_category: ErrorCategory };
  farello_search_cancelled: { source: "manual" };
  farello_network_check_finished: { trigger: "startup" | "manual"; proxy_status: SafeStatus; google_flights_status: SafeStatus };
  farello_history_opened: Record<string, never>;
  farello_schedule_configured: { interval_hours: number; notification_enabled: boolean };
  farello_schedule_disabled: Record<string, never>;
  farello_alert_delivery: { channel: "desktop" | "reminders"; outcome: "success" | "failure" };
};

export type AnalyticsEventName = keyof AnalyticsEventProperties;
export type ResultCountBucket = "0" | "1-10" | "11-50" | "51+";
export type DurationBucket = "<5s" | "5-30s" | "30-120s" | ">=120s";
export type ErrorCategory = "validation" | "cancelled" | "timeout" | "network" | "provider" | "no_results" | "unknown";
type SafeStatus = "ok" | "warning" | "error" | "skipped" | "unknown";

const eventPropertyAllowlist: { [K in AnalyticsEventName]: ReadonlyArray<keyof AnalyticsEventProperties[K]> } = {
  farello_app_opened: ["app_version", "platform"],
  farello_workspace_viewed: ["workspace"],
  farello_search_started: ["source"],
  farello_search_finished: ["source", "outcome", "result_count_bucket", "duration_bucket"],
  farello_search_failed: ["source", "error_category"],
  farello_search_cancelled: ["source"],
  farello_network_check_finished: ["trigger", "proxy_status", "google_flights_status"],
  farello_history_opened: [],
  farello_schedule_configured: ["interval_hours", "notification_enabled"],
  farello_schedule_disabled: [],
  farello_alert_delivery: ["channel", "outcome"],
};

const projectToken = import.meta.env.VITE_POSTHOG_PROJECT_TOKEN?.trim();
const apiHost = import.meta.env.VITE_POSTHOG_HOST?.trim() || "https://us.i.posthog.com";
const productionTauri = import.meta.env.PROD && "__TAURI_INTERNALS__" in globalThis;
let initialized = false;
let enabled = false;
let availabilityOverride: boolean | null = null;
let client: Pick<PostHog, "init" | "capture" | "opt_in_capturing" | "opt_out_capturing"> = posthog;

export function analyticsAvailable(): boolean {
  return availabilityOverride ?? (productionTauri && Boolean(projectToken && apiHost));
}

export function configureAnalytics(settings: AppSettings): void {
  if (!analyticsAvailable()) return;
  if (settings.analytics_consent !== "granted") {
    enabled = false;
    if (initialized) client.opt_out_capturing();
    return;
  }
  if (!initialized) {
    client.init(projectToken!, {
      api_host: apiHost,
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      disable_session_recording: true,
      person_profiles: "never",
      persistence: "memory",
      advanced_disable_feature_flags: true,
      disable_surveys: true,
      opt_out_capturing_by_default: false,
      bootstrap: { distinctID: settings.analytics_install_id, isIdentifiedID: false },
      before_send: sanitizeCaptureResult,
    });
    initialized = true;
  } else {
    client.opt_in_capturing();
  }
  enabled = true;
}

export function captureAnalytics<K extends AnalyticsEventName>(event: K, properties: AnalyticsEventProperties[K]): void {
  if (!enabled) return;
  try {
    client.capture(event, properties);
  } catch {
    // Analytics must never affect product behavior.
  }
}

export function captureAppOpened(): void {
  captureAnalytics("farello_app_opened", {
    app_version: packageInfo.version,
    platform: navigator.platform.toLowerCase().includes("mac") ? "macos" : "other",
  });
}

export function sanitizeCaptureResult(result: CaptureResult | null): CaptureResult | null {
  if (!result || !(result.event in eventPropertyAllowlist)) return null;
  const event = result.event as AnalyticsEventName;
  const allowed = new Set<string>(eventPropertyAllowlist[event] as readonly string[]);
  const properties: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(result.properties || {})) {
    if (allowed.has(key) || key === "token" || key === "distinct_id" || key === "$process_person_profile") {
      properties[key] = value;
    }
  }
  return { ...result, properties };
}

export function resultCountBucket(count: number): ResultCountBucket {
  if (count <= 0) return "0";
  if (count <= 10) return "1-10";
  if (count <= 50) return "11-50";
  return "51+";
}

export function durationBucket(durationMs: number): DurationBucket {
  if (durationMs < 5_000) return "<5s";
  if (durationMs < 30_000) return "5-30s";
  if (durationMs < 120_000) return "30-120s";
  return ">=120s";
}

export function normalizedErrorCategory(message: string): ErrorCategory {
  const text = message.toLowerCase();
  if (text.includes("取消") || text.includes("cancel")) return "cancelled";
  if (text.includes("超时") || text.includes("timeout")) return "timeout";
  if (text.includes("网络") || text.includes("连接") || text.includes("proxy") || text.includes("network")) return "network";
  if (text.includes("无结果") || text.includes("没有符合") || text.includes("no result")) return "no_results";
  if (text.includes("参数") || text.includes("请输入") || text.includes("日期")) return "validation";
  if (text.includes("provider") || text.includes("google flights") || text.includes("errorresponse") || text.includes("数据源")) return "provider";
  return "unknown";
}

export function networkAnalyticsProperties(result: NetworkCheckResult, trigger: "startup" | "manual"): AnalyticsEventProperties["farello_network_check_finished"] {
  const moduleStatus = (name: string): SafeStatus => {
    const status = result.modules.find((item) => item.name === name)?.status;
    return status === "ok" || status === "warning" || status === "error" || status === "skipped" ? status : "unknown";
  };
  return {
    trigger,
    proxy_status: moduleStatus("proxy"),
    google_flights_status: moduleStatus("google_flights"),
  };
}

export function setAnalyticsClientForTests(nextClient: typeof client, available = true): void {
  client = nextClient;
  initialized = false;
  enabled = false;
  availabilityOverride = available;
}
