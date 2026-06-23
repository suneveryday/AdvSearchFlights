import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { mockSearchEnvelope } from "./mockResult";
import type { AlertPermissionStatus, AppSettings, AppSettingsUpdate, GuiSearchEnvelope, GuiSearchPayload, HistoryBatch, HistoryDetail, HistoryFilters, HistoryGroup, HistoryGroupDetail, HistoryGroupResults, HistorySchedule, NetworkCheckResult, ScheduleStatus, SearchProgressEvent } from "./types";

type InvokeFn = (command: string, args: Record<string, unknown>) => Promise<GuiSearchEnvelope>;
type HistoryDeleteInvokeFn = (command: string, args: Record<string, unknown>) => Promise<{ deleted: boolean }>;
type ScheduleToggleInvokeFn = (command: string, args: Record<string, unknown>) => Promise<{ item: HistorySchedule }>;
type ScheduleConfigureInvokeFn = (command: string, args: Record<string, unknown>) => Promise<{ item: HistorySchedule; immediate_queued: boolean }>;
type SettingsInvokeFn = (command: string, args?: Record<string, unknown>) => Promise<{ item: AppSettings }>;
type NetworkInvokeFn = (command: string, args: Record<string, unknown>) => Promise<NetworkCheckResult>;
let demoScheduleEnabled = true;

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export async function runGuiSearch(payload: GuiSearchPayload, invokeFn?: InvokeFn): Promise<GuiSearchEnvelope> {
  if (invokeFn) {
    return invokeFn("gui_search", { payload });
  }
  if (hasTauri()) {
    return invoke<GuiSearchEnvelope>("gui_search", { payload });
  }
  await wait(180);
  return mockSearchEnvelope;
}

export async function startGuiSearch(
  payload: GuiSearchPayload,
  onEvent: (event: SearchProgressEvent) => void,
): Promise<{ taskId: string; cancel: () => Promise<void>; cleanup: () => void }> {
  if (hasTauri()) {
    let activeTaskId: string | null = null;
    const unlisten = await listen<{ task_id: string; event: SearchProgressEvent }>("gui-search-event", (message) => {
      if (!activeTaskId || message.payload.task_id === activeTaskId) {
        onEvent(message.payload.event);
      }
    });
    activeTaskId = await invoke<string>("start_gui_search", { payload });
    return {
      taskId: activeTaskId,
      cancel: () => invoke<void>("cancel_gui_search", { taskId: activeTaskId }),
      cleanup: unlisten,
    };
  }

  const taskId = `mock-${Date.now()}`;
  const timers = mockProgress(onEvent);
  return {
    taskId,
    cancel: async () => {
      timers.forEach((timer) => globalThis.clearTimeout(timer));
      onEvent({ type: "failed", message: "搜索已取消" });
    },
    cleanup: () => timers.forEach((timer) => globalThis.clearTimeout(timer)),
  };
}

export async function runNetworkCheck(payload: GuiSearchPayload, mode: "first_run" | "startup" | "manual" = "manual", invokeFn?: NetworkInvokeFn): Promise<NetworkCheckResult> {
  if (invokeFn) {
    return invokeFn("network_check", { payload, mode });
  }
  if (hasTauri()) {
    return invoke<NetworkCheckResult>("network_check", { payload, mode });
  }
  await wait(160);
  return {
    status: "ok",
    guide_status: mode === "manual" ? "proxy_auto_configured" : "direct_ok",
    user_message: "网络检测通过",
    auto_configured: false,
    manual_required: false,
    modules: [
      { name: "proxy", label: "代理配置", status: "ok", ok: true, message: "已检测到代理环境" },
      { name: "fli_cli", label: "fli CLI", status: "ok", ok: true, message: "找到 fli CLI" },
      { name: "google_flights", label: "Google Flights 页面", status: "ok", ok: true, message: "Google Flights 可访问" },
      { name: "github_releases", label: "GitHub Releases", status: "warning", ok: false, message: "开发态 mock 未执行真实检测" },
    ],
  };
}

export async function listHistory(): Promise<HistoryBatch[]> {
  if (hasTauri()) {
    const response = await invoke<{ items: HistoryBatch[] }>("history_list", { limit: 50 });
    return response.items;
  }
  return [];
}

export async function getHistory(batchId: string): Promise<HistoryDetail | null> {
  if (hasTauri()) {
    const response = await invoke<{ item: HistoryDetail | null }>("history_get", { batchId });
    return response.item;
  }
  return null;
}

export async function listHistoryGroups(): Promise<HistoryGroup[]> {
  if (!hasTauri()) return historyDemoEnabled() ? [demoHistoryGroup()] : [];
  const response = await invoke<{ items: HistoryGroup[] }>("history_group_list", { limit: 100 });
  return response.items;
}

export async function getHistoryGroup(groupId: string): Promise<HistoryGroupDetail | null> {
  if (!hasTauri()) return historyDemoEnabled() && groupId === "demo-group" ? { ...demoHistoryGroup(), batches: demoHistoryBatches() } : null;
  const response = await invoke<{ item: HistoryGroupDetail | null }>("history_group_get", { groupId });
  return response.item;
}

export async function getHistoryGroupResults(groupId: string, batchId: string | null, filters: HistoryFilters): Promise<HistoryGroupResults | null> {
  if (!hasTauri()) return historyDemoEnabled() && groupId === "demo-group" ? demoHistoryResults(batchId, filters) : null;
  const response = await invoke<{ item: HistoryGroupResults | null }>("history_group_results", { groupId, batchId, filters });
  return response.item;
}

export async function deleteHistoryGroup(groupId: string, invokeFn?: HistoryDeleteInvokeFn): Promise<boolean> {
  if (invokeFn) {
    const response = await invokeFn("history_group_delete", { groupId });
    return response.deleted;
  }
  if (!hasTauri()) {
    await wait(800);
    return false;
  }
  const response = await invoke<{ deleted: boolean }>("history_group_delete", { groupId });
  return response.deleted;
}

export async function listHistorySchedules(): Promise<HistorySchedule[]> {
  if (!hasTauri()) return [];
  const response = await invoke<{ items: HistorySchedule[] }>("history_schedule_list");
  return response.items;
}

export async function toggleHistorySchedule(groupId: string, enabled: boolean, invokeFn?: ScheduleToggleInvokeFn): Promise<HistorySchedule> {
  if (!invokeFn && !hasTauri()) {
    demoScheduleEnabled = enabled;
    return { group_id: groupId, enabled, enabled_at: enabled ? new Date().toISOString() : null, next_run_at: enabled ? new Date(Date.now() + 3_600_000).toISOString() : null, last_run_at: null, status: enabled ? "scheduled" : "disabled", last_error: null, origin: "上海", destinations: ["墨尔本", "悉尼"], departure: "2026-09-29", return_date: "2026-10-07" };
  }
  const response = invokeFn
    ? await invokeFn("history_schedule_toggle", { groupId, enabled })
    : await invoke<{ item: HistorySchedule }>("history_schedule_toggle", { groupId, enabled });
  return response.item;
}

export async function configureHistorySchedule(
  groupId: string,
  intervalHours: number,
  notificationEnabled: boolean,
  priceThreshold: number | null,
  invokeFn?: ScheduleConfigureInvokeFn,
): Promise<{ item: HistorySchedule; immediate_queued: boolean }> {
  const args = { groupId, intervalHours, notificationEnabled, priceThreshold };
  if (invokeFn) return invokeFn("history_schedule_configure", args);
  if (!hasTauri()) {
    demoScheduleEnabled = true;
    return {
      item: {
        group_id: groupId, enabled: true, enabled_at: new Date().toISOString(),
        next_run_at: new Date(Date.now() + intervalHours * 3_600_000).toISOString(), last_run_at: null,
        status: "queued", last_error: null, interval_hours: intervalHours, notification_enabled: notificationEnabled,
        price_threshold: priceThreshold, desktop_last_notified_price: null, desktop_last_notified_at: null,
        reminder_last_notified_price: null, reminder_last_notified_at: null,
        origin: "上海", destinations: ["墨尔本", "悉尼"], departure: "2026-09-29", return_date: "2026-10-07",
      },
      immediate_queued: true,
    };
  }
  return invoke<{ item: HistorySchedule; immediate_queued: boolean }>("history_schedule_configure", args);
}

export async function getAlertPermissionStatus(requestReminders: boolean): Promise<AlertPermissionStatus> {
  if (!hasTauri()) return { desktop: "granted", reminders: requestReminders ? "granted" : "unchecked" };
  return invoke<AlertPermissionStatus>("alert_permission_status", { requestReminders });
}

export async function updateHistorySchedule(groupId: string, status: ScheduleStatus, error: string | null = null): Promise<HistorySchedule> {
  const response = await invoke<{ item: HistorySchedule }>("history_schedule_update", { groupId, status, error });
  return response.item;
}

export async function getAppSettings(): Promise<AppSettings> {
  if (!hasTauri()) return { rate_limit_retry_minutes: 5, analytics_consent: "unset", analytics_install_id: "browser-preview", http_proxy: "", all_proxy: "", first_network_check_succeeded: "false" };
  const response = await invoke<{ item: AppSettings }>("app_settings_get");
  return response.item;
}

export async function updateAppSettings(update: AppSettingsUpdate, invokeFn?: SettingsInvokeFn): Promise<AppSettings> {
  const args = {
    rateLimitRetryMinutes: update.rate_limit_retry_minutes,
    analyticsConsent: update.analytics_consent,
    httpProxy: update.http_proxy,
    allProxy: update.all_proxy,
    firstNetworkCheckSucceeded: update.first_network_check_succeeded,
  };
  if (invokeFn) {
    const response = await invokeFn("app_settings_update", args);
    return response.item;
  }
  if (!hasTauri()) return {
    rate_limit_retry_minutes: update.rate_limit_retry_minutes ?? 5,
    analytics_consent: update.analytics_consent ?? "unset",
    analytics_install_id: "browser-preview",
    http_proxy: update.http_proxy ?? "",
    all_proxy: update.all_proxy ?? "",
    first_network_check_succeeded: update.first_network_check_succeeded ?? "false",
  };
  const response = await invoke<{ item: AppSettings }>("app_settings_update", args);
  return response.item;
}

export async function configureScheduler(payload: GuiSearchPayload): Promise<void> {
  if (hasTauri()) await invoke<void>("configure_scheduler", { payload });
}

export async function subscribeScheduleEvents(onEvent: (payload: { group_id: string; event: SearchProgressEvent }) => void): Promise<() => void> {
  if (!hasTauri()) return () => undefined;
  return listen<{ group_id: string; event: SearchProgressEvent }>("schedule-status-event", (message) => onEvent(message.payload));
}

export async function openExternalUrl(url: string): Promise<void> {
  if (hasTauri()) {
    return invoke<void>("open_external_url", { url });
  }
  globalThis.open(url, "_blank", "noopener,noreferrer");
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms));
}

function mockProgress(onEvent: (event: SearchProgressEvent) => void): number[] {
  const events: SearchProgressEvent[] = [
    { type: "process_started", provider: "mock", message: "已启动本地搜索进程：provider=mock" },
    { type: "network_check", message: "网络预检：ok" },
    { type: "started", completed: 0, total: 4, message: "准备搜索 4 个单程组合" },
    { type: "leg_started", completed: 0, total: 4, origin: "PVG", destination: "MEL", message: "正在查询 PVG->MEL" },
    { type: "leg_finished", completed: 1, total: 4, origin: "PVG", destination: "MEL", message: "已完成 1/4：PVG->MEL" },
    { type: "leg_started", completed: 1, total: 4, origin: "SYD", destination: "PVG", message: "正在查询 SYD->PVG" },
    { type: "leg_finished", completed: 2, total: 4, origin: "SYD", destination: "PVG", message: "已完成 2/4：SYD->PVG" },
    { type: "combining", completed: 4, total: 4, message: "正在组合去程和回程结果" },
    { type: "completed", envelope: mockSearchEnvelope, message: "搜索完成" },
  ];
  return events.map((event, index) => globalThis.setTimeout(() => onEvent(event), 180 + index * 280));
}

function hasTauri(): boolean {
  return typeof window !== "undefined" && Boolean(window.__TAURI_INTERNALS__);
}

function historyDemoEnabled(): boolean {
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).get("historyDemo") === "1";
}

function demoHistoryGroup(): HistoryGroup {
  return {
    id: "demo-group", origin: "上海", destinations: ["墨尔本", "悉尼"], departure: "2026-09-29", return_date: "2026-10-07",
    cabin_class: "BUSINESS", adults: 1, max_stops: 1, max_layover_hours: 10, provider: "fli", currency: "CNY",
    created_at: "2026-06-10T04:00:00Z", updated_at: "2026-06-19T04:00:00Z", batch_count: 10, result_count: 100,
    latest_created_at: "2026-06-19T04:00:00Z", title: "上海 → 墨尔本 / 悉尼", date_label: "2026-09-29 至 2026-10-07",
    schedule_enabled: demoScheduleEnabled, schedule_enabled_at: demoScheduleEnabled ? "2026-06-19T04:30:00Z" : null, schedule_next_run_at: demoScheduleEnabled ? "2026-06-19T05:30:00Z" : null, schedule_status: demoScheduleEnabled ? "scheduled" : "disabled",
  };
}

function demoHistoryBatches(): HistoryBatch[] {
  return Array.from({ length: 10 }, (_, index) => ({
    id: `demo-batch-${index}`, created_at: `2026-06-${19 - index}T${String(4 + index).padStart(2, "0")}:00:00Z`, provider: "fli", origin: "上海",
    destinations: ["墨尔本", "悉尼"], departure: "2026-09-29", return_date: "2026-10-07", cabin_class: "BUSINESS",
    result_count: index === 2 ? 0 : 10, minimum_price_cny: index === 2 ? null : 12800 - (9 - index) * 900, label: `示例批次 ${index + 1}`,
  }));
}

function demoHistoryResults(batchId: string | null, filters: HistoryFilters): HistoryGroupResults {
  const batches = demoHistoryBatches();
  const selected = batches.find((item) => item.id === batchId) ?? batches[0];
  const sourceRows = mockSearchEnvelope.response?.rendered ?? [];
  const demoRows = sourceRows.length === 0 ? [] : Array.from({ length: 10 }, (_, index) => {
    const source = sourceRows[index % sourceRows.length];
    return {
      ...source,
      rank: index + 1,
      total_price_cny: source.total_price_cny + Math.floor(index / sourceRows.length) * 120,
    };
  });
  const rows = demoRows.filter((row) => filters.max_total_price == null || row.total_price_cny <= filters.max_total_price);
  return {
    group: demoHistoryGroup(), batches, selected_batch: selected, filters,
    filter_options: { airlines: ["中国南方航空", "宿务太平洋航空"], airport_routes: ["PVG→MEL / SYD→PVG"], layover_airports: ["CAN", "MNL"] },
    trend: batches.slice().reverse().map((batch, index) => ({ batch_id: batch.id, created_at: batch.created_at, label: batch.created_at.slice(5, 16).replace("T", " "), minimum_price_cny: batch.result_count ? 12800 - index * 900 : null, match_count: batch.result_count })),
    rendered: selected.result_count ? rows : [], result_count: selected.result_count ? rows.length : 0,
  };
}
