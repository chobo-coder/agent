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
