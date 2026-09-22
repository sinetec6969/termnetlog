# termnetlog release-readiness audit

Reviewed 2026-09-22 at commit `408c17f79a1deca40fe53312d396d203b60d5e36`.

Implementation follow-up: A1–A10 are now addressed in local changes
on `release/ci-packaging`. Their checks are in the regular tests and package
validation script; the expected-failure module has been retired. The findings and
results below describe the original reviewed commit. See [release progress](RELEASE_PLAN.md#implementation-progress)
for current implementation status.

**Verdict: a well-structured personal-use prototype, but not yet ready for a general release.** The core workflow works, and all 41 existing tests pass. Three high-priority defects affect cached data, exported files, and continuity of live logging. Fix those before recruiting wider users. No application source was changed during this audit.

## Scope and evidence

Reviewed all application modules, TUI screens/widgets, configuration, packaging, and the existing tests. Ran on Linux, Python 3.13.5, Textual 8.2.8, HTTPX 0.28.1, pytest 9.1.1. Exact installed versions are in `audit/environment.json`.

| Check | Result |
|---|---|
| Existing test suite | 41 passed, including headless TUI workflows |
| Targeted release expectations | 11 strict expected failures reproducing nine findings; three cases cover A3 |
| Wheel and source distribution build | Both succeed using the declared setuptools backend |
| Wheel installed to a separate directory | Imports from installed wheel; TUI opens a new net at 80×24 |
| Installed dependency consistency | `pip check` passes |
| Tests collected from extracted source distribution | Fails: missing `conftest.py`; fixture files also absent |
| Layout at 80×24 | Roster viewport 46 columns wide, content 83; horizontal overflow hidden |

The initial no-isolation build lacked setuptools in the new virtual environment; installing the declared backend resolved that environment issue. It is not an application defect.

Tests use temporary/in-memory databases and mocked providers. No real QRZ credentials or production operator records were used. Live provider availability/authentication, actual third-party ADIF imports, other Python versions, Windows/macOS, physical terminal rendering, and dependency vulnerability scanning were not verified. Passing tests are not a security certification.

## Findings

P1 means fix before wider beta use. P2 means resolve before the proposed stable release, or explicitly narrow the supported scope. P3 is a lower-impact correctness issue.

### A1 — P1: partial lookup refresh destroys existing cached details

**Location:** `src/termnetlog/repo.py:48`, `src/termnetlog/lookup/service.py:69`.

`apply_lookup()` replaces every lookup field, including fields absent from the new response. Cache a full record, then refresh when QRZ returns only a name and the fallback provider is offline: city, grid, and other previously known fields become NULL. The degraded record is also marked fresh for the normal cache duration. Because old rosters join the current operator record, their displays and subsequent exports also lose those details.

**Evidence:** `test_partial_refresh_preserves_known_location` reproduces the loss through `LookupService`, with one partial and one failing provider.

**Fix:** distinguish absent values from explicit corrections; preserve existing fields when a provider omits them. Track refresh attempts separately from successful enrichment and use a shorter retry policy for degraded results. Keep deliberate manual clears meaningful. Add field provenance/manual overrides as a later extension.

### A2 — P1: exporting one net can overwrite another net's files

**Location:** `src/termnetlog/tui/app.py:61`.

The filename uses only the starting minute and a sanitized name. Two nets with the same name started in the same minute produce identical paths; punctuation-only name differences can collide too. `write_text()` silently replaces the first export. This loses exported artifacts, not the database records.

**Evidence:** `test_different_nets_keep_distinct_exports` exports a one-check-in net followed by an empty net with identical timestamps/names and finds the same paths and overwritten roster.

**Fix:** include the immutable net ID in filenames; define whether re-exporting the same net updates or versions its files. Write to temporary files and replace only after successful serialization. Catch write failures and report a useful error without exiting the logger; avoid announcing success for only one of two outputs.

### A3 — P1: malformed provider data can terminate the live TUI

**Location:** `src/termnetlog/lookup/hamdb.py:13`, `src/termnetlog/lookup/service.py:57`, `src/termnetlog/tui/screens/net.py:236`; the operators screen also starts lookup workers.

HamDB parsing guards only the outer key access. Valid JSON such as `{"hamdb": null}`, a string in `messages`, or a numeric name raises `AttributeError`. These exceptions bypass `LookupFailed`, which is the only provider error caught by the service. Lookup workers use Textual's default fatal error behavior.

**Evidence:** three mocked HTTP-response tests reproduce exceptions escaping `resolve()`. The application-exit consequence follows the worker call sites and [Textual's documented default behavior](https://textual.textualize.io/guide/workers/#worker-errors); it was not separately exercised as a full TUI crash test. Already committed check-ins survive, but live operation is interrupted.

**Fix:** validate nested shapes/types and convert malformed responses into bounded, sanitized `LookupFailed` errors. Distinguish service errors from genuine not-found records. Contain unexpected worker errors with explicit reporting so logging remains usable, without silently hiding programmer errors. Test cancellation during navigation and shutdown too.

### A4 — P2: the TUI cannot start without system timezone data

**Location:** `src/termnetlog/tui/format.py:9`, `pyproject.toml:10`.

Importing the TUI eagerly constructs `ZoneInfo("America/New_York")`, even when UTC display is selected. The package does not declare `tzdata`. Systems without an IANA database therefore fail before the app starts. An invalid configured timezone also raises an uncaught exception.

**Evidence:** `test_tui_import_without_system_timezone_database` runs a fresh process with `PYTHONTZPATH=''` and reproduces `ZoneInfoNotFoundError`. This simulates missing system data; it is not a Windows test. [Python's zoneinfo documentation](https://docs.python.org/3/library/zoneinfo.html#data-sources) specifically describes the dependency requirement for cross-platform use.

**Fix:** bundle an appropriate tzdata dependency, avoid an unnecessary import-time zone lookup, validate zone names, and provide an actionable configuration error or explicit UTC fallback.

### A5 — P2: Unicode text is emitted in incompatible ADI fields

**Location:** `src/termnetlog/export.py:26` and `:55`.

Names and notes flow directly into `.adi` fields. A name such as José produces `<NAME:4>José`. ADIF 3.1.4 defines ordinary String fields using ASCII characters and reserves international string fields for ADX. The existing test covers only ASCII field lengths, so it misses this incompatibility. Frequency, band, mode, and locator values are also emitted without domain validation.

**Evidence:** `test_adi_name_is_ascii_compatible` reproduces the non-ASCII output. The interoperability concern is grounded in the [ADIF 3.1.4 data types specification](https://www.adif.org/314/ADIF_314.htm#Data_Types), not a claim that every importer rejects it.

**Fix:** make the ADI text policy explicit, normalize/transliterate with disclosure where appropriate, or offer ADX for lossless international text. Validate structured fields and test with an independent reader plus an actual intended destination. Merely switching character counts to UTF-8 byte counts does not solve the format issue.

### A6 — P2: older binaries accept databases with newer schemas

**Location:** `src/termnetlog/db.py:65`.

`MIGRATIONS[version:]` silently does nothing when `user_version` is beyond the migrations this binary understands. The connection is returned writable. Future upgrades followed by a downgrade could cause incompatible reads/writes instead of a clear refusal.

**Evidence:** `test_future_database_schema_is_rejected` sets version 999 and observes successful migration return. No actual corruption is claimed: this is a missing compatibility guard demonstrated with a synthetic future version.

**Fix:** reject unsupported schema versions before normal operation; define migration backup/recovery policy and close failed connections. Test upgrade, interrupted migration, and downgrade refusal against real old-schema fixtures.

### A7 — P2: the history screen silently hides older nets after 200

**Location:** `src/termnetlog/repo.py:177`, `src/termnetlog/tui/screens/history.py:49`.

The repository defaults to 200 nets and the history screen has no pagination, search, or truncation indicator. After roughly seven months of nightly use, older nets cannot be selected or exported through that screen. They remain in SQLite and can be reached through CLI IDs; this is a discoverability/access defect, not deletion. Operator search likewise caps results at 200, though its search box helps narrow them.

**Evidence:** `test_past_nets_are_accessible_beyond_200` creates 201 ended nets; the screen displays only 200.

**Fix:** add paginated history with date/name filters and visible totals. Preserve selection while loading pages. Avoid solving this only by removing limits and making all queries/UI updates unbounded.

### A8 — P3: tied timestamps incorrectly mark repeat operators as new

**Location:** `src/termnetlog/models.py:10`, `src/termnetlog/repo.py:251`.

Timestamps are rounded to seconds. History counting includes strictly earlier timestamps or the current ID, but excludes another check-in at the same second. The same operator logged into two nets that second appears as a first-time operator in both; previous-seen is also absent. This is uncommon in manual use but matters for overlapping nets and future bulk imports.

**Evidence:** `test_history_uses_id_to_break_timestamp_ties` produces `nth == 1` for the second record.

**Fix:** use a deterministic `(time_utc, id)` ordering consistently for counts, previous-seen, and history ordering.

### A9 — P2: the published source archive cannot run its own tests

**Location:** `pyproject.toml` packaging configuration; built `termnetlog-0.1.0.tar.gz`.

Setuptools includes `tests/test_*.py`, but omits `tests/conftest.py` and all XML/JSON fixtures. Collecting tests from the extracted archive fails twice with `ModuleNotFoundError: conftest`; more fixture failures would follow. Runtime wheel contents, including the stylesheet, are present.

**Fix:** explicitly include the complete test support tree in the sdist manifest and run the extracted archive's tests in CI, outside the checkout. Check wheel startup separately.

### A10 — P2: small terminals clip essential roster columns

**Location:** `src/termnetlog/tui/app.tcss:21`, `:33`, `src/termnetlog/tui/widgets/checkin_table.py:70`.

The operator card reserves at least 34 columns while the roster uses fixed-width columns and disables horizontal overflow. At 80×24, the roster is 83 columns wide in a 46-column viewport; flags and history columns lie off-screen with no horizontal scrollbar. Existing tests use 140×40 and do not detect this.

**Evidence:** measured during the installed-wheel smoke test; retained in `test_small_terminal_can_access_full_roster`. This is a layout measurement, not a claim that every keyboard navigation route was tested.

**Fix:** use a collapsible card and a compact roster at narrow widths, allow horizontal access where needed, and keep dialogs scrollable. Define and test a minimum supported terminal size.

## What is already good

- The module boundaries are sensible: small domain models, a centralized SQL repository, provider adapters, and separate UI screens. Keep this architecture.
- SQL values are parameterized and dynamic update-column names are allowlisted in the reviewed paths.
- Foreign keys, cascade cleanup, and a per-net callsign uniqueness constraint enforce useful invariants.
- Lookup failure normally does not prevent saving a check-in; offline failures remain eligible for retry.
- Manual operator edits and persistent notes are deliberately protected from remote lookup replacement.
- UTC storage is kept separate from display timezone conversion.
- QRZ network errors avoid echoing credential-bearing request URLs; newly created configuration files request POSIX mode 0600.
- The existing tests cover meaningful workflows, including actual headless keyboard interactions, provider fallback, duplicate prevention, and exports.

## Additional release risks and design decisions

These are code-review observations or missing capabilities, not additional claims of reproduced data loss.

- **Atomic entry save:** the initial check-in, each flag, and the note are separate commits (`net.py:213–223`). A process/I/O failure between commits leaves an incomplete entry. Add one transactional repository operation for a parsed entry; nested helpers must not commit early.
- **Operational errors:** disk-full, permission, invalid TOML, invalid configuration types, and database-lock errors mostly propagate. Surface actionable errors, preserve unsaved input, and avoid credential/config dumps.
- **Lookup load:** resuming a net creates a worker per unlooked-up operator; QRZ session initialization has no lock. Add bounded concurrency, per-callsign coalescing, login synchronization, and retry/backoff. Do not make all calls exclusive and cancel unrelated operators.
- **Time display:** history column headings use today's abbreviation while row times use each record's historical offset; winter records can appear under an EDT heading. Prefer an unambiguous zone label or per-row suffix and add DST tests.
- **Record correction:** there is no normal UI path to correct an entered callsign or edit net metadata, and closing a net does not prevent new check-ins. Define explicit correction/reopen behavior before treating ended nets as final.
- **Manual overrides:** editing any one operator field disables all future enrichment. Per-field overrides and an explicit reset-to-provider action would improve this safely.
- **Historical identity:** prior exports use the current mutable operator profile. Decide whether names/location should describe the person now or at the time of check-in before adding location-sensitive reporting.
- **Input domain:** callsign parsing accepts arbitrary slash components, and metadata/relay edits have minimal validation. Define supported callsign forms and validate identity separately from syntax without requiring an online lookup.
- **Release operations:** no license file, CI workflow, changelog, user recovery guide, or backup/restore command is present. Dependency lower bounds span a large range without compatibility evidence. Select a license with the owner; do not invent one.

## Reproduce and use the audit

From the repository root:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m build --no-isolation --outdir /tmp/termnetlog-audit-dist
.venv/bin/pip check
```

The initial audit used strict expected-failure tests to reproduce the findings.
Those regressions have now moved into the regular suite as fixes landed; history
coverage checks pagination and search rather than requiring unbounded row loading.
A9 is checked by `scripts/check_distribution.py`. The original measurements above
remain historical and should not be read as current test results.

See [RELEASE_PLAN.md](RELEASE_PLAN.md) for the proposed delivery order and acceptance criteria.
