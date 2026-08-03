#!/usr/bin/env python3
"""Repair the OCR'd text of an Audiveris MusicXML export.

Audiveris exports page text in a shape MuseScore renders badly, and it does so
on every conversion:

* **Duplicate metadata.** Two `<creator type="composer">` elements and two
  `<rights>` elements anchor to the same spot, so the composer lines print on
  top of each other.
* **Untyped credits.** With no `type` attribute, MuseScore falls back to
  Audiveris's raw `default-x`/`default-y` - pixel values that mean nothing in
  MuseScore's coordinate system - so text lands arbitrarily and collides.
* **Junk credits.** Guitar fretboard grids become dozens of credits like
  `X 0 O`, `>O<`, `000`, `3fr`; chord symbols get misfiled as page credits;
  and any purchase or order line from the source PDF is carried along.
* **No title.** `<work-title>` is usually absent entirely.

Note that `<work-title>` and `<creator>` populate metadata only - they render
nothing. Visible text needs typed `<credit>` elements *with* positions, in
MusicXML tenths measured upward from the page bottom.

It works on two levels, both broken by the same cause - text recognised without
knowing what it means:

* **Page furniture** - the title block and footer (see above).
* **In-measure text** - fretboard markers land as `<words>` directions inside
  bars, and a chord name Tesseract misread (`FsusZ` for `Fsus2`) is demoted from
  a chord symbol to plain text, so it vanishes from the harmony data. Repairing
  the spelling and promoting it back to `<harmony>` recovers the chord *at the
  right bar*, because a direction carries a measure anchor that a credit does not.

Usage:
    clean_omr_text.py IN.xml OUT.xml [--title T] [--subtitle S] [--composer C]

Anything not supplied is inferred from the existing credits. Safe to re-run.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET

# Fretboard markers and OCR noise: only X/O/0/brackets/dashes, or a fret hint.
JUNK = re.compile(r"^[XxOo0()<>_|:—\-.,'“”i\s]+$|^\d+fr$|^I.?it\.$")
# Typographic quotes, pipes and underscores never occur in real tempo or
# expression text, so a fragment containing one is OCR debris. Matching on the
# character rather than on length keeps genuine short marks like `rit.` safe.
QUOTE_JUNK = re.compile(r"[“”‘’|_]")
# A bare chord symbol misfiled as a page credit.
CHORDISH = re.compile(r"^[A-G][#b]?\s?(sus|maj|min|m|add|dim|aug)?\d?\d?(/[A-G][#b]?)?$")
# Purchase / order provenance from the source PDF.
ORDER = re.compile(r"order\s*\d|copy purchased|sheetmusic|\binvoice\b", re.I)
COPYRIGHT = re.compile(r"©|\(c\)|copyright|rights|reserved|permission|administered|publishing", re.I)
# Deliberately short: a broad list would relocate real text into bar 1.
TEMPO = re.compile(
    r"^(slowly|slow|moderately|moderato|andante|adagio|allegro|allegretto|largo|"
    r"lento|vivace|presto|freely|ballad|with feeling|rubato)\b", re.I)


def text_of(credit: ET.Element) -> str:
    return " ".join((w.text or "") for w in credit.iter("credit-words")).strip()


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    src, dst = args[0], args[1]

    def opt(name: str) -> str | None:
        if name in args:
            i = args.index(name)
            if i + 1 >= len(args):
                sys.exit(f"FAIL  {name} needs a value")
            return args[i + 1]
        return None

    try:
        tree = ET.parse(src)
    except (ET.ParseError, OSError) as exc:
        sys.exit(f"FAIL  {src}: {exc}")
    root = tree.getroot()

    # --- page geometry: MusicXML y runs upward from the page bottom ----------
    page_h, page_w = 1553, 1200
    defaults = root.find("defaults")
    layout = defaults.find("page-layout") if defaults is not None else None
    if layout is not None:
        page_h = int(float(layout.findtext("page-height") or page_h))
        page_w = int(float(layout.findtext("page-width") or page_w))
    margin = 80
    centre, right = page_w // 2, page_w - margin

    # --- harvest existing text, then classify it ----------------------------
    credits = root.findall("credit")
    kept_titleish: list[tuple[int, str]] = []   # (font-size, text)
    copyright_bits: list[str] = []
    tempo_terms: list[str] = []
    # Credits this script has already typed on a previous run. Trusting them
    # keeps re-runs idempotent; without this the title (largest font) gets
    # re-consumed as the subtitle on a second pass.
    typed: dict[str, str] = {}
    dropped = {"junk": 0, "chord": 0, "order": 0}

    for c in credits:
        txt = text_of(c)
        if not txt:
            dropped["junk"] += 1
            continue
        ctype = c.get("type")
        if ctype in ("title", "subtitle", "composer", "rights"):
            typed.setdefault(ctype, txt)
            if ctype == "rights":
                copyright_bits.append(txt)
            continue
        if ORDER.search(txt):
            dropped["order"] += 1
        elif COPYRIGHT.search(txt):
            copyright_bits.append(txt)
        elif TEMPO.match(txt):
            tempo_terms.append(txt)
        elif JUNK.match(txt) or QUOTE_JUNK.search(txt):
            dropped["junk"] += 1
        elif CHORDISH.match(txt.replace("Z", "2")):
            dropped["chord"] += 1
        else:
            w = c.find("credit-words")
            try:
                size = int(float((w.get("font-size") if w is not None else 0) or 0))
            except ValueError:
                size = 0
            kept_titleish.append((size, txt))

    ident = root.find("identification")
    composers: list[str] = []
    if ident is not None:
        for cr in ident.findall("creator"):
            if cr.get("type") == "composer" and (cr.text or "").strip():
                composers.append(cr.text.strip())
        for ri in ident.findall("rights"):
            if (ri.text or "").strip():
                copyright_bits.append(ri.text.strip())

    # --- decide the four fields --------------------------------------------
    kept_titleish.sort(key=lambda t: -t[0])          # biggest type first
    existing_title = None
    work = root.find("work")
    if work is not None:
        existing_title = (work.findtext("work-title") or "").strip() or None

    title = opt("--title") or typed.get("title") or existing_title
    subtitle = opt("--subtitle") or typed.get("subtitle")
    leftovers = [t for _s, t in kept_titleish]
    # Composer credits are the "words and music" style lines, plus any
    # continuation line - engravers split a co-writing credit across two lines
    # ("Words and Music by X" / "and Y"), and dropping the second loses a
    # co-author.
    composer_credits = [t for t in leftovers
                        if re.search(r"words|music by|composed|lyrics", t, re.I)
                        or re.match(r"^and\s+\S", t)]
    leftovers = [t for t in leftovers if t not in composer_credits]
    if title is None and leftovers:
        title = leftovers.pop(0)
    if subtitle is None and leftovers:
        subtitle = leftovers.pop(0)

    composer = opt("--composer") or typed.get("composer")
    if composer is None:
        # Both sources: a line may appear in only one of them.
        seen, uniq = set(), []
        for p in composer_credits + composers:
            k = re.sub(r"[^a-z]", "", p.lower())
            if k and k not in seen:
                seen.add(k); uniq.append(p)
        composer = " ".join(uniq).strip() or None
        if composer:
            composer = re.sub(r"\s+and\s+and\s+", " and ", composer)

    seen, rights_parts = set(), []
    for bit in copyright_bits:
        k = re.sub(r"[^a-z0-9]", "", bit.lower())
        if k and k not in seen:
            seen.add(k); rights_parts.append(bit.rstrip(". "))
    rights = ". ".join(rights_parts) + "." if rights_parts else None

    if not title:
        sys.exit("FAIL  could not infer a title; pass --title")

    # --- rewrite metadata: one creator, one rights -------------------------
    for old in root.findall("work"):
        root.remove(old)
    w = ET.Element("work")
    ET.SubElement(w, "work-title").text = title
    root.insert(0, w)

    if ident is None:
        ident = ET.Element("identification")
        root.insert(1, ident)
    for cr in list(ident.findall("creator")) + list(ident.findall("rights")):
        ident.remove(cr)
    if composer:
        e = ET.Element("creator"); e.set("type", "composer"); e.text = composer
        ident.insert(0, e)
    if rights:
        e = ET.Element("rights"); e.text = rights
        ident.insert(1, e)

    # --- rewrite credits: typed and positioned ----------------------------
    for c in credits:
        root.remove(c)
    spec = [("title", title, centre, page_h - 116, 24, "center")]
    if subtitle:
        spec.append(("subtitle", subtitle, centre, page_h - 171, 14, "center"))
    if composer:
        spec.append(("composer", composer, right, page_h - 226, 11, "right"))
    if rights:
        spec.append(("rights", rights, centre, 130, 7, "center"))

    idx = list(root).index(ident) + 1
    for i, (ctype, txt, x, y, size, halign) in enumerate(spec):
        c = ET.Element("credit"); c.set("page", "1"); c.set("type", ctype)
        cw = ET.SubElement(c, "credit-words")
        cw.text = txt
        cw.set("default-x", str(x)); cw.set("default-y", str(y))
        cw.set("font-size", str(size)); cw.set("halign", halign); cw.set("valign", "top")
        root.insert(idx + i, c)

    # --- a tempo term belongs in bar 1, not in the page furniture ----------
    moved_tempo = None
    if tempo_terms:
        part = root.find("part")
        first = part.find("measure") if part is not None else None
        if first is not None:
            already = any(TEMPO.match((x.text or "")) for x in first.iter("words"))
            if not already:
                d = ET.Element("direction"); d.set("placement", "above")
                dt = ET.SubElement(d, "direction-type")
                wo = ET.SubElement(dt, "words")
                wo.text = moved_tempo = tempo_terms[0]
                wo.set("font-weight", "bold")
                first.insert(1, d)

    # --- in-measure text: drop junk, promote misspelled chord names ---------
    KIND = {"sus2": "suspended-second", "sus4": "suspended-fourth",
            "m7": "minor-seventh", "maj9": "major-ninth", "maj7": "major-seventh",
            "m": "minor", "6": "major-sixth", "9": "dominant-ninth",
            "7": "dominant", "5": "power", "": "major"}
    promoted, junked = [], 0
    for part in root.findall("part"):
        for meas in part.findall("measure"):
            for d in list(meas.findall("direction")):
                words = d.find("direction-type/words")
                if words is None or not (words.text or "").strip():
                    continue
                raw = words.text.strip()
                # Tesseract reads digits as letters in chord names; Audiveris
                # then cannot parse them and demotes them to plain text.
                cand = raw.replace("Z", "2").replace("z", "2").replace(" ", "")
                mo = re.fullmatch(r"([A-G][#b]?)(sus2|sus4|maj9|maj7|m7|m|6|9|7|5|)", cand)
                if mo and cand != raw.replace(" ", ""):
                    step, qual = mo.group(1), mo.group(2)
                    h = ET.Element("harmony")
                    rt = ET.SubElement(h, "root")
                    ET.SubElement(rt, "root-step").text = step[0]
                    if len(step) > 1:
                        ET.SubElement(rt, "root-alter").text = "1" if step[1] == "#" else "-1"
                    k = ET.SubElement(h, "kind")
                    k.text = KIND.get(qual, "major"); k.set("text", qual)
                    i = list(meas).index(d)
                    meas.remove(d); meas.insert(i, h)
                    promoted.append(f"m{meas.get('number')}:{step}{qual}")
                elif JUNK.match(raw) or QUOTE_JUNK.search(raw):
                    meas.remove(d); junked += 1

    tree.write(dst, encoding="UTF-8", xml_declaration=True)

    print(f"title      {title!r}")
    print(f"subtitle   {subtitle!r}")
    print(f"composer   {composer!r}")
    print(f"rights     {(rights or '')[:60]!r}...")
    print(f"tempo      {moved_tempo!r} moved into bar 1" if moved_tempo else "tempo      none found")
    print(f"credits    {len(credits)} -> {len(spec)} (typed and positioned)")
    print(f"dropped    junk={dropped['junk']} chord-symbols={dropped['chord']} "
          f"order-lines={dropped['order']}")
    print(f"in-bar     promoted {len(promoted)} misread chord name(s) to harmony"
          + (f": {', '.join(promoted)}" if promoted else ""))
    print(f"           dropped {junked} junk text direction(s)")
    print(f"wrote      {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
