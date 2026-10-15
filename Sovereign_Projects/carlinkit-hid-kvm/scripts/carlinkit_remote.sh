#!/usr/bin/env bash
# ==============================================================================
# ⚡ CARLINKIT REMOTE CONTROLLER & SMART BOOT MANAGER
# Autonomous remote management engine for Carlinkit & connected Mac 14,1
# ==============================================================================
set -e

CARLINKIT_HOST="${1:-REDACTED_IP}"
PORT_SSH=22
PORT_HTTP=8080
USER_SSH="root"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3"

show_header() {
    echo "========================================================================"
    echo "⚡ CARLINKIT REMOTE MANAGER :: OBJETIVO [$CARLINKIT_HOST]"
    echo "========================================================================"
}

show_help() {
    show_header
    echo "Uso: $0 [ip_carlinkit] <comando> [argumentos...]"
    echo ""
    echo "Comandos Disponibles:"
    echo "  status            - Muestra el estado del Gadget, Wi-Fi y servidor KVM"
    echo "  identify          - Identifica el dispositivo anfitrión y periféricos USB conectados"
    echo "  netboot           - Inyecta tecla 'N' para forzar NetBoot en el iMac 14,1"
    echo "  option            - Mantiene presionada tecla 'Option' (Startup Manager de Mac)"
    echo "  ssh               - Abre una sesión SSH root interactiva en el Carlinkit"
    echo "  exec <comando>    - Ejecuta un comando remoto en el SoC del Carlinkit"
    echo "  push <local> <rem> - Transfiere un archivo al Carlinkit (o a la USB de arranque)"
    echo "  pull <rem> <local> - Descarga un archivo desde el Carlinkit"
    echo "  wifi-status       - Inspecciona clientes Wi-Fi conectados a '0hack'"
    echo "  reboot            - Reinicia el dongle Carlinkit"
    echo "  key <tecla>       - Inyecta una tecla al anfitrión (ej: enter, f12, alt+f4)"
    echo "  type '<texto>'    - Escribe texto directamente por USB en el anfitrión"
    echo "  ipad <acción>     - Atajos iPadOS (home, spotlight, switcher, dock, lock)"
    echo "========================================================================"
}

# Desplazar primer argumento si es una IP
if [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    CARLINKIT_HOST="$1"
    shift
fi

ACTION="${1:-status}"
shift 2>/dev/null || true

case "$ACTION" in
    identify)
        show_header
        echo "[*] Consultando telemetría de identificación de dispositivo en $CARLINKIT_HOST..."
        if nc -z -w 1 "$CARLINKIT_HOST" $PORT_SSH 2>/dev/null && sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "true" 2>/dev/null; then
            sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "python3 /etc/carlinkit_hid/carlinkit_sentinel.py identify 2>/dev/null || python /etc/carlinkit_hid/carlinkit_sentinel.py identify 2>/dev/null || tail -n 25 /var/log/carlinkit_sentinel.log 2>/dev/null" 2>/dev/null
        else
            STATUS_JSON=$(curl -s -m 2 "http://$CARLINKIT_HOST:$PORT_HTTP/api/identify" 2>/dev/null || echo "offline")
            if [ "$STATUS_JSON" != "offline" ]; then
                echo "$STATUS_JSON" | jq . 2>/dev/null || echo "$STATUS_JSON"
            else
                echo "⚠️ No se pudo obtener identificación directa (Carlinkit no responde en $CARLINKIT_HOST)."
            fi
        fi
        ;;

    netboot)
        show_header
        echo "🚀 Inyectando pulsación física 'N' continua (Arranque NetBoot en iMac 14,1)..."
        if nc -z -w 1 "$CARLINKIT_HOST" $PORT_SSH 2>/dev/null && sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "true" 2>/dev/null; then
            sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "python3 /etc/carlinkit_hid/carlinkit_sentinel.py netboot" 2>/dev/null
        else
            curl -s -X POST "http://$CARLINKIT_HOST:$PORT_HTTP/api/key" -H "Content-Type: application/json" -d '{"key": "n", "action": "press"}'
        fi
        echo "✅ Orden de arranque en red enviada por USB."
        ;;

    option)
        show_header
        echo "🍎 Inyectando pulsación 'Option' (Left Alt) continua para abrir Startup Manager de Apple..."
        if nc -z -w 1 "$CARLINKIT_HOST" $PORT_SSH 2>/dev/null && sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "true" 2>/dev/null; then
            sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "python3 /etc/carlinkit_hid/carlinkit_sentinel.py option" 2>/dev/null
        else
            curl -s -X POST "http://$CARLINKIT_HOST:$PORT_HTTP/api/key" -H "Content-Type: application/json" -d '{"key": "alt", "action": "press"}'
        fi
        echo "✅ Tecla Option inyectada durante arranque."
        ;;

    status)
        show_header
        echo "[*] Consultando API HTTP en http://$CARLINKIT_HOST:$PORT_HTTP/api/status..."
        STATUS_JSON=$(curl -s -m 2 "http://$CARLINKIT_HOST:$PORT_HTTP/api/status" 2>/dev/null || echo "offline")
        if [ "$STATUS_JSON" != "offline" ]; then
            echo "✅ Servidor KVM y Control en Línea: $STATUS_JSON"
        else
            echo "⚠️ API HTTP no responde en $CARLINKIT_HOST:$PORT_HTTP."
        fi

        echo "[*] Verificando enlace SSH en $CARLINKIT_HOST:$PORT_SSH..."
        if nc -z -w 1 "$CARLINKIT_HOST" $PORT_SSH 2>/dev/null; then
            echo "✅ Puerto SSH activo. Obteniendo telemetría del sistema..."
            sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "uname -a; uptime; ls /sys/kernel/config/usb_gadget/ 2>/dev/null || true" 2>/dev/null || true
        else
            echo "⚠️ Puerto SSH cerrado o no alcanzable desde esta red."
        fi
        ;;

    ssh)
        show_header
        echo "🚀 Iniciando consola SSH en Carlinkit ($CARLINKIT_HOST)..."
        sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" 2>/dev/null || ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST"
        ;;

    exec)
        CMD="$*"
        if [ -z "$CMD" ]; then
            echo "❌ Error: Especifica el comando a ejecutar."
            exit 1
        fi
        show_header
        echo "💻 Ejecutando: $CMD"
        sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "$CMD" 2>/dev/null || ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "$CMD"
        ;;

    push)
        SRC="$1"
        DST="$2"
        if [ -z "$SRC" ] || [ -z "$DST" ]; then
            echo "Uso: $0 push <archivo_local> <destino_remoto>"
            exit 1
        fi
        show_header
        echo "📤 Enviando $SRC -> $CARLINKIT_HOST:$DST..."
        sshpass -p "root" scp $SSH_OPTS "$SRC" "$USER_SSH@$CARLINKIT_HOST:$DST" 2>/dev/null || scp $SSH_OPTS "$SRC" "$USER_SSH@$CARLINKIT_HOST:$DST"
        echo "✅ Archivo transferido con éxito."
        ;;

    pull)
        SRC="$1"
        DST="${2:-.}"
        show_header
        echo "📥 Descargando $CARLINKIT_HOST:$SRC -> $DST..."
        sshpass -p "root" scp $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST:$SRC" "$DST" 2>/dev/null || scp $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST:$SRC" "$DST"
        echo "✅ Descarga finalizada."
        ;;

    wifi-status)
        show_header
        echo "[*] Consultando estado de clientes Wi-Fi en red '0hack'..."
        sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "cat /proc/net/arp; iw dev wlan0 station dump 2>/dev/null || true" 2>/dev/null || true
        ;;

    reboot)
        show_header
        echo "🔄 Reiniciando Carlinkit..."
        sshpass -p "root" ssh $SSH_OPTS "$USER_SSH@$CARLINKIT_HOST" "reboot -f" 2>/dev/null || true
        echo "✅ Orden de reinicio enviada."
        ;;

    key)
        KEY="$1"
        show_header
        echo "⌨️ Inyectando pulsación física de tecla [$KEY] al dispositivo anfitrión..."
        curl -s -X POST "http://$CARLINKIT_HOST:$PORT_HTTP/api/key" -H "Content-Type: application/json" -d "{\"key\": \"$KEY\"}"
        echo ""
        ;;

    type)
        TEXT="$1"
        show_header
        echo "⌨️ Escribiendo texto por USB físico en el dispositivo anfitrión..."
        curl -s -X POST "http://$CARLINKIT_HOST:$PORT_HTTP/api/type" -H "Content-Type: application/json" -d "{\"text\": \"$TEXT\"}"
        echo ""
        ;;

    ipad)
        SUB="$1"
        show_header
        case "$SUB" in
            home)
                echo "📱 iPad Pro M2: Ir a Pantalla de Inicio (Cmd + H)..."
                curl -s -X POST "http://$CARLINKIT_HOST:$PORT_HTTP/api/key" -H "Content-Type: application/json" -d '{"key": "cmd+h"}'
                ;;
            spotlight)
                echo "🔍 iPad Pro M2: Abrir Búsqueda Spotlight (Cmd + Space)..."
                curl -s -X POST "http://$CARLINKIT_HOST:$PORT_HTTP/api/key" -H "Content-Type: application/json" -d '{"key": "cmd+space"}'
                ;;
            switcher)
                echo "📑 iPad Pro M2: Selector de Aplicaciones (Cmd + Tab)..."
                curl -s -X POST "http://$CARLINKIT_HOST:$PORT_HTTP/api/key" -H "Content-Type: application/json" -d '{"key": "cmd+tab"}'
                ;;
            dock)
                echo "📂 iPad Pro M2: Mostrar/Ocultar Dock (Cmd + Option + D)..."
                curl -s -X POST "http://$CARLINKIT_HOST:$PORT_HTTP/api/key" -H "Content-Type: application/json" -d '{"key": "cmd+alt+d"}'
                ;;
            lock)
                echo "🔒 iPad Pro M2: Bloquear / Apagar Pantalla (Cmd + Ctrl + Q)..."
                curl -s -X POST "http://$CARLINKIT_HOST:$PORT_HTTP/api/key" -H "Content-Type: application/json" -d '{"key": "cmd+ctrl+q"}'
                ;;
            *)
                echo "Uso: $0 ipad <home|spotlight|switcher|dock|lock>"
                ;;
        esac
        echo "✅ Comando iPadOS ejecutado."
        ;;

    help|*)
        show_help
        ;;
esac
