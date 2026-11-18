"""
tests/test_voice_program.py - Comando de voz «programa» multi-micrófono
=======================================================================
Verifica que TARDIS detecte la orden «programa» en cualquier transcripción,
extraiga el objetivo dictado y despache la creación de la función a FTL.
"""

import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tardis_voice_program import (
    ProgramJob,
    VoiceProgramRouter,
    is_program_command,
    parse_program_command,
)


@pytest.fixture(autouse=True)
def _isolated_event_log(tmp_path, monkeypatch):
    """Los tests no deben contaminar la auditoría real de órdenes de voz."""
    monkeypatch.setattr(
        "core.tardis_voice_program.EVENT_LOG",
        tmp_path / "voice_program_commands.jsonl",
    )


def test_parse_basic_command():
    command = parse_program_command("programa una función que revise el correo")
    assert command is not None
    assert command.command_token == "programa"
    assert command.goal == "que revise el correo"
    assert command.has_goal is True


def test_parse_with_wake_and_accent():
    command = parse_program_command("TARDIS, estás ahí, programá la función de ordenar descargas")
    assert command is not None
    assert command.goal == "de ordenar descargas"
    assert command.prefix.lower().startswith("tardis")


def test_parse_programame_and_filler():
    command = parse_program_command("programame un script para respaldar documentos")
    assert command is not None
    assert command.command_token == "programame"
    assert command.goal == "para respaldar documentos"


def test_parse_stt_typo():
    command = parse_program_command("progama una funcion que avise cuando llegue alguien")
    assert command is not None
    assert command.approximate is True
    assert command.goal == "que avise cuando llegue alguien"


def test_parse_without_goal_opens_dialogue():
    command = parse_program_command("programa")
    assert command is not None
    assert command.goal == ""


def test_parse_courtesy_does_not_become_the_goal():
    assert parse_program_command("programa, por favor").goal == ""
    command = parse_program_command(
        "programa, por favor, una función que ordene las descargas"
    )
    assert command is not None
    assert command.goal == "que ordene las descargas"
    command = parse_program_command(
        "programa una función que cuente palabras, por favor"
    )
    assert command is not None
    assert command.goal == "que cuente palabras"


def test_never_confuse_nouns_or_questions():
    for text in (
        "programas de televisión",
        "que programa es ese",
        "quiero programar algo",
        "la función programa no sirve",
        "programación de tareas",
    ):
        assert parse_program_command(text) is None, text
        assert is_program_command(text) is False


def test_handle_non_command_returns_none():
    router = VoiceProgramRouter()
    assert router.handle("hola, ¿cómo estás?", channel="test") is None


def test_handle_empty_goal_asks_for_description():
    router = VoiceProgramRouter()
    result = router.handle("programa", channel="test")
    assert result is not None
    assert result["handled"] is True
    assert result["dispatched"] is False
    assert "qué función" in result["reply"].lower()


def test_handle_dispatches_to_worker(monkeypatch):
    router = VoiceProgramRouter()
    captured = {}

    def fake_process(job):
        captured["job"] = job
        job.status = "completed"
        job.engine = "FTL"
        job.finished_at = time.time()

    monkeypatch.setattr(router, "_process_job", fake_process)

    result = router.handle(
        "programa una función que cuente palabras",
        channel="unit_test_mic",
        source="micrófono de prueba",
        chat_id=None,
    )
    assert result is not None
    assert result["dispatched"] is True
    assert "FTL" in result["reply"]
    assert result["goal"] == "que cuente palabras"

    deadline = time.time() + 5
    while "job" not in captured and time.time() < deadline:
        time.sleep(0.05)
    assert captured.get("job") is not None
    assert captured["job"].goal == "que cuente palabras"
    assert captured["job"].channel == "unit_test_mic"


def test_autofunc_parser_reads_ftl_output(monkeypatch):
    router = VoiceProgramRouter()
    job = ProgramJob(
        job_id="vprog_test",
        goal="sumar dos números",
        raw_text="programa sumar dos números",
        channel="unit_test",
        source="micrófono de prueba",
    )
    sample = (
        "\x1b[1m✔ Herramienta dinámica sintetizada con éxito en 12.5s:\x1b[0m\n"
        "  • Módulo:    sumar_dos_numeros_1234 (Clase: SumarDosNumeros1234)\n"
        "  • Archivo:   /home/m11/modulos_ftl/sumar_dos_numeros_1234.py\n"
        "  • Test Run:  {'status': 'ok', 'result': 7}\n"
    )

    class _Result:
        returncode = 0
        stdout = sample

    monkeypatch.setattr(
        "core.tardis_voice_program.subprocess.run",
        lambda *args, **kwargs: _Result(),
    )
    res = router._run_ftl_autofunc(job)
    assert res["ok"] is True
    assert res["module_name"] == "sumar_dos_numeros_1234"
    assert res["file_path"].endswith("sumar_dos_numeros_1234.py")
    assert res["files_changed"] == ["/home/m11/modulos_ftl/sumar_dos_numeros_1234.py"]


def test_autofunc_parser_detects_failure(monkeypatch):
    router = VoiceProgramRouter()
    job = ProgramJob(
        job_id="vprog_test_fail",
        goal="meta imposible",
        raw_text="programa meta imposible",
        channel="unit_test",
        source="micrófono de prueba",
    )

    class _Result:
        returncode = 0
        stdout = "✖ Error sintetizando herramienta: no se pudo generar código"

    monkeypatch.setattr(
        "core.tardis_voice_program.subprocess.run",
        lambda *args, **kwargs: _Result(),
    )
    res = router._run_ftl_autofunc(job)
    assert res["ok"] is False
    assert "error" in res
