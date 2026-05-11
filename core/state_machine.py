"""Finite State Machine for the analysis workflow.

워크플로우 3종:
  - conventional: 기존 분석 (조회→전처리→피처→예측)
  - map_trend:    MAP 경향성 분석
  - equip_trend:  장비 경향성 분석
"""

from enum import Enum, auto
from typing import Optional


# =============================================================================
# 워크플로우 유형
# =============================================================================

class WorkflowType(Enum):
    CONVENTIONAL = "conventional"   # 기존 분석
    MAP_TREND = "map_trend"         # MAP 경향성 분석
    YIELD_TREND = "yield_trend"     # 수율 경향성 분석
    EQUIP_TREND = "equip_trend"     # TODO: 장비 경향성 분석


# =============================================================================
# 공통 상태 + 워크플로우별 상태
# =============================================================================

class WorkflowState(Enum):
    # ── 공통 (모든 워크플로우가 공유) ──
    IDLE = auto()
    SELECTING_WORKFLOW = auto()      # 워크플로우 유형 선택
    COLLECTING_PARAMS = auto()       # 기간/LOT 등 필수값 수집
    VALIDATING_PARAMS = auto()       # 필수 입력값 체크
    QUERYING_DATA = auto()
    SHOWING_QUERY_RESULTS = auto()
    AWAITING_LOAD_DECISION = auto()
    LOADING_PARQUET = auto()
    SHOWING_DATA_OVERVIEW = auto()

    # ── conventional 워크플로우 ──
    AWAITING_PREPROCESS = auto()
    PREPROCESSING = auto()
    SHOWING_PREPROCESSED = auto()
    ANALYZING_FEATURES = auto()
    SHOWING_FEATURES = auto()
    AWAITING_COMBINATIONS = auto()
    PREDICTING = auto()
    SHOWING_PREDICTIONS = auto()

    # ── MAP 경향성 워크플로우 ──
    MAP_QUERYING_LOT = auto()                # LOT 조회 + 1차 fail 집계
    MAP_SHOWING_FAIL_CONCENTRATION = auto()  # run/wafer별 fail 몰림 표시
    MAP_SELECTING_WAFERS = auto()            # 분석 대상 wafer 선택
    MAP_ANALYZING_WAFER_MAP = auto()         # wafer map 상세 조회 + 분석
    MAP_SHOWING_RESULTS = auto()             # 개별/aggregate map + 패턴 판정
    MAP_AWAITING_PREV_PROCESS_MERGE = auto() # 전공정 merge 여부 선택
    MAP_ANALYZING_PREV_PROCESS = auto()      # 전공정 데이터 merge + similarity
    MAP_SHOWING_PREV_PROCESS_RESULTS = auto() # 전공정 feature ranking 표시

    # ── 수율 경향성 워크플로우 ──
    YIELD_LOADING_DATA = auto()         # parquet 확인 → 없으면 DB 조회 + 저장
    YIELD_PREPROCESSING = auto()        # 자동: 피벗, 수율/불량률 계산
    YIELD_SHOWING_OVERVIEW = auto()     # 공정별 수율 + cat별 불량률 표시
    YIELD_AWAITING_REQUEST = auto()     # 사용자 요청 대기 (루프)
    YIELD_SHOWING_DETAIL = auto()       # 요청 결과 표시

    # ── 장비 경향성 워크플로우 ──
    # TODO: 장비 경향성 분석에 필요한 상태 추가
    # EQUIP_SELECTING_PARAMS = auto() # 장비 선택 (장비 ID, 챔버, 센서 등)
    # EQUIP_LOADING_DATA = auto()     # 장비 센서 데이터 로딩
    # EQUIP_TREND_ANALYZING = auto()  # 경향성 분석 실행 (시계열 트렌드, drift 감지)
    # EQUIP_SHOWING_TREND = auto()    # 경향성 결과 표시 (시계열 차트, SPC 차트)
    # EQUIP_CORRELATION = auto()      # 장비 파라미터 ↔ 불량률 상관 분석 (선택)

    # ── 공통 종료 ──
    COMPLETED = auto()


# =============================================================================
# 워크플로우별 분기점 (사용자 입력 대기 상태)
# =============================================================================

DECISION_STATES = {
    WorkflowState.SELECTING_WORKFLOW,
    WorkflowState.COLLECTING_PARAMS,
    WorkflowState.VALIDATING_PARAMS,
    WorkflowState.SHOWING_QUERY_RESULTS,
    WorkflowState.SHOWING_DATA_OVERVIEW,
    WorkflowState.SHOWING_FEATURES,
    WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION,
    WorkflowState.MAP_SHOWING_RESULTS,
    WorkflowState.MAP_AWAITING_PREV_PROCESS_MERGE,
    WorkflowState.MAP_SHOWING_PREV_PROCESS_RESULTS,
    WorkflowState.YIELD_SHOWING_OVERVIEW,
    WorkflowState.YIELD_AWAITING_REQUEST,
    # TODO: 장비 워크플로우 분기점 추가
    # WorkflowState.EQUIP_SELECTING_PARAMS,
    # WorkflowState.EQUIP_SHOWING_TREND,
}


# =============================================================================
# 워크플로우별 전이 규칙
# =============================================================================

# 공통 전이 (데이터 조회까지)
_COMMON_TRANSITIONS: dict[WorkflowState, list[WorkflowState]] = {
    WorkflowState.IDLE: [WorkflowState.SELECTING_WORKFLOW],
    WorkflowState.SELECTING_WORKFLOW: [WorkflowState.COLLECTING_PARAMS],
    WorkflowState.COLLECTING_PARAMS: [
        WorkflowState.VALIDATING_PARAMS,
        WorkflowState.QUERYING_DATA,
    ],
    WorkflowState.VALIDATING_PARAMS: [
        WorkflowState.COLLECTING_PARAMS,
        WorkflowState.QUERYING_DATA,
    ],
    WorkflowState.QUERYING_DATA: [WorkflowState.SHOWING_QUERY_RESULTS],
    WorkflowState.SHOWING_QUERY_RESULTS: [
        WorkflowState.AWAITING_LOAD_DECISION,
    ],
    WorkflowState.AWAITING_LOAD_DECISION: [
        WorkflowState.LOADING_PARQUET,
        WorkflowState.SHOWING_DATA_OVERVIEW,
    ],
    WorkflowState.LOADING_PARQUET: [WorkflowState.SHOWING_DATA_OVERVIEW],
}

# conventional 전이 (오버뷰 이후)
_CONVENTIONAL_TRANSITIONS: dict[WorkflowState, list[WorkflowState]] = {
    WorkflowState.SHOWING_DATA_OVERVIEW: [WorkflowState.AWAITING_PREPROCESS],
    WorkflowState.AWAITING_PREPROCESS: [WorkflowState.PREPROCESSING],
    WorkflowState.PREPROCESSING: [WorkflowState.SHOWING_PREPROCESSED],
    WorkflowState.SHOWING_PREPROCESSED: [WorkflowState.ANALYZING_FEATURES],
    WorkflowState.ANALYZING_FEATURES: [WorkflowState.SHOWING_FEATURES],
    WorkflowState.SHOWING_FEATURES: [WorkflowState.AWAITING_COMBINATIONS],
    WorkflowState.AWAITING_COMBINATIONS: [WorkflowState.PREDICTING],
    WorkflowState.PREDICTING: [WorkflowState.SHOWING_PREDICTIONS],
    WorkflowState.SHOWING_PREDICTIONS: [WorkflowState.COMPLETED],
}

# MAP 경향성 전이 규칙 (파라미터 수집 완료 후 분기)
_MAP_TREND_TRANSITIONS: dict[WorkflowState, list[WorkflowState]] = {
    WorkflowState.COLLECTING_PARAMS: [
        WorkflowState.VALIDATING_PARAMS,
        WorkflowState.MAP_QUERYING_LOT,
    ],
    WorkflowState.VALIDATING_PARAMS: [
        WorkflowState.COLLECTING_PARAMS,
        WorkflowState.MAP_QUERYING_LOT,
    ],
    WorkflowState.MAP_QUERYING_LOT: [WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION],
    WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION: [WorkflowState.MAP_SELECTING_WAFERS],
    WorkflowState.MAP_SELECTING_WAFERS: [WorkflowState.MAP_ANALYZING_WAFER_MAP],
    WorkflowState.MAP_ANALYZING_WAFER_MAP: [WorkflowState.MAP_SHOWING_RESULTS],
    WorkflowState.MAP_SHOWING_RESULTS: [WorkflowState.MAP_AWAITING_PREV_PROCESS_MERGE],
    WorkflowState.MAP_AWAITING_PREV_PROCESS_MERGE: [
        WorkflowState.MAP_ANALYZING_PREV_PROCESS,
        WorkflowState.COMPLETED,
    ],
    WorkflowState.MAP_ANALYZING_PREV_PROCESS: [WorkflowState.MAP_SHOWING_PREV_PROCESS_RESULTS],
    WorkflowState.MAP_SHOWING_PREV_PROCESS_RESULTS: [WorkflowState.COMPLETED],
}

# 수율 경향성 전이 규칙 (파라미터 수집 완료 후 분기)
_YIELD_TREND_TRANSITIONS: dict[WorkflowState, list[WorkflowState]] = {
    WorkflowState.COLLECTING_PARAMS: [
        WorkflowState.VALIDATING_PARAMS,
        WorkflowState.YIELD_LOADING_DATA,
    ],
    WorkflowState.VALIDATING_PARAMS: [
        WorkflowState.COLLECTING_PARAMS,
        WorkflowState.YIELD_LOADING_DATA,
    ],
    WorkflowState.YIELD_LOADING_DATA: [WorkflowState.YIELD_PREPROCESSING],
    WorkflowState.YIELD_PREPROCESSING: [WorkflowState.YIELD_SHOWING_OVERVIEW],
    WorkflowState.YIELD_SHOWING_OVERVIEW: [WorkflowState.YIELD_AWAITING_REQUEST],
    WorkflowState.YIELD_AWAITING_REQUEST: [
        WorkflowState.YIELD_SHOWING_DETAIL,
        WorkflowState.COMPLETED,
    ],
    WorkflowState.YIELD_SHOWING_DETAIL: [WorkflowState.YIELD_AWAITING_REQUEST],
}

# TODO: 장비 경향성 전이 규칙
# _EQUIP_TREND_TRANSITIONS: dict[WorkflowState, list[WorkflowState]] = {
#     WorkflowState.SHOWING_DATA_OVERVIEW: [WorkflowState.EQUIP_SELECTING_PARAMS],
#     WorkflowState.EQUIP_SELECTING_PARAMS: [WorkflowState.EQUIP_LOADING_DATA],
#     WorkflowState.EQUIP_LOADING_DATA: [WorkflowState.EQUIP_TREND_ANALYZING],
#     WorkflowState.EQUIP_TREND_ANALYZING: [WorkflowState.EQUIP_SHOWING_TREND],
#     WorkflowState.EQUIP_SHOWING_TREND: [
#         WorkflowState.EQUIP_CORRELATION,  # 상관 분석 추가
#         WorkflowState.COMPLETED,           # 종료
#     ],
#     WorkflowState.EQUIP_CORRELATION: [WorkflowState.COMPLETED],
# }

# 전이 테이블 빌더
def _build_transitions(workflow_type: WorkflowType) -> dict[WorkflowState, list[WorkflowState]]:
    """워크플로우 유형에 따라 공통 + 전용 전이 규칙을 합산"""
    transitions = dict(_COMMON_TRANSITIONS)
    transitions[WorkflowState.COMPLETED] = [WorkflowState.IDLE]

    if workflow_type == WorkflowType.CONVENTIONAL:
        transitions.update(_CONVENTIONAL_TRANSITIONS)
    elif workflow_type == WorkflowType.MAP_TREND:
        transitions.update(_MAP_TREND_TRANSITIONS)
    elif workflow_type == WorkflowType.YIELD_TREND:
        transitions.update(_YIELD_TREND_TRANSITIONS)
    # TODO: 장비 워크플로우 전이 연결
    # elif workflow_type == WorkflowType.EQUIP_TREND:
    #     transitions.update(_EQUIP_TREND_TRANSITIONS)
    else:
        # 미구현 워크플로우는 conventional fallback
        transitions.update(_CONVENTIONAL_TRANSITIONS)

    return transitions

# 기본값: conventional (하위 호환)
TRANSITIONS = _build_transitions(WorkflowType.CONVENTIONAL)


# =============================================================================
# StateMachine
# =============================================================================

class StateMachine:
    """Manages workflow state transitions."""

    def __init__(self, workflow_type: WorkflowType = WorkflowType.CONVENTIONAL):
        self._state = WorkflowState.IDLE
        self._workflow_type = workflow_type
        self._transitions = _build_transitions(workflow_type)
        self._history: list[WorkflowState] = [WorkflowState.IDLE]

    @property
    def state(self) -> WorkflowState:
        return self._state

    @property
    def workflow_type(self) -> WorkflowType:
        return self._workflow_type

    @property
    def is_decision_point(self) -> bool:
        return self._state in DECISION_STATES

    def set_workflow_type(self, workflow_type: WorkflowType) -> None:
        """워크플로우 유형 변경 (IDLE 또는 SELECTING_WORKFLOW에서만 허용)"""
        if self._state not in (WorkflowState.IDLE, WorkflowState.SELECTING_WORKFLOW):
            raise InvalidTransitionError(
                f"워크플로우 변경은 IDLE/SELECTING_WORKFLOW에서만 가능 (현재: {self._state})"
            )
        self._workflow_type = workflow_type
        self._transitions = _build_transitions(workflow_type)

    def can_transition_to(self, target: WorkflowState) -> bool:
        allowed = self._transitions.get(self._state, [])
        return target in allowed

    @property
    def visited_states(self) -> list[WorkflowState]:
        """방문한 상태 목록 (중복 제거, 순서 유지)"""
        seen: set[WorkflowState] = set()
        result: list[WorkflowState] = []
        for s in self._history:
            if s not in seen:
                seen.add(s)
                result.append(s)
        return result

    @property
    def history(self) -> list[WorkflowState]:
        return list(self._history)

    def transition_to(self, target: WorkflowState) -> None:
        if not self.can_transition_to(target):
            raise InvalidTransitionError(
                f"Cannot transition from {self._state} to {target} "
                f"(workflow: {self._workflow_type.value})"
            )
        self._state = target
        self._history.append(target)

    def jump_to(self, target: WorkflowState) -> None:
        """롤백 전용: 전이 규칙 무시하고 이전에 방문한 상태로 강제 이동.
        미방문 상태로는 점프 불가 → InvalidTransitionError.
        history를 target까지 잘라냄."""
        if target not in self._history:
            raise InvalidTransitionError(
                f"미방문 상태로 점프 불가: {target}"
            )
        # history를 target의 마지막 등장 위치까지 잘라냄
        last_idx = len(self._history) - 1 - self._history[::-1].index(target)
        self._history = self._history[:last_idx + 1]
        self._state = target

    def reset(self) -> None:
        self._state = WorkflowState.IDLE
        self._history = [WorkflowState.IDLE]

    def get_next_auto_state(self) -> Optional[WorkflowState]:
        """Get the next state for automatic (non-decision) transitions."""
        if self.is_decision_point:
            return None
        allowed = self._transitions.get(self._state, [])
        return allowed[0] if len(allowed) == 1 else None


class InvalidTransitionError(Exception):
    pass
