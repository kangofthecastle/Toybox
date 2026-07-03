"""Encrypted, authenticated framing for clipboard-sync payloads, pure stdlib.

Encrypt-then-MAC: an HMAC-SHA256 keystream in counter mode gives confidentiality;
a separate HMAC-SHA256 tag over (nonce + ciphertext) gives integrity. Keys are
derived once from the shared passphrase via PBKDF2-HMAC-SHA256 with a fixed
application-label salt (domain separation, not secrecy), so both peers derive
identical keys and the KDF cost is paid once per process, not per message. No
pip, no AES -- everything is composed from hashlib/hmac/os."""
import hashlib
import hmac
import os

MAGIC = b"TBCS"                       # Toy Box Clip Sync, frame v1
_KDF_SALT = b"toybox-clipsync-v1"
_KDF_ITERS = 200_000
_NONCE_LEN = 16
_TAG_LEN = 32
_HEADER_LEN = len(MAGIC) + _NONCE_LEN + _TAG_LEN


def derive_keys(passphrase):
    """Derive (key_enc, key_mac) from a passphrase. Deterministic: the same
    passphrase always yields the same pair, so both machines match."""
    master = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"),
                                 _KDF_SALT, _KDF_ITERS, dklen=64)
    return master[:32], master[32:]


def _keystream(key_enc, nonce, length):
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hmac.new(key_enc, nonce + counter.to_bytes(8, "big"),
                            "sha256").digest())
        counter += 1
    return bytes(out[:length])


def _xor(data, keystream):
    n = len(data)
    return (int.from_bytes(data, "big")
            ^ int.from_bytes(keystream, "big")).to_bytes(n, "big")


def seal(key_enc, key_mac, text):
    """Encrypt-then-MAC `text` into MAGIC(4) | nonce(16) | tag(32) | ciphertext."""
    plaintext = text.encode("utf-8")
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = _xor(plaintext, _keystream(key_enc, nonce, len(plaintext)))
    tag = hmac.new(key_mac, nonce + ciphertext, "sha256").digest()
    return MAGIC + nonce + tag + ciphertext


def unseal(key_enc, key_mac, frame):
    """Inverse of seal(). Return the plaintext str, or None on any tamper, wrong
    key, or malformed input. Never raises on bad input."""
    try:
        if len(frame) < _HEADER_LEN or frame[:len(MAGIC)] != MAGIC:
            return None
        nonce = frame[len(MAGIC):len(MAGIC) + _NONCE_LEN]
        tag = frame[len(MAGIC) + _NONCE_LEN:_HEADER_LEN]
        ciphertext = frame[_HEADER_LEN:]
        expected = hmac.new(key_mac, nonce + ciphertext, "sha256").digest()
        if not hmac.compare_digest(tag, expected):
            return None
        return _xor(ciphertext, _keystream(key_enc, nonce, len(ciphertext))).decode("utf-8")
    except Exception:
        return None
