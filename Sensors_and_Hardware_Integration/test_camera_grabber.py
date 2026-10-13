import pytest
from telemetry.camera_grabber import PersistentCameraGrabber, get_camera_grabber

def test_camera_grabber_instance():
    grabber = get_camera_grabber(0)
    assert isinstance(grabber, PersistentCameraGrabber)
    assert grabber.camera_index == 0
    assert grabber.target_fps >= 1

def test_camera_grabber_get_frame():
    grabber = get_camera_grabber(0)
    ok, frame, ts = grabber.get_latest_frame()
    # Si la cámara está presente o no, el método debe responder sin lanzar excepciones
    assert isinstance(ok, bool)
    if ok:
        assert frame is not None
        assert ts > 0
