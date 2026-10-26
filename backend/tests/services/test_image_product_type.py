"""Image detection writes the enum and never overwrites a document type.

detect_image_content returns free text ("Map", "Token", "Stock Art"). Written
as is on every re-extraction, it put "Map" back over the enum `map` and over
types the AI run had decided.
"""
from grimoire.services.queue_processor import image_product_type


def test_detected_label_is_written_as_the_enum():
    assert image_product_type(None, "Map") == "map"
    assert image_product_type("", "Token") == "tools"


def test_existing_image_type_is_refreshed_but_document_types_are_kept():
    assert image_product_type("Map", "Map") == "map"
    assert image_product_type("map", "Map") == "map"
    assert image_product_type("gm_tools", "Map") == "gm_tools"
    assert image_product_type("adventure", "Stock Art") == "adventure"


def test_no_label_keeps_the_current_type():
    assert image_product_type("adventure", None) == "adventure"
    assert image_product_type(None, None) is None
