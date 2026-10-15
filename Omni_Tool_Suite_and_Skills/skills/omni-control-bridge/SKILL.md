---
name: omni-control-bridge
description: Active bidirectional feedback and telemetry bridge with OMNI-LOCAL-TEMPORAL CONTROL (GODWORKS SYSTEM v26.4). Use to inspect system health, retrieve live self-improvement instructions, talk directly with the sovereign GIA node, and submit optimization requests.
---

# OMNI-LOCAL-TEMPORAL CONTROL Active Feedback Bridge

Este skill permite a Antigravity comunicarse de forma bidireccional y continua con el sistema soberano **OMNI-LOCAL-TEMPORAL CONTROL** (puerto 8757 o buzón local no bloqueante).

## Cuándo usar este Skill
- Cuando desees comprobar la salud, cuellos de botella y rendimiento de inferencia del sistema GIA.
- Cuando necesites conocer las instrucciones de auto-mejora generadas autónomamente por el sistema.
- Cuando quieras enviar directivas, confirmaciones o sugerencias al diálogo activo del sistema.
- Cuando el usuario solicite un estado holístico o diagnóstico de OMNI-LOCAL.

## Arquitectura de Comunicación No Bloqueante

El puente opera a través de dos canales redundantes:
1. **Canal REST / HTTP (Cuando OMNI-LOCAL está en ejecución)**:
   - Base URL: `http://127.0.0.1:8757`
   - Cabecera opcional / Token: `X-GIA-Key: <token>` o `?key=<token>` (obtenido de `gia_bridge_token.txt`).
   - Endpoints:
     - `GET /api/antigravity/feedback`: Retorna puntaje de salud, telemetría y lista de instrucciones de mejora.
     - `GET /api/antigravity/dialogue`: Retorna el historial de conversación en vivo.
     - `POST /api/antigravity/dialogue`: Envía una respuesta o instrucción de Antigravity al sistema.
     - `POST /api/antigravity/diagnostics`: Ejecuta un ciclo de análisis profundo bajo demanda.
     - `POST /api/antigravity/propose_improvement`: Encola una mejora formal en `improvement_queue`.

2. **Canal de Buzón Local (Cuando OMNI-LOCAL está offline o en reposo)**:
   - Directorio: `%LOCALAPPDATA%\vw-control\antigravity_bridge\` (o `.agents/antigravity_bridge/`).
   - Archivos:
     - `system_feedback.json`: Último diagnóstico completo del sistema.
     - `live_dialogue.jsonl`: Historial secuencial de mensajes.
     - `live_telemetry.json`: Snapshot de CPU, RAM, salud.

## Comandos Rápidos de Diagnóstico e Interacción

### 1. Consultar Diagnóstico y Necesidades Actuales del Sistema
```powershell
python -c "import antigravity_bridge; b = antigravity_bridge.get_bridge(); d = b.assess_system_needs(); print(f'Salud: {d[\"health_score\"]}% | Estado: {d[\"status\"]}'); [print(f' - [{i[\"severity\"]}] {i[\"component\"]}: {i[\"instruction\"]}') for i in d.get('instructions', [])]"
```

### 2. Enviar Mensaje al Diálogo de Retroalimentación Activa
```powershell
python -c "import antigravity_bridge; b = antigravity_bridge.get_bridge(); b.post_dialogue_message('Antigravity-AI', 'Directiva recibida. Optimizando parámetros causales...', role='assistant')"
```

### 3. Consultar Últimos Mensajes del Diálogo
```powershell
python -c "import antigravity_bridge; b = antigravity_bridge.get_bridge(); [print(f'[{m[\"sender\"]} ({m[\"category\"]})]: {m[\"text\"]}') for m in b.get_full_dialogue(10)]"
```
