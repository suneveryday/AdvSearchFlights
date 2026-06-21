# Public Release Audit

This repository is a source-only public snapshot of Farello v0.10.0.

## Excluded data

- Local SQLite search history and application settings
- Diagnostic logs and JSONL/HTTP archive files
- Real `.env` and `.env.local` files
- API keys, access tokens, cookies, and personal credentials
- Local build outputs, macOS app bundles, and disk images
- Python bytecode, dependency directories, and tool caches
- Previous private development commits and commit metadata
- Personal itinerary, date, and proxy defaults

## Included fixtures

Tests and browser previews contain synthetic mock flight records. They are code fixtures only and are never loaded from a user's local history database.

## Analytics configuration

The tracked `desktop/.env.example` contains a placeholder PostHog Project Token. A real frontend Project Token must be supplied through an ignored local environment file or the build environment. Personal API keys must never be embedded in the application.

PostHog analytics is opt-in. Autocapture, page views, session replay, user profiles, and automatic exception capture are disabled. The event sanitizer only preserves required PostHog transport metadata and explicitly allowlisted anonymous product properties.

## Maintainer checklist

Before publishing a release:

1. Run the secret and personal-path scans described in `SECURITY.md`.
2. Confirm `git status --ignored` does not reveal tracked local data.
3. Run Python, frontend, and Rust tests.
4. Build with credentials supplied only through the build environment.
5. Verify PostHog's `Discard client IP data` setting remains enabled.
