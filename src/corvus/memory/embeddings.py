"""Deterministic text embeddings for sqlite-vec semantic memory search."""

from __future__ import annotations

import hashlib
import math
import re

EMBEDDING_DIM = 384

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def embed_text(text: str, *, dim: int = EMBEDDING_DIM) -> list[float]:
    """Hash bag-of-words embedding — deterministic, no external model."""
    vec = [0.0] * dim
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return vec

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for offset in range(0, len(digest) - 1, 2):
            idx = int.from_bytes(digest[offset : offset + 2], "big") % dim
            vec[idx] += 1.0

    norm = math.sqrt(sum(value * value for value in vec))
    if norm == 0.0:
        return vec
    return [value / norm for value in vec]
