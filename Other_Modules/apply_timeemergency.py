import re
import os

path = '/home/timemachine/Escritorio/GODWORKS SYSTEM/core/telegram_bridge.py'

with open(path, 'r') as f:
    content = f.read()

snippet = """
        if cmd.lower() in ("/timeemergency",):
            te_args = text[len(parts[0]):].strip()
            try:
                import sys
                te_path = "/home/timemachine/TimeEmergency"
                if te_path not in sys.path:
                    sys.path.append(te_path)
                from engine import TimeEmergencyEngine
                
                if not hasattr(self, "_te_engine"):
                    self._te_engine = TimeEmergencyEngine()
                
                if te_args:
                    self.send_message(f"⏳ [TimeEmergency KAIJU] Procesando...", chat_id=chat_id)
                    reply = self._te_engine.generate(te_args)
                    self.send_message(f"🌀 *TimeEmergency (Qwen3.8-27B)*:\n{reply}", chat_id=chat_id, parse_mode="Markdown")
                else:
                    self.send_message("🛸 *Modo TimeEmergency* activo. Usa `/timeemergency <mensaje>` para hablar con el sistema Qwen.", chat_id=chat_id, parse_mode="Markdown")
            except Exception as e:
                self.send_message(f"⚠️ Error al conectar con TimeEmergency: {e}", chat_id=chat_id)
            return
"""

if "/timeemergency" not in content.lower():
    # Insert right before 'if cmd in ("/ftl",):'
    parts = content.split('if cmd in ("/ftl",):')
    if len(parts) == 2:
        new_content = parts[0] + snippet + '\n        if cmd in ("/ftl",):\n' + parts[1]
        with open(path, 'w') as f:
            f.write(new_content)
        print("Patched telegram_bridge.py with /TimeEmergency command.")
    else:
        print("Could not find /ftl command in telegram_bridge.py.")
else:
    print("/TimeEmergency already in telegram_bridge.py")
