#!/usr/bin/env python3
"""
scripts/ingest_omni_tools_knowledge.py - Ingesta Masiva de Conocimiento de Herramientas en RAG Vault y Knowledge Graph
====================================================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Directiva Soberana:
"Todas las herramientas con las que tiene acceso agy, tardis, asi como ftl deben tener
control y saber de su conocimiento para poder emplearlas en sus sistemas de forma individual."

Este script inyecta la documentación operacional, sintaxis, ejemplos y parámetros de:
  1. Phone Harness (Control móvil y sensorial)
  2. Xcode para Linux (Toolchain iOS, Mach-O, zsign, pymobiledevice3, AFC)
  3. REA (Reverse Engineer Anything - Descompilación e ingeniería inversa)
  4. FTL Kernel Bridge (Ring 0, sysctl, dmesg, PSI, uinput, uhid)
  5. FTL Git Sync (Compilación, sanitización y sincronización con GitHub)
  6. Ecosistema AGY y repositorios locales
"""

import sys
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.rag_vault import get_rag_vault

DOCS_CATALOG = [
    {
        "title": "Manual Operativo de Phone Harness para Control Móvil",
        "source": "manual_phone_harness",
        "term": "phone-harness",
        "text": """
Phone Harness (phone-harness) se define como el framework soberano para control de teléfonos inteligentes desde scripts Python y línea de comandos.
Phone Harness implementa control bidireccional sobre dispositivos Android mediante ADB, dispositivos Apple iPhone vía Mirroring y USB, y Cloud Phones sobre HTTPS.
Phone Harness conecta con la pantalla del teléfono mediante reconocimiento óptico de caracteres OCR y el árbol de accesibilidad UI.
Phone Harness optimiza la automatización de aplicaciones, pulsaciones táctiles, pulsaciones prolongadas, escritura de texto y navegación gestual.
Funciones y helpers principales:
- ensure_device(): valida la conexión con el teléfono y devuelve los límites de pantalla.
- screen(min_confidence=0.3): lee todos los textos visibles en pantalla con sus coordenadas [x, y, w, h] listos para ser pulsados.
- screenshot(path): captura la pantalla actual en formato PNG de alta resolución.
- find_text(query): busca cajas de texto visibles que coincidan con la consulta.
- tap_text(query): pulsa en el centro exacto del texto visible indicado.
- tap(x, y): pulsa en las coordenadas físicas de la pantalla.
- type_text(text): escribe texto en el campo activo enfocado.
- open_app(name): abre cualquier aplicación por su nombre visible o bundle ID.
- swipe(direction): ejecuta deslizamiento de dedo (up, down, left, right).
- scroll(direction): realiza scroll para revelar contenido.
- home(): vuelve a la pantalla de inicio del sistema operativo.
- back(): ejecuta el botón de retroceso nativo.
- ui(): extrae el árbol completo de accesibilidad con todos los identificadores de elementos.
Invocación en terminal bash:
phone-harness <<'PY'
open_app("Settings")
print([o["text"] for o in screen()][:10])
PY
"""
    },
    {
        "title": "Manual de Arquitectura y Operación de Xcode para Linux",
        "source": "manual_xcode_linux",
        "term": "xcode-linux",
        "text": """
Xcode para Linux (xcode-linux) se define como el entorno de desarrollo y toolchain soberano para Apple iOS y iPadOS en Linux.
Xcode para Linux implementa compilación con Clang ARM64, enlazado con LLD, inspección Mach-O con llvm-objdump, firmado zsign y transporte por USBMUXD.
Xcode para Linux conecta con iPad Pro M2 (iPad14,6) y iPhones mediante usbmuxd y Apple File Conduit AFC.
Xcode para Linux optimiza la inspección de paquetes IPA, el firmado independiente y el despliegue directo sin depender de macOS.
Subcomandos de la herramienta /usr/local/bin/xcode-linux:
- xcode-linux info: muestra el estado de salud de todos los componentes del toolchain y dispositivos iOS conectados.
- xcode-linux devices: enumera los dispositivos Apple conectados con su UDID, versión de iOS y estado de Developer Mode.
- xcode-linux apps: lista todas las aplicaciones de usuario instaladas en el dispositivo móvil.
- xcode-linux inspect <path>: realiza un análisis estructural profundo de un paquete .ipa o binario Mach-O utilizando el motor REA.
- xcode-linux install <ipa>: instala directamente un paquete IPA en el iPhone o iPad conectado.
- xcode-linux push <archivo> <destino>: transfiere archivos al almacenamiento interno del iPad por el bus de hardware AFC.
- xcode-linux console: transmite en vivo los logs de syslog y del kernel del dispositivo iOS.
- xcode-linux build <directorio>: compila código fuente Objective-C, Swift y C en paquetes IPA listos para su distribución.
"""
    },
    {
        "title": "Manual de Ingeniería Inversa con REA (Reverse Engineer Anything)",
        "source": "manual_rea",
        "term": "rea",
        "text": """
REA (Reverse Engineer Anything) se define como el motor analítico de descompilación, reconstrucción y examen de artefactos de software.
REA implementa descompilación de código máquina, análisis estático de grafos de llamadas, extracción de cadenas y desensamblado.
REA conecta con binarios nativos Mach-O, ejecutables ELF de Linux, archivos PE de Windows, aplicaciones Android APK, paquetes Apple IPA, árboles JavaScript/Electron y firmwares embebidos.
REA optimiza la recuperación de código fuente, la auditoría de seguridad y el análisis forense de aplicaciones sin código fuente disponible.
Herramientas y comandos fundamentales:
- rea providers: enumera los motores de análisis y descompilación activos (Ghidra, LLVM, JADX, etc.).
- rea inspect_apk <archivo.apk>: realiza el inventario y proyección de una aplicación Android.
- rea inspect_ipa <archivo.ipa>: analiza la estructura interna, binario Mach-O y recursos de una aplicación iOS.
- rea inspect_js <ruta>: analiza bundles web y aplicaciones Electron/Node.js.
- rea decompile <binario> <simbolo_o_direccion>: descompila a pseudocódigo legible una función o dirección de memoria.
- rea disassemble <binario>: genera el listado de instrucciones en ensamblador con referencias cruzadas.
- rea search <binario> <patron>: busca cadenas de texto, llamadas a APIs o patrones criptográficos.
"""
    },
    {
        "title": "Manual de Control de Kernel Ring 0 y Puente FTL",
        "source": "manual_kernel_bridge",
        "term": "kernel-bridge",
        "text": """
FTL Kernel Bridge se define como el módulo de enlace soberano entre los agentes de inteligencia artificial y el núcleo del sistema operativo Linux.
FTL Kernel Bridge implementa acceso irrestricto a los subsistemas del kernel mediante sysctl, interfaces /proc y /sys, búferes dmesg y nodos de hardware.
FTL Kernel Bridge conecta con dispositivos /dev/uinput y /dev/uhid con permisos 0666 para inyección de eventos sintéticos táctiles y de teclado.
FTL Kernel Bridge optimiza la latencia del sistema, purga cachés de memoria RAM en caliente (drop_caches=3) y monitorea la presión de recursos PSI.
Configuración de bajo nivel aplicada en el sistema:
- kernel.dmesg_restrict = 0: lectura libre del ringbuffer de mensajes del kernel sin sudo.
- kernel.yama.ptrace_scope = 0: depuración, tracing e introspección de memoria entre procesos sin restricciones.
- kernel.perf_event_paranoid = -1: telemetría de rendimiento y contadores de hardware para observabilidad profunda.
- kernel.kptr_restrict = 0: resolución de punteros de símbolos del kernel para diagnósticos nativos.
- kernel.unprivileged_bpf_disabled = 0: habilitación de programas eBPF para monitorización de red.
- /proc/pressure/{cpu,memory,io}: métricas en tiempo real de saturación de procesador, RAM y discos.
"""
    },
    {
        "title": "Manual de Sincronización Continua FTL Git Sync con GitHub",
        "source": "manual_git_sync",
        "term": "ftl-git-sync",
        "text": """
FTL Git Sync se define como el módulo de publicación y preservación continua del código de TARDIS, FTL y Easy Touch en GitHub.
FTL Git Sync implementa compilación de portafolio mediante build_portfolio.py, sanitización estricta de credenciales y push a repositorios remotos.
FTL Git Sync conecta con el repositorio remoto oficial https://github.com/sparkedoficial-stack/TARDIS.git en la rama main.
FTL Git Sync optimiza la actualización de avances de software, la catalogación modular y la generación automática de READMEs técnicos.
Capacidades del módulo:
- build_portfolio(): recorre GODWORKS SYSTEM, modulos_ftl, .ftl y el directorio raíz, sanitizando tokens y credenciales.
- sync(): detecta cambios pendientes, crea commits soberanos estructurados con timestamp y empuja el código a GitHub.
- status(): comprueba el árbol de trabajo y la sincronización con origin/main.
- log(): consulta el historial de los commits más recientes confirmados en el repositorio.
"""
    }
]

def main():
    print("=== INGESTA SOBERANA DE CONOCIMIENTO DE HERRAMIENTAS EN RAG VAULT ===")
    vault = get_rag_vault()
    total_stored = 0
    total_terms = 0
    total_relations = 0

    for doc in DOCS_CATALOG:
        res = vault.ingest(
            text=doc["text"],
            source=doc["source"],
            title=doc["title"],
            term=doc["term"]
        )
        stored = res.get("stored", 0)
        terms = res.get("extracted_terms", 0)
        rels = res.get("extracted_relations", 0)
        total_stored += stored
        total_terms += terms
        total_relations += rels
        print(f"✓ '{doc['title']}': {stored} fragmentos almacenados, {terms} términos, {rels} relaciones.")

    print(f"\n[ÉXITO] Ingesta completada: {total_stored} fragmentos nuevos, {total_terms} términos ontológicos y {total_relations} relaciones agregadas al Grafo de Conocimiento.")

if __name__ == "__main__":
    main()
