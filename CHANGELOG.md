# Changelog

## 0.2.0b1 — prepared, not published

First operator beta candidate, distributed under the MIT license. Linux is the
initial test target; physical terminal and operator pilot checks remain open.

### Added

- Explicit offline mode, configuration editing, and credential-safe diagnostics.
- Named net templates; callsign correction; net editing and reopening.
- Session-local removal undo (up to 50 removals per net).
- Validated SQLite backup/restore with safety snapshots and schema checks.
- Searchable, paginated history and compact terminal layouts.
- CI, installable source/wheel checks, recovery tests, and repeatable benchmarks.

### Fixed

- Partial lookup responses erasing cached information and provider failures
  interrupting logging; concurrency, cancellation, and retry handling.
- Export filename collisions, partial writes, and invalid ADI field output.
- Partial check-in saves, timezone/configuration startup failures, and timestamp ties.
- Incomplete source packages, hidden old nets, and inaccessible narrow-screen fields.

### Updating

Close termnetlog. Install the beta into your existing virtual environment, run
`termnetlog backup` before starting the TUI, then `termnetlog doctor`. Existing data
and configuration paths are preserved. Opening an older database upgrades it to
schema 2; use the retained backup when rolling back to an older application.
Config/templates are excluded from database snapshots: keep a secure separate copy.

### Known limits

Undo expires at application exit. Actual logging-application import, physical
terminal testing, QRZ authentication, second-device recovery, and operator trials
remain release gates. See BETA_CHECKLIST.md and BETA_EVIDENCE.md. ADI conversion
can lose Unicode characters, with warnings; text rosters retain Unicode. Participants
must only import genuine contacts into a QSO log; roster membership alone is not a QSO.
