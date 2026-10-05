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
echo "   COMPILADOR SOBERANO TARDIS · LINUX NATIVO (UBUNTU x86_64)                  "
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
    --add-data "$DIR/client_chat.html:." \
    --add-data "$DIR/companion_overlay.html:." \
    --add-data "$DIR/gia_context_matrix.json:." \
    --add-data "$DIR/agent_context.py:." \
    --add-data "$DIR/tardis-icon.png:." \
    --add-data "$DIR/godworks-icon.png:." \
    --add-data "$DIR/tardis_app.py:." \
    --add-data "$DIR/tardis_desktop_companion.py:." \
    --add-data "$DIR/tardis_master_app.py:." \
    --add-data "$DIR/launch_tardis_master_hub.sh:." \
    --add-data "$DIR/tardis-master-hub-icon.png:." \
    --add-data "$DIR/Tardis-Master-Hub.desktop:." \
    --add-data "$DIR/temporal_brain_config.json:." \
    --add-data "$DIR/launch_tardis.sh:." \
    --add-data "$DIR/launch_tardis_companion.sh:." \
    --add-data "$DIR/tardis_command.sh:." \
    --add-data "$DIR/tardis_cli.py:." \
    --add-data "$DIR/share_client_link.py:." \
    --add-data "$DIR/optimize_os.sh:." \
    --add-data "$DIR/client_user_manager.html:." \
    --add-data "$DIR/bridge_dashboard.html:." \
    --add-data "$DIR/offline_chat_vault.html:." \
    --add-data "$DIR/tardis_master_cockpit.html:." \
    --add-data "$DIR/client_gateway.py:." \
    --add-data "$DIR/start_client_gateway.sh:." \
    --add-data "$DIR/mobile_terminal:mobile_terminal" \
    --add-data "$DIR/web:web" \
    --add-data "$DIR/native_gui:native_gui" \
    --add-data "$DIR/Modelfile.kaiju:." \
    --add-data "$DIR/core:core" \
    --add-data "$DIR/server:server" \
    --add-data "$DIR/telemetry:telemetry" \
    --hidden-import="core.rag_vault" \
    --hidden-import="core.knowledge_graph" \
    --hidden-import="core.atmospheric_sensor" \
    --hidden-import="core.video_pipeline_4k" \
    --hidden-import="core.character_3d_renderer" \
    --hidden-import="core.causal_prompt_graph" \
    --hidden-import="client_gateway" \
    --hidden-import="jinja2" \
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
    --hidden-import="core.temporal_brain" \
    --hidden-import="core.sovereign_local_runner" \
    --hidden-import="core.ai_improvement_sandbox" \
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
    --hidden-import="core.mission_scouting_engine" \
    --hidden-import="core.telegram_bridge" \
    --hidden-import="core.render_3d_engine" \
    --hidden-import="core.protected_users_vault" \
    --hidden-import="core.sms_bridge" \
    --hidden-import="core.emotional_presence_agent" \
    --hidden-import="core.daily_context_rotator" \
    --hidden-import="core.os_optimizer" \
    --hidden-import="core.sovereign_neural_engine" \
    --hidden-import="core.kaiju_cognitive_orchestrator" \
    --hidden-import="core.hardware_controller" \
    --hidden-import="core.network_controller" \
    --hidden-import="core.task_manager" \
    --hidden-import="core.background_hardware_orchestrator" \
    --hidden-import="core.autonomous_existence_learner" \
    --hidden-import="core.physical_presence_sensor" \
    --hidden-import="core.agent_harness" \
    --hidden-import="core.whatsapp_bridge" \
    --hidden-import="core.ip_vault" \
    --hidden-import="core.device_vault" \
    --hidden-import="core.security" \
    --hidden-import="core.config" \
    --hidden-import="telemetry" \
    --hidden-import="telemetry.camera_grabber" \
    "$DIR/omni_temporal_control.py"

# Copiar archivos maestros del Hub y Gateway al directorio compilado
echo -e "${C_CYAN}[+] Inyectando lanzadores y componentes de TARDIS Master Hub y Gateway...${C_RESET}"
cp -f "$DIR/launch_tardis_master_hub.sh" "$DIR/dist/TARDIS-v26.4-Linux/"
cp -f "$DIR/tardis_master_app.py" "$DIR/dist/TARDIS-v26.4-Linux/"
cp -f "$DIR/tardis-master-hub-icon.png" "$DIR/dist/TARDIS-v26.4-Linux/"
cp -f "$DIR/Tardis-Master-Hub.desktop" "$DIR/dist/TARDIS-v26.4-Linux/"
cp -f "$DIR/temporal_brain_config.json" "$DIR/dist/TARDIS-v26.4-Linux/"
cp -f "$DIR/start_client_gateway.sh" "$DIR/dist/TARDIS-v26.4-Linux/" 2>/dev/null || true
cp -f "$DIR/client_gateway.py" "$DIR/dist/TARDIS-v26.4-Linux/" 2>/dev/null || true
cp -rf "$DIR/mobile_terminal" "$DIR/dist/TARDIS-v26.4-Linux/" 2>/dev/null || true
chmod +x "$DIR/dist/TARDIS-v26.4-Linux/launch_tardis_master_hub.sh" 2>/dev/null || true
chmod +x "$DIR/dist/TARDIS-v26.4-Linux/start_client_gateway.sh" 2>/dev/null || true

# 3. Empaquetado Soberano (Tarball de Distribución)
echo -e "${C_CYAN}[3/4] Empaquetando distribución soberana en dist/TARDIS-Master-Hub-Linux.tar.gz...${C_RESET}"
tar -czf "$DIR/dist/TARDIS-Master-Hub-Linux.tar.gz" -C "$DIR/dist" TARDIS-v26.4-Linux
cp -f "$DIR/dist/TARDIS-Master-Hub-Linux.tar.gz" "$DIR/dist/TARDIS-Linux-Sovereign.tar.gz"
cp -f "$DIR/dist/TARDIS-Master-Hub-Linux.tar.gz" "$DIR/dist/TARDIS-v26.4-Linux-Sovereign.tar.gz"
PKG_SIZE=$(du -h "$DIR/dist/TARDIS-Master-Hub-Linux.tar.gz" | cut -f1)
echo -e "${C_GREEN}✓ Paquete TARDIS Master Hub generado con éxito: dist/TARDIS-Master-Hub-Linux.tar.gz (${PKG_SIZE})${C_RESET}"

# 4. Post-Limpieza
echo -e "${C_YELLOW}[4/4] Post-limpieza de artefactos temporales...${C_RESET}"
rm -rf build
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo ""
echo -e "${C_GREEN}${C_BOLD}==============================================================================${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}   BUILD EXITOSO: dist/TARDIS-v26.4-Linux/TARDIS-v26.4-Linux                 ${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}   PAQUETE: dist/TARDIS-Linux-Sovereign.tar.gz (${PKG_SIZE})                ${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}==============================================================================${C_RESET}"

