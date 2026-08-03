---
name: sheet-music-pdf-to-musescore
description: Convert a sheet music PDF into MuseScore-editable notation using Audiveris OMR. Use when the user has a PDF or scanned image of printed sheet music and wants it as MusicXML or a .mscz MuseScore file, or asks to "transcribe", "digitise", "OCR", or "convert" a score PDF so they can edit, transpose, or play it back.
---

# Sheet music PDF → MuseScore

Runs **Audiveris** optical music recognition over a printed-score PDF to produce MusicXML, inspects and repairs the result, then converts to MuseScore's native `.mscz`.

Both tools are local macOS apps and you invoke them directly with Bash. Verify paths in Step 0 rather than assuming them.

## Step 0 — Preflight

```bash
ls -d /Applications/Audiveris.app 2>/dev/null || echo "AUDIVERIS MISSING"
ls -d /Applications/MuseScore*.app 2>/dev/null || echo "MUSESCORE MISSING"
find /Applications/Audiveris.app/Contents/MacOS -type f 2>/dev/null
```

The `find` matters: the executable name inside the bundle is set by jpackage and should be `Audiveris`, but confirm it and use the real path throughout. Same for the MuseScore bundle name — it varies by major version (`MuseScore 4.app`).

Then confirm the Audiveris version and that OCR data is present:

```bash
/Applications/Audiveris.app/Contents/MacOS/Audiveris -version
find ~/Library -maxdepth 5 -type d -name tessdata 2>/dev/null
```

`-version` prints the Audiveris version and the bundled Tesseract version. Audiveris keeps OCR data in a `tessdata` folder under its user config directory — locate it with `find` rather than hardcoding the path, then check it contains `eng.traineddata` (or the score's language). If it's absent or empty, OCR will fail silently — stop and have the user fix it (see below) before burning time on a conversion. If `TESSDATA_PREFIX` is set in their environment, Audiveris uses that instead; check with `echo $TESSDATA_PREFIX`.

### If Audiveris isn't installed

Don't try to install it unattended — it needs GUI interaction. Give the user these steps:

1. Download the installer for their chip from https://github.com/Audiveris/audiveris/releases — `Audiveris-<version>-macosx-arm64.dmg` for Apple Silicon, `-x86_64.dmg` for Intel. 5.11.0 (July 2026) was current when this skill was written; take whatever is latest.
2. Open the DMG, drag `Audiveris.app` to `/Applications`.
3. The app isn't code-signed, so Gatekeeper blocks the first launch. Open it, get refused, then allow it under System Settings → Privacy & Security → "Open Anyway".
4. **No separate Java install needed** — installers since 5.5 bundle their own JRE.
5. **Install OCR data before converting anything.** Since 5.4 the installers ship no Tesseract language data. Launch the GUI and use **Tools → Languages** to download `eng` (plus the score's language if not English). Without this, lyrics, tempo text, and chord names silently fail. Audiveris runs Tesseract in *legacy* mode, so hand-installed data must be the legacy model rather than LSTM — the in-app downloader gets this right, so prefer it.

Don't set `TESSDATA_PREFIX` yourself unless there's a specific reason — Audiveris manages its own tessdata folder perfectly well.

## Step 1 — Assess the PDF first

Input quality dominates output quality, and a bad scan wastes far more time in proofing than a rescan costs. Inspect before converting:

```bash
pdfinfo score.pdf
pdfimages -list score.pdf
```

Read these for:

- **Born-digital vs scanned.** No images (or one small logo) in `pdfimages -list` means vector notation — the best case. One full-page image per page means a scan, and the listed resolution matters.
- **Scan resolution.** The real target is **~20 pixels between staff lines**. As a proxy: 300 DPI for A4/Letter, 400 DPI if the engraving is small or dense. Below 200 DPI recognition degrades badly; above 500 DPI just wastes time.
- **Grayscale beats bitonal.** Hard black-and-white thresholding destroys thin stems and slurs; Audiveris binarises better from grayscale itself.
- **Page count.** Each page becomes one Audiveris "sheet" in one "book". Long scores mean long runs — tell the user the expected scale before starting.
- **Skew and clipping.** Visibly rotated or edge-cropped staves are worth rescanning rather than fighting.

To eyeball a page yourself, rasterise one and Read it:

```bash
pdftoppm -png -r 150 -f 1 -l 1 score.pdf /tmp/page
```

That's often the fastest way to see what you're dealing with — instrumentation, staff count, polyphony density, whether there are lyrics, whether it's handwritten. Use it to set expectations and to flag the known-hard cases in Limitations below *before* converting.

For a scan that can't be redone, the Audiveris handbook's "Improved Input" page documents two community-contributed rescue techniques: brightness/contrast correction in an image editor, and `waifu2x` super-resolution upscaling.

## Step 2 — Convert a sample first

**On any score longer than a few pages, do not run the whole thing first.** Convert a representative sample, check quality, then commit. Pick pages that show the hard parts, not just the title page.

```bash
/Applications/Audiveris.app/Contents/MacOS/Audiveris \
  -batch -transcribe -export -save \
  -constant org.audiveris.omr.sheet.BookManager.useCompression=false \
  -sheets 2-4 \
  -output ~/Desktop/omr-out \
  -- ~/Desktop/score.pdf
```

Then the full run, once the sample looks sane — same command without `-sheets`.

Flag by flag:

- `-batch` — no GUI.
- `-transcribe` — run the full pipeline over the book.
- `-export` — write MusicXML.
- `-save` — also write the `.omr` project file. **Always include this.** The `.omr` holds all recognition state; without it, any later GUI correction means re-running the whole pipeline from scratch.
- `-constant org.audiveris.omr.sheet.BookManager.useCompression=false` — emit uncompressed `.xml` instead of the default zipped `.mxl`, so you can read and patch it directly. (`-option` is the old name for `-constant`; both work.)
- `-output DIR` — where results land.
- `-sheets 2-4` — sheet selection; also accepts individual numbers.
- `--` — ends options, so odd filenames are safe.

Other options worth knowing:

- `-force` — reprocess sheets already done (only meaningful with `-step` or `-transcribe`).
- `-constant org.audiveris.omr.text.Language.defaultSpecification=fra+eng` — OCR languages, `+`-joined. Don't pile these on: extra languages slow recognition and add false positives.
- `-step SYMBOLS` — stop at an earlier pipeline step to diagnose where recognition breaks. Steps in order: LOAD, BINARY, SCALE, GRID, HEADERS, STEM_SEEDS, BEAMS, LEDGERS, HEADS, STEMS, REDUCTION, CUE_BEAMS, TEXTS, MEASURES, CHORDS, CURVES, SYMBOLS, LINKS, RHYTHMS, PAGE.

Runs are slow — minutes per sheet on dense music. Use a generous Bash timeout, and prefer sampling over one long blind run.

**Read the console output.** Audiveris logs warnings per sheet, and they point straight at the damage. Book-level export writes one MusicXML file per movement by default, so check what actually landed:

```bash
ls -la ~/Desktop/omr-out/
```

If GRID failed or no staves were found, go back to Step 1 — that's a resolution or skew problem, not something to fix downstream.

## Step 3 — Inspect and repair the MusicXML

You have the file, so use it. Cheap, high-value checks:

```bash
cd ~/Desktop/omr-out
python3 -c "import xml.dom.minidom; xml.dom.minidom.parse('score.xml')" && echo "well-formed"
grep -c "<measure" score.xml
grep -c "<part " score.xml
grep -o "<key>.*</key>" score.xml | head
grep -o "<time>.*</time>" score.xml | head
```

Then compare measure counts per part — a part out of step with its siblings means dropped or invented measures, and it's the single most diagnostic signal available:

```bash
python3 - <<'PY'
import xml.etree.ElementTree as ET
r = ET.parse('score.xml').getroot()
for p in r.findall('part'):
    ms = p.findall('measure')
    print(p.get('id'), len(ms))
PY
```

Compare all of this against the printed score (rasterise pages as in Step 1 if needed). Key signatures, time signatures, divisions-per-quarter, measure counts, and part names are where OMR errors are both most common and most fixable in text — patch those directly with Edit.

**Know where to stop.** Signatures, structural metadata, part names, and instrument transpositions are fair game in XML. Do not attempt wholesale rewriting of note content — that belongs in a GUI, and hand-editing pitches in MusicXML is a good way to produce a file that's subtly worse. If recognition is structurally bad, the right move is Audiveris GUI correction (Step 5), not XML surgery.

## Step 4 — MusicXML → .mscz

```bash
/Applications/MuseScore\ 4.app/Contents/MacOS/mscore \
  -f -o ~/Desktop/score.mscz ~/Desktop/omr-out/score.xml
```

- `-o` / `--export-to` switches MuseScore to converter mode; output format comes from the extension. Accepts `.xml`, `.musicxml`, and `.mxl` as input.
- `-f` / `--force` suppresses corruption and version-mismatch prompts, which OMR output does sometimes trigger.
- `-S mystyle.mss` applies a house style file during conversion, if the user has one.
- For several files at once, `-j job.json` takes an array of `{"in": ..., "out": ...}` objects, where `out` may be an array of output paths.

Two caveats. Converter mode is **not truly headless on macOS** — it still starts a Qt app and has historically stolen window focus, so it needs a normal logged-in desktop session and may briefly pull focus from the user. Warn them rather than letting it surprise them. And MusicXML *import* preferences (import layout, system/page breaks, default typeface, infer text type) exist only in Edit → Preferences → Import, with no CLI equivalent; if imported layout is fighting them, that's where to look.

`.mscz` is a convenience only — MuseScore opens MusicXML natively, so if the CLI misbehaves the user can just open the `.xml` and save.

## Step 5 — Report honestly, then hand over the checklist

OMR output is a draft, always. Report what you actually observed — warnings in the log, measure-count mismatches, what the sample pages looked like — and calibrate the user's expectations to it. A 150 DPI scan of a dense piano score needs real proofing; say so rather than implying it's ready to play.

Then give a proofing checklist, ordered by how often these break and trimmed to what this score actually contains:

1. **Key and time signatures**, including mid-score changes, which are frequently dropped.
2. **Measure durations.** The most common defect, and it cascades — one wrong duration shifts everything after it.
3. **Ties vs slurs.** Visually near-identical, semantically unrelated: a tie read as a slur changes rhythm.
4. **Voices and cross-staff beaming.** Piano and choral music with multiple voices per staff is where Audiveris struggles most.
5. **Accidentals**, especially courtesy accidentals and ones landing on the wrong chord member.
6. **Octave errors** — a note read a ledger line off, or a missing 8va/8vb.
7. **Lyrics**: verse alignment, hyphenation, melismas, verse numbering. This is OCR, so expect character errors.
8. **Chord symbols** — sharps and flats are unreliable, see Limitations.
9. **Repeats, codas, D.S./D.C., volta brackets.** Easy to miss and they change the whole structure.
10. **Dynamics, hairpins, articulations, tempo text.** Cosmetic but tedious later.
11. **Instrument names and transpositions** — confirm transposing instruments sound at the right pitch.
12. **Play it back.** Wrong notes are far easier to hear than to see.

### When to send them to the Audiveris GUI instead

For structural damage, correcting in Audiveris and re-exporting beats fixing in MuseScore, because Audiveris corrections propagate through all downstream interpretation — fix a misread time signature there and the rhythms follow. Tell them to open the saved `.omr`, correct the misrecognised entities (Audiveris calls them "Inters"), then Book → Export book, and re-run Step 4 on the new export. The pipeline only runs forward, so going back means resetting to an earlier step and re-running — which is exactly why `-save` in Step 2 matters.

## Documented limitations

Raise these proactively when the score contains the relevant features:

- **Opposed stems**: adjacent chords with opposing stem directions that visually merge get read as one long stem, then discarded at REDUCTION. Needs manual stem and head re-insertion.
- **Chord names**: Tesseract can't reliably read ♯ and ♭ glyphs. Workaround is substituting `#` and `b`.
- **Tuplets**: only triplets and 6-tuplets are supported, even manually. Quintuplets and septuplets need hand entry in MuseScore.
- **Roman numeral analysis** is recognised but never exported to MusicXML.
- **Tablature** staves (4-line bass, 6-line guitar) are detected and then deliberately excluded from note and symbol processing, so they produce no false notes — but they aren't transcribed either and won't appear in the output.
- Not documented as limitations but implied by Audiveris's stated scope of *printed Common Western Music Notation*: handwritten manuscript, shape notes, and graphic/contemporary notation are outside what it targets. Don't promise results there.

## Failure triage

| Symptom | Cause |
|---|---|
| Gatekeeper refuses to launch | Unsigned app; allow via Privacy & Security → Open Anyway |
| No lyrics or text recognised at all | OCR language data not installed (Tools → Languages) |
| PDF with vector graphics fails to load | FreeType missing — required on macOS for PDFBox vector rendering |
| Staves not detected / GRID fails | Resolution too low or scan skewed; check the ~20px staff-line-gap rule |
| Wildly wrong rhythms throughout | Usually a misread time signature early on; fix in the GUI and re-export |
| Output is `.mxl` not `.xml` | The `useCompression=false` constant was omitted or misspelled |
| `mscore` hangs or steals focus | Converter mode isn't truly headless on macOS; needs a desktop session |
| Run seems to hang for minutes | Normal on dense sheets — raise the Bash timeout, don't kill it |

## Deliverables

Report the paths to the MusicXML, the `.omr` project file, and the `.mscz`; a summary of what the inspection found and anything you patched; and the trimmed proofing checklist. Keep the `.omr` — it's what makes iterative correction cheap.
