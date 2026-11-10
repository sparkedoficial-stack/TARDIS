"""
tests/test_tardis_social.py - Pruebas de la Función Soberana /SOCIAL de TARDIS
==============================================================================
Verifica la composición de leyendas, el filtro Constante AEGIS, la cola
persistente, la deduplicación, el flujo de publicación simulada y el
renderizado real de la tarjeta de conclusiones (MP4 720x1280).
"""

from __future__ import annotations

import sqlite3
import types
from pathlib import Path

import pytest

import core.tardis_social_engine as tse
from core.tardis_social_engine import (
    ConclusionsCardRenderer,
    SocialPublishError,
    compose_caption,
    hashtags_for,
    init_publish_db,
    strip_markdown,
    trim_for_social,
)


class FakeRecord:
    """Registro de Video Pensante mínimo para pruebas de composición."""

    def __init__(self, **kw):
        self.id = kw.get("id", "vp_test_0001")
        self.title = kw.get("title", "Entrelazamiento cuántico explicado")
        self.topic = kw.get("topic", "Bell y la no-localidad cuántica")
        self.domain = kw.get("domain", "Física Cuántica y Microfísica")
        self.duration_sec = kw.get("duration_sec", 133.0)
        self.resolution = kw.get("resolution", "1280x720")
        self.file_path = kw.get("file_path", "/tmp/inexistente.mp4")
        self.url = kw.get("url", "https://www.youtube.com/watch?v=abc123")
        self.visual_summary = kw.get("visual_summary", "Fotones correlacionados cruzando polarizadores paralelos.")
        self.audio_summary = kw.get("audio_summary", "Narración científica sobre la causalidad y la señal.")
        self.audio_transcript = kw.get("audio_transcript", "…")
        self.abstraction_conclusions = kw.get(
            "abstraction_conclusions",
            "La no-localidad se manifiesta como correlación sin transmisión lumínica: "
            "la información no viaja, la geometría la comparte."
        )
        self.learned_insights = kw.get("learned_insights", [
            "Las desigualdades de Bell se violan sistemáticamente.",
            "La geometría del espacio es anterior a la señal.",
        ])
        self.next_questions = kw.get("next_questions", ["¿Qué significa construir un detector de Bell?"])
        self.curiosity_rationale = kw.get("curiosity_rationale", "Exploración de la realidad")


@pytest.fixture()
def social_env(tmp_path, monkeypatch):
    """Aísla config, log de publicaciones y tarjetas en un entorno temporal por prueba."""
    monkeypatch.setattr(tse, "DB_PATH", tmp_path / "publish_log_test.db")
    monkeypatch.setattr(tse, "SOCIAL_CONFIG_FILE", tmp_path / "social_config_test.json")
    monkeypatch.setattr(tse, "CARDS_DIR", tmp_path / "social_cards")
    init_publish_db(tse.DB_PATH)

    engine = tse.TardisSocialEngine.__new__(tse.TardisSocialEngine)
    engine.cfg = tse.load_social_config()
    engine.cfg["tiktok"]["min_gap_sec"] = 0
    engine.cfg["x"]["min_gap_sec"] = 0
    engine._renderer = None
    engine._last_publish_ts = 0.0
    engine._last_x_publish_ts = 0.0

    class ReadyStub:
        def __init__(self, cfg):
            self.cfg = cfg
            self.published = []

        def publish_from_file(self, path, title="", privacy_level=None):
            self.published.append((str(path), title))
            return {"publish_id": f"faux{len(self.published)}", "mode": "FILE_UPLOAD",
                    "file": str(path), "bytes": 123}

    stub = ReadyStub(engine.cfg["tiktok"])
    monkeypatch.setattr(engine, "_tiktok", lambda: stub)
    return engine, stub, tmp_path


def test_trim_for_social_respects_limit_and_sentences():
    txt = ".".join([f"Oración importante número {i} sobre la realidad" for i in range(40)])
    out = trim_for_social(txt, 200)
    assert len(out) <= 200
    assert out.endswith("…") or out.endswith(".")


def test_strip_markdown_removes_markup_and_tables():
    raw = "**Negrita** | col1 | col2 |\n# Título\n[Enlace](https://x.y)\n- punto suelto"
    clean = strip_markdown(raw)
    assert "**" not in clean
    assert "#" not in clean and "](" not in clean
    assert "· punto suelto" in clean or "punto suelto" in clean


def test_hashtags_map_domain_and_add_defaults():
    tags = hashtags_for("Bell y la no-localidad", "Física Cuántica y Microfísica")
    assert any("#FisicaCuantica" == t or "#FisicaCuantica".casefold() == t.casefold() for t in tags)
    assert "#TARDIS" in tags and "#PolimatasLatam" in tags


def test_compose_caption_within_limit_and_content():
    cfg = json_cfg = tse.load_social_config()
    long_concl = "Conclusion " * 400
    rec = FakeRecord(abstraction_conclusions=long_concl,
                     learned_insights=[f"Aprendizaje {i} " + "x" * 150 for i in range(3)])
    cap = compose_caption(rec, cfg, max_chars=1500)
    assert len(cap) <= 1500
    assert rec.topic in cap
    assert "#TARDIS" in cap
    assert "CONCLUSIONES" in cap


def test_aegis_blocks_private_names(social_env):
    engine, _, _ = social_env
    with pytest.raises(SocialPublishError):
        engine._validate_publication("Según ello, Andrea Carrillo Jimenez comentó algo.", "")
    with pytest.raises(SocialPublishError):
        engine._validate_publication("El ancla kármica de Annya May Carrillo.", "")
    engine._validate_publication("La desigualdad de Bell y los fotones entrelazados.", "")  # no debe lanzar


def test_publish_queues_pending_without_credentials(social_env):
    engine, _, tmp_path = social_env
    rec = FakeRecord()
    rec.file_path = str(tmp_path / "fake_video.mp4")
    Path(rec.file_path).write_bytes(b"0" * 4096)

    rep = engine.publish_record(rec, item="all")
    assert rep["results"]["video"]["status"] == "pending"
    assert rep["results"]["card"]["status"] == "pending"

    with sqlite3.connect(str(tse.DB_PATH)) as conn:
        rows = conn.execute("SELECT status, item_type FROM publish_log").fetchall()
    assert len(rows) == 2
    assert all(r[0] == "pending" for r in rows)
    assert {r[1] for r in rows} == {"video", "card"}


def test_pending_dedup_does_not_duplicate(social_env):
    engine, _, _ = social_env
    rec = FakeRecord()
    engine.publish_record(rec, item="all")
    engine.publish_record(rec, item="all")
    with sqlite3.connect(str(tse.DB_PATH)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM publish_log WHERE status='pending'").fetchone()[0]
    assert count == 2  # un video + una tarjeta, sin duplicados extra


def test_retry_pending_publishes_and_marks(social_env, monkeypatch):
    engine, stub, _ = social_env

    # 1) Sin credenciales: la publicación encola ambos ítems como pendientes
    rec = FakeRecord()
    rec.file_path = "/tmp/archive3895.mp4"
    Path(rec.file_path).write_bytes(b"1" * 4096)
    engine.publish_record(rec, item="all")
    with sqlite3.connect(str(tse.DB_PATH)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM publish_log WHERE status='pending'").fetchone()[0] == 2

    # 2) Se autentica el motor social...
    engine.cfg["enabled"] = True
    engine.cfg["tiktok"]["enabled"] = True
    engine.cfg["tiktok"]["access_token"] = "token_de_prueba"

    # 3) Stub de la memoria de /VideoPensante para la consulta por ID en retry
    import core.tardis_video_thinking_engine as vte
    monkeypatch.setattr(vte, "get_video_thinking_engine",
                        lambda: types.SimpleNamespace(
                            get_video_detail=lambda vid: rec.__dict__ | {"file_path": rec.file_path}))

    res = engine.retry_pending()
    assert res["published"], res
    with sqlite3.connect(str(tse.DB_PATH)) as conn:
        cur = conn.execute("SELECT status, publish_id FROM publish_log ORDER BY id").fetchall()
    states = {s for s, _ in cur}
    assert states == {"published"}
    assert all(pid for _, pid in cur)


def test_publish_record_dedups_after_published(social_env, monkeypatch):
    engine, stub, tmp_path = social_env
    engine.cfg["enabled"] = True
    engine.cfg["tiktok"]["enabled"] = True
    engine.cfg["tiktok"]["access_token"] = "token_de_prueba"

    rec = FakeRecord()
    rec.file_path = str(tmp_path / "v.mp4")
    Path(rec.file_path).write_bytes(b"2" * 4096)

    rep1 = engine.publish_record(rec, item="all")
    assert rep1["results"]["video"]["status"] == "published"
    assert rep1["results"]["card"]["status"] == "published"
    published_before = len(stub.published)

    rep2 = engine.publish_record(rec, item="all")
    assert rep2["results"]["video"]["status"] == "skipped"
    assert rep2["results"]["card"]["status"] == "skipped"
    assert len(stub.published) == published_before  # cero reenvíos


def test_conclusions_card_renders_real_mp4(social_env):
    engine, _, tmp_path = social_env
    detail = FakeRecord().__dict__
    out = tmp_path / "card_test.mp4"
    path = engine.render_card_for(detail, out_path=out)
    assert path is not None and Path(path).exists()
    assert Path(path).stat().st_size > 10_000
    # Verificar geometría 720x1280 con ffprobe
    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert "720,1280" in probe.stdout.decode()


@pytest.mark.parametrize("item_type,expected_title_prefix", [
    ("card", "TARDIS investiga"),
    ("video", "por TARDIS"),
])
def test_social_title_for_handles_markdown(item_type, expected_title_prefix):
    detail = {"topic": "**Bell & la no-localidad**", "title": "T<>ítulo `raro`"}
    title = tse.social_title_for(detail, item_type)
    assert expected_title_prefix in title or expected_title_prefix in title
    assert "**" not in title and "`" not in title


def test_x_video_publish_and_dedup(social_env, monkeypatch):
    engine, _, tmp_path = social_env
    engine.cfg["enabled"] = True
    engine.cfg["x"]["enabled"] = True

    rec = FakeRecord(id="vp_x_test_0001")
    rec.file_path = str(tmp_path / "x_vid.mp4")
    Path(rec.file_path).write_bytes(b"3" * 4096)

    published_x = []

    class XStub:
        def is_ready(self):
            return True

        def publish_video_reflection(self, snapshot, dry_run=False):
            published_x.append(snapshot["id"])
            return {
                "publish_id": "https://x.com/AsleepAstronaut/status/123456",
                "tweet_url": "https://x.com/AsleepAstronaut/status/123456",
                "account": "Asleep_astronaut | @AsleepAstronaut",
                "text": "🤖 [TARDIS · IA Externa Local] Reflexión de prueba #TARDIS",
                "thread_text": "🤖 [TARDIS · IA Externa Local] Conclusión extendida.",
                "thread_attached": True,
                "video_path": snapshot["file_path"],
                "transcoded": False,
                "duration_sec": 21.0,
                "mode": "X_CDP_VIDEO",
            }

    monkeypatch.setattr(engine, "_x_client", lambda: XStub())

    rep1 = engine.publish_record(rec, item="video", platform="x")
    assert rep1["x_results"]["x_video"]["status"] == "published"
    assert rep1["x_results"]["x_video"]["tweet_url"].endswith("/123456")
    assert len(published_x) == 1

    rep2 = engine.publish_record(rec, item="video", platform="x")
    assert rep2["x_results"]["x_video"]["status"] == "skipped"
    assert len(published_x) == 1


def test_x_reflection_synthesis_and_aegis():
    from core.tardis_browser import get_tardis_browser
    b = get_tardis_browser()
    rec = FakeRecord().__dict__
    syn = b.synthesize_video_x_reflection(rec, use_local_llm=False)
    assert syn["ok"] is True
    assert syn["primary_chars"] <= 275
    assert syn["thread_chars"] <= 275
    assert "TARDIS" in syn["primary_post"]

    bad = dict(rec)
    bad["abstraction_conclusions"] = "Nota privada sobre Annya May Carrillo."
    with pytest.raises(ValueError):
        b.synthesize_video_x_reflection(bad, use_local_llm=False)


def test_kaiju_orchestrator_enforces_local_inference(monkeypatch):
    monkeypatch.delenv("TARDIS_ALLOW_CLOUD_OFFLOAD", raising=False)
    from core.kaiju_cognitive_orchestrator import get_kaiju_cognitive_orchestrator
    orch = get_kaiju_cognitive_orchestrator()
    ev = orch.evaluate_task_complexity("Explícame cómo funciona el entrelazamiento cuántico", force_offload=False)
    assert ev["is_heavy"] is False
    assert ev["use_accelerator"] is False
    assert ev["local_sovereign"] is True
    assert ev["recommended_worker"] == "temporal_brain_local"
