# Audiveris CLI reference

Every flag and constant below was verified against the Audiveris handbook source
and, where noted, the Java source.

## Invocation

```bash
"$AUDIVERIS" -batch -transcribe -export -save \
  -constant org.audiveris.omr.sheet.BookManager.useCompression=false \
  -sheets 2-4 \
  -output ~/Desktop/omr-out \
  -- ~/Desktop/score.pdf
```

| Flag | Meaning |
|---|---|
| `-batch` | Run with no graphic user interface. |
| `-transcribe` | Transcribe the whole book — equivalent to targeting the final `PAGE` step. |
| `-export` | Export MusicXML. Default output is **compressed `.mxl`**. |
| `-save` | Save each book's OMR data to its `.omr` project file as each sheet step completes. **Only effective in `-batch` mode.** |
| `-output DIRNAME` | Target folder for all outputs (`.omr`, `.mxl`, …). Falls back to the standard-folders policy if omitted. |
| `-sheets int[]` | Select sheet numbers and ranges. |
| `-step <STEP>` | Stop at a specific target step. Already-reached steps are skipped unless `-force`. |
| `-force` | Reprocess even if the target step was reached. Resets the sheet to `BINARY`, then re-runs. Only meaningful with `-step` or `-transcribe`. |
| `-constant <k>=<v>` | Set a Java constant. `-option` is the older name; both are supported. |
| `-version` | Prints Version, Commit, OS, Architecture, Java VM, and the OCR engine's Tesseract version. |
| `--` | Delimiter: every following argument is an input path, even one starting with `-`. |

### `-sheets` gotchas

- Sheet IDs start at **1**.
- Space-separated numbers and `X-Y` ranges both work and can be mixed: `-sheets 1 4-5`.
- **`X-Y` must be a single argument with no spaces around the hyphen.**
- Sheet IDs apply to **every book** on the command line.

## Useful constants

| Constant | Effect |
|---|---|
| `org.audiveris.omr.sheet.BookManager.useCompression=false` | Emit uncompressed `.xml` instead of zipped `.mxl`, so the result can be read and patched directly. |
| `org.audiveris.omr.sheet.BookManager.useOpus=true` | Emit a single `.mxl` opus instead of one file per movement. |
| `org.audiveris.omr.text.Language.defaultSpecification=fra+eng` | OCR languages, `+`-joined. Default `eng`. Don't pile these on — extra languages slow recognition and add false positives. |

## Processing switches

Each switch in `ProcessingSwitch` is backed by a boolean constant, settable from
the CLI as `org.audiveris.omr.sheet.ProcessingSwitches.<name>`. Available names:

`oneLineStaves`, `fiveLineStaves`, `fourStringTablatures`, `sixStringTablatures`,
`drumNotation`, `smallHeads`, `smallBeams`, `crossHeads`, `tremolos`,
`fingerings`, `frets`, `pluckings`, `partialWholeRests`, `multiWholeHeadChords`,
`chordNames`, `lyrics`, `lyricsAboveStaff`, `articulations`,
`dynamicsAboveStaff`, `dynamicsBelowStaff`, `keepGrayImages`, `indentations`,
`bothSharedHeadDots`, `disconnectedBracedParts`, `implicitTuplets`

### Recipe for charts with guitar chord diagrams

The `X`/`O` markers in fretboard grids get misread as staccato dots and
dynamics. Measured on a 2-page piano/vocal/guitar chart:

```bash
-constant org.audiveris.omr.sheet.ProcessingSwitches.articulations=false \
-constant org.audiveris.omr.sheet.ProcessingSwitches.dynamicsAboveStaff=false
```

| Setting | Phantom markings | Real data |
|---|---|---|
| default | 4 staccato + `p` + `sfz` | 10 chords, 68 lyrics, real `mp` |
| `articulations=false` | staccato gone; `p` + `sfz` remain | unchanged |
| both switches | only `sfz` remains | unchanged — `mp`, chords, lyrics all intact |

So 5 of 6 phantoms disappear with no loss. **The trade-off is real**: these
switches suppress genuine articulations and genuine above-staff dynamics too.
Only use them when the rasterised page (step 1) shows the score has none —
typical for pop/rock lead sheets, wrong for classical piano.

**`frets=true` does nothing for chord diagrams** — tested, byte-identical
output. It governs tablature fret digits, not chord frames.

## Pipeline steps, in order

`LOAD`, `BINARY`, `SCALE`, `GRID`, `HEADERS`, `STEM_SEEDS`, `BEAMS`, `LEDGERS`,
`HEADS`, `STEMS`, `REDUCTION`, `CUE_BEAMS`, `TEXTS`, `MEASURES`, `CHORDS`,
`CURVES`, `SYMBOLS`, `LINKS`, `RHYTHMS`, `PAGE`

Use `-step` to stop early and find where recognition breaks. The pipeline only
runs **forward**: going back means resetting to an earlier step and re-running,
which is why `-save` matters.

## Book / Sheet / Page

- One **Book** = one input file.
- One **Sheet** = one image in that file (so one PDF page = one sheet).
- A **Page** is a movement-fragment *within* a sheet. Usually one page per sheet,
  but an indented system can split a sheet into two or more pages, and a sheet
  with no music contains no page at all.

Export granularity follows from this: a **book** export writes one file **per
movement** by default; a **sheet** export writes one file per page.

## Input quality

The engine's needs, from the handbook's scanning guidance:

- **~20 pixels between staff lines** is the real target.
- **300 DPI** for standard A4/Letter; **400 DPI** where symbols are small.
- Below **200 DPI** detail is lost; above **500 DPI** you waste CPU and memory
  for no gain.
- **Prefer grayscale** to bitonal or colour — Audiveris binarises itself with an
  adaptive algorithm, and hard thresholding in the scanner destroys thin stems
  and slurs.

### Rescuing a scan that can't be redone

The handbook's "Improved Input" page collects two community techniques:

- **Gimp** — brightness/contrast via the colour-curve tool, then filters
  (gaussian blur 1.5–2.0, curve clipping, unsharp mask σ≈1.0).
- **waifu2x** — `waifu2x-ncnn-vulkan -s 4` to upscale low-resolution scans. 2x is
  sometimes enough; note 4x can exceed Audiveris's maximum pixel capacity.

## Runtime expectations

Dense music takes **minutes per sheet**. A run that appears to hang usually
isn't. See the timeout guidance in `SKILL.md` — long runs need backgrounding,
not a longer foreground timeout.
