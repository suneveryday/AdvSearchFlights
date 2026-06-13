# Contributing

Thanks for helping improve this project.

## Local setup

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

## Development notes

- Keep provider-specific parsing inside `src/adv_search_flights/providers/`.
- Keep filtering and sorting rules inside `src/adv_search_flights/search/`.
- Do not commit `.env`, API keys, tokens, or real user data.
- Add focused tests for provider parsing and search combination logic.

## Before opening a pull request

```powershell
python -m pytest
adv-search-flights search --origin SHA --dest MEL SYD --departure 2026-09-29 --return-date 2026-10-07 --provider mock --format table --limit 2 --no-cooldown
```
