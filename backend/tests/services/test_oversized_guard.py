"""Oversized-PDF guard: pure skip-reason helper + handler flagging + ordering."""
from types import SimpleNamespace

import pytest

from grimoire.services.queue_processor import (
    MAX_EXTRACTION_FILE_MB,
    MAX_EXTRACTION_PAGES,
    _oversized_skip_reason,
)


def test_size_over_limit_returns_reason():
    # 300 MB > 250 MB limit
    p = SimpleNamespace(file_size=300 * 1024 * 1024, page_count=None)
    reason = _oversized_skip_reason(p)
    assert reason is not None
    assert "oversized" in reason
    assert "300 MB" in reason


def test_pages_over_limit_returns_reason_when_page_count_set():
    # Under size limit, but page_count exceeds MAX_EXTRACTION_PAGES
    p = SimpleNamespace(file_size=1 * 1024 * 1024, page_count=MAX_EXTRACTION_PAGES + 1)
    reason = _oversized_skip_reason(p)
    assert reason is not None
    assert "oversized" in reason
    assert str(MAX_EXTRACTION_PAGES + 1) in reason


def test_high_page_count_ignored_when_page_count_none():
    # page_count None means we never opened the file; size alone must decide
    p = SimpleNamespace(file_size=1 * 1024 * 1024, page_count=None)
    assert _oversized_skip_reason(p) is None


def test_both_under_limit_returns_none():
    p = SimpleNamespace(file_size=10 * 1024 * 1024, page_count=200)
    assert _oversized_skip_reason(p) is None


def test_missing_file_size_returns_none():
    # Defensive: file_size None should not raise, and is under limit
    p = SimpleNamespace(file_size=None, page_count=None)
    assert _oversized_skip_reason(p) is None


def test_constants_have_expected_values():
    assert MAX_EXTRACTION_FILE_MB == 250
    assert MAX_EXTRACTION_PAGES == 1000
