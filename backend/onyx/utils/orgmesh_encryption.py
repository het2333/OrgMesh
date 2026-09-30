"""Independent OrgMesh credential encryption using standard cryptography APIs.

New values use AES-256-GCM and scrypt over the full UTF-8 secret.
The v1 frame contains a marker, version, 16-byte salt, 12-byte nonce, and ciphertext/tag.
Legacy CBC reads use IV(16) + PKCS7 ciphertext. Their UTF-8 key uses the longest
supported prefix: 32 bytes, then 24 bytes, then 16 bytes. Legacy values are not rewritten.
"""

import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FRAME_PREFIX = b"\x89OrgMesh\x00"
FRAME_VERSION = 1
SALT_LENGTH = 16
NONCE_LENGTH = 12
TAG_LENGTH = 16
HEADER_LENGTH = len(FRAME_PREFIX) + 1 + SALT_LENGTH + NONCE_LENGTH
SCRYPT_COST = 2**14


class OrgMeshEncryptionError(ValueError):
    """Reject invalid encrypted values without including their contents."""


def _derive_key(secret: str, salt: bytes) -> bytes:
    secret_bytes = secret.encode("utf-8")
    if len(secret_bytes) < 16:
        raise OrgMeshEncryptionError(
            "Encryption key must contain at least 16 UTF-8 bytes"
        )
    return Scrypt(salt=salt, length=32, n=SCRYPT_COST, r=8, p=1).derive(secret_bytes)


def encrypt_secret(value: str, secret: str) -> bytes:
    if not secret:
        return value.encode("utf-8")
    salt = secrets.token_bytes(SALT_LENGTH)
    nonce = secrets.token_bytes(NONCE_LENGTH)
    header = FRAME_PREFIX + bytes([FRAME_VERSION]) + salt + nonce
    ciphertext = AESGCM(_derive_key(secret, salt)).encrypt(
        nonce, value.encode("utf-8"), header
    )
    return header + ciphertext


def _decrypt_legacy_cbc(value: bytes, secret: str) -> str:
    raw_key = secret.encode("utf-8")
    key_length = next(
        (length for length in (32, 24, 16) if len(raw_key) >= length), None
    )
    if key_length is None or len(value) < 32 or len(value) % 16:
        raise OrgMeshEncryptionError("Could not decrypt encrypted value")
    decryptor = Cipher(
        algorithms.AES(raw_key[:key_length]), modes.CBC(value[:16])
    ).decryptor()
    padded = decryptor.update(value[16:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return plaintext.decode("utf-8")


def decrypt_secret(value: bytes, secret: str, *, allow_plaintext: bool = True) -> str:
    if value.startswith(FRAME_PREFIX):
        if not secret:
            raise OrgMeshEncryptionError(
                "Encryption key is required for encrypted values"
            )
        if (
            len(value) < HEADER_LENGTH + TAG_LENGTH
            or value[len(FRAME_PREFIX)] != FRAME_VERSION
        ):
            raise OrgMeshEncryptionError("Unsupported encrypted value format")
        salt_start = len(FRAME_PREFIX) + 1
        salt = value[salt_start : salt_start + SALT_LENGTH]
        nonce = value[salt_start + SALT_LENGTH : HEADER_LENGTH]
        try:
            plaintext = AESGCM(_derive_key(secret, salt)).decrypt(
                nonce, value[HEADER_LENGTH:], value[:HEADER_LENGTH]
            )
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeError):
            raise OrgMeshEncryptionError("Could not decrypt encrypted value") from None

    if secret:
        try:
            return _decrypt_legacy_cbc(value, secret)
        except (ValueError, UnicodeError):
            if not allow_plaintext:
                raise OrgMeshEncryptionError(
                    "Could not decrypt encrypted value"
                ) from None
    if allow_plaintext or not secret:
        try:
            return value.decode("utf-8")
        except UnicodeError:
            raise OrgMeshEncryptionError(
                "Could not decode legacy plaintext value"
            ) from None
    raise OrgMeshEncryptionError("Could not decrypt encrypted value")
