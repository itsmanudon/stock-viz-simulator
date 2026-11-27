"""Text embeddings on local Ollama (A8.4, M11.1).

Owner, 27 Nov 2026: ``nomic-embed-text`` through the Ollama already running,
so the API gains no torch. Off until ``OLLAMA_EMBED_MODEL`` is set.
``POST {url}/api/embed`` with ``{"model", "input": [...]}`` answers
``{"embeddings": [[...], ...]}`` in input order. nomic models expect the task
prefixes ``search_document: `` and ``search_query: ``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from stockviz.services.ai.provider import AiProviderError, Post, default_post

Task = Literal["document", "query"]
BATCH = 32


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str], task: Task) -> list[list[float]]: ...


def _prefix(model: str, task: Task) -> str:
    if "nomic" not in model:
        return ""
    return "search_document: " if task == "document" else "search_query: "


@dataclass
class OllamaEmbedder:
    model: str
    url: str = "http://127.0.0.1:11434"
    timeout: float = 120.0
    post: Post = default_post

    def embed(self, texts: list[str], task: Task) -> list[list[float]]:
        out: list[list[float]] = []
        pre = _prefix(self.model, task)
        for i in range(0, len(texts), BATCH):
            batch = [pre + t for t in texts[i : i + BATCH]]
            body = {"model": self.model, "input": batch}
            try:
                response = self.post(f"{self.url.rstrip('/')}/api/embed", body, self.timeout)
            except httpx.HTTPError as exc:
                raise AiProviderError(
                    f"Ollama is not reachable ({exc.__class__.__name__})"
                ) from exc
            if response.status_code != 200:
                raise AiProviderError(f"Ollama answered HTTP {response.status_code}")
            try:
                vectors = response.json()["embeddings"]
            except (ValueError, KeyError, TypeError) as exc:
                raise AiProviderError("Ollama's answer was not in the documented shape") from exc
            if not isinstance(vectors, list) or len(vectors) != len(batch):
                raise AiProviderError("Ollama returned the wrong number of embeddings")
            for v in vectors:
                if (
                    not isinstance(v, list)
                    or not v
                    or not all(isinstance(x, int | float) and math.isfinite(x) for x in v)
                ):
                    raise AiProviderError("Ollama returned an embedding that is not numbers")
                out.append([float(x) for x in v])
        return out


def embedder_from_settings(settings: Any) -> OllamaEmbedder | None:
    model = (getattr(settings, "ollama_embed_model", "") or "").strip()
    if not model:
        return None
    return OllamaEmbedder(
        model=model, url=getattr(settings, "ollama_url", "") or OllamaEmbedder.url
    )
