"""MAP 경향성 분석 파이프라인.

mock 데이터 기반으로 동작. 실제 DB/S3 연동은 루코드가 구현.

워크플로우:
  MAP_QUERYING_LOT → MAP_SHOWING_FAIL_CONCENTRATION → MAP_SELECTING_WAFERS
  → MAP_ANALYZING_WAFER_MAP → MAP_SHOWING_RESULTS
  → MAP_AWAITING_PREV_PROCESS_MERGE → MAP_ANALYZING_PREV_PROCESS
  → MAP_SHOWING_PREV_PROCESS_RESULTS
"""

from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import schema


# =============================================================================
# 1차: LOT 조회 + fail 집계
# =============================================================================

def query_lot_fail_summary(params: dict) -> pd.DataFrame:
    """LOT 조건으로 run/wafer별 fail 집계 조회.

    Returns:
        DataFrame columns: lot_no, run_id, wafer_id, count, total_count, fail_rate
    """
    # TODO: 실제 SQL 쿼리는 루코드가 구현
    # 현재는 mock 데이터 반환
    rng = np.random.default_rng(42)
    lot_no = params.get("lot_no", "LOT_001")
    rows = []
    for run_id in range(1, 4):
        for wafer_id in range(1, 6):
            total = rng.integers(800, 1200)
            fail_count = rng.integers(0, 30)
            rows.append({
                schema.MAP_LOT_NO_COLUMN: lot_no,
                schema.MAP_RUN_COLUMN: f"RUN_{run_id:02d}",
                schema.MAP_WAFER_COLUMN: f"W{wafer_id:02d}",
                schema.MAP_FAIL_COUNT_COLUMN: int(fail_count),
                schema.MAP_TOTAL_COUNT_COLUMN: int(total),
                "fail_rate": round(fail_count / total, 4),
            })
    return pd.DataFrame(rows)


def get_concentration_candidates(summary_df: pd.DataFrame) -> pd.DataFrame:
    """fail 몰림 후보 추출 (count >= threshold)."""
    threshold = schema.MAP_FAIL_CONCENTRATION_THRESHOLD
    candidates = summary_df[
        summary_df[schema.MAP_FAIL_COUNT_COLUMN] >= threshold
    ].copy()
    candidates = candidates.sort_values(
        schema.MAP_FAIL_COUNT_COLUMN, ascending=False
    ).reset_index(drop=True)
    return candidates


def build_fail_summary_message(summary_df: pd.DataFrame, candidates: pd.DataFrame) -> str:
    """fail 집계 + 몰림 후보 메시지 생성."""
    total_wafers = len(summary_df)
    total_fails = summary_df[schema.MAP_FAIL_COUNT_COLUMN].sum()

    lines = [
        "### Fail 집계 결과\n",
        f"- 전체 wafer 수: {total_wafers}",
        f"- 총 fail die 수: {total_fails}",
        f"- 몰림 기준: fail count >= {schema.MAP_FAIL_CONCENTRATION_THRESHOLD}\n",
    ]

    if candidates.empty:
        lines.append("**몰림 후보 없음** — 기준 이상의 fail이 발견되지 않았습니다.\n")
        lines.append("분석할 wafer를 직접 지정해주세요.")
    else:
        lines.append(f"**몰림 후보 {len(candidates)}개:**\n")
        lines.append("| # | run_id | wafer_id | fail count | total | fail rate |")
        lines.append("|---|--------|----------|-----------|-------|-----------|")
        for i, (_, row) in enumerate(candidates.iterrows(), 1):
            lines.append(
                f"| {i} | {row[schema.MAP_RUN_COLUMN]} | {row[schema.MAP_WAFER_COLUMN]} "
                f"| {row[schema.MAP_FAIL_COUNT_COLUMN]} | {row[schema.MAP_TOTAL_COUNT_COLUMN]} "
                f"| {row.get('fail_rate', 0):.4f} |"
            )
        lines.append("\n**분석할 wafer를 선택해주세요.**")
        lines.append("번호 입력 (예: `1, 2, 3`) 또는 `전체`")
        lines.append("직접 지정: `RUN_01/W03, RUN_02/W05`")

    return "\n".join(lines)


# =============================================================================
# wafer 선택 파싱
# =============================================================================

def parse_wafer_selection(
    text: str,
    candidates: pd.DataFrame,
    summary_df: pd.DataFrame,
) -> list[dict]:
    """사용자 입력에서 wafer 선택 파싱.

    Returns:
        [{"run_id": str, "wafer_id": str}, ...]
    """
    import re
    text_lower = text.lower().strip()

    # "전체" / "all"
    if any(kw in text_lower for kw in ["전체", "전부", "모두", "all"]):
        result = []
        for _, row in summary_df.iterrows():
            result.append({
                "run_id": row[schema.MAP_RUN_COLUMN],
                "wafer_id": row[schema.MAP_WAFER_COLUMN],
            })
        return result

    # 번호 선택: "1, 2, 3"
    numbers = re.findall(r"\d+", text)
    if numbers and not re.search(r"[A-Za-z]", text.replace("RUN", "").replace("W", "")):
        result = []
        for num_str in numbers:
            idx = int(num_str) - 1
            if 0 <= idx < len(candidates):
                row = candidates.iloc[idx]
                result.append({
                    "run_id": row[schema.MAP_RUN_COLUMN],
                    "wafer_id": row[schema.MAP_WAFER_COLUMN],
                })
        if result:
            return result

    # 직접 지정: "RUN_01/W03, RUN_02/W05"
    direct = re.findall(r"(RUN_\d+)\s*/\s*(W\d+)", text, re.IGNORECASE)
    if direct:
        return [{"run_id": r.upper(), "wafer_id": w.upper()} for r, w in direct]

    # fallback: 후보 전체
    if not candidates.empty:
        result = []
        for _, row in candidates.iterrows():
            result.append({
                "run_id": row[schema.MAP_RUN_COLUMN],
                "wafer_id": row[schema.MAP_WAFER_COLUMN],
            })
        return result

    return []


# =============================================================================
# 2차: wafer map 상세 조회 + 분석
# =============================================================================

def query_wafer_map_detail(
    params: dict,
    selected_wafers: list[dict],
) -> pd.DataFrame:
    """선택된 wafer의 die 좌표 상세 데이터 조회.

    Returns:
        DataFrame columns: lot_no, run_id, wafer_id, die_x, die_y, bin_cd, category, fail_flag
    """
    # TODO: 실제 SQL 쿼리는 루코드가 구현
    # mock: layout mask 기반으로 die 데이터 생성
    lot_cd = params.get("lot_cd", "")
    lot_no = params.get("lot_no", "LOT_001")
    oper = params.get("oper", "")
    cat = params.get("cat")
    layout = schema.MAP_LAYOUT_BY_LOT_CD.get(lot_cd, schema.MAP_DEFAULT_LAYOUT)

    rng = np.random.default_rng(123)
    rows = []

    for wafer_info in selected_wafers:
        run_id = wafer_info["run_id"]
        wafer_id = wafer_info["wafer_id"]

        for row_idx, row_data in enumerate(layout):
            for col_idx, has_die in enumerate(row_data):
                if not has_die:
                    continue

                if schema.MAP_LAYOUT_OFFSET_MODE == "subtract":
                    die_x = col_idx - schema.MAP_LAYOUT_X_OFFSET
                    die_y = row_idx - schema.MAP_LAYOUT_Y_OFFSET
                else:
                    die_x = col_idx + schema.MAP_LAYOUT_X_OFFSET
                    die_y = row_idx + schema.MAP_LAYOUT_Y_OFFSET

                # mock fail 판정
                is_fail = rng.random() < 0.15
                bin_cd = rng.integers(1, 10) if is_fail else 1
                category = "fail" if is_fail else "pass"

                # fail 판정: cat이 있으면 category 기준, 없으면 FAILBIN 기준
                if cat:
                    fail_flag = 1 if category == cat else 0
                else:
                    fail_bins = schema.FAILBIN.get(oper, [])
                    fail_flag = 1 if int(bin_cd) in fail_bins else (1 if is_fail else 0)

                rows.append({
                    schema.MAP_LOT_NO_COLUMN: lot_no,
                    schema.MAP_RUN_COLUMN: run_id,
                    schema.MAP_WAFER_COLUMN: wafer_id,
                    schema.MAP_X_COLUMN: die_x,
                    schema.MAP_Y_COLUMN: die_y,
                    schema.MAP_BIN_COLUMN: int(bin_cd),
                    schema.MAP_CATEGORY_COLUMN: category,
                    schema.MAP_FAIL_COLUMN: fail_flag,
                })

    return pd.DataFrame(rows)


def classify_pattern(map_df: pd.DataFrame) -> str:
    """wafer map의 fail 패턴 판정 (edge/center/random).

    MVP: 좌표 중심으로부터의 거리 기반 단순 판정.
    """
    fail_df = map_df[map_df[schema.MAP_FAIL_COLUMN] == 1]
    if fail_df.empty:
        return "no_fail"

    x = fail_df[schema.MAP_X_COLUMN].values.astype(float)
    y = fail_df[schema.MAP_Y_COLUMN].values.astype(float)

    all_x = map_df[schema.MAP_X_COLUMN].values.astype(float)
    all_y = map_df[schema.MAP_Y_COLUMN].values.astype(float)

    cx, cy = all_x.mean(), all_y.mean()
    max_dist = np.sqrt((all_x - cx) ** 2 + (all_y - cy) ** 2).max()
    if max_dist == 0:
        return "random"

    fail_dists = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max_dist

    # edge: 평균 정규화 거리 > 0.65
    # center: 평균 정규화 거리 < 0.35
    mean_dist = fail_dists.mean()
    if mean_dist > 0.65:
        return "edge"
    elif mean_dist < 0.35:
        return "center"
    else:
        return "random"


def build_aggregate_fail_map(map_df: pd.DataFrame) -> pd.DataFrame:
    """여러 wafer의 fail을 좌표별로 누적.

    Returns:
        DataFrame columns: die_x, die_y, fail_count, wafer_count
    """
    agg = map_df.groupby(
        [schema.MAP_X_COLUMN, schema.MAP_Y_COLUMN]
    ).agg(
        fail_count=(schema.MAP_FAIL_COLUMN, "sum"),
        wafer_count=(schema.MAP_WAFER_COLUMN, "nunique"),
    ).reset_index()
    return agg


# =============================================================================
# wafer map 시각화
# =============================================================================

def plot_wafer_map(
    map_df: pd.DataFrame,
    wafer_id: str,
    run_id: str,
    layout: list[list[int]] | None = None,
) -> bytes:
    """단일 wafer scatter plot (PNG bytes).

    색상: missing/미측정=회색, normal=연두색, fail=빨간색
    """
    if layout is None:
        layout = schema.MAP_DEFAULT_LAYOUT

    wafer_data = map_df[
        (map_df[schema.MAP_WAFER_COLUMN] == wafer_id) &
        (map_df[schema.MAP_RUN_COLUMN] == run_id)
    ]

    fig, ax = plt.subplots(figsize=(3, 3))

    # layout mask에서 die 존재 좌표 계산
    layout_coords = set()
    for row_idx, row_data in enumerate(layout):
        for col_idx, has_die in enumerate(row_data):
            if has_die:
                if schema.MAP_LAYOUT_OFFSET_MODE == "subtract":
                    lx = col_idx - schema.MAP_LAYOUT_X_OFFSET
                    ly = row_idx - schema.MAP_LAYOUT_Y_OFFSET
                else:
                    lx = col_idx + schema.MAP_LAYOUT_X_OFFSET
                    ly = row_idx + schema.MAP_LAYOUT_Y_OFFSET
                layout_coords.add((lx, ly))

    # 측정된 die 좌표
    measured_coords = set()
    if not wafer_data.empty:
        for _, row in wafer_data.iterrows():
            measured_coords.add((row[schema.MAP_X_COLUMN], row[schema.MAP_Y_COLUMN]))

    # missing die (layout에 있지만 측정 없음)
    missing_coords = layout_coords - measured_coords
    if missing_coords:
        mx, my = zip(*missing_coords)
        ax.scatter(mx, my, c="lightgray", s=15, marker="s", label="missing", zorder=1)

    if not wafer_data.empty:
        # normal die
        normal = wafer_data[wafer_data[schema.MAP_FAIL_COLUMN] == 0]
        if not normal.empty:
            ax.scatter(
                normal[schema.MAP_X_COLUMN], normal[schema.MAP_Y_COLUMN],
                c="limegreen", s=15, marker="s", label="normal", zorder=2,
            )

        # fail die
        fail = wafer_data[wafer_data[schema.MAP_FAIL_COLUMN] == 1]
        if not fail.empty:
            ax.scatter(
                fail[schema.MAP_X_COLUMN], fail[schema.MAP_Y_COLUMN],
                c="red", s=15, marker="s", label="fail", zorder=3,
            )

    ax.set_xlabel(schema.MAP_X_COLUMN)
    ax.set_ylabel(schema.MAP_Y_COLUMN)
    ax.set_title(f"{run_id} / {wafer_id}")
    ax.set_aspect("equal")
    ax.legend(loc="upper right", fontsize=6)
    ax.invert_yaxis()
    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def plot_aggregate_map(agg_df: pd.DataFrame) -> bytes:
    """aggregate fail count heatmap (PNG bytes)."""
    fig, ax = plt.subplots(figsize=(3, 3))

    sc = ax.scatter(
        agg_df[schema.MAP_X_COLUMN],
        agg_df[schema.MAP_Y_COLUMN],
        c=agg_df["fail_count"],
        cmap="YlOrRd",
        s=20,
        marker="s",
    )
    fig.colorbar(sc, ax=ax, label="fail count")
    ax.set_xlabel(schema.MAP_X_COLUMN)
    ax.set_ylabel(schema.MAP_Y_COLUMN)
    ax.set_title("Aggregate Fail Map")
    ax.set_aspect("equal")
    ax.invert_yaxis()
    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def plot_feature_map(
    merged_df: pd.DataFrame,
    feature: str,
    layout: list[list[int]] | None = None,
) -> bytes:
    """단일 피처의 die별 값을 wafer map으로 시각화 (PNG bytes).

    색상: feature 값의 연속 heatmap (coolwarm).
    fail die는 검은 테두리로 표시.
    """
    if layout is None:
        layout = schema.MAP_DEFAULT_LAYOUT

    if feature not in merged_df.columns:
        # 피처 없으면 빈 plot
        fig, ax = plt.subplots(figsize=(3, 3))
        ax.text(0.5, 0.5, f"'{feature}' not found", ha="center", va="center", fontsize=10)
        ax.set_title(f"Feature Map: {feature}")
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    # wafer별로 aggregate (평균값)
    agg = merged_df.groupby(
        [schema.MAP_X_COLUMN, schema.MAP_Y_COLUMN], as_index=False
    ).agg({feature: "mean", schema.MAP_FAIL_COLUMN: "max"})

    fig, ax = plt.subplots(figsize=(3.5, 3))

    # layout mask — missing die 표시
    layout_coords = set()
    for row_idx, row_data in enumerate(layout):
        for col_idx, has_die in enumerate(row_data):
            if has_die:
                if schema.MAP_LAYOUT_OFFSET_MODE == "subtract":
                    lx = col_idx - schema.MAP_LAYOUT_X_OFFSET
                    ly = row_idx - schema.MAP_LAYOUT_Y_OFFSET
                else:
                    lx = col_idx + schema.MAP_LAYOUT_X_OFFSET
                    ly = row_idx + schema.MAP_LAYOUT_Y_OFFSET
                layout_coords.add((lx, ly))

    measured_coords = set(zip(agg[schema.MAP_X_COLUMN], agg[schema.MAP_Y_COLUMN]))
    missing = layout_coords - measured_coords
    if missing:
        mx, my = zip(*missing)
        ax.scatter(mx, my, c="lightgray", s=15, marker="s", label="missing", zorder=1)

    # feature heatmap
    sc = ax.scatter(
        agg[schema.MAP_X_COLUMN],
        agg[schema.MAP_Y_COLUMN],
        c=agg[feature],
        cmap="coolwarm",
        s=20,
        marker="s",
        zorder=2,
    )
    fig.colorbar(sc, ax=ax, label=feature)

    # fail die 테두리 표시
    fail_dies = agg[agg[schema.MAP_FAIL_COLUMN] == 1]
    if not fail_dies.empty:
        ax.scatter(
            fail_dies[schema.MAP_X_COLUMN],
            fail_dies[schema.MAP_Y_COLUMN],
            facecolors="none",
            edgecolors="black",
            s=30,
            linewidths=1.5,
            marker="s",
            label="fail",
            zorder=3,
        )

    ax.set_xlabel(schema.MAP_X_COLUMN)
    ax.set_ylabel(schema.MAP_Y_COLUMN)
    ax.set_title(f"Feature Map: {feature}")
    ax.set_aspect("equal")
    ax.legend(loc="upper right", fontsize=6)
    ax.invert_yaxis()
    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def build_map_results_message(
    map_df: pd.DataFrame,
    selected_wafers: list[dict],
    pattern: str,
) -> str:
    """MAP 분석 결과 메시지 생성."""
    total_dies = len(map_df)
    fail_dies = map_df[schema.MAP_FAIL_COLUMN].sum()
    fail_rate = fail_dies / total_dies if total_dies > 0 else 0

    pattern_labels = {
        "edge": "Edge 집중",
        "center": "Center 집중",
        "random": "Random (특정 패턴 없음)",
        "no_fail": "Fail 없음",
    }

    lines = [
        "### Wafer Map 분석 완료\n",
        f"- 분석 wafer: **{len(selected_wafers)}**장",
        f"- Fail: **{int(fail_dies)}** / {total_dies} die ({fail_rate:.2%})",
        f"- 패턴: **{pattern_labels.get(pattern, pattern)}**\n",
        "위의 Wafer Map에서 공간 분포를 확인하세요.\n",
        "---\n",
        "**다음 단계를 선택해주세요** (아래 안내 참고).",
    ]

    return "\n".join(lines)


# =============================================================================
# 전공정 merge + feature similarity
# =============================================================================

def parse_prev_process_selection(text: str) -> list[dict] | None:
    """전공정 선택 파싱. None이면 skip."""
    import re
    text_lower = text.lower().strip()

    # skip
    if any(kw in text_lower for kw in ["아니오", "아니", "skip", "no", "종료"]):
        return None

    options = schema.PREV_PROCESS_OPTIONS

    # "전체" / "전부" / "all" / "예"
    if any(kw in text_lower for kw in ["전체", "전부", "모두", "all", "예", "yes", "y"]):
        return list(options)

    # 번호
    numbers = re.findall(r"\d+", text)
    if numbers:
        selected = []
        for n in numbers:
            idx = int(n) - 1
            if 0 <= idx < len(options):
                selected.append(options[idx])
        if selected:
            return selected

    # id/label 매칭
    selected = []
    for opt in options:
        if opt["id"] in text_lower or opt["label"] in text:
            selected.append(opt)
    return selected if selected else None


def merge_prev_process_data(
    map_df: pd.DataFrame,
    selected_options: list[dict],
) -> pd.DataFrame:
    """전공정 데이터를 merge.

    Returns:
        merge된 DataFrame (map 데이터 + 전공정 feature 컬럼)
    """
    # TODO: 실제 DB 조회 + merge는 루코드가 구현
    # mock: 전공정 feature를 랜덤으로 생성하여 merge
    rng = np.random.default_rng(456)
    result = map_df.copy()

    for opt in selected_options:
        for col in opt["columns"]:
            result[col] = rng.normal(0, 1, len(result))

    return result


def compute_feature_similarity(
    merged_df: pd.DataFrame,
    feature_columns: list[str],
) -> pd.DataFrame:
    """fail map과 feature map의 유사도 계산.

    Returns:
        DataFrame columns: feature, pearson_score, cosine_score, total_score
        total_score 내림차순 정렬
    """
    # TODO: 실제 유사도 계산은 루코드가 구현
    # mock 구현
    fail_map = merged_df[schema.MAP_FAIL_COLUMN].values.astype(float)

    rows = []
    for feat in feature_columns:
        if feat not in merged_df.columns:
            continue

        feat_vals = merged_df[feat].values.astype(float)

        # z-score 정규화
        if schema.MAP_FEATURE_SIMILARITY_NORMALIZATION == "zscore":
            std = feat_vals.std()
            if std > 0:
                feat_vals = (feat_vals - feat_vals.mean()) / std

        # valid mask
        valid = ~(np.isnan(fail_map) | np.isnan(feat_vals))
        if valid.sum() < 3:
            continue

        f = fail_map[valid]
        v = feat_vals[valid]

        # Pearson correlation
        if f.std() > 0 and v.std() > 0:
            pearson = float(np.corrcoef(f, v)[0, 1])
        else:
            pearson = 0.0

        # Cosine similarity
        dot = np.dot(f, v)
        norm_f = np.linalg.norm(f)
        norm_v = np.linalg.norm(v)
        cosine = float(dot / (norm_f * norm_v)) if (norm_f > 0 and norm_v > 0) else 0.0

        total = (abs(pearson) + cosine) / 2

        rows.append({
            "feature": feat,
            "pearson_score": round(pearson, 4),
            "cosine_score": round(cosine, 4),
            "total_score": round(total, 4),
        })

    result = pd.DataFrame(rows)
    result = result.sort_values("total_score", ascending=False).reset_index(drop=True)
    return result.head(schema.MAP_FEATURE_SIMILARITY_TOP_N)


def build_prev_process_results_message(similarity_df: pd.DataFrame) -> str:
    """전공정 feature similarity 결과 메시지."""
    lines = [
        "### 전공정 Feature Similarity 분석 완료\n",
        f"상위 {len(similarity_df)}개 feature의 유사도를 계산했습니다.\n",
    ]

    # 상위 3개만 채팅에 요약
    top_n = min(3, len(similarity_df))
    if top_n > 0:
        lines.append(f"**Top {top_n} Feature:**")
        for i, (_, row) in enumerate(similarity_df.head(top_n).iterrows(), 1):
            lines.append(f"  {i}. **{row['feature']}** (score: {row['total_score']:.4f})")
        lines.append("")

    lines.append("아래 테이블에서 feature를 클릭하면 **Feature Map**을 확인할 수 있습니다.")
    return "\n".join(lines)
