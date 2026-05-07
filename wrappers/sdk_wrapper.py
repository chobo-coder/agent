"""Adapter for internal database SDK."""

import pandas as pd

import config


class SDKWrapper:
    """Wraps the internal DB SDK for SQL queries."""

    def __init__(self):
        self._api_url = config.SDK_API_URL
        self._api_key = config.SDK_API_KEY

    def execute_query(self, query: str) -> pd.DataFrame:
        """Execute a SQL query and return results as DataFrame.

        TODO: Replace with actual SDK call.
        """
        raise NotImplementedError(
            "Replace with actual SDK integration: "
            "e.g., sdk_client.query(query).to_dataframe()"
        )

    def test_connection(self) -> bool:
        """Verify SDK connectivity."""
        raise NotImplementedError("Replace with actual SDK health check")
