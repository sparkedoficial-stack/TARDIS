#!/usr/bin/env bash
# ==============================================================================
# optimize_os.sh - Optimizador Soberano del Kernel y Sistema Operativo
# GODWORKS SYSTEM & TARDIS Architecture
# ==============================================================================
# Aplica parámetros de alto rendimiento para inferencia de IA, baja latencia
# de red y operaciones concurrentes de bases de datos SQLite en disco NVMe/SSD.
# ==============================================================================

set -e

SYSCTL_CONF="/etc/sysctl.d/99-godworks-performance.conf"
LIMITS_CONF="/etc/security/limits.d/99-godworks.conf"

echo "==================================================================="
echo " ⚡ OPTIMIZACIÓN SOBERANA DE SISTEMA OPERATIVO Y PROCESOS DE FONDO"
echo "==================================================================="

# 1. Aplicación de perfil energético máximo
if command -v powerprofilesctl >/dev/null 2>&1; then
    echo "• Configurando perfil energético a 'performance'..."
    powerprofilesctl set performance 2>/dev/null || true
fi

# 2. Configuración de parámetros sysctl de alto rendimiento
if [ "$(id -u)" -eq 0 ]; then
    echo "• Escribiendo configuración persistente en $SYSCTL_CONF..."
    cat << 'EOF' > "$SYSCTL_CONF"
# --- GODWORKS SYSTEM: OPTIMIZACIÓN DE KERNEL PARA IA Y BAJA LATENCIA ---
# 1. Reducir swappiness a 10 para priorizar el uso de los 22 GB de RAM
vm.swappiness = 10

# 2. Mantener inodos y dentry caches de SQLite en RAM
vm.vfs_cache_pressure = 50

# 3. Escritura en segundo plano ágil para SSD/NVMe
vm.dirty_background_ratio = 5
vm.dirty_ratio = 15

# 4. Expansión de cola de conexiones TCP para endpoints de clientes y túneles
net.core.somaxconn = 16384
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_max_syn_backlog = 8192

# 5. Aceleración TCP Fast Open y reutilización de conexiones
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_tw_reuse = 1

# 6. Aumento de descriptores máximos del sistema
fs.file-max = 2097152

# 7. Aumento de monitores inotify para centinelas de archivos
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 1024
EOF

    echo "• Aplicando parámetros con sysctl..."
    sysctl -p "$SYSCTL_CONF" 2>/dev/null || true

    echo "• Configurando límites de proceso en $LIMITS_CONF..."
    cat << 'EOF' > "$LIMITS_CONF"
# Límites para el usuario de GODWORKS
* soft nofile 65536
* hard nofile 524288
* soft nproc 65536
* hard nproc 78874
* soft memlock unlimited
* hard memlock unlimited
EOF

    echo "✅ Parámetros del kernel y límites de sistema aplicados exitosamente."
else
    echo "ℹ️ Para aplicar los parámetros a nivel de kernel (/etc/sysctl.d):"
    echo "   sudo bash optimize_os.sh"
fi

# 3. Optimización a nivel de usuario en tiempo de ejecución
echo "• Aplicando optimizaciones de runtime a nivel de usuario..."
python3 -c "
from core.os_optimizer import get_os_optimizer
opt = get_os_optimizer()
res = opt.apply_runtime_optimizations()
print('  Resultados de optimización en runtime:', res)
rep = opt.get_system_efficiency_report()
print('  RAM disponible:', rep['ram_available_gb'], 'GB /', rep['ram_total_gb'], 'GB')
print('  Límites NOFILE activos:', rep['nofile_soft_limit'])
"

echo "==================================================================="
echo " ✅ OPTIMIZACIÓN COMPLETADA CON ÉXITO"
echo "==================================================================="
