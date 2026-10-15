#!/usr/bin/env bash
# ==============================================================================
# 🛸 TARDIS-NEURAL-SPACE-KAIJU :: SUITE SOBERANA DE CONTROL REMOTO (iMac 14,1)
# Control, Automatización y Diagnóstico Unificado (Android ADB + Linux SSH)
# ==============================================================================
set -o pipefail

IMAC_HOST="${IMAC_HOST:-imac-gia.local}"
FALLBACK_IPS=("REDACTED_IP" "REDACTED_IP" "REDACTED_IP")
PORT_API=8757
PORT_ADB=5555
PORT_SSH=22
USER_SSH="root"
SSH_KEY="/home/timemachine/.ssh/id_ed25519"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3"
ADB_BIN="/home/timemachine/.local/bin/adb"
if [ ! -x "$ADB_BIN" ]; then
    ADB_BIN="$(which adb 2>/dev/null || echo adb)"
fi

# Detectar IP y modo operativo del iMac
detect_imac() {
    # 1. Probar nombres y listas estáticas
    for ip in "${FALLBACK_IPS[@]}" "$IMAC_HOST" "imac"; do
        if ping -c 1 -W 1 "$ip" >/dev/null 2>&1; then
            echo "$ip"
            return 0
        fi
    done

    # 2. Escaneo dinámico por ARP neighbors (192.168.1.x y 10.42.0.x)
    local neighbors
    neighbors=$(ip neigh show 2>/dev/null | grep -E "192\.168\.1\.|10\.42\.0\." | awk '{print $1}')
    for ip in $neighbors; do
        if nc -z -w 1 "$ip" $PORT_ADB 2>/dev/null || nc -z -w 1 "$ip" $PORT_SSH 2>/dev/null || curl -s -m 0.5 "http://$ip:$PORT_API/api/ping" 2>/dev/null | grep -q "PONG"; then
            echo "$ip"
            return 0
        fi
    done

    # Fallback predeterminado
    echo "${FALLBACK_IPS[0]}"
}

get_mode() {
    local target="$1"
    if nc -z -w 1 "$target" $PORT_ADB 2>/dev/null; then
        echo "android_adb"
    elif nc -z -w 1 "$target" $PORT_SSH 2>/dev/null; then
        echo "linux_ssh"
    elif curl -s -m 0.5 "http://$target:$PORT_API/api/ping" 2>/dev/null | grep -q "PONG"; then
        echo "gia_api"
    else
        echo "offline"
    fi
}

show_header() {
    echo "========================================================================"
    echo "🛸 TARDIS-NEURAL-SPACE-KAIJU :: CONTROL REMOTO & AUTOMATIZACIÓN (iMac 14,1)"
    echo "========================================================================"
}

show_help() {
    show_header
    echo "Uso: ./imac_remote.sh <comando> [argumentos]"
    echo ""
    echo "📡 DIAGNÓSTICO Y DESCUBRIMIENTO:"
    echo "  scan                 - Escanea la red LAN/Ethernet y reporta el modo activo del iMac"
    echo "  status               - Telemetría integral (ADB / SSH / GPU / Display / Kernel)"
    echo "  wait-boot            - Monitorea hasta que el iMac arranque y responda por red"
    echo "  watch                - Monitor continuo en tiempo real de enlace y puertos"
    echo ""
    echo "📱 CONTROL ANDROID x86 (Modo ADB / Bliss OS):"
    echo "  adb-connect          - Establece y fuerza enlace TCP ADB en puerto 5555"
    echo "  adb-shell            - Abre shell root interactiva en Android"
    echo "  screen / scrcpy      - Espejea y controla la pantalla del iMac con baja latencia"
    echo "  unlock               - Despierta y desbloquea la pantalla de Android"
    echo "  key <evento>         - Envía teclas (home, back, menu, power, volup, voldn, enter)"
    echo "  install-apk <apk>    - Instala una aplicación APK en el iMac"
    echo "  optimize-android     - Configura pantalla activa, salta wizard y optimiza GPU"
    echo ""
    echo "🐧 CONTROL LINUX (Modo Rescate / GIA OS):"
    echo "  ssh                  - Sesión interactiva SSH root sin contraseña"
    echo "  clean-install        - Dispara instalación limpia de Android 17 en el disco de 1TB"
    echo ""
    echo "⚡ CONTROL GENERAL Y ENERGÍA:"
    echo "  exec \"<comando>\"     - Ejecuta comando remoto automáticamente adaptado a ADB o SSH"
    echo "  push <origen> <dest> - Transfiere archivo al iMac (vía ADB o SCP)"
    echo "  pull <remoto> <dest> - Descarga archivo desde el iMac (vía ADB o SCP)"
    echo "  reboot               - Reinicia el iMac de forma segura"
    echo "  poweroff             - Apaga el iMac remotamente"
    echo "========================================================================"
}

CMD="${1:-help}"
shift 2>/dev/null || true

case "$CMD" in
    scan)
        show_header
        echo "🔍 Escaneando red local para localizar el iMac 14,1..."
        TARGET=$(detect_imac)
        MODE=$(get_mode "$TARGET")
        echo "🎯 Objetivo detectado: $TARGET"
        echo "⚙️ Modo activo: $MODE"
        
        if ping -c 1 -W 1 "$TARGET" >/dev/null 2>&1; then
            echo "✅ Ping: OK"
        else
            echo "❌ Ping: No responde"
        fi

        echo -n "  • Puerto 22 (SSH): "
        nc -z -w 1 "$TARGET" $PORT_SSH 2>/dev/null && echo "ABIERTO" || echo "Cerrado"
        echo -n "  • Puerto 5555 (ADB): "
        nc -z -w 1 "$TARGET" $PORT_ADB 2>/dev/null && echo "ABIERTO" || echo "Cerrado"
        echo -n "  • Puerto 8757 (API): "
        nc -z -w 1 "$TARGET" $PORT_API 2>/dev/null && echo "ABIERTO" || echo "Cerrado"
        ;;

    status)
        show_header
        TARGET=$(detect_imac)
        MODE=$(get_mode "$TARGET")
        echo "📊 Telemetría del iMac 14,1 ($TARGET) :: Modo [$MODE]"
        
        if [ "$MODE" = "android_adb" ]; then
            $ADB_BIN connect "$TARGET:$PORT_ADB" >/dev/null 2>&1
            echo "--- ANDROID SYSTEM INFO ---"
            echo "Modelo: $($ADB_BIN -s "$TARGET:$PORT_ADB" shell getprop ro.product.model 2>/dev/null)"
            echo "Versión Android: $($ADB_BIN -s "$TARGET:$PORT_ADB" shell getprop ro.build.version.release 2>/dev/null)"
            echo "Kernel: $($ADB_BIN -s "$TARGET:$PORT_ADB" shell uname -a 2>/dev/null)"
            echo "Uptime: $($ADB_BIN -s "$TARGET:$PORT_ADB" shell uptime 2>/dev/null)"
            echo "Memoria:"
            $ADB_BIN -s "$TARGET:$PORT_ADB" shell free -m 2>/dev/null || true
            echo "GPU / SurfaceFlinger:"
            $ADB_BIN -s "$TARGET:$PORT_ADB" shell dumpsys SurfaceFlinger 2>/dev/null | grep -E "GLES|OpenGL|Vendor|Renderer" | head -n 4 || true
        elif [ "$MODE" = "linux_ssh" ]; then
            echo "--- LINUX SYSTEM INFO ---"
            ssh $SSH_OPTS -i "$SSH_KEY" "$USER_SSH@$TARGET" "uname -a; uptime; free -m; lsblk" 2>/dev/null || true
        else
            echo "⚠️ El dispositivo se encuentra offline o los puertos remotos no están activos aún."
        fi
        ;;

    wait-boot)
        show_header
        echo "⏳ Esperando enlace y respuesta del iMac 14,1..."
        while true; do
            TARGET=$(detect_imac)
            MODE=$(get_mode "$TARGET")
            if [ "$MODE" != "offline" ]; then
                echo ""
                echo "🎉 ¡iMac 14,1 EN LÍNEA en $TARGET! Modo: $MODE"
                exit 0
            fi
            printf "."
            sleep 2
        done
        ;;

    watch)
        show_header
        echo "👁️ Monitor de conectividad en tiempo real (Ctrl+C para salir)..."
        while true; do
            TARGET=$(detect_imac)
            MODE=$(get_mode "$TARGET")
            TIMESTAMP=$(date +"%T")
            echo "[$TIMESTAMP] iMac: $TARGET | Modo: $MODE"
            sleep 3
        done
        ;;

    adb-connect)
        TARGET=$(detect_imac)
        echo "🔌 Conectando ADB a $TARGET:$PORT_ADB..."
        $ADB_BIN connect "$TARGET:$PORT_ADB"
        $ADB_BIN -s "$TARGET:$PORT_ADB" get-state
        ;;

    adb-shell)
        TARGET=$(detect_imac)
        $ADB_BIN connect "$TARGET:$PORT_ADB" >/dev/null 2>&1
        echo "🚀 Iniciando consola root ADB en iMac ($TARGET)..."
        $ADB_BIN -s "$TARGET:$PORT_ADB" shell
        ;;

    screen|scrcpy)
        TARGET=$(detect_imac)
        $ADB_BIN connect "$TARGET:$PORT_ADB" >/dev/null 2>&1
        echo "🖥️ Lanzando scrcpy en $TARGET:$PORT_ADB..."
        scrcpy --tcpip="$TARGET:$PORT_ADB" --max-fps=60 --video-bit-rate=12M "$@"
        ;;

    unlock)
        TARGET=$(detect_imac)
        $ADB_BIN connect "$TARGET:$PORT_ADB" >/dev/null 2>&1
        echo "🔓 Despertando y desbloqueando pantalla del iMac..."
        $ADB_BIN -s "$TARGET:$PORT_ADB" shell input keyevent 26
        $ADB_BIN -s "$TARGET:$PORT_ADB" shell input keyevent 82
        echo "✅ Pantalla activa y desbloqueada."
        ;;

    key)
        TARGET=$(detect_imac)
        EVENT="$1"
        case "$EVENT" in
            home) CODE=3 ;;
            back) CODE=4 ;;
            menu) CODE=82 ;;
            power) CODE=26 ;;
            volup) CODE=24 ;;
            voldn) CODE=25 ;;
            enter) CODE=66 ;;
            *) CODE="$EVENT" ;;
        esac
        $ADB_BIN connect "$TARGET:$PORT_ADB" >/dev/null 2>&1
        echo "⌨️ Enviando keyevent $CODE a $TARGET..."
        $ADB_BIN -s "$TARGET:$PORT_ADB" shell input keyevent "$CODE"
        ;;

    install-apk)
        TARGET=$(detect_imac)
        APK="$1"
        if [ -z "$APK" ] || [ ! -f "$APK" ]; then
            echo "❌ Error: Especifica una ruta válida a un archivo .apk"
            exit 1
        fi
        $ADB_BIN connect "$TARGET:$PORT_ADB" >/dev/null 2>&1
        echo "📦 Instalando $APK en el iMac..."
        $ADB_BIN -s "$TARGET:$PORT_ADB" install -r "$APK"
        ;;

    optimize-android)
        TARGET=$(detect_imac)
        $ADB_BIN connect "$TARGET:$PORT_ADB" >/dev/null 2>&1
        echo "⚙️ Optimizando Android en iMac ($TARGET)..."
        $ADB_BIN -s "$TARGET:$PORT_ADB" shell settings put global setup_wizard_has_run 1
        $ADB_BIN -s "$TARGET:$PORT_ADB" shell settings put secure user_setup_complete 1
        $ADB_BIN -s "$TARGET:$PORT_ADB" shell settings put system screen_off_timeout REDACTED_PHONE
        $ADB_BIN -s "$TARGET:$PORT_ADB" shell setenforce 0 2>/dev/null || true
        echo "✅ Parámetros de Android optimizados."
        ;;

    ssh)
        TARGET=$(detect_imac)
        echo "🔑 Conectando vía SSH a $USER_SSH@$TARGET..."
        ssh $SSH_OPTS -i "$SSH_KEY" "$USER_SSH@$TARGET"
        ;;

    clean-install)
        TARGET=$(detect_imac)
        echo "⚡ Disparando instalación limpia autónoma de Android 17 en el disco de 1TB..."
        /home/timemachine/clean_install_android17_imac.sh "$TARGET"
        ;;

    exec)
        TARGET=$(detect_imac)
        MODE=$(get_mode "$TARGET")
        COMMAND="$*"
        if [ -z "$COMMAND" ]; then
            echo "❌ Error: Especifica el comando a ejecutar."
            exit 1
        fi
        echo "💻 Ejecutando en $TARGET ($MODE): $COMMAND"
        if [ "$MODE" = "android_adb" ]; then
            $ADB_BIN -s "$TARGET:$PORT_ADB" shell "$COMMAND"
        elif [ "$MODE" = "linux_ssh" ]; then
            ssh $SSH_OPTS -i "$SSH_KEY" "$USER_SSH@$TARGET" "$COMMAND"
        else
            echo "❌ Error: El dispositivo no está accesible."
            exit 1
        fi
        ;;

    push)
        TARGET=$(detect_imac)
        MODE=$(get_mode "$TARGET")
        SRC="$1"
        DST="$2"
        if [ -z "$SRC" ] || [ -z "$DST" ]; then
            echo "Uso: ./imac_remote.sh push <origen_local> <destino_remoto>"
            exit 1
        fi
        echo "📤 Transfiriendo $SRC a $TARGET:$DST ($MODE)..."
        if [ "$MODE" = "android_adb" ]; then
            $ADB_BIN -s "$TARGET:$PORT_ADB" push "$SRC" "$DST"
        else
            scp $SSH_OPTS -i "$SSH_KEY" "$SRC" "$USER_SSH@$TARGET:$DST"
        fi
        ;;

    pull)
        TARGET=$(detect_imac)
        MODE=$(get_mode "$TARGET")
        SRC="$1"
        DST="${2:-.}"
        if [ -z "$SRC" ]; then
            echo "Uso: ./imac_remote.sh pull <origen_remoto> [destino_local]"
            exit 1
        fi
        echo "📥 Descargando $SRC desde $TARGET ($MODE)..."
        if [ "$MODE" = "android_adb" ]; then
            $ADB_BIN -s "$TARGET:$PORT_ADB" pull "$SRC" "$DST"
        else
            scp $SSH_OPTS -i "$SSH_KEY" "$USER_SSH@$TARGET:$SRC" "$DST"
        fi
        ;;

    reboot)
        TARGET=$(detect_imac)
        MODE=$(get_mode "$TARGET")
        echo "🔄 Reiniciando iMac ($TARGET)..."
        if [ "$MODE" = "android_adb" ]; then
            $ADB_BIN -s "$TARGET:$PORT_ADB" reboot
        elif [ "$MODE" = "linux_ssh" ]; then
            ssh $SSH_OPTS -i "$SSH_KEY" "$USER_SSH@$TARGET" "reboot -f"
        else
            echo "⚠️ No se detectó servicio activo; intentando comando por SSH de contingencia..."
            ssh $SSH_OPTS -i "$SSH_KEY" "$USER_SSH@$TARGET" "reboot -f" 2>/dev/null || true
        fi
        echo "✅ Señal de reinicio enviada."
        ;;

    poweroff)
        TARGET=$(detect_imac)
        MODE=$(get_mode "$TARGET")
        echo "🛑 Apagando iMac ($TARGET)..."
        if [ "$MODE" = "android_adb" ]; then
            $ADB_BIN -s "$TARGET:$PORT_ADB" reboot -p
        elif [ "$MODE" = "linux_ssh" ]; then
            ssh $SSH_OPTS -i "$SSH_KEY" "$USER_SSH@$TARGET" "poweroff -f"
        else
            ssh $SSH_OPTS -i "$SSH_KEY" "$USER_SSH@$TARGET" "poweroff -f" 2>/dev/null || true
        fi
        echo "✅ Señal de apagado enviada."
        ;;

    help|*)
        show_help
        ;;
esac
