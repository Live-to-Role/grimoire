"""Regression test: local embedding generation must not block the event loop.

The local sentence-transformers path runs a synchronous, CPU-bound
`model.encode()`. If it runs directly on the event loop it freezes all HTTP
handling (symptom: every endpoint takes many seconds while the embedding
backfill runs). It must be offloaded to a thread via asyncio.to_thread.
"""
import asyncio
import time

import pytest
from unittest.mock import AsyncMock, patch

from grimoire.services import embeddings
from grimoire.services.embeddings import EmbeddingResult, generate_embeddings


@pytest.mark.asyncio
async def test_local_embedding_does_not_block_event_loop():
    """While a (simulated) slow local encode runs, the loop stays responsive."""

    def slow_blocking_embed(texts, model_name="all-MiniLM-L6-v2"):
        # Simulate SentenceTransformer.encode(): a synchronous CPU/IO stall.
        time.sleep(0.5)
        return [EmbeddingResult(embedding=[0.1, 0.2, 0.3], model=model_name) for _ in texts]

    # A concurrent heartbeat coroutine that ticks every 10ms. If the event loop
    # is blocked by the embed call, it cannot tick during that window.
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    hb = asyncio.create_task(heartbeat())
    try:
        with patch.object(embeddings, "embed_with_local", slow_blocking_embed), \
             patch("grimoire.processors.ai_identifier.get_setting_from_db",
                   new=AsyncMock(return_value="")), \
             patch("grimoire.processors.ai_identifier.get_ollama_url",
                   new=AsyncMock(return_value="")):
            results = await generate_embeddings(["hello", "world"], provider="local")
    finally:
        hb.cancel()

    # The embed took ~0.5s; a non-blocked loop should have ticked many times.
    assert ticks >= 10, f"event loop appears blocked during local embed (ticks={ticks})"
    assert len(results) == 2
    assert results[0].embedding == [0.1, 0.2, 0.3]
