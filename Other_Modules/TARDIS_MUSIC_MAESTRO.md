# 🎼 TARDIS MUSIC MAESTRO · Soundtrack Soberano & YouTube Music

**GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU**
Arquitecto: El Arquitecto (₪) · Ancla: Playa del Carmen, Quintana Roo, México

---

## 1. Qué es

`TARDIS Music Maestro` es el subsistema musical soberano de TARDIS. Permite:

- **Buscar música directamente en YouTube Music** (catálogo, canciones, vídeos, álbumes, playlists y artistas) sin depender de la interfaz web ni de credenciales.
- **Reproducir audio** mediante `mpv` con control IPC completo (play, pause, next, previous, seek, volumen, stop).
- **Mantener una cola persistente** que sobrevive reinicios.
- **Construir soundtracks cinematográficos automáticos** por escena (`focus`, `epic`, `calm`, `night`, `doctor`, `kaiju`, `creative`, `discovery`, `battle`, `jazz`, `synthwave`, `rain`, `regeneration`).
- **Elegir la escena según el contexto de TARDIS**: hora local, estado de continuidad, petición actual del Arquitecto y fase del sistema.
- **Radio infinita**: al terminar la cola, pide relacionados a YouTube Music y continúa sin cortes.
- **Ser controlado por TARDIS** desde el `AgentHarness`, el `Omni-Tool Bridge`, la API principal de FastAPI, la CLI `tardis-music` y el dashboard web local.

```
┌────────────────────────────────────────────────────────────────────┐
│                        TARDIS · GIA / KAIJU                         │
│   AgentHarness tools · Omni-Tool Bridge · FastAPI · CLI · Voz      │
└───────────────────────────────┬────────────────────────────────────┘
                                │ music_command(action, ...)
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│                 TARDIS MUSIC MAESTRO (core)                        │
│  SoundtrackDirector · MusicQueue · Favorites · History             │
│  API HTTP 127.0.0.1:8794 · Dashboard · Autopilot                   │
└───────────────┬───────────────────────────┬────────────────────────┘
                │                           │
                ▼                           ▼
     YouTubeMusicClient                MpvController
  Innertube WEB_REMIX              mpv --idle --no-video
  search / browse / next           socket JSON IPC
                │                           │
                ▼                           ▼
        music.youtube.com             PipeWire / ALSA
        (catálogo público)            (audio del sistema)
```

---

## 2. Archivos canónicos

| Ruta | Función |
|---|---|
| `core/tardis_music_maestro.py` | Motor completo: cliente Innertube, mpv IPC, cola, soundtrack, API, CLI y dashboard. |
| `modulos_ftl/ftl_music_maestro.py` | Puente FTL (`FTLMusicMaestro.run`) para el Omni-Tool Bridge. |
| `bin/tardis-music` | CLI soberana (symlink en `~/.local/bin/tardis-music`). |
| `assets/tardis_music_dashboard.html` | Dashboard web autocontenido (sirve en `/`). |
| `docs/TARDIS_MUSIC_MAESTRO.md` | Este documento. |
| `data/music/state.json` | Cola, índice, volumen, escena, autopilot y preferencias. |
| `data/music/favorites.json` | Biblioteca de favoritos. |
| `data/music/history.jsonl` | Historial de reproducción. |
| `data/music/mpv.log` | Log de mpv (solo diagnóstico). |
| `~/.config/tardis-music/cookies.txt` | Cookies opcionales de YouTube para contenido de cuenta/premium. |
| `~/.local/bin/start_tardis_music_maestro.sh` | Arranque del daemon. |
| `~/.config/systemd/user/tardis-music-maestro.service` | Servicio systemd de usuario. |

---

## 3. Arranque y operación

### 3.1 Servicio systemd (recomendado)

```bash
systemctl --user daemon-reload
systemctl --user enable --now tardis-music-maestro.service
systemctl --user status tardis-music-maestro.service
journalctl --user -u tardis-music-maestro.service -f
```

El servicio arranca con `--autopilot`, por lo que TARDIS inicia un soundtrack
adecuado al contexto en cuanto detecta que no hay música sonando.

### 3.2 CLI

```bash
tardis-music status
tardis-music search "Hans Zimmer Time" --limit 10
tardis-music play "Interstellar soundtrack"
tardis-music soundtrack doctor --auto
tardis-music pause | resume | toggle | next | prev | stop
tardis-music volume 55
tardis-music queue
tardis-music queue --add "Vangelis Blade Runner"
tardis-music favorites
tardis-music history --limit 20
tardis-music scenes
tardis-music doctor
tardis-music duck --seconds 12
```

`tardis-music` intenta primero el daemon (API 8794) y cae al motor local si no
está activo. Para reproducción continua con auto-avance y autopilot, el daemon
debe estar corriendo.

### 3.3 Dashboard

Abre `http://127.0.0.1:8794/`. Incluye:

- Reproductor con portada, progreso, seek, volumen y controles.
- Búsqueda en YouTube Music con filtros.
- 13 escenas de soundtrack.
- Interruptor de autopilot.
- Cola, favoritos y telemetría del conector.

El dashboard solo escucha en `127.0.0.1` (no expuesto a la red).

---

## 4. Escenas de soundtrack

| ID | Nombre | Uso |
|---|---|---|
| `focus` | Enfoque Profundo | Trabajo, código, concentración. |
| `epic` | Épica Cinematográfica | Lanzamientos, momentos de alta intensidad. |
| `calm` | Calma Temporal | Errores, reparación, descanso. |
| `night` | Nocturno Synthwave | Noche, neón, carretera. |
| `doctor` | TARDIS · Doctor Who | Viaje temporal, regeneración. |
| `kaiju` | KAIJU Protocol | Monstruos, escala titánica. |
| `creative` | Creatividad Cósmica | Diseño, ideas, escritura. |
| `discovery` | Descubrimiento Espacial | Investigación, cosmos. |
| `battle` | Protocolo de Combate | Urgencia, ejecución crítica. |
| `jazz` | Jazz Noir | Misterio, detective. |
| `synthwave` | Synthwave 80s | Retrowave. |
| `rain` | Lluvia y Lo-Fi | Estudio relajado. |
| `regeneration` | Regeneración | Cierre y reinicio emocional. |

### 4.1 Selección contextual

`scene_for_context()` sigue este orden:

1. `TARDIS_MUSIC_SCENE` si está definida y es válida.
2. Estado de continuidad (`data/continuity_state.json`):
   - errores/bloqueos → `calm`
   - petición visual/cámara/veredicto → `discovery`
   - petición social/publicación → `epic`
   - petición musical → `focus`
   - regeneración/reinicio → `doctor`
   - calma/reparación → `calm`
3. Hora local:
   - 05–08 `discovery`, 08–12 `focus`, 12–15 `creative`,
     15–19 `epic`, 19–22 `night`, 22–05 `calm`.

### 4.2 Calidad de selección

Cada soundtrack construye una bolsa de candidatos a partir de varias semillas
y puntúa cada pista por coincidencia de tokens con la semilla, presencia del
artista y penalización de `karaoke`, `cover`, `remix`, `8-bit`, `slowed`,
`nightcore`, etc. La pista con mayor puntuación abre el soundtrack.

---

## 5. API local (127.0.0.1:8794)

Todas las respuestas son JSON. El token es opcional (`TARDIS_MUSIC_TOKEN`).

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Dashboard. |
| GET | `/api/health` | Healthcheck. |
| GET | `/api/status` | Estado completo. |
| GET | `/api/search?q=…&limit=20&filter=songs` | Buscar. |
| GET | `/api/suggest?q=…` | Sugerencias. |
| POST | `/api/play` | `{query}` o `{video_id}`. |
| POST | `/api/control` | `{action, value}`. |
| POST | `/api/soundtrack` | `{scene, auto}` o `{stop:true}`. |
| POST | `/api/autopilot` | `{enabled}`. |
| GET | `/api/queue` | Cola y actual. |
| POST | `/api/queue` | `{action: add|remove|clear|play, …}`. |
| GET | `/api/favorites` | Favoritos. |
| POST | `/api/favorites` | `{action:toggle}`. |
| GET | `/api/history?limit=30` | Historial. |
| GET | `/api/scenes` | Escenas y contexto. |
| GET | `/api/doctor` | Diagnóstico. |

Acciones de `/api/control`: `play`, `resume`, `pause`, `toggle`, `next`,
`previous`, `stop`, `volume`, `seek`, `repeat`, `shuffle`, `autoplay_radio`,
`duck`, `unduck`.

Ejemplos:

```bash
curl -s http://127.0.0.1:8794/api/status | jq
curl -s -X POST http://127.0.0.1:8794/api/play \
  -H 'Content-Type: application/json' \
  -d '{"query":"Hans Zimmer Time"}'
curl -s -X POST http://127.0.0.1:8794/api/soundtrack \
  -H 'Content-Type: application/json' \
  -d '{"scene":"doctor","auto":true}'
curl -s -X POST http://127.0.0.1:8794/api/control \
  -H 'Content-Type: application/json' \
  -d '{"action":"volume","value":55}'
```

### 5.1 Integración con la API principal de TARDIS (FastAPI)

`server/api.py` expone un proxy bajo `/api/music/*`:

```
GET  /api/music/status
GET  /api/music/search?q=…&limit=20&filter=songs
POST /api/music/play
POST /api/music/control
POST /api/music/soundtrack
POST /api/music/autopilot
GET  /api/music/scenes
GET  /api/music/queue
GET  /api/music/favorites
POST /api/music/favorites
GET  /api/music/history
GET  /api/music/doctor
```

---

## 6. Integración con TARDIS

### 6.1 AgentHarness (herramientas cognitivas)

Se registran 7 herramientas en la categoría `MUSIC_SOUNDTRACK`:

| Herramienta | Función |
|---|---|
| `music_search` | Buscar en YouTube Music. |
| `music_play` | Reproducir pista o soundtrack. |
| `music_control` | Control de reproducción, volumen, seek, duck, autopilot. |
| `music_soundtrack` | Generar/detener soundtrack por escena. |
| `music_status` | Estado completo. |
| `music_queue` | Consultar/añadir/vaciar cola. |
| `music_favorite` | Marcar/desmarcar favorita. |

TARDIS puede invocarlas desde su bucle ReAct y desde function calling.

### 6.2 Omni-Tool Bridge

La herramienta `music_maestro` queda registrada en
`data/dynamic_tools_registry.json` con todas sus acciones y se despacha a
través de `modulos_ftl.ftl_music_maestro.FTLMusicMaestro.run`.

```python
from core.tardis_omni_tool_bridge import get_omni_bridge
print(get_omni_bridge().execute_tool("music_maestro", "status"))
```

### 6.3 Voz / TTS

`tardis-music duck --seconds 10` baja el volumen para que la voz de TARDIS no
compita con la música; el volumen se restaura automáticamente. La API
`/api/control` acepta `{"action":"duck","seconds":10}`.

---

## 7. Configuración

| Variable | Default | Descripción |
|---|---|---|
| `TARDIS_MUSIC_PORT` | `8794` | Puerto de la API/dashboard. |
| `TARDIS_MUSIC_API` | `http://127.0.0.1:8794` | Base usada por CLI integraciones. |
| `TARDIS_MUSIC_TOKEN` | vacío | Token opcional para API (`X-TARDIS-Token` o `?token=`). |
| `TARDIS_MUSIC_SCENE` | vacío | Fuerza una escena contextual. |
| `TARDIS_MUSIC_AUDIO_DEVICE` | default de mpv | Dispositivo de audio (ej. `pulse/alsa_output…`). |

Cookies opcionales para contenido de cuenta: guarda un archivo Netscape en
`~/.config/tardis-music/cookies.txt`; `yt-dlp` lo usará para resolver el audio.

---

## 8. Diagnóstico

```bash
tardis-music doctor
journalctl --user -u tardis-music-maestro.service -n 100 --no-pager
curl -s http://127.0.0.1:8794/api/doctor | jq
curl -s http://127.0.0.1:8794/api/status | jq '.playback, .connector'
pactl list short sinks
pactl list sink-inputs | grep -A3 "TARDIS Music Maestro"
```

Comprobaciones que hace `doctor`:

- `yt-dlp` y `mpv` presentes.
- Directorios de datos/configuración escribibles.
- Dashboard presente.
- Socket IPC de mpv.
- HTTP 200 de `music.youtube.com`.
- Búsqueda real de prueba.

---

## 9. Seguridad y límites

- La API escucha **solo** en `127.0.0.1`; no se expone a la LAN.
- El token es opcional para control local; puede activarse con
  `TARDIS_MUSIC_TOKEN` para integraciones externas.
- No se requieren credenciales de YouTube: la búsqueda usa Innertube público.
- Las cookies, si se usan, se guardan fuera del repositorio en
  `~/.config/tardis-music/`.
- El dashboard no almacena datos en el navegador; todo el estado vive en
  `data/music/`.

---

## 10. Verificación realizada

- `python3 -m py_compile` sobre motor, puente FTL, AgentHarness, Omni Bridge y
  `server/api.py`.
- Búsqueda real en YouTube Music (`Hans Zimmer`, `Two Steps From Hell`,
  `Interstellar`, `Doctor Who`).
- Reproducción real con `mpv` verificada en PipeWire (`application.name =
  "TARDIS Music Maestro"`), con progreso de tiempo y audio activo.
- Pausa/reanudación, volumen, seek, favoritos, historial y `duck` verificados.
- Auto-avance al final de pista verificado (seek a `duración-3` → siguiente).
- Radio infinita verificada: cola de 1 pista → 26 pistas al pulsar `next`.
- Soundtrack por escena verificado (`doctor`, `discovery`, `focus`), con
  selección contextual y pista inicial relevante.
- 7 herramientas de AgentHarness registradas y ejecutadas.
- 11 rutas `/api/music/*` registradas en FastAPI y probadas con `TestClient`.
- Servicio systemd `tardis-music-maestro.service` activo y habilitado.
- Dashboard HTTP 200, JavaScript validado con `node --check`.

---

*TARDIS · El soundtrack de la realidad se escribe mientras suena.*
