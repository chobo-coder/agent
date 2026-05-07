# Roo Code 프롬프트 모음

각 태스크별로 루코드에 복사-붙여넣기할 프롬프트입니다.
순서대로 실행하세요.

**사전 조건:** 코딩 시작 전 `.roo/rules.md`를 반드시 읽을 것.

---

## Task 01: Project Setup

```
프로젝트 환경 설정을 완료해줘.

먼저 `.roo/rules.md`와 `schema.py`를 읽어서 프로젝트 구조를 파악해.

1. `.env.example` 파일 생성:
   - LLM_API_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS
   - S3_BUCKET, S3_REGION
   - SDK_API_URL, SDK_API_KEY
   - CHECKPOINT_DIR
   각 값은 placeholder로 채워줘.

2. `.gitignore` 파일 생성:
   - .env, .checkpoints/, __pycache__/, *.pyc, .pytest_cache/, .venv/, .history/

3. `requirements.txt`에 있는 패키지들이 정상 import 되는지 확인하는 스크립트 `scripts/check_env.py` 만들어줘. 각 패키지를 import하고 성공/실패를 출력하면 돼.

4. `streamlit run app.py` 실행했을 때 에러 없이 뜨는지 확인하고, 에러가 있으면 수정해줘.
```

---

## Task 02: State Machine 보완

```
`core/state_machine.py`의 StateMachine 클래스에 다음 기능을 추가해줘.

먼저 `.roo/rules.md`를 읽고, `docs/roo_tasks/02_state_machine.md`의 변경 이력을 확인해.
현재 WorkflowType(CONVENTIONAL, MAP_TREND, EQUIP_TREND)과 SELECTING_WORKFLOW 상태가 이미 있어.

1. **상태 이력 추적**: `_history: list[WorkflowState]` 필드 추가. 초기값 `[WorkflowState.IDLE]`. `transition_to()` 호출마다 history에 append.

2. **rollback()**: 마지막 전이를 취소하고 이전 상태로 복귀. history가 1개 이하면 무시.

3. **progress_percent property**: 현재 워크플로우 타입의 전이 테이블 기준으로 진행률 계산 (0.0~1.0).

4. **직렬화**: `to_dict()` → {"state": "STATE_NAME", "workflow_type": "conventional", "history": [...]}, `from_dict(data)` classmethod로 복원.

5. `tests/test_state_machine.py`에 다음 테스트 추가:
   - test_history_tracking: 2번 전이 후 history 길이 3, 순서 확인
   - test_rollback: 전이 후 rollback하면 이전 상태
   - test_rollback_at_idle: IDLE에서 rollback은 무시
   - test_progress_percent: IDLE=0.0, COMPLETED=1.0
   - test_serialization_roundtrip: to_dict → from_dict 후 상태/workflow_type 동일
   - test_workflow_type_change: SELECTING_WORKFLOW에서 set_workflow_type 정상 동작
   - test_workflow_type_change_blocked: QUERYING_DATA에서 set_workflow_type 시 에러

기존 테스트가 깨지지 않게 해줘. `pytest tests/test_state_machine.py -v`로 전체 통과 확인.
```

---

## Task 03: LLM Integration 강화

```
LLM 모듈을 개선해줘.

먼저 `.roo/rules.md`를 읽고, `docs/roo_tasks/03_llm_integration.md`의 변경 이력을 확인해.
현재 build_param_extraction() 프롬프트가 lot_cd/from_date/end_date/cat 기준으로 되어있어.

### 1. `llm/client.py` — 이미 retry 구현됨. 확인만 해줘.

### 2. `llm/prompts.py` — few-shot 예시 보강

각 분기점 프롬프트의 예시를 더 추가:
- `_build_load_decision_prompt`: 2~4개 예시
- `_build_preprocess_decision_prompt`: 2~4개 예시
- `_build_combination_prompt`: schema.AVAILABLE_FEATURES를 사용한 예시

`build_param_extraction`에 LOT 코드 패턴 예시 추가:
- "LOT A2401 2025-01-01 2025-03-31 CAT_A" → 4필드 추출
- "A2502 지난 분기" → lot_cd + 날짜만
- "CAT_B로 해줘" → cat만

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

먼저 `.roo/rules.md`를 읽고, `schema.py`를 확인해. 모든 컬럼/테이블 참조는 schema.*를 사용해야 해.
`docs/roo_tasks/04_pipeline_steps.md`의 변경 이력도 확인해.

### 1. `wrappers/sdk_wrapper.py`

mock 데이터 반환:
- execute_query(query, params): 100행 DataFrame, schema.DB_COLUMNS 컬럼 사용
- numpy random으로 생성, seed=42 고정
- test_connection(): True 반환

### 2. `wrappers/s3_wrapper.py`

mock 데이터 반환:
- read_parquet(prefix): 50행 DataFrame, schema.S3_COLUMNS 컬럼 사용
- list_files(prefix): 빈 리스트 반환
- DataNotFoundError 예외 클래스 추가

### 3. `pipeline/data_query.py`

_build_query()에서 schema.DB_TABLE, schema.DB_LOT_COLUMN, schema.DB_DATE_COLUMN, schema.DB_CAT_COLUMN 참조.
params에서 lot_cd, from_date, end_date, cat(선택)을 받아 SQL 생성.

### 4. `pipeline/data_loader.py`

_merge()에서 schema.S3_MERGE_KEYS를 join key로 사용. 중복 제거 + reset_index.

### 5. `pipeline/preprocessing.py`

현재 13개 도구가 정의되어있어. 확인하고 누락된 핸들러가 있으면 추가:
- _handle_outliers: params에서 outlier_method(iqr/zscore), outlier_threshold 받기
- _handle_scaling: params에서 scaling_method(standard/minmax/robust) 받기
- _handle_low_variance, _handle_high_na_columns, _handle_ttest_filter, _handle_correlated_pairs: 이미 구현됨. 동작 확인.

### 6. Y값 생성 로직 추가

`pipeline/data_query.py` 또는 별도 유틸에 Y값 생성 함수 추가:
- cat 파라미터 있음 → y = 1 if row[schema.DB_CAT_COLUMN] == cat else 0
- cat 없음 → schema.FAILBIN 참조, oper별 bin 리스트에 해당하면 y=1

### 7. `pipeline/feature_analysis.py`

피처 중요도 계산 추가:
- RandomForestClassifier(n_estimators=100), schema.TARGET_COLUMN을 target으로
- 결과를 "feature_importance" DataFrame으로 StepResult에 추가

### 8. 테스트 (`tests/test_pipeline.py`)

- TestPreprocessing: missing_mean, missing_drop, outlier_iqr, scaling_minmax, low_variance, ttest_filter
- TestPrediction: scores 범위 0~1, 빈 features 시 전체 사용
- TestFeatureAnalysis: correlation matrix 정방행렬, 값 범위 -1~1
- TestYValueGeneration: cat 지정 시 이진값, FAILBIN 기반 이진값

`pytest tests/test_pipeline.py -v` 전체 통과 확인.
```

---

## Task 05: Chat UI 완성

```
Streamlit UI를 완성해줘.

먼저 `.roo/rules.md`를 읽고, `ui/chat.py`를 확인해. 현재 사이드바에 워크플로우 진행률, 상태 라벨, 쿼리 파라미터가 표시되고 있어.

### 1. 워크플로우 선택 UI

앱 시작 시 워크플로우 메뉴가 표시됨 (1:기존분석, 2:MAP, 3:장비).
현재 app.py의 WORKFLOW_MENU 상수와 _handle_workflow_selection()이 이미 있어.
render_sidebar()에 현재 워크플로우 유형도 표시해줘.

### 2. `ui/chat.py` 수정

render_sidebar()에:
- 워크플로우 유형 표시 (session.state_machine.workflow_type)
- 조회 조건 표시: lot_cd, from_date~end_date, cat(있으면)
- Y값 결정 방식 표시 (cat이면 cat 기반, 아니면 FAILBIN)

### 3. `app.py` 수정

- 에러 발생 시 st.error()로 표시 + 복구 안내
- step_result의 figures가 있으면 st.pyplot으로 표시
- step_result의 dataframes가 있으면 expander로 표시

### 4. `ui/chat.py`에 `render_error(error, state_name)` 함수 추가

st.error()로 에러 표시 + "다시 요청" / "처음부터" 안내 텍스트.

`streamlit run app.py` 실행해서 에러 없이 뜨는지 확인.
```

---

## Task 06: Orchestrator 통합

```
Orchestrator에 에러 핸들링과 멀티 워크플로우 로직을 완성해줘.

먼저 `.roo/rules.md`를 읽고, `docs/roo_tasks/06_orchestrator.md`의 변경 이력을 확인해.
현재 Orchestrator가 _common_handlers와 _workflow_handlers[WorkflowType]으로 분리되어있어.

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

"top_3_correlated" 문자열 → 실제 피처명 리스트로 변환하는 _resolve_top_features() 추가.

### 3. `core/checkpoints.py`에 `load_all(state)` 메서드 추가

해당 state 디렉토리의 모든 .parquet 파일을 dict[str, DataFrame]으로 반환.

### 4. `resume_from_checkpoint(state)` 메서드 추가

load_all로 DataFrame 복원 → session에 저장 → state_machine 상태 직접 설정.

### 5. 테스트 (`tests/test_integration.py` 신규 생성)

- test_start_workflow: 워크플로우 선택 후 파라미터 수집으로 전이
- test_llm_error_keeps_state: LLMError 발생 시 상태 유지
- test_pipeline_error_rollback: handler 에러 시 이전 상태로 복귀
- test_workflow_type_routing: conventional과 다른 워크플로우에서 핸들러 분기 확인

`pytest tests/ -v` 전체 통과 확인.
```

---

## Task 07: Testing 완성

```
테스트를 완성하고 전체 통과를 확인해줘.

먼저 `.roo/rules.md`를 읽어.

### 1. `tests/conftest.py` 생성

공통 fixtures:
- sample_df: 50행, schema.DB_COLUMNS 컬럼 사용, seed=42
- sample_df_with_nulls: sample_df에서 일부 NaN
- mock_session: MagicMock, get_dataframe은 sample_df 반환, get_metadata는 키별 다른 값
- mock_llm_client: MagicMock, complete은 '{"lot_cd": "A2401"}' 반환

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
- test_workflow_type_transitions: WorkflowType별 전이 테이블 검증
- test_selecting_workflow_state: SELECTING_WORKFLOW 분기점 동작

test_pipeline.py:
- test_low_variance_removal, test_high_na_removal
- test_ttest_filter, test_correlated_pairs_removal
- test_y_value_with_cat, test_y_value_with_failbin

test_integration.py:
- test_full_conventional_flow: IDLE → COMPLETED 전체 시나리오
- test_workflow_selection_menu: 워크플로우 메뉴 표시 동작

### 5. 전체 실행

`pytest tests/ -v` 실행해서 전체 통과 확인.
실패하는 테스트가 있으면 코드를 수정해서 통과시켜줘.
```

---

## 사용 방법

1. 루코드를 열고 프로젝트 루트(`/Users/hyeonjaeyeol/agent`)를 워크스페이스로 설정
2. **먼저 `.roo/rules.md`를 읽게 해** (코딩 규칙, 파일 구조, 패턴이 정리되어있음)
3. 위 프롬프트를 **순서대로** 하나씩 복사하여 루코드에 입력
4. 각 태스크 완료 후 테스트가 통과하는지 확인한 뒤 다음으로 진행
5. Task 01 → 02 → 03 → 04 → 05 → 06 → 07 순서 필수 (의존성 있음)

---

## 주의사항

- 각 프롬프트는 독립적으로 실행 가능하지만, 이전 태스크의 코드가 있어야 동작
- **모든 데이터 참조는 `schema.py`에서 import** — 컬럼명/테이블명 하드코딩 금지
- 조회 파라미터는 `lot_cd`, `from_date`, `end_date`, `cat`(선택)
- Y값은 cat 지정 시 cat 기반, 미지정 시 `schema.FAILBIN` 기반
- MAP/장비 워크플로우는 TODO 상태 — 주석 해제 + 핸들러 구현으로 활성화
- 사내 SDK/S3 실제 연동은 mock으로 대체한 상태이므로, 추후 별도 교체 필요
- 테스트 실패 시 루코드에 "이 테스트 실패하는데 수정해줘: [에러 메시지]"로 후속 요청
