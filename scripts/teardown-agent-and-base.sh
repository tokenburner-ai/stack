#!/usr/bin/env bash
# Deprecated wrapper — use the CLI instead:
#   printf 'destroy\n' | python3 tokenburner.py destroy --purge-retained
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
printf 'destroy\n' | python3 tokenburner.py destroy --purge-retained
