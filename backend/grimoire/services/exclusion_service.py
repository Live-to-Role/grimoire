"""Service for managing exclusion rules and matching files."""

import fnmatch
import logging
import re
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import ExclusionRule, ExclusionRuleType, DEFAULT_EXCLUSION_RULES

logger = logging.getLogger(__name__)


class ExclusionMatcher:
    """Matches files against exclusion rules."""
    
    def __init__(self, rules: list[ExclusionRule]):
        self.rules = sorted(
            [r for r in rules if r.enabled],
            key=lambda r: -r.priority
        )
        self._compiled_regex: dict[int, re.Pattern] = {}
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for performance."""
        for rule in self.rules:
            if rule.rule_type == ExclusionRuleType.REGEX.value:
                try:
                    self._compiled_regex[rule.id] = re.compile(rule.pattern)
                except re.error as e:
                    logger.warning(f"Invalid regex pattern in rule {rule.id}: {e}")
    
    def should_exclude(
        self,
        file_path: Path,
        file_size: int,
    ) -> tuple[bool, ExclusionRule | None]:
        """
        Check if a file should be excluded.
        
        Returns:
            Tuple of (should_exclude, matching_rule)
        """
        for rule in self.rules:
            if self._matches(rule, file_path, file_size):
                return True, rule
        return False, None
    
    def _matches(self, rule: ExclusionRule, path: Path, size: int) -> bool:
        """Check if a single rule matches the file."""
        rule_type = rule.rule_type
        pattern = rule.pattern
        
        if rule_type == ExclusionRuleType.FOLDER_PATH.value:
            return fnmatch.fnmatch(str(path.parent), pattern)
        
        elif rule_type == ExclusionRuleType.FOLDER_NAME.value:
            return pattern in path.parts
        
        elif rule_type == ExclusionRuleType.FILENAME.value:
            return fnmatch.fnmatch(path.name, pattern)
        
        elif rule_type == ExclusionRuleType.SIZE_MIN.value:
            try:
                min_size = int(pattern)
                return size < min_size
            except ValueError:
                return False
        
        elif rule_type == ExclusionRuleType.SIZE_MAX.value:
            try:
                max_size = int(pattern)
                return size > max_size
            except ValueError:
                return False
        
        elif rule_type == ExclusionRuleType.REGEX.value:
            compiled = self._compiled_regex.get(rule.id)
            if compiled:
                return bool(compiled.search(str(path)))
            return False
        
        return False


async def get_exclusion_rules(db: AsyncSession) -> list[ExclusionRule]:
    """Get all exclusion rules, ordered by priority."""
    query = select(ExclusionRule).order_by(ExclusionRule.priority.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_enabled_rules(db: AsyncSession) -> list[ExclusionRule]:
    """Get only enabled exclusion rules."""
    query = (
        select(ExclusionRule)
        .where(ExclusionRule.enabled == True)
        .order_by(ExclusionRule.priority.desc())
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_exclusion_matcher(db: AsyncSession) -> ExclusionMatcher:
    """Create an ExclusionMatcher with current rules from database."""
    rules = await get_enabled_rules(db)
    return ExclusionMatcher(rules)


async def seed_default_rules(db: AsyncSession) -> int:
    """
    Seed default exclusion rules if they don't exist.
    Returns count of rules created.
    """
    # Check if defaults already exist
    query = select(ExclusionRule).where(ExclusionRule.is_default == True)
    result = await db.execute(query)
    existing = list(result.scalars().all())
    
    if existing:
        logger.debug(f"Default exclusion rules already exist ({len(existing)} rules)")
        return 0
    
    created = 0
    for rule_data in DEFAULT_EXCLUSION_RULES:
        rule = ExclusionRule(
            rule_type=rule_data["rule_type"],
            pattern=rule_data["pattern"],
            description=rule_data.get("description"),
            priority=rule_data.get("priority", 0),
            is_default=True,
            enabled=True,
        )
        db.add(rule)
        created += 1
    
    await db.commit()
    logger.info(f"Seeded {created} default exclusion rules")
    return created


async def create_rule(
    db: AsyncSession,
    rule_type: str,
    pattern: str,
    description: str | None = None,
    priority: int = 0,
    enabled: bool = True,
) -> ExclusionRule:
    """Create a new exclusion rule."""
    rule = ExclusionRule(
        rule_type=rule_type,
        pattern=pattern,
        description=description,
        priority=priority,
        enabled=enabled,
        is_default=False,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def update_rule(
    db: AsyncSession,
    rule_id: int,
    updates: dict[str, Any],
) -> ExclusionRule | None:
    """Update an existing exclusion rule."""
    query = select(ExclusionRule).where(ExclusionRule.id == rule_id)
    result = await db.execute(query)
    rule = result.scalar_one_or_none()
    
    if not rule:
        return None
    
    for field, value in updates.items():
        if hasattr(rule, field) and field not in ("id", "created_at", "is_default"):
            setattr(rule, field, value)
    
    await db.commit()
    await db.refresh(rule)
    return rule


async def delete_rule(db: AsyncSession, rule_id: int) -> bool:
    """Delete an exclusion rule. Returns True if deleted."""
    query = select(ExclusionRule).where(ExclusionRule.id == rule_id)
    result = await db.execute(query)
    rule = result.scalar_one_or_none()
    
    if not rule:
        return False
    
    await db.delete(rule)
    await db.commit()
    return True


async def test_rule_pattern(
    db: AsyncSession,
    rule_type: str,
    pattern: str,
    library_path: Path,
) -> dict[str, Any]:
    """
    Test a rule pattern against the library without saving.
    Returns list of files that would be matched.
    """
    # Create a temporary rule for testing
    temp_rule = ExclusionRule(
        id=-1,
        rule_type=rule_type,
        pattern=pattern,
        enabled=True,
        priority=0,
    )
    
    matcher = ExclusionMatcher([temp_rule])
    matched_files = []
    scanned = 0
    
    for pdf_path in library_path.rglob("*.pdf"):
        scanned += 1
        try:
            size = pdf_path.stat().st_size
            excluded, _ = matcher.should_exclude(pdf_path, size)
            if excluded:
                matched_files.append({
                    "path": str(pdf_path),
                    "name": pdf_path.name,
                    "size": size,
                })
        except OSError:
            continue
        
        # Limit for performance
        if len(matched_files) >= 100:
            break
    
    return {
        "scanned": scanned,
        "matched_count": len(matched_files),
        "matched_files": matched_files[:50],  # Return first 50
        "truncated": len(matched_files) >= 100,
    }


async def increment_rule_match(
    db: AsyncSession,
    rule_id: int,
) -> None:
    """Increment the match counter for a rule."""
    query = select(ExclusionRule).where(ExclusionRule.id == rule_id)
    result = await db.execute(query)
    rule = result.scalar_one_or_none()
    
    if rule:
        rule.files_excluded += 1
        rule.last_matched_at = datetime.now(UTC)
        await db.commit()


async def get_exclusion_stats(db: AsyncSession) -> dict[str, Any]:
    """Get statistics about exclusion rules."""
    query = select(ExclusionRule)
    result = await db.execute(query)
    rules = list(result.scalars().all())
    
    total_excluded = sum(r.files_excluded for r in rules)
    enabled_count = sum(1 for r in rules if r.enabled)
    
    return {
        "total_rules": len(rules),
        "enabled_rules": enabled_count,
        "disabled_rules": len(rules) - enabled_count,
        "default_rules": sum(1 for r in rules if r.is_default),
        "custom_rules": sum(1 for r in rules if not r.is_default),
        "total_files_excluded": total_excluded,
        "rules_by_type": {
            rule_type.value: sum(1 for r in rules if r.rule_type == rule_type.value)
            for rule_type in ExclusionRuleType
        },
    }
