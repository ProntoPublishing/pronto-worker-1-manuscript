#!/usr/bin/env bash
# Canonical test runner — the ONLY sanctioned way to run this repo's
# suite in scripts or CI. `set -o pipefail` + explicit exit propagation
# make it impossible to report green over a red test, even when output
# is piped (the 2026-07-18 masked-exit lesson: `unittest | tail`
# swallows the failure code without this).
set -euo pipefail
python -m unittest discover -s tests -v "$@"
