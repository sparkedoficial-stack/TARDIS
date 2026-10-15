#!/bin/sh
# ==============================================================================
# FIJADOR SOBERANO DE LED CARLINKIT: LUZ ROJA FIJA Y ESTABLE (SIN PARPADEO)
# ==============================================================================

# 1. Desactivar todos los triggers de parpadeo (timer, heartbeat, blink, etc.)
for t in /sys/class/leds/*/trigger; do
    [ -f "$t" ] && echo none > "$t" 2>/dev/null || true
done

# 2. Apagar completamente cualquier canal verde, azul, blanco o amarillo
for led in /sys/class/leds/*green* /sys/class/leds/*blue* /sys/class/leds/*yellow* /sys/class/leds/*white*; do
    [ -f "$led/brightness" ] && echo 0 > "$led/brightness" 2>/dev/null || true
done

# 3. Encender de forma continua y fija el canal ROJO al 100% de brillo
for led in /sys/class/leds/*red*; do
    if [ -f "$led/max_brightness" ]; then
        cat "$led/max_brightness" > "$led/brightness" 2>/dev/null || true
    elif [ -f "$led/brightness" ]; then
        echo 1 > "$led/brightness" 2>/dev/null || true
    fi
done

# 4. Asegurar persistencia matando demonios que intenten parpadear el LED
while true; do
    for t in /sys/class/leds/*red*/trigger; do
        [ -f "$t" ] && echo none > "$t" 2>/dev/null || true
    done
    for led in /sys/class/leds/*red*/brightness; do
        [ -f "$led" ] && echo 1 > "$led" 2>/dev/null || true
    done
    for led in /sys/class/leds/*green*/brightness /sys/class/leds/*blue*/brightness; do
        [ -f "$led" ] && echo 0 > "$led" 2>/dev/null || true
    done
    sleep 2
done
