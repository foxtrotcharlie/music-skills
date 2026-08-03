#!/usr/bin/env python3
"""Extract chord symbols from a born-digital score PDF's text layer.

OMR rasterises the page and OCRs it, which throws away perfect text when the
PDF is born-digital. Tesseract then confuses digits for letters - observed
turning "Fsus2" into "FsusZ" in ~40% of instances on a commercial chart - and
Audiveris demotes any chord name it cannot parse to a plain text annotation, so
the chord silently disappears from the harmony data.

Reading the text layer sidesteps that entirely: exact chord names, in order.

Usage:
    chords_from_pdf.py SCORE.pdf                 # ground-truth chord list
    chords_from_pdf.py SCORE.pdf --compare S.xml # what OMR lost

Exit: 0 = chords found. 1 = no text layer (scanned PDF), or none matched.
"""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter

# Root, optional accidental, optional quality/extension, optional slash bass.
# Deliberately strict: a loose pattern swallows lyrics.
CHORD = re.compile(
    r"^[A-G][#b♯♭]?"
    r"(?:maj|min|m|M|dim|aug|sus|add|alt|°|\+)?"
    r"\d{0,2}"
    r"(?:(?:maj|sus|add|no|b|\#)\d{1,2})?"
    r"(?:/[A-G][#b♯♭]?)?$"
)


def words_by_page(pdf: str) -> list[list[tuple[float, float, str]]]:
    """Return per-page [(y, x, text)] from pdftotext -bbox."""
    try:
        xml = subprocess.run(
            ["pdftotext", "-bbox", pdf, "-"],
            capture_output=True, text=True, check=True,
        ).stdout
    except FileNotFoundError:
        sys.exit("FAIL  pdftotext not found -> brew install poppler")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"FAIL  pdftotext failed: {exc.stderr.strip()[:200]}")

    # Strip the XHTML namespace so find/iter stay readable.
    xml = re.sub(r'\sxmlns="[^"]+"', "", xml, count=1)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        sys.exit(f"FAIL  could not parse pdftotext output: {exc}")

    pages = []
    for page in root.iter("page"):
        got = []
        for w in page.iter("word"):
            if w.text and w.text.strip():
                got.append((float(w.get("yMin", 0)), float(w.get("xMin", 0)), w.text.strip()))
        pages.append(got)
    return pages


def rows(items: list[tuple[float, float, str]], tol: float = 6.0):
    """Group words into visual rows, then order left-to-right within each."""
    out, cur, last_y = [], [], None
    for y, x, t in sorted(items):
        if last_y is None or abs(y - last_y) <= tol:
            cur.append((x, t))
        else:
            out.append(sorted(cur))
            cur = [(x, t)]
        last_y = y if last_y is None else last_y if abs(y - last_y) <= tol else y
    if cur:
        out.append(sorted(cur))
    return out


def omr_chords(path: str) -> list[str]:
    """Chord symbols Audiveris actually exported, as printed-style strings."""
    r = ET.parse(path).getroot()
    KIND = {
        "major": "", "minor": "m", "dominant": "7", "major-seventh": "maj7",
        "minor-seventh": "m7", "major-sixth": "6", "minor-sixth": "m6",
        "dominant-ninth": "9", "major-ninth": "maj9", "minor-ninth": "m9",
        "suspended-second": "sus2", "suspended-fourth": "sus4",
        "diminished": "dim", "augmented": "aug", "power": "5",
    }
    out = []
    for h in r.iter("harmony"):
        root = h.find("root")
        if root is None:
            continue
        step = root.findtext("root-step", "?")
        alter = root.findtext("root-alter")
        acc = {"1": "#", "-1": "b"}.get(alter or "", "")
        kind_el = h.find("kind")
        kind = ""
        if kind_el is not None:
            kind = kind_el.get("text") or KIND.get(kind_el.text or "", kind_el.text or "")
        bass = h.find("bass")
        slash = ""
        if bass is not None:
            slash = "/" + (bass.findtext("bass-step") or "?")
        out.append(f"{step}{acc}{kind}{slash}")
    return out


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pdf = sys.argv[1]
    compare = None
    if "--compare" in sys.argv:
        i = sys.argv.index("--compare")
        if i + 1 >= len(sys.argv):
            sys.exit("FAIL  --compare needs a MusicXML path")
        compare = sys.argv[i + 1]

    pages = words_by_page(pdf)
    total_words = sum(len(p) for p in pages)
    if total_words == 0:
        print("no text layer: this is a scanned PDF, so OMR's OCR is the only route.")
        print("Watch for digit/letter confusion in chord names (2 as Z, 0 as O, 5 as S)")
        print("- Audiveris demotes an unparseable chord name to plain text and the")
        print("  chord vanishes from the harmony data.")
        return 1

    found: list[str] = []
    for n, page in enumerate(pages, 1):
        page_syms = []
        for row in rows(page):
            for _x, text in row:
                if CHORD.match(text):
                    page_syms.append(text)
        if page_syms:
            print(f"page {n}  ({len(page_syms)})  {' '.join(page_syms)}")
        found.extend(page_syms)

    print(f"\ntotal {len(found)} chord symbols in the PDF text layer")
    tally = Counter(found)
    print("distinct:", ", ".join(f"{k}x{v}" for k, v in tally.most_common()))

    if not found:
        print("\nnone matched the chord grammar - if the score clearly has chord")
        print("symbols, they may be drawn as graphics rather than text.")
        return 1

    if compare:
        got = omr_chords(compare)
        gt, om = Counter(found), Counter(got)
        print(f"\n=== OMR vs PDF ===")
        print(f"PDF text layer: {len(found)}    OMR exported: {len(got)}")
        missing = gt - om
        if missing:
            print("MISSING from OMR (re-enter these):")
            for k, v in missing.most_common():
                print(f"   {k} x{v}")
        extra = om - gt
        if extra:
            print("in OMR but NOT in the PDF text (suspect misreads):")
            for k, v in extra.most_common():
                print(f"   {k} x{v}")
        if not missing and not extra:
            print("chord symbols agree.")

    print("\nSingle uppercase letters are valid chords AND possible lyrics - eyeball")
    print("the per-page lists above before trusting the count.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
