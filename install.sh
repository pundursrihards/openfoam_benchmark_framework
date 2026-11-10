#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
PYTHON="${PYTHON:-python3}"
"$PYTHON" -m venv .venv
. .venv/bin/activate
# Optional extras: ./install.sh analysis   or   ./install.sh casefoam
# Both may be installed together with: ./install.sh analysis,casefoam
if [[ $# -gt 0 ]]; then
  python -m pip install -e ".[${1}]"
else
  python -m pip install -e .
fi
python -m foambench.cli doctor --config config/run.yaml
printf '\nInstalled. Run ./fetchCases.sh then ./Allrun --dry-run\n'
