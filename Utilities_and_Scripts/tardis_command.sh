#!/usr/bin/env bash
# ==============================================================================
# tardis - Comando Universal de Terminal para TARDIS v26.4
# ==============================================================================
# Permite acceder a TARDIS desde cualquier terminal del sistema operativo.
# ==============================================================================

set -e

DIR="/home/timemachine/Escritorio/GODWORKS SYSTEM"
PORT="8757"
TOKEN = "REDACTED"
API_BASE="http://REDACTED_IP:$PORT"

C_RESET="\033[0m"
C_CYAN="\033[96m"
C_GREEN="\033[92m"
C_YELLOW="\033[93m"
C_RED="\033[91m"
C_GOLD="\033[38;5;220m"
C_BOLD="\033[1m"

show_banner() {
    echo -e "${C_CYAN}${C_BOLD}"
    echo "  ▲  T A R D I S  v 2 6 . 4"
    echo "  Nexo Temporal Soberano · Sistema Operativo Local"
    echo -e "${C_RESET}"
}

check_service_status() {
    if curl -s --max-time 2 "$API_BASE/api/health" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

start_daemon_if_needed() {
    if ! check_service_status; then
        echo -e "${C_YELLOW}⚡ Iniciando servicio TARDIS en segundo plano...${C_RESET}"
        if command -v systemctl >/dev/null 2>&1 && systemctl --user is-enabled tardis.service >/dev/null 2>&1; then
            systemctl --user start tardis.service || true
        else
            nohup "$DIR/start_tardis_daemon.sh" >/dev/null 2>&1 &
        fi
        for i in {1..15}; do
            if check_service_status; then
                echo -e "${C_GREEN}✓ Servicio TARDIS activo en puerto $PORT.${C_RESET}"
                return 0
            fi
            sleep 0.5
        done
        echo -e "${C_YELLOW}Aviso: El servicio tardó más de lo esperado en responder.${C_RESET}"
    fi
}

cmd="${1:-open}"

case "$cmd" in
    open|"")
        show_banner
        start_daemon_if_needed
        echo -e "${C_GREEN}🚀 Lanzando Interfaz Soberana de TARDIS...${C_RESET}"
        exec "$DIR/launch_tardis.sh"
        ;;

    companion|overlay|widget)
        show_banner
        start_daemon_if_needed
        echo -e "${C_CYAN}▲ Desplegando Asistente Flotante sobre el Sistema Operativo...${C_RESET}"
        exec "$DIR/launch_tardis_companion.sh"
        ;;

    status|health)
        show_banner
        echo -e "${C_BOLD}--- ESTADO DEL SISTEMA ---${C_RESET}"
        if check_service_status; then
            echo -e "Servidor TARDIS:    ${C_GREEN}● ACTIVO (http://REDACTED_IP:$PORT)${C_RESET}"
            HEALTH_JSON=$(curl -s "$API_BASE/api/health" || echo "{}")
            echo -e "Telemetría API:     ${C_CYAN}$HEALTH_JSON${C_RESET}"
        else
            echo -e "Servidor TARDIS:    ${C_RED}○ INACTIVO${C_RESET}"
        fi

        if curl -s --max-time 2 "http://REDACTED_IP:11434/api/tags" >/dev/null 2>&1; then
            echo -e "Motor Ollama:       ${C_GREEN}● ACTIVO (http://REDACTED_IP:11434)${C_RESET}"
        else
            echo -e "Motor Ollama:       ${C_YELLOW}○ INACTIVO o no responde${C_RESET}"
        fi

        if pgrep -f "tardis_desktop_companion.py" >/dev/null 2>&1; then
            echo -e "Asistente Flotante: ${C_GREEN}● ACTIVO sobre el Escritorio OS${C_RESET}"
        else
            echo -e "Asistente Flotante: ${C_YELLOW}○ En espera (ejecuta 'tardis companion')${C_RESET}"
        fi
        ;;

    start)
        echo -e "${C_CYAN}Iniciando TARDIS...${C_RESET}"
        systemctl --user start tardis.service 2>/dev/null || nohup "$DIR/start_tardis_daemon.sh" >/dev/null 2>&1 &
        sleep 1
        $0 status
        ;;

    stop)
        echo -e "${C_YELLOW}Deteniendo servicio TARDIS...${C_RESET}"
        systemctl --user stop tardis.service 2>/dev/null || true
        pkill -f "omni_temporal_control.py" || true
        echo -e "${C_GREEN}✓ TARDIS detenido.${C_RESET}"
        ;;

    restart)
        echo -e "${C_YELLOW}Reiniciando servicio TARDIS...${C_RESET}"
        $0 stop
        sleep 1
        $0 start
        ;;

    logs)
        journalctl --user -u tardis.service -f -n 40 2>/dev/null || tail -f "$DIR/tardis.log" 2>/dev/null || echo "No se encontraron logs recientes."
        ;;

    activate|reactivate)
        start_daemon_if_needed
        echo -e "${C_CYAN}⚡ Auto-reactivando todos los botones y subsistemas de hardware y software...${C_RESET}"
        RESP=$(curl -s -X POST "$API_BASE/api/system/buttons/auto_activate_all?key=$TOKEN" -H "Authorization: Bearer $TOKEN" || echo "{}")
        echo -e "${C_GREEN}✓ Resultado: $RESP${C_RESET}"
        ;;

    chat)
        shift
        MSG="$*"
        if [ -z "$MSG" ]; then
            echo -e "${C_YELLOW}Uso: tardis chat \"Tu pregunta o instrucción\"${C_RESET}"
            exit 1
        fi
        start_daemon_if_needed
        echo -e "${C_CYAN}💬 TARDIS (${C_GOLD}Núcleo Soberano${C_CYAN}):${C_RESET}"
        "$DIR/.venv-linux/bin/python3" -c "
import urllib.request, json, sys

data = json.dumps({'message': '''$MSG''', 'stream': False, 'num_predict': 350}).encode('utf-8')
req = urllib.request.Request('$API_BASE/api/chat?key=$TOKEN', data=data, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer $TOKEN'})
try:
    with urllib.request.urlopen(req, timeout=40) as response:
        res = json.loads(response.read().decode('utf-8'))
        print(res.get('reply', 'Sin respuesta'))
except Exception as e:
    print(f'Error al consultar TARDIS: {e}')
"
        ;;

    explain-screen|screen)
        start_daemon_if_needed
        echo -e "${C_CYAN}📸 Capturando pantalla y analizando con núcleo soberano...${C_RESET}"
        "$DIR/.venv-linux/bin/python3" -c "
import urllib.request, json

req = urllib.request.Request('$API_BASE/api/system/companion/explain_os_screen?key=$TOKEN', data=b'{}', headers={'Authorization': 'Bearer $TOKEN'})
try:
    with urllib.request.urlopen(req, timeout=30) as response:
        res = json.loads(response.read().decode('utf-8'))
        print('\n' + res.get('explanation', 'Sin explicación disponible'))
except Exception as e:
    print(f'Error analizando pantalla: {e}')
"
        ;;

    cli)
        shift
        exec "$DIR/.venv-linux/bin/python3" "$DIR/tardis_cli.py" "$@"
        ;;

    capture|shot|iris)
        shift
        if command -v iris >/dev/null 2>&1; then
            exec iris "$@"
        else
            echo "Error: iris no encontrado en PATH"
            exit 1
        fi
        ;;

    help|--help|-h)
        show_banner
        echo "Uso: tardis [comando] [opciones]"
        echo ""
        echo "Comandos disponibles:"
        echo "  tardis                     Abre la interfaz soberana nativa de escritorio"
        echo "  tardis companion           Lanza el asistente triangular flotante sobre el SO"
        echo "  tardis status              Muestra el estado de salud, puertos y memoria"
        echo "  tardis chat <pregunta>     Chatea con el núcleo soberano directamente desde la terminal"
        echo "  tardis explain-screen      Captura tu pantalla y la explica con IA en la terminal"
        echo "  tardis capture <url>       Captura ultra-rápida de sitios web con Iris"
        echo "  tardis activate            Reactiva todos los 63 botones y subsistemas de hardware"
        echo "  tardis start | stop | restart  Controla el demonio de fondo TARDIS"
        echo "  tardis logs                Muestra los logs en tiempo real"
        echo "  tardis cli                 Abre la consola CLI interactiva de TARDIS"
        echo ""
        ;;

    *)
        echo -e "${C_YELLOW}Comando desconocido: '$cmd'. Mostrando ayuda:${C_RESET}"
        $0 help
        ;;
esac
