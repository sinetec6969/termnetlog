"""Repeatable synthetic beta performance/recovery check; no network or user data.

Run: .venv/bin/python scripts/check_beta.py --output /tmp/termnetlog-beta.json
Headless render completion is a proxy, not physical terminal latency.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
import tempfile
import time

from textual.widgets import Input
from termnetlog import backup, db
from termnetlog.config import Config
from termnetlog.repo import Repo
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.widgets.checkin_table import CallInput


def stats(samples):
    ordered = sorted(samples)
    return {'samples': len(samples), 'p50_ms': round(ordered[len(ordered)//2], 2),
            'p95_ms': round(ordered[math.ceil(len(ordered)*.95)-1], 2), 'max_ms': round(max(samples), 2)}


def digest(conn):
    result = {}
    for table in ('nets', 'operators', 'checkins', 'lookup_attempts'):
        hasher = hashlib.sha256()
        count = 0
        for row in conn.execute(f'SELECT * FROM {table} ORDER BY 1'):
            hasher.update(json.dumps(tuple(row), ensure_ascii=True).encode())
            count += 1
        result[table] = {'rows': count, 'sha256': hasher.hexdigest()}
    return result


def seed(conn):
    calls = [f'K1{chr(65+i//26)}{chr(65+i%26)}' for i in range(200)]
    stamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with conn:
        conn.executemany('INSERT INTO operators(callsign,name,operator_notes,created_at) VALUES (?,?,?,?)',
                         [(call, f'Synthetic operator {i}', f'Synthetic note {i}', stamp.isoformat()) for i, call in enumerate(calls)])
        for i in range(501):
            date = (stamp + timedelta(days=i)).strftime('%Y-%m-%dT%H:%M:%SZ')
            conn.execute('INSERT INTO nets(id,name,frequency,started_utc,ended_utc,notes) VALUES (?,?,?,?,?,?)',
                         (i+1, f'Weekly net {i}', '146.520', date, date if i < 500 else None, 'Synthetic net notes'))
            conn.executemany('INSERT INTO checkins(net_id,callsign,logged_as,seq,time_utc,has_traffic,notes) VALUES (?,?,?,?,?,?,?)',
                             [(i+1, call, call, n+1, date, n % 2, f'Synthetic entry {n}') for n, call in enumerate(calls)])
    return 501


async def measure(repo, net_id, work):
    results = {}
    for name, operation in [('history_page', lambda: repo.list_nets(50, offset=400)),
                            ('history_filter', lambda: (repo.count_nets('Weekly net 4'), repo.list_nets(50, search='Weekly net 4'))),
                            ('active_roster', lambda: repo.list_checkins(net_id))]:
        samples = []
        for _ in range(30):
            started = time.perf_counter()
            operation()
            samples.append((time.perf_counter()-started)*1000)
        results[name] = stats(samples)
    app = NetLogApp(Config(offline=True), repo, export_dir=work / 'exports')
    async with app.run_test(size=(100, 30)) as pilot:
        app.open_net(net_id)
        await pilot.pause()
        await app.workers.wait_for_complete()
        screen = app.screen
        inp = screen.query_one(CallInput)
        original = screen.refresh_all
        pending = None
        def refreshed(*args, **kwargs):
            original(*args, **kwargs)
            target = pending
            if target is not None:
                def complete():
                    if not target.done():
                        target.set_result(time.perf_counter())
                app.call_after_refresh(complete)
        screen.refresh_all = refreshed
        samples = []
        for i in range(30):
            inp.value = f'N9{chr(65+i//26)}{chr(65+i%26)}'
            await pilot.pause()
            pending = asyncio.get_running_loop().create_future()
            started = time.perf_counter()
            inp.post_message(Input.Submitted(inp, inp.value))
            finished = await asyncio.wait_for(pending, 15)
            samples.append((finished-started)*1000)
            await app.workers.wait_for_complete()
        results['entry_to_headless_render'] = stats(samples)
        assert len(repo.list_checkins(net_id)) == 230
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'recorded_utc': datetime.now(timezone.utc).isoformat(), 'platform': platform.platform(),
              'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version, 'cpu_count': os.cpu_count(),
              'dependencies': {name: version(name) for name in ('textual', 'httpx', 'platformdirs', 'tzdata', 'tomlkit')},
              'dataset': {'historical_checkins': 100000, 'initial_active_checkins': 200},
              'limitations': 'Synthetic data; temporary local filesystem; headless 100x30 render, not a physical terminal or second backup device.'}
    cpuinfo = Path('/proc/cpuinfo')
    if cpuinfo.exists():
        report['cpu'] = next((line.split(':', 1)[1].strip() for line in cpuinfo.read_text().splitlines() if line.startswith('model name')), 'unknown')
    with tempfile.TemporaryDirectory(prefix='termnetlog-beta-') as directory:
        work = Path(directory)
        database = work / 'source.db'
        with closing(db.connect(database)) as conn:
            net_id = seed(conn)
            report['timings'] = asyncio.run(measure(Repo(conn), net_id, work))
            before = digest(conn)
        started = time.perf_counter()
        snapshot = backup.backup(database, work / 'backups')
        restored = work / 'restored.db'
        backup.restore(snapshot, restored)
        with closing(db.connect(restored)) as conn:
            after = digest(conn)
        assert before == after, 'Recovery did not preserve every table'
        report['recovery'] = {'all_tables_match': True, 'tables': after, 'seconds': round(time.perf_counter()-started, 3)}
        report['database_bytes'] = database.stat().st_size
    report['budgets_met'] = {'entry_p95_under_100ms': report['timings']['entry_to_headless_render']['p95_ms'] < 100,
                             'history_p95_under_300ms': all(report['timings'][key]['p95_ms'] < 300 for key in ('history_page', 'history_filter'))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
