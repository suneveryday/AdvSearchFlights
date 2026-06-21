import { describe, expect, it } from "vitest";
import { scheduleDraftForGroup, validateScheduleDraft } from "./scheduleSettings";
import type { HistoryGroup } from "./types";

const group = {
  id: "g1", origin: "上海", destinations: ["墨尔本"], departure: "2026-09-29", return_date: "2026-10-07",
  cabin_class: "ECONOMY", adults: 1, max_stops: 1, max_layover_hours: 10, provider: "fli", currency: "CNY",
  created_at: "2026-06-20T00:00:00Z", updated_at: "2026-06-20T00:00:00Z", title: "上海 → 墨尔本", date_label: "2026-09-29 至 2026-10-07",
} satisfies HistoryGroup;

describe("schedule settings", () => {
  it("defaults to eight hours and the latest minimum price", () => {
    expect(scheduleDraftForGroup(group, 7479)).toEqual({ intervalHours: 8, notificationEnabled: false, priceThreshold: 7479 });
  });

  it("preserves existing schedule settings", () => {
    expect(scheduleDraftForGroup({ ...group, schedule_interval_hours: 12, schedule_notification_enabled: true, schedule_price_threshold: 7000 }, 7479))
      .toEqual({ intervalHours: 12, notificationEnabled: true, priceThreshold: 7000 });
  });

  it("validates interval and enabled thresholds", () => {
    expect(validateScheduleDraft({ intervalHours: 0, notificationEnabled: false, priceThreshold: null })).toContain("定时搜索间隔必须为 1 到 48 小时");
    expect(validateScheduleDraft({ intervalHours: 8, notificationEnabled: true, priceThreshold: null })).toContain("开启提醒时请输入大于 0 的整数价格阈值");
    expect(validateScheduleDraft({ intervalHours: 48, notificationEnabled: true, priceThreshold: 7000 })).toEqual([]);
  });
});
