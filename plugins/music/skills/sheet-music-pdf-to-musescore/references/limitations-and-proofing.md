# Limitations, proofing, and failure triage

## Documented limitations

Raise these proactively when the score contains the relevant features.

- **Opposed stems** — adjacent chords with opposing stem directions that visually
  merge get read as one long stem with heads attached near its middle and none at
  either end. At `REDUCTION` that stem is discarded, and the now-isolated heads
  with it. Fix by manually inserting separate stems and heads.
- **Chord names** — Tesseract cannot correctly handle the ♯ and ♭ glyphs.
  Workaround is replacing them with `#` and lowercase `b`.
- **Tuplets** — only triplets and 6-tuplets are supported, *even manually*.
  Quintuplets and septuplets need hand entry in MuseScore.
- **Roman numeral analysis** — recognised, but not exported to MusicXML.

## Tablature: off by default

**Tablature detection is disabled unless you enable it.** Turn on the 4-line
and/or 6-line processing switches explicitly. Once enabled, `GRID` identifies the
staff as tablature and its area is then carefully *ignored* by subsequent
processing — so it produces no false notes, but isn't transcribed either and
won't appear in the output.

Known gap: stems and beams *outside* the tablature area are still not ignored.

(This is a "specific feature", not an entry on the handbook's limitations page.)

## Out of scope

Audiveris targets **printed Common Western Music Notation**. Handwritten
manuscript, shape notes, and graphic or contemporary notation are outside what it
targets — don't promise results there.

## Proofing checklist

OMR output is a draft, always. Trim this to what the score actually contains, and
order by how often each breaks.

1. **Key and time signatures**, including mid-score changes, which are frequently
   dropped.
2. **Measure durations.** The most common defect, and it cascades — one wrong
   duration shifts everything after it.
3. **Ties vs slurs.** Visually near-identical, semantically unrelated: a tie read
   as a slur changes the rhythm.
4. **Voices and cross-staff beaming.** Piano and choral music with multiple voices
   per staff is where Audiveris struggles most.
5. **Accidentals**, especially courtesy accidentals and ones landing on the wrong
   chord member.
6. **Octave errors** — a note read a ledger line off, or a missing 8va/8vb.
7. **Lyrics** — verse alignment, hyphenation, melismas, verse numbering. This is
   OCR, so expect character errors.
8. **Chord symbols** — sharps and flats are unreliable (see above).
9. **Repeats, codas, D.S./D.C., volta brackets.** Easy to miss and they change the
   whole structure.
10. **Dynamics, hairpins, articulations, tempo text.** Cosmetic but tedious later.
11. **Instrument names and transpositions** — confirm transposing instruments
    sound at the right pitch.
12. **Play it back.** Wrong notes are far easier to hear than to see.

## Failure triage

| Symptom | Cause / response |
|---|---|
| `mscore` exits **134** (SIGABRT) after writing output | A known MuseScore bug — *"CLI: fix crash on app quit"* — **fixed in 4.7.5**. On 4.7.5+ upgrade and it goes away; on 4.7.4 and earlier it is intermittent and **not** a failure. Either way, judge the `.mscz`, not the exit code; `scripts/to_mscz.sh` does. |
| Setting `QT_QPA_PLATFORM=offscreen` to "fix" that crash | **There is no offscreen plugin on macOS** — the bundle ships only `libqcocoa.dylib`, so Qt fails to start and **no output file is produced**. Verified. On Linux 4.6+, offscreen exists but you must set both `QT_QPA_PLATFORM` *and* `MU_QT_QPA_PLATFORM`. |
| `grep`ping `<key>`/`<time>` finds nothing | The elements are pretty-printed across lines. A line-oriented grep silently reports nothing — use `scripts/inspect_musicxml.py`, which parses the XML. |
| No `<key>` element in the export | Normal for C major / A minor: there is no key signature to print, so Audiveris emits none. Not a defect by itself. |
| No lyrics or text recognised at all | OCR language data not installed. See `references/install-macos.md`. Fails silently. |
| Gatekeeper refuses to launch Audiveris | App is unsigned; allow via Privacy & Security → "Open Anyway" (on Tahoe, press "Done" first). |
| Staves not detected / `GRID` fails | Resolution too low or scan skewed. Check the ~20px staff-line-gap rule; this is an input problem, not something to fix downstream. |
| Wildly wrong rhythms throughout | Usually a misread time signature early on. Fix in the Audiveris GUI and re-export, so the corrected signature propagates. |
| Output is `.mxl` not `.xml` | The `useCompression=false` constant was omitted or misspelled. `inspect_musicxml.py` reads `.mxl` anyway. |
| Run seems to hang for minutes | Normal on dense sheets. Background it rather than raising a foreground timeout. |
| PDF with vector graphics fails to load | FreeType — but only relevant for from-source builds, not the DMG. |
| Measure counts differ between parts | OMR dropped or invented measures. The single most diagnostic signal; `inspect_musicxml.py` flags it. On a **single-part** score this check is unavailable — count measures against the printed page by hand. |

> Not substantiated: converter mode is often said to steal window focus. It does
> start a real Qt `QApplication`, but a search of MuseScore's CLI issues found no
> such report, and `lsappinfo front` did not change across test conversions.
> Treat it as folklore rather than warning users about it as fact.

## When to correct in the Audiveris GUI instead

For structural damage, correcting in Audiveris and re-exporting beats fixing in
MuseScore, because Audiveris corrections propagate through all downstream
interpretation — fix a misread time signature there and the rhythms follow.

Open the saved `.omr`, correct the misrecognised entities (Audiveris calls them
"Inters"), then Book → Export book, and re-run the `.mscz` conversion on the new
export. This is why `-save` matters: without the `.omr`, any later correction
means re-running the whole pipeline from scratch.
