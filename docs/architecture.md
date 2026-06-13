# AdvSearchFlights Architecture

AdvSearchFlights is a pure Python backend package with a CLI entry point.

```text
src/adv_search_flights/
  cli.py        command-line entry point
  control/      retry, timeout, cooldown, and pacing
  data/         city, airport, airline, and aircraft reference data
  domain/       Pydantic request and result models
  output/       table, text, and JSON renderers
  providers/    fli, Skyscanner, mock, and auto fallback providers
  search/       orchestration, filtering, sorting, combination, validation
```

## Search flow

1. Resolve the origin city into all known airports.
2. Resolve one to five candidate destination cities into all known airports.
3. Query one-way outbound flights for every origin/destination airport pair.
4. Query one-way return flights for every destination/origin airport pair.
5. Filter each one-way option by price availability, stop count, and layover duration.
6. Choose one to two candidate destinations: the same destination creates a round trip; two different destinations create an open-jaw route.
7. Sort by total CNY price and render as table, text, or JSON.

## Provider strategy

`auto` tries Google Flights through `fli` first. If it fails or returns no usable priced results, it tries the optional experimental Skyscanner provider when the third-party library is installed.

`mock` is kept for deterministic tests and local development.
