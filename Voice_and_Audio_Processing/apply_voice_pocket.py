import os
import re

file_path = "/home/timemachine/Escritorio/GODWORKS SYSTEM/mobile_terminal/tardis_pocket.html"
if not os.path.exists(file_path):
    print("File not found")
    import sys; sys.exit(0)
    
with open(file_path, "r") as f:
    content = f.read()

# Buscamos un contenedor de botones o el header para inyectar el botón
btn = """
      <button onclick="startPocketVoice()" style="background: rgba(189, 147, 249, 0.2); border: 1px solid #bd93f9; color: #bd93f9; padding: 12px; border-radius: 8px; font-weight: bold; width: 100%; margin-top: 10px;">🎤 Habilitar Reconocimiento de Voz</button>
"""

js = """
    function startPocketVoice() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            alert("El navegador no soporta control por voz.");
            return;
        }
        const recognition = new SpeechRecognition();
        recognition.lang = 'es-ES';
        recognition.interimResults = false;
        
        recognition.onstart = function() {
            if(typeof showToast === "function") showToast("Escuchando...");
            else alert("Escuchando (Voz Activa)...");
        };
        
        recognition.onresult = function(event) {
            const transcript = event.results[0][0].transcript;
            
            // Intenta pasarlo al backend local del pocket daemon
            fetch('/api/command', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({command: transcript})
            }).then(res => res.json()).then(data => {
                if(typeof showToast === "function") showToast("Comando de voz enviado.");
            }).catch(e => {
                // Copia al portapapeles
                navigator.clipboard.writeText(transcript);
                if(typeof showToast === "function") showToast("Copiado al portapapeles: " + transcript);
                else alert("Copiado: " + transcript);
            });
        };
        recognition.start();
    }
</script>
"""

if "startPocketVoice" not in content:
    content = content.replace("</script>", js)
    # Busca la sección de botones rápidos para agregar el botón
    content = content.replace('<div class="quick-actions">', '<div class="quick-actions">' + btn)
    
    with open(file_path, "w") as f:
        f.write(content)
        print("Modificado pocket")
