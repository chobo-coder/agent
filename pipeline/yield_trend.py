"""수율 경향성 분석 파이프라인.

mock 데이터 기반으로 동작. 실제 DB 연동은 루코드가 구현.

워크플로우:
  YIELD_LOADING_DATA → YIELD_PREPROCESSING → YIELD_SHOWING_OVERVIEW
  → YIELD_AWAITING_REQUEST ↔ YIELD_SHOWING_DETAIL → COMPLETED
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import schema


# =============================================================================
# Week 유틸리티
# =============================================================================

def _current_week() -> str:
    """현재 주차를 YYYY-WNN 형식으로 반환."""
    today = datetime.now()
    iso = today.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _previous_week() -> str:
    """전주를 YYYY-WNN 형식으로 반환."""
    last_week = datetime.now() - timedelta(weeks=1)
    iso = last_week.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _week_to_date_range(week_str: str) -> tuple[str, str]:
    """YYYY-WNN → (월요일 YYYYMMDD, 일요일 YYYYMMDD) 변환."""
    # "2025-W20" → year=2025, week=20
    match = re.match(r"(\d{4})-?W(\d{1,2})", week_str)
    if not match:
        raise ValueError(f"잘못된 week 형식: {week_str}")
    year, week_num = int(match.group(1)), int(match.group(2))
    # ISO week: 월요일 기준
    monday = datetime.strptime(f"{year}-W{week_num:02d}-1", "%G-W%V-%u")
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y%m%d"), sunday.strftime("%Y%m%d")


def _date_to_week(date_str: str) -> str:
    """YYYYMMDD → YYYY-WNN 변환."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def resolve_weeks(params: dict) -> list[str]:
    """파라미터에서 조회 대상 week 목록 결정.

    우선순위:
      1. from_date/end_date → 해당 날짜들이 걸치는 week 목록
      2. week 명시 → 해당 week
      3. 없음 → 전주
    """
    from_date = params.get("from_date")
    end_date = params.get("end_date")

    if from_date and end_date:
        weeks: list[str] = []
        start_week = _date_to_week(from_date)
        end_week = _date_to_week(end_date)
        # 시작 week부터 끝 week까지 순회
        current = datetime.strptime(from_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        seen: set[str] = set()
        while current <= end_dt:
            w = _date_to_week(current.strftime("%Y%m%d"))
            if w not in seen:
                seen.add(w)
                weeks.append(w)
            current += timedelta(days=7)
        # end_week이 누락될 수 있으므로 보정
        if end_week not in seen:
            weeks.append(end_week)
        return weeks

    week = params.get("week")
    if week:
        return [week]

    return [_previous_week()]


# =============================================================================
# Parquet 캐싱
# =============================================================================

def get_parquet_path(lot_cd: str, week: str) -> Path:
    """parquet 파일 경로 생성."""
    safe_week = week.replace("-", "")
    return Path(schema.YIELD_PARQUET_DIR) / lot_cd / f"week_{safe_week}.parquet"


def save_parquet(df: pd.DataFrame, lot_cd: str, week: str) -> Path:
    """DataFrame을 parquet으로 저장."""
    path = get_parquet_path(lot_cd, week)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def load_or_query(params: dict, weeks: list[str]) -> pd.DataFrame:
    """각 week별로 parquet 존재 시 로드, 없으면 DB 조회 + 저장. 여러 week이면 concat."""
    lot_cd = params["lot_cd"]
    frames: list[pd.DataFrame] = []

    for week in weeks:
        path = get_parquet_path(lot_cd, week)
        if path.exists():
            df = pd.read_parquet(path)
        else:
            df = query_yield_data(params, week)
            save_parquet(df, lot_cd, week)
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# =============================================================================
# DB 조회 (mock)
# =============================================================================

def query_yield_data(params: dict, week: str) -> pd.DataFrame:
    """단일 week의 수율 데이터 조회 (mock).

    Returns:
        DataFrame columns: lot_cd, oper, test_date, cat, in_count, out_count
    """
    # TODO: 실제 SQL 쿼리는 루코드가 구현
    lot_cd = params.get("lot_cd", "LOT_001")
    oper_list = params.get("oper")
    if oper_list:
        opers = [oper_list] if isinstance(oper_list, str) else oper_list
    else:
        opers = schema.OPER_OPTIONS if schema.OPER_OPTIONS else ["OP1", "OP2", "OP3"]

    start_str, end_str = _week_to_date_range(week)
    start_dt = datetime.strptime(start_str, "%Y%m%d")
    end_dt = datetime.strptime(end_str, "%Y%m%d")

    cats = ["cat1", "cat2", "cat3"]
    rng = np.random.default_rng(hash(f"{lot_cd}_{week}") % (2**31))

    rows = []
    current = start_dt
    while current <= end_dt:
        date_str = current.strftime("%Y%m%d")
        for oper in opers:
            for cat in cats:
                in_count = rng.integers(800, 1200)
                # 수율 90~99% 범위의 mock
                yield_rate = rng.uniform(0.90, 0.99)
                out_count = int(in_count * yield_rate)
                rows.append({
                    schema.YIELD_LOT_COLUMN: lot_cd,
                    schema.YIELD_OPER_COLUMN: oper,
                    schema.YIELD_DATE_COLUMN: date_str,
                    schema.YIELD_CAT_COLUMN: cat,
                    schema.YIELD_IN_COLUMN: in_count,
                    schema.YIELD_OUT_COLUMN: out_count,
                })
        current += timedelta(days=1)

    return pd.DataFrame(rows)


# =============================================================================
# 날짜 필터링
# =============================================================================

def filter_by_date(
    df: pd.DataFrame,
    from_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    """from_date ~ end_date 범위로 필터링. None이면 필터 안 함."""
    if not from_date and not end_date:
        return df
    result = df.copy()
    date_col = schema.YIELD_DATE_COLUMN
    if from_date:
        result = result[result[date_col] >= from_date]
    if end_date:
        result = result[result[date_col] <= end_date]
    return result.reset_index(drop=True)


# =============================================================================
# 전처리 (수율/불량률 계산)
# =============================================================================

def preprocess_yield(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """수율/불량률 계산 + 집계.

    Returns:
        {
            "oper_summary": DataFrame[oper, test_date, total_in, total_out, yield_rate],
            "cat_detail": DataFrame[oper, test_date, cat, in_count, fail_count, defect_rate],
        }
    """
    date_col = schema.YIELD_DATE_COLUMN
    oper_col = schema.YIELD_OPER_COLUMN
    cat_col = schema.YIELD_CAT_COLUMN
    in_col = schema.YIELD_IN_COLUMN
    out_col = schema.YIELD_OUT_COLUMN

    # 공정별 수율 (날짜별)
    oper_summary = df.groupby([oper_col, date_col], as_index=False).agg(
        total_in=(in_col, "sum"),
        total_out=(out_col, "sum"),
    )
    oper_summary["yield_rate"] = (
        oper_summary["total_out"] / oper_summary["total_in"]
    ).round(4)

    # 공정-cat별 불량률 (날짜별)
    cat_detail = df.copy()
    cat_detail["fail_count"] = cat_detail[in_col] - cat_detail[out_col]
    cat_detail["defect_rate"] = (
        cat_detail["fail_count"] / cat_detail[in_col]
    ).round(4)
    cat_detail = cat_detail[
        [oper_col, date_col, cat_col, in_col, "fail_count", "defect_rate"]
    ].rename(columns={in_col: "in_count"})

    return {
        "oper_summary": oper_summary,
        "cat_detail": cat_detail,
    }


# =============================================================================
# 메시지 빌더
# =============================================================================

def build_overview_message(
    oper_summary: pd.DataFrame,
    cat_detail: pd.DataFrame,
) -> str:
    """공정별 수율 + cat별 불량률 overview 메시지 생성."""
    oper_col = schema.YIELD_OPER_COLUMN
    cat_col = schema.YIELD_CAT_COLUMN

    lines = ["### 공정별 수율 요약\n"]

    # 공정별 평균 수율
    oper_avg = oper_summary.groupby(oper_col, as_index=False).agg(
        avg_yield=("yield_rate", "mean"),
        total_in=("total_in", "sum"),
        total_out=("total_out", "sum"),
    )
    lines.append("| 공정 | 총 투입 | 총 양품 | 평균 수율 |")
    lines.append("|------|---------|---------|----------|")
    for _, row in oper_avg.iterrows():
        lines.append(
            f"| {row[oper_col]} | {row['total_in']:,} | {row['total_out']:,} "
            f"| {row['avg_yield']:.2%} |"
        )

    lines.append("\n### 공정-카테고리별 불량률 요약\n")

    # 공정-cat별 평균 불량률
    cat_avg = cat_detail.groupby([oper_col, cat_col], as_index=False).agg(
        avg_defect=("defect_rate", "mean"),
        total_fail=("fail_count", "sum"),
    )
    lines.append("| 공정 | 카테고리 | 총 불량 | 평균 불량률 |")
    lines.append("|------|----------|---------|-----------|")
    for _, row in cat_avg.iterrows():
        lines.append(
            f"| {row[oper_col]} | {row[cat_col]} | {row['total_fail']:,} "
            f"| {row['avg_defect']:.2%} |"
        )

    lines.append("\n---")
    lines.append("**다음 명령을 입력해주세요:**")
    lines.append("- `전체 보여줘` — 모든 공정의 수율 trend 표")
    lines.append("- `{공정} 보여줘` — 특정 공정의 수율 + cat 불량률")
    lines.append("- `{공정} {cat} 보여줘` — 특정 공정-cat 불량률 상세")
    lines.append("- `종료` — 분석 종료")

    return "\n".join(lines)


# =============================================================================
# 사용자 요청 파싱
# =============================================================================

def parse_detail_request(text: str) -> dict:
    """사용자 요청 파싱.

    Returns:
        {"show_all": bool, "oper": str|None, "cat": str|None, "quit": bool}
    """
    text_lower = text.lower().strip()

    # 종료
    if any(kw in text_lower for kw in ["종료", "끝", "quit", "exit", "done"]):
        return {"show_all": False, "oper": None, "cat": None, "quit": True}

    # 전체
    if any(kw in text_lower for kw in ["전체", "전부", "모두", "all"]):
        return {"show_all": True, "oper": None, "cat": None, "quit": False}

    # oper + cat 파싱
    oper = None
    cat = None

    # OPER_OPTIONS에서 매칭
    for op in schema.OPER_OPTIONS:
        if op and op.lower() in text_lower:
            oper = op
            break

    # cat 매칭 (cat1, cat2 등)
    cat_match = re.search(r"(cat\d+)", text_lower)
    if cat_match:
        cat = cat_match.group(1)

    return {"show_all": False, "oper": oper, "cat": cat, "quit": False}


# =============================================================================
# 상세 뷰 빌더
# =============================================================================

def build_detail_view(
    oper_summary: pd.DataFrame,
    cat_detail: pd.DataFrame,
    request: dict,
) -> str:
    """사용자 요청에 따른 상세 뷰 메시지 생성."""
    oper_col = schema.YIELD_OPER_COLUMN
    date_col = schema.YIELD_DATE_COLUMN
    cat_col = schema.YIELD_CAT_COLUMN

    lines: list[str] = []

    if request.get("show_all"):
        # 모든 공정 수율 trend 표
        lines.append("### 전체 공정 수율 Trend\n")
        opers = sorted(oper_summary[oper_col].unique())
        for oper in opers:
            oper_data = oper_summary[oper_summary[oper_col] == oper].sort_values(date_col)
            lines.append(f"**{oper}**\n")
            lines.append("| 날짜 | 투입 | 양품 | 수율 |")
            lines.append("|------|------|------|------|")
            for _, row in oper_data.iterrows():
                lines.append(
                    f"| {row[date_col]} | {row['total_in']:,} | {row['total_out']:,} "
                    f"| {row['yield_rate']:.2%} |"
                )
            lines.append("")
        return "\n".join(lines)

    oper = request.get("oper")
    cat = request.get("cat")

    if oper and cat:
        # 특정 공정-cat 불량률 상세
        filtered = cat_detail[
            (cat_detail[oper_col] == oper) & (cat_detail[cat_col] == cat)
        ].sort_values(date_col)
        if filtered.empty:
            return f"**{oper} / {cat}** 에 해당하는 데이터가 없습니다."
        lines.append(f"### {oper} — {cat} 불량률 Trend\n")
        lines.append("| 날짜 | 투입 | 불량 | 불량률 |")
        lines.append("|------|------|------|--------|")
        for _, row in filtered.iterrows():
            lines.append(
                f"| {row[date_col]} | {row['in_count']:,} | {row['fail_count']:,} "
                f"| {row['defect_rate']:.2%} |"
            )
        return "\n".join(lines)

    if oper:
        # 특정 공정 수율 + 전체 cat 불량률
        oper_data = oper_summary[oper_summary[oper_col] == oper].sort_values(date_col)
        cat_data = cat_detail[cat_detail[oper_col] == oper].sort_values([date_col, cat_col])

        if oper_data.empty:
            return f"**{oper}** 공정 데이터가 없습니다."

        lines.append(f"### {oper} 수율 Trend\n")
        lines.append("| 날짜 | 투입 | 양품 | 수율 |")
        lines.append("|------|------|------|------|")
        for _, row in oper_data.iterrows():
            lines.append(
                f"| {row[date_col]} | {row['total_in']:,} | {row['total_out']:,} "
                f"| {row['yield_rate']:.2%} |"
            )
        lines.append(f"\n### {oper} 카테고리별 불량률\n")
        lines.append("| 날짜 | 카테고리 | 투입 | 불량 | 불량률 |")
        lines.append("|------|----------|------|------|--------|")
        for _, row in cat_data.iterrows():
            lines.append(
                f"| {row[date_col]} | {row[cat_col]} | {row['in_count']:,} "
                f"| {row['fail_count']:,} | {row['defect_rate']:.2%} |"
            )
        return "\n".join(lines)

    if cat:
        # 모든 공정의 해당 cat 불량률
        filtered = cat_detail[cat_detail[cat_col] == cat].sort_values([oper_col, date_col])
        if filtered.empty:
            return f"**{cat}** 카테고리 데이터가 없습니다."
        lines.append(f"### {cat} 불량률 Trend (전체 공정)\n")
        lines.append("| 공정 | 날짜 | 투입 | 불량 | 불량률 |")
        lines.append("|------|------|------|------|--------|")
        for _, row in filtered.iterrows():
            lines.append(
                f"| {row[oper_col]} | {row[date_col]} | {row['in_count']:,} "
                f"| {row['fail_count']:,} | {row['defect_rate']:.2%} |"
            )
        return "\n".join(lines)

    return "공정 또는 카테고리를 지정해주세요. (예: `OP1 보여줘`, `OP1 cat1 보여줘`, `전체 보여줘`)"
