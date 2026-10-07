import os
import re

file_path = "/home/timemachine/.ftl/ftl_web_server.py"
with open(file_path, "r") as f:
    content = f.read()

# 1. Add /api/voice_command endpoint
voice_api = """
@app.post("/api/voice_command")
async def api_voice_command(request: Request):
    try:
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return JSONResponse({"status": "error", "error": "No text provided"})
        
        text_lower = text.lower()
        import subprocess
        output = ""
        
        # Lógica de tardis_voice_terminal
        if "lista los archivos" in text_lower or "listar archivos" in text_lower:
            res = subprocess.run("ls -la", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "qué hora es" in text_lower or "que hora es" in text_lower:
            res = subprocess.run("date", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "estado del sistema" in text_lower or "memoria" in text_lower:
            res = subprocess.run("free -h && df -h", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "limpiar" in text_lower or "borrar pantalla" in text_lower:
            res = subprocess.run("clear", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "quién soy" in text_lower or "quien soy" in text_lower:
            res = subprocess.run("whoami", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "procesos" in text_lower:
            res = subprocess.run("top -b -n 1 | head -n 15", shell=True, capture_output=True, text=True)
            output = res.stdout
        elif "crea un archivo" in text_lower or "crear un archivo" in text_lower:
            parts = text_lower.split("llamado")
            if len(parts) > 1:
                filename = parts[1].strip().replace(" ", "_") + ".txt"
                subprocess.run(f"touch {filename}", shell=True)
                output = f"Archivo {filename} creado."
        else:
            # Enviar a FTL HUB
            try:
                import requests
                FTL_HUB_API = "http://REDACTED_IP:8757/api/chat?key=DiosDelTiempo01"
                payload = {"message": f"Desde terminal de voz FTL Web: {text}", "source": "voice"}
                response = requests.post(FTL_HUB_API, json=payload, timeout=5)
                if response.status_code == 200:
                    output = "TARDIS HUB: " + str(response.json().get('response', 'OK'))
            except Exception as e:
                output = "Comando recibido pero FTL HUB no está disponible: " + text

        return JSONResponse({"status": "ok", "text": text, "output": output})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

@app.get("/api/status")"""

content = content.replace('@app.get("/api/status")', voice_api)

# 2. Add button in HTML
btn_replacement = """            <button class="btn" onclick="openBrightnessModal()" style="border-color: var(--neon-cyan); color: var(--neon-cyan);" title="Control de Brillo Dual (iMac & TUF)">🔆 Brillo</button>
            <button class="btn" onclick="startVoiceRecognition()" style="border-color: var(--neon-magenta); color: var(--neon-magenta);" title="Control por Voz FTL">🎤 Hablar</button>"""
content = content.replace('<button class="btn" onclick="openBrightnessModal()" style="border-color: var(--neon-cyan); color: var(--neon-cyan);" title="Control de Brillo Dual (iMac & TUF)">🔆 Brillo</button>', btn_replacement)

# 3. Add JS function
js_injection = """        function startVoiceRecognition() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                showToast("Tu navegador no soporta control por voz.");
                return;
            }
            const recognition = new SpeechRecognition();
            recognition.lang = 'es-ES';
            recognition.interimResults = false;
            recognition.maxAlternatives = 1;
            
            showToast("🎤 Escuchando... Di un comando.");
            
            recognition.onresult = async function(event) {
                const transcript = event.results[0][0].transcript;
                showToast("Procesando: " + transcript);
                
                // Opción 1: Enviar al backend para que lo ejecute el sistema
                try {
                    const res = await fetch('/api/voice_command', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({text: transcript})
                    });
                    if (res.ok) {
                        const data = await res.json();
                        if (data.output) {
                            showToast("Salida: " + data.output.substring(0, 100) + "...");
                        } else {
                            showToast("✅ Comando ejecutado: " + transcript);
                        }
                    }
                } catch(e) {
                    // Fallback
                    showToast("Error enviando comando");
                }
                
                // Opción 2: También copiar al portapapeles por si quiere pegarlo en ttyd
                navigator.clipboard.writeText(transcript).catch(e=>console.log(e));
            };
            
            recognition.onerror = function(event) {
                showToast("Error de voz: " + event.error);
            };
            
            recognition.start();
        }

        function showToast(msg) {"""

content = content.replace('function showToast(msg) {', js_injection)

with open(file_path, "w") as f:
    f.write(content)

print("Modificaciones aplicadas con éxito.")
