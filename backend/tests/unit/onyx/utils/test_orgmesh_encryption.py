import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from onyx.utils import encryption

TEST_SECRET = "test-orgmesh-encryption-secret-32-bytes"
FRAME_PREFIX = b"\x89OrgMesh\x00"


@pytest.mark.parametrize(
    "text", ["", "test credential", "中文凭据🔑", '{"token": "测试"}']
)
def test_native_ce_encrypts_and_round_trips_unicode(
    text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(encryption, "ENCRYPTION_KEY_SECRET", TEST_SECRET)
    ciphertext = encryption._encrypt_string(text)
    assert ciphertext.startswith(FRAME_PREFIX)
    assert ciphertext != text.encode("utf-8")
    assert encryption._decrypt_bytes(ciphertext) == text


@pytest.mark.parametrize("offset", [0, 9, 12, 30, -1])
def test_framed_payload_rejects_tampering(offset: int) -> None:
    ciphertext = encryption._encrypt_string("credential-value", key=TEST_SECRET)
    assert ciphertext.startswith(FRAME_PREFIX)
    changed = bytearray(ciphertext)
    changed[offset] ^= 1
    with pytest.raises(ValueError):
        encryption._decrypt_bytes(bytes(changed), key=TEST_SECRET)


def test_framed_payload_rejects_wrong_key_and_uses_the_full_secret() -> None:
    ciphertext = encryption._encrypt_string("credential-value", key=TEST_SECRET)
    assert ciphertext.startswith(FRAME_PREFIX)
    with pytest.raises(ValueError):
        encryption._decrypt_bytes(ciphertext, key=TEST_SECRET + "different-tail")


def test_ciphertext_uses_a_new_salt_and_nonce_each_time() -> None:
    first = encryption._encrypt_string("same credential", key=TEST_SECRET)
    second = encryption._encrypt_string("same credential", key=TEST_SECRET)
    assert first != second
    assert encryption._decrypt_bytes(first, key=TEST_SECRET) == "same credential"
    assert encryption._decrypt_bytes(second, key=TEST_SECRET) == "same credential"


def _legacy_ciphertext(text: str, secret: str) -> bytes:
    raw_key = secret.encode("utf-8")
    key_length = next(length for length in (32, 24, 16) if len(raw_key) >= length)
    iv = bytes(range(16))
    padder = padding.PKCS7(128).padder()
    padded = padder.update(text.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(raw_key[:key_length]), modes.CBC(iv)).encryptor()
    return iv + encryptor.update(padded) + encryptor.finalize()


@pytest.mark.parametrize("length", [16, 20, 24, 30, 32, 40])
def test_reads_standard_legacy_cbc_with_utf8_key_prefix(length: int) -> None:
    secret = "0123456789abcdef" * 3
    secret = secret[:length]
    ciphertext = _legacy_ciphertext("legacy customer UUID 测试", secret)
    assert (
        encryption._decrypt_bytes(ciphertext, key=secret) == "legacy customer UUID 测试"
    )


def test_implicit_reads_accept_preexisting_ce_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(encryption, "ENCRYPTION_KEY_SECRET", TEST_SECRET)
    assert encryption._decrypt_bytes("旧版明文凭据".encode()) == "旧版明文凭据"
    assert encryption._decrypt_bytes(b"x" * 32) == "x" * 32


def test_missing_key_keeps_old_ce_plaintext_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(encryption, "ENCRYPTION_KEY_SECRET", "")
    assert encryption._encrypt_string("未配置密钥") == "未配置密钥".encode()
    assert encryption._decrypt_bytes("未配置密钥".encode()) == "未配置密钥"


def test_explicit_empty_key_preserves_plaintext_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(encryption, "ENCRYPTION_KEY_SECRET", TEST_SECRET)
    assert encryption._encrypt_string("plain", key="") == b"plain"
    assert encryption._decrypt_bytes(b"plain", key="") == "plain"


def test_framed_ciphertext_cannot_be_read_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ciphertext = encryption._encrypt_string("credential-value", key=TEST_SECRET)
    assert ciphertext.startswith(FRAME_PREFIX)
    monkeypatch.setattr(encryption, "ENCRYPTION_KEY_SECRET", "")
    with pytest.raises(ValueError):
        encryption._decrypt_bytes(ciphertext)


def test_explicit_nonempty_key_does_not_accept_plaintext() -> None:
    with pytest.raises(ValueError):
        encryption._decrypt_bytes(b"old plaintext", key=TEST_SECRET)


def test_versioned_public_functions_use_native_ce_encryption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(encryption, "ENCRYPTION_KEY_SECRET", TEST_SECRET)
    ciphertext = encryption.encrypt_string_to_bytes("native caller credential")
    assert ciphertext.startswith(FRAME_PREFIX)
    assert encryption.decrypt_bytes_to_string(ciphertext) == "native caller credential"


def test_truncated_encrypted_values_are_rejected() -> None:
    ciphertext = encryption._encrypt_string("credential-value", key=TEST_SECRET)
    for length in [1, 9, 10, 38, 53]:
        with pytest.raises(ValueError):
            encryption._decrypt_bytes(ciphertext[:length], key=TEST_SECRET)


def test_failure_messages_do_not_include_secret_or_value() -> None:
    ciphertext = encryption._encrypt_string("credential-value", key=TEST_SECRET)
    wrong_secret = TEST_SECRET + "different-tail"
    with pytest.raises(ValueError) as raised:
        encryption._decrypt_bytes(ciphertext, key=wrong_secret)
    assert "credential-value" not in str(raised.value)
    assert TEST_SECRET not in str(raised.value)
    assert raised.value.__suppress_context__


def test_prebuilt_standard_cbc_uuid_fixture() -> None:
    fixture = bytes.fromhex(
        "000102030405060708090a0b0c0d0e0f8ec807f61fc5e4e1276c5ab45db59520"
        "829bdfdd4a45b22518b288eb1e3a0276bd3fc749f017444fbeb56a5e6a506aee"
    )
    key = "0123456789abcdef0123456789abcdef"
    assert (
        encryption._decrypt_bytes(fixture, key=key)
        == "00000000-0000-0000-0000-000000000000"
    )
