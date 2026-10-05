#!/usr/bin/env bash
# ==============================================================================
# build_tardis_linux.sh - Compilador Maestro del Paquete Nativo Linux de TARDIS
# ==============================================================================
# Genera el ejecutable autónomo para Ubuntu Linux usando PyInstaller en .venv-linux.
# ==============================================================================

set -e

C_RESET="\033[0m"
C_CYAN="\033[96m"
C_GREEN="\033[92m"
C_YELLOW="\033[93m"
C_RED="\033[91m"
C_BOLD="\033[1m"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo -e "${C_CYAN}${C_BOLD}"
echo "=============================================================================="
echo "   COMPILADOR SOBERANO TARDIS v26.4 · LINUX NATIVO (UBUNTU x86_64)            "
echo "=============================================================================="
echo -e "${C_RESET}"

PYTHON_EXE="$DIR/.venv-linux/bin/python3"
if [ ! -x "$PYTHON_EXE" ]; then
    PYTHON_EXE="$(command -v python3)"
fi

echo -e "Utilizando intérprete: ${C_GREEN}$PYTHON_EXE${C_RESET}"

# 1. Limpieza de residuos de compilaciones previas
echo -e "${C_YELLOW}[1/3] Limpiando residuos temporales...${C_RESET}"
rm -rf build dist/TARDIS-v26.4-Linux
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

# 2. Ejecutar PyInstaller
echo -e "${C_YELLOW}[2/3] Compilando suite TARDIS con PyInstaller...${C_RESET}"
"$PYTHON_EXE" -m PyInstaller \
    --name="TARDIS-v26.4-Linux" \
    --distpath="$DIR/dist" \
    --onedir \
    --clean \
    --noconfirm \
    --add-data "$DIR/index.html:." \
    --add-data "$DIR/companion_overlay.html:." \
    --add-data "$DIR/gia_context_matrix.json:." \
    --add-data "$DIR/agent_context.py:." \
    --add-data "$DIR/tardis-icon.png:." \
    --add-data "$DIR/godworks-icon.png:." \
    --add-data "$DIR/tardis_app.py:." \
    --add-data "$DIR/tardis_desktop_companion.py:." \
    --add-data "$DIR/launch_tardis.sh:." \
    --add-data "$DIR/launch_tardis_companion.sh:." \
    --add-data "$DIR/tardis_command.sh:." \
    --add-data "$DIR/tardis_cli.py:." \
    --add-data "$DIR/native_gui:native_gui" \
    --add-data "$DIR/core:core" \
    --add-data "$DIR/server:server" \
    --add-data "$DIR/telemetry:telemetry" \
    --hidden-import="server" \
    --hidden-import="server.api" \
    --hidden-import="httpx" \
    --hidden-import="httpcore" \
    --hidden-import="websockets" \
    --hidden-import="agent_context" \
    --hidden-import="gia_memory" \
    --hidden-import="geon_causal_engine" \
    --hidden-import="sensor_telemetry" \
    --hidden-import="em_spectrum_engine" \
    --hidden-import="rf_noise_binary_engine" \
    --hidden-import="agent_safety" \
    --hidden-import="vlm_visual_guard" \
    --hidden-import="autonomous_voice" \
    --hidden-import="web_chat" \
    --hidden-import="voice" \
    --hidden-import="pdf_processor" \
    --hidden-import="rf_presence_radar" \
    --hidden-import="ios_bridge" \
    --hidden-import="screen_reader" \
    --hidden-import="self_improve" \
    --hidden-import="self_modify" \
    --hidden-import="whatsapp_bridge" \
    --hidden-import="start_bridge" \
    --hidden-import="ecca_orchestrator" \
    --hidden-import="ecca_credentials" \
    --hidden-import="ecca_fft_engine" \
    --hidden-import="distributed_compute" \
    --hidden-import="install_context_matrix" \
    --hidden-import="device_sensors" \
    --hidden-import="gia_agent" \
    --hidden-import="tool_selector" \
    --hidden-import="voice_assistant" \
    --hidden-import="deep_search" \
    --hidden-import="supervisor" \
    --hidden-import="antigravity_bridge" \
    --hidden-import="gia_bootstrap" \
    --hidden-import="gia_sovereign_engine" \
    --hidden-import="gia_sovereign_bridge" \
    --hidden-import="gia_direct_local" \
    --hidden-import="gia_self_test" \
    --hidden-import="gemini_bridge" \
    --hidden-import="gemini_privacy_vault" \
    --hidden-import="gia_control" \
    --hidden-import="gia_launcher" \
    --hidden-import="gia_sales_presentation" \
    --hidden-import="gia_subconscious" \
    --hidden-import="gia_swarm" \
    --hidden-import="start_tunnel" \
    --hidden-import="colibri_optimizer" \
    --hidden-import="colibri_bridge" \
    --hidden-import="sqlite3" \
    --hidden-import="json" \
    --hidden-import="psutil" \
    --hidden-import="numpy" \
    --hidden-import="cryptography" \
    --hidden-import="rich" \
    --hidden-import="core.tardis_error_sentinel" \
    --hidden-import="core.chinese_cloud_api" \
    --hidden-import="core.interaction_logger" \
    --hidden-import="core.individual_tracker" \
    --hidden-import="core.os_controller" \
    --hidden-import="core.autonomous_controller" \
    --hidden-import="core.button_orchestrator" \
    --hidden-import="core.terminal_camera_hub" \
    --hidden-import="core.inter_ai_protocol" \
    --hidden-import="core.thought_noise_engine" \
    --hidden-import="core.speaking_video_generator" \
    --hidden-import="core.sensor_orchestrator" \
    --hidden-import="core.auto_context_synchronizer" \
    --hidden-import="core.background_thought_engine" \
    --hidden-import="core.deep_memory_vault" \
    --hidden-import="core.network_shield" \
    --hidden-import="core.offline_chat_vault" \
    --hidden-import="core.traffic_monitor" \
    --hidden-import="core.hotspot_watchdog" \
    --hidden-import="core.package_manager" \
    --hidden-import="core.web_research_engine" \
    --hidden-import="core.autonomous_coder" \
    --hidden-import="core.idle_evolution_daemon" \
    --hidden-import="telemetry" \
    --hidden-import="telemetry.camera_grabber" \
    "$DIR/omni_temporal_control.py"

# 3. Post-Limpieza
echo -e "${C_YELLOW}[3/3] Post-limpieza de artefactos temporales...${C_RESET}"
rm -rf build
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo ""
echo -e "${C_GREEN}${C_BOLD}==============================================================================${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}   BUILD EXITOSO: dist/TARDIS-v26.4-Linux/TARDIS-v26.4-Linux                 ${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}==============================================================================${C_RESET}"
