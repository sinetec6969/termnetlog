import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from zoneinfo import ZoneInfoNotFoundError

import pytest

from termnetlog import cli, config
from termnetlog.tui import format as fmt


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    for key in ('QRZ_USER', 'QRZ_PASS', 'TERMNETLOG_CONFIG', 'TERMNETLOG_DB'):
        monkeypatch.delenv(key, raising=False)


def test_default_config_created_privately(tmp_path):
    path = tmp_path / 'config' / 'config.toml'
    cfg = config.load(path)
    assert cfg.net.name == 'Nightly 2m Net' and cfg.cache_days == 30
    assert cfg.local_tz == 'America/New_York' and not cfg.local_time
    assert path.read_text(encoding='utf-8') == config.DEFAULT_CONFIG
    if os.name == 'posix':
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('text, label', [
    ('net = "SECRET"', 'net'),
    ('my_callsign = 123', 'my_callsign'),
    ('[net]\nfrequency = 146.52', 'net.frequency'),
    ('[net]\nrole = "SECRET"', 'net.role'),
    ('[net]\nname = " "', 'net.name'),
    ('[qrz]\npassword = ["SECRET"]', 'qrz.password'),
    ('[lookup]\ncache_days = true', 'lookup.cache_days'),
    ('[lookup]\ncache_days = -1', 'lookup.cache_days'),
    ('[lookup]\ncache_days = 1.5', 'lookup.cache_days'),
    ('[lookup]\ncache_days = 99999999999999999999', 'lookup.cache_days'),
    ('[lookup]\nhamdb = "false"', 'lookup.hamdb'),
    ('[display]\nlocal_time = "true"', 'display.local_time'),
    ('[display]\nlocal_tz = "../SECRET"', 'display.local_tz'),
    ('[display]\nlocal_tz = "No/Such_Zone"', 'display.local_tz'),
])
def test_invalid_config_is_actionable_without_echoing_values(tmp_path, text, label):
    path = tmp_path / 'config.toml'
    path.write_text(text, encoding='utf-8')
    with pytest.raises(config.ConfigError) as caught:
        config.load(path)
    assert label in str(caught.value) and str(path) in str(caught.value)
    assert 'SECRET' not in str(caught.value)
    assert path.read_text(encoding='utf-8') == text


@pytest.mark.parametrize('contents', [b'[qrz]\npassword = "SECRET', b'\xffSECRET'])
def test_invalid_syntax_and_encoding_are_not_echoed(tmp_path, contents):
    path = tmp_path / 'config.toml'
    path.write_bytes(contents)
    with pytest.raises(config.ConfigError, match='syntax and encoding') as caught:
        config.load(path)
    assert 'SECRET' not in str(caught.value)


def test_env_overrides_and_false_values(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    path.write_text('''my_callsign = " w1aw "
[qrz]
username = "file-user"
password = "file-secret"
[lookup]
hamdb = false
cache_days = 0
[display]
local_tz = "UTC"
local_time = true
''')
    monkeypatch.setenv('QRZ_USER', 'env-user')
    monkeypatch.setenv('QRZ_PASS', '')
    monkeypatch.setenv('TERMNETLOG_CONFIG', str(path))
    monkeypatch.setenv('TERMNETLOG_DB', str(tmp_path / 'custom.db'))
    cfg = config.load()
    assert cfg.qrz_username == 'env-user' and cfg.qrz_password == ''
    assert cfg.my_callsign == 'W1AW' and cfg.local_time
    assert cfg.cache_days == 0 and cfg.hamdb is False
    assert cfg.db_path == tmp_path / 'custom.db'
    assert 'SECRET' not in repr(config.Config(qrz_password='SECRET'))


def test_missing_config_without_creation(tmp_path):
    path = tmp_path / 'absent.toml'
    assert config.load(path, create=False).cache_days == 30
    assert not path.exists()


def test_config_access_error_has_useful_path(tmp_path):
    with pytest.raises(config.ConfigError, match='permissions') as caught:
        config.load(tmp_path)
    assert str(tmp_path) in str(caught.value)


def test_cli_reports_configuration_error_before_creating_database(tmp_path, capsys):
    path = tmp_path / 'config.toml'
    path.write_text('[qrz]\npassword = "SECRET')
    database = tmp_path / 'test.db'
    assert cli.main(['--config', str(path), '--db', str(database), 'nets']) == 2
    captured = capsys.readouterr()
    assert 'configuration error:' in captured.err
    assert 'SECRET' not in captured.err and 'Traceback' not in captured.err
    assert not database.exists()


@pytest.mark.parametrize('kind', ['future', 'corrupt', 'directory'])
def test_cli_database_startup_errors_are_reported(tmp_path, capsys, kind):
    path = tmp_path / 'test.db'
    if kind == 'future':
        with sqlite3.connect(path) as conn:
            conn.execute('PRAGMA user_version = 999')
    elif kind == 'corrupt':
        path.write_bytes(b'not a sqlite database')
    else:
        path.mkdir()
    code = cli.main(['--config', str(tmp_path / 'config.toml'), '--db', str(path), 'nets'])
    assert code == 1
    error = capsys.readouterr().err
    assert 'Traceback' not in error
    assert ('requires a newer' if kind == 'future' else 'database error:') in error


def test_tui_starts_without_system_timezone_data(tmp_path):
    script = '''
import asyncio
from pathlib import Path
from termnetlog import config, db
from termnetlog.repo import Repo
from termnetlog.lookup.service import LookupService
from termnetlog.tui.app import NetLogApp
from termnetlog.tui import format as fmt
cfg = config.load(Path('settings.toml'))
repo = Repo(db.connect(':memory:'))
app = NetLogApp(cfg, repo, LookupService(repo, []))
async def main():
    async with app.run_test() as pilot:
        await pilot.press('ctrl+t')
        assert fmt.hhmm('2026-09-13T01:30:00Z') == '2130'
asyncio.run(main())
repo.conn.close()
'''
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=tmp_path,
        env={**os.environ, 'PYTHONTZPATH': '', 'PYTHONPATH': str(Path(config.__file__).resolve().parents[1])},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_timezone_labels_and_dst_transitions():
    try:
        fmt.set_display_tz('America/New_York', True)
        assert fmt.zone_label() == 'Local' and fmt.zone_name() == 'America/New_York'
        assert fmt.zone('2026-01-01T12:00:00Z') == 'EST'
        assert fmt.zone('2026-07-01T12:00:00Z') == 'EDT'
        assert fmt.hhmm('2026-03-08T06:59:00Z') == '0159'
        assert fmt.hhmm('2026-03-08T07:00:00Z') == '0300'
        assert fmt.hhmm('2026-11-01T05:30:00Z') == fmt.hhmm('2026-11-01T06:30:00Z') == '0130'
        assert fmt.zone('2026-11-01T05:30:00Z') == 'EDT'
        assert fmt.zone('2026-11-01T06:30:00Z') == 'EST'
        fmt.toggle_local()
        assert fmt.zone_label() == 'UTC' and fmt.hhmm('2026-07-01T12:00:00Z') == '1200'
    finally:
        fmt.set_display_tz('UTC', False)


def test_utc_remains_available_if_all_zone_data_is_missing(tmp_path, monkeypatch):
    def missing(name):
        raise ZoneInfoNotFoundError(name)
    monkeypatch.setattr(config, 'ZoneInfo', missing)
    path = tmp_path / 'settings.toml'
    path.write_text('[display]\nlocal_tz = "UTC"\nlocal_time = true')
    cfg = config.load(path)
    try:
        fmt.set_display_tz(cfg.local_tz, cfg.local_time)
        assert fmt.hhmm('2026-09-13T01:30:00Z') == '0130'
        with pytest.raises(config.ConfigError, match='timezone data is missing'):
            config.display_timezone('America/New_York')
    finally:
        fmt.set_display_tz('UTC', False)
