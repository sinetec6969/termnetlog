import pytest

from termnetlog import callsign, entry


@pytest.mark.parametrize(
    "text, base, mobile, portable",
    [
        ("w1aw", "W1AW", False, False),
        (" KX9ABC ", "KX9ABC", False, False),
        ("K9XYZ/M", "K9XYZ", True, False),
        ("k9xyz/mm", "K9XYZ", True, False),
        ("W1AW/P", "W1AW", False, True),
        ("W1AW/4", "W1AW", False, True),
        ("VE3/W1AW", "W1AW", False, True),
        ("2E0ABC", "2E0ABC", False, False),
        ("AA7BQ", "AA7BQ", False, False),
    ],
)
def test_parse(text, base, mobile, portable):
    p = callsign.parse(text)
    assert p is not None
    assert (p.base, p.mobile, p.portable) == (base, mobile, portable)


@pytest.mark.parametrize("text", ["", "hello", "123", "/M", "W1", "QRP"])
def test_parse_invalid(text):
    assert callsign.parse(text) is None


def test_entry_flags_relay_note():
    e = entry.parse("k9xyz/m t r via w1aw weak signal")
    assert e is not None
    assert e.call.base == "K9XYZ"
    assert e.flags == {"mobile", "has_traffic", "ragchew"}
    assert e.relayed_by == "W1AW"
    assert e.note == "weak signal"


def test_entry_note_words_are_not_flags_after_note_starts():
    e = entry.parse("w1aw new rig t")
    assert e is not None
    assert e.flags == set()
    assert e.note == "new rig t"


def test_entry_invalid():
    assert entry.parse("hello there") is None
    assert entry.parse("   ") is None
