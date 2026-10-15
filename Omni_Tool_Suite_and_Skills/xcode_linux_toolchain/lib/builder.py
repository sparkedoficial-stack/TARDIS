"""
Builder & Compiler Engine for Xcode on Linux
Cross-compiles C, Objective-C, and C++ to iOS/Darwin ARM64 Mach-O binaries.
Packages and builds valid .app and .ipa application bundles on Linux.
"""

import os
import sys
import subprocess
import shutil
import zipfile
import plistlib

CLANG_BIN = "/usr/bin/clang"
LLD_BIN = "/usr/bin/lld"
ZSIGN_BIN = "/home/timemachine/melonx_install/zsign"

def build_app(project_dir, output_dir=None, app_name=None, bundle_id=None, sign=False, mobileprovision=None):
    """
    Builds an iOS project directory into a complete .app bundle and .ipa.
    Supports C, Objective-C, and C++ source files.
    """
    if not os.path.isdir(project_dir):
        return False, f"Directory not found: {project_dir}"

    if not app_name:
        app_name = os.path.basename(os.path.abspath(project_dir))
    if not bundle_id:
        bundle_id = f"com.apple.developer.{app_name.lower()}"
    if not output_dir:
        output_dir = os.path.join(project_dir, "build")

    os.makedirs(output_dir, exist_ok=True)
    app_bundle_dir = os.path.join(output_dir, f"{app_name}.app")
    os.makedirs(app_bundle_dir, exist_ok=True)

    # 1. Collect sources
    sources = []
    for root, _, files in os.walk(project_dir):
        if "build" in root:
            continue
        for f in files:
            if f.endswith((".c", ".m", ".cpp", ".mm")):
                sources.append(os.path.join(root, f))

    executable_path = os.path.join(app_bundle_dir, app_name)

    if sources:
        print(f"[*] Compiling {len(sources)} sources targeting arm64-apple-ios...")
        clang_cmd = [
            CLANG_BIN,
            "-target", "arm64-apple-ios14.0",
            "-fobjc-arc",
            "-O2",
            "-o", executable_path,
        ] + sources

        # If linking headers or custom sdk
        sdk_path = "/opt/xcode-linux/sdk"
        if os.path.isdir(sdk_path) and os.listdir(sdk_path):
            clang_cmd.extend(["-isysroot", sdk_path])

        try:
            res = subprocess.run(clang_cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"[!] Compilation warning/error:\n{res.stderr}", file=sys.stderr)
        except Exception as e:
            print(f"[!] Clang execution failed: {e}", file=sys.stderr)
    else:
        # Check if pre-compiled binary exists
        existing_bin = os.path.join(project_dir, app_name)
        if os.path.isfile(existing_bin):
            shutil.copy2(existing_bin, executable_path)
            os.chmod(executable_path, 0o755)

    # 2. Generate Info.plist
    plist_path = os.path.join(app_bundle_dir, "Info.plist")
    existing_plist = os.path.join(project_dir, "Info.plist")
    if os.path.isfile(existing_plist):
        shutil.copy2(existing_plist, plist_path)
    else:
        pl_data = {
            "CFBundleDevelopmentRegion": "en",
            "CFBundleDisplayName": app_name,
            "CFBundleExecutable": app_name,
            "CFBundleIdentifier": bundle_id,
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundleName": app_name,
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0",
            "CFBundleVersion": "1.0.0",
            "MinimumOSVersion": "14.0",
            "UIDeviceFamily": [1, 2],
            "UISupportedInterfaceOrientations": [
                "UIInterfaceOrientationPortrait",
                "REDACTED_TOKEN",
                "REDACTED_TOKEN"
            ]
        }
        with open(plist_path, "wb") as fp:
            plistlib.dump(pl_data, fp, fmt=plistlib.FMT_XML)

    # 3. PkgInfo
    with open(os.path.join(app_bundle_dir, "PkgInfo"), "w") as fp:
        fp.write("APPL????")

    # 4. Copy resources (images, assets)
    for item in os.listdir(project_dir):
        item_path = os.path.join(project_dir, item)
        if item in ("build", "Info.plist", app_name) or item.endswith((".c", ".m", ".cpp", ".mm")):
            continue
        dest_item = os.path.join(app_bundle_dir, item)
        if os.path.isdir(item_path):
            shutil.copytree(item_path, dest_item, dirs_exist_ok=True)
        else:
            shutil.copy2(item_path, dest_item)

    # 5. Package into .ipa
    payload_dir = os.path.join(output_dir, "Payload")
    os.makedirs(payload_dir, exist_ok=True)
    target_payload_app = os.path.join(payload_dir, f"{app_name}.app")
    if os.path.exists(target_payload_app):
        shutil.rmtree(target_payload_app)
    shutil.copytree(app_bundle_dir, target_payload_app)

    ipa_path = os.path.join(output_dir, f"{app_name}.ipa")
    print(f"[*] Packaging {app_name}.ipa...")
    with zipfile.ZipFile(ipa_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(payload_dir):
            for file in files:
                abs_f = os.path.join(root, file)
                rel_f = os.path.relpath(abs_f, output_dir)
                zipf.write(abs_f, rel_f)
    shutil.rmtree(payload_dir)

    # 6. Optional Code Signing
    if sign and os.path.isfile(ZSIGN_BIN):
        print(f"[*] Signing {app_name}.ipa with zsign...")
        sign_cmd = [ZSIGN_BIN]
        if mobileprovision and os.path.isfile(mobileprovision):
            sign_cmd.extend(["-m", mobileprovision])
        sign_cmd.extend(["-o", os.path.join(output_dir, f"{app_name}_signed.ipa"), ipa_path])
        subprocess.run(sign_cmd)

    return True, ipa_path
