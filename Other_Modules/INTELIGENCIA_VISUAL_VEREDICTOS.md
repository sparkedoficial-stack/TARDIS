# 👁️ TARDIS · Inteligencia Visual y Veredictos (v26.5)

Motor de percepción multimodal real: TARDIS **observa** la imagen (no solo extrae
rasgos ópticos), la describe con un VLM local y emite un **veredicto estructurado**
sobre el entorno del Arquitecto.

## 1. Arquitectura

```
Cámara C310 / foto / video / audio
        │
        ▼
core/visual_intelligence_engine.py
        ├── analyze_frame_features()        → rostros, OCR, color, nitidez, movimiento
        ├── describe_image_with_vlm()       → VLM multimodal real
        │      1) Ollama local  qwen3-vl:2b-instruct   (privado, la imagen no sale del equipo)
        │      2) Gemini  (solo si hay GEMINI_API_KEY)
        │      3) endpoint OpenAI-compatible (VLM_BASE_URL/VLM_MODEL)
        ├── _sanitize_vlm_text()            → neutraliza bucles de repetición de VLM pequeños
        ├── _synthesize_conclusions_with_kaiju(verdict_mode=True)
        │      → Groq LPU (qwen/qwen3.8-27b) ~3 s · fallback KAIJU local
        ├── _build_verdict_data()           → risk_level 0-10 + etiqueta + hechos/inferencias
        └── persistencia SQLite + Bóveda RAG/Akasha
```

**Veredicto**: estado general, hechos observados, inferencias, dudas, nivel de
riesgo objetivo 0–10 y recomendación concreta.

## 2. Fuentes de imagen para "el entorno"

Orden de `capture_surroundings_image()`:

1. **GOD-EYE C310** (`http://127.0.0.1:8797/c310/snapshot.jpg`) — cámara de seguridad.
2. `latest_frame.jpg` persistido por `tapo_c310_sentinel`.
3. Hub de cámara local.
4. Webcam OpenCV del portátil.

## 3. Capas de acceso

| Capa | Comando / endpoint |
|---|---|
| Telegram | `/veredicto`, `/dictamen`, `/alrededor`, `/entorno`, `/que_ves` · `/veredictos` (historial) |
| CLI | `tardis visual veredicto [c310\|local\|webcam\|auto] [pregunta]` |
| API | `POST /api/visual_intelligence/verdict` · `GET .../verdict/last` · `GET .../records` |
| Agentes | tools `visual_verdict_about_surroundings`, `get_last_visual_verdict` |
| 24/7 | `tardis-visual-intelligence.service` (veredicto periódico cada 900 s si la escena cambió) |

### Ejemplos

```bash
tardis visual veredicto c310 "¿hay alguien sospechoso?"
curl -X POST http://127.0.0.1:8757/api/visual_intelligence/verdict \
     -H 'Content-Type: application/json' \
     -d '{"camera":"c310","question":"describe mi entorno"}'
```

## 4. Variables de entorno

| Variable | Default | Uso |
|---|---|---|
| `TARDIS_SURROUNDINGS_INTERVAL` | `900` | Segundos entre veredictos automáticos (0 = desactiva) |
| `TARDIS_VLM_VIDEO` | `1` | Analiza keyframes de video con VLM |
| `VLM_PROVIDER` | `auto` | `ollama` \| `gemini` \| `openai` \| `auto` |
| `VLM_GEMINI_MODEL` | `gemini-2.5-flash` | Modelo de respaldo en nube |
| `VLM_BASE_URL` / `VLM_API_KEY` / `VLM_MODEL` | — | Endpoint OpenAI-compatible alterno |

## 5. Rendimiento (ASUS TUF A15 · Ryzen 7 4800H · RTX 3050 4 GB)

La GPU está comprometida por el cerebro KAIJU (`llama-server`, ~3.3 GB VRAM), por lo
que el VLM corre en CPU. El servicio `ollama.service` se prioriza con `nice -5`
(drop-in `10-priority.conf`) y el cerebro KAIJU baja a `nice 10` para no asfixiar
la inferencia interactiva.

| Escenario | Latencia |
|---|---|
| Prefill de imagen (1 049 tokens visuales, fijo) | 22–30 s |
| Decodificación (~150 tokens) | 8–12 s |
| Síntesis de veredicto (Groq LPU) | ~3 s |
| **E2E en frío (incluye carga del modelo)** | **~58 s** |
| **E2E en caliente** | **~35–45 s** |

El prefill visual es independiente de la resolución enviada: Ollama normaliza toda
imagen a un presupuesto fijo de tokens (~1 049).

## 6. Diagnóstico

```bash
systemctl --user status tardis-visual-intelligence.service
journalctl --user -u tardis-visual-intelligence.service -f
cat "data/visual_intelligence/daemon_status.json" | jq .surroundings
ollama ps                     # debe mostrar solo qwen3-vl:2b-instruct
curl -s localhost:8757/api/visual_intelligence/status | jq '{vlm_ready,vlm_model,stored_verdicts_count}'
```

Si `ollama ps` muestra varios modelos cargados, liberar RAM:

```bash
ollama stop qwen3-vl:2b            # variante "thinking": no usar
ollama stop TARDIS-NEURAL-SPACE-KAIJU
```
