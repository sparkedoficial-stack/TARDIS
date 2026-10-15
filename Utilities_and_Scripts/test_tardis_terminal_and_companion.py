import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def test_vector_character_in_index_html():
    index_path = PROJECT_ROOT / "index.html"
    assert index_path.exists(), "index.html debe existir"
    content = index_path.read_text(encoding="utf-8")
    assert "renderVectorTriangularCharacter" in content
    assert "backgroundAvatarBounds" in content
    assert "renderVectorTriangularCharacter(ctx, charCenterX, charCenterY, charSize" in content
    assert "renderVectorTriangularCharacter(ctx, W * 0.5, H * 0.52, 102" in content

def test_vector_character_in_companion_overlay():
    overlay_path = PROJECT_ROOT / "companion_overlay.html"
    assert overlay_path.exists(), "companion_overlay.html debe existir"
    content = overlay_path.read_text(encoding="utf-8")
    assert "renderVectorTriangularCharacter" in content
    assert "renderVectorTriangularCharacter(ctx, W * 0.5, H * 0.52, 102" in content

def test_tardis_command_script_exists_and_executable():
    cmd_script = PROJECT_ROOT / "tardis_command.sh"
    assert cmd_script.exists()
    assert os.access(cmd_script, os.X_OK)

def test_tardis_cli_script_exists_and_executable():
    cli_script = PROJECT_ROOT / "tardis_cli.py"
    assert cli_script.exists()
    assert os.access(cli_script, os.X_OK)

def test_global_bin_links():
    local_bin = Path.home() / ".local" / "bin"
    tardis_bin = local_bin / "tardis"
    companion_bin = local_bin / "tardis-companion"
    cli_bin = local_bin / "tardis-cli"

    assert tardis_bin.exists(), "tardis debe existir en ~/.local/bin"
    assert os.access(tardis_bin, os.X_OK), "tardis debe ser ejecutable"

    assert companion_bin.exists(), "tardis-companion debe existir en ~/.local/bin"
    assert os.access(companion_bin, os.X_OK), "tardis-companion debe ser ejecutable"

    assert cli_bin.exists(), "tardis-cli debe existir en ~/.local/bin"
    assert os.access(cli_bin, os.X_OK), "tardis-cli debe ser ejecutable"

def test_cli_help_execution():
    res = subprocess.run(
        [str(Path.home() / ".local" / "bin" / "tardis-cli"), "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    assert res.returncode == 0
    assert "TARDIS Sovereign CLI Interface" in res.stdout
