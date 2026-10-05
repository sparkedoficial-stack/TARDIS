#!/usr/bin/env python3
"""
==============================================================================
TARDIS SOVEREIGN OS - CUSTOM ROM BUILDER (MOTOROLA MOTO X PLAY)
==============================================================================
Genera la imagen y paquete flashable de la Custom ROM para el Moto X Play.
Elimina todo el bloatware de Android, mantiene únicamente la pila de
conectividad (Wi-Fi + Datos Móviles LTE/4G), y establece TARDIS como el único
sistema operativo y entorno del dispositivo con ARQUITECTURA ZERO-URL:
  - Demonio autónomo nativo en segundo plano (REDACTED_IP:8080).
  - Telemetría física y control de hardware sin requerir navegadores abiertos.
  - Interfaz offline permanente e instantánea vía Kiosk / Service Worker.
==============================================================================
"""

import os
import sys
import shutil
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TOOLS_DIR = BASE_DIR / "tools"
SYSTEM_DIR = BASE_DIR / "system"
META_INF_DIR = BASE_DIR / "META-INF" / "com" / "google" / "android"
OUTPUT_DIR = BASE_DIR / "dist"
MOBILE_DIR = BASE_DIR.parent / "mobile_terminal"

# Configuración Soberana Zero-URL
DEVICE_NAME = "Motorola Moto X Play"
DEVICE_CODENAME = "lux"
HUB_URL = "http://REDACTED_IP:8080"
HEALTH_URL = "http://REDACTED_IP:8080/api/local/status"
DEVICE_ID = "tardis_mobile_terminal_moto_x_play_zy222zxwpp"

# Lista quirúrgica de paquetes a eliminar (Bloatware y apps estándar)
DEBLOAT_PACKAGES = [
    # Google & Telemetría
    "system/app/GoogleContactsSyncAdapter",
    "system/app/GoogleCalendarSyncAdapter",
    "system/app/GoogleTTS",
    "system/app/GoogleFeedback",
    "system/app/Chrome",
    "system/app/Gmail2",
    "system/app/Maps",
    "system/app/YouTube",
    "system/app/Music2",
    "system/app/Photos",
    "system/app/Drive",
    "system/app/Videos",
    "system/app/Hangouts",
    "system/app/GooglePrintRecommendationService",
    "system/priv-app/GmsCore",
    "system/priv-app/GoogleServicesFramework",
    "system/priv-app/GooglePartnerSetup",
    "system/priv-app/GoogleBackupTransport",
    "system/priv-app/ConfigUpdater",
    "system/priv-app/SetupWizard",
    "system/priv-app/GoogleRestore",
    "system/priv-app/Velvet",
    # Lanzadores estándar y de terceros
    "system/priv-app/Launcher3",
    "system/priv-app/Trebuchet",
    "system/priv-app/NexusLauncherPrebuilt",
    "system/priv-app/MotoLauncher",
    # Aplicaciones estándar innecesarias
    "system/app/Calculator",
    "system/app/ExactCalculator",
    "system/app/Calendar",
    "system/app/DeskClock",
    "system/app/Email",
    "system/app/Exchange2",
    "system/app/Gallery2",
    "system/app/HTMLViewer",
    "system/app/LatinIME",
    "system/app/Music",
    "system/app/SoundRecorder",
    "system/app/LiveWallpapers",
    "system/app/LiveWallpapersPicker",
    "system/app/PrintSpooler",
    # Servicios propietarios de Motorola
    "system/app/MotoCare",
    "system/app/MotoCheckin",
    "system/app/MotorolaSettingsProvider",
    "system/priv-app/MotoDisplay",
    "system/priv-app/MotoActions",
    "system/priv-app/MotoVoice",
    "system/priv-app/BodyGuard",
    "system/priv-app/3c_main"
]

def generate_update_binary() -> str:
    """Genera el script ejecutable de instalación para el Recovery con Zero-URL OS."""
    return f"""#!/sbin/sh
# ==============================================================================
# TARDIS SOVEREIGN OS - UPDATE-BINARY INSTALLER (ZERO-URL ENGINE v2.0)
# ==============================================================================
# Dispositivo: {DEVICE_NAME} ({DEVICE_CODENAME})
# ==============================================================================

OUTFD=$2
ui_print() {{
    echo -e "ui_print $1\\nui_print" > /proc/self/fd/$OUTFD
}}

ui_print "================================================="
ui_print "       TARDIS SOVEREIGN OS · NODO MÓVIL         "
ui_print "================================================="
ui_print "Dispositivo : {DEVICE_NAME}"
ui_print "Arquitectura: Snapdragon 615 ({DEVICE_CODENAME})"
ui_print "Modo        : ZERO-URL AUTONOMOUS MESH"
ui_print "================================================="

# 1. Montar particiones
ui_print "[1/5] Montando particiones /system y /data..."
mount /system 2>/dev/null || mount -o rw /dev/block/bootdevice/by-name/system /system
mount /data 2>/dev/null || mount -o rw /dev/block/bootdevice/by-name/userdata /data

if [ ! -d "/system/priv-app" ]; then
    ui_print "❌ ERROR: No se pudo montar /system correctamente."
    exit 1
fi

# 2. Purgar bloatware y aplicaciones innecesarias
ui_print "[2/5] Purgando bloatware de Android (manteniendo Wi-Fi y Datos)..."
""" + "\n".join([f'rm -rf "/{pkg}"' for pkg in DEBLOAT_PACKAGES]) + f"""

# 3. Instalar Lanzador Soberano TARDIS
ui_print "[3/5] Inyectando TARDIS Sovereign Shell como Lanzador Raíz..."
mkdir -p /system/priv-app/TardisLauncher
cp -f /tmp/TardisLauncher.apk /system/priv-app/TardisLauncher/TardisLauncher.apk
chmod 644 /system/priv-app/TardisLauncher/TardisLauncher.apk
chmod 755 /system/priv-app/TardisLauncher

# Otorgar permisos privilegiados en el sistema
mkdir -p /system/etc/permissions
cat << 'EOF' > /system/etc/permissions/privapp-permissions-tardis.xml
<?xml version="1.0" encoding="utf-8"?>
<permissions>
    <privapp-permissions package="com.tardis.sovereign">
        <permission name="android.permission.INTERNET"/>
        <permission name="android.permission.ACCESS_NETWORK_STATE"/>
        <permission name="android.permission.ACCESS_WIFI_STATE"/>
        <permission name="android.permission.CHANGE_WIFI_STATE"/>
        <permission name="android.permission.WAKE_LOCK"/>
        <permission name="android.permission.RECEIVE_BOOT_COMPLETED"/>
        <permission name="android.permission.MODIFY_AUDIO_SETTINGS"/>
        <permission name="android.permission.RECORD_AUDIO"/>
        <permission name="android.permission.CAMERA"/>
        <permission name="android.permission.ACCESS_FINE_LOCATION"/>
        <permission name="android.permission.VIBRATE"/>
    </privapp-permissions>
</permissions>
EOF
chmod 644 /system/etc/permissions/privapp-permissions-tardis.xml

# Inyectar servicio init.d nativo para arrancar el demonio al boot
mkdir -p /system/etc/init.d
cat << 'EOF' > /system/etc/init.d/99tardis_pocket
#!/system/bin/sh
# TARDIS POCKET SOBERANO - SERVICIO DE ARRANQUE NATIVO
if [ -f "/data/tardis/tardis_pocket_daemon.sh" ]; then
    /system/bin/sh /data/tardis/tardis_pocket_daemon.sh >/dev/null 2>&1 &
fi
EOF
chmod 755 /system/etc/init.d/99tardis_pocket

# Preconfigurar Kiosk Preferences de kiFOSSk
mkdir -p /data/data/com.shinydiscoballsdev.kifossk/shared_prefs
cat << 'EOF' > /data/data/com.shinydiscoballsdev.kifossk/shared_prefs/KioskPrefs.xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="targetUrl">http://REDACTED_IP:8080</string>
    <string name="currentUrl">http://REDACTED_IP:8080</string>
    <boolean name="kioskMode" value="true" />
</map>
EOF
chmod -R 777 /data/data/com.shinydiscoballsdev.kifossk 2>/dev/null || true

# 4. Inyectar ajustes soberanos en build.prop
ui_print "[4/5] Configurando build.prop (Modo Zero-URL, Cero Bloqueos, ADB Root)..."
sed -i '/ro.setupwizard.mode/d' /system/build.prop
sed -i '/persist.sys.usb.config/d' /system/build.prop
sed -i '/ro.adb.secure/d' /system/build.prop
sed -i '/persist.service.adb.enable/d' /system/build.prop

cat << 'EOF' >> /system/build.prop
# --- TARDIS SOVEREIGN OS PROPERTIES ---
ro.setupwizard.mode=DISABLED
persist.sys.usb.config=mtp,adb
ro.adb.secure=0
persist.service.adb.enable=1
ro.config.ringtone=
ro.config.notification_sound=
ro.config.alarm_alert=
persist.sys.timezone=America/Mexico_City
ro.tardis.sovereign_os=1
ro.tardis.node_id={DEVICE_ID}
ro.tardis.hub_url={HUB_URL}
ro.tardis.zero_url=1
EOF

# Inyectar archivos y suite autónoma en /data/tardis
mkdir -p /data/tardis
cp -f /tmp/tardis_kaiju_pocket_engine.py /data/tardis/tardis_kaiju_pocket_engine.py 2>/dev/null || true
cp -f /tmp/tardis_pocket_daemon.py /data/tardis/tardis_pocket_daemon.py 2>/dev/null || true
cp -f /tmp/tardis_pocket_daemon.sh /data/tardis/tardis_pocket_daemon.sh 2>/dev/null || true
cp -f /tmp/tardis_pocket.html /data/tardis/tardis_pocket.html 2>/dev/null || true
cp -f /tmp/sw.js /data/tardis/sw.js 2>/dev/null || true
cp -f /tmp/manifest.json /data/tardis/manifest.json 2>/dev/null || true
cp -f /tmp/tardis_terminal_config.json /data/tardis/tardis_terminal_config.json 2>/dev/null || true
cp -f /tmp/start_tardis_terminal.sh /data/tardis/start_tardis_terminal.sh 2>/dev/null || true
cp -f /tmp/setup_termux_boot.sh /data/tardis/setup_termux_boot.sh 2>/dev/null || true
chmod -R 777 /data/tardis

ui_print "[5/5] Sincronizando y desmontando..."
sync
umount /system 2>/dev/null
umount /data 2>/dev/null

ui_print "================================================="
ui_print "✓ INSTALACIÓN DE TARDIS SOVEREIGN OS COMPLETADA "
ui_print "================================================="
ui_print "El dispositivo se reiniciará directamente en la "
ui_print "Cabina Soberana TARDIS sin requerir URLs manuales."
ui_print "================================================="
exit 0
"""

def generate_updater_script() -> str:
    """Genera el dummy updater-script para compatibilidad con recoveries antiguos."""
    return '#!/sbin/sh\n# TARDIS SOVEREIGN OS DUMMY SCRIPT FOR EDIFY COMPATIBILITY\n'

def build_rom():
    print("===============================================================")
    print(" CONSTRUYENDO CUSTOM ROM: TARDIS SOVEREIGN OS (MOTO X PLAY)")
    print(" MODO: ZERO-URL AUTONOMOUS MESH (100% INDEPENDIENTE)")
    print("===============================================================")
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    META_INF_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Escribir update-binary y updater-script
    binary_path = META_INF_DIR / "update-binary"
    binary_path.write_text(generate_update_binary(), encoding="utf-8")
    os.chmod(binary_path, 0o755)
    print(f"✓ update-binary generado: {binary_path}")
    
    script_path = META_INF_DIR / "updater-script"
    script_path.write_text(generate_updater_script(), encoding="utf-8")
    print(f"✓ updater-script generado: {script_path}")
    
    # 2. Seleccionar el APK para el Launcher Soberano Nativo
    target_apk = SYSTEM_DIR / "priv-app" / "TardisLauncher" / "TardisLauncher.apk"
    target_apk.parent.mkdir(parents=True, exist_ok=True)
    
    source_apk = None
    for candidate in [
        BASE_DIR / "tardis_os_shell" / "TardisLauncher.apk",
        TOOLS_DIR / "kiFOSSk.apk",
        TOOLS_DIR / "KioskZen.apk",
        TOOLS_DIR / "freekiosk.apk",
        MOBILE_DIR / "apks" / "Termux.apk"
    ]:
        if candidate.exists():
            source_apk = candidate
            break
            
    if source_apk:
        shutil.copy2(source_apk, target_apk)
        print(f"✓ Launcher Soberano seleccionado: {source_apk.name} -> TardisLauncher.apk")
    else:
        print("⚠️ No se encontró APK en tools/, se creará marcador.")
        target_apk.write_text("TARDIS_LAUNCHER_PLACEHOLDER")

    # 3. Empaquetar el ZIP flashable
    zip_output = OUTPUT_DIR / "TARDIS_SOVEREIGN_OS_MOTO_X_PLAY.zip"
    print(f"📦 Empaquetando {zip_output.name}...")
    
    with zipfile.ZipFile(zip_output, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Añadir update-binary y updater-script
        zipf.write(binary_path, arcname="META-INF/com/google/android/update-binary")
        zipf.write(script_path, arcname="META-INF/com/google/android/updater-script")
        
        # Añadir APK del launcher
        zipf.write(target_apk, arcname="TardisLauncher.apk")
        
        # Añadir suite autónoma completa
        files_to_bundle = [
            "tardis_kaiju_pocket_engine.py",
            "tardis_pocket_daemon.py",
            "tardis_pocket_daemon.sh",
            "tardis_pocket.html",
            "sw.js",
            "manifest.json",
            "tardis_terminal_config.json",
            "start_tardis_terminal.sh",
            "setup_termux_boot.sh",
            "TARDIS_TERMINAL_APP.html"
        ]

        for fname in files_to_bundle:
            src = MOBILE_DIR / fname
            if src.exists():
                zipf.write(src, arcname=fname)
                print(f"  + Empaquetado: {fname}")

    size_mb = zip_output.stat().st_size / (1024 * 1024)
    print(f"✓ Paquete flashable creado exitosamente ({size_mb:.2f} MB): {zip_output}")
    print("===============================================================")

if __name__ == "__main__":
    build_rom()
