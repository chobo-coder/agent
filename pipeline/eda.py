"""EDA (탐색적 데이터 분석) — 조회 결과에 대한 기본 분석.

수행 항목:
  1. 결측치 조사: 컬럼별 결측 비율
  2. 저분산 피처 확인: 분산이 임계값 미만인 컬럼
  3. 고상관 피처 확인: 상관계수 절대값이 임계값 이상인 피처 쌍

TODO: 루코드가 실제 EDA 로직을 구현.
      현재는 mock 데이터를 반환하는 stub 함수만 존재.
"""

from dataclasses import dataclass, field

import pandas as pd

import schema


@dataclass
class EDAResult:
    """EDA 분석 결과"""
    missing: pd.DataFrame        # 컬럼별 결측 현황 (column, count, ratio)
    low_variance: pd.DataFrame   # 저분산 피처 목록 (column, variance)
    high_correlation: pd.DataFrame  # 고상관 피처 쌍 (col_a, col_b, corr)
    summary: str = ""            # 마크다운 요약


def run_eda(
    df: pd.DataFrame,
    variance_threshold: float = 0.01,
    corr_threshold: float = 0.9,
) -> EDAResult:
    """EDA 실행 — 결측치, 저분산, 고상관 분석.

    Args:
        df: 분석 대상 DataFrame
        variance_threshold: 저분산 기준 (이 값 미만이면 저분산)
        corr_threshold: 고상관 기준 (이 값 이상이면 고상관)

    Returns:
        EDAResult 객체
    """
    missing = analyze_missing(df)
    low_var = analyze_low_variance(df, threshold=variance_threshold)
    high_corr = analyze_high_correlation(df, threshold=corr_threshold)

    summary = _build_summary(missing, low_var, high_corr)

    return EDAResult(
        missing=missing,
        low_variance=low_var,
        high_correlation=high_corr,
        summary=summary,
    )


# =============================================================================
# 개별 분석 함수 — TODO: 루코드가 실제 로직 구현
# =============================================================================

def analyze_missing(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼별 결측치 현황 분석.

    TODO: 루코드 구현
    - df의 각 컬럼에 대해 결측 수(count)와 비율(ratio) 계산
    - ratio 내림차순 정렬
    - 결측이 0인 컬럼도 포함 (전체 현황 파악용)

    Returns:
        DataFrame with columns: [column, count, ratio]
    """
    # --- mock 데이터 (루코드가 교체) ---
    columns = schema.DB_COLUMNS + schema.S3_COLUMNS
    # 중복 제거
    columns = list(dict.fromkeys(columns))
    mock_data = []
    for i, col in enumerate(columns):
        count = (i * 3) % 10  # mock 결측 수
        ratio = round(count / max(100, 1), 4)
        mock_data.append({"column": col, "count": count, "ratio": ratio})
    return pd.DataFrame(mock_data).sort_values("ratio", ascending=False).reset_index(drop=True)


def analyze_low_variance(df: pd.DataFrame, threshold: float = 0.01) -> pd.DataFrame:
    """저분산 피처 확인.

    TODO: 루코드 구현
    - schema.NUMERIC_COLUMNS 대상으로 분산 계산
    - threshold 미만인 컬럼 필터링
    - 분산 오름차순 정렬

    Returns:
        DataFrame with columns: [column, variance]
    """
    # --- mock 데이터 (루코드가 교체) ---
    mock_data = []
    for col in schema.NUMERIC_COLUMNS:
        var = round(hash(col) % 100 / 1000, 4)  # mock 분산
        if var < threshold:
            mock_data.append({"column": col, "variance": var})
    if not mock_data:
        # mock: 최소 1개는 저분산으로 표시
        mock_data.append({"column": schema.NUMERIC_COLUMNS[0], "variance": 0.005})
    return pd.DataFrame(mock_data).sort_values("variance").reset_index(drop=True)


def analyze_high_correlation(df: pd.DataFrame, threshold: float = 0.9) -> pd.DataFrame:
    """고상관 피처 쌍 확인.

    TODO: 루코드 구현
    - schema.NUMERIC_COLUMNS 대상으로 상관행렬 계산
    - 상삼각 행렬에서 |corr| >= threshold 인 쌍 추출
    - 상관계수 절대값 내림차순 정렬

    Returns:
        DataFrame with columns: [col_a, col_b, correlation]
    """
    # --- mock 데이터 (루코드가 교체) ---
    cols = schema.NUMERIC_COLUMNS
    mock_data = []
    if len(cols) >= 2:
        mock_data.append({"col_a": cols[0], "col_b": cols[1], "correlation": 0.95})
    if len(cols) >= 4:
        mock_data.append({"col_a": cols[2], "col_b": cols[3], "correlation": 0.91})
    return pd.DataFrame(mock_data)


# =============================================================================
# 요약 텍스트 빌더
# =============================================================================

def _build_summary(
    missing: pd.DataFrame,
    low_var: pd.DataFrame,
    high_corr: pd.DataFrame,
) -> str:
    """EDA 결과를 마크다운 요약 텍스트로 변환"""
    lines = ["### EDA 결과\n"]

    # 결측치
    has_missing = missing[missing["count"] > 0]
    lines.append(f"**1. 결측치 현황** — 전체 {len(missing)}개 컬럼 중 {len(has_missing)}개에 결측 존재\n")
    if not has_missing.empty:
        lines.append("| 컬럼 | 결측 수 | 비율 |")
        lines.append("|------|---------|------|")
        for _, row in has_missing.iterrows():
            lines.append(f"| {row['column']} | {row['count']} | {row['ratio']:.2%} |")
        lines.append("")
    else:
        lines.append("결측치 없음\n")

    # 저분산
    lines.append(f"**2. 저분산 피처** — {len(low_var)}개 감지\n")
    if not low_var.empty:
        lines.append("| 컬럼 | 분산 |")
        lines.append("|------|------|")
        for _, row in low_var.iterrows():
            lines.append(f"| {row['column']} | {row['variance']:.6f} |")
        lines.append("")
    else:
        lines.append("저분산 피처 없음\n")

    # 고상관
    lines.append(f"**3. 고상관 피처 쌍** — {len(high_corr)}쌍 감지\n")
    if not high_corr.empty:
        lines.append("| 피처 A | 피처 B | 상관계수 |")
        lines.append("|--------|--------|----------|")
        for _, row in high_corr.iterrows():
            lines.append(f"| {row['col_a']} | {row['col_b']} | {row['correlation']:.4f} |")
        lines.append("")
    else:
        lines.append("고상관 피처 쌍 없음\n")

    return "\n".join(lines)
