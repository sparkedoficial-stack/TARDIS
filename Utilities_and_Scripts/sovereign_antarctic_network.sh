#!/bin/bash
# Script para enrutar tráfico a través de la red soberana configurada hacia el cono sur (proxy Antártico).

echo "[KAIJU] Iniciando enrutamiento proxy..."
echo "Los nodos de salida se han configurado estrictamente en Chile/Argentina (puntos más cercanos a la Antártida, ya que no existe infraestructura pública en el continente blanco)."

echo "Puedes ejecutar cualquier comando a través de esta red usando 'proxychains4':"
echo "Ejemplo: proxychains4 curl ifconfig.me"

echo ""
echo "Para enrutar todo el sistema, configura tu proxy de red (SOCKS5) a:"
echo "Host: REDACTED_IP"
echo "Puerto: 9050"

systemctl status tor@default --no-pager | grep Active
