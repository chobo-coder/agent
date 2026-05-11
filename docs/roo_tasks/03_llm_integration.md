# Task 03: LLM Integration

## Goal
LLM 클라이언트에 에러 핸들링/재시도 추가, 프롬프트 정확도 개선, 파서 견고성 강화

---

## 현재 상태

- `llm/client.py`: OpenAI SDK 기반 `complete()`, `complete_with_history()`
- `llm/prompts.py`: 5개 프롬프트 빌더 메서드
- `llm/parser.py`: JSON 추출 + regex fallback
- 테스트 6개 통과 (파서)

---

## 추가 구현 필요 사항

### 3-1. LLM 클라이언트 — 에러 핸들링 & 재시도

`llm/client.py`에 추가:

```python
import time
from openai import (
    APITimeoutError,
    RateLimitError,
    APIConnectionError,
)

class LLMClient:
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 2, 4]  # 초 단위 exponential backoff

    def complete(self, prompt: str, system: str | None = None) -> str:
        messages = self._build_messages(prompt, system)
        return self._call_with_retry(messages)

    def _call_with_retry(self, messages: list[dict]) -> str:
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    timeout=30,
                )
                return response.choices[0].message.content or ""
            except (APITimeoutError, APIConnectionError) as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise LLMError(f"API 연결 실패 ({self.MAX_RETRIES}회 재시도): {e}")
                time.sleep(self.RETRY_DELAYS[attempt])
            except RateLimitError as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise LLMError(f"Rate limit 초과: {e}")
                time.sleep(self.RETRY_DELAYS[attempt] * 2)
        return ""

class LLMError(Exception):
    """LLM API 호출 실패"""
    pass
```

### 3-2. 프롬프트 개선 — Few-shot 예시 추가

`llm/prompts.py` 각 빌더에 예시를 포함:

```python
def _build_load_decision_prompt(self, user_input: str) -> str:
    return f"""사용자가 추가 데이터를 로딩할지 결정합니다.

## 예시
- "추가 데이터도 가져와줘" → {{"load_additional": true, "reason": "사용자가 추가 로딩 요청"}}
- "이 정도면 충분해" → {{"load_additional": false, "reason": "현재 데이터로 충분"}}
- "S3에 있는 것도 봐야 할 것 같아" → {{"load_additional": true, "reason": "S3 데이터 필요"}}
- "바로 분석 진행해" → {{"load_additional": false, "reason": "즉시 진행 희망"}}

## 규칙
- 반드시 JSON만 출력 (다른 텍스트 없이)
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
    return f"""사용자가 예측에 사용할 피처 조합과 threshold를 지정합니다.

## 예시
- "feature_a랑 feature_b로 0.7 기준 예측해줘"
  → {{"features": ["feature_a", "feature_b"], "threshold": 0.7}}
- "모든 피처 사용하고 임계값 0.5"
  → {{"features": [], "threshold": 0.5}}
- "상관계수 높은 상위 3개로 0.6"
  → {{"features": "top_3_correlated", "threshold": 0.6}}

## 규칙
- 반드시 JSON만 출력
- features: 피처명 리스트 (빈 리스트 = 전체 사용)
- threshold: 0.0~1.0 사이 float

## 사용자 입력
{user_input}"""
```

### 3-3. 파서 견고성 강화

`llm/parser.py`에 중첩 JSON, 마크다운 코드블록 처리 추가:

```python
import re
import json
from typing import Any


class ResponseParser:
    def _extract_json(self, text: str) -> dict[str, Any]:
        """여러 전략으로 JSON 추출 시도"""
        # 1. 직접 파싱
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # 2. 마크다운 코드블록 내 JSON
        code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 3. 중첩 가능한 JSON 객체 추출
        brace_start = text.find("{")
        if brace_start != -1:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start:i+1])
                        except json.JSONDecodeError:
                            break

        # 4. 단순 regex (flat JSON)
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return {}
```

### 3-4. 시스템 프롬프트 추가

`llm/prompts.py`에 시스템 프롬프트 상수:

```python
SYSTEM_PROMPT = """당신은 데이터 분석 어시스턴트입니다.
사용자의 요청을 정확히 이해하고, 지정된 JSON 형식으로만 응답합니다.
추가 설명이나 마크다운 포맷 없이 순수 JSON만 출력하세요."""
```

`LLMClient.complete()` 호출 시 기본 system 파라미터로 전달.

---

## 테스트 추가

```python
# tests/test_orchestrator.py에 추가

def test_extract_json_from_code_block(self):
    response = '```json\n{"product": "TestProduct"}\n```'
    assert self.parser.extract_product(response) == "TestProduct"

def test_extract_nested_json(self):
    response = '{"items": ["a", "b"], "params": {"strategy": "mean"}}'
    result = self.parser._extract_json(response)
    assert result["params"]["strategy"] == "mean"

def test_extract_from_verbose_response(self):
    response = "분석 결과입니다.\n\n```json\n{\"features\": [\"col_a\"], \"threshold\": 0.8}\n```\n\n위 설정으로 진행하겠습니다."
    assert self.parser.extract_features(response) == ["col_a"]
    assert self.parser.extract_threshold(response) == 0.8
```

---

## 파일 체크리스트

| 파일 | 액션 | 변경 내용 |
|------|------|----------|
| `llm/client.py` | 수정 | retry 로직, LLMError, timeout 추가 |
| `llm/prompts.py` | 수정 | few-shot 예시, SYSTEM_PROMPT 추가 |
| `llm/parser.py` | 수정 | 코드블록/중첩 JSON 파싱 강화 |
| `tests/test_orchestrator.py` | 수정 | 3개 테스트 추가 |

---

## 완료 기준

- [ ] API 타임아웃 시 3회 재시도 후 `LLMError` 발생
- [ ] Rate limit 시 exponential backoff 동작
- [ ] 마크다운 코드블록 내 JSON 정상 추출
- [ ] 중첩 JSON (params 내 dict) 정상 파싱
- [ ] few-shot 프롬프트로 분류 정확도 90% 이상 (수동 테스트 10건)
- [ ] `pytest tests/test_orchestrator.py` 전체 통과

---

## 변경 이력

### 2026-05-07: 파라미터 추출 프롬프트 및 규칙 기반 fallback 추가

**변경 사항:**
- `llm/prompts.py`에 `build_param_extraction()` 메서드 추가 — 사용자 자연어에서 product/date_from/date_to/process를 JSON으로 추출
- `app.py`에 `_extract_params_with_llm()` 함수 추가 — LLM 호출 실패 시 `_parse_params_fallback()` 규칙 기반으로 전환
- `app.py`에 `_parse_params_fallback()` 함수 추가 — regex 기반 파라미터 추출

**새로 추가된 인터페이스:**
```python
# llm/prompts.py
class PromptBuilder:
    def build_param_extraction(self, user_input: str, existing_params: dict) -> str:
        """사용자 입력에서 분석 파라미터 추출 프롬프트 생성.

        Args:
            user_input: 사용자의 자연어 입력
            existing_params: 이전에 수집된 파라미터 (누락 보완용)

        Returns:
            LLM에 전달할 프롬프트 문자열
        """

# app.py — LLM 기반 추출 + fallback
def _extract_params_with_llm(user_input: str, existing_params: dict) -> dict:
    """LLM으로 파라미터 추출. 실패 시 규칙 기반 fallback.

    Returns:
        {"product": str|None, "date_from": str|None, "date_to": str|None, "process": str|None}
    """

def _parse_params_fallback(user_input: str) -> dict:
    """regex 기반 파라미터 추출 (LLM 없이 동작).

    패턴:
    - 날짜: YYYY-MM-DD, N월, N월부터 M월
    - 공정: schema.PROCESS_OPTIONS 매칭
    - 제품: '제품X', 'X제품', 영문 대문자 패턴
    """
```

**기존 코드 수정:**
- `llm/prompts.py:PromptBuilder` — `build_param_extraction` 메서드 추가 (few-shot 예시 포함)

**루코드 구현 시 주의사항:**
- LLM API 키가 없어도 앱이 동작해야 함 (`_parse_params_fallback`이 대체)
- `schema.REQUIRED_PARAMS`의 key 목록과 추출 결과의 key가 일치해야 함
- `schema.PROCESS_OPTIONS`가 비어있으면 공정은 자유 입력으로 처리
- 날짜 파싱에서 "N월" → 해당 연도 N월 1일~말일로 변환하는 로직 포함

### 2026-05-11: LLM 프롬프트 대폭 개선 + 수율 전용 프롬프트 추가

**변경 사항:**
- `llm/prompts.py:build_param_extraction` — 완전 재작성:
  - 추출 파라미터: `lot_cd`, `oper`, `from_date`, `end_date`, `cat`
  - 날짜 형식: YYYYMMDD (하이픈 없이 8자리)
  - `schema.LOT_OPTIONS`, `schema.OPER_OPTIONS` 기반 few-shot 예시 동적 생성
  - 기존 `existing_params` 머지 규칙 명시
  - "1월부터 3월까지", "최근 3개월", "지난달" 등 한국어 날짜 표현 변환 규칙 추가
- `llm/prompts.py:build_yield_param_extraction` — 수율 워크플로우 전용 신규:
  - 추출 파라미터: `lot_cd`(필수), `week`(선택), `oper`(선택), `from_date`(선택), `end_date`(선택)
  - week 형식: YYYY-WNN (예: "2025-W20")
  - "20주차" → "2025-W20", "지난주" → null 변환 규칙
- `llm/prompts.py:_build_combination_prompt` — selections 배열 형식으로 변경:
  - 기존: `{"features": [...], "threshold": float}`
  - 변경: `{"selections": [{"feature": str, "threshold": float|null, "condition": str|null}]}`
  - 피처별 독립 조건/임계값 지정 가능

**새로 추가된 인터페이스:**
```python
# llm/prompts.py
class PromptBuilder:
    def build_yield_param_extraction(self, user_input: str, existing_params: dict) -> str:
        """수율 워크플로우 전용 파라미터 추출 프롬프트.
        추출 결과: {"lot_cd": str, "week": str|null, "oper": str|null, "from_date": str|null, "end_date": str|null}
        """
```

**기존 코드 수정:**
- `llm/prompts.py:build_param_extraction` — 반환 JSON 키가 `lot_cd, oper, from_date, end_date, cat`으로 변경 (기존 product/date_from/date_to 대신)
- `llm/prompts.py:_build_combination_prompt` — 반환 형식이 `{"selections": [...]}` 배열로 변경

**루코드 구현 시 주의사항:**
- `build_param_extraction`의 반환 키가 `schema.REQUIRED_PARAMS`의 key와 일치해야 함
- `build_yield_param_extraction`은 `app.py`에서 `WorkflowType.YIELD_TREND`일 때만 호출됨
- `_build_combination_prompt`의 `selections` 형식 변경에 따라 `_parse_feature_selections()`도 이 형식을 기대함
- `schema.LOT_OPTIONS`가 빈 리스트면 프롬프트에 LOT 예시 없이 표시
- `schema.OPER_OPTIONS`가 빈 리스트면 프롬프트에 공정 목록 없이 표시
