import re

path = '/home/timemachine/Escritorio/GODWORKS SYSTEM/core/telegram_bridge.py'
with open(path, 'r') as f:
    content = f.read()

if "/timeemergency" not in content.lower() or "TimeEmergency" not in content:
    print("Wait, it should be there.")

content = content.replace("f\"• `/ftl <petición>` : Pedir a FTL creación o mejora de código (`/ftl` para ver opciones)\\n\\n\"", 
                          "f\"• `/ftl <petición>` : Pedir a FTL creación o mejora de código (`/ftl` para ver opciones)\\n\"\n                f\"• `/timeemergency <msg>` : Chatear con TimeEmergency (Qwen3.8-27B)\\n\\n\"")

with open(path, 'w') as f:
    f.write(content)
print("Updated help text.")
