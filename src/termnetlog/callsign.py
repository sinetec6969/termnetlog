"""Callsign normalization.

Operators often sign with prefixes/suffixes (``VE3/W1AW``, ``W1AW/M``). The
operator database is keyed on the base call, while the raw string is kept on
the check-in.

When asked, ``?`` stands in for a character the operator didn't catch
(``W1A?``) so the check-in can be logged now and corrected later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A base amateur callsign: optional digit/letter prefix, at least one digit, letter suffix.
_BASE_RE = re.compile(r"^(?:[A-Z]{1,2}|[0-9][A-Z]{1,2}|[A-Z][0-9])[0-9]{1,2}[A-Z]{1,4}$")
# The same shape with UNKNOWN allowed in any position, i.e. some fill-in would be valid.
_PARTIAL_RE = re.compile(r"^(?:[A-Z?]{1,2}|[0-9?][A-Z?]{1,2}|[A-Z?][0-9?])[0-9?]{1,2}[A-Z?]{1,4}$")

UNKNOWN = "?"

MOBILE_SUFFIXES = {"M", "MM", "AM"}


@dataclass(frozen=True)
class ParsedCall:
    raw: str
    base: str
    mobile: bool = False
    portable: bool = False


def is_incomplete(call: str) -> bool:
    return UNKNOWN in call


def is_valid_base(call: str, allow_unknown: bool = False) -> bool:
    call = call.upper()
    if allow_unknown and is_incomplete(call):
        # At least two known characters, so a stray "?" isn't logged as a call.
        return bool(_PARTIAL_RE.match(call)) and len(call) - call.count(UNKNOWN) >= 2
    return bool(_BASE_RE.match(call))


def parse(text: str, allow_unknown: bool = False) -> ParsedCall | None:
    """Parse user-entered text into a ParsedCall, or None if it isn't a callsign.

    With allow_unknown, ``?`` may stand in for characters still to be filled in.
    """
    raw = text.strip().upper().replace("\\", "/")
    if not raw:
        return None
    parts = [p for p in raw.split("/") if p]
    if not parts:
        return None
    bases = [p for p in parts if is_valid_base(p, allow_unknown)]
    if not bases:
        return None
    # With VE3/W1AW both parts can look valid-ish; prefer the longest.
    base = max(bases, key=len)
    extras = {p for p in parts if p != base}
    mobile = bool(extras & MOBILE_SUFFIXES)
    # Anything else (/P, /QRP, /4, VE3/) means operating away from home.
    portable = bool(extras - MOBILE_SUFFIXES)
    return ParsedCall(raw="/".join(parts), base=base, mobile=mobile, portable=portable)
