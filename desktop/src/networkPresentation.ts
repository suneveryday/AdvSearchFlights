import type { NetworkCheckModule, NetworkCheckResult } from "./types";

const VISIBLE_NETWORK_MODULES = new Set(["proxy", "google_flights"]);

export function visibleNetworkModules(result: NetworkCheckResult | null): NetworkCheckModule[] {
  return (result?.modules ?? []).filter((item) => VISIBLE_NETWORK_MODULES.has(item.name));
}

export function visibleNetworkStatus(result: NetworkCheckResult | null): NetworkCheckResult["status"] | null {
  const modules = visibleNetworkModules(result);
  if (!modules.length) return result?.status ?? null;
  if (modules.some((item) => item.status === "error")) return "error";
  if (modules.some((item) => item.status === "warning")) return "warning";
  return "ok";
}
