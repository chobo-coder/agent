# Task 02: State Machine

## Goal
워크플로우 FSM이 모든 전이 경로를 올바르게 처리하는지 검증하고, 필요 시 보완

---

## 현재 상태

`core/state_machine.py`에 아래가 이미 구현됨:
- `WorkflowState` enum (15개 상태)
- `TRANSITIONS` 전이 테이블
- `DECISION_STATES` (3개 분기점)
- `StateMachine` 클래스 (transition_to, reset, get_next_auto_state 등)
- `InvalidTransitionError` 예외

테스트 `tests/test_state_machine.py` 10개 통과 완료.

---

## 추가 구현 필요 사항

### 2-1. 상태 이력 추적 (History)

현재 상태 전이만 가능하고, 어떤 경로로 왔는지 추적이 안 됨.
디버깅 및 UI 진행률 표시를 위해 이력 기능 추가:

```python
class StateMachine:
    def __init__(self):
        self._state = WorkflowState.IDLE
        self._history: list[WorkflowState] = [WorkflowState.IDLE]

    def transition_to(self, target: WorkflowState) -> None:
        # ... 기존 유효성 검사 ...
        self._state = target
        self._history.append(target)

    @property
    def history(self) -> list[WorkflowState]:
        return self._history.copy()

    @property
    def progress_percent(self) -> float:
        """전체 워크플로우 대비 진행률 (0.0 ~ 1.0)"""
        all_states = list(WorkflowState)
        current_idx = all_states.index(self._state)
        return current_idx / (len(all_states) - 1)
```

### 2-2. 롤백 기능

에러 발생 시 이전 상태로 되돌리기:

```python
def rollback(self) -> None:
    """마지막 전이를 취소하고 이전 상태로 복귀"""
    if len(self._history) > 1:
        self._history.pop()
        self._state = self._history[-1]
```

### 2-3. Serialization (세션 복구용)

Streamlit은 매 인터랙션마다 스크립트를 재실행하므로, 상태를 직렬화할 수 있어야 함:

```python
def to_dict(self) -> dict:
    return {
        "state": self._state.name,
        "history": [s.name for s in self._history],
    }

@classmethod
def from_dict(cls, data: dict) -> "StateMachine":
    sm = cls()
    sm._state = WorkflowState[data["state"]]
    sm._history = [WorkflowState[s] for s in data["history"]]
    return sm
```

---

## 추가 테스트 케이스

```python
def test_history_tracking(self):
    sm = StateMachine()
    sm.transition_to(WorkflowState.QUERYING_DATA)
    sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)
    assert len(sm.history) == 3  # IDLE + 2 transitions
    assert sm.history[0] == WorkflowState.IDLE

def test_rollback(self):
    sm = StateMachine()
    sm.transition_to(WorkflowState.QUERYING_DATA)
    sm.rollback()
    assert sm.state == WorkflowState.IDLE

def test_progress_percent(self):
    sm = StateMachine()
    assert sm.progress_percent == 0.0
    sm.transition_to(WorkflowState.QUERYING_DATA)
    assert sm.progress_percent > 0.0

def test_serialization(self):
    sm = StateMachine()
    sm.transition_to(WorkflowState.QUERYING_DATA)
    data = sm.to_dict()
    sm2 = StateMachine.from_dict(data)
    assert sm2.state == WorkflowState.QUERYING_DATA
    assert sm2.history == sm.history
```

---

## 파일 체크리스트

| 파일 | 액션 | 변경 내용 |
|------|------|----------|
| `core/state_machine.py` | 수정 | history, rollback, progress_percent, serialization 추가 |
| `tests/test_state_machine.py` | 수정 | 4개 테스트 케이스 추가 |

---

## 완료 기준

- [ ] `sm.history`가 전이 경로를 정확히 기록
- [ ] `sm.rollback()`으로 이전 상태 복귀
- [ ] `sm.progress_percent`가 0.0~1.0 범위 반환
- [ ] `to_dict()` / `from_dict()` 라운드트립 성공
- [ ] `pytest tests/test_state_machine.py` 14개 전체 통과

---

## 변경 이력

### 2026-05-07: COLLECTING_PARAMS / VALIDATING_PARAMS 상태 추가

**변경 사항:**
- `WorkflowState` enum에 `COLLECTING_PARAMS`, `VALIDATING_PARAMS` 2개 상태 추가 (총 17개)
- `TRANSITIONS` 테이블에 새 전이 경로 추가:
  - `IDLE → COLLECTING_PARAMS`
  - `COLLECTING_PARAMS → VALIDATING_PARAMS`
  - `VALIDATING_PARAMS → COLLECTING_PARAMS` (누락 시 루프)
  - `VALIDATING_PARAMS → QUERYING_DATA` (모든 필수값 충족 시)
- `DECISION_STATES`에 `COLLECTING_PARAMS`, `VALIDATING_PARAMS` 추가 (사용자 입력 대기 상태)

**새로 추가된 인터페이스:**
```python
# core/state_machine.py — WorkflowState enum 확장
class WorkflowState(Enum):
    IDLE = "idle"
    COLLECTING_PARAMS = "collecting_params"      # 신규
    VALIDATING_PARAMS = "validating_params"      # 신규
    QUERYING_DATA = "querying_data"
    # ... 이하 기존 상태 동일

# 전이 규칙 추가
TRANSITIONS[WorkflowState.IDLE].append(WorkflowState.COLLECTING_PARAMS)
TRANSITIONS[WorkflowState.COLLECTING_PARAMS].append(WorkflowState.VALIDATING_PARAMS)
TRANSITIONS[WorkflowState.VALIDATING_PARAMS].extend([
    WorkflowState.COLLECTING_PARAMS,  # 누락 시 재수집
    WorkflowState.QUERYING_DATA,      # 완료 시 진행
])
```

**루코드 구현 시 주의사항:**
- 기존 `IDLE → QUERYING_DATA` 직접 전이는 제거됨. 반드시 `COLLECTING_PARAMS`를 거쳐야 함
- `COLLECTING_PARAMS`와 `VALIDATING_PARAMS` 모두 `DECISION_STATES`이므로 사용자 입력을 기다림
- `progress_percent` 계산 시 상태 수가 15 → 17로 늘어남에 따라 분모 변경됨
- `schema.py`의 `REQUIRED_PARAMS`를 참조하여 검증 로직이 동작함

### 2026-05-07: 멀티 워크플로우 구조 (WorkflowType + SELECTING_WORKFLOW)

**변경 사항:**
- `WorkflowType` enum 추가: `CONVENTIONAL`, `MAP_TREND`, `EQUIP_TREND`
- `SELECTING_WORKFLOW` 상태 추가 (IDLE → 유형 선택 → 파라미터 수집)
- `TRANSITIONS`를 단일 dict에서 공통 + 워크플로우별로 분리
  - `_COMMON_TRANSITIONS`: IDLE ~ SHOWING_DATA_OVERVIEW (모든 워크플로우 공유)
  - `_CONVENTIONAL_TRANSITIONS`: 오버뷰 이후 전처리→피처→예측
  - `_MAP_TREND_TRANSITIONS`: TODO (MAP 전용 상태 전이)
  - `_EQUIP_TREND_TRANSITIONS`: TODO (장비 전용 상태 전이)
- `_build_transitions(workflow_type)` 함수로 전이 테이블 동적 생성
- `StateMachine`에 `workflow_type` 속성, `set_workflow_type()` 메서드 추가

**새로 추가된 인터페이스:**
```python
# core/state_machine.py

class WorkflowType(Enum):
    CONVENTIONAL = "conventional"
    MAP_TREND = "map_trend"       # TODO
    EQUIP_TREND = "equip_trend"   # TODO

class WorkflowState(Enum):
    SELECTING_WORKFLOW = auto()   # 신규 — 워크플로우 유형 선택
    # MAP 전용 상태 (TODO: 주석 해제)
    # MAP_SELECTING_PARAMS, MAP_LOADING_DATA, MAP_ANALYZING,
    # MAP_SHOWING_RESULTS, MAP_COMPARING
    # 장비 전용 상태 (TODO: 주석 해제)
    # EQUIP_SELECTING_PARAMS, EQUIP_LOADING_DATA, EQUIP_TREND_ANALYZING,
    # EQUIP_SHOWING_TREND, EQUIP_CORRELATION

class StateMachine:
    def __init__(self, workflow_type: WorkflowType = WorkflowType.CONVENTIONAL): ...
    @property
    def workflow_type(self) -> WorkflowType: ...
    def set_workflow_type(self, workflow_type: WorkflowType) -> None:
        """IDLE/SELECTING_WORKFLOW에서만 변경 허용"""

def _build_transitions(workflow_type: WorkflowType) -> dict[WorkflowState, list[WorkflowState]]:
    """공통 전이 + 워크플로우별 전이를 합산하여 반환"""
```

**기존 코드 수정:**
- `StateMachine.__init__` — `workflow_type` 파라미터 추가, `self._transitions` 인스턴스 변수로 전이 테이블 보유
- `StateMachine.can_transition_to` / `get_next_auto_state` — `TRANSITIONS` 글로벌 대신 `self._transitions` 참조
- `TRANSITIONS` 글로벌 변수는 하위 호환용으로 `_build_transitions(CONVENTIONAL)`로 유지

**루코드 구현 시 주의사항:**
- MAP/장비 워크플로우 구현 시 WorkflowState enum의 주석 해제 → 대응 전이 규칙 dict 주석 해제 → `_build_transitions`에 elif 추가
- `SELECTING_WORKFLOW`가 `DECISION_STATES`에 포함되어 사용자 입력을 기다림
- `set_workflow_type()`은 이미 진행 중인 워크플로우에서 유형 변경을 방지함
- `app.py`의 `_parse_workflow_type()`이 유형을 판별하여 `sm.set_workflow_type()` 호출
