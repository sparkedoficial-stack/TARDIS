#!/bin/bash
# TARDIS SOBERANO: Agente de Configuración Post-Instalación
TARGET="REDACTED_IP"
echo "TARDIS KAIJU: Iniciando vigilancia temporal sobre $TARGET..."
while true; do
  adb connect $TARGET:5555 > /dev/null 2>&1
  STATE=$(adb -s $TARGET:5555 get-state 2>/dev/null)
  if [ "$STATE" == "device" ]; then
      echo "TARDIS SOBERANO: Enlace cuántico establecido con la Mac. Aplicando optimizaciones..."
      # Disable sleep, set up screen, bypass setup wizard, etc.
      adb -s $TARGET:5555 shell settings put global setup_wizard_has_run 1
      adb -s $TARGET:5555 shell settings put secure user_setup_complete 1
      adb -s $TARGET:5555 shell settings put system screen_off_timeout 2147483647
      echo "TARDIS SOBERANO: Configuración post-instalación completada."
      break
  fi
  sleep 10
done
