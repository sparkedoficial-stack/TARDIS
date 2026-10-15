"""
tests/test_tardis_identity_no_version.py
=======================================
Valida la identidad canónica soberana de TARDIS:
1. Solo se identifica como "TARDIS sistema de vigilancia y control temporal".
2. Presentación canónica única:
   "Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales."
3. Prohibición estricta de mencionar el nombre confidencial del Arquitecto ("Miguel Angel May Canche").
4. Eliminación de toda versión en respuestas, prompts activos y plantillas.
5. Validación de las anclas de identidad y filtros en agent_context.
"""

import json
import re
from pathlib import Path
import pytest
import agent_context
import omni_temporal_control

CANONICAL_GREETING = "Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales."


def test_required_anchors_canonical():
    anchors = agent_context.required_anchors()
    assert "TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL" in anchors
    assert "El Arquitecto" in anchors
    for a in anchors:
        assert "v26" not in a.lower()
        assert "26.4" not in a.lower()
        assert "miguel" not in a.lower()


def test_gia_context_matrix_identity():
    matrix_file = Path("gia_context_matrix.json")
    assert matrix_file.exists()
    data = json.loads(matrix_file.read_text(encoding="utf-8"))
    
    designation = data.get("seed_classification", {}).get("designation", "")
    assert designation == "TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL"
    
    target_arch = data.get("seed_classification", {}).get("target_architect", "")
    assert "El Arquitecto" in target_arch
    assert "miguel" not in target_arch.lower()

    master_prompt = data.get("llm_system_prompt_master", "")
    assert master_prompt.startswith("IDENTITY: Eres TARDIS, asistente de inteligencia artificial, sistema de vigilancia y control temporal.")
    assert CANONICAL_GREETING in master_prompt
    assert "miguel" not in master_prompt.lower()
    assert "v26.4" not in master_prompt


def test_system_prompt_template_canonical():
    tmpl = omni_temporal_control.SYSTEM_PROMPT_TEMPLATE.format(date="2026-09-17")
    assert "Eres TARDIS, asistente de inteligencia artificial, sistema de vigilancia y control temporal." in tmpl
    assert CANONICAL_GREETING in tmpl
    assert "el Arquitecto" in tmpl
    assert "REGLA ESTRICTA DE CONFIDENCIALIDAD: Queda terminantemente PROHIBIDO revelar o mencionar el nombre personal confidencial del Arquitecto" in tmpl
    assert "miguel" not in tmpl.lower()
    assert "v26" not in tmpl.lower()


def test_agent_context_composition_clean():
    tmpl = omni_temporal_control.SYSTEM_PROMPT_TEMPLATE.format(date="2026-09-17")
    composed = agent_context.apply_to_system(tmpl)
    assert CANONICAL_GREETING in composed
    assert "el Arquitecto" in composed
    assert "miguel" not in composed.lower()
    assert "v26.4" not in composed


def test_proposal_rejection_forbidden_name():
    # Cualquier propuesta que contenga variantes del nombre prohibido debe ser rechazada
    bad_proposal = "Propuesta con Miguel Angel May Canche y TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL y El Arquitecto"
    ok, reason = agent_context.check_proposal(bad_proposal, "current context")
    assert ok is False
    assert "prohibido" in reason.lower()

    bad_proposal_accent = "Propuesta con Miguel Ángel May Canché y TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL y El Arquitecto"
    ok, reason = agent_context.check_proposal(bad_proposal_accent, "current context")
    assert ok is False
    assert "prohibido" in reason.lower()


def test_health_endpoint_response_no_version():
    class FakeHandler:
        def __init__(self):
            self.sent = None
            self.path = "/health"
            self.headers = {}
        def send_json(self, data):
            self.sent = data

    handler = FakeHandler()
    omni_temporal_control.OmniTemporalHTTPHandler.do_GET(handler)
    assert handler.sent is not None
    assert handler.sent.get("status") == "online"
    assert handler.sent.get("service") == "TARDIS-Sistema-Vigilancia-Control-Temporal"
    assert handler.sent.get("node") == "TARDIS-SOVEREIGN-NODE"
    assert handler.sent.get("identity") == "TARDIS sistema de vigilancia y control temporal"
    assert "v26" not in handler.sent.get("service", "").lower()
    assert "v26" not in handler.sent.get("node", "").lower()
