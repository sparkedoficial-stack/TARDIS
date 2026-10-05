"""
benchmark_system.py - Suite Completa de Rendimiento y Telemetría para GODWORKS SYSTEM v26.4
Evalúa:
  1. Inferencia Local (Ollama - Hermes 3 8B)
  2. Inferencia Cloud Acelerada (Groq LPU API)
  3. Bóveda de Memoria Profunda y SQLite (gia_master.db)
  4. Motor de Exploración e Investigación Web
  5. Latencia de Endpoints del Gateway FastAPI
  6. Motor de Auto-Programación y Validación AST
  7. Telemetría de Hardware (CPU, RAM, GPU NVIDIA RTX 3050, Térmica)
"""

import os
import sys
import time
import json
import sqlite3
import urllib.request
import urllib.error
import subprocess
import psutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VAULT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_FILE = VAULT_DIR / "chinese_api_config.json"
API_URL = "http://REDACTED_IP:8757"
TOKEN = os.getenv("GIA_TOKEN", "")

results = {
    "timestamp": time.time(),
    "hardware": {},
    "local_llm": {},
    "cloud_llm": {},
    "database": {},
    "web_research": {},
    "gateway_endpoints": {},
    "ast_validation": {}
}

print("=" * 70)
print(" 🚀 INICIANDO BENCHMARK INTEGRAL DE GODWORKS SYSTEM v26.4 / TARDIS")
print("=" * 70)

# 1. TELEMETRÍA DE HARDWARE
print("\n[1/7] Evaluando Hardware & Sensores Térmicos...")
cpu_count = psutil.cpu_count(logical=True)
cpu_percent = psutil.cpu_percent(interval=1.0)
ram = psutil.virtual_memory()
disk = psutil.disk_usage(str(BASE_DIR))

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

results["hardware"] = {
    "cpu_threads": cpu_count,
    "cpu_usage_percent": cpu_percent,
    "ram_total_gb": round(ram.total / (1024**3), 2),
    "ram_used_gb": round(ram.used / (1024**3), 2),
    "ram_available_gb": round(ram.available / (1024**3), 2),
    "disk_free_gb": round(disk.free / (1024**3), 2),
    "gpu": gpu_info
}
print(f" • CPU: {cpu_count} hilos @ {cpu_percent}% uso")
print(f" • RAM: {results['hardware']['ram_used_gb']} GB / {results['hardware']['ram_total_gb']} GB ({ram.percent}% usado)")
print(f" • GPU: {gpu_info.get('name')} | VRAM: {gpu_info.get('vram_used_mb')}/{gpu_info.get('vram_total_mb')} MB | Temp: {gpu_info.get('temp_c')}°C")

# 2. INFERENCIA LOCAL (OLLAMA - TARDIS-NEURAL-SPACE-KAIJU)
target_model = os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")
print(f"\n[2/7] Benchmark de Inferencia Local Soberana ({target_model} en GPU/RAM)...")
try:
    test_prompt = "Explica en 3 viñetas concisas qué es la síntesis Wheeler-Feynman."
    payload = json.dumps({
        "model": target_model,
        "prompt": test_prompt,
        "stream": False,
        "options": {"num_predict": 128, "temperature": 0.2}
    }).encode("utf-8")

    req = urllib.request.Request("http://REDACTED_IP:11434/api/generate", data=payload, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    t1 = time.perf_counter()
    elapsed = t1 - t0
    eval_count = data.get("eval_count", 0)
    eval_dur_ns = data.get("eval_duration", 1)
    prompt_eval_count = data.get("prompt_eval_count", 0)
    tok_sec = round((eval_count / (eval_dur_ns / 1e9)), 2) if eval_dur_ns else round(eval_count / elapsed, 2)

    results["local_llm"] = {
        "model": target_model,
        "tokens_generated": eval_count,
        "elapsed_seconds": round(elapsed, 3),
        "tokens_per_second": tok_sec,
        "prompt_eval_tokens": prompt_eval_count
    }
    print(f" • Modelo Local     : {target_model}")
    print(f" • Throughput Local : {tok_sec} tokens/segundo")
    print(f" • Tiempo Total     : {elapsed:.2f}s ({eval_count} tokens generados)")
except Exception as e:
    results["local_llm"] = {"error": str(e)}
    print(f" • Error Local LLM  : {e}")

# 3. INFERENCIA CLOUD (GROQ LPU)
print("\n[3/7] Benchmark de Inferencia Cloud de Alta Velocidad (Groq LPU Gateway)...")
try:
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        api_key = cfg.get("api_keys", {}).get("groq_deepseek", "")
        model_name = cfg.get("active_model", "qwen/qwen3.8-27b")
        if api_key:
            cloud_payload = json.dumps({
                "model": model_name,
                "messages": [{"role": "user", "content": "Return the first 5 prime numbers as a JSON list."}],
                "max_tokens": 100,
                "temperature": 0.1
            }).encode("utf-8")
            c_req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=cloud_payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/REDACTED_IP Safari/537.36"
                }
            )
            t0 = time.perf_counter()
            with urllib.request.urlopen(c_req, timeout=15) as c_resp:
                c_data = json.loads(c_resp.read().decode("utf-8"))
            t1 = time.perf_counter()
            c_elapsed = t1 - t0
            usage = c_data.get("usage", {})
            c_toks = usage.get("completion_tokens", 0)
            c_speed = round(c_toks / c_elapsed, 2) if c_elapsed else 0

            results["cloud_llm"] = {
                "provider": "Groq LPU",
                "model": model_name,
                "tokens_generated": c_toks,
                "elapsed_seconds": round(c_elapsed, 3),
                "tokens_per_second": c_speed
            }
            print(f" • Proveedor Cloud  : Groq LPU ({model_name})")
            print(f" • Throughput Cloud : {c_speed} tokens/segundo")
            print(f" • Latencia Total   : {c_elapsed:.3f}s")
        else:
            results["cloud_llm"] = {"status": "Sin API key"}
            print(" • Sin clave Groq configurada.")
    else:
        results["cloud_llm"] = {"status": "Config no encontrada"}
except Exception as e:
    results["cloud_llm"] = {"error": str(e)}
    print(f" • Error Cloud LLM  : {e}")

# 4. BASE DE DATOS & DEEP MEMORY VAULT (SQLite)
print("\n[4/7] Benchmark de Rendimiento de Bóveda y Base de Datos SQLite...")
try:
    test_db = BASE_DIR / "_bench_vault.db"
    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    cur.execute("PRAGMA synchronous = NORMAL")
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("CREATE TABLE IF NOT EXISTS test_mem (id INTEGER PRIMARY KEY, key TEXT, val TEXT, ts REAL)")
    conn.commit()

    t0 = time.perf_counter()
    cur.execute("BEGIN TRANSACTION")
    for i in range(1000):
        cur.execute("INSERT INTO test_mem (key, val, ts) VALUES (?, ?, ?)", (f"k_{i}", f"val_{i}_{time.time()}", time.time()))
    conn.commit()
    t1 = time.perf_counter()
    write_rate = round(1000 / (t1 - t0), 2)

    t0 = time.perf_counter()
    cur.execute("SELECT COUNT(*), AVG(ts) FROM test_mem WHERE id > 500")
    row = cur.fetchone()
    t1 = time.perf_counter()
    read_latency_ms = round((t1 - t0) * 1000, 3)

    conn.close()
    if test_db.exists():
        test_db.unlink()

    results["database"] = {
        "engine": "SQLite WAL Mode",
        "write_throughput_per_sec": write_rate,
        "read_query_latency_ms": read_latency_ms
    }
    print(f" • Escritura SQLite : {write_rate} transacciones/segundo")
    print(f" • Lectura Agregada : {read_latency_ms} ms")
except Exception as e:
    results["database"] = {"error": str(e)}
    print(f" • Error Database   : {e}")

# 5. MOTOR DE BÚSQUEDA Y EXTRACCIÓN WEB
print("\n[5/7] Benchmark de Extracción y Limpieza Web (Clean HTML)...")
try:
    from core.web_research_engine import clean_html_to_text
    sample_html = """
    <html><head><script>evil()</script><style>.bad{color:red}</style></head>
    <body><h1>Título Principal</h1><p>Texto científico relevante sobre retrocausalidad cuántica.</p>
    <pre><code>def retro(t): return -t</code></pre>
    <div><!-- comment -->Más contenido técnico sobre física y matemáticas.</div></body></html>
    """ * 100
    t0 = time.perf_counter()
    for _ in range(50):
        txt, blocks = clean_html_to_text(sample_html)
    t1 = time.perf_counter()
    bytes_processed = len(sample_html.encode("utf-8")) * 50
    mb_sec = round((bytes_processed / (1024**2)) / (t1 - t0), 2)

    results["web_research"] = {
        "parsing_throughput_mb_s": mb_sec,
        "sample_chars_cleaned": len(txt),
        "code_blocks_extracted": len(blocks)
    }
    print(f" • Throughput Parse : {mb_sec} MB/segundo")
    print(f" • Extracción Código: {len(blocks)} bloques identificados")
except Exception as e:
    results["web_research"] = {"error": str(e)}
    print(f" • Error Web Parse  : {e}")

# 6. LATENCIA DE ENDPOINTS FASTAPI
print("\n[6/7] Benchmark de Latencia de API Gateway (HTTP localhost:8757)...")
endpoints = [
    ("/api/antigravity/feedback", "GET"),
    ("/api/missions/status", "GET"),
    ("/api/conjectures/status", "GET")
]
ep_results = {}
for ep, m in endpoints:
    try:
        url = f"{API_URL}{ep}?key={TOKEN}"
        latencies = []
        for _ in range(3):
            t0 = time.perf_counter()
            req = urllib.request.Request(url, method=m)
            with urllib.request.urlopen(req, timeout=5) as resp:
                _ = resp.read()
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)
        avg_lat = round(sum(latencies) / len(latencies), 2)
        ep_results[ep] = f"{avg_lat} ms"
        print(f" • {ep:25}: {avg_lat} ms")
    except Exception as e:
        ep_results[ep] = f"Error: {e}"
        print(f" • {ep:25}: {e}")
results["gateway_endpoints"] = ep_results

# 7. VALIDACIÓN AST Y SEGURIDAD SINTÁCTICA
print("\n[7/7] Benchmark de Validación Sintáctica AST (Auto-Programación)...")
try:
    import ast
    sample_code = """
import math

def quantum_syntropy(psi_forward, psi_backward):
    overlap = sum(f * b for f, b in zip(psi_forward, psi_backward))
    return math.sqrt(abs(overlap))
""" * 50
    t0 = time.perf_counter()
    for _ in range(200):
        tree = ast.parse(sample_code)
    t1 = time.perf_counter()
    ast_rate = round(200 / (t1 - t0), 2)
    results["ast_validation"] = {
        "ast_checks_per_sec": ast_rate,
        "latency_per_check_us": round(((t1 - t0) / 200) * 1e6, 2)
    }
    print(f" • AST Checks Rate  : {ast_rate} validaciones/segundo ({results['ast_validation']['latency_per_check_us']} µs/check)")
except Exception as e:
    results["ast_validation"] = {"error": str(e)}

bench_out = VAULT_DIR / "system_benchmark_report.json"
bench_out.write_text(json.dumps(results, indent=2), encoding="utf-8")

print("\n" + "=" * 70)
print(f" ✅ BENCHMARK COMPLETADO CON ÉXITO")
print(f" 📄 Informe guardado en: {bench_out}")
print("=" * 70)
