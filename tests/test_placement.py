"""End-to-end placement tests: fixture PDF plus the MusicXML that produced it.

The expected bar and beat for all nine chord symbols are known by construction -
they were written into tests/fixtures/geometry.musicxml by hand - so this pins the
whole pipeline, not just the geometry underneath it.

Run with the venv that has pdfplumber:

    ~/.venvs/music-skills/bin/python -m unittest discover -s tests -v
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "plugins/music/skills/sheet-music-pdf-to-musescore/scripts"))

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

try:
    import pdfplumber
except ImportError:                                    # pragma: no cover
    pdfplumber = None

import place_chords_from_pdf as placer


class UnionOnsetTest(unittest.TestCase):
    """Every rhythmic position in a bar, across all parts and both piano staves.

    The reason this has to span parts: chord symbols are engraved above whichever
    note sounds at that moment, in any staff. Counting only the top part's onsets
    made the note columns and the score disagree, and when the counts coincided
    anyway the chord was mapped to the wrong column - putting the G in bar 13 of
    the test chart on beat 2 instead of beat 3.
    """

    @classmethod
    def setUpClass(cls):
        _layout, cls.tree = placer.score_layout(str(FIXTURES / "geometry.musicxml"))
        cls.onsets = placer.union_onsets(cls.tree.getroot())

    def test_a_bar_of_eighths_has_eight_positions(self):
        """Quarter = 4 divisions here, so eighths land on the even numbers."""
        self.assertEqual(self.onsets["1"], [0, 2, 4, 6, 8, 10, 12, 14])

    def test_a_bar_of_whole_notes_has_one_position(self):
        self.assertEqual(self.onsets["2"], [0])
        self.assertEqual(self.onsets["6"], [0])

    def test_the_piano_left_hand_adds_no_position_it_shares(self):
        """Two half notes under four quarters contribute nothing new."""
        self.assertEqual(self.onsets["5"], [0, 4, 8, 12])

    def test_a_backup_rewinds_the_clock_rather_than_advancing_it(self):
        """Bar 4 is two halves over one whole note in the left hand.

        Without honouring <backup> the left hand's whole note would be counted at
        division 16, past the end of the bar.
        """
        self.assertEqual(self.onsets["4"], [0, 8])


@unittest.skipIf(pdfplumber is None, "pdfplumber not installed")
class PlacementTest(unittest.TestCase):
    """Where each of the nine chord symbols ends up."""

    # (measure, symbol, division) as written into the fixture MusicXML.
    EXPECTED = [
        ("0", "C", 0.0),
        ("1", "F", 0.0), ("1", "G", 8.0),
        ("2", "Am", 0.0),
        ("3", "Dm", 0.0),
        ("4", "E7", 8.0),
        ("5", "C", 0.0), ("5", "G/B", 8.0),
        ("6", "Fsus2", 0.0),
    ]

    @classmethod
    def setUpClass(cls):
        layout, tree = placer.score_layout(str(FIXTURES / "geometry.musicxml"))
        part = tree.getroot().find("part")
        measures = {m.get("number"): m for m in part.findall("measure")}
        cls.doc = pdfplumber.open(FIXTURES / "geometry.pdf")
        cls.placements, cls.notes = placer.place_by_geometry(
            cls.doc, layout, measures, placer.union_onsets(tree.getroot()))

    @classmethod
    def tearDownClass(cls):
        cls.doc.close()

    def test_every_chord_lands_in_the_bar_it_was_written_in(self):
        got = sorted((m, sym) for m, syms in self.placements.items()
                     for _x, sym, _d in syms)
        self.assertEqual(got, sorted((m, sym) for m, sym, _d in self.EXPECTED))

    def test_every_chord_lands_on_the_beat_it_was_written_on(self):
        got = sorted((m, sym, round(d, 2)) for m, syms in self.placements.items()
                     for _x, sym, d in syms)
        self.assertEqual(got, sorted(self.EXPECTED))

    def test_a_second_chord_in_a_bar_lands_on_beat_three(self):
        """Not beat one, which is what stacks two chords on top of each other."""
        for bar in ("1", "5"):
            divisions = sorted(d for _x, _s, d in self.placements[bar])
            self.assertEqual(divisions, [0.0, 8.0])

    def test_the_pickup_bar_places_its_chord_on_the_downbeat(self):
        """Bar 0's clef and time signature push the note 45% across the bar.

        Measuring proportionally from the barline would call that beat three. The
        clef and time signature glyphs are discounted instead.
        """
        self.assertEqual([d for _x, _s, d in self.placements["0"]], [0.0])

    def test_beat_placement_is_exact_not_proportional(self):
        self.assertIn("9 exact", " ".join(self.notes))