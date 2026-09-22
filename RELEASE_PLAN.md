# termnetlog: path to a supported release

This plan follows the [2026-09-22 audit](AUDIT.md) of commit `408c17f`. Milestones below are proposed releases, not promises or existing project commitments.

**Product direction:** make termnetlog a dependable, offline-capable logger for a single operator running recurring amateur-radio nets. Its strongest existing feature is fast keyboard entry combined with persistent operator context. Preserve that focus while making correction, recovery, and repeated nightly use reliable.

Assumptions: one local writer, SQLite as the system of record, optional QRZ/HamDB enrichment, no account required, text rosters as the primary sharing format. Start with Linux as the verified platform; add macOS/Windows only when installation and terminal checks pass there. Actual use on emergency/public-service nets would require a separate operational validation effort.

## Implementation progress

The first change is prepared locally on `release/ci-packaging`:

- A9 fixed: the source manifest includes the complete test support tree.
- Added CI for Linux/Python 3.11–3.14 and a minimum-runtime-dependency job.
- Added executable package regression checks: fixture completeness, independent
  wheel/source installs, CLI entry point, stylesheet, TUI startup, and the
  extracted archive's full test suite.
- Verified locally on Python 3.13.5: 41 tests pass against both installed
  artifacts, and 41 pass with the declared minimum runtime dependencies.
- GitHub-hosted matrix results are pending.

The second change implements lookup reliability:

- A1: absent provider fields no longer erase cached details; partial/error attempts
  are persisted separately and retry after a five-minute cooldown (force bypasses it).
- A3: malformed responses and unexpected provider errors become recoverable
  outcomes; nonfatal TUI workers report remaining errors without request contents.
- Four concurrent lookups maximum, shared per-callsign requests, cancellation when
  the last caller leaves, shutdown cleanup, and synchronized QRZ session login.
- Schema 2 adds lookup-attempt metadata. A6's newer-schema guard is included because
  this change introduces a migration; v1 upgrade preservation is tested.
- A1/A3/A6 reproductions have moved into the passing regular test suite.
- Local validation: 70 regular tests pass with both the current and minimum
  runtime dependencies; six remaining audit cases are still expected failures.

The third change implements export safety:

- A2: TUI exports publish a new snapshot directory containing both formats in one
  rename; names contain the net ID and earlier snapshots are never updated.
- Explicit CLI output uses a staged file and atomic replacement. Validation/write
  errors preserve previous exports, return failure, and do not terminate the TUI.
- A5: ADI free text converts to printable ASCII with visible warnings; original
  records and UTF-8 rosters remain unchanged. Structured fields are validated,
  common submodes are mapped, and long locators use GRIDSQUARE_EXT.
- Added independent `adif-io` parsing checks, failed-write/publication tests,
  clipboard failure handling, and recovery checks on both export screens.
- A2/A5 regressions now run in the regular suite. Actual target logging-application
  imports remain a release-candidate gate; parser checks do not replace them.
- Local validation: 117 regular tests pass with current and minimum runtime
  dependencies; the four remaining audit expectations still fail as expected.

The fourth change implements entry and startup reliability:

- Parsed entries now save operator/check-in/flags/relay/note together. Failed
  insertion or commit rolls back the entry and preserves TUI input for retry;
  nested calls preserve the caller's transaction boundary.
- A4: packaged timezone data, no eager timezone lookup, explicit UTC support,
  validated configuration types/ranges/zones, and credential-safe error messages.
- Startup reports configuration, database, and filesystem failures clearly;
  connections close on failed initialization and CLI completion. Failed migration
  tests verify that schema versions and existing data remain unchanged.
- A8: timestamp ties use check-in IDs consistently. Local-time headings no longer
  suggest today's daylight-saving abbreviation applies to historical records.
- Local validation: 154 tests pass with current and minimum runtime dependencies,
  and against both installed wheel and source artifacts; package startup and
  dependency checks pass.
  A4/A8 regressions are now regular tests; only A7/A10 remain expected failures.

The fifth change adds backup and restore:

- CLI snapshots use SQLite's backup API, validate integrity/schema/references,
  and include application/schema/time metadata without configuration credentials.
- Restore validates and upgrades a private copy before touching the destination.
  Existing databases require `--replace`, an exclusive lock, and a successful
  safety snapshot before transactional replacement, including WAL databases.
- Recovery works independently of configuration. The README documents a recovery
  drill, separate-storage guidance, and a pre-upgrade backup policy.
- Tests cover complete record recovery, WAL snapshots/restores, old schema upgrades,
  bad candidates, active writers, failed safety snapshots/publication, and rollback
  after an interrupted page copy.
- Local validation: all 170 tests pass against installed wheel and source
  artifacts and with minimum runtime dependencies, including 16 recovery tests.

The sixth change resolves history and terminal access:

- A7: bounded 50-net pages, visible totals, literal name/UTC-date search, stable
  ordering, selection preservation on reload, and last-page deletion recovery.
- A10: compact roster below 120 columns, F2 access to the full operator card,
  horizontal table scrolling, and width-constrained, vertically scrollable dialogs.
- Tests reach the oldest of 205 nets, search/open it, verify empty results, and
  exercise 80×24/100×30/140×40 plus resize with unfinished input and selection.
- All original audit findings now have passing regression coverage; the separate
  expected-failure module has been retired.
- Validation: 177 tests pass against both installed package formats. The minimum
  dependency suite passed before the final dialog test was added; all seven new
  history/layout tests, including that dialog test, also pass on minimum dependencies.

The seventh change adds onboarding and diagnostics:

- `config --init`, repeatable `--set`, and hidden `--qrz` prompts support station,
  timezone, net defaults, offline/provider selection, and optional credentials.
  TOML edits preserve comments and unrelated fields using tomlkit; validation
  precedes private, atomic writes.
- Explicit offline mode overrides all provider settings and environment credentials,
  with a visible start-menu status. The README includes an offline-first quick start.
- `doctor` reports paths, versions, configuration/provider state, and database
  validation without exposing credentials, migrating data, or creating log/config
  files. `--test-lookup CALL` explicitly tests providers without updating logs.
- Tests cover preserved settings, rejected/failed saves, credential redaction,
  noninteractive credential refusal, offline guarantees, no implicit network,
  old/corrupt/future databases, and provider cleanup.
- Validation: 203 tests pass against both installed package formats. The full
  202-test suite passed with current/minimum dependencies before the final offline
  TUI test; all 26 setup/diagnostics tests, including that test, pass in both environments.

The eighth change adds corrections and recurring-net templates:

- F3 previews and confirms a callsign correction for one check-in. Transactional
  updates preserve entry fields, reject conflicts, and leave operator profiles,
  private notes, and unrelated attendance untouched.
- Ctrl+D edits net metadata; Ctrl+O explicitly reopens ended nets. Ended nets
  still allow corrections but preserve/refuse new input until reopened.
- `config --template NAME --set net.FIELD VALUE` creates/edits named presets.
  New presets inherit existing defaults; start-menu choices open a prefilled form
  and create fresh sessions with notes but no copied check-ins.
- Templates use existing TOML configuration rather than a new database table:
  they contain operator preferences, require no schema migration, and are excluded
  from database-only backups. This storage choice is documented in the README.
- Validation: 216 tests pass against both installed package formats. The full
  minimum-dependency suite passed before the final empty-template-name regression;
  all 13 correction/template tests, including that regression, pass in both environments.

The ninth change adds removal undo and an automated recovery drill:

- Ctrl+Z restores the last removed check-in for the current net, preserving its
  fields and roster position without overwriting later records. Undo survives
  screen navigation within the process, retains up to 50 removals per net, and
  clears on application exit or net deletion.
- Removal and restoration are transactional, respect outer transactions, reject
  duplicate callsigns, handle reused row IDs, and retain failed undo for retry.
- An offline integration drill creates configuration and a template, logs a net,
  ends/exports it, backs it up, restores into a fresh database, and checks entry
  fields, operator notes, net notes, and diagnostics.
- [BETA_CHECKLIST.md](BETA_CHECKLIST.md) separates automated evidence from the
  remaining human/platform/interoperability release checks.
- Validation: all 225 tests pass with current and minimum runtime dependencies
  and against both installed package formats; package startup and dependency
  checks also pass. Release documentation is included in the source archive.

Beta checklist follow-up: the maintainer selected MIT and GitHub Releases. Candidate
0.2.0b1 metadata, draft-release workflow, release/support docs, installation/recovery
evidence, dependency scan, live HamDB check, and large-history measurements are
prepared on main. Entry redraw work reduced measured p95 from 149.50 ms to 63.04 ms.
See [BETA_EVIDENCE.md](BETA_EVIDENCE.md) and the updated checklist for limitations
and open physical-terminal, QRZ, logging-application, and second-device checks.

Next: review beta preparation, verify its hosted CI, and finish the remaining checklist.
The core reliability changes are implemented; no release has been published.
The work is prepared on `release/ci-packaging` for review; no release has been published.

## Delivery order

| Milestone | User outcome | Scope | Rough engineering effort |
|---|---|---|---|
| 0.1.1 reliability | Logging and exporting preserve data despite external failures | Audit fixes, transactional entry save, CI and package checks | 1–2 engineer-weeks |
| 0.2 operator beta | A new user can configure, correct, recover, and repeat a nightly net | Onboarding, backups, templates, corrections, usable history/layout | 2–3 engineer-weeks |
| 0.3 workflow beta | Net control can track traffic and returning operators efficiently | Traffic lifecycle, roster filters, reports, import preview | 2–3 engineer-weeks |
| 1.0 release candidate | Installation, upgrades, exports, and recovery are documented and validated | Compatibility matrix, interoperability checks, pilot fixes, release process | 1–2 engineer-weeks plus field trial |

These are planning estimates for one developer familiar with Python/Textual, excluding new platform surprises and review delays. Re-estimate after 0.1.1. A reliable 0.2 is a useful first public beta; do not delay it for every 0.3 feature.

## Milestone 0.1.1 — protect the current workflow

Complete before adding feature breadth.

| Work item | Implementation direction | Acceptance criteria |
|---|---|---|
| Preserve cached data (A1) | Merge only supplied provider fields; separate attempts from successful refresh | Partial response plus failed fallback keeps known city/grid; manual clears remain protected; retry is possible without waiting the full normal TTL |
| Safe exports (A2) | Add net ID to filenames; stage file writes; handle filesystem errors | Same-minute nets never collide; failed exports preserve existing files and keep the TUI usable; success identifies exactly what was written |
| Isolate lookup failures (A3) | Validate response types, classify errors, contain worker failures | Malformed JSON/XML, HTTP errors, timeouts, and cancellation never lose check-ins or terminate ordinary logging; errors omit secrets |
| Atomic entry persistence | Add `Repo.record_entry(...)` accepting the parsed entry; commit operator/check-in/flags/note coherently | Inject a failure after row creation and verify no partial entry; duplicate handling leaves the previous entry untouched |
| Upgrade safety (A6) | Refuse unknown schema versions and define transaction/backup boundaries | Old-schema migration succeeds; newer schema is refused with useful instructions; failed migration does not advance its version |
| Runtime and config validation (A4) | Supply timezone data where needed, validate TOML types and zones | Startup works without host tzdata; invalid config yields an actionable message; UTC remains usable |
| Export correctness (A5) | Define ADI character policy and validate field values before export | Accented names, multiline text, invalid frequency/band/mode, and midnight UTC dates have deterministic tested outcomes |
| Remaining correctness | Fix timestamp ties (A8); use accurate timezone headings | Repeated same-second check-ins are ordered correctly; winter/summer history is labeled accurately |
| Continuous checks and packaging (A9) | CI runs tests, installs wheel, and tests extracted sdist; include fixture tree | Tests pass from checkout and archive; installed wheel has CSS and starts; minimum dependency claims are supported or revised |

The current nine-finding regression set becomes normal passing tests as work lands. Add targeted tests for I/O failure and transactional rollback; avoid merely raising coverage numbers with duplicated implementation assertions.

Suggested initial PRs, in dependency order:

1. CI, package manifest, and regression-test integration.
2. Lookup merge/error boundaries and bounded lookup scheduling.
3. Export identity, atomic file handling, and ADI validation.
4. Transactional entry saves, migration guard, and configuration/timezone handling.

Keep each PR reviewable and runnable; add the relevant regression with its fix rather than landing a permanently failing main branch.

## Milestone 0.2 — make everyday use complete

**Onboarding and diagnostics.** Add `termnetlog config` or a TUI settings screen for station callsign, timezone, net defaults, provider choice, and optional QRZ credentials. Offer a clearly labeled offline mode and an explicit provider test. Add `termnetlog doctor` to show application version, data/config paths, schema version, and provider configuration status with credentials redacted. Keep headless CLI commands available.

**Backup and restore.** Add `backup` and `restore` commands using SQLite's backup API rather than copying only a live WAL database file. Include schema/app version metadata; exclude credentials by default. Restore validates the candidate, creates a backup of the current database, and requires an explicit replacement action. Document a full recovery exercise. Gate beta on restoring operators, notes, nets, flags, and ordering into a fresh data directory.

**Net templates.** Introduce named presets for weekly nets: frequency, band, mode, NCS defaults, role, and optional opening/closing notes. Start a fresh session from a template without copying previous check-ins. Keep existing config defaults as the migration/default template. A user with two recurring nets should start either in a few keystrokes.

**Corrections and undo.** Support correcting a check-in callsign while preserving its time, sequence, flags, relay, and note; preview conflicts when the corrected operator is already checked in. Separate operator-profile identity from one mistaken check-in. Allow net metadata editing and explicit reopen; distinguish post-net corrections from new check-ins. Add undo for check-in removal before tackling complex multi-record history. Acceptance tests must prove that a callsign correction does not move the old operator's unrelated history or private notes.

**Usable history and terminal layout (A7/A10).** Add date/name search, pagination, total counts, and explicit empty states. Use a compact roster with a toggleable operator card at 80×24, and scrollable forms. Verify 80×24, 100×30, 140×40, resize during entry, long names, and narrow dialogs. Older nets must remain accessible after at least a year of nightly sessions.

**Observable lookup state.** Show cached, fetching, not found, stale, and offline states distinctly. Cap concurrent requests, deduplicate repeated requests for the same operator, synchronize QRZ login, and bound retries. Preserve immediate entry response while lookups are delayed. Permit retrying incomplete lookups without changing notes.

Exit gate: a new user can install, configure offline, start/resume/end a net, correct a typo, export, back up, restore, and find an old net using the documentation alone.

## Milestone 0.3 — improve net-control work

Prioritize these based on pilot feedback rather than implementing every idea at once.

| Feature | Why it matters | Definition of done |
|---|---|---|
| Traffic queue | A boolean says traffic exists but not whether it has been handled | Track pending/in-progress/handled traffic, optional destination/message count, and completion time; keyboard filtering and export summaries agree |
| Roll-call roster | Recurring nets need a quick view of expected versus checked-in stations | Template-specific expected roster and last-seen context; inviting a station does not create a check-in |
| Roster filters and counts | Net control needs traffic, short-time, relay, and ragchew groups quickly | Keyboard toggles preserve selection; filtered counts are labeled; no hidden filter changes saved data |
| Attendance reports | Net managers need useful totals over time | Date/template filters, unique operators versus total check-ins clearly distinguished, CSV/text output with documented columns |
| Operator enrichment controls | One hand-edited nickname should not freeze every lookup field | Per-field manual overrides, source/timestamp display, and explicit reset action; old manual records migrate without losing protection |
| CSV import with preview | Existing logs make the operator history useful immediately | Preview validation and duplicates before writes; explicit timezone for timestamps; transactional import; safe rerun/idempotency; row-level errors |

Start import with a documented CSV schema and a sample file. Defer broad ADIF import until the application's distinction between net participation and a two-way QSO is explicit. Exporting a participant's entire net roster as QSOs should require intentional selection/confirmation of actual contacts, rather than implying every heard station was worked.

Traffic state should live on check-ins (or a related traffic table), template defaults in a templates table, and operator overrides in a migration designed for per-field provenance. Retain the existing repository/service/UI boundaries. Add an application-service layer only for operations shared by CLI and TUI that need coherent transactions; no wholesale rewrite is warranted.

## Release candidate and 1.0 gates

1. **Data safety:** zero unresolved P1 findings; migration, downgrade refusal, rollback, backup, and restore tests pass. Perform a recovery drill with a realistic anonymized history. Any remaining P2 must have an explicit scope restriction or documented decision.
2. **Compatibility:** test Python 3.11 and each newer minor version claimed in release support; check minimum and release-resolved dependency sets. Test intended OS/terminal combinations before advertising them. Keep a repeatable release environment while allowing compatible application dependencies.
3. **Package quality:** build both artifacts in CI, test the extracted source archive, install the wheel outside the checkout, verify stylesheet/entry point/version, and run dependency metadata/security checks. Ensure audit-only expected failures are not used as the release gate.
4. **Export interoperability:** independently parse exported ADI and import a sample into at least one target logging application chosen by pilot users. Cover Unicode policy, mobile/portable calls, UTC dates, station identity, empty nets, and participant-mode contact selection.
5. **Responsiveness:** use a synthetic history of 100,000 check-ins with a 200-station active net. Initial target: entry-to-visible-row under 100 ms p95 and useful history/filter results under 300 ms on documented reference hardware. These are proposed budgets, not measured claims. Profile joins and full-table redraws before adding caches.
6. **Field trial:** ask 3–5 operators to use the beta across at least 10 real nets, including offline operation, restart/resume, correcting mistakes, and end-of-net reporting. Obtain permission before collecting any logs or diagnostics. Resolve issues that interrupt operation or threaten records before tagging 1.0.
7. **Documentation and support:** quick start, keyboard reference, minimum terminal size, data paths, QRZ setup, offline behavior, privacy/export contents, backup/restore, upgrade/rollback, and troubleshooting. Add a changelog, issue templates, contribution instructions, and an owner-selected license.
8. **Release process:** a reviewed version tag builds tested artifacts with release notes and known limitations. Configure publishing credentials/permissions only when the maintainer chooses the distribution channel. This plan does not authorize publication.

## Keep out of the first stable release

Cloud accounts/sync, simultaneous multi-user editing, mobile/web clients, plugin frameworks, radio/CAT integration, automatic public roster posting, and contest logging would each add a substantial support surface. Revisit after stable local logging and pilot demand. SQLite remains a suitable foundation for the proposed single-writer workflow.

Decisions needed before the release candidate: owner-selected license; supported operating systems and terminal sizes; target ADIF destination; how completed-net corrections are represented; and whether first public distribution is GitHub artifacts or a package index. None prevents starting the reliability work now.
