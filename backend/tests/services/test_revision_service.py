import pytest
from grimoire.services.revision_service import normalize_stem, has_revision_indicator


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
