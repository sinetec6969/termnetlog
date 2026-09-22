# Synthetic import samples

Import these files into a disposable test log in the selected logging application.
They are synthetic records, not evidence of real contacts. Do not upload them to
LoTW/eQSL or merge them into a production log.

- `midnight-unicode-mobile.adi`: two records straddling midnight UTC, /M and /P
  callsigns, accented name/city converted to ASCII, and station identity.
- `participant-contact.adi`: one synthetic contact with the NCS in participant mode.
- `expected.json`: independently parsed fields to compare against imported values.

Record application/version, imported counts, dates/times, callsigns/suffixes,
mode/band/frequency, station identity, notes, and warnings. Delete the test log
when done. This fixture set does not close the interoperability gate until an
actual destination application has been tested.
