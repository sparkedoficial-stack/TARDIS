import os
import sys

def generate_blender_script(output_path, concept):
    """
    Genera un script de Python ejecutable en Blender para modelar formas 3D.
    """
    script_content = f"""
import bpy
import math

# Limpiar escena
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# Crear abstracción de concepto: {concept}
# Ejemplo base: Generar un sistema de partículas / geometría abstracta
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=1, location=(0, 0, 0))
sphere = bpy.context.active_object
sphere.name = "Abstract_{concept.replace(' ', '_')}"

# Añadir modificador de desplazamiento para abstracción visual
mod = sphere.modifiers.new(name="Displacement", type='DISPLACE')
tex = bpy.data.textures.new("DisplaceTex", type='CLOUDS')
tex.noise_scale = 0.5
mod.texture = tex
mod.strength = 0.3

# Configurar material
mat = bpy.data.materials.new(name="ScientificMaterial")
mat.use_nodes = True
nodes = mat.node_tree.nodes
principled = nodes.get("Principled BSDF")
principled.inputs['Base Color'].default_value = (0.1, 0.4, 0.8, 1)
principled.inputs['Emission'].default_value = (0.1, 0.2, 0.4, 1)
principled.inputs['Emission Strength'].default_value = 2.0

sphere.data.materials.append(mat)

# Guardar
bpy.ops.wm.save_as_mainfile(filepath="{output_path}.blend")
bpy.ops.export_scene.obj(filepath="{output_path}.obj")
print(f"Modelo exportado en {{'{output_path}'}}")
"""
    script_file = output_path + "_gen.py"
    with open(script_file, "w") as f:
        f.write(script_content)
    return script_file

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "output_model"
    ctx = sys.argv[2] if len(sys.argv) > 2 else "Abstract Geometry"
    generate_blender_script(out, ctx)
