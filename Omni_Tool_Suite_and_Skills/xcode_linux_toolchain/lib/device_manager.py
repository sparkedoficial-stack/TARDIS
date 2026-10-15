"""
Device Manager for Xcode on Linux
Wraps pymobiledevice3, usbmuxd, and libimobiledevice.
Provides full Xcode Organizer & Device management capabilities on Linux.
"""

import subprocess
import json
import os
import sys

PYMOBILEDEVICE3 = "/home/timemachine/.local/bin/pymobiledevice3"

def get_connected_devices():
    """Returns list of connected iOS/iPadOS devices with full metadata."""
    devices = []
    try:
        res = subprocess.run([PYMOBILEDEVICE3, "usbmux", "list"], capture_output=True, text=True, check=True)
        raw_list = json.loads(res.stdout)
        for dev in raw_list:
            udid = dev.get("UniqueDeviceID") or dev.get("Identifier")
            # Query extended properties
            dev_info = {
                "udid": udid,
                "name": dev.get("DeviceName", "Unknown iOS Device"),
                "model": dev.get("ProductType", "Unknown"),
                "version": dev.get("ProductVersion", "Unknown"),
                "build": dev.get("BuildVersion", "Unknown"),
                "connection": dev.get("ConnectionType", "USB"),
                "class": dev.get("DeviceClass", "iPhone/iPad"),
            }
            # Check developer mode
            try:
                dm_res = subprocess.run([PYMOBILEDEVICE3, "amfi", "developer-mode-status"], capture_output=True, text=True, timeout=3)
                dev_info["developer_mode"] = dm_res.stdout.strip() == "true"
            except Exception:
                dev_info["developer_mode"] = False
                
            devices.append(dev_info)
    except Exception as e:
        print(f"Error querying usbmux devices: {e}", file=sys.stderr)
    return devices

def list_installed_apps(udid=None):
    """Lists installed user applications on target device."""
    cmd = ["ideviceinstaller", "list"]
    if udid:
        cmd.extend(["-u", udid])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = res.stdout.strip().splitlines()
        apps = []
        for line in lines[1:]:  # skip header
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                bundle_id = parts[0]
                version = parts[1].strip('"')
                name = parts[2].strip('"')
                apps.append({"bundle_id": bundle_id, "version": version, "name": name})
        return apps
    except Exception as e:
        print(f"Error listing apps: {e}", file=sys.stderr)
        return []

def install_app(ipa_path, udid=None):
    """Installs an IPA file directly on the device."""
    if not os.path.isfile(ipa_path):
        return False, f"File not found: {ipa_path}"
    
    cmd = ["ideviceinstaller", "install", ipa_path]
    if udid:
        cmd.extend(["-u", udid])
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        return True, "Installation completed successfully."
    return False, res.stderr or res.stdout

def push_to_media(local_file, remote_path="/Downloads/"):
    """Pushes a file to the device's /var/mobile/Media via AFC."""
    cmd = [PYMOBILEDEVICE3, "afc", "push", local_file, remote_path]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        return True, f"Pushed {local_file} -> {remote_path}"
    return False, res.stderr

def stream_syslog(udid=None):
    """Streams the device console log in real time (like Xcode Console)."""
    cmd = [PYMOBILEDEVICE3, "syslog", "live"]
    if udid:
        cmd.extend(["--udid", udid])
    try:
        proc = subprocess.Popen(cmd)
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
