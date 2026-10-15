#!/usr/bin/env bash
# ==============================================================================
# launch_native.sh - Enlace de compatibilidad hacia la aplicación unificada Tardis
# ==============================================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/launch_tardis.sh" "$@"
