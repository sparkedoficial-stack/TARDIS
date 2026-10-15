#!/bin/bash
# Despliegue remoto vía Wi-Fi hacia el Carlinkit (REDACTED_IP)
TARGET_IP="${1:-REDACTED_IP}"
echo "[*] Conectando con Carlinkit en: $TARGET_IP"

ssh-keyscan -H "$TARGET_IP" >> ~/.ssh/known_hosts 2>/dev/null || true
sshpass -p "root" scp -o StrictHostKeyChecking=no -r $(dirname "$0")/* "root@$TARGET_IP:/tmp/" 2>/dev/null || scp -r $(dirname "$0")/* "root@$TARGET_IP:/tmp/"

ssh -o StrictHostKeyChecking=no "root@$TARGET_IP" "sh /tmp/auto_run.sh"
echo "[+] Despliegue remoto completado con éxito."
