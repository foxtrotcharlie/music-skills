# music-skills

A small marketplace of [Claude Code](https://claude.com/claude-code) skills
for music notation and score digitisation. Skills are grouped into
independently-installable plugins so you only pull in what you want.

## Install

```
/plugin marketplace add foxtrotcharlie/music-skills
/plugin install music@music-skills
```

## Plugins

### `music`

Score digitisation and notation skills:

- **sheet-music-pdf-to-musescore** — converts a printed sheet music PDF into
  editable MuseScore/MusicXML notation using [Audiveris](https://github.com/Audiveris/audiveris)
  OMR. Assess the PDF, sample before committing to a full run, inspect and
  repair the MusicXML, convert to `.mscz`, then report honestly with a proofing
  checklist. Ships five helper scripts:

  | Script | Purpose |
  | :----- | :------ |
  | `preflight.sh` | Verifies Audiveris, OCR language data, MuseScore, poppler, and python3 before any work starts |
  | `clean_omr_text.py` | Rebuilds the title block and strips OCR'd text artefacts — duplicate metadata, untyped credits placed at raw pixel coordinates, fretboard-grid junk, purchase lines |
  | `inspect_musicxml.py` | Parses `.xml`/`.musicxml`/`.mxl` and flags structural OMR damage (per-part measure mismatches, missing signatures, orphan volta brackets, unsupported tuplets) |
  | `chords_from_pdf.py` | Extracts ground-truth chord symbols from a born-digital PDF's text layer and diffs them against the OMR output; `--lyrics` flags OCR'd syllables absent from the text layer and suggests corrections |
  | `to_mscz.sh` | Converts MusicXML → `.mscz`, validating the artifact rather than MuseScore's exit code |

  Reference material lives in `references/` (macOS install, Audiveris CLI,
  limitations + proofing + triage) and is read on demand.

## Requirements

The skill's `preflight.sh` checks all of these and tells you what's missing:

- **Audiveris** 5.5+ — no Homebrew cask exists; install the DMG manually, then
  install OCR language data via **Tools → Install languages…** (no installer has
  shipped language data since 5.5, and its absence fails *silently*)
- **MuseScore** 4.x — DMG from [musescore.org](https://musescore.org/download) or
  `brew install --cask musescore`. Note converter mode aborts with exit 134 after
  writing valid output on 4.7.4 (latest at time of writing); the upstream fix is
  merged but unreleased, so `to_mscz.sh` validates the output file instead
- **poppler** — `brew install poppler`
- **python3**

## License

MIT
