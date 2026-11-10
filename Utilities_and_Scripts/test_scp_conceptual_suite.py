import json
from pathlib import Path
import struct
import zlib

import pytest

from core.scp_conceptual_suite import (
    BABEL_PAGE_LEN,
    DEFAULT_UNIVERSE_CODE,
    SCPConceptualSuite,
    main as scp_cli_main,
)


def _make_tiny_png(width: int = 16, height: int = 12) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = (
        struct.pack(">I", len(ihdr_data))
        + b"IHDR"
        + ihdr_data
        + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    )
    raw_scanlines = b"".join(b"\x00" + (b"\x10\x40\x90" * width) for _ in range(height))
    idat_data = zlib.compress(raw_scanlines)
    idat = (
        struct.pack(">I", len(idat_data))
        + b"IDAT"
        + idat_data
        + struct.pack(">I", zlib.crc32(b"IDAT" + idat_data) & 0xFFFFFFFF)
    )
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    return sig + ihdr + idat + iend


@pytest.fixture()
def isolated_suite(tmp_path: Path) -> SCPConceptualSuite:
    return SCPConceptualSuite(
        db_path=tmp_path / "test_scp.db",
        creations_dir=tmp_path / "creations",
    )


def test_scp001_babel_bijection_roundtrip(isolated_suite: SCPConceptualSuite) -> None:
    text = "la biblioteca infinita contiene cada página posible en español: áéíóúüñ 12345!"
    located = isolated_suite.library.locate_text(text)
    assert located["page_length"] == BABEL_PAGE_LEN
    assert located["address"].startswith("HEX-")

    read_back = isolated_suite.library.read_address(located["address"])
    assert read_back["trimmed_text"] == text

    # Un cambio de un solo carácter debe producir otra coordenada completamente distinta
    located_b = isolated_suite.library.locate_text(text[:-1] + "?")
    assert located_b["address"] != located["address"]
    assert isolated_suite.library.read_address(located_b["address"])["trimmed_text"] == text[:-1] + "?"


def test_scp002_branching_time_machine_lineage(isolated_suite: SCPConceptualSuite) -> None:
    b1 = isolated_suite.time_machine.jump_and_branch("2026-11-08", "Rama alfa")
    b2 = isolated_suite.time_machine.jump_and_branch(
        "2026-11-08",
        "Rama beta derivada",
        parent_branch_id=b1["new_branch_id"],
    )
    lineage = isolated_suite.ledger.trace_lineage(b2["new_branch_id"])
    assert len(lineage) == 3
    assert lineage[0]["branch_id"] == isolated_suite.ledger.MAINLINE_ID
    assert lineage[1]["branch_id"] == b1["new_branch_id"]
    assert lineage[2]["branch_id"] == b2["new_branch_id"]


def test_scp003_universe_single_digit_mutation(isolated_suite: SCPConceptualSuite) -> None:
    result = isolated_suite.universe.mutate_single_digit(
        base_code=DEFAULT_UNIVERSE_CODE,
        digit_index=0,
        new_digit="9",
    )
    assert result["divergence"]["mutated_position"] == 0
    assert result["divergence"]["hamming_spacetime_divergence"] > 0.0
    assert result["base_universe"]["spacetime_digest"] != result["mutated_universe"]["spacetime_digest"]

    with pytest.raises(ValueError):
        isolated_suite.universe.validate_code("12345")


def test_scp004_truth_camera_magic_mismatch_and_dimensions(
    isolated_suite: SCPConceptualSuite,
    tmp_path: Path,
) -> None:
    png_bytes = _make_tiny_png(24, 18)
    real_png = tmp_path / "sample.png"
    real_png.write_bytes(png_bytes)

    res_ok = isolated_suite.truth_camera.inspect(real_png)
    rep_ok = res_ok["verification_report"]
    assert rep_ok["detected_mime"] == "image/png"
    assert rep_ok["extension_matches_magic_header"] is True
    assert rep_ok["image_dimensions"] == {"width": 24, "height": 18}

    disguised_file = tmp_path / "disguised.txt"
    disguised_file.write_bytes(png_bytes)
    res_mismatch = isolated_suite.truth_camera.inspect(disguised_file)
    assert res_mismatch["verification_report"]["detected_mime"] == "image/png"
    assert res_mismatch["verification_report"]["extension_matches_magic_header"] is False


def test_scp005_procedural_creation_and_full_demo(isolated_suite: SCPConceptualSuite) -> None:
    created = isolated_suite.creator.create(
        concept_name="Cronómetro Topológico",
        category="artifact",
        attributes={"precision": "1e-9"},
    )
    json_file = Path(created["files"]["json_blueprint"])
    svg_file = Path(created["files"]["svg_geometry"])
    assert json_file.is_file()
    assert svg_file.is_file()
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["timeline_branch_id"] == created["branch_id"]
    assert "<svg" in svg_file.read_text(encoding="utf-8")

    demo = isolated_suite.run_full_demonstration()
    assert demo["scp_001_library"]["exact_roundtrip_verified"] is True
    assert len(demo["lineage_chain"]) == 5


def test_cli_status_runs_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    rc = scp_cli_main(["mapping"])
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert len(parsed) == 5
