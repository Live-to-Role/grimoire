"""Where the Ollama address comes from, and which source wins.

The Settings page used to pre-fill this field with http://localhost:11434.
Saving the form for any reason wrote that to the database, where it overrides
OLLAMA_BASE_URL from the environment. In Docker that address points at the
container itself, so every Ollama call failed with a connection error and
nothing indicated why.

The UI now leaves the field blank. These tests pin the behaviour that makes
blank the right default: an empty stored value must defer to the environment
rather than being treated as a configured address.
"""
import pytest

from grimoire.models import Setting
from grimoire.processors import ai_identifier


@pytest.fixture
def env_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")


@pytest.fixture
def stored(db, monkeypatch):
    """Point get_setting_from_db at the test session."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db

    monkeypatch.setattr(
        "grimoire.database.get_db_session", fake_session, raising=False
    )

    async def _set(value):
        db.add(Setting(key="ollama_base_url", value=f'"{value}"'))
        await db.commit()

    return _set


async def test_blank_stored_value_defers_to_the_environment(db, env_url, stored):
    """The case the UI fix depends on: blank means "not configured"."""
    await stored("")

    assert await ai_identifier.get_ollama_url() == "http://host.docker.internal:11434"


async def test_absent_setting_uses_the_environment(db, env_url, stored):
    assert await ai_identifier.get_ollama_url() == "http://host.docker.internal:11434"


async def test_a_real_stored_value_still_wins(db, env_url, stored):
    """Someone who deliberately points at another host must keep that."""
    await stored("http://192.168.1.50:11434")

    assert await ai_identifier.get_ollama_url() == "http://192.168.1.50:11434"


async def test_falls_back_to_localhost_with_no_environment(db, stored, monkeypatch):
    """Bare-metal default, which is why localhost was ever plausible."""
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    assert await ai_identifier.get_ollama_url() == "http://localhost:11434"
