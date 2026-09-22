# Operator beta checklist

The release work is on `release/ci-packaging`. This checklist records evidence and open
release gates; it is not a publication approval or a claim of field validation.

## Automated evidence

- Offline setup, template selection, logging, ending a net, text/ADI export,
  backup, restore into a fresh path, and post-restore diagnostics:
  `tests/test_undo_recovery.py::test_offline_setup_export_backup_restore_drill`.
- Correction preserves unrelated history and private notes; removal undo preserves
  entry fields and ordering, rejects duplicates, and rolls back failures:
  `tests/test_corrections_templates.py`, `tests/test_undo_recovery.py`.
- History reaches old nets; narrow layouts, resize, and long dialogs work in
  headless tests: `tests/test_history_layout.py`.
- Configuration/credential handling, offline guarantees, provider failure handling,
  backup safety, and export interoperability have dedicated regression suites.
- `scripts/check_distribution.py` checks installed wheel/source packages, dependency
  consistency, stylesheet/TUI startup, and the extracted source test suite.

## Before inviting beta users

- [ ] Review the local changes and run the GitHub-hosted Python 3.11–3.14 matrix.
- [ ] Choose a project license and the beta distribution channel; prepare release
      notes, versioning, and support/issue-report instructions.
- [ ] Run the README quick start in a clean user account and a physical Linux
      terminal at 80×24. Check keyboard navigation, resize, clipboard failure,
      history search, correction, reopen, undo, and shutdown/restart.
- [ ] Repeat the documented recovery drill with a realistic anonymized history
      and a backup stored on a different device. Keep config/templates separately.
- [ ] Import representative ADI exports into a chosen logging application; cover
      Unicode conversion, mobile/portable calls, midnight UTC, and participant use.
- [ ] Test optional QRZ/HamDB access with maintainer-supplied credentials/network;
      automated tests use mocks and do not establish live service compatibility.
- [ ] Measure the performance budgets in RELEASE_PLAN.md against a large history.
- [ ] Verify each additional OS/terminal before claiming support for it.

## Pilot feedback

Invite 3–5 operators to use the beta across at least 10 nets. Ask them to exercise
restart/resume, offline logging, typo correction, removal undo, export, and recovery.
Record reproducible workflow problems without requesting credentials or private
operator logs. Resolve data loss or operation-interrupting failures before 1.0.

Known scope: undo is process-local and limited to removals; template removal uses
the configuration file; cloud sync and concurrent multi-user editing are excluded.
