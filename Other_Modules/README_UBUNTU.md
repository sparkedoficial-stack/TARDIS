# Guía de Instalación y Operación en Linux Ubuntu - GODWORKS SYSTEM v26.4

Esta carpeta contiene la adaptación nativa completa de **GODWORKS SYSTEM v26.4** para sistemas operativos **Linux**, diseñada y optimizada específicamente para **Ubuntu 22.04 LTS** y **Ubuntu 24.04 LTS (x86_64 / amd64)**.

El sistema opera bajo una arquitectura **Dual-Stack Transparente**: los mismos archivos Python detectan automáticamente si se ejecutan en Windows o en Linux, activando las herramientas y llamadas al kernel nativas correspondientes (`nmcli`, `sysfs`, `BlueZ`, `flock`, `bash`, etc.) sin requerir bifurcaciones separadas de código.

---

## 1. Requisitos del Sistema

- **Distribución:** Ubuntu 20.04+, 22.04 LTS o 24.04 LTS.
- **Procesador:** CPU x86_64 con soporte AVX2 / FMA.
- **Memoria RAM:** Mínimo 16 GB (24 GB o más recomendado para modelos de gran escala).
- **Aceleración GPU (Opcional pero recomendada):** NVIDIA RTX (drivers `>= 535` para CUDA 12+).
- **Conectividad:**
  - Adaptador Wi-Fi (gestionado por `NetworkManager` / `nmcli`) para radar pasivo y análisis de espectro.
  - Adaptador Bluetooth / BLE (pila `bluez` / `bluetoothctl`) para escaneo de proximidad física.

---

## 2. Instalación en 1 Paso

En una terminal de Ubuntu, colócate en esta carpeta y ejecuta:

```bash
chmod +x setup_ubuntu.sh start_ubuntu.sh
./setup_ubuntu.sh
```

### ¿Qué realiza el instalador automáticamente?
1. **Paquetes APT:** Instala `python3`, `python3-venv`, `python3-pip`, `network-manager`, `bluez`, `lm-sensors`, `curl`, `jq`, `net-tools`, `pciutils`, `ffmpeg`, etc.
2. **Permisos de Hardware:** Agrega tu usuario a los grupos `netdev`, `dialout` y `bluetooth` para permitir el escaneo de radiofrecuencia y telemetría sin requerir privilegios de `root`.
3. **Entorno Virtual (.venv-linux):** Crea un entorno virtual Python dedicado y actualiza pip.
4. **Dependencias Python:** Instala las librerías necesarias (`flask`, `httpx`, `numpy`, `psutil`, `pillow`, `cryptography`, `rich`).
5. **Ollama:** Detecta si Ollama está presente; si no, ejecuta el instalador oficial de Linux.
6. **Cloudflared:** Descarga e instala el paquete `.deb` de Cloudflare para el túnel de internet seguro.

---

## 3. Modos de Ejecución

### Modo A: Lanzador Interactivo HUD
Ejecuta:
```bash
./start_ubuntu.sh
```
El lanzador te presentará un menú interactivo:
- **Opción 1:** Iniciar Suite Completa (`supervisor.py` vigila y mantiene activos todos los servicios).
- **Opción 2:** Servidor Web Dashboard (`gia_web_server.py` en el puerto `8757`).
- **Opción 3:** Servidor Maestro Temporal (`omni_temporal_control.py`).
- **Opción 4:** Puente de Internet Resiliente (`start_bridge.py` con túnel cifrado y código QR).
- **Opción 5:** Agente Autónomo GIA Interactivo en consola (`gia_agent.py` con soporte Bash nativo).
- **Opción 6:** Diagnóstico integral de hardware, sensores térmicos y radar RF calibrado a 1.0s.
- **Opción 7:** Iniciar el motor local Colibri (`./colibri/coli chat`).

### Modo B: Servicio de Fondo 24/7 (systemd)
Para registrar GODWORKS SYSTEM como un servicio que arranque automáticamente al encender el equipo:

1. Modifica las variables de usuario y ruta en `godworks.service`:
   ```bash
   sed -i "s|%USER%|$USER|g" godworks.service
   sed -i "s|%WORKDIR%|$(pwd)|g" godworks.service
   ```
2. Instala y habilita el servicio:
   ```bash
   sudo cp godworks.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now godworks.service
   ```
3. Comprueba el estado:
   ```bash
   sudo systemctl status godworks.service
   ```
4. Ver logs en tiempo real:
   ```bash
   journalctl -u godworks.service -f
   ```

---

## 4. Adaptaciones Técnicas Clave para Linux

### 1. Radar Pasivo Wi-Fi y Análisis de Espectro (1sg)
- **Implementación:** `rf_presence_radar.py` y `em_spectrum_engine.py` ejecutan `nmcli -t -f SSID,BSSID,SIGNAL,CHAN,FREQ dev wifi list` con fallback a `iwlist scan`.
- **Compatibilidad con VPS/Contenedores:** Si el sistema se ejecuta en un servidor virtual sin antena Wi-Fi física, genera balizas de referencia ambiental virtuales con micro-jitter físico, asegurando que las funciones matemáticas y la inferencia temporal nunca fallen por división entre cero.

### 2. Detección Bluetooth & BLE
- **Implementación:** `rf_noise_binary_engine.py` lee directamente las interfaces en `/sys/class/bluetooth/hci*` y ejecuta `bluetoothctl devices` con un tiempo de corte estricto de 1.0s para alimentar la matriz de inferencia.

### 3. Sensores Térmicos y Semiconductores
- **Implementación:** Lee en tiempo real los registros térmicos del kernel `/sys/class/thermal/thermal_zone*/temp` (mili-grados Celsius) junto con `nvidia-smi` y `psutil.sensors_temperatures()`.

### 4. Bóveda Criptográfica ECCA
- **Implementación:** `ecca_credentials.py` en Windows usa DPAPI. En Linux, utiliza cifrado autenticado simétrico (AES-GCM o HMAC-SHA256 CTR) derivado criptográficamente del identificador único de la máquina (`/etc/machine-id`), el home del usuario y una sal segura con permisos POSIX `0600`.

### 5. Agente Autónomo (gia_agent.py)
- **Implementación:** La herramienta `run_shell` invoca `/bin/bash -c` nativo y `open_app` utiliza `xdg-open`. Las rutas críticas del sistema de archivos Linux (`/etc`, `/boot`, `/sys`, `/proc`, `/dev`, `/root`, `/usr`) están rigurosamente protegidas contra escritura o borrado accidental por `agent_safety.py`.

---

## 5. Acceso al Dashboard Web

Una vez iniciado el servidor, abre tu navegador favorito en:
- **Local:** [http://localhost:8757](http://localhost:8757)
- **Red Local (LAN):** `http://<IP_DE_TU_UBUNTU>:8757`
- **Túnel Remoto Seguro:** Ejecuta `./start_ubuntu.sh` (opción 4) o `python3 start_bridge.py` para obtener un enlace público HTTPS / WSS con código QR escaneable desde tu móvil.
