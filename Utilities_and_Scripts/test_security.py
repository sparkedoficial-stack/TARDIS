import pytest
from core.security import verify_token, is_request_authorized

def test_verify_token():
    for valid in ("DiosDelTiempo01", "Imznu9ZNtdbFl2ebIGSzpYqe7A3OS4Y5"):
        assert verify_token(valid) is True
        assert verify_token(f"  {valid}  ") is True
    assert verify_token("wrong_token_xyz") is False
    assert verify_token(None) is False
    assert verify_token("") is False

def test_is_request_authorized():
    for valid in ("DiosDelTiempo01", "Imznu9ZNtdbFl2ebIGSzpYqe7A3OS4Y5"):
        assert is_request_authorized({"x-api-key": valid}) is True
        assert is_request_authorized({"authorization": f"Bearer {valid}"}) is True
        assert is_request_authorized({"cookie": f"gia_token={valid}"}) is True
        assert is_request_authorized({}, {"key": valid}) is True
        assert is_request_authorized({}, {"token": valid}) is True
    assert is_request_authorized({"x-api-key": "invalid"}) is False
    assert is_request_authorized({}, {}) is False
