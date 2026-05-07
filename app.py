"""Streamlit entry point for the data analysis agent."""

import re
import streamlit as st

from core.session import SessionManager
from core.state_machine import WorkflowState, WorkflowType, DECISION_STATES
from ui.chat import render_chat_history, render_sidebar, render_step_result
from ui.formatters import format_dataframe
from llm.client import LLMClient, LLMError
from llm.prompts import PromptBuilder, SYSTEM_PROMPT
from llm.parser import ResponseParser
import schema


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
        "**추가 데이터를 S3에서 로딩할까요?**\n"
        "- '예' / '로딩해줘' → S3 parquet 추가 로딩\n"
        "- '아니오' / '충분해' → 현재 데이터로 진행"
    ),
    WorkflowState.SHOWING_DATA_OVERVIEW: _build_preprocess_menu(),
    WorkflowState.SHOWING_FEATURES: (
        "피처 분석 결과입니다.\n\n"
        "**예측에 사용할 피처와 임계값을 지정해주세요.**\n\n"
        f"사용 가능한 피처: `{'`, `'.join(schema.AVAILABLE_FEATURES)}`\n\n"
        f"예: '{schema.AVAILABLE_FEATURES[0]}, {schema.AVAILABLE_FEATURES[1]}로 0.7 기준으로 예측해줘'"
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
        return _handle_collecting(session, user_input)

    # ─── VALIDATING_PARAMS: 누락 항목 재요청 ───
    if state == WorkflowState.VALIDATING_PARAMS:
        return _handle_collecting(session, user_input)

    # ─── 분기점 1: 추가 데이터 로딩 여부 ───
    if state == WorkflowState.SHOWING_QUERY_RESULTS:
        load = _parse_yes_no(user_input)
        if load:
            sm.transition_to(WorkflowState.AWAITING_LOAD_DECISION)
            sm.transition_to(WorkflowState.LOADING_PARQUET)
            sm.transition_to(WorkflowState.SHOWING_DATA_OVERVIEW)
            return (
                "S3에서 추가 데이터를 로딩하고 머지했습니다.\n"
                "(50건 추가 - mock 데이터)\n\n"
                "---\n\n"
                f"{STATE_MESSAGES[WorkflowState.SHOWING_DATA_OVERVIEW]}"
            )
        else:
            sm.transition_to(WorkflowState.AWAITING_LOAD_DECISION)
            sm.transition_to(WorkflowState.SHOWING_DATA_OVERVIEW)
            return (
                "현재 데이터로 진행합니다.\n\n"
                "---\n\n"
                f"{STATE_MESSAGES[WorkflowState.SHOWING_DATA_OVERVIEW]}"
            )

    # ─── 분기점 2: 전처리 도구 선택 ───
    if state == WorkflowState.SHOWING_DATA_OVERVIEW:
        selected_tools = _parse_tool_selection(user_input)
        session.set_metadata("selected_tools", selected_tools)

        # 선택된 도구에서 handler + params 추출
        items = []
        merged_params = {}
        tool_names = []
        for tool in selected_tools:
            items.append(tool["handler"])
            merged_params.update(tool["params"])
            tool_names.append(tool["name"])

        session.set_metadata("preprocess_items", items)
        session.set_metadata("preprocess_params", merged_params)

        sm.transition_to(WorkflowState.AWAITING_PREPROCESS)
        sm.transition_to(WorkflowState.PREPROCESSING)
        sm.transition_to(WorkflowState.SHOWING_PREPROCESSED)
        sm.transition_to(WorkflowState.ANALYZING_FEATURES)
        sm.transition_to(WorkflowState.SHOWING_FEATURES)

        tool_list = "\n".join(f"  - {name}" for name in tool_names)
        return (
            f"**적용할 전처리 도구:**\n{tool_list}\n\n"
            f"전처리 실행 완료. 피처 분석 진행합니다.\n\n"
            f"---\n\n"
            f"{STATE_MESSAGES[WorkflowState.SHOWING_FEATURES]}"
        )

    # ─── 분기점 3: 피처 조합 + threshold ───
    if state == WorkflowState.SHOWING_FEATURES:
        features, threshold = _parse_feature_request(user_input)
        session.set_metadata("selected_features", features)
        session.set_metadata("threshold", threshold)
        sm.transition_to(WorkflowState.AWAITING_COMBINATIONS)
        sm.transition_to(WorkflowState.PREDICTING)
        sm.transition_to(WorkflowState.SHOWING_PREDICTIONS)
        sm.transition_to(WorkflowState.COMPLETED)
        return (
            f"피처: {', '.join(features) if features else '전체'}\n"
            f"임계값: {threshold}\n\n"
            f"**예측 결과 (mock)**\n"
            f"- 전체: 100건\n"
            f"- 임계값 이상: 47건\n"
            f"- 임계값 미만: 53건\n"
            f"- 평균 점수: 0.4832\n\n"
            f"---\n\n"
            f"분석이 완료되었습니다! 새 분석을 시작하려면 다시 입력하세요."
        )

    # TODO: MAP 경향성 워크플로우 상태 핸들링
    # ─── MAP_SELECTING_PARAMS: wafer/die 좌표 기준 선택 ───
    # if state == WorkflowState.MAP_SELECTING_PARAMS:
    #     return _handle_map_params(session, user_input)
    #
    # ─── MAP_SHOWING_RESULTS: MAP 분석 결과 + LOT 비교 여부 ───
    # if state == WorkflowState.MAP_SHOWING_RESULTS:
    #     return _handle_map_results(session, user_input)

    # TODO: 장비 경향성 워크플로우 상태 핸들링
    # ─── EQUIP_SELECTING_PARAMS: 장비/챔버/센서 선택 ───
    # if state == WorkflowState.EQUIP_SELECTING_PARAMS:
    #     return _handle_equip_params(session, user_input)
    #
    # ─── EQUIP_SHOWING_TREND: 경향성 결과 + 상관 분석 여부 ───
    # if state == WorkflowState.EQUIP_SHOWING_TREND:
    #     return _handle_equip_results(session, user_input)

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
    "| 3 | 장비 경향성 분석 | 장비 센서 시계열 트렌드 분석 |\n\n"
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
        WorkflowType.EQUIP_TREND: "장비 경향성 분석",
    }

    # MAP/장비는 아직 미구현 안내
    if wf_type in (WorkflowType.MAP_TREND, WorkflowType.EQUIP_TREND):
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
    if text_lower in ("3", "장비", "equip"):
        return WorkflowType.EQUIP_TREND

    # 키워드 기반
    if any(kw in text_lower for kw in ["map", "wafer", "공간 패턴", "다이"]):
        return WorkflowType.MAP_TREND
    if any(kw in text_lower for kw in ["장비", "챔버", "센서", "drift", "경향성"]):
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

def _handle_collecting(session: SessionManager, user_input: str) -> str:
    """LLM으로 사용자 입력에서 필수 파라��터를 추출��고 검증"""
    sm = session.state_machine

    # ��존 수집된 값 가져오기
    params = session.get_metadata("query_params", {})

    # LLM으로 파라미터 추출
    parsed = _extract_params_with_llm(user_input, params)
    # null 값은 무시하고 기존 값 유지
    for k, v in parsed.items():
        if v is not None:
            params[k] = v
    session.set_metadata("query_params", params)

    # 필수값 체크
    missing = _get_missing_params(params)

    if missing:
        # 누락 있으면 상태 전이
        if sm.state == WorkflowState.COLLECTING_PARAMS:
            sm.transition_to(WorkflowState.VALIDATING_PARAMS)
        elif sm.state != WorkflowState.VALIDATING_PARAMS:
            sm.transition_to(WorkflowState.COLLECTING_PARAMS)

        # 현재까지 수집된 값 + 누락 안내
        filled_lines = []
        for p in schema.REQUIRED_PARAMS:
            val = params.get(p["key"])
            if val:
                filled_lines.append(f"  - {p['label']}: **{val}**")

        missing_labels = [p["label"] for p in schema.REQUIRED_PARAMS if p["key"] in missing]

        response = ""
        if filled_lines:
            response += "현재 입력된 조건:\n" + "\n".join(filled_lines) + "\n\n"

        response += "**아래 항목��� 누락되었습니다:**\n"
        for label in missing_labels:
            response += f"- {label}\n"

        response += "\n누락된 항목을 입력해주세요."

        # 카테고리는 선택 사항 안내
        if not params.get("cat") and schema.CAT_OPTIONS:
            response += f"\n\n(선택) 카테고리 지정 가능: `{'`, `'.join(schema.CAT_OPTIONS)}`"

        return response

    # 모든 필수값 충족 → 쿼리 진행
    session.set_metadata("current_lot", params.get("lot_cd", ""))
    sm.transition_to(WorkflowState.QUERYING_DATA)
    sm.transition_to(WorkflowState.SHOWING_QUERY_RESULTS)

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

        # null 문자열 처리
        result = {}
        for key in ["lot_cd", "from_date", "end_date", "cat"]:
            val = parsed.get(key)
            if val and val != "null" and val != "None":
                result[key] = val
            else:
                result[key] = None
        return result

    except (LLMError, Exception):
        # LLM 실패 시 규칙 기반 fallback
        return _parse_params_fallback(user_input)


def _parse_params_fallback(text: str) -> dict:
    """규칙 기반 파라미터 추출 (LLM fallback용)"""
    params = {}
    text_lower = text.strip().lower()

    # 날짜 추출 (YYYY-MM-DD 또는 YYYYMMDD)
    dates = re.findall(r"(\d{4}[-/.]?\d{2}[-/.]?\d{2})", text)
    if dates:
        normalized = [d.replace("/", "-").replace(".", "-") for d in dates]
        normalized = [
            f"{d[:4]}-{d[4:6]}-{d[6:8]}" if "-" not in d else d
            for d in normalized
        ]
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

    # 카테고리 추출 (schema에 정의된 목록과 매칭)
    if schema.CAT_OPTIONS:
        for cat in schema.CAT_OPTIONS:
            if cat.lower() in text_lower or cat in text:
                params["cat"] = cat
                break

    # 카테고리가 매칭 안 됐으면 키워드 뒤의 값 추출
    if "cat" not in params:
        cat_match = re.search(r"(?:cat|카테고리|분류)[_\s:]*([^\s,]+)", text, re.IGNORECASE)
        if cat_match:
            params["cat"] = cat_match.group(1).upper()

    return params


def _get_missing_params(params: dict) -> list[str]:
    """누락된 필수 파라미터 키 목록 반환 (REQUIRED_PARAMS만 체크)"""
    missing = []
    for p in schema.REQUIRED_PARAMS:
        if not params.get(p["key"]):
            missing.append(p["key"])
    return missing


def _format_conditions(params: dict) -> str:
    """수집된 조건을 보기 좋게 포맷"""
    lines = ["### 조회 조건", "", "| 항목 | 값 |", "|------|------|"]
    for p in schema.REQUIRED_PARAMS:
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


def _parse_feature_request(text: str) -> tuple[list[str], float]:
    """텍스트에서 피처명과 threshold 추출 (schema.AVAILABLE_FEATURES 기반)"""
    # threshold 추출
    decimal_match = re.search(r"(0\.\d+)", text)
    if decimal_match:
        threshold = float(decimal_match.group(1))
    else:
        numbers = re.findall(r"(\d+)", text)
        candidates = [int(n) for n in numbers if int(n) >= 10]
        if candidates:
            threshold = max(candidates) / 100.0
        else:
            threshold = schema.DEFAULT_THRESHOLD

    # schema에 정의된 피처명 매칭
    text_lower = text.lower()
    features = [f for f in schema.AVAILABLE_FEATURES if f in text_lower]

    # 매칭 안 되면 일반 패턴으로 fallback
    if not features:
        found = re.findall(r"([a-z][a-z0-9]*_[a-z0-9_]+)", text_lower)
        features = [f for f in found if f in schema.AVAILABLE_FEATURES]

    return features, threshold


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

    # 사용자 입력 처리
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

    if schema.CAT_OPTIONS:
        lines.append(f"\n사용 가능한 카테고리: `{'`, `'.join(schema.CAT_OPTIONS)}`")

    lines.append("\n예: 'LOT A2401 2025-01-01 2025-03-31 CAT_A 분석해줘'")
    lines.append("\n한 번에 입력하거나, 하나씩 입력해도 됩니다.")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
