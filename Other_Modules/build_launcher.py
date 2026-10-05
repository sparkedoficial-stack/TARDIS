#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR / "tardis_os_shell"
ANDROID_JAR = Path("/tmp/android-25.jar")
GEN_DIR = PROJECT_DIR / "gen"
BIN_DIR = PROJECT_DIR / "bin"
KEYSTORE = BASE_DIR / "tardis_release.keystore"
OUTPUT_APK = PROJECT_DIR / "TardisLauncher.apk"
TARGET_PRIV_APP = BASE_DIR / "system" / "priv-app" / "TardisLauncher" / "TardisLauncher.apk"

def run_cmd(cmd, cwd=PROJECT_DIR):
    print(f">> Running: {cmd} in {cwd}")
    res = subprocess.run(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        print(f"❌ ERROR (code {res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        sys.exit(res.returncode)
    if res.stdout.strip():
        print(res.stdout.strip())
    return res

def build():
    print("==================================================")
    print(" COMPILANDO TARDIS SOVEREIGN LAUNCHER (APK NATIVO)")
    print("==================================================")

    if not ANDROID_JAR.exists():
        print(f"Descargando android-25.jar...")
        run_cmd(f'curl -sL "https://raw.githubusercontent.com/Sable/android-platforms/master/android-25/android.jar" -o "{ANDROID_JAR}"')

    # Clean & recreate dirs
    shutil.rmtree(GEN_DIR, ignore_errors=True)
    shutil.rmtree(BIN_DIR, ignore_errors=True)
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    # 1. AAPT Generate R.java
    print("[1/6] Generando R.java con AAPT...")
    run_cmd(f'aapt package -f -m -J "{GEN_DIR}" -M AndroidManifest.xml -S res -I "{ANDROID_JAR}"')

    # 2. Javac compile Java sources
    print("[2/6] Compilando clases Java con javac (--release 8)...")
    src_files = list((PROJECT_DIR / "src").glob("**/*.java"))
    gen_files = list(GEN_DIR.glob("**/*.java"))
    all_java = [f'"{str(p)}"' for p in (src_files + gen_files)]
    run_cmd(f'javac --release 8 -cp "{ANDROID_JAR}":"{GEN_DIR}" -d "{BIN_DIR}" ' + " ".join(all_java))

    # 3. Dalvik Exchange (dx) to DEX
    print("[3/6] Convirtiendo bytecode a Dalvik DEX...")
    dex_out = BIN_DIR / "classes.dex"
    run_cmd(f'/usr/bin/dalvik-exchange --dex --output="{dex_out}" "{BIN_DIR}"')

    # 4. AAPT package resources into initial APK
    print("[4/6] Empaquetando recursos en APK preliminar...")
    unsigned_apk = PROJECT_DIR / "unsigned.apk"
    if unsigned_apk.exists():
        unsigned_apk.unlink()
    run_cmd(f'aapt package -f -M AndroidManifest.xml -S res -I "{ANDROID_JAR}" -F "{unsigned_apk}"')

    # Add classes.dex into APK
    print("  + Inyectando classes.dex...")
    run_cmd(f'aapt add "{unsigned_apk}" classes.dex', cwd=BIN_DIR)

    # 5. Zipalign APK
    print("[5/6] Optimizando y alineando con zipalign...")
    aligned_apk = PROJECT_DIR / "aligned.apk"
    if aligned_apk.exists():
        aligned_apk.unlink()
    run_cmd(f'zipalign -f -p 4 "{unsigned_apk}" "{aligned_apk}"')

    # 6. Apksigner
    print("[6/6] Firmando APK con apksigner...")
    if not KEYSTORE.exists():
        print("  + Generando keystore de firma...")
        run_cmd(f'keytool -genkeypair -v -keystore "{KEYSTORE}" -alias tardis -keyalg RSA -keysize 2048 -validity 10000 -storepass tardis2026 -keypass tardis2026 -dname "CN=TARDIS Sovereign, OU=Omni, O=Godworks, C=MX"', cwd=BASE_DIR)

    if OUTPUT_APK.exists():
        OUTPUT_APK.unlink()
    run_cmd(f'apksigner sign --ks "{KEYSTORE}" --ks-pass pass:tardis2026 --key-pass pass:tardis2026 --out "{OUTPUT_APK}" "{aligned_apk}"')
    run_cmd(f'apksigner verify "{OUTPUT_APK}"')

    # Copy to system/priv-app
    TARGET_PRIV_APP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUTPUT_APK, TARGET_PRIV_APP)
    print(f"✓ Copiado a: {TARGET_PRIV_APP}")
    print(f"✓ APK creado exitosamente ({OUTPUT_APK.stat().st_size / 1024:.1f} KB): {OUTPUT_APK}")
    print("==================================================")

if __name__ == "__main__":
    build()
