# 🍏 AirPlay Monitor Soberano

Aplicación interactiva nativa con interfaz gráfica (GTK 4 / Libadwaita) para la **monitorización, telemetría y control** del receptor AirPlay en Linux, optimizado para dispositivos Apple iOS (iPhone, iPad) y macOS.

---

## 🌟 Características Principales

### 1. 🎛️ Panel de Control en Vivo (Dashboard)
- **Estado del Servidor en Tiempo Real:** Visualiza si el receptor AirPlay (`TimeMachine-AirPlay`) está activo, detenido o en transición con un interruptor de encendido/apagado directo.
- **Detección Instantánea de Conexión:** Muestra el dispositivo que está transmitiendo en tiempo real (ej. *iPad de Miguel*), modelo de hardware, ID de dispositivo, dirección IP remota y modo de streaming (Mirroring 60 FPS o Audio ALAC).
- **Telemetría de Recursos:** Monitoreo en vivo de consumo de CPU, memoria RAM y PID del proceso.
- **Direcciones de Red mDNS:** Muestra las IPs locales (LAN Ethernet y Wi-Fi Hotspot) con sus puertos abiertos.
- **Acciones Rápidas:** Botones para reiniciar el receptor y verificar los anuncios mDNS de Avahi.

### 2. 📡 Explorador de Red y mDNS
- Escáner en tiempo real de servicios `_airplay._tcp`, `_raop._tcp` y `_companion-link._tcp`.
- Detección de dispositivos Apple en la subred con indicación del estado del puerto Lockdown `62078`.

### 3. 🔌 Dispositivos Apple por Cable USB
- Integración nativa con `usbmuxd`, `idevicepair`, `ideviceinfo` e `ifuse`.
- Lectura de nivel de batería y estado de carga.
- Verificación del estado de confianza (Lockdown Pairing).
- **Montaje con 1 Clic:** Monta el sistema de archivos de iOS en `~/Dispositivos/Apple_iOS` y abre el explorador Nautilus automáticamente para transferir fotos y documentos.

### 4. 📜 Registro de Eventos en Tiempo Real (Live Logs)
- Streaming continuo de logs del servicio con resaltado de sintaxis (errores, advertencias, conexiones exitosas).
- Filtro de búsqueda en tiempo real, botón para pausar auto-scroll y copia al portapapeles.

### 5. ⚙️ Configuración del Servidor y Rendimiento Extremo
- **Tasa de Cuadros Dinámica (hasta 144 FPS):** Soporte para streaming de tasa variable adaptativa (Variable Refresh Rate / ProMotion de Apple) con techo a 144Hz.
- **Telemetría de FPS en Vivo (`FPSdata`):** Monitorea la tasa de cuadros y rendimiento transmitida en tiempo real desde el cliente.
- **Resolución Nativa del Monitor:** Modos preconfigurados a 144Hz: `2560x1440@144` (QHD 2K Nativo del monitor), `3840x2160@144` (4K UHD) y `1920x1080@144` (1080p).
- **Decodificación Hardware por GPU:** Directa en NVIDIA GeForce RTX 3050 (`nvh264dec` / `nvh265dec`).
- **Modo Tiempo Real (vsync no):** Decodificación y dibujo inmediato de fotogramas sin retardos de búfer.
- **Gama sRGB Completa [0-255]:** Color auténtico sin compresión a niveles de video.
- **Soporte Códec H.265 / HEVC:** Máxima nitidez y fidelidad Retina.

---

## 🚀 Instalación y Empaquetado

Para instalar o actualizar todos los componentes del sistema, ejecuta:

```bash
cd /home/timemachine/airplay-monitor
./install.sh
```

El script configura automáticamente:
1. Permisos de ejecución.
2. Iconos vectoriales y renderizados en el tema estándar del sistema (`~/.local/share/icons/hicolor/`).
3. Acceso directo en el Escritorio: `~/Escritorio/AirPlay Monitor.desktop`.
4. Registro en el menú de aplicaciones de GNOME: `~/.local/share/applications/airplay-monitor.desktop`.
5. Comandos en el PATH: `airplay-monitor` y `airplay-studio`.

---

## 🖥️ Formas de Interactuar con el Sistema

Puedes abrir la aplicación de cualquiera de las siguientes maneras:

1. **Doble clic en el icono del Escritorio:** `AirPlay Monitor`
2. **Desde el menú de aplicaciones de GNOME:** Presiona la tecla `Super` (Windows) y escribe `AirPlay Monitor`.
3. **Desde el terminal:**
   ```bash
   airplay-monitor
   ```
4. **Desde las herramientas existentes:**
   ```bash
   screen-ctl gui
   # o bien:
   apple-ctl gui
   ```

---

## 📲 ¿Cómo Conectar tu iPhone o iPad?

1. Conecta tu iPhone o iPad a la misma red Wi-Fi o al Hotspot TimeMachine (`REDACTED_IP`).
2. Desliza hacia abajo desde la esquina superior derecha para abrir el **Centro de Control**.
3. Toca el botón **Duplicar pantalla** (dos pantallas rectangulares superpuestas).
4. Selecciona **TimeMachine-AirPlay**.
5. ¡La pantalla de tu dispositivo aparecerá inmediatamente en el monitor!

> **Atajo de Teclado:** Presiona `F11` o `Alt+Enter` en la ventana de duplicación para alternar a **Pantalla Completa**.
