---
name: tardis4ever
description: "Agente Soberano Tardis4Ever para sincronización periódica (cada 24 horas) y publicación inmediata en GitHub ante hitos importantes o llamativos con blindaje total de información personal."
metadata:
  version: "1.0.0"
  target_repo: "https://github.com/sparkedoficial-stack/TARDIS.git"
  service_name: "tardis4ever.service"
  cli_bin: "/usr/local/bin/tardis4ever"
---

# Tardis4Ever (Sentinel & Sovereign Publication Agent)

Agente soberano autónomo diseñado para garantizar que los proyectos, herramientas, toolchains y avances del ecosistema TARDIS / GODWORKS SYSTEM se publiquen y sincronicen en GitHub de manera continua, inteligente y rigurosamente protegida.

## 🌟 Principios de Operación

1. **Rutina Periódica 24 Horas:** Respaldo y publicación automática cada 24 horas exactas de todos los cambios acumulados.
2. **Vigilante de Hitos (Milestone Watcher):** Detección en tiempo real de avances importantes o llamativos (módulos Ring 0, toolchains iOS/Linux, nuevos skills, integraciones de IA) y publicación INMEDIATA en GitHub sin esperar al ciclo de 24 horas.
3. **Seguridad y Privacidad Absoluta:** Sanitización estricta de credenciales, API keys (AWS, GitHub, Google, Groq, OpenAI), tokens, números de teléfono, correos electrónicos, IPs privadas y PII.

---

## 🛠️ Comandos CLI

El agente está instalado globalmente en `/usr/local/bin/tardis4ever`:

```bash
# Consultar estado, telemetría y próximo ciclo de 24 horas
tardis4ever status

# Evaluar cambios en tiempo real y disparar publicación si detecta hito
tardis4ever check

# Forzar sincronización y publicación manual inmediata
tardis4ever sync

# Ejecutar en modo demonio (bucle continuo)
tardis4ever daemon
```

---

## ⚙️ Servicio Systemd en Segundo Plano

El demonio opera desacoplado de la CLI como servicio de usuario:

```bash
# Ver estado del servicio
systemctl --user status tardis4ever.service

# Iniciar o reiniciar
systemctl --user restart tardis4ever.service

# Consultar logs en tiempo real
journalctl --user -u tardis4ever.service -f
# O consultar el log dedicado
tail -f /home/timemachine/.ftl/logs/tardis4ever.log
```

---

## 🧠 Integración en Python (Master Hub FTL)

```python
from modulos_ftl.ftl_master_hub import initialize_sovereign_master_hub

hub = initialize_sovereign_master_hub()
status = hub.execute_module("ftl_tardis4ever", action="status")
check_res = hub.execute_module("ftl_tardis4ever", action="check")
```
