"""Tests for the workflow state machine."""

import pytest

from core.state_machine import StateMachine, WorkflowState, InvalidTransitionError


class TestStateMachine:
    def test_initial_state(self):
        sm = StateMachine()
        assert sm.state == WorkflowState.IDLE

    def test_valid_transition(self):
        sm = StateMachine()
        sm.transition_to(WorkflowState.QUERYING_DATA)
        assert sm.state == WorkflowState.QUERYING_DATA

    def test_invalid_transition(self):
        sm = StateMachine()
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(WorkflowState.PREDICTING)

    def test_full_happy_path(self):
        sm = StateMachine()
        path = [
            WorkflowState.QUERYING_DATA,
            WorkflowState.SHOWING_QUERY_RESULTS,
            WorkflowState.AWAITING_LOAD_DECISION,
            WorkflowState.LOADING_PARQUET,
            WorkflowState.SHOWING_DATA_OVERVIEW,
            WorkflowState.AWAITING_PREPROCESS,
            WorkflowState.PREPROCESSING,
            WorkflowState.SHOWING_PREPROCESSED,
            WorkflowState.ANALYZING_FEATURES,
            WorkflowState.SHOWING_FEATURES,
            WorkflowState.AWAITING_COMBINATIONS,
            WorkflowState.PREDICTING,
            WorkflowState.SHOWING_PREDICTIONS,
            WorkflowState.COMPLETED,
        ]
        for state in path:
            sm.transition_to(state)
        assert sm.state == WorkflowState.COMPLETED

    def test_skip_loading_path(self):
        sm = StateMachine()
        sm.transition_to(WorkflowState.QUERYING_DATA)
        sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)
        sm.transition_to(WorkflowState.AWAITING_LOAD_DECISION)
        sm.transition_to(WorkflowState.SHOWING_DATA_OVERVIEW)
        assert sm.state == WorkflowState.SHOWING_DATA_OVERVIEW

    def test_decision_points(self):
        sm = StateMachine()
        sm.transition_to(WorkflowState.QUERYING_DATA)
        sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)
        assert sm.is_decision_point is True

    def test_non_decision_point(self):
        sm = StateMachine()
        assert sm.is_decision_point is False

    def test_reset(self):
        sm = StateMachine()
        sm.transition_to(WorkflowState.QUERYING_DATA)
        sm.reset()
        assert sm.state == WorkflowState.IDLE

    def test_auto_advance(self):
        sm = StateMachine()
        next_state = sm.get_next_auto_state()
        assert next_state == WorkflowState.QUERYING_DATA

    def test_no_auto_advance_at_decision(self):
        sm = StateMachine()
        sm.transition_to(WorkflowState.QUERYING_DATA)
        sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)
        assert sm.get_next_auto_state() is None
