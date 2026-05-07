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
        elif item == "low_variance":
            return self._handle_low_variance(df, params)
        elif item == "high_na_columns":
            return self._handle_high_na_columns(df, params)
        elif item == "ttest_filter":
            return self._handle_ttest_filter(df, params)
        elif item == "correlated_pairs":
            return self._handle_correlated_pairs(df, params)
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

    def _handle_low_variance(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """분산이 임계값 미만인 컬럼 제거."""
        threshold = params.get("variance_threshold", 0.01)
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        variances = df[numeric_cols].var()
        keep_cols = variances[variances >= threshold].index.tolist()
        drop_cols = variances[variances < threshold].index.tolist()
        if drop_cols:
            df = df.drop(columns=drop_cols)
        return df

    def _handle_high_na_columns(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """결측치 비율이 임계값 이상인 컬럼 제거."""
        threshold = params.get("na_threshold", 0.5)
        na_ratio = df.isna().mean()
        drop_cols = na_ratio[na_ratio >= threshold].index.tolist()
        if drop_cols:
            df = df.drop(columns=drop_cols)
        return df

    def _handle_ttest_filter(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """타겟 대비 t-test에서 유의하지 않은 컬럼 제거."""
        from scipy import stats
        import schema

        alpha = params.get("alpha", 0.05)
        target = schema.TARGET_COLUMN

        if target not in df.columns:
            return df

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if target in numeric_cols:
            numeric_cols.remove(target)

        # 타겟을 중앙값 기준으로 이진 분할
        median_val = df[target].median()
        group_high = df[df[target] >= median_val]
        group_low = df[df[target] < median_val]

        keep_cols = []
        for col in numeric_cols:
            h = group_high[col].dropna()
            l = group_low[col].dropna()
            if len(h) < 2 or len(l) < 2:
                keep_cols.append(col)
                continue
            _, p_value = stats.ttest_ind(h, l, equal_var=False)
            if p_value < alpha:
                keep_cols.append(col)

        # 비수치형 컬럼 + 타겟 + 유의한 컬럼만 유지
        non_numeric = df.select_dtypes(exclude=[np.number]).columns.tolist()
        final_cols = non_numeric + keep_cols + [target]
        return df[[c for c in final_cols if c in df.columns]]

    def _handle_correlated_pairs(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """상관계수가 임계값 이상인 컬럼 쌍 중 하나를 제거."""
        threshold = params.get("corr_threshold", 0.9)
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        corr_matrix = df[numeric_cols].corr().abs()

        # 상삼각 행렬에서 임계값 이상인 쌍 찾기
        drop_cols = set()
        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                if corr_matrix.iloc[i, j] >= threshold:
                    # 다른 컬럼과의 평균 상관이 더 높은 쪽을 제거
                    col_i = corr_matrix.columns[i]
                    col_j = corr_matrix.columns[j]
                    mean_i = corr_matrix[col_i].mean()
                    mean_j = corr_matrix[col_j].mean()
                    if mean_i > mean_j:
                        drop_cols.add(col_i)
                    else:
                        drop_cols.add(col_j)

        if drop_cols:
            df = df.drop(columns=list(drop_cols))
        return df
