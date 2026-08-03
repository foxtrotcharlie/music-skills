# Installing the toolchain (macOS)

Read this when `scripts/preflight.sh` reports something missing.

## Audiveris

**There is no Homebrew cask** — checked, none exists. Installation is manual and
needs GUI interaction, so don't attempt it unattended. Hand the user these steps:

1. Download the installer for their chip from
   <https://github.com/Audiveris/audiveris/releases> — `…-macosx-arm64.dmg` for
   Apple Silicon, `…-x86_64.dmg` for Intel. Take whatever is latest (5.11.0,
   released 2026-07-11, was current when this skill was written).
2. Open the DMG, drag `Audiveris.app` to `/Applications`.
3. The app is **not signed with an Apple Developer certificate**, so Gatekeeper
   blocks the first launch. Open it, get refused, then allow it under
   System Settings → Privacy & Security → "Open Anyway". On Tahoe the dialog
   differs — press "Done" first.
4. **No separate Java install needed.** Since 5.5, installers bundle their own JRE.

The macOS CLI path is `/Applications/Audiveris.app/Contents/MacOS/Audiveris`.
Note this is *inferred* from jpackage's standard app-image layout (the handbook
documents CLI paths for Windows and Linux only, never macOS) — which is exactly
why preflight discovers the executable with `find` instead of hardcoding it.

## OCR language data — install this before converting anything

**No installer has shipped Tesseract language data since 5.5.** Without it,
lyrics, tempo text, and chord names fail **silently** — you get a clean-looking
result with the text missing.

Install from the GUI: **Tools → Install languages…** Download `eng`, plus the
score's language if it isn't English.

> The handbook labels this menu item "Tools → Languages", but the application's
> own resource string is `Install languages...`. Trust the app.

Prefer the in-app downloader. Audiveris runs Tesseract in **legacy** mode
(`OEM_TESSERACT_ONLY`), so hand-installed data must be the *legacy* model, not
LSTM — a mismatch is a common failure, and the downloader gets it right.

Where the data lands, in Audiveris's own order of precedence:

1. `$TESSDATA_PREFIX`, if set **and** pointing at a real directory — this wins.
2. Otherwise a `tessdata` directory under the OS-dependent Audiveris user config
   folder, created on the fly if absent (so "exists but empty" is normal).

Don't set `TESSDATA_PREFIX` yourself without a specific reason; Audiveris manages
its own folder fine, and setting it silently overrides the data the GUI installed.

## MuseScore

Either the DMG from <https://musescore.org/download> or Homebrew
(`brew install --cask musescore`) is fine. If it was installed from the DMG,
`brew upgrade` won't manage it — update in-app or by DMG.

The CLI binary is at `/Applications/MuseScore 4.app/Contents/MacOS/mscore`
(confirmed on 4.7.4; `CFBundleExecutable` is `mscore`). **MuseScore 3 also named
its binary `mscore`**, so discriminate by the `.app` bundle name rather than the
executable, and always quote the path — it contains a space.

**Expect converter mode to abort with exit 134** after writing valid output. The
fix is merged upstream for 4.7.5 but unreleased (4.7.4, 2026-07-07, is latest),
so no upgrade avoids it yet — `scripts/to_mscz.sh` validates the artifact instead.

## poppler

```bash
brew install poppler
```

Provides `pdfinfo`, `pdfimages`, and `pdftoppm`, which step 1 depends on. Not
present by default on macOS.

## waifu2x (optional)

Only needed to rescue a scan that can't be redone. See the upscaling notes in
`references/audiveris-cli.md`.

## FreeType — probably not your problem

The handbook lists FreeType as a prerequisite for **building Audiveris from
source**, needed for PDFs containing vector graphics. It is *not* listed as a
requirement for the bundled DMG installer. Don't send users chasing it unless
they're building from source.
