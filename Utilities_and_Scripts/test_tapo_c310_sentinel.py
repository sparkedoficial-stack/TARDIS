import numpy as np
from pathlib import Path
from core.tapo_c310_sentinel import (
    BASE_DIR,
    PersonDetection,
    YoloV8PersonDetector,
    render_tardis_hud,
)


def test_yolov8_detector_empty_and_hud():
    model_path = BASE_DIR / "models" / "yolov8s.onnx"
    assert model_path.is_file(), "yolov8s.onnx debe existir en models/"

    detector = YoloV8PersonDetector(model_path=model_path, conf_threshold=0.42)
    blank = np.zeros((1296, 2304, 3), dtype=np.uint8)
    detections, latency_ms = detector.detect(blank)
    assert detections == []
    assert latency_ms > 0.0

    fake_det = [PersonDetection(x1=400, y1=300, x2=680, y2=980, confidence=0.914)]
    hud = render_tardis_hud(blank, fake_det, camera_alias="GOD-EYE", camera_ip="REDACTED_IP")
    assert hud.shape == blank.shape
    assert int(hud.sum()) > 0
