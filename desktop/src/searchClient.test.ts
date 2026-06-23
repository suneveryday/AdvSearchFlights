import { afterEach, describe, expect, it, vi } from "vitest";
import { defaultSearchForm, buildGuiSearchPayload } from "./searchPayload";
import { configureHistorySchedule, deleteHistoryGroup, getHistoryGroupResults, listHistory, listHistoryGroups, runGuiSearch, runNetworkCheck, startGuiSearch, toggleHistorySchedule, updateAppSettings } from "./searchClient";

afterEach(() => vi.unstubAllGlobals());

describe("search client", () => {
  it("invokes the tauri gui_search command when an invoker is provided", async () => {
    const payload = buildGuiSearchPayload(defaultSearchForm);
    const calls: Array<{ command: string; args: Record<string, unknown> }> = [];
    const envelope = await runGuiSearch(payload, async (command, args) => {
      calls.push({ command, args });
      return {
        ok: false,
        response: null,
        network_status: null,
        provider_status: { provider: "mock", status: "no_results", result_count: 0, warnings: [], categories: ["no_results"] },
        error: { type: "test", message: "test" },
      };
    });

    expect(calls[0].command).toBe("gui_search");
    expect(calls[0].args.payload).toEqual(payload);
    expect(envelope.error?.type).toBe("test");
  });

  it("simulates progress events outside Tauri", async () => {
    const payload = buildGuiSearchPayload(defaultSearchForm);
    const events: string[] = [];
    const task = await startGuiSearch(payload, (event) => events.push(event.type));

    await new Promise((resolve) => setTimeout(resolve, 2500));
    task.cleanup();

    expect(events).toContain("started");
    expect(events).toContain("completed");
  });

  it("returns a mock network check outside Tauri", async () => {
    const result = await runNetworkCheck(buildGuiSearchPayload(defaultSearchForm));

    expect(result.modules.map((item) => item.name)).toContain("google_flights");
  });

  it("passes first-run and manual modes to the Tauri network command", async () => {
    const payload = buildGuiSearchPayload(defaultSearchForm);
    const calls: Array<{ command: string; args: Record<string, unknown> }> = [];
    await runNetworkCheck(payload, "first_run", async (command, args) => {
      calls.push({ command, args });
      return { status: "ok", modules: [], guide_status: "direct_ok" };
    });
    await runNetworkCheck(payload, "manual", async (command, args) => {
      calls.push({ command, args });
      return { status: "ok", modules: [], guide_status: "proxy_auto_configured" };
    });

    expect(calls).toEqual([
      { command: "network_check", args: { payload, mode: "first_run" } },
      { command: "network_check", args: { payload, mode: "manual" } },
    ]);
  });

  it("does not expose mock search results as saved history outside Tauri", async () => {
    await expect(listHistory()).resolves.toEqual([]);
  });

  it("maps history group deletion to the Tauri command contract", async () => {
    const calls: Array<{ command: string; args: Record<string, unknown> }> = [];
    const deleted = await deleteHistoryGroup("group-123", async (command, args) => {
      calls.push({ command, args });
      return { deleted: true };
    });

    expect(deleted).toBe(true);
    expect(calls).toEqual([{ command: "history_group_delete", args: { groupId: "group-123" } }]);
  });

  it("maps schedule toggles and retry settings to Tauri command contracts", async () => {
    const scheduleCalls: Array<{ command: string; args: Record<string, unknown> }> = [];
    await toggleHistorySchedule("group-1", true, async (command, args) => {
      scheduleCalls.push({ command, args });
      return { item: { group_id: "group-1", enabled: true, enabled_at: null, next_run_at: null, last_run_at: null, status: "scheduled", last_error: null, origin: "上海", destinations: ["悉尼"], departure: "2026-09-01", return_date: "2026-09-10" } };
    });
    const settingsCalls: Array<{ command: string; args?: Record<string, unknown> }> = [];
    await updateAppSettings({ rate_limit_retry_minutes: 10 }, async (command, args) => {
      settingsCalls.push({ command, args });
      return { item: { rate_limit_retry_minutes: 10, analytics_consent: "unset", analytics_install_id: "test-id", http_proxy: "", all_proxy: "", first_network_check_succeeded: "false" } };
    });

    expect(scheduleCalls).toEqual([{ command: "history_schedule_toggle", args: { groupId: "group-1", enabled: true } }]);
    expect(settingsCalls).toEqual([{ command: "app_settings_update", args: { rateLimitRetryMinutes: 10, analyticsConsent: undefined, httpProxy: undefined, allProxy: undefined, firstNetworkCheckSucceeded: undefined } }]);
  });

  it("updates analytics consent without overwriting unrelated settings", async () => {
    const calls: Array<{ command: string; args?: Record<string, unknown> }> = [];
    await updateAppSettings({ analytics_consent: "denied" }, async (command, args) => {
      calls.push({ command, args });
      return { item: { rate_limit_retry_minutes: 5, analytics_consent: "denied", analytics_install_id: "test-id", http_proxy: "", all_proxy: "", first_network_check_succeeded: "false" } };
    });

    expect(calls).toEqual([{ command: "app_settings_update", args: { rateLimitRetryMinutes: undefined, analyticsConsent: "denied", httpProxy: undefined, allProxy: undefined, firstNetworkCheckSucceeded: undefined } }]);
  });

  it("persists proxy settings through the Tauri settings contract", async () => {
    const calls: Array<{ command: string; args?: Record<string, unknown> }> = [];
    await updateAppSettings({ http_proxy: "http://127.0.0.1:7893", all_proxy: "socks5://127.0.0.1:7894" }, async (command, args) => {
      calls.push({ command, args });
      return { item: { rate_limit_retry_minutes: 5, analytics_consent: "unset", analytics_install_id: "test-id", http_proxy: "http://127.0.0.1:7893", all_proxy: "socks5://127.0.0.1:7894", first_network_check_succeeded: "false" } };
    });

    expect(calls).toEqual([{ command: "app_settings_update", args: {
      rateLimitRetryMinutes: undefined,
      analyticsConsent: undefined,
      httpProxy: "http://127.0.0.1:7893",
      allProxy: "socks5://127.0.0.1:7894",
      firstNetworkCheckSucceeded: undefined,
    } }]);
  });

  it("persists first network check completion through settings", async () => {
    const calls: Array<{ command: string; args?: Record<string, unknown> }> = [];
    await updateAppSettings({ first_network_check_succeeded: "true" }, async (command, args) => {
      calls.push({ command, args });
      return { item: { rate_limit_retry_minutes: 5, analytics_consent: "unset", analytics_install_id: "test-id", http_proxy: "", all_proxy: "", first_network_check_succeeded: "true" } };
    });

    expect(calls).toEqual([{ command: "app_settings_update", args: {
      rateLimitRetryMinutes: undefined,
      analyticsConsent: undefined,
      httpProxy: undefined,
      allProxy: undefined,
      firstNetworkCheckSucceeded: "true",
    } }]);
  });

  it("maps configurable schedules to the immediate queue command", async () => {
    const calls: Array<{ command: string; args: Record<string, unknown> }> = [];
    await configureHistorySchedule("group-1", 8, true, 7000, async (command, args) => {
      calls.push({ command, args });
      return { item: {} as never, immediate_queued: true };
    });
    expect(calls).toEqual([{
      command: "history_schedule_configure",
      args: { groupId: "group-1", intervalHours: 8, notificationEnabled: true, priceThreshold: 7000 },
    }]);
  });

  it("exposes an isolated history demo for visual regression without saving mock history", async () => {
    vi.stubGlobal("window", { location: { search: "?historyDemo=1" } });
    const groups = await listHistoryGroups();
    const results = await getHistoryGroupResults(groups[0].id, null, {
      max_total_price: 7500,
      include_airlines: [],
      exclude_airlines: [],
      airport_routes: [],
      max_stops_per_leg: null,
      max_single_layover_hours: null,
      exclude_layover_airports: [],
      departure_time_range: null,
      arrival_time_range: null,
    });

    expect(groups[0].title).toBe("上海 → 墨尔本 / 悉尼");
    expect(results?.trend.some((point) => point.minimum_price_cny === null)).toBe(true);
    expect(results?.rendered.every((row) => row.total_price_cny <= 7500)).toBe(true);
    await expect(listHistory()).resolves.toEqual([]);
  });
});
