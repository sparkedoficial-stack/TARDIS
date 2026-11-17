"""
tests/test_aegis.py — Pruebas del sistema de blindaje AEGIS-Ω.
==============================================================
Cubre criptografía autenticada, detección de manipulación, cadena de
custodia, clasificación, política de permisos, antiforense y bóveda.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from core.aegis.classifier import Severity, classify_path, scan_text
from core.aegis.crypto import (
    AegisCryptoError,
    Keyring,
    decrypt_bytes,
    decrypt_file,
    encrypt_bytes,
    encrypt_file,
)
from core.aegis.engine import AegisEngine
from core.aegis.ledger import IntegrityLedger
from core.aegis.policy import PolicyAuditor
from core.aegis.antiforensic import shred_file


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    h = tmp_path / "aegis"
    h.mkdir()
    return h


@pytest.fixture()
def keyring(home: Path) -> Keyring:
    return Keyring(home)


class TestCrypto:
    def test_master_key_created_0400(self, keyring: Keyring) -> None:
        keyring.ensure()
        mode = keyring.master_path.stat().st_mode & 0o777
        assert mode == 0o400
        assert len(keyring.load()) == 32
        assert keyring.fingerprint() == keyring.fingerprint()

    def test_roundtrip_small(self, keyring: Keyring) -> None:
        payload = b"informacion clasificada C4" * 10
        blob = encrypt_bytes(payload, keyring)
        assert blob.startswith(b"AGS1")
        assert payload not in blob
        assert decrypt_bytes(blob, keyring) == payload

    def test_roundtrip_empty(self, keyring: Keyring) -> None:
        blob = encrypt_bytes(b"", keyring)
        assert decrypt_bytes(blob, keyring) == b""

    def test_roundtrip_chunked_file(self, keyring: Keyring, tmp_path: Path) -> None:
        src = tmp_path / "big.bin"
        payload = os.urandom(9000)
        src.write_bytes(payload)
        dst = tmp_path / "big.bin.aegis"
        meta = encrypt_file(src, dst, keyring, chunk_size=4096)
        assert meta.size == len(payload)
        out = tmp_path / "big.out"
        decrypt_file(dst, out, keyring)
        assert out.read_bytes() == payload

    def test_tamper_detected(self, keyring: Keyring) -> None:
        blob = bytearray(encrypt_bytes(b"dato critico", keyring))
        blob[-20] ^= 0xFF
        with pytest.raises(AegisCryptoError):
            decrypt_bytes(bytes(blob), keyring)

    def test_truncation_detected(self, keyring: Keyring) -> None:
        blob = encrypt_bytes(b"x" * 5000, keyring)
        with pytest.raises(AegisCryptoError):
            decrypt_bytes(blob[:-8], keyring)

    def test_wrong_key_fails(self, home: Path, keyring: Keyring, tmp_path: Path) -> None:
        blob = encrypt_bytes(b"secreto", keyring)
        other = Keyring(tmp_path / "other")
        with pytest.raises(AegisCryptoError):
            decrypt_bytes(blob, other)

    def test_passphrase_wrap(self, keyring: Keyring) -> None:
        master = keyring.ensure()
        keyring.wrap_with_passphrase("passphrase-militar-2026")
        assert keyring.unwrap_with_passphrase("passphrase-militar-2026") == master
        with pytest.raises(AegisCryptoError):
            keyring.unwrap_with_passphrase("incorrecta")


class TestLedger:
    def test_chain_and_anchor(self, home: Path, keyring: Keyring) -> None:
        ledger = IntegrityLedger(home, keyring)
        for i in range(4):
            ledger.append("test", {"i": i})
        state = ledger.verify()
        assert state.ok and state.entries == 4 and state.anchor_ok

    def test_tamper_breaks_chain(self, home: Path, keyring: Keyring) -> None:
        ledger = IntegrityLedger(home, keyring)
        ledger.append("test", {"valor": "original"})
        ledger.append("test", {"valor": "segundo"})
        lines = ledger.path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["data"]["valor"] = "alterado"
        lines[0] = json.dumps(rec, sort_keys=True)
        ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        state = ledger.verify()
        assert not state.ok
        assert state.broken_at == 1

    def test_truncation_detected(self, home: Path, keyring: Keyring) -> None:
        ledger = IntegrityLedger(home, keyring)
        ledger.append("a", {})
        ledger.append("b", {})
        lines = ledger.path.read_text(encoding="utf-8").splitlines()
        ledger.path.write_text(lines[0] + "\n", encoding="utf-8")
        assert not ledger.verify().ok


class TestClassifier:
    @pytest.mark.parametrize(
        "path,expected",
        [
            (".env", 4),
            ("telegram_config.json", 4),
            ("akashic_secret.key", 4),
            ("id_rsa", 4),
            ("core/network_shield.py", 1),
            ("core/aegis/crypto.py", 1),
            (".aegis/keys/master.key", 4),
            ("data/telemetry.json", 2),
            ("README.md", 0),
        ],
    )
    def test_levels(self, path: str, expected: int) -> None:
        assert int(classify_path(path).level) == expected

    def test_secret_detection_and_redaction(self) -> None:
        token = "REDACTED" + "A" * 35
        findings = scan_text(f"TELEGRAM_TOKEN={token}\n", "x.env")
        assert any(f.kind == "Telegram Bot Token" for f in findings)
        assert all(token not in f.preview for f in findings)

    def test_pii_detection(self) -> None:
        findings = scan_text("correo: REDACTED_EMAIL", "nota.txt")
        assert any(f.rule == "email" for f in findings)

    def test_clean_text(self) -> None:
        assert scan_text("linea normal sin credenciales\n", "x.txt") == []

    def test_url_key_param_detected(self) -> None:
        found = scan_text(
            "http://host:8757/?key=Zx9Qw8Er7Ty6", "gui.py"  # aegis:allow-secret
        )
        assert any(f.rule == "url_key_param" for f in found)
        assert all("Zx9Qw8Er7Ty6" not in f.preview for f in found)
        assert scan_text("http://host/?key=YOUR_KEY_HERE", "doc.md") == []

    def test_code_assignments_are_not_secrets(self) -> None:
        # El propio código de AEGIS asigna variables llamadas `token`; eso no es
        # una credencial y no debe bloquear el hook pre-commit.
        assert scan_text("token = match.group(0)\n", "core/aegis/classifier.py") == []
        assert scan_text("secret = get_secret(store, name)\n", "modulo.py") == []


class TestPolicy:
    def test_world_readable_secret_is_flagged_and_fixed(self, tmp_path: Path) -> None:
        secret = tmp_path / ".env"
        secret.write_text("TELEGRAM_TOKEN=123456789:" + "B" * 35 + "\n", encoding="utf-8")
        os.chmod(secret, 0o644)
        auditor = PolicyAuditor(tmp_path, home=tmp_path)
        result = auditor.audit(deep=True)
        assert any(f.code == "PERM_SECRETO_ABIERTO" for f in result.findings)
        assert result.score < 100

        fixed = auditor.audit(deep=False, remediation=True)
        assert stat.S_IMODE(secret.stat().st_mode) == 0o600
        assert all(f.fixed for f in fixed.findings if f.code == "PERM_SECRETO_ABIERTO")

    def test_clean_tree_scores_high(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# público\n", encoding="utf-8")
        src = tmp_path / "modulo.py"
        src.write_text("print('hola')\n", encoding="utf-8")
        os.chmod(src, 0o644)
        result = PolicyAuditor(tmp_path, home=tmp_path).audit(deep=True)
        assert result.score >= 80


class TestAntiforensic:
    def test_shred_removes_and_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "secreto.txt"
        target.write_bytes(b"S" * 4096)
        result = shred_file(target)
        assert result["ok"]
        assert not target.exists()

    def test_shred_rejects_symlink(self, tmp_path: Path) -> None:
        real = tmp_path / "real.txt"
        real.write_text("x")
        link = tmp_path / "link"
        link.symlink_to(real)
        assert not shred_file(link)["ok"]
        assert real.exists()


class TestEngine:
    def make_engine(self, tmp_path: Path) -> AegisEngine:
        project = tmp_path / "proj"
        project.mkdir()
        return AegisEngine(home=tmp_path / "custody", project_root=project)

    def test_seal_verify_unseal(self, tmp_path: Path) -> None:
        engine = self.make_engine(tmp_path)
        src = tmp_path / "proj" / "payload.txt"
        src.write_text("material clasificado " * 100, encoding="utf-8")

        sealed = engine.seal([src], shred_source=True)
        assert sealed["ok"], sealed["errors"]
        assert not src.exists()
        container = Path(sealed["sealed"][0]["container"])
        assert container.exists()

        verification = engine.verify(deep=True)
        assert verification["ok"], verification

        out = tmp_path / "restored.txt"
        unsealed = engine.unseal(container, output=out)
        assert unsealed["ok"]
        assert out.read_text(encoding="utf-8") == "material clasificado " * 100
        assert engine.status()["sealed_files"] == 1

    def test_vault_roundtrip(self, tmp_path: Path) -> None:
        engine = self.make_engine(tmp_path)
        src = tmp_path / "objeto.bin"
        src.write_bytes(b"\x00\x01\x02vault" * 100)
        assert engine.vault_put(src, "objeto-secreto")["ok"]
        listing = engine.vault_list()
        assert listing[0]["name"] == "objeto-secreto"
        out = tmp_path / "salida.bin"
        assert engine.vault_get("objeto-secreto", output=out)["ok"]
        assert out.read_bytes() == src.read_bytes()
        assert engine.vault_rm("objeto-secreto")["ok"]
        assert engine.vault_list() == []

    def test_scan_staged_clean_repo(self, tmp_path: Path) -> None:
        engine = self.make_engine(tmp_path)
        assert engine.scan_staged()["ok"]
