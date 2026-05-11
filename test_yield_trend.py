"""수율 경향성 워크플로우 테스트."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import schema
from core.state_machine import WorkflowState, WorkflowType, StateMachine
from pipeline import yield_trend as yp


# =============================================================================
# 1. Week 유틸리티 테스트
# =============================================================================

def test_week_to_date_range():
    start, end = yp._week_to_date_range("2025-W01")
    assert len(start) == 8 and len(end) == 8
    assert start < end
    print(f"  W01: {start} ~ {end}")

    start2, end2 = yp._week_to_date_range("2025-W20")
    assert start2 < end2
    print(f"  W20: {start2} ~ {end2}")


def test_date_to_week():
    w = yp._date_to_week("20250512")  # 2025-05-12 (월)
    assert w.startswith("2025-W")
    print(f"  20250512 → {w}")


def test_resolve_weeks_default():
    """파라미터 없으면 전주 반환."""
    weeks = yp.resolve_weeks({"lot_cd": "LOT001"})
    assert len(weeks) == 1
    print(f"  기본값(전주): {weeks}")


def test_resolve_weeks_explicit():
    """week 명시."""
    weeks = yp.resolve_weeks({"lot_cd": "LOT001", "week": "2025-W20"})
    assert weeks == ["2025-W20"]
    print(f"  명시: {weeks}")


def test_resolve_weeks_date_range():
    """날짜 범위 → 여러 week."""
    weeks = yp.resolve_weeks({
        "lot_cd": "LOT001",
        "from_date": "20250501",
        "end_date": "20250520",
    })
    assert len(weeks) >= 2
    print(f"  날짜범위: {weeks}")


# =============================================================================
# 2. Parquet 캐싱 테스트
# =============================================================================

def test_parquet_cache():
    """parquet 저장/로드 사이클."""
    tmp_dir = tempfile.mkdtemp()
    original_dir = schema.YIELD_PARQUET_DIR
    try:
        schema.YIELD_PARQUET_DIR = tmp_dir

        df = pd.DataFrame({
            schema.YIELD_LOT_COLUMN: ["LOT001"] * 3,
            schema.YIELD_OPER_COLUMN: ["OP1", "OP1", "OP2"],
            schema.YIELD_DATE_COLUMN: ["20250512", "20250513", "20250512"],
            schema.YIELD_CAT_COLUMN: ["cat1", "cat2", "cat1"],
            schema.YIELD_IN_COLUMN: [1000, 1000, 1000],
            schema.YIELD_OUT_COLUMN: [950, 960, 970],
        })

        # 저장
        path = yp.save_parquet(df, "LOT001", "2025-W20")
        assert path.exists()
        print(f"  저장: {path}")

        # 로드
        loaded = pd.read_parquet(path)
        assert len(loaded) == 3
        print(f"  로드: {len(loaded)}행")

        # load_or_query에서 캐시 히트
        result = yp.load_or_query({"lot_cd": "LOT001"}, ["2025-W20"])
        assert len(result) == 3
        print(f"  캐시 히트: {len(result)}행")

    finally:
        schema.YIELD_PARQUET_DIR = original_dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# 3. Mock 데이터 조회 테스트
# =============================================================================

def test_query_yield_data():
    """mock 데이터 생성 확인."""
    df = yp.query_yield_data({"lot_cd": "LOT001"}, "2025-W20")
    assert not df.empty
    assert schema.YIELD_LOT_COLUMN in df.columns
    assert schema.YIELD_OPER_COLUMN in df.columns
    assert schema.YIELD_DATE_COLUMN in df.columns
    assert schema.YIELD_CAT_COLUMN in df.columns
    assert schema.YIELD_IN_COLUMN in df.columns
    assert schema.YIELD_OUT_COLUMN in df.columns
    print(f"  mock 데이터: {len(df)}행, 컬럼: {list(df.columns)}")


# =============================================================================
# 4. 전처리 테스트
# =============================================================================

def test_preprocess_yield():
    """수율/불량률 계산."""
    df = yp.query_yield_data({"lot_cd": "LOT001"}, "2025-W20")
    result = yp.preprocess_yield(df)

    assert "oper_summary" in result
    assert "cat_detail" in result

    oper_summary = result["oper_summary"]
    assert "yield_rate" in oper_summary.columns
    assert (oper_summary["yield_rate"] >= 0).all()
    assert (oper_summary["yield_rate"] <= 1).all()
    print(f"  oper_summary: {len(oper_summary)}행")

    cat_detail = result["cat_detail"]
    assert "defect_rate" in cat_detail.columns
    assert (cat_detail["defect_rate"] >= 0).all()
    assert (cat_detail["defect_rate"] <= 1).all()
    print(f"  cat_detail: {len(cat_detail)}행")


# =============================================================================
# 5. 날짜 필터링 테스트
# =============================================================================

def test_filter_by_date():
    """날짜 범위 필터링."""
    df = yp.query_yield_data({"lot_cd": "LOT001"}, "2025-W20")
    start, end = yp._week_to_date_range("2025-W20")

    # 전체 (필터 없음)
    no_filter = yp.filter_by_date(df, None, None)
    assert len(no_filter) == len(df)

    # 첫째 날만
    filtered = yp.filter_by_date(df, start, start)
    assert len(filtered) < len(df)
    assert (filtered[schema.YIELD_DATE_COLUMN] == start).all()
    print(f"  전체: {len(df)}행 → 필터({start}): {len(filtered)}행")


# =============================================================================
# 6. 메시지 빌더 테스트
# =============================================================================

def test_build_overview_message():
    """overview 메시지 생성."""
    df = yp.query_yield_data({"lot_cd": "LOT001"}, "2025-W20")
    result = yp.preprocess_yield(df)
    msg = yp.build_overview_message(result["oper_summary"], result["cat_detail"])

    assert "공정별 수율 요약" in msg
    assert "카테고리별 불량률 요약" in msg
    assert "전체 보여줘" in msg
    print(f"  overview 메시지: {len(msg)}자")


def test_build_detail_view_all():
    """전체 공정 수율 trend."""
    df = yp.query_yield_data({"lot_cd": "LOT001"}, "2025-W20")
    result = yp.preprocess_yield(df)
    msg = yp.build_detail_view(
        result["oper_summary"], result["cat_detail"],
        {"show_all": True, "oper": None, "cat": None, "quit": False},
    )
    assert "전체 공정 수율 Trend" in msg
    print(f"  전체 뷰: {len(msg)}자")


def test_build_detail_view_oper():
    """특정 공정 뷰."""
    df = yp.query_yield_data({"lot_cd": "LOT001"}, "2025-W20")
    result = yp.preprocess_yield(df)
    opers = result["oper_summary"][schema.YIELD_OPER_COLUMN].unique()
    oper = opers[0]
    msg = yp.build_detail_view(
        result["oper_summary"], result["cat_detail"],
        {"show_all": False, "oper": oper, "cat": None, "quit": False},
    )
    assert f"{oper} 수율 Trend" in msg
    print(f"  공정 뷰({oper}): {len(msg)}자")


# =============================================================================
# 7. 요청 파싱 테스트
# =============================================================================

def test_parse_detail_request():
    """사용자 요청 파싱."""
    # 종료
    r = yp.parse_detail_request("종료")
    assert r["quit"] is True

    r = yp.parse_detail_request("exit")
    assert r["quit"] is True

    # 전체
    r = yp.parse_detail_request("전체 보여줘")
    assert r["show_all"] is True
    assert r["quit"] is False

    # cat만
    r = yp.parse_detail_request("cat2 불량률 보여줘")
    assert r["cat"] == "cat2"
    assert r["quit"] is False

    print("  파싱 테스트 통과")


# =============================================================================
# 8. FSM 전이 테스트
# =============================================================================

def test_fsm_transitions():
    """수율 워크플로우 FSM 전이 검증."""
    sm = StateMachine(WorkflowType.YIELD_TREND)

    # COLLECTING_PARAMS → YIELD_LOADING_DATA
    sm._state = WorkflowState.COLLECTING_PARAMS
    sm.transition_to(WorkflowState.YIELD_LOADING_DATA)
    assert sm.state == WorkflowState.YIELD_LOADING_DATA

    # YIELD_LOADING_DATA → YIELD_PREPROCESSING
    sm.transition_to(WorkflowState.YIELD_PREPROCESSING)
    assert sm.state == WorkflowState.YIELD_PREPROCESSING

    # YIELD_PREPROCESSING → YIELD_SHOWING_OVERVIEW
    sm.transition_to(WorkflowState.YIELD_SHOWING_OVERVIEW)
    assert sm.state == WorkflowState.YIELD_SHOWING_OVERVIEW

    # YIELD_SHOWING_OVERVIEW → YIELD_AWAITING_REQUEST
    sm.transition_to(WorkflowState.YIELD_AWAITING_REQUEST)
    assert sm.state == WorkflowState.YIELD_AWAITING_REQUEST

    # YIELD_AWAITING_REQUEST → YIELD_SHOWING_DETAIL (루프)
    sm.transition_to(WorkflowState.YIELD_SHOWING_DETAIL)
    assert sm.state == WorkflowState.YIELD_SHOWING_DETAIL

    # YIELD_SHOWING_DETAIL → YIELD_AWAITING_REQUEST (루프 복귀)
    sm.transition_to(WorkflowState.YIELD_AWAITING_REQUEST)
    assert sm.state == WorkflowState.YIELD_AWAITING_REQUEST

    # YIELD_AWAITING_REQUEST → COMPLETED (종료)
    sm.transition_to(WorkflowState.COMPLETED)
    assert sm.state == WorkflowState.COMPLETED

    print("  FSM 전이 테스트 통과")


# =============================================================================
# 9. 통합 테스트 (파이프라인 end-to-end)
# =============================================================================

def test_end_to_end():
    """전체 파이프라인 흐름 mock 테스트."""
    tmp_dir = tempfile.mkdtemp()
    original_dir = schema.YIELD_PARQUET_DIR
    try:
        schema.YIELD_PARQUET_DIR = tmp_dir

        params = {"lot_cd": "LOT001"}

        # 1. week 결정
        weeks = yp.resolve_weeks(params)
        assert len(weeks) == 1

        # 2. 데이터 로드 (첫 호출: DB 조회 + parquet 저장)
        raw_df = yp.load_or_query(params, weeks)
        assert not raw_df.empty
        parquet_path = yp.get_parquet_path("LOT001", weeks[0])
        assert parquet_path.exists()

        # 3. 필터링
        filtered = yp.filter_by_date(raw_df, None, None)
        assert len(filtered) == len(raw_df)

        # 4. 전처리
        summary = yp.preprocess_yield(filtered)
        assert "oper_summary" in summary
        assert "cat_detail" in summary

        # 5. overview 메시지
        overview = yp.build_overview_message(
            summary["oper_summary"], summary["cat_detail"]
        )
        assert len(overview) > 0

        # 6. 상세 뷰 (전체)
        detail = yp.build_detail_view(
            summary["oper_summary"], summary["cat_detail"],
            {"show_all": True, "oper": None, "cat": None, "quit": False},
        )
        assert "전체 공정 수율 Trend" in detail

        # 7. 두 번째 호출: 캐시 히트
        raw_df2 = yp.load_or_query(params, weeks)
        assert len(raw_df2) == len(raw_df)

        print(f"  E2E: {len(raw_df)}행 → overview {len(overview)}자 → detail {len(detail)}자")

    finally:
        schema.YIELD_PARQUET_DIR = original_dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# Runner
# =============================================================================

if __name__ == "__main__":
    tests = [
        ("Week → 날짜 범위 변환", test_week_to_date_range),
        ("날짜 → Week 변환", test_date_to_week),
        ("resolve_weeks 기본값", test_resolve_weeks_default),
        ("resolve_weeks 명시", test_resolve_weeks_explicit),
        ("resolve_weeks 날짜범위", test_resolve_weeks_date_range),
        ("Parquet 캐싱", test_parquet_cache),
        ("Mock 데이터 조회", test_query_yield_data),
        ("전처리 (수율/불량률)", test_preprocess_yield),
        ("날짜 필터링", test_filter_by_date),
        ("Overview 메시지", test_build_overview_message),
        ("Detail 뷰 (전체)", test_build_detail_view_all),
        ("Detail 뷰 (공정)", test_build_detail_view_oper),
        ("요청 파싱", test_parse_detail_request),
        ("FSM 전이", test_fsm_transitions),
        ("E2E 통합", test_end_to_end),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            print(f"[TEST] {name}")
            fn()
            print(f"  => PASS\n")
            passed += 1
        except Exception as e:
            print(f"  => FAIL: {e}\n")
            failed += 1

    print(f"{'='*40}")
    print(f"결과: {passed} passed, {failed} failed / {len(tests)} total")
    if failed == 0:
        print("모든 테스트 통과!")
    else:
        print("실패한 테스트가 있습니다.")
