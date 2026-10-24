#!/bin/bash
# Auto-update TARDIS Portfolio
set -uo pipefail

echo "[$(date)] Running TARDIS Portfolio Builder to sanitize and copy files..."
python3 /home/timemachine/build_portfolio.py || echo "[$(date)] WARN: build_portfolio.py falló (rc=$?)"

cd /home/timemachine/TARDIS_Portfolio || exit 1

git add -A

if git diff-index --quiet HEAD --; then
    echo "[$(date)] No changes detected. Working tree is clean."
    exit 0
fi

git commit -m "Auto-update TARDIS Core: $(date)"
if push_out=$(git push origin main 2>&1); then
    echo "[$(date)] Push OK: $(git rev-parse --short HEAD)"
else
    rc=$?
    printf '%s\n' "$push_out" >&2
    echo "[$(date)] ERROR: push falló (rc=$rc); commits pendientes: $(git rev-list --count origin/main..HEAD)" >&2
    exit "$rc"
fi
