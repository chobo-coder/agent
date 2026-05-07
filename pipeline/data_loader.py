"""S3 parquet loading and merging."""

import pandas as pd

from pipeline import BaseHandler
from core.session import SessionManager
from core.orchestrator import StepResult
from wrappers.s3_wrapper import S3Wrapper


class DataLoaderHandler(BaseHandler):
    """Loads parquet data from S3 and merges with existing data."""

    def __init__(self):
        self._s3 = S3Wrapper()

    def execute(self, session: SessionManager) -> StepResult:
        """Load additional data from S3 and merge."""
        product = session.get_metadata("current_product")
        existing_df = session.get_dataframe("query_result")

        s3_df = self._s3.read_parquet(prefix=f"data/{product}/")
        merged_df = self._merge(existing_df, s3_df)

        return StepResult(
            dataframes={"merged_data": merged_df},
            summary=f"S3에서 {len(s3_df)}건 로딩 후 머지 완료. "
            f"최종 데이터: {merged_df.shape[0]}행 x {merged_df.shape[1]}열",
        )

    def _merge(
        self, existing: pd.DataFrame | None, new: pd.DataFrame
    ) -> pd.DataFrame:
        """Merge existing query result with S3 data."""
        if existing is None:
            return new
        return pd.concat([existing, new], ignore_index=True).drop_duplicates()
