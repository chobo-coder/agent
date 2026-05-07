"""Session state management wrapper for Streamlit."""

from typing import Any

import streamlit as st
import pandas as pd

from core.state_machine import StateMachine, WorkflowState


class SessionManager:
    """Wraps st.session_state for typed access."""

    def __init__(self):
        if "initialized" not in st.session_state:
            self._initialize()

    def _initialize(self) -> None:
        st.session_state.initialized = True
        st.session_state.state_machine = StateMachine()
        st.session_state.chat_history = []
        st.session_state.workflow_context = {}  # str -> DataFrame
        st.session_state.current_product = None
        st.session_state.metadata = {}

    @property
    def state_machine(self) -> StateMachine:
        return st.session_state.state_machine

    @property
    def current_state(self) -> WorkflowState:
        return self.state_machine.state

    @property
    def chat_history(self) -> list[dict[str, str]]:
        return st.session_state.chat_history

    def add_message(self, role: str, content: str) -> None:
        st.session_state.chat_history.append({"role": role, "content": content})

    def get_dataframe(self, key: str) -> pd.DataFrame | None:
        return st.session_state.workflow_context.get(key)

    def set_dataframe(self, key: str, df: pd.DataFrame) -> None:
        st.session_state.workflow_context[key] = df

    def set_metadata(self, key: str, value: Any) -> None:
        st.session_state.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return st.session_state.metadata.get(key, default)

    def reset(self) -> None:
        st.session_state.clear()
        self._initialize()
