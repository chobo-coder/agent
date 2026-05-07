"""Tests for the LLM response parser."""

import pytest

from llm.parser import ResponseParser


class TestResponseParser:
    def setup_method(self):
        self.parser = ResponseParser()

    def test_extract_product_clean_json(self):
        response = '{"product": "ProductX"}'
        assert self.parser.extract_product(response) == "ProductX"

    def test_extract_product_from_text(self):
        response = 'Here is the result: {"product": "WidgetA"} as requested.'
        assert self.parser.extract_product(response) == "WidgetA"

    def test_extract_product_empty(self):
        response = "I could not determine the product."
        assert self.parser.extract_product(response) == ""

    def test_parse_load_decision(self):
        from core.state_machine import WorkflowState

        response = '{"load_additional": true, "reason": "need more data"}'
        result = self.parser.parse_decision(
            WorkflowState.SHOWING_QUERY_RESULTS, response
        )
        assert result["load_additional"] is True

    def test_extract_features(self):
        response = '{"features": ["col_a", "col_b"], "threshold": 0.7}'
        assert self.parser.extract_features(response) == ["col_a", "col_b"]
        assert self.parser.extract_threshold(response) == 0.7

    def test_malformed_json_fallback(self):
        response = "not json at all"
        assert self.parser.extract_product(response) == ""
