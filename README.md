# termnetlog

A keyboard-driven terminal logger for amateur radio nets (built for a nightly 2m FM net).
Type a callsign, it's logged and looked up in the background (QRZ.com, falling back to HamDB),
and every operator you've logged before shows their history and your notes about them.

## Project recap — September 22, 2026

We audited the original prototype, reproduced its release-blocking defects, and
built a staged plan for a supported operator beta. The work preserved the existing
Python/Textual/SQLite architecture while improving reliability and daily use.

- **Audit and release planning:** documented ten findings, addressed all original
  audit regressions, and added a [release plan](RELEASE_PLAN.md) and
  [beta checklist](BETA_CHECKLIST.md). The [audit](AUDIT.md) retains the original
  findings and evidence for reference.
- **Reliable logging and lookups:** entries save atomically; failed saves retain
  input for retry. Partial provider responses preserve cached details. Lookups
  have bounded concurrency, shared requests, retry cooldowns, cancellation cleanup,
  and recoverable failures. Manual operator edits remain protected.
- **Safer exports:** each TUI export creates a distinct text/ADI snapshot; failed
  writes preserve previous exports. ADIF fields are validated, Unicode conversion
  is disclosed, and independent parser tests check the output.
- **Configuration and diagnostics:** added safe configuration editing, hidden QRZ
  credential prompts, explicit offline mode, and local `doctor` checks with optional
  provider tests. Packaged timezone data, configuration validation, historical DST
  handling, and schema guards improve startup and upgrade behavior.
- **Backup and recovery:** added validated SQLite snapshots, including committed
  WAL data, and restore with an explicit replacement flag and a safety backup.
  An automated offline drill covers setup, logging, export, backup, and recovery.
- **Everyday workflows:** added searchable, paginated history; compact terminal
  layouts and scrollable dialogs; callsign correction; net-detail editing and
  explicit reopening; named templates; and session-local undo for removed check-ins.
- **Packaging and verification:** expanded the suite from 41 to **225 passing
  tests**. Local checks pass with current and minimum runtime dependencies and
  against installed wheel/source packages. Added a Linux/Python 3.11–3.14 CI
  workflow and included test support files and release documents in source archives.

**Status at this checkpoint:** the release work is on `release/ci-packaging`;
no release has been published. Hosted CI and maintainer review are still pending.
Before beta distribution, complete the checklist's physical-terminal, live-provider,
logging-application import, recovery, and performance checks, and select a license
and distribution channel. Passing automated tests does not replace operator trials.

## Setup

The **0.2.0b1 operator beta candidate** is being prepared under the [MIT license](LICENSE)
for GitHub Releases; it has not been published. See [beta evidence](BETA_EVIDENCE.md)
for completed checks and [remaining gates](BETA_CHECKLIST.md) before pilot use.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/termnetlog config --set my_callsign W1AW --set lookup.offline true
.venv/bin/termnetlog doctor
.venv/bin/termnetlog
```

First run creates `~/.config/termnetlog/config.toml` (mode 0600). Set `my_callsign`, your net
defaults, and optionally your QRZ login. Without a paid QRZ XML subscription QRZ returns partial
records; HamDB (free, US FCC data) fills in name/location.

Replace `W1AW` above with your station callsign. That quick start explicitly
selects offline logging; known operator details and manual editing still work.
To enable lookups, set `lookup.offline` to `false`. HamDB is enabled by default.

```sh
termnetlog config --init                       # create defaults; preserve existing file
termnetlog config                              # show path and supported settings
termnetlog config --set display.local_tz Europe/London --set display.local_time true
termnetlog config --set net.name "Weekly Net" --set net.ncs_callsign W1AW
termnetlog config --set lookup.offline false --set lookup.hamdb true
termnetlog config --qrz                        # optional hidden credential prompts
termnetlog doctor                              # local checks only
termnetlog doctor --test-lookup W1AW            # explicitly contact configured providers
```

The config command validates all changes before an atomic save, preserves comments
and unrelated fields, and creates a private file on POSIX systems. Credentials
cannot be supplied through `--set`; use hidden `--qrz` prompts or `QRZ_USER` and
`QRZ_PASS`. Environment overrides remain active after file edits. Configuration
changes take effect on the next application start. `lookup.offline = true`
disables every network lookup, including providers configured through environment
variables; the start menu displays `offline`.

Doctor reports application version, config/database/export/backup paths, schema,
integrity, timezone validity, and provider configuration status without printing
credentials or operator records. It does not create configuration or log databases,
run migrations, or contact providers by default. Missing files are normal before
first use; invalid configuration/database or incomplete enabled QRZ credentials
return a nonzero status. Explicit provider tests contact each configured provider,
use a temporary in-memory database, and leave logged operators unchanged. A
successful response does not guarantee a paid QRZ subscription or complete data.

Data lives in `~/.local/share/termnetlog/netlog.db`; exports go to `~/.local/share/termnetlog/exports/`.
Override with `TERMNETLOG_DB`, `TERMNETLOG_CONFIG`, or `--db` / `--config`.

Lookup refreshes preserve existing fields when a provider omits them. Partial
results and failures have a five-minute cooldown before another ordinary lookup;
`l` forces a retry immediately. Retries occur when a lookup is requested or a net
is reopened, not on a background timer. Up to four different callsigns are looked
up concurrently; duplicate requests share one lookup. Leaving a screen cancels
requests that no other screen needs. Manual operator edits remain protected.

The database upgrades automatically to schema 2 to record lookup attempts
separately from cached details. Newer unsupported schemas are refused.

Configuration values are checked before opening the database. Use quoted strings,
TOML booleans (`true`/`false`), and a nonnegative integer for `lookup.cache_days`.
Invalid syntax, types, or timezones produce an actionable error without echoing
configuration values. `QRZ_USER` and `QRZ_PASS` override the file, including when
set to empty strings.

## Logging a net

Entry line syntax: `CALL [flags] [via RELAY] [note…]`

```
w1aw                       plain check-in
k9xyz/m t r                mobile, has traffic, staying for the ragchew
n0call via w1aw weak       relayed by W1AW, note "weak"
```

Flags: **t** traffic · **s** short time · **r** ragchew · **c** recognized · **m** mobile · **p** portable · **e** EchoLink

A submitted entry saves the operator, check-in, flags, relay, and note in one
transaction. If saving fails, the entry remains in the input box for retry;
no partial check-in is retained.

`esc` jumps to the check-in list, where those same letters toggle flags on the selected row,
`enter` edits the check-in note, `o` edits persistent operator notes, `Shift+E` edits operator details,
`l` re-runs the lookup. Start typing a callsign to jump back to the entry line.
`ctrl+e` export · `ctrl+g` net notes · `ctrl+x` end net · `ctrl+b` menu · `ctrl+t` UTC/Eastern times · `f1` help.

`ctrl+t` only changes what's on screen; the database, text roster, and ADIF exports stay in UTC.
Set `[display] local_tz` (default `America/New_York`) and `local_time = true` in the config to change the zone or start in local time.
Timezone data is included as a package dependency. `local_tz = "UTC"` also works
without timezone data. Local-time columns use the heading `Local`; individual
timestamps use the historical daylight-saving offset, rather than today's offset.

At widths below 120 columns, the compact roster omits the location column.
Press **F2** to switch between the roster and the full, scrollable operator card;
at wider sizes F2 hides/shows the side card. Tables allow horizontal scrolling.
The layout is tested at 80×24, 100×30, and 140×40, including resizing during entry.

Past nets are shown in pages of 50 with visible totals. **Ctrl+N/Ctrl+P** change
pages; **/** focuses search. Search matches a literal part of the net name
(case-insensitive for ASCII) or its UTC start date (`YYYY-MM-DD`). Press Enter
to return to the list, then Enter again to open the selected net. Empty searches
show all nets; open sessions remain included.

## CLI

```sh
termnetlog lookup W1AW              # test lookups / cache an operator
termnetlog nets                     # list nets
termnetlog export 12 -f text        # roster for email/groups.io
termnetlog export 12 -f adif -o net.adi
```

TUI exports create a new snapshot folder under `exports/` each time. Folder and
file names include the net ID; each snapshot contains a UTF-8 `.txt` roster and
an ASCII `.adi` file. Both are written before the snapshot becomes visible.
Earlier snapshots are retained, including when exporting the same net again.
An interrupted export may leave a hidden `.pending-*` folder; it is not a
completed snapshot. Snapshot publication is atomic, but is not a database backup
or a guarantee against filesystem/hardware failure.

The CLI's explicit `-o` destination is replaced only after the complete output
has been written. Validation or write failures return a nonzero exit status and
preserve any previous file. TUI failures show an error and leave logging usable.

ADIF exports validate band/frequency consistency, mode, callsigns, timestamps,
and Maidenhead locators. Common submodes such as USB, DMR, and FT4 are emitted
with their parent MODE and a SUBMODE. Locators longer than eight characters use
GRIDSQUARE_EXT. These checks follow the exported
[ADIF 3.1.4 definitions](https://www.adif.org/314/ADIF_314.htm); they do not check
regional operating permissions or verify that a contact occurred.

ADI free text uses printable ASCII: accents are removed where possible,
remaining unsupported characters become `?`, and whitespace is collapsed.
Conversions produce a TUI warning or a CLI warning on stderr. Original database
values and the UTF-8 text roster are unchanged. For a roster without ADIF
validation/conversion, use `termnetlog export NET_ID -f text`. ADX export is not
yet supported.

## Corrections and recurring nets

Select a check-in and press **F3** to correct its callsign. Confirmation shows the
old and new callsigns. A duplicate operator in the same net is refused. Only that
check-in changes: time, sequence, relay, flags, and entry note remain intact.
Operator profiles and private notes stay attached to their original callsigns;
unrelated attendance history is never moved. Mobile/portable flags are preserved
even if the corrected callsign suffix changes; adjust them separately as needed.

Use **Ctrl+D** to edit net name, frequency, band, mode, role, and NCS. Ended nets
allow corrections, but new check-ins require **Ctrl+O** and confirmation to reopen.
An attempted entry into an ended net remains in the input box. Previously exported
snapshots remain unchanged; export again after corrections.

After removing a check-in, **Ctrl+Z** restores the most recent removal for that
net. Up to 50 removals per net are kept in memory during the current application
session, including when you leave and reopen the screen. Undo restores the entry's
timestamp, fields, and old roster position (or the end if the roster is now shorter)
without overwriting later entries. A reused internal row ID is replaced with a new
one. A duplicate callsign blocks undo without merging records; resolve the conflict
first. Failed undo remains available to retry. Undo also works on ended nets.
Quitting the application or deleting the net clears its undo history; use backups
for recovery across restarts. Ctrl+Z is removal undo on the net screen, not general
undo for edits or callsign corrections.

Create a reusable preset with the configuration command:

```sh
termnetlog config --template Tuesday --set net.name "Tuesday Club Net" --set net.frequency 147.000
termnetlog config --template Tuesday --set net.ncs_callsign W1AW --set net.notes "Opening script"
termnetlog config --template Weekend --set net.role participant
```

New templates copy the current net defaults. Later edits affect only the named
template; only `net.*` settings are accepted. On the next application start,
choose **Template: Tuesday** from the menu, review the prefilled form, and press
Ctrl+S. Each use creates a fresh net with its template notes and no check-ins.
The ordinary New net action continues to use the original config defaults.
Templates live in the configuration file, so keep a secure copy of that file
separately from database-only backups. Template removal currently requires editing
its `[templates.NAME]` table in that file.

## Backup and recovery

```sh
termnetlog backup
termnetlog backup --directory /path/to/snapshots
termnetlog --db /path/to/recovered.db restore /path/to/snapshots/backup-TIMESTAMP-ID
termnetlog restore /path/to/snapshots/backup-TIMESTAMP-ID --replace
```

Backups use SQLite's backup API, including committed WAL data. Each new snapshot
folder contains a validated `netlog.db` and `metadata.json` with application/schema
versions and creation time. Configuration and QRZ credentials are excluded;
operator details and private notes are included. Store snapshots securely and
copy them to separate storage for protection against disk loss. By default they
live in `backups/` beside the database. Existing snapshots are never overwritten.

Close other termnetlog processes before restoring. Restore validates a private
copy, upgrades supported older schemas there, and refuses unknown schemas,
unexpected database structures, corruption, and broken record references.
An existing destination requires `--replace`: a safety snapshot is saved in
`backups/` beside it while an exclusive database lock prevents concurrent writes.
If that snapshot fails, replacement does not start. SQLite applies the restore
transactionally. A busy database causes failure rather than bypassing its locks.

For a recovery drill, restore into a fresh path with `--db`, open it using the same
`--db` option, and check nets, operator notes, check-in flags, sequence, and exports.
Keep the original and snapshot until that check succeeds. If the existing database
is corrupt, restore into a fresh path: replacement requires a valid safety backup.
Recovery commands honor `--db`/`TERMNETLOG_DB` without reading configuration, so a
broken config cannot block recovery. Before upgrading, create a backup and retain
it with the previous application version; automatic migration is not a backup.

## Tests

```sh
.venv/bin/python -m pytest
```

The CI workflow is configured to run the suite on Linux with Python 3.11–3.14, plus the declared minimum
runtime dependencies on Python 3.11 (`tests/minimum-requirements.txt`).
To reproduce the package checks:

```sh
.venv/bin/pip install build 'setuptools>=68' wheel
.venv/bin/python scripts/check_distribution.py
```

This builds the wheel and source archive, checks that test fixtures are included,
and installs each artifact into a temporary environment outside the checkout.
Both installations must start the TUI, load its stylesheet, and pass the tests
from the extracted archive. The temporary environments reuse your installed dev
dependencies; install `.[dev]` first. Package checks require Python 3.12 or later.

The [audit](AUDIT.md) and [release plan](RELEASE_PLAN.md) track remaining work.
The [beta checklist](BETA_CHECKLIST.md) records automated evidence and the manual
checks still required before inviting users.
All original audit regressions now run as passing checks in `tests/` or, for
package completeness (A9), `scripts/check_distribution.py`. The historical audit
is retained as context; passing automated checks do not replace release trials.
