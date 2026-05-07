"""Prompt templates for each workflow stage."""

from core.state_machine import WorkflowState


class PromptBuilder:
    """Builds prompts for LLM calls at various stages."""

    def build_product_extraction(self, user_input: str) -> str:
        return f"""사용자의 분석 요청에서 제품명을 추출하세요.
응답은 JSON 형식으로: {{"product": "제품명"}}

사용자 입력: {user_input}"""

    def build_decision_prompt(self, state: WorkflowState, user_input: str) -> str:
        """Build a prompt for decision points."""
        if state == WorkflowState.SHOWING_QUERY_RESULTS:
            return self._build_load_decision_prompt(user_input)
        elif state == WorkflowState.SHOWING_DATA_OVERVIEW:
            return self._build_preprocess_decision_prompt(user_input)
        elif state == WorkflowState.SHOWING_FEATURES:
            return self._build_combination_prompt(user_input)
        return user_input

    def build_summary_prompt(self, raw_summary: str) -> str:
        return f"""다음 분석 결과를 사용자에게 이해하기 쉽게 한국어로 요약하세요.
핵심 인사이트를 중심으로 간결하게 설명하세요.

분석 결과:
{raw_summary}"""

    def _build_load_decision_prompt(self, user_input: str) -> str:
        return f"""사용자가 추가 데이터를 로딩할지 결정합니다.
응답은 JSON: {{"load_additional": true/false, "reason": "..."}}

사용자 입력: {user_input}"""

    def _build_preprocess_decision_prompt(self, user_input: str) -> str:
        return f"""사용자가 전처리할 항목을 선택합니다.
가능한 항목: missing_values, outliers, encoding, scaling, feature_selection
응답은 JSON: {{"items": ["항목1", "항목2"], "params": {{}}}}

사용자 입력: {user_input}"""

    def _build_combination_prompt(self, user_input: str) -> str:
        return f"""사용자가 예측에 사용할 피처 조합과 threshold를 지정합니다.
응답은 JSON: {{"features": ["f1", "f2"], "threshold": 0.5}}

사용자 입력: {user_input}"""
