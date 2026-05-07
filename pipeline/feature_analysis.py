"""Feature analysis: correlation, importance."""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

from pipeline import BaseHandler
from core.session import SessionManager
from core.orchestrator import StepResult


class FeatureAnalysisHandler(BaseHandler):
    """Performs correlation analysis and feature importance."""

    def execute(self, session: SessionManager) -> StepResult:
        """Analyze features in the preprocessed dataset."""
        df = session.get_dataframe("preprocessed") or session.get_dataframe(
            "query_result"
        )
        if df is None:
            return StepResult(summary="분석할 데이터가 없습니다.")

        numeric_df = df.select_dtypes(include=[np.number])
        corr_matrix = numeric_df.corr()

        fig = self._plot_correlation(corr_matrix)
        top_correlations = self._get_top_correlations(corr_matrix)

        return StepResult(
            dataframes={"correlation_matrix": corr_matrix},
            figures=[fig],
            summary=f"상관분석 완료. 피처 수: {len(numeric_df.columns)}\n"
            f"주요 상관관계:\n{top_correlations}",
        )

    def _plot_correlation(self, corr: pd.DataFrame) -> plt.Figure:
        """Create correlation heatmap."""
        fig, ax = plt.subplots(figsize=(10, 8))
        sns.heatmap(corr, annot=True, fmt=".2f", cmap="coolwarm", ax=ax)
        ax.set_title("Feature Correlation Matrix")
        plt.tight_layout()
        return fig

    def _get_top_correlations(self, corr: pd.DataFrame, n: int = 10) -> str:
        """Get top N strongest correlations."""
        pairs = []
        cols = corr.columns
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                pairs.append((cols[i], cols[j], abs(corr.iloc[i, j])))

        pairs.sort(key=lambda x: x[2], reverse=True)
        lines = [f"  {a} <-> {b}: {v:.3f}" for a, b, v in pairs[:n]]
        return "\n".join(lines)
