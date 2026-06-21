import type { HistoryGroup } from "./types";

export interface ScheduleDraft {
  intervalHours: number;
  notificationEnabled: boolean;
  priceThreshold: number | null;
}

export function scheduleDraftForGroup(group: HistoryGroup, latestMinimumPrice: number | null = null): ScheduleDraft {
  return {
    intervalHours: group.schedule_interval_hours ?? 8,
    notificationEnabled: Boolean(group.schedule_notification_enabled),
    priceThreshold: group.schedule_price_threshold ?? latestMinimumPrice,
  };
}

export function validateScheduleDraft(draft: ScheduleDraft): string[] {
  const errors: string[] = [];
  if (!Number.isInteger(draft.intervalHours) || draft.intervalHours < 1 || draft.intervalHours > 48) {
    errors.push("定时搜索间隔必须为 1 到 48 小时");
  }
  if (draft.notificationEnabled && (!draft.priceThreshold || draft.priceThreshold <= 0 || !Number.isInteger(draft.priceThreshold))) {
    errors.push("开启提醒时请输入大于 0 的整数价格阈值");
  }
  return errors;
}
