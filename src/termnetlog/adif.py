"""Validation for the ADIF 3.1.4 fields emitted by termnetlog.

Enumeration/range reference: https://www.adif.org/314/ADIF_314.htm
These are interchange definitions, not regional operating permissions.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal

from termnetlog import callsign
from termnetlog.models import from_iso


class ExportValidationError(ValueError):
    """The log contains a value that cannot be exported as ADIF."""


BANDS = {
    '2190m': ('.1357', '.1378'), '630m': ('.472', '.479'), '560m': ('.501', '.504'),
    '160m': ('1.8', '2.0'), '80m': ('3.5', '4.0'), '60m': ('5.06', '5.45'),
    '40m': ('7.0', '7.3'), '30m': ('10.1', '10.15'), '20m': ('14.0', '14.35'),
    '17m': ('18.068', '18.168'), '15m': ('21.0', '21.45'), '12m': ('24.890', '24.99'),
    '10m': ('28.0', '29.7'), '8m': ('40', '45'), '6m': ('50', '54'),
    '5m': ('54.000001', '69.9'), '4m': ('70', '71'), '2m': ('144', '148'),
    '1.25m': ('222', '225'), '70cm': ('420', '450'), '33cm': ('902', '928'),
    '23cm': ('1240', '1300'), '13cm': ('2300', '2450'), '9cm': ('3300', '3500'),
    '6cm': ('5650', '5925'), '3cm': ('10000', '10500'), '1.25cm': ('24000', '24250'),
    '6mm': ('47000', '47200'), '4mm': ('75500', '81000'), '2.5mm': ('119980', '123000'),
    '2mm': ('134000', '149000'), '1mm': ('241000', '250000'), 'submm': ('300000', '7500000'),
}
MODES = set('''AM ARDOP ATV CHIP CLO CONTESTI CW DIGITALVOICE DOMINO DYNAMIC FAX FM
FSK441 FT8 HELL ISCAT JT4 JT6M JT9 JT44 JT65 MFSK MSK144 MT63 OLIVIA OPERA PAC PAX
PKT PSK PSK2K Q15 QRA64 ROS RTTY RTTYM SSB SSTV T10 THOR THRB TOR V4 VOI WINMOR WSPR'''.split())
# Common input submodes; the net model has a single mode field.
SUBMODES = {
    'USB': 'SSB', 'LSB': 'SSB', 'C4FM': 'DIGITALVOICE', 'DMR': 'DIGITALVOICE',
    'DSTAR': 'DIGITALVOICE', 'FREEDV': 'DIGITALVOICE', 'M17': 'DIGITALVOICE',
    'FT4': 'MFSK', 'JS8': 'MFSK', 'Q65': 'MFSK', 'PSK31': 'PSK',
}


def radio_fields(band: str, frequency: str, mode: str) -> tuple[str, str, str, str]:
    band, frequency, mode = band.strip().lower(), frequency.strip(), mode.strip().upper()
    if band and band not in BANDS:
        raise ExportValidationError('BAND: use an ADIF band such as 2m or 70cm')
    if frequency:
        if not re.fullmatch(r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)', frequency) or Decimal(frequency) <= 0:
            raise ExportValidationError('FREQ: enter a positive decimal frequency in MHz (for example 146.520)')
        if band:
            low, high = map(Decimal, BANDS[band])
            if not low <= Decimal(frequency) <= high:
                raise ExportValidationError(f'FREQ/BAND: frequency does not match {band}; check net details')
    if mode in SUBMODES:
        return band, frequency, SUBMODES[mode], mode
    if mode and mode not in MODES:
        raise ExportValidationError('MODE: use an ADIF 3.1.4 mode (for example FM, SSB, or FT8)')
    return band, frequency, mode, ''


def call(value: str, label: str, *, optional: bool = False) -> str:
    value = value.strip().upper()
    if optional and not value:
        return ''
    if not re.fullmatch(r'[A-Z0-9]+(?:/[A-Z0-9]+)*', value) or callsign.parse(value) is None:
        raise ExportValidationError(f'{label}: correct the callsign before exporting')
    return value


def grid(value: str | None, label: str) -> tuple[str, str]:
    value = (value or '').strip().upper()
    if value and not re.fullmatch(r'[A-R]{2}(?:[0-9]{2}(?:[A-X]{2}(?:[0-9]{2}(?:[A-X]{2}(?:[0-9]{2})?)?)?)?)?', value):
        raise ExportValidationError(f'{label}: use a valid 2–12 character Maidenhead locator')
    return value[:8], value[8:]


def timestamp(value: str | None, label: str) -> datetime:
    try:
        parsed = from_iso(value)
    except (ValueError, TypeError):
        parsed = None
    if parsed is None or parsed.year < 1930:
        raise ExportValidationError(f'{label}: expected a UTC timestamp from 1930 onward')
    return parsed


def ascii_text(value: str, field: str, warnings: list[str] | None = None) -> str:
    # ADI String fields contain printable ASCII. The UTF-8 roster remains lossless.
    value = ' '.join(value.split())
    decomposed = unicodedata.normalize('NFKD', value)
    converted = ''.join(
        ch if ' ' <= ch <= '~' else '?'
        for ch in decomposed if not unicodedata.combining(ch)
    )
    if value and not converted:
        converted = '?'
    if converted != value and warnings is not None:
        message = f'ADIF {field}: characters converted to ASCII; original data remains in the log'
        if message not in warnings:
            warnings.append(message)
    return converted
