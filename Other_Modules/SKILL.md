---
name: godworks-system-suite
description: Sovereign control over GODWORKS SYSTEM v26.4 & TARDIS. Perform web research, autonomous code evolution, query conjectures, inspect sensor/radar telemetry, and interact with the sovereign LLM directly from Orca.
---

# GODWORKS SYSTEM & TARDIS Sovereign Skill for Orca

Este skill dota a cualquier agente dentro de Orca (Antigravity, Claude, Codex, Gemini, etc.) de acceso total a la infraestructura soberana de GODWORKS SYSTEM v26.4.

## Capacidades Principales

1. **Investigación Web Profunda (`godworks research "<query>"`)**:
   - Explora fuentes web multi-motor (Yahoo, ArXiv, Wikipedia, DDG) sin bloqueos de bots.
   - Sintetiza hallazgos técnicos y citas con aceleración Cloud API (Groq LPU a 350+ tok/s).

2. **Auto-Programación Segura (`godworks evolve <archivo> "<meta>"`)**:
   - Reescribe y optimiza funciones del repositorio.
   - Aplica validación sintáctica AST, respaldos automáticos con timestamp y verificación de tests (`pytest`) con rollback automático en caso de regresión.

3. **Conjeturas y Auto-Mejora Continua (`godworks conjecture [trigger]`)**:
   - Monitorea el ciclo de auto-mejora por inactividad (umbral 30 min).
   - Consulta las conjeturas archivadas en la Bóveda Akáshica o fuerza una nueva hipótesis técnica.

4. **Inferencia con el Modelo Soberano (`godworks chat "<mensaje>"`)**:
   - Despacha consultas al acelerador en la nube (Groq) con respaldo automático al modelo local en Ollama (`huihui_ai/llama3.1-8b-instruct-abliterated` anclado en 18 GB RAM).

5. **Telemetría y Estado Holístico (`godworks status`)**:
   - Salud del nodo local en puerto 8757, hardware, radar RF, sensores y túnel público HTTPS.

## Variables de Entorno Activas
- `GIA_API_URL`: `http://127.0.0.1:8757`
- `GIA_TOKEN`: Definido dinámicamente en `.env` (Bóveda Segura)
- `OLLAMA_HOST`: `http://127.0.0.1:11434`
- `GIA_MODEL`: `huihui_ai/llama3.1-8b-instruct-abliterated`
