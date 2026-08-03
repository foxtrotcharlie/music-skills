#!/usr/bin/env bash
# MusicXML -> .mscz via MuseScore's converter mode, judged on the OUTPUT rather
# than the exit code.
#
# Why this wrapper exists: MuseScore writes a complete, valid .mscz and THEN
# intermittently aborts (SIGABRT, exit 134). Trusting $? reports failure on a
# perfectly good conversion and kills any `set -e` caller.
#
# The upstream fix (PR #34136) is merged but UNRELEASED - 4.7.4 is still the
# latest release - so validating the artifact is the only mitigation available.
#
# Do NOT "fix" that with QT_QPA_PLATFORM=offscreen: macOS ships no offscreen Qt
# plugin, so MuseScore fails to start and produces no output at all.
#
# Usage:  to_mscz.sh INPUT.{xml,musicxml,mxl} OUTPUT.mscz [extra mscore args...]
# Exit:   0 = output exists and validates. 1 = genuinely failed.

set -uo pipefail

if [ "$#" -lt 2 ]; then
  sed -n '2,20p' "$0"
  exit 2
fi

IN="$1"; OUT="$2"; shift 2

[ -f "$IN" ] || { echo "FAIL  input not found: $IN"; exit 1; }

MSCORE="${MSCORE:-}"
if [ -z "$MSCORE" ]; then
  MSCORE=$(find /Applications -maxdepth 4 -type f -name mscore -path '*MuseScore*' 2>/dev/null | head -1)
fi
[ -n "$MSCORE" ] && [ -x "$MSCORE" ] || {
  echo "FAIL  mscore not found; set MSCORE=/path/to/mscore"; exit 1; }

rm -f "$OUT"

echo "note  MuseScore converter mode starts a real Qt app, not a headless process."
echo "      An abort after writing valid output is a known, still-unreleased bug."

LOG=$(mktemp -t to_mscz)
# -f suppresses the corruption / version-mismatch warnings OMR output can trigger.
#
# Run mscore under an inner `bash -c` rather than directly: when a foreground
# child dies from SIGABRT, the shell that WAITS on it prints "Abort trap: 6" to
# its own stderr. Letting the inner shell do the waiting means that notice goes
# to /dev/null, and this script sees an ordinary exit status (134) instead of a
# signal - so nothing alarming lands next to the success line.
bash -c 'm=$1; o=$2; i=$3; l=$4; shift 4; "$m" -f -o "$o" "$i" "$@" >"$l" 2>&1' \
  _ "$MSCORE" "$OUT" "$IN" "$LOG" "$@" 2>/dev/null
rc=$?

# --- judge the artifact, not the exit code ---------------------------------
if [ ! -s "$OUT" ]; then
  echo "FAIL  no output written (mscore exit $rc)"
  echo "--- last log lines ---"; tail -5 "$LOG"; rm -f "$LOG"
  exit 1
fi

if ! unzip -tqq "$OUT" >/dev/null 2>&1; then
  echo "FAIL  $OUT is not a readable zip (mscore exit $rc)"
  rm -f "$LOG"; exit 1
fi

# Capture then match, rather than piping into `grep -q`: grep -q exits on the
# first hit, SIGPIPEs unzip, and under `set -o pipefail` that intermittently
# reports failure on a perfectly good archive.
listing=$(unzip -l "$OUT" 2>/dev/null || true)
case "$listing" in
  *.mscx*) ;;
  *) echo "FAIL  $OUT contains no .mscx score payload (mscore exit $rc)"
     rm -f "$LOG"; exit 1 ;;
esac

payload=$(unzip -p "$OUT" '*.mscx' 2>/dev/null || true)
notes=$(printf '%s' "$payload" | grep -c '<Note>' || true)
size=$(wc -c <"$OUT" | tr -d ' ')

if [ "$rc" -eq 0 ]; then
  echo "ok    $OUT  (${size} bytes, ${notes} notes)"
else
  echo "ok    $OUT  (${size} bytes, ${notes} notes)"
  echo "      mscore exited $rc after writing valid output - known crash-on-quit"
  echo "      bug (fix merged upstream, not yet released). Output verified above."
fi

if [ "$notes" -eq 0 ]; then
  echo "warn  no <Note> elements in the result - check the input actually had music"
fi

rm -f "$LOG"
exit 0
