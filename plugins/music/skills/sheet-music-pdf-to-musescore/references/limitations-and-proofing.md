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
| `mscore` exits **134** (SIGABRT) after writing output | A known crash-on-quit bug. The fix ([PR #34136](https://github.com/musescore/MuseScore/pull/34136), *"[4.7.5] CLI: fix crash on app quit"*) is **merged but unreleased** — 4.7.4, published 2026-07-07, is still the latest release, so there is nothing to upgrade to. Not a conversion failure: judge the `.mscz`, not the exit code, as `scripts/to_mscz.sh` does. Re-check whether 4.7.5 has shipped before repeating this advice. |
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
| A volta bracket appears where the score has none | Long slurs, ties, and lyric extender lines get read as voltas, and a phantom volta silently changes playback structure. `inspect_musicxml.py` flags a volta with no repeat barline to jump back to, and an unclosed bracket. Observed on a real piano/vocal chart: a tie plus a `now.___` extender produced a volta and a tuplet in the same measure. |
| Guitar chord diagrams present | The fretboard `X`/`O` grids get read as dynamics (`sfz`, `sf`, `fp`) and staccato dots. Mitigate with the `articulations=false` + `dynamicsAboveStaff=false` switch recipe in `references/audiveris-cli.md` (tested: 5 of 6 phantoms gone, no real data lost). `frets=true` does **not** help. |
| A chord symbol becomes plain text instead of a chord | Tesseract misreads a digit as a letter — observed `Fsus2` to `FsusZ` in ~40% of instances — Audiveris cannot parse the result as a chord name, and demotes it to a `<words>` annotation, so it vanishes from the harmony data. This is the main cause of chord loss: 51 of 67 symbols on a real chart. If the PDF is born-digital, recover them with `scripts/chords_from_pdf.py`, which reads the text layer instead of OCR. |
| An implausible dynamic (`sfz` in a quiet ballad) | Often a chord symbol that lost a scoring contest to a dynamic interpretation — check the chord at that exact position before deleting. Verified case: `sfz` above the lyric "home" was the score's `Am7`. Suppressing dynamics does not reliably recover the chord; use `scripts/chords_from_pdf.py`. |
| Header/footer text piles up on top of itself | Audiveris emits two `<creator type="composer">` and two `<rights>` elements; MuseScore anchors duplicates at the same point. It also emits credits with no `type`, which MuseScore places by raw OMR pixel coordinates. Run `scripts/clean_omr_text.py`. |
| Title missing from the score | `<work-title>` is usually absent, and even when set it populates metadata only — it renders nothing. Visible text needs a typed `<credit>` with a position. `clean_omr_text.py` writes both. |
| Purchase or order details appear in the score | The source PDF's footer is OCR'd into a credit on every page. `clean_omr_text.py` drops them. |
| A lyric has the right letters but wrong capitalisation | OCR case errors such as `neVer` for "never" survive any case-insensitive check. `chords_from_pdf.py --lyrics` compares case-sensitively and reports these separately from outright misreads. Note that a syllable can hide inside an all-caps title (`FALL` within `FALLING`), so long all-caps tokens are excluded from that comparison. |
| A `C5`-style power chord vanishes from the export | Audiveris recognises it, then throws `NullPointerException` in `PartwiseBuilder.processChordName` because the chord kind is null, and drops that symbol. Export continues, so it fails quietly — check the log for `No kind type for`. Not fixable in the XML. |
| Slash chords lose their bass note | `G/F` exports as `G`; some are missed entirely. Verify every slash chord by eye. |

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
