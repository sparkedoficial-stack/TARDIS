import os
file_path = "/home/timemachine/Escritorio/GODWORKS SYSTEM/mobile_terminal/TARDIS_TERMINAL_APP.html"
if not os.path.exists(file_path):
    print("File not found")
    import sys; sys.exit(0)
    
with open(file_path, "r") as f:
    content = f.read()

btn = """
        <button id="voiceBtn" style="background: rgba(189, 147, 249, 0.2); border: 1px solid #bd93f9; color: #bd93f9; padding: 12px; border-radius: 8px; font-weight: bold; width: 100%; margin-top: 10px; margin-bottom: 10px;" onclick="startTerminalVoice()">🎤 Usar Control por Voz</button>
"""

js = """
    function startTerminalVoice() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            alert("El navegador no soporta voz.");
            return;
        }
        const recognition = new SpeechRecognition();
        recognition.lang = 'es-ES';
        recognition.onstart = () => {
            const btn = document.getElementById("voiceBtn");
            if(btn) btn.innerText = "Escuchando...";
        };
        recognition.onresult = (event) => {
            const btn = document.getElementById("voiceBtn");
            if(btn) btn.innerText = "🎤 Usar Control por Voz";
            const transcript = event.results[0][0].transcript;
            
            navigator.clipboard.writeText(transcript);
            alert("Texto copiado para pegar en la terminal: " + transcript);
        };
        recognition.onerror = () => {
            const btn = document.getElementById("voiceBtn");
            if(btn) btn.innerText = "🎤 Usar Control por Voz";
        };
        recognition.start();
    }
</script>
"""

if "startTerminalVoice" not in content:
    content = content.replace("</script>", js)
    content = content.replace('<div id="controls" style="display:none; width: 100%; max-width: 600px; padding: 10px; z-index: 100; background: #030712; flex-shrink: 0; text-align: center;">', '<div id="controls" style="display:none; width: 100%; max-width: 600px; padding: 10px; z-index: 100; background: #030712; flex-shrink: 0; text-align: center;">\n' + btn)
    
    with open(file_path, "w") as f:
        f.write(content)
        print("Modificado terminal app")
