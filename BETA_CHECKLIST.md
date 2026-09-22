# Operator beta checklist

Beta candidate **0.2.0b1** is being prepared under MIT for GitHub Releases.
No release has been published. See [BETA_EVIDENCE.md](BETA_EVIDENCE.md) for dated
results and their limits. The implementation is merged into main at `c940515`;
beta preparation follows on main, with its hosted CI verification pending.

## Completed evidence and preparation

- [x] Original implementation passes hosted Linux/Python 3.11–3.14 CI and package
      checks ([run](https://github.com/sinetec6969/termnetlog/actions/runs/35766688229)).
- [x] Maintainer selected MIT license and GitHub Releases; added license, beta
      version metadata, changelog, contribution guidance, and feedback template.
- [x] Prepared a manual workflow to create a tested **draft** GitHub prerelease.
- [x] Installed in a fresh virtual environment; dependency consistency passes.
- [x] All 226 local tests pass with current/minimum dependencies and both installed
      package formats; the new beta candidate still needs hosted CI verification.
- [x] Isolated-config, headless 80×24 setup/log/restart/resume/recovery smoke check.
- [x] Large synthetic recovery drill preserves every row in every application table.
- [x] Measured 100,000-history/200-active-net performance; improved entry redraws.
      Measured entry p95 is 63 ms, history queries under 10 ms (headless/local limits apply).
- [x] Live public HamDB response verified without storing returned operator details.
- [x] Clean-install runtime dependency vulnerability scan: no known findings.
- [x] Prepared synthetic ADI samples with independently parsed expected fields.

## Still required before inviting beta users

- [ ] Review the beta preparation changes and verify their hosted CI.
- [ ] Complete physical Linux terminal testing at 80×24 in a clean OS user account:
      keyboard navigation, resize, clipboard failure, search, corrections, reopen,
      undo, and restart. Headless tests do not close this gate.
- [ ] Repeat recovery with realistic anonymized data and a backup on another device;
      preserve config/templates separately. Synthetic same-filesystem recovery is done.
- [ ] Name the destination logging application/version and import the supplied ADI
      samples into a disposable test log; compare counts/fields and participant use.
- [ ] Verify optional QRZ authentication using locally configured credentials;
      do not send credentials or credential-bearing URLs in chat/issues.
- [ ] Review remaining participant/QSO export semantics: only actual contacts belong
      in a QSO log; roster inclusion does not establish that a contact occurred.
- [ ] Run the manual draft-release workflow, review assets/notes, and explicitly
      approve publication. Do not claim additional OS support before testing it.

## Pilot feedback

After the gates above, invite 3–5 operators across at least 10 real nets. Exercise
restart/resume, offline operation, typo correction, undo, export, and recovery.
Use the GitHub beta feedback template, with synthetic examples and sanitized errors.
No pilot users have been contacted and no real operator logs have been collected.

Known limits: removal undo is process-local; template removal requires configuration
editing; cloud sync and concurrent multi-user editing are outside the beta scope.
