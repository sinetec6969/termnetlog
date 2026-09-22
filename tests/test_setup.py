import os
import sqlite3
import tomllib
from contextlib import closing

import pytest

from termnetlog import cli, config, db, setup
from termnetlog.lookup.service import LookupService
from termnetlog.repo import Repo


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ('QRZ_USER', 'QRZ_PASS', 'TERMNETLOG_CONFIG', 'TERMNETLOG_DB'):
        monkeypatch.delenv(name, raising=False)


def test_onboarding_edits_preserve_comments_unknown_keys_and_secrets(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text(config.DEFAULT_CONFIG + '\n# custom setting\ncustom = "keep"\n')
    setup.edit(path, [['my_callsign', 'W1AW'], ['lookup.offline', 'true'], ['net.name', 'A "quoted" net'], ['display.local_tz', 'UTC']])
    text = path.read_text()
    assert '# custom setting' in text and 'custom = "keep"' in text
    cfg = config.load(path)
    assert cfg.my_callsign == 'W1AW' and cfg.offline
    assert cfg.net.name == 'A "quoted" net'
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('key,value', [('lookup.offline', 'yes'), ('lookup.cache_days', '-1'), ('lookup.cache_days', 'x'), ('display.local_tz', 'bad/zone'), ('net.role', 'bad'), ('qrz.password', 'SECRET'), ('my_callsign', '!')])
def test_invalid_changes_leave_file_unchanged(tmp_path, key, value):
    path = tmp_path / 'config.toml'
    path.write_text(config.DEFAULT_CONFIG)
    before = path.read_bytes()
    with pytest.raises(config.ConfigError) as error:
        setup.edit(path, [[key, value]])
    assert 'SECRET' not in str(error.value)
    assert path.read_bytes() == before


def test_failed_write_keeps_existing_configuration(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    path.write_text(config.DEFAULT_CONFIG)
    def fail(*args):
        raise OSError('full')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        setup.edit(path, [['my_callsign', 'W1AW']])
    assert path.read_text() == config.DEFAULT_CONFIG


def test_hidden_qrz_credentials_are_not_printed(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'config.toml'
    answers = iter(['SECRETUSER', 'SECRETPASS'])
    monkeypatch.setattr(setup.getpass, 'getpass', lambda prompt: next(answers))
    setup.edit(path, [], qrz=True)
    assert config.load(path).qrz_password == 'SECRETPASS'
    assert setup.doctor(path, tmp_path / 'absent.db') == 0
    output = capsys.readouterr().out
    assert 'SECRET' not in output and 'configured (not tested)' in output


def test_offline_overrides_environment_credentials(repo, monkeypatch):
    monkeypatch.setenv('QRZ_USER', 'SECRETUSER')
    monkeypatch.setenv('QRZ_PASS', 'SECRETPASS')
    cfg = config._from_data({'lookup': {'offline': True}})
    service = LookupService.from_config(repo, cfg)
    assert service.providers == []


def test_doctor_does_not_create_config_or_database(tmp_path, capsys):
    path, database = tmp_path / 'config.toml', tmp_path / 'log.db'
    assert cli.main(['--config', str(path), '--db', str(database), 'doctor']) == 0
    assert not path.exists() and not database.exists()
    assert 'not created yet' in capsys.readouterr().out


def test_doctor_reports_config_error_without_secrets_and_still_checks_db(tmp_path, capsys):
    path, database = tmp_path / 'config.toml', tmp_path / 'log.db'
    path.write_text('password = "SECRET')
    with closing(db.connect(database)):
        pass
    assert setup.doctor(path, database) == 1
    output = capsys.readouterr().out
    assert 'SECRET' not in output and 'Database integrity and schema: OK' in output


def test_doctor_does_not_migrate_old_schema(tmp_path, capsys):
    database = tmp_path / 'log.db'
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(db.MIGRATIONS[0])
        conn.execute('PRAGMA user_version=1')
    before = database.read_bytes()
    assert setup.doctor(tmp_path / 'absent.toml', database) == 0
    assert database.read_bytes() == before
    assert 'Upgrade pending' in capsys.readouterr().out


@pytest.mark.parametrize('kind', ['corrupt', 'future'])
def test_doctor_rejects_bad_database(tmp_path, kind):
    database = tmp_path / 'log.db'
    if kind == 'corrupt':
        database.write_bytes(b'bad')
    else:
        with closing(db.connect(database)) as conn:
            conn.execute('PRAGMA user_version=999')
    assert setup.doctor(tmp_path / 'absent.toml', database) == 1


def test_config_cli_init_and_edit_without_database(tmp_path):
    path, database = tmp_path / 'config.toml', tmp_path / 'log.db'
    args = ['--config', str(path), '--db', str(database), 'config']
    assert cli.main(args + ['--init']) == 0
    assert cli.main(args + ['--set', 'my_callsign', 'W1AW', '--set', 'lookup.offline', 'true']) == 0
    before = path.read_bytes()
    assert cli.main(args + ['--init']) == 0
    assert path.read_bytes() == before
    assert config.load(path).offline and not database.exists()


async def test_provider_probe_sanitizes_failure_closes_every_provider(monkeypatch, capsys):
    class Provider:
        name = 'fake'
        closed = False
        async def lookup(self, call):
            raise RuntimeError('SECRET URL')
        async def aclose(self):
            self.closed = True
    provider = Provider()
    monkeypatch.setattr(LookupService, 'from_config', lambda repo, cfg: LookupService(repo, [provider]))
    assert await setup.test_providers(config.Config(), 'W1AW') == 1
    assert provider.closed
    output = capsys.readouterr().out
    assert 'SECRET' not in output and 'request failed' in output


async def test_offline_probe_never_constructs_providers(monkeypatch):
    def forbidden(*args):
        raise AssertionError('network provider constructed')
    monkeypatch.setattr('termnetlog.lookup.service.HamDBProvider', forbidden)
    assert await setup.test_providers(config.Config(offline=True), 'W1AW') == 1


def test_invalid_toml_edit_is_sanitized_and_unchanged(tmp_path):
    path = tmp_path / 'config.toml'
    original = 'password = "SECRET'
    path.write_text(original)
    with pytest.raises(config.ConfigError) as error:
        setup.edit(path, [['my_callsign', 'W1AW']])
    assert 'SECRET' not in str(error.value)
    assert path.read_text() == original


def test_doctor_makes_no_provider_requests(tmp_path, monkeypatch):
    def forbidden(*args):
        raise AssertionError('provider constructed during local diagnostics')
    monkeypatch.setattr(LookupService, 'from_config', forbidden)
    assert cli.main(['--config', str(tmp_path / 'absent.toml'), '--db', str(tmp_path / 'absent.db'), 'doctor']) == 0


def test_config_help_does_not_create_files(tmp_path):
    path = tmp_path / 'config.toml'
    assert cli.main(['--config', str(path), 'config']) == 0
    assert not path.exists()


def test_incomplete_credentials_reported_without_values(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv('QRZ_USER', 'SECRETUSER')
    assert setup.doctor(tmp_path / 'absent.toml', tmp_path / 'absent.db') == 1
    output = capsys.readouterr().out
    assert 'incomplete credentials' in output and 'SECRETUSER' not in output


def test_noninteractive_qrz_prompts_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    path = tmp_path / 'config.toml'
    assert cli.main(['--config', str(path), 'config', '--qrz']) == 2
    assert not path.exists()


async def test_successful_provider_probe_uses_ephemeral_database(tmp_path, monkeypatch, capsys):
    observed = []
    class Provider:
        name = 'fake'
        async def lookup(self, call):
            observed.append(call)
            return None
        async def aclose(self):
            pass
    monkeypatch.setattr(LookupService, 'from_config', lambda repo, cfg: LookupService(repo, [Provider()]))
    missing = tmp_path / 'log.db'
    assert await setup.test_providers(config.Config(db_path=missing), 'w1aw') == 0
    assert observed == ['W1AW'] and not missing.exists()
    assert 'not found (request succeeded)' in capsys.readouterr().out


async def test_offline_tui_labels_mode_and_logs_without_providers(repo, tmp_path, monkeypatch):
    from textual.widgets import Static
    from termnetlog.tui.app import NetLogApp
    from termnetlog.tui.widgets.checkin_table import CallInput
    def forbidden(*args):
        raise AssertionError('offline mode constructed a network provider')
    monkeypatch.setattr('termnetlog.lookup.service.HamDBProvider', forbidden)
    monkeypatch.setattr('termnetlog.lookup.service.QRZProvider', forbidden)
    cfg = config.Config(offline=True, qrz_username='SECRET', qrz_password='SECRET')
    app = NetLogApp(cfg, repo, export_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        assert 'offline' in str(app.screen.query_one('#start-status', Static).render())
        net = repo.create_net('Offline', '146.520', 'FM', '2m', 'W1AW', 'ncs')
        app.open_net(net.id)
        await pilot.pause()
        app.screen.query_one(CallInput).value = 'K9XYZ t offline note'
        await pilot.press('enter')
        await app.workers.wait_for_complete()
        rows = repo.list_checkins(net.id)
        assert len(rows) == 1 and rows[0].checkin.notes == 'offline note'
        assert rows[0].checkin.has_traffic
