"""Feature combination + threshold prediction."""

import pandas as pd
import numpy as np

from pipeline import BaseHandler
from core.session import SessionManager
from core.orchestrator import StepResult


class PredictionHandler(BaseHandler):
    """Generates predictions based on feature combinations and thresholds."""

    def execute(self, session: SessionManager) -> StepResult:
        """Run prediction with selected features and threshold."""
        df = session.get_dataframe("preprocessed") or session.get_dataframe(
            "query_result"
        )
        if df is None:
            return StepResult(summary="예측할 데이터가 없습니다.")

        features = session.get_metadata("selected_features", [])
        threshold = session.get_metadata("threshold", 0.5)

        predictions = self._predict(df, features, threshold)

        result_df = df.copy()
        result_df["prediction"] = predictions
        result_df["above_threshold"] = predictions >= threshold

        summary_stats = {
            "total": len(predictions),
            "above_threshold": int((predictions >= threshold).sum()),
            "below_threshold": int((predictions < threshold).sum()),
            "mean_score": float(predictions.mean()),
        }

        return StepResult(
            dataframes={"predictions": result_df},
            summary=f"예측 완료:\n"
            f"  전체: {summary_stats['total']}건\n"
            f"  임계값({threshold}) 이상: {summary_stats['above_threshold']}건\n"
            f"  임계값 미만: {summary_stats['below_threshold']}건\n"
            f"  평균 점수: {summary_stats['mean_score']:.4f}",
            metadata=summary_stats,
        )

    def _predict(
        self, df: pd.DataFrame, features: list[str], threshold: float
    ) -> np.ndarray:
        """Generate prediction scores from feature combination."""
        if not features:
            features = df.select_dtypes(include=[np.number]).columns.tolist()

        feature_df = df[features].select_dtypes(include=[np.number])
        if feature_df.empty:
            return np.zeros(len(df))

        # Normalized mean as simple scoring
        normalized = (feature_df - feature_df.min()) / (
            feature_df.max() - feature_df.min() + 1e-8
        )
        scores = normalized.mean(axis=1).values
        return scores
