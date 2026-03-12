"""Tests for image content classification heuristics."""
import pytest


def test_classify_map_by_filename():
    from grimoire.processors.image_classifier import classify_image_content
    result = classify_image_content("Dungeon Battlemap Pack.pdf", "/maps/battlemap.pdf")
    assert result == "Map"


def test_classify_stock_art_by_filename():
    from grimoire.processors.image_classifier import classify_image_content
    result = classify_image_content("Fantasy Stock Art Collection.pdf", "/art/stock.pdf")
    assert result == "Stock Art"


def test_classify_map_by_folder():
    from grimoire.processors.image_classifier import classify_image_content
    result = classify_image_content("pack_01.pdf", "/rpg/Maps/Caves/pack_01.pdf")
    assert result == "Map"


def test_classify_default_to_stock_art():
    from grimoire.processors.image_classifier import classify_image_content
    result = classify_image_content("unknown_images.pdf", "/rpg/misc/unknown_images.pdf")
    assert result == "Stock Art"


def test_classify_token_by_filename():
    from grimoire.processors.image_classifier import classify_image_content
    result = classify_image_content("NPC Token Pack.pdf", "/tokens/npc.pdf")
    assert result == "Token"
