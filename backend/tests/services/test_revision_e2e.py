"""End-to-end test: full lifecycle of revision detection -> confirm -> verify."""
import pytest
from sqlalchemy import select
from grimoire.models.product import Product
from grimoire.services.revision_service import (
    mark_revision_candidates,
    confirm_revision,
    get_revision_groups,
    cleanup_orphaned_superseded,
)


@pytest.mark.asyncio
async def test_full_revision_lifecycle(db):
    """Complete flow: create products -> detect -> confirm -> verify visibility."""
    # 1. Create two products that are revisions of each other
    old = Product(
        file_path="/lib/Curse_of_Strahd-PDF.pdf",
        file_name="Curse_of_Strahd-PDF.pdf",
        file_hash="hash_original",
        file_size=50000,
        normalized_stem="curse_of_strahd",
        title="Curse of Strahd",
        author="Wizards",
        publisher="WotC",
        game_system="D&D 5e",
    )
    revised = Product(
        file_path="/lib/Curse_of_Strahd-PDF_(Revised).pdf",
        file_name="Curse_of_Strahd-PDF_(Revised).pdf",
        file_hash="hash_revised",
        file_size=55000,
        normalized_stem="curse_of_strahd",
        title=None,  # Not yet identified
    )
    db.add_all([old, revised])
    await db.commit()

    # 2. Detect candidates
    count = await mark_revision_candidates(db)
    assert count >= 1

    await db.refresh(old)
    assert old.is_duplicate is True
    assert old.duplicate_reason == "revision"
    assert old.duplicate_of_id == revised.id  # revised is newer (has indicator)

    # 3. Check groups API
    groups = await get_revision_groups(db)
    assert len(groups) >= 1

    # 4. Confirm the revision
    result = await confirm_revision(db, old.id)
    assert "author" in result["transferred_fields"]

    await db.refresh(revised)
    assert revised.author == "Wizards"
    assert revised.publisher == "WotC"
    assert revised.game_system == "D&D 5e"
    assert revised.title == "Curse of Strahd"  # Transferred from old since revised.title was None

    await db.refresh(old)
    assert old.is_superseded is True
    assert old.is_duplicate is False

    # 5. Verify superseded product is not in visible queries
    visible = await db.execute(
        select(Product).where(Product.is_superseded == False, Product.is_missing == False)
    )
    visible_products = visible.scalars().all()
    assert old.id not in [p.id for p in visible_products]
    assert revised.id in [p.id for p in visible_products]

    # 6. Test orphan cleanup
    await db.delete(revised)
    await db.commit()

    cleanup = await cleanup_orphaned_superseded(db)
    assert cleanup["cleaned"] == 1

    await db.refresh(old)
    assert old.is_superseded is False
