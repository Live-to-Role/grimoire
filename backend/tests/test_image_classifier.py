"""Tests for image content classification heuristics."""
import pytest

from grimoire.processors.image_classifier import (
    classify_by_name,
    _has_book_indicators,
    _normalize_for_matching,
    matches_image_publisher,
)


def test_classify_map_by_filename():
    result = classify_by_name("Dungeon Battlemap Pack.pdf", "/maps/battlemap.pdf")
    assert result == "Map"


def test_classify_stock_art_by_filename():
    result = classify_by_name("Fantasy Stock Art Collection.pdf", "/art/stock.pdf")
    assert result == "Stock Art"


def test_classify_map_by_folder():
    result = classify_by_name("pack_01.pdf", "/rpg/Maps/Caves/pack_01.pdf")
    assert result == "Map"


def test_classify_no_default():
    """Unknown files should return None, not default to Stock Art."""
    result = classify_by_name("unknown_images.pdf", "/rpg/misc/unknown_images.pdf")
    assert result is None


def test_classify_token_by_filename():
    result = classify_by_name("NPC Token Pack.pdf", "/tokens/npc.pdf")
    assert result == "Token"


def test_book_indicators_detected():
    """Regular RPG books should be flagged as books."""
    assert _has_book_indicators("Tome_of_Adventure_Volume_4.pdf", "/rpg/")
    assert _has_book_indicators("Players Guide.pdf", "/rpg/")
    assert _has_book_indicators("Campaign Setting.pdf", "/rpg/")


def test_book_indicators_not_on_art():
    """Image content filenames should NOT trigger book indicators."""
    assert not _has_book_indicators("Battlemap Pack.pdf", "/maps/")
    assert not _has_book_indicators("Stock Art Collection.pdf", "/art/")


def test_false_positives_from_user_report():
    """These were incorrectly classified as Stock Art — should return None."""
    cases = [
        ("Tome_of_Adventure_Volume_4_Purple_Planet_PDF.pdf", "/rpg/dcc/"),
        ("DCC91.1Barako.pdf", "/rpg/dcc/"),
        ("Silam3-TheGalleriesofVarsu-DigitalMaster.pdf", "/rpg/"),
        ("Crowdfund_Your_Fking_Life_-_Second_Edition.pdf", "/rpg/"),
    ]
    for filename, path in cases:
        result = classify_by_name(filename, path)
        # These should NOT match any image content pattern
        # DCC91.1Barako and Silam3 have no image keywords
        # Tome has "volume" but that's a book indicator
        # Crowdfund has "edition" but that's a book indicator
        if result is not None:
            pytest.fail(f"{filename} was classified as '{result}' but should be None")


def test_normalize_splits_camelcase():
    assert _normalize_for_matching("HeroicMaps") == "Heroic Maps"


def test_normalize_treats_separators_as_spaces():
    assert _normalize_for_matching("Village_tiles-pack") == "Village tiles pack"


def test_normalize_leaves_plain_words():
    assert _normalize_for_matching("forest river") == "forest river"


def test_publisher_match_on_folder_path():
    # Real DB path form: folder 'Heroic Maps', filename 'HeroicMaps_*'
    assert matches_image_publisher(
        "HeroicMaps_FireWyrm_GRID.pdf",
        r"D:\Drivethrurpg\Heroic Maps\HeroicMaps_FireWyrm_GRID.pdf",
    )


def test_publisher_match_camelcase_filename_only():
    # Even without the folder, the camelCase filename normalizes to a hit
    assert matches_image_publisher("HeroicMaps_Cliffs.pdf", "/misc/HeroicMaps_Cliffs.pdf")


def test_publisher_match_0one_games():
    assert matches_image_publisher("dungeon.pdf", r"D:\Drivethrurpg\0one Games\dungeon.pdf")


def test_publisher_no_match_regular_book():
    assert not matches_image_publisher(
        "Players_Handbook.pdf", r"D:\Drivethrurpg\Wizards\Players_Handbook.pdf"
    )
