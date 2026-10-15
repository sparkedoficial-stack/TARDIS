import re

with open("gia_agent.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add import for Logger
if "from sensor_telemetry import Logger" not in content:
    content = content.replace("import agent_safety as safety", "import agent_safety as safety\nfrom sensor_telemetry import Logger\n\n# Inicializar logger por defecto\nagent_logger = Logger()")

# In main(), add argument parser for --log-level
arg_parser_str = """
    ap.add_argument("--ctx", type=int, default=DEFAULT_CTX)
    ap.add_argument("--log-level", type=str, default="info", choices=["debug", "info", "warning", "error"],
                    help="nivel de logeo para el agente")
"""

content = re.sub(r'(\s+)ap\.add_argument\("--ctx", type=int, default=DEFAULT_CTX\)', arg_parser_str, content)

# Set logger level based on args.log_level
log_level_setup = """
    DRY_RUN = args.dry_run
    
    # Configurar nivel de log
    Logger.set_level(args.log_level)
    agent_logger.info(f"Iniciando GIA Agent. Tarea solicitada: {args.task}")
"""

content = re.sub(r'(\s+)DRY_RUN = args\.dry_run', log_level_setup, content)

# Also log when operations run
content = content.replace('safety.audit("shell", cmd[:200], verdict="ALLOW")', 'safety.audit("shell", cmd[:200], verdict="ALLOW")\n    agent_logger.info(f"Ejecutando shell: {cmd[:200]}")')

content = content.replace('safety.audit("read_file", path[:200])', 'safety.audit("read_file", path[:200])\n        agent_logger.info(f"Leyendo archivo: {path[:200]}")')

content = content.replace('safety.audit("write_file", path[:200], verdict="ALLOW")', 'safety.audit("write_file", path[:200], verdict="ALLOW")\n    agent_logger.info(f"Escribiendo archivo: {path[:200]}")')

content = content.replace('return {"ok": False, "error": f"{type(e).__name__}: {e}"}', 'agent_logger.error(f"Error: {type(e).__name__}: {e}")\n        return {"ok": False, "error": f"{type(e).__name__}: {e}"}')

with open("gia_agent.py", "w", encoding="utf-8") as f:
    f.write(content)

