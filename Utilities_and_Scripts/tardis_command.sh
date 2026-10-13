#!/usr/bin/env bash
# ==============================================================================
# TARDIS · FTL SOVEREIGN APEX SYSTEM v26.4
# Unified Self-Programmable Temporal System Entrypoint (tardis / godworks / gia)
# Unrestricted Autonomous Operations Across All Projects and Environments.
# ==============================================================================

export USER="timemachine"
export HOME="/home/timemachine"
export PATH="/home/timemachine/.local/bin:$PATH"
export PYTHONUNBUFFERED="1"
export FORCE_COLOR="1"
export CLAUDE_CODE_SKIP_PERMISSIONS="1"
export FTL_AUTONOMOUS="1"
export GIA_API_URL="${GIA_API_URL:-http://127.0.0.1:8757}"
export GIA_TOKEN="REDACTED"
export GIA_AUTH_TOKEN="REDACTED"
export GIA_MODEL="${GIA_MODEL:-TARDIS-NEURAL-SPACE-KAIJU}"

FTL_CLI="/home/timemachine/.ftl/ftl_cli.py"

if [ -f "$FTL_CLI" ]; then
    exec /usr/bin/python3 "$FTL_CLI" "$@"
fi

# Fallback failsafe
BASE="/home/timemachine/Escritorio/GODWORKS SYSTEM"
PYTHON="$BASE/.venv-linux/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="/usr/bin/python3"
fi
exec "$PYTHON" "$BASE/tardis_cli.py" "$@"
