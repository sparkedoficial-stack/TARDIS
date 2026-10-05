"""
tests/test_cognitive_adaptability.py - Validación de los 7 Pilares de Adaptabilidad Universal
=============================================================================================
Suite de pruebas para verificar:
1. Adaptabilidad de Idioma y Moduladores Cognitivos (agent_context.py).
2. Sanitización activa de PII y trazabilidad (agent_safety.py).
3. Abstracción y capacidades de hardware/software (core/os_controller.py).
4. Endpoints y contratos API extendidos (server/api.py).
"""
import json
import pytest
from starlette.testclient import TestClient
import agent_context
import agent_safety
from core.os_controller import get_os_controller
from server.api import app

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "Imznu9ZNtdbFl2ebIGSzpYqe7A3OS4Y5"}


class TestPIISanitization:
    """Pruebas del Pilar 7: Seguridad, Soberanía y Sanitización de PII."""

    def test_sanitize_bearer_token(self):
        raw = "Authorization: Bearer Imznu9ZNtdbFl2ebIGSzpYqe7A3OS4Y5"
        clean = agent_safety.sanitize_pii(raw)
        assert "Imznu9ZNtdbFl2ebIGSzpYqe7A3OS4Y5" not in clean
        assert "Bearer [REDACTED_TOKEN]" in clean

    def test_sanitize_jwt(self):
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozG4m1e_pQ"
        raw = f"Header: {jwt_token}"
        clean = agent_safety.sanitize_pii(raw)
        assert jwt_token not in clean
        assert "[REDACTED_JWT]" in clean

    def test_sanitize_password_and_key(self):
        raw = 'config: api_key = "REDACTED" password: SuperSecretPassword123'
        clean = agent_safety.sanitize_pii(raw)
        assert "sk-live-9999888877776666" not in clean
        assert "SuperSecretPassword123" not in clean
        assert '[REDACTED_SECRET]' in clean

    def test_sanitize_credit_card(self):
        raw = "Payment card: 4532 1234 5678 9012"
        clean = agent_safety.sanitize_pii(raw)
        assert "4532 1234 5678 9012" not in clean
        assert "[REDACTED_CC]" in clean

    def test_sanitize_private_key(self):
        raw = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0m...\n-----END RSA PRIVATE KEY-----"
        clean = agent_safety.sanitize_pii(raw)
        assert "MIIEowIBAAKCAQEA0m" not in clean
        assert "[REDACTED_PRIVATE_KEY]" in clean

    def test_audit_logs_sanitized(self, tmp_path, monkeypatch):
        test_log = tmp_path / "test_audit.log"
        monkeypatch.setattr(agent_safety, "AUDIT_LOG", test_log)
        agent_safety.audit("test_action", "User password: MySecret123 Bearer abcdef1234567890")
        assert test_log.exists()
        content = test_log.read_text(encoding="utf-8")
        assert "MySecret123" not in content
        assert "abcdef1234567890" not in content
        assert "[REDACTED_SECRET]" in content or "[REDACTED_TOKEN]" in content


class TestCognitiveDirectivesAndModifiers:
    """Pruebas de los Pilares 1, 2, 3 y 6: Adaptabilidad de Idioma, Pedagogía, Dialéctica y Afecto."""

    def test_language_modifier(self):
        prompt = agent_context.apply_to_system("System Prompt Base", detected_lang="Français")
        assert "[MODULADOR DE IDIOMA]" in prompt
        assert "Français" in prompt
        assert "System Prompt Base" in prompt

    def test_pedagogical_levels(self):
        # Intuitivo
        prompt_i = agent_context.apply_to_system("Base", pedagogical_level="intuitive")
        assert "[MODULADOR PEDAGÓGICO - NIVEL INTUITIVO]" in prompt_i

        # Ingeniería
        prompt_e = agent_context.apply_to_system("Base", pedagogical_level="engineering")
        assert "[MODULADOR PEDAGÓGICO - INGENIERÍA DE SISTEMAS]" in prompt_e

        # Formal
        prompt_f = agent_context.apply_to_system("Base", pedagogical_level="formal")
        assert "[MODULADOR PEDAGÓGICO - RIGOR MATEMÁTICO FORMAL]" in prompt_f

    def test_dialectic_roles(self):
        # Mediador
        prompt_m = agent_context.apply_to_system("Base", dialectic_role="mediator")
        assert "[ROL DIALÉCTICO - MEDIADOR]" in prompt_m

        # Árbitro
        prompt_a = agent_context.apply_to_system("Base", dialectic_role="arbitrator")
        assert "[ROL DIALÉCTICO - ÁRBITRO]" in prompt_a

        # Conciliador
        prompt_c = agent_context.apply_to_system("Base", dialectic_role="conciliator")
        assert "[ROL DIALÉCTICO - CONCILIADOR]" in prompt_c

    def test_affective_state_injection(self):
        affective = {
            "primary": "focused",
            "mood_state": "analytical",
            "gaze": "direct",
            "confidence": 0.95
        }
        prompt = agent_context.apply_to_system("Base", affective_state=affective)
        assert "[COMPUTACIÓN AFECTIVA EN VIVO]" in prompt
        assert "Emoción primaria: focused" in prompt
        assert "Estado de ánimo: analytical" in prompt

    def test_compose_with_attachments_forwards_modifiers(self):
        attachments = [{"name": "doc.txt", "content": "Sample content", "type": "text"}]
        prompt = agent_context.compose_with_attachments(
            "Base",
            attachments=attachments,
            detected_lang="Deutsch",
            pedagogical_level="formal",
            dialectic_role="arbitrator"
        )
        assert "[DOCUMENTO ADJUNTO EN CONTEXTO: doc.txt" in prompt
        assert "Deutsch" in prompt
        assert "[MODULADOR PEDAGÓGICO - RIGOR MATEMÁTICO FORMAL]" in prompt
        assert "[ROL DIALÉCTICO - ÁRBITRO]" in prompt

    def test_identity_anchors_and_proposal_check(self):
        anchors = agent_context.required_anchors()
        assert "GIA-V26-COGNITIVE-ALIGNMENT-MATRIX" in anchors
        assert "Miguel Angel May Canche" in anchors
        assert "GIA-V26-ARCHITECT-777" in anchors

        valid_proposal = (
            "[GIA-V26-COGNITIVE-ALIGNMENT-MATRIX] Identidad: GIA-V26-ARCHITECT-777. "
            "Arquitecto: Miguel Angel May Canche. Directivas soberanas actualizadas "
            + ("X" * 1500)
        )
        ok, reason = agent_context.check_proposal(valid_proposal, current=valid_proposal[:1200])
        assert ok, f"check_proposal falló: {reason}"


class TestHardwareSoftwareCapabilities:
    """Pruebas del Pilar 4: Abstracción de Hardware y Software."""

    def test_platform_capabilities_structure(self):
        ctrl = get_os_controller()
        caps = ctrl.get_platform_capabilities()
        assert "platform" in caps
        assert "os_name" in caps
        assert "system_architecture" in caps
        assert "subsystems" in caps
        assert "supported_environments" in caps
        assert "accelerators" in caps
        assert isinstance(caps["subsystems"], dict)
        assert "linux_x86_64" in caps["supported_environments"]

    def test_api_capabilities_endpoint(self):
        resp = client.get("/api/system/capabilities", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "capabilities" in data
        assert data["capabilities"]["platform"] is not None

        # Ruta alias
        resp_alias = client.get("/api/os/capabilities", headers=AUTH_HEADERS)
        assert resp_alias.status_code == 200
        assert resp_alias.json()["ok"] is True


class TestAPICognitiveContract:
    """Pruebas de validación de esquemas y chat con moduladores cognitivos."""

    def test_chat_endpoint_schema_acceptance(self):
        payload = {
            "message": "Hola sistema",
            "language": "English",
            "pedagogical_level": "intuitive",
            "dialectic_role": "mediator",
            "affective_state": {
                "primary": "curious",
                "mood_state": "engaged",
                "confidence": 0.88
            }
        }
        resp = client.post("/api/chat", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code != 422, f"Error de validación Pydantic: {resp.text}"


class TestCortanaVoice:
    """Pruebas del motor de voz de Cortana (TTS)."""

    def test_cortana_voice_list(self):
        import voice
        voices = voice.list_voices()
        assert len(voices) > 0
        default_v = next(v for v in voices if v.get("is_default"))
        assert "cortana" in default_v["name"].lower() or "dalia" in default_v["id"].lower()

    def test_cortana_config(self):
        import voice
        cfg = voice.get_config()
        assert cfg["ok"] is True
        assert cfg["cortana_active"] is True
        assert "dalia" in cfg["pref_voice"].lower()

    def test_voice_endpoints(self):
        resp_voices = client.get("/api/voice/voices")
        assert resp_voices.status_code == 200
        data = resp_voices.json()
        assert data["ok"] is True
        assert any("cortana" in v["name"].lower() for v in data["voices"])

        resp_audio = client.get("/api/voice/tts_audio?text=Prueba+de+voz+de+Cortana")
        assert resp_audio.status_code == 200
        assert resp_audio.headers["content-type"].startswith("audio/")
        assert len(resp_audio.content) > 1000
