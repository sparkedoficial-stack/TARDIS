import re

with open("sensor_telemetry.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add logging import if not exists
if "import logging" not in content:
    content = content.replace("import base64", "import logging\nimport base64")

# Add Logger class
logger_code = """
# =====================================================================
#  SISTEMA DE LOGS DEL AGENTE
# =====================================================================
class Logger:
    _instance = None

    def __new__(cls, log_file="agent_operations.log", level=logging.INFO):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
            cls._instance.logger = logging.getLogger("AgentLogger")
            cls._instance.logger.setLevel(level)
            
            # Evitar handlers duplicados
            if not cls._instance.logger.handlers:
                formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
                
                fh = logging.FileHandler(log_file, encoding='utf-8')
                fh.setFormatter(formatter)
                cls._instance.logger.addHandler(fh)
        return cls._instance

    @classmethod
    def set_level(cls, level_name):
        level = getattr(logging, level_name.upper(), logging.INFO)
        if cls._instance is None:
            cls("agent_operations.log", level)
        cls._instance.logger.setLevel(level)
        for handler in cls._instance.logger.handlers:
            handler.setLevel(level)

    def debug(self, msg):
        self.logger.debug(msg)
        
    def info(self, msg):
        self.logger.info(msg)
        
    def warning(self, msg):
        self.logger.warning(msg)
        
    def error(self, msg):
        self.logger.error(msg)
"""

if "class Logger:" not in content:
    content = content.replace("# =====================================================================\n#  RELOJ DE LAMPORT", logger_code + "\n\n# =====================================================================\n#  RELOJ DE LAMPORT")

with open("sensor_telemetry.py", "w", encoding="utf-8") as f:
    f.write(content)

