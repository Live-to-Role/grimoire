"""The identification prompt asks for the Codex enum and sees the level passages.

It used to offer free-text examples ("Adventure", "Core Rulebook") and read only
text[:4000], so a level range stated past the first pages never reached it.
"""
import grimoire.processors.ai_identifier as ai_identifier
from grimoire.processors.ai_identifier import IDENTIFICATION_PROMPT, identify_product


def test_identification_prompt_uses_enum_not_examples():
    assert "one of:" in IDENTIFICATION_PROMPT and "core_rulebook" in IDENTIFICATION_PROMPT
    assert 'e.g. "Adventure"' not in IDENTIFICATION_PROMPT
    # Michael's pilot ruling: every periodical is a zine.
    assert "magazine" not in IDENTIFICATION_PROMPT.split("product_type:")[1].split("\n")[0]


def test_identification_prompt_carries_level_rules():
    assert "0-level" in IDENTIFICATION_PROMPT
    assert "never infer" in IDENTIFICATION_PROMPT.lower()


async def _sent_text(monkeypatch, text: str) -> str:
    seen = {}

    async def fake_ollama(t, url, model, filename=None):
        seen["text"] = t
        return {"product_type": "adventure"}

    async def no_setting(key):
        return ""

    async def ollama_url():
        return "http://ollama.test"

    monkeypatch.setattr(ai_identifier, "identify_with_ollama", fake_ollama)
    monkeypatch.setattr(ai_identifier, "get_setting_from_db", no_setting)
    monkeypatch.setattr(ai_identifier, "get_ollama_url", ollama_url)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    await identify_product(text, provider="ollama", filename="tomb.pdf")
    return seen["text"]


async def test_identify_sends_level_passage_beyond_first_4000_chars(monkeypatch):
    text = "Introduction to the dungeon. " * 1500 + "An adventure for 3rd to 5th level characters."

    sent = await _sent_text(monkeypatch, text)

    assert "3rd to 5th level characters" in sent
    assert sent.startswith("# Document")
