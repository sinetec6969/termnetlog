# Beta verification evidence — 2026-09-22

Candidate: **0.2.0b1**, MIT license, GitHub Releases selected by the maintainer.
Prepared on main; no tag or release has been published.

## Hosted CI

The merged implementation at `c940515` passed the main-branch workflow:
[GitHub run 35766688229](https://github.com/sinetec6969/termnetlog/actions/runs/35766688229).
This covers Linux/Python 3.11–3.14, minimum dependencies, and package checks.
The subsequent beta preparation/performance changes still need hosted CI verification.
Locally, all **226 tests** pass with current and minimum runtime dependencies and
against both installed distribution formats. Installed package/application versions
match; dependency consistency and stylesheet/TUI startup checks also pass.

## Installation and recovery

A fresh virtual environment at `/tmp/termnetlog-beta-020b1` installed the package
and runtime dependencies independently of the development environment. `pip check`
passed. `scripts/check_clean_install.py` exercised isolated temporary XDG paths,
offline setup, a headless 80×24 TUI, logging, shutdown/restart/resume, backup, and
local diagnostics. This is not a new OS account or physical-terminal test.

The large-history recovery exercise compared counts and SHA-256 digests for all
rows in all application tables before and after backup/restore: **501 nets,
230 operators, 100,230 check-ins**, and the empty lookup-attempt table matched.
Backup/restore plus comparison took about 0.91 seconds. Both paths were on the
same temporary filesystem, so the separate-device recovery gate remains open.

## Performance

Run `python scripts/check_beta.py --output /tmp/termnetlog-beta.json` to reproduce.
It creates 100,000 historical check-ins plus a 200-station active net, then measures
30 additional entries. Reference environment: Linux x86_64, Intel Core i7-8665U,
8 visible logical CPUs, Python 3.13.5, SQLite 3.46.1, Textual 8.2.8; local temporary
storage. Full environment and results are retained in `audit/beta-performance.json`.

| Measurement | p95 | Proposed budget |
|---|---:|---:|
| Entry to headless render completion | 63.04 ms | <100 ms |
| History page (offset 400) repository query | 9.83 ms | <300 ms |
| History count/filter repository queries | 2.62 ms | <300 ms |
| Active roster repository query | 14.45 ms | Diagnostic only |

Initial entry p95 was 149.50 ms (`audit/beta-performance-before.json`). Removing
unnecessary offline lookup workers alone did not meet the target; updating only
changed/appended roster cells instead of rebuilding the table brought this run
within budget. Deletion/reordering still rebuilds the table when needed.

These are warm, synthetic, headless measurements. History numbers measure repository
queries, not complete screen interaction. They do not establish physical-terminal
latency, online-provider performance, other platforms, or a universal guarantee.

## Providers, dependencies, and exports

- A live public HamDB request for W1AW returned a parsed response. No operator
  details were retained in this report, and no saved database was modified.
- QRZ credentials were not requested/read for this probe; authenticated QRZ remains
  unverified. Offline/no-network behavior is covered by automated tests.
- `pip-audit` checked the exact runtime dependency versions from the clean install
  against public PyPI vulnerability data and reported no known vulnerabilities.
  Raw evidence: `audit/beta-dependency-audit.json`. The local project and installer
  tooling were excluded; this is not a code security certification.
- Synthetic ADI fixtures and independently parsed expected fields are in
  `audit/adif-samples/`. Destination application/version is still needed; actual
  application import has not been performed.

## Release preparation

Added MIT LICENSE, beta version metadata, CHANGELOG.md, CONTRIBUTING.md, and a
credential-conscious feedback template. The manual `beta-release.yml` workflow
runs package checks and creates a **draft prerelease** with wheel/source assets.
It does not publish automatically and has not been executed. Finish the remaining
checklist and review the draft before publication.
