"""Parse LLM responses into structured data."""

import json
import re
from typing import Any

from core.state_machine import WorkflowState


class ResponseParser:
    """Extracts structured data from LLM text responses."""

    def extract_product(self, response: str) -> str:
        """Extract product name from LLM response."""
        data = self._extract_json(response)
        return data.get("product", "")

    def parse_decision(self, state: WorkflowState, response: str) -> dict[str, Any]:
        """Parse decision response based on current state."""
        return self._extract_json(response)

    def extract_features(self, response: str) -> list[str]:
        """Extract feature list from response."""
        data = self._extract_json(response)
        return data.get("features", [])

    def extract_threshold(self, response: str) -> float:
        """Extract threshold value from response."""
        data = self._extract_json(response)
        return float(data.get("threshold", 0.5))

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract first JSON object from text."""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try regex extraction
        pattern = r"\{[^{}]*\}"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return {}
