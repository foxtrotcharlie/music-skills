---
name: sheet-music-pdf-to-musescore
description: Use when the user has a PDF or scanned image of printed sheet music and wants editable notation — MusicXML or a MuseScore .mscz — or asks to "transcribe", "digitise", "OCR", or "convert" a score PDF so they can edit, transpose, or play it back.
---

# Sheet music PDF → MuseScore

Optical music recognition (OMR) with **Audiveris**, then conversion to MuseScore.

Two principles govern everything here:

1. **Input quality dominates output quality.** A bad scan costs far more in
   proofing than a rescan does. Assess before converting.
2. **OMR output is a draft, always.** Your job ends with an honest report and a
   proofing checklist, never "here's your score".

## When NOT to use

Audiveris targets **printed** Common Western Music Notation. Stop and say so if
the input is handwritten manuscript, shape notes, or graphic/contemporary
notation. Tablature is detected only behind an off-by-default switch and is never
transcribed. Rasterise a page (step 1) to check *before* investing in a run.

## Step 0 — Preflight

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/preflight.sh
```

Checks Audiveris, OCR language data, MuseScore, poppler, and python3, and prints
the `AUDIVERIS` and `MSCORE` paths to use. Non-zero exit means stop — resolve the
gaps first, using `references/install-macos.md`.

Two traps it exists to catch: **missing OCR language data fails silently** (no
lyrics, tempo text, or chord names, and no error), and Audiveris has shipped
**no** language data in any installer since 5.5.

## Step 1 — Assess the PDF

```bash
pdfinfo score.pdf
pdfimages -list score.pdf
pdftoppm -png -r 150 -f 1 -l 1 score.pdf /tmp/page   # then Read the PNG
```

Read for: **born-digital vs scanned** (no images, or one small logo, means vector
notation — the best case; one full-page image per page means a scan);
**resolution** against the ~20px-between-staff-lines target; **page count**, since
each page becomes one sheet; and **skew or clipping**, which is worth rescanning
rather than fighting.

Rasterising a page is also the fastest way to see instrumentation, staff count,
polyphony density, and whether there are lyrics — use it to set expectations and
flag out-of-scope input early. Full guidance, DPI bounds, and rescue techniques
for unrepeatable scans: `references/audiveris-cli.md`.

## Step 2 — Sample first, then commit

**On anything longer than a few pages, never run the whole score first.** Convert
pages that show the hard parts, not the title page:

```bash
"$AUDIVERIS" -batch -transcribe -export -save \
  -constant org.audiveris.omr.sheet.BookManager.useCompression=false \
  -sheets 2-4 -output ~/Desktop/omr-out -- ~/Desktop/score.pdf
```

`-save` writes the `.omr` project file — **always include it.** Without it, any
later GUI correction means re-running the whole pipeline from scratch. The
`useCompression=false` constant emits readable `.xml` instead of zipped `.mxl`.

**If the page shows guitar chord diagrams**, add the two switches in
`references/audiveris-cli.md` — the fretboard `X`/`O` grids otherwise generate
phantom staccatos and dynamics. Tested: 5 of 6 phantoms removed, no real data
lost. Only do this when step 1 showed the score has no genuine articulations.

Flags, constants, pipeline steps, and `-sheets` range gotchas:
`references/audiveris-cli.md`.

**Runs take minutes per sheet.** A foreground Bash call is capped at 15 minutes,
so run the full pass **in the background** rather than reaching for a longer
timeout — a killed run wastes all of it. Then **read the console output**:
Audiveris logs per-sheet warnings that point straight at the damage. If `GRID`
failed or no staves were found, go back to step 1 — that's an input problem, not
something to fix downstream.

## Step 3 — Inspect and repair the MusicXML

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/inspect_musicxml.py ~/Desktop/omr-out/score.xml
```

Reports parts, **per-part measure counts** (a part out of step with its siblings
is the single most diagnostic signal of dropped or invented measures),
signatures including mid-score changes, divisions, transpositions, and which
features drive the proofing checklist. Reads `.xml`, `.musicxml`, and `.mxl`.

Do not hand-grep for `<key>`/`<time>` — those elements are often pretty-printed
across lines, so a line-oriented grep silently reports nothing and invents a
missing-signature bug.

**If the PDF is born-digital, recover the chord symbols from its text layer
instead of trusting OCR:**

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/chords_from_pdf.py score.pdf --compare ~/Desktop/omr-out/score.xml
```

OMR rasterises the page and throws away perfect text. Tesseract then reads
`Fsus2` as `FsusZ`, Audiveris rejects the unparseable name and demotes it to a
plain text annotation, and the chord vanishes from the harmony data. On a real
chart this cost **51 of 67 chord symbols**. The script prints the exact
ground-truth list per page plus what OMR lost, so chord symbols get retyped from
a verified list rather than squinting at the PDF. It exits 1 on a scanned PDF
(no text layer), where OCR is the only route.

`--lyrics score.xml` does the same for sung text: it lists every syllable that
does **not** appear in the text layer and suggests the closest real word. On the
same chart that found 3 misreads in 158 syllables — `'HOW.'` for "now.",
`'WOT].'` for "won.", `'feted'` for "fered" — which is far cheaper than
proofreading lyrics by eye.

Compare the output against the printed score. **Know where to stop:** signatures,
structural metadata, part names, and transpositions are fair game to patch in
XML. Wholesale rewriting of note content is not — hand-editing pitches produces a
subtly worse file. Structurally bad recognition belongs in the Audiveris GUI, not
in XML surgery.

## Step 4 — MusicXML → `.mscz`

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/to_mscz.sh ~/Desktop/omr-out/score.xml ~/Desktop/score.mscz
```

**Never judge this step by the exit code.** MuseScore writes a complete, valid
`.mscz` and then intermittently aborts with **exit 134**. This is a known
crash-on-quit bug; the fix is merged upstream and slated for 4.7.5, but **4.7.4
is the latest release**, so there is no version to upgrade to yet. Validating the
artifact — the zip reads, contains a `.mscx`, holds notes — is the only
mitigation, and the wrapper does it.

Do not reach for `QT_QPA_PLATFORM=offscreen` to suppress it — macOS ships no
offscreen Qt plugin, so MuseScore fails to start and writes nothing at all.

Converter mode starts a real Qt application rather than a true headless process,
so expect a brief app launch. `.mscz` is a convenience anyway: MuseScore opens
MusicXML natively. Two import flags are worth knowing for OMR input —
`--musicxml-infer-text-type` and `--musicxml-use-default-font`; "import layout"
and "import system and page breaks" remain GUI-only.

## Step 5 — Report honestly

Report what you **observed** — log warnings, measure-count mismatches, what the
sample pages looked like — and calibrate expectations to it. A 150 DPI scan of a
dense piano score needs real proofing; say so rather than implying it's ready to
play.

Then hand over the proofing checklist from
`references/limitations-and-proofing.md`, trimmed to what this score actually
contains, plus the paths to the MusicXML, the `.omr`, and the `.mscz`. **Keep the
`.omr`** — it's what makes iterative correction cheap.

When recognition is structurally damaged, send the user to the Audiveris GUI
rather than MuseScore: corrections there propagate through all downstream
interpretation. Triage table and documented limitations:
`references/limitations-and-proofing.md`.
