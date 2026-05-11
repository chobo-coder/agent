"""전처리 미리보기 — 실제 데이터 변경 없이 영향도만 계산.

각 전처리 도구가 적용되면 어떤 행/컬럼이 제거되는지 미리 계산하고,
사용자가 '완료'할 때까지 누적한 후 한 번에 적용하는 지연(lazy) 방식.

TODO: 루코드가 실제 미리보기 로직을 구현.
      현재는 mock 데이터를 반환하는 stub 함수만 존재.
"""

from dataclasses import dataclass, field

import pandas as pd
import numpy as np

import schema


@dataclass
class PreprocessAction:
    """단일 전처리 도구의 미리보기 결과"""
    tool_id: str
    tool_name: str
    handler: str
    params: dict
    drop_indices: list[int] = field(default_factory=list)   # 제거될 행 인덱스
    drop_columns: list[str] = field(default_factory=list)   # 제거될 컬럼
    transform_columns: list[str] = field(default_factory=list)  # 변환될 컬럼 (스케일링, 인코딩 등)
    description: str = ""  # 미리보기 설명


@dataclass
class PreprocessPlan:
    """누적된 전처리 계획 (지연 적용용)"""
    actions: list[PreprocessAction] = field(default_factory=list)
    original_shape: tuple[int, int] = (0, 0)  # 원본 (rows, cols)

    def add(self, action: PreprocessAction) -> None:
        self.actions.append(action)

    def remove(self, index: int) -> PreprocessAction | None:
        """index번째 액션을 제거하고 반환"""
        if 0 <= index < len(self.actions):
            return self.actions.pop(index)
        return None

    @property
    def all_drop_indices(self) -> set[int]:
        """누적된 전체 제거 행 인덱스"""
        indices: set[int] = set()
        for a in self.actions:
            indices.update(a.drop_indices)
        return indices

    @property
    def all_drop_columns(self) -> set[str]:
        """누적된 전체 제거 컬럼"""
        cols: set[str] = set()
        for a in self.actions:
            cols.update(a.drop_columns)
        return cols

    @property
    def remaining_shape(self) -> tuple[int, int]:
        """전처리 후 예상 shape"""
        rows = self.original_shape[0] - len(self.all_drop_indices)
        cols = self.original_shape[1] - len(self.all_drop_columns)
        return (max(rows, 0), max(cols, 0))

    def build_summary(self) -> str:
        """누적된 전처리 계획 요약"""
        if not self.actions:
            return "적용된 전처리가 없습니다."

        lines = ["### 전처리 계획 현황\n"]
        lines.append(f"원본 데이터: **{self.original_shape[0]}행 × {self.original_shape[1]}열**\n")

        for i, a in enumerate(self.actions, 1):
            lines.append(f"**{i}. {a.tool_name}**")
            lines.append(f"  {a.description}")

        remaining = self.remaining_shape
        drop_rows = len(self.all_drop_indices)
        drop_cols = len(self.all_drop_columns)

        lines.append("")
        lines.append("---")
        lines.append(f"**누적 결과**: 행 -{drop_rows} / 컬럼 -{drop_cols}")
        lines.append(f"**예상 결과**: **{remaining[0]}행 × {remaining[1]}열**")

        if self.all_drop_columns:
            lines.append(f"\n제거 예정 컬럼: `{'`, `'.join(sorted(self.all_drop_columns))}`")

        lines.append("\n---\n")
        lines.append("추가 전처리를 선택하거나, `완료`를 입력하면 전처리를 적용합니다.")

        return "\n".join(lines)


def preview_tool(
    df: pd.DataFrame,
    tool: dict,
    plan: PreprocessPlan,
) -> PreprocessAction:
    """전처리 도구의 미리보기를 계산 (데이터 변경 없음).

    Args:
        df: 원본 DataFrame
        tool: schema.PREPROCESSING_TOOLS 항목
        plan: 기존 누적 계획 (이전 액션의 drop_indices/columns 반영)

    Returns:
        PreprocessAction 미리보기 결과
    """
    # 이미 누적된 제거 반영한 가상 DataFrame
    virtual_df = _get_virtual_df(df, plan)

    handler = tool["handler"]
    params = tool["params"]
    tool_id = tool["id"]
    tool_name = tool["name"]

    if handler == "missing_values":
        return _preview_missing(virtual_df, tool_id, tool_name, params)
    elif handler == "outliers":
        return _preview_outliers(virtual_df, tool_id, tool_name, params)
    elif handler == "encoding":
        return _preview_encoding(virtual_df, tool_id, tool_name, params)
    elif handler == "scaling":
        return _preview_scaling(virtual_df, tool_id, tool_name, params)
    elif handler == "low_variance":
        return _preview_low_variance(virtual_df, tool_id, tool_name, params)
    elif handler == "high_na_columns":
        return _preview_high_na(virtual_df, tool_id, tool_name, params)
    elif handler == "ttest_filter":
        return _preview_ttest(virtual_df, tool_id, tool_name, params)
    elif handler == "correlated_pairs":
        return _preview_correlated(virtual_df, tool_id, tool_name, params)
    else:
        return PreprocessAction(
            tool_id=tool_id, tool_name=tool_name,
            handler=handler, params=params,
            description="미리보기 미지원",
        )


def apply_plan(df: pd.DataFrame, plan: PreprocessPlan) -> pd.DataFrame:
    """누적된 계획을 실제 데이터에 적용.

    TODO: 루코드가 실제 적용 로직 구현.
    현재는 drop_indices/drop_columns만 적용하고,
    변환(스케일링/인코딩 등)은 PreprocessingHandler에 위임.
    """
    result = df.copy()

    # 행 제거
    drop_idx = plan.all_drop_indices
    if drop_idx:
        result = result.drop(index=[i for i in drop_idx if i in result.index])

    # 컬럼 제거
    drop_cols = plan.all_drop_columns
    if drop_cols:
        result = result.drop(columns=[c for c in drop_cols if c in result.columns])

    result = result.reset_index(drop=True)
    return result


# =============================================================================
# 내부 헬퍼
# =============================================================================

def _get_virtual_df(df: pd.DataFrame, plan: PreprocessPlan) -> pd.DataFrame:
    """기존 계획의 제거를 반영한 가상 DataFrame (미리보기 계산용)"""
    virtual = df.copy()
    drop_idx = plan.all_drop_indices
    drop_cols = plan.all_drop_columns
    if drop_idx:
        virtual = virtual.drop(index=[i for i in drop_idx if i in virtual.index])
    if drop_cols:
        virtual = virtual.drop(columns=[c for c in drop_cols if c in virtual.columns])
    return virtual


# =============================================================================
# 도구별 미리보기 함수 — TODO: 루코드가 실제 로직 구현
# =============================================================================

def _preview_missing(df: pd.DataFrame, tool_id: str, tool_name: str, params: dict) -> PreprocessAction:
    """결측치 처리 미리보기.

    TODO: 루코드 구현
    - strategy == "drop": df에서 NaN이 있는 행의 인덱스 목록 반환
    - strategy == "mean"/"median": 변환될 컬럼 목록 반환 (행/컬럼 제거 없음)
    """
    strategy = params.get("missing_strategy", "drop")

    # --- mock (루코드가 교체) ---
    if strategy == "drop":
        total = len(df)
        drop_count = max(1, total // 10)  # mock: 10% 제거
        drop_indices = list(range(0, drop_count))
        return PreprocessAction(
            tool_id=tool_id, tool_name=tool_name,
            handler="missing_values", params=params,
            drop_indices=drop_indices,
            description=f"결측치 포함 행 {drop_count}개 제거 예정 ({drop_count}/{total}행)",
        )
    else:
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        return PreprocessAction(
            tool_id=tool_id, tool_name=tool_name,
            handler="missing_values", params=params,
            transform_columns=numeric_cols,
            description=f"수치형 {len(numeric_cols)}개 컬럼의 결측치를 {strategy}으로 대체 (행/컬럼 변화 없음)",
        )


def _preview_outliers(df: pd.DataFrame, tool_id: str, tool_name: str, params: dict) -> PreprocessAction:
    """이상치 제거 미리보기.

    TODO: 루코드 구현
    - IQR/zscore 기준으로 이상치 행 인덱스 계산
    """
    method = params.get("outlier_method", "iqr")
    total = len(df)
    drop_count = max(1, total // 20)  # mock: 5% 제거
    drop_indices = list(range(total - drop_count, total))
    return PreprocessAction(
        tool_id=tool_id, tool_name=tool_name,
        handler="outliers", params=params,
        drop_indices=drop_indices,
        description=f"이상치({method}) {drop_count}행 제거 예정 ({drop_count}/{total}행)",
    )


def _preview_encoding(df: pd.DataFrame, tool_id: str, tool_name: str, params: dict) -> PreprocessAction:
    """인코딩 미리보기.

    TODO: 루코드 구현
    - 범주형 컬럼 목록 반환 (원핫 시 컬럼 수 변화 예측)
    """
    cat_cols = schema.CATEGORICAL_COLUMNS
    return PreprocessAction(
        tool_id=tool_id, tool_name=tool_name,
        handler="encoding", params=params,
        transform_columns=list(cat_cols),
        description=f"범주형 {len(cat_cols)}개 컬럼 인코딩 예정: `{'`, `'.join(cat_cols)}`",
    )


def _preview_scaling(df: pd.DataFrame, tool_id: str, tool_name: str, params: dict) -> PreprocessAction:
    """스케일링 미리보기."""
    method = params.get("scaling_method", "standard")
    numeric_cols = schema.NUMERIC_COLUMNS
    return PreprocessAction(
        tool_id=tool_id, tool_name=tool_name,
        handler="scaling", params=params,
        transform_columns=list(numeric_cols),
        description=f"수치형 {len(numeric_cols)}개 컬럼 {method} 스케일링 예정 (행/컬럼 변화 없음)",
    )


def _preview_low_variance(df: pd.DataFrame, tool_id: str, tool_name: str, params: dict) -> PreprocessAction:
    """저분산 컬럼 제거 미리보기.

    TODO: 루코드 구현
    - df.var() < threshold 인 컬럼 목록 반환
    """
    # --- mock (루코드가 교체) ---
    drop_cols = [schema.NUMERIC_COLUMNS[0]] if schema.NUMERIC_COLUMNS else []
    return PreprocessAction(
        tool_id=tool_id, tool_name=tool_name,
        handler="low_variance", params=params,
        drop_columns=drop_cols,
        description=f"저분산 컬럼 {len(drop_cols)}개 제거 예정: `{'`, `'.join(drop_cols)}`" if drop_cols else "저분산 컬럼 없음",
    )


def _preview_high_na(df: pd.DataFrame, tool_id: str, tool_name: str, params: dict) -> PreprocessAction:
    """NA 다수 컬럼 제거 미리보기.

    TODO: 루코드 구현
    - df.isna().mean() >= threshold 인 컬럼 목록 반환
    """
    # --- mock ---
    return PreprocessAction(
        tool_id=tool_id, tool_name=tool_name,
        handler="high_na_columns", params=params,
        drop_columns=[],
        description="NA 비율 초과 컬럼 없음 (mock)",
    )


def _preview_ttest(df: pd.DataFrame, tool_id: str, tool_name: str, params: dict) -> PreprocessAction:
    """t-test 비유의 컬럼 제거 미리보기.

    TODO: 루코드 구현
    - 타겟 대비 p-value >= alpha 인 컬럼 목록 반환
    """
    # --- mock ---
    drop_cols = [schema.NUMERIC_COLUMNS[-1]] if len(schema.NUMERIC_COLUMNS) > 1 else []
    return PreprocessAction(
        tool_id=tool_id, tool_name=tool_name,
        handler="ttest_filter", params=params,
        drop_columns=drop_cols,
        description=f"t-test 비유의 컬럼 {len(drop_cols)}개 제거 예정" + (f": `{'`, `'.join(drop_cols)}`" if drop_cols else ""),
    )


def _preview_correlated(df: pd.DataFrame, tool_id: str, tool_name: str, params: dict) -> PreprocessAction:
    """고상관 페어 컬럼 제거 미리보기.

    TODO: 루코드 구현
    - |corr| >= threshold 쌍에서 평균 상관 높은 쪽 컬럼 목록 반환
    """
    # --- mock ---
    drop_cols = [schema.NUMERIC_COLUMNS[1]] if len(schema.NUMERIC_COLUMNS) > 1 else []
    return PreprocessAction(
        tool_id=tool_id, tool_name=tool_name,
        handler="correlated_pairs", params=params,
        drop_columns=drop_cols,
        description=f"고상관 페어 컬럼 {len(drop_cols)}개 제거 예정" + (f": `{'`, `'.join(drop_cols)}`" if drop_cols else ""),
    )
