"""The default minimum-size rule was set high enough to eat real books.

10KB excluded any one-page PDF — character sheets, handouts, maps, one-page
dungeons — which are ordinary contents of an RPG library, not corruption. The
threshold drops to 1KB, which still catches empty and truncated files.

Existing installs must be corrected too, but only where the rule is still the
one Grimoire shipped: a threshold the user chose is theirs to keep.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grimoire.models import DEFAULT_EXCLUSION_RULES, ExclusionRule
from grimoire.services.exclusion_service import (
    LEGACY_SIZE_MIN_PATTERN,
    SIZE_MIN_PATTERN,
    correct_legacy_size_min_default,
    seed_default_rules,
)


@pytest.fixture
def maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _size_min_rule(db) -> ExclusionRule | None:
    result = await db.execute(
        select(ExclusionRule).where(ExclusionRule.rule_type == "size_min")
    )
    return result.scalars().first()


def test_shipped_default_is_1kb():
    """A fresh install must never ship the 10KB threshold."""
    size_rules = [r for r in DEFAULT_EXCLUSION_RULES if r["rule_type"] == "size_min"]
    assert len(size_rules) == 1
    assert size_rules[0]["pattern"] == SIZE_MIN_PATTERN == "1024"
    assert "corrupt" not in (size_rules[0]["description"] or "").lower()


async def test_fresh_install_seeds_1kb(db):
    await seed_default_rules(db)
    rule = await _size_min_rule(db)
    assert rule.pattern == "1024"


async def test_existing_install_with_untouched_rule_is_corrected(db):
    """The upgrade path: an install still carrying the shipped 10KB rule."""
    db.add(ExclusionRule(
        rule_type="size_min",
        pattern=LEGACY_SIZE_MIN_PATTERN,
        description="Files under 10KB (likely corrupt)",
        is_default=True,
        enabled=True,
    ))
    await db.flush()

    changed = await correct_legacy_size_min_default(db)

    assert changed == 1
    rule = await _size_min_rule(db)
    assert rule.pattern == "1024"
    assert "corrupt" not in (rule.description or "").lower()


async def test_a_threshold_the_user_chose_is_left_alone(db):
    db.add(ExclusionRule(
        rule_type="size_min", pattern="51200", is_default=True, enabled=True
    ))
    await db.flush()

    changed = await correct_legacy_size_min_default(db)

    assert changed == 0
    rule = await _size_min_rule(db)
    assert rule.pattern == "51200"


async def test_a_user_created_rule_is_left_alone(db):
    """Same threshold, but the user made it — not ours to rewrite."""
    db.add(ExclusionRule(
        rule_type="size_min",
        pattern=LEGACY_SIZE_MIN_PATTERN,
        is_default=False,
        enabled=True,
    ))
    await db.flush()

    changed = await correct_legacy_size_min_default(db)

    assert changed == 0
    rule = await _size_min_rule(db)
    assert rule.pattern == LEGACY_SIZE_MIN_PATTERN


async def test_correction_preserves_a_disabled_rule(db):
    """If the user turned the rule off, it stays off."""
    db.add(ExclusionRule(
        rule_type="size_min",
        pattern=LEGACY_SIZE_MIN_PATTERN,
        is_default=True,
        enabled=False,
    ))
    await db.flush()

    await correct_legacy_size_min_default(db)

    rule = await _size_min_rule(db)
    assert rule.pattern == "1024"
    assert rule.enabled is False


async def test_correction_is_idempotent(db):
    db.add(ExclusionRule(
        rule_type="size_min",
        pattern=LEGACY_SIZE_MIN_PATTERN,
        is_default=True,
        enabled=True,
    ))
    await db.flush()

    assert await correct_legacy_size_min_default(db) == 1
    assert await correct_legacy_size_min_default(db) == 0


async def test_correction_on_an_empty_database_is_a_no_op(db):
    assert await correct_legacy_size_min_default(db) == 0
