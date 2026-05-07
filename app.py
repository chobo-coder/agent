"""Streamlit entry point for the data analysis agent."""

import streamlit as st

from core.session import SessionManager
from core.orchestrator import Orchestrator
from ui.chat import render_chat_history, render_sidebar


def main():
    st.set_page_config(
        page_title="Data Analysis Agent",
        page_icon="chart_with_upwards_trend",
        layout="wide",
    )
    st.title("Data Analysis Agent")

    session = SessionManager()
    orchestrator = Orchestrator(session)

    render_sidebar(session)
    render_chat_history(session)

    user_input = st.chat_input("분석 요청을 입력하세요...")
    if user_input:
        session.add_message("user", user_input)
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("처리 중..."):
                result = orchestrator.handle_input(user_input)
            st.markdown(result.summary)

        session.add_message("assistant", result.summary)
        st.rerun()


if __name__ == "__main__":
    main()
