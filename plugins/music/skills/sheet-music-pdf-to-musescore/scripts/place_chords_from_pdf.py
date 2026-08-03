#!/usr/bin/env python3
"""Place chord symbols from a born-digital PDF into an OMR MusicXML score.

OMR loses most chord symbols: Tesseract misreads a digit, Audiveris cannot parse
the result as a chord name and demotes it to plain text, and the symbol vanishes
from the harmony data. On a real 6-page chart only 16 of 67 survived.

The PDF text layer has all of them, exactly, with coordinates. The score has its
own layout in `<print new-page>` / `<print new-system>` markers. Together those
are enough to put every chord in the right bar:

1. Cluster the PDF's chord symbols into rows - one row per system.
2. Match each row to a system, skipping ahead where the vertical step between
   rows doubles, because a system with no chords at all would otherwise shift
   every later row up by one.
3. Split each system's x-extent by its number of bars, and assign each chord to
   the bar its x falls in.

Known limit: if the *first* system of a page carries no chords, the rows shift
up by one. The script reports a mismatch rather than guessing when the rows
cannot fit the systems.

Usage:
    place_chords_from_pdf.py SCORE.pdf IN.xml OUT.xml [--dry-run]

Exit: 0 = chords placed (or dry run). 1 = no text layer, or layout mismatch.
"""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET

CHORD = re.compile(
    r"^[A-G][#b♯♭]?"
    r"(?:maj|min|m|M|dim|aug|sus|add|alt|°|\+)?"
    r"\d{0,2}"
    r"(?:(?:maj|sus|add|no|b|\#)\d{1,2})?"
    r"(?:/[A-G][#b♯♭]?)?$"
)
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


def bands(ys: list[float], count: int) -> list[tuple[float, float]]:
    """Split y values into exactly `count` bands at the largest vertical gaps.

    A fixed gap threshold cannot work here: in a piano/vocal system the space
    between the vocal staff and the piano staves rivals the space between whole
    systems, so a threshold either merges systems or splits one into three.
    Since the score already states how many systems a page has, cut at the
    (count - 1) biggest gaps instead - deterministic, and no tuning.
    """
    ys = sorted(ys)
    if count <= 1 or len(ys) <= count:
        return [(ys[0], ys[-1])] if ys else []
    gaps = sorted(((ys[i + 1] - ys[i], i) for i in range(len(ys) - 1)),
                  reverse=True)[:count - 1]
    cuts = sorted(i for _g, i in gaps)
    out, start = [], 0
    for c in cuts:
        out.append((ys[start], ys[c]))
        start = c + 1
    out.append((ys[start], ys[-1]))
    return out


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

    pages = pdf_items(pdf)
    if not any(pages):
        print("no text layer: this is a scanned PDF, so the chord symbols are "
              "not recoverable this way.")
        return 1

    layout, tree = score_layout(src)
    placements: dict[str, list[str]] = {}
    mismatches = []

    for pno, systems in layout.items():
        if pno > len(pages):
            mismatches.append(f"score page {pno} has no matching PDF page")
            continue
        items = pages[pno - 1]
        chords = [(y, x0, t) for y, x0, _x1, t in items if CHORD.match(t)]
        if not chords:
            continue

        # Chord symbols sit in a horizontal row above each system, so cluster
        # them by y. This tracks the printed layout directly.
        rows: list[list[tuple[float, float, str]]] = []
        for y, x0, sym in sorted(chords):
            if rows and y - rows[-1][0][0] <= ROW_TOL:
                rows[-1].append((y, x0, sym))
            else:
                rows.append([(y, x0, sym)])

        # A system with no chords at all would shift every later row up by one,
        # so walk the rows and skip ahead when the vertical step doubles. The
        # smallest step between rows is one system.
        tops = [r[0][0] for r in rows]
        steps = [b - a for a, b in zip(tops, tops[1:])]
        unit = min(steps) if steps else 0
        idx, indices = 0, []
        for i in range(len(rows)):
            if i:
                idx += max(1, round(steps[i - 1] / unit)) if unit else 1
            indices.append(idx)
        if indices and indices[-1] >= len(systems):
            mismatches.append(
                f"page {pno}: {len(rows)} chord row(s) do not fit "
                f"{len(systems)} system(s); chords left unplaced")
            continue

        for row, sidx in zip(rows, indices):
            row = sorted(row, key=lambda r: r[1])
            mlist = systems[sidx]
            # Staff width for this system, from every item on its row band.
            band = [(a, b) for yy, a, b, _t in items
                    if row[0][0] - 6 <= yy <= row[0][0] + BAND_DEPTH]
            if not band:
                continue
            left = min(a for a, _ in band)
            right = max(b for _, b in band)
            span = (right - left) / len(mlist)
            for _y, x0, sym in row:
                k = max(0, min(int((x0 - left) / span), len(mlist) - 1))
                placements.setdefault(mlist[k], []).append((x0, sym))

    for m in placements:
        placements[m] = [s for _x, s in sorted(placements[m])]

    total = sum(len(v) for v in placements.values())
    print(f"placed {total} chord symbol(s) across {len(placements)} bar(s)")
    for mismatch in mismatches:
        print(f"  SKIPPED {mismatch}")

    for m in sorted(placements, key=lambda s: int(re.sub(r"\D", "", s) or 0)):
        print(f"   m{m}: {' '.join(placements[m])}")

    if dry:
        print("dry run: nothing written")
        return 0

    # Replace existing harmony wholesale - the text layer is complete and exact,
    # so merging with OMR's partial guesses would only reintroduce its errors.
    # Clear harmony from EVERY part, not just the first: a chord left behind in a
    # lower part renders a second time above its own staff.
    replaced = 0
    for anypart in tree.getroot().findall("part"):
        for meas in anypart.findall("measure"):
            for h in list(meas.findall("harmony")):
                meas.remove(h); replaced += 1
    # Chord symbols belong to the top part only.
    part = tree.getroot().find("part")
    for meas in part.findall("measure"):
        syms = placements.get(meas.get("number"))
        if not syms:
            continue
        at = 0
        for i, child in enumerate(list(meas)):
            if child.tag in ("print", "attributes"):
                at = i + 1
        for j, sym in enumerate(syms):
            h = harmony(sym)
            if h is not None:
                meas.insert(at + j, h)

    tree.write(dst, encoding="UTF-8", xml_declaration=True)
    print(f"removed {replaced} OMR harmony element(s), wrote {total} from the PDF")
    print(f"wrote      {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
