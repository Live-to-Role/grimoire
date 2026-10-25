from grimoire.services.classification.enum import CODEX_PRODUCT_TYPES, VOCAB_MAP, normalize_free_text


def test_enum_has_fourteen_values_and_no_core_rules():
    assert len(CODEX_PRODUCT_TYPES) == 14
    assert "core_rules" not in CODEX_PRODUCT_TYPES
    assert "core_rulebook" in CODEX_PRODUCT_TYPES


def test_vocab_map_targets_are_enum_values():
    assert set(VOCAB_MAP.values()) <= set(CODEX_PRODUCT_TYPES)


def test_normalize_free_text():
    assert normalize_free_text("Core Rulebook") == "core_rulebook"
    assert normalize_free_text("  quick start guide ") == "core_rulebook"
    assert normalize_free_text("adventure") == "adventure"
    assert normalize_free_text("Anthology") is None
    assert normalize_free_text(None) is None


def test_magazine_free_text_is_a_zine():
    # Michael, pilot review: the catalog has no true periodicals; zine is right.
    assert normalize_free_text("Magazine") == "zine"
    assert normalize_free_text("magazine") == "zine"
