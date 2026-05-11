"""Streamlit entry point for the data analysis agent."""

import re
import pandas as pd
import streamlit as st

from core.session import SessionManager
from core.state_machine import WorkflowState, WorkflowType, DECISION_STATES
from ui.chat import render_chat_history, render_sidebar, render_step_result
from ui.formatters import format_dataframe
from llm.client import LLMClient, LLMError
from llm.prompts import PromptBuilder, SYSTEM_PROMPT
from llm.parser import ResponseParser
from pipeline.eda import run_eda
from pipeline.preprocess_preview import PreprocessPlan, preview_tool, apply_plan
from pipeline.threshold_scanning import (
    run_threshold_scanning,
    compute_prediction_metrics,
    plot_feature_scatter,
)
from pipeline import map_trend as map_pipeline
from pipeline import yield_trend as yield_pipeline
import schema


def _get_active_dataframe(session: SessionManager) -> pd.DataFrame | None:
    """merged_data → query_result 순으로 활성 DataFrame 반환"""
    df = session.get_dataframe("merged_data")
    if df is None:
        df = session.get_dataframe("query_result")
    return df


# =============================================================================
# 전처리 도구 메뉴 빌더
# =============================================================================

def _build_preprocess_menu() -> str:
    """schema.PREPROCESSING_TOOLS 기반으로 선택 메뉴 생성"""
    lines = [
        "**적용할 전처리 도구를 선택해주세요.**\n",
        "번호 또는 이름으로 선택할 수 있습니다. (복수 선택 가능)\n",
        "| # | 도구 | 설명 |",
        "|---|------|------|",
    ]
    for i, tool in enumerate(schema.PREPROCESSING_TOOLS, 1):
        lines.append(f"| {i} | {tool['name']} | {tool['description']} |")

    lines.append("")
    lines.append("예: `1, 4, 7` 또는 `결측치 평균 대체, 이상치 제거, 표준 스케일링`")
    lines.append("")
    lines.append("전체 적용하려면 `전부` 입력")

    return "\n".join(lines)


# =============================================================================
# 상태별 메시지
# =============================================================================

STATE_MESSAGES = {
    WorkflowState.SHOWING_QUERY_RESULTS: (
        "SQL 조회 결과입니다.\n\n"
        "**EDA(탐색적 데이터 분석)를 수행하시겠습니까?**\n"
        "아래 버튼으로 EDA를 실행하거나, 바로 다음 단계로 진행할 수 있습니다.\n\n"
        "---\n\n"
        "**추가 데이터를 S3에서 로딩할까요?**\n"
        "- '예' / '로딩해줘' → S3 parquet 추가 로딩\n"
        "- '아니오' / '충분해' → 현재 데이터로 진행"
    ),
    WorkflowState.SHOWING_DATA_OVERVIEW: _build_preprocess_menu(),
    WorkflowState.SHOWING_FEATURES: (
        "피처 분석 결과입니다.\n\n"
        "**아래 Threshold Scanning 테이블에서 행을 클릭하여 피처/조건/임계값을 선택하세요.**\n\n"
        "행을 클릭하면 입력창에 자동으로 채워집니다.\n"
        "직접 입력도 가능합니다. 임계값을 지정하지 않으면 기본값이 적용됩니다."
    ),
}


# =============================================================================
# 핵심 로직
# =============================================================================

def handle_user_input(session: SessionManager, user_input: str) -> str:
    """사용자 입력을 처리하고 응답 텍스트 반환"""
    state = session.current_state
    sm = session.state_machine

    # ─── IDLE: 워크플로우 유형 선택 ───
    if state == WorkflowState.IDLE:
        return _handle_workflow_selection(session, user_input)

    # ─── SELECTING_WORKFLOW: 유형 확정 후 파라미터 수집 진입 ───
    if state == WorkflowState.SELECTING_WORKFLOW:
        return _handle_workflow_selection(session, user_input)

    # ─── COLLECTING_PARAMS: 기간/공정 등 필수값 수집 ───
    if state == WorkflowState.COLLECTING_PARAMS:
        session.save_snapshot()
        return _handle_collecting(session, user_input)

    # ─── VALIDATING_PARAMS: 누락 항목 재요청 ───
    if state == WorkflowState.VALIDATING_PARAMS:
        return _handle_collecting(session, user_input)

    # ─── 분기점 1: 추가 데이터 로딩 여부 ───
    if state == WorkflowState.SHOWING_QUERY_RESULTS:
        session.save_snapshot()
        load = _parse_yes_no(user_input)
        if load:
            with st.status("S3에서 데이터를 로딩하고 있습니다...", expanded=True) as status:
                status.update(label="S3 parquet 파일 탐색 중...")
                sm.transition_to(WorkflowState.AWAITING_LOAD_DECISION)
                status.update(label="parquet 파일 읽는 중...")
                sm.transition_to(WorkflowState.LOADING_PARQUET)
                status.update(label="기존 데이터와 머지 중...")
                sm.transition_to(WorkflowState.SHOWING_DATA_OVERVIEW)
                status.update(label="S3 로딩 완료", state="complete")
            session.save_snapshot()  # 데이터 오버뷰 시점 스냅샷
            return (
                "S3에서 추가 데이터를 로딩하고 머지했습니다.\n"
                "(50건 추가 - mock 데이터)\n\n"
                "---\n\n"
                f"{STATE_MESSAGES[WorkflowState.SHOWING_DATA_OVERVIEW]}"
            )
        else:
            sm.transition_to(WorkflowState.AWAITING_LOAD_DECISION)
            sm.transition_to(WorkflowState.SHOWING_DATA_OVERVIEW)
            session.save_snapshot()  # 데이터 오버뷰 시점 스냅샷
            return (
                "현재 데이터로 진행합니다.\n\n"
                "---\n\n"
                f"{STATE_MESSAGES[WorkflowState.SHOWING_DATA_OVERVIEW]}"
            )

    # ─── 분기점 2: 전처리 도구 선택 (루프) ───
    if state == WorkflowState.SHOWING_DATA_OVERVIEW:
        # 첫 진입 시 스냅샷 저장 + 계획 초기화
        if session.get_metadata("preprocess_plan") is None:
            session.save_snapshot()
            df = _get_active_dataframe(session)
            if df is None:
                import pandas as pd
                import numpy as np
                df = pd.DataFrame(np.random.randn(100, 10), columns=[f"col_{i}" for i in range(10)])
                session.set_dataframe("query_result", df)
            plan = PreprocessPlan(original_shape=df.shape)
            session.set_metadata("preprocess_plan", plan)

        # "완료" 입력 → 누적된 계획 실제 적용 후 다음 단계
        if _parse_complete(user_input):
            return _apply_preprocess_plan(session)

        # 도구 선택 → 미리보기 계산 후 루프
        plan: PreprocessPlan = session.get_metadata("preprocess_plan")
        df = _get_active_dataframe(session)

        # mock/테스트 환경에서 df가 없으면 빈 DataFrame 생성
        if df is None:
            import pandas as pd
            import numpy as np
            df = pd.DataFrame(np.random.randn(100, 10), columns=[f"col_{i}" for i in range(10)])
            session.set_dataframe("query_result", df)

        selected_tools = _parse_tool_selection(user_input)

        for tool in selected_tools:
            action = preview_tool(df, tool, plan)
            plan.add(action)

        session.set_metadata("preprocess_plan", plan)

        # 미리보기 결과 + 추가 선택 안내
        return plan.build_summary()

    # ─── 분기점 3: 피처 조합 + threshold + condition ───
    if state == WorkflowState.SHOWING_FEATURES:
        session.save_snapshot()
        selections = _parse_feature_selections(user_input)

        # 기본값 적용
        for sel in selections:
            if sel["threshold"] is None:
                sel["threshold"] = schema.DEFAULT_THRESHOLD
            if sel["condition"] is None:
                sel["condition"] = ">="

        features = [s["feature"] for s in selections]
        session.set_metadata("selected_features", features)
        session.set_metadata("feature_selections", selections)

        # 예측 지표 계산
        df = session.get_dataframe("preprocessed")
        if df is None:
            df = session.get_dataframe("query_result")

        with st.status("예측을 실행하고 있습니다...", expanded=True) as status:
            status.update(label="선택된 조건으로 지표 계산 중...")
            metrics = compute_prediction_metrics(df, schema.TARGET_COLUMN, selections)
            session.set_metadata("prediction_metrics", metrics)
            st.write(f"Screened: {metrics['screened']}건 / F1: {metrics['f1_score']}")

            status.update(label="Scatter Plot 생성 중...")
            plot_png = plot_feature_scatter(df, schema.TARGET_COLUMN, selections)
            session.set_metadata("prediction_plot", plot_png)

            sm.transition_to(WorkflowState.AWAITING_COMBINATIONS)
            sm.transition_to(WorkflowState.PREDICTING)
            sm.transition_to(WorkflowState.SHOWING_PREDICTIONS)
            session.save_snapshot()  # 예측 결과 시점 스냅샷
            sm.transition_to(WorkflowState.COMPLETED)
            status.update(label="예측 완료", state="complete")

        # 조건 요약
        cond_lines = []
        for s in selections:
            cond_lines.append(f"  - {s['feature']} {s['condition']} {s['threshold']}")
        cond_text = "\n".join(cond_lines)

        return (
            f"**선택 조건**\n{cond_text}\n\n"
            f"**예측 결과**\n"
            f"- 전체: {metrics['total']}건\n"
            f"- Screened: {metrics['screened']}건\n"
            f"- Screen Rate: {metrics['screen_rate']}\n"
            f"- Drop Rate: {metrics['drop_rate']}\n"
            f"- ROI: {metrics['roi']}\n"
            f"- F1 Score: {metrics['f1_score']}\n\n"
            f"---\n\n"
            f"분석이 완료되었습니다! 새 분석을 시작하려면 다시 입력하세요."
        )

    # ─── MAP: fail 몰림 후보에서 wafer 선택 ───
    if state == WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION:
        session.save_snapshot()
        candidates = session.get_metadata("map_concentration_candidates")
        summary_df = session.get_dataframe("map_fail_summary")
        selected = map_pipeline.parse_wafer_selection(user_input, candidates, summary_df)

        if not selected:
            return "wafer를 선택할 수 없습니다. 번호 또는 RUN_01/W03 형식으로 입력해주세요."

        session.set_metadata("map_selected_wafers", selected)
        sm.transition_to(WorkflowState.MAP_SELECTING_WAFERS)

        # 자동으로 wafer map 분석 진행
        params = session.get_metadata("query_params", {})

        with st.status("Wafer Map을 분석하고 있습니다...", expanded=True) as status:
            status.update(label="Wafer Map 데이터 조회 중...")
            map_df = map_pipeline.query_wafer_map_detail(params, selected)
            session.set_dataframe("map_die_detail", map_df)

            status.update(label="패턴 분석 중 (edge/center/random)...")
            pattern = map_pipeline.classify_pattern(map_df)
            session.set_metadata("map_pattern", pattern)

            status.update(label="Aggregate Map 생성 중...")
            agg_df = map_pipeline.build_aggregate_fail_map(map_df)
            session.set_dataframe("map_aggregate", agg_df)

            # wafer별 plot + aggregate plot 생성
            lot_cd = params.get("lot_cd", "")
            layout = schema.MAP_LAYOUT_BY_LOT_CD.get(lot_cd, schema.MAP_DEFAULT_LAYOUT)

            plots = []
            for w in selected:
                status.update(label=f"Wafer Map 렌더링 중... ({w['wafer_id']})")
                png = map_pipeline.plot_wafer_map(map_df, w["wafer_id"], w["run_id"], layout)
                plots.append({"run_id": w["run_id"], "wafer_id": w["wafer_id"], "png": png})

            status.update(label="Aggregate Map 렌더링 중...")
            agg_png = map_pipeline.plot_aggregate_map(agg_df)
            plots.append({"run_id": "aggregate", "wafer_id": "all", "png": agg_png})
            session.set_metadata("map_plots", plots)
            status.update(label="MAP 분석 완료", state="complete")

        sm.transition_to(WorkflowState.MAP_ANALYZING_WAFER_MAP)
        sm.transition_to(WorkflowState.MAP_SHOWING_RESULTS)
        session.save_snapshot()

        return map_pipeline.build_map_results_message(map_df, selected, pattern)

    # ─── MAP: 전공정 merge 여부 선택 ───
    if state == WorkflowState.MAP_SHOWING_RESULTS:
        return _handle_map_prev_process_decision(session, user_input)

    # ─── MAP: 전공정 결과 표시 후 완료 ───
    if state == WorkflowState.MAP_SHOWING_PREV_PROCESS_RESULTS:
        sm.transition_to(WorkflowState.COMPLETED)
        return handle_user_input(session, user_input)

    # ─── YIELD: overview 표시 후 요청 대기 진입 ───
    if state == WorkflowState.YIELD_SHOWING_OVERVIEW:
        sm.transition_to(WorkflowState.YIELD_AWAITING_REQUEST)
        return _handle_yield_request(session, user_input)

    # ─── YIELD: 사용자 요청 처리 (루프) ───
    if state == WorkflowState.YIELD_AWAITING_REQUEST:
        return _handle_yield_request(session, user_input)

    # ─── YIELD: 상세 표시 후 다시 요청 대기 ───
    if state == WorkflowState.YIELD_SHOWING_DETAIL:
        sm.transition_to(WorkflowState.YIELD_AWAITING_REQUEST)
        return _handle_yield_request(session, user_input)

    # TODO: 장비 경향성 워크플로우 상태 핸들링

    # ─── COMPLETED: 새 워크플로우 시작 ───
    if state == WorkflowState.COMPLETED:
        sm.reset()
        return handle_user_input(session, user_input)

    return "알 수 없는 상태입니다. Reset을 눌러주세요."


# =============================================================================
# 워크플로우 유형 선택
# =============================================================================

WORKFLOW_MENU = (
    "**어떤 분석을 진행할까요?**\n\n"
    "| # | 분석 유형 | 설명 |\n"
    "|---|----------|------|\n"
    "| 1 | 기존 분석 (Conventional) | 전처리 → 피처 분석 → 예측 |\n"
    "| 2 | MAP 경향성 분석 | wafer map 공간 패턴 분석 |\n"
    "| 3 | 수율 경향성 분석 | 공정별 수율 + cat별 불량률 trend |\n"
    "| 4 | 장비 경향성 분석 | 장비 센서 시계열 트렌드 분석 |\n\n"
    "번호 또는 이름으로 선택해주세요."
)

def _handle_workflow_selection(session: SessionManager, user_input: str) -> str:
    """워크플로우 유형을 판별하고 파라미터 수집으로 진입"""
    sm = session.state_machine

    if sm.state == WorkflowState.IDLE:
        sm.transition_to(WorkflowState.SELECTING_WORKFLOW)

    wf_type = _parse_workflow_type(user_input)

    if wf_type is None:
        # 판별 불가 → 메뉴 표시
        return WORKFLOW_MENU

    sm.set_workflow_type(wf_type)
    session.set_metadata("workflow_type", wf_type.value)
    sm.transition_to(WorkflowState.COLLECTING_PARAMS)

    wf_labels = {
        WorkflowType.CONVENTIONAL: "기존 분석 (Conventional)",
        WorkflowType.MAP_TREND: "MAP 경향성 분석",
        WorkflowType.YIELD_TREND: "수율 경향성 분석",
        WorkflowType.EQUIP_TREND: "장비 경향성 분석",
    }

    # 장비는 아직 미구현 안내
    if wf_type == WorkflowType.EQUIP_TREND:
        return (
            f"**{wf_labels[wf_type]}**을 선택했습니다.\n\n"
            f"⚠ 이 워크플로우는 아직 구현 중입니다. "
            f"기존 분석으로 전환합니다.\n\n"
            f"분석을 시작하려면 조회 조건을 입력해주세요."
        )

    return (
        f"**{wf_labels[wf_type]}**을 선택했습니다.\n\n"
        f"분석을 시작하려면 조회 조건을 입력해주세요."
    )


def _parse_workflow_type(text: str) -> WorkflowType | None:
    """사용자 입력에서 워크플로우 유형 판별"""
    text_lower = text.lower().strip()

    # 번호 선택
    if text_lower in ("1", "기존", "conventional"):
        return WorkflowType.CONVENTIONAL
    if text_lower in ("2", "map", "맵"):
        return WorkflowType.MAP_TREND
    if text_lower in ("3", "수율", "yield"):
        return WorkflowType.YIELD_TREND
    if text_lower in ("4", "장비", "equip"):
        return WorkflowType.EQUIP_TREND

    # 키워드 기반
    if any(kw in text_lower for kw in ["map", "wafer", "공간 패턴", "다이"]):
        return WorkflowType.MAP_TREND
    if any(kw in text_lower for kw in ["수율", "yield", "트렌드", "trend", "불량률"]):
        return WorkflowType.YIELD_TREND
    if any(kw in text_lower for kw in ["장비", "챔버", "센서", "drift"]):
        return WorkflowType.EQUIP_TREND

    # 조회 조건이 바로 들어온 경우 → conventional로 간주하고 파싱도 시도
    if any(kw in text_lower for kw in ["lot", "분석", "조회"]) or re.search(r"\d{4}[-/]\d{2}", text):
        return WorkflowType.CONVENTIONAL

    return None


# TODO: MAP 경향성 핸들러 함수
# def _handle_map_params(session: SessionManager, user_input: str) -> str:
#     """MAP 분석 파라미터 수집.
#     추가 필요 파라미터:
#       - wafer_id 또는 lot 내 wafer 범위
#       - 좌표 기준 (die / shot / zone)
#       - 분석 대상 컬럼 (수율, 특성값 등)
#     """
#     pass
#
# def _handle_map_results(session: SessionManager, user_input: str) -> str:
#     """MAP 분석 결과 후 LOT 간 비교 여부 판단"""
#     pass

# TODO: 장비 경향성 핸들러 함수
# def _handle_equip_params(session: SessionManager, user_input: str) -> str:
#     """장비 경향성 분석 파라미터 수집.
#     추가 필요 파라미터:
#       - equip_id: 장비 ID
#       - chamber_id: 챔버 ID (선택)
#       - sensor_list: 모니터링 센서 목록
#       - 분석 기간 (from_date/end_date는 공통에서 수집)
#     """
#     pass
#
# def _handle_equip_results(session: SessionManager, user_input: str) -> str:
#     """장비 경향성 결과 후 상관 분석 진행 여부 판단"""
#     pass


# =============================================================================
# 파라미터 수집 & 검증 (LLM 기반)
# =============================================================================

def _get_required_params_for_workflow(session: SessionManager) -> list[dict]:
    """현재 워크플로우에 맞는 필수 파라미터 목록 반환"""
    wf_type = session.get_metadata("workflow_type")
    if wf_type == WorkflowType.MAP_TREND.value:
        return schema.MAP_REQUIRED_PARAMS
    if wf_type == WorkflowType.YIELD_TREND.value:
        return schema.YIELD_REQUIRED_PARAMS
    return schema.REQUIRED_PARAMS


def _handle_collecting(session: SessionManager, user_input: str) -> str:
    """LLM으로 사용자 입력에서 필수 파라미터를 추출하고 검증"""
    sm = session.state_machine

    # 기존 수집된 값 가져오기
    params = session.get_metadata("query_params", {})

    # LLM으로 파라미터 추출
    with st.status("조건을 분석하고 있습니다...", expanded=False) as status:
        status.update(label="입력에서 파라미터 추출 중...")
        parsed = _extract_params_with_llm(user_input, params)
        status.update(label="조건 분석 완료", state="complete")
    # null 값은 무시하고 기존 값 유지
    for k, v in parsed.items():
        if v is not None:
            params[k] = v
    session.set_metadata("query_params", params)

    # 워크플로우별 필수값 체크
    required_params = _get_required_params_for_workflow(session)
    missing = _get_missing_params(params, required_params)

    if missing:
        # 누락 있으면 상태 전이
        if sm.state == WorkflowState.COLLECTING_PARAMS:
            sm.transition_to(WorkflowState.VALIDATING_PARAMS)
        elif sm.state != WorkflowState.VALIDATING_PARAMS:
            sm.transition_to(WorkflowState.COLLECTING_PARAMS)

        # 현재까지 수집된 값 + 누락 안내
        filled_lines = []
        for p in required_params:
            val = params.get(p["key"])
            if val:
                filled_lines.append(f"  - {p['label']}: **{val}**")

        missing_labels = [p["label"] for p in required_params if p["key"] in missing]

        response = ""
        if filled_lines:
            response += "현재 입력된 조건:\n" + "\n".join(filled_lines) + "\n\n"

        response += "**아래 항목이 누락되었습니다:**\n"
        for label in missing_labels:
            response += f"- {label}\n"

        response += "\n누락된 항목을 입력해주세요."

        # 카테고리는 선택 사항 안내
        if not params.get("cat"):
            response += "\n\n(선택) 카테고리 지정 가능: 예) `cat1`, `cat2`"

        return response

    # 모든 필수값 충족 → 워크플로우별 분기
    session.set_metadata("current_lot", params.get("lot_cd", ""))
    wf_type = session.get_metadata("workflow_type")

    if wf_type == WorkflowType.MAP_TREND.value:
        return _handle_map_query(session, params)

    if wf_type == WorkflowType.YIELD_TREND.value:
        return _handle_yield_loading(session, params)

    # conventional: 기존 로직
    with st.status("데이터를 조회하고 있습니다...", expanded=True) as status:
        status.update(label="SQL 쿼리 생성 중...")
        sm.transition_to(WorkflowState.QUERYING_DATA)
        status.update(label="DB에서 데이터 조회 중...")
        sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)
        status.update(label="데이터 조회 완료", state="complete")

    overview = _build_data_overview(params)
    conditions = _format_conditions(params)

    return (
        f"조회 조건이 확인되었습니다.\n\n"
        f"{conditions}\n\n"
        f"데이터를 조회했습니다. (mock 데이터)\n\n"
        f"---\n\n"
        f"{overview}\n\n"
        f"---\n\n"
        f"{STATE_MESSAGES[WorkflowState.SHOWING_QUERY_RESULTS]}"
    )


def _extract_params_with_llm(user_input: str, existing_params: dict) -> dict:
    """LLM을 호출하여 파라미터 추출. 실패 시 규칙 기반 fallback."""
    try:
        llm = LLMClient()
        prompts = PromptBuilder()
        parser = ResponseParser()

        prompt = prompts.build_param_extraction(user_input, existing_params)
        response = llm.complete(prompt, system=SYSTEM_PROMPT)
        parsed = parser._extract_json(response)

        # null 문자열 처리 + 날짜 YYYYMMDD 정규화
        result = {}
        for key in ["lot_cd", "lot_no", "oper", "from_date", "end_date", "cat", "week"]:
            val = parsed.get(key)
            if val and val != "null" and val != "None":
                if key in ("from_date", "end_date"):
                    val = _normalize_date(val)
                result[key] = val
            else:
                result[key] = None
        return result

    except (LLMError, Exception):
        # LLM 실패 시 규칙 기반 fallback
        return _parse_params_fallback(user_input)


def _normalize_date(val: str) -> str:
    """날짜 문자열을 YYYYMMDD 형식으로 정규화"""
    # 구분자 제거 (-, /, .)
    cleaned = val.replace("-", "").replace("/", "").replace(".", "")
    # 8자리 숫자인지 확인
    if re.match(r"^\d{8}$", cleaned):
        return cleaned
    return val


def _parse_params_fallback(text: str) -> dict:
    """규칙 기반 파라미터 추출 (LLM fallback용)"""
    params = {}
    text_lower = text.strip().lower()

    # 날짜 추출 (YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD, YYYYMMDD)
    dates = re.findall(r"(\d{4}[-/.]?\d{2}[-/.]?\d{2})", text)
    if dates:
        normalized = [_normalize_date(d) for d in dates]
        if len(normalized) >= 2:
            params["from_date"] = normalized[0]
            params["end_date"] = normalized[1]
        elif len(normalized) == 1:
            params["from_date"] = normalized[0]

    # LOT 코드 추출 (영문+숫자 혼합 패턴, 또는 "LOT" 키워드 뒤)
    lot_match = re.search(r"(?:lot[_\s:]*)?([A-Za-z]\d{2,}[A-Za-z0-9\-_]*)", text, re.IGNORECASE)
    if not lot_match:
        lot_match = re.search(r"(?:lot|LOT)[_\s:]+([^\s,]+)", text)
    if lot_match:
        params["lot_cd"] = lot_match.group(1).upper()

    # LOT 번호 추출 (LOT_001, lot-002 등)
    lot_no_match = re.search(r"(LOT[-_]\d{3,})", text, re.IGNORECASE)
    if lot_no_match:
        params["lot_no"] = lot_no_match.group(1).upper()

    # OPER(공정) 추출 (schema에 정의된 목록과 매칭)
    if schema.OPER_OPTIONS:
        for oper in schema.OPER_OPTIONS:
            if oper.lower() in text_lower or oper in text:
                params["oper"] = oper
                break

    # OPER가 매칭 안 됐으면 키워드 패턴으로 추출
    if "oper" not in params:
        # "oper_001" 같은 독립 토큰 우선 (한국어 조사 제거)
        oper_token = re.search(r"\b(oper[_-][A-Za-z0-9_]+)", text, re.IGNORECASE)
        if oper_token:
            params["oper"] = oper_token.group(1).upper()
        else:
            # "공정: xxx" 또는 "공정은 xxx" 패턴
            oper_match = re.search(r"(?:공정)[은는이가]?\s*[:=]?\s*([^\s,이고]+)", text, re.IGNORECASE)
            if oper_match:
                params["oper"] = oper_match.group(1).upper()

    # Week 추출 — "W20", "20주차", "2025-W20" 패턴
    week_match = re.search(r"(\d{4})-?W(\d{1,2})", text, re.IGNORECASE)
    if week_match:
        params["week"] = f"{week_match.group(1)}-W{int(week_match.group(2)):02d}"
    else:
        week_match = re.search(r"W(\d{1,2})", text, re.IGNORECASE)
        if week_match:
            from datetime import datetime
            year = datetime.now().year
            params["week"] = f"{year}-W{int(week_match.group(1)):02d}"
        else:
            week_match = re.search(r"(\d{1,2})\s*주차", text)
            if week_match:
                from datetime import datetime
                year = datetime.now().year
                params["week"] = f"{year}-W{int(week_match.group(1)):02d}"

    # 카테고리 추출 — "cat1", "cat 2", "카테고리 3" 패턴
    if "cat" not in params:
        cat_match = re.search(r"(cat[_\s]?\d{1,4})", text, re.IGNORECASE)
        if cat_match:
            # "cat 2" → "cat2", "CAT_3" → "cat3" 등 정규화
            params["cat"] = re.sub(r"[_\s]", "", cat_match.group(1)).lower()
        else:
            cat_match = re.search(r"(?:카테고리|분류)[_\s:]*(\d{1,4})", text, re.IGNORECASE)
            if cat_match:
                params["cat"] = f"cat{cat_match.group(1)}"

    return params


def _get_missing_params(params: dict, required: list[dict] | None = None) -> list[str]:
    """누락된 필수 파라미터 키 목록 반환"""
    if required is None:
        required = schema.REQUIRED_PARAMS
    missing = []
    for p in required:
        if not params.get(p["key"]):
            missing.append(p["key"])
    return missing


def _format_conditions(params: dict, required: list[dict] | None = None) -> str:
    """수집된 조건을 보기 좋게 포맷"""
    if required is None:
        required = schema.REQUIRED_PARAMS
    lines = ["### 조회 조건", "", "| 항목 | 값 |", "|------|------|"]
    for p in required:
        val = params.get(p["key"], "-")
        lines.append(f"| {p['label']} | {val} |")
    return "\n".join(lines)


# =============================================================================
# 데이터 오버뷰
# =============================================================================

def _build_data_overview(params: dict) -> str:
    """schema.py 기반으로 데이터 오버뷰 생성"""
    lot_cd = params.get("lot_cd", "")
    from_date = params.get("from_date", "")
    end_date = params.get("end_date", "")
    cat = params.get("cat", "")

    # Y값 결정 방식 표시
    if cat:
        y_method = f"cat='{cat}' → 1, 그 외 → 0"
    else:
        failbin_summary = ", ".join(f"{k}: {v}" for k, v in list(schema.FAILBIN.items())[:3])
        y_method = f"FAILBIN 기반 ({failbin_summary}...)"

    lines = [
        "### 데이터 오버뷰",
        "",
        "| 항목 | 값 |",
        "|------|------|",
        f"| 테이블 | `{schema.DB_TABLE}` |",
        f"| LOT 코드 | {lot_cd} |",
        f"| 기간 | {from_date} ~ {end_date} |",
        f"| 카테고리 | {cat if cat else '미지정 (FAILBIN 사용)'} |",
        f"| Y값 결정 | {y_method} |",
        f"| 컬럼 수 | {len(schema.DB_COLUMNS)} |",
        f"| 컬럼 | {', '.join(schema.DB_COLUMNS)} |",
        f"| 수치형 | {', '.join(schema.NUMERIC_COLUMNS)} |",
        f"| 범주형 | {', '.join(schema.CATEGORICAL_COLUMNS)} |",
        f"| 타겟 | {schema.TARGET_COLUMN} |",
    ]

    if schema.S3_COLUMNS:
        lines.append(f"| S3 추가 컬럼 | {', '.join(schema.S3_COLUMNS)} |")
        lines.append(f"| S3 머지 키 | {', '.join(schema.S3_MERGE_KEYS)} |")

    return "\n".join(lines)


# =============================================================================
# 전처리 계획 적용
# =============================================================================

def _parse_complete(text: str) -> bool:
    """사용자가 '완료'를 입력했는지 판별"""
    keywords = ["완료", "끝", "적용", "done", "apply", "finish"]
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in keywords)


def _apply_preprocess_plan(session: SessionManager) -> str:
    """누적된 전처리 계획을 실제 데이터에 적용하고 다음 단계로 진행"""
    sm = session.state_machine
    plan: PreprocessPlan = session.get_metadata("preprocess_plan")
    df = _get_active_dataframe(session)

    with st.status("전처리를 적용하고 있습니다...", expanded=True) as status:
        if plan and plan.actions and df is not None:
            for i, a in enumerate(plan.actions):
                status.update(label=f"[{i+1}/{len(plan.actions)}] {a.tool_name} 적용 중...")
            result_df = apply_plan(df, plan)
            session.set_dataframe("preprocessed", result_df)

            # 핸들러/파라미터 정보 저장 (호환용)
            items = []
            merged_params = {}
            tool_names = []
            for a in plan.actions:
                items.append(a.handler)
                merged_params.update(a.params)
                tool_names.append(a.tool_name)
            session.set_metadata("preprocess_items", items)
            session.set_metadata("preprocess_params", merged_params)
        else:
            result_df = df
            tool_names = []

        # 계획 정리
        session.set_metadata("preprocess_plan", None)

        # scanning 자동 실행
        status.update(label="Threshold Scanning 실행 중...")
        scanning_df = run_threshold_scanning(
            result_df if result_df is not None else df,
            schema.AVAILABLE_FEATURES,
            schema.TARGET_COLUMN,
        )
        session.set_dataframe("scanning_result", scanning_df)
        st.write(f"전처리 완료: {result_df.shape[0]:,}행 × {result_df.shape[1]}열" if result_df is not None else "")
        status.update(label="전처리 + Scanning 완료", state="complete")

    # 상태 전이
    sm.transition_to(WorkflowState.AWAITING_PREPROCESS)
    sm.transition_to(WorkflowState.PREPROCESSING)
    sm.transition_to(WorkflowState.SHOWING_PREPROCESSED)
    sm.transition_to(WorkflowState.ANALYZING_FEATURES)
    sm.transition_to(WorkflowState.SHOWING_FEATURES)
    session.save_snapshot()

    before = plan.original_shape if plan else (0, 0)
    after = result_df.shape if result_df is not None else (0, 0)
    tool_list = "\n".join(f"  - {name}" for name in tool_names) if tool_names else "  (없음)"

    return (
        f"**전처리 적용 완료**\n\n"
        f"적용 도구:\n{tool_list}\n\n"
        f"데이터 변화: {before[0]}행×{before[1]}열 → **{after[0]}행×{after[1]}열**\n\n"
        f"---\n\n"
        f"피처 분석 진행합니다.\n\n"
        f"---\n\n"
        f"{STATE_MESSAGES[WorkflowState.SHOWING_FEATURES]}"
    )


# =============================================================================
# EDA 핸들러
# =============================================================================

def _handle_eda(session: SessionManager) -> None:
    """EDA 실행 후 결과를 채팅에 추가"""
    df = session.get_dataframe("query_result")

    with st.status("EDA 분석 중...", expanded=True) as status:
        status.update(label="결측치 분석 중...")
        result = run_eda(df)
        status.update(label="EDA 분석 완료", state="complete")

    # EDA 결과 DataFrame을 세션에 저장
    session.set_dataframe("eda_missing", result.missing)
    session.set_dataframe("eda_low_variance", result.low_variance)
    session.set_dataframe("eda_high_correlation", result.high_correlation)
    session.set_metadata("eda_done", True)

    session.add_message("assistant", result.summary)


# =============================================================================
# MAP 워크플로우 핸들러
# =============================================================================

def _handle_map_query(session: SessionManager, params: dict) -> str:
    """MAP 워크플로우: 파라미터 수집 완료 → LOT 조회 + fail 집계"""
    sm = session.state_machine

    with st.status("MAP 데이터를 조회하고 있습니다...", expanded=True) as status:
        status.update(label="LOT fail 집계 조회 중...")
        sm.transition_to(WorkflowState.MAP_QUERYING_LOT)
        summary_df = map_pipeline.query_lot_fail_summary(params)
        session.set_dataframe("map_fail_summary", summary_df)
        st.write(f"조회 완료: {len(summary_df)}건 (run × wafer)")

        status.update(label="Fail 몰림 분석 중...")
        candidates = map_pipeline.get_concentration_candidates(summary_df)
        session.set_metadata("map_concentration_candidates", candidates)
        status.update(label="MAP 조회 완료", state="complete")

    sm.transition_to(WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION)
    session.save_snapshot()

    conditions = _format_conditions(params, schema.MAP_REQUIRED_PARAMS)
    msg = map_pipeline.build_fail_summary_message(summary_df, candidates)

    return (
        f"조회 조건이 확인되었습니다.\n\n"
        f"{conditions}\n\n"
        f"---\n\n"
        f"{msg}"
    )


def _handle_map_prev_process_decision(session: SessionManager, user_input: str) -> str:
    """MAP: 전공정 merge 여부 선택 → 분석 또는 완료"""
    sm = session.state_machine

    selected_options = map_pipeline.parse_prev_process_selection(user_input)

    if selected_options is None:
        # skip → 완료
        sm.transition_to(WorkflowState.MAP_AWAITING_PREV_PROCESS_MERGE)
        sm.transition_to(WorkflowState.COMPLETED)
        return "분석이 완료되었습니다! 새 분석을 시작하려면 다시 입력하세요."

    sm.transition_to(WorkflowState.MAP_AWAITING_PREV_PROCESS_MERGE)
    sm.transition_to(WorkflowState.MAP_ANALYZING_PREV_PROCESS)

    with st.status("전공정 데이터를 분석하고 있습니다...", expanded=True) as status:
        # merge + similarity 계산
        status.update(label="전공정 데이터 조회 + Merge 중...")
        map_df = session.get_dataframe("map_die_detail")
        merged_df = map_pipeline.merge_prev_process_data(map_df, selected_options)
        session.set_dataframe("map_prev_merged", merged_df)

        feature_cols = []
        for opt in selected_options:
            feature_cols.extend(opt["columns"])

        status.update(label="Feature Similarity 계산 중...")
        similarity_df = map_pipeline.compute_feature_similarity(merged_df, feature_cols)
        session.set_dataframe("map_similarity", similarity_df)
        status.update(label="전공정 분석 완료", state="complete")

    sm.transition_to(WorkflowState.MAP_SHOWING_PREV_PROCESS_RESULTS)
    session.save_snapshot()

    return map_pipeline.build_prev_process_results_message(similarity_df)


# =============================================================================
# 수율 경향성 워크플로우 핸들러
# =============================================================================

def _handle_yield_loading(session: SessionManager, params: dict) -> str:
    """수율 워크플로우: 파라미터 수집 완료 → parquet 로드 or DB 조회 → 전처리 → overview"""
    sm = session.state_machine

    with st.status("수율 데이터를 조회하고 있습니다...", expanded=True) as status:
        # 1. week 결정 + 데이터 로드
        sm.transition_to(WorkflowState.YIELD_LOADING_DATA)
        weeks = yield_pipeline.resolve_weeks(params)
        status.update(label=f"조회 대상: {', '.join(weeks)}")

        for i, week in enumerate(weeks):
            parquet_path = yield_pipeline.get_parquet_path(params["lot_cd"], week)
            if parquet_path.exists():
                status.update(label=f"[{i+1}/{len(weeks)}] {week} — 캐시 로드 중...")
            else:
                status.update(label=f"[{i+1}/{len(weeks)}] {week} — DB 조회 + 저장 중...")

        raw_df = yield_pipeline.load_or_query(params, weeks)
        session.set_dataframe("yield_raw", raw_df)
        st.write(f"로드 완료: {len(raw_df):,}행")

        # 2. 날짜 필터링 (from_date/end_date 지정 시)
        sm.transition_to(WorkflowState.YIELD_PREPROCESSING)
        status.update(label="수율/불량률 계산 중...")
        filtered_df = yield_pipeline.filter_by_date(
            raw_df, params.get("from_date"), params.get("end_date")
        )

        # 3. 전처리 (수율/불량률 계산)
        summary = yield_pipeline.preprocess_yield(filtered_df)
        session.set_dataframe("yield_oper_summary", summary["oper_summary"])
        session.set_dataframe("yield_cat_detail", summary["cat_detail"])
        status.update(label="수율 데이터 준비 완료", state="complete")

    # 4. overview 표시
    sm.transition_to(WorkflowState.YIELD_SHOWING_OVERVIEW)
    session.save_snapshot()

    week_info = ", ".join(weeks)
    conditions = _format_conditions(params, schema.YIELD_REQUIRED_PARAMS)
    overview_msg = yield_pipeline.build_overview_message(
        summary["oper_summary"], summary["cat_detail"]
    )

    return (
        f"조회 조건이 확인되었습니다.\n\n"
        f"{conditions}\n\n"
        f"조회 주차: **{week_info}**\n\n"
        f"---\n\n"
        f"{overview_msg}"
    )


def _handle_yield_request(session: SessionManager, user_input: str) -> str:
    """수율 워크플로우: 사용자 요청 파싱 → 상세 뷰 표시 (루프)"""
    sm = session.state_machine

    request = yield_pipeline.parse_detail_request(user_input)

    # 종료
    if request.get("quit"):
        sm.transition_to(WorkflowState.COMPLETED)
        return "분석이 완료되었습니다! 새 분석을 시작하려면 다시 입력하세요."

    # 상세 뷰 생성
    oper_summary = session.get_dataframe("yield_oper_summary")
    cat_detail = session.get_dataframe("yield_cat_detail")

    if oper_summary is None or cat_detail is None:
        return "데이터가 없습니다. 다시 시작해주세요."

    sm.transition_to(WorkflowState.YIELD_SHOWING_DETAIL)
    detail_msg = yield_pipeline.build_detail_view(oper_summary, cat_detail, request)

    sm.transition_to(WorkflowState.YIELD_AWAITING_REQUEST)
    session.save_snapshot()

    return (
        f"{detail_msg}\n\n"
        f"---\n"
        f"다른 데이터를 보시려면 입력하세요. (`전체 보여줘`, `공정 cat 보여줘`, `종료`)"
    )


# =============================================================================
# 파서들
# =============================================================================

def _parse_yes_no(text: str) -> bool:
    """간단한 긍정/부정 판단"""
    positive = ["예", "네", "응", "좋아", "로딩", "가져", "추가", "yes", "y", "ok"]
    text_lower = text.lower().strip()
    return any(word in text_lower for word in positive)


def _parse_tool_selection(text: str) -> list[dict]:
    """사용자 입력에서 전처리 도구 선택 파싱 (번호, 이름, 키워드)"""
    tools = schema.PREPROCESSING_TOOLS
    text_lower = text.lower().strip()

    # "전부" / "모두" / "all"
    if any(kw in text_lower for kw in ["전부", "모두", "다 ", "전체", "all"]):
        return tools.copy()

    selected = []

    # 번호로 선택: "1, 4, 7" 또는 "1 4 7"
    numbers = re.findall(r"\d+", text)
    if numbers:
        for num_str in numbers:
            idx = int(num_str) - 1
            if 0 <= idx < len(tools):
                if tools[idx] not in selected:
                    selected.append(tools[idx])

    # 이름/키워드로 선택
    if not selected:
        for tool in tools:
            # 도구 이��� 또는 id가 텍스트에 포함
            if tool["name"] in text or tool["id"] in text_lower:
                if tool not in selected:
                    selected.append(tool)

        # 키워드 매칭 — 구체적 키워드 우선, 포괄적 키워드는 대체용
        # (순서 중요: 구체적인 것 먼저 매칭)
        keyword_map = [
            # 결측치 — 세부 방식 키워드로 분기
            ("평균", ["fill_mean"]),
            ("mean", ["fill_mean"]),
            ("중앙", ["fill_median"]),
            ("median", ["fill_median"]),
            ("drop", ["drop_missing"]),
            # 이상치
            ("iqr", ["remove_outliers_iqr"]),
            ("zscore", ["remove_outliers_zscore"]),
            ("z-score", ["remove_outliers_zscore"]),
            ("이상치", ["remove_outliers_iqr"]),  # 기본값 IQR
            # 인코딩
            ("원핫", ["onehot_encoding"]),
            ("onehot", ["onehot_encoding"]),
            ("인코딩", ["onehot_encoding"]),
            # 스케일링
            ("표준", ["standard_scaling"]),
            ("standard", ["standard_scaling"]),
            ("minmax", ["minmax_scaling"]),
            ("민맥스", ["minmax_scaling"]),
            ("로버스트", ["robust_scaling"]),
            ("robust", ["robust_scaling"]),
            ("스케일", ["standard_scaling"]),  # 기본값
            # 컬럼 제거 계열
            ("저분산", ["drop_low_variance"]),
            ("분산", ["drop_low_variance"]),
            ("variance", ["drop_low_variance"]),
            ("na 컬럼", ["drop_high_na"]),
            ("결측 컬럼", ["drop_high_na"]),
            ("na 많", ["drop_high_na"]),
            ("t-test", ["drop_insignificant_ttest"]),
            ("ttest", ["drop_insignificant_ttest"]),
            ("유의", ["drop_insignificant_ttest"]),
            ("고상관", ["drop_correlated_pairs"]),
            ("상관 제거", ["drop_correlated_pairs"]),
            ("페어", ["drop_correlated_pairs"]),
            ("correlated", ["drop_correlated_pairs"]),
        ]

        # "결측치 제거" 패턴 감지 (이상치 제거와 구분)
        if re.search(r"결측[치]?\s*제거", text_lower):
            drop_tool = next((t for t in tools if t["id"] == "drop_missing"), None)
            if drop_tool and drop_tool not in selected:
                selected.append(drop_tool)

        # 결측치 관련: "결측" 키워드가 있을 때 세부 키워드 없으면 fill_mean 기본
        has_missing_keyword = "결측" in text_lower or "missing" in text_lower
        has_specific_missing = any(
            kw in text_lower for kw in ["평균", "mean", "중앙", "median", "drop"]
        ) or re.search(r"결측[치]?\s*제거", text_lower)

        for keyword, tool_ids in keyword_map:
            if keyword in text_lower:
                for tid in tool_ids:
                    tool = next((t for t in tools if t["id"] == tid), None)
                    if tool and tool not in selected:
                        selected.append(tool)

        # "결측"만 있고 구체적 방식 언급 없으면 fill_mean 추가
        if has_missing_keyword and not has_specific_missing:
            fill_mean = next((t for t in tools if t["id"] == "fill_mean"), None)
            if fill_mean and fill_mean not in selected:
                selected.append(fill_mean)

    # 아무것도 못 찾으면 기본값: 결측치 평균 대체
    if not selected:
        selected = [tools[1]]  # fill_mean

    return selected


def _parse_preprocess_items(text: str) -> list[str]:
    """텍스트에서 전처리 항목 추출"""
    items = []
    keywords = {
        "결측": "missing_values",
        "missing": "missing_values",
        "이상치": "outliers",
        "outlier": "outliers",
        "인코딩": "encoding",
        "encoding": "encoding",
        "원핫": "encoding",
        "스케일": "scaling",
        "scaling": "scaling",
        "정규화": "scaling",
        "피처선택": "feature_selection",
        "feature_selection": "feature_selection",
        "전부": "all",
        "모두": "all",
        "다": "all",
    }
    text_lower = text.lower()
    for keyword, item in keywords.items():
        if keyword in text_lower:
            if item == "all":
                return ["missing_values", "outliers", "encoding", "scaling"]
            if item not in items:
                items.append(item)
    return items if items else ["missing_values"]


def _parse_feature_selections(text: str) -> list[dict]:
    """사용자 입력에서 피처/조건/임계값 조합 목록을 추출.

    Returns:
        [{"feature": str, "threshold": float|None, "condition": str|None}, ...]
    """
    try:
        llm = LLMClient()
        prompts = PromptBuilder()
        parser = ResponseParser()

        prompt = prompts._build_combination_prompt(text)
        response = llm.complete(prompt, system=SYSTEM_PROMPT)
        parsed = parser._extract_json(response)

        selections = parsed.get("selections")
        if selections and isinstance(selections, list):
            result = []
            for sel in selections:
                feat = sel.get("feature", "")
                if feat not in schema.AVAILABLE_FEATURES:
                    continue
                thresh = float(sel["threshold"]) if sel.get("threshold") is not None else None
                cond = sel.get("condition") if sel.get("condition") in (">=", "<=") else None
                result.append({"feature": feat, "threshold": thresh, "condition": cond})
            if result:
                return result

        # legacy 호환: features/threshold/condition 단일 반환
        features = parsed.get("features", [])
        threshold = parsed.get("threshold")
        condition = parsed.get("condition")
        if isinstance(features, str):
            features = [f.strip() for f in features.split(",") if f.strip()]
        features = [f for f in features if f in schema.AVAILABLE_FEATURES]
        if threshold is not None:
            threshold = float(threshold)
        if condition not in (">=", "<="):
            condition = None
        return [{"feature": f, "threshold": threshold, "condition": condition} for f in features] if features else []

    except (LLMError, Exception):
        return _parse_feature_selections_fallback(text)


def _parse_feature_selections_fallback(text: str) -> list[dict]:
    """규칙 기반 피처/임계값/조건 추출 (복수 조합 지원).

    패턴: "col_3 >= 0.7, col_4 <= 0.3 조건으로 예측해줘"
    """
    # 구조화된 패턴 매칭: "피처 조건 임계값" 반복
    pattern = r"([a-z][a-z0-9]*_[a-z0-9_]+)\s*(>=|<=)\s*(0?\.\d+|\d+(?:\.\d+)?)"
    matches = re.findall(pattern, text.lower())

    if matches:
        result = []
        for feat, cond, thresh_str in matches:
            if feat in schema.AVAILABLE_FEATURES:
                result.append({
                    "feature": feat,
                    "threshold": float(thresh_str),
                    "condition": cond,
                })
        if result:
            return result

    # 단일 condition/threshold + 복수 피처 fallback
    condition = None
    cond_match = re.search(r"(>=|<=)", text)
    if cond_match:
        condition = cond_match.group(1)

    threshold = None
    decimal_match = re.search(r"(0\.\d+)", text)
    if decimal_match:
        threshold = float(decimal_match.group(1))
    else:
        pct_match = re.search(r"(\d{2,3})\s*(?:%|기준|퍼센트)", text)
        if pct_match:
            threshold = int(pct_match.group(1)) / 100.0

    text_lower = text.lower()
    features = [f for f in schema.AVAILABLE_FEATURES if f in text_lower]
    if not features:
        found = re.findall(r"([a-z][a-z0-9]*_[a-z0-9_]+)", text_lower)
        features = [f for f in found if f in schema.AVAILABLE_FEATURES]

    return [{"feature": f, "threshold": threshold, "condition": condition} for f in features]


# =============================================================================
# 피처 선택 UI
# =============================================================================

def _render_scanning_table():
    """SHOWING_FEATURES 상태에서 threshold scanning 결과 테이블 표시.
    행 클릭 시 피처·조건·임계값이 입력창에 자동 채워진다."""
    scanning_df = st.session_state.workflow_context.get("scanning_result")
    if scanning_df is None:
        st.warning("scanning 결과가 없습니다.")
        return

    st.markdown("**Threshold Scanning 결과** — 행을 클릭하여 선택하세요 (복수 선택 가능):")
    event = st.dataframe(
        scanning_df,
        on_select="rerun",
        selection_mode="multi-row",
        use_container_width=True,
        key="_scanning_table",
    )

    # 행 선택 시 text_input 자동 채움
    if event and event.selection and event.selection.rows:
        selected_rows = event.selection.rows
        parts = []
        key_parts = []
        for row_idx in selected_rows:
            row = scanning_df.iloc[row_idx]
            feat = row["feature"]
            cond = row["condition"]
            thresh = row["threshold"]
            parts.append(f"{feat} {cond} {thresh}")
            key_parts.append(f"{feat}_{cond}_{thresh}")

        new_key = "|".join(key_parts)
        if st.session_state.get("_last_scan_selection") != new_key:
            st.session_state._last_scan_selection = new_key
            if len(parts) == 1:
                st.session_state._feat_text_input = f"{parts[0]} 조건으로 예측해줘"
            else:
                conditions_text = ", ".join(parts)
                st.session_state._feat_text_input = f"{conditions_text} 조건으로 예측해줘"

    col_input, col_btn = st.columns([5, 1])
    with col_input:
        feat_input = st.text_input(
            "피처/조건/임계값 입력",
            placeholder="예: col_3 >= 0.7 조건으로 예측해줘",
            key="_feat_text_input",
            label_visibility="collapsed",
        )
    with col_btn:
        submitted = st.button("전송", type="primary", use_container_width=True, key="_feat_send")

    if submitted and feat_input.strip():
        st.session_state._feature_submit = feat_input.strip()
        st.rerun()


def _render_fail_candidates_table():
    """MAP_SHOWING_FAIL_CONCENTRATION 상태에서 몰림 후보 테이블 표시.
    행 클릭 시 wafer 선택이 입력창에 자동 채워진다."""
    session = SessionManager()
    candidates = session.get_metadata("map_concentration_candidates")
    if candidates is None or candidates.empty:
        return

    st.markdown("**몰림 후보** — 행을 클릭하여 선택하세요 (복수 선택 가능):")
    event = st.dataframe(
        candidates,
        on_select="rerun",
        selection_mode="multi-row",
        use_container_width=True,
        key="_fail_candidates_table",
    )

    # 행 선택 시 text_input 자동 채움
    if event and event.selection and event.selection.rows:
        selected_rows = event.selection.rows
        if len(selected_rows) == len(candidates):
            text = "전체"
        else:
            parts = []
            for row_idx in selected_rows:
                row = candidates.iloc[row_idx]
                parts.append(str(row_idx + 1))
            text = ", ".join(parts)

        new_key = "|".join(str(r) for r in selected_rows)
        if st.session_state.get("_last_candidate_selection") != new_key:
            st.session_state._last_candidate_selection = new_key
            st.session_state._candidate_text_input = text

    col_input, col_btn = st.columns([5, 1])
    with col_input:
        candidate_input = st.text_input(
            "wafer 선택 입력",
            placeholder="예: 1, 2, 3 또는 전체",
            key="_candidate_text_input",
            label_visibility="collapsed",
        )
    with col_btn:
        submitted = st.button("전송", type="primary", use_container_width=True, key="_candidate_send")

    if submitted and candidate_input.strip():
        st.session_state._candidate_submit = candidate_input.strip()
        st.rerun()


def _render_similarity_table():
    """MAP_SHOWING_PREV_PROCESS_RESULTS 상태에서 similarity 테이블 표시.
    행 선택 시 해당 피처의 feature map을 렌더링."""
    session = SessionManager()
    similarity_df = session.get_dataframe("map_similarity")
    if similarity_df is None or similarity_df.empty:
        return

    st.divider()

    # 상위 feature 요약 metric
    if len(similarity_df) >= 3:
        top3 = similarity_df.head(3)
        cols = st.columns(3)
        for i, (_, row) in enumerate(top3.iterrows()):
            with cols[i]:
                st.metric(
                    label=f"#{i+1} {row['feature']}",
                    value=f"{row['total_score']:.4f}",
                    help=f"Pearson: {row['pearson_score']:.4f} / Cosine: {row['cosine_score']:.4f}",
                )

    st.markdown("**Feature Similarity 결과** — 행을 클릭하면 해당 피처의 공간 분포(Feature Map)를 확인할 수 있습니다:")
    st.caption("Feature Map은 die 위치별 피처 값을 heatmap으로, fail die는 검은 테두리로 표시합니다.")
    event = st.dataframe(
        similarity_df,
        on_select="rerun",
        selection_mode="multi-row",
        use_container_width=True,
        key="_similarity_table",
    )

    if event and event.selection and event.selection.rows:
        selected_rows = event.selection.rows
        merged_df = session.get_dataframe("map_prev_merged")
        if merged_df is None:
            return

        params = session.get_metadata("query_params", {})
        lot_cd = params.get("lot_cd", "")
        layout = schema.MAP_LAYOUT_BY_LOT_CD.get(lot_cd, schema.MAP_DEFAULT_LAYOUT)

        for row_idx in selected_rows:
            feat = similarity_df.iloc[row_idx]["feature"]
            png = map_pipeline.plot_feature_map(merged_df, feat, layout)
            st.image(png, caption=f"Feature Map: {feat}")
    else:
        st.info("테이블에서 feature를 선택하면 Feature Map이 여기에 표시됩니다.")

    st.divider()
    st.success("분석이 완료되었습니다. 새로운 분석을 시작하려면 아래 채팅에 입력하세요.")


# =============================================================================
# Streamlit 메인
# =============================================================================

def main():
    st.set_page_config(
        page_title="Data Analysis Agent",
        page_icon="chart_with_upwards_trend",
        layout="wide",
    )
    st.title("Data Analysis Agent")

    session = SessionManager()
    render_sidebar(session)
    render_chat_history(session)

    # 초기 안내 메시지
    if not session.chat_history:
        with st.chat_message("assistant"):
            welcome = _build_welcome_message()
            st.markdown(welcome)

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
        _render_scanning_table()

    # 몰림 후보 선택 UI (MAP_SHOWING_FAIL_CONCENTRATION 상태에서만)
    if session.current_state == WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION:
        _render_fail_candidates_table()

    # 전공정 similarity 테이블 + feature map (MAP_SHOWING_PREV_PROCESS_RESULTS 상태에서만)
    if session.current_state == WorkflowState.MAP_SHOWING_PREV_PROCESS_RESULTS:
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
        # 요약 정보 패널
        pattern = session.get_metadata("map_pattern")
        if pattern and session.current_state == WorkflowState.MAP_SHOWING_RESULTS:
            pattern_labels = {
                "edge": "Edge 집중", "center": "Center 집중",
                "random": "Random", "no_fail": "Fail 없음",
            }
            map_die_df = session.get_dataframe("map_die_detail")
            if map_die_df is not None:
                total = len(map_die_df)
                fails = int(map_die_df[schema.MAP_FAIL_COLUMN].sum())
                rate = f"{fails/total:.2%}" if total > 0 else "0%"
                col1, col2, col3 = st.columns(3)
                col1.metric("Fail / Total", f"{fails} / {total}")
                col2.metric("Fail Rate", rate)
                col3.metric("패턴", pattern_labels.get(pattern, pattern))

        with st.expander(
            f"Wafer Map ({len(map_plots)}장)",
            expanded=session.current_state == WorkflowState.MAP_SHOWING_RESULTS,
        ):
            for p in map_plots:
                st.image(p["png"], caption=f"{p['run_id']} / {p['wafer_id']}")

        # 전공정 merge 안내 (MAP_SHOWING_RESULTS에서만)
        if session.current_state == WorkflowState.MAP_SHOWING_RESULTS:
            st.divider()
            st.markdown("#### 다음 단계: 전공정 데이터 Merge")
            st.info(
                "전공정 데이터를 merge하면 fail 패턴과 상관이 높은 feature를 분석할 수 있습니다.\n\n"
                "아래 채팅에서 선택해주세요:\n"
                "- **번호 입력** (예: `1, 2`) 또는 `전체` → 전공정 merge + similarity 분석\n"
                "- `아니오` / `skip` → 분석 종료"
            )
            if schema.PREV_PROCESS_OPTIONS:
                cols = st.columns(len(schema.PREV_PROCESS_OPTIONS) + 1)
                for i, opt in enumerate(schema.PREV_PROCESS_OPTIONS):
                    with cols[i]:
                        st.caption(f"**{i+1}. {opt['label']}**")
                with cols[-1]:
                    st.caption("또는 `전체`")

    # 사용자 입력 처리
    _feature_input = st.session_state.pop("_feature_submit", None)
    _candidate_input = st.session_state.pop("_candidate_submit", None)
    if session.current_state == WorkflowState.SHOWING_FEATURES:
        user_input = _feature_input
    elif session.current_state == WorkflowState.MAP_SHOWING_FAIL_CONCENTRATION:
        user_input = _candidate_input
    else:
        user_input = st.chat_input("메시지를 입력하세요...")
    if user_input:
        # 중복 방지
        if session.chat_history and session.chat_history[-1].get("content") == user_input:
            st.stop()

        session.add_message("user", user_input)

        # 응답 생성
        response = handle_user_input(session, user_input)
        session.add_message("assistant", response)

        st.rerun()


def _build_welcome_message() -> str:
    """초기 안내 메시지 생성"""
    lines = [
        "안녕하세요! 데이터 분석 에이전트입니다.\n",
        "분석을 시작하려면 아래 정보를 입력해주세요:\n",
    ]

    for p in schema.REQUIRED_PARAMS:
        fmt = f" ({p['format']})" if "format" in p else ""
        lines.append(f"- **{p['label']}**{fmt}")

    lines.append("\n(선택) 카테고리: cat1, cat2 등 자유 입력")

    lines.append("\n예: 'LOT *** *** 20250101 20250331 cat2 분석해줘'")
    lines.append("\n한 번에 입력하거나, 하나씩 입력해도 됩니다.")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
