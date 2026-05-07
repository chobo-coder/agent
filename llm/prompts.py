"""Prompt templates for each workflow stage."""

import schema
from core.state_machine import WorkflowState


SYSTEM_PROMPT = """당신은 데이터 분석 어시스턴트입니다.
사용자의 요청을 정확히 이해하고, 지정된 JSON 형식으로만 응답합니다.
추가 설명이나 마크다운 포맷 없이 순수 JSON만 출력하세요."""


class PromptBuilder:
    """Builds prompts for LLM calls at various stages."""

    def build_param_extraction(self, user_input: str, existing_params: dict) -> str:
        """사용자 입력에서 분석 조건 파라미터를 추출하는 프롬프트"""
        cat_info = ""
        if schema.CAT_OPTIONS:
            cat_info = f"\n사용 가능한 카테고리 목록: {schema.CAT_OPTIONS}"

        existing_info = ""
        if existing_params:
            existing_info = f"\n\n이전에 수집된 값 (이미 있는 값은 유지, 새 값이 있으면 덮어쓰기):\n{existing_params}"

        return f"""사용자의 분석 요청에서 다음 파라미터를 추출하세요.

## 추출할 파라미터
- lot_cd: LOT 코드 (영문+숫자 조합, 예: A2401, LOT-2025-001) [필수]
- from_date: 조회 시작일 (YYYY-MM-DD 형식) [필수]
- end_date: 조회 종료일 (YYYY-MM-DD 형식) [필수]
- cat: 분석 카테고리 (문자열) [선택 — 없으면 null]{cat_info}
{existing_info}

## 규칙
- 입력에서 해당 정보를 찾을 수 없으면 null로 표시
- 날짜는 반드시 YYYY-MM-DD 형식으로 변환
- "1월부터 3월까지" → 해당 연도의 01-01 ~ 03-31로 변환
- "최근 3개월" → 오늘 기준 3개월 전 ~ 오늘로 계산
- "지난달" → 지난달 1일 ~ 지난달 말일
- LOT 코드는 원문 그대로 유지 (대문자로 변환)
- 카테고리가 목록에 없어도 사용자가 명시했으면 그대로 추출

## 예시
- "LOT A2401 2025-01-01부터 3월말까지 CAT_B로 분석해줘"
  → {{"lot_cd": "A2401", "from_date": "2025-01-01", "end_date": "2025-03-31", "cat": "CAT_B"}}

- "A2502 지난 분기 CAT_A"
  → {{"lot_cd": "A2502", "from_date": "2025-01-01", "end_date": "2025-03-31", "cat": "CAT_A"}}

- "기간은 2025년 상반기"
  → {{"lot_cd": null, "from_date": "2025-01-01", "end_date": "2025-06-30", "cat": null}}

- "CAT_C로 해줘"
  → {{"lot_cd": null, "from_date": null, "end_date": null, "cat": "CAT_C"}}

## 응답 형식
반드시 아래 JSON만 출력:
{{"lot_cd": "...", "from_date": "...", "end_date": "...", "cat": "..."}}

## 사용자 입력
{user_input}"""

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

## 예시
- "추가 데이터도 가져와줘" → {{"load_additional": true, "reason": "사용자가 추가 로딩 요청"}}
- "이 정도면 충분해" → {{"load_additional": false, "reason": "현재 데이터로 충분"}}
- "S3에 있는 것도 봐야 할 것 같아" → {{"load_additional": true, "reason": "S3 데이터 필요"}}
- "바로 분석 진행해" → {{"load_additional": false, "reason": "즉시 진행 희망"}}

## 규칙
- 반드시 JSON만 출력
- load_additional: boolean
- reason: 판단 근거 (한국어)

## 사용자 입력
{user_input}"""

    def _build_preprocess_decision_prompt(self, user_input: str) -> str:
        return f"""사용자가 전처리할 항목을 선택합니다.

## 가능한 항목
- missing_values: 결측치 처리 (strategy: drop/mean/median/mode)
- outliers: 이상치 제거 (method: iqr/zscore, threshold: 1.5/3.0)
- encoding: 범주형 인코딩 (method: onehot/label)
- scaling: 수치형 스케일링 (method: standard/minmax/robust)
- feature_selection: 피처 선택 (keep_columns: [...])

## 예시
- "결측치 평균으로 채우고 스케일링해줘"
  → {{"items": ["missing_values", "scaling"], "params": {{"missing_strategy": "mean", "scaling_method": "standard"}}}}
- "이상치 제거하고 원핫인코딩 적용"
  → {{"items": ["outliers", "encoding"], "params": {{"outlier_method": "iqr", "encoding_method": "onehot"}}}}
- "전부 다 해줘"
  → {{"items": ["missing_values", "outliers", "encoding", "scaling"], "params": {{}}}}

## 규칙
- 반드시 JSON만 출력
- items: 선택된 항목 리스트
- params: 각 항목의 세부 파라미터

## 사용자 입력
{user_input}"""

    def _build_combination_prompt(self, user_input: str) -> str:
        features_str = ", ".join(schema.AVAILABLE_FEATURES)
        return f"""사용자가 예측에 사용할 피처 조합과 threshold를 지정합니다.

## 사용 가능한 피처
{features_str}

## 예시
- "{schema.AVAILABLE_FEATURES[0]}이랑 {schema.AVAILABLE_FEATURES[1]}로 0.7 기준 예측해줘"
  → {{"features": ["{schema.AVAILABLE_FEATURES[0]}", "{schema.AVAILABLE_FEATURES[1]}"], "threshold": 0.7}}
- "모든 피처 사용하고 임계값 0.5"
  → {{"features": [], "threshold": 0.5}}
- "상관계수 높은 상위 3개로 0.6"
  → {{"features": "top_3_correlated", "threshold": 0.6}}

## 규칙
- 반드시 JSON만 출력
- features: 피처명 리스트 (빈 리스트 = 전체 사용, "top_N_correlated" = 상위 N개 자동 선택)
- threshold: 0.0~1.0 사이 float

## 사용자 입력
{user_input}"""
