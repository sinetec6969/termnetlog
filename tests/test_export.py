import re

from termnetlog import callsign, export
from termnetlog.lookup.base import LookupResult


def build(repo):
    net = repo.create_net("Nightly 2m Net", "146.520", "FM", "2m", "KX9ABC", "ncs")
    repo.apply_lookup(LookupResult("W1AW", "hamdb", first_name="Hiram", name="Hiram Maxim", city="Newington", state="CT", county="Hartford", grid="FN31pr"))
    a = repo.add_checkin(net.id, callsign.parse("W1AW"))
    b = repo.add_checkin(net.id, callsign.parse("K9XYZ/M"))
    repo.set_flag(a.id, "has_traffic")
    repo.set_flag(b.id, "ragchew")
    repo.set_checkin_notes(b.id, "new mobile rig")
    return repo.get_net(net.id), repo.list_checkins(net.id)


def test_adif_field_lengths(repo):
    net, rows = build(repo)
    adi = export.to_adif(net, rows, "N0ME")
    assert "<EOH>" in adi and adi.count("<EOR>") == 2
    # Each declared length must end exactly where the field's value ends.
    for name, length, rest in re.findall(r"<(\w+):(\d+)>([^<]*)", adi):
        assert rest[int(length) :].strip() == "", (name, length, rest)
    assert "<CALL:7>K9XYZ/M" in adi
    assert "<BAND:2>2m" in adi and "<MODE:2>FM" in adi
    assert "<CNTY:11>CT,Hartford" in adi
    assert "<STATION_CALLSIGN:4>N0ME" in adi


def test_text_roster(repo):
    net, rows = build(repo)
    text = export.to_text(net, rows)
    assert "2 check-ins" in text
    assert "NCS: KX9ABC" in text
    assert "Traffic: W1AW" in text
    assert "Stayed for ragchew: K9XYZ/M" in text
    assert "new mobile rig" in text
    assert "in progress" in text
