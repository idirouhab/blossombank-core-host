#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
if [[ ! -x build/bin/entrychk || ! -x build/bin/balctl || ! -x build/bin/intrcalc || ! -x build/bin/legacyamt || ! -x build/bin/acctunld ]]; then
  bash build.sh
fi
exec "${PYTHON:-python3}" -m hostbridge serve "$@"
