import { describe, expect, it } from "vitest";
import { visibleNetworkModules, visibleNetworkStatus } from "./networkPresentation";

describe("network presentation", () => {
  it("only exposes proxy and Google Flights checks", () => {
    const result = {
      status: "error" as const,
      modules: [
        { name: "proxy", label: "代理配置", status: "ok" as const, ok: true, message: "ok" },
        { name: "fli_cli", label: "fli CLI", status: "error" as const, ok: false, message: "missing" },
        { name: "google_flights", label: "Google Flights", status: "ok" as const, ok: true, message: "ok" },
        { name: "github_releases", label: "GitHub", status: "error" as const, ok: false, message: "offline" },
      ],
    };

    expect(visibleNetworkModules(result).map((item) => item.name)).toEqual(["proxy", "google_flights"]);
    expect(visibleNetworkStatus(result)).toBe("ok");
  });

  it("treats skipped proxy as ok when Google Flights is directly reachable", () => {
    const result = {
      status: "ok" as const,
      modules: [
        { name: "proxy", label: "代理配置", status: "skipped" as const, ok: null, message: "Google Flights 可直连，无需配置代理" },
        { name: "google_flights", label: "Google Flights", status: "ok" as const, ok: true, message: "ok" },
      ],
    };

    expect(visibleNetworkStatus(result)).toBe("ok");
  });
});
