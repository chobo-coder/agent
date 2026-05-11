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
    # MAP 워크플로우
    "MAP_QUERYING_LOT": "LOT 조회",
    "MAP_SHOWING_FAIL_CONCENTRATION": "Fail 몰림 확인",
    "MAP_SELECTING_WAFERS": "Wafer 선택",
    "MAP_ANALYZING_WAFER_MAP": "Wafer Map 분석",
    "MAP_SHOWING_RESULTS": "MAP 분석 결과",
    "MAP_AWAITING_PREV_PROCESS_MERGE": "전공정 Merge 선택",
    "MAP_ANALYZING_PREV_PROCESS": "전공정 분석",
    "MAP_SHOWING_PREV_PROCESS_RESULTS": "전공정 분석 결과",
}

# 사이드바에 표시할 주요 스테이지 (사용자에게 의미 있는 단계만)
SIDEBAR_STAGES = [
    WorkflowState.COLLECTING_PARAMS,
    WorkflowState.SHOWING_QUERY_RESULTS,
    WorkflowState.SHOWING_DATA_OVERVIEW,
    WorkflowState.SHOWING_FEATURES,
    WorkflowState.SHOWING_PREDICTIONS,
    WorkflowState.COMPLETED,
]

# MAP 워크플로우용 사이드바 스테이지
MAP_SIDEBAR_STAGES = [
    WorkflowState.COLLECTING_PARAMS,
    WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION,
    WorkflowState.MAP_SHOWING_RESULTS,
    WorkflowState.MAP_SHOWING_PREV_PROCESS_RESULTS,
    WorkflowState.COMPLETED,
]


def get_sidebar_stages(session: SessionManager) -> list[WorkflowState]:
    """현재 워크플로우에 맞는 사이드바 스테이지 반환"""
    wf_type = session.get_metadata("workflow_type")
    if wf_type == "map_trend":
        return MAP_SIDEBAR_STAGES
    return SIDEBAR_STAGES


def render_chat_history(session: SessionManager) -> None:
    """채팅 히스토리 렌더링"""
    for msg in session.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


def render_sidebar(session: SessionManager) -> None:
    """사이드바: 워크플로우 진행률 + 상태 정보 (완료 스테이지 클릭 → 롤백)"""
    with st.sidebar:
        st.header("워크플로우 진행")

        stages = get_sidebar_stages(session)

        # 진행률 바
        current = session.current_state
        completed_states = session.get_completed_states()

        # 현재 상태가 stages에 포함되어 있으면 해당 인덱스, 아니면 가장 가까운 이전 단계
        current_stage_idx = -1
        for i, stage in enumerate(stages):
            if stage == current:
                current_stage_idx = i
                break
            all_states = list(WorkflowState)
            if all_states.index(current) > all_states.index(stage):
                current_stage_idx = i

        progress = (current_stage_idx / (len(stages) - 1)) if current_stage_idx >= 0 and len(stages) > 1 else 0
        st.progress(min(progress, 1.0), text=f"{int(min(progress, 1.0) * 100)}%")

        st.divider()

        # 단계별 표시
        all_states = list(WorkflowState)
        current_all_idx = all_states.index(current)

        for stage in stages:
            label = STATE_LABELS.get(stage.name, stage.name)
            stage_all_idx = all_states.index(stage)

            if stage == current:
                # 현재 스테이지 — 볼드 텍스트
                st.markdown(f"**▶ {label}**")
            elif stage.name in [s.name for s in completed_states] and stage_all_idx < current_all_idx:
                # 완료된 스테이지 — 클릭 가능 버튼
                if st.button(f"↩ {label}", key=f"rollback_{stage.name}", use_container_width=True):
                    session.restore_snapshot(stage)
                    st.rerun()
            elif stage_all_idx < current_all_idx:
                # 지나갔지만 스냅샷 없는 스테이지 — 취소선
                st.markdown(f"~~{label}~~")
            else:
                # 미래 스테이지 — 빈 원
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

        # 전처리 계획 (SHOWING_DATA_OVERVIEW 상태에서 누적된 액션 표시)
        plan = session.get_metadata("preprocess_plan")
        if plan and plan.actions:
            with st.expander(f"전처리 계획 ({len(plan.actions)}개 추가됨)", expanded=True):
                for i, action in enumerate(plan.actions):
                    col_label, col_btn = st.columns([3, 1])
                    with col_label:
                        st.caption(f"{i+1}. {action.tool_name}")
                    with col_btn:
                        if st.button("✕", key=f"pp_remove_{i}", help=f"{action.tool_name} 제거"):
                            plan.remove(i)
                            session.set_metadata("preprocess_plan", plan)
                            st.rerun()
                remaining = plan.remaining_shape
                st.caption(f"예상: {remaining[0]}행 × {remaining[1]}열")

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
