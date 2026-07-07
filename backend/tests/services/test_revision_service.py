import pytest
from datetime import datetime
from grimoire.models.product import Product
from grimoire.services.revision_service import (
    normalize_stem,
    has_revision_indicator,
    find_revision_candidates,
    determine_newer_product,
    mark_revision_candidates,
    confirm_revision,
    dismiss_revision,
    cleanup_orphaned_superseded,
)


class TestNormalizeStem:
    def test_basic_filename(self):
        assert normalize_stem("A_Conspiracy_of_Ravens.pdf") == "a_conspiracy_of_ravens"

    def test_strips_pdf_suffix(self):
        assert normalize_stem("A_Conspiracy_of_Ravens-PDF.pdf") == "a_conspiracy_of_ravens"
        assert normalize_stem("A_Conspiracy_of_Ravens_PDF.pdf") == "a_conspiracy_of_ravens"

    def test_strips_revised_suffix(self):
        assert normalize_stem("A_Conspiracy_of_Ravens-PDF_(Revised).pdf") == "a_conspiracy_of_ravens"
        assert normalize_stem("A_Conspiracy_of_Ravens_Revised.pdf") == "a_conspiracy_of_ravens"

    def test_strips_version_suffix(self):
        assert normalize_stem("Monster_Manual_v2.pdf") == "monster_manual"
        assert normalize_stem("Monster_Manual_v1.2.pdf") == "monster_manual"

    def test_strips_edition_suffix(self):
        assert normalize_stem("Players_Handbook_2nd_Edition.pdf") == "players_handbook"

    def test_strips_updated_errata_final(self):
        assert normalize_stem("Core_Rules_Updated.pdf") == "core_rules"
        assert normalize_stem("Core_Rules_Errata.pdf") == "core_rules"
        assert normalize_stem("Core_Rules_Final.pdf") == "core_rules"

    def test_strips_print_friendly(self):
        assert normalize_stem("Dungeon_Map_(Print_Friendly).pdf") == "dungeon_map"
        assert normalize_stem("Dungeon_Map_(Print Friendly).pdf") == "dungeon_map"

    def test_no_false_positive_mid_word(self):
        """Patterns only match at trailing position, not mid-filename."""
        assert normalize_stem("The_Final_Dungeon.pdf") == "the_final_dungeon"
        assert normalize_stem("The_PDF_Guide_to_Dragons.pdf") == "the_pdf_guide_to_dragons"

    def test_collapses_separators(self):
        assert normalize_stem("Tomb - of - Horrors.pdf") == "tomb_of_horrors"
        assert normalize_stem("Tomb__of__Horrors.pdf") == "tomb_of_horrors"

    def test_case_insensitive(self):
        assert normalize_stem("MONSTER_MANUAL-pdf.pdf") == "monster_manual"
        assert normalize_stem("Monster_Manual-PDF_(REVISED).pdf") == "monster_manual"

    def test_multiple_suffixes_stripped(self):
        """Format tag + revision pattern both stripped."""
        assert normalize_stem("Adventure_PDF_Revised.pdf") == "adventure"
        assert normalize_stem("Adventure-PDF_(Revised).pdf") == "adventure"

    def test_empty_after_strip(self):
        """Edge case: if stripping leaves nothing, return what we can."""
        assert normalize_stem("PDF.pdf") == "pdf"


class TestHasRevisionIndicator:
    def test_revised(self):
        assert has_revision_indicator("A_Conspiracy_of_Ravens-PDF_(Revised).pdf") is True

    def test_version(self):
        assert has_revision_indicator("Monster_Manual_v2.pdf") is True

    def test_no_indicator(self):
        assert has_revision_indicator("A_Conspiracy_of_Ravens-PDF.pdf") is False

    def test_final(self):
        assert has_revision_indicator("Core_Rules_Final.pdf") is True

    def test_mid_word_not_indicator(self):
        assert has_revision_indicator("The_Final_Dungeon.pdf") is False


# --- Database tests ---


@pytest.mark.asyncio
async def test_find_revision_candidates(db):
    """Products with same normalized_stem but different hash are candidates."""
    old = Product(
        file_path="/t/Ravens-PDF.pdf", file_name="Ravens-PDF.pdf",
        title="Ravens", file_hash="aaa", file_size=100, normalized_stem="ravens",
    )
    revised = Product(
        file_path="/t/Ravens-PDF_(Revised).pdf", file_name="Ravens-PDF_(Revised).pdf",
        title="Ravens Revised", file_hash="bbb", file_size=200, normalized_stem="ravens",
    )
    unrelated = Product(
        file_path="/t/Dragons.pdf", file_name="Dragons.pdf",
        title="Dragons", file_hash="ccc", file_size=300, normalized_stem="dragons",
    )
    db.add_all([old, revised, unrelated])
    await db.commit()

    groups = await find_revision_candidates(db)
    our_groups = [g for g in groups if g["normalized_stem"] == "ravens"]
    assert len(our_groups) == 1
    assert len(our_groups[0]["products"]) == 2


@pytest.mark.asyncio
async def test_find_revision_candidates_excludes_already_marked(db):
    """Already-superseded or already-duplicate products are excluded."""
    old = Product(
        file_path="/t/Ravens2.pdf", file_name="Ravens2.pdf",
        title="Ravens", file_hash="aaa2", file_size=100,
        normalized_stem="ravens2", is_superseded=True,
    )
    revised = Product(
        file_path="/t/Ravens2_Revised.pdf", file_name="Ravens2_Revised.pdf",
        title="Ravens Revised", file_hash="bbb2", file_size=200, normalized_stem="ravens2",
    )
    db.add_all([old, revised])
    await db.commit()

    groups = await find_revision_candidates(db)
    # Filter to only our stem
    our_groups = [g for g in groups if g["normalized_stem"] == "ravens2"]
    assert len(our_groups) == 0


@pytest.mark.asyncio
async def test_find_revision_candidates_three_way_group(db):
    """Three products with same stem form one group."""
    p1 = Product(file_path="/t/A3.pdf", file_name="A3.pdf", file_hash="a31", file_size=100, normalized_stem="book3", title="A")
    p2 = Product(file_path="/t/A3_v2.pdf", file_name="A3_v2.pdf", file_hash="a32", file_size=200, normalized_stem="book3", title="A v2")
    p3 = Product(file_path="/t/A3_Revised.pdf", file_name="A3_Revised.pdf", file_hash="a33", file_size=300, normalized_stem="book3", title="A Rev")
    db.add_all([p1, p2, p3])
    await db.commit()

    groups = await find_revision_candidates(db)
    our_groups = [g for g in groups if g["normalized_stem"] == "book3"]
    assert len(our_groups) == 1
    assert len(our_groups[0]["products"]) == 3


class TestDetermineNewerProduct:
    def test_revision_indicator_wins(self):
        """Product with revision indicator is newer."""
        old = Product(file_path="/t/A.pdf", file_name="A.pdf", file_hash="a1", title="A")
        new = Product(file_path="/t/A_Revised.pdf", file_name="A_Revised.pdf", file_hash="a2", title="A Rev")
        assert determine_newer_product([old, new]) == new

    def test_falls_back_to_file_modified(self):
        """When no indicators, use file_modified_at."""
        old = Product(file_path="/t/A4.pdf", file_name="A4.pdf", file_hash="a41", title="A")
        old.file_modified_at = datetime(2025, 1, 1)
        new = Product(file_path="/t/B4.pdf", file_name="B4.pdf", file_hash="b41", title="B")
        new.file_modified_at = datetime(2026, 1, 1)
        assert determine_newer_product([old, new]) == new

    def test_falls_back_to_created_at(self):
        """When no indicators or mtime, use created_at."""
        old = Product(file_path="/t/A5.pdf", file_name="A5.pdf", file_hash="a51", title="A")
        old.created_at = datetime(2025, 1, 1)
        new = Product(file_path="/t/B5.pdf", file_name="B5.pdf", file_hash="b51", title="B")
        new.created_at = datetime(2026, 1, 1)
        assert determine_newer_product([old, new]) == new


@pytest.mark.asyncio
async def test_mark_revision_candidates(db):
    """Marking sets is_duplicate, duplicate_of_id, duplicate_reason on older products."""
    old = Product(
        file_path="/t/Ravens3.pdf", file_name="Ravens3.pdf", file_hash="aaa3",
        file_size=100, normalized_stem="ravens3", title="Ravens",
    )
    revised = Product(
        file_path="/t/Ravens3_Revised.pdf", file_name="Ravens3_Revised.pdf", file_hash="bbb3",
        file_size=200, normalized_stem="ravens3", title="Ravens Revised",
    )
    db.add_all([old, revised])
    await db.commit()

    count = await mark_revision_candidates(db)
    assert count >= 1

    await db.refresh(old)
    assert old.is_duplicate is True
    assert old.duplicate_of_id == revised.id
    assert old.duplicate_reason == "revision"

    await db.refresh(revised)
    assert revised.is_duplicate is False


@pytest.mark.asyncio
async def test_mark_revision_candidates_idempotent(db):
    """Running twice doesn't double-mark."""
    old = Product(
        file_path="/t/Ravens4.pdf", file_name="Ravens4.pdf", file_hash="aaa4",
        file_size=100, normalized_stem="ravens4", title="Ravens",
    )
    revised = Product(
        file_path="/t/Ravens4_Revised.pdf", file_name="Ravens4_Revised.pdf", file_hash="bbb4",
        file_size=200, normalized_stem="ravens4", title="Ravens Revised",
    )
    db.add_all([old, revised])
    await db.commit()

    count1 = await mark_revision_candidates(db)
    count2 = await mark_revision_candidates(db)
    assert count1 >= 1
    assert count2 == 0  # Already marked, excluded from candidates


@pytest.mark.asyncio
async def test_confirm_revision_transfers_metadata(db):
    """Confirming transfers metadata from old to new where new is empty."""
    old = Product(
        file_path="/t/Ravens5.pdf", file_name="Ravens5.pdf", file_hash="aaa5",
        file_size=100, normalized_stem="ravens5", title="Ravens",
        author="Author A", publisher="Publisher X", game_system="D&D 5e",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/Ravens5_Revised.pdf", file_name="Ravens5_Revised.pdf", file_hash="bbb5",
        file_size=200, normalized_stem="ravens5", title="Ravens Revised",
        author=None, publisher=None, game_system="D&D 5e",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    await confirm_revision(db, old.id)

    await db.refresh(old)
    await db.refresh(new)

    assert new.author == "Author A"
    assert new.publisher == "Publisher X"
    assert new.game_system == "D&D 5e"  # Not overwritten

    assert old.is_superseded is True
    assert old.superseded_by_id == new.id


@pytest.mark.asyncio
async def test_confirm_revision_clears_duplicate_flag(db):
    """After confirming, old product's duplicate flags are cleared (superseded takes over)."""
    old = Product(
        file_path="/t/A6.pdf", file_name="A6.pdf", file_hash="aaa6",
        file_size=100, normalized_stem="a6", title="A",
        is_duplicate=True, duplicate_of_id=None, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/A6_v2.pdf", file_name="A6_v2.pdf", file_hash="bbb6",
        file_size=200, normalized_stem="a6", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    await confirm_revision(db, old.id)

    await db.refresh(old)
    assert old.is_duplicate is False
    assert old.duplicate_of_id is None
    assert old.duplicate_reason is None
    assert old.is_superseded is True


@pytest.mark.asyncio
async def test_dismiss_revision(db):
    """Dismissing clears all duplicate/revision markers."""
    old = Product(
        file_path="/t/A7.pdf", file_name="A7.pdf", file_hash="aaa7",
        file_size=100, normalized_stem="a7", title="A",
        is_duplicate=True, duplicate_reason="revision",
    )
    new = Product(
        file_path="/t/A7_v2.pdf", file_name="A7_v2.pdf", file_hash="bbb7",
        file_size=200, normalized_stem="a7", title="A v2",
    )
    db.add_all([old, new])
    await db.flush()
    old.duplicate_of_id = new.id
    await db.commit()

    await dismiss_revision(db, old.id)

    await db.refresh(old)
    assert old.is_duplicate is False
    assert old.duplicate_of_id is None
    assert old.duplicate_reason is None
    assert old.is_superseded is False


@pytest.mark.asyncio
async def test_cleanup_orphaned_superseded(db):
    """If the newer product is deleted, clear superseded state on old products."""
    old = Product(
        file_path="/t/A8.pdf", file_name="A8.pdf", file_hash="aaa8",
        file_size=100, normalized_stem="a8", title="A",
    )
    newer = Product(
        file_path="/t/A8_v2.pdf", file_name="A8_v2.pdf", file_hash="bbb8",
        file_size=200, normalized_stem="a8", title="A v2",
    )
    db.add_all([old, newer])
    await db.flush()

    old.is_superseded = True
    old.superseded_by_id = newer.id
    await db.commit()

    # Delete the newer product
    await db.delete(newer)
    await db.commit()

    result = await cleanup_orphaned_superseded(db)
    assert result["cleaned"] == 1

    await db.refresh(old)
    assert old.is_superseded is False
    assert old.superseded_by_id is None
