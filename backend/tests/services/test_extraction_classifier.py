"""classify_extraction_failure: permanent (per-product) vs transient (environmental)."""
import pytest
from grimoire.services.extraction_classifier import classify_extraction_failure


@pytest.mark.parametrize("msg", [
    "PDF is encrypted",
    "password required",
    "Cannot open document: FileDataError",
    "corrupt pdf",
    "no text after ocr",
    "Product 5 has no text layer",
])
def test_permanent_signals(msg):
    assert classify_extraction_failure(msg) == "permanent"


@pytest.mark.parametrize("msg", [
    "Connection refused to ollama",
    "tesseract not installed",
    "Read timed out",
    "[Errno 13] Permission denied",
    "429 rate limit",
    "some unrecognised failure",   # unknown -> conservative transient
    "",
    None,
])
def test_transient_or_unknown(msg):
    assert classify_extraction_failure(msg) == "transient"


def test_transient_wins_when_both_present():
    # A permanent-looking word inside an environmental error stays retryable.
    assert classify_extraction_failure("ollama connection: model corrupt?") == "transient"
