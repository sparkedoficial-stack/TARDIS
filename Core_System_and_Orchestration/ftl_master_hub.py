import os
import sys
import importlib.util
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class MasterHub:
    """
    Centro principal de control donde se registran y gestionan los módulos.
    Accesible tanto para el sistema autónomo como para el usuario.
    """
    def __init__(self):
        self.modules = {}

    def register_module(self, name, module_instance):
        self.modules[name] = module_instance
        logging.info(f"Módulo '{name}' registrado exitosamente en el Master Hub.")

    def list_modules(self):
        return list(self.modules.keys())

    def get_module(self, name):
        return self.modules.get(name)

    def execute_module(self, name, *args, **kwargs):
        if name in self.modules:
            logging.info(f"Ejecutando módulo: {name}")
            # Se espera que cada módulo implemente un método 'run' o 'execute'
            mod = self.modules[name]
            if hasattr(mod, 'run'):
                return mod.run(*args, **kwargs)
            elif hasattr(mod, 'execute'):
                return mod.execute(*args, **kwargs)
            else:
                logging.error(f"El módulo '{name}' no tiene un método 'run' o 'execute'.")
        else:
            logging.error(f"Módulo '{name}' no encontrado.")
            return None


class SistemaAdaptacionTecnologica:
    """
    Sistema encargado de investigar, generar, autodescubrir y adaptar nuevos módulos 
    (tecnología FTL) de forma autónoma.
    """
    def __init__(self, hub: MasterHub, modules_dir="modulos_ftl"):
        self.hub = hub
        self.modules_dir = modules_dir
        os.makedirs(self.modules_dir, exist_ok=True)

    def generate_and_load_module(self, module_name, code_content, class_name=None):
        """
        Crea físicamente el archivo del módulo, lo carga en tiempo de ejecución 
        y lo integra al Master Hub.
        """
        filepath = os.path.join(self.modules_dir, f"{module_name}.py")
        
        # Guardar el código fuente del módulo generado autónomamente
        with open(filepath, "w") as f:
            f.write(code_content)
        logging.info(f"Módulo '{module_name}' creado en disco: {filepath}")
        return self.load_module_from_file(filepath, module_name, class_name)

    def load_module_from_file(self, filepath: str, module_name: str = None, class_name: str = None):
        """Carga dinámicamente un módulo existente en disco e instanciarlo."""
        if not module_name:
            module_name = os.path.splitext(os.path.basename(filepath))[0]
        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if not spec or not spec.loader:
                return False
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 1. Probar con clase específica si se provee
            if class_name and hasattr(module, class_name):
                cls = getattr(module, class_name)
                self.hub.register_module(module_name, cls())
                return True

            # 2. Probar con nombre inferido (CamelCase)
            inferred = "".join(word.capitalize() for word in module_name.split("_"))
            if hasattr(module, inferred):
                cls = getattr(module, inferred)
                self.hub.register_module(module_name, cls())
                return True

            # 3. Buscar cualquier clase en el módulo con método 'run' o 'execute'
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and attr.__module__ == module_name:
                    if hasattr(attr, "run") or hasattr(attr, "execute"):
                        self.hub.register_module(module_name, attr())
                        return True

            # 4. Si hay una función run o execute a nivel de módulo
            if hasattr(module, "run") or hasattr(module, "execute"):
                class FunctionWrapper:
                    def __init__(self, mod):
                        self.fn = getattr(mod, "run", getattr(mod, "execute", None))
                    def run(self, *args, **kwargs):
                        return self.fn(*args, **kwargs)
                self.hub.register_module(module_name, FunctionWrapper(module))
                return True

            logging.warning(f"No se detectó punto de entrada ejecutable en '{module_name}'.")
            return False
        except Exception as e:
            logging.error(f"Fallo al cargar módulo '{module_name}': {e}")
            return False

    def autoload_all_modules(self):
        """Descubre y carga automáticamente todos los módulos de modulos_ftl/."""
        loaded = []
        if os.path.exists(self.modules_dir):
            for fname in sorted(os.listdir(self.modules_dir)):
                if fname.endswith(".py") and not fname.startswith("__"):
                    mod_name = os.path.splitext(fname)[0]
                    fpath = os.path.join(self.modules_dir, fname)
                    if self.load_module_from_file(fpath, mod_name):
                        loaded.append(mod_name)
        logging.info(f"Autocarga FTL completada: {len(loaded)} módulos registrados.")
        return loaded


def initialize_sovereign_master_hub() -> MasterHub:
    """Inicializa el Master Hub soberano con todos los subsistemas y sinergia híbrida."""
    hub = MasterHub()
    sistema_adaptacion = SistemaAdaptacionTecnologica(hub)
    sistema_adaptacion.autoload_all_modules()

    # Integración con la Matriz de Sinergia Híbrida de Modelos e Ingenierías
    try:
        sys_path = "/home/timemachine/Escritorio/GODWORKS SYSTEM"
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from core.tardis_hybrid_synergy import get_tardis_hybrid_synergy
        synergy = get_tardis_hybrid_synergy()
        class HybridSynergyModule:
            def __init__(self, syn):
                self.syn = syn
            def run(self, action="matrix", prompt="", env="cockpit_web"):
                if action == "evaluate":
                    return self.syn.evaluate_optimal_combination(prompt, target_environment=env)
                return self.syn.get_full_matrix()
        hub.register_module("matriz_sinergia_hibrida", HybridSynergyModule(synergy))
    except Exception as e_syn:
        logging.warning(f"Aviso al vincular Matriz de Sinergia Híbrida: {e_syn}")

    return hub


get_master_hub = initialize_sovereign_master_hub


if __name__ == "__main__":
    print("=== TARDIS FTL MASTER HUB :: INICIALIZACIÓN SOBERANA ===")
    master_hub = initialize_sovereign_master_hub()
    
    print("\n--- Estado del Master Hub ---")
    modulos = master_hub.list_modules()
    print(f"Total Módulos Disponibles: {len(modulos)}")
    for m in modulos:
        print(f"  • {m}")
    
    print("\n--- Verificación de Sinergia Híbrida ---")
    res_syn = master_hub.execute_module("matriz_sinergia_hibrida")
    if res_syn:
        print(f"Modelos Activos: {res_syn.get('models_count')}, Ingenierías: {res_syn.get('engineering_layers_count')}")
