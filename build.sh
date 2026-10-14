#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v cobc >/dev/null || { echo 'GnuCOBOL is required (cobc).' >&2; exit 1; }
mkdir -p build/bin
for source in cobol/programs/*.cob; do
  name="$(basename "$source" .cob)"
  cobc -x -free -Wall -I cobol/copybooks -o "build/bin/$name" "$source"
done
printf 'Compiled online and batch modules.\n'
