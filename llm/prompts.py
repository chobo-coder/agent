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
        lot_info = ""
        if schema.LOT_OPTIONS:
            lot_info = f"\n사용 가능한 LOT 코드 예시: {schema.LOT_OPTIONS}"

        oper_info = ""
        if schema.OPER_OPTIONS:
            oper_info = f"\n사용 가능한 공정 목록: {schema.OPER_OPTIONS}"

        cat_info = ""  # cat은 자유 입력 (cat1, cat2 등)

        existing_info = ""
        if existing_params:
            existing_info = f"\n\n이전에 수집된 값 (이미 있는 값은 유지, 새 값이 있으면 덮어쓰기):\n{existing_params}"

        return f"""사용자의 분석 요청에서 다음 파라미터를 추출하세요.

## 추출할 파라미터
- lot_cd: LOT 코드 (영문+숫자 조합, 3글자) [필수]{lot_info}
- oper: 공정(OPER) 코드 [필수]{oper_info}
- from_date: 조회 시작일 (YYYYMMDD 형식, 하이픈 없이 8자리) [필수]
- end_date: 조회 종료일 (YYYYMMDD 형식, 하이픈 없이 8자리) [필수]
- cat: 분석 카테고리 (예: "cat1", "cat2") [선택 — 없으면 null]{cat_info}
{existing_info}

## 규칙
- 입력에서 해당 정보를 찾을 수 없으면 null로 표시
- 날짜는 반드시 YYYYMMDD 형식으로 변환 (하이픈/슬래시/점 없이 8자리 숫자)
  - "2025-01-01" → "20250101"
  - "2025/03/31" → "20250331"
  - "2025.06.30" → "20250630"
- "1월부터 3월까지" → 해당 연도의 20250101 ~ 20250331로 변환
- "최근 3개월" → 오늘 기준 3개월 전 ~ 오늘로 계산
- "지난달" → 지난달 1일 ~ 지난달 말일
- LOT 코드는 원문 그대로 유지 (대문자로 변환)
- 카테고리가 목록에 없어도 사용자가 명시했으면 그대로 추출

## 예시
- "LOT *** *** 2025-01-01부터 3월말까지 cat2로 분석해줘"
  → {{"lot_cd": "***", "oper": "***", "from_date": "20250101", "end_date": "20250331", "cat": "cat2"}}

- "*** *** 지난 분기 cat1"
  → {{"lot_cd": "***", "oper": "***", "from_date": "20250101", "end_date": "20250331", "cat": "cat1"}}

- "기간은 2025년 상반기 ***"
  → {{"lot_cd": null, "oper": "***", "from_date": "20250101", "end_date": "20250630", "cat": null}}

- "*** 20250401 20250630"
  → {{"lot_cd": "***", "oper": null, "from_date": "20250401", "end_date": "20250630", "cat": null}}

- "cat3으로 해줘"
  → {{"lot_cd": null, "oper": null, "from_date": null, "end_date": null, "cat": "cat3"}}

## 응답 형식
반드시 아래 JSON만 출력:
{{"lot_cd": "...", "oper": "...", "from_date": "YYYYMMDD", "end_date": "YYYYMMDD", "cat": "..."}}

## 사용자 입력
{user_input}"""

    def build_yield_param_extraction(self, user_input: str, existing_params: dict) -> str:
        """수율 경향성 워크플로우용 파라미터 추출 프롬프트"""
        lot_info = ""
        if schema.LOT_OPTIONS:
            lot_info = f"\n사용 가능한 LOT 코드 예시: {schema.LOT_OPTIONS}"

        oper_info = ""
        if schema.OPER_OPTIONS:
            oper_info = f"\n사용 가능한 공정 목록: {schema.OPER_OPTIONS}"

        existing_info = ""
        if existing_params:
            existing_info = f"\n\n이전에 수집된 값 (이미 있는 값은 유지, 새 값이 있으면 덮어쓰기):\n{existing_params}"

        return f"""사용자의 수율 경향성 분석 요청에서 다음 파라미터를 추출하세요.

## 추출할 파라미터
- lot_cd: LOT 코드 (영문+숫자 조합) [필수]{lot_info}
- week: 조회 주차 (YYYY-WNN 형식, 예: "2025-W20") [선택 — 없으면 null]
- oper: 공정(OPER) 코드 [선택 — 없으면 전체 공정 조회]{oper_info}
- from_date: 시작일 (YYYYMMDD 형식) [선택 — 특정 날짜 범위 지정 시]
- end_date: 종료일 (YYYYMMDD 형식) [선택 — 특정 날짜 범위 지정 시]
{existing_info}

## 규칙
- lot_cd만 필수, 나머지는 선택
- week를 명시하지 않고 날짜도 없으면 week는 null (기본값으로 전주 사용)
- "20주차", "W20" → "2025-W20" 형식으로 변환 (올해 기준)
- "지난주", "전주" → null (코드에서 전주로 자동 처리)
- 날짜는 YYYYMMDD 형식 (하이픈 없이 8자리)
- LOT 코드는 원문 그대로 유지 (대문자로 변환)

## 예시
- "LOT001 트렌드 확인해줘"
  → {{"lot_cd": "LOT001", "week": null, "oper": null, "from_date": null, "end_date": null}}

- "LOT001 20주차 트렌드"
  → {{"lot_cd": "LOT001", "week": "2025-W20", "oper": null, "from_date": null, "end_date": null}}

- "LOT001 OP1 지난주"
  → {{"lot_cd": "LOT001", "week": null, "oper": "OP1", "from_date": null, "end_date": null}}

- "LOT001 5월 1일부터 5월 10일까지"
  → {{"lot_cd": "LOT001", "week": null, "oper": null, "from_date": "20250501", "end_date": "20250510"}}

## 응답 형식
반드시 아래 JSON만 출력:
{{"lot_cd": "...", "week": "...", "oper": "...", "from_date": "...", "end_date": "..."}}

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
        f0, f1 = schema.AVAILABLE_FEATURES[0], schema.AVAILABLE_FEATURES[1]
        return f"""사용자가 예측에 사용할 피처별 조건(condition)과 임계값(threshold)을 지정합니다.
각 피처마다 독립적인 조건/임계값을 가질 수 있습니다.

## 사용 가능한 피처
{features_str}

## 예시
- "{f0} >= 0.7 조건으로 예측해줘"
  → {{"selections": [{{"feature": "{f0}", "threshold": 0.7, "condition": ">="}}]}}
- "{f0} >= 0.7, {f1} <= 0.3 조건으로 예측해줘"
  → {{"selections": [{{"feature": "{f0}", "threshold": 0.7, "condition": ">="}}, {{"feature": "{f1}", "threshold": 0.3, "condition": "<="}}]}}
- "{f0}, {f1}로 예측해줘"
  → {{"selections": [{{"feature": "{f0}", "threshold": null, "condition": null}}, {{"feature": "{f1}", "threshold": null, "condition": null}}]}}
- "{f0}이랑 {f1}로 0.7 기준 예측해줘"
  → {{"selections": [{{"feature": "{f0}", "threshold": 0.7, "condition": null}}, {{"feature": "{f1}", "threshold": 0.7, "condition": null}}]}}

## 규칙
- 반드시 JSON만 출력
- selections: 피처별 조건 배열. 각 항목은 {{"feature": str, "threshold": float|null, "condition": str|null}}
- threshold: 사용자가 **명시적으로 임계값을 지정한 경우에만** 0.0~1.0 float 값. 없으면 null.
- condition: ">=" 또는 "<=" (명시한 경우만, 아니면 null)

## 사용자 입력
{user_input}"""
