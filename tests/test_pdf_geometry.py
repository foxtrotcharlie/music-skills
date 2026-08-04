"""Ground-truth tests for pdf_geometry, against tests/fixtures/geometry.pdf.

Run with the venv that has pdfplumber:

    ~/.venvs/music-skills/bin/python -m unittest discover -s tests -v

Every expected value here was measured off the fixture and cross-checked against
the MusicXML that produced it, so a failure means the extractor is wrong, not that
the numbers drifted. Positions are asserted with a tolerance of a point, because
they are typeset coordinates, not integers.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "plugins/music/skills/sheet-music-pdf-to-musescore/scripts"))

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures/geometry.pdf"

try:
    import pdfplumber
except ImportError:                                    # pragma: no cover
    pdfplumber = None

import pdf_geometry


@unittest.skipIf(pdfplumber is None, "pdfplumber not installed")
class StaffGeometryTest(unittest.TestCase):
    """The fixture is one page: two systems of three staves (voice + piano)."""

    @classmethod
    def setUpClass(cls):
        cls.pdf = pdfplumber.open(FIXTURE)
        cls.page = cls.pdf.pages[0]

    @classmethod
    def tearDownClass(cls):
        cls.pdf.close()

    def test_finds_six_staves(self):
        self.assertEqual(len(pdf_geometry.staves(self.page)), 6)

    def test_each_staff_has_five_lines(self):
        for staff in pdf_geometry.staves(self.page):
            self.assertEqual(len(staff.tops), 5)

    def test_staff_tops_match_the_engraving(self):
        tops = [round(s.tops[0], 1) for s in pdf_geometry.staves(self.page)]
        for got, want in zip(tops, [126.9, 213.6, 265.6, 437.4, 524.1, 576.2]):
            self.assertAlmostEqual(got, want, delta=1.0)

    def test_merges_the_segments_a_staff_line_is_drawn_in(self):
        """MuseScore breaks each staff line at every barline; Sibelius does not.

        A staff's x-extent has to come from the union of its segments, or a
        three-segment line reads as three separate short staves.
        """
        first = pdf_geometry.staves(self.page)[0]
        self.assertAlmostEqual(first.x0, 79.8, delta=1.0)
        self.assertAlmostEqual(first.x1, 552.9, delta=1.0)

    def test_groups_staves_into_two_systems_of_three(self):
        got = pdf_geometry.systems(self.page)
        self.assertEqual([len(s.staves) for s in got], [3, 3])

    def test_system_x_extent_ignores_lyrics_that_overhang(self):
        """The last bar's lyric runs past the final barline.

        Taking the extent from text bounding boxes - what the old equal-slot code
        did - stretches the system right and skews every bar. Staff lines are
        immune to that.
        """
        got = pdf_geometry.systems(self.page)
        self.assertAlmostEqual(got[0].x0, 79.8, delta=1.0)
        self.assertAlmostEqual(got[1].x0, 42.5, delta=1.0)
        for system in got:
            self.assertAlmostEqual(system.x1, 552.9, delta=1.0)


@unittest.skipIf(pdfplumber is None, "pdfplumber not installed")
class BarlineTest(unittest.TestCase):
    """System 1 holds the pickup plus two bars; system 2 holds four."""

    @classmethod
    def setUpClass(cls):
        cls.pdf = pdfplumber.open(FIXTURE)
        cls.systems = pdf_geometry.systems(cls.pdf.pages[0])

    @classmethod
    def tearDownClass(cls):
        cls.pdf.close()

    def test_finds_every_bar_boundary_in_the_first_system(self):
        for got, want in zip(self.systems[0].barlines, [80.3, 170.0, 435.8, 552.5]):
            self.assertAlmostEqual(got, want, delta=1.0)
        self.assertEqual(len(self.systems[0].barlines), 4)

    def test_finds_every_bar_boundary_in_the_second_system(self):
        for got, want in zip(self.systems[1].barlines,
                             [43.0, 204.9, 311.4, 466.2, 547.9]):
            self.assertAlmostEqual(got, want, delta=1.0)
        self.assertEqual(len(self.systems[1].barlines), 5)

    def test_note_stems_are_not_mistaken_for_barlines(self):
        """The fixture has 73 vertical strokes and only 9 of them are barlines.

        Stems are the same width and the same hairline weight; what separates
        them is that a barline's ends sit on a staff's top and bottom lines.
        """
        self.assertEqual(sum(len(s.barlines) for s in self.systems), 9)

    def test_a_light_heavy_final_barline_counts_once(self):
        """The final barline is a thin stroke and a thick one 3.7pt apart.

        Left as two boundaries it would invent an empty bar at the end of the
        score, so the pair collapses to the leftmost.
        """
        last_two = self.systems[1].barlines[-2:]
        self.assertGreater(last_two[1] - last_two[0], 50.0)

    def test_bars_are_not_equal_width(self):
        """Eight eighths against one whole note. Equal slots cannot model this.

        This is the assumption the old placement code made, and the reason it
        could not generalise.
        """
        bars = self.systems[0].barlines
        widths = [b - a for a, b in zip(bars, bars[1:])]
        self.assertGreater(max(widths) / min(widths), 2.0)


class BarBoundaryTest(unittest.TestCase):
    """Coverage rule, on coordinates measured off a real Sibelius engraving.

    These are the strokes of page 1 system 2 of the test chart, a vocal staff over
    a piano grand staff. Two of them are note stems that happen to run the full
    height of their staff and so pass the alignment test on their own; what marks
    them out is that a barline crosses every staff in the system and a stem
    crosses one. The barline at 228.9 is drawn twice, 2.3pt apart.

    Held as data rather than a PDF because the chart is a purchased score and
    cannot be committed.
    """

    STAVES = [
        pdf_geometry.Staff([256.0, 260.2, 264.2, 268.4, 272.5], 36.0, 575.9),
        pdf_geometry.Staff([314.5, 318.6, 322.8, 326.9, 331.0], 36.0, 575.9),
        pdf_geometry.Staff([354.8, 358.9, 363.1, 367.2, 371.3], 36.0, 575.9),
    ]
    STROKES = [
        (36.24, 256.0, 371.3),      # system start, one stroke over all three
        (191.20, 314.6, 330.4),     # stem
        (228.90, 256.0, 272.5), (228.90, 314.5, 371.3),
        (231.18, 256.0, 272.5), (231.18, 314.5, 371.3),
        (403.38, 256.0, 272.5), (403.38, 314.5, 371.3),
        (540.80, 314.6, 330.4),     # stem
        (575.70, 256.0, 272.5), (575.70, 314.5, 371.3),
    ]

    def test_keeps_only_strokes_that_cross_every_staff(self):
        got = pdf_geometry.bar_boundaries(self.STAVES, self.STROKES)
        self.assertEqual([round(x, 2) for x in got],
                         [36.24, 228.90, 403.38, 575.70])

    def test_a_stem_spanning_one_staff_is_not_a_bar_boundary(self):
        got = pdf_geometry.bar_boundaries(self.STAVES, self.STROKES)
        for stem in (191.20, 540.80):
            self.assertNotIn(stem, [round(x, 2) for x in got])

    def test_a_barline_split_across_staves_still_counts_once(self):
        """The vocal staff and the piano get separate strokes at the same x."""
        got = pdf_geometry.bar_boundaries(self.STAVES, self.STROKES)
        self.assertEqual(len(got), 4)


@unittest.skipIf(pdfplumber is None, "pdfplumber not installed")
class ChordSymbolTest(unittest.TestCase):
    """Nine chord symbols, in two rows above the two systems."""

    @classmethod
    def setUpClass(cls):
        cls.pdf = pdfplumber.open(FIXTURE)
        cls.page = cls.pdf.pages[0]
        cls.rows = pdf_geometry.chord_symbols(cls.page,
                                              pdf_geometry.systems(cls.page))

    @classmethod
    def tearDownClass(cls):
        cls.pdf.close()

    def test_reads_every_chord_symbol_in_printed_order(self):
        self.assertEqual([[sym for _x, sym in row] for row in self.rows],
                         [["C", "F", "G", "Am"],
                          ["Dm", "E7", "C", "G/B", "Fsus2"]])

    def test_reports_the_x_each_symbol_starts_at(self):
        for got, want in zip([x for x, _s in self.rows[1]],
                             [67.4, 258.3, 317.6, 378.1, 462.7]):
            self.assertAlmostEqual(got, want, delta=1.0)

    def test_lyrics_are_not_read_as_chords(self):
        """MuseScore sets chord symbols and lyrics in one font at one size.

        Only position separates them, so a font test - which works on Sibelius
        output, where chords have their own font - is not enough in general.
        """
        symbols = [sym for row in self.rows for _x, sym in row]
        for lyric in ("a", "and", "the", "go", "down", "tree"):
            self.assertNotIn(lyric, symbols)

    def test_a_measure_number_in_the_chord_band_is_not_read_as_a_chord(self):
        """The '3' above system 2 sits in the same band as its chords."""
        self.assertNotIn("3", [sym for row in self.rows for _x, sym in row])

    def test_part_names_are_not_read_as_chords(self):
        symbols = [sym for row in self.rows for _x, sym in row]
        self.assertNotIn("Voice", symbols)
        self.assertNotIn("Piano", symbols)


@unittest.skipIf(pdfplumber is None, "pdfplumber not installed")
class NoteColumnTest(unittest.TestCase):
    """Every rhythmic position in a system, as an x column."""

    @classmethod
    def setUpClass(cls):
        cls.pdf = pdfplumber.open(FIXTURE)
        cls.page = cls.pdf.pages[0]
        cls.systems = pdf_geometry.systems(cls.page)

    @classmethod
    def tearDownClass(cls):
        cls.pdf.close()

    def columns(self, index):
        return pdf_geometry.note_columns(self.page, self.systems[index])

    def test_a_column_is_shared_by_every_staff_playing_together(self):
        """Voice and piano are in rhythmic unison, so they share columns.

        Eight eighths in bar 1 give eight columns, not sixteen or twenty-four.
        """
        bars = self.systems[0].barlines
        inside = [x for x in self.columns(0) if bars[1] <= x < bars[2]]
        self.assertEqual(len(inside), 8)

    def test_finds_the_whole_note_bar_as_one_column(self):
        bars = self.systems[0].barlines
        inside = [x for x in self.columns(0) if bars[2] <= x < bars[3]]
        self.assertEqual(len(inside), 1)
        self.assertAlmostEqual(inside[0], 442.4, delta=1.0)

    def test_the_first_bar_of_a_system_includes_its_clef_and_time_signature(self):
        """Not a defect - the caller reconciles the count against the score.

        Clef, key and time signature are music glyphs at their own x, so the
        opening bar of a system reports more columns than it has notes. Recording
        the fact here because the placement code depends on it.
        """
        bars = self.systems[0].barlines
        inside = [x for x in self.columns(0) if bars[0] <= x < bars[1]]
        self.assertEqual(len(inside), 3)      # clef, time signature, one note
        self.assertAlmostEqual(inside[-1], 121.0, delta=1.0)

    def test_lyrics_and_chord_symbols_are_not_columns(self):
        """Only Private Use Area glyphs count, so text cannot land in the list."""
        bars = self.systems[1].barlines
        inside = [x for x in self.columns(1) if bars[3] <= x < bars[4]]
        self.assertEqual(len(inside), 1)      # the whole note, not its long lyric


class BarIndexTest(unittest.TestCase):
    """Which bar a chord symbol belongs to, given the bar boundaries."""

    BARS = [43.0, 204.9, 311.4, 466.2, 547.9]

    def test_a_chord_after_a_barline_is_in_the_bar_it_opens(self):
        self.assertEqual(pdf_geometry.bar_index(318.0, self.BARS), 2)

    def test_a_chord_mid_bar_stays_in_that_bar(self):
        self.assertEqual(pdf_geometry.bar_index(383.9, self.BARS), 2)

    def test_a_wide_chord_overhanging_its_barline_belongs_to_the_next_bar(self):
        """'Fsus2' is set 3.5pt left of the barline of the bar it belongs to.

        Chord symbols are left-aligned to their note, so a wide one can start
        before the barline. Measured on the real chart: the worst overhang is
        0.24pt while the nearest genuine mid-bar chord is 63pt from a barline, so
        the two cases do not come close to overlapping.
        """
        self.assertEqual(pdf_geometry.bar_index(462.7, self.BARS), 3)

    def test_a_chord_before_the_system_starts_lands_in_the_first_bar(self):
        self.assertEqual(pdf_geometry.bar_index(40.0, self.BARS), 0)

    def test_a_chord_past_the_final_barline_lands_in_the_last_bar(self):
        self.assertEqual(pdf_geometry.bar_index(600.0, self.BARS), 3)


if __name__ == "__main__":
    unittest.main()
