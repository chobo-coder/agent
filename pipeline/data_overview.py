"""Data overview and summary statistics."""

import pandas as pd

from pipeline import BaseHandler
from core.session import SessionManager
from core.orchestrator import StepResult


class DataOverviewHandler(BaseHandler):
    """Generates summary statistics and data overview."""

    def execute(self, session: SessionManager) -> StepResult:
        """Produce data overview for the current dataset."""
        df = session.get_dataframe("merged_data") or session.get_dataframe(
            "query_result"
        )
        if df is None:
            return StepResult(summary="데이터가 없습니다.")

        summary_parts = [
            f"데이터 크기: {df.shape[0]}행 x {df.shape[1]}열",
            f"결측치 비율:\n{(df.isnull().sum() / len(df) * 100).to_string()}",
            f"수치형 컬럼 통계:\n{df.describe().to_string()}",
        ]

        return StepResult(
            dataframes={"overview_stats": df.describe()},
            summary="\n\n".join(summary_parts),
        )
