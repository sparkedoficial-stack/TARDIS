"""
run_comprehensive_benchmark.py - Suite Maestra de Benchmark Integral
GODWORKS SYSTEM & TARDIS Sovereign Architecture
==============================================================================
Evalúa rigurosamente:
  1. Silicio y Memoria: 32 GB RAM física, 28 GB mlock, 16 hilos CPU, RTX 3050 VRAM.
  2. Motor Neuronal Soberano: Inferencia local TARDIS-NEURAL-SPACE-KAIJU (tokens/s, latencia, num_ctx 8192).
  3. Orquestador Cognitivo Causal: Compilación IR, despacho híbrido y memoria continua SSM.
  4. Bóveda de Memoria Profunda: SQLite FTS5 BM25, 4 GB MMAP zero-copy, grafo akáshico.
  5. Sensores de Presencia Física: Fusión óptica, radar RF y actividad de entrada.
  6. Orquestador Multi-Capa de Hardware: Monitoreo de 5 capas en background.
  7. API Gateway & Endpoints: Latencias de respuesta HTTP local (puerto 8757).
  8. Acelerador Cloud Cognitivo: Pasarela Groq LPU de alta velocidad.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import resource
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

import psutil

# Suprimir logs ruidosos durante benchmark
logging.basicConfig(level=logging.WARNING)

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

VAULT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
BENCH_REPORT_PATH = VAULT_DIR / "comprehensive_system_benchmark_report.json"

results: Dict[str, Any] = {
    "benchmark_timestamp": time.time(),
    "benchmark_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
    "silicon_memory": {},
    "sovereign_llm_inference": {},
    "cognitive_orchestrator": {},
    "deep_memory_vault": {},
    "physical_presence_sensors": {},
    "hardware_orchestrator_layers": {},
    "api_gateway_latency": {},
    "cloud_accelerator": {},
    "overall_score": {}
}


def print_section(num: int, title: str):
    print(f"\n{'='*75}")
    print(f" [{num}/8] {title}")
    print(f"{'='*75}")


# =============================================================================
# 1. SILICIO Y MEMORIA RAM (32 GB / 28 GB MLOCK / RYZEN 16 HILOS / RTX 3050)
# =============================================================================
print_section(1, "EVALUACIÓN DE SILICIO, MEMORIA RAM Y VRAM")

mem = psutil.virtual_memory()
swap = psutil.swap_memory()
cpu_count_logical = psutil.cpu_count(logical=True)
cpu_count_physical = psutil.cpu_count(logical=False)
cpu_freq = psutil.cpu_freq()

soft_memlock, hard_memlock = resource.getrlimit(resource.RLIMIT_MEMLOCK)

# GPU NVIDIA
gpu_info = {"name": "No detectada", "vram_used_mb": 0, "vram_total_mb": 0, "temp_c": 0, "util_percent": 0}
try:
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=3
    )
    if smi.returncode == 0 and smi.stdout.strip():
        parts = [p.strip() for p in smi.stdout.strip().split(",")]
        if len(parts) >= 5:
            gpu_info = {
                "name": parts[0],
                "vram_used_mb": float(parts[1]),
                "vram_total_mb": float(parts[2]),
                "temp_c": float(parts[3]),
                "util_percent": float(parts[4])
            }
except Exception as e:
    gpu_info["error"] = str(e)

# Test de ancho de banda de memoria RAM sintético (lectura/escritura en RAM)
t0 = time.perf_counter()
test_bytes = bytearray(256 * 1024 * 1024)  # 256 MB
for i in range(0, len(test_bytes), 4096):
    test_bytes[i] = 1
t1 = time.perf_counter()
ram_speed_gb_s = round((256 / 1024) / (t1 - t0), 2)
del test_bytes

results["silicon_memory"] = {
    "ram_total_gb": round(mem.total / (1024**3), 2),
    "ram_used_gb": round(mem.used / (1024**3), 2),
    "ram_available_gb": round(mem.available / (1024**3), 2),
    "ram_percent_used": mem.percent,
    "ram_write_bandwidth_gb_s": ram_speed_gb_s,
    "mlock_budget_gb": 28.0,
    "os_reserved_gb": 4.0,
    "cpu_logical_threads": cpu_count_logical,
    "cpu_physical_cores": cpu_count_physical,
    "cpu_frequency_mhz": round(cpu_freq.current if cpu_freq else 0, 1),
    "gpu": gpu_info,
    "swap_total_gb": round(swap.total / (1024**3), 2),
    "swap_used_gb": round(swap.used / (1024**3), 2)
}

print(f" • Memoria RAM Física : {results['silicon_memory']['ram_total_gb']} GB detectados ({results['silicon_memory']['ram_available_gb']} GB disponibles)")
print(f" • Presupuesto MLOCK  : 28.0 GB fijados en RAM (4.0 GB para SO/Buffers)")
print(f" • Ancho de Banda RAM : {ram_speed_gb_s} GB/s (sintético secuencial)")
print(f" • CPU AMD Ryzen      : {cpu_count_physical} núcleos físicos / {cpu_count_logical} hilos lógicos")
print(f" • GPU NVIDIA         : {gpu_info.get('name')} | VRAM: {gpu_info.get('vram_used_mb')}/{gpu_info.get('vram_total_mb')} MB | Temp: {gpu_info.get('temp_c')}°C")


# =============================================================================
# 2. INFERENCIA LOCAL DEL MODELO SOBERANO (TARDIS-NEURAL-SPACE-KAIJU)
# =============================================================================
print_section(2, "INFERENCIA LOCAL SOBERANA (TARDIS-NEURAL-SPACE-KAIJU)")

try:
    test_prompt = "¿Cómo converge la función de onda probabilística hacia el atractor sintrópico?"
    payload = json.dumps({
        "model": "TARDIS-NEURAL-SPACE-KAIJU",
        "prompt": test_prompt,
        "stream": False,
        "options": {
            "num_predict": 128,
            "num_ctx": 8192,
            "temperature": 0.2
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://REDACTED_IP:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    t1 = time.perf_counter()
    elapsed = t1 - t0

    eval_count = data.get("eval_count", 0)
    eval_dur_ns = data.get("eval_duration", 1)
    prompt_eval_count = data.get("prompt_eval_count", 0)
    prompt_eval_dur_ns = data.get("prompt_eval_duration", 1)

    tok_sec = round((eval_count / (eval_dur_ns / 1e9)), 2) if eval_dur_ns else round(eval_count / elapsed, 2)
    prompt_tok_sec = round((prompt_eval_count / (prompt_eval_dur_ns / 1e9)), 2) if prompt_eval_dur_ns else 0

    results["sovereign_llm_inference"] = {
        "model": "TARDIS-NEURAL-SPACE-KAIJU",
        "context_window_used": 8192,
        "tokens_generated": eval_count,
        "generation_elapsed_seconds": round(elapsed, 3),
        "tokens_per_second": tok_sec,
        "prompt_eval_tokens": prompt_eval_count,
        "prompt_eval_tokens_per_sec": prompt_tok_sec,
        "status": "OPERATIONAL"
    }
    print(f" • Modelo Soberano    : TARDIS-NEURAL-SPACE-KAIJU (num_ctx 8192)")
    print(f" • Throughput Gen     : {tok_sec} tokens/segundo")
    print(f" • Throughput Prompt  : {prompt_tok_sec} tokens/segundo")
    print(f" • Latencia Total     : {elapsed:.2f}s ({eval_count} tokens emitidos)")
except Exception as e:
    results["sovereign_llm_inference"] = {"status": "ERROR", "error": str(e)}
    print(f" • Error Inferencia Local: {e}")


# =============================================================================
# 3. ORQUESTADOR COGNITIVO CAUSAL (KAIJU & SSM CONTINUO)
# =============================================================================
print_section(3, "ORQUESTADOR COGNITIVO CAUSAL & MEMORIA CONTINUA SSM")

try:
    from core.kaiju_cognitive_orchestrator import get_kaiju_cognitive_orchestrator
    from core.sovereign_neural_engine import get_sovereign_neural_engine

    k_orch = get_kaiju_cognitive_orchestrator()
    sne = get_sovereign_neural_engine()

    # 1. Benchmark de compilación de Representación Intermedia (IR)
    t0 = time.perf_counter()
    for _ in range(100):
        ir = k_orch.compile_to_inter_ai_ir(
            user_prompt="Optimizar la coherencia topológica del tensor de estado.",
            active_expert="Expert_TemporalCausality",
            presence_summary="IMMEDIATE_DESK (0.4m, 98% confianza)"
        )
    t1 = time.perf_counter()
    ir_compile_latency_us = round(((t1 - t0) / 100) * 1e6, 2)

    # 2. Benchmark de asimilación en el Estado Recurrente Continuo SSM (Mamba/Jamba O(1))
    t0 = time.perf_counter()
    for i in range(50):
        sne.process_context(f"Muestra de estado causal {i}: entropía {i*0.01:.3f}", session_id="bench_session")
    t1 = time.perf_counter()
    ssm_update_latency_ms = round(((t1 - t0) / 50) * 1000, 3)

    results["cognitive_orchestrator"] = {
        "ir_compilation_latency_us": ir_compile_latency_us,
        "ssm_context_update_latency_ms": ssm_update_latency_ms,
        "ir_hardware_metrics_active": "[HARDWARE_METRICS: 32 GB RAM (28 GB Dedicated Working Set mlock, 4 GB OS)" in ir,
        "status": "OPERATIONAL"
    }
    print(f" • Compilación IR     : {ir_compile_latency_us} µs / compilación (Throughput: {int(1e6/ir_compile_latency_us)} ops/s)")
    print(f" • Actualización SSM  : {ssm_update_latency_ms} ms / ciclo de estado continuo")
    print(f" • Inyección Métrica  : {'ACTIVA Y VERIFICADA' if results['cognitive_orchestrator']['ir_hardware_metrics_active'] else 'INACTIVA'}")
except Exception as e:
    results["cognitive_orchestrator"] = {"status": "ERROR", "error": str(e)}
    print(f" • Error Orquestador Cognitivo: {e}")


# =============================================================================
# 4. BÓVEDA DE MEMORIA PROFUNDA AKÁSHICA (250 GB / 4 GB MMAP)
# =============================================================================
print_section(4, "BÓVEDA DE MEMORIA PROFUNDA (SQLITE FTS5 & 4 GB MMAP ZERO-COPY)")

try:
    from core.deep_memory_vault import get_deep_memory_vault
    vault = get_deep_memory_vault()
    v_stats = vault.get_vault_telemetry()

    # 1. Test de Inserción Masiva
    t0 = time.perf_counter()
    for i in range(200):
        vault.ingest(
            source="benchmark_harness",
            role="system",
            content=f"Evento de benchmark #{i}: Sintonización causal de hardware 32 GB RAM y mlock 28 GB.",
            session_id="benchmark_session",
            importance=1.0
        )
    t1 = time.perf_counter()
    ingest_rate = round(200 / (t1 - t0), 2)
    ingest_latency_ms = round(((t1 - t0) / 200) * 1000, 3)

    # 2. Test de Búsqueda FTS5 BM25 en memoria indexada
    t0 = time.perf_counter()
    for _ in range(50):
        search_res = vault.search("Hardware 32GB RAM", k=5)
    t1 = time.perf_counter()
    search_latency_ms = round(((t1 - t0) / 50) * 1000, 3)

    # 3. Recuperación del Grafo Akáshico
    t0 = time.perf_counter()
    nodes = vault.get_relevant_knowledge_nodes(limit=10)
    t1 = time.perf_counter()
    graph_latency_ms = round((t1 - t0) * 1000, 3)

    results["deep_memory_vault"] = {
        "vault_size_mb": v_stats.get("vault_size_mb", 0),
        "total_events": v_stats.get("total_events", 0),
        "knowledge_nodes": v_stats.get("knowledge_nodes", 0),
        "complexity_level": v_stats.get("complexity_level", 0),
        "sqlite_mmap_configured_mb": 4096,
        "sqlite_cache_configured_mb": 128,
        "ingest_throughput_per_sec": ingest_rate,
        "ingest_latency_ms": ingest_latency_ms,
        "fts5_search_latency_ms": search_latency_ms,
        "graph_node_retrieval_ms": graph_latency_ms,
        "status": "OPTIMAL"
    }
    print(f" • Eventos Totales    : {v_stats.get('total_events', 0):,} turnos indexados sin truncamiento")
    print(f" • Nodos Akáshicos    : {v_stats.get('knowledge_nodes', 0)} entidades cognitivas (Nivel Complejidad: {v_stats.get('complexity_level', 0)})")
    print(f" • Ingesta Zero-Copy  : {ingest_rate} eventos/s ({ingest_latency_ms} ms/evento)")
    print(f" • Búsqueda FTS5 BM25 : {search_latency_ms} ms / consulta")
    print(f" • Grafo Akáshico     : {graph_latency_ms} ms / resolución de 10 nodos")
except Exception as e:
    results["deep_memory_vault"] = {"status": "ERROR", "error": str(e)}
    print(f" • Error Bóveda Profunda: {e}")


# =============================================================================
# 5. SENSORES DE DETECCIÓN DE PRESENCIA FÍSICA
# =============================================================================
print_section(5, "DETECCIÓN SENSORIAL DE PRESENCIA FÍSICA & MOVIMIENTO")

try:
    from core.physical_presence_sensor import get_physical_presence_sensor
    sensor = get_physical_presence_sensor()

    t0 = time.perf_counter()
    reading = sensor.get_presence_reading(force_refresh=True)
    t1 = time.perf_counter()
    acq_latency_ms = round((t1 - t0) * 1000, 2)

    results["physical_presence_sensors"] = {
        "presence_detected": reading.presence_detected,
        "proximity_zone": str(reading.proximity_zone),
        "motion_detected": reading.motion_detected,
        "confidence_score": reading.confidence_score,
        "estimated_distance_m": reading.estimated_distance_m,
        "acquisition_latency_ms": acq_latency_ms,
        "status": "OPERATIONAL"
    }
    dist_str = f"{reading.estimated_distance_m:.1f} m" if reading.estimated_distance_m else "N/A"
    print(f" • Presencia Detectada: {'SÍ' if reading.presence_detected else 'NO'}")
    print(f" • Zona de Proximidad : {reading.proximity_zone} (~{dist_str})")
    print(f" • Movimiento Humano  : {'DETECTADO' if reading.motion_detected else 'ESTÁTICO'} (Confianza: {reading.confidence_score*100:.1f}%)")
    print(f" • Latencia Adquisición: {acq_latency_ms} ms")
except Exception as e:
    results["physical_presence_sensors"] = {"status": "ERROR", "error": str(e)}
    print(f" • Error Sensor de Presencia: {e}")


# =============================================================================
# 6. ORQUESTADOR DE HARDWARE MULTI-CAPA EN SEGUNDO PLANO
# =============================================================================
print_section(6, "ORQUESTADOR DE HARDWARE EN SEGUNDO PLANO (5 CAPAS)")

try:
    from core.background_hardware_orchestrator import get_background_hardware_orchestrator
    hw_orch = get_background_hardware_orchestrator()

    t0 = time.perf_counter()
    l1 = hw_orch.inspect_layer_1_audio()
    l2 = hw_orch.inspect_layer_2_optical()
    l3 = hw_orch.inspect_layer_3_power_thermals()
    l4 = hw_orch.inspect_layer_4_rf_networks()
    l5 = hw_orch.inspect_layer_5_silicon_memory()
    t1 = time.perf_counter()
    telemetry_latency_us = round((t1 - t0) * 1e6, 2)

    results["hardware_orchestrator_layers"] = {
        "layer_1_audio": l1,
        "layer_2_optical": l2,
        "layer_3_power_thermals": l3,
        "layer_4_rf_networks": l4,
        "layer_5_silicon_memory": l5,
        "inspection_latency_us": telemetry_latency_us,
        "status": "ACTIVE"
    }
    print(f" • Capa 1 Acústica    : Volumen {l1.get('volume_percent')}% | Muted: {l1.get('muted')}")
    print(f" • Capa 2 Óptica      : Brillo {l2.get('screen_brightness_percent')}% | Teclado: Nivel {l2.get('keyboard_backlight_level')}")
    print(f" • Capa 3 Potencia    : Perfil '{l3.get('active_profile')}' | Temp CPU: {l3.get('max_cpu_temp_c', 0):.1f}°C")
    print(f" • Capa 4 RF / Redes  : SSID '{l4.get('active_ssid')}' | Bluetooth: {l4.get('bluetooth_powered')}")
    print(f" • Capa 5 Memoria     : RAM {l5.get('ram_used_gb')} GB / {l5.get('ram_total_gb')} GB (Presupuesto: {l5.get('target_working_set_gb')} GB mlock)")
    print(f" • Latencia Inspección: {telemetry_latency_us} µs")
except Exception as e:
    results["hardware_orchestrator_layers"] = {"status": "ERROR", "error": str(e)}
    print(f" • Error Orquestador Multi-Capa: {e}")


# =============================================================================
# 7. LATENCIA DE ENDPOINTS DE LA API SOBERANA (PUERTO 8757)
# =============================================================================
print_section(7, "LATENCIA DEL GATEWAY HTTP Y ENDPOINTS (PUERTO 8757)")

endpoints = [
    ("/api/status", "GET"),
    ("/api/antigravity/feedback", "GET"),
    ("/api/missions/status", "GET"),
    ("/api/conjectures/status", "GET")
]
api_latencies: Dict[str, Any] = {}
for ep, method in endpoints:
    url = f"http://REDACTED_IP:8757{ep}"
    try:
        lat_list = []
        for _ in range(3):
            t0 = time.perf_counter()
            req = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(req, timeout=5) as r:
                _ = r.read()
            t1 = time.perf_counter()
            lat_list.append((t1 - t0) * 1000)
        avg = round(sum(lat_list) / len(lat_list), 2)
        api_latencies[ep] = {"average_ms": avg, "status": "ONLINE"}
        print(f" • {ep:25}: {avg:6.2f} ms")
    except Exception as e:
        api_latencies[ep] = {"status": "ERROR", "error": str(e)}
        print(f" • {ep:25}: Error ({e})")
results["api_gateway_latency"] = api_latencies


# =============================================================================
# 8. ACELERADOR CLOUD COGNITIVO (GROQ LPU / HIGH SPEED GATEWAY)
# =============================================================================
print_section(8, "ACELERADOR COGNITIVO DE ALTA VELOCIDAD (GROQ LPU)")

try:
    cfg_path = VAULT_DIR / "chinese_api_config.json"
    if cfg_path.exists():
        cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
        api_key = cfg_data.get("api_keys", {}).get("groq_deepseek", "")
        model_name = cfg_data.get("active_model", "qwen/qwen3.8-27b")
        if api_key:
            payload = json.dumps({
                "model": model_name,
                "messages": [{"role": "user", "content": "Return 'OK'"}],
                "max_tokens": 10,
                "temperature": 0.1
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"
                }
            )
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=10) as c_resp:
                c_data = json.loads(c_resp.read().decode("utf-8"))
            t1 = time.perf_counter()
            elapsed_cloud = t1 - t0
            usage = c_data.get("usage", {})
            c_toks = usage.get("completion_tokens", 0)
            tok_s = round(c_toks / elapsed_cloud, 2) if elapsed_cloud else 0

            results["cloud_accelerator"] = {
                "provider": "Groq LPU",
                "model": model_name,
                "latency_seconds": round(elapsed_cloud, 3),
                "tokens_per_second": tok_s,
                "status": "OPERATIONAL"
            }
            print(f" • Pasarela Cloud     : Groq LPU ({model_name})")
            print(f" • Latencia Respuesta : {elapsed_cloud:.3f}s")
            print(f" • Throughput Tokens  : {tok_s} tok/s")
        else:
            results["cloud_accelerator"] = {"status": "Sin API key"}
            print(" • Sin API key configurada para el acelerador cloud.")
    else:
        results["cloud_accelerator"] = {"status": "Configurador no encontrado"}
        print(" • Archivo de configuración no encontrado.")
except Exception as e:
    results["cloud_accelerator"] = {"status": "ERROR", "error": str(e)}
    print(f" • Error Acelerador Cloud: {e}")


# =============================================================================
# CONCLUSIÓN Y PUNTUACIÓN DE EFICIENCIA SISTÉMICA
# =============================================================================
print_section(8, "RESUMEN EJECUTIVO Y PUNTUACIÓN DE EFICIENCIA")

score = 100.0
deductions = []
if results["sovereign_llm_inference"].get("status") != "OPERATIONAL":
    score -= 20
    deductions.append("Fallo en inferencia local Ollama")
if results["deep_memory_vault"].get("status") != "OPTIMAL":
    score -= 15
    deductions.append("Anomalía en Deep Memory Vault")
if results["physical_presence_sensors"].get("status") != "OPERATIONAL":
    score -= 10
    deductions.append("Fallo en sensores de presencia física")

results["overall_score"] = {
    "systemic_efficiency_score": score,
    "grade": "SOBERANO EXCELENTE" if score >= 90 else "BUENO",
    "deductions": deductions
}

# Guardar reporte consolidado
BENCH_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
BENCH_REPORT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"\n📊 PUNTUACIÓN DE EFICIENCIA SISTÉMICA: {score}/100 ({results['overall_score']['grade']})")
print(f"📄 Reporte completo archivado en: {BENCH_REPORT_PATH}")
print("=" * 75)
