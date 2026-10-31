#!/bin/bash
# Optional: fetch the Inter font. script.py falls back to DejaVu Sans (already
# installed on ubuntu-latest) if this fails, so a failed download never breaks the build.
#
# The URL points at one fixed commit of google/fonts (not "main"), and the file's
# SHA-256 fingerprint is checked, so the build only ever uses this exact font file.
# To update the font: pick a newer commit, change FONTS_COMMIT, and put the new
# file's "sha256sum" in INTER_SHA256.
FONTS_COMMIT="6c1dbe27dcf7d817d4b62cec033ba77fa8e2a5ec"
INTER_SHA256="29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031"

mkdir -p fonts
URL="https://github.com/google/fonts/raw/${FONTS_COMMIT}/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf"
if curl -fsSL --max-time 30 -o fonts/Inter.ttf "$URL" \
   && echo "${INTER_SHA256}  fonts/Inter.ttf" | sha256sum --check --status; then
  echo "Inter font downloaded and verified"
else
  rm -f fonts/Inter.ttf
  echo "Inter download failed or did not match the expected file; using fallback font"
fi
exit 0
