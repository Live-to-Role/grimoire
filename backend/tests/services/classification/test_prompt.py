import json

import pytest

from grimoire.services.classification.enum import CODEX_PRODUCT_TYPES
from grimoire.services.classification.prompt import (
    OUTPUT_SCHEMA,
    SYSTEM_PROMPT,
    build_request,
    parse_output,
)


def _output(**overrides) -> str:
    body = {
        "product_type": "adventure",
        "level_range_min": 0,
        "level_range_max": 0,
        "confidence": 0.9,
        "type_evidence": "x",
        "level_evidence": "0-level funnel",
        "notes": "",
    }
    body.update(overrides)
    return json.dumps(body)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_schema_enum_is_codex_enum():
    assert set(OUTPUT_SCHEMA["properties"]["product_type"]["enum"]) == set(CODEX_PRODUCT_TYPES)
    assert OUTPUT_SCHEMA["additionalProperties"] is False


def test_schema_requires_every_field():
    assert set(OUTPUT_SCHEMA["required"]) == set(OUTPUT_SCHEMA["properties"])


def test_schema_has_no_constraints_structured_outputs_rejects():
    # Batch requests are plain dicts the SDK does not clean, so the schema must
    # already be free of numeric and string constraints.
    banned = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength"}
    for node in _walk(OUTPUT_SCHEMA):
        assert not banned & set(node), node


def test_system_prompt_states_the_rules():
    for needle in ("0-level", "level 0", "never infer", "core_rulebook", "page number", "spell level"):
        assert needle.lower() in SYSTEM_PROMPT.lower()
    assert "core_rules" not in SYSTEM_PROMPT.replace("core_rulebook", "")
    for value in CODEX_PRODUCT_TYPES:
        assert f"`{value}`" in SYSTEM_PROMPT


def test_build_request_shape():
    r = build_request("cx-1", "text", "claude-opus-5-5", "medium")
    assert r["custom_id"] == "cx-1"
    p = r["params"]
    assert p["model"] == "claude-opus-5-5" and p["max_tokens"] == 8000
    assert p["output_config"]["effort"] == "medium"
    assert p["output_config"]["format"] == {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    assert p["system"][0] == {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    assert p["messages"] == [{"role": "user", "content": "text"}]
    assert "thinking" not in p and "temperature" not in p and "tool_choice" not in p


def test_parse_output_accepts_level_zero_and_rejects_41():
    assert parse_output(_output()).level_range_min == 0
    with pytest.raises(ValueError):
        parse_output(_output(level_range_min=41))


def test_parse_output_rejects_core_rules_and_bad_json():
    with pytest.raises(ValueError):
        parse_output(_output(product_type="core_rules"))
    with pytest.raises(ValueError, match="not json"):
        parse_output("not json")


def test_parse_output_allows_null_levels():
    out = parse_output(_output(level_range_min=None, level_range_max=None, level_evidence=None))
    assert out.level_range_min is None and out.level_evidence is None
