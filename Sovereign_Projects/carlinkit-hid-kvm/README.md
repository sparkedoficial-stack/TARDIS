# ⚡ Carlinkit Universal Virtual Keyboard & Mouse (HID) Engine

Convierte un adaptador **Carlinkit** (como las series CPC200-U2W, 3.0, 4.0, 5.0, CCPA) o cualquier sistema Linux en un **Controlador y Cliente de Teclado y Ratón Virtual Plug-and-Play**, capaz de inyectar pulsaciones de teclado y movimientos de ratón a nivel de hardware/kernel sin necesidad de controladores adicionales en el equipo controlado.

---

## 1. Arquitectura de Operación Dual

El motor opera de manera transparente en dos modalidades:

### Modo A: Hardware USB-C Plug & Play (Dongle Físico Carlinkit)
```
[Dispositivo de Control]  --- (Wi-Fi / Web KVM en puerto 8080) ---> [Carlinkit Dongle]
  (Móvil / Portátil / PC)                                             | (SoC Linux Embebido)
                                                                      | (/dev/hidg0 & /dev/hidg1)
                                                                      V (Conector USB-C)
                                                            [Máquina Objetivo (Target)]
                                                            (PC / Mac / Tablet / Consola / BIOS)
                                                            *Reconoce Teclado y Mouse Logitech*
```

### Modo B: Entrada Virtual a Nivel de Kernel Linux (`/dev/uinput`)
```
[Dispositivo de Control]  --- (Red / Wi-Fi Hotspot en puerto 8080) ---> [Servidor Carlinkit HID]
  (Móvil / Tablet / Navegador)                                           | (Linux Kernel Ring 0)
                                                                         | (/dev/uinput)
                                                                         V
                                                            [Sistema Operativo Local]
                                                            *Control inmediato de Pantalla y GUI*
```

---

## 2. Componentes Técnicos

1. **[`setup_carlinkit_hid.sh`](file:///home/timemachine/carlinkit-hid-kvm/scripts/setup_carlinkit_hid.sh)**:
   - Desactiva los demonios stock de fábrica (`autobox`, `box`, `linkserver`).
   - Configura el subsistema **Linux USB Gadget (`configfs`)** del controlador OTG/UDC.
   - Emula identificadores de alta compatibilidad: **`0x046d:0xc31c`** (Logitech USB Optical Mouse & Keyboard Combo).
   - Registra dos endpoints HID estándar:
     - `/dev/hidg0`: Teclado USB Boot Protocol (8 bytes por reporte).
     - `/dev/hidg1`: Mouse óptico de 3 botones con rueda de desplazamiento (4 bytes por reporte).

2. **[`carlinkit_hid_server.py`](file:///home/timemachine/carlinkit-hid-kvm/server/carlinkit_hid_server.py)**:
   - Demonio servidor multi-hilo en Python que escucha en el puerto `8080`.
   - Soporta **WebSockets RFC 6455** para transmisión de movimiento de ratón en tiempo real (< 1 ms de latencia) y fallback REST.
   - Detección automática de backend:
     - Si existen `/dev/hidg0` y `/dev/hidg1`, emite paquetes USB HID directos por el conector USB-C físico.
     - Si no existen los nodos gadget pero `/dev/uinput` está disponible, genera dispositivos virtuales a nivel de kernel (`Carlinkit Virtual Mouse` y `Carlinkit Virtual Keyboard`).

3. **[`web/index.html`](file:///home/timemachine/carlinkit-hid-kvm/web/index.html)**:
   - Panel táctil ultra-rápido optimizado para pantallas táctiles de teléfonos móviles y laptops.
   - Gestos: Deslizar (mover cursor con aceleración), 1 toque (click izquierdo), 2 toques (click derecho), deslizamiento vertical con 2 dedos (scroll wheel).
   - Inyector de texto directo a velocidad de hardware.
   - Captura de teclado físico en vivo (modo interactivo).
   - Botonera de combinaciones críticas: `Ctrl+Alt+Del`, `Win / Super`, `Alt+Tab`, `Ctrl+Shift+Esc`, `F1-F12`, etc.

4. **[`carlinkit-hid.service`](file:///etc/systemd/system/carlinkit-hid.service)**:
   - Servicio systemd en segundo plano completamente desacoplado de la CLI con reinicio automático y registro en `/var/log/carlinkit_hid.log`.

---

## 3. URLs de Acceso y Control Inmediato

El servicio se encuentra activo y disponible en:

| Origen | Dirección URL |
| :--- | :--- |
| **Desde este equipo (Local)** | `http://127.0.0.1:8080` |
| **Desde tu móvil / iPad (Vía Hotspot "TimeMachine")** | `http://REDACTED_IP:8080` |
| **Desde cualquier dispositivo en la Red Local (Wi-Fi/LAN)** | `http://REDACTED_IP:8080` |
| **Desde el dongle Carlinkit flasheado (Wi-Fi propia)** | `http://REDACTED_IP:8080` |

---

## 4. Despliegue en el Adaptador Físico Carlinkit

Para que el adaptador Carlinkit funcione de forma autónoma conectado por USB-C a una máquina externa:

### Opción 1: Memoria USB (FAT32)
1. Formatea una memoria USB en **FAT32**.
2. Copia todos los archivos de la carpeta [`payload_dist`](file:///home/timemachine/carlinkit-hid-kvm/payload_dist) a la raíz del pendrive:
   - `auto_run.sh`
   - `factory.sh`
   - `update.sh`
   - `setup_hid.sh`
   - `hid_server.py`
   - `carlinkit-hid.service`
   - Carpeta `web/` con `index.html`
3. Conecta la memoria al puerto USB-A hembra del Carlinkit y aliméntalo por USB-C.
4. El cargador de arranque ejecutará `auto_run.sh` o `factory.sh`, reemplazará el firmware de CarPlay y dejará listos los nodos `/dev/hidg0` y `/dev/hidg1`.

### Opción 2: Despliegue por Red (SSH / Wi-Fi a REDACTED_IP)
1. Conéctate a la red Wi-Fi del Carlinkit (SSID tipo `AutoKit_xxxx` o `VOLVO_xxxx`, clave `12345678`).
2. Ejecuta el script de despliegue automatizado:
   ```bash
   /home/timemachine/carlinkit-hid-kvm/payload_dist/install_network.sh REDACTED_IP
   ```
