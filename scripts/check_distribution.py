"""Build and exercise both distributions outside the checkout.

Run with the project's dev dependencies, build, setuptools and wheel installed.
Temporary environments share those dependencies, but install their own copy of
termnetlog. An explicit import-location check rejects checkout/system fallback.
No live provider requests are made.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import venv


SMOKE = r'''
import asyncio
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import termnetlog
from termnetlog import db
from termnetlog.config import Config
from termnetlog.lookup.service import LookupService
from termnetlog.repo import Repo
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.screens.net import NetScreen

assert Path(termnetlog.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), termnetlog.__file__
assert files('termnetlog.tui').joinpath('app.tcss').read_text(encoding='utf-8').strip()

async def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        conn = db.connect(root / 'smoke.db')
        try:
            repo = Repo(conn)
            app = NetLogApp(Config(), repo, LookupService(repo, []), export_dir=root / 'exports')
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.press('n', 'ctrl+s')
                await pilot.pause()
                assert isinstance(app.screen, NetScreen)
        finally:
            conn.close()

asyncio.run(main())
print('Installed package import, stylesheet, and TUI startup passed')
'''


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME'):
        env.pop(key, None)

    def run(*args: str | Path, cwd: Path) -> None:
        subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, check=True)

    with tempfile.TemporaryDirectory(prefix='termnetlog-package-') as directory:
        work = Path(directory)
        dist = work / 'dist'
        run(sys.executable, '-m', 'build', '--no-isolation', '--outdir', dist, cwd=root)
        wheel, = dist.glob('*.whl')
        sdist, = dist.glob('*.tar.gz')
        source_dir = work / 'source'
        with tarfile.open(sdist) as archive:
            archive.extractall(source_dir, filter='data')
        source, = source_dir.iterdir()

        # Explicitly guard A9, including fixtures no existing test happens to use.
        for path in (root / 'tests').rglob('*'):
            if path.is_file() and path.suffix in {'.py', '.xml', '.json', '.txt'}:
                relative = path.relative_to(root)
                packaged = source / relative
                assert packaged.is_file(), f'Missing from source distribution: {relative}'
                assert packaged.read_bytes() == path.read_bytes(), f'Stale packaged file: {relative}'

        for kind, artifact in (('wheel', wheel), ('sdist', sdist)):
            prefix = work / kind
            venv.EnvBuilder(with_pip=True).create(prefix)
            binaries = prefix / ('Scripts' if os.name == 'nt' else 'bin')
            python = binaries / ('python.exe' if os.name == 'nt' else 'python')
            cli = binaries / ('termnetlog.exe' if os.name == 'nt' else 'termnetlog')
            site_packages = Path(subprocess.check_output(
                [str(python), '-c', "import sysconfig; print(sysconfig.get_path('purelib'))"],
                cwd=work, env=env, text=True,
            ).strip())
            # Reuse this interpreter's dependencies, not unrelated global packages.
            # Nested .pth files (including editable checkout hooks) are not loaded.
            dependency_paths = dict.fromkeys(sysconfig.get_path(key) for key in ('purelib', 'platlib'))
            (site_packages / 'build_dependencies.pth').write_text(
                '\n'.join(dependency_paths) + '\n', encoding='utf-8',
            )
            run(python, '-m', 'pip', 'install', '--no-deps', '--no-build-isolation',
                '--ignore-installed', artifact, cwd=work)
            run(python, '-m', 'pip', 'check', cwd=work)
            run(cli, '--version', cwd=work)
            run(python, '-c', SMOKE, cwd=work)
            # No checkout conftest or fixtures can mask an incomplete archive.
            run(python, '-m', 'pytest', '-q', cwd=source)
            print(f'{kind}: installed artifact and extracted test suite passed', flush=True)


if __name__ == '__main__':
    main()
