# AdvSearchFlights Architecture

AdvSearchFlights is a Python backend package with a CLI entry point and a macOS desktop GUI shell.

```text
src/adv_search_flights/
  cli.py        command-line entry point
  control/      retry, timeout, cooldown, and pacing
  data/         city, airport, airline, and aircraft reference data
  domain/       Pydantic request and result models
  output/       table, text, and JSON renderers
  providers/    fli, Skyscanner, mock, and auto fallback providers
  search/       orchestration, filtering, sorting, combination, validation
  network/      proxy summary, provider error classification, and network diagnostics
desktop/
  src/          React/TypeScript GUI
  src-tauri/    Tauri macOS shell and local gui-search command bridge
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

## GUI flow

The desktop GUI calls the Python backend through a local subprocess instead of a server:

1. React maps the search form into the stable `gui-search` JSON payload.
2. Tauri invokes the `gui_search` command.
3. The command starts `adv-search-flights gui-search`, writes JSON to stdin, and parses stdout.
4. The Python CLI returns an envelope with `response`, `network_status`, `provider_status`, and `error`.
5. The GUI renders user-friendly network status, errors, results, and raw JSON details.

When the React app runs in a normal browser instead of Tauri, it uses mock data so UI work can continue without a Python subprocess.

## Network diagnostics

`adv_search_flights.network` is intentionally independent from providers and GUI code. It owns:

- proxy environment summaries with credential redaction
- `fli` CLI availability checks
- Google Flights reachability checks
- classification of timeout, connection failure, rate limit, missing dependency, and no-result states

This boundary keeps future network and monitoring work isolated from search orchestration.
