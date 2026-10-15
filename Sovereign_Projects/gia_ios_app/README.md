# GIA · iOS Sovereign Client (SwiftUI)

Aplicación nativa para **iPhone y iPad (iOS 16.0+)** diseñada para interactuar en tiempo real con el nodo central **GODWORKS SYSTEM / GIA** (`gia_web_server.py`).

---

## 📱 Capacidades Principales

1. **Chat Cuántico & Vector Temporal**:
   - Selector de modo de inferencia: **Presente** (Acción situacional), **Futuro Ψ** (Lente retrocausal y extrapolación espectral FFT) y **Pasado** (Retro-origen).
   - Interruptores rápidos para búsqueda web en tiempo real, salida de voz en altavoces del PC y síntesis de voz nativa en el iPhone.
   - Visor de fuentes web, eco futuro de fase desplazada, velocidad de respuesta en segundos y modelo utilizado.

2. **Rejilla Sensorial & Telemetría (`CoreMotion`)**:
   - Captura en tiempo real de aceleración de 3 ejes, gravedad, velocidad angular (giroscopio) y cálculo dinámico de **Entropía de Shannon**.
   - Sincronización continua de paquetes de telemetría (1 Hz) para alimentar la semilla del cono de luz retrocausal en el servidor.
   - Consulta del **Oráculo Físico**: generación de respuestas determinadas por el ruido ambiental real capturado por el iPhone.

3. **Monitor de Recursos Hardware**:
   - Dashboard con anillos visuales de consumo de **CPU** y **RAM**.
   - Monitor de **GPU y VRAM** (temperatura y memoria usada/total).
   - Lista de modelos Ollama cargados en memoria y procesos principales.
   - Estado de salud y latencia de los nodos del cluster distribuido.

4. **Siri & Atajos de iOS (`AppIntents`)**:
   - Comando directo *"Oye Siri, pregunta a GIA [tu consulta]"*.
   - Consulta rápida *"Oye Siri, estado de GIA"*.

5. **Audio & Dictado (`AVFoundation` & `Speech`)**:
   - Dictado por voz (Speech-to-Text) con soporte para español.
   - Síntesis de voz (Text-to-Speech) local en el altavoz del dispositivo móvil.

---

## 📂 Estructura del Proyecto

```
ios-app/
├── Package.swift                    # Configuración Swift Package Manager (iOS 16+)
├── README.md                        # Esta documentación
└── GIA/
    ├── GIAApp.swift                 # Punto de entrada (@main)
    ├── Info.plist                   # Permisos de Micrófono, Reconocimiento de Voz y Sensores
    ├── Models/
    │   └── GIAModels.swift          # Estructuras Codable de Chat, Sensores, Monitor y Retrocausalidad
    ├── Services/
    │   ├── GIANetworkService.swift  # Cliente de red async/await con soporte de Token Auth
    │   ├── MotionSensorManager.swift# Gestor de CoreMotion y cálculo de Entropía
    │   └── AudioVoiceService.swift  # Manejador de entrada/salida de audio nativo
    ├── ViewModels/
    │   ├── ChatViewModel.swift      # Estado y lógica del chat
    │   └── MonitorViewModel.swift   # Polling de métricas de hardware
    ├── Views/
    │   ├── Theme.swift              # Sistema de diseño, paleta Cyberpunk y Glassmorphism
    │   ├── MainTabView.swift        # Barra de pestañas principal
    │   ├── ChatView.swift           # Interfaz de chat conversacional
    │   ├── SensorsView.swift        # Vista de acelerómetros y entropía física
    │   ├── MonitorView.swift        # Dashboard de CPU/RAM/GPU
    │   └── SettingsView.swift       # Configuración de URL, Token y Parámetros
    └── Intents/
        └── GIAAppIntents.swift      # Integración con Siri y Atajos de iOS
```

---

## 🚀 Despliegue y Ejecución

### 1. Iniciar el Servidor GIA en tu PC Windows
Para que el iPhone pueda conectarse en la misma red Wi-Fi:
```powershell
python gia_web_server.py --lan
```
*El servidor mostrará en consola su IP local (por ejemplo `http://REDACTED_IP:8757`) y el token de acceso generado.*

### 2. Abrir el Proyecto en Xcode (macOS)
1. Abre **Xcode**.
2. Selecciona **File > Open** y elige la carpeta `ios-app/` (o arrastra los archivos a un proyecto nuevo de tipo *iOS App / SwiftUI*).
3. Selecciona tu iPhone o un Simulador como destino de ejecución.
4. Presiona **⌘ + R (Run)** para compilar e instalar en tu dispositivo.

### 3. Configurar la Conexión en la App
1. Abre la app **GIA** en el iPhone.
2. Ve a la pestaña **Ajustes**.
3. Introduce la **URL del Servidor** (ej. `http://REDACTED_IP:8757` o la URL de tu túnel Tailscale/Cloudflare) y el **Token**.
4. Pulsa **Probar Conexión**. Una vez confirmado el estado `✅ Conexión exitosa`, ¡el sistema está 100% operativo!
