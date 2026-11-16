"""Text embeddings: turn text into a list of numbers so similar meanings sit close together.

Two implementations behind one interface:
- FastEmbedEmbedder: real semantic embeddings, runs on your machine, no API key.
- HashEmbedder: offline stand-in used by the tests and the demo. It only captures
  shared words, so never use it to report results.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence

from .config import EMBED_DIM, get_settings


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Bag-of-words hashing into a fixed-size vector, then normalised to length 1."""

    name = "hash"

    def __init__(self, dim: int = EMBED_DIM) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.md5(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class FastEmbedEmbedder:
    """Local ONNX embedding model. The first call downloads the model (about 100 MB)."""

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding  # imported here so tests do not need the model

        self.name = model_name
        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = [[float(x) for x in vec] for vec in self._model.embed(list(texts))]
        if vectors and len(vectors[0]) != EMBED_DIM:
            raise ValueError(
                f"{self.name} produces {len(vectors[0])}-dimensional vectors but the database "
                f"column is vector({EMBED_DIM}). Change both or pick a {EMBED_DIM}-dimensional model."
            )
        return vectors


def get_embedder(kind: str | None = None) -> Embedder:
    settings = get_settings()
    kind = kind or settings.embedder
    if kind == "hash":
        return HashEmbedder()
    if kind == "fastembed":
        return FastEmbedEmbedder(settings.embed_model)
    raise ValueError(f"Unknown EMBEDDER '{kind}'. Use 'fastembed' or 'hash'.")
