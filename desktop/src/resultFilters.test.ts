import { describe, expect, it } from "vitest";
import { buildResultFilterOptions, formatHistoryBatchTimestamp, matchesResultFilters, nextHistoryGroupAfterDeletion, timeMatches } from "./App";
import { mockSearchEnvelope } from "./mockResult";
import type { HistoryFilters, HistoryGroup, RenderedResult } from "./types";

const emptyFilters: HistoryFilters = {
  max_total_price: null,
  include_airlines: [],
  exclude_airlines: [],
  airport_routes: [],
  max_stops_per_leg: null,
  max_single_layover_hours: null,
  exclude_layover_airports: [],
  departure_time_range: null,
  arrival_time_range: null,
};

describe("shared result filters", () => {
  const row = mockSearchEnvelope.response?.rendered[0] as RenderedResult;

  it("builds stable options for both current and historical results", () => {
    const options = buildResultFilterOptions(mockSearchEnvelope.response?.rendered ?? []);

    expect(options.airlines).toContain(row.outbound.airlines[0]);
    expect(options.airport_routes).toContain(`${row.outbound.origin_airport}→${row.outbound.destination_airport} / ${row.inbound.origin_airport}→${row.inbound.destination_airport}`);
    expect(options.layover_airports).toContain(row.outbound.layovers[0].airport);
  });

  it("applies every table-header filter semantic", () => {
    const airline = row.outbound.airlines[0];
    const airportRoute = `${row.outbound.origin_airport}→${row.outbound.destination_airport} / ${row.inbound.origin_airport}→${row.inbound.destination_airport}`;
    const layoverAirport = row.outbound.layovers[0].airport;
    const departureClock = row.outbound.departure_time?.slice(11, 16) ?? "00:00";
    const arrivalClock = row.inbound.arrival_time?.slice(11, 16) ?? "00:00";

    expect(matchesResultFilters(row, { ...emptyFilters, max_total_price: row.total_price_cny - 1 })).toBe(false);
    expect(matchesResultFilters(row, { ...emptyFilters, include_airlines: [airline] })).toBe(true);
    expect(matchesResultFilters(row, { ...emptyFilters, exclude_airlines: [airline] })).toBe(false);
    expect(matchesResultFilters(row, { ...emptyFilters, airport_routes: [airportRoute] })).toBe(true);
    expect(matchesResultFilters(row, { ...emptyFilters, airport_routes: ["OTHER"] })).toBe(false);
    expect(matchesResultFilters(row, { ...emptyFilters, max_stops_per_leg: 0 })).toBe(false);
    expect(matchesResultFilters(row, { ...emptyFilters, max_single_layover_hours: 0 })).toBe(false);
    expect(matchesResultFilters(row, { ...emptyFilters, exclude_layover_airports: [layoverAirport] })).toBe(false);
    expect(matchesResultFilters(row, { ...emptyFilters, departure_time_range: { start: departureClock, end: departureClock } })).toBe(true);
    expect(matchesResultFilters(row, { ...emptyFilters, arrival_time_range: { start: arrivalClock, end: arrivalClock } })).toBe(true);
  });

  it("supports time ranges that cross midnight", () => {
    expect(timeMatches("2026-09-29T23:30:00", { start: "22:00", end: "06:00" })).toBe(true);
    expect(timeMatches("2026-09-29T12:00:00", { start: "22:00", end: "06:00" })).toBe(false);
  });
});

describe("history group selection after deletion", () => {
  const groups = ["a", "b", "c"].map((id) => ({ id })) as unknown as HistoryGroup[];

  it("selects the next group, then falls back to the previous group", () => {
    expect(nextHistoryGroupAfterDeletion(groups, "b").next?.id).toBe("c");
    expect(nextHistoryGroupAfterDeletion(groups, "c").next?.id).toBe("b");
  });

  it("returns an empty state after deleting the final group", () => {
    expect(nextHistoryGroupAfterDeletion(groups.slice(0, 1), "a")).toEqual({ remaining: [], next: null });
  });
});

describe("history batch timestamp", () => {
  it("separates the local date and time for compact batch cards", () => {
    expect(formatHistoryBatchTimestamp("2026-06-19T12:30:00+08:00")).toEqual({ date: "06-19", time: "12:30" });
  });
});
