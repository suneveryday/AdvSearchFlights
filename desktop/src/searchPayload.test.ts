import { describe, expect, it } from "vitest";
import { buildGuiSearchPayload, defaultSearchForm, destinationsFromText, validatePayload } from "./searchPayload";

describe("search payload mapping", () => {
  it("splits and de-duplicates destinations", () => {
    expect(destinationsFromText("墨尔本, 悉尼\nMEL，悉尼")).toEqual(["墨尔本", "悉尼", "MEL"]);
  });

  it("accepts slash, whitespace, semicolon, and mixed punctuation separators", () => {
    expect(destinationsFromText("墨尔本/悉尼；东京 Osaka，SIN\n曼谷")).toEqual([
      "墨尔本", "悉尼", "东京", "Osaka", "SIN", "曼谷",
    ]);
  });

  it("preserves known multi-word cities while splitting adjacent cities", () => {
    expect(destinationsFromText("New York Los Angeles")).toEqual(["New York", "Los Angeles"]);
    expect(destinationsFromText("Kuala Lumpur / Ho Chi Minh City")).toEqual(["Kuala Lumpur", "Ho Chi Minh City"]);
  });

  it("maps form state to gui-search JSON payload", () => {
    const payload = buildGuiSearchPayload({
      ...defaultSearchForm,
      origin: "北京",
      destinationsText: "东京, 大阪",
      departure: "2026-11-03",
      returnDate: "2026-11-10",
    });

    expect(payload.origin).toBe("北京");
    expect(payload.destinations).toEqual(["东京", "大阪"]);
    expect(payload.return_date).toBe("2026-11-10");
    expect(payload.provider).toBe("fli");
    expect(payload.format).toBe("json");
    expect(payload.cabin_class).toBe("ECONOMY");
    expect(payload.limit).toBe(50);
    expect(payload.no_cooldown).toBe(false);
    expect(payload.cooldown_seconds).toBe(2);
    expect(payload.retry_waits).toEqual([3, 8, 15]);
    expect(payload.request_interval_min_seconds).toBe(3);
    expect(payload.request_interval_max_seconds).toBe(8);
  });

  it("does not ship personal itinerary or proxy defaults", () => {
    expect(defaultSearchForm.origin).toBe("");
    expect(defaultSearchForm.destinationsText).toBe("");
    expect(defaultSearchForm.departure).toBe("");
    expect(defaultSearchForm.returnDate).toBe("");
    expect(defaultSearchForm.httpProxy).toBe("");
    expect(defaultSearchForm.allProxy).toBe("");
    expect(defaultSearchForm.limit).toBe(50);
  });

  it("maps a positive result limit without changing it", () => {
    expect(buildGuiSearchPayload({ ...defaultSearchForm, limit: 25 }).limit).toBe(25);
  });

  it("keeps zero as the explicit unlimited result option", () => {
    expect(buildGuiSearchPayload({ ...defaultSearchForm, limit: 0 }).limit).toBeNull();
  });

  it("maps saved proxy values into every child-process environment variant", () => {
    const payload = buildGuiSearchPayload({
      ...defaultSearchForm,
      httpProxy: "http://127.0.0.1:7893",
      allProxy: "socks5://127.0.0.1:7894",
    });

    expect(payload.proxy).toEqual({
      http_proxy: "http://127.0.0.1:7893",
      https_proxy: "http://127.0.0.1:7893",
      HTTP_PROXY: "http://127.0.0.1:7893",
      HTTPS_PROXY: "http://127.0.0.1:7893",
      all_proxy: "socks5://127.0.0.1:7894",
      ALL_PROXY: "socks5://127.0.0.1:7894",
    });
  });

  it("validates required fields", () => {
    const payload = buildGuiSearchPayload({ ...defaultSearchForm, origin: "", destinationsText: "" });

    expect(validatePayload(payload)).toContain("请输入出发城市或机场");
    expect(validatePayload(payload)).toContain("至少输入 1 个目的地");
  });
});
