#!/bin/bash
# scripts/tardis_voice_channel_c310.sh - Lanzador del Canal de Voz Soberano TARDIS (C310 @ REDACTED_IP)
# Canal siempre en espera; se activa al escuchar: "TARDIS ¿estás ahí?"
set -u

BASE_DIR="/home/m11/Escritorio/GODWORKS SYSTEM"
PY="$BASE_DIR/.venv-linux/bin/python"
DAEMON="$BASE_DIR/core/tardis_voice_channel_c310.py"
LOG_DIR="$BASE_DIR/data/tapo_c310_voice_channel"
PID_FILE="$LOG_DIR/tardis-voice-c310.pid"
LOG_FILE="$LOG_DIR/voice_channel.log"
mkdir -p "$LOG_DIR"

export PYTHONPATH="$BASE_DIR"

case "${1:-start}" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "TARDIS voz C310 ya está ejecutándose (PID $(cat "$PID_FILE"))."
      exit 0
    fi
    nohup "$PY" "$DAEMON" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "TARDIS voz C310 iniciado (PID $!). Escuchando despertar: 'TARDIS ¿estás ahí?'"
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "TARDIS voz C310 detenido."
    else
      echo "No hay PID de TARDIS voz C310."
    fi
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "TARDIS voz C310 ACTIVO (PID $(cat "$PID_FILE"))."
    else
      echo "TARDIS voz C310 INACTIVO."
    fi
    ;;
  log)
    tail -n 40 "$LOG_FILE" 2>/dev/null || echo "Sin log aún."
    ;;
  *)
    echo "Uso: $0 {start|stop|status|log}"
    exit 1
    ;;
esac
