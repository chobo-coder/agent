"""Chat message rendering and sidebar."""

import streamlit as st

from core.session import SessionManager
from core.state_machine import WorkflowState, TRANSITIONS
from ui.formatters import format_dataframe, render_figure


def render_chat_history(session: SessionManager) -> None:
    """Render all messages in chat history."""
    for msg in session.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


def render_sidebar(session: SessionManager) -> None:
    """Render workflow progress in the sidebar."""
    with st.sidebar:
        st.header("Workflow Progress")

        all_states = list(WorkflowState)
        current = session.current_state
        current_idx = all_states.index(current)

        for i, state in enumerate(all_states):
            label = state.name.replace("_", " ").title()
            if i < current_idx:
                st.markdown(f"~~{label}~~")
            elif i == current_idx:
                st.markdown(f"**>> {label}**")
            else:
                st.markdown(f"{label}")

        st.divider()
        if st.button("Reset Workflow"):
            session.reset()
            st.rerun()


def render_step_result(result) -> None:
    """Render a StepResult within a chat message."""
    if result.summary:
        st.markdown(result.summary)

    for key, df in result.dataframes.items():
        st.subheader(key.replace("_", " ").title())
        format_dataframe(df)

    for fig in result.figures:
        render_figure(fig)
