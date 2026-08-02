"""Optional at-rest encryption for memory record content."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def derive_agent_key(master_key: str, agent_id: str) -> bytes:
    return hashlib.sha256(f"{master_key}:{agent_id}".encode()).digest()


def encrypt_content(*, master_key: str, agent_id: str, plaintext: str) -> str:
    key = derive_agent_key(master_key, agent_id)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_content(*, master_key: str, agent_id: str, encoded: str) -> str:
    key = derive_agent_key(master_key, agent_id)
    raw = base64.b64decode(encoded.encode("ascii"))
    nonce, ciphertext = raw[:12], raw[12:]
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
