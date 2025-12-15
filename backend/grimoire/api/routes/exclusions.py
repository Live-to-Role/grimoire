"""Exclusion rules API endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from grimoire.api.deps import DbSession
from grimoire.config import settings
from grimoire.services.exclusion_service import (
    get_exclusion_rules,
    create_rule,
    update_rule,
    delete_rule,
    test_rule_pattern,
    get_exclusion_stats,
    seed_default_rules,
)
from grimoire.models import ExclusionRuleType

router = APIRouter()


class CreateRuleRequest(BaseModel):
    """Request to create an exclusion rule."""
    rule_type: str
    pattern: str
    description: str | None = None
    priority: int = 0
    enabled: bool = True


class UpdateRuleRequest(BaseModel):
    """Request to update an exclusion rule."""
    pattern: str | None = None
    description: str | None = None
    priority: int | None = None
    enabled: bool | None = None


class TestPatternRequest(BaseModel):
    """Request to test a pattern."""
    rule_type: str
    pattern: str


@router.get("")
async def list_exclusion_rules(db: DbSession) -> dict:
    """List all exclusion rules."""
    rules = await get_exclusion_rules(db)
    return {
        "rules": [
            {
                "id": r.id,
                "rule_type": r.rule_type,
                "pattern": r.pattern,
                "description": r.description,
                "enabled": r.enabled,
                "is_default": r.is_default,
                "priority": r.priority,
                "files_excluded": r.files_excluded,
                "last_matched_at": r.last_matched_at.isoformat() if r.last_matched_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rules
        ],
        "total": len(rules),
    }


@router.get("/stats")
async def exclusion_stats(db: DbSession) -> dict:
    """Get exclusion rule statistics."""
    return await get_exclusion_stats(db)


@router.get("/types")
async def list_rule_types() -> dict:
    """List available rule types."""
    return {
        "types": [
            {"value": t.value, "name": t.name}
            for t in ExclusionRuleType
        ]
    }


@router.post("")
async def create_exclusion_rule(
    db: DbSession,
    request: CreateRuleRequest,
) -> dict:
    """Create a new exclusion rule."""
    # Validate rule type
    try:
        ExclusionRuleType(request.rule_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid rule type: {request.rule_type}"
        )
    
    rule = await create_rule(
        db=db,
        rule_type=request.rule_type,
        pattern=request.pattern,
        description=request.description,
        priority=request.priority,
        enabled=request.enabled,
    )
    
    return {
        "id": rule.id,
        "rule_type": rule.rule_type,
        "pattern": rule.pattern,
        "description": rule.description,
        "enabled": rule.enabled,
        "priority": rule.priority,
    }


@router.put("/{rule_id}")
async def update_exclusion_rule(
    db: DbSession,
    rule_id: int,
    request: UpdateRuleRequest,
) -> dict:
    """Update an exclusion rule."""
    updates = request.model_dump(exclude_unset=True)
    rule = await update_rule(db, rule_id, updates)
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    return {
        "id": rule.id,
        "rule_type": rule.rule_type,
        "pattern": rule.pattern,
        "description": rule.description,
        "enabled": rule.enabled,
        "priority": rule.priority,
    }


@router.delete("/{rule_id}")
async def delete_exclusion_rule(
    db: DbSession,
    rule_id: int,
) -> dict:
    """Delete an exclusion rule."""
    success = await delete_rule(db, rule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"deleted": True, "id": rule_id}


@router.post("/test")
async def test_pattern(
    db: DbSession,
    request: TestPatternRequest,
) -> dict:
    """Test a pattern against the library without saving."""
    # Validate rule type
    try:
        ExclusionRuleType(request.rule_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid rule type: {request.rule_type}"
        )
    
    library_path = Path(settings.library_path)
    if not library_path.exists():
        raise HTTPException(status_code=400, detail="Library path not configured")
    
    return await test_rule_pattern(
        db=db,
        rule_type=request.rule_type,
        pattern=request.pattern,
        library_path=library_path,
    )


@router.post("/seed-defaults")
async def seed_defaults(db: DbSession) -> dict:
    """Seed default exclusion rules."""
    count = await seed_default_rules(db)
    return {"created": count}
