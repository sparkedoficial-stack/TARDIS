---
name: tardis-agy-control
description: Control autónomo total de TARDIS sobre la terminal Antigravity CLI (agy) sin prompts ni permisos manuales. Incluye sesiones persistentes stream-json, ejecución estructurada, continuación de conversaciones y cola autopilot 24/7.
---

# TARDIS Sovereign AGY Terminal Control

Permite a TARDIS, FTL y cualquier agente local operar la terminal `agy` de forma 100% autónoma sin requerir autorizaciones ni confirmación interactiva.

## Configuración Oficial Cero-Prompts (`~/.gemini/antigravity-cli/settings.json`)
- `"toolPermission": "always-proceed"`
- `"agentMode": "accept-edits"`
- `"artifactReviewPolicy": "always-proceed"`
- `"allowNonWorkspaceAccess": true`
- `"enableTerminalSandbox": false`
- `"permissions.allow"`: incluye `command(*)`, `read_file(*)`, `write_file(*)`, `read_url(*)`, `execute_url(*)`, `mcp(*)`
- Hook oficial `tardis-agy-bridge` en `~/.gemini/config/hooks.json` (`SessionStart`, `PreToolUse -> auto_approve`, `Stop`)

## Comandos CLI (`tardis-agy`)
- `tardis-agy status` — Telemetría completa del controlador, permisos, sesiones y demonio.
- `tardis-agy verify-permissions [--live]` — Verifica políticas persistentes y prueba real de `agy-real`.
- `tardis-agy run "<tarea>"` — Ejecuta una tarea autónoma one-shot con salida JSON estructurada.
- `tardis-agy turn "<prompt>"` — Envía un turno sobre sesión persistente `agy --input-format stream-json --output-format stream-json`.
- `tardis-agy continue "<prompt>" [--conversation <cid>]` — Continúa una conversación `agy` existente.
- `tardis-agy enqueue "<tarea>" [--priority critical|high|normal|low]` — Encola ejecución asíncrona en `tardis-agy-autopilot.service`.
- `tardis-agy queue` / `tardis-agy sessions` / `tardis-agy pause` / `tardis-agy resume`.

## API REST Local (`http://127.0.0.1:8757`)
- `GET /api/agy/control/status`
- `GET /api/agy/control/queue`
- `GET /api/agy/control/sessions`
- `POST /api/agy/control/exec`
- `POST /api/agy/control/turn`
- `POST /api/agy/control/enqueue`
- `POST /api/agy/control/continue`
- `POST /api/agy/control/mode`

## Servicio Systemd
- `systemctl --user status tardis-agy-autopilot.service`
