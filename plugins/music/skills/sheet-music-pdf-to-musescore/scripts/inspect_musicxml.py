#!/usr/bin/env python3
"""Structural inspection of an OMR-produced MusicXML file.

Replaces line-oriented grepping, which silently reports nothing when a writer
pretty-prints <key>/<time> across multiple lines - a false "missing signature"
is worse than no check at all in a step whose whole job is finding OMR errors.

Accepts .xml, .musicxml, or .mxl (compressed - Audiveris's default export).

Usage:  inspect_musicxml.py SCORE
Exit:   0 = parsed, no structural red flags
        1 = unparseable, or a red flag worth resolving before proofing
"""

from __future__ import annotations

import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter


def load(path: str) -> ET.Element:
    """Return the score root, transparently unwrapping a compressed .mxl."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            target = None
            # A .mxl points at its real score file from META-INF/container.xml.
            try:
                container = ET.fromstring(z.read("META-INF/container.xml"))
                rootfile = container.find(".//rootfile")
                if rootfile is not None:
                    target = rootfile.get("full-path")
            except KeyError:
                pass
            if target is None:
                candidates = [
                    n for n in z.namelist()
                    if n.endswith((".xml", ".musicxml")) and "META-INF" not in n
                ]
                if not candidates:
                    sys.exit(f"FAIL  {path}: zip contains no score xml")
                target = candidates[0]
            print(f"container   {path} -> {target}")
            return ET.fromstring(z.read(target))
    return ET.parse(path).getroot()


def text_of(parent: ET.Element, tag: str, default: str = "?") -> str:
    node = parent.find(tag)
    return node.text if node is not None and node.text else default


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = sys.argv[1]

    try:
        root = load(path)
    except ET.ParseError as exc:
        sys.exit(f"FAIL  {path}: not well-formed XML: {exc}")
    except (OSError, zipfile.BadZipFile) as exc:
        sys.exit(f"FAIL  {path}: {exc}")

    print(f"well-formed yes ({root.tag})")
    problems: list[str] = []

    if root.tag == "score-timewise":
        problems.append(
            "score-timewise layout; most tools expect score-partwise "
            "(convert before proofing)"
        )

    # ---- parts and per-part measure counts -------------------------------
    # A part out of step with its siblings is the single most diagnostic
    # signal that OMR dropped or invented measures.
    names = {
        sp.get("id"): text_of(sp, "part-name", "(unnamed)")
        for sp in root.findall(".//score-part")
    }
    parts = root.findall("part")
    print(f"parts       {len(parts)}")
    counts: dict[str, int] = {}
    for p in parts:
        pid = p.get("id") or "?"
        counts[pid] = len(p.findall("measure"))
        print(f"  {pid:<6} {counts[pid]:>5} measures   {names.get(pid, '(no score-part)')}")

    if len(set(counts.values())) > 1:
        tally = Counter(counts.values())
        majority = tally.most_common(1)[0][0]
        odd = [f"{k}={v}" for k, v in counts.items() if v != majority]
        problems.append(
            f"measure counts disagree across parts (majority {majority}; "
            f"outliers {', '.join(odd)}) - OMR dropped or invented measures"
        )
    elif len(parts) < 2:
        print("            single part: the cross-part measure-count check is "
              "unavailable, so count measures against the printed page yourself")

    # ---- signatures, including mid-score changes -------------------------
    for label, tag, fields, absence in (
        ("key", "key", ("fifths", "mode"), "info"),
        ("time", "time", ("beats", "beat-type"), "flag"),
    ):
        seen = []
        for p in parts:
            pid = p.get("id") or "?"
            for m in p.findall("measure"):
                for el in m.iter(tag):
                    vals = "/".join(text_of(el, f) for f in fields if el.find(f) is not None)
                    seen.append((pid, m.get("number"), vals or "(empty)"))
        if not seen:
            if absence == "info":
                # C major / A minor print no key signature, so Audiveris
                # legitimately emits no <key> at all. Not a defect on its own.
                print(f"{label:<11} absent - normal for C major/A minor; "
                      f"confirm against the printed score")
            else:
                problems.append(
                    f"no <{tag}> element anywhere - {label} signature missing"
                )
            continue
        first = [s for s in seen if s[0] == (parts[0].get("id") if parts else None)]
        print(f"{label:<11} {len(seen)} occurrence(s); first: {seen[0][2]}")
        # Changes after measure 1 are legitimate but frequently misread.
        changes = [s for s in first[1:] if s[2] != first[0][2]]
        if changes:
            where = ", ".join(f"m{n}->{v}" for _, n, v in changes[:6])
            print(f"            mid-score {label} changes: {where}")

    divisions = {d.text for d in root.iter("divisions") if d.text}
    print(f"divisions   {', '.join(sorted(divisions)) or '(none declared)'}")
    if not divisions:
        problems.append("no <divisions> declared - durations cannot be interpreted")

    # ---- transposing instruments ----------------------------------------
    for tr in root.iter("transpose"):
        print(f"transpose   chromatic={text_of(tr, 'chromatic', '0')} "
              f"diatonic={text_of(tr, 'diatonic', '0')}")

    # ---- features that drive the proofing checklist ---------------------
    feature_tags = {
        "lyrics": "lyric",
        "chord names": "harmony",
        "tuplets": "tuplet",
        "slurs": "slur",
        "ties": "tie",
        "repeats": "repeat",
        "voltas": "ending",
        "dynamics": "dynamics",
        "hairpins": "wedge",
    }
    present = {
        label: sum(1 for _ in root.iter(tag))
        for label, tag in feature_tags.items()
    }
    shown = ", ".join(f"{k}={v}" for k, v in present.items() if v)
    print(f"features    {shown or '(none detected)'}")

    voices = {v.text for v in root.iter("voice") if v.text}
    if len(voices) > 1:
        print(f"voices      {len(voices)} distinct - multi-voice staves are "
              f"where OMR struggles most")

    # ---- voltas that cannot mean anything -------------------------------
    # A volta bracket only makes sense with a repeat to jump back to. OMR
    # invents these from long slurs, ties, and lyric extender lines, and a
    # phantom volta silently changes playback structure - so a count alone
    # isn't enough, the bracket has to be corroborated.
    endings, repeats = [], []
    for p in parts:
        pid = p.get("id") or "?"
        for m in p.findall("measure"):
            for e in m.iter("ending"):
                endings.append((pid, m.get("number"), e.get("type"), e.get("number")))
            for rp in m.iter("repeat"):
                repeats.append((pid, m.get("number"), rp.get("direction")))

    if endings:
        where = ", ".join(f"{pid}/m{num} {typ or '?'}" for pid, num, typ, _ in endings[:6])
        print(f"voltas      {len(endings)}: {where}")
        if repeats:
            print(f"repeats     {len(repeats)}: "
                  + ", ".join(f"{pid}/m{num} {d or '?'}" for pid, num, d in repeats[:6]))
        else:
            problems.append(
                f"volta bracket(s) at {where} but NO repeat barline anywhere - "
                f"a volta with nothing to repeat back to is almost always a "
                f"misread slur, tie, or lyric extender"
            )
        # An unterminated bracket is the same story from a different angle.
        starts = sum(1 for _, _, t, _ in endings if t == "start")
        closes = sum(1 for _, _, t, _ in endings if t in ("stop", "discontinue"))
        if starts != closes:
            problems.append(
                f"volta brackets unbalanced ({starts} start vs {closes} "
                f"stop/discontinue) - an unclosed volta is usually invented"
            )

    if present["tuplets"]:
        problems.append(
            "tuplets present - only triplets and 6-tuplets are supported by "
            "Audiveris even manually; verify others by hand"
        )
    if present["chord names"]:
        problems.append(
            "chord names present - Tesseract cannot read the sharp/flat glyphs; "
            "check accidentals in every symbol"
        )

    print()
    if problems:
        print("RED FLAGS")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("no structural red flags (still proof against the printed score)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
