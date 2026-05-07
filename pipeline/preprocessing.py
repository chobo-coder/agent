"""Data preprocessing pipeline."""

import pandas as pd
import numpy as np

from pipeline import BaseHandler
from core.session import SessionManager
from core.orchestrator import StepResult


class PreprocessingHandler(BaseHandler):
    """Executes selected preprocessing steps."""

    def execute(self, session: SessionManager) -> StepResult:
        """Apply preprocessing based on user-selected items."""
        df = (
            session.get_dataframe("merged_data")
            or session.get_dataframe("query_result")
        ).copy()

        items = session.get_metadata("preprocess_items", [])
        params = session.get_metadata("preprocess_params", {})

        for item in items:
            df = self._apply(df, item, params)

        return StepResult(
            dataframes={"preprocessed": df},
            summary=f"전처리 완료: {items}\n"
            f"결과 데이터: {df.shape[0]}행 x {df.shape[1]}열",
        )

    def _apply(self, df: pd.DataFrame, item: str, params: dict) -> pd.DataFrame:
        """Apply a single preprocessing step."""
        if item == "missing_values":
            return self._handle_missing(df, params)
        elif item == "outliers":
            return self._handle_outliers(df, params)
        elif item == "encoding":
            return self._handle_encoding(df, params)
        elif item == "scaling":
            return self._handle_scaling(df, params)
        elif item == "feature_selection":
            return self._handle_feature_selection(df, params)
        return df

    def _handle_missing(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Handle missing values."""
        strategy = params.get("missing_strategy", "drop")
        if strategy == "drop":
            return df.dropna()
        elif strategy == "mean":
            return df.fillna(df.mean(numeric_only=True))
        elif strategy == "median":
            return df.fillna(df.median(numeric_only=True))
        return df

    def _handle_outliers(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Remove outliers using IQR method."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            q1 = df[col].quantile(0.25)
            q3 = df[col].quantile(0.75)
            iqr = q3 - q1
            mask = (df[col] >= q1 - 1.5 * iqr) & (df[col] <= q3 + 1.5 * iqr)
            df = df[mask]
        return df

    def _handle_encoding(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Encode categorical variables."""
        cat_cols = df.select_dtypes(include=["object", "category"]).columns
        return pd.get_dummies(df, columns=cat_cols)

    def _handle_scaling(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Scale numeric features."""
        from sklearn.preprocessing import StandardScaler

        numeric_cols = df.select_dtypes(include=[np.number]).columns
        scaler = StandardScaler()
        df[numeric_cols] = scaler.fit_transform(df[numeric_cols])
        return df

    def _handle_feature_selection(
        self, df: pd.DataFrame, params: dict
    ) -> pd.DataFrame:
        """Select features based on parameters."""
        keep_cols = params.get("keep_columns")
        if keep_cols:
            return df[keep_cols]
        return df
