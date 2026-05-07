"""Chat message rendering and sidebar."""

import streamlit as st

from core.session import SessionManager
from core.state_machine import WorkflowState


# 상태별 한국어 라벨
STATE_LABELS = {
    "IDLE": "대기",
    "COLLECTING_PARAMS": "조건 입력",
    "VALIDATING_PARAMS": "입력 확인",
    "QUERYING_DATA": "데이터 조회",
    "SHOWING_QUERY_RESULTS": "조회 결과 확인",
    "AWAITING_LOAD_DECISION": "추가 로딩 결정",
    "LOADING_PARQUET": "S3 로딩",
    "SHOWING_DATA_OVERVIEW": "데이터 오버뷰",
    "AWAITING_PREPROCESS": "전처리 선택",
    "PREPROCESSING": "전처리 실행",
    "SHOWING_PREPROCESSED": "전처리 결과",
    "ANALYZING_FEATURES": "피처 분석",
    "SHOWING_FEATURES": "피처 분석 결과",
    "AWAITING_COMBINATIONS": "피처 조합 선택",
    "PREDICTING": "예측 실행",
    "SHOWING_PREDICTIONS": "예측 결과",
    "COMPLETED": "완료",
}


def render_chat_history(session: SessionManager) -> None:
    """채팅 히스토리 렌더링"""
    for msg in session.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


def render_sidebar(session: SessionManager) -> None:
    """사이드바: 워크플로우 진행률 + 상태 정보"""
    with st.sidebar:
        st.header("워크플로우 진행")

        # 진행률 바
        all_states = list(WorkflowState)
        current = session.current_state
        current_idx = all_states.index(current)
        progress = current_idx / (len(all_states) - 1) if len(all_states) > 1 else 0
        st.progress(progress, text=f"{int(progress * 100)}%")

        st.divider()

        # 단계별 표시
        for i, state in enumerate(all_states):
            label = STATE_LABELS.get(state.name, state.name)
            if i < current_idx:
                st.markdown(f"~~{label}~~")
            elif i == current_idx:
                st.markdown(f"**▶ {label}**")
            else:
                st.markdown(f"○ {label}")

        st.divider()

        # 현재 컨텍스트
        query_params = session.get_metadata("query_params")
        if query_params:
            info_lines = []
            if query_params.get("product"):
                info_lines.append(f"제품: {query_params['product']}")
            if query_params.get("date_from"):
                info_lines.append(f"기간: {query_params['date_from']} ~ {query_params.get('date_to', '')}")
            if query_params.get("process"):
                info_lines.append(f"공정: {query_params['process']}")
            if info_lines:
                st.info("\n".join(info_lines))

        preprocess = session.get_metadata("preprocess_items")
        if preprocess:
            st.caption(f"전처리: {', '.join(preprocess)}")

        features = session.get_metadata("selected_features")
        if features:
            st.caption(f"피처: {', '.join(features)}")

        threshold = session.get_metadata("threshold")
        if threshold:
            st.caption(f"임계값: {threshold}")

        st.divider()

        # Reset 버튼
        if st.button("처음부터 다시", type="secondary", use_container_width=True):
            session.reset()
            st.rerun()


def render_step_result(result) -> None:
    """StepResult를 채팅 내에 렌더링"""
    if result.summary:
        st.markdown(result.summary)

    for key, df in result.dataframes.items():
        with st.expander(f"데이터: {key}", expanded=False):
            st.dataframe(df, use_container_width=True)

    for fig in result.figures:
        st.pyplot(fig)
