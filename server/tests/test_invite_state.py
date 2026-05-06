import pytest

from server.auth.invite_state import (
    InviteStateError,
    decode_invite_state,
    encode_invite_state,
)


SECRET = "test-secret"


def test_encode_decode_roundtrip():
    encoded = encode_invite_state(invite_token="tok_123", secret=SECRET)
    assert decode_invite_state(encoded, secret=SECRET) == "tok_123"


def test_decode_rejects_tampered_payload():
    encoded = encode_invite_state(invite_token="tok_123", secret=SECRET)
    head, sig = encoded.rsplit(".", 1)
    tampered = head.replace("tok_123", "tok_xxx") + "." + sig
    with pytest.raises(InviteStateError):
        decode_invite_state(tampered, secret=SECRET)


def test_decode_rejects_bad_signature():
    encoded = encode_invite_state(invite_token="tok_123", secret=SECRET)
    head, _sig = encoded.rsplit(".", 1)
    forged = head + ".aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    with pytest.raises(InviteStateError):
        decode_invite_state(forged, secret=SECRET)


def test_decode_rejects_wrong_secret():
    encoded = encode_invite_state(invite_token="tok_123", secret=SECRET)
    with pytest.raises(InviteStateError):
        decode_invite_state(encoded, secret="other-secret")


def test_decode_rejects_malformed():
    with pytest.raises(InviteStateError):
        decode_invite_state("not-a-valid-state", secret=SECRET)
