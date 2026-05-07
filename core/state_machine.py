"""Finite State Machine for the analysis workflow."""

from enum import Enum, auto
from typing import Optional


class WorkflowState(Enum):
    IDLE = auto()
    QUERYING_DATA = auto()
    SHOWING_QUERY_RESULTS = auto()
    AWAITING_LOAD_DECISION = auto()
    LOADING_PARQUET = auto()
    SHOWING_DATA_OVERVIEW = auto()
    AWAITING_PREPROCESS = auto()
    PREPROCESSING = auto()
    SHOWING_PREPROCESSED = auto()
    ANALYZING_FEATURES = auto()
    SHOWING_FEATURES = auto()
    AWAITING_COMBINATIONS = auto()
    PREDICTING = auto()
    SHOWING_PREDICTIONS = auto()
    COMPLETED = auto()


# States where LLM decision is required
DECISION_STATES = {
    WorkflowState.SHOWING_QUERY_RESULTS,
    WorkflowState.SHOWING_DATA_OVERVIEW,
    WorkflowState.SHOWING_FEATURES,
}

# Valid state transitions
TRANSITIONS: dict[WorkflowState, list[WorkflowState]] = {
    WorkflowState.IDLE: [WorkflowState.QUERYING_DATA],
    WorkflowState.QUERYING_DATA: [WorkflowState.SHOWING_QUERY_RESULTS],
    WorkflowState.SHOWING_QUERY_RESULTS: [
        WorkflowState.AWAITING_LOAD_DECISION,
    ],
    WorkflowState.AWAITING_LOAD_DECISION: [
        WorkflowState.LOADING_PARQUET,
        WorkflowState.SHOWING_DATA_OVERVIEW,  # skip loading if not needed
    ],
    WorkflowState.LOADING_PARQUET: [WorkflowState.SHOWING_DATA_OVERVIEW],
    WorkflowState.SHOWING_DATA_OVERVIEW: [WorkflowState.AWAITING_PREPROCESS],
    WorkflowState.AWAITING_PREPROCESS: [WorkflowState.PREPROCESSING],
    WorkflowState.PREPROCESSING: [WorkflowState.SHOWING_PREPROCESSED],
    WorkflowState.SHOWING_PREPROCESSED: [WorkflowState.ANALYZING_FEATURES],
    WorkflowState.ANALYZING_FEATURES: [WorkflowState.SHOWING_FEATURES],
    WorkflowState.SHOWING_FEATURES: [WorkflowState.AWAITING_COMBINATIONS],
    WorkflowState.AWAITING_COMBINATIONS: [WorkflowState.PREDICTING],
    WorkflowState.PREDICTING: [WorkflowState.SHOWING_PREDICTIONS],
    WorkflowState.SHOWING_PREDICTIONS: [WorkflowState.COMPLETED],
    WorkflowState.COMPLETED: [WorkflowState.IDLE],
}


class StateMachine:
    """Manages workflow state transitions."""

    def __init__(self):
        self._state = WorkflowState.IDLE

    @property
    def state(self) -> WorkflowState:
        return self._state

    @property
    def is_decision_point(self) -> bool:
        return self._state in DECISION_STATES

    def can_transition_to(self, target: WorkflowState) -> bool:
        allowed = TRANSITIONS.get(self._state, [])
        return target in allowed

    def transition_to(self, target: WorkflowState) -> None:
        if not self.can_transition_to(target):
            raise InvalidTransitionError(
                f"Cannot transition from {self._state} to {target}"
            )
        self._state = target

    def reset(self) -> None:
        self._state = WorkflowState.IDLE

    def get_next_auto_state(self) -> Optional[WorkflowState]:
        """Get the next state for automatic (non-decision) transitions."""
        if self.is_decision_point:
            return None
        allowed = TRANSITIONS.get(self._state, [])
        return allowed[0] if len(allowed) == 1 else None


class InvalidTransitionError(Exception):
    pass
