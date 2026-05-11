"""워크플로우 테스트 에이전트.

localhost:8506에서 실행하여 전체 워크플로우를 mock 데이터로 테스트.
사이드바에 테스트 시나리오 버튼을 제공하여 빠르게 각 단계를 진행.

실행: streamlit run test_app.py --server.port 8506
"""

import streamlit as st

# LLM 호출을 mock으로 패치 (API 키 없이 동작)
import llm.client as _llm_mod

class _MockLLMClient:
    """LLM API 없이 테스트용 — 예외 발생시켜 regex fallback 파서 사용"""
    def complete(self, prompt: str, system: str | None = None) -> str:
        raise _llm_mod.LLMError("Mock mode: regex fallback 사용")
    def complete_with_history(self, messages, system=None) -> str:
        raise _llm_mod.LLMError("Mock mode: regex fallback 사용")

_llm_mod.LLMClient = _MockLLMClient  # 패치

# 이제 app.py 로직을 import
from core.session import SessionManager
from core.state_machine import WorkflowState
from ui.chat import render_chat_history, render_sidebar, STATE_LABELS, SIDEBAR_STAGES, get_sidebar_stages
from app import handle_user_input, WORKFLOW_MENU, _build_welcome_message, _handle_eda


# =============================================================================
# 개발자 모드 판별
# =============================================================================

def _is_dev_mode() -> bool:
    """URL 쿼리 파라미터로 개발자 모드 판별.
    접속 URL에 ?dev=1 이 있으면 True.
    예: http://localhost:8506/?dev=1
    """
    return st.query_params.get("dev") == "1"


# =============================================================================
# 테스트 시나리오 정의
# =============================================================================

TEST_SCENARIOS = {
    "1단계: 워크플로우 선택 (기존 분석)": "1",
    "2단계: 조건 입력 (전체 파라미터)": "LOT A01 oper_001 20250101 20250331 cat2 분석해줘",
    "3단계: S3 추가 로딩 (예)": "예, 추가 로딩해줘",
    "3단계: S3 추가 로딩 (아니오)": "아니오, 충분합니다",
    "4-1단계: 전처리 추가 (결측치 제거)": "1",
    "4-2단계: 전처리 추가 (스케일링)": "7",
    "4-3단계: 전처리 완료": "완료",
    "5단계: 피처 + 임계값": "col_3, col_4로 0.7 기준으로 예측해줘",
}

MAP_TEST_SCENARIOS = {
    "MAP-1: 워크플로우 선택 (MAP)": "2",
    "MAP-2: 조건 입력": "LOT A01 LOT_001 oper_001 20250101 20250331 분석해줘",
    "MAP-3: Wafer 선택 (전체)": "전체",
    "MAP-4: 전공정 merge (전체)": "전체",
}


def render_test_sidebar(session: SessionManager) -> None:
    """테스트 전용 사이드바 — 롤백 가능 스테이지 + 테스트 버튼"""
    with st.sidebar:
        st.header("워크플로우 진행")

        # ── 진행률 + 롤백 버튼 (원본 render_sidebar 로직) ──
        current = session.current_state
        completed_states = session.get_completed_states()

        stages = get_sidebar_stages(session)
        current_stage_idx = -1
        all_states = list(WorkflowState)
        current_all_idx = all_states.index(current)
        for i, stage in enumerate(stages):
            if stage == current:
                current_stage_idx = i
                break
            if all_states.index(current) > all_states.index(stage):
                current_stage_idx = i

        progress = (current_stage_idx / (len(stages) - 1)) if current_stage_idx >= 0 and len(stages) > 1 else 0
        st.progress(min(progress, 1.0), text=f"{int(min(progress, 1.0) * 100)}%")

        st.divider()

        for stage in stages:
            label = STATE_LABELS.get(stage.name, stage.name)
            stage_all_idx = all_states.index(stage)

            if stage == current:
                st.markdown(f"**▶ {label}**")
            elif stage.name in [s.name for s in completed_states] and stage_all_idx < current_all_idx:
                if st.button(f"↩ {label}", key=f"rollback_{stage.name}", use_container_width=True):
                    session.restore_snapshot(stage)
                    st.rerun()
            elif stage_all_idx < current_all_idx:
                st.markdown(f"~~{label}~~")
            else:
                st.markdown(f"○ {label}")

        st.divider()

        # ── 현재 컨텍스트 ──
        query_params = session.get_metadata("query_params")
        if query_params:
            info_lines = []
            if query_params.get("lot_cd"):
                info_lines.append(f"LOT: {query_params['lot_cd']}")
            if query_params.get("from_date"):
                info_lines.append(f"기간: {query_params['from_date']} ~ {query_params.get('end_date', '')}")
            if query_params.get("oper"):
                info_lines.append(f"공정: {query_params['oper']}")
            if info_lines:
                st.info("\n".join(info_lines))

        # 전처리 계획 (누적된 액션 표시 + 개별 롤백)
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

        # ── 개발자 전용 영역 (URL에 ?dev=1 필요) ──
        if _is_dev_mode():
            # 디버그 정보
            with st.expander("디버그 정보", expanded=False):
                sm = session.state_machine
                st.code(f"현재 상태: {current.name}")
                st.code(f"워크플로우: {sm.workflow_type.value}")
                st.code(f"히스토리: {[s.name for s in sm.history]}")
                st.code(f"스냅샷: {list(st.session_state.get('snapshots', {}).keys())}")
                st.code(f"채팅 수: {len(session.chat_history)}")

                base_dir = st.session_state.get("snapshot_base_dir")
                if base_dir and base_dir.exists():
                    files = list(base_dir.rglob("*.parquet"))
                    st.code(f"디스크 파일: {len(files)}개")
                    for f in files:
                        st.code(f"  {f.relative_to(base_dir)}")

            st.divider()

            # 테스트 시나리오 버튼
            st.subheader("Conventional 시나리오")
            st.caption("버튼 클릭 → 자동 입력")

            for label, input_text in TEST_SCENARIOS.items():
                if st.button(label, key=f"test_{label}", use_container_width=True):
                    st.session_state._test_input = input_text
                    st.rerun()

            st.divider()

            st.subheader("MAP 시나리오")
            for label, input_text in MAP_TEST_SCENARIOS.items():
                if st.button(label, key=f"test_{label}", use_container_width=True):
                    st.session_state._test_input = input_text
                    st.rerun()

            st.divider()

        if st.button("처음부터 다시", type="secondary", use_container_width=True):
            session.reset()
            st.rerun()


def main():
    st.set_page_config(
        page_title="워크플로우 테스트 에이전트",
        page_icon="🧪",
        layout="wide",
    )
    st.title("🧪 워크플로우 테스트 에이전트")
    st.caption("mock 데이터 기반 전체 워크플로우 테스트 · 사이드바 롤백 기능 검증")

    session = SessionManager()
    render_test_sidebar(session)
    render_chat_history(session)

    # 초기 안내 메시지
    if not session.chat_history:
        with st.chat_message("assistant"):
            welcome = _build_welcome_message()
            st.markdown(welcome)
            st.markdown("\n---\n**테스트 모드**: 사이드바의 '테스트 시나리오' 버튼으로 빠르게 진행할 수 있습니다.")

    # EDA 버튼 (SHOWING_QUERY_RESULTS 상태에서만)
    if session.current_state == WorkflowState.SHOWING_QUERY_RESULTS:
        eda_done = session.get_metadata("eda_done", False)
        if not eda_done:
            if st.button("📊 EDA 수행 (결측치·저분산·고상관 분석)", use_container_width=True):
                _handle_eda(session)
                st.rerun()
        else:
            st.success("EDA 완료 — 아래 채팅에서 S3 추가 로딩 여부를 입력하세요.")

    # 피처 선택 UI (SHOWING_FEATURES 상태에서만)
    if session.current_state == WorkflowState.SHOWING_FEATURES:
        from app import _render_scanning_table
        _render_scanning_table()

    # 몰림 후보 선택 UI (MAP_SHOWING_FAIL_CONCENTRATION 상태에서만)
    if session.current_state == WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION:
        from app import _render_fail_candidates_table
        _render_fail_candidates_table()

    # 전공정 similarity 테이블 + feature map
    if session.current_state == WorkflowState.MAP_SHOWING_PREV_PROCESS_RESULTS:
        from app import _render_similarity_table
        _render_similarity_table()

    # 예측 결과 scatter plot (COMPLETED 상태에서)
    if session.current_state == WorkflowState.COMPLETED:
        plot_png = session.get_metadata("prediction_plot")
        if plot_png:
            st.image(plot_png, caption="Feature Scatter Plot", use_container_width=True)

    # MAP wafer map plots
    map_plots = session.get_metadata("map_plots")
    if map_plots and session.current_state in (
        WorkflowState.MAP_SHOWING_RESULTS,
        WorkflowState.MAP_AWAITING_PREV_PROCESS_MERGE,
        WorkflowState.MAP_SHOWING_PREV_PROCESS_RESULTS,
        WorkflowState.COMPLETED,
    ):
        # 요약 metric
        pattern = session.get_metadata("map_pattern")
        if pattern and session.current_state == WorkflowState.MAP_SHOWING_RESULTS:
            from app import schema as _schema
            pattern_labels = {
                "edge": "Edge 집중", "center": "Center 집중",
                "random": "Random", "no_fail": "Fail 없음",
            }
            map_die_df = session.get_dataframe("map_die_detail")
            if map_die_df is not None:
                total = len(map_die_df)
                fails = int(map_die_df[_schema.MAP_FAIL_COLUMN].sum())
                rate = f"{fails/total:.2%}" if total > 0 else "0%"
                col1, col2, col3 = st.columns(3)
                col1.metric("Fail / Total", f"{fails} / {total}")
                col2.metric("Fail Rate", rate)
                col3.metric("패턴", pattern_labels.get(pattern, pattern))

        with st.expander(f"Wafer Map ({len(map_plots)}장)",
                         expanded=session.current_state == WorkflowState.MAP_SHOWING_RESULTS):
            for p in map_plots:
                st.image(p["png"], caption=f"{p['run_id']} / {p['wafer_id']}")

        # 전공정 merge 안내
        if session.current_state == WorkflowState.MAP_SHOWING_RESULTS:
            from app import schema as _schema
            st.divider()
            st.markdown("#### 다음 단계: 전공정 데이터 Merge")
            st.info(
                "전공정 데이터를 merge하면 fail 패턴과 상관이 높은 feature를 분석할 수 있습니다.\n\n"
                "아래 채팅에서 선택해주세요:\n"
                "- **번호 입력** (예: `1, 2`) 또는 `전체` → 전공정 merge + similarity 분석\n"
                "- `아니오` / `skip` → 분석 종료"
            )

    # 테스트 시나리오 자동 입력 처리
    test_input = st.session_state.pop("_test_input", None)
    feature_input = st.session_state.pop("_feature_submit", None)
    candidate_input = st.session_state.pop("_candidate_submit", None)
    if session.current_state == WorkflowState.SHOWING_FEATURES:
        user_input = test_input or feature_input
    elif session.current_state == WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION:
        user_input = test_input or candidate_input
    else:
        user_input = test_input or st.chat_input("메시지를 입력하세요...")

    if user_input:
        # 중복 방지
        if session.chat_history and session.chat_history[-1].get("content") == user_input:
            if not test_input:
                st.stop()

        session.add_message("user", user_input)
        response = handle_user_input(session, user_input)
        session.add_message("assistant", response)
        st.rerun()


if __name__ == "__main__":
    main()
