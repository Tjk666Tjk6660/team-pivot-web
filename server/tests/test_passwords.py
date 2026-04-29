from server.passwords import hash_password, verify_password


def test_hash_then_verify_succeeds():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h)


def test_verify_wrong_password_fails():
    h = hash_password("hunter2")
    assert not verify_password("notthepw", h)


def test_hash_is_deterministic_within_same_salt_only():
    h1 = hash_password("x")
    h2 = hash_password("x")
    assert h1 != h2  # bcrypt salts random — must NOT match
    assert verify_password("x", h1)
    assert verify_password("x", h2)


def test_verify_handles_legacy_string_input():
    h = hash_password("x")
    # Hash returned as str so DB column TEXT works
    assert isinstance(h, str)
    assert verify_password("x", h)
