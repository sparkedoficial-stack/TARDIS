"""
tests/test_native_gui.py - Pruebas Unitarias para la Interfaz Nativa de Escritorio
GODWORKS SYSTEM v26.4 (GTK4 + Libadwaita · Sin Navegador)
"""

import os
import subprocess
import sys
from pathlib import Path
import pytest

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from native_gui.app import NativeGiaApplication, NativeGiaWindow

PROJECT_DIR = Path(__file__).resolve().parent.parent


def test_native_gui_environment():
    """Verifica que el entorno de escritorio GTK4 y Libadwaita esté activo y disponible."""
    assert Gtk.get_major_version() >= 4
    assert Adw.get_major_version() >= 1


def test_native_app_window_and_stack():
    """Verifica la construcción de la ventana nativa y la presencia de las 7 pestañas."""
    app = NativeGiaApplication()
    window_created = [False]

    def on_activate(a):
        try:
            win = NativeGiaWindow(application=a)
            assert win is not None
            assert "TARDIS" in win.get_title()

            # Verificar presencia de las 7 vistas soberanas
            expected_views = ["chat", "cognitive", "hardware", "security", "vault", "telemetry", "terminal"]
            for v in expected_views:
                child = win.stack.get_child_by_name(v)
                assert child is not None, f"La vista {v} no está presente en el stack"

            # Verificar componentes clave del Chat
            assert win.chat_input is not None
            assert win.btn_send is not None
            assert win.btn_cancel is not None
            assert win.model_combo is not None

            # Verificar componentes de Hardware
            assert win.scale_volume is not None
            assert win.pic_preview is not None

            # Verificar componentes de Metapensamiento y Bóveda
            assert win.spectrum_area is not None
            assert win.vault_search is not None
            assert win.vault_list is not None

            window_created[0] = True
        finally:
            a.quit()

    app.connect("activate", on_activate)
    app.run([])
    assert window_created[0] is True


def test_native_chat_formatting():
    """Verifica que el formateo de burbujas (Pango Markup) renderice correctamente."""
    app = NativeGiaApplication()
    verified = [False]

    def on_activate(a):
        try:
            win = NativeGiaWindow(application=a)
            # Formatos ricos: negrita, cursiva y código
            lbl_user = win._append_chat_bubble("user", "Pregunta de prueba con **negrita**, __cursiva__ y `código`.")
            assert lbl_user is not None

            lbl_bot = win._append_chat_bubble("assistant", "Respuesta **verificada** con directiva de sintropía.")
            assert lbl_bot is not None

            lbl_sys = win._append_chat_bubble("system", "Aviso del sistema: canal seguro.")
            assert lbl_sys is not None

            verified[0] = True
        finally:
            a.quit()

    app.connect("activate", on_activate)
    app.run([])
    assert verified[0] is True


def test_desktop_launcher_and_scripts():
    """Verifica la existencia, permisos y sintaxis de los lanzadores de escritorio de Tardis."""
    launcher_sh = PROJECT_DIR / "launch_tardis.sh"
    assert launcher_sh.exists()
    assert os.access(launcher_sh, os.X_OK), "launch_tardis.sh debe tener permisos de ejecución"

    desktop_file = Path("/home/timemachine/Escritorio/Tardis.desktop")
    assert desktop_file.exists()
    assert os.access(desktop_file, os.X_OK), "El archivo Tardis.desktop debe tener permisos de ejecución"

    content = desktop_file.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "launch_tardis.sh" in content
    assert "tardis-icon.png" in content
    assert "Name=Tardis" in content

    # Verificar que los archivos obsoletos fueron eliminados
    assert not Path("/home/timemachine/Escritorio/GIA_SISTEMA_NATIVO.desktop").exists()
    assert not Path("/home/timemachine/Escritorio/gia_direct.desktop").exists()
    assert not Path("/home/timemachine/Escritorio/godworks.desktop").exists()

    # Verificar existencia del icono maestro
    assert (PROJECT_DIR / "tardis-icon.png").exists()


def test_standalone_shell_script():
    """Verifica la sintaxis del script nativo standalone WebKitGTK y de tardis_app.py."""
    tardis_app = PROJECT_DIR / "tardis_app.py"
    assert tardis_app.exists()
    assert os.access(tardis_app, os.X_OK)

    res_tardis = subprocess.run([sys.executable, "-m", "py_compile", str(tardis_app)], capture_output=True, text=True)
    assert res_tardis.returncode == 0, f"Error de sintaxis en tardis_app.py: {res_tardis.stderr}"

    shell_py = PROJECT_DIR / "native_gui" / "gia_standalone_shell.py"
    assert shell_py.exists()
    assert os.access(shell_py, os.X_OK)

    # Validar compilación de sintaxis Python
    res = subprocess.run([sys.executable, "-m", "py_compile", str(shell_py)], capture_output=True, text=True)
    assert res.returncode == 0, f"Error de sintaxis en gia_standalone_shell.py: {res.stderr}"
