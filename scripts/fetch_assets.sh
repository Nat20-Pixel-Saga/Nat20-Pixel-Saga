#!/usr/bin/env bash
# Fetch third-party art, audio and fonts into vendor/ (not committed).
#
#   Ninja Adventure Asset Pack — Pixel-boy & AAA — CC0 1.0
#     https://pixel-boy.itch.io/ninja-adventure-asset-pack
#     fetched from a public GitHub copy of the full pack, pinned to a commit.
#   Pixelify Sans, Tiny5 — SIL Open Font License 1.1 — via github.com/google/fonts
#
# Usage: scripts/fetch_assets.sh          (idempotent; re-run to repair)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/vendor"
mkdir -p "$VENDOR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

NA_REPO="https://github.com/rinn7e/ninja-adventure-indigo.git"
NA_COMMIT="83268adcfc06ddf12f6a115577f533a3432539c7"
NA_PATH="assets/Ninja Adventure - Asset Pack"

FONTS_REPO="https://github.com/google/fonts.git"
FONTS_COMMIT="9710da1eacb3be272583c3224dcb70f9da6eadbb"

if [ ! -f "$VENDOR/ninja-adventure/LICENSE.txt" ]; then
  echo "Fetching Ninja Adventure Asset Pack (CC0)…"
  git clone -q --filter=blob:none --no-checkout "$NA_REPO" "$TMP/na"
  git -C "$TMP/na" sparse-checkout set --no-cone "$NA_PATH/*"
  git -C "$TMP/na" checkout -q "$NA_COMMIT"
  rm -rf "$VENDOR/ninja-adventure"
  mv "$TMP/na/$NA_PATH" "$VENDOR/ninja-adventure"
  grep -q "CC0 1.0 Universal" "$VENDOR/ninja-adventure/LICENSE.txt" || { echo "Licence check failed"; exit 1; }
fi

if [ ! -f "$VENDOR/fonts/PixelifySans.ttf" ] || [ ! -f "$VENDOR/fonts/Tiny5-Regular.ttf" ]; then
  echo "Fetching Pixelify Sans and Tiny5 (OFL 1.1)…"
  git clone -q --depth 1 --filter=blob:none --no-checkout "$FONTS_REPO" "$TMP/gf"
  git -C "$TMP/gf" sparse-checkout set --no-cone "ofl/pixelifysans/*" "ofl/tiny5/*"
  git -C "$TMP/gf" checkout -q HEAD
  mkdir -p "$VENDOR/fonts"
  cp "$TMP/gf/ofl/pixelifysans/PixelifySans[wght].ttf" "$VENDOR/fonts/PixelifySans.ttf"
  cp "$TMP/gf/ofl/pixelifysans/OFL.txt" "$VENDOR/fonts/PixelifySans-OFL.txt"
  cp "$TMP/gf/ofl/tiny5/Tiny5-Regular.ttf" "$VENDOR/fonts/Tiny5-Regular.ttf"
  cp "$TMP/gf/ofl/tiny5/OFL.txt" "$VENDOR/fonts/Tiny5-OFL.txt"
fi

echo "Assets ready in $VENDOR"
