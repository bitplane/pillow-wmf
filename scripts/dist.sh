#!/bin/bash

set -euo pipefail
source .venv/bin/activate

mkdir -p dist
# Only remove generated distribution archives, not unrelated user files.
find dist -maxdepth 1 -type f \( -name '*.whl' -o -name '*.tar.gz' \) -delete
python -m build .
