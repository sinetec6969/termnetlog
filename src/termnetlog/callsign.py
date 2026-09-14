"""Callsign normalization.

Operators often sign with prefixes/suffixes (``VE3/W1AW``, ``W1AW/M``). The
operator database is keyed on the base call, while the raw string is kept on
the check-in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A base amateur callsign: optional digit/letter prefix, at least one digit, letter suffix.
_BASE_RE = re.compile(r"^(?:[A-Z]{1,2}|[0-9][A-Z]{1,2}|[A-Z][0-9])[0-9]{1,2}[A-Z]{1,4}$")

MOBILE_SUFFIXES = {"M", "MM", "AM"}


@dataclass(frozen=True)
class ParsedCall:
    raw: str
    base: str
    mobile: bool = False
    portable: bool = False


def is_valid_base(call: str) -> bool:
    return bool(_BASE_RE.match(call.upper()))


def parse(text: str) -> ParsedCall | None:
    """Parse user-entered text into a ParsedCall, or None if it isn't a callsign."""
    raw = text.strip().upper().replace("\\", "/")
    if not raw:
        return None
    parts = [p for p in raw.split("/") if p]
    if not parts:
        return None
    bases = [p for p in parts if is_valid_base(p)]
    if not bases:
        return None
    # With VE3/W1AW both parts can look valid-ish; prefer the longest.
    base = max(bases, key=len)
    extras = {p for p in parts if p != base}
    mobile = bool(extras & MOBILE_SUFFIXES)
    # Anything else (/P, /QRP, /4, VE3/) means operating away from home.
    portable = bool(extras - MOBILE_SUFFIXES)
    return ParsedCall(raw="/".join(parts), base=base, mobile=mobile, portable=portable)
