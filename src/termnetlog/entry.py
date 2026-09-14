"""Parse the check-in entry line.

Syntax:  CALL [flags...] [via RELAY] [note words...]

    w1aw                    plain check-in
    k9xyz/m t r             mobile, has traffic, staying for ragchew
    n0call via w1aw weak    relayed by W1AW, note "weak"

Flag letters: t traffic, s short time, r ragchew, c recognized, m mobile, p portable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from termnetlog import callsign
from termnetlog.callsign import ParsedCall

FLAG_LETTERS = {
    "t": "has_traffic",
    "s": "short_time",
    "r": "ragchew",
    "c": "recognized",
    "m": "mobile",
    "p": "portable",
}


@dataclass
class Entry:
    call: ParsedCall
    flags: set[str] = field(default_factory=set)
    relayed_by: str = ""
    note: str = ""


def parse(text: str) -> Entry | None:
    tokens = text.split()
    if not tokens:
        return None
    call = callsign.parse(tokens[0])
    if call is None:
        return None
    entry = Entry(call=call)
    if call.mobile:
        entry.flags.add("mobile")
    if call.portable:
        entry.flags.add("portable")

    rest = tokens[1:]
    note_words: list[str] = []
    i = 0
    while i < len(rest):
        tok = rest[i]
        low = tok.lower()
        if not note_words and low in FLAG_LETTERS:
            entry.flags.add(FLAG_LETTERS[low])
        elif not note_words and low == "via" and i + 1 < len(rest) and callsign.parse(rest[i + 1]):
            entry.relayed_by = callsign.parse(rest[i + 1]).raw  # type: ignore[union-attr]
            i += 1
        else:
            note_words.append(tok)
        i += 1
    entry.note = " ".join(note_words)
    return entry
