#!/usr/bin/env python3
"""Place chord symbols from a born-digital PDF into an OMR MusicXML score.

OMR loses most chord symbols: Tesseract misreads a digit, Audiveris cannot parse
the result as a chord name and demotes it to plain text, and the symbol vanishes
from the harmony data. On a real 6-page chart only 16 of 67 survived.

The PDF has all of them, exactly, and it also has the engraving: staff lines and
barlines as vector strokes, noteheads as glyphs at known coordinates. So the bar a
chord belongs to is not a guess. Reading `pdf_geometry`:

1. Group staff lines into staves, and staves into systems, joining two staves when
   a barline crosses the gap between them.
2. Take each system's real bar boundaries from its barlines.
3. Read the chord symbols out of the band above each system.
4. Assign each chord to the bar its x falls in, and to a beat by matching the
   bar's note columns against that measure's onsets in the score.

Step 4 is exact whenever a bar's column count matches its onset count, which is
the normal case; a system's opening bar also carries clef, key and time signature
glyphs, and those are discounted by the difference. Where the counts cannot be
reconciled the beat is taken from the chord's proportional position across the
real bar and snapped to the nearest onset, and the count of each is reported.

Without pdfplumber the script falls back to `pdftotext -bbox` and the older method
of dividing a system into equal-width bars, which gets the bar right only when
chord symbols sit near the start of theirs. It says which route it took.

Usage:
    place_chords_from_pdf.py SCORE.pdf IN.xml OUT.xml [--dry-run]

Exit: 0 = chords placed (or dry run). 1 = no text layer, or layout mismatch.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf_geometry
from pdf_geometry import CHORD

# Chord symbols on one system land within this many points of each other.
ROW_TOL = 12.0
# How far below a chord row that system's own staves extend.
BAND_DEPTH = 90.0

KIND = {
    "sus2": "suspended-second", "sus4": "suspended-fourth",
    "m7": "minor-seventh", "m9": "minor-ninth", "m6": "minor-sixth",
    "maj7": "major-seventh", "maj9": "major-ninth",
    "m": "minor", "6": "major-sixth", "7": "dominant", "9": "dominant-ninth",
    "5": "power", "dim": "diminished", "aug": "augmented", "": "major",
}


def open_pdf(path: str):
    """A pdfplumber PDF, or None if pdfplumber cannot be reached.

    Homebrew's Python is externally managed and there is no pdfplumber formula, so
    the library usually lives in a venv rather than on the interpreter running this
    script. Rather than fail, hand off to an interpreter that has it.
    """
    try:
        import pdfplumber
        return pdfplumber.open(path)
    except ImportError:
        pass
    if os.environ.get("MUSIC_SKILLS_REEXEC"):
        return None
    for candidate in (os.path.expanduser("~/.venvs/music-skills/bin/python"),
                      os.environ.get("MUSIC_SKILLS_PYTHON")):
        if not candidate or not os.path.exists(candidate):
            continue
        probe = subprocess.run([candidate, "-c", "import pdfplumber"],
                               capture_output=True)
        if probe.returncode == 0:
            # execv replaces the process and discards whatever is still sitting in
            # stdout's buffer, so this has to be flushed or the hand-off is silent.
            print(f"note  re-running under {candidate} for pdfplumber", flush=True)
            os.environ["MUSIC_SKILLS_REEXEC"] = "1"
            os.execv(candidate, [candidate, os.path.abspath(__file__), *sys.argv[1:]])
    return None


def pdf_items(pdf: str) -> list[list[tuple[float, float, float, str]]]:
    """Per page: [(yMin, xMin, xMax, text)] from pdftotext -bbox."""
    try:
        out = subprocess.run(["pdftotext", "-bbox", pdf, "-"],
                             capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("FAIL  pdftotext not found -> brew install poppler")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"FAIL  pdftotext failed: {exc.stderr.strip()[:200]}")
    out = re.sub(r'\sxmlns="[^"]+"', "", out, count=1)
    root = ET.fromstring(out)
    pages = []
    for pg in root.iter("page"):
        items = []
        for w in pg.iter("word"):
            t = (w.text or "").strip()
            if t:
                items.append((float(w.get("yMin", 0)), float(w.get("xMin", 0)),
                              float(w.get("xMax", 0)), t))
        pages.append(items)
    return pages


def onsets_of(meas: ET.Element) -> list[tuple[int, int]]:
    """Where each distinct note onset starts, and its index among the children.

    <chord> notes share the previous onset. A <backup> ends the pass, because what
    follows restarts the bar for another voice or staff.
    """
    out: list[tuple[int, int]] = []
    clock = 0
    for i, child in enumerate(list(meas)):
        if child.tag == "note":
            if child.find("chord") is None:
                out.append((clock, i))
                dur = child.findtext("duration")
                clock += int(dur) if dur and dur.isdigit() else 0
        elif child.tag == "backup":
            break
    return out or [(0, len(list(meas)))]


def union_onsets(root: ET.Element) -> dict[str, list[int]]:
    """{measure number: every rhythmic position in it, across all parts}.

    A chord symbol is engraved above whichever note sounds at that moment, in any
    staff, so this is the list the PDF's note columns have to be compared against.
    Counting only the top part's onsets makes them disagree wherever the voice
    rests and the piano plays - and worse, where the two counts coincide anyway the
    chord gets mapped to the wrong column with full confidence. That put the G in
    bar 13 of the test chart on beat 2 instead of beat 3.
    """
    out: dict[str, set[int]] = {}
    for part in root.findall("part"):
        for meas in part.findall("measure"):
            found = out.setdefault(meas.get("number"), set())
            clock = 0
            for child in list(meas):
                dur = child.findtext("duration")
                length = int(dur) if dur and dur.isdigit() else 0
                if child.tag == "note":
                    # A <chord> note sounds with the one before it, not after.
                    if child.find("chord") is None:
                        found.add(clock)
                        clock += length
                elif child.tag == "backup":
                    clock -= length
                elif child.tag == "forward":
                    clock += length
    return {n: sorted(v) for n, v in out.items()}


def bar_length(meas: ET.Element) -> int:
    """Total divisions in a bar, from its own notes."""
    clock = 0
    for child in list(meas):
        if child.tag == "note" and child.find("chord") is None:
            dur = child.findtext("duration")
            clock += int(dur) if dur and dur.isdigit() else 0
        elif child.tag == "backup":
            break
    return clock or 1


def score_layout(xml: str) -> tuple[dict[int, list[list[str]]], ET.ElementTree]:
    """{page number: [[measure numbers per system], ...]} from print markers."""
    tree = ET.parse(xml)
    part = tree.getroot().find("part")
    if part is None:
        sys.exit("FAIL  no <part> in the score")
    nums, new_page, new_sys = [], [], []
    for m in part.findall("measure"):
        n = m.get("number")
        nums.append(n)
        pr = m.find("print")
        if pr is not None:
            if pr.get("new-page") == "yes":
                new_page.append(n)
            if pr.get("new-system") == "yes":
                new_sys.append(n)

    starts = [nums[0]] + new_page
    sys_starts = set(new_sys) | {nums[0]} | set(new_page)
    layout: dict[int, list[list[str]]] = {}
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else None
        chunk = nums[nums.index(s): (nums.index(end) if end else len(nums))]
        systems: list[list[str]] = []
        for m in chunk:
            if m in sys_starts or not systems:
                systems.append([m])
            else:
                systems[-1].append(m)
        layout[i + 1] = systems
    return layout, tree


def place_by_geometry(doc, layout, measures, onsets):
    """Chord placements read from the engraving. Returns (placements, notes)."""
    placements: dict[str, list[tuple[float, str, float]]] = {}
    notes, exact, approx = [], 0, 0

    for pno, score_systems in layout.items():
        if pno > len(doc.pages):
            notes.append(f"score page {pno} has no matching PDF page")
            continue
        page = doc.pages[pno - 1]
        found = pdf_geometry.systems(page)
        if len(found) != len(score_systems):
            notes.append(f"page {pno}: PDF shows {len(found)} system(s), the score "
                         f"says {len(score_systems)}; page left to the fallback")
            continue
        rows = pdf_geometry.chord_symbols(page, found)
        for system, mlist, row in zip(found, score_systems, rows):
            if len(system.barlines) - 1 != len(mlist):
                notes.append(f"page {pno}: a system has {len(system.barlines) - 1} "
                             f"bar(s) in the PDF and {len(mlist)} in the score; "
                             f"its chords are placed proportionally")
            columns = pdf_geometry.note_columns(page, system)
            for x, sym in row:
                b = pdf_geometry.bar_index(x, system.barlines)
                if b >= len(mlist):
                    continue
                number = mlist[b]
                left, right = system.barlines[b], system.barlines[b + 1]
                inside = [c for c in columns if left <= c < right]
                ons = onsets.get(number, [])
                # A system's opening bar also holds clef, key and time signature
                # glyphs, always to the left of its first note.
                if b == 0 and len(inside) > len(ons):
                    inside = inside[len(inside) - len(ons):]
                if ons and len(inside) == len(ons):
                    # The chord is engraved above its note, so the column nearest
                    # it is the rhythmic position it belongs to.
                    nearest = min(range(len(inside)),
                                  key=lambda i: abs(inside[i] - x))
                    division = float(ons[nearest])
                    exact += 1
                else:
                    # Engraved spacing is not proportional, so this is a estimate;
                    # it still snaps to a real onset on the way in.
                    span = (right - left) or 1.0
                    frac = min(max((x - left) / span, 0.0), 0.999)
                    division = frac * bar_length(measures[number])
                    approx += 1
                placements.setdefault(number, []).append((x, sym, division))

    notes.append(f"beat placement: {exact} exact from note columns, "
                 f"{approx} proportional")
    return placements, notes


def place_by_text_layer(pdf: str, layout, measures):
    """Fallback: chord rows from the text layer, bars assumed equal width.

    Kept for PDFs where the vector geometry cannot be read. It gets the bar right
    only because chord symbols tend to sit near the start of theirs; bars are not
    equal width, and lyrics overhanging the final barline inflate the extent.
    """
    pages = pdf_items(pdf)
    if not any(pages):
        return None, ["no text layer: this is a scanned PDF, so the chord symbols "
                      "are not recoverable this way."]
    placements: dict[str, list[tuple[float, str, float]]] = {}
    notes = ["route: pdftotext, equal-width bars (beat placement approximate)"]

    for pno, systems in layout.items():
        if pno > len(pages):
            notes.append(f"score page {pno} has no matching PDF page")
            continue
        items = pages[pno - 1]
        chords = [(y, x0, t) for y, x0, _x1, t in items if CHORD.match(t)]
        if not chords:
            continue

        rows: list[list[tuple[float, float, str]]] = []
        for y, x0, sym in sorted(chords):
            if rows and y - rows[-1][0][0] <= ROW_TOL:
                rows[-1].append((y, x0, sym))
            else:
                rows.append([(y, x0, sym)])

        # A system with no chords at all would shift every later row up by one, so
        # walk the rows and skip ahead when the vertical step doubles.
        tops = [r[0][0] for r in rows]
        steps = [b - a for a, b in zip(tops, tops[1:])]
        unit = min(steps) if steps else 0
        idx, indices = 0, []
        for i in range(len(rows)):
            if i:
                idx += max(1, round(steps[i - 1] / unit)) if unit else 1
            indices.append(idx)
        if indices and indices[-1] >= len(systems):
            notes.append(f"page {pno}: {len(rows)} chord row(s) do not fit "
                         f"{len(systems)} system(s); chords left unplaced")
            continue

        for row, sidx in zip(rows, indices):
            row = sorted(row, key=lambda r: r[1])
            mlist = systems[sidx]
            band = [(a, b) for yy, a, b, _t in items
                    if row[0][0] - 6 <= yy <= row[0][0] + BAND_DEPTH]
            if not band:
                continue
            left = min(a for a, _ in band)
            right = max(b for _, b in band)
            span = (right - left) / len(mlist)
            for _y, x0, sym in row:
                k = max(0, min(int((x0 - left) / span), len(mlist) - 1))
                frac = (x0 - (left + k * span)) / span
                frac = min(max(frac, 0.0), 0.999)
                number = mlist[k]
                placements.setdefault(number, []).append(
                    (x0, sym, frac * bar_length(measures[number])))
    return placements, notes


def harmony(symbol: str) -> ET.Element | None:
    mo = re.fullmatch(r"([A-G][#b]?)(.*?)(?:/([A-G][#b]?))?$", symbol)
    if not mo:
        return None
    step, qual, bass = mo.group(1), (mo.group(2) or ""), mo.group(3)
    h = ET.Element("harmony"); h.set("print-frame", "no")
    rt = ET.SubElement(h, "root")
    ET.SubElement(rt, "root-step").text = step[0]
    if len(step) > 1:
        ET.SubElement(rt, "root-alter").text = "1" if step[1] == "#" else "-1"
    k = ET.SubElement(h, "kind")
    k.text = KIND.get(qual, "other")
    k.set("text", qual)
    if bass:
        b = ET.SubElement(h, "bass")
        ET.SubElement(b, "bass-step").text = bass[0]
        if len(bass) > 1:
            ET.SubElement(b, "bass-alter").text = "1" if bass[1] == "#" else "-1"
    return h


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 3:
        sys.exit(__doc__)
    pdf, src, dst = args[0], args[1], args[2]
    dry = "--dry-run" in args

    layout, tree = score_layout(src)
    part = tree.getroot().find("part")
    measures = {m.get("number"): m for m in part.findall("measure")}

    doc = open_pdf(pdf)
    if doc is not None:
        print("route: pdfplumber, real barlines from the engraving")
        placements, notes = place_by_geometry(doc, layout, measures,
                                              union_onsets(tree.getroot()))
        doc.close()
    else:
        print("note  pdfplumber unavailable -> falling back to pdftotext")
        placements, notes = place_by_text_layer(pdf, layout, measures)
    if placements is None:
        for note in notes:
            print(note)
        return 1

    for m in placements:
        placements[m] = sorted(placements[m])

    total = sum(len(v) for v in placements.values())
    print(f"placed {total} chord symbol(s) across {len(placements)} bar(s)")
    for note in notes:
        print(f"  {note}")

    for m in sorted(placements, key=lambda s: int(re.sub(r"\D", "", s) or 0)):
        print(f"   m{m}: {' '.join(s for _x, s, _d in placements[m])}")

    if dry:
        print("dry run: nothing written")
        return 0

    # Replace existing harmony wholesale - the PDF is complete and exact, so
    # merging with OMR's partial guesses would only reintroduce its errors. Clear
    # harmony from EVERY part, not just the first: a chord left behind in a lower
    # part renders a second time above its own staff.
    replaced = 0
    for anypart in tree.getroot().findall("part"):
        for meas in anypart.findall("measure"):
            for h in list(meas.findall("harmony")):
                meas.remove(h); replaced += 1

    # Chord symbols belong to the top part only.
    for meas in part.findall("measure"):
        syms = placements.get(meas.get("number"))
        if not syms:
            continue
        onsets = onsets_of(meas)
        # MuseScore ignores <offset> on harmony - verified - so a chord has to be
        # interleaved between notes to sit later in the bar. Insert from the back
        # so earlier indices stay valid.
        for _x, sym, division in sorted(syms, key=lambda s: s[2], reverse=True):
            h = harmony(sym)
            if h is None:
                continue
            _t, idx = min(onsets, key=lambda o: abs(o[0] - division))
            meas.insert(idx, h)

    tree.write(dst, encoding="UTF-8", xml_declaration=True)
    print(f"removed {replaced} OMR harmony element(s), wrote {total} from the PDF")
    print(f"wrote      {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
