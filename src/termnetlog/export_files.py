"""Publish complete export snapshots and atomically replace explicit CLI files."""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from termnetlog import adif, export
from termnetlog.models import CheckInRow, Net


def _write_file(path: Path, text: str, encoding: str) -> None:
    with path.open('w', encoding=encoding, newline='\n') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_write_text(path: Path, text: str, *, encoding: str = 'utf-8') -> None:
    """A failed write leaves the previous destination intact."""
    # Serialize first, before creating files or replacing an existing destination.
    text.encode(encoding)
    fd, filename = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    staged = Path(filename)
    try:
        with os.fdopen(fd, 'w', encoding=encoding, newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def write_bundle(directory: Path, net: Net, rows: list[CheckInRow], station_callsign: str = '',
                 *, warnings: list[str] | None = None) -> list[Path]:
    """Publish a new snapshot directory with both formats, never update older ones.

    The staging directory and destination share a filesystem so one directory
    rename publishes the pair. A process killed before that may leave a hidden
    .pending-* directory, but never a partially written published snapshot.
    """
    adi = export.to_adif(net, rows, station_callsign, warnings=warnings)
    txt = export.to_text(net, rows)
    adi.encode('ascii')
    txt.encode('utf-8')
    directory.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r'[^a-z0-9]+', '-', net.name.lower()).strip('-')[:60] or 'net'
    started = adif.timestamp(net.started_utc, 'Net start')
    stem = f'net-{net.id}-{started:%Y%m%d-%H%M}-{slug}'
    destination = directory / f'{stem}-{uuid4().hex}'
    names = [f'{stem}.txt', f'{stem}.adi']
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=directory) as temporary:
        staging = Path(temporary)
        _write_file(staging / names[0], txt, 'utf-8')
        _write_file(staging / names[1], adi, 'ascii')
        staging.rename(destination)
    return [destination / name for name in names]
