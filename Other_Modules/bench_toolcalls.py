"""
bench_toolcalls.py - Mide fiabilidad de tool-calls: full 35 tools vs subset.
============================================================================
Para cada tarea: pide al 7b que actue, parsea la respuesta y mide
  (a) emitio un tool-call PARSEABLE
  (b) fue la tool CORRECTA (esperada)
Compara condicion FULL (35 tools) contra SUBSET (tool_selector).
"""
import json
import sys
import time
import httpx

sys.path.insert(0, r"C:\LOCAL-LLM\GODWORKS SYSTEM")
from gia_agent import TOOLS_SCHEMA, parse_tool_calls, SYSTEM_PROMPT, _build_env_context
import tool_selector
from datetime import date

OLLAMA = "http://REDACTED_IP:11434"
MODEL = "qwen2.5-coder:7b"

# tarea -> tools aceptables como "correctas"
TESTS = [
    ("Crea un archivo llamado nota.txt en el escritorio con el texto hola", {"write_file"}),
    ("Lista los archivos de mi carpeta de Descargas", {"list_dir"}),
    ("Busca en internet cuanto cuesta un iPhone 15", {"web_search"}),
    ("Toma una foto con la camara y guardala", {"capture_photo"}),
    ("Lee el texto que hay en la pantalla", {"read_screen", "read_window"}),
    ("Cierra los programas mas pesados para liberar RAM", {"free_compute"}),
    ("Dime en voz alta: hola Miguel", {"speak"}),
    ("Que temperatura tienen mi CPU y GPU ahora", {"read_sensors"}),
    ("Ejecuta el comando dir con powershell", {"run_shell"}),
    ("Busca archivos con extension pdf en todo mi disco", {"search_files"}),
]


def ask(task, tools):
    system = SYSTEM_PROMPT.format(date=date.today().isoformat(),
                                  env_context=_build_env_context())
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"TAREA: {task}"}]
    t0 = time.time()
    r = httpx.post(f"{OLLAMA}/api/chat", json={
        "model": MODEL, "messages": messages, "tools": tools,
        "stream": False, "options": {"num_ctx": 8192, "temperature": 0.0},
        "keep_alive": "30m",
    }, timeout=600.0)
    r.raise_for_status()
    msg = r.json().get("message", {})
    calls = parse_tool_calls(msg)
    return calls, time.time() - t0


def run(condition, get_tools):
    ok_parse = ok_correct = 0
    total_t = 0.0
    print(f"\n===== {condition} =====")
    for task, expected in TESTS:
        tools = get_tools(task)
        try:
            calls, dt = ask(task, tools)
        except Exception as e:
            print(f"  ERR {task[:40]}: {e}")
            continue
        total_t += dt
        parsed = len(calls) > 0
        correct = parsed and calls[0][0] in expected
        ok_parse += parsed
        ok_correct += correct
        got = calls[0][0] if parsed else "(ninguno)"
        mark = "OK " if correct else ("~  " if parsed else "XX ")
        print(f"  {mark}[{len(tools)}t] {task[:44]:44} -> {got}")
    n = len(TESTS)
    print(f"  PARSEABLE: {ok_parse}/{n}  CORRECTO: {ok_correct}/{n}  "
          f"t_prom: {total_t/n:.1f}s")
    return ok_parse, ok_correct


if __name__ == "__main__":
    # Verificar Ollama
    httpx.get(f"{OLLAMA}/api/tags", timeout=5.0)
    fp, fc = run("FULL (35 tools)", lambda task: TOOLS_SCHEMA)
    sp, sc = run("SUBSET (tool_selector)",
                 lambda task: tool_selector.subset_schema(TOOLS_SCHEMA, task))
    n = len(TESTS)
    print("\n================ RESUMEN ================")
    print(f"FULL   : parseable {fp}/{n}, correcto {fc}/{n}")
    print(f"SUBSET : parseable {sp}/{n}, correcto {sc}/{n}")
    print(f"Delta correcto: {sc - fc:+d}")
