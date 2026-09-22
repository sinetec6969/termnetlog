from dataclasses import replace
from pathlib import Path

import adif_io
import pytest

from termnetlog import callsign, cli, export, export_files
from termnetlog.adif import ExportValidationError
from termnetlog.config import Config
from termnetlog.lookup.service import LookupService
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.widgets.checkin_table import CallInput


def make_net(repo):
    net = repo.create_net('Test Net', '146.520', 'FM', '2m', 'W1AW', 'ncs')
    repo.add_checkin(net.id, callsign.parse('W1AW'))
    return net


def test_different_nets_and_reexports_preserve_snapshots(repo, tmp_path):
    first, second = make_net(repo), make_net(repo)
    first = replace(first, started_utc='2026-09-22T01:00:00Z')
    second = replace(second, started_utc=first.started_utc)
    directory = tmp_path / 'exports'
    paths1 = export_files.write_bundle(directory, first, repo.list_checkins(first.id))
    original = [path.read_bytes() for path in paths1]
    paths2 = export_files.write_bundle(directory, second, [])
    paths3 = export_files.write_bundle(directory, first, [])
    assert len({path.parent for path in paths1 + paths2 + paths3}) == 3
    assert [path.read_bytes() for path in paths1] == original
    assert f'net-{first.id}-' in paths1[0].name
    assert all({p.suffix for p in folder.iterdir()} == {'.adi', '.txt'} for folder in directory.iterdir())


@pytest.mark.parametrize('failure', ['second_write', 'publish'])
def test_bundle_failure_preserves_existing_files(repo, tmp_path, monkeypatch, failure):
    net = make_net(repo)
    rows = repo.list_checkins(net.id)
    directory = tmp_path / 'exports'
    old = export_files.write_bundle(directory, net, rows)
    original = {path: path.read_bytes() for path in old}
    original_write = export_files._write_file

    def fail_write(path, text, encoding):
        if path.suffix == '.adi':
            path.write_text('partial')
            raise OSError('disk full')
        original_write(path, text, encoding)

    def fail_publish(self, target):
        raise PermissionError('cannot publish')

    if failure == 'second_write':
        monkeypatch.setattr(export_files, '_write_file', fail_write)
    else:
        monkeypatch.setattr(Path, 'rename', fail_publish)
    with pytest.raises(OSError):
        export_files.write_bundle(directory, net, rows)
    assert {path: path.read_bytes() for path in old} == original
    assert list(directory.iterdir()) == [old[0].parent]


def test_invalid_adif_does_not_publish_text_only_bundle(repo, tmp_path):
    net = replace(make_net(repo), frequency='not a frequency')
    directory = tmp_path / 'exports'
    with pytest.raises(ExportValidationError, match='FREQ'):
        export_files.write_bundle(directory, net, repo.list_checkins(net.id))
    assert not directory.exists()


def test_adi_ascii_conversion_and_embedded_tags_parse_independently(repo):
    net = replace(make_net(repo), name='Net <EOH> café')
    repo.update_operator('W1AW', name='José 日本')
    row = repo.list_checkins(net.id)[0]
    repo.set_checkin_notes(row.checkin.id, 'Discussed <EOR>\nnew antenna ☕')
    warnings = []
    rows = repo.list_checkins(net.id)
    output = export.to_adif(net, rows, warnings=warnings)
    records, header = adif_io.read_from_string(output)
    assert output.isascii() and header['ADIF_VER'] == '3.1.4'
    assert len(records) == 1
    assert records[0]['NAME'] == 'Jose ??'
    assert records[0]['COMMENT'] == 'Net <EOH> cafe; Discussed <EOR> new antenna ?'
    assert any('NAME' in message for message in warnings)
    assert any('COMMENT' in message for message in warnings)
    assert repo.get_operator('W1AW').name == 'José 日本'
    assert 'José 日本' in export.to_text(net, rows)


@pytest.mark.parametrize('field,value,label', [
    ('frequency', '146.520 MHz', 'FREQ'), ('frequency', 'NaN', 'FREQ'),
    ('frequency', '-1', 'FREQ'), ('frequency', '0', 'FREQ'),
    ('frequency', '1e2', 'FREQ'), ('frequency', '146,520', 'FREQ'),
    ('frequency', '440.0', 'FREQ/BAND'), ('band', 'VHF', 'BAND'),
    ('mode', 'made up', 'MODE'), ('started_utc', 'yesterday', 'Net start'),
])
def test_invalid_metadata_is_rejected(repo, field, value, label):
    net = replace(make_net(repo), **{field: value})
    with pytest.raises(ExportValidationError, match=label):
        export.to_adif(net, repo.list_checkins(net.id))


@pytest.mark.parametrize('grid', ['ZZ99', 'FN1', 'FN31YY', 'FN31PR001', 'FN31PR00ZZ', 'FN31\nPR'])
def test_invalid_locators_are_rejected(repo, grid):
    net = make_net(repo)
    repo.update_operator('W1AW', grid=grid)
    with pytest.raises(ExportValidationError, match='GRIDSQUARE'):
        export.to_adif(net, repo.list_checkins(net.id))


@pytest.mark.parametrize('grid', ['FN', 'FN31', 'fn31pr', 'FN31PR00', 'FN31PR00AA', 'FN31PR00AA12'])
def test_locator_precision_roundtrips(repo, grid):
    net = make_net(repo)
    repo.update_operator('W1AW', grid=grid)
    records, _ = adif_io.read_from_string(export.to_adif(net, repo.list_checkins(net.id)))
    assert records[0]['GRIDSQUARE'] + records[0].get('GRIDSQUARE_EXT', '') == grid.upper()


@pytest.mark.parametrize('mode, expected, submode', [('fm', 'FM', ''), ('usb', 'SSB', 'USB'),
    ('DMR', 'DIGITALVOICE', 'DMR'), ('FT4', 'MFSK', 'FT4')])
def test_modes_normalize_to_valid_fields(repo, mode, expected, submode):
    net = replace(make_net(repo), mode=mode)
    records, _ = adif_io.read_from_string(export.to_adif(net, repo.list_checkins(net.id)))
    assert records[0]['MODE'] == expected
    assert records[0].get('SUBMODE', '') == submode


def test_utc_midnight_and_mobile_calls_roundtrip(repo):
    net = make_net(repo)
    first = repo.list_checkins(net.id)[0].checkin
    second = repo.add_checkin(net.id, callsign.parse('K9XYZ/M'))
    repo.conn.execute("UPDATE checkins SET time_utc = '2026-09-22T23:59:59Z' WHERE id = ?", (first.id,))
    repo.conn.execute("UPDATE checkins SET time_utc = '2026-09-23T00:00:01Z' WHERE id = ?", (second.id,))
    repo.conn.commit()
    records, _ = adif_io.read_from_string(export.to_adif(net, repo.list_checkins(net.id), 'N0ME'))
    assert [r['QSO_DATE'] for r in records] == ['20260922', '20260923']
    assert [r['TIME_ON'] for r in records] == ['235959', '000001']
    assert records[1]['CALL'] == 'K9XYZ/M'
    assert all(r['STATION_CALLSIGN'] == 'N0ME' for r in records)


def test_empty_net_and_optional_metadata(repo):
    net = replace(make_net(repo), band='', frequency='', mode='')
    records, header = adif_io.read_from_string(export.to_adif(net, []))
    assert len(records) == 0 and header['PROGRAMID'] == 'termnetlog'
    records, _ = adif_io.read_from_string(export.to_adif(net, repo.list_checkins(net.id)))
    assert records[0].get('STATION_CALLSIGN') is None
    assert records[0].get('FREQ') is None


@pytest.mark.parametrize('value', ['W1AW/<EOH>', 'W1AW//M', '日本', 'W1AW\nM'])
def test_invalid_calls_are_rejected_without_transliteration(repo, value):
    net = make_net(repo)
    with pytest.raises(ExportValidationError, match='STATION_CALLSIGN'):
        export.to_adif(net, repo.list_checkins(net.id), value)


@pytest.mark.parametrize('failure', ['flush', 'replace'])
def test_atomic_file_failure_keeps_previous_file(tmp_path, monkeypatch, failure):
    target = tmp_path / 'net.adi'
    target.write_text('previous')
    def fail(*args):
        raise OSError('write failed')
    monkeypatch.setattr(export_files.os, 'fsync' if failure == 'flush' else 'replace', fail)
    with pytest.raises(OSError):
        export_files.atomic_write_text(target, 'replacement')
    assert target.read_text() == 'previous'
    assert list(tmp_path.iterdir()) == [target]


def test_cli_validation_failure_keeps_destination(repo, tmp_path, capsys):
    net = replace(make_net(repo), mode='invalid')
    repo.update_net(net.id, mode=net.mode)
    target = tmp_path / 'net.adi'
    target.write_text('previous')
    args = ['--config', str(tmp_path / 'config.toml'), '--db', str(tmp_path / 'test.db'),
            'export', str(net.id), '-f', 'adif', '-o', str(target)]
    assert cli.main(args) == 1
    captured = capsys.readouterr()
    assert 'MODE' in captured.err and not captured.out
    assert target.read_text() == 'previous'


def test_cli_warns_separately_from_adif_stdout(repo, tmp_path, capsys):
    net = make_net(repo)
    repo.update_operator('W1AW', name='José')
    args = ['--config', str(tmp_path / 'config.toml'), '--db', str(tmp_path / 'test.db'),
            'export', str(net.id), '-f', 'adif']
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    records, _ = adif_io.read_from_string(captured.out)
    assert records[0]['NAME'] == 'Jose' and 'warning:' in captured.err


@pytest.mark.parametrize('format', ['text', 'adif'])
def test_cli_replaces_explicit_output_with_correct_encoding(repo, tmp_path, capsys, format):
    net = make_net(repo)
    repo.update_operator('W1AW', name='José')
    target = tmp_path / 'output'
    target.write_text('previous')
    args = ['--config', str(tmp_path / 'config.toml'), '--db', str(tmp_path / 'test.db'),
            'export', str(net.id), '-f', format, '-o', str(target)]
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    assert 'wrote' in captured.out
    if format == 'text':
        assert 'José' in target.read_text(encoding='utf-8')
    else:
        records, _ = adif_io.read_from_string(target.read_text(encoding='ascii'))
        assert records[0]['NAME'] == 'Jose' and 'warning:' in captured.err


def test_cli_io_error_returns_failure_without_overwriting(repo, tmp_path, monkeypatch, capsys):
    net = make_net(repo)
    target = tmp_path / 'output'
    target.write_text('previous')
    def fail(*args):
        raise PermissionError('cannot replace output')
    monkeypatch.setattr(export_files.os, 'replace', fail)
    args = ['--config', str(tmp_path / 'config.toml'), '--db', str(tmp_path / 'test.db'),
            'export', str(net.id), '-o', str(target)]
    assert cli.main(args) == 1
    captured = capsys.readouterr()
    assert 'export failed:' in captured.err and 'wrote' not in captured.out
    assert target.read_text() == 'previous'


@pytest.mark.parametrize('screen_name', ['net', 'history'])
async def test_tui_export_failure_is_recoverable(repo, tmp_path, monkeypatch, screen_name):
    net = make_net(repo)
    app = NetLogApp(Config(), repo, LookupService(repo, []), export_dir=tmp_path / 'exports')
    notices = []
    monkeypatch.setattr(app, 'notify', lambda message, **kw: notices.append((str(message), kw)))
    def fail(*args, **kwargs):
        raise PermissionError('export directory is read-only')
    monkeypatch.setattr(app, 'write_exports', fail)
    async with app.run_test(size=(140, 40)) as pilot:
        if screen_name == 'net':
            app.open_net(net.id)
            await pilot.pause()
            await pilot.press('ctrl+e')
            app.screen.query_one(CallInput).value = 'K9XYZ'
            await pilot.press('enter')
            assert len(repo.list_checkins(net.id)) == 2
        else:
            await pilot.press('h')
            await pilot.pause()
            await pilot.press('x')
        await pilot.pause()
        assert any(kw.get('title') == 'Export failed' for _, kw in notices)
        assert not any(kw.get('title') == 'Exported' for _, kw in notices)


async def test_clipboard_failure_does_not_misreport_saved_files(repo, tmp_path, monkeypatch):
    net = make_net(repo)
    app = NetLogApp(Config(), repo, LookupService(repo, []), export_dir=tmp_path / 'exports')
    notices = []
    monkeypatch.setattr(app, 'notify', lambda message, **kw: notices.append((str(message), kw)))
    def fail(text):
        raise RuntimeError('clipboard unavailable')
    monkeypatch.setattr(app, 'copy_to_clipboard', fail)
    async with app.run_test(size=(140, 40)) as pilot:
        app.open_net(net.id)
        await pilot.pause()
        await pilot.press('ctrl+e')
        assert any(kw.get('title') == 'Exported' for _, kw in notices)
        assert any('Files saved; clipboard copy failed' in msg for msg, _ in notices)
        assert len(list((tmp_path / 'exports').rglob('*.adi'))) == 1
