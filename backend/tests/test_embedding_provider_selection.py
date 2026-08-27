"""Which provider generates embeddings, and who decides.

Auto-detect used to prefer OpenAI whenever an API key happened to exist,
regardless of what the user had configured. A key left over from some other
purpose silently redirected embedding to a paid API — and, because the query
side auto-detected separately, could leave query vectors and document vectors
coming from different models.

The configured provider now decides. Ollama is the fallback when nothing is
configured, so the default costs nothing and stays on the user's machine.
"""
import pytest

from grimoire.services import embeddings as emb


@pytest.fixture
def calls(monkeypatch):
    """Record which backend was asked to embed, without calling anything."""
    seen: list[str] = []

    def _result(model):
        return [emb.EmbeddingResult(embedding=[0.1, 0.2, 0.3], model=model)]

    async def fake_openai(texts, key, model):
        seen.append("openai")
        return _result(model)

    async def fake_ollama(texts, url, model):
        seen.append("ollama")
        return _result(model)

    def fake_local(texts, model):
        seen.append("local")
        return _result(model)

    monkeypatch.setattr(emb, "embed_with_openai", fake_openai)
    monkeypatch.setattr(emb, "embed_with_ollama", fake_ollama)
    monkeypatch.setattr(emb, "embed_with_local", fake_local)
    return seen


@pytest.fixture
def settings(monkeypatch):
    """Control what the database appears to hold."""
    store: dict[str, str] = {}

    async def fake_get(key_name):
        return store.get(key_name, "")

    async def fake_ollama_url():
        return "http://localhost:11434"

    monkeypatch.setattr(
        "grimoire.processors.ai_identifier.get_setting_from_db", fake_get
    )
    monkeypatch.setattr(
        "grimoire.processors.ai_identifier.get_ollama_url", fake_ollama_url
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return store


async def test_configured_provider_wins_over_a_stray_openai_key(calls, settings):
    """The reported bug: a key that exists redirected embedding to OpenAI."""
    settings["openai_api_key"] = "sk-leftover"
    settings["semantic_search_provider"] = "ollama"

    await emb.generate_embeddings(["some text"])

    assert calls == ["ollama"]


async def test_openai_is_used_when_it_is_what_was_configured(calls, settings):
    settings["openai_api_key"] = "sk-deliberate"
    settings["semantic_search_provider"] = "openai"

    await emb.generate_embeddings(["some text"])

    assert calls == ["openai"]


async def test_an_explicit_argument_still_wins(calls, settings):
    """Routes pass the provider the user picked for that one request."""
    settings["openai_api_key"] = "sk-leftover"
    settings["semantic_search_provider"] = "ollama"

    await emb.generate_embeddings(["some text"], "local")

    assert calls == ["local"]


async def test_nothing_configured_falls_back_to_ollama(calls, settings):
    settings["openai_api_key"] = "sk-leftover"

    await emb.generate_embeddings(["some text"])

    assert calls == ["ollama"]


async def test_provider_none_falls_back_to_ollama(calls, settings):
    """"none" means semantic search is switched off, not "pick something"."""
    settings["openai_api_key"] = "sk-leftover"
    settings["semantic_search_provider"] = "none"

    await emb.generate_embeddings(["some text"])

    assert calls == ["ollama"]


async def test_configured_openai_without_a_key_is_an_error(calls, settings):
    """Better to say so than to quietly embed with something else."""
    settings["semantic_search_provider"] = "openai"

    with pytest.raises(ValueError, match="OpenAI API key"):
        await emb.generate_embeddings(["some text"])

    assert calls == []
