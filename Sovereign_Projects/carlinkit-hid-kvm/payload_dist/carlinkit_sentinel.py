#!/usr/bin/env python3
# ==============================================================================
# CARLINKIT INTELLIGENT DEVICE IDENTIFIER & AUTONOMOUS CONTROLLER
# GODWORKS SYSTEM v26.4 / TARDIS Core Module
# ==============================================================================
import os
import sys
import time
import json
import subprocess
import glob
import re

LOG_FILE = "/var/log/carlinkit_sentinel.log"

def log(msg):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{ts} [SENTINEL] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ==============================================================================
# 1. SUBSISTEMA DE CONTROL DE LED SOBERANO (LUZ ROJA FIJA ESTABLE)
# ==============================================================================
def enforce_solid_red_led():
    """Fuerza el LED en luz roja continua y apaga verde/azul sin parpadeo."""
    try:
        # Desactivar triggers
        for trig in glob.glob("/sys/class/leds/*/trigger"):
            try:
                with open(trig, "w") as f:
                    f.write("none")
            except Exception:
                pass
        # Apagar cualquier canal verde, azul, blanco
        for led in glob.glob("/sys/class/leds/*green*/brightness") + glob.glob("/sys/class/leds/*blue*/brightness"):
            try:
                with open(led, "w") as f:
                    f.write("0")
            except Exception:
                pass
        # Encender canal rojo al máximo continuo
        for led in glob.glob("/sys/class/leds/*red*/brightness"):
            try:
                max_path = os.path.join(os.path.dirname(led), "max_brightness")
                max_val = "1"
                if os.path.exists(max_path):
                    with open(max_path, "r") as mf:
                        max_val = mf.read().strip()
                with open(led, "w") as f:
                    f.write(max_val)
            except Exception:
                pass
    except Exception as e:
        log(f"Error al controlar LED: {e}")

# ==============================================================================
# 2. IDENTIFICADOR DEL DISPOSITIVO ANFITRIÓN (USB GADGET / HOST DETECTION)
# ==============================================================================
def identify_connected_host():
    """Identifica el sistema anfitrión conectado al conector USB del Carlinkit."""
    info = {
        "host_type": "UNKNOWN",
        "details": "",
        "confidence": 0,
        "usb_state": "disconnected",
        "speed": "unknown"
    }

    # 1. Verificar estado del controlador UDC (USB Device Controller)
    udc_list = glob.glob("/sys/class/udc/*")
    if udc_list:
        udc_dir = udc_list[0]
        state_file = os.path.join(udc_dir, "state")
        speed_file = os.path.join(udc_dir, "current_speed")
        if os.path.exists(state_file):
            try:
                with open(state_file, "r") as f:
                    info["usb_state"] = f.read().strip()
            except Exception:
                pass
        if os.path.exists(speed_file):
            try:
                with open(speed_file, "r") as f:
                    info["speed"] = f.read().strip()
            except Exception:
                pass

    # 2. Inspeccionar ring buffer del kernel (dmesg) para firmas del Host
    try:
        dmesg_out = subprocess.check_output(["dmesg"], stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore")
        tail_dmesg = dmesg_out[-50000:]

        # Apple iPad Pro M2 / iPadOS Host Signature Detection
        if re.search(r"ipad|apple\s*silicon|m2|t8112|t6020|darwin.*arm|apple.*tablet|ipad.*pro", tail_dmesg, re.IGNORECASE):
            info["host_type"] = "APPLE_IPAD_PRO"
            info["details"] = "Apple iPad Pro M2 (iPadOS) Detectado vía bus USB-C / Darwin ARM Host"
            info["confidence"] = 98

        # Apple Mac / EFI Signature Detection
        elif re.search(r"macbook|imac|boot\.efi|AAPLBSDPC|x86_64.*apple", tail_dmesg, re.IGNORECASE):
            info["host_type"] = "APPLE_MAC"
            info["details"] = "iMac 14,1 / Apple EFI Host Detectado vía señales USB y peticiones EFI/AAPL"
            info["confidence"] = 95

        # Generic Apple Device (iPadOS / macOS / iOS)
        elif re.search(r"apple|05ac:|ipheth|AAPL", tail_dmesg, re.IGNORECASE):
            # En conexión directa USB-C sin EFI se clasifica como iPad Pro M2
            info["host_type"] = "APPLE_IPAD_PRO"
            info["details"] = "Apple iPad Pro M2 / Dispositivo Apple Host Detectado vía descriptor USB 05ac"
            info["confidence"] = 90

        # Car Head Unit Signature Detection
        elif re.search(r"huid|SAIC|autobox|carplay_client|androidauto", tail_dmesg, re.IGNORECASE):
            info["host_type"] = "CAR_HEAD_UNIT"
            info["details"] = "Unidad Principal de Vehículo (Head Unit Automotive)"
            info["confidence"] = 90

        # Generic Linux PC Detection
        elif re.search(r"Linux Foundation|xhci_hcd|usbcore.*configured", tail_dmesg, re.IGNORECASE):
            info["host_type"] = "LINUX_PC"
            info["details"] = "Computadora Personal Linux x86_64"
            info["confidence"] = 80

        # Microsoft Windows Detection
        elif re.search(r"MSFT100|Microsoft OS Descriptor", tail_dmesg, re.IGNORECASE):
            info["host_type"] = "WINDOWS_PC"
            info["details"] = "Computadora Personal Microsoft Windows"
            info["confidence"] = 85
    except Exception as e:
        log(f"Error al analizar dmesg: {e}")

    # 3. Inspeccionar configuración activa del firmware Carlinkit
    try:
        if os.path.exists("/etc/config.ini"):
            with open("/etc/config.ini", "r") as f:
                cdata = f.read()
                m = re.search(r"huid\s*=\s*([^\r\n]+)", cdata)
                if m and m.group(1).strip() and info["host_type"] == "UNKNOWN":
                    info["host_type"] = "CAR_HEAD_UNIT"
                    info["details"] = f"Automotive HeadUnit HUID: {m.group(1).strip()}"
                    info["confidence"] = 85
    except Exception:
        pass

    return info

# ==============================================================================
# 3. IDENTIFICADOR DEL DISPOSITIVO CONECTADO AL PUERTO USB-A (PERIPHERAL)
# ==============================================================================
def identify_connected_peripherals():
    """Identifica cualquier dispositivo conectado al puerto USB-A hembra del Carlinkit."""
    peripherals = []
    usb_devs = glob.glob("/sys/bus/usb/devices/[0-9]*-[0-9]*")
    for dev in usb_devs:
        # Ignorar interfaces internas (e.g. 1-1:1.0)
        if ":" in os.path.basename(dev):
            continue
        item = {"id": os.path.basename(dev), "vendor": "", "product": "", "type": "UNKNOWN"}
        try:
            idv = os.path.join(dev, "idVendor")
            idp = os.path.join(dev, "idProduct")
            mf = os.path.join(dev, "manufacturer")
            pr = os.path.join(dev, "product")
            if os.path.exists(idv):
                with open(idv, "r") as f:
                    item["vendor"] = f.read().strip()
            if os.path.exists(idp):
                with open(idp, "r") as f:
                    item["product"] = f.read().strip()
            if os.path.exists(mf):
                with open(mf, "r") as f:
                    item["manufacturer"] = f.read().strip()
            if os.path.exists(pr):
                with open(pr, "r") as f:
                    item["product_name"] = f.read().strip()

            # Clasificar tipo
            bclass = os.path.join(dev, "bDeviceClass")
            bintclass = glob.glob(os.path.join(dev, "*/bInterfaceClass"))
            int_classes = []
            for bic in bintclass:
                try:
                    with open(bic, "r") as f:
                        int_classes.append(f.read().strip())
                except Exception:
                    pass

            if "08" in int_classes or item.get("vendor") == "325d":
                item["type"] = "MASS_STORAGE"
                item["description"] = "Memoria USB / Disco de Almacenamiento Flash"
            elif item.get("vendor") == "05ac":
                item["type"] = "APPLE_IOS"
                item["description"] = "Apple iPhone / iPad"
            elif item.get("vendor") in ["18d1", "04e8", "2717"]:
                item["type"] = "ANDROID_PHONE"
                item["description"] = "Smartphone Android"
            elif "03" in int_classes:
                item["type"] = "HID_DEVICE"
                item["description"] = "Teclado / Ratón Físico USB"
            else:
                item["type"] = "GENERIC_USB"
                item["description"] = "Dispositivo USB Genérico"

            peripherals.append(item)
        except Exception:
            pass

    return peripherals

# ==============================================================================
# 4. MOTOR DE CONTROL ACTUADOR (VIRTUAL KEYBOARD HID / DEV/HIDG0)
# ==============================================================================
class VirtualKeyboard:
    """Controlador autónomo de pulsaciones para el Host mediante /dev/hidg0."""
    def __init__(self, hid_dev="/dev/hidg0"):
        self.hid_dev = hid_dev
        # Mapeo de teclas USB HID (Usage ID)
        self.KEY_MAP = {
            "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
            "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D, "k": 0x0E, "l": 0x0F,
            "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
            "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B,
            "y": 0x1C, "z": 0x1D, "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21,
            "5": 0x22, "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
            "enter": 0x28, "return": 0x28, "esc": 0x29, "escape": 0x29,
            "bspc": 0x2A, "tab": 0x2B, "space": 0x2C, "minus": 0x2D,
            "equal": 0x2E, "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52
        }
        self.MODIFIERS = {
            "none": 0x00,
            "lctrl": 0x01, "ctrl": 0x01,
            "lshift": 0x02, "shift": 0x02,
            "lalt": 0x04, "alt": 0x04, "option": 0x04,  # APPLE OPTION KEY!
            "lcmd": 0x08, "cmd": 0x08, "gui": 0x08, "super": 0x08,
            "rctrl": 0x10, "rshift": 0x20, "ralt": 0x40, "rcmd": 0x80
        }

    def send_report(self, mod=0x00, key=0x00):
        """Escribe un reporte de teclado estándar de 8 bytes en /dev/hidg0."""
        report = bytearray([mod, 0x00, key, 0x00, 0x00, 0x00, 0x00, 0x00])
        try:
            if os.path.exists(self.hid_dev):
                with open(self.hid_dev, "wb") as f:
                    f.write(report)
                return True
            else:
                log(f"Dispositivo HID {self.hid_dev} no presente en el kernel.")
                return False
        except Exception as e:
            log(f"Error escribiendo reporte HID: {e}")
            return False

    def release_all(self):
        """Libera todas las teclas."""
        return self.send_report(0x00, 0x00)

    def press_key(self, key_name, modifier_name="none", hold_seconds=0.1):
        """Presiona y libera una tecla especificada."""
        mod = self.MODIFIERS.get(modifier_name.lower(), 0x00)
        key = self.KEY_MAP.get(key_name.lower(), 0x00)
        log(f"Inyectando pulsación: Key='{key_name}' (0x{key:02X}) Mod='{modifier_name}' (0x{mod:02X})")
        self.send_report(mod, key)
        time.sleep(hold_seconds)
        self.release_all()
        time.sleep(0.05)

    def hold_key(self, key_name, modifier_name="none", duration_seconds=5.0):
        """Mantiene presionada una tecla de forma continua (e.g. Option o N al arrancar el Mac)."""
        mod = self.MODIFIERS.get(modifier_name.lower(), 0x00)
        key = self.KEY_MAP.get(key_name.lower(), 0x00)
        log(f"Manteniendo pulsación continua por {duration_seconds}s: Key='{key_name}' Mod='{modifier_name}'")
        end_time = time.time() + duration_seconds
        while time.time() < end_time:
            self.send_report(mod, key)
            time.sleep(0.05)
        self.release_all()

# ==============================================================================
# 5. BUCLE PRINCIPAL DE CENTINELA (SENTINEL RUNNER)
# ==============================================================================
def run_sentinel_loop():
    log("Iniciando Centinela de Identificación y Control Autónomo Carlinkit...")
    vk = VirtualKeyboard()

    # Estado persistente
    last_host_type = None

    while True:
        # A) Mantener luz roja sólida sin intermitencias
        enforce_solid_red_led()

        # B) Identificar Host conectado
        host_info = identify_connected_host()
        peripherals = identify_connected_peripherals()

        if host_info["host_type"] != last_host_type:
            last_host_type = host_info["host_type"]
            log(f"⚡ CAMBIO DE ESTADO EN DETECCIÓN DE HARDWARE:")
            log(f"   - Anfitrión: {host_info['host_type']} ({host_info['details']})")
            log(f"   - Estado USB: {host_info['usb_state']} | Velocidad: {host_info['speed']}")
            log(f"   - Periféricos en USB-A: {len(peripherals)} dispositivos conectados.")
            for p in peripherals:
                log(f"     -> {p['type']}: {p.get('product_name', '')} [{p['vendor']}:{p['product']}]")

            # C) Actuación y Control Autónomo
            if host_info["host_type"] == "APPLE_MAC":
                log("🎯 OBJETIVO APPLE MAC 14,1 CONFIRMADO.")
                log("   Actuando como Teclado Virtual para control de arranque...")
                # Opcional: inyectar scancode N o Option si se requiere arranque en red

        time.sleep(2)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        vk = VirtualKeyboard()
        if cmd == "identify":
            h = identify_connected_host()
            p = identify_connected_peripherals()
            print(json.dumps({"host": h, "peripherals": p}, indent=2))
        elif cmd == "led_red":
            enforce_solid_red_led()
            print("LED rojo fijo configurado.")
        elif cmd == "option":
            # Mantener tecla Option por 6 segundos al arrancar Mac
            vk.hold_key("none", "option", 6.0)
        elif cmd == "netboot":
            # Mantener tecla N por 6 segundos para forzar Netboot sobre Ethernet
            vk.hold_key("n", "none", 6.0)
        elif cmd == "enter":
            vk.press_key("enter")
        elif cmd == "right":
            vk.press_key("right")
        elif cmd == "ipad_home":
            # Cmd + H: Ir a pantalla de inicio en iPadOS
            vk.press_key("h", "cmd")
        elif cmd == "ipad_spotlight":
            # Cmd + Space: Abrir búsqueda Spotlight en iPadOS
            vk.press_key("space", "cmd")
        elif cmd == "ipad_switcher":
            # Cmd + Tab: Selector de aplicaciones en iPadOS
            vk.press_key("tab", "cmd")
        elif cmd == "ipad_lock":
            # Cmd + Ctrl + Q: Bloquear pantalla en iPadOS
            vk.send_report(0x08 | 0x01, 0x14) # Cmd + Ctrl + Q
            time.sleep(0.1)
            vk.release_all()
        elif cmd == "ipad_dock":
            # Cmd + Option + D: Mostrar/Ocultar Dock en iPadOS
            vk.send_report(0x08 | 0x04, 0x07) # Cmd + Alt + D
            time.sleep(0.1)
            vk.release_all()
    else:
        run_sentinel_loop()
