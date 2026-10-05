#!/usr/bin/env bash
# ==============================================================================
# start_client_gateway.sh - Lanza el gateway seguro de clientes + túnel público
# ==============================================================================
# Servicio aislado (client_gateway.py) que solo permite chat autenticado por
# magic-link de email. No expone el bridge de control completo.
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

VENV_PYTHON="$DIR/.venv-linux/bin/python3"
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="$(command -v python3)"
fi

GATEWAY_PORT="$("$VENV_PYTHON" -c "import json; print(json.load(open('client_gateway_secrets.json'))['gateway_port'])")"
LOG_FILE="$DIR/client_gateway.log"
TUNNEL_LOG="$DIR/client_gateway_tunnel.log"
URL_FILE="$DIR/CLIENT_GATEWAY_TUNNEL_URL.txt"

echo "🔐 [Client Gateway] Deteniendo instancias previas..."
pkill -f "client_gateway.py" 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://REDACTED_IP:${GATEWAY_PORT}" 2>/dev/null || true
sleep 1

echo "🔐 [Client Gateway] Iniciando servicio en REDACTED_IP:${GATEWAY_PORT}..."
nohup "$VENV_PYTHON" "$DIR/client_gateway.py" > "$LOG_FILE" 2>&1 &
GATEWAY_PID=$!
echo "   PID: $GATEWAY_PID"

sleep 2
if ! curl -s -m 5 "http://REDACTED_IP:${GATEWAY_PORT}/health" > /dev/null; then
    echo "❌ El gateway no respondió. Revisá $LOG_FILE"
    exit 1
fi

echo "🌐 [Client Gateway] Levantando túnel público (cloudflared)..."
CF_BIN="$(command -v cloudflared || echo "$HOME/.local/bin/cloudflared")"
nohup "$CF_BIN" tunnel --url "http://REDACTED_IP:${GATEWAY_PORT}" > "$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!

PUBLIC_URL=""
for i in $(seq 1 30); do
    sleep 1
    PUBLIC_URL="$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -n1 || true)"
    if [ -n "$PUBLIC_URL" ]; then
        break
    fi
done

if [ -z "$PUBLIC_URL" ]; then
    echo "❌ No se pudo obtener la URL pública del túnel. Revisá $TUNNEL_LOG"
    exit 1
fi

echo "$PUBLIC_URL" > "$URL_FILE"
echo ""
echo "✅ Gateway de clientes activo."
echo "   URL pública: $PUBLIC_URL"
echo "   Solo acceso de chat, con login por email (magic link)."
echo "   Gateway PID: $GATEWAY_PID · Tunnel PID: $TUNNEL_PID"
