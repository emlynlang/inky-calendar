#!/bin/bash
# Optional: fetch the Inter font. script.py falls back to DejaVu Sans (already
# installed on ubuntu-latest) if this fails, so a failed download never breaks the build.
mkdir -p fonts
URL="https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf"
if curl -fsSL --max-time 30 -o fonts/Inter.ttf "$URL" \
   && [ "$(head -c 4 fonts/Inter.ttf | od -An -tx1 | tr -d ' \n')" = "00010000" ]; then
  echo "Inter font downloaded"
else
  rm -f fonts/Inter.ttf
  echo "Inter download failed; using fallback font"
fi
exit 0
