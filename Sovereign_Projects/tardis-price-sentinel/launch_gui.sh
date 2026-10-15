#!/usr/bin/env bash
# ₪ TARDIS Launcher :: Interfaz de Ofertas & Carrito Directo
export DISPLAY="${DISPLAY:-:0}"
if [ -z "$WAYLAND_DISPLAY" ] && [ -e "/run/user/1000/wayland-0" ]; then
    export WAYLAND_DISPLAY="wayland-0"
fi
exec /usr/bin/python3 /home/timemachine/tardis-price-sentinel/tardis_deals_gui.py
