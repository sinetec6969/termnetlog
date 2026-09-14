"""User configuration (~/.config/termnetlog/config.toml)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_config_path, user_data_path

APP = "termnetlog"

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


@dataclass
class Config:
    my_callsign: str = ""
    net: NetDefaults = field(default_factory=NetDefaults)
    qrz_username: str = ""
    qrz_password: str = ""
    cache_days: int = 30
    hamdb: bool = True
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
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(DEFAULT_CONFIG)


def load(path: Path | None = None, create: bool = True) -> Config:
    path = path or config_path()
    if create:
        ensure_config_file(path)
    data: dict = {}
    if path.exists():
        with path.open("rb") as f:
            data = tomllib.load(f)

    net = data.get("net", {})
    qrz = data.get("qrz", {})
    lookup = data.get("lookup", {})
    display = data.get("display", {})
    defaults = NetDefaults()
    return Config(
        my_callsign=str(data.get("my_callsign", "")).upper(),
        net=NetDefaults(
            name=str(net.get("name", defaults.name)),
            frequency=str(net.get("frequency", defaults.frequency)),
            mode=str(net.get("mode", defaults.mode)),
            band=str(net.get("band", defaults.band)),
            role=str(net.get("role", defaults.role)),
            ncs_callsign=str(net.get("ncs_callsign", "")).upper(),
        ),
        qrz_username=os.environ.get("QRZ_USER") or str(qrz.get("username", "")),
        qrz_password=os.environ.get("QRZ_PASS") or str(qrz.get("password", "")),
        cache_days=int(lookup.get("cache_days", 30)),
        hamdb=bool(lookup.get("hamdb", True)),
        local_tz=str(display.get("local_tz", "America/New_York")),
        local_time=bool(display.get("local_time", False)),
    )
