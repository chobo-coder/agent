"""SQL query execution via internal SDK."""

from pipeline import BaseHandler
from core.session import SessionManager
from core.orchestrator import StepResult
from wrappers.sdk_wrapper import SDKWrapper


class DataQueryHandler(BaseHandler):
    """Executes SQL queries against the internal database."""

    def __init__(self):
        self._sdk = SDKWrapper()

    def execute(self, session: SessionManager) -> StepResult:
        """Query data for the specified product."""
        product = session.get_metadata("current_product")
        query = self._build_query(product)
        df = self._sdk.execute_query(query)

        return StepResult(
            dataframes={"query_result": df},
            summary=f"제품 '{product}'에 대해 {len(df)}건의 데이터를 조회했습니다.\n"
            f"컬럼: {list(df.columns)}",
        )

    def _build_query(self, product: str) -> str:
        """Build SQL query for the given product."""
        return f"""
        SELECT *
        FROM analytics.product_data
        WHERE product_name = '{product}'
        ORDER BY created_at DESC
        """
