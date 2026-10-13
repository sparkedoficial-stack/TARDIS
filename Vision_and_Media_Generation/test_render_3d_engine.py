"""
tests/test_render_3d_engine.py - Suite de Pruebas del Motor 3D Soberano
======================================================================
Valida la generación de mallas procedurales, proyecciones 3D y renderizado
a imagen PNG de alta resolución para demostración, enseñanza y exploración.
"""

import pytest
from core.render_3d_engine import Render3DEngine, Mesh3D, get_render_3d_engine


class TestRender3DEngine:
    def setup_method(self):
        self.engine = get_render_3d_engine()

    def test_catalog_presets_available(self):
        """Verifica que los modelos pedagógicos y científicos estén cargados."""
        catalog = self.engine.get_catalog_summary()
        ids = [m["id"] for m in catalog]
        assert "dna" in ids
        assert "atom" in ids
        assert "torus" in ids
        assert "tesseract" in ids
        assert "mobius" in ids
        assert "icosahedron" in ids
        assert "saddle" in ids
        assert len(catalog) >= 10

    def test_dna_helix_structure(self):
        """La doble hélice de ADN debe contener vértices y pares de bases simétricos."""
        mesh = self.engine.get_mesh("dna")
        assert mesh is not None
        assert mesh.title == "Doble Hélice de ADN"
        assert len(mesh.vertices) == 72
        assert len(mesh.faces) > 0
        assert len(mesh.edges) > 0

    def test_bohr_atom_structure(self):
        """El átomo de Bohr debe contener núcleo y orbitales inclinados."""
        mesh = self.engine.get_mesh("atom")
        assert mesh is not None
        assert "Átomo de Bohr" in mesh.title
        assert len(mesh.vertices) > 50
        assert len(mesh.faces) >= 20

    def test_platonic_solids_geometry(self):
        """Comprueba que los sólidos platónicos tengan el número exacto de vértices."""
        ico = self.engine.get_mesh("icosahedron")
        assert len(ico.vertices) == 12
        assert len(ico.faces) == 20

        cube = self.engine.get_mesh("cube")
        assert len(cube.vertices) == 8
        assert len(cube.faces) == 6

        octa = self.engine.get_mesh("octahedron")
        assert len(octa.vertices) == 6
        assert len(octa.faces) == 8

    def test_render_to_png_bytes(self):
        """El renderizador debe generar bytes de imagen PNG válidos."""
        mesh = self.engine.get_mesh("torus")
        assert mesh is not None
        png_bytes = self.engine.render_to_png_bytes(mesh, width=320, height=240, style="hologram")
        assert len(png_bytes) > 1000
        # Firma mágica de archivo PNG: \x89PNG\r\n\x1a\n
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    def test_custom_mesh_creation(self):
        """Debe permitir sintetizar mallas 3D arbitrarias a partir de JSON."""
        spec = {
            "name": "tetra_custom",
            "title": "Tetraedro Personalizado",
            "vertices": [[0, 0, 1], [1, 0, -0.5], [-0.5, 0.86, -0.5], [-0.5, -0.86, -0.5]],
            "faces": [[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]]
        }
        mesh = self.engine.create_custom_mesh(spec)
        assert mesh.name == "tetra_custom"
        assert len(mesh.vertices) == 4
        assert len(mesh.faces) == 4
        assert len(mesh.edges) == 6

        png_bytes = self.engine.render_to_png_bytes(mesh, width=200, height=200, style="wireframe")
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    def test_alias_resolution(self):
        """Comprueba que los nombres en español e inglés resuelvan al mismo modelo."""
        assert self.engine.get_mesh("adn") == self.engine.get_mesh("dna")
        assert self.engine.get_mesh("átomo") == self.engine.get_mesh("atom")
        assert self.engine.get_mesh("toroide") == self.engine.get_mesh("torus")
        assert self.engine.get_mesh("hipercubo") == self.engine.get_mesh("tesseract")

    def test_render_hd_scaling(self):
        """Comprueba que el renderizador en Alta Definición (1920x1440 HD) escale correctamente."""
        mesh = self.engine.get_mesh("dna")
        assert mesh is not None
        img_hd = self.engine.render_mesh_to_image(mesh, width=1920, height=1440, style="hologram")
        assert img_hd.size == (1920, 1440)
        png_hd = self.engine.render_to_png_bytes(mesh, width=1920, height=1440, style="hologram")
        assert png_hd.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(png_hd) > 30000

