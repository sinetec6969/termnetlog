"""User configuration (~/.config/termnetlog/config.toml)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from platformdirs import user_config_path, user_data_path

APP = "termnetlog"


class ConfigError(ValueError):
    """An actionable configuration problem, without secret values."""


def display_timezone(name: str) -> tzinfo:
    if name == 'UTC':
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(
            'display.local_tz: use a valid IANA timezone such as America/New_York, '
            'or UTC. Reinstall termnetlog if timezone data is missing.'
        ) from None

DEFAULT_CONFIG = """\
# termnetlog configuration

# Your own callsign (used as STATION_CALLSIGN in ADIF exports).
my_callsign = ""

[net]
# Defaults used to prefill the "New net" form.
name = "Nightly 2m Net"
frequency = "146.520"
mode = "FM"
band = "2m"
role = "ncs"            # "ncs" or "participant"
ncs_callsign = ""

[qrz]
# QRZ.com login for the XML API. Without a paid XML subscription QRZ returns
# only partial records; HamDB fills the gaps for US calls.
# Env vars QRZ_USER / QRZ_PASS override these.
username = ""
password = ""

[lookup]
offline = false        # disable all network lookups, including QRZ env credentials
cache_days = 30         # re-lookup operators older than this
hamdb = true            # use api.hamdb.org as a free fallback

[display]
# ctrl+t toggles displayed times between UTC and this zone. Logs and ADIF stay UTC.
local_tz = "America/New_York"
local_time = false      # start in local time instead of UTC
"""


@dataclass
class NetDefaults:
    name: str = "Nightly 2m Net"
    frequency: str = "146.520"
    mode: str = "FM"
    band: str = "2m"
    role: str = "ncs"
    ncs_callsign: str = ""
    notes: str = ""


@dataclass
class Config:
    my_callsign: str = ""
    net: NetDefaults = field(default_factory=NetDefaults)
    qrz_username: str = ""
    qrz_password: str = field(default="", repr=False)
    cache_days: int = 30
    hamdb: bool = True
    offline: bool = False
    templates: dict[str, NetDefaults] = field(default_factory=dict)
    local_tz: str = "America/New_York"
    local_time: bool = False
    db_path: Path = field(default_factory=lambda: default_db_path())


def config_path() -> Path:
    env = os.environ.get("TERMNETLOG_CONFIG")
    return Path(env) if env else user_config_path(APP) / "config.toml"


def default_db_path() -> Path:
    env = os.environ.get("TERMNETLOG_DB")
    return Path(env) if env else user_data_path(APP) / "netlog.db"


def ensure_config_file(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return  # Another invocation created the file after the initial check.
    with os.fdopen(fd, "w", encoding='utf-8') as f:
        f.write(DEFAULT_CONFIG)


def load(path: Path | None = None, create: bool = True) -> Config:
    path = path or config_path()
    try:
        if create:
            ensure_config_file(path)
        data: dict = {}
        if path.exists():
            with path.open("rb") as f:
                data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, UnicodeError):
        # Parser messages can contain fragments of credential-bearing lines.
        raise ConfigError(f'{path}: invalid TOML or UTF-8; check the file syntax and encoding') from None
    except OSError:
        raise ConfigError(f'{path}: cannot read or create configuration; check path and permissions') from None

    try:
        return _from_data(data)
    except ConfigError as error:
        raise ConfigError(f'{path}: {error}') from None


def _from_data(data: dict) -> Config:
    def section(name: str) -> dict:
        value = data.get(name, {})
        if not isinstance(value, dict):
            raise ConfigError(f'{name}: expected a TOML table [{name}]')
        return value

    def value(table: dict, key: str, default, label: str = ''):
        result = table.get(key, default)
        if type(result) is not type(default):
            expected = {str: 'a quoted string', bool: 'true or false', int: 'an integer'}[type(default)]
            raise ConfigError(f'{label or key}: expected {expected}')
        return result

    net, qrz, lookup, display = (section(name) for name in ('net', 'qrz', 'lookup', 'display'))
    defaults = NetDefaults()
    cfg = Config(
        my_callsign=value(data, 'my_callsign', '').strip().upper(),
        net=NetDefaults(
            **{key: value(net, key, getattr(defaults, key), f'net.{key}')
               for key in ('name', 'frequency', 'mode', 'band', 'role', 'ncs_callsign', 'notes')},
        ),
        qrz_username=os.environ['QRZ_USER'] if 'QRZ_USER' in os.environ else value(qrz, 'username', '', 'qrz.username'),
        qrz_password=os.environ['QRZ_PASS'] if 'QRZ_PASS' in os.environ else value(qrz, 'password', '', 'qrz.password'),
        cache_days=value(lookup, 'cache_days', 30, 'lookup.cache_days'),
        hamdb=value(lookup, 'hamdb', True, 'lookup.hamdb'),
        offline=value(lookup, 'offline', False, 'lookup.offline'),
        local_tz=value(display, 'local_tz', 'America/New_York', 'display.local_tz'),
        local_time=value(display, 'local_time', False, 'display.local_time'),
    )
    cfg.net.ncs_callsign = cfg.net.ncs_callsign.strip().upper()
    if cfg.net.role not in ('ncs', 'participant'):
        raise ConfigError('net.role: expected "ncs" or "participant"')
    if not cfg.net.name.strip():
        raise ConfigError('net.name: cannot be blank')
    if cfg.cache_days < 0:
        raise ConfigError('lookup.cache_days: expected a nonnegative integer')
    try:
        timedelta(days=cfg.cache_days)
    except OverflowError:
        raise ConfigError('lookup.cache_days: value is too large') from None
    display_timezone(cfg.local_tz)
    for name, settings in section('templates').items():
        if not name.strip() or not isinstance(settings, dict):
            raise ConfigError('templates: expected nonblank names containing net defaults')
        # Reuse net validation; template tables contain only net-default fields.
        nested = _from_data({'net': settings, 'display': {'local_tz': 'UTC'}})
        cfg.templates[name] = nested.net
    return cfg
