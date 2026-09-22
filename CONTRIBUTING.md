# Contributing and beta feedback

Install Python 3.11 or newer, create a virtual environment, and install `.[dev]`.
Run `python -m pytest -q` before submitting changes. Packaging checks additionally
need `build`, `setuptools>=68`, and `wheel`; run `python scripts/check_distribution.py`.
Run `python scripts/check_beta.py --output /tmp/termnetlog-beta.json` for the synthetic
performance/recovery check. It uses temporary data and makes no network requests.

Open a GitHub issue with the version, OS/terminal, terminal size, reproduction steps,
and expected/actual behavior. Use synthetic callsigns and notes when possible.
Never attach QRZ credentials, config files, your database, private operator notes,
or unreviewed diagnostic output. Doctor output includes local filesystem paths;
redact them if you do not want to share them. Do not include live-provider URLs.

For changes, open a branch/PR with the problem, intended behavior, and verification.
Keep schema changes versioned and test upgrades and rollback on synthetic fixtures.
Preserve manual edits, existing logs, and failed-input recovery. Contributions are
under the project's MIT license.

A maintainer can manually run **Prepare draft beta release** on main after the
checklist passes. It rebuilds/tests packages and creates a draft GitHub prerelease
with wheel/source assets. Review its notes and assets before explicitly publishing.
The workflow is not triggered by pushes or tags and does not publish automatically.
