"""
Test Suite: FTL Mascot TON 618 & Relativistic Terminal Animation
================================================================
Verifies that TON 618 rendering, animation frames, status messages,
mascot badges, and UI integrations function correctly and without errors.
"""

import sys
from pathlib import Path

# Add ~/.ftl to path
FTL_DIR = Path(__file__).parent
sys.path.insert(0, str(FTL_DIR))

import ton618
import ui


def test_render_ton618_frame_standard():
    """Verify that render_ton618_frame generates standard frames properly."""
    lines = ton618.render_ton618_frame(t=0.0, width=68, height=13, compact=False)
    assert len(lines) == 13
    # Check that center label TON 618 is present
    full_text = "\n".join(lines)
    assert "TON 618" in full_text


def test_render_ton618_frame_compact():
    """Verify that compact mode renders within smaller constraints."""
    lines = ton618.render_ton618_frame(t=1.5, width=48, height=9, compact=True)
    assert len(lines) == 9
    full_text = "\n".join(lines)
    assert "TON 618" in full_text


def test_get_ton618_status_bar():
    """Verify narrative status bar progression across animation phases."""
    s_early = ton618.get_ton618_status_bar(0, 10, width=68)
    assert "COLAPSO GRAVITACIONAL" in s_early or "SINGULARIDAD" in s_early

    s_mid = ton618.get_ton618_status_bar(5, 10, width=68)
    assert "DISCO DE ACRECIÓN" in s_mid or "JETS POLARES" in s_mid

    s_late = ton618.get_ton618_status_bar(9, 10, width=68)
    assert "MASCOTA SOBERANA TON 618" in s_late or "VELOCIDAD" in s_late


def test_get_ton618_badge_card():
    """Verify the mascot badge panel contents and metrics."""
    badge = ton618.get_ton618_badge_card(width=68)
    assert "TON 618" in badge
    assert "66 Mil Millones M☉" in badge
    assert "MASCOTA" in badge


def test_get_ton618_art():
    """Verify that get_ton618_art generates full static representation."""
    art = ton618.get_ton618_art()
    assert "TON 618" in art
    assert "MASCOTA" in art


def test_play_ton618_animation_execution():
    """Verify that animation loop runs cleanly without raising any exceptions."""
    # Run with small frame count and minimal delay
    ton618.play_ton618_animation(frames=2, delay=0.001, force=True)


def test_ui_integration():
    """Verify UI commands, banner art, and method integration."""
    assert ":ton618" in ui.COMMANDS
    assert ":mascot" in ui.COMMANDS
    assert "TON 618" in ui.BANNER_ART
    test_ui = ui.FTLInterface()
    assert hasattr(test_ui, "play_ton618")


if __name__ == "__main__":
    test_render_ton618_frame_standard()
    test_render_ton618_frame_compact()
    test_get_ton618_status_bar()
    test_get_ton618_badge_card()
    test_get_ton618_art()
    test_play_ton618_animation_execution()
    test_ui_integration()
    print("ALL TON 618 MASCOT TESTS PASSED!")
