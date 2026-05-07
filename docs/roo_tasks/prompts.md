# Roo Code 프롬프트 모음

각 태스크별로 루코드에 복사-붙여넣기할 프롬프트입니다.
순서대로 실행하세요.

---

## Task 01: Project Setup

```
프로젝트 환경 설정을 완료해줘.

1. `.env.example` 파일 생성:
   - LLM_API_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS
   - S3_BUCKET, S3_REGION
   - SDK_API_URL, SDK_API_KEY
   - CHECKPOINT_DIR
   각 값은 placeholder로 채워줘.

2. `.gitignore` 파일 생성:
   - .env, .checkpoints/, __pycache__/, *.pyc, .pytest_cache/, .venv/

3. `requirements.txt`에 있는 패키지들이 정상 import 되는지 확인하는 스크립트 `scripts/check_env.py` 만들어줘. 각 패키지를 import하고 성공/실패를 출력하면 돼.

4. `streamlit run app.py` 실행했을 때 에러 없이 뜨는지 확인하고, 에러가 있으면 수정해줘.
```

---

## Task 02: State Machine 보완

```
`core/state_machine.py`의 StateMachine 클래스에 다음 기능을 추가해줘:

1. **상태 이력 추적**: `_history: list[WorkflowState]` 필드 추가. 초기값 `[WorkflowState.IDLE]`. `transition_to()` 호출마다 history에 append.

2. **rollback()**: 마지막 전이를 취소하고 이전 상태로 복귀. history가 1개 이하면 무시.

3. **progress_percent property**: 현재 상태가 전체 WorkflowState enum에서 몇 번째인지 비율로 반환 (0.0~1.0).

4. **직렬화**: `to_dict()` → {"state": "STATE_NAME", "history": ["STATE1", "STATE2"]}, `from_dict(data)` classmethod로 복원.

5. `tests/test_state_machine.py`에 다음 테스트 추가:
   - test_history_tracking: 2번 전이 후 history 길이 3, 순서 확인
   - test_rollback: 전이 후 rollback하면 이전 상태
   - test_rollback_at_idle: IDLE에서 rollback은 무시
   - test_progress_percent: IDLE=0.0, COMPLETED=1.0
   - test_serialization_roundtrip: to_dict → from_dict 후 상태 동일

기존 테스트가 깨지지 않게 해줘. `pytest tests/test_state_machine.py -v`로 전체 통과 확인.
```

---

## Task 03: LLM Integration 강화

```
LLM 모듈을 개선해줘. 3개 파일 수정:

### 1. `llm/client.py` — 재시도 로직 추가

- openai의 APITimeoutError, RateLimitError, APIConnectionError를 catch
- 최대 3회 재시도, delay는 [1, 2, 4]초 (exponential backoff)
- 모든 재시도 실패 시 `LLMError` 예외 raise
- `LLMError` 클래스를 같은 파일에 정의
- `complete()` 메서드에서 timeout=30 파라미터 추가

### 2. `llm/prompts.py` — few-shot 예시 추가

각 분기점 프롬프트에 2~4개의 예시를 포함해줘:

- `_build_load_decision_prompt`: "추가 데이터 가져와" → true, "충분해" → false 등
- `_build_preprocess_decision_prompt`: "결측치 평균으로 채우고 스케일링" → items+params 예시
- `_build_combination_prompt`: "feature_a, feature_b로 0.7" → features+threshold 예시

또한 SYSTEM_PROMPT 상수 추가: "JSON만 출력하라"는 지시를 담아줘.
`build_product_extraction`과 `build_summary_prompt`에도 예시 1개씩 추가.

### 3. `llm/parser.py` — 파싱 전략 강화

`_extract_json` 메서드의 파싱 순서:
1. 직접 json.loads
2. ```json 코드블록 내 추출
3. 중첩 JSON (brace depth counting)
4. flat regex fallback

### 4. 테스트 추가 (`tests/test_orchestrator.py`)

- test_json_in_markdown_code_block
- test_nested_json_with_params
- test_json_with_surrounding_korean_text

`pytest tests/test_orchestrator.py -v` 전체 통과 확인.
```

---

## Task 04: Pipeline 실제 구현

```
파이프라인 핸들러와 wrapper를 실제 동작하도록 구현해줘.

### 1. `wrappers/sdk_wrapper.py`

실제 SDK 연동 전까지 mock 데이터를 반환하도록 구현:
- execute_query(): 100행짜리 DataFrame 반환 (product_name, date, metric_a, metric_b, metric_c, category 컬럼)
- numpy random으로 생성, seed=42 고정
- test_connection(): True 반환

### 2. `wrappers/s3_wrapper.py`

실제 S3 연동 전까지 mock:
- read_parquet(): 50행짜리 DataFrame 반환 (동일 스키마, 다른 seed)
- list_files(): 빈 리스트 반환
- DataNotFoundError 예외 클래스 추가

### 3. `pipeline/data_loader.py`

_merge() 개선:
- 공통 키(date, product_name)가 있으면 merge, 없으면 concat
- 중복 제거 + reset_index

### 4. `pipeline/preprocessing.py`

_handle_outliers에 zscore 방식 추가 (params에서 "outlier_method": "zscore" 받으면 scipy.stats.zscore 사용).
_handle_scaling에 minmax, robust 방식 추가.

### 5. `pipeline/feature_analysis.py`

execute()에 피처 중요도 계산 추가:
- RandomForestClassifier(n_estimators=100) 사용
- 마지막 수치형 컬럼을 target으로 (median 기준 이진분류)
- 결과를 "feature_importance" DataFrame으로 StepResult에 추가

### 6. 테스트 (`tests/test_pipeline.py`)

- mock_session fixture의 get_metadata를 side_effect로 변경하여 키별 다른 값 반환
- TestPreprocessing: missing_mean, missing_drop, outlier_iqr, scaling_minmax 테스트
- TestPrediction: scores 범위 0~1, 빈 features시 전체 사용
- TestFeatureAnalysis: correlation matrix가 정방행렬, 값 범위 -1~1

`pytest tests/test_pipeline.py -v` 전체 통과 확인.
```

---

## Task 05: Chat UI 완성

```
Streamlit UI를 완성해줘.

### 1. `core/session.py`에 `add_rich_message` 메서드 추가

```python
def add_rich_message(self, role, content, step_result=None, widget=None):
    msg = {
        "role": role,
        "content": content,
        "df_keys": list(step_result.dataframes.keys()) if step_result else [],
        "has_figures": bool(step_result and step_result.figures),
        "widget": widget,
        "state": self.current_state.name,
    }
    st.session_state.chat_history.append(msg)
```

### 2. `ui/chat.py` 수정

render_chat_history()에서:
- msg에 "df_keys"가 있으면 st.expander로 해당 DataFrame 표시
- msg에 "widget"이 있고 마지막 메시지이면 위젯 렌더링
- 위젯 종류: "yes_no" (버튼 2개), "multi_select", "slider_confirm"

render_sidebar()에서:
- st.progress() 바 추가 (state_machine.progress_percent 사용)
- 각 상태를 한국어 라벨로 표시
- 현재 분석 제품명 표시
- 저장된 DataFrame 목록과 shape 표시

### 3. `app.py` 수정

- 에러 발생 시 st.error()로 표시 + 복구 안내
- 동일 입력 중복 처리 방지 (마지막 user 메시지와 비교)
- step_result의 figures가 있으면 st.pyplot으로 표시
- step_result의 dataframes가 있으면 expander로 표시

### 4. `ui/chat.py`에 `render_error(error, state_name)` 함수 추가

st.error()로 에러 표시 + "다시 요청" / "처음부터" 안내 텍스트.

`streamlit run app.py` 실행해서 에러 없이 뜨는지 확인.
```

---

## Task 06: Orchestrator 통합

```
Orchestrator에 에러 핸들링과 분기점 로직을 완성해줘.

### 1. `core/orchestrator.py` — handle_input에 try-except 추가

```python
def handle_input(self, user_input: str) -> StepResult:
    try:
        # 기존 로직...
    except LLMError as e:
        return StepResult(summary=f"LLM 호출 실패: {e}\n다시 시도해주세요.", metadata={"error": True})
    except Exception as e:
        self.session.state_machine.rollback()
        return StepResult(summary=f"오류 발생: {e}\n이전 단계로 돌아갑니다.", metadata={"error": True})
```

### 2. `_store_decision` 메서드 추가

분기점에서 LLM이 파싱한 결과를 session metadata에 저장:
- SHOWING_QUERY_RESULTS: "load_decision" 저장
- SHOWING_DATA_OVERVIEW: "preprocess_items"와 "preprocess_params" 저장
- SHOWING_FEATURES: "selected_features"와 "threshold" 저장

"top_3_correlated" 같은 문자열이 features에 오면, correlation_matrix에서 상관계수 합 기준 상위 N개 피처명으로 변환하는 `_resolve_top_features(spec)` 메서드도 추가.

### 3. `core/checkpoints.py`에 `load_all(state)` 메서드 추가

해당 state 디렉토리의 모든 .parquet 파일을 dict[str, DataFrame]으로 반환.

### 4. `resume_from_checkpoint(state)` 메서드 추가

load_all로 DataFrame 복원 → session에 저장 → state_machine 상태 직접 설정.

### 5. `app.py`에 중복 실행 방지

마지막 user 메시지와 동일한 입력이면 st.stop().

### 6. 테스트 (`tests/test_integration.py` 신규 생성)

- test_start_workflow: "ProductA 분석" → state가 QUERYING_DATA 이후로 전이
- test_llm_error_keeps_state: LLMError 발생 시 상태 유지
- test_pipeline_error_rollback: handler 에러 시 이전 상태로 복귀

`pytest tests/ -v` 전체 통과 확인.
```

---

## Task 07: Testing 완성

```
테스트를 완성하고 전체 통과를 확인해줘.

### 1. `tests/conftest.py` 생성

공통 fixtures:
- sample_df: 50행, 6컬럼 (product_name, date, metric_a, metric_b, metric_c, category), seed=42
- sample_df_with_nulls: sample_df에서 metric_a 0~4행, metric_b 10~12행 NaN
- mock_session: MagicMock, get_dataframe은 sample_df 반환
- mock_llm_client: MagicMock, complete은 '{"product": "ProductA"}' 반환

### 2. `pytest.ini` 생성

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

### 3. 각 테스트 파일에서 conftest의 fixture 사용하도록 리팩터링

기존 test_pipeline.py의 sample_df fixture를 conftest로 이동. 중복 제거.

### 4. 누락된 테스트 추가

test_state_machine.py:
- test_history_tracking, test_rollback, test_progress_percent, test_serialization

test_orchestrator.py:
- test_json_in_code_block, test_nested_json, test_korean_json, test_boolean_parsing

test_pipeline.py:
- test_missing_mean, test_outlier_iqr, test_scaling_minmax, test_encoding_removes_cat
- test_prediction_score_range, test_correlation_matrix_square

test_integration.py:
- test_start_workflow, test_llm_error, test_pipeline_error_rollback

### 5. 전체 실행

`pytest tests/ -v` 실행해서 전체 통과 확인.
실패하는 테스트가 있으면 코드를 수정해서 통과시켜줘.
```

---

## 사용 방법

1. 루코드를 열고 프로젝트 루트(`/Users/hyeonjaeyeol/agent`)를 워크스페이스로 설정
2. 위 프롬프트를 **순서대로** 하나씩 복사하여 루코드에 입력
3. 각 태스크 완료 후 테스트가 통과하는지 확인한 뒤 다음으로 진행
4. Task 01 → 02 → 03 → 04 → 05 → 06 → 07 순서 필수 (의존성 있음)

---

## 주의사항

- 각 프롬프트는 독립적으로 실행 가능하지만, 이전 태스크의 코드가 있어야 동작
- 루코드가 파일을 수정하면 `git diff`로 변경 확인 후 커밋
- 사내 SDK/S3 실제 연동은 mock으로 대체한 상태이므로, 추후 별도 교체 필요
- 테스트 실패 시 루코드에 "이 테스트 실패하는데 수정해줘: [에러 메시지]"로 후속 요청
