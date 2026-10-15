#!/usr/bin/env python3
# ==============================================================================
# CARLINKIT UNIVERSAL VIRTUAL MOUSE & KEYBOARD ENGINE (SERVER & DAEMON)
# Supports Dual-Mode Operation:
# 1. Hardware USB Gadget (/dev/hidg0, /dev/hidg1) for Physical USB-C OTG Devices
# 2. Linux Kernel Input (/dev/uinput) for Local/Remote Virtual Control
# Includes Ultra-Low Latency WebSocket & REST API + Modern Web KVM Touch UI
# ==============================================================================

import os
import sys
import time
import json
import socket
import struct
import fcntl
import select
import hashlib
import base64
import signal
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.parse

PORT = 8080
KEYBOARD_DEV = "/dev/hidg0"
MOUSE_DEV = "/dev/hidg1"
UINPUT_DEV = "/dev/uinput"

# Linux uinput ioctls & constants
UI_SET_EVBIT   = 0x40045564
UI_SET_KEYBIT  = 0x40045565
UI_SET_RELBIT  = 0x40045566
UI_DEV_SETUP   = 0x405c5503
UI_DEV_CREATE  = 0x5501
UI_DEV_DESTROY = 0x5502

EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02

REL_X = 0x00
REL_Y = 0x01
REL_WHEEL = 0x08
REL_HWHEEL = 0x06

BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113
BTN_EXTRA = 0x114

TIME_FMT = 'll' if struct.calcsize('P') == 8 else 'ii'
EVENT_FMT = TIME_FMT + 'HHi'

# USB HID Usage Page 0x07 (Keyboard) Codes
HID_KEYMAP = {
    'a': 0x04, 'b': 0x05, 'c': 0x06, 'd': 0x07, 'e': 0x08, 'f': 0x09,
    'g': 0x0A, 'h': 0x0B, 'i': 0x0C, 'j': 0x0D, 'k': 0x0E, 'l': 0x0F,
    'm': 0x10, 'n': 0x11, 'o': 0x12, 'p': 0x13, 'q': 0x14, 'r': 0x15,
    's': 0x16, 't': 0x17, 'u': 0x18, 'v': 0x19, 'w': 0x1A, 'x': 0x1B,
    'y': 0x1C, 'z': 0x1D,
    '1': 0x1E, '2': 0x1F, '3': 0x20, '4': 0x21, '5': 0x22,
    '6': 0x23, '7': 0x24, '8': 0x25, '9': 0x26, '0': 0x27,
    '\n': 0x28, 'enter': 0x28, 'return': 0x28,
    'esc': 0x29, 'escape': 0x29,
    '\b': 0x2A, 'backspace': 0x2A,
    '\t': 0x2B, 'tab': 0x2B,
    ' ': 0x2C, 'space': 0x2C,
    '-': 0x2D, '=': 0x2E, '[': 0x2F, ']': 0x30, '\\': 0x31,
    ';': 0x33, "'": 0x34, '`': 0x35, ',': 0x36, '.': 0x37, '/': 0x38,
    'capslock': 0x39,
    'f1': 0x3A, 'f2': 0x3B, 'f3': 0x3C, 'f4': 0x3D, 'f5': 0x3E, 'f6': 0x3F,
    'f7': 0x40, 'f8': 0x41, 'f9': 0x42, 'f10': 0x43, 'f11': 0x44, 'f12': 0x45,
    'printscreen': 0x46, 'scrolllock': 0x47, 'pause': 0x48,
    'insert': 0x49, 'home': 0x4A, 'pageup': 0x4B,
    'delete': 0x4C, 'end': 0x4D, 'pagedown': 0x4E,
    'right': 0x4F, 'left': 0x50, 'down': 0x51, 'up': 0x52
}

# Linux Input Event KEY_* Codes (for uinput)
UINPUT_KEYMAP = {
    'esc': 1, 'escape': 1,
    '1': 2, '2': 3, '3': 4, '4': 5, '5': 6, '6': 7, '7': 8, '8': 9, '9': 10, '0': 11,
    '-': 12, '=': 13, '\b': 14, 'backspace': 14, '\t': 15, 'tab': 15,
    'q': 16, 'w': 17, 'e': 18, 'r': 19, 't': 20, 'y': 21, 'u': 22, 'i': 23, 'o': 24, 'p': 25,
    '[': 26, ']': 27, '\n': 28, 'enter': 28, 'return': 28,
    'ctrl': 29, 'lctrl': 29,
    'a': 30, 's': 31, 'd': 32, 'f': 33, 'g': 34, 'h': 35, 'j': 36, 'k': 37, 'l': 38,
    ';': 39, "'": 40, '`': 41, 'shift': 42, 'lshift': 42, '\\': 43,
    'z': 44, 'x': 45, 'c': 46, 'v': 47, 'b': 48, 'n': 49, 'm': 50,
    ',': 51, '.': 52, '/': 53, 'rshift': 54, 'alt': 56, 'lalt': 56, 'space': 57, ' ': 57,
    'capslock': 58,
    'f1': 59, 'f2': 60, 'f3': 61, 'f4': 62, 'f5': 63, 'f6': 64,
    'f7': 65, 'f8': 66, 'f9': 67, 'f10': 68, 'f11': 87, 'f12': 88,
    'rctrl': 97, 'ralt': 100,
    'home': 102, 'up': 103, 'pageup': 104, 'left': 105, 'right': 106,
    'end': 107, 'down': 108, 'pagedown': 109, 'insert': 110, 'delete': 111,
    'mute': 113, 'volumedown': 114, 'volumeup': 115, 'power': 116,
    'super': 125, 'meta': 125, 'win': 125, 'cmd': 125,
    'playpause': 164
}

SHIFT_MAP = {
    '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
    '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
    '_': '-', '+': '=', '{': '[', '}': ']', '|': '\\',
    ':': ';', '"': "'", '~': '`', '<': ',', '>': '.', '?': '/'
}

HID_MODIFIERS = {
    'ctrl': 0x01, 'lctrl': 0x01,
    'shift': 0x02, 'lshift': 0x02,
    'alt': 0x04, 'lalt': 0x04,
    'meta': 0x08, 'win': 0x08, 'cmd': 0x08, 'super': 0x08,
    'rctrl': 0x10, 'rshift': 0x20, 'ralt': 0x40, 'rmeta': 0x80
}

class UniversalHIDManager:
    """Manages input emission to either physical USB Gadget endpoints or Linux Kernel /dev/uinput."""
    def __init__(self, force_mode=None):
        self.mode = "simulation"
        self.kbd_fd = None
        self.mouse_fd = None
        self.uinput_mouse_fd = None
        self.uinput_kbd_fd = None
        self.lock = threading.Lock()

        # Check for Hardware USB Gadget mode (/dev/hidg0 and /dev/hidg1)
        gadget_ok = os.path.exists(KEYBOARD_DEV) and os.path.exists(MOUSE_DEV)
        uinput_ok = os.path.exists(UINPUT_DEV) and os.access(UINPUT_DEV, os.W_OK)

        if force_mode == "hid" or (force_mode is None and gadget_ok):
            try:
                self.kbd_fd = open(KEYBOARD_DEV, 'wb', buffering=0)
                self.mouse_fd = open(MOUSE_DEV, 'wb', buffering=0)
                self.mode = "hardware_hid"
                print(f"[+] Initialized in HARDWARE USB GADGET mode ({KEYBOARD_DEV}, {MOUSE_DEV})")
            except Exception as e:
                print(f"[-] Failed opening hardware USB gadget nodes: {e}")

        if self.mode != "hardware_hid" and (force_mode == "uinput" or uinput_ok):
            try:
                self._init_uinput()
                self.mode = "kernel_uinput"
                print("[+] Initialized in LINUX KERNEL UINPUT mode (/dev/uinput)")
            except Exception as e:
                print(f"[-] Failed initializing Linux Kernel uinput: {e}")

        if self.mode == "simulation":
            print("[!] Running in SIMULATION mode (Events logged, no hardware/kernel nodes active)")

    def _init_uinput(self):
        # 1. Virtual Mouse Setup
        self.uinput_mouse_fd = os.open(UINPUT_DEV, os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.uinput_mouse_fd, UI_SET_EVBIT, EV_KEY)
        for btn in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA):
            fcntl.ioctl(self.uinput_mouse_fd, UI_SET_KEYBIT, btn)
        fcntl.ioctl(self.uinput_mouse_fd, UI_SET_EVBIT, EV_REL)
        for rel in (REL_X, REL_Y, REL_WHEEL, REL_HWHEEL):
            fcntl.ioctl(self.uinput_mouse_fd, UI_SET_RELBIT, rel)

        mouse_setup = struct.pack('HHHH80sI', 0x03, 0x046d, 0xc31c, 1, b'Carlinkit Virtual Mouse\x00', 0)
        fcntl.ioctl(self.uinput_mouse_fd, UI_DEV_SETUP, mouse_setup)
        fcntl.ioctl(self.uinput_mouse_fd, UI_DEV_CREATE)

        # 2. Virtual Keyboard Setup
        self.uinput_kbd_fd = os.open(UINPUT_DEV, os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.uinput_kbd_fd, UI_SET_EVBIT, EV_KEY)
        for k in range(1, 248):
            try:
                fcntl.ioctl(self.uinput_kbd_fd, UI_SET_KEYBIT, k)
            except Exception:
                pass

        kbd_setup = struct.pack('HHHH80sI', 0x03, 0x046d, 0xc31c, 1, b'Carlinkit Virtual Keyboard\x00', 0)
        fcntl.ioctl(self.uinput_kbd_fd, UI_DEV_SETUP, kbd_setup)
        fcntl.ioctl(self.uinput_kbd_fd, UI_DEV_CREATE)

    def close(self):
        with self.lock:
            if self.kbd_fd:
                try: self.kbd_fd.close()
                except Exception: pass
            if self.mouse_fd:
                try: self.mouse_fd.close()
                except Exception: pass
            if self.uinput_mouse_fd:
                try:
                    fcntl.ioctl(self.uinput_mouse_fd, UI_DEV_DESTROY)
                    os.close(self.uinput_mouse_fd)
                except Exception: pass
            if self.uinput_kbd_fd:
                try:
                    fcntl.ioctl(self.uinput_kbd_fd, UI_DEV_DESTROY)
                    os.close(self.uinput_kbd_fd)
                except Exception: pass

    # ==================== MOUSE CONTROL ====================
    def mouse_move(self, dx: int, dy: int, buttons: int = 0, wheel: int = 0):
        with self.lock:
            if self.mode == "hardware_hid":
                dx_c = max(-127, min(127, int(dx))) & 0xFF
                dy_c = max(-127, min(127, int(dy))) & 0xFF
                wh_c = max(-127, min(127, int(wheel))) & 0xFF
                report = bytes([buttons & 0x07, dx_c, dy_c, wh_c])
                try:
                    self.mouse_fd.write(report)
                except Exception as e:
                    print(f"[-] Hardware Mouse Write Error: {e}")
            elif self.mode == "kernel_uinput":
                try:
                    if dx != 0:
                        os.write(self.uinput_mouse_fd, struct.pack(EVENT_FMT, 0, 0, EV_REL, REL_X, int(dx)))
                    if dy != 0:
                        os.write(self.uinput_mouse_fd, struct.pack(EVENT_FMT, 0, 0, EV_REL, REL_Y, int(dy)))
                    if wheel != 0:
                        os.write(self.uinput_mouse_fd, struct.pack(EVENT_FMT, 0, 0, EV_REL, REL_WHEEL, int(wheel)))
                    os.write(self.uinput_mouse_fd, struct.pack(EVENT_FMT, 0, 0, EV_SYN, 0, 0))
                except Exception as e:
                    print(f"[-] Uinput Mouse Move Error: {e}")

    def mouse_button(self, button: str, action: str = "click"):
        b_map_hid = {"left": 0x01, "right": 0x02, "middle": 0x04}
        b_map_uinput = {"left": BTN_LEFT, "right": BTN_RIGHT, "middle": BTN_MIDDLE}

        btn_str = button.lower()
        btn_hid = b_map_hid.get(btn_str, 0x01)
        btn_code = b_map_uinput.get(btn_str, BTN_LEFT)

        with self.lock:
            if self.mode == "hardware_hid":
                if action in ("click", "down"):
                    self.mouse_fd.write(bytes([btn_hid, 0, 0, 0]))
                if action in ("click", "up"):
                    if action == "click": time.sleep(0.02)
                    self.mouse_fd.write(bytes([0, 0, 0, 0]))
            elif self.mode == "kernel_uinput":
                try:
                    if action in ("click", "down"):
                        os.write(self.uinput_mouse_fd, struct.pack(EVENT_FMT, 0, 0, EV_KEY, btn_code, 1))
                        os.write(self.uinput_mouse_fd, struct.pack(EVENT_FMT, 0, 0, EV_SYN, 0, 0))
                    if action in ("click", "up"):
                        if action == "click": time.sleep(0.02)
                        os.write(self.uinput_mouse_fd, struct.pack(EVENT_FMT, 0, 0, EV_KEY, btn_code, 0))
                        os.write(self.uinput_mouse_fd, struct.pack(EVENT_FMT, 0, 0, EV_SYN, 0, 0))
                except Exception as e:
                    print(f"[-] Uinput Button Error: {e}")

    # ==================== KEYBOARD CONTROL ====================
    def send_key(self, key: str, action: str = "press"):
        key_lower = key.strip().lower()
        if "+" in key_lower:
            self.send_combination(key_lower)
            return

        with self.lock:
            if self.mode == "hardware_hid":
                keycode = HID_KEYMAP.get(key_lower, 0)
                if keycode:
                    if action in ("press", "down"):
                        self.kbd_fd.write(bytes([0, 0, keycode, 0, 0, 0, 0, 0]))
                    if action in ("press", "up"):
                        if action == "press": time.sleep(0.02)
                        self.kbd_fd.write(bytes(8))
            elif self.mode == "kernel_uinput":
                keycode = UINPUT_KEYMAP.get(key_lower, 0)
                if keycode:
                    try:
                        if action in ("press", "down"):
                            os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_KEY, keycode, 1))
                            os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_SYN, 0, 0))
                        if action in ("press", "up"):
                            if action == "press": time.sleep(0.02)
                            os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_KEY, keycode, 0))
                            os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_SYN, 0, 0))
                    except Exception as e:
                        print(f"[-] Uinput Key Error: {e}")

    def send_combination(self, combo: str):
        parts = [p.strip().lower() for p in combo.split('+')]
        with self.lock:
            if self.mode == "hardware_hid":
                mod = 0
                keys = []
                for p in parts:
                    if p in HID_MODIFIERS: mod |= HID_MODIFIERS[p]
                    elif p in HID_KEYMAP: keys.append(HID_KEYMAP[p])
                report = bytearray(8)
                report[0] = mod
                for i, k in enumerate(keys[:6]): report[2 + i] = k
                self.kbd_fd.write(bytes(report))
                time.sleep(0.04)
                self.kbd_fd.write(bytes(8))
            elif self.mode == "kernel_uinput":
                active_codes = []
                for p in parts:
                    code = UINPUT_KEYMAP.get(p)
                    if code:
                        active_codes.append(code)
                        os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_KEY, code, 1))
                os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_SYN, 0, 0))
                time.sleep(0.04)
                for code in active_codes:
                    os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_KEY, code, 0))
                os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_SYN, 0, 0))

    def type_text(self, text: str, delay: float = 0.015):
        for char in text:
            is_shift = False
            base_char = char
            if char.isupper():
                is_shift = True
                base_char = char.lower()
            elif char in SHIFT_MAP:
                is_shift = True
                base_char = SHIFT_MAP[char]

            if self.mode == "hardware_hid":
                keycode = HID_KEYMAP.get(base_char, 0)
                if keycode:
                    mod = 0x02 if is_shift else 0x00
                    with self.lock:
                        self.kbd_fd.write(bytes([mod, 0, keycode, 0, 0, 0, 0, 0]))
                        time.sleep(0.01)
                        self.kbd_fd.write(bytes(8))
            elif self.mode == "kernel_uinput":
                keycode = UINPUT_KEYMAP.get(base_char, 0)
                if keycode:
                    with self.lock:
                        if is_shift:
                            os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_KEY, UINPUT_KEYMAP['shift'], 1))
                        os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_KEY, keycode, 1))
                        os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_SYN, 0, 0))
                        time.sleep(0.01)
                        os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_KEY, keycode, 0))
                        if is_shift:
                            os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_KEY, UINPUT_KEYMAP['shift'], 0))
                        os.write(self.uinput_kbd_fd, struct.pack(EVENT_FMT, 0, 0, EV_SYN, 0, 0))
            time.sleep(delay)


hid_manager = UniversalHIDManager()

def handle_websocket(sock, key):
    """Simple RFC 6455 WebSocket Handler for sub-millisecond mouse & keyboard transport."""
    guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept_val = base64.b64encode(hashlib.sha1((key + guid).encode('utf-8')).digest()).decode('utf-8')
    handshake = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_val}\r\n\r\n"
    )
    sock.sendall(handshake.encode('utf-8'))

    sock.setblocking(False)
    buffer = bytearray()

    while True:
        try:
            ready = select.select([sock], [], [], 30.0)
            if not ready[0]:
                continue
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)

            while len(buffer) >= 2:
                b1 = buffer[0]
                b2 = buffer[1]
                opcode = b1 & 0x0F
                masked = (b2 & 0x80) != 0
                payload_len = b2 & 0x7F

                if opcode == 0x08:  # Close
                    return

                offset = 2
                if payload_len == 126:
                    if len(buffer) < 4: break
                    payload_len = struct.unpack("!H", buffer[2:4])[0]
                    offset = 4
                elif payload_len == 127:
                    if len(buffer) < 10: break
                    payload_len = struct.unpack("!Q", buffer[2:10])[0]
                    offset = 10

                mask_size = 4 if masked else 0
                if len(buffer) < offset + mask_size + payload_len:
                    break

                mask_key = buffer[offset:offset+4] if masked else None
                data = bytearray(buffer[offset+mask_size:offset+mask_size+payload_len])
                if masked:
                    for i in range(len(data)):
                        data[i] ^= mask_key[i % 4]

                # Consume parsed frame
                buffer = buffer[offset+mask_size+payload_len:]

                if opcode == 0x01:  # Text frame
                    msg = data.decode('utf-8', errors='ignore')
                    try:
                        cmd = json.loads(msg)
                        t = cmd.get("type")
                        if t == "m":  # Mouse move {type: 'm', dx: 5, dy: 5, b: 0, w: 0}
                            hid_manager.mouse_move(cmd.get("dx", 0), cmd.get("dy", 0), cmd.get("b", 0), cmd.get("w", 0))
                        elif t == "c":  # Click {type: 'c', b: 'left'|'right'|'middle', a: 'click'|'down'|'up'}
                            hid_manager.mouse_button(cmd.get("btn", "left"), cmd.get("act", "click"))
                        elif t == "k":  # Key {type: 'k', key: 'enter', a: 'press'}
                            hid_manager.send_key(cmd.get("key", ""), cmd.get("act", "press"))
                        elif t == "t":  # Type text {type: 't', text: '...'}
                            hid_manager.type_text(cmd.get("text", ""))
                    except Exception:
                        pass
        except Exception:
            break


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class CarlinkitHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Mute normal HTTP logging to maintain zero noise directive
        pass

    def do_GET(self):
        # Check for WebSocket Upgrade
        upgrade = self.headers.get("Upgrade", "").lower()
        if upgrade == "websocket":
            key = self.headers.get("Sec-WebSocket-Key", "")
            if key:
                handle_websocket(self.connection, key)
                return

        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            web_file = os.path.join(os.path.dirname(__file__), "../web/index.html")
            if os.path.exists(web_file):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(web_file, "rb") as f:
                    self.wfile.write(f.read())
                return
        elif parsed.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            status = {
                "status": "online",
                "mode": hid_manager.mode,
                "hardware_hid_ready": os.path.exists(KEYBOARD_DEV) and os.path.exists(MOUSE_DEV),
                "kernel_uinput_ready": os.path.exists(UINPUT_DEV),
                "port": PORT,
                "timestamp": time.time()
            }
            self.wfile.write(json.dumps(status).encode('utf-8'))
            return

        elif parsed.path == "/api/identify":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                cur_dir = os.path.dirname(os.path.abspath(__file__))
                for extra in [cur_dir, os.path.join(cur_dir, "../scripts"), os.path.join(cur_dir, "../payload_dist"), "/etc/carlinkit_hid"]:
                    if os.path.exists(extra) and extra not in sys.path:
                        sys.path.insert(0, extra)
                import carlinkit_sentinel
                host_info = carlinkit_sentinel.identify_connected_host()
                peripherals = carlinkit_sentinel.identify_connected_peripherals()
                carlinkit_sentinel.enforce_solid_red_led()
                payload = {"host": host_info, "peripherals": peripherals, "status": "online"}
            except Exception as e:
                payload = {"error": str(e), "status": "error"}
            self.wfile.write(json.dumps(payload, indent=2).encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8') if length > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        parsed = urllib.parse.urlparse(self.path)
        res = {"success": True, "mode": hid_manager.mode}

        if parsed.path == "/api/type":
            text = data.get("text", "")
            hid_manager.type_text(text)
        elif parsed.path == "/api/key":
            key = data.get("key", "")
            act = data.get("action", "press")
            hid_manager.send_key(key, action=act)
        elif parsed.path == "/api/mouse/move":
            dx = data.get("dx", 0)
            dy = data.get("dy", 0)
            b = data.get("buttons", 0)
            w = data.get("wheel", 0)
            hid_manager.mouse_move(dx, dy, buttons=b, wheel=w)
        elif parsed.path == "/api/mouse/click":
            btn = data.get("button", "left")
            act = data.get("action", "click")
            hid_manager.mouse_button(btn, action=act)
        elif parsed.path == "/api/macro":
            steps = data.get("steps", [])
            for s in steps:
                action = s.get("action")
                if action == "type": hid_manager.type_text(s.get("text", ""))
                elif action == "combo": hid_manager.send_combination(s.get("combo", ""))
                elif action == "key": hid_manager.send_key(s.get("key", ""))
                elif action == "sleep": time.sleep(float(s.get("duration", 0.1)))
        else:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(res).encode('utf-8'))


def run():
    server = ThreadedHTTPServer(('0.0.0.0', PORT), CarlinkitHTTPHandler)
    print(f"[+] Carlinkit Virtual HID Engine active on http://0.0.0.0:{PORT}")
    print(f"    Mode: {hid_manager.mode.upper()}")

    def shutdown(signum, frame):
        print("\n[*] Shutting down Carlinkit HID server...")
        hid_manager.close()
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == '__main__':
    run()
