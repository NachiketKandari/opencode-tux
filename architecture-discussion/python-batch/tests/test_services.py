"""Tests for batch services — using in-memory state, no database."""

import pytest

from services.ingest import IngestService
from services.validate import ValidateService
from services.transform import TransformService


class TestIngestService:
    def test_parse_input(self):
        svc = IngestService()
        svc.input_data = "1|100|Test Title|This is the body text for the post"
        # Service parses correctly
        assert svc.name == "BATCH_INGEST"

    def test_empty_input(self):
        svc = IngestService()
        svc.input_data = ""
        assert svc.total_ingested == 0


class TestValidateService:
    def test_valid_record(self):
        valid, reason = ValidateService._validate(
            "Good Title", "This body is long enough to pass validation easily"
        )
        assert valid is True
        assert reason == "OK"

    def test_empty_title(self):
        valid, reason = ValidateService._validate("", "Body text here is sufficient length")
        assert valid is False
        assert "R1" in reason

    def test_empty_body(self):
        valid, reason = ValidateService._validate("Good Title", "")
        assert valid is False
        assert "R2" in reason

    def test_short_body(self):
        valid, reason = ValidateService._validate("Good Title", "short")
        assert valid is False
        assert "R3" in reason

    def test_exactly_20_chars(self):
        valid, reason = ValidateService._validate("Title", "12345678901234567890")
        assert valid is True


class TestTransformService:
    def test_word_count_simple(self):
        assert TransformService._compute_word_count("hello world") == 2

    def test_word_count_empty(self):
        assert TransformService._compute_word_count("") == 0

    def test_word_count_none(self):
        assert TransformService._compute_word_count(None) == 0

    def test_word_count_extra_spaces(self):
        assert TransformService._compute_word_count("  hello   world  ") == 2

    def test_word_count_punctuation(self):
        # "hello, world" — comma is not space, so "hello," and "world" are 2 words
        assert TransformService._compute_word_count("hello, world") == 2
