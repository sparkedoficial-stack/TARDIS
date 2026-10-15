---
name: xcode-for-linux
description: "Xcode development, Mach-O binary analysis, REA inspection, codesigning, and device deployment for Apple iOS and iPadOS directly on Linux. Use when inspecting IPAs, compiling iOS apps, analyzing Mach-O headers, deploying to connected iPhones/iPads via USB/Wi-Fi, and checking iOS device status."
metadata:
  version: "1.0.0"
  target_os: "linux"
  bin_path: "/usr/local/bin/xcode-linux"
  toolchain_root: "/opt/xcode-linux"
---

# Xcode for Linux (xcode-linux)

Sovereign Linux toolchain for Apple iOS and iPadOS software development, binary inspection, codesigning, and device management.

## Toolchain Architecture

The toolchain is located at `/opt/xcode-linux` and accessible globally via `/usr/local/bin/xcode-linux`:
- **CLI Executable:** `/usr/local/bin/xcode-linux`
- **Compiler:** Clang (`/usr/bin/clang`) targeting `arm64-apple-ios`
- **Linker:** LLD (`/usr/bin/lld`)
- **Binary Analysis:** LLVM Objdump (`/usr/bin/llvm-objdump`), LLVM Lipo (`/usr/bin/llvm-lipo`)
- **Property Lists:** Plistutil / Plutil (`/usr/bin/plistutil` / `/opt/xcode-linux/bin/plutil`)
- **Codesigning:** `zsign` (`/home/timemachine/melonx_install/zsign`)
- **Apple Protocols:** `pymobiledevice3` (`/home/timemachine/.local/bin/pymobiledevice3`)
- **USB Transport:** `usbmuxd` (`/usr/sbin/usbmuxd`)
- **App Installer:** `ideviceinstaller` (`/usr/bin/ideviceinstaller`)

---

## Core Commands and Usage

### 1. Toolchain & Connected Device Status
```bash
xcode-linux info
```
Outputs the status of all compilers, linkers, signers, usbmuxd daemon, and enumerates all connected iOS/iPadOS devices with their UDID, model, iOS version, and Developer Mode state.

### 2. Device Organizer & Enumeration
```bash
xcode-linux devices
```
Lists connected devices with UDID, connection type (USB/Wi-Fi), build version, and Developer Mode verification.

### 3. Installed User Applications
```bash
xcode-linux apps [--udid <UDID>]
```
Queries the device's `InstallationProxyService` and displays all installed user applications, bundle IDs, and versions.

### 4. Binary Inspection & Reverse Engineering (REA Bridge)
```bash
xcode-linux inspect <path_to_ipa_or_macho>
```
- **For IPAs (`.ipa`):** Unpacks payload, extracts `Info.plist`, identifies bundle ID, architecture, supported devices, minimum OS version, and invokes REA (`reverse-engineer-anything`) for deep structural analysis.
- **For Mach-O Binaries:** Parses Mach-O 64-bit headers, load commands (`LC_SEGMENT_64`, `LC_LOAD_DYLIB`, `LC_CODE_SIGNATURE`), entry points, and crypt flags.

### 5. Application Deployment (Sideloading)
```bash
xcode-linux install <path_to_ipa> [--udid <UDID>]
```
Transfers and installs the signed `.ipa` package onto the targeted device via usbmuxd and `com.apple.mobile.installd`.
*Note:* Requires a valid provisioning profile matching the device UDID.

### 6. High-Speed File Injection (Apple File Conduit)
```bash
xcode-linux push <local_file> <remote_path> [--udid <UDID>]
```
Injects files directly into the iPad/iPhone local storage (e.g., `/Downloads/file.ext`) over USB at full hardware speeds.

### 7. Live Syslog Streaming
```bash
xcode-linux console [--udid <UDID>]
```
Streams realtime operating system and application log output from the device kernel and user space.

### 8. Project Compilation
```bash
xcode-linux build <project_dir> [--out <output_dir>]
```
Compiles Objective-C, Swift, or C sources into Mach-O binaries, sets up application bundle structure, generates `Info.plist`, and packages into an installable `.ipa`.

---

## Programmatic Integration in Python

```python
import subprocess
import json

def get_xcode_device_status():
    res = subprocess.run(["xcode-linux", "devices"], capture_output=True, text=True)
    return res.stdout

def inspect_ios_package(ipa_path):
    res = subprocess.run(["xcode-linux", "inspect", ipa_path], capture_output=True, text=True)
    return res.stdout
```
