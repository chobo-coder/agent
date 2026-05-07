"""Reusable Streamlit UI components."""

import streamlit as st


def multi_select_widget(label: str, options: list[str]) -> list[str]:
    """Render a multi-select widget and return selected items."""
    return st.multiselect(label, options)


def threshold_slider(
    label: str = "Threshold", min_val: float = 0.0, max_val: float = 1.0
) -> float:
    """Render a threshold slider."""
    return st.slider(label, min_value=min_val, max_value=max_val, value=0.5, step=0.05)


def confirm_button(label: str = "확인") -> bool:
    """Render a confirm button."""
    return st.button(label, type="primary")


def option_radio(label: str, options: list[str]) -> str | None:
    """Render radio buttons for option selection."""
    return st.radio(label, options)
