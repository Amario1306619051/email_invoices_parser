#!/usr/bin/env bash
# Install Python deps into the shared venv and the Tesseract binary on the host.
set -euo pipefail

VENV="/home/rnd/Documents/Belajar/Portofolio_tambbahan/venv"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -x "$VENV/bin/pip" ]; then
  echo "venv pip not found at $VENV/bin/pip" >&2
  exit 1
fi

echo "==> Installing Python packages into $VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

if ! command -v tesseract >/dev/null 2>&1; then
  echo "==> Tesseract not found. Install with:"
  echo "    sudo apt update && sudo apt install -y tesseract-ocr tesseract-ocr-ind poppler-utils"
else
  echo "==> Tesseract OK: $(tesseract --version | head -n1)"
fi

if [ ! -f "$SCRIPT_DIR/.env" ]; then
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
  echo "==> Created .env from template. Fill in API keys + credential paths."
fi

echo "Done. Activate the venv with: source $VENV/bin/activate"
