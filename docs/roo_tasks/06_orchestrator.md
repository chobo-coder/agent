# Task 06: Orchestrator

## Goal
Orchestrator에 에러 복구, 체크포인트 재개, 분기점 위젯 연동 로직 추가

---

## 현재 상태

- `core/orchestrator.py`: 기본 라우팅 (`handle_input` → `_start_workflow` / `_handle_decision` / `_auto_advance`)
- 핸들러 6개 등록
- StepResult 반환 구조

---

## 구현 상세

### 6-1. 에러 핸들링 + 상태 롤백

```python
# core/orchestrator.py 수정

from llm.client import LLMError

class Orchestrator:
    def handle_input(self, user_input: str) -> StepResult:
        sm = self.session.state_machine

        try:
            if sm.is_decision_point:
                return self._handle_decision(user_input)
            if sm.state == WorkflowState.IDLE:
                return self._start_workflow(user_input)
            return self._auto_advance()

        except LLMError as e:
            # LLM 호출 실패: 상태 유지, 사용자에게 재시도 안내
            return StepResult(
                summary=f"LLM 호출에 실패했습니다: {e}\n다시 시도해주세요.",
                metadata={"error": True, "error_type": "llm"},
            )
        except Exception as e:
            # 파이프라인 실패: 상태 롤백
            sm.rollback()
            return StepResult(
                summary=f"처리 중 오류가 발생했습니다: {e}\n이전 단계로 돌아갑니다.",
                metadata={"error": True, "error_type": "pipeline"},
            )
```

### 6-2. 체크포인트에서 워크플로우 재개

```python
class Orchestrator:
    def resume_from_checkpoint(self, state: WorkflowState) -> StepResult:
        """저장된 체크포인트에서 워크플로우 재개"""
        # 체크포인트에서 DataFrame 복원
        checkpoint_data = self.checkpoints.load_all(state)
        if not checkpoint_data:
            return StepResult(summary="해당 체크포인트를 찾을 수 없습니다.")

        # 세션에 DataFrame 복원
        for key, df in checkpoint_data.items():
            self.session.set_dataframe(key, df)

        # 상태 직접 설정 (전이 규칙 무시)
        self.session.state_machine._state = state
        self.session.state_machine._history.append(state)

        return StepResult(
            summary=f"'{state.name}' 단계에서 재개합니다.",
            dataframes=checkpoint_data,
        )
```

`CheckpointManager`에 `load_all` 추가:

```python
# core/checkpoints.py에 추가

def load_all(self, state: WorkflowState) -> dict[str, pd.DataFrame]:
    """해당 상태의 모든 체크포인트를 로드"""
    state_dir = self._dir / state.name.lower()
    if not state_dir.exists():
        return {}

    result = {}
    for path in state_dir.glob("*.parquet"):
        result[path.stem] = pd.read_parquet(path)
    return result
```

### 6-3. 분기점 처리 고도화

각 분기점에서 LLM 결정 결과를 세션에 저장하고, 다음 핸들러가 사용:

```python
class Orchestrator:
    def _handle_decision(self, user_input: str) -> StepResult:
        state = self.session.state_machine.state
        prompt = self.prompts.build_decision_prompt(state, user_input)
        response = self.llm.complete(prompt)
        decision = self.parser.parse_decision(state, response)

        # 결정 결과를 세션에 저장 (다음 핸들러에서 사용)
        self._store_decision(state, decision)

        next_state = self._resolve_next_state(state, decision)
        self.session.state_machine.transition_to(next_state)

        return self._execute_current_step()

    def _store_decision(self, state: WorkflowState, decision: dict) -> None:
        """분기점 결정을 세션 메타데이터에 저장"""
        if state == WorkflowState.SHOWING_QUERY_RESULTS:
            self.session.set_metadata("load_decision", decision)

        elif state == WorkflowState.SHOWING_DATA_OVERVIEW:
            self.session.set_metadata("preprocess_items", decision.get("items", []))
            self.session.set_metadata("preprocess_params", decision.get("params", {}))

        elif state == WorkflowState.SHOWING_FEATURES:
            features = decision.get("features", [])
            # "top_N_correlated" 처리
            if isinstance(features, str) and "top" in features:
                features = self._resolve_top_features(features)
            self.session.set_metadata("selected_features", features)
            self.session.set_metadata("threshold", decision.get("threshold", 0.5))

    def _resolve_top_features(self, spec: str) -> list[str]:
        """'top_3_correlated' 같은 스펙을 실제 피처 목록으로 변환"""
        import re
        match = re.search(r"top_(\d+)", spec)
        n = int(match.group(1)) if match else 3

        corr_matrix = self.session.get_dataframe("correlation_matrix")
        if corr_matrix is None:
            return []

        # 상관계수 절대값 합 기준 상위 N개
        importance = corr_matrix.abs().sum().sort_values(ascending=False)
        return importance.head(n).index.tolist()
```

### 6-4. 전체 워크플로우 시나리오 (제어 흐름)

```
[사용자] "ProductA 분석해줘"
  └─ Orchestrator._start_workflow()
     ├─ LLM: 제품명 추출 → "ProductA"
     ├─ session.set_metadata("current_product", "ProductA")
     ├─ transition: IDLE → QUERYING_DATA
     └─ _execute_current_step()
        ├─ DataQueryHandler.execute() → StepResult(query_result)
        ├─ checkpoint.save(QUERYING_DATA, {query_result})
        ├─ LLM: 결과 요약
        └─ auto-transition: QUERYING_DATA → SHOWING_QUERY_RESULTS

[시스템] "ProductA 100건 조회. 추가 데이터를 로딩할까요?"
         (is_decision_point = True, 사용자 입력 대기)

[사용자] "S3 데이터도 가져와"
  └─ Orchestrator._handle_decision()
     ├─ LLM: {"load_additional": true}
     ├─ _store_decision() → session.metadata["load_decision"]
     ├─ transition: SHOWING_QUERY_RESULTS → AWAITING_LOAD_DECISION → LOADING_PARQUET
     └─ _execute_current_step()
        ├─ DataLoaderHandler.execute() → StepResult(merged_data)
        └─ auto-transition: → SHOWING_DATA_OVERVIEW

[시스템] "500건 머지 완료. 전처리 항목을 선택해주세요."

[사용자] "결측치 평균으로 채우고 스케일링"
  └─ _handle_decision()
     ├─ LLM: {"items": ["missing_values", "scaling"], "params": {"missing_strategy": "mean"}}
     ├─ _store_decision() → preprocess_items, preprocess_params
     ├─ transition: → AWAITING_PREPROCESS → PREPROCESSING
     └─ PreprocessingHandler.execute()
        └─ auto-transition: → SHOWING_PREPROCESSED → ANALYZING_FEATURES

[시스템] "상관분석 결과 + heatmap 표시"
         (SHOWING_FEATURES = decision point)

[사용자] "metric_a, metric_b로 0.7 기준"
  └─ _handle_decision()
     ├─ LLM: {"features": ["metric_a", "metric_b"], "threshold": 0.7}
     ├─ _store_decision() → selected_features, threshold
     ├─ transition: → AWAITING_COMBINATIONS → PREDICTING
     └─ PredictionHandler.execute()
        └─ auto-transition: → SHOWING_PREDICTIONS → COMPLETED

[시스템] "예측 완료. 임계값 이상 47건."
```

### 6-5. 중복 실행 방지

Streamlit은 매 인터랙션마다 전체 스크립트를 재실행하므로, 이미 처리된 입력을 다시 처리하지 않도록:

```python
# app.py에서

if user_input:
    # 이미 마지막으로 처리한 입력과 동일하면 스킵
    last_user_msg = next(
        (m for m in reversed(session.chat_history) if m["role"] == "user"),
        None,
    )
    if last_user_msg and last_user_msg["content"] == user_input:
        st.stop()

    # 처리 진행...
```

---

## 파일 체크리스트

| 파일 | 액션 | 변경 내용 |
|------|------|----------|
| `core/orchestrator.py` | 수정 | 에러 핸들링, 체크포인트 재개, _store_decision, top_features |
| `core/checkpoints.py` | 수정 | `load_all()` 메서드 추가 |
| `core/session.py` | 확인 | 기존 인터페이스로 충분 |
| `app.py` | 수정 | 중복 실행 방지, 에러 처리 연결 |

---

## 완료 기준

- [ ] LLM 에러 시 상태 유지 + 재시도 안내 메시지
- [ ] 파이프라인 에러 시 이전 상태로 롤백
- [ ] 체크포인트 재개 시 DataFrame 복원 + 상태 설정
- [ ] 분기점 결정이 세션 메타데이터에 저장되어 다음 핸들러에서 사용
- [ ] "top_3_correlated" 스펙이 실제 피처 목록으로 변환
- [ ] 동일 입력 중복 처리 방지
- [ ] 전체 시나리오 (IDLE → COMPLETED) 수동 테스트 통과

---

## 변경 이력

### 2026-05-07: 파라미터 수집/검증 플로우 + 도구 선택 전처리 추가

**변경 사항:**
- `app.py`의 워크플로우 시작이 `IDLE → COLLECTING_PARAMS` → `VALIDATING_PARAMS` → `QUERYING_DATA` 순서로 변경
- `_handle_collecting()`: LLM으로 파라미터 추출 후 기존 params에 머지
- `_handle_validating()`: `schema.REQUIRED_PARAMS` 기준 필수값 체크, 누락 시 COLLECTING으로 루프
- `_handle_showing_data_overview()`: 전처리 도구 메뉴를 표시, 사용자가 번호/이름/키워드로 선택
- `_handle_preprocessing()`: 선택된 도구 목록을 순서대로 실행

**새로 추가된 인터페이스:**
```python
# app.py — 파라미터 수집 핸들러
def _handle_collecting(user_input: str) -> None:
    """COLLECTING_PARAMS 상태 처리.

    1. _extract_params_with_llm()으로 파라미터 추출
    2. session의 기존 params와 머지 (None이 아닌 값만 덮어쓰기)
    3. VALIDATING_PARAMS로 전이
    """

def _handle_validating() -> None:
    """VALIDATING_PARAMS 상태 처리.

    1. schema.REQUIRED_PARAMS의 모든 key가 params에 존재하는지 확인
    2. 누락 있음 → 누락 항목 안내 메시지 + COLLECTING_PARAMS로 전이
    3. 누락 없음 → 확인 메시지 + QUERYING_DATA로 전이
    """

def _build_preprocess_menu() -> str:
    """전처리 도구 선택 메뉴 문자열 생성.

    Returns:
        번호가 매겨진 도구 목록 (예: "1. 결측치 제거 - 결측치가 포함된 행을 삭제")
    """
```

**기존 코드 수정:**
- `app.py:handle_user_input` — 상태별 라우팅에 `COLLECTING_PARAMS`, `VALIDATING_PARAMS` 분기 추가
- `app.py:_handle_showing_data_overview` — LLM 자유 파싱 대신 `_parse_tool_selection()` 사용

**루코드 구현 시 주의사항:**
- 파라미터 수집 루프는 무한 반복 가능 (사용자가 필수값을 모두 입력할 때까지)
- `session_state["query_params"]`에 수집된 파라미터 저장 (dict)
- 검증 실패 메시지에 누락된 항목의 `label`(한국어)을 표시해야 함
- 전처리 도구 실행 순서: 사용자가 선택한 순서 그대로 (결측치 → 이상치 → 스케일링 등)
- `_parse_tool_selection()`이 빈 리스트를 반환하면 "선택된 도구가 없습니다" 안내 후 재입력 대기

### 2026-05-07: 멀티 워크플로우 Orchestrator + 워크플로우 선택 UI

**변경 사항:**
- `core/orchestrator.py` 핸들러를 `_common_handlers` + `_workflow_handlers[WorkflowType]`으로 분리
- `_handle_workflow_selection()` 메서드 추가 — 워크플로우 유형 판별 후 `set_workflow_type()` 호출
- `_get_handler(state)` — 공통 → 워크플로우별 순서로 핸들러 탐색
- `app.py`에 IDLE → `SELECTING_WORKFLOW` 상태 추가, 워크플로우 메뉴 표시
- `app.py`에 `_handle_workflow_selection()`, `_parse_workflow_type()` 함수 추가

**새로 추가된 인터페이스:**
```python
# core/orchestrator.py
class Orchestrator:
    _common_handlers: dict    # 공통 핸들러 (QUERYING_DATA, LOADING_PARQUET, SHOWING_DATA_OVERVIEW)
    _workflow_handlers: dict[WorkflowType, dict]  # 워크플로우별 핸들러

    def _get_handler(self, state: WorkflowState) -> BaseHandler | None:
        """공통 → 워크플로우별 순서로 핸들러 탐색"""

    def _handle_workflow_selection(self, user_input: str) -> StepResult:
        """워크플로우 유형 판별 후 COLLECTING_PARAMS로 진입"""

# app.py
WORKFLOW_MENU: str  # "1. 기존 분석 / 2. MAP 경향성 / 3. 장비 경향성" 메뉴

def _handle_workflow_selection(session, user_input) -> str:
    """워크플로우 유형 판별 → set_workflow_type → COLLECTING_PARAMS 진입"""

def _parse_workflow_type(text: str) -> WorkflowType | None:
    """번호(1/2/3) 또는 키워드(map/장비/기존)로 워크플로우 유형 판별"""
```

**기존 코드 수정:**
- `core/orchestrator.py:__init__` — 단일 `_handlers` dict → 공통/워크플로우별 분리
- `core/orchestrator.py:_execute_current_step` — `self._handlers.get` → `self._get_handler()` 호출
- `core/orchestrator.py:handle_input` — `SELECTING_WORKFLOW` 분기 추가
- `app.py:handle_user_input` — IDLE에서 `_handle_workflow_selection()` 호출, `SELECTING_WORKFLOW` 분기 추가

**루코드 구현 시 주의사항:**
- 워크플로우 선택은 항상 첫 단계. 조회 조건이 바로 들어오면 CONVENTIONAL로 자동 판별
- MAP/장비는 현재 미구현 안내 후 CONVENTIONAL로 폴백
- MAP/장비 워크플로우 구현 시: `_workflow_handlers`에 핸들러 등록 + `_resolve_next_state`에 분기 추가
- `_parse_workflow_type()`이 None 반환 시 메뉴를 다시 표시
- `SELECTING_WORKFLOW`가 `DECISION_STATES`이므로 사용자 입력을 기다림

### 2026-05-08: SessionSnapshot 스냅샷 저장/복원 + 롤백 기능

**변경 사항:**
- `core/session.py`에 `SessionSnapshot` dataclass 추가
- `SessionManager`에 3개 메서드 추가: `save_snapshot()`, `restore_snapshot()`, `get_completed_states()`
- `_initialize()`에 `st.session_state.snapshots = {}`, `snapshot_base_dir` 추가
- 기존 세션 호환: `__init__`에서 `snapshots`, `snapshot_base_dir` 키 없으면 자동 추가
- `app.py`에 각 주요 단계 도달 시 `session.save_snapshot()` 호출 추가:
  - `COLLECTING_PARAMS` 핸들러 진입 시
  - `SHOWING_QUERY_RESULTS` 핸들러 진입 시
  - `SHOWING_DATA_OVERVIEW` 도달 직후
  - `SHOWING_FEATURES` 도달 직후
  - `SHOWING_PREDICTIONS` 도달 직후

**새로 추가된 인터페이스:**
```python
# core/session.py

@dataclass
class SessionSnapshot:
    state: WorkflowState
    workflow_type: WorkflowType
    metadata: dict                    # deep copy (메모리)
    context_keys: list[str]           # workflow_context에 있던 DataFrame 키 목록
    disk_dir: Path                    # parquet 파일이 저장된 디렉토리
    chat_history_length: int          # 채팅 잘라내기용
    state_history: list[WorkflowState]

    def load_context(self) -> dict[str, pd.DataFrame]:
        """디스크에서 DataFrame들을 읽어 반환"""

    def cleanup(self) -> None:
        """디스크의 parquet 파일 삭제"""

class SessionManager:
    def save_snapshot(self) -> None:
        """현재 상태의 스냅샷을 저장.
        - metadata: deep copy (메모리)
        - DataFrame: disk_dir/{key}.parquet로 디스크 저장
        - 기존 스냅샷이 있으면 디스크 정리 후 덮어쓰기"""

    def restore_snapshot(self, target_state: WorkflowState) -> bool:
        """스냅샷에서 metadata(메모리), workflow_context(디스크→메모리), history 복원.
        chat_history를 스냅샷 시점까지 잘라내고 롤백 안내 메시지 추가.
        target 이후 스냅샷은 디스크 정리 포함 삭제. 성공 시 True 반환."""

    def get_completed_states(self) -> list[WorkflowState]:
        """스냅샷이 존재하는 상태 목록 반환 (= 롤백 가능 상태)"""
```

**디스크 저장 구조:**
```
/tmp/agent_snapshots_XXXXXX/          ← snapshot_base_dir (세션당 1개)
  COLLECTING_PARAMS/                  ← 상태별 디렉토리
    (DataFrame 없으면 빈 디렉토리)
  SHOWING_QUERY_RESULTS/
    query_result.parquet
  SHOWING_DATA_OVERVIEW/
    query_result.parquet
    merged_data.parquet
  SHOWING_FEATURES/
    query_result.parquet
    merged_data.parquet
    preprocessed.parquet
  SHOWING_PREDICTIONS/
    ...all above + predictions.parquet
```

**기존 코드 수정:**
- `core/session.py:SessionSnapshot` — `workflow_context: dict` → `context_keys: list[str]` + `disk_dir: Path`로 변경
- `core/session.py:_initialize` — `TemporaryDirectory`로 `snapshot_base_dir` 초기화, `atexit` 핸들러 등록
- `core/session.py:save_snapshot` — DataFrame을 parquet로 디스크 저장, 메모리에는 키 목록만 보관
- `core/session.py:restore_snapshot` — `snapshot.load_context()`로 디스크에서 DataFrame 복원, 삭제 시 `cleanup()` 호출
- `core/session.py:reset` — `TemporaryDirectory.cleanup()` 호출로 디스크 전체 삭제
- 모듈 로딩 시 `_cleanup_stale_snapshots()` 실행 — 24시간 이상 된 고아 디렉토리 자동 삭제

**디스크 라이프사이클 (3중 안전장치):**

| 삭제 시점 | 메커니즘 | 커버하는 시나리오 |
|-----------|----------|-----------------|
| 사용자가 "처음부터 다시" 클릭 | `reset()` → `TemporaryDirectory.cleanup()` | 정상 초기화 |
| 롤백 | `restore_snapshot()` → 이후 스냅샷 `cleanup()` | 부분 삭제 |
| Streamlit 프로세스 종료 | `atexit` 핸들러 + `TemporaryDirectory` 소멸자 | 정상 종료 (Ctrl+C 등) |
| 앱 재시작 | `_cleanup_stale_snapshots()` — 24시간 초과 고아 디렉토리 삭제 | 비정상 종료 (kill -9, 서버 다운) |
| OS 재부팅 | `/tmp` 자동 정리 (macOS/Linux) | 최후의 안전망 |

**루코드 구현 시 주의사항:**
- `st.session_state.snapshot_tmp_handle`에 `TemporaryDirectory` 객체 참조를 유지해야 함 (GC 방지). 이 참조가 사라지면 디렉토리가 즉시 삭제됨
- DataFrame은 메모리에 보관하지 않고 `{snapshot_base_dir}/{state_name}/{key}.parquet`에 저장
- `restore_snapshot()`은 `load_context()`로 parquet를 읽어 메모리로 복원 — I/O 비용은 있으나 메모리 절약
- `cleanup()`은 `shutil.rmtree()`로 상태 디렉토리 전체 삭제
- `_SNAPSHOT_MAX_AGE_HOURS = 24` — 운영 환경에 맞게 조정 가능
- 실제 데이터 연동 시 parquet 직렬화가 안 되는 컬럼 타입(예: object 내 복잡한 중첩 구조)이 있으면 `to_parquet()` 실패 가능 → 해당 컬럼은 전처리 단계에서 단순 타입으로 변환 필요

### 2026-05-08: 수율 경향성 워크플로우 핸들러 + 워크플로우 메뉴 확장

**변경 사항:**
- `app.py` — 워크플로우 메뉴에 "수율 경향성 분석" 추가 (3번 → 수율, 4번 → 장비)
- `app.py` — `_parse_workflow_type()` — `"3"`, `"수율"`, `"yield"`, `"트렌드"` 등 키워드 인식
- `app.py` — `_get_required_params_for_workflow()` — `YIELD_TREND` 시 `schema.YIELD_REQUIRED_PARAMS` 반환
- `app.py` — `_handle_collecting()` — 필수값 충족 시 `YIELD_TREND`이면 `_handle_yield_loading()` 호출
- `app.py` — `handle_user_input()` — `YIELD_SHOWING_OVERVIEW`, `YIELD_AWAITING_REQUEST`, `YIELD_SHOWING_DETAIL` 상태 핸들링 추가
- `app.py` — `_extract_params_with_llm()` — `week` 파라미터 추출 키 추가
- `app.py` — `_parse_params_fallback()` — week 추출 패턴 추가 (`W20`, `20주차`, `2025-W20`)
- `llm/prompts.py` — `build_yield_param_extraction()` 메서드 추가 (week 파싱 포함)
- `pipeline/yield_trend.py` import 추가

**새로 추가된 인터페이스:**
```python
# app.py — 수율 핸들러
def _handle_yield_loading(session: SessionManager, params: dict) -> str:
    """수율 워크플로우 진입: week 결정 → parquet 로드/DB 조회 → 전처리 → overview 표시.
    상태 전이: YIELD_LOADING_DATA → YIELD_PREPROCESSING → YIELD_SHOWING_OVERVIEW"""

def _handle_yield_request(session: SessionManager, user_input: str) -> str:
    """사용자 요청 파싱 → 상세 뷰 표시 → 루프.
    상태 전이: YIELD_SHOWING_DETAIL → YIELD_AWAITING_REQUEST (또는 COMPLETED)"""

# llm/prompts.py
class PromptBuilder:
    def build_yield_param_extraction(self, user_input: str, existing_params: dict) -> str:
        """수율 워크플로우 전용 파라미터 추출 프롬프트.
        추출 대상: lot_cd(필수), week(선택), oper(선택), from_date(선택), end_date(선택)"""
```

**앱 핸들러 흐름:**
```
YIELD_LOADING_DATA:
  resolve_weeks(params) → load_or_query() → session 저장
  → YIELD_PREPROCESSING → filter_by_date() → preprocess_yield()
  → YIELD_SHOWING_OVERVIEW → overview 테이블 표시

YIELD_SHOWING_OVERVIEW / YIELD_AWAITING_REQUEST:
  parse_detail_request(user_input)
  - "종료" → COMPLETED
  - "전체 보여줘" → 모든 공정 수율 trend 표
  - "OP1 cat1 보여줘" → 특정 공정-cat 필터
  → YIELD_SHOWING_DETAIL → YIELD_AWAITING_REQUEST (루프)
```

**세션 저장 키:**

| 키 | 타입 | 용도 |
|----|------|------|
| `yield_raw` | DataFrame | 원본 수율 데이터 |
| `yield_oper_summary` | DataFrame | 공정별 수율 집계 |
| `yield_cat_detail` | DataFrame | 공정-cat별 불량률 집계 |

**루코드 구현 시 주의사항:**
- 워크플로우 메뉴 번호가 변경됨: 3번=수율, 4번=장비
- `_parse_workflow_type()`의 키워드 우선순위: "트렌드"/"trend" → YIELD_TREND, "장비"/"챔버"/"센서" → EQUIP_TREND
- `week` 파라미터는 fallback 파서에서 `W20`, `20주차`, `2025-W20` 패턴을 인식
- conventional, MAP 워크플로우 코드는 일절 변경 없음

### 2026-05-11: MAP 경향성 워크플로우 핸들러 + conventional 파이프라인 확장 반영

**변경 사항:**
- `app.py` — MAP 워크플로우 핸들러 추가:
  - `_handle_map_query(session, params)` — LOT 조회 + fail 몰림 표시 → wafer 선택 → map 분석
  - `_handle_map_prev_process_decision(session, user_input)` — 전공정 merge 선택 → similarity 분석
  - `handle_user_input()` — MAP_SHOWING_FAIL_CONCENTRATION, MAP_SELECTING_WAFERS, MAP_SHOWING_RESULTS, MAP_AWAITING_PREV_PROCESS_MERGE, MAP_SHOWING_PREV_PROCESS_RESULTS 상태 분기 추가
- `app.py` — conventional 파이프라인 확장:
  - EDA 버튼 (`st.button("📊 EDA 수행")`) + `_handle_eda()` 핸들러
  - 전처리 미리보기 루프: `_handle_preprocess_loop()` — 도구 선택 → preview → 누적 → "완료" 시 apply
  - Threshold Scanning: 전처리 완료 후 자동 `run_threshold_scanning()` 실행
  - Scatter Plot: 예측 완료 시 `plot_feature_scatter()` → PNG 저장 + 표시
- `app.py` — `_parse_params_fallback()` 확장:
  - OPER 매칭: `schema.OPER_OPTIONS` 기반 키워드 검색
  - 날짜 형식: YYYYMMDD (하이픈 없이) 변환
  - LOT 코드: 영문+숫자 3글자 이상 패턴

**새로 추가된 인터페이스:**
```python
# app.py — MAP 핸들러
def _handle_map_query(session: SessionManager, params: dict) -> str:
    """MAP 워크플로우 진입: LOT 조회 → fail 집계 → 몰림 표시.
    상태 전이: MAP_QUERYING_LOT → MAP_SHOWING_FAIL_CONCENTRATION"""

def _handle_map_prev_process_decision(session: SessionManager, user_input: str) -> str:
    """전공정 merge 여부 선택. '예' → merge + similarity, '아니오' → COMPLETED."""

# app.py — conventional 확장
def _handle_eda(session: SessionManager) -> None:
    """EDA 실행. 상태 전이 없음 (현재 상태 내 실행)."""

def _handle_preprocess_loop(session: SessionManager, user_input: str) -> str:
    """전처리 도구 미리보기 루프. '완료' 입력 시 일괄 적용."""

def _apply_preprocess_plan(session: SessionManager) -> str:
    """누적된 전처리 계획 적용 → threshold scanning → SHOWING_FEATURES 전이."""
```

**MAP 핸들러 상태 흐름:**
```
COLLECTING_PARAMS (필수값 충족)
  → _handle_map_query() → MAP_QUERYING_LOT → MAP_SHOWING_FAIL_CONCENTRATION
  → 사용자 wafer 선택 → MAP_SELECTING_WAFERS → MAP_ANALYZING_WAFER_MAP → MAP_SHOWING_RESULTS
  → 사용자 전공정 선택 → MAP_AWAITING_PREV_PROCESS_MERGE
    → "예" → MAP_ANALYZING_PREV_PROCESS → MAP_SHOWING_PREV_PROCESS_RESULTS → COMPLETED
    → "아니오" → COMPLETED
```

**conventional 확장 흐름:**
```
SHOWING_QUERY_RESULTS
  → [EDA 버튼] → run_eda() → 결과 표시 (상태 변화 없음)
  → "예" (S3 추가) → 로딩 → SHOWING_DATA_OVERVIEW
  → "아니오" → SHOWING_DATA_OVERVIEW

SHOWING_DATA_OVERVIEW (전처리 루프)
  → "1" → preview_tool() → 미리보기 표시 → 대기 (루프)
  → "7" → preview_tool() → 미리보기 표시 → 대기 (루프)
  → "완료" → apply_plan() → run_threshold_scanning() → SHOWING_FEATURES

SHOWING_FEATURES
  → 피처/조건/임계값 선택 → compute_prediction_metrics() → plot_feature_scatter() → COMPLETED
```

**루코드 구현 시 주의사항:**
- MAP 핸들러에서 실제 DB 연동 시 `map_pipeline.query_lot_fail_summary()`와 `map_pipeline.query_wafer_map_detail()` 교체
- EDA는 상태 전이 없이 SHOWING_QUERY_RESULTS 내에서 실행 — `session.metadata["eda_done"]`으로 중복 방지
- 전처리 미리보기 루프는 `session.metadata["preprocess_plan"]`에 PreprocessPlan 객체 저장
- Threshold Scanning 결과는 `session.set_dataframe("scanning_result", df)`로 저장 — SHOWING_FEATURES에서 `st.dataframe`으로 표시
- Scatter Plot PNG는 `session.metadata["scatter_plot"]`에 bytes로 저장 — COMPLETED에서 `st.image()`로 표시
