#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
bash build.sh
exec "${PYTHON:-python3}" -m unittest discover -s tests -t . -v
