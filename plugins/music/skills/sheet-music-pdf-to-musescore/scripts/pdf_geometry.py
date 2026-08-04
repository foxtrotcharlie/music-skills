"""Read the geometry of a born-digital score PDF: staves, systems, barlines,
note columns and chord symbols.

A born-digital score is already a structured document. Staff lines and barlines
are vector strokes, noteheads are glyphs at known coordinates, and chord symbols
are text. Rasterising it for OMR throws all of that away and then guesses it back
from pixels. This module reads it instead.

The discriminators here were each verified against two PDFs engraved by different
programs - Sibelius (Opus fonts) and MuseScore (Leland) - because every one of
them is a claim about engraving in general, not about one file:

* A staff is five equally spaced hairline horizontal strokes. MuseScore breaks
  each line at every barline and Sibelius draws it whole, so segments at the same
  y must be merged before grouping.
* A barline is a vertical stroke aligned to a staff's top and bottom lines that
  also crosses *every* staff in its system. Alignment alone is not enough: a note
  stem is the same width and weight, and five stems on the test chart run the
  exact height of their staff. Crossing the whole system is what rejects them.
* Staves belong to the same system when a barline runs continuously across the
  gap between them. Vertical proximity does not work: in the test score the gap
  between systems is 46.6pt and the gap between a vocal staff and the piano below
  it is 42.0pt, and no threshold splits those reliably.
* Music glyphs live in the Unicode Private Use Area - SMuFL fonts from U+E000,
  older fonts like Opus from U+F000 - so noteheads are separable from lyrics and
  chord symbols without knowing which font the engraver used.
* A chord symbol is text above a system's top staff line. Font cannot identify
  one in general: Sibelius gives chord symbols their own font, but MuseScore sets
  them in the lyric font at the lyric size, so only position separates the two.

All coordinates are pdfplumber's: x from the left edge, `top` down from the top
edge, both in points.
"""

from __future__ import annotations

import re
from collections import namedtuple

# tops: the five line positions, top to bottom. x0/x1: full horizontal extent.
Staff = namedtuple("Staff", "tops x0 x1")
# barlines: bar boundary x positions, left to right, including both system ends.
System = namedtuple("System", "staves x0 x1 barlines")

# A staff line and a barline are both hairlines; anything thicker is a beam or a
# bracket.
HAIRLINE = 1.5
# Shortest horizontal stroke still worth considering as part of a staff. Low,
# because MuseScore splits a staff line at every barline and a narrow bar's
# segment is short. False positives are filtered by the five-equal-gaps test.
MIN_SEGMENT = 20.0
# Two strokes this close together are the same line drawn twice, or a double or
# light-heavy barline pair. Measured: 2.3pt in Sibelius, 3.7pt in MuseScore.
SAME_LINE = 4.0
# Slack when matching a stroke end to a staff line, in points. Tight on purpose:
# a stem on a note centred on the bottom line can reach almost exactly to the top
# line and then reads as a barline, inventing a bar boundary. Measured alignment
# error for real barlines is 0.0pt in Sibelius and 0.3pt in MuseScore, while the
# nearest offending stem in the fixture misses by 1.2pt.
SNAP = 0.75
# Note columns closer than this are the same rhythmic position on two staves.
COLUMN_TOL = 3.0
# How far a chord symbol may start to the left of its own barline. Chord symbols
# are left-aligned to their note and a wide one overhangs. Measured on the test
# chart: the worst overhang is 0.24pt, the closest genuine mid-bar chord 62.9pt.
OVERHANG = 6.0
# Chord symbols on one system are set at a common height; this is how much they
# may vary and still count as the same row.
ROW_TOL = 6.0

CHORD = re.compile(
    r"^[A-G][#b♯♭]?"
    r"(?:maj|min|m|M|dim|aug|sus|add|alt|°|\+)?"
    r"\d{0,2}"
    r"(?:(?:maj|sus|add|no|b|\#)\d{1,2})?"
    r"(?:/[A-G][#b♯♭]?)?$"
)


def is_music_glyph(text: str) -> bool:
    """True for a single Private Use Area character, i.e. a music symbol.

    SMuFL fonts (Bravura, Leland) start at U+E000; Sibelius's Opus and Finale's
    Maestro use U+F000 upward. Nothing else in a score is set in the PUA, so this
    identifies music glyphs without a per-engraver font table.
    """
    return len(text) == 1 and 0xE000 <= ord(text) <= 0xF8FF


def _horizontal_rows(page) -> list[tuple[float, float, float]]:
    """Hairline horizontal strokes as (top, x0, x1), merged by y, top-down."""
    rows: list[list[float]] = []
    found = [l for l in page.lines
             if l["height"] <= HAIRLINE and l["width"] >= MIN_SEGMENT]
    for line in sorted(found, key=lambda l: l["top"]):
        if rows and line["top"] - rows[-1][0] <= SAME_LINE / 4:
            rows[-1][1] = min(rows[-1][1], line["x0"])
            rows[-1][2] = max(rows[-1][2], line["x1"])
        else:
            rows.append([line["top"], line["x0"], line["x1"]])
    return [(t, a, b) for t, a, b in rows]


def _vertical_strokes(page) -> list[tuple[float, float, float]]:
    """Hairline vertical strokes as (x, top, bottom), collinear runs merged.

    Merging matters: a barline crossing a grand staff is emitted as one segment
    per staff, and only the merged run reveals that it spans the whole system.
    """
    found = [l for l in page.lines if l["width"] <= HAIRLINE and l["height"] > 2]
    by_x: list[list] = []
    for line in sorted(found, key=lambda l: (l["x0"], l["top"])):
        if by_x and line["x0"] - by_x[-1][0]["x0"] <= SAME_LINE / 4:
            by_x[-1].append(line)
        else:
            by_x.append([line])
    out = []
    for column in by_x:
        runs: list[list[float]] = []
        for line in sorted(column, key=lambda l: l["top"]):
            if runs and line["top"] <= runs[-1][2] + 0.5:
                runs[-1][2] = max(runs[-1][2], line["bottom"])
            else:
                runs.append([line["x0"], line["top"], line["bottom"]])
        out.extend((x, t, b) for x, t, b in runs)
    return sorted(out)


def staves(page) -> list[Staff]:
    """Every staff on the page, top to bottom."""
    rows = _horizontal_rows(page)
    out, i = [], 0
    while i + 5 <= len(rows):
        window = rows[i:i + 5]
        gaps = [window[j + 1][0] - window[j][0] for j in range(4)]
        mean = sum(gaps) / 4
        # Five lines, evenly spaced. Rejects hairpins, ledger lines and the odd
        # stray rule without needing to know the staff size in advance.
        if mean > 0 and all(abs(g - mean) <= 0.2 * mean for g in gaps):
            out.append(Staff([w[0] for w in window],
                             min(w[1] for w in window),
                             max(w[2] for w in window)))
            i += 5
        else:
            i += 1
    return out


def _barline_strokes(page, staff_list: list[Staff]) -> list[tuple[float, float, float]]:
    """Vertical strokes that start on a staff's top line and end on a bottom one.

    Candidates only - some are note stems that happen to span their staff. They
    are separated in bar_boundaries, which can see the whole system.
    """
    tops = [s.tops[0] for s in staff_list]
    bottoms = [s.tops[-1] for s in staff_list]
    return [(x, t, b) for x, t, b in _vertical_strokes(page)
            if any(abs(t - v) <= SNAP for v in tops)
            and any(abs(b - v) <= SNAP for v in bottoms)]


def bar_boundaries(group: list[Staff],
                   strokes: list[tuple[float, float, float]]) -> list[float]:
    """Bar boundary x positions for one system, left to right.

    Given staff-aligned candidate strokes, keep the x positions where the strokes
    cross *every* staff in the system. A barline always does, whether drawn as one
    stroke down the whole system or as a separate stroke per staff - engravers
    break the barline between a vocal staff and the piano below it. A note stem
    that happens to run the exact height of its staff passes the alignment test on
    its own but crosses only that one staff, and this is what rejects it. Five
    such stems survive alignment on the six-page test chart.

    The remaining blind spot is a single-staff system, a lead sheet, where there
    are no other staves to cross and only the alignment tolerance stands between a
    full-height stem and a phantom bar.
    """
    clusters: list[list[tuple[float, float, float]]] = []
    for stroke in sorted(strokes):
        if clusters and stroke[0] - clusters[-1][0][0] <= SAME_LINE:
            clusters[-1].append(stroke)
        else:
            clusters.append([stroke])
    out = []
    for cluster in clusters:
        if all(any(t <= staff.tops[0] + SNAP and b >= staff.tops[-1] - SNAP
                   for _x, t, b in cluster)
               for staff in group):
            # A double or light-heavy barline is two strokes; the bar ends at the
            # leftmost of them.
            out.append(min(x for x, _t, _b in cluster))
    return out


def systems(page) -> list[System]:
    """Staves grouped into systems, each with its bar boundaries."""
    staff_list = staves(page)
    if not staff_list:
        return []
    bars = _barline_strokes(page, staff_list)

    groups = [[staff_list[0]]]
    for above, below in zip(staff_list, staff_list[1:]):
        bridged = any(t <= above.tops[-1] + SNAP and b >= below.tops[0] - SNAP
                      for _x, t, b in bars)
        if bridged:
            groups[-1].append(below)
        else:
            groups.append([below])

    out = []
    for group in groups:
        top, bottom = group[0].tops[0], group[-1].tops[-1]
        inside = [s for s in bars if s[1] >= top - SNAP and s[2] <= bottom + SNAP]
        out.append(System(group,
                          min(s.x0 for s in group),
                          max(s.x1 for s in group),
                          bar_boundaries(group, inside)))
    return out


def note_columns(page, system: System) -> list[float]:
    """The x of every rhythmic column in a system, left to right.

    A column is a cluster of music glyphs sharing an x. Staves playing together
    share one column, which is what makes these comparable with the score's own
    note onsets.

    Two things are deliberately left in. Ledger-line notes above or below a staff
    are kept, by taking the y band from the top staff's top line to the bottom
    staff's bottom line with a staff-height of margin either side. And the clef,
    key and time signature of a system's opening bar are kept, because separating
    them from noteheads needs a per-engraver glyph table - Opus is not SMuFL - and
    guessing a codepoint wrong drops a real onset. The caller compares each bar's
    column count against the score instead, which needs no such table.
    """
    if not system.staves:
        return []
    margin = system.staves[0].tops[-1] - system.staves[0].tops[0]
    top = system.staves[0].tops[0] - margin
    bottom = system.staves[-1].tops[-1] + margin
    xs = sorted(c["x0"] for c in page.chars
                if is_music_glyph(c.get("text") or "")
                and top <= c["top"] <= bottom
                and system.x0 - SNAP <= c["x0"] <= system.x1)
    out: list[float] = []
    for x in xs:
        if not out or x - out[-1] > COLUMN_TOL:
            out.append(x)
    return out


def bar_index(x: float, barlines: list[float]) -> int:
    """Which bar of a system a symbol at x sits in, counting from zero.

    A chord symbol is left-aligned to its note, so a wide one - 'Fsus2', 'Fmaj9' -
    can start a fraction before the barline of the bar it belongs to. Anything
    within OVERHANG of the next barline is read as belonging past it.
    """
    bars = max(len(barlines) - 1, 1)
    for i in range(bars):
        if x < barlines[i + 1] - OVERHANG:
            return i
    return bars - 1


def chord_symbols(page, system_list: list[System]) -> list[list[tuple[float, str]]]:
    """Chord symbols above each system, as (x0, text), left to right.

    A chord symbol is text, not a music glyph, sitting in the gap above a system's
    top staff line and within the staff's horizontal extent. Two further filters
    earn their place:

    * The chord row is the row of candidates *closest* to the staff. Above it can
      sit a tempo mark or a rehearsal letter, and below it the lyrics of the system
      before, when that score hangs lyrics under its bottom staff.
    * The text still has to look like a chord. Position alone lets a measure number
      through, because engravers set those in the same gap - the fixture's '3' sits
      15.7pt above the staff its chords sit 19.7pt above.
    """
    rows = []
    ceilings = [0.0] + [s.staves[-1].tops[-1] for s in system_list]
    for system, ceiling in zip(system_list, ceilings):
        floor = system.staves[0].tops[0]
        found = [w for w in page.extract_words()
                 if ceiling < w["bottom"] <= floor
                 and system.x0 - SNAP <= w["x0"] <= system.x1
                 and not any(is_music_glyph(ch) for ch in w["text"])
                 and CHORD.match(w["text"])]
        if found:
            nearest = max(w["bottom"] for w in found)
            found = [w for w in found if w["bottom"] >= nearest - ROW_TOL]
        rows.append(sorted((w["x0"], w["text"]) for w in found))
    return rows
