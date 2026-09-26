#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
trap 'echo "Setup stopped. Read the error above and README.md. No files were deleted."' ERR
python3 -c "import sys; assert sys.version_info >= (3,11), 'Install Python 3.11+ from python.org'"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if [ ! -f .venv/.oriori_ready ]; then
  echo '[oriori_gsr] First setup needs an internet connection.'
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  echo '1.0' > .venv/.oriori_ready
fi
echo '[oriori_gsr] Keep this terminal open. Ctrl+C stops the booth.'
.venv/bin/python app.py
