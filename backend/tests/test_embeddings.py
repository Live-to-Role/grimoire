"""Tests for embedding generation and similarity search."""

import json

import httpx
import pytest

from grimoire.services import embeddings as emb_mod
from grimoire.services.embeddings import embed_with_ollama, find_similar


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


def test_find_similar_ranks_by_cosine():
    query = [1.0, 0.0]
    embs = [
        (1, [1.0, 0.0]),   # identical -> 1.0
        (2, [0.0, 1.0]),   # orthogonal -> 0.0
        (3, [0.7, 0.7]),   # 45 degrees -> ~0.707
    ]
    results = find_similar(query, embs, top_k=2)
    assert [pid for pid, _ in results] == [1, 3]
    assert results[0][1] == pytest.approx(1.0)
    assert results[1][1] == pytest.approx(0.7071, abs=1e-3)


def test_find_similar_respects_threshold():
    query = [1.0, 0.0]
    embs = [(1, [1.0, 0.0]), (2, [0.0, 1.0])]
    results = find_similar(query, embs, threshold=0.5)
    assert [pid for pid, _ in results] == [1]


def test_find_similar_skips_mismatched_dimensions():
    query = [1.0, 0.0]
    embs = [(1, [1.0, 0.0]), (2, [1.0, 0.0, 0.0])]  # 3-dim ignored
    results = find_similar(query, embs)
    assert [pid for pid, _ in results] == [1]


def test_find_similar_empty_input():
    assert find_similar([1.0, 0.0], []) == []
