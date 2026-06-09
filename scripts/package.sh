#!/usr/bin/env bash
set -euo pipefail

ADDON_DIR="auto_seam_uv_equalizer"
ZIP_NAME="auto_seam_uv_equalizer.zip"

if [ ! -d "$ADDON_DIR" ]; then
  echo "Addon folder not found: $ADDON_DIR" >&2
  exit 1
fi

find . -name "__pycache__" -type d -prune -exec rm -rf {} +
find . -name "*.pyc" -delete

rm -f "$ZIP_NAME"
zip -r "$ZIP_NAME" "$ADDON_DIR" -x "*/__pycache__/*" "*.pyc"

echo "Created $ZIP_NAME"
echo "Check structure with:"
echo "unzip -l $ZIP_NAME"
