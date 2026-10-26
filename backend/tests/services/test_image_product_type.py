"""Image detection never overwrites a document type.

detect_image_content returns free text ("Map", "Token", "Stock Art"). Written
on every re-extraction, it went over types the AI run had decided. The label
itself is canonicalised by the Product validator (test_product_type_validator).
"""
from grimoire.models import Product
from grimoire.services.queue_processor import image_product_type


def test_detected_label_is_stored_by_the_model_rule():
    p = Product(file_path="/t/x.pdf", file_name="x.pdf", file_size=1, file_hash="x")
    p.product_type = image_product_type(p.product_type, "Map")
    assert p.product_type == "map"
    p.product_type = None
    p.product_type = image_product_type(p.product_type, "Token")
    assert p.product_type == "Token"


def test_existing_image_type_is_refreshed_but_document_types_are_kept():
    assert image_product_type("Map", "Map") == "Map"
    assert image_product_type("map", "Token") == "Token"
    assert image_product_type("gm_tools", "Map") == "gm_tools"
    assert image_product_type("adventure", "Stock Art") == "adventure"


def test_no_label_keeps_the_current_type():
    assert image_product_type("adventure", None) == "adventure"
    assert image_product_type(None, None) is None
