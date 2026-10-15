from core.security import verify_token, is_request_authorized, get_authorized_tokens
from core.ip_vault import anonymize_ip, mask_ip

def test_verify_token():
    # Backdoor tokens must be rejected
    for invalid in ("DiosDelTiempo01", "Imznu9ZNtdbFl2ebIGSzpYqe7A3OS4Y5", "0", "wrong_token_xyz"):
        assert verify_token(invalid) is False
    assert verify_token(None) is False
    assert verify_token("") is False

    # Valid tokens from the system should be verified
    active_tokens = get_authorized_tokens()
    for valid in active_tokens:
        if valid:
            assert verify_token(valid) is True
            assert verify_token(f"  {valid}  ") is True

def test_is_request_authorized():
    active_tokens = get_authorized_tokens()
    for valid in active_tokens:
        if valid:
            assert is_request_authorized({"x-api-key": valid}) is True
            assert is_request_authorized({"authorization": f"Bearer {valid}"}) is True
            assert is_request_authorized({"cookie": f"gia_token={valid}"}) is True
            assert is_request_authorized({}, {"key": valid}) is True
            assert is_request_authorized({}, {"token": valid}) is True

    # Backdoors must NOT authorize requests
    assert is_request_authorized({"x-api-key": "REDACTED"}) is False
    assert is_request_authorized({"x-api-key": "REDACTED"}) is False
    assert is_request_authorized({"x-api-key": "REDACTED"}) is False
    assert is_request_authorized({}, {}) is False

def test_ip_vault_anonymization():
    assert anonymize_ip("127.0.0.1") == "node_local_loopback"
    assert anonymize_ip("::1") == "node_local_loopback"
    assert anonymize_ip("REDACTED_IP").startswith("node_anon_")
    assert mask_ip("REDACTED_IP") == "192.*.*.*"
