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
  editable MuseScore/MusicXML notation using Audiveris OMR. Covers preflight
  checks, sampling before a full run, inspecting and repairing the resulting
  MusicXML, converting to `.mscz`, and a proofing checklist for the parts OMR
  commonly gets wrong (rhythms, ties vs. slurs, voices, accidentals, repeats).

## License

MIT
