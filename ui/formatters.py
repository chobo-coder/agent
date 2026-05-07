"""Data formatting utilities for chat display."""

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt


def format_dataframe(df: pd.DataFrame, max_rows: int = 100) -> None:
    """Display a DataFrame in the chat."""
    if len(df) > max_rows:
        st.dataframe(df.head(max_rows))
        st.caption(f"상위 {max_rows}행만 표시 (전체 {len(df)}행)")
    else:
        st.dataframe(df)


def render_figure(fig: plt.Figure) -> None:
    """Display a matplotlib figure."""
    st.pyplot(fig)
    plt.close(fig)


def format_summary_table(data: dict) -> str:
    """Convert a dict to a markdown table."""
    lines = ["| 항목 | 값 |", "|------|-----|"]
    for k, v in data.items():
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)
