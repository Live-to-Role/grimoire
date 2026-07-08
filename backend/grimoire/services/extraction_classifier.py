"""Classify an extraction/identify failure as permanent (per-product) or transient.

Permanent  -> the PDF itself can never be extracted/identified (encrypted, corrupt,
              no text). Safe to flag the product and stop re-queueing.
Transient  -> environmental/config (provider down, tooling missing, I/O). Must stay
              retryable — never flag the product for these.

Conservative by design: only 'permanent' when a permanent signal is present AND no
transient signal is present. Everything else is 'transient'.
"""

PERMANENT_SIGNALS = (
    "encrypted",
    "password",
    "corrupt",
    "damaged",
    "cannot open document",
    "cannot open broken document",
    "filedataerror",
    "format error",
    "no text after ocr",
    "no text layer",
    "no embeddable text",
    "no extractable text",
)

TRANSIENT_SIGNALS = (
    "connection",
    "timeout",
    "timed out",
    "ollama",
    "tesseract",
    "not available",
    "not installed",
    "errno",
    "permission denied",
    "temporarily",
    "rate limit",
    "429",
    "502",
    "503",
)


def classify_extraction_failure(error_message: str | None) -> str:
    """Return 'permanent' or 'transient' for a failure message."""
    msg = (error_message or "").lower()
    if any(sig in msg for sig in TRANSIENT_SIGNALS):
        return "transient"
    if any(sig in msg for sig in PERMANENT_SIGNALS):
        return "permanent"
    return "transient"
