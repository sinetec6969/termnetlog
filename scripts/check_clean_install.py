"""Exercise an installed package with temporary XDG directories (not a new OS user)."""
import asyncio
from contextlib import closing
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import termnetlog
from termnetlog import config, db
from termnetlog.repo import Repo
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.widgets.checkin_table import CallInput

assert Path(termnetlog.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())

async def check(root):
    os.environ['XDG_CONFIG_HOME'] = str(root / 'config')
    os.environ['XDG_DATA_HOME'] = str(root / 'data')
    for key in ('TERMNETLOG_CONFIG', 'TERMNETLOG_DB', 'QRZ_USER', 'QRZ_PASS'):
        os.environ.pop(key, None)
    for args in [('config', '--set', 'my_callsign', 'W1AW', '--set', 'lookup.offline', 'true'), ('doctor',)]:
        subprocess.run([sys.executable, '-m', 'termnetlog', *args], check=True)
    cfg = config.load()
    with closing(db.connect(cfg.db_path)) as conn:
        repo = Repo(conn)
        app = NetLogApp(cfg, repo, export_dir=root / 'exports')
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press('n', 'ctrl+s')
            await pilot.pause()
            net_id = app.screen.net_id
            app.screen.query_one(CallInput).value = 'K9XYZ t synthetic note'
            await pilot.press('enter')
            await pilot.pause()
    with closing(db.connect(cfg.db_path)) as conn:
        repo = Repo(conn)
        app = NetLogApp(cfg, repo, export_dir=root / 'exports')
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press('enter')  # Resume the saved open net.
            await pilot.pause()
            assert app.screen.net_id == net_id
            assert repo.list_checkins(net_id)[0].checkin.notes == 'synthetic note'
    subprocess.run([sys.executable, '-m', 'termnetlog', 'backup'], check=True)
    subprocess.run([sys.executable, '-m', 'termnetlog', 'doctor'], check=True)
    print('Clean installed-package setup, 80x24 headless logging, restart/resume, backup, and diagnostics passed.')

with tempfile.TemporaryDirectory(prefix='termnetlog-clean-user-') as directory:
    asyncio.run(check(Path(directory)))
