#!/usr/bin/env bash
# ==============================================================================
# start_ubuntu.sh - Lanzador Maestro de GODWORKS SYSTEM v26.4 en Ubuntu Linux
# ==============================================================================

set -e

C_RESET="\033[0m"
C_CYAN="\033[96m"
C_GREEN="\033[92m"
C_YELLOW="\033[93m"
C_RED="\033[91m"
C_MAGENTA="\033[95m"
C_BOLD="\033[1m"
C_DIM="\033[90m"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Localizar intérprete de Python
if [ -x "$SCRIPT_DIR/.venv-linux/bin/python3" ]; then
    PYTHON_EXE="$SCRIPT_DIR/.venv-linux/bin/python3"
elif [ -x "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON_EXE="$SCRIPT_DIR/.venv/bin/python3"
else
    PYTHON_EXE="$(command -v python3)"
fi

echo -e "${C_CYAN}${C_BOLD}"
echo "=============================================================================="
echo "         GODWORKS SYSTEM v26.4 - LANZADOR NATIVO UBUNTU LINUX                "
echo "=============================================================================="
echo -e "${C_RESET}"
echo -e "Directorio base: ${C_DIM}$SCRIPT_DIR${C_RESET}"
echo -e "Intérprete:      ${C_GREEN}$PYTHON_EXE${C_RESET}"
echo -e "Dirección IP:    ${C_GREEN}$(hostname -I | awk '{print $1}')${C_RESET}"
echo ""

show_menu() {
    echo -e "${C_BOLD}Selecciona el modo de arranque:${C_RESET}"
    echo -e "  ${C_GREEN}1)${C_RESET} Iniciar Suite Completa (Supervisor + Servidor Web + Control Temporal) ${C_DIM}[Recomendado]${C_RESET}"
    echo -e "  ${C_CYAN}2)${C_RESET} Iniciar Servidor Web Dashboard (gia_web_server.py en :8757)"
    echo -e "  ${C_CYAN}3)${C_RESET} Iniciar Servidor Maestro Temporal (omni_temporal_control.py)"
    echo -e "  ${C_CYAN}4)${C_RESET} Iniciar Puente de Internet Resiliente (start_bridge.py)"
    echo -e "  ${C_MAGENTA}5)${C_RESET} Iniciar Agente Autónomo GIA Interactivo (gia_agent.py)"
    echo -e "  ${C_YELLOW}6)${C_RESET} Diagnóstico de Sensores RF, Térmicos y Hardware"
    echo -e "  ${C_YELLOW}7)${C_RESET} Iniciar Motor Local Colibri (./colibri/coli chat)"
    echo -e "  ${C_RED}0)${C_RESET} Salir"
    echo ""
}

# Auto-selección tras 10 segundos o lectura interactiva
show_menu
read -t 15 -p "Opción [1-7, por defecto 1]: " OPTION || OPTION="1"
echo ""

case "$OPTION" in
    2)
        echo -e "${C_CYAN}Iniciando gia_web_server.py...${C_RESET}"
        exec "$PYTHON_EXE" "$SCRIPT_DIR/gia_web_server.py" --port 8757
        ;;
    3)
        echo -e "${C_CYAN}Iniciando omni_temporal_control.py...${C_RESET}"
        exec "$PYTHON_EXE" "$SCRIPT_DIR/omni_temporal_control.py"
        ;;
    4)
        echo -e "${C_CYAN}Iniciando start_bridge.py...${C_RESET}"
        exec "$PYTHON_EXE" "$SCRIPT_DIR/start_bridge.py" --port 8757
        ;;
    5)
        echo -e "${C_MAGENTA}Iniciando gia_agent.py en consola interactiva...${C_RESET}"
        exec "$PYTHON_EXE" "$SCRIPT_DIR/gia_agent.py" --interactive
        ;;
    6)
        echo -e "${C_YELLOW}Ejecutando diagnóstico integral de hardware y sensores RF (1.0s)...${C_RESET}"
        "$PYTHON_EXE" -c "
import colibri_optimizer as co
import rf_noise_binary_engine as rnb
import rf_presence_radar as rpr
print('--- 1. TOPOLOGÍA DE HARDWARE ---')
opt = co.HardwareSensor()
print('CPU:', opt.get_cpu_info())
print('RAM:', opt.get_memory_info())
print('GPU:', opt.get_gpu_info())
print('Disco:', opt.get_storage_info())
print('\n--- 2. RADAR RF PASIVO (1sg) ---')
radar = rpr.get_radar()
state = radar.scan_burst(1.0)
print('Estado:', state.presence_state, '| Ventana:', state.capture_duration_s, 's | Tasa:', state.sample_rate_hz, 'Hz | Var/s:', state.variance_rate_per_sec)
print('\n--- 3. ESPECTRO MULTI-SENSOR Y RUIDO EM BINARIO ---')
data = rnb.read_all_spectrum_sensors(1.0)
print('Tiempo de escaneo:', data.get('elapsed_s'), 's')
print('Wi-Fi redes:', len(data.get('wifi_spectrum', {}).get('networks', [])))
print('Bluetooth:', data.get('bluetooth_spectrum', {}).get('activity_level'), '| Nodos:', data.get('bluetooth_spectrum', {}).get('total_nodes'))
print('Térmico:', data.get('thermal_sensors', {}).get('summary'))
print('Binario:', data.get('binary_noise_quantization', {}).get('bitrate_bps'), 'bps | H:', data.get('binary_noise_quantization', {}).get('shannon_entropy_bits'))
"
        ;;
    7)
        if [ -x "$SCRIPT_DIR/colibri/coli" ]; then
            echo -e "${C_YELLOW}Iniciando Colibri...${C_RESET}"
            exec "$SCRIPT_DIR/colibri/coli" chat
        else
            echo -e "${C_RED}Error: $SCRIPT_DIR/colibri/coli no encontrado o sin permisos de ejecución.${C_RESET}"
            exit 1
        fi
        ;;
    0)
        echo "Saliendo..."
        exit 0
        ;;
    1|*)
        echo -e "${C_GREEN}Iniciando Suite Completa bajo supervisión activa (supervisor.py)...${C_RESET}"
        exec "$PYTHON_EXE" "$SCRIPT_DIR/supervisor.py"
        ;;
esac
