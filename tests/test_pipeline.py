"""Tests for pipeline handlers with mocked wrappers."""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch

from pipeline.data_overview import DataOverviewHandler
from pipeline.preprocessing import PreprocessingHandler
from pipeline.feature_analysis import FeatureAnalysisHandler
from pipeline.prediction import PredictionHandler


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "feature_a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "feature_b": [10.0, 20.0, 30.0, 40.0, 50.0],
            "category": ["A", "B", "A", "B", "A"],
        }
    )


@pytest.fixture
def mock_session(sample_df):
    session = MagicMock()
    session.get_dataframe.return_value = sample_df
    session.get_metadata.return_value = []
    return session


class TestDataOverview:
    def test_execute(self, mock_session):
        handler = DataOverviewHandler()
        result = handler.execute(mock_session)
        assert result.summary
        assert "overview_stats" in result.dataframes

    def test_no_data(self):
        session = MagicMock()
        session.get_dataframe.return_value = None
        handler = DataOverviewHandler()
        result = handler.execute(session)
        assert "없습니다" in result.summary


class TestPreprocessing:
    def test_missing_drop(self, sample_df):
        handler = PreprocessingHandler()
        df_with_na = sample_df.copy()
        df_with_na.loc[0, "feature_a"] = np.nan

        session = MagicMock()
        session.get_dataframe.return_value = df_with_na
        session.get_metadata.side_effect = lambda k, d=None: {
            "preprocess_items": ["missing_values"],
            "preprocess_params": {"missing_strategy": "drop"},
        }.get(k, d)

        result = handler.execute(session)
        assert len(result.dataframes["preprocessed"]) == 4

    def test_encoding(self, sample_df):
        handler = PreprocessingHandler()
        session = MagicMock()
        session.get_dataframe.return_value = sample_df
        session.get_metadata.side_effect = lambda k, d=None: {
            "preprocess_items": ["encoding"],
            "preprocess_params": {},
        }.get(k, d)

        result = handler.execute(session)
        df = result.dataframes["preprocessed"]
        assert "category" not in df.columns


class TestFeatureAnalysis:
    def test_execute(self, mock_session):
        handler = FeatureAnalysisHandler()
        result = handler.execute(mock_session)
        assert "correlation_matrix" in result.dataframes
        assert len(result.figures) == 1


class TestPrediction:
    def test_execute(self, mock_session, sample_df):
        mock_session.get_metadata.side_effect = lambda k, d=None: {
            "selected_features": ["feature_a", "feature_b"],
            "threshold": 0.5,
        }.get(k, d)

        handler = PredictionHandler()
        result = handler.execute(mock_session)
        assert "predictions" in result.dataframes
        assert "prediction" in result.dataframes["predictions"].columns
