"""normalize_product_type passes the Codex enum through and maps nothing else.

Grimoire's product_type column now holds the Codex enum. The old mapping turned
enum values back into stale ones: core_rulebook -> core_rules (which Codex
refuses), setting -> sourcebook, map -> other.
"""

import grimoire.services.sync_service as sync_service
from grimoire.services.classification.enum import CODEX_PRODUCT_TYPES
from grimoire.services.sync_service import normalize_product_type


def test_enum_values_pass_through_unchanged():
    for v in CODEX_PRODUCT_TYPES:
        assert normalize_product_type(v) == v


def test_core_rulebook_is_never_core_rules():
    assert normalize_product_type("core_rulebook") == "core_rulebook"
    assert normalize_product_type("Core Rulebook") == "core_rulebook"


def test_free_text_goes_through_vocab_then_other():
    assert normalize_product_type("Setting") == "setting"
    assert normalize_product_type("Map") == "map"
    assert normalize_product_type("GM Tools") == "gm_tools"
    assert normalize_product_type("Anthology") == "other"
    assert normalize_product_type(None) is None


def test_core_rules_from_old_data_is_sent_as_core_rulebook():
    # Codex refuses core_rules; the vocabulary maps it to core_rulebook.
    assert normalize_product_type("core_rules") == "core_rulebook"


def test_old_mapping_is_gone():
    assert not hasattr(sync_service, "PRODUCT_TYPE_MAPPING")
    # One enum, shared with classification — not a local copy that can drift.
    assert getattr(sync_service, "CODEX_PRODUCT_TYPES", CODEX_PRODUCT_TYPES) is CODEX_PRODUCT_TYPES
