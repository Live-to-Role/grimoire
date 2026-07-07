"""Tests for embedding generation and similarity search."""

import json

import httpx
import pytest

from grimoire.services import embeddings as emb_mod
from grimoire.services.embeddings import embed_with_ollama


@pytest.mark.asyncio
async def test_ollama_embeds_batch_in_single_request(monkeypatch):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests_seen.append(payload)
        n = len(payload["input"])
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]] * n})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    results = await embed_with_ollama(["a", "b", "c"], "http://fake:11434")

    assert len(requests_seen) == 1, "must be a single batched request"
    assert requests_seen[0]["input"] == ["a", "b", "c"]
    assert len(results) == 3
    assert results[0].embedding == [0.1, 0.2, 0.3]
