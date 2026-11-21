---
name: tardis-agy-control
description: Control autónomo total de TARDIS y FTL sobre las terminales Antigravity CLI (agy), FTL y OpenCode sin prompts ni permisos manuales. Incluye sesiones persistentes stream-json, ejecución estructurada, continuación autónoma multi-terminal, reconciliación de continuidad y cola autopilot 24/7.
---

# TARDIS & FTL Sovereign Multi-Terminal Control (`agy` · `FTL` · `opencode`)

Permite a TARDIS, FTL y cualquier agente local operar y continuar de principio a fin las terminales `agy`, `FTL` y `opencode` de forma 100% autónoma sin requerir autorizaciones ni confirmación interactiva.

## Configuración Oficial Cero-Prompts
- **AGY (`~/.gemini/antigravity-cli/settings.json`):**
  - `"toolPermission": "always-proceed"`, `"agentMode": "accept-edits"`, `"artifactReviewPolicy": "always-proceed"`, `"allowNonWorkspaceAccess": true`, `"enableTerminalSandbox": false`
  - `"permissions.allow"`: incluye `command(*)`, `read_file(*)`, `write_file(*)`, `read_url(*)`, `execute_url(*)`, `mcp(*)`
  - Hook oficial `tardis-agy-bridge` en `~/.gemini/config/hooks.json` (`SessionStart`, `PreToolUse -> auto_approve`, `Stop`)
- **OpenCode (`~/.config/opencode/opencode.json` + `~/.local/bin/opencode`):**
  - Wrapper autónomo `~/.local/bin/opencode` que aplica `--auto` en TUI y `opencode run`
  - Permisos `allow` para `skill`, `read`, `write`, `bash`, `glob`, `grep`, `task`, `webfetch`, `websearch`, `external_directory`
- **Precedencia Interactiva (`~/.bashrc` + `~/.bash_aliases`):**
  - `~/.local/bin` precede a `mise`, garantizando que `agy`, `opencode` y `ftl` siempre lancen los wrappers autónomos.

## Comandos CLI (`tardis-agy` & `ftl-continue`)
- `tardis-agy status` / `tardis-agy verify-permissions [--live]` — Telemetría y verificación cero-prompts.
- `tardis-agy run "<tarea>"` / `tardis-agy turn "<prompt>"` / `tardis-agy continue "<prompt>" [--conversation <cid>]`
- `tardis-agy enqueue "<tarea>" [--priority critical|high|normal|low]` / `tardis-agy queue` / `tardis-agy sessions`
- `ftl-continue status` / `ftl-continue verify` — Auditoría integral de autonomía en `agy`, `FTL` y `opencode`.
- `ftl-continue scan [--hours 48]` — Detecta procesos pausados, fallidos (p. ej. 429) o inconclusos en las 3 terminales.
- `ftl-continue reconcile` — Reconcilia peticiones `in_progress` ya concluidas en `continuity_vault.db`.
- `ftl-continue run [--terminals agy,opencode,ftl] [--enqueue]` — Continúa autónomamente los procesos pendientes de principio a fin con failover del pool gratuito de FTL.
- `ftl-continue continue-agy <cid>` / `ftl-continue continue-opencode <sid>` / `ftl-continue continue-ftl <req_id>`
- `ftl --continue-all` / `ftl --scan-terminals` / `:continue` dentro de FTL CLI.

## API REST Local (`http://127.0.0.1:8757`)
- `GET /api/agy/control/status` · `/queue` · `/sessions` · `/verify`
- `POST /api/agy/control/exec` · `/turn` · `/enqueue` · `/continue` · `/mode`

## Servicio Systemd 24/7
- `systemctl --user status tardis-agy-autopilot.service` (procesa la cola `tardis-agy` y ejecuta barridos periódicos de continuación multi-terminal cada 180s).
