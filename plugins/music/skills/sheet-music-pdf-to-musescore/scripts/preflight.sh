#!/usr/bin/env bash
# Preflight for sheet-music-pdf-to-musescore.
# Checks every tool the workflow actually invokes, then reports what is missing.
#
# Deliberately does NOT launch MuseScore: converter mode starts a real Qt app
# that steals window focus, so we only check the binary is present.
#
# Exit 0 = ready. Exit 1 = something required is missing.

set -uo pipefail

miss_required=0
miss_optional=0

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok       %s\n' "$*"; }
bad()  { printf '  MISSING  %s\n' "$*"; }
warn() { printf '  warn     %s\n' "$*"; }

say "== Audiveris (OMR engine) =="
AUDIVERIS_BIN=""
if [ -d /Applications/Audiveris.app ]; then
  # jpackage names the executable after the app; confirm rather than assume.
  AUDIVERIS_BIN=$(find /Applications/Audiveris.app/Contents/MacOS -maxdepth 1 -type f -perm -u+x 2>/dev/null | head -1)
  if [ -n "$AUDIVERIS_BIN" ]; then
    ok "$AUDIVERIS_BIN"
  else
    bad "Audiveris.app present but no executable in Contents/MacOS"
    miss_required=1
  fi
else
  bad "/Applications/Audiveris.app  -> see references/install-macos.md"
  miss_required=1
fi

say "== OCR language data (Tesseract, legacy models) =="
# Audiveris checks TESSDATA_PREFIX first, else a tessdata dir under its user
# config folder, which it creates on the fly (so existing-but-empty is normal).
TESSDATA=""
if [ -n "${TESSDATA_PREFIX:-}" ] && [ -d "${TESSDATA_PREFIX:-}" ]; then
  TESSDATA="$TESSDATA_PREFIX"
  warn "TESSDATA_PREFIX is set and takes precedence: $TESSDATA"
else
  TESSDATA=$(find "$HOME/Library/Application Support" -maxdepth 4 -type d -name tessdata 2>/dev/null | head -1)
fi
if [ -n "$TESSDATA" ] && compgen -G "$TESSDATA/*.traineddata" >/dev/null 2>&1; then
  ok "$TESSDATA"
  # Glob-loop rather than `ls | xargs basename`: the tessdata path contains
  # "Application Support", and word splitting turns that space into a bogus entry.
  printf '           languages:'
  for f in "$TESSDATA"/*.traineddata; do
    base=${f##*/}
    printf ' %s' "${base%.traineddata}"
  done
  printf '\n'
else
  bad "no *.traineddata found${TESSDATA:+ in $TESSDATA}"
  warn "install in the GUI: Tools -> Install languages...  (no installer ships language data since 5.5)"
  warn "without it, lyrics / tempo text / chord names fail SILENTLY"
  miss_required=1
fi

say "== MuseScore (MusicXML -> .mscz) =="
MSCORE=$(find /Applications -maxdepth 4 -type f -name mscore -path '*MuseScore*' 2>/dev/null | head -1)
if [ -n "$MSCORE" ]; then
  ok "$MSCORE"
else
  bad "MuseScore not found  -> brew install --cask musescore"
  miss_required=1
fi

say "== poppler (PDF assessment, step 1) =="
for t in pdfinfo pdfimages pdftoppm; do
  if command -v "$t" >/dev/null 2>&1; then
    ok "$t"
  else
    bad "$t  -> brew install poppler"
    miss_required=1
  fi
done

say "== python3 (MusicXML inspection, step 3) =="
if command -v python3 >/dev/null 2>&1; then
  ok "$(python3 --version 2>&1)"
else
  bad "python3  -> brew install python"
  miss_required=1
fi

say "== optional =="
if command -v waifu2x-ncnn-vulkan >/dev/null 2>&1; then
  ok "waifu2x-ncnn-vulkan (upscaling unrecoverable low-res scans)"
else
  warn "waifu2x-ncnn-vulkan absent - only needed to rescue a low-res scan"
  miss_optional=1
fi

say ""
if [ "$miss_required" -eq 0 ]; then
  say "READY. Export paths for the run:"
  say "  AUDIVERIS=\"$AUDIVERIS_BIN\""
  say "  MSCORE=\"$MSCORE\""
  exit 0
fi
say "NOT READY - resolve the MISSING items above before converting."
say "Install guidance: references/install-macos.md"
exit 1
